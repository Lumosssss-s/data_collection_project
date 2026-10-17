"""多跳 B：查询分解（规则前置 → LLM 兜底 → 失败降级单跳）。

医疗版：把「肺癌术后辅助治疗和随访复查有哪些要求」这类复合查询拆成若干单一意图
子查询，交给 RetrieverService 并行检索后合并；规则无法判定时再用 LLM 兜底。

设计约束：
  - 规则前置：能从字面确定性切分就不调 LLM（省时、确定、可复现）；
  - LLM 兜底：仅当查询「明显复合但规则切不干净」时启用，且带超时；
  - 失败降级：任何异常/超时/解析失败一律返回 []，调用方回退单跳，绝不阻断检索；
  - 让路对比 / 专题：查询同时涉及 ≥2 个癌种时视为跨癌种对比意图（对比 BE-08 / 专题
    BE-09 职责），不做分解；
  - 让路精准意图：查询已带多项临床条件（分期 / 分子 / 治疗线数，见
    _CLINICAL_GUARD_MIN_DIMS）时视为精确检索意图，不做分解。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from core.config import settings
from utils.llm_client import chat, get_client

logger = logging.getLogger(__name__)

# 癌种别名（§5.7.3 cancer_type）：code -> 别名（含中文简称 / 英文缩写 / 常见写法）。
# 高频别名硬编码（与 core.domain_enums.CANCER_TYPE_ALIASES 同源思路）；完整同义词表
# 待 A5 术语字典到位后可改为字典驱动。
_CANCER_ALIASES: Dict[str, List[str]] = {
    "lung": ["肺癌", "肺恶性肿瘤", "非小细胞肺癌", "nsclc", "sclc", "小细胞肺癌",
             "肺腺癌", "肺鳞癌", "肺ca"],
    "breast": ["乳腺癌", "乳腺恶性肿瘤", "乳癌", "乳腺ca"],
    "colorectal": ["结直肠癌", "大肠癌", "结肠癌", "直肠癌", "结直肠", "肠癌"],
    "gastric": ["胃癌", "胃恶性肿瘤", "胃ca"],
    "thyroid": ["甲状腺癌", "甲状腺恶性肿瘤", "甲状腺ca"],
    "liver": ["肝癌", "肝恶性肿瘤", "肝ca"],
}


def detect_cancer_types(text: str) -> List[str]:
    """返回文本中出现的癌种代码（去重，按别名表顺序）。

    供本模块的「多癌种让路」守卫使用，也可供其他模块（如对比 / 专题）复用。
    """
    lowered = (text or "").lower()
    return [code for code, aliases in _CANCER_ALIASES.items()
            if any(a.lower() in lowered for a in aliases)]


# ---- 临床条件（PICO 要素）识别：分期 / 分子 / 治疗线数，各计一维 ----
# 分期只取「明确期别」（罗马数字期 / 细分期 IIIA 等 / TNM），不含 早期/中期/晚期 定性词 ——
# 避免把「晚期肺癌怎么治」这类常规问题误判为精准意图。
_STAGE_RE = re.compile(r"(?:^|[^A-Za-z0-9])(0|I{1,3}|IV|Ⅰ|Ⅱ|Ⅲ|Ⅳ)[ABCabc]?\s*期")
_TNM_RE = re.compile(r"[Tt][1-4][Nn][0-3][Mm][01]")
_BIOMARKER_TOKENS = [
    "EGFR", "ALK", "ROS1", "KRAS", "NRAS", "HRAS", "BRAF", "HER2", "BRCA",
    "MSI-H", "dMMR", "PD-L1", "TMB", "HRD", "NTRK", "RET", "MET", "EBV", "ER", "PR",
]
# 词边界匹配：避免短标记（ER / PR / MET / RET）在英文或拼音串中被误命中
_BIOMARKER_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in _BIOMARKER_TOKENS) + r")(?![a-z0-9])",
    re.IGNORECASE,
)
_LINE_RE = re.compile(r"(?:^|[^0-9])([一二三四五12345])\s*线")

# 视为「精准意图」所需命中的临床条件维度数（分期 / 分子 / 线数，任取 N 项）。
# 调高=更少拦截（更多查询会被分解）；调低=更容易拦截。默认 2（两项约束即视为精准）。
_CLINICAL_GUARD_MIN_DIMS = 2


def _clinical_dims(text: str) -> int:
    """统计文本命中的临床条件维度数（分期 / 分子 / 线数，取值 0~3）。"""
    q = text or ""
    dims = 0
    if _STAGE_RE.search(q) or _TNM_RE.search(q):
        dims += 1
    if _BIOMARKER_RE.search(q):
        dims += 1
    if _LINE_RE.search(q) or "后线" in q or "末线" in q:
        dims += 1
    return dims


# 并列 / 对比标志：出现其一才认为查询可能复合。
_CONJUNCTION_RE = re.compile(r"以及|並且|并且|和|與|与|跟|、|對比|对比|比較|比较|分別|分别|各自")

# 触发 LLM 兜底的最小查询长度：太短的句子几乎不会是真正的复合问题，
# 用长度门槛挡掉「和平与发展」这类被误判的短语，避免无谓的 LLM 调用与延迟。
_LLM_MIN_LEN = 12
# 规则切分后每段的最小长度（字符）。
_MIN_PART_LEN = 3


# 共享限定语的边界标志：并列结构右半段通常省略了左半段已有的主语/限定语
# （「肺癌术后辅助治疗和随访要求」→ 右半段需补回「肺癌术后辅助治疗」这一语境）。
_CONTEXT_BOUNDARY = ("的", "對", "对", "關於", "关于", "就")


def _context_prefix(left: str) -> str:
    """取左半段最后一个限定语边界（的/对/关于/就…）及其之前的部分，作为右半段的共享前缀。"""
    idx = -1
    for marker in _CONTEXT_BOUNDARY:
        pos = left.rfind(marker)
        if pos > idx:
            idx = pos
    return left[: idx + 1] if idx >= 0 else ""


def _split_by_conjunction(query: str) -> List[str]:
    """按第一个并列/对比标志把查询一分为二；任一侧过短则视为切不干净。

    右半段补上左半段的共享限定语，避免产生「随访要求有哪些」这类丢失主体的
    子查询——那会召回大量无关文档，把噪声带进合并候选池。
    """
    m = _CONJUNCTION_RE.search(query)
    if not m:
        return []
    left = query[:m.start()].strip(" \t，,、。；;：:")
    right = query[m.end():].strip(" \t，,、。；;：:")
    if len(left) < _MIN_PART_LEN or len(right) < _MIN_PART_LEN:
        return []
    prefix = _context_prefix(left)
    right_full = (prefix + right) if prefix else right
    return [left, right_full]


def _parse_llm_subqueries(text: str, original: str) -> List[str]:
    """从 LLM 输出里稳定地取出子查询列表（优先 JSON 数组，退化为逐行）。"""
    parts: List[str] = []
    m = re.search(r"\[.*\]", text or "", re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            parts = [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            parts = []
    if not parts:
        parts = [ln.strip(" \t-•*0123456789.、)") for ln in (text or "").splitlines() if ln.strip()]

    out: List[str] = []
    for p in parts:
        if p and p != original and len(p) >= 2 and p not in out:
            out.append(p)
    return out


def _llm_decompose(query: str) -> List[str]:
    """LLM 兜底：让模型把复合查询拆成 2~3 条自包含子查询。失败返回 []。"""
    if not settings.multihop_decompose_llm_enabled:
        return []
    api_key = settings.llm_api_key or ""
    if not api_key:
        return []
    model = settings.llm_model or "deepseek-flash"
    prompt = (
        "你是肿瘤循证检索的查询改写助手。把下面这条可能包含多个临床问题的复合查询，"
        "拆成 2~3 条各自独立、语义完整、可直接用于检索的子查询。\n"
        "要求：\n"
        "1. 每条子查询自包含，不要出现「上述/前者/后者/它」等指代；\n"
        "2. 保留原查询中的癌种、分期、分子分型、治疗线数等临床限定条件；\n"
        "3. 如果它其实只有一个问题、无法拆解，返回空数组 []；\n"
        "4. 只输出 JSON 数组，例如 [\"子查询1\",\"子查询2\"]，不要输出解释。\n"
        f"查询：{query}"
    )
    try:
        text = chat(
            prompt,
            model=model,
            temperature=0,
            max_tokens=200,
            client=get_client(timeout=settings.multihop_decompose_llm_timeout),
        )
        return _parse_llm_subqueries(text, query)
    except Exception as e:  # 超时/网络/解析等一律降级
        logger.warning("LLM 查询分解失败，降级单跳: %s", e)
        return []


def decompose_query(query: str) -> List[str]:
    """把复合查询拆成子查询列表；无法/无需分解时返回 []。

    返回的子查询**不包含**原查询——调用方负责把原查询作为锚点一并检索，
    从而保证分解只增加候选、不丢原有召回。
    """
    q = (query or "").strip()
    if len(q) < 4:
        return []

    # 多癌种查询让路对比 / 专题，避免把对比意图拆成两路普通检索
    if len(detect_cancer_types(q)) >= 2:
        return []

    # 精准意图（已带多项临床条件）不分解：拆分会稀释精确检索的召回精度
    if _clinical_dims(q) >= _CLINICAL_GUARD_MIN_DIMS:
        return []

    max_sub = max(2, settings.multihop_decompose_max_subqueries - 1)  # 预留 1 个给锚点

    # 规则前置：必须出现并列/对比标志才尝试切分
    if _CONJUNCTION_RE.search(q):
        parts = _split_by_conjunction(q)
        if len(parts) >= 2:
            return parts[:max_sub]
        # 规则切不干净但查询明显复合 → LLM 兜底
        if len(q) >= _LLM_MIN_LEN:
            parts = _llm_decompose(q)
            if len(parts) >= 2:
                return parts[:max_sub]

    return []
