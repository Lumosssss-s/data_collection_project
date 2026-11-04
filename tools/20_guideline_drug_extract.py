# -*- coding: utf-8 -*-
"""tools/20_guideline_drug_extract.py

从《新型抗肿瘤药物临床应用指导原则（2025年版）》PDF 抽取中文适应证、用法用量
（标准剂量 + 调整）与药物相互作用，回补 data/clean/drug_labels/drug_catalog_v2.json。

背景：NMPA 数据查询页（如 inbox 的「国家药品监督管理局数据查询.pdf」）只提供注册信息
（注册证号/批准文号、产品名称、商品名、剂型、规格、持有人、生产厂商、药品本位码），
不含说明书四段正文；故中文适应证与用法用量改以卫健委《新型抗肿瘤药物临床应用指导原则
（2025年版）》为主来源，禁忌与不良反应频率仍保留 openFDA 英文 interim（19 号脚本）。

抽取范围：仅「呼吸系统肿瘤用药 / 消化系统肿瘤用药 / 乳腺癌用药」三个章节，且适应证条目
须命中该药 cancer_type 对应的癌种关键词（需求清单 §A4⑦：适应证只保留 5 癌种子集）；
「※」标注的境外获批、国内未获批适应证不纳入。

依赖：PyMuPDF（fitz）
输入：raw/guidelines/all/new_antitumor_drug_principles_nhc_2025.pdf
输出：data/clean/drug_labels/drug_catalog_v2.json（indications / dosage / interactions / label_zh_source）
审计：cache/drug_labels/guideline_extract.json

用法：
  python tools/20_guideline_drug_extract.py            # 抽取并回写
  python tools/20_guideline_drug_extract.py --dry-run  # 只输出审计，不回写
"""
import argparse
import json
import os
import re
import sys

import fitz

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(BASE, "raw", "guidelines", "all", "new_antitumor_drug_principles_nhc_2025.pdf")
CAT = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")
AUDIT = os.path.join(BASE, "cache", "drug_labels", "guideline_extract.json")

SOURCE = {
    "source_name": "新型抗肿瘤药物临床应用指导原则（2025年版）",
    "source_version": "2025年版",
    "source_file": "raw/guidelines/all/new_antitumor_drug_principles_nhc_2025.pdf",
}

# 只取与 A4 癌种子集相关章节；泌尿/皮肤/血液/妇科/中枢等章节不入 A4
# 2026-11-04 扩展：新增「甲状腺癌用药」「头颈部肿瘤用药（甲状腺适应证）」「骨与软组织肿瘤用药」，
# 以补齐甲状腺癌与 general 类药品的中文适应证/用法用量缺口。
CHAPTER_TYPES = {
    "呼吸系统肿瘤用药": {"lung"},
    "消化系统肿瘤用药": {"colorectal", "gastric"},
    "乳腺癌用药": {"breast"},
    "甲状腺癌用药": {"thyroid"},
    "头颈部肿瘤用药": {"thyroid"},
    "骨与软组织肿瘤用药": {"general"},
}

CANCER_KEYWORDS = {
    "lung": ["肺癌", "NSCLC", "非小细胞肺", "小细胞肺"],
    "breast": ["乳腺"],
    "colorectal": ["结直肠", "结肠", "直肠"],
    "gastric": ["胃癌", "胃腺癌", "胃食管结合部", "胃或胃食管"],
    "thyroid": ["甲状腺"],
}

# 指导原则用名与项目 canonical 不一致的个别药
ALIAS = {
    "曲妥珠单抗-emtansine": "恩美曲妥珠单抗",
}

HEAD_RE = re.compile(r"^([零一二三四五六七八九十百]+)、\s*(\S.*)$")
STOP_MARKERS = ("合理用药要点", "制剂与规格", "注意事项", "禁忌", "不良反应", "药物相互作用")


def norm(s):
    s = s.replace("－", "-").replace("—", "-").replace("–", "-")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"[\s\-_·]", "", s).lower()


def is_cjk(ch):
    return "\u4e00" <= ch <= "\u9fff"


def smart_join(lines):
    """中文按行直接拼接，中英文边界补空格，避免跨行断词。"""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
            continue
        prev, nxt = out[-1], ln[0]
        if is_cjk(prev) or is_cjk(nxt) or prev in "，。；：、）》”%”" or nxt in "，。；：、）》”":
            out += ln
        else:
            out += " " + ln
    # 修复跨页/跨行造成的剂量单位断裂（如 mg/m 2）
    out = re.sub(r"(mg|μg|ug)\s*/\s*(m\s*2|kg|mL|ml|L)\b",
                 lambda m: "%s/%s" % (m.group(1), m.group(2).replace(" ", "")), out)
    return out


def load_pages():
    if not os.path.exists(PDF):
        raise SystemExit("缺少指导原则 PDF：%s" % PDF)
    doc = fitz.open(PDF)
    pages = []
    for i, page in enumerate(doc, 1):
        lines = []
        for ln in page.get_text("text").splitlines():
            ln = ln.strip()
            if not ln or re.fullmatch(r"\d{1,4}", ln):  # 去页码/空白
                continue
            lines.append(ln)
        pages.append((i, lines))
    doc.close()
    return pages


def build_sections(pages):
    """按章节 → 药名标题切分，返回 section 列表。"""
    flat = []
    for pno, lines in pages:
        for ln in lines:
            flat.append((pno, ln))

    sections = []
    chapter = None
    cur = None
    for idx, (pno, ln) in enumerate(flat):
        if ln in CHAPTER_TYPES:
            chapter = ln
            continue
        m = HEAD_RE.match(ln)
        if m and "…" not in ln and "……" not in ln:
            title = m.group(2).strip()
            zh = re.split(r"(?<=[\u4e00-\u9fff）)])(?=[A-Za-z])", title, 1)[0].strip()
            if not zh or zh in ("病理组织学确诊后方可使用", "部分需靶点检测后方可使用",
                                "严格遵循适应证用药", "合理选择适宜的抗肿瘤药物",
                                "特殊情况下的药物合理使用", "重视药物相关性不良反应"):
                continue
            if cur:
                cur["end"] = idx
                sections.append(cur)
            cur = {"chapter": chapter, "num": m.group(1), "title": title, "zh": zh,
                   "page": pno, "start": idx, "end": len(flat)}
            continue
    if cur:
        sections.append(cur)

    for sec in sections:
        sec["lines"] = [ln for _, ln in flat[sec["start"] + 1:sec["end"]]]
    return sections


def split_items(text):
    """把适应证文本拆成条目：优先按编号，其次按句号。"""
    text = re.sub(r"^适应证[:：]?\s*", "", text)
    text = text.strip()
    if not text:
        return []
    numbered = re.split(r"(?:^|(?<=[。；;]))\s*(?=\d{1,2}[.．、])", text)
    if len(numbered) <= 1:
        numbered = [x for x in re.split(r"(?<=。)", text) if x.strip()]
    out = []
    for x in numbered:
        x = re.sub(r"^\s*\d{1,2}[.．、]\s*", "", x).strip()
        x = x.strip("；;，, ")
        if len(x) < 8:
            continue
        if "※" in x or "尚未获批" in x or "未在中国获批" in x or "日本厚生劳动省" in x:
            continue
        out.append(x)
    return out


def extract_indications(sec):
    lines = sec["lines"]
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("适应证"):
            start = i
            break
    if start is None:
        return []
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if any(ln.startswith(m) for m in STOP_MARKERS):
            break
        block.append(ln)
    return split_items(smart_join(block))


def points_block(sec):
    lines = sec["lines"]
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("合理用药要点"):
            start = i
            break
    if start is None:
        return ""
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if any(ln.startswith(m) for m in ("注意事项", "禁忌", "不良反应", "药物相互作用")):
            break
        block.append(ln)
    return re.sub(r"^合理用药要点[:：]?", "", smart_join(block))


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=。)", text) if s.strip()]


def point_items(pts):
    """按「1. 2. 3.」切分合理用药要点，剔除 ※ 境外获批/国内未获批条目。"""
    text = re.sub(r"^合理用药要点[:：]?", "", pts)
    parts = re.split(r"(?<=[。；;])\s*(?=\d{1,2}[.．、])", text)
    out = []
    for p in parts:
        p = re.sub(r"^\s*\d{1,2}[.．、]\s*", "", p).strip()
        if not p:
            continue
        if "※" in p or "日本厚生劳动省" in p or "尚未获批" in p or "未在中国获批" in p:
            continue
        out.append(p)
    return out


def extract_dosage(sec):
    pts = points_block(sec)
    adj_re = re.compile(r"减量|下调|降低.*剂量|减少.*剂量|调整.*剂量|漏服|停药|停用|中断|减至")
    std_re = re.compile(r"推荐剂量|剂量为|剂量是|用法为|初始剂量|负荷剂量|维持剂量|给药剂量|每次.*mg|每日.*mg|mg/次|mg/m2|mg/kg")
    standard, adjustment = [], []
    for item in point_items(pts):
        for s in sentences(item):
            s = s.strip()
            if not s:
                continue
            compact = re.sub(r"\s+", "", s)  # 跨行断词（如 mg/m 2）不影响匹配
            is_std, is_adj = bool(std_re.search(compact)), bool(adj_re.search(compact))
            if is_std and (not is_adj or re.match(r"^(推荐剂量|剂量为|剂量是|用法为|初始剂量|负荷剂量)", compact)):
                if s not in standard:
                    standard.append(s)
            if is_adj and s not in adjustment:
                adjustment.append(s)
    return {
        "standard": "".join(standard[:2]) or None,
        "adjustment": "".join(adjustment[:3]) or None,
    }, pts


def extract_interactions(sec, pts):
    out = []
    for item in point_items(pts):
        for s in sentences(item):
            s = s.strip()
            if re.search(r"联合使用|合用|相互作用|CYP3A|CYP2|P-gp|BCRP|抑制剂|诱导剂", s) and len(s) >= 8:
                out.append(s)
    return out[:6]


def pick_sections(sections, rec):
    wanted = set(rec.get("cancer_type") or [])
    names = {norm(rec["generic_name"])}
    alias = ALIAS.get(rec["generic_name"])
    if alias:
        names.add(norm(alias))
    picked = []
    for sec in sections:
        if norm(sec["zh"]) not in names:
            continue
        if sec["chapter"] not in CHAPTER_TYPES:
            continue
        if not (CHAPTER_TYPES[sec["chapter"]] & wanted):
            continue
        picked.append(sec)
    # 主癌种章节优先，保证 dosage 取到与主适应证一致的段落
    primary = (rec.get("cancer_type") or [None])[0]
    picked.sort(key=lambda s: 0 if primary in CHAPTER_TYPES[s["chapter"]] else 1)
    return picked


def filter_indications(items, rec):
    types = rec.get("cancer_type") or []
    if "general" in types:
        return items
    kws = []
    for t in types:
        kws.extend(CANCER_KEYWORDS.get(t, []))
    if not kws:
        return []
    return [x for x in items if any(k in x for k in kws)]


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只输出审计，不回写 drug_catalog_v2.json")
    args = ap.parse_args()

    pages = load_pages()
    sections = build_sections(pages)
    catalog = json.load(open(CAT, encoding="utf-8"))

    audit = {"generated_at": None, "source_file": SOURCE["source_file"],
             "sections_total": len(sections), "records": []}
    applied = skipped = 0

    for rec in catalog:
        picked = pick_sections(sections, rec)
        item = {"drug_id": rec["drug_id"], "generic_name": rec["generic_name"],
                "cancer_type": rec.get("cancer_type"), "status": "", "sections": []}
        if not picked:
            item["status"] = "skip_no_section"
            audit["records"].append(item)
            skipped += 1
            continue

        indications, dosage, interactions, used = [], {"standard": None, "adjustment": None}, [], []
        for sec in picked:
            inds = filter_indications(extract_indications(sec), rec)
            if inds:
                indications.extend(x for x in inds if x not in indications)
                used.append(sec)
                if not dosage["standard"]:
                    d, pts = extract_dosage(sec)
                    dosage = d
                    interactions = extract_interactions(sec, pts)
        if not indications:
            item["status"] = "skip_no_indication"
            item["sections"] = [s["zh"] for s in picked]
            audit["records"].append(item)
            skipped += 1
            continue

        if rec.get("label") and rec["label"].get("status") == "zh_from_nmpa":
            item["status"] = "skip_manual_override"
            audit["records"].append(item)
            skipped += 1
            continue

        rec["indications"] = indications
        rec["dosage"] = dosage
        rec["interactions"] = interactions or None
        rec["label_zh_source"] = {
            "source_name": SOURCE["source_name"],
            "source_version": SOURCE["source_version"],
            "source_section": "；".join("%s·%s、%s" % (s["chapter"], s["num"], s["zh"]) for s in used),
            "source_file": SOURCE["source_file"],
            "updated_at": "2026-11-04",
        }
        item["status"] = "applied"
        item["sections"] = [s["zh"] for s in used]
        item["pages"] = [s["page"] for s in used]
        item["indications"] = len(indications)
        item["dosage_has_standard"] = bool(dosage["standard"])
        item["dosage_has_adjustment"] = bool(dosage["adjustment"])
        item["interactions"] = len(interactions)
        audit["records"].append(item)
        applied += 1

    audit["applied"] = applied
    audit["skipped"] = skipped
    from datetime import datetime
    audit["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_json(AUDIT, audit)
    if not args.dry_run:
        save_json(CAT, catalog)

    print("指导原则章节 %d 个；回补 %d 条，跳过 %d 条" % (len(sections), applied, skipped))
    for r in audit["records"]:
        if r["status"] != "applied":
            print("  [%s] %s" % (r["status"], r["generic_name"]))
    print("审计：%s" % AUDIT)
    print("提示：回写后请重跑 python tools/19_fetch_openfda_labels.py --offline 刷新 missing_fields")


if __name__ == "__main__":
    main()
