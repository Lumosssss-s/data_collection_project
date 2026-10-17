"""ChatPromptTemplate 构造。

变量契约（与既有 _build_messages 的输出结构对齐）：
    system_prompt : str                系统文案（作为变量值传入，避免文案中的花括号被当作模板变量）
    history       : List[BaseMessage]  历史对话，可选
    user_message  : str                当前用户消息（已渲染的参考资料 + 问题）
"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


def build_chat_prompt() -> ChatPromptTemplate:
    """构造问答提示词模板：system 文案 + 历史轮次 + 当前用户消息。"""
    return ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            MessagesPlaceholder("history", optional=True),
            ("human", "{user_message}"),
        ]
    )
