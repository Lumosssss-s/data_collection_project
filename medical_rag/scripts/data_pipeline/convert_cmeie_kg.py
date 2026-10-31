"""CMeIE 关系语料 → 图谱三元组口径转换（纯本地，零 token）。

第五批 kg_cmeie_cancer.json 落地口径修正：
  1. 字段结构对齐 ES 契约（head_id/head_name/canonical_id + 数值 confidence）
  2. subtype_of 剔除：本体 9 类关系无此类型，单独归档不丢弃原始数据
  3. 关系语义改写：examined_by→diagnosed_by、treated_by（疾病→药物）→uses_drug
  4. 实体类型裁剪：仅保留本体 8 类；disease 按疾病档案映射为 Cancer，非癌种实体丢弃
  5. 越界癌种（肺癌/结直肠癌之外）落盘归档，不入库

用法（宿主机）：
  python scripts/data_pipeline/convert_cmeie_kg.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE_DIR, "data", "clean", "kg_triples", "kg_cmeie_cancer.json")
OUT_DIR = os.path.join(BASE_DIR, "data", "intermediate")
OUT = os.path.join(OUT_DIR, "kg_cmeie_converted.json")
OUT_SCOPE = os.path.join(OUT_DIR, "kg_outofscope.json")

# disease 实体 → 疾病档案 canonical（Cancer 类）；未列出的非癌种实体一律丢弃
DISEASE_MAP: Dict[str, Dict] = {
    "肺恶性肿瘤": {"id": "Cancer::肺癌", "name": "肺癌", "cancer": "lung"},
    "结肠恶性肿瘤": {"id": "Cancer::结肠癌", "name": "结肠癌", "cancer": "colorectal"},
    "直肠恶性肿瘤": {"id": "Cancer::直肠癌", "name": "直肠癌", "cancer": "colorectal"},
}

# 关系改写：原谓词 → (本体关系, 尾实体类型)
REL_MAP: Dict[str, tuple] = {
    "has_symptom": ("has_symptom", "Symptom"),
    "examined_by": ("diagnosed_by", "Examination"),
    "treated_by": ("uses_drug", "Drug"),
}

TAIL_TYPE: Dict[str, str] = {"symptom": "Symptom", "examination": "Examination", "drug": "Drug"}
CONF_MAP = {"high": 0.8, "medium": 0.6, "low": 0.4}
IN_SCOPE = {"lung", "colorectal"}
# 未标癌种时按名称判定越界的关键词
OUT_KW = ["甲状腺", "乳腺", "乳房", "胃"]


def is_out_of_scope(rec: Dict) -> bool:
    ct = rec.get("cancer_type")
    if ct in IN_SCOPE:
        return False
    if ct in ("breast", "gastric", "thyroid"):
        return True
    return any(k in (rec.get("head") or "") + (rec.get("tail") or "") for k in OUT_KW)


def main() -> None:
    records = json.load(open(SRC, encoding="utf-8"))
    entities: Dict[str, Dict] = {}
    triples: List[Dict] = []
    dropped: List[Dict] = []
    out_scope: List[Dict] = []
    subtype: List[Dict] = []

    for rec in records:
        rid = rec.get("triple_id", "")
        if rec.get("relation") == "subtype_of":
            subtype.append(rec)
            continue
        if is_out_of_scope(rec):
            out_scope.append(rec)
            continue

        rel = REL_MAP.get(rec.get("relation"))
        head = DISEASE_MAP.get(rec.get("head"))
        if not rel or not head:
            dropped.append({"triple_id": rid, "reason": "关系或头实体不在本体口径内",
                            "head": rec.get("head"), "relation": rec.get("relation")})
            continue

        tail_type = TAIL_TYPE.get(rec.get("tail_type"))
        if not tail_type:
            dropped.append({"triple_id": rid, "reason": "尾实体类型非本体 8 类",
                            "tail": rec.get("tail"), "tail_type": rec.get("tail_type")})
            continue

        tail_name = (rec.get("tail") or "").strip()
        tail_id = f"{tail_type}::{tail_name}"
        cancer = rec.get("cancer_type") or head["cancer"]

        for eid, name, etype in (
            (head["id"], head["name"], "Cancer"),
            (tail_id, tail_name, tail_type),
        ):
            ent = entities.setdefault(eid, {"entity_id": eid, "name": name, "type": etype,
                                            "aliases": [], "cancer_types": []})
            if cancer not in ent["cancer_types"]:
                ent["cancer_types"].append(cancer)

        triples.append({
            "head": {"id": head["id"], "type": "Cancer", "name": head["name"],
                     "canonical_id": head["id"]},
            "tail": {"id": tail_id, "type": tail_type, "name": tail_name,
                     "canonical_id": tail_id},
            "relation": rel[0],
            "source_ref": rid,
            "confidence": CONF_MAP.get(rec.get("confidence"), 0.5),
            "cancer_type": cancer,
        })

    payload = {"entities": list(entities.values()), "triples": triples,
               "rejected": {"subtype_of": subtype, "dropped": dropped}}
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out_scope, open(OUT_SCOPE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"源记录 {len(records)}")
    print(f"  2b subtype_of 归档 {len(subtype)}")
    print(f"  5b 越界癌种归档 {len(out_scope)} -> {OUT_SCOPE}")
    print(f"  4b 实体/关系不达标丢弃 {len(dropped)}")
    print(f"  入库三元组 {len(triples)}，实体 {len(entities)}")
    print(f"  关系分布 {dict(Counter(t['relation'] for t in triples))}")
    print(f"  实体类型 {dict(Counter(e['type'] for e in entities.values()))}")
    if dropped:
        print(f"  丢弃明细 {[(d['triple_id'], d['reason']) for d in dropped]}")


if __name__ == "__main__":
    main()
