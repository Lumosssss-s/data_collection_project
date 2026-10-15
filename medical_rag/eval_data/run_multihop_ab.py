"""多跳 B（查询分解）受影响查询的 A/B 快速回归（医疗 · C1 BE-44 / C3 E-06）。

目的：验证开启查询分解后，会走分解路径的那部分查询是否发生指标退化。

做法：
  - 仅跑 hybrid+reranker 策略（分解只作用于该路径）；
  - 关闭 LLM 兜底 → 规则切分确定、可复现，且不引入网络波动；
  - 关闭检索缓存 → 两次跑互不污染；
  - 先筛出「关 LLM 兜底时 decompose_query 非空」的查询，作为受影响集合；
  - 同一 retriever 分别以 multihop_decompose_enabled=False/True 各跑一遍，
    对比 MRR / R@10 / NDCG@10 等，并逐条给出变好/变差/持平。

医疗多跳链示例：分期 → 分子 → 用药。

用法（在 backend 容器内，工作目录 /app）：
    python eval_data/run_multihop_ab.py --dataset eval_data/eval_dataset.json
"""
import argparse
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
_spec = importlib.util.spec_from_file_location(
    "ree", os.path.join(BASE_DIR, "run_enhanced_eval.py")
)
ree = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ree)

from core.config import settings  # noqa: E402
from services.retriever_service import RetrieverService  # noqa: E402
from services.query_decomposer import decompose_query  # noqa: E402


def load_queries(dataset_path: str):
    with open(dataset_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    queries = [
        ree.EvalQuery(
            id=it["id"],
            query=it["query"],
            cancer_type=it.get("cancer_type"),
            relevant=it.get("relevant", []),
        )
        for it in items
    ]
    return [q for q in queries if q.relevant]


def run_once(queries, enabled, retriever, top_k):
    settings.multihop_decompose_enabled = enabled
    rows = []
    for q in queries:
        gold = q.get_relevant_units()
        ids = ree.strategy_hybrid_reranker(retriever, q, top_k)
        m = ree.compute_metrics(ids, gold, q)
        rows.append({
            "query_id": q.id,
            "query_text": q.query,
            "mrr": m["mrr"],
            "r10": m["recall"][10],
            "r20": m["recall"][20],
            "ndcg10": m["ndcg"][10],
            "ndcg20": m["ndcg"][20],
        })
    return rows


def fmt(label, rows):
    n = max(len(rows), 1)

    def avg(key):
        return sum(r[key] for r in rows) / n

    top1 = sum(1.0 for r in rows if r["mrr"] > 0) / n
    print(f"  {label:<6} MRR={avg('mrr'):.4f}  Top1={top1:.4f}  "
          f"R@10={avg('r10'):.4f}  R@20={avg('r20'):.4f}  "
          f"NDCG@10={avg('ndcg10'):.4f}  NDCG@20={avg('ndcg20'):.4f}")


def main():
    parser = argparse.ArgumentParser(description="多跳查询分解 A/B 回归（医疗）")
    parser.add_argument("--dataset", default=os.path.join(BASE_DIR, "eval_dataset.json"),
                        help="评测集 JSON 路径")
    parser.add_argument("--out-dir", default=os.path.join(BASE_DIR, "results"),
                        help="结果输出根目录（实际写入 <out-dir>/<时间戳>/）")
    parser.add_argument("--top-k", type=int, default=20, help="候选 Top-K")
    args = parser.parse_args()

    settings.search_cache_enabled = False
    settings.multihop_decompose_llm_enabled = False  # 规则确定、避免网络波动
    settings.reranker_enabled = True

    if not os.path.exists(args.dataset):
        print(f"[ERROR] 未找到评测集: {args.dataset}")
        return

    all_q = load_queries(args.dataset)
    affected = [q for q in all_q if decompose_query(q.query)]
    print("=" * 78)
    print(f"  多跳 B 查询分解 A/B 回归：总查询 {len(all_q)}，受影响（会触发分解）{len(affected)}")
    print("=" * 78)

    retriever = RetrieverService()

    # 让路多癌种/对比路由后，部分查询会被守卫拦下：统计修复后真正仍走分解的条数，
    # 用于解释 ON 侧为何不再对「比较类」查询生效。
    settings.multihop_decompose_enabled = True
    still = [q for q in affected if retriever._decompose_query(q.query)]
    print(f"\n  让路路由守卫后，仍会走分解的查询：{len(still)} / {len(affected)}")

    print("\n  >>> 跑 OFF（multihop_decompose_enabled=False）")
    off = run_once(affected, False, retriever, args.top_k)
    print("  >>> 跑 ON （multihop_decompose_enabled=True）")
    on = run_once(affected, True, retriever, args.top_k)

    print("\n  === 汇总（受影响子集） ===")
    fmt("OFF", off)
    fmt("ON", on)

    # 逐条对比
    on_map = {r["query_id"]: r for r in on}
    better, worse, same = [], [], []
    for r in off:
        o = on_map[r["query_id"]]
        d = round(o["mrr"] - r["mrr"], 4)
        rec = (r["query_text"], r["mrr"], o["mrr"], d)
        if d > 1e-9:
            better.append(rec)
        elif d < -1e-9:
            worse.append(rec)
        else:
            same.append(rec)

    print(f"\n  === 逐条 MRR 对比 ===  变好 {len(better)} / 变差 {len(worse)} / 持平 {len(same)}")
    if worse:
        print("\n  [变差清单]")
        for t, a, b, d in sorted(worse, key=lambda x: x[3]):
            print(f"    {d:+.4f}  {a:.4f} -> {b:.4f}  {t}")
    if better:
        print("\n  [变好清单]")
        for t, a, b, d in sorted(better, key=lambda x: -x[3]):
            print(f"    {d:+.4f}  {a:.4f} -> {b:.4f}  {t}")

    # 落盘（C3 §6.3 #3）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "_snapshot": {"run_at": stamp, "dataset": os.path.abspath(args.dataset),
                      "top_k": args.top_k, "affected": len(affected), "still_decomposed": len(still)},
        "off": off,
        "on": on,
        "diff": {"better": len(better), "worse": len(worse), "same": len(same)},
    }
    with open(os.path.join(out_dir, "multihop_ab.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  结果目录: {out_dir}")

    print("\n" + "=" * 78)
    print("  完成")
    print("=" * 78)


if __name__ == "__main__":
    main()
