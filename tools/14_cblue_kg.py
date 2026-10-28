# -*- coding: utf-8 -*-
"""CBLUE CMeIE-V2 → A6 关系三元组（癌症子图）。

输入：cache/cblue/kg_candidates.json（13 号脚本产出）、data/clean/terminology/terminology_cancer.json
输出：data/clean/kg_triples/kg_cmeie_cancer.json

规则：
1. head/tail 必须命中 A5 canonical 且类别与关系约束一致（V5 引用完整性）；
2. 只保留 A6 关系词表内的 relation（需求清单 §A6② 的 9 种）；
3. 方向已按关系语义纠正（病理分型/并发症 在 CMeIE 中主语是上位/原发，需翻转）。
"""
import os
import json
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache", "cblue")
TERM_FILE = os.path.join(BASE, "data", "clean", "terminology", "terminology_cancer.json")
OUT_DIR = os.path.join(BASE, "data", "clean", "kg_triples")
TODAY = "2026-10-27"

# A6 关系词表（需求清单 §A6②）；staging 不在词表内，丢弃
RELATION_ENUM = {"has_symptom", "examined_by", "treated_by", "complication_of",
                 "subtype_of", "expressed_by", "targeted_by", "recommended_for", "followed_by"}
# 各关系对 tail 类别的约束
TAIL_CONSTRAINT = {
    "has_symptom": "symptom",
    "examined_by": "examination",
    "treated_by": "drug",
    "complication_of": "disease",
    "subtype_of": "disease",
    "targeted_by": "drug",
    "expressed_by": "disease",
}

SOURCE = "CBLUE CMeIE-V2 中文医疗关系抽取语料（train+dev 14,339 条文本），已按 5 癌种术语集筛子图"


def main():
    with open(TERM_FILE, encoding="utf-8") as f:
        terms = json.load(f)
    canonical = {t["canonical"]: t for t in terms}

    with open(os.path.join(CACHE, "kg_candidates.json"), encoding="utf-8") as f:
        cands = json.load(f)

    out, dropped = [], Counter()
    seen = set()
    for c in cands:
        rel = c["relation"]
        if rel not in RELATION_ENUM:
            dropped["relation_not_in_enum"] += 1
            continue
        head, tail = c["head"], c["tail"]
        h, t = canonical.get(head), canonical.get(tail)
        if h is None or t is None:
            dropped["endpoint_not_in_A5"] += 1
            continue
        if h["category"] != "disease":
            dropped["head_not_disease"] += 1
            continue
        if TAIL_CONSTRAINT.get(rel) and t["category"] != TAIL_CONSTRAINT[rel]:
            dropped["tail_type_mismatch"] += 1
            continue
        # 「转移性/继发性/复发性 X」是疾病状态而非亚型，不能建成 subtype_of
        if rel == "subtype_of" and any(k in head for k in ("转移", "继发", "复发")):
            dropped["subtype_of_state_not_subtype"] += 1
            continue
        key = (head, rel, tail)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        out.append({
            "triple_id": "KG-CBLUE-%05d" % (len(out) + 1),
            "head": head,
            "head_type": h["category"],
            "relation": rel,
            "tail": tail,
            "tail_type": t["category"],
            "cancer_type": h.get("cancer_type"),
            "evidence": c["evidence"],
            "confidence": c["confidence"],
            "raw_predicate": c["raw_predicate"],
            "source": SOURCE,
            "origin": "cblue",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    dest = os.path.join(OUT_DIR, "kg_cmeie_cancer.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("候选 %d → 入库 %d" % (len(cands), len(out)))
    print("  丢弃原因:", dict(dropped))
    print("  关系分布:", Counter(x["relation"] for x in out).most_common())
    print("  癌种分布:", Counter(x["cancer_type"] for x in out).most_common())
    print("  输出:", dest)


if __name__ == "__main__":
    main()
