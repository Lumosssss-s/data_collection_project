"""查询辅助：癌种识别 + 口语化改写。

本模块原承担多跳查询分解（多跳 B）与两跳扩展词构造（多跳 C），
两能力已于 2026-10-30 整体弃用，原因见 core/config.py 注释与 docs/多跳推理评测报告.md：
  - 两跳扩展在 30 题多跳评测集上 MRR 仅 +0.0028（噪声量级）；瓶颈是召回而非排序。
  - 法规项目的两条主力多跳链（引用链 + 实体导航链）在医疗语料上无结构基础
    （1513 条 REC 的 refs 全空、KG 无 Drug 出边），照搬预期增益接近零。

保留的两项工具被 qa_service / retriever_service / rag.retriever 多处引用：
  - detect_cancer_types：从查询中识别癌种代码，用作检索过滤维度。
  - expand_colloquial：把「肺上有结节要不要开刀」这类口语化查询补成标准医学术语，
    解决向量检索因字面表述差异导致的召回失败。
"""
from __future__ import annotations

import re
from typing import Dict, List


# ---------------------------------------------------------------------------
# 癌种别名（§5.7.3 cancer_type）：code -> 别名（含中文简称 / 英文缩写 / 常见写法）。
# 高频别名硬编码（与 core.domain_enums.CANCER_TYPE_ALIASES 同源思路）；完整同义词表
# 待 A5 术语字典到位后可改为字典驱动。
# ---------------------------------------------------------------------------
_CANCER_ALIASES: Dict[str, List[str]] = {
    # 肺结节 / 磨玻璃结节属于肺癌筛查与结节管理范畴，按 lung 处理：
    # 否则「肺上有结节要不要开刀」识别不到癌种，会回退全域检索并混入结直肠条目。
    "lung": ["肺癌", "肺恶性肿瘤", "非小细胞肺癌", "nsclc", "sclc", "小细胞肺癌",
             "肺腺癌", "肺鳞癌", "肺ca", "肺结节", "肺部结节", "磨玻璃结节", "毛玻璃结节"],
    "breast": ["乳腺癌", "乳腺恶性肿瘤", "乳癌", "乳腺ca"],
    # 肛管癌/肛门癌属结直肠范畴；乙状结肠癌已被「结肠癌」子串覆盖，无需重复登记
    "colorectal": ["结直肠癌", "大肠癌", "结肠癌", "直肠癌", "结直肠", "肠癌",
                   "肛管癌", "肛门癌"],
    "gastric": ["胃癌", "胃恶性肿瘤", "胃ca"],
    "thyroid": ["甲状腺癌", "甲状腺恶性肿瘤", "甲状腺ca"],
    "liver": ["肝癌", "肝恶性肿瘤", "肝ca"],
    # 知识库未覆盖的常见癌种统一归为 other：只用于「越界拦截 / 搜索无结果」，
    # 不写入任何记录（记录侧 cancer_type 仍受 §5.7.3 受控枚举约束）。
    "other": ["胰腺癌", "前列腺癌", "食管癌", "宫颈癌", "子宫颈癌", "卵巢癌", "膀胱癌",
              "肾癌", "胆囊癌", "胆管癌", "鼻咽癌", "喉癌", "口腔癌", "舌癌",
              "白血病", "淋巴瘤", "骨髓瘤", "黑色素瘤", "骨肉瘤", "胶质瘤", "脑瘤"],
}


# 口语句式的肺结节表述（「肺上有结节」「右肺下叶小结节」）不含「肺结节」字串，
# 用受限于「肺…结节」之间最多 6 字的模式补齐，避免误命中甲状腺结节 / 乳腺结节。
_LUNG_NODULE_RE = re.compile(r"肺[^，,。；;、]{0,6}结节|磨玻璃|毛玻璃")


def detect_cancer_types(text: str) -> List[str]:
    """返回文本中出现的癌种代码（去重，按别名表顺序）。

    供 qa_service._scope_boundary（癌种边界守卫）与 retriever_service /
    rag.retriever 的默认检索过滤复用。
    """
    lowered = (text or "").lower()
    hits = {code for code, aliases in _CANCER_ALIASES.items()
            if any(a.lower() in lowered for a in aliases)}
    if _LUNG_NODULE_RE.search(lowered):
        hits.add("lung")
    return [code for code in _CANCER_ALIASES if code in hits]


# ---------------------------------------------------------------------------
# 口语化查询改写：把患者口述补成标准医学表述。
# 只在查询命中口语化标志时触发，避免影响常规临床表述查询的向量表示。
# 做法是「追加标准术语」而非替换原词：原句保留，标准术语补足检索所需的关键概念
# （磨玻璃结节 / 肺结节 / 手术指征），解决「肺上有结节要不要开刀」这类查询召回失败。
# ---------------------------------------------------------------------------
_COLLOQUIAL_RE = re.compile(
    r"开刀|动手术|要不要|需不需要|该不该|吃啥药|吃什么药|咋办|怎么办|严重吗|要紧吗")
_COLLOQUIAL_TERMS: List[tuple] = [
    (re.compile(r"磨玻璃|毛玻璃|GGO|GGN", re.IGNORECASE),
     "磨玻璃结节 ground-glass nodule pulmonary nodule"),
    (re.compile(r"结节"), "肺结节 pulmonary nodule"),
    (re.compile(r"开刀|动手术|手术"), "手术切除 surgical resection 手术指征"),
    (re.compile(r"吃药|服药|用药|药"), "药物治疗 用药方案"),
]


def expand_colloquial(query: str) -> str:
    """口语化查询补全标准术语；非常规口语表述原样返回。

    例：「肺上有结节要不要开刀」→ 原句 + 「肺结节 pulmonary nodule 手术切除 surgical
    resection 手术指征」。仅追加、不替换，保证原查询语义不丢。
    """
    q = (query or "").strip()
    if not q or not _COLLOQUIAL_RE.search(q):
        return q
    extra: List[str] = []
    for pattern, term in _COLLOQUIAL_TERMS:
        if pattern.search(q) and term not in extra:
            extra.append(term)
    return f"{q} {' '.join(extra)}" if extra else q
