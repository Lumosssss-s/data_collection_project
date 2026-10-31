"""P5：从 FDA/DailyMed 原始 XML 抽取「药物相互作用」段落（零 token，纯规则）。

背景：现有 5 份药品说明书 JSON 的 `interactions` 字段全部为 null —— 原始 XML 里有该
章节（LOINC code 34073-7 / 标题「DRUG INTERACTIONS」），但转换时没有抽取。

做法：
  1. 用 ElementTree 遍历 SPL 文档，按 code=34073-7 定位第 7 章（含其子章节）；
  2. 收集该章节下所有 <paragraph> 与 <tr> 的文本（子章节 7.1/7.2…一并纳入）；
  3. 归一空白、剔除纯交叉引用（「[see Drug Interactions (7)]」）与过短片段；
  4. 去重后写回 data/clean/drug_labels/*.json 的 interactions 字段（数组，最大 30 条）。

只补这一个字段，其余字段保持不动，保证 doc_hash / 溯源字段不被改写。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "drug_labels")
CLEAN_DIR = os.path.join(BASE_DIR, "data", "clean", "drug_labels")

INTERACTION_CODE = "34073-7"
MAX_ITEMS = 30
MIN_LEN = 15


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_text(node) -> str:
    """取节点内全部文本并归一空白。"""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _is_boilerplate(text: str) -> bool:
    """纯交叉引用 / 章节指引，无实质信息。"""
    stripped = re.sub(r"\[[^\]]*\]", "", text).strip(" .;:()")
    if len(stripped) < MIN_LEN:
        return True
    if re.fullmatch(r"(see|refer to)?\s*(drug interactions|section)?\s*\(?\d*\.?\d*\)?\.?", stripped.lower()):
        return True
    return False


def extract(xml_path: str) -> List[str]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return []

    items: List[str] = []
    seen = set()
    for sec in root.iter():
        if _local(sec.tag) != "section":
            continue
        codes = {c.get("code") for c in sec.iter() if _local(c.tag) == "code"}
        if INTERACTION_CODE not in codes:
            continue
        for node in sec.iter():
            if _local(node.tag) not in ("paragraph", "tr"):
                continue
            text = _iter_text(node)
            if not text or _is_boilerplate(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(text[:600])
            if len(items) >= MAX_ITEMS:
                break
        break  # 同一文档只取第一个匹配章节
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="P5：药品相互作用抽取")
    ap.add_argument("--raw-dir", default=RAW_DIR)
    ap.add_argument("--clean-dir", default=CLEAN_DIR)
    args = ap.parse_args()

    total, filled = 0, 0
    for name in sorted(os.listdir(args.clean_dir)):
        if not name.endswith(".json"):
            continue
        clean_path = os.path.join(args.clean_dir, name)
        xml_name = name.replace(".json", ".xml")
        xml_path = os.path.join(args.raw_dir, xml_name)
        records = json.load(open(clean_path, encoding="utf-8"))
        if not isinstance(records, list) or not records:
            continue
        items = extract(xml_path) if os.path.exists(xml_path) else []
        total += len(records)
        for rec in records:
            rec["interactions"] = items or None
        with open(clean_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        filled += 1 if items else 0
        print(f"{name:<28} interactions={len(items):>2}  " +
              (items[0][:60] if items else "（未抽到）"))

    print(f"\n处理 {total} 条药品记录，成功抽取 {filled} 份说明书")


if __name__ == "__main__":
    main()
