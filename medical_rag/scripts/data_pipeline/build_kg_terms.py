"""从 kgdrug 子图抽取术语增量（零 token）。

用途：kgdrug 是 2018 年 gStore 图谱产物，639 条关系、46 个药物全是头孢/激素/中成药
（无任何抗肿瘤药），不能用于 A2 推荐或 A4 药品；但其中的疾病名与症状名可以作为
A5 术语表的种子词，用于口语化查询改写的同义词素材。

本脚本只输出术语种子文件，不写入主数据、不改变检索行为：
  - 疾病实体：肺癌 / 非小细胞肺癌 / 大肠癌 / 结肠癌 / 直肠癌 / 乙状结肠癌 / 肛管癌 …
  - 症状实体：咯血 / 咳痰 / 便血 / 腹部肿块 / 消瘦 …

过滤规则：
  1. 只保留 cancer_type ∈ {lung, colorectal}（本项目锁定的两个癌种）；
  2. 丢弃药物实体（该库药物与肿瘤治疗无实质关联，进词表会污染）；
  3. 丢弃空串、纯数字、长度 > 30 的短语（长句不是术语）；
  4. 同名去重，保留首次出现的癌种归属。

用法：
  python scripts/data_pipeline/build_kg_terms.py \
      --src e:/兴智杯/kg/kgdrug/kg_cancer_subgraph.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 种子文件放在脚本目录而非 data/clean：它不是契约内的 A5 数据（字段与 term schema 不同），
# 放进 data/clean/terminology 会被 V-01 按 term schema 校验而报「canonical 缺失」。
OUT_PATH = os.path.join(BASE_DIR, "scripts", "data_pipeline", "seeds", "kg_terms_seed.json")
DEFAULT_SRC = r"e:/兴智杯/kg/kgdrug/kg_cancer_subgraph.json"
TARGET_CANCERS = {"lung", "colorectal"}
MAX_TERM_LEN = 30


def _is_clean_term(name: str) -> bool:
    if not name or not name.strip():
        return False
    if len(name) > MAX_TERM_LEN:
        return False
    if re.fullmatch(r"[\d\W_]+", name):
        return False
    return True


def build(src: str) -> List[Dict]:
    with open(src, encoding="utf-8") as f:
        relations = json.load(f)

    seen: Dict[str, Dict] = {}
    for rel in relations:
        if rel.get("cancer_type") not in TARGET_CANCERS:
            continue
        head_type = (rel.get("head") or {}).get("type")
        name = (rel.get("head") or {}).get("name", "")
        # 症状实体出现在 tail；疾病实体出现在 head
        if rel.get("relation") == "has_symptom":
            name = (rel.get("tail") or {}).get("name", "")
            category = "symptom"
        elif head_type == "disease":
            category = "disease"
        else:
            continue  # 药物实体不入词表
        if not _is_clean_term(name) or name in seen:
            continue
        seen[name] = {
            "term": name,
            "category": category,
            "cancer_type": rel["cancer_type"],
            "synonyms": [],
            "source": "kgdrug(2018, gStore)",
            "review_status": "draft",
        }
    return sorted(seen.values(), key=lambda x: (x["category"], x["cancer_type"], x["term"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="kgdrug 术语增量抽取")
    parser.add_argument("--src", default=DEFAULT_SRC, help="kg_cancer_subgraph.json 路径")
    parser.add_argument("--out", default=OUT_PATH, help="输出术语种子文件")
    args = parser.parse_args()

    terms = build(args.src)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False, indent=2)

    print(f"术语种子 {len(terms)} 条 -> {args.out}")
    print("category:", dict(Counter(t["category"] for t in terms)))
    print("cancer:", dict(Counter(t["cancer_type"] for t in terms)))
    for t in terms:
        print(f"  [{t['category']}/{t['cancer_type']}] {t['term']}")


if __name__ == "__main__":
    main()
