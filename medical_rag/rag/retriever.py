"""医疗循证检索器：把既有问答检索口径封装为 LangChain BaseRetriever。

严格镜像 QAService 既有检索逻辑，保证迁移前后候选集与顺序等值：
    查询增强 → 向量检索（ElasticsearchRepository.query）→ 按 item_id 去重
    → 同指南上下文扩展（settings.reference_expand_*）→ 质量门 + 全域回退。
"""
from typing import Any, ClassVar, Dict, List, Optional, Set

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from core.config import settings
from rag.documents import to_document
from repositories.elasticsearch import ElasticsearchRepository

# 质量门阈值（与 QAService._is_retrieval_poor 默认值一致）
_MIN_RESULTS = 2
_MIN_SIMILARITY = 0.6
# 候选池倍数（与 QAService._retrieve_contexts 一致）
_CANDIDATE_MULTIPLIER = 3
_CANDIDATE_FLOOR = 20


class MedicalEvidenceRetriever(BaseRetriever):
    """循证检索器（自定义 BaseRetriever），行为等值于既有问答检索链路。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 主证据库类型：文献层只作兜底；术语层（term）仅用于实体归一与词表对齐，
    # 不作检索结果返回——短实体名在向量检索中会挤占指南/推荐条目位次。
    PRIMARY_DATA_TYPES: ClassVar[List[str]] = ["doc", "rec", "drug"]

    repo: ElasticsearchRepository = Field(default_factory=ElasticsearchRepository)
    top_k: int = 5
    filters: Optional[Dict[str, Any]] = None
    allow_fallback: bool = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        contexts = self.retrieve_contexts_with_fallback(query)
        return [to_document(ctx) for ctx in contexts]

    # ------------------------------------------------------------------ 公开口径
    def retrieve_contexts_with_fallback(self, query: str) -> List[Dict]:
        """检索-反馈自适应：先按过滤条件检索，质量不达标且允许回退时追加全域检索。"""
        contexts = self._retrieve_contexts(query, self.filters, data_types=self.PRIMARY_DATA_TYPES)

        if self.allow_fallback and self.filters and self._is_retrieval_poor(contexts):
            fallback_contexts = self._retrieve_contexts(
                query, None, data_types=self.PRIMARY_DATA_TYPES)
            contexts = self._merge_deduplicate_contexts([contexts, fallback_contexts])

        # 文献证据层补充：追加在指南证据之后，不参与主库排序
        if settings.literature_fallback_enabled:
            lit = self._retrieve_contexts(
                query, self.filters, expand=False, data_types=["literature"]
            )
            lit = [c for c in lit
                   if (c.get("similarity") or 0) >= settings.literature_min_similarity]
            lit = lit[: settings.literature_top_k]
            if lit:
                contexts = contexts + lit

        return contexts

    # ------------------------------------------------------------------ 内部实现
    def _retrieve_contexts(
        self, query: str, filters: Optional[Dict[str, Any]], expand: bool = True,
        data_types: Optional[List[str]] = None
    ) -> List[Dict]:
        candidate_k = max(self.top_k * _CANDIDATE_MULTIPLIER, _CANDIDATE_FLOOR)
        contexts: List[Dict] = []

        # 查询增强：口语化表述补全标准术语（与 QAService._enhance_query 同口径）
        from services.query_decomposer import expand_colloquial
        enhanced_query = expand_colloquial(query)

        # data_type 显式约束：主库检索排除 literature，文献兜底只查 literature
        where = dict(filters) if filters else {}
        if data_types:
            where["data_type"] = list(data_types)
        results = self.repo.query([enhanced_query], n_results=candidate_k, where=where or None)
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                distance = results["distances"][0][i]
                meta = dict(results["metadatas"][0][i])
                meta["item_id"] = results["ids"][0][i]
                contexts.append(
                    {
                        "content": results["documents"][0][i],
                        "metadata": meta,
                        "similarity": 1 / (1 + distance),
                    }
                )

        contexts.sort(key=lambda x: x["similarity"], reverse=True)

        seen: Set[str] = set()
        deduped: List[Dict] = []
        for ctx in contexts:
            key = (ctx.get("metadata") or {}).get("item_id") or ctx.get("content", "")[:50]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ctx)

        top_contexts = deduped[: self.top_k]

        if settings.reference_expand_enabled and expand:
            top_contexts = top_contexts + self._expand_contexts(top_contexts)

        return top_contexts

    def _expand_contexts(self, contexts: List[Dict]) -> List[Dict]:
        """同指南上下文扩展：回取命中条目所在指南的相邻条目（失败静默降级）。"""
        seeds = contexts[: settings.reference_expand_sources]
        existing = {(c.get("metadata") or {}).get("item_id") for c in contexts}
        expanded: List[Dict] = []

        for seed in seeds:
            meta = seed.get("metadata") or {}
            doc_id = meta.get("doc_id")
            if not doc_id:
                continue
            breadcrumb = meta.get("breadcrumb") or ""
            prefix = breadcrumb.rsplit("/", 1)[0] if "/" in breadcrumb else breadcrumb
            try:
                docs = self.repo.get_doc_context_recs(
                    doc_id, existing, prefix, settings.reference_expand_max
                )
            except Exception:
                continue

            for doc in docs:
                item_id = doc.get("item_id")
                if not item_id or item_id in existing:
                    continue
                existing.add(item_id)
                expanded.append(
                    {
                        "content": doc.get("content", ""),
                        "metadata": {k: v for k, v in doc.items() if k != "content"},
                        "similarity": 0.0,
                        "retrieval_hop": 2,
                        "referenced_by": meta.get("item_id", ""),
                    }
                )
                if len(expanded) >= settings.reference_expand_max:
                    return expanded
        return expanded

    def _is_retrieval_poor(
        self,
        contexts: List[Dict],
        min_results: int = _MIN_RESULTS,
        min_similarity: float = _MIN_SIMILARITY,
    ) -> bool:
        if len(contexts) < min_results:
            return True
        return contexts[0]["similarity"] < min_similarity

    @staticmethod
    def _merge_deduplicate_contexts(contexts_list: List[List[Dict]]) -> List[Dict]:
        seen: Set[str] = set()
        merged: List[Dict] = []
        for contexts in contexts_list:
            for ctx in contexts:
                key = (ctx.get("metadata") or {}).get("item_id") or ctx.get("content", "")[:50]
                if key in seen:
                    continue
                seen.add(key)
                merged.append(ctx)
        merged.sort(key=lambda x: x["similarity"], reverse=True)
        return merged
