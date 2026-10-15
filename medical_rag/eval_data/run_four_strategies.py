"""四策略对比评测（医疗 · C1 BE-42 / C3 E-04）
================================================
对比：仅 BM25 / 仅向量 / 混合(BM25+向量+RRF) / 混合+重排序；框架沿用，评测集替换
为医疗口径。指标口径见主方案 §9。

评测集口径（C3 §4.1，实体字段医疗化）：
  [{id, query, cancer_type, relevant: [{rec_id, doc_id, breadcrumb, relevance}]}]

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/run_four_strategies.py --dataset eval_data/eval_dataset.json

输出（C3 §6.3 #3）：<out-dir>/<时间戳>/four_strategies_summary.json
"""
import argparse
import datetime
import gc
import json
import math
import os
import sys
from typing import Dict, List


def _unit_key(d: Dict) -> str:
    """统一「检索单元」标识：优先 rec_id / item_id，回落 doc_id / breadcrumb。"""
    return str(d.get("rec_id") or d.get("item_id") or d.get("doc_id")
               or d.get("breadcrumb") or "")


class EvalQuery:
    def __init__(self, id="", query="", cancer_type=None, relevant=None):
        self.id = id
        self.query = query
        self.cancer_type = cancer_type
        self.relevant = relevant or []

    def get_relevant_units(self):
        return {_unit_key(r) for r in self.relevant}

    def get_gain(self, unit_key):
        for r in self.relevant:
            if _unit_key(r) == unit_key:
                return (2 ** r.get("relevance", 1)) - 1
        return 0


def compute_metrics(retrieved_ids, gold_set, eval_query):
    mrr = 0.0
    for i, uid in enumerate(retrieved_ids):
        if uid in gold_set:
            mrr = 1.0 / (i + 1)
            break
    rel_count = len(gold_set)
    recall, precision = {}, {}
    for k in [1, 3, 5, 10, 20]:
        topk = retrieved_ids[:k]
        hits = sum(1 for uid in topk if uid in gold_set)
        recall[k] = hits / max(rel_count, 1)
        precision[k] = hits / max(k, 1)
    R = min(rel_count, 20)
    r_hits = sum(1 for uid in retrieved_ids[:R] if uid in gold_set)
    r_prec = r_hits / max(R, 1)
    gains = sorted([eval_query.get_gain(uid) for uid in gold_set], reverse=True)
    ideal_dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:20]))
    dcg = {}
    for k in [5, 10, 20]:
        dcg_k = sum(eval_query.get_gain(uid) / math.log2(i + 2)
                    for i, uid in enumerate(retrieved_ids[:k]))
        dcg[k] = dcg_k / max(ideal_dcg, 1e-10) if k <= len(gains) else 0.0
    return {"mrr": round(mrr, 4), "top1_acc": 1.0 if mrr > 0 else 0.0,
            "r_precision": round(r_prec, 4),
            "recall": {k: round(v, 4) for k, v in recall.items()},
            "precision": {k: round(v, 4) for k, v in precision.items()},
            "ndcg": {k: round(v, 4) for k, v in dcg.items()},
            "relevant_count": rel_count, "retrieved_count": len(retrieved_ids)}


def compute_summary(results):
    if not results:
        return {}
    n = len(results)
    out = {"total_queries": n}
    out["MRR"] = round(sum(r["mrr"] for r in results) / n, 4)
    out["Top1_Accuracy"] = round(sum(r["top1_acc"] for r in results) / n, 4)
    out["R-Precision"] = round(sum(r["r_precision"] for r in results) / n, 4)
    for k in [1, 3, 5, 10, 20]:
        out[f"Recall@{k}"] = round(sum(r["recall"][k] for r in results) / n, 4)
    for k in [5, 10, 20]:
        out[f"Precision@{k}"] = round(sum(r["precision"][k] for r in results) / n, 4)
        out[f"NDCG@{k}"] = round(sum(r["ndcg"][k] for r in results) / n, 4)
    return out


def print_comparison_table(all_summaries):
    print(f"\n  {'策略':<26} {'MRR':>8} {'Top1':>8} {'R-Prec':>8} {'R@5':>8} {'R@10':>8} {'R@20':>8} {'P@5':>8} {'NDCG@20':>10}")
    print(f"  {'-'*94}")
    for sk, s in all_summaries.items():
        print(f"  {sk:<26} {s['MRR']:>8.4f} {s['Top1_Accuracy']:>8.4f} {s['R-Precision']:>8.4f} "
              f"{s['Recall@5']:>8.4f} {s['Recall@10']:>8.4f} {s['Recall@20']:>8.4f} "
              f"{s['Precision@5']:>8.4f} {s['NDCG@20']:>10.4f}")


def main():
    parser = argparse.ArgumentParser(description="医疗四策略对比评测")
    parser.add_argument("--dataset",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "eval_dataset.json"),
                        help="评测集 JSON 路径")
    parser.add_argument("--out-dir",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"),
                        help="结果输出根目录（实际写入 <out-dir>/<时间戳>/）")
    parser.add_argument("--top-k", type=int, default=20, help="候选 Top-K")
    args = parser.parse_args()
    top_k = args.top_k

    base_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base_dir)
    sys.path.insert(0, os.path.dirname(base_dir))

    import torch
    from services.retriever_service import RetrieverService
    from core.config import settings

    print("=" * 70)
    print("  四策略对比评测（医疗）：BM25 / 向量 / 混合(RRF) / 混合+重排序")
    print("=" * 70)

    # 加载评测集
    with open(args.dataset, "r", encoding="utf-8") as f:
        items = json.load(f)
    queries = [EvalQuery(id=item["id"], query=item["query"],
                         cancer_type=item.get("cancer_type"),
                         relevant=item.get("relevant", [])) for item in items]
    active = [q for q in queries if q.relevant]
    print(f"\n  评测集: {len(queries)}（有 gold: {len(active)}）")

    # Phase 1: BM25 + 向量 + 混合（只需 Retriever）
    print("\n  Phase 1: 运行 BM25 / 向量 / 混合...")
    settings.reranker_enabled = False
    retriever = RetrieverService()

    strategy_results = {
        "仅BM25": [],
        "仅向量检索": [],
        "混合检索(BM25+向量+RRF)": [],
    }

    for q in active:
        filters = {"cancer_type": q.cancer_type} if q.cancer_type else None
        gold_set = q.get_relevant_units()

        try:
            bm25_res = retriever.bm25_search(query=q.query, top_k=top_k, filters=filters)
            bm25_ids = [_unit_key(r) for r in bm25_res]
        except Exception:
            bm25_ids = []
        m = compute_metrics(bm25_ids, gold_set, q)
        m.update({"query_id": q.id, "cancer_type": q.cancer_type or "未指定"})
        strategy_results["仅BM25"].append(m)

        vec_res = retriever.search(query=q.query, top_k=top_k, filters=filters)
        vec_ids = [_unit_key(r) for r in vec_res]
        m = compute_metrics(vec_ids, gold_set, q)
        m.update({"query_id": q.id, "cancer_type": q.cancer_type or "未指定"})
        strategy_results["仅向量检索"].append(m)

        hybrid_res = retriever.hybrid_search(query=q.query, top_k=top_k, filters=filters)
        hybrid_ids = [_unit_key(r) for r in hybrid_res]
        m = compute_metrics(hybrid_ids, gold_set, q)
        m.update({"query_id": q.id, "cancer_type": q.cancer_type or "未指定"})
        strategy_results["混合检索(BM25+向量+RRF)"].append(m)

    print("  释放 Retriever...")
    del retriever
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Phase 2: 混合+重排序（需要 Reranker）
    print("\n  Phase 2: 运行 混合+重排序...")
    settings.reranker_enabled = True
    retriever2 = RetrieverService()

    strategy_results["混合检索+重排序"] = []
    for q in active:
        filters = {"cancer_type": q.cancer_type} if q.cancer_type else None
        gold_set = q.get_relevant_units()
        rr_res = retriever2.hybrid_search(query=q.query, top_k=top_k, filters=filters)
        rr_ids = [_unit_key(r) for r in rr_res]
        m = compute_metrics(rr_ids, gold_set, q)
        m.update({"query_id": q.id, "cancer_type": q.cancer_type or "未指定"})
        strategy_results["混合检索+重排序"].append(m)

    # 汇总
    print("\n" + "=" * 70)
    print("  四策略对比结果")
    print("=" * 70)
    all_summaries = {name: compute_summary(results) for name, results in strategy_results.items()}
    print_comparison_table(all_summaries)

    # 增量对比
    print("\n  === 增量提升 ===")
    base = "仅BM25"
    for name in ["仅向量检索", "混合检索(BM25+向量+RRF)", "混合检索+重排序"]:
        delta_mrr = (all_summaries[name]["MRR"] - all_summaries[base]["MRR"]) / max(all_summaries[base]["MRR"], 1e-10) * 100
        delta_r20 = (all_summaries[name]["Recall@20"] - all_summaries[base]["Recall@20"]) / max(all_summaries[base]["Recall@20"], 1e-10) * 100
        delta_p5 = (all_summaries[name]["Precision@5"] - all_summaries[base]["Precision@5"]) / max(all_summaries[base]["Precision@5"], 1e-10) * 100
        print(f"  {name:<28} vs {base:<12}: MRR={delta_mrr:+.1f}%  R@20={delta_r20:+.1f}%  P@5={delta_p5:+.1f}%")

    # 落盘（C3 §6.3 #3）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "_snapshot": {"run_at": stamp, "dataset": os.path.abspath(args.dataset), "top_k": top_k},
        "overall_four": all_summaries,
        "per_query": strategy_results,
    }
    with open(os.path.join(out_dir, "four_strategies_summary.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  结果目录: {out_dir}")
    print("\n  完成！")


if __name__ == "__main__":
    main()
