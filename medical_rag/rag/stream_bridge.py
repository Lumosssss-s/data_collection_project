"""SSE 协议帧构造（与既有服务端输出逐字段一致）。

既有协议（服务端 api/v1/qa.py 产出、前端 frontend/js/app.js 消费）：
    {"type": "status",  "stage": str, "data": str}
    {"type": "sources", "sources": [...], "retrieved_count": int, "cancer_types": [...]}
    {"type": "content", "data": <delta>}
    {"type": "error",   "data": str}
    {"type": "end",     "timing": {...}}

本模块只负责「业务对象 → 协议帧」的翻译，输出为 dict，由调用方 yield。
"""
from typing import Any, Dict, Iterable

_SNIPPET_LIMIT = 100


def status_frame(stage: str, data: str) -> Dict[str, Any]:
    return {"type": "status", "stage": stage, "data": data}


def content_frame(delta: str) -> Dict[str, Any]:
    return {"type": "content", "data": delta}


def error_frame(message: str) -> Dict[str, Any]:
    return {"type": "error", "data": message}


def end_frame(timing: Dict[str, str]) -> Dict[str, Any]:
    return {"type": "end", "timing": timing}


def sources_frame(contexts: Iterable[Dict]) -> Dict[str, Any]:
    """把检索结果（含扩展条目）转为 sources 帧。

    cancer_type 取值回落 chain 与既有实现一致：cancer_type 为空时取 cancer_types 首项；
    正文截断为 100 字并追加省略号。
    """
    sources = []
    cancer_types = set()
    count = 0

    for ctx in contexts:
        count += 1
        meta = ctx.get("metadata") or {}
        cancer_type = meta.get("cancer_type", "") or (meta.get("cancer_types") or [""])[0]
        if cancer_type:
            cancer_types.add(cancer_type)

        content = ctx.get("content") or ""
        sources.append(
            {
                "item_id": meta.get("item_id", ""),
                "data_type": meta.get("data_type", ""),
                "title": meta.get("title", ""),
                "cancer_type": cancer_type,
                "breadcrumb": meta.get("breadcrumb", ""),
                "similarity": ctx.get("similarity"),
                "content": content[:_SNIPPET_LIMIT] + "..."
                if len(content) > _SNIPPET_LIMIT
                else content,
            }
        )

    return {
        "type": "sources",
        "sources": sources,
        "retrieved_count": count,
        "cancer_types": list(cancer_types),
    }
