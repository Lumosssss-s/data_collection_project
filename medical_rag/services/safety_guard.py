"""生成后安全校验：对已生成完的答案做规则检查，命中则追加一段提示。

为什么放在生成后：剂量 / 预后 / 来源缺失这三类风险无法在检索前判定，必须看模型
实际写了什么；但又不能打断流式输出，所以在流末尾追加可读的提示，原文保持完整。

判定保持保守（宁可漏报也不误伤）：
  - 剂量：仅当问题在问「我个人吃多少」且答案出现具体数值剂量、又没有免责表述时才提示；
  - 预后：仅当问题在问「还能活多久」且答案给出个体化时间预测时才提示；
  - 来源：仅当答案有临床建议内容却一条来源标注都没有时才提示。
"""
from __future__ import annotations

import re
from typing import List

# 问题侧：患者询问个人给药剂量
_PERSONAL_DOSE_Q = re.compile(
    # ① 自己要求调整剂量（「我自己减半吃」「能不能停」）
    r"(?:我|自己|我爸|我妈|家人|老人).{0,15}(?:减半|加倍|减量|加量|停药|调整剂量)"
    # ② 问个人吃多少（「一天吃几片」「打多少毫克」）
    r"|(?:我|自己|家人|老人).{0,15}(?:吃|服|用|打).{0,8}(?:多少|几片|几粒|几支|毫克|剂量)"
    r"|体表面积|按我的体重")
# 答案侧：出现具体剂量数值
_CONCRETE_DOSE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|毫克|片|粒|mg/m2|mg/m²)", re.IGNORECASE)
_DOSE_DISCLAIMER = ("必须由主管医师", "由医师", "请勿自行", "不可自行", "个体化",
                    "遵医嘱", "以说明书为准", "不构成用药决策", "具体用药请以")

# 问题侧：询问预后
_PROGNOSIS_Q = re.compile(r"还能活|能活多久|活几年|活多长时间|生存期|还能撑|能拖多久")
# 答案侧：给出个体化时间预测（区别于引用试验的中位生存期数据）
_INDIVIDUAL_PROGNOSIS = re.compile(
    r"(?:预计|大约|大概|估计).{0,12}(?:生存|活|生存期).{0,12}(?:\d+\s*个?月|\d+\s*年)"
    r"|(?:您|你|患者).{0,12}(?:生存|存活).{0,8}(?:\d+\s*个?月|\d+\s*年)")
_PROGNOSIS_DISCLAIMER = ("无法预测", "不能预测", "因人而异", "受多种因素",
                         "建议与主管医师", "不构成诊断")

_CITATION_MARKS = ("【来源", "【文献", "【关联条目")
_CLINICAL_WORDS = ("推荐", "治疗", "建议", "用药", "手术")


def _has_any(text: str, words) -> bool:
    return any(w in text for w in words)


def check_answer(question: str, answer: str) -> str:
    """返回需要追加的安全提示段落（无需提示时返回空串）。"""
    q = question or ""
    a = answer or ""
    if len(a) < 200:  # 过短的一律视为拒答/边界说明，不再追加
        return ""

    warnings: List[str] = []

    if _PERSONAL_DOSE_Q.search(q) and _CONCRETE_DOSE.search(a) \
            and not _has_any(a, _DOSE_DISCLAIMER):
        warnings.append(
            "剂量提示：上文数值是指南或说明书中的标准剂量，不能直接用于个人。实际剂量须由"
            "主管医师结合体重、肝肾功能、血象与不良反应分级决定，请勿自行减量、加量或停药。")

    if _PROGNOSIS_Q.search(q) and _INDIVIDUAL_PROGNOSIS.search(a) \
            and not _has_any(a, _PROGNOSIS_DISCLAIMER):
        warnings.append(
            "预后提示：生存期受分期、分子分型、治疗反应和个体状况影响，任何单一时间数字都不"
            "代表个人结局。请与主管医师结合完整病历讨论后续方案。")

    if _has_any(a, _CLINICAL_WORDS) and not _has_any(a, _CITATION_MARKS):
        warnings.append(
            "来源提示：本回答未标注循证来源，不能作为诊疗依据。请以指南原文与主管医师判断为准。")

    if not warnings:
        return ""
    return "\n\n---\n\n" + "\n".join(f"> {w}" for w in warnings)
