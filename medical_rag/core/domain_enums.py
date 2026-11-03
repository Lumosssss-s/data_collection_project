"""医疗领域受控枚举（主方案 §5.7.3 受控词表的代码权威定义）

- CancerType：癌种代码（cancer_type 字段合法值）
- DiseaseCategory：疾病档案收录类别（disease_profile.category）
- CANCER_TYPE_INFO / CANCER_TYPE_ALIASES：中文名、别名到标准代码的映射

范围码 = 癌种代码大写，用于 G5 记录 ID（<前缀>-<范围码>-<来源码>-<序号>，
如 REC-LUNG-CACA-0001 / DOC-BREAST-CACA-001）。
"""
from enum import Enum
from typing import Dict, List, Tuple


class CancerType(str, Enum):
    """癌种枚举（§5.7.3；liver 为赛程外扩预留，赛程内不交付数据）"""
    LUNG = "lung"                # 肺癌
    BREAST = "breast"            # 乳腺癌
    COLORECTAL = "colorectal"    # 结直肠癌
    GASTRIC = "gastric"          # 胃癌
    THYROID = "thyroid"          # 甲状腺癌
    LIVER = "liver"              # 肝癌（预留）


class DiseaseCategory(str, Enum):
    """疾病档案收录类别（disease_profile.category，§5.7.3）"""
    PRIMARY_CANCER = "primary_cancer"                    # 原发恶性肿瘤
    PRECANCEROUS_LESION = "precancerous_lesion"          # 癌前病变
    BORDERLINE_BENIGN_TUMOR = "borderline_benign_tumor"  # 交界性/良性肿瘤
    TUMOR_COMPLICATION = "tumor_complication"            # 肿瘤并发症/相关疾病


# 癌种信息映射表：标准中文名 -> (癌种代码, 范围码)
CANCER_TYPE_INFO: Dict[str, Tuple[str, str]] = {
    "肺癌": ("lung", "LUNG"),
    "乳腺癌": ("breast", "BREAST"),
    "结直肠癌": ("colorectal", "COLORECTAL"),
    "胃癌": ("gastric", "GASTRIC"),
    "甲状腺癌": ("thyroid", "THYROID"),
    "肝癌": ("liver", "LIVER"),
}

# 中文别名 -> 标准癌种代码（别名表扩充归术语字典/词表管，此处仅收录高频临床变体）
CANCER_TYPE_ALIASES: Dict[str, str] = {
    "肺恶性肿瘤": "lung",
    "乳腺恶性肿瘤": "breast",
    "乳腺": "breast",
    "乳癌": "breast",
    "breast cancer": "breast",
    "大肠癌": "colorectal",
    "结直肠": "colorectal",
    "胃恶性肿瘤": "gastric",
    "甲状腺恶性肿瘤": "thyroid",
    "肝恶性肿瘤": "liver",
}


def get_cancer_type_info(name: str) -> Tuple[str, str]:
    """癌种中文名 / 别名 / 代码（大小写不敏感）-> (标准癌种代码, 范围码)

    Raises:
        ValueError: 输入不在受控词表内。医疗侧癌种为受控枚举，不自动派生，
        与法规版 get_jurisdiction_info 的宽松回退行为刻意不同。
    """
    if not name or not name.strip():
        raise ValueError("癌种名称不能为空")

    key = name.strip()

    # 1) 标准中文名精确匹配
    if key in CANCER_TYPE_INFO:
        return CANCER_TYPE_INFO[key]

    # 2) 中文别名匹配
    if key in CANCER_TYPE_ALIASES:
        code = CANCER_TYPE_ALIASES[key]
        return code, code.upper()

    # 3) 癌种代码匹配（大小写不敏感）
    lowered = key.lower()
    for member in CancerType:
        if member.value == lowered:
            return member.value, member.value.upper()

    raise ValueError(
        f"未知癌种：{name!r}（合法值：{', '.join(m.value for m in CancerType)}）"
    )


def get_all_cancer_types() -> List[str]:
    """全部标准癌种代码列表"""
    return [code for code, _ in CANCER_TYPE_INFO.values()]
