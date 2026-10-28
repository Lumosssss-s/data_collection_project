# -*- coding: utf-8 -*-
"""CBLUE → A5 术语字典。

输入：raw/cblue/CHIP-CDN.zip（含 ICD-10 北京临床版 v601 码表）、raw/cblue/CMeIE-V2.zip
中间：cache/cblue/
输出：data/clean/terminology/terminology_cancer.json
      cache/cblue/kg_candidates.json（供 14 号脚本生成 A6 三元组）
"""
import os
import re
import json
import glob
import zipfile
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw", "cblue")
CACHE = os.path.join(BASE, "cache", "cblue")
UNZIP = os.path.join(CACHE, "_unzipped")
OUT_DIR = os.path.join(BASE, "data", "clean", "terminology")
TODAY = "2026-10-27"

SOURCE_ICD = "CBLUE CHIP-CDN 附带《国际疾病分类 ICD-10北京临床版v601》码表（40,474 条）"
SOURCE_IE = "CBLUE CMeIE-V2 中文医疗关系抽取语料（train+dev 14,339 条文本）"


# ---------------------------------------------------------------- 解压
def fix_name(name):
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return name


def ensure_unzipped():
    os.makedirs(UNZIP, exist_ok=True)
    for zpath in sorted(glob.glob(os.path.join(RAW, "*.zip"))):
        tag = os.path.splitext(os.path.basename(zpath))[0]
        dest = os.path.join(UNZIP, tag)
        if os.path.isdir(dest) and os.listdir(dest):
            continue
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = fix_name(info.filename)
                name = name.split("/", 1)[1] if "/" in name else name
                with zf.open(info) as src, open(os.path.join(dest, name), "wb") as dst:
                    dst.write(src.read())


# ---------------------------------------------------------------- ICD-10
SITE_PREFIX = {
    "lung": ("C34", "D02.2"),
    "breast": ("C50", "D05"),
    "colorectal": ("C18", "C19", "C20", "C21", "D01"),
    "gastric": ("C16",),
    "thyroid": ("C73", "D09.3", "D34", "E04"),
}
ORGAN_WORD = {
    "lung": ("肺", "支气管"),
    "breast": ("乳腺",),
    "colorectal": ("结肠", "直肠", "肛管", "肛门"),
    "gastric": ("胃",),
    "thyroid": ("甲状腺",),
}
# 癌前病变：编码章节 + 器官网 + 病变词
PRECANCER_CODE = ("D12", "D13", "D14", "D24", "D34", "K31", "K62", "K63", "N60", "E04")
PRECANCER_WORD = ("腺瘤", "息肉", "上皮内瘤变", "不典型增生", "异型增生", "增生", "结节", "囊肿")
# 肿瘤并发症（按名称精确匹配，不用编码猜）
COMPLICATION = (
    "恶性胸腔积液", "恶性腹水", "恶性腹腔积液", "恶性心包积液", "恶病质", "癌性疼痛",
    "肿瘤溶解综合征", "上腔静脉综合征", "脊髓压迫", "病理性骨折", "高钙血症", "淋巴水肿",
)
METASTASIS_CODE = ("C77", "C78", "C79", "C80")

# ICD-10 标准名 ← 通用简称（需求清单 A5⑩ 示例即「肺癌」为「肺恶性肿瘤」的同义词）
ALIAS = {
    "肺癌": "肺恶性肿瘤",
    "乳腺癌": "乳腺恶性肿瘤",
    "胃癌": "胃恶性肿瘤",
    "结肠癌": "结肠恶性肿瘤",
    "直肠癌": "直肠恶性肿瘤",
    "甲状腺癌": "甲状腺恶性肿瘤",
}


def in_site(code, name):
    """返回癌种；仅对器官词做限定，避免 D01/E04 等宽章节串入无关器官。"""
    for site, prefixes in SITE_PREFIX.items():
        if not any(code.startswith(p) for p in prefixes):
            continue
        # 宽章节（原位癌/良性/甲状腺其他疾患）必须命中本器官网
        if code.startswith(("D01", "D05", "D02.2", "D09.3", "D34", "E04")):
            if not any(w in name for w in ORGAN_WORD[site]):
                continue
        return site
    return None


def build_diseases(rows):
    """rows: [(code, name)] → 疾病条目列表。"""
    picked = []
    seen = {}
    for code, name in rows:
        site = in_site(code, name)
        kind = "primary"
        if site is None:
            if code.startswith(METASTASIS_CODE) and any(
                    w in name for ws in ORGAN_WORD.values() for w in ws):
                site = next(s for s, ws in ORGAN_WORD.items() if any(w in name for w in ws))
                kind = "metastasis"
            elif code.startswith(PRECANCER_CODE) and any(w in name for w in PRECANCER_WORD):
                site = next((s for s, ws in ORGAN_WORD.items() if any(w in name for w in ws)), None)
                kind = "precancer"
            elif name in COMPLICATION:
                site = next((s for s, ws in ORGAN_WORD.items() if any(w in name for w in ws)), None)
                kind = "complication"
        if site is None and kind == "primary":
            continue
        if site is None and name not in COMPLICATION and not any(
                w in name for w in PRECANCER_WORD):
            continue
        if name in seen:            # canonical 全局唯一，保留层级最高（编码最短）的条目
            if len(code) < len(seen[name]["code"]):
                seen[name].update(code=code, site=site, kind=kind)
            continue
        rec = {"code": code, "name": name, "site": site, "kind": kind}
        seen[name] = rec
        picked.append(rec)
    # 过滤明显非肿瘤串入（炎症/结核/溃疡）
    bad = ("结核", "炎症", "溃疡", "感染", "结石")
    picked = [r for r in picked if not any(b in r["name"] for b in bad)]
    return picked


# ---------------------------------------------------------------- CMeIE
PRED_MAP = {
    "临床表现": ("has_symptom", "symptom", False),
    "相关（症状）": ("has_symptom", "symptom", False),
    "治疗后症状": ("has_symptom", "symptom", False),
    "实验室检查": ("examined_by", "examination", False),
    "影像学检查": ("examined_by", "examination", False),
    "辅助检查": ("examined_by", "examination", False),
    "组织学检查": ("examined_by", "examination", False),
    "内窥镜检查": ("examined_by", "examination", False),
    "筛查": ("examined_by", "examination", False),
    "药物治疗": ("treated_by", "drug", False),
    "病理分型": ("subtype_of", "disease", True),      # 尾为亚型，需翻转
    "并发症": ("complication_of", "disease", True),
    "阶段": ("staging", "staging", False),
}
CATEGORY_OF_TYPE = {
    "症状": "symptom", "检查": "examination", "药物": "drug", "疾病": "disease", "其他": "staging",
}

# 误标为「检查」的基因符号 → 归入 gene
GENE_OF_EXAM = {"BRAF": "BRAF", "EGFR": "EGFR", "ALK": "ALK", "HER2": "HER2",
                "KRAS": "KRAS", "BRCA1": "BRCA1", "BRCA2": "BRCA2", "MSI": "MSI"}
STAGING_OK = {"T分期", "N分期", "M分期", "早期", "中期", "晚期", "晚期", "早中期", "局部晚期"}

# 药物类别名/短语：不是单一药品，无法映射唯一 ATC 单药码，不入 A5 drug
DRUG_CLASS_DROP = {"双膦酸盐", "双磷酸盐", "糖皮质激素", "维生素D", "钙片",
                   "联合或不联合长期选择性雌激素受体调节剂"}


def keep_pending(cat, name):
    """自动抽取条目的入池质量闸门（不满足者丢弃，避免脏词进字典）。"""
    if len(name) < 2:
        return False
    if cat == "disease":
        if name in {"DCIS", "LCIS", "NSCLC", "SCLC"}:
            return True
        # 关系尾只收肿瘤性病变（癌/瘤/原位/上皮内瘤变），避免并发症外的非肿瘤疾病串入
        return any(k in name for k in ("癌", "瘤", "原位", "上皮内瘤变"))
    if cat == "staging":
        return name in STAGING_OK
    if cat == "examination":
        if re.fullmatch(r"[A-Za-z0-9\-]{1,6}", name):
            return False
        return True
    if cat == "drug":
        if name in DRUG_CLASS_DROP:
            return False
        return not any(k in name for k in ("疗法", "治疗", "抑制", "方案", "手术"))
    return True


def load_triples(disease_names, alias_to):
    files = []
    for name in ("CMeIE-V2_train.jsonl", "CMeIE-V2_dev.jsonl"):
        p = os.path.join(UNZIP, "CMeIE-V2", name)
        if os.path.exists(p):
            files.append(p)
    triples, tail_pool, new_diseases = [], Counter(), set()
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                for spo in rec["spo_list"]:
                    pred = spo["predicate"]
                    obj = spo["object"]["@value"].strip()
                    obj_type = spo["object_type"]["@value"]
                    if pred == "同义词" or pred not in PRED_MAP:
                        continue
                    subj_raw = spo["subject"]
                    subj = alias_to.get(subj_raw, subj_raw)
                    if subj not in disease_names:
                        continue
                    relation, tail_type, flip = PRED_MAP[pred]
                    if CATEGORY_OF_TYPE.get(obj_type) != tail_type:
                        continue
                    if not obj or len(obj) > 30 or obj == subj:
                        continue
                    if flip:
                        head_raw, tail = obj, subj
                        head = alias_to.get(head_raw, head_raw)
                        if relation in ("subtype_of", "complication_of") and head not in disease_names:
                            new_diseases.add(head)
                    else:
                        head, tail = subj, obj
                    if len(head) > 40:
                        continue
                    triples.append({
                        "head": head, "head_type": "disease",
                        "relation": relation, "tail": tail, "tail_type": tail_type,
                        "evidence": rec["text"][:200],
                        "confidence": "medium" if len(rec["text"]) >= 20 else "low",
                        "cancer_type": None,
                        "raw_predicate": pred,
                    })
                    if tail_type in ("symptom", "examination", "drug", "staging"):
                        tail_pool[(tail_type, tail)] += 1
    # 去重
    uniq, seen = [], set()
    for t in triples:
        key = (t["head"], t["relation"], t["tail"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    return uniq, tail_pool, new_diseases


def load_synonyms(disease_names):
    """CMeIE 同义词关系 → A5 synonyms（最可靠的同义词来源）。"""
    syn = {}
    p = os.path.join(UNZIP, "CMeIE-V2", "CMeIE-V2_train.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for spo in rec["spo_list"]:
                if spo["predicate"] != "同义词":
                    continue
                s, o = spo["subject"], spo["object"]["@value"]
                if s in disease_names and o not in disease_names and len(o) <= 25:
                    syn.setdefault(s, set()).add(o)
    return syn


# ---------------------------------------------------------------- 主流程
def main():
    ensure_unzipped()
    import openpyxl

    xlsx = os.path.join(UNZIP, "CHIP-CDN", "国际疾病分类 ICD-10北京临床版v601.xlsx")
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    rows = [(str(r[0]).strip(), str(r[1]).strip())
            for r in wb["Sheet1"].iter_rows(values_only=True) if r[0] and r[1]]

    diseases = build_diseases(rows)
    print("ICD-10 总条目 %d → 疾病候选 %d" % (len(rows), len(diseases)))
    print("  按类型:", Counter(d["kind"] for d in diseases))
    print("  按癌种:", Counter(d["site"] for d in diseases))

    disease_names = {d["name"] for d in diseases}
    alias_to = {a: c for a, c in ALIAS.items() if c in disease_names}
    triples, tail_pool, new_diseases = load_triples(disease_names, alias_to)
    syn = load_synonyms(disease_names)
    for alias, canon in alias_to.items():
        syn.setdefault(canon, set()).add(alias)
    print("CMeIE 可映射三元组 %d（主语已归一，含 %d 条别名）" % (len(triples), len(alias_to)))
    print("  尾实体池:", Counter(k for k, _ in tail_pool))
    print("  新增疾病（关系尾，未在 ICD-10 排污）:", len(new_diseases))

    terms = []
    for i, d in enumerate(diseases, 1):
        terms.append({
            "term_id": "TERM-DISEASE-%04d" % i,
            "canonical": d["name"],
            "category": "disease",
            "synonyms": sorted(syn[d["name"]]) if d["name"] in syn else None,
            "icd10": d["code"],
            "icd_o3": None,
            "atc": None,
            "pinyin": None,
            "en_name": None,
            "mapping_status": "confirmed",
            "cancer_type": d["site"],
            "source": SOURCE_ICD,
            "origin": "cblue",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })

    # 关系尾新增疾病：作为 pending 条目，保证 A6 引用完整性（head/tail 可解析）
    start = len(terms)
    added_disease = 0
    for name in sorted(new_diseases):
        if not keep_pending("disease", name):
            continue
        added_disease += 1
        terms.append({
            "term_id": "TERM-DISEASE-%04d" % (start + added_disease),
            "canonical": name,
            "category": "disease",
            "synonyms": sorted(syn[name]) if name in syn else None,
            "icd10": None,
            "icd_o3": None,
            "atc": None,
            "pinyin": None,
            "en_name": None,
            "mapping_status": "pending",
            "cancer_type": None,
            "source": SOURCE_IE,
            "origin": "cblue",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })

    seq = {"symptom": 0, "examination": 0, "drug": 0, "staging": 0, "gene": 0}
    existing = {t["canonical"] for t in terms}
    for (cat, name), cnt in sorted(tail_pool.items(), key=lambda x: (-x[1], x[0][1])):
        if name in existing:
            continue
        if cat == "examination" and name in GENE_OF_EXAM:
            cat, name = "gene", GENE_OF_EXAM[name]
        if not keep_pending(cat, name):
            continue
        seq[cat] += 1
        terms.append({
            "term_id": "TERM-%s-%04d" % (cat.upper(), seq[cat]),
            "canonical": name,
            "category": cat,
            "synonyms": None,
            "icd10": None,
            "icd_o3": None,
            "atc": None,
            "pinyin": None,
            "en_name": None,
            "mapping_status": "pending",
            "cancer_type": None,
            "source": SOURCE_IE,
            "origin": "cblue",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })
        existing.add(name)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "terminology_cancer.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False, indent=2)
    print("已写出 %s：%d 条" % (out, len(terms)))
    print("  分类:", Counter(t["category"] for t in terms))
    print("  mapping_status:", Counter(t["mapping_status"] for t in terms))

    # 三元组候选落 cache，供 14 号脚本
    with open(os.path.join(CACHE, "kg_candidates.json"), "w", encoding="utf-8") as f:
        json.dump(triples, f, ensure_ascii=False, indent=2)
    print("kg_candidates.json：%d 条候选" % len(triples))


if __name__ == "__main__":
    main()
