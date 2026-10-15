"""疾病知识库服务（NM-01，主方案 §6.7）。

以「疾病」为中心的结构化百科：名称归一检索 / 症状反查 / 分类浏览 / 双版本详情。

数据来源：`medical_disease_profiles` 索引（A3 疾病档案，mapping 见 C2 §4.2）。
数据未就绪（索引空）时**优雅降级**：返回 `degraded=True` + 提示文案，不抛异常。

复用：`EntityDisambiguationService.resolve` 做名称归一（A5 术语字典到位前为高频别名兜底）。
"""
import logging
import re
from typing import Dict, List, Optional

from core.domain_enums import DiseaseCategory
from repositories.elasticsearch import ElasticsearchRepository
from services.entity_disambiguation_service import EntityDisambiguationService

logger = logging.getLogger(__name__)

# 14 section 展示顺序与中文标签（A3 §②；sections / patient_version 同构）
SECTION_ORDER: List[Dict[str, str]] = [
    {"key": "overview", "label": "概述", "group": "基础"},
    {"key": "epidemiology", "label": "流行病学", "group": "基础"},
    {"key": "etiology", "label": "病因与危险因素", "group": "基础"},
    {"key": "pathophysiology", "label": "病理生理", "group": "基础"},
    {"key": "pathology_subtypes", "label": "病理分型与分子分型", "group": "病理"},
    {"key": "symptoms_early", "label": "早期症状", "group": "临床表现"},
    {"key": "symptoms_late", "label": "晚期症状", "group": "临床表现"},
    {"key": "signs", "label": "体征", "group": "临床表现"},
    {"key": "workup", "label": "检查与评估", "group": "诊断"},
    {"key": "diagnosis", "label": "诊断", "group": "诊断"},
    {"key": "differential", "label": "鉴别诊断", "group": "诊断"},
    {"key": "staging", "label": "分期", "group": "诊断"},
    {"key": "treatment", "label": "治疗", "group": "治疗"},
    {"key": "complications", "label": "并发症", "group": "治疗"},
    {"key": "prognosis", "label": "预后", "group": "随访与预防"},
    {"key": "followup", "label": "随访", "group": "随访与预防"},
    {"key": "prevention", "label": "预防", "group": "随访与预防"},
    {"key": "screening", "label": "筛查", "group": "随访与预防"},
    {"key": "patient_education", "label": "患者教育", "group": "患者关怀"},
    {"key": "care_seeking", "label": "就医指引", "group": "患者关怀"},
]

# 收录类别中文标签（DiseaseCategory，§5.7.3）
CATEGORY_LABELS: Dict[str, str] = {
    DiseaseCategory.PRIMARY_CANCER.value: "原发恶性肿瘤",
    DiseaseCategory.PRECANCEROUS_LESION.value: "癌前病变",
    DiseaseCategory.BORDERLINE_BENIGN_TUMOR.value: "交界性/良性肿瘤",
    DiseaseCategory.TUMOR_COMPLICATION.value: "肿瘤并发症/相关疾病",
}

# 详情页免责声明（专业版 / 患者版）
DISCLAIMER_PRO = "本内容基于指南与共识整理，仅供临床参考，不替代诊疗决策。"
DISCLAIMER_PATIENT = "本内容仅供参考，不构成诊断，具体请遵医嘱。"

# 症状反查时的分隔符（支持中英文顿号/逗号/分号/空格）
_SYMPTOM_SPLIT_RE = re.compile(r"[、,，;；/\s]+")


class DiseaseService:
    """疾病知识库检索 / 浏览 / 详情。"""

    def __init__(self, repo: Optional[ElasticsearchRepository] = None):
        self.repo = repo or ElasticsearchRepository()

    # ---------- 名称归一 ----------
    @staticmethod
    def _normalize_name(name: str) -> str:
        """名称归一：优先癌种别名表，其次症状别名表，均未命中则原样返回。

        A5 术语字典到位后，此处可切换为按字典 canonical 归一。
        """
        name = (name or "").strip()
        if not name:
            return ""
        for etype in ("Cancer", "Symptom", "Examination"):
            _, canonical = EntityDisambiguationService.resolve(name, etype)
            if canonical and canonical != name:
                return canonical
        return name

    # ---------- 搜索 ----------
    def search(self, query: str, mode: str = "name", size: int = 20) -> Dict:
        """疾病检索。

        mode=name：名称归一检索（名称/别名/拼音/英文/概述多路匹配）；
        mode=symptom：症状反查（按症状做 OR 匹配，命中越多越靠前）。
        """
        query = (query or "").strip()
        degraded = self.repo.count_diseases() == 0
        if not query:
            return {"mode": mode, "query": query, "normalized": "", "total": 0,
                    "items": [], "degraded": degraded,
                    "note": "" if not degraded else self._empty_note()}

        if mode == "symptom":
            terms = [t for t in _SYMPTOM_SPLIT_RE.split(query) if t]
            hits = self.repo.search_diseases_by_symptom(terms, size=size)
            note = "" if hits else self._no_hit_note(degraded)
            return {"mode": mode, "query": query, "normalized": terms,
                    "total": len(hits), "items": [self._to_card(h) for h in hits],
                    "degraded": degraded, "note": note}

        normalized = self._normalize_name(query)
        hits = self.repo.search_diseases_by_name(query, size=size)
        if not hits and normalized and normalized != query:
            hits = self.repo.search_diseases_by_name(normalized, size=size)
        note = "" if hits else self._no_hit_note(degraded)
        return {"mode": "name", "query": query, "normalized": normalized,
                "total": len(hits), "items": [self._to_card(h) for h in hits],
                "degraded": degraded, "note": note}

    # ---------- 详情 ----------
    def get(self, disease_id: str, version: str = "pro") -> Optional[Dict]:
        """取疾病详情（version=pro 专业版 / patient 患者版），返回 None 表示不存在。"""
        profile = self.repo.get_disease_profile(disease_id)
        if not profile:
            return None
        version = "patient" if version == "patient" else "pro"
        raw_sections = profile.get("patient_version" if version == "patient" else "sections") or {}

        # 按 SECTION_ORDER 排序并只保留有内容的 section（缺项不计入，保持整洁）
        sections: List[Dict] = []
        for item in SECTION_ORDER:
            text = raw_sections.get(item["key"])
            if text is None:
                continue
            if not isinstance(text, str):
                text = str(text)
            text = text.strip()
            if not text:
                continue
            sections.append({"key": item["key"], "label": item["label"],
                             "group": item["group"], "text": text})

        return {
            "disease_id": profile.get("disease_id", disease_id),
            "name_canonical": profile.get("name_canonical", ""),
            "name_en": profile.get("name_en", ""),
            "synonyms": profile.get("synonyms") or [],
            "pinyin": profile.get("pinyin", ""),
            "icd10": profile.get("icd10", ""),
            "icd_o3": profile.get("icd_o3", ""),
            "category": profile.get("category", ""),
            "category_label": CATEGORY_LABELS.get(profile.get("category", ""), ""),
            "cancer_type": profile.get("cancer_type", ""),
            "departments": profile.get("departments") or [],
            "version": version,
            "sections": sections,
            "links": profile.get("links") or {},
            "section_gaps": profile.get("section_gaps") or [],
            "sources": profile.get("sources") or [],
            "disclaimer": DISCLAIMER_PATIENT if version == "patient" else DISCLAIMER_PRO,
        }

    # ---------- 分类浏览 ----------
    def browse(self, category: Optional[str] = None, cancer_type: Optional[str] = None,
               size: int = 200) -> Dict:
        """分类浏览 / 分面计数。"""
        res = self.repo.list_diseases(category=category, cancer_type=cancer_type, size=size)
        degraded = self.repo.count_diseases() == 0
        return {
            "total": res["total"],
            "items": [self._to_card(h) for h in res["items"]],
            "facets": {
                "category": [{"value": k, "label": CATEGORY_LABELS.get(k, k), "count": v}
                             for k, v in res["facets"].get("category", {}).items()],
                "cancer_type": [{"value": k, "count": v}
                                for k, v in res["facets"].get("cancer_type", {}).items()],
            },
            "degraded": degraded,
            "note": "" if not degraded else self._empty_note(),
        }

    # ---------- 内部 ----------
    @staticmethod
    def _to_card(hit: Dict) -> Dict:
        """检索命中 → 列表卡片展示子集。"""
        return {
            "disease_id": hit.get("disease_id", ""),
            "name_canonical": hit.get("name_canonical", ""),
            "name_en": hit.get("name_en", ""),
            "category": hit.get("category", ""),
            "category_label": CATEGORY_LABELS.get(hit.get("category", ""), ""),
            "cancer_type": hit.get("cancer_type", ""),
            "departments": hit.get("departments") or [],
            "overview": (hit.get("overview_text") or "")[:200],
            "symptoms": (hit.get("symptoms") or [])[:10],
            "score": hit.get("_score"),
        }

    @staticmethod
    def _empty_note() -> str:
        return "疾病知识库数据未就绪（medical_disease_profiles 尚无数据，A3 疾病档案待入库）。"

    @staticmethod
    def _no_hit_note(degraded: bool) -> str:
        if degraded:
            return DiseaseService._empty_note()
        return "未找到匹配的疾病。本库仅收录肿瘤相关疾病；如为其他健康问题，请咨询全科或相应专科医生。"
