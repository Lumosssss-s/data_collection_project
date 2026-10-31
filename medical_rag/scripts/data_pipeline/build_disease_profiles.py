"""A3 疾病档案（方案 1：零 token 规则拼装，8 个 profile）。

数据来源：
  1. 指南推荐条目（1,513 条 REC，含章节路径与溯源）—— 筛查/检查/诊断/分期/
     病理分型/治疗/并发症/随访/流行病学 等节；
  2. 药品说明书（27 份）—— treatment 节的药物清单；
  3. kgdrug 子图（2018 科普库）—— overview / etiology / prevention / 症状，
     文本前统一标注低可信来源，仅供补缺。

契约约束（《医疗数据需求清单》A3 §⑥）：
  - 14 组 section 全部建键（本脚本按代码 SECTION_ORDER 的 20 个键落位）；
  - 无内容时写 null，并在 section_gaps 写明原因；
  - patient_version 与 sections 同构（方案 1 不生成通俗版，全部 null + 缺口说明）；
  - 全部 review 状态为 draft，sources 记录实际引用。

用法（宿主机）：
  python scripts/data_pipeline/build_disease_profiles.py
输出：
  data/clean/disease_profiles/<disease_id>.json（每条一个文件）
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REC_DIR = os.path.join(BASE_DIR, "data", "clean", "recommendations")
DRUG_DIR = os.path.join(BASE_DIR, "data", "clean", "drug_labels")
OUT_DIR = os.path.join(BASE_DIR, "data", "clean", "disease_profiles")
KGD = r"e:/兴智杯/kg/kgdrug/kg_cancer_subgraph.json"

SECTION_KEYS = ["overview", "epidemiology", "etiology", "pathophysiology",
                "pathology_subtypes", "symptoms_early", "symptoms_late", "signs",
                "workup", "diagnosis", "differential", "staging", "treatment",
                "complications", "prognosis", "followup", "prevention", "screening",
                "patient_education", "care_seeking"]

# 疾病定义：id、名称、ICD、所属癌种、名称过滤词（用于从该癌种条目中挑出本疾病的）
DISEASES: List[Dict] = [
    {"disease_id": "DIS-LUNG-001", "name_canonical": "肺癌", "name_en": "Lung cancer",
     "synonyms": ["肺恶性肿瘤", "支气管肺癌", "lung cancer", "NSCLC"],
     "icd10": "C34.9", "icd_o3": "M8010/3", "category": "primary_cancer",
     "cancer_type": "lung", "body_system": "呼吸系统", "pinyin": "feiai",
     "departments": ["肿瘤内科", "胸外科", "呼吸内科"],
     "match": ["lung", "nsclc", "non-small cell"]},
    {"disease_id": "DIS-LUNG-002", "name_canonical": "非小细胞肺癌", "name_en": "Non-small cell lung cancer",
     "synonyms": ["NSCLC", "非小细胞肺癌", "肺腺癌", "肺鳞癌"],
     "icd10": "C34.9", "icd_o3": "M8046/3", "category": "primary_cancer",
     "cancer_type": "lung", "body_system": "呼吸系统", "pinyin": "feixiaoxibaofeiai",
     "departments": ["肿瘤内科", "胸外科"],
     "match": ["nsclc", "non-small cell", "adenocarcinoma", "squamous"]},
    {"disease_id": "DIS-COLORECTAL-001", "name_canonical": "结直肠癌", "name_en": "Colorectal cancer",
     "synonyms": ["大肠癌", "colorectal cancer", "CRC"],
     "icd10": "C18.9", "icd_o3": "M8010/3", "category": "primary_cancer",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "jiezhichangai",
     "departments": ["肿瘤内科", "胃肠外科", "消化内科"],
     "match": ["colorectal", "colon", "rectal"]},
    {"disease_id": "DIS-COLORECTAL-002", "name_canonical": "结肠癌", "name_en": "Colon cancer",
     "synonyms": ["结肠恶性肿瘤", "colon cancer"],
     "icd10": "C18.9", "icd_o3": "M8140/3", "category": "primary_cancer",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "jiechangai",
     "departments": ["肿瘤内科", "胃肠外科"],
     "match": ["colon"]},
    {"disease_id": "DIS-COLORECTAL-003", "name_canonical": "直肠癌", "name_en": "Rectal cancer",
     "synonyms": ["直肠恶性肿瘤", "rectal cancer"],
     "icd10": "C20", "icd_o3": "M8140/3", "category": "primary_cancer",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "zhichangai",
     "departments": ["肿瘤内科", "胃肠外科"],
     "match": ["rectal"]},
    {"disease_id": "DIS-COLORECTAL-004", "name_canonical": "乙状结肠癌", "name_en": "Sigmoid colon cancer",
     "synonyms": ["乙状结肠恶性肿瘤"],
     "icd10": "C18.7", "icd_o3": "M8140/3", "category": "primary_cancer",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "yizhuangjiechangai",
     "departments": ["肿瘤内科", "胃肠外科"],
     "match": ["sigmoid"]},
    {"disease_id": "DIS-COLORECTAL-005", "name_canonical": "肛管癌", "name_en": "Anal canal cancer",
     "synonyms": ["肛门癌", "anal cancer"],
     "icd10": "C21.1", "icd_o3": "M8070/3", "category": "primary_cancer",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "angguanai",
     "departments": ["肿瘤内科", "胃肠外科", "放疗科"],
     "match": ["anal", "肛管"]},
    {"disease_id": "DIS-COLORECTAL-006", "name_canonical": "结直肠腺瘤性息肉", "name_en": "Colorectal adenomatous polyp",
     "synonyms": ["腺瘤性息肉", "结直肠腺瘤", "adenomatous polyp"],
     "icd10": "D12.6", "icd_o3": "M8140/0", "category": "precancerous_lesion",
     "cancer_type": "colorectal", "body_system": "消化系统", "pinyin": "jiezhichangxianliu",
     "departments": ["消化内科", "胃肠外科"],
     "match": ["adenoma", "polyp", "息肉"]},
]

# section -> 关键词（在 breadcrumb + 正文中命中即归入该节）
SECTION_RULES: Dict[str, List[str]] = {
    "screening": ["screening", "low-dose ct", "ldct", "nodule"],
    "workup": ["workup", "diagnostic", "biopsy", "pathologic review", "endoscop",
               "colonoscopy", "imaging", "ct scan", "mri"],
    "diagnosis": ["diagnosis", "diagnostic criteria", "pathologic diagnosis", "workup"],
    "staging": ["pstage", "stage i", "stage ii", "stage iii", "stage iv", "tnm", "ajcc"],
    "pathology_subtypes": ["adenocarcinoma", "squamous", "subtype", "histolog", "msi",
                           "dmmr", "egfr", "alk", "kras"],
    "treatment": ["adjuvant", "neoadjuvant", "chemotherapy", "surgery", "resection",
                  "radiotherapy", "targeted", "immunotherapy", "folfox", "folfiri",
                  "oxaliplatin", "capecitabine", "conversion"],
    "complications": ["complication", "adverse", "toxicity", "pneumonitis", "obstruction",
                      "perforation", "anastomotic"],
    "followup": ["follow-up", "surveillance", "monitor"],
    "epidemiology": ["incidence", "epidemiolog", "prevalence"],
    "prevention": ["prevention", "smoking cessation", "risk factor", "chemoprevention"],
    "prognosis": ["prognos", "survival", "recurrence"],
}

MAX_RECS_PER_SECTION = 4
EXCERPT_LEN = 200


def _load_recs() -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for name in sorted(os.listdir(REC_DIR)):
        if not name.endswith("_recs.json"):
            continue
        out[name] = json.load(open(os.path.join(REC_DIR, name), encoding="utf-8"))
    return out


def _load_drugs() -> List[Dict]:
    out = []
    for name in sorted(os.listdir(DRUG_DIR)):
        if name.endswith(".json"):
            out.extend(json.load(open(os.path.join(DRUG_DIR, name), encoding="utf-8")))
    return out


def _load_kg() -> List[Dict]:
    try:
        return json.load(open(KGD, encoding="utf-8"))
    except Exception:
        return []


def _kg_text(kg: List[Dict], names: List[str], relation: str) -> Optional[str]:
    """从 kgdrug 取某疾病的文本属性（概述/病因/预防）。"""
    for rel in kg:
        if rel.get("relation") != relation:
            continue
        if (rel.get("head") or {}).get("name") in names:
            text = (rel.get("tail") or {}).get("text")
            if text:
                return text[:900]
    return None


def _kg_symptoms(kg: List[Dict], names: List[str]) -> List[str]:
    out: List[str] = []
    for rel in kg:
        if rel.get("relation") != "has_symptom":
            continue
        if (rel.get("head") or {}).get("name") in names:
            sym = (rel.get("tail") or {}).get("name")
            if sym and sym not in out:
                out.append(sym)
    return out


def _match_disease(rec: Dict, disease: Dict) -> bool:
    """疾病归属判定：英文关键词按词边界匹配，避免 anal 命中 analysis 这类误伤。"""
    text = ((rec.get("breadcrumb") or "") + " " + (rec.get("recommendation_text") or "")).lower()
    for kw in disease["match"]:
        k = kw.lower()
        if k.isascii():
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", text):
                return True
        elif k in text:
            return True
    return False


# 章节 → 优先使用的 scenario 集合（REC 已完成 scenario 标注，比关键词更可靠）
SECTION_SCENARIOS: Dict[str, set] = {
    "screening": {"screening"},
    "workup": {"diagnosis"},
    "diagnosis": {"diagnosis"},
    "staging": {"staging"},
    "treatment": {"treatment_neoadjuvant", "treatment_adjuvant", "treatment_first_line",
                  "treatment_second_line", "treatment_later", "surgery",
                  "radiotherapy", "targeted", "immunotherapy"},
    "followup": {"followup"},
    "complications": {"supportive_care"},
    "prevention": {"screening"},
    "epidemiology": set(),
    "pathology_subtypes": set(),
    "prognosis": set(),
}


# 章节 → breadcrumb 必须命中的词（章节路径最能代表官方主题，优先级高于正文关键词）
SECTION_BREADCRUMB: Dict[str, List[str]] = {
    "screening": ["screening", "low-dose", "nodule"],
    "workup": ["diagnos", "workup", "patholog", "staging", "imaging"],
    "diagnosis": ["diagnos", "workup", "patholog"],
    "staging": ["staging", "stage"],
    # 不收录 "recommendation"：几乎所有章节都带该词，会把围手术期条目误归到治疗节
    "treatment": ["treatment", "therapy", "surgery", "resection",
                  "chemotherapy", "radiotherapy"],
    "complications": ["complication", "adverse", "toxic"],
    "followup": ["follow"],
    "epidemiology": ["incidence", "epidemiolog"],
    "prevention": ["prevention", "screening", "smoking"],
}


def _pick_recs(recs: List[Dict], disease: Dict, section: str) -> List[Dict]:
    """章节归属：breadcrumb 命中优先 → scenario 次之 → 正文关键词兜底。"""
    scenarios = SECTION_SCENARIOS.get(section) or set()
    breadcrumb_kws = SECTION_BREADCRUMB.get(section) or []
    kws = SECTION_RULES.get(section, [])
    pool: List[Dict] = []
    for rec in recs:
        if rec.get("cancer_type") != disease["cancer_type"] or not _match_disease(rec, disease):
            continue
        bc = (rec.get("breadcrumb") or "").lower()
        text = (bc + " " + (rec.get("recommendation_text") or "")).lower()
        if breadcrumb_kws:
            if any(k in bc for k in breadcrumb_kws):
                pool.append(rec)
            continue
        if scenarios and rec.get("scenario") in scenarios:
            pool.append(rec)
        elif kws and any(k in text for k in kws):
            pool.append(rec)
    # 优先带证据等级的条目，其次按原文长度（信息量）降序
    pool.sort(key=lambda r: (bool(r.get("evidence_level")), len(r.get("recommendation_text") or "")),
              reverse=True)
    return pool[:MAX_RECS_PER_SECTION]


def _render_section(picked: List[Dict], intro: str) -> Optional[str]:
    if not picked:
        return None
    parts = [intro]
    for rec in picked:
        excerpt = (rec.get("recommendation_text") or "").strip()[:EXCERPT_LEN]
        parts.append(f"· {excerpt}【来源 {rec['rec_id']}】")
    return "\n".join(parts)


def build_profile(disease: Dict, recs: List[Dict], drugs: List[Dict],
                  kg: List[Dict]) -> Dict:
    sections: Dict[str, Optional[str]] = {k: None for k in SECTION_KEYS}
    gaps: List[str] = []
    sources: List[str] = []
    kg_names = [disease["name_canonical"], disease["name_en"], *disease["synonyms"]]

    # 1) 指南类 section
    for sec in ("screening", "workup", "diagnosis", "staging", "pathology_subtypes",
                "treatment", "complications", "followup", "epidemiology", "prognosis"):
        picked = _pick_recs(recs, disease, sec)
        text = _render_section(picked, f"本节整理自 {len(picked)} 条指南推荐条目：")
        if text:
            sections[sec] = text
            sources.extend(f"REC:{r['rec_id']}" for r in picked)

    # 2) 治疗节补充可用药物（FDA 说明书）
    drug_names = []
    for drug in drugs:
        cts = drug.get("cancer_type")
        cts = cts if isinstance(cts, list) else [cts]
        if disease["cancer_type"] in cts:
            drug_names.append(drug.get("generic_name") or drug.get("drug_id"))
    if drug_names:
        line = "可及药物（FDA 说明书，详见 A4）：" + "、".join(sorted(set(drug_names)))
        sections["treatment"] = ((sections["treatment"] or "") + "\n" + line).strip()
        sources.append("A4:drug_labels")

    # 3) kgdrug 补缺（低可信，显式标注）
    kg_overview = _kg_text(kg, kg_names, "overview")
    kg_etiology = _kg_text(kg, kg_names, "cause")
    kg_prevention = _kg_text(kg, kg_names, "prevention")
    kg_compl = _kg_text(kg, kg_names, "complication")
    kg_symptoms = _kg_symptoms(kg, kg_names)
    if kg_overview and not sections["overview"]:
        sections["overview"] = "（来源：kgdrug 2018 科普库，未经医学审核，仅供参考）\n" + kg_overview
        sources.append("kgdrug")
    if kg_etiology and not sections["etiology"]:
        sections["etiology"] = "（来源：kgdrug 2018 科普库，未经医学审核，仅供参考）\n" + kg_etiology
        sources.append("kgdrug")
    if kg_prevention and not sections["prevention"]:
        sections["prevention"] = "（来源：kgdrug 2018 科普库，未经医学审核，仅供参考）\n" + kg_prevention
        sources.append("kgdrug")
    if kg_compl and not sections["complications"]:
        sections["complications"] = "（来源：kgdrug 2018 科普库，未经医学审核，仅供参考）\n" + kg_compl
        sources.append("kgdrug")
    if kg_symptoms and not sections["symptoms_early"]:
        sections["symptoms_early"] = "常见症状（kgdrug 2018 科普库）：" + "、".join(kg_symptoms)
        sources.append("kgdrug")

    # 4) 缺口清单
    for key in SECTION_KEYS:
        if not sections[key]:
            reason = ("患者版待 LLM 通俗化" if False else "无可靠来源（指南/说明书未覆盖）")
            gaps.append(f"{key}: {reason}")

    # 5) 抽平字段
    pathology = []
    for token, zh in (("adenocarcinoma", "腺癌"), ("squamous", "鳞癌"),
                      ("MSI", "MSI-H/dMMR"), ("EGFR", "EGFR 突变"),
                      ("ALK", "ALK 融合"), ("KRAS", "KRAS 突变")):
        for rec in recs:
            if rec.get("cancer_type") != disease["cancer_type"]:
                continue
            if token.lower() in ((rec.get("recommendation_text") or "").lower()):
                if zh not in pathology:
                    pathology.append(zh)
                break

    stages = sorted({m.group(0).upper() for rec in recs
                     if rec.get("cancer_type") == disease["cancer_type"]
                     for m in re.finditer(r"(?:pstage\s*)?(?:stage\s*)?(I{1,3}V?|IV)\b",
                                          (rec.get("recommendation_text") or ""), re.IGNORECASE)
                     if m.group(0).upper().startswith(("II", "III", "IV", "I"))})[:6]

    treatment_methods = []
    for token, zh in (("surgery", "手术"), ("resection", "手术切除"),
                      ("chemotherapy", "化疗"), ("radiotherapy", "放疗"),
                      ("targeted", "靶向治疗"), ("immunotherapy", "免疫治疗"),
                      ("chemoradiotherapy", "放化疗")):
        for rec in recs:
            if rec.get("cancer_type") != disease["cancer_type"]:
                continue
            if token in ((rec.get("recommendation_text") or "").lower()):
                if zh not in treatment_methods:
                    treatment_methods.append(zh)
                break

    guideline_docs = sorted({rec["doc_id"] for rec in recs
                             if rec.get("cancer_type") == disease["cancer_type"]})

    treat_line = ""
    if sections["treatment"]:
        lines = sections["treatment"].split("\n")
        treat_line = (lines[1] if len(lines) > 1 else lines[0])[:200]
    overview_text = " ".join(filter(None, [
        disease["name_canonical"], disease["name_en"],
        (sections["overview"] or "").split("\n")[-1][:300],
        treat_line,
    ]))

    return {
        "disease_id": disease["disease_id"],
        "name_canonical": disease["name_canonical"],
        "synonyms": disease["synonyms"],
        "name_en": disease["name_en"],
        "pinyin": disease["pinyin"],
        "icd10": disease["icd10"],
        "icd_o3": disease["icd_o3"],
        "category": disease["category"],
        "body_system": disease["body_system"],
        "departments": disease["departments"],
        "department": disease["departments"],
        "cancer_type": disease["cancer_type"],
        "sections": sections,
        "patient_version": {k: None for k in SECTION_KEYS},
        "section_gaps": gaps,
        "links": {
            "symptoms": kg_symptoms,
            "drugs": sorted(set(drug_names)),
            "checks": [],
            "diseases": [],
            "guidelines": guideline_docs,
            "genes": [p for p in pathology if p.isupper() or "突变" in p or "融合" in p],
            "biomarkers": pathology,
        },
        "symptom_early": kg_symptoms[:12],
        "symptom_late": [],
        "signs": [],
        "pathology_subtypes": pathology,
        "stages": stages,
        "treatment_methods": treatment_methods,
        "overview_text": overview_text[:1200],
        "sources": sorted(set(sources)),
        "profile_version": "2026.10-draft",
        "last_updated": "2026-10-27",
    }


def main() -> None:
    recs = [r for recs_ in _load_recs().values() for r in recs_]
    drugs = _load_drugs()
    kg = _load_kg()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"{'疾病':<16}{'已填/20':>8}{'指南条目':>10}{'药品':>6}")
    print("-" * 44)
    for disease in DISEASES:
        profile = build_profile(disease, recs, drugs, kg)
        filled = sum(1 for k in SECTION_KEYS if profile["sections"].get(k))
        guides = len([s for s in profile["sources"] if s.startswith("REC:")])
        with open(os.path.join(OUT_DIR, f"{disease['disease_id']}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=1)
        print(f"{disease['name_canonical']:<16}{filled:>6}/20{guides:>10}{len(profile['links']['drugs']):>6}")

    print(f"\n输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()
