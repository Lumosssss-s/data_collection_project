# -*- coding: utf-8 -*-
"""tools/22_a3_disease_profile.py

A3 疾病档案生成（批次一 · 肺癌试点）。

输入：raw/guidelines/lung/nhc2022_01_lung.pdf
参考：data/clean/terminology/terminology_cancer.json（canonical / icd10 / icd_o3）
输出：data/clean/disease_profiles/disease_profiles_lung_20261028.json（顶层数组）
审计：cache/disease_profiles/a3_extract_audit.json

方法：按「一、」/「（一）」重建章节 → 按 section 关键词规则聚合原文 → 生成 1 个主体
profile（肺恶性肿瘤）+ 若干亚型 profile。20 个 section 键全部存在，缺内容写 null 并
在 section_gaps[] 登记原因；专业版为原文摘录，患者版因规则脚本无法可靠通俗改写而留 null。

口径与限制：
  - 不做 LLM 改写，不编造原文没有的内容；frequency 无法判定时写 null 并登记 gap。
  - staging 不填单值（同一疾病跨多个期别），留 null + gap。
  - links 内实体名优先取 A5 canonical，取不到时不写入。
"""
import argparse
import json
import os
import re
import sys

try:
    import fitz
except ImportError:
    sys.exit("缺少 PyMuPDF：pip install pymupdf")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(BASE, "raw", "guidelines", "lung", "nhc2022_01_lung.pdf")
TERM = os.path.join(BASE, "data", "clean", "terminology", "terminology_cancer.json")
DRUGS = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")
OUT_DIR = os.path.join(BASE, "data", "clean", "disease_profiles")
OUT = os.path.join(OUT_DIR, "disease_profiles_lung_20261028_v2.json")
AUDIT = os.path.join(BASE, "cache", "disease_profiles", "a3_extract_audit.json")

DOC_ID = "DOC-LUNG-NHC-001"
SOURCE_NAME = "原发性肺癌诊疗指南（2022年版）"
SOURCE_NOTE = "国家卫健委 国卫办医函〔2022〕104号"
SOURCE_FILE = "nhc2022_01_lung.pdf"
UPDATED_AT = "2026-10-28"

L1_RE = re.compile(r"^([一二三四五六七八九十]+)、\s*(.+)$")
L2_RE = re.compile(r"^（([一二三四五六七八九十]+)）\s*(.+)$")
DROP_RE = re.compile(r"^(\d{1,3}|第\s*\d+\s*页|[—\-]?\s*\d+\s*[—\-]?)$")

SECTION_KEYS = [
    "overview", "epidemiology", "etiology", "pathophysiology", "pathology_subtypes",
    "symptoms_early", "symptoms_late", "signs", "workup", "diagnosis",
    "differential", "staging", "treatment", "complications", "prognosis",
    "followup", "prevention", "screening", "patient_education", "care_seeking",
]

STAGE_RE = re.compile(r"(Ⅰ|Ⅱ|Ⅲ|Ⅳ)[A-C]?期|\b(I|II|III|IV)[A-C]?\s*期")
BIOMARKER_RE = re.compile(
    r"(?<![A-Za-z-])(EGFR|ALK|ROS1|KRAS|NRAS|HRAS|BRAF|HER2|BRCA|MSI-H|dMMR|"
    r"PD-L1|TMB|HRD|NTRK|RET|MET|EBV)(?![A-Za-z])"
)

SUBTYPE_NAMES = [
    "非小细胞肺癌", "小细胞肺癌", "肺腺癌", "肺鳞状细胞癌", "大细胞癌",
    "腺鳞癌", "肉瘤样癌", "神经内分泌癌", "类癌", "微浸润性腺癌",
    "原位腺癌", "非典型腺瘤样增生",
]
SUBTYPE_PROFILES = ["非小细胞肺癌", "小细胞肺癌", "肺腺癌", "肺鳞状细胞癌", "微浸润性腺癌"]
# 指南正文常用简称（「腺癌」而非「肺腺癌」），别名用于亚型描述句匹配
SUBTYPE_ALIASES = {
    "非小细胞肺癌": ("非小细胞肺癌", "NSCLC"),
    "小细胞肺癌": ("小细胞肺癌", "小细胞癌", "SCLC"),
    "肺腺癌": ("肺腺癌", "腺癌"),
    "肺鳞状细胞癌": ("肺鳞状细胞癌", "肺鳞癌", "鳞癌", "鳞状细胞癌"),
    "微浸润性腺癌": ("微浸润性腺癌", "MIA"),
}
# 亚型 overview 必须是描述句，纯罗列/表格碎片不算
DESC_CUE = ("占", "是", "为", "多见", "常见", "少见", "罕见", "典型", "特点",
            "包括", "起源于", "来源于", "近年", "表现", "好发", "预后", "定义")
# 治疗/检查类句子属 A2 场景，不作为亚型画像首段
SUBTYPE_NOISE = ("活检", "检测", "推荐", "治疗", "化疗", "放疗", "手术")

SYMPTOM_DEFS = [
    ("咳嗽", ("咳嗽",)),
    ("咯血", ("咯血", "痰中带血")),
    ("胸痛", ("胸痛",)),
    ("发热", ("发热",)),
    ("气促", ("气促", "呼吸困难", "胸闷")),
    ("声音嘶哑", ("声音嘶哑", "声嘶")),
    ("吞咽困难", ("吞咽困难",)),
    ("上腔静脉阻塞综合征", ("上腔静脉",)),
    ("Horner综合征", ("霍纳", "Horner")),
    ("Pancoast综合征", ("Pancoast",)),
    ("杵状指", ("杵状指",)),
    ("消瘦", ("消瘦", "体重下降")),
    ("恶性胸腔积液", ("胸腔积液",)),
    ("骨痛", ("骨痛", "骨转移")),
    ("头痛", ("头痛",)),
]

CHECK_NAMES = [
    "胸部低剂量CT", "胸部CT", "MRI", "PET-CT", "支气管镜", "纵隔镜",
    "胸腔镜", "痰脱落细胞学检查", "骨核素扫描",
]


def join_lines(lines):
    out = ""
    for ln in lines:
        if not out:
            out = ln
            continue
        if re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", ln):
            out += " " + ln
        else:
            out += ln
    return out


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。！？])", text) if s.strip()]


def parse_blocks(path):
    doc = fitz.open(path)
    blocks, cur = [], None
    for pno, page in enumerate(doc, 1):
        for raw in page.get_text().splitlines():
            line = raw.strip()
            if not line or DROP_RE.match(line):
                continue
            if L1_RE.match(line):
                cur = {"l1": line.rstrip("。．."), "l2": None, "page": pno, "lines": []}
                blocks.append(cur)
                continue
            if L2_RE.match(line):
                cur = {"l1": (cur or {}).get("l1", ""), "l2": line.rstrip("。．."),
                       "page": pno, "lines": []}
                blocks.append(cur)
                continue
            if cur is None:
                cur = {"l1": "", "l2": None, "page": pno, "lines": []}
                blocks.append(cur)
            cur["lines"].append(line)
    return blocks


def block_sentences(blocks, l1_kw=None, l2_kw=None):
    res = []
    for b in blocks:
        if l1_kw and l1_kw not in b["l1"]:
            continue
        if l2_kw and l2_kw not in (b["l2"] or ""):
            continue
        res.extend(split_sentences(join_lines(b["lines"])))
    return res


def all_sentences(blocks):
    out = []
    for b in blocks:
        out.extend(split_sentences(join_lines(b["lines"])))
    return out


def pick(sentences, contains=None, exclude=None, limit=6, cap=820):
    got = []
    for s in sentences:
        if contains and not any(k in s for k in contains):
            continue
        if exclude and any(k in s for k in exclude):
            continue
        got.append(s)
        if len(got) >= limit:
            break
    text = "".join(got)
    return text[:cap] if text else None


def symptom_entries(sentences):
    entries, seen = [], set()
    for s in sentences:
        stype = "early"
        if any(k in s for k in ("转移", "侵犯", "压迫", "上腔静脉", "脊髓")):
            stype = "late"
        if any(k in s for k in ("肺外", "副肿瘤", "杵状指", "内分泌")):
            stype = "sign"
        freq = None
        if "常见" in s or "多见" in s:
            freq = "common"
        elif "少见" in s:
            freq = "uncommon"
        elif "罕见" in s:
            freq = "rare"
        for name, kws in SYMPTOM_DEFS:
            if name in seen:
                continue
            if any(k in s for k in kws):
                seen.add(name)
                entries.append({"name": name, "type": stype, "frequency": freq})
    return entries or None


def is_table_fragment(s):
    """WHO 组织学分型表被 PDF 挤成一条无标点长串，密集罗列亚型名，不可作描述句。"""
    if len(s) > 200 and s.count("，") < 3:
        return True
    return sum(1 for n in SUBTYPE_NAMES if n in s) >= 3


def subtype_overview(name, desc_sents):
    """亚型描述句择优：占比陈述 > 定义 > 一般描述 > 列举；列举型不作首句。

    命中不到专属句时，退一步用「两大类」分类总定义句（NSCLC/SCLC 共用）。
    """
    aliases = SUBTYPE_ALIASES.get(name, (name,))
    others = [n for n in SUBTYPE_NAMES if n != name]

    def foreign(s):
        """含其他亚型名、MIA/AIS 专指或治疗检查类表述 → 非本亚型画像句。"""
        if any(o in s for o in others):
            return True
        if any(k in s for k in SUBTYPE_NOISE):
            return True
        return name not in ("微浸润性腺癌", "原位腺癌") and ("MIA" in s or "AIS" in s)

    def rank(s):
        if "%" in s and "占" in s:
            return 0
        if "定义" in s:
            return 1
        if "包括" in s:
            return 3
        return 2

    cands = [s for s in desc_sents
             if len(s) <= 300 and any(a in s[:20] for a in aliases)
             and any(k in s for k in DESC_CUE) and not foreign(s)]
    cands.sort(key=rank)
    got = []
    for s in cands:
        if got and foreign(s):
            continue
        got.append(s)
        if len(got) >= 2:
            break
    if not got:
        for s in desc_sents:
            if ("两大类" in s or "可以分为" in s) and any(a in s for a in aliases):
                got.append(s)
                break
    text = "".join(got)
    return text[:300] if text else None


def genes_in(text):
    found = []
    for m in BIOMARKER_RE.finditer(text or ""):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def icd10_who(code):
    """国家临床版 5 位扩展码 → WHO 4 位码（如 C34.901 → C34.9）。"""
    if not code:
        return None
    m = re.match(r"^([A-Z]\d{2}\.\d)", str(code))
    return m.group(1) if m else str(code)


def build_main(blocks, term_idx):
    sec = {k: None for k in SECTION_KEYS}
    gaps = []

    overview_sents = block_sentences(blocks, l1_kw="概述")
    sec["overview"] = pick(
        overview_sents,
        exclude=("发病率", "死亡率", "万例", "新发", "生存率", "构成比"),
        limit=3, cap=300)
    sec["epidemiology"] = pick(
        overview_sents, contains=("发病率", "死亡率", "万例", "新发", "年龄", "性别"),
        limit=5, cap=600)
    sec["etiology"] = pick(block_sentences(blocks, l2_kw="危险因素"), limit=6, cap=600)
    sec["pathophysiology"] = pick(
        all_sentences(blocks), contains=("机制", "通路", "驱动基因", "免疫逃逸"),
        limit=3, cap=600)

    pathology_sents = block_sentences(blocks, l2_kw="组织学分型")
    pathology_text = join_lines([l for b in blocks if b["l2"] and "组织学分型" in b["l2"]
                                 for l in b["lines"]])
    subtypes = []
    for name in SUBTYPE_NAMES:
        t = term_idx.get(name) or {}
        if name in pathology_text or t.get("icd_o3"):
            subtypes.append({"name": name, "icd_o3": t.get("icd_o3"), "frequency": None})
    sec["pathology_subtypes"] = subtypes or None

    symptom_sents = block_sentences(blocks, l2_kw="临床表现")
    entries = symptom_entries(symptom_sents) or []
    sec["symptoms_early"] = [e for e in entries if e["type"] == "early"] or None
    sec["symptoms_late"] = [e for e in entries if e["type"] == "late"] or None
    sign_entries = [e for e in entries if e["type"] == "sign"]
    sign_sents = block_sentences(blocks, l2_kw="体格检查")
    for e in symptom_entries(sign_sents) or []:
        if e["name"] not in [x["name"] for x in sign_entries]:
            e["type"] = "sign"
            sign_entries.append(e)
    sec["signs"] = sign_entries or None

    workup_sents = block_sentences(blocks, l2_kw="辅助检查") + \
        block_sentences(blocks, l2_kw="病理组织学检查")
    sec["workup"] = pick(workup_sents, limit=8, cap=820)
    sec["diagnosis"] = pick(
        workup_sents, contains=("诊断标准", "病理诊断", "免疫组化", "分子病理", "诊断依据"),
        limit=5, cap=620)
    sec["differential"] = pick(
        all_sentences(blocks), contains=("鉴别诊断", "鉴别"), limit=3, cap=420)

    treat_sents = []
    for kw in ("外科治疗", "放射治疗", "药物治疗", "分期治疗模式", "姑息治疗"):
        treat_sents.extend(pick(block_sentences(blocks, l2_kw=kw), limit=2, cap=600) or "")
    sec["treatment"] = (treat_sents and "".join(treat_sents)[:900]) or None

    sec["complications"] = pick(
        all_sentences(blocks),
        contains=("并发症", "不良反应", "骨髓抑制", "放射性肺炎", "免疫相关"),
        limit=5, cap=620)
    sec["prognosis"] = pick(block_sentences(blocks, l1_kw="预后"), limit=4, cap=520)
    sec["followup"] = pick(block_sentences(blocks, l1_kw="随访"), limit=6, cap=620)
    sec["prevention"] = pick(
        block_sentences(blocks, l2_kw="高危人群的筛查"),
        contains=("筛查", "戒烟", "预防", "低剂量"), limit=4, cap=520)
    sec["screening"] = sec["prevention"]

    gap_reasons = {
        "pathophysiology": "指南未单列发病机制章节，规则抽取无可靠命中",
        "staging": "同一疾病跨多个期别，单值 AJCC8 分期不适用；待按 T/N/M 组合建分期映射表",
        "differential": "指南未设独立鉴别诊断章节，仅零散出现「鉴别诊断」表述",
        "patient_education": "指南无患者教育章节，待 CACA/CSCO 或科普来源补齐",
        "care_seeking": "指南无就诊指引章节，待补充",
    }
    for k in SECTION_KEYS:
        if sec[k] is None:
            gaps.append({"section": k, "reason": gap_reasons.get(
                k, "原文无对应内容，规则抽取未命中")})

    treatment_text = sec["treatment"] or ""
    full_text = "".join(all_sentences(blocks))
    drugs = []
    for d in load_json(DRUGS, []):
        name = d.get("generic_name")
        if name and name in full_text:
            drugs.append(name)
    # 检查项从完整 workup 原文匹配（sec["workup"] 已被 pick 截断，会漏掉后半段影像检查）
    workup_full = "".join(workup_sents)
    checks = [c for c in CHECK_NAMES if c in workup_full]
    genes = genes_in((sec["workup"] or "") + treatment_text + full_text)

    t = term_idx.get("肺恶性肿瘤") or {}
    profile = {
        "disease_id": "DIS-LUNG-0001",
        "name_canonical": "肺恶性肿瘤",
        "synonyms": (t.get("synonyms") or ["肺癌", "原发性支气管肺癌"]),
        "name_en": "Lung cancer",
        "icd10": icd10_who(t.get("icd10")),
        "icd_o3": t.get("icd_o3"),
        "category": "primary_cancer",
        "body_system": "呼吸系统",
        "department": ["肿瘤内科", "胸外科", "放疗科"],
        "sections": sec,
        "patient_version": None,
        "links": {
            "symptoms": [e["name"] for e in entries] or None,
            "drugs": drugs or None,
            "checks": checks or None,
            "diseases": None,
            "genes": genes or None,
            "biomarkers": None,
            "guidelines": [DOC_ID],
        },
        "section_gaps": gaps + [{
            "section": "patient_version",
            "reason": "患者版需 LLM/人工通俗改写（句均长≤40 字、术语括注），规则脚本不生成",
        }],
        "sources": [SOURCE_NAME, SOURCE_NOTE],
        "version": "v2",
        "last_updated": UPDATED_AT,
        "annotation": {
            "annotator": "rule-extract 22_a3_disease_profile.py",
            "date": UPDATED_AT,
            "status": "draft",
            "icd10_national": t.get("icd10"),
            "icd10_note": "主字段取 WHO 4 位码（§A3 规范）；国家临床版 5 位扩展码保留在本字段作来源记录",
        },
    }
    desc_pool = []
    for s in (pathology_sents + block_sentences(blocks, l1_kw="概述")
              + block_sentences(blocks, l2_kw="病理组织学检查")):
        if len(s) >= 8 and not is_table_fragment(s) and s not in desc_pool:
            desc_pool.append(s)
    return profile, desc_pool


def build_subtype(name, idx, blocks, term_idx, desc_sents):
    t = term_idx.get(name) or {}
    overview = subtype_overview(name, desc_sents)
    gaps = [{"section": k, "reason": "该亚型仅指南病理章节有片段描述，其余 section 待 A1 扩充后抽取"}
            for k in SECTION_KEYS if k not in ("overview", "pathology_subtypes")]
    if overview is None:
        gaps.append({"section": "overview", "reason": "指南未给出该亚型独立描述"})
    gaps.append({"section": "patient_version",
                 "reason": "患者版需 LLM/人工通俗改写，规则脚本不生成"})
    return {
        "disease_id": "DIS-LUNG-%04d" % idx,
        "name_canonical": name,
        "synonyms": t.get("synonyms"),
        "name_en": None,
        "icd10": icd10_who(t.get("icd10")),
        "icd_o3": t.get("icd_o3"),
        "category": "primary_cancer",
        "body_system": "呼吸系统",
        "department": ["肿瘤内科", "胸外科"],
        "sections": {k: (overview if k == "overview" else
                         ([{"name": name, "icd_o3": t.get("icd_o3"), "frequency": None}]
                          if k == "pathology_subtypes" else None))
                     for k in SECTION_KEYS},
        "patient_version": None,
        "links": {
            "symptoms": None, "drugs": None, "checks": None, "diseases": None,
            "genes": genes_in(overview) or None, "biomarkers": None,
            "guidelines": [DOC_ID],
        },
        "section_gaps": gaps,
        "sources": [SOURCE_NAME, SOURCE_NOTE],
        "version": "v2",
        "last_updated": UPDATED_AT,
        "annotation": {
            "annotator": "rule-extract 22_a3_disease_profile.py",
            "date": UPDATED_AT,
            "status": "draft",
            "icd10_national": t.get("icd10"),
            "icd10_note": "主字段取 WHO 4 位码（§A3 规范）；国家临床版 5 位扩展码保留在本字段作来源记录",
        },
    }


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(PDF):
        sys.exit("缺少输入 PDF：%s" % PDF)
    term = load_json(TERM, [])
    term_idx = {x.get("canonical"): x for x in term if x.get("canonical")}

    blocks = parse_blocks(PDF)
    main_profile, desc_sents = build_main(blocks, term_idx)
    profiles = [main_profile]
    for name in SUBTYPE_PROFILES:
        profiles.append(build_subtype(name, len(profiles) + 1, blocks, term_idx,
                                      desc_sents))

    filled = sum(1 for k in SECTION_KEYS if main_profile["sections"][k] is not None)
    audit = {
        "generated_at": UPDATED_AT,
        "input_pdf": os.path.relpath(PDF, BASE),
        "blocks": len(blocks),
        "profiles": len(profiles),
        "main_sections_filled": filled,
        "main_sections_total": len(SECTION_KEYS),
        "main_section_gaps": [g["section"] for g in main_profile["section_gaps"]],
        "note": "患者版全部为 null；staging 为 null；频率无法判定处为 null。",
    }
    print("profiles=%d main_sections_filled=%d/%d" % (len(profiles), filled, len(SECTION_KEYS)))
    print("gaps:", [g["section"] for g in main_profile["section_gaps"]])
    print("subtypes:", [s["name"] for s in main_profile["sections"]["pathology_subtypes"]])
    print("links.drugs:", main_profile["links"]["drugs"])
    if args.dry_run:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("written:", os.path.relpath(OUT, BASE))


if __name__ == "__main__":
    main()
