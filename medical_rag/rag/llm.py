"""LangChain ChatOpenAI 工厂。

统一解析 settings 的 base_url / api_key / model，并注入思考模式 extra_body，
口径与 utils/llm_client 保持一致，避免 SDK 与编排层配置漂移。
"""
from typing import Optional

from langchain_openai import ChatOpenAI

from core.config import settings

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-flash"


def build_chat_model(
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    streaming: bool = False,
) -> ChatOpenAI:
    """构造 ChatOpenAI，参数口径与 utils/llm_client 一致。"""
    kwargs = {
        "model": model or settings.llm_model or _DEFAULT_MODEL,
        "api_key": settings.llm_api_key or "",
        "base_url": settings.llm_api_base_url or _DEFAULT_BASE_URL,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
        "streaming": streaming,
    }
    extra_body = settings.llm_extra_body()
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatOpenAI(**kwargs)
