"""问答评估脚本（医疗 · C1 BE-40 / C3 E-02）
================================================
对「检索 + 生成」全链路按医疗口径评估，指标（主方案 §9）：

  1. 检索命中@K    —— 检索结果是否命中 gold 推荐条目（原 HasAns@5）
  2. 引用正确率    —— 生成答案所引用的来源中，确属 gold 条目的比例
  3. 忠实性 / 无幻觉率 —— LLM-as-judge 判定答案是否忠实于参考资料（≥4 分视为无幻觉）
  4. 拒答正确率    —— 无 gold 的查询应拒答、有 gold 的查询不应误拒

评测集口径（C3 §4.1，实体字段医疗化）：
  - 查询集：{"queries": [{query_id, query, cancer_type, scenario, topic, is_core, ...}]}
  - gold 集：[{id, relevant: [{rec_id, doc_id, breadcrumb, relevance}]}]

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/run_qa_eval.py \
      --queries eval_data/eval_queries.json \
      --gold    eval_data/eval_dataset.json \
      --out-dir eval_data/results

输出（C3 §6.3 #3）：
  <out-dir>/<时间戳>/qa_results.json  - 每条查询详细结果
  <out-dir>/<时间戳>/qa_summary.json  - 汇总指标 + 运行快照（评测集/索引/脚本版本）
"""
import argparse
import datetime
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 只评估中文自然语言变体，兼顾效率与代表性
USE_VARIANT = "B_nl_zh"

# 拒答识别关键词（无 gold 的查询若命中其一，视为正确拒答）
_REFUSAL_MARKERS = ("无法回答", "无法确定", "资料不足", "没有找到", "未找到", "暂无相关",
                    "未提供", "不足以回答", "建议咨询", "建议就医", "请咨询医生")

# 答案中的来源引用标记：【来源X】
_CITATION_RE = re.compile(r"【来源\s*(\d+)\s*】")


def _unit_key(d: Dict) -> str:
    """统一「检索单元」标识：优先 rec_id / item_id，回落 doc_id / breadcrumb。"""
    return str(d.get("rec_id") or d.get("item_id") or d.get("doc_id")
               or d.get("breadcrumb") or "")


def _looks_like_refusal(answer: str) -> bool:
    """答案是否表现为「拒答 / 资料不足」。"""
    if not answer or len(answer.strip()) < 10:
        return True
    return any(m in answer for m in _REFUSAL_MARKERS)


# ============================================================
# 1. 加载数据
# ============================================================
def load_queries(path: str) -> List[Dict]:
    """加载评测查询集，返回 [{query_id, query, cancer_type, scenario, ...}]"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    queries = []
    for item in data.get("queries", []):
        qid = item.get("query_id")
        if not qid:
            continue
        query_text = item.get(USE_VARIANT) or item.get("query", "")
        if not query_text:
            continue
        queries.append({
            "query_id": qid,
            "query": query_text,
            "cancer_type": item.get("cancer_type", ""),
            "scenario": item.get("scenario", ""),
            "topic": item.get("topic", ""),
            "core_concept": item.get("core_concept", ""),
            "is_core": item.get("is_core", False),
        })
    print(f"  加载 {len(queries)} 条查询（变体: {USE_VARIANT}）")
    return queries


def load_gold(path: str) -> Dict[str, List[Dict]]:
    """加载 gold 集，返回 {query_id: [{rec_id, doc_id, breadcrumb, relevance}]}"""
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    gold: Dict[str, List[Dict]] = defaultdict(list)
    for item in items:
        qid = item.get("id", "")
        if not qid:
            continue
        base_id = qid.split("_")[0] if "_" in qid else qid
        gold[base_id].extend(item.get("relevant", []))
    return dict(gold)


# ============================================================
# 2. 检索 + 生成 + 引用校验
# ============================================================
def run_qa_pipeline(query: str, cancer_type: str, gold_units: List[Dict],
                    retriever, qa_service, settings, top_k: int = 5) -> Dict:
    """执行单条问答评估（检索 → 生成 → 引用正确率）。"""
    result = {
        "query": query,
        "retrieval_hit": False,
        "gold_matched": [],
        "retrieved_units": [],
        "generated_answer": "",
        "citation_accuracy": None,
        "faithfulness_score": 0,
        "is_refusal": False,
        "error": None,
    }

    # ---- Step 1: 检索（medical filters） ----
    try:
        filters = {"cancer_type": cancer_type} if cancer_type else None
        retrieved = retriever.hybrid_search(query=query, top_k=top_k, filters=filters)
        retrieved_units = [(_unit_key(r), r.get("breadcrumb", ""), r.get("content", ""))
                           for r in retrieved]
        result["retrieved_units"] = [{"unit": u, "breadcrumb": bc}
                                     for u, bc, _ in retrieved_units]
    except Exception as e:
        result["error"] = f"检索失败: {e}"
        return result

    # ---- Step 2: 检索命中@K ----
    gold_set = {_unit_key(g) for g in gold_units}
    matched = [u for u, _, _ in retrieved_units if u and u in gold_set]
    result["retrieval_hit"] = bool(matched)
    result["gold_matched"] = matched

    # ---- Step 3: 生成答案（可直接用检索结果构建 prompt，避免重复加载 embedding 模型） ----
    try:
        ref_text = "\n\n".join([
            f"【来源{i+1}】{r.get('cancer_type_zh') or r.get('cancer_type', '')}"
            f"《{r.get('title', '')}》{r.get('breadcrumb', '')}\n{r.get('content', '')[:1500]}"
            for i, r in enumerate(retrieved)
        ])
        prompt = f"""你是肿瘤科临床决策支持助手。请严格基于以下循证参考资料回答用户问题。

【参考资料】
{ref_text}

【用户问题】
{query}

请用中文回答，要求：
1. 直接回答问题，给出明确结论
2. 引用相关推荐条目（标注【来源X】）
3. 如资料不足，明确说明「资料不足，无法回答」，不要编造
4. 涉及用药时提示以药品说明书与临床医嘱为准
5. 回答控制在 500 字以内"""

        answer = qa_service._call_llm_with_model(prompt, model=settings.llm_qa_model)
        result["generated_answer"] = answer
        result["is_refusal"] = _looks_like_refusal(answer)
    except Exception as e:
        result["error"] = f"生成失败: {e}"
        return result

    # ---- Step 4: 引用正确率（解析【来源X】→ 命中 gold 的比例） ----
    cited = [int(x) for x in _CITATION_RE.findall(answer)]
    if cited:
        correct = 0
        for idx in cited:
            if 1 <= idx <= len(retrieved_units):
                u = retrieved_units[idx - 1][0]
                if u in gold_set:
                    correct += 1
        result["citation_accuracy"] = round(correct / len(cited), 4)

    # ---- Step 5: LLM-as-judge 忠实度 ----
    try:
        result["faithfulness_score"] = judge_faithfulness(query, answer, retrieved_units, qa_service)
    except Exception as e:
        result["error"] = (result.get("error") or "") + f" | 评估失败: {e}"

    return result


# ============================================================
# 3. LLM-as-Judge
# ============================================================
def judge_faithfulness(query: str, answer: str, retrieved_units: List[tuple],
                       qa_service) -> int:
    """LLM-as-judge 评估忠实度（1-5 分）。"""
    ref_text = "\n\n".join([f"【来源{i+1}】\n{c[:500]}"
                            for i, (_, _, c) in enumerate(retrieved_units)])

    prompt = f"""请评估以下生成答案对循证参考资料的忠实程度（是否出现幻觉）。

【用户问题】
{query}

【参考资料】
{ref_text}

【生成答案】
{answer}

请根据以下标准给出 1-5 分的评价：
1 = 完全编造，与参考资料无关
2 = 大部分内容无法从参考资料推导
3 = 部分忠实，部分编造
4 = 大部分忠实，少量细节无法确认
5 = 完全忠实，所有内容都能从参考资料找到依据

请仅输出一个数字。"""

    try:
        response = qa_service._call_llm(prompt)
        for ch in response.strip():
            if ch.isdigit():
                return max(1, min(5, int(ch)))
    except Exception:
        pass
    return 0


# ============================================================
# 4. 汇总计算
# ============================================================
def compute_summary(results: List[Dict]) -> Dict:
    n = len(results)
    if n == 0:
        return {}

    hit_count = sum(1 for r in results if r["retrieval_hit"])
    faith_scores = [r["faithfulness_score"] for r in results if r["faithfulness_score"] > 0]
    cite_scores = [r["citation_accuracy"] for r in results if r["citation_accuracy"] is not None]

    # 拒答正确率：无 gold 应拒答、有 gold 不应误拒
    refusal_total = 0
    refusal_correct = 0
    for r in results:
        should_refuse = not r.get("_has_gold")
        refused = r["is_refusal"]
        refusal_total += 1
        if (should_refuse and refused) or (not should_refuse and not refused):
            refusal_correct += 1

    return {
        "total_queries": n,
        "retrieval_hit_at_k": round(hit_count / n, 4),
        "retrieval_hit_count": hit_count,
        "citation_accuracy": round(sum(cite_scores) / len(cite_scores), 4) if cite_scores else None,
        "citation_samples": len(cite_scores),
        "avg_faithfulness": round(sum(faith_scores) / len(faith_scores), 2) if faith_scores else 0,
        "no_hallucination_rate": (round(sum(1 for s in faith_scores if s >= 4) / len(faith_scores), 4)
                                  if faith_scores else None),
        "refusal_accuracy": round(refusal_correct / refusal_total, 4) if refusal_total else None,
        "faithfulness_distribution": {
            "1-2分": sum(1 for s in faith_scores if s <= 2),
            "3分": sum(1 for s in faith_scores if s == 3),
            "4-5分": sum(1 for s in faith_scores if s >= 4),
        },
        "error_count": sum(1 for r in results if r.get("error")),
    }


def print_summary(summary: Dict):
    print(f"\n  {'='*60}")
    print(f"  问答评估结果（医疗口径）")
    print(f"  {'='*60}")
    print(f"  总查询数:        {summary['total_queries']}")
    print(f"  错误数:          {summary['error_count']}")
    print(f"  检索命中@K:      {summary['retrieval_hit_at_k']:.2%} "
          f"({summary['retrieval_hit_count']}/{summary['total_queries']})")
    ca = summary['citation_accuracy']
    print(f"  引用正确率:      {ca:.2%}" if ca is not None else "  引用正确率:      N/A")
    print(f"  忠实性均分:      {summary['avg_faithfulness']:.2f} / 5.0")
    nh = summary['no_hallucination_rate']
    print(f"  无幻觉率(≥4分):  {nh:.2%}" if nh is not None else "  无幻觉率(≥4分):  N/A")
    ra = summary['refusal_accuracy']
    print(f"  拒答正确率:      {ra:.2%}" if ra is not None else "  拒答正确率:      N/A")
    print(f"  {'-'*60}")
    print(f"  忠实度分布:")
    for k, v in summary["faithfulness_distribution"].items():
        pct = v / max(summary['total_queries'], 1) * 100
        print(f"    {k}: {v} ({pct:.1f}%)")


# ============================================================
# 5. 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="医疗问答评估（RAG QA Evaluation）")
    parser.add_argument("--queries", default=os.path.join(BASE_DIR, "eval_queries.json"),
                        help="评测查询集 JSON 路径")
    parser.add_argument("--gold", default=os.path.join(BASE_DIR, "eval_dataset.json"),
                        help="gold 集 JSON 路径")
    parser.add_argument("--out-dir", default=os.path.join(BASE_DIR, "results"),
                        help="结果输出根目录（实际写入 <out-dir>/<时间戳>/）")
    parser.add_argument("--top-k", type=int, default=5, help="问答场景检索 Top-K")
    args = parser.parse_args()

    sys.path.insert(0, BASE_DIR)
    # 脚本位于 eval_data/ 子目录，需把 medical_rag 包根加入 sys.path 才能 import core/services
    sys.path.insert(0, os.path.dirname(BASE_DIR))

    print("=" * 60)
    print("  问答评估（医疗 RAG QA Evaluation）")
    print(f"  变体: {USE_VARIANT}  Top-K: {args.top_k}")
    print(f"  查询集: {args.queries}")
    print(f"  gold 集: {args.gold}")
    print("=" * 60)

    queries = load_queries(args.queries)
    gold_map = load_gold(args.gold)
    if not queries:
        print("  [ERROR] 无查询数据")
        return
    print(f"  Gold 数据: {len(gold_map)} 条 base query")

    from services.retriever_service import RetrieverService
    from services.qa_service import QAService
    from core.config import settings

    # 禁用 reranker（混合检索 RRF 融合，不加载重排序模型）
    settings.reranker_enabled = False

    retriever = RetrieverService()
    qa_service = QAService()

    all_results = []
    for i, q in enumerate(queries):
        qid = q["query_id"]
        gold = gold_map.get(qid, [])
        print(f"  [{i+1}/{len(queries)}] {qid}: {q['query'][:60]}...", end=" ", flush=True)

        result = run_qa_pipeline(
            query=q["query"],
            cancer_type=q["cancer_type"],
            gold_units=gold,
            retriever=retriever,
            qa_service=qa_service,
            settings=settings,
            top_k=args.top_k,
        )
        result["query_id"] = qid
        result["cancer_type"] = q["cancer_type"]
        result["topic"] = q["topic"]
        result["is_core"] = q["is_core"]
        result["_has_gold"] = bool(gold)

        if result.get("error"):
            print(f"❌ {result['error'][:50]}")
        else:
            print(f"✓ 命中={result['retrieval_hit']} 引用={result['citation_accuracy']} "
                  f"忠实={result['faithfulness_score']} 拒答={result['is_refusal']}")
        all_results.append(result)

    summary = compute_summary(all_results)
    print_summary(summary)

    # 落盘（C3 §6.3 #3：<out-dir>/<时间戳>/）
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, stamp)
    os.makedirs(out_dir, exist_ok=True)
    summary["_snapshot"] = {
        "run_at": stamp,
        "queries_path": os.path.abspath(args.queries),
        "gold_path": os.path.abspath(args.gold),
        "variant": USE_VARIANT,
        "top_k": _TOP_K,
    }
    with open(os.path.join(out_dir, "qa_results.json"), "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "qa_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n  结果目录: {out_dir}")

    # 按癌种细分
    print(f"\n  {'='*60}")
    print(f"  按癌种细分")
    print(f"  {'='*60}")
    ct_groups = defaultdict(list)
    for r in all_results:
        ct_groups[r["cancer_type"] or "未指定"].append(r)
    for ct in sorted(ct_groups.keys()):
        grp = ct_groups[ct]
        hit = sum(1 for r in grp if r["retrieval_hit"])
        fs = [r["faithfulness_score"] for r in grp if r["faithfulness_score"] > 0]
        print(f"  {ct:<10} n={len(grp):>2}  命中={hit}/{len(grp)}  "
              f"忠实={sum(fs)/max(len(fs),1):.1f}")

    print("\n" + "=" * 60)
    print("  完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
