# -*- coding: utf-8 -*-
"""tools/31_merge_cn_labels.py

把 fetched/labels_cn/labels_cn.json 中已采集的中文说明书原文，合并进
data/clean/drug_labels/drug_catalog_v2.json。

合并规则（严格按任务硬约束）
- 只填空：已有中文适应证/用法用量（来自《新型抗肿瘤药物临床应用指导原则》）不覆盖。
- 英文 interim（openFDA）的禁忌/不良反应，在拿到中文说明书原文后整块替换，并保留
  被替换的英文层摘要到 *_source.replaced_interim，便于追溯。
- 中文说明书字段只写说明书原文；注册信息（国药准字/商品名/规格/持有人）单独放在
  cn_registration 块，并标注 source_type=official_label_text，不与正文混写。
- 缺失字段保持 null；missing_fields 依据实际空值重算。
- 幂等：第二次运行不改变任何字节（只填空 + 确定性序列化）。

用法：
    python tools/31_merge_cn_labels.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = os.path.join(ROOT, "fetched", "labels_cn", "labels_cn.json")
CAT = os.path.join(ROOT, "data", "clean", "drug_labels", "drug_catalog_v2.json")
AUDIT = os.path.join(ROOT, "cache", "drug_labels", "cn_label_merge.json")

MISSING_ORDER = ["indications", "dosage", "contraindications", "adverse_reactions",
                 "approval_number_cn", "chinese_label"]

NEW_DRUGS = {
    "DRUG-EXTRA-003": {
        "generic_name": "信迪利单抗",
        "generic_name_en": "SINITILIMAB",
        "drug_class": "靶向",
        "atc_code": None,
    },
}

# 说明书适应证原文中的明确瘤种 → 项目癌种标签（仅字面匹配，不做药理学推断）
CANCER_TAG_RULES = [
    ("lung", ("非小细胞肺癌", "小细胞肺癌")),
    ("gastric", ("胃癌", "胃及胃食管交界处")),
    ("colorectal", ("结肠癌", "直肠癌", "结直肠癌")),
    ("breast", ("乳腺癌",)),
    ("thyroid", ("甲状腺癌",)),
]


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def is_english_items(items) -> bool:
    """条目全为英文（openFDA interim）时返回 True。"""
    if not items:
        return False
    for it in items:
        if isinstance(it, dict):
            if it.get("lang") == "zh":
                return False
            text = it.get("term") or ""
        else:
            text = str(it)
        if has_cjk(text):
            return False
    return True


def source_block(label: dict) -> dict:
    return {
        "lang": "zh",
        "status": "zh_from_official_label",
        "source_type": label["source_type"],
        "source_name": label["source_name"],
        "source_url": label["source_url"],
        "source_holder": label.get("source_holder"),
        "fetched_at": label["fetched_at"],
        "usage_note": label["usage_note"],
    }


def label_block(label: dict) -> dict:
    return {
        "lang": "zh",
        "status": "zh_from_official_label",
        "source_type": label["source_type"],
        "source_name": label["source_name"],
        "source_url": label["source_url"],
        "source_holder": label.get("source_holder"),
        "fetched_at": label["fetched_at"],
        "usage_note": label["usage_note"],
        "content_type": label.get("content_type"),
        "pages": label.get("pages"),
        "char_count": label.get("char_count"),
        "raw_path": label.get("raw_path"),
        "text_path": label.get("text_path"),
        "text_sha256": label.get("text_sha256"),
        "sections": label.get("sections"),
        "text_stored_in_catalog": False,
        "note": "说明书全文不写入目录（体积过大），按 text_path 读取；目录仅存元数据与关键字段。",
    }


def recompute_missing(rec: dict) -> list[str]:
    out = []
    if not rec.get("indications"):
        out.append("indications")
    d = rec.get("dosage") or {}
    if not (isinstance(d, dict) and (d.get("standard") or d.get("adjustment"))):
        out.append("dosage")
    if not rec.get("contraindications"):
        out.append("contraindications")
    if not rec.get("adverse_reactions"):
        out.append("adverse_reactions")
    if not rec.get("approval_no"):
        out.append("approval_number_cn")
    if not rec.get("label"):
        out.append("chinese_label")
    return [m for m in MISSING_ORDER if m in out]


def main() -> int:
    labels = json.load(open(LABELS, encoding="utf-8"))["records"]
    cat = json.load(open(CAT, encoding="utf-8"))

    primary = {}
    for r in labels:
        if r.get("secondary"):
            continue
        primary[r["drug_id"]] = r

    by_id = {r["drug_id"]: r for r in cat}
    actions = []

    def fill(rec: dict, label: dict, drug_key: str) -> dict:
        act = {"drug_id": rec["drug_id"], "generic_name": rec["generic_name"],
               "label_key": label["key"], "filled": [], "replaced": [], "kept": []}
        src = source_block(label)

        if not rec.get("indications") and label["indications"]:
            rec["indications"] = list(label["indications"])
            rec["indications_source"] = src
            act["filled"].append("indications")
        elif rec.get("indications"):
            act["kept"].append("indications")

        cur_dos = rec.get("dosage") or {}
        if label.get("dosage"):
            if not (cur_dos.get("standard") or cur_dos.get("adjustment")):
                rec["dosage"] = {
                    "standard": label["dosage"].get("standard"),
                    "adjustment": label["dosage"].get("adjustment"),
                }
                rec["dosage_source"] = src
                act["filled"].append("dosage")
            else:
                act["kept"].append("dosage")

        if label["contraindications"]:
            if not rec.get("contraindications"):
                rec["contraindications"] = list(label["contraindications"])
                rec["contraindications_source"] = src
                act["filled"].append("contraindications")
            elif is_english_items(rec["contraindications"]):
                prev = rec.get("contraindications_source") or {}
                rec["contraindications"] = list(label["contraindications"])
                rec["contraindications_source"] = {
                    **src, "replaced_interim": {"lang": prev.get("lang", "en"),
                                                "set_id": prev.get("set_id"),
                                                "fetched_at": prev.get("fetched_at")},
                }
                act["replaced"].append("contraindications")
            else:
                act["kept"].append("contraindications")

        if label["adverse_reactions"]:
            if not rec.get("adverse_reactions"):
                rec["adverse_reactions"] = list(label["adverse_reactions"])
                rec["adverse_reactions_source"] = src
                act["filled"].append("adverse_reactions")
            elif is_english_items(rec["adverse_reactions"]):
                prev = rec.get("adverse_reactions_source") or {}
                rec["adverse_reactions"] = list(label["adverse_reactions"])
                rec["adverse_reactions_source"] = {
                    **src, "replaced_interim": {"lang": prev.get("lang", "en"),
                                                "set_id": prev.get("set_id"),
                                                "fetched_at": prev.get("fetched_at"),
                                                "item_count": len(prev.get("items") or []) or None},
                }
                act["replaced"].append("adverse_reactions")
            else:
                act["kept"].append("adverse_reactions")

        reg = label.get("cn_registration") or {}
        if reg.get("approval_no") and not rec.get("approval_no"):
            rec["approval_no"] = reg["approval_no"]
            act["filled"].append("approval_no")
        rec["cn_registration"] = {
            "approval_no": reg.get("approval_no"),
            "brand_name": reg.get("brand_name"),
            "specification": reg.get("specification"),
            "dosage_form": reg.get("dosage_form"),
            "mah": reg.get("mah"),
            "manufacturer": reg.get("manufacturer"),
            "source_type": "official_label_text",
            "source_name": label["source_name"],
            "source_url": label["source_url"],
            "fetched_at": label["fetched_at"],
            "note": "注册类字段摘自说明书原文（批准文号/商品名/规格/持有人/生产企业），"
                    "不使用注册库字段；未在说明书中出现的项为 null。",
        }

        rec["label"] = label_block(label)
        act["filled"].append("label")

        if not rec.get("label_zh_source"):
            rec["label_zh_source"] = {
                "source_name": label["source_name"],
                "source_version": label["fetched_at"],
                "source_section": "说明书全文",
                "source_file": label.get("text_path"),
                "updated_at": label["fetched_at"][:10] if label["fetched_at"] else None,
            }
        else:
            act["kept"].append("label_zh_source(guideline)")

        rec["missing_fields"] = recompute_missing(rec)
        act["missing_after"] = list(rec["missing_fields"])
        return act

    for drug_id, label in sorted(primary.items()):
        rec = by_id.get(drug_id)
        if rec is None:
            meta = NEW_DRUGS.get(drug_id)
            if not meta:
                actions.append({"drug_id": drug_id, "generic_name": label["drug_name"],
                                "status": "skip_no_catalog_record"})
                continue
            tags = []
            for tag, kws in CANCER_TAG_RULES:
                if any(k in ind for ind in label["indications"] for k in kws) and tag not in tags:
                    tags.append(tag)
            rec = {
                "drug_id": drug_id,
                "generic_name": meta["generic_name"],
                "generic_name_en": meta["generic_name_en"],
                "brand_names": [],
                "atc_code": meta.get("atc_code"),
                "approval_no": None,
                "indications": None,
                "dosage": None,
                "contraindications": None,
                "adverse_reactions": None,
                "interactions": None,
                "drug_class": meta["drug_class"],
                "cancer_type": tags,
                "origin": "cn_label",
                "source": label["source_name"],
                "annotation": "2026-11-04 由官网说明书原文建档；癌种标签按说明书适应证字面匹配，"
                              "未做药理学推断。",
            }
            cat.append(rec)
            by_id[drug_id] = rec
            actions.append({"drug_id": drug_id, "generic_name": rec["generic_name"],
                            "status": "created", "label_key": label["key"]})
        actions.append(fill(rec, label, drug_id))

    # 未拿到说明书原文的品种：只重算 missing_fields，保持 null
    for rec in cat:
        if rec["drug_id"] not in primary:
            before = list(rec.get("missing_fields") or [])
            rec["missing_fields"] = recompute_missing(rec)
            if before != rec["missing_fields"]:
                actions.append({"drug_id": rec["drug_id"], "generic_name": rec["generic_name"],
                                "status": "recomputed_missing",
                                "missing_before": before,
                                "missing_after": rec["missing_fields"]})

    with open(CAT, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=2)
        f.write("\n")

    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    summary = {"filled": {}, "replaced": {}, "total": len(cat)}
    for a in actions:
        for f_ in a.get("filled", []):
            summary["filled"][f_] = summary["filled"].get(f_, 0) + 1
        for f_ in a.get("replaced", []):
            summary["replaced"][f_] = summary["replaced"].get(f_, 0) + 1
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "actions": actions}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[31] catalog=%d merged_drugs=%d" % (len(cat), sum(1 for a in actions if "missing_after" in a)))
    print("     filled:", summary["filled"])
    print("     replaced(EN→ZH):", summary["replaced"])
    for a in actions:
        if a.get("status") == "created":
            print("     created:", a["drug_id"], a["generic_name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
