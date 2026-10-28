# -*- coding: utf-8 -*-
"""步骤4（pubmed_cancer）：读取 cache/pubmed_cancer/ → 生成对齐字段的 JSON 到 data/clean/corpus/pubmed_cancer/。

ID 规则：DOC-<癌种码>-PUB-<4位序号>（前缀 DOC 属需求清单 §0.5 允许前缀；PUB=PubMed 来源码）。
用法：在项目根目录执行（需先跑步骤3）
    python tools/4_pubmed_to_json.py
"""
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache", "pubmed_cancer")
OUT_DIR = os.path.join(BASE, "data", "clean", "corpus")
OUT = os.path.join(OUT_DIR, "cancer_literature_corpus.json")

SOURCE_TEXT = "PubMed-Cancer-NLP-Textual-Dataset（HuggingFace cyberpsych，apache-2.0，PubMed 癌症文献摘要）"

# cancer_type → ID 范围码
SCOPE = {"lung": "LUNG", "breast": "BREAST", "colorectal": "CRC", "gastric": "GAS"}
TODAY = "2026-10-24"


def main():
    with open(os.path.join(CACHE, "cleaned_records.json"), encoding="utf-8") as f:
        records = json.load(f)

    counters = Counter()
    out_records = []
    for rec in records:
        ctype = rec["cancer_type"]
        counters[ctype] += 1
        out_records.append({
            "doc_id": "DOC-%s-PUB-%04d" % (SCOPE[ctype], counters[ctype]),
            "pmid": rec["pmid"],
            "title": rec["title"],
            "abstract": rec["abstract"],
            "cancer_type": ctype,
            "lang": "en",
            "source": SOURCE_TEXT,
            "origin": "pubmed_cancer",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out_records, f, ensure_ascii=False, indent=2)

    print("总记录数:", len(out_records))
    print("癌种分布:", dict(Counter(r["cancer_type"] for r in out_records)))
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
