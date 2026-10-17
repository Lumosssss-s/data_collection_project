"""LLM 客户端统一工厂与请求构造工具。

收敛散落在各服务的 `OpenAI(...)` 裸构造与重复的 base_url / api_key / model 解析，
并集中注入思考模式 extra_body（见 Settings.llm_extra_body）。

设计约束：本模块为纯工厂 + 工具函数，不持有业务状态；`timeout` / `max_retries`
默认不传，沿用 OpenAI SDK 默认值，仅显式指定时覆盖，以保证各调用点的既有超时行为不变。
"""
import logging
from typing import Dict, Iterator, List, Optional

from openai import OpenAI

from core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-flash"


def get_client(
    *,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OpenAI:
    """构造统一的 OpenAI 兼容客户端。

    api_key / base_url 未显式传入时回落 settings；timeout / max_retries 为 None 时
    沿用 SDK 默认，避免改变既有调用点的超时与重试语义。
    """
    kwargs: Dict = {
        "api_key": api_key or settings.llm_api_key or "",
        "base_url": base_url or settings.llm_api_base_url or _DEFAULT_BASE_URL,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return OpenAI(**kwargs)


def build_create_kwargs(
    *,
    model: str,
    messages: List[Dict],
    stream: bool,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict] = None,
) -> Dict:
    """构造 chat.completions.create 入参，统一注入思考模式 extra_body。"""
    kwargs: Dict = {
        "model": model,
        "messages": messages,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
        "stream": stream,
    }
    if response_format:
        kwargs["response_format"] = response_format
    extra_body = settings.llm_extra_body()
    if extra_body:
        kwargs["extra_body"] = extra_body
    return kwargs


def chat(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict] = None,
    client: Optional[OpenAI] = None,
) -> str:
    """非流式对话，返回去空白的回答文本。"""
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空")

    target_model = model or settings.llm_model or _DEFAULT_MODEL
    client = client or get_client()
    kwargs = build_create_kwargs(
        model=target_model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    logger.info("[LLM] chat 模型=%s prompt长度=%d", target_model, len(prompt))
    response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


def stream_chat_messages(
    messages: List[Dict],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    client: Optional[OpenAI] = None,
) -> Iterator[str]:
    """流式对话，产出回答文本片段（delta.content）。"""
    target_model = model or settings.llm_model or _DEFAULT_MODEL
    client = client or get_client()
    kwargs = build_create_kwargs(
        model=target_model,
        messages=messages,
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info("[LLM] stream 模型=%s messages=%d", target_model, len(messages))
    response = client.chat.completions.create(**kwargs)
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
