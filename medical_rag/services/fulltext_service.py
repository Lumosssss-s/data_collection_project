"""指南全文解析服务（只读，不改索引）。

背景：ES 中 `doc` 记录只保留摘要（ingest._extract_content 对 doc 只取
summary/abstract/title），正文以 REG 推荐条目分块承载。需要「整篇通读」时
按需解析原始 JATS XML，避免把全文塞进检索索引改变召回分布。

数据来源：`data/raw/guidelines/<doc_id>.xml`（Europe PMC fullTextXML）。
输出：按 `<sec>` 递归的章节树，排除参考文献、致谢、脚注等后置部分。
"""
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from core.config import settings

logger = logging.getLogger(__name__)

GUIDELINE_DIR = os.path.join(settings.data_dir, "guidelines")

# 单文件上限：当前最大 946 KB，留足余量同时防异常大文件拖垮解析
MAX_XML_BYTES = 4 * 1024 * 1024

# doc_id 白名单：只允许大写字母、数字与连字符（同时挡住路径穿越）
_DOC_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{4,63}$")

# 不进入正文树的 section 类型（参考文献 / 致谢 / 脚注 / 利益冲突 / 补充材料等后置部分）
_EXCLUDED_SEC_TYPES = {
    "ref-list", "ack", "fn-group", "notes", "supplementary-material",
    "COI-statement", "data-availability", "history",
}

# 无 sec-type 时的兜底排除：按标题判定的后置章节
_EXCLUDED_HEADINGS = {
    "funding", "conflicts of interest", "conflict of interest", "disclosure",
    "supporting information", "supplementary data", "data availability statement",
    "author contributions", "acknowledgements", "acknowledgments",
    "footnotes", "references",
}


def _local(tag: str) -> str:
    """去掉可能的命名空间前缀。"""
    return tag.split("}")[-1] if "}" in tag else tag


def _text(el: Optional[ET.Element]) -> str:
    """元素内全部文本，压缩空白。"""
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _blocks(sec: ET.Element) -> List[str]:
    """取该 section 直属的段落类内容（不含子 section）。"""
    out: List[str] = []
    for child in sec:
        tag = _local(child.tag)
        if tag == "p":
            t = _text(child)
            if t:
                out.append(t)
        elif tag == "list":
            for li in child.iter():
                if _local(li.tag) != "list-item":
                    continue
                t = _text(li)
                if t:
                    out.append("• " + t)
        elif tag in ("fig", "table-wrap"):
            label = _text(child.find("label"))
            caption = _text(child.find("caption"))
            if caption:
                out.append(f"[{label or ('图' if tag == 'fig' else '表')}] {caption}")
        elif tag == "def-list":
            for di in child:
                if _local(di.tag) != "def-item":
                    continue
                term, definition = _text(di.find("term")), _text(di.find("def"))
                if term or definition:
                    out.append(f"{term}：{definition}")
    return out


def _parse_section(sec: ET.Element, level: int) -> Optional[Dict]:
    """递归解析一个 <sec>；后置章节（参考文献/致谢/利益冲突等）返回 None。"""
    if (sec.get("sec-type") or "") in _EXCLUDED_SEC_TYPES:
        return None
    heading = _text(sec.find("title"))
    if heading.strip().lower() in _EXCLUDED_HEADINGS:
        return None
    node = {
        "id": sec.get("id") or "",
        "heading": heading,
        "level": level,
        "paragraphs": _blocks(sec),
        "children": [],
    }
    for sub in sec:
        if _local(sub.tag) != "sec":
            continue
        child = _parse_section(sub, level + 1)
        if child:
            node["children"].append(child)
    return node


def _count(node: Dict) -> int:
    return (sum(len(p) for p in node["paragraphs"])
            + sum(_count(c) for c in node["children"]))


def _resolve_path(doc_id: str) -> str:
    """校验 doc_id 并返回解析后的绝对路径（防路径穿越）。"""
    if not _DOC_ID_RE.match(doc_id or ""):
        raise ValueError("doc_id 格式非法")
    base = os.path.realpath(GUIDELINE_DIR)
    path = os.path.realpath(os.path.join(base, doc_id + ".xml"))
    if os.path.dirname(path) != base:
        raise ValueError("doc_id 越界")
    return path


def get_fulltext(doc_id: str) -> Dict:
    """读取并解析指南全文，返回章节树。

    Raises:
        ValueError: doc_id 非法 / 文件超大 / XML 解析失败
    """
    path = _resolve_path(doc_id)
    if not os.path.isfile(path):
        return {"found": False, "doc_id": doc_id, "message": "该指南没有可用的全文 XML"}

    size = os.path.getsize(path)
    if size > MAX_XML_BYTES:
        raise ValueError(f"全文文件过大（{size} 字节），拒绝解析")

    with open(path, "rb") as f:
        raw = f.read()

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning("[fulltext] XML 解析失败 doc_id=%s: %s", doc_id, e)
        raise ValueError("全文 XML 解析失败")

    title = _text(root.find(".//article-title"))
    abstract_el = root.find(".//abstract")
    abstract = _text(abstract_el)

    body = root.find(".//body")
    sections: List[Dict] = []
    if body is not None:
        for sec in body:
            if _local(sec.tag) != "sec":
                continue
            node = _parse_section(sec, 1)
            if node:
                sections.append(node)

    total = sum(_count(s) for s in sections)
    return {
        "found": True,
        "doc_id": doc_id,
        "title": title,
        "abstract": abstract,
        "sections": sections,
        "stats": {
            "section_count": len(sections),
            "char_count": total,
            "xml_bytes": size,
        },
    }
