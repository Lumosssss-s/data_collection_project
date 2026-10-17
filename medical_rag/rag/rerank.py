"""ReRankerService 的 Document 级封装。

供检索页路径（混合检索 RRF 之后的两阶段精排）在 LangChain 编排下复用，
不改变 ReRankerService 的评分与并发语义——模型不可用时沿用其「保持原序返回」的降级行为。
"""
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from core.config import settings
from rag.documents import from_documents, to_documents


def rerank_documents(
    query: str,
    documents: List[Document],
    *,
    top_k: Optional[int] = None,
    service=None,
) -> List[Document]:
    """对 Document 列表按 query 精排，返回带 rerank_score 的前 top_k 条。

    settings.reranker_enabled 关闭时直接截断，与既有行为一致。
    """
    if not documents:
        return []
    if not settings.reranker_enabled:
        return documents[:top_k] if top_k else documents

    if service is None:
        from services.reranker_service import ReRankerService
        service = ReRankerService()

    ranked = service.rerank(query=query, candidates=from_documents(documents), top_k=top_k)
    return to_documents(ranked)


def build_rerank_step(*, top_k: Optional[int] = None, service=None) -> RunnableLambda:
    """构造 LCEL 可用的精排步骤：输入 {"query", "documents"} → 输出排序后的 documents。"""

    def _step(payload) -> List[Document]:
        query = payload.get("query", "") if isinstance(payload, dict) else str(payload)
        documents = payload.get("documents") if isinstance(payload, dict) else payload
        return rerank_documents(query, documents or [], top_k=top_k, service=service)

    return RunnableLambda(_step)
