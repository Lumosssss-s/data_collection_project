"""从已入库的 A3 疾病档案 / A4 药品 / A2 推荐条目派生肿瘤图谱（零 token）。

为什么不用 kgdrug 的 639 条：那批 2018 年关系里药物全是头孢/激素/中成药，
needs_drug 噪声大；本脚本改为从我们已校验的数据派生，关系类型对齐
/api/v1/kg/ontology 的 8 类实体与 9 类关系。

产出关系：
  Cancer --uses_drug--> Drug           （药品说明书 cancer_type + 疾病档案 links.drugs）
  Cancer --treated_by--> Treatment     （疾病档案 treatment_methods）
  Cancer --has_stage--> Stage          （疾病档案 stages）
  Cancer --has_symptom--> Symptom      （疾病档案 links.symptoms）
  Cancer --diagnosed_by--> Examination （推荐条目中出现的检查关键词）
  Gene --biomarker_of--> Cancer        （疾病档案 pathology_subtypes / biomarkers）

输出：data/intermediate/kg_derived.json {"entities": [...], "triples": [...]}
用法（宿主机）：
  python scripts/data_pipeline/build_kg_from_corpus.py
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE_DIR = os.path.join(BASE_DIR, "data", "clean", "disease_profiles")
REC_DIR = os.path.join(BASE_DIR, "data", "clean", "recommendations")
OUT = os.path.join(BASE_DIR, "data", "intermediate", "kg_derived.json")

TREATMENT_ZH = {
    "手术": "手术治疗", "手术切除": "手术切除", "化疗": "化学治疗",
    "放疗": "放射治疗", "靶向治疗": "靶向治疗", "免疫治疗": "免疫治疗",
    "放化疗": "放化疗",
}
# 检查关键词 → 标准检查名（需在推荐原文中出现才建关系）
EXAMS = [
    ("low-dose ct", "低剂量CT"), ("ldct", "低剂量CT"), ("ct scan", "CT检查"),
    ("colonoscopy", "结肠镜检查"), ("endoscopy", "内镜检查"),
    ("biopsy", "活检"), ("mri", "磁共振成像"), ("pet", "PET-CT"),
    ("pathologic", "病理检查"),
]
GENE_ALIASES = {
    "EGFR 突变": ("EGFR", "表皮生长因子受体"),
    "ALK 融合": ("ALK", "间变性淋巴瘤激酶"),
    "KRAS 突变": ("KRAS", "KRAS 基因"),
    "MSI-H/dMMR": ("MSI-H", "微卫星高度不稳定"),
}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text.lower()).strip("-")
    return s or "unknown"


def main() -> None:
    profiles = []
    for name in sorted(os.listdir(PROFILE_DIR)):
        if name.endswith(".json"):
            profiles.append(json.load(open(os.path.join(PROFILE_DIR, name), encoding="utf-8")))

    recs = []
    for name in sorted(os.listdir(REC_DIR)):
        if name.endswith("_recs.json"):
            recs.extend(json.load(open(os.path.join(REC_DIR, name), encoding="utf-8")))

    entities: Dict[str, Dict] = {}
    triples: List[Dict] = []
    seen = set()

    def eid_of(etype: str, name: str) -> str:
        """实体 ID 约定：`Type::标准名`（与 kg_extraction_service / 消歧服务一致）。"""
        return f"{etype}::{eid_name(name)}"

    def eid_name(name: str) -> str:
        return re.sub(r"\s+", " ", name or "").strip()

    def add_entity(eid: str, name: str, etype: str, cancer: str = "", aliases=None) -> str:
        ent = entities.setdefault(eid, {"entity_id": eid, "name": name, "type": etype,
                                        "aliases": [], "cancer_types": []})
        if cancer and cancer not in ent["cancer_types"]:
            ent["cancer_types"].append(cancer)
        for a in aliases or []:
            if a and a != name and a not in ent["aliases"]:
                ent["aliases"].append(a)
        return eid

    def add_triple(hid: str, htype: str, hname: str, rel: str,
                   tid: str, ttype: str, tname: str, cancer: str, ref: str) -> None:
        key = (hid, rel, tid)
        if key in seen:
            return
        seen.add(key)
        triples.append({
            "head": {"id": hid, "type": htype, "name": hname, "canonical_id": hid},
            "tail": {"id": tid, "type": ttype, "name": tname, "canonical_id": tid},
            "relation": rel,
            "source_ref": ref,
            "confidence": 0.9,
            "cancer_type": cancer,
        })

    for p in profiles:
        cancer = p.get("cancer_type") or ""
        cname = p["name_canonical"]
        cid = add_entity(eid_of("Cancer", cname), cname, "Cancer", cancer,
                         p.get("synonyms") + [p.get("name_en", "")])

        for drug in (p.get("links") or {}).get("drugs") or []:
            did = add_entity(eid_of("Drug", drug), drug, "Drug", cancer)
            add_triple(cid, "Cancer", cname, "uses_drug", did, "Drug", drug, cancer,
                       p["disease_id"])

        for method in p.get("treatment_methods") or []:
            zh = TREATMENT_ZH.get(method, method)
            tid = add_entity(eid_of("Treatment", zh), zh, "Treatment", cancer)
            add_triple(cid, "Cancer", cname, "treated_by", tid, "Treatment", zh, cancer,
                       p["disease_id"])

        for stage in p.get("stages") or []:
            sid = add_entity(eid_of("Stage", f"{stage} 期"), f"{stage} 期", "Stage", cancer)
            add_triple(cid, "Cancer", cname, "has_stage", sid, "Stage", f"{stage} 期",
                       cancer, p["disease_id"])

        for sym in (p.get("links") or {}).get("symptoms") or []:
            sid = add_entity(eid_of("Symptom", sym), sym, "Symptom", cancer)
            add_triple(cid, "Cancer", cname, "has_symptom", sid, "Symptom", sym, cancer,
                       p["disease_id"])

        for item in p.get("pathology_subtypes") or []:
            gene = GENE_ALIASES.get(item)
            if not gene:
                continue
            gid = add_entity(eid_of("Gene", gene[0]), gene[0], "Gene", cancer, [gene[1]])
            add_triple(gid, "Gene", gene[0], "biomarker_of", cid, "Cancer", cname,
                       cancer, p["disease_id"])

        # 检查：仅当该癌种的推荐原文里确实出现过该检查关键词
        text = " ".join((r.get("recommendation_text") or "") for r in recs
                        if r.get("cancer_type") == cancer).lower()
        for kw, exam in EXAMS:
            if kw in text:
                eid = add_entity(eid_of("Examination", exam), exam, "Examination", cancer)
                add_triple(cid, "Cancer", cname, "diagnosed_by", eid, "Examination", exam,
                           cancer, "guideline-recs")

    payload = {"entities": list(entities.values()), "triples": triples}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"实体 {len(entities)} 个，三元组 {len(triples)} 条 -> {OUT}")
    from collections import Counter
    print("关系分布:", dict(Counter(t["relation"] for t in triples)))
    print("实体类型:", dict(Counter(e["type"] for e in entities.values())))


if __name__ == "__main__":
    main()
