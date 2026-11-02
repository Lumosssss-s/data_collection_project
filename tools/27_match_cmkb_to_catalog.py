# -*- coding: utf-8 -*-
"""tools/27_match_cmkb_to_catalog.py

把 26 号脚本抓到的 CMKB 药物目录（fetched/cmkb_drugs/drugs.json，2,724 条）
匹配到 A4 药单（data/clean/drug_labels/drug_catalog_v2.json，48 种），
评估 CMKB 的「禁忌症 / 药物相互作用」能补多少 A4 缺口。

只做匹配与缺口评估，**不把 CMKB 文本写进 data/clean/**：
CMKB 无开放许可（站点版权 © 中国医学科学院医学信息研究所/图书馆），
故匹配结果仅落 cache/drug_labels/ 作内部评估用。

匹配四级（逐级兜底，命中即停）：
  1. exact     去空白/标点/大小写后完全相同
  2. contains  一方包含另一方（取较长一侧，长度 ≥3，避免「铂」「钙」这类短名误命中）
  3. alias     ALIAS 表显式别名（人工维护，仅收录算法无法覆盖的写法）
  4. salt      去掉盐/酯类后缀（盐酸、二钠、甲磺酸盐……）后再比

产物：
  cache/drug_labels/cmkb_match_audit.json  逐药匹配结果 + 候选 + 缺口评估

用法：
  python tools/27_match_cmkb_to_catalog.py
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")
CMKB = os.path.join(BASE, "fetched", "cmkb_drugs", "drugs.json")
AUDIT_DIR = os.path.join(BASE, "cache", "drug_labels")
AUDIT = os.path.join(AUDIT_DIR, "cmkb_match_audit.json")

# 算法无法覆盖的写法（T-DM1 中文名不统一；英文缩写直接给中文名）
ALIAS = {
    "曲妥珠单抗-emtansine": ["恩美曲妥珠单抗", "曲妥珠单抗美坦新", "曲妥珠单抗-美坦新偶联物"],
    "非格司亭": ["重组人粒细胞集落刺激因子", "非格司亭"],
    "聚乙二醇非格司亭": ["聚乙二醇重组人粒细胞集落刺激因子", "培非格司亭"],
    # CMKB 药物库收录的是旧式音译名，与现行通用名不同
    "曲妥珠单抗": ["群司珠单抗"],
    "昂丹司琼": ["盐酸恩丹西酮", "恩丹西酮"],
}

SALT = ("二盐酸盐", "盐酸盐", "甲磺酸盐", "马来酸盐", "枸橼酸盐", "乳酸盐", "琥珀酸盐",
        "酒石酸盐", "醋酸盐", "磷酸盐", "硫酸盐", "二钠", "钠", "钾", "钙", "镁",
        "盐酸", "硫酸", "磷酸", "溴化物", "氯化物", "酯")


def norm(s):
    s = str(s or "")
    s = re.sub(r"[\s\u3000（）()\[\]【】\"'`·・,，。;；:：/／\\\-–—_]+", "", s)
    return s.strip().lower()


def strip_salt(s):
    for t in SALT:
        if s.endswith(t) and len(s) - len(t) >= 2:
            return s[: -len(t)]
    return s


def load(path, what):
    if not os.path.exists(path):
        sys.exit("缺少 %s：%s" % (what, path))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def match_one(name, cmkb_rows, cmkb_norm):
    raw = norm(name)
    if raw in cmkb_norm:
        return cmkb_rows[cmkb_norm[raw]], "exact"
    for a in ALIAS.get(name, []):
        if norm(a) in cmkb_norm:
            return cmkb_rows[cmkb_norm[norm(a)]], "alias"
    best = None
    for cn, idx in cmkb_norm.items():
        if len(raw) >= 3 and len(cn) >= 3 and (raw in cn or cn in raw):
            score = min(len(raw), len(cn)) / max(len(raw), len(cn))
            if best is None or score > best[0]:
                best = (score, idx, "contains")
    if best:
        return cmkb_rows[best[1]], "contains"
    raw2 = strip_salt(raw)
    if raw2 != raw and raw2 in cmkb_norm:
        return cmkb_rows[cmkb_norm[raw2]], "salt"
    for cn, idx in cmkb_norm.items():
        if strip_salt(cn) == raw2 and len(raw2) >= 3:
            return cmkb_rows[idx], "salt"
    return None, None


def has(v):
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return len(v) > 0


def main():
    catalog = load(CATALOG, "A4 药单")
    cmkb_rows = load(CMKB, "CMKB 抓取结果")
    cmkb_norm = {}
    for i, r in enumerate(cmkb_rows):
        cmkb_norm.setdefault(norm(r["generic_name_zh"]), i)

    items = []
    for drug in catalog:
        hit, how = match_one(drug["generic_name"], cmkb_rows, cmkb_norm)
        rec = {
            "drug_id": drug["drug_id"],
            "generic_name": drug["generic_name"],
            "catalog_fields_empty": [f for f in ("contraindications", "interactions")
                                     if not has(drug.get(f))],
        }
        if hit:
            fills = []
            for catalog_f, cmkb_f in (("contraindications", "contraindications"),
                                      ("interactions", "interactions")):
                if not has(drug.get(catalog_f)) and has(hit.get(cmkb_f)):
                    fills.append(catalog_f)
            rec.update({
                "status": "matched",
                "match_type": how,
                "cmkb_id": hit["cmkb_id"],
                "cmkb_name": hit["generic_name_zh"],
                "cmkb_drug_kind": hit["drug_kind"],
                "cmkb_indications": hit["indications"],
                "cmkb_contraindications": hit["contraindications"],
                "cmkb_interactions": hit["interactions"],
                "fills": fills,
            })
        else:
            rec.update({"status": "unmatched"})
        items.append(rec)

    matched = [i for i in items if i["status"] == "matched"]
    unmatched = [i["generic_name"] for i in items if i["status"] == "unmatched"]
    coverage = {
        "catalog_total": len(catalog),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "contraindications_fillable": sum(1 for i in matched if "contraindications" in i["fills"]),
        "interactions_fillable": sum(1 for i in matched if "interactions" in i["fills"]),
    }

    os.makedirs(AUDIT_DIR, exist_ok=True)
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump({
            "catalog": os.path.relpath(CATALOG, BASE).replace("\\", "/"),
            "cmkb": os.path.relpath(CMKB, BASE).replace("\\", "/"),
            "coverage": coverage,
            "unmatched": unmatched,
            "items": items,
            "note": "CMKB 内容仅作内部缺口评估，未写入 data/clean/；对外使用需授权",
        }, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("A4 药单 %d 种 → CMKB 命中 %d 种，未命中 %d 种"
          % (coverage["catalog_total"], coverage["matched"], coverage["unmatched"]))
    print("可补 禁忌 %d 条 / 相互作用 %d 条（仅统计 A4 当前为空且 CMKB 有值）"
          % (coverage["contraindications_fillable"], coverage["interactions_fillable"]))
    for i in items:
        if i["status"] == "matched":
            print("  [%-8s] %-22s → %-16s(%s) 补:%s"
                  % (i["match_type"], i["generic_name"], i["cmkb_name"],
                     i["cmkb_id"], ",".join(i["fills"]) or "-"))
    if unmatched:
        print("未命中：" + " / ".join(unmatched))
    print("审计写入 %s" % AUDIT)


if __name__ == "__main__":
    main()
