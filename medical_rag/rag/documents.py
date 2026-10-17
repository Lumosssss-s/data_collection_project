"""检索结果（dict）与 LangChain Document 的互转。

检索结果字段口径见 services.qa_service / services.retriever_service：
    content 正文 + metadata（含 item_id / title / breadcrumb / cancer_type / doc_id …）
    + similarity + 可选 retrieval_hop（=2 表示同指南扩展条目）。

转换时把 similarity / retrieval_hop / referenced_by 收入 metadata，往返无损，
使链外用 from_document 还原后仍与既有 _build_messages 的输入结构一致。
"""
from typing import Any, Dict

from langchain_core.documents import Document

_EXTRA_KEYS = ("similarity", "retrieval_hop", "referenced_by")


def to_document(record: Dict[str, Any]) -> Document:
    """把单条检索结果转为 Document（metadata 收入全部业务字段）。"""
    meta = dict(record.get("metadata") or {})
    for key in _EXTRA_KEYS:
        if key in record:
            meta[key] = record[key]
    return Document(page_content=record.get("content", "") or "", metadata=meta)


def from_document(doc: Document) -> Dict[str, Any]:
    """把 Document 还原为检索结果结构（与 _build_messages 输入一致）。"""
    meta = dict(doc.metadata or {})
    return {
        "content": doc.page_content,
        "metadata": meta,
        "similarity": meta.get("similarity", 0.0),
        "retrieval_hop": meta.get("retrieval_hop", 1),
        "referenced_by": meta.get("referenced_by", ""),
    }


def to_documents(records) -> list:
    return [to_document(r) for r in (records or [])]


def from_documents(docs) -> list:
    return [from_document(d) for d in (docs or [])]
