# -*- coding: utf-8 -*-
"""步骤3（pubmed_cancer）：清洗 raw/pubmed_cancer/ 的 4 个癌种 CSV → 中间产物到 cache/pubmed_cancer/。

清洗内容：PMID 去重（含跨文件）、空/过短摘要剔除、空白规范化、保留原始字段。
用法：在项目根目录执行
    python tools/3_clean_pubmed_cancer.py
"""
import csv
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw", "pubmed_cancer")      # 输入原文件（数据集 pubmed_cancer）
CACHE = os.path.join(BASE, "cache", "pubmed_cancer")  # 中间产物缓存（按数据集分目录）

# 文件名 → 受控词表 cancer_type（需求清单 §6.1；本数据集无 thyroid 文件）
FILE_MAP = {
    "lung_cancer_samples.csv": "lung",
    "breast_cancer_samples.csv": "breast",
    "colon_cancer_samples.csv": "colorectal",
    "gastric_cancer_samples.csv": "gastric",
}

MIN_ABSTRACT_LEN = 50  # 过短摘要视为无效


def normalize(text):
    """空白规范化：合并连续空白、去首尾。"""
    return re.sub(r"\s+", " ", text or "").strip()


def main():
    os.makedirs(CACHE, exist_ok=True)
    records = []
    seen_pmids = {}
    stats = {t: {"raw": 0, "dup": 0, "short": 0, "kept": 0} for t in FILE_MAP.values()}

    for fname, ctype in FILE_MAP.items():
        path = os.path.join(RAW, fname)
        with open(path, encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                stats[ctype]["raw"] += 1
                pmid = (row.get("PMID") or "").strip()
                title = normalize(row.get("Title"))
                abstract = normalize(row.get("Abstract"))
                if not pmid:
                    continue
                if pmid in seen_pmids:            # 跨文件/文件内去重
                    stats[ctype]["dup"] += 1
                    continue
                if len(abstract) < MIN_ABSTRACT_LEN:
                    stats[ctype]["short"] += 1
                    continue
                seen_pmids[pmid] = ctype
                records.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "cancer_type": ctype,
                })
                stats[ctype]["kept"] += 1

    out = os.path.join(CACHE, "cleaned_records.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    print("总保留记录:", len(records))
    for t, s in stats.items():
        print("  %-11s raw=%d dup=%d short=%d kept=%d" % (t, s["raw"], s["dup"], s["short"], s["kept"]))
    print("DONE ->", out)


if __name__ == "__main__":
    main()
