# -*- coding: utf-8 -*-
"""步骤8（fda_ndc）：cache/fda_ndc/oncology_products.csv → data/clean/drug_labels/fda_ndc/

按英文通用名聚合为「药品条目」，每个条目含基础字段 + 美国上市制剂清单，
并显式标注 A4 必填项中本数据集缺失的部分（适应证/用法/禁忌/不良反应/ATC/中国批准文号）。

用法：python tools/8_fda_to_json.py（需先跑步骤7）
"""
import csv
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "cache", "fda_ndc", "oncology_products.csv")
OUT_DIR = os.path.join(BASE, "data", "clean", "drug_labels")
OUT = os.path.join(OUT_DIR, "drug_catalog.json")

SOURCE_TEXT = "FDA NDC Directory（美国 FDA 公开数据 product.txt，公有领域，快照至 20271231）"

TODAY = "2026-10-25"
SCOPE = {"lung": "LUNG", "breast": "BREAST", "colorectal": "CRC", "gastric": "GAS",
         "thyroid": "THY", "general": "SUP"}

# A4 要求的必填项中，本数据集没有的（如实标注，避免误用）
MISSING = ["indications", "dosage_and_administration", "contraindications",
           "adverse_reactions", "atc_code", "approval_number_cn", "chinese_label"]


def clean(s):
    return (s or "").strip()


def main():
    if not os.path.exists(SRC):
        print("未找到", SRC, "请先运行 tools/7_clean_fda_ndc.py")
        return 1

    groups = {}
    with open(SRC, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            key = r["drug_key"]
            g = groups.setdefault(key, {
                "name_zh": r["name_zh"],
                "drug_class": r["drug_class"],
                "cancer_types": r["cancer_types"].split("|"),
                "pharm_classes": set(),
                "routes": set(),
                "dosage_forms": set(),
                "labelers": set(),
                "applications": set(),
                "products": [],
            })
            if r["pharm_classes"]:
                g["pharm_classes"].add(r["pharm_classes"])
            if r["route"]:
                g["routes"].add(r["route"])
            if r["dosage_form"]:
                g["dosage_forms"].add(r["dosage_form"])
            if r["labeler"]:
                g["labelers"].add(r["labeler"])
            if r["application_number"]:
                g["applications"].add(r["application_number"])
            g["products"].append({
                "product_id": r["product_id"],
                "ndc": r["ndc"],
                "proprietary_name": r["proprietary_name"],
                "nonproprietary_name": r["nonproprietary_name"],
                "substancename": r["substancename"],
                "dosage_form": r["dosage_form"],
                "route": r["route"],
                "strength": r["strength"],
                "labeler": r["labeler"],
                "application_number": r["application_number"],
                "product_type": r["product_type"],
                "marketing_status": r["marketing_status"],
            })

    records = []
    seq = Counter()
    for key in sorted(groups):
        g = groups[key]
        scope_code = SCOPE.get(g["cancer_types"][0], "GEN")
        seq[scope_code] += 1
        records.append({
            "drug_id": "DRUG-%s-%03d" % (scope_code, seq[scope_code]),
            "generic_name_en": key.upper(),
            "canonical_zh": g["name_zh"],
            "drug_class": g["drug_class"],
            "cancer_type": g["cancer_types"],
            "pharm_classes": sorted(g["pharm_classes"]),
            "routes": sorted(g["routes"]),
            "dosage_forms": sorted(g["dosage_forms"]),
            "product_count": len(g["products"]),
            "labeler_count": len(g["labelers"]),
            "application_numbers": sorted(g["applications"]),
            "products": g["products"],
            "missing_fields": MISSING,
            "source": SOURCE_TEXT,
            "origin": "fda_ndc",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print("药品条目 %d 个，制剂记录 %d 条" % (len(records), sum(r["product_count"] for r in records)))
    print("药品条目按癌种:", dict(Counter(c for r in records for c in r["cancer_type"])))
    print("按类别:", dict(Counter(r["drug_class"] for r in records)))
    zero = [r["canonical_zh"] for r in records if not r["pharm_classes"]]
    print("PHARM_CLASSES 为空的药: %d 个 -> %s" % (len(zero), ", ".join(zero)))
    print("DONE ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
