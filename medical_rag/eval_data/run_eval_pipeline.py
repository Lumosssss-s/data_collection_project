"""检索评估管道（医疗 · C1 BE-39 / C3 E-01）
================================================
按主方案 §9 计算检索指标（Recall@5/@10、MRR、NDCG@10 等），默认跑主链路
「混合检索 + 精排」，可用 ``--strategy`` 切换单策略。

> 医疗化说明：法规版的「Excel 人工标注工作流（L/M 列）」与硬编码法规 GT 已移除——
> 医疗 gold 由数据清单 C 组（``eval_sets``）直接交付，无需 Excel 标注。

评测集口径（C3 §4.1，实体字段医疗化）：
  [{id, query, cancer_type, scenario, relevant: [{rec_id, doc_id, breadcrumb, relevance}]}]

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/run_eval_pipeline.py --dataset eval_data/eval_dataset.json

输出（C3 §6.3 #3）：<out-dir>/<时间戳>/{eval_pipeline_summary.json, eval_pipeline_per_query.csv}
"""
import argparse
import csv
import datetime
import importlib.util
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PKG_ROOT)
sys.path.insert(0, BASE_DIR)

# 复用 run_enhanced_eval 的 EvalQuery / 策略 / 指标实现，避免重复维护
_spec = importlib.util.spec_from_file_location("ree", os.path.join(BASE_DIR, "run_enhanced_eval.py"))
ree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ree)

from services.retriever_service import RetrieverService  # noqa: E402


def load_queries(dataset_path: str):
    with open(dataset_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    queries = [
        ree.EvalQuery(id=it["id"], query=it["query"],
                      cancer_type=it.get("cancer_type"),
                      relevant=it.get("relevant", []))
        for it in items
    ]
    return [q for q in queries if q.relevant]


def main():
    parser = argparse.ArgumentParser(description="医疗检索评估管道")
    parser.add_argument("--dataset", default=os.path.join(BASE_DIR, "eval_dataset.json"),
                        help="评测集 JSON 路径")
    parser.add_argument("--out-dir", default=os.path.join(BASE_DIR, "results"),
                        help="结果输出根目录（实际写入 <out-dir>/<时间戳>/）")
    parser.add_argument("--strategy", default="hybrid+reranker",
                        choices=list(ree.STRATEGIES.keys()),
                        help="评估策略（默认主链路 hybrid+reranker）")
    parser.add_argument("--top-k", type=int, default=20, help="候选 Top-K")
    parser.add_argument("--unit", default="rec", choices=["rec", "doc"],
                        help="评测单元粒度：rec=推荐条目级；doc=文档级（gold 仅有 doc_id 时用）")
    args = parser.parse_args()
    ree.UNIT_MODE = args.unit

    print("=" * 60)
    print(f"  检索评估管道（医疗 · 策略={ree.STRATEGIES[args.strategy]['name']}）")
    print("=" * 60)

    if not os.path.exists(args.dataset):
        print(f"\n  [ERROR] 未找到评测集: {args.dataset}")
        return

    active = load_queries(args.dataset)
    print(f"\n  评测集: {len(active)} 条（有 gold）")
    if not active:
        print("  [ERROR] 无有效评测条目")
        return

    retriever = RetrieverService()
    run = ree.STRATEGIES[args.strategy]["run"]

    results = []
    for q in active:
        gold_set = q.get_relevant_units()
        retrieved_ids = run(retriever, q, args.top_k)
        # 单元去重（文档级下同一 doc 的多个片段只计首次命中的位次）
        retrieved_ids = list(dict.fromkeys(retrieved_ids))
        metrics = ree.compute_metrics(retrieved_ids, gold_set, q)
        metrics.update({"query_id": q.id, "query_text": q.query[:100],
                        "cancer_type": q.cancer_type or "未指定"})
        results.append(metrics)

    summary = ree.compute_summary(results)
    print(f"\n  === 汇总（n={summary['total_queries']}） ===")
    print(f"  {'MRR':>8} {'R@5':>8} {'R@10':>8} {'R@20':>8} {'P@5':>8} {'NDCG@10':>10}")
    print(f"  {'-'*56}")
    print(f"  {summary['MRR']:>8.4f} {summary['Recall@5']:>8.4f} {summary['Recall@10']:>8.4f} "
          f"{summary['Recall@20']:>8.4f} {summary['Precision@5']:>8.4f} {summary['NDCG@10']:>10.4f}")

    # 落盘（C3 §6.3 #3）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)
    summary["_snapshot"] = {"run_at": stamp, "dataset": os.path.abspath(args.dataset),
                            "strategy": args.strategy, "top_k": args.top_k}
    with open(os.path.join(out_dir, "eval_pipeline_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "eval_pipeline_per_query.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "query_id", "query_text", "cancer_type",
                    "relevant_count", "retrieved_count", "MRR",
                    "recall@5", "recall@10", "recall@20", "ndcg@10"])
        for r in results:
            w.writerow([args.strategy, r["query_id"], r["query_text"], r["cancer_type"],
                        r["relevant_count"], r["retrieved_count"], r["mrr"],
                        r["recall"][5], r["recall"][10], r["recall"][20], r["ndcg"][10]])

    print(f"\n  结果目录: {out_dir}")
    print("\n" + "=" * 60)
    print("  完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
