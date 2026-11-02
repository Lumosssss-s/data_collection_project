# -*- coding: utf-8 -*-
"""ATC 码 ↔ 药名 中文/英文对照 → 回补术语表 drug 条目的 atc / en_name。

输入：
  fetched/atc/atc_oncology.csv         # 15 号脚本抓取（WHO L01/L02/L03/H02/H03/M05/A11/A12 591 条，未经加工）
  data/clean/terminology/terminology_cancer.json   # 需回补的术语表
  data/clean/drug_labels/drug_catalog_v2.json          # 48 种药（generic_name + generic_name_en）

输出：
  data/clean/terminology/terminology_cancer.json  （原地更新 drug 条目的 atc / en_name / mapping_status）
  data/clean/drug_labels/drug_catalog_v2.json        （追加 atc_code / atc_parent 字段）
  fetched/atc/zh_en_inn.json                     （中文 → INN 人工对照表，随抓取结果留痕）

运行：python tools/16_atc_mapping.py
"""
import os
import csv
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATC_CSV = os.path.join(BASE, "fetched", "atc", "atc_oncology.csv")
ZH_EN = os.path.join(BASE, "fetched", "atc", "zh_en_inn.json")
TERM = os.path.join(BASE, "data", "clean", "terminology", "terminology_cancer.json")
CAT = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")

# ---------------------------------------------------- 手工中文 → INN 对照表
# 只覆盖 5 癌种术语表 drug 里 catalog 未收录的药 + 拼写差异项。
# 注意：药物类别名/短语（双膦酸盐、糖皮质激素、维生素D、钙片 等）已在 13 号脚本
#       DRUG_CLASS_DROP 中过滤，不会进入 A5，因此此处无需占位。
ZH_TO_INN = {
    "他莫西芬": "tamoxifen",                  # 他莫昔芬 别名
    "雷洛昔芬": "raloxifene",                 # SERM，L02BA02
    "德尼单抗": "denosumab",                  # 抗 RANKL 单抗，M05BX04
    "长春新碱": "vincristine",                 # L01CA01
    "泼尼松": "prednisone",                    # 糖皮质激素通用名
    "强的松龙": "prednisolone",               # 泼尼松龙 别名
    "阿霉素": "doxorubicin",                  # 多柔比星 别名
}


def load_atc():
    """返回 (exact, contains) 两层索引，以及 (code → row) 供打印。"""
    exact, rows = {}, {}
    with open(ATC_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = r["name_en"].strip().lower()
            exact[key] = r
            rows[r["code"]] = r
    return exact, rows


def lookup(atc_exact, inn):
    """INN（lowercase）→ ATC 行；先精确，再包含 fallback（如 LEVOTHYROXINE → levothyroxine sodium）。"""
    k = inn.strip().lower()
    if k in atc_exact:
        return atc_exact[k]
    for full, row in atc_exact.items():
        if k in full or full in k:
            return row
    return None


def main():
    with open(TERM, encoding="utf-8") as f:
        terms = json.load(f)
    with open(CAT, encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_zh_to_en = {r["generic_name"]: r["generic_name_en"].strip() for r in catalog}

    atc_exact, atc_rows = load_atc()

    hits, miss, skip = 0, 0, 0
    for t in terms:
        if t["category"] != "drug":
            continue
        zh = t["canonical"]

        # 1) 优先查 catalog 拿 generic_name_en
        if zh in catalog_zh_to_en:
            inn = catalog_zh_to_en[zh].lower()
            src = "drug_catalog"
        elif zh in ZH_TO_INN:
            inn = ZH_TO_INN[zh]
            src = "zh_to_inn"
        else:
            inn = None
            src = None

        if inn is None:
            skip += 1
            continue

        row = lookup(atc_exact, inn)
        if row is None:
            miss += 1
            print("  MISS", zh, "→", inn)
            continue

        t["atc"] = row["code"]
        t["en_name"] = row["name_en"]
        t["mapping_status"] = "confirmed"
        hits += 1
        print("  HIT  %-14s → %s %s (%s)" % (zh, row["code"], row["name_en"], row["parent"]))

    # catalog 也顺手补 atc_code 字段
    for r in catalog:
        zh = r["generic_name"]
        inn = r["generic_name_en"].strip().lower()
        row = lookup(atc_exact, inn)
        r["atc_code"] = row["code"] if row else None
        r["atc_parent"] = row["parent"] if row else None

    with open(TERM, "w", encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False, indent=2)
    with open(CAT, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    with open(ZH_EN, "w", encoding="utf-8") as f:
        json.dump(ZH_TO_INN, f, ensure_ascii=False, indent=2)

    print("\n=== 合计：HIT %d / MISS %d / SKIP（类别名/短语）%d ===" % (hits, miss, skip))
    print("已回写：", TERM)
    print("已更新：", CAT)
    print("对照表：", ZH_EN)


if __name__ == "__main__":
    main()
