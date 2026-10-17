"""指南结构化速览服务（医疗）。

为 DOC（指南 / 规范 / 共识）生成**结构化速览**（检索页摘要卡片 / 管理端展示），
带指纹缓存。数据来源：优先取该指南下的 REC 推荐条目正文汇总，无 REC 时回落
doc.content（BE-38 生成的指南摘要）。

输出 schema（医疗）：
    basic_info{guide_name, issuer, doc_type, cancer_types, publish_date, version, item_count}
    overview                指南概要
    key_recommendations     核心推荐要点（list）
    evidence_notes          证据特点
    keywords{core, cancers, scenarios}

其中 basic_info 由文档记录/目录权威填充（不走 LLM，避免编造）；其余由 LLM 从
推荐条目内容提炼。
"""
import json
from typing import Dict, List, Optional, Tuple

from utils.llm_client import chat, get_client

from core.config import settings
from repositories.elasticsearch import ElasticsearchRepository
from services.summary_cache import summary_cache
from utils.doc_catalog import DocCatalog


class SummaryService:
    """指南结构化速览服务"""

    def __init__(self):
        self.repo = ElasticsearchRepository()
        self.catalog = DocCatalog()
        # LLM 上下文窗口限制（字符数）
        self.MAX_CONTEXT_LENGTH = 15000
        # 智能压缩后保留的长度
        self.COMPRESSED_LENGTH = 10000

    # ===== 数据来源 =====

    def _get_doc_record(self, doc_id: str) -> Dict:
        """读取 DOC 记录（doc_id = ES _id），不存在返回空 dict。"""
        return self.repo.get(doc_id) or {}

    def _get_doc_recs(self, doc_id: str) -> List[Dict]:
        """读取该指南下的推荐条目（用于汇总速览来源文本）。"""
        try:
            resp = self.repo.client.search(
                index=settings.es_index_name,
                body={
                    "query": {"bool": {"filter": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"data_type": "rec"}},
                    ]}},
                    "size": 500,
                    "_source": ["content", "breadcrumb", "scenario", "evidence_level", "rec_strength"],
                },
            )
            return [h.get("_source", {}) for h in resp.get("hits", {}).get("hits", [])]
        except Exception:
            return []

    def _gather_source(self, doc_id: str) -> Tuple[str, Dict]:
        """汇总速览来源文本与权威元数据。

        优先用该指南下全部 REC 的正文（含章/节定位）；无 REC 时回落 doc.content。
        元数据（指南名 / 机构 / 癌种 / 版本 / 条目数）来自 DOC 记录 + 目录，供 basic_info 直填。
        """
        doc = self._get_doc_record(doc_id)
        recs = self._get_doc_recs(doc_id)

        if recs:
            parts = []
            for r in recs:
                text = (r.get("content") or "").strip()
                if not text:
                    continue
                breadcrumb = r.get("breadcrumb") or ""
                prefix = f"[{breadcrumb}] " if breadcrumb else ""
                parts.append(f"{prefix}{text}")
            source_text = "\n".join(parts)
        else:
            source_text = (doc.get("content") or "").strip()

        cat_record = self.catalog.find_by_doc_id(doc_id) or {}
        meta = {
            "guide_name": doc.get("title") or cat_record.get("title", ""),
            "issuer": doc.get("issuer") or cat_record.get("issuer", ""),
            "doc_type": doc.get("doc_type") or cat_record.get("doc_type", ""),
            "cancer_types": doc.get("cancer_types") or cat_record.get("cancer_types", []),
            "publish_date": doc.get("publish_date") or cat_record.get("publish_date", ""),
            "version": cat_record.get("version", ""),
            "item_count": cat_record.get("item_count", len(recs)),
        }
        return source_text, meta

    # ===== Prompt =====

    def _build_prompt(self, source_text: str, meta: Dict) -> str:
        cancers = "、".join(meta.get("cancer_types") or []) or "未知"
        return f"""你是肿瘤循证知识库的内容编辑。请阅读以下指南的推荐条目内容，生成该指南的结构化速览。
严格只输出 JSON（不要输出其他内容），所有文本用中文：

{{
  "overview": "指南概要（120-200字，说明指南定位、覆盖癌种与主要诊疗环节）",
  "key_recommendations": ["核心推荐要点1（含适用人群/分期/分子分型等前提条件）", "要点2", "...（3-6 条）"],
  "evidence_notes": "证据特点概述（如推荐所依据的证据等级分布、推荐强度倾向）",
  "keywords": {{
    "core": ["核心概念/术语1", "..."],
    "cancers": ["涉及的癌种/亚型", "..."],
    "scenarios": ["涉及的诊疗场景（如筛查/辅助治疗/一线治疗/随访）", "..."]
  }}
}}

要求：
1. 所有内容必须基于下方推荐条目，不得编造；
2. key_recommendations 逐条精炼，保留关键限定条件，不要罗列原文；
3. 若某字段资料不足，返回空数组或"资料不足"。

## 指南信息
- 名称：{meta.get('guide_name', '')}
- 发布机构：{meta.get('issuer', '')}
- 覆盖癌种：{cancers}

## 推荐条目内容：
{source_text}"""

    def _call_llm(self, prompt: str) -> str:
        """调用远程 LLM API（带超时和重试）"""
        return chat(
            prompt,
            model=settings.llm_model,
            temperature=0.3,
            client=get_client(timeout=100.0, max_retries=2),
        )

    # ===== 生成 =====

    def generate_summary(self, doc_id: str) -> Dict:
        """生成指南的结构化速览（basic_info 由文档权威填充，其余由 LLM 提炼）。"""
        source_text, meta = self._gather_source(doc_id)
        if not source_text:
            raise ValueError(f"指南不存在或无可用于生成速览的内容: {doc_id}")

        if len(source_text) > self.MAX_CONTEXT_LENGTH:
            source_text = source_text[: self.COMPRESSED_LENGTH]

        prompt = self._build_prompt(source_text, meta)
        response = self._call_llm(prompt)

        try:
            parsed = json.loads(response.strip())
        except json.JSONDecodeError:
            return self._fallback_summary(meta, response)

        # 校验并规整
        keywords = parsed.get("keywords") or {}
        if not isinstance(keywords, dict):
            keywords = {}
        return {
            "basic_info": {
                "guide_name": meta.get("guide_name", ""),
                "issuer": meta.get("issuer", ""),
                "doc_type": meta.get("doc_type", ""),
                "cancer_types": meta.get("cancer_types", []),
                "publish_date": meta.get("publish_date", ""),
                "version": meta.get("version", ""),
                "item_count": meta.get("item_count", 0),
            },
            "overview": str(parsed.get("overview") or ""),
            "key_recommendations": [
                str(x) for x in (parsed.get("key_recommendations") or []) if str(x).strip()
            ],
            "evidence_notes": str(parsed.get("evidence_notes") or ""),
            "keywords": {
                "core": [str(x) for x in (keywords.get("core") or [])],
                "cancers": [str(x) for x in (keywords.get("cancers") or [])],
                "scenarios": [str(x) for x in (keywords.get("scenarios") or [])],
            },
            "from_cache": False,
        }

    @staticmethod
    def _fallback_summary(meta: Dict, raw_response: str) -> Dict:
        """LLM 输出非 JSON 时的降级结构（保留原始响应便于排查）。"""
        return {
            "basic_info": {
                "guide_name": meta.get("guide_name", ""),
                "issuer": meta.get("issuer", ""),
                "doc_type": meta.get("doc_type", ""),
                "cancer_types": meta.get("cancer_types", []),
                "publish_date": meta.get("publish_date", ""),
                "version": meta.get("version", ""),
                "item_count": meta.get("item_count", 0),
            },
            "overview": "解析失败",
            "key_recommendations": [],
            "evidence_notes": "",
            "keywords": {"core": [], "cancers": [], "scenarios": []},
            "raw_response": raw_response,
            "from_cache": False,
        }

    def generate_summary_with_cache(self, doc_id: str) -> Dict:
        """生成指南结构化速览（带缓存）。

        流程：内存/ES 缓存命中即返回；否则生成并写入缓存（生成失败不写缓存）。
        """
        cached = summary_cache.get(doc_id)
        if cached:
            cached["from_cache"] = True
            return cached

        summary = self.generate_summary(doc_id)
        if summary and summary.get("overview") not in ("解析失败", ""):
            summary_cache.set(doc_id, summary)
        return summary
