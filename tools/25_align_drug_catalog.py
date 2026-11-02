# -*- coding: utf-8 -*-
"""tools/25_align_drug_catalog.py

A4 字段名对齐（需求清单 §A4 ⑥ 字段结构，前缀 DRUG）。

输入：data/clean/drug_labels/drug_catalog_v1_20261025.json   # 旧版（canonical_zh / atc）
输出：data/clean/drug_labels/drug_catalog_v2.json   # 新版（generic_name / atc_code）
审计：cache/drug_labels/align_v2_audit.json

只做改名与补空字段，不重新抓数、不改动已采集内容：
  canonical_zh → generic_name（中文通用名 canonical）
  atc          → atc_code
  新增 brand_names / approval_no / contraindications / adverse_reactions
  dosage 统一为 {"standard","adjustment"}；indications 统一为数组
旧文件按 G4 保留不覆盖，下游（22 号）改读 v2。

用法：
  python tools/25_align_drug_catalog.py            # 迁移并写盘
  python tools/25_align_drug_catalog.py --dry-run  # 只打印审计
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v1_20261025.json")
OUT = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")
AUDIT = os.path.join(BASE, "cache", "drug_labels", "align_v2_audit.json")
UPDATED_AT = "2026-10-28"

# 需求清单 §A4 ⑥ 的必填/选填顺序，其余字段按原顺序附在后面
A4_ORDER = ["drug_id", "generic_name", "brand_names", "atc_code", "approval_no",
            "indications", "dosage", "contraindications", "adverse_reactions",
            "interactions"]


def brand_names(rec):
    names = sorted({p.get("proprietary_name") for p in rec.get("products") or []
                    if p.get("proprietary_name")})
    return names or None


def norm_dosage(v):
    if v is None:
        return None
    if isinstance(v, str):
        return {"standard": v.strip() or None, "adjustment": None}
    if isinstance(v, dict):
        return {"standard": v.get("standard"), "adjustment": v.get("adjustment")}
    return v


def norm_indications(v):
    if v is None:
        return None
    if isinstance(v, str):
        return [v] if v.strip() else None
    return v


def migrate(rec):
    new = {}
    legacy = rec.get("canonical_zh")
    new["drug_id"] = rec.get("drug_id")
    new["generic_name"] = rec.get("generic_name") or legacy
    new["brand_names"] = rec.get("brand_names") or brand_names(rec)
    new["atc_code"] = rec.get("atc_code") or rec.get("atc")
    new["approval_no"] = rec.get("approval_no")
    new["indications"] = norm_indications(rec.get("indications"))
    new["dosage"] = norm_dosage(rec.get("dosage"))
    new["contraindications"] = rec.get("contraindications")
    new["adverse_reactions"] = rec.get("adverse_reactions")
    new["interactions"] = rec.get("interactions")
    for k, v in rec.items():
        if k in new or k in ("canonical_zh", "atc"):
            continue
        new[k] = v
    ann = dict(new.get("annotation") or {})
    ann["schema_version"] = "v2"
    ann["field_alignment"] = ("按 §A4 ⑥ 改名：canonical_zh→generic_name、atc→atc_code；"
                              "brand_names 取 FDA 商品名（proprietary_name），中文商品名待补")
    new["annotation"] = ann
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(SRC, encoding="utf-8") as f:
        records = json.load(f)

    out = [migrate(r) for r in records]
    filled = {k: sum(1 for r in out if r.get(k) not in (None, "", [], {}))
              for k in A4_ORDER}
    dup = len(out) - len({r.get("generic_name") for r in out})
    audit = {
        "generated_at": UPDATED_AT,
        "input": os.path.relpath(SRC, BASE),
        "output": os.path.relpath(OUT, BASE),
        "records": len(out),
        "required_field_filled": filled,
        "duplicate_generic_name": dup,
        "renamed": {"canonical_zh": "generic_name", "atc": "atc_code"},
        "added_null_fields": ["brand_names", "approval_no", "indications", "dosage",
                              "contraindications", "adverse_reactions", "interactions"],
        "note": ("纯改名迁移，未新增采集内容；approval_no（国药准字）与禁忌/不良反应仍缺，"
                 "已在 missing_fields 中登记，待 NMPA 说明书授权渠道补齐"),
    }

    print("records=%d dup_generic_name=%d" % (len(out), dup))
    print("filled:", json.dumps(filled, ensure_ascii=False))
    if args.dry_run:
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("written:", os.path.relpath(OUT, BASE))


if __name__ == "__main__":
    main()
