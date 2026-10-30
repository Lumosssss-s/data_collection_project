"""增强评估脚本（医疗 · C1 BE-43 / C3 E-05）
================================================
四种检索策略（BM25 / 向量 / 混合 RRF / 混合+Re-ranker）逐策略指标 + 按癌种/变体细分；
框架沿用，实体字段医疗化。指标口径见主方案 §9。

评测集口径（C3 §4.1，实体字段医疗化）：
  [{id, query, cancer_type, relevant: [{rec_id, doc_id, breadcrumb, relevance}]}]

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/run_enhanced_eval.py --dataset eval_data/eval_dataset.json

输出（C3 §6.3 #3）：
  <out-dir>/<时间戳>/enhanced_{per_query.csv, viz_data.json}
"""
import argparse
import csv
import datetime
import json
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List


# 评测单元粒度：rec=推荐条目级（默认）；doc=文档级（gold 仅有 doc_id 时使用）
UNIT_MODE = "rec"


def _unit_key(d: Dict) -> str:
    """统一「检索单元」标识：优先 rec_id / item_id，回落 doc_id / breadcrumb。"""
    if UNIT_MODE == "doc":
        return str(d.get("doc_id") or "")
    return str(d.get("rec_id") or d.get("item_id") or d.get("doc_id")
               or d.get("breadcrumb") or "")


# ============================================================
# EvalQuery（医疗）
# ============================================================
class EvalQuery:
    def __init__(self, id="", query="", cancer_type=None, relevant=None):
        self.id = id
        self.query = query
        self.cancer_type = cancer_type
        self.relevant = relevant or []

    def get_relevant_units(self) -> set:
        """返回检索单元标识集合"""
        return {_unit_key(r) for r in self.relevant}

    def get_gain(self, unit_key):
        for r in self.relevant:
            if _unit_key(r) == unit_key:
                return (2 ** r.get("relevance", 1)) - 1
        return 0


# ============================================================
# 策略函数（独立实现）
# ============================================================
# 主证据库类型：文献层只作问答兜底，评测检索链路按主库口径对齐
PRIMARY_DATA_TYPES = ["doc", "rec", "drug"]


def _filters_of(query_q):
    """评测过滤条件：癌种（可选）+ 主库 data_type（排除文献层，保持与基线同口径）。"""
    f = {"data_type": PRIMARY_DATA_TYPES}
    ct = getattr(query_q, "cancer_type", None)
    if ct:
        f["cancer_type"] = ct
    return f


def strategy_bm25(retriever, query_q, top_k=20):
    """仅 BM25 全文检索"""
    results = retriever.bm25_search(query=query_q.query, top_k=top_k, filters=_filters_of(query_q))
    return [_unit_key(r) for r in results]


def strategy_vector(retriever, query_q, top_k=20):
    """纯向量检索"""
    from core.config import settings
    settings.reranker_enabled = False
    results = retriever.search(query=query_q.query, top_k=top_k, filters=_filters_of(query_q))
    return [_unit_key(r) for r in results]


def strategy_hybrid(retriever, query_q, top_k=20):
    """混合检索(RRF)"""
    from core.config import settings
    settings.reranker_enabled = False
    results = retriever.hybrid_search(query=query_q.query, top_k=top_k, filters=_filters_of(query_q))
    return [_unit_key(r) for r in results]


def strategy_hybrid_reranker(retriever, query_q, top_k=20):
    """混合+Re-ranker"""
    from core.config import settings
    settings.reranker_enabled = True
    results = retriever.hybrid_search(query=query_q.query, top_k=top_k, filters=_filters_of(query_q))
    return [_unit_key(r) for r in results]


STRATEGIES = {
    "bm25": {"name": "仅BM25检索", "run": strategy_bm25},
    "vector": {"name": "纯向量检索", "run": strategy_vector},
    "hybrid": {"name": "混合检索(RRF)", "run": strategy_hybrid},
    "hybrid+reranker": {"name": "混合+Re-ranker", "run": strategy_hybrid_reranker},
}


# ============================================================
# 指标计算
# ============================================================
def compute_metrics(retrieved_ids, gold_set, eval_query):
    """计算单条 query 的完整指标"""
    mrr = 0.0
    for i, uid in enumerate(retrieved_ids):
        if uid in gold_set:
            mrr = 1.0 / (i + 1)
            break

    top1_acc = 1.0 if mrr > 0 else 0.0

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
        # 分母为理想 DCG；gold 数少于 k 时仍按同一分母归一（未命中位置增益为 0）
        dcg[k] = dcg_k / ideal_dcg if ideal_dcg > 0 else 0.0

    return {
        "mrr": round(mrr, 4),
        "top1_acc": round(top1_acc, 4),
        "r_precision": round(r_prec, 4),
        "recall": {k: round(v, 4) for k, v in recall.items()},
        "precision": {k: round(v, 4) for k, v in precision.items()},
        "ndcg": {k: round(v, 4) for k, v in dcg.items()},
        "relevant_count": rel_count,
        "retrieved_count": len(retrieved_ids),
    }


def compute_summary(results: List[Dict]) -> Dict:
    """汇总多条 query 的平均指标"""
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


def print_summary_block(label: str, results: List[Dict]):
    if not results:
        print(f"\n  [{label}] 无数据")
        return
    s = compute_summary(results)
    print(f"\n  --- {label} (n={s['total_queries']}) ---")
    print(f"  {'MRR':>8} {'Top1':>8} {'R-Prec':>8} {'R@5':>8} {'R@10':>8} {'R@20':>8} {'P@5':>8} {'NDCG@10':>10}")
    print(f"  {'-'*76}")
    print(f"  {s['MRR']:>8.4f} {s['Top1_Accuracy']:>8.4f} {s['R-Precision']:>8.4f} "
          f"{s['Recall@5']:>8.4f} {s['Recall@10']:>8.4f} {s['Recall@20']:>8.4f} "
          f"{s['Precision@5']:>8.4f} {s['NDCG@10']:>10.4f}")


def print_comparison_table(all_summaries: Dict):
    print(f"\n  {'策略':<22} {'MRR':>8} {'R@5':>8} {'R@10':>8} {'R@20':>8} {'P@5':>8} {'NDCG@10':>10} {'NDCG@20':>10}")
    print(f"  {'-'*84}")
    for sk, s in all_summaries.items():
        name = STRATEGIES[sk]["name"]
        print(f"  {name:<22} {s['MRR']:>8.4f} {s['Recall@5']:>8.4f} {s['Recall@10']:>8.4f} "
              f"{s['Recall@20']:>8.4f} {s['Precision@5']:>8.4f} {s['NDCG@10']:>10.4f} {s['NDCG@20']:>10.4f}")


def export_per_query_csv(strategy_names, strategy_results, output_path):
    rows = []
    for sk, name in strategy_names.items():
        for r in strategy_results[sk]:
            rows.append({
                "strategy": name,
                "query_id": r["query_id"],
                "query_text": r["query_text"],
                "cancer_type": r["cancer_type"],
                "relevant_count": r["relevant_count"],
                "retrieved_count": r["retrieved_count"],
                "MRR": r["mrr"],
                "R@5": r["recall"][5],
                "R@10": r["recall"][10],
                "R@20": r["recall"][20],
                "P@5": r["precision"][5],
            })
    if not rows:
        return
    fieldnames = ["strategy", "query_id", "query_text", "cancer_type",
                  "relevant_count", "retrieved_count", "MRR", "R@5", "R@10", "R@20", "P@5"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  CSV: {output_path} ({len(rows)} 行)")


def export_viz_json(all_summaries, ct_summaries, output_path):
    data = {
        "overall": all_summaries,
        "by_cancer_type": {c: s for c, s in ct_summaries.items()},
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Viz: {output_path}")


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="医疗增强检索评估")
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

    from services.retriever_service import RetrieverService

    print("=" * 60)
    print("  增强检索评估（医疗）")
    print("=" * 60)

    if not os.path.exists(args.dataset):
        print(f"\n  [ERROR] 未找到: {args.dataset}")
        return

    with open(args.dataset, "r", encoding="utf-8") as f:
        items = json.load(f)
    queries = [EvalQuery(id=item["id"], query=item["query"],
                         cancer_type=item.get("cancer_type"),
                         relevant=item.get("relevant", [])) for item in items]

    active = [q for q in queries if q.relevant]
    print(f"\n  评测集: {len(queries)}（有 gold: {len(active)}）")
    if not active:
        return

    retriever = RetrieverService()
    strategy_keys = ["bm25", "vector", "hybrid", "hybrid+reranker"]

    all_strategy_results = {}
    all_summaries = {}
    strategy_names = {k: STRATEGIES[k]["name"] for k in strategy_keys}

    for sk in strategy_keys:
        print(f"\n  >>> {strategy_names[sk]}")
        results = []
        for q in active:
            gold_set = q.get_relevant_units()
            retrieved_ids = STRATEGIES[sk]["run"](retriever, q, top_k)
            metrics = compute_metrics(retrieved_ids, gold_set, q)
            results.append({
                **metrics,
                "query_id": q.id,
                "query_text": q.query[:100],
                "cancer_type": q.cancer_type or "未指定",
                "strategy_key": sk,
            })
        all_strategy_results[sk] = results
        all_summaries[sk] = compute_summary(results)
        print(f"    完成: MRR={all_summaries[sk]['MRR']:.4f}")

    print("\n  === 总体对比 ===")
    print_comparison_table(all_summaries)

    print("\n  === 额外指标 ===")
    print(f"  {'策略':<22} {'Top1-Acc':>10} {'R-Precision':>12}")
    print(f"  {'-'*46}")
    for sk in strategy_keys:
        s = all_summaries[sk]
        print(f"  {strategy_names[sk]:<22} {s['Top1_Accuracy']:>10.4f} {s['R-Precision']:>12.4f}")

    print("\n  === 按癌种细分 (混合检索) ===")
    ct_summaries = {}
    ct_groups = defaultdict(list)
    for r in all_strategy_results["hybrid"]:
        ct_groups[r["cancer_type"]].append(r)
    for ct in sorted(ct_groups.keys()):
        ct_summaries[ct] = compute_summary(ct_groups[ct])
        print_summary_block(ct, ct_groups[ct])

    # 落盘（C3 §6.3 #3）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)

    all_summaries["_snapshot"] = {"run_at": stamp, "dataset": os.path.abspath(args.dataset),
                                  "top_k": top_k}
    export_per_query_csv(strategy_names, all_strategy_results,
                         os.path.join(out_dir, "enhanced_per_query.csv"))
    export_viz_json(all_summaries, ct_summaries,
                    os.path.join(out_dir, "enhanced_viz_data.json"))
    print(f"\n  结果目录: {out_dir}")

    print("\n" + "=" * 60)
    print("  完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
