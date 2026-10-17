"""LCEL 链组装（两段式）。

问答主链是同步生成器（api/v1/qa.py 逐帧消费 StreamingResponse），而 LangChain 的
astream_events 仅提供异步接口；为保持既有 SSE 协议与同步路由不变，问答链拆为两段：
    build_retrieval_stage : retriever → message_builder（一次检索，产出提示词变量 + documents）
    build_generation_stage: prompt → llm → 文本（.stream 逐块产出）

消息组装（参考资料渲染）以 message_builder 注入，文案来源仍是 services.qa_service，
避免在编排层复制业务口径。
"""
from typing import Any, Callable, Dict, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from rag.llm import build_chat_model

MessageBuilder = Callable[[Dict[str, Any]], Dict[str, Any]]


def build_retrieval_stage(
    *, retriever: BaseRetriever, message_builder: MessageBuilder
) -> Runnable:
    """检索 + 消息组装（一次检索）。

    输入 payload：{"question": str, "history": List[BaseMessage], ...}
    输出：message_builder 产出的提示词变量（含并入的 documents）。
    """
    return RunnablePassthrough.assign(
        documents=RunnableLambda(lambda payload: payload["question"]) | retriever
    ) | RunnableLambda(message_builder)


def build_generation_stage(
    *, prompt: ChatPromptTemplate, model: Optional[str] = None, streaming: bool = True
) -> Runnable:
    """提示词 → 模型 → 文本。

    输入：{"system_prompt", "history", "user_message"}（见 rag.prompts）。
    """
    return prompt | build_chat_model(model=model, streaming=streaming) | StrOutputParser()
