"""RAG 编排包（LangChain）。

把项目既有的手写 RAG 链（检索 → 提示词 → LLM → 流式输出）落成 LangChain 编排层：
    - llm            : ChatOpenAI 工厂（统一 base_url/api_key/extra_body）
    - documents      : 检索结果 dict 与 LangChain Document 互转
    - retriever      : 既有问答检索口径的 BaseRetriever 封装（行为等值）
    - rerank         : ReRankerService 的 Document 级封装（供检索页路径复用）
    - prompts        : ChatPromptTemplate 构造
    - chain          : LCEL 链组装（两段式）
    - stream_bridge  : 业务对象 → 既有 SSE 协议帧

设计约束：检索口径与提示词文本均以「迁移前后行为等值」为准，不改变召回集与顺序。
"""
from rag.chain import build_generation_stage, build_retrieval_stage
from rag.llm import build_chat_model
from rag.retriever import MedicalEvidenceRetriever

__all__ = [
    "build_chat_model",
    "build_retrieval_stage",
    "build_generation_stage",
    "MedicalEvidenceRetriever",
]
