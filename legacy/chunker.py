"""医疗文本分块工具（C1 BE-34）。

设计前提：
- **条目化切分是主路径**——一条推荐条目（REC）= 一个检索单元，由入库脚本
  （``ingest.py``）按业务 ID 直接落库，**不经过本模块**：本模块不参与 REC 切分，
  也不感知 doc/rec/drug/term 等业务字段语义。
- 本模块只处理**长文本兜底**：药品说明书等单条正文可能远超 bge-m3 的有效输入
  长度，需按滑动窗口切分为若干子块，避免单条 embedding 序列过长而失真。

因此本模块仅保留与领域无关的通用分块能力（定长滑窗 + 末尾碎块合并），不含任何
法规/医疗字段语义。法规遗留的结构化解析（``article_number``/``chapter``/
``law_name`` 等，原 ``process_pre_chunked_data`` / ``chunk_from_structure``）已删除。

接线状态：drug 长文本分块（说明书）尚未接入 ``ingest.py``（该处当前按「1 条 = 1
单元」入库），本模块作为该兜底能力的就绪工具待用。
"""
from typing import List

from core.config import settings


def chunk_text(text: str, chunk_size: int = None, chunk_overlap: int = None) -> List[str]:
    """定长滑动窗口切分纯文本（领域无关）。

    :param text: 待切分文本
    :param chunk_size: 单块最大字符数，缺省取 ``settings.chunk_size``
    :param chunk_overlap: 相邻块重叠字符数，缺省取 ``settings.chunk_overlap``
    :return: 切分后的文本块列表；空文本返回 ``[]``
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    chunks: List[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]

        if end < text_length:
            chunk = chunk[:-chunk_overlap]

        chunks.append(chunk)
        start = end - chunk_overlap

    return chunks


def resplit_long_text(text: str, chunk_size: int = None, chunk_overlap: int = None,
                      min_chunk_size: int = 300) -> List[str]:
    """超长文本切分：不超过 ``chunk_size`` 时原样返回单块，否则滑窗切分。

    末尾块若短于 ``min_chunk_size`` 则合并进前一块，避免产生无意义的碎尾块。

    :return: 文本块列表（至少一块）
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    if len(text) <= chunk_size:
        return [text]

    raw_chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not raw_chunks:
        return [text]

    # 合并过短末尾块，避免产生无意义的小碎片
    if len(raw_chunks) >= 2 and len(raw_chunks[-1]) < min_chunk_size:
        raw_chunks[-2] = raw_chunks[-2] + '\n' + raw_chunks[-1]
        raw_chunks = raw_chunks[:-1]

    return raw_chunks
