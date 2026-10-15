"""精排增益评估（医疗 · C1 BE-41 / C3 E-03）
================================================
先跑混合检索生成候选，再用 bge-reranker 重排，对比精排增益；指标口径沿用
主方案 §9（Recall@5/10、MRR、NDCG@10 等）。

评测集口径（C3 §4.1，实体字段医疗化）：
  [{id, query, cancer_type, relevant: [{rec_id, doc_id, breadcrumb, relevance}]}]

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/run_reranker_eval.py --dataset eval_data/eval_dataset.json

输出（C3 §6.3 #3）：<out-dir>/<时间戳>/{reranker_summary.json, reranker_per_query.csv}
"""
import argparse
import csv
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
    for k, label in [("mrr", "MRR"), ("top1_acc", "Top1_Accuracy"), ("r_precision", "R-Precision")]:
        out[label] = round(sum(r[k] for r in results) / n, 4)
    for k in [1, 3, 5, 10, 20]:
        out[f"Recall@{k}"] = round(sum(r["recall"][k] for r in results) / n, 4)
    for k in [5, 10, 20]:
        out[f"Precision@{k}"] = round(sum(r["precision"][k] for r in results) / n, 4)
        out[f"NDCG@{k}"] = round(sum(r["ndcg"][k] for r in results) / n, 4)
    return out


def load_reranker_direct():
    """加载 reranker（页面文件已扩大，可直接 from_pretrained）"""
    import torch
    from core.config import settings
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    model_path = settings.reranker_model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  加载 reranker: {model_path} -> {device}")

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    ).to(device)
    model.eval()

    print(f"  模型加载完成: {sum(p.numel() for p in model.parameters())/1e6:.0f}M 参数")
    return tokenizer, model, device


def batch_rerank(query, candidates, tokenizer, model, device, top_k=20):
    """使用已加载的模型重排"""
    import torch

    pairs, valid = [], []
    for doc in candidates:
        content = doc.get("content", "")
        if not content:
            continue
        pairs.append([query, content[:2000]])
        valid.append(doc)

    if not pairs:
        return candidates[:top_k]

    all_scores = []
    batch_size = 8
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        inputs = tokenizer(batch, padding=True, truncation=True,
                           max_length=2048, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
            scores = outputs.logits.squeeze(-1).cpu().tolist()
            all_scores.extend(scores if isinstance(scores, list) else [scores])

    for doc, score in zip(valid, all_scores):
        doc["rerank_score"] = round(score, 4)
    valid.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return valid[:top_k]


def main():
    parser = argparse.ArgumentParser(description="医疗精排增益评估（Re-ranker）")
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

    print("=" * 60)
    print("  Re-ranker 策略评估（医疗）")
    print("=" * 60)

    # 1. 加载评测集
    with open(args.dataset, "r", encoding="utf-8") as f:
        items = json.load(f)
    queries = [EvalQuery(id=item["id"], query=item["query"],
                         cancer_type=item.get("cancer_type"),
                         relevant=item.get("relevant", [])) for item in items]
    active = [q for q in queries if q.relevant]
    print(f"\n  评测集: {len(queries)}（有 gold: {len(active)}）")

    # Phase 1: 生成混合检索候选（保留完整文档，含 content，免去二次回查）
    print("\n  Phase 1: 生成混合检索候选...")
    from services.retriever_service import RetrieverService
    from core.config import settings

    settings.reranker_enabled = False
    retriever = RetrieverService()
    candidates_map = {}
    for q in active:
        filters = {"cancer_type": q.cancer_type} if q.cancer_type else None
        candidates_map[q.id] = retriever.hybrid_search(query=q.query, top_k=top_k, filters=filters)

    print("  释放 Retriever...")
    del retriever
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print(f"  显存: {torch.cuda.memory_allocated()/1024**3:.1f} GB")

    # Phase 2: 加载 Reranker
    print("\n  Phase 2: 加载 Re-ranker...")
    tokenizer, model, device = load_reranker_direct()

    # Phase 3: 重排 + 评分
    print("\n  Phase 3: 重排 + 评分...")
    all_results = []
    for idx, q in enumerate(active):
        candidates = candidates_map[q.id]
        gold_set = q.get_relevant_units()
        if not candidates:
            all_results.append(compute_metrics([], gold_set, q))
            continue

        reranked = batch_rerank(q.query, candidates, tokenizer, model, device, top_k)
        retrieved_ids = [_unit_key(r) for r in reranked]

        metrics = compute_metrics(retrieved_ids, gold_set, q)
        metrics.update({"query_id": q.id, "query_text": q.query[:100],
                        "cancer_type": q.cancer_type or "未指定"})
        all_results.append(metrics)

        if (idx + 1) % 40 == 0:
            print(f"    [{idx+1}/{len(active)}] MRR so far: "
                  f"{sum(r['mrr'] for r in all_results)/len(all_results):.4f}")

    # 汇总
    summary = compute_summary(all_results)
    print(f"\n  === 混合+Re-ranker 结果 (n={summary.get('total_queries', 0)}) ===")
    if summary:
        print(f"  {'MRR':>8} {'Top1':>8} {'R-Prec':>8} {'R@5':>8} {'R@10':>8} {'R@20':>8} {'P@5':>8} {'NDCG@10':>10}")
        print(f"  {'-'*76}")
        print(f"  {summary['MRR']:>8.4f} {summary['Top1_Accuracy']:>8.4f} {summary['R-Precision']:>8.4f} "
              f"{summary['Recall@5']:>8.4f} {summary['Recall@10']:>8.4f} {summary['Recall@20']:>8.4f} "
              f"{summary['Precision@5']:>8.4f} {summary['NDCG@10']:>10.4f}")

    # 落盘（C3 §6.3 #3）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)

    summary["_snapshot"] = {"run_at": stamp, "dataset": os.path.abspath(args.dataset),
                            "top_k": top_k, "strategy": "hybrid+reranker"}
    with open(os.path.join(out_dir, "reranker_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    csv_path = os.path.join(out_dir, "reranker_per_query.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "query_id", "query_text", "cancer_type",
                    "relevant_count", "retrieved_count", "mrr",
                    "recall@5", "recall@10", "recall@20", "precision@5"])
        for r in all_results:
            w.writerow(["混合+Re-ranker", r["query_id"], r["query_text"], r["cancer_type"],
                        r["relevant_count"], r["retrieved_count"], r["mrr"],
                        r["recall"][5], r["recall"][10], r["recall"][20], r["precision"][5]])

    print(f"\n  结果目录: {out_dir}")
    print("\n  完成！")


if __name__ == "__main__":
    main()
