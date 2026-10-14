"""跨癌种循证专题分析服务（医疗，BE-09 + BE-27）

针对一个临床专题（如「PD-1 抑制剂在各癌种的适应证与证据」），分别检索两个癌种的
推荐条目，聚合为指南级结构化文本，再由 LLM 生成跨癌种专题分析报告。

三阶段流水线：
    1. 检索：分别对两个癌种执行混合检索，各取 Top-N 推荐条目
    2. 聚合：按 doc_id（指南）分组 → 拼接为指南级结构化文本
    3. LLM：基于两癌种的聚合文本，生成跨癌种专题分析报告

与「双癌种对比（BE-08/19）」的区别：对比为轻量固定维度对照（不调用 LLM），
本专题为 LLM 深度分析报告（可按需追问）。
"""
from collections import defaultdict
from typing import Dict, List

from core.domain_enums import CANCER_TYPE_INFO, get_cancer_type_info
from repositories.elasticsearch import ElasticsearchRepository
from services.qa_service import QAService
import time

_CODE_TO_NAME = {code: name for name, (code, _) in CANCER_TYPE_INFO.items()}


class TopicAnalysisService:
    """跨癌种循证专题分析服务"""

    # 分析维度（固定框架，医疗版）
    ANALYSIS_DIMENSIONS = [
        "适应证与适用人群：该专题涉及的癌种、分期、分子分型或人群范围。",
        "疗效与证据：关键疗效数据（如 ORR、PFS、OS）及证据等级、推荐强度。",
        "用药/治疗方案：具体药物、方案组合、给药与疗程要点。",
        "安全性：主要不良反应、禁忌与需要注意的监测事项。",
        "总体差异总结：用对比表格清晰呈现两个癌种在上述各维度的核心异同点。",
    ]

    def __init__(self):
        self.repo = ElasticsearchRepository()
        self.qa_service = QAService()
        self._retriever = None  # 懒加载，避免导入期加载大模型

    @property
    def retriever(self):
        if self._retriever is None:
            from services.retriever_service import RetrieverService
            self._retriever = RetrieverService()
        return self._retriever

    def _search_by_cancer(
        self,
        query: str,
        cancer_type: str,
        top_n: int = 8,
    ) -> List[Dict]:
        """
        阶段一：对指定癌种执行混合检索，保证返回 top_n 条结果。

        分开检索确保每个癌种都有足够素材，不会被另一个癌种"淹没"。
        """
        results = self.retriever.hybrid_search(query, top_k=top_n, filters={"cancer_type": cancer_type})

        recs = []
        for r in results:
            recs.append({
                "_id": r.get("item_id", ""),
                "content": r.get("content", ""),
                "doc_id": r.get("doc_id", ""),
                "rec_id": r.get("rec_id", ""),
                "title": r.get("title", ""),
                "cancer_type": r.get("cancer_type", cancer_type),
                "breadcrumb": r.get("breadcrumb", ""),
                "scenario": r.get("scenario", ""),
                "evidence_level": r.get("evidence_level", ""),
                "rec_strength": r.get("rec_strength", ""),
                "chunk_index": r.get("chunk_index", 0),
                "similarity": round(float(r.get("score", 0.0)), 4),
            })
        return recs

    def _aggregate_recs_to_guides(self, recs: List[Dict]) -> List[Dict]:
        """
        阶段二：将碎片化的推荐条目聚合为指南级别的结构化文本。

        按 doc_id 分组 → 同指南条目按 chunk_index 排序 → 拼接为指南级上下文。
        """
        guides_map: Dict[str, Dict] = defaultdict(lambda: {
            "recs": [],
            "rec_ids": set(),
            "title": "",
        })

        for rec in recs:
            did = rec["doc_id"] or rec.get("_id", "")
            guides_map[did]["recs"].append(rec)
            if rec.get("rec_id"):
                guides_map[did]["rec_ids"].add(rec["rec_id"])
            if not guides_map[did]["title"]:
                guides_map[did]["title"] = rec["title"] or did

        aggregated = []
        for did, info in guides_map.items():
            sorted_recs = sorted(info["recs"], key=lambda c: c.get("chunk_index", 0))

            parts = [f"## {info['title']}"]
            for ch in sorted_recs:
                breadcrumb = ch.get("breadcrumb", "")
                content = (ch.get("content") or "").strip()
                sim = ch.get("similarity", 0)
                header = f"### {breadcrumb}" if breadcrumb else "### 推荐条目"
                parts.append(f"{header}\n{content}\n*(匹配度: {sim:.2%})*")

            aggregated.append({
                "doc_id": did,
                "title": info["title"],
                "rec_ids": sorted(info["rec_ids"]),
                "rec_count": len(sorted_recs),
                "context_text": "\n\n".join(parts),
                "max_similarity": max(c["similarity"] for c in sorted_recs) if sorted_recs else 0,
            })

        aggregated.sort(key=lambda x: x["max_similarity"], reverse=True)
        return aggregated

    def _build_analysis_prompt(
        self,
        query: str,
        cancer_a_name: str,
        context_a: str,
        cancer_b_name: str,
        context_b: str,
    ) -> str:
        """阶段三：构建跨癌种专题分析 Prompt（医疗）。"""
        dimension_lines = "\n".join(
            "   {}. {}".format(i + 1, dim) for i, dim in enumerate(self.ANALYSIS_DIMENSIONS)
        )

        prompt = (
            "你是一位资深肿瘤科临床决策支持助手，熟悉各癌种的循证诊疗规范。\n"
            "你需要基于提供的推荐条目原文，给出客观、准确、结构化的跨癌种专题分析报告。\n"
            "\n"
            "**重要原则：**\n"
            "- 必须严格基于提供的推荐条目原文进行分析和引用，不得编造\n"
            "- 每个分析维度都要分别对" + cancer_a_name + "和" + cancer_b_name + "进行独立阐述\n"
            "- 引用时请注明指南名称与章节（breadcrumb）\n"
            "- 如某癌种在该专题无相关推荐，明确标注\"未检索到相关推荐\"\n"
            "- 涉及具体用药时，须提示以权威指南与药品说明书为准；不给出个体化处方\n"
            "\n"
            "---\n"
            "\n"
            "**分析专题：** " + query + "\n"
            "\n"
            "**对比癌种：** " + cancer_a_name + " vs " + cancer_b_name + "\n"
            "\n"
            "---\n"
            "\n"
            "## 分析框架（请逐项展开，每项不少于150字）\n"
            "\n" +
            dimension_lines +
            "\n"
            "---\n"
            "\n"
            "### " + cancer_a_name + "相关推荐条目原文\n"
            "\n" +
            context_a +
            "\n"
            "---\n"
            "\n"
            "### " + cancer_b_name + "相关推荐条目原文\n"
            "\n" +
            context_b +
            "\n"
            "---\n"
            "\n"
            "## 输出格式要求\n"
            "\n"
            "请按以下结构输出完整的专题分析报告：\n"
            "\n"
            "# " + query + " —— " + cancer_a_name + "与" + cancer_b_name + "专题分析报告\n"
            "\n"
            "## 一、适应证与适用人群\n"
            "（分别阐述两癌种的适用分期、分子分型与人群...）\n"
            "\n"
            "## 二、疗效与证据\n"
            "（分别阐述关键疗效数据与证据等级、推荐强度...）\n"
            "\n"
            "## 三、用药与治疗方案\n"
            "（分别说明药物、方案组合与疗程要点...）\n"
            "\n"
            "## 四、安全性\n"
            "（分别列举主要不良反应与监测要点...）\n"
            "\n"
            "## 五、总体差异总结表格\n"
            "\n"
            "| 对比维度 | " + cancer_a_name + " | " + cancer_b_name + " |\n"
            "|---------|------|------|\n"
            "| 适应证与人群 | ... | ... |\n"
            "| 疗效与证据 | ... | ... |\n"
            "| 用药方案 | ... | ... |\n"
            "| 安全性 | ... | ... |\n"
            "\n"
            "## 六、临床提示\n"
            "（基于以上分析，给出面向临床实践的提示；注明以权威指南与说明书为准）"
        )

        return prompt

    def analyze(
        self,
        query: str,
        cancer_type_a: str,
        cancer_type_b: str,
        top_n_per_cancer: int = 8,
    ) -> Dict:
        """
        执行完整的跨癌种专题分析流程。

        Args:
            query: 用户输入的专题（如"PD-1 抑制剂的适应证与证据"）
            cancer_type_a / cancer_type_b: 癌种代码或中文名（受控词表）
            top_n_per_cancer: 每个癌种检索的推荐条目数量
        """
        code_a, _ = get_cancer_type_info(cancer_type_a)
        code_b, _ = get_cancer_type_info(cancer_type_b)
        name_a = _CODE_TO_NAME.get(code_a, cancer_type_a)
        name_b = _CODE_TO_NAME.get(code_b, cancer_type_b)

        t_total = time.time()

        # ===== 阶段一：分别对两个癌种检索 =====
        t1 = time.time()
        recs_a = self._search_by_cancer(query, code_a, top_n_per_cancer)
        recs_b = self._search_by_cancer(query, code_b, top_n_per_cancer)
        t_search = time.time() - t1

        # ===== 阶段二：聚合为指南级别结构化文本 =====
        t2 = time.time()
        guides_a = self._aggregate_recs_to_guides(recs_a)
        guides_b = self._aggregate_recs_to_guides(recs_b)

        context_a = "\n\n---\n\n".join(g["context_text"] for g in guides_a)
        context_b = "\n\n---\n\n".join(g["context_text"] for g in guides_b)
        t_aggregate = time.time() - t2

        # ===== 阶段三：LLM 生成专题分析报告 =====
        t3 = time.time()
        prompt = self._build_analysis_prompt(query, name_a, context_a, name_b, context_b)
        analysis_report = self.qa_service._call_llm(prompt)
        t_llm = time.time() - t3

        total_time = time.time() - t_total

        print(
            f"【专题分析计时】总耗时: {total_time:.4f}s | "
            f"检索: {t_search:.4f}s | 聚合: {t_aggregate:.4f}s | LLM: {t_llm:.4f}s"
        )

        return {
            "query": query,
            "cancer_type_a": code_a,
            "cancer_type_b": code_b,
            "cancer_name_a": name_a,
            "cancer_name_b": name_b,
            "retrieval": {
                "recs_a_count": len(recs_a),
                "recs_b_count": len(recs_b),
                "top_n_per_cancer": top_n_per_cancer,
            },
            "aggregated": {
                "guides_a": [
                    {"doc_id": g["doc_id"], "title": g["title"],
                     "rec_ids": g["rec_ids"], "rec_count": g["rec_count"],
                     "max_similarity": g["max_similarity"]}
                    for g in guides_a
                ],
                "guides_b": [
                    {"doc_id": g["doc_id"], "title": g["title"],
                     "rec_ids": g["rec_ids"], "rec_count": g["rec_count"],
                     "max_similarity": g["max_similarity"]}
                    for g in guides_b
                ],
                "guides_a_count": len(guides_a),
                "guides_b_count": len(guides_b),
            },
            "analysis_report": analysis_report,
            "timing": {
                "retrieval": f"{t_search:.4f}s",
                "aggregation": f"{t_aggregate:.4f}s",
                "llm_generation": f"{t_llm:.4f}s",
                "total": f"{total_time:.4f}s",
            },
        }

    def follow_up(self, original_analysis: Dict, follow_up_question: str) -> Dict:
        """
        追问功能：基于已生成的专题分析报告，回答用户的后续问题。
        """
        t_start = time.time()

        analysis_report = original_analysis.get("analysis_report", "")
        name_a = original_analysis.get("cancer_name_a", original_analysis.get("cancer_type_a", ""))
        name_b = original_analysis.get("cancer_name_b", original_analysis.get("cancer_type_b", ""))

        prompt = self._build_follow_up_prompt(follow_up_question, name_a, name_b, analysis_report)
        answer = self.qa_service._call_llm(prompt)
        t_llm = time.time() - t_start

        print(f"【专题分析追问计时】LLM调用: {t_llm:.4f}s")

        return {
            "follow_up_question": follow_up_question,
            "answer": answer,
            "timing": {
                "llm_generation": f"{t_llm:.4f}s",
                "total": f"{t_llm:.4f}s",
            },
        }

    def _build_follow_up_prompt(
        self,
        question: str,
        cancer_a_name: str,
        cancer_b_name: str,
        original_report: str,
    ) -> str:
        """构建追问的 Prompt（医疗）。"""
        return (
            "你是一位资深肿瘤科临床决策支持助手，正在处理用户对已生成专题分析报告的追问。\n"
            "\n"
            "**重要原则：**\n"
            "- 必须基于以下已有的分析报告进行回答\n"
            "- 如追问涉及报告中未涵盖的内容，可适当扩展但需注明\n"
            "- 保持回答简洁，直接针对用户的问题\n"
            "- 引用时请注明指南名称与章节；涉及用药须提示以权威指南与说明书为准\n"
            "\n"
            "---\n"
            "\n"
            "**原始分析报告（" + cancer_a_name + " vs " + cancer_b_name + "）：**\n"
            "\n" +
            original_report +
            "\n"
            "---\n"
            "\n"
            "**用户追问：** " + question + "\n"
            "\n"
            "请基于以上分析报告，对用户的追问给出专业、准确的回答：\n"
        )
