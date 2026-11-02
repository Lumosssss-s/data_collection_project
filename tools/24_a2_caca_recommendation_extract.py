# -*- coding: utf-8 -*-
"""tools/24_a2_caca_recommendation_extract.py

A2 结构化推荐条目抽取（批次一 · 肺癌 · CACA 官方英译版）。

输入：raw/guidelines/lung/caca2024_lung_en.pdf
      CACA guidelines for holistic integrative management of lung cancer
      Holistic Integrative Oncology (2024) 3:10, DOI 10.1007/s44178-024-00069-w
      Open Access, CC BY 4.0
输出：data/clean/recommendations/recommendations_lung_caca_20261028.json
审计：cache/recommendations/a2_caca_extract_audit.json

与 21 号脚本（卫健委中文指南）的区别：
  - 条目为**英文原文**（annotation.lang = "en"），不并入中文文件，供跨语言检索；
  - CACA 全文无任何证据分级（Level of evidence / Category / Grade / 1A / 2A 命中均为 0），
    按需求清单 §A2 映射表「原文无分级 → very_low / not_graded」处理，不做伪造；
  - 只抽 "Main recommendations:" 段内的编号/段落条目，遇到下一个章节标题或 Notes 即止。

用法：
  python tools/24_a2_caca_recommendation_extract.py            # 抽取并写盘
  python tools/24_a2_caca_recommendation_extract.py --dry-run  # 只打印统计与样例
"""
import argparse
import json
import os
import re
import sys

try:
    import fitz
except ImportError:
    sys.exit("缺少 PyMuPDF：pip install pymupdf")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(BASE, "raw", "guidelines", "lung", "caca2024_lung_en.pdf")
OUT_DIR = os.path.join(BASE, "data", "clean", "recommendations")
OUT = os.path.join(OUT_DIR, "recommendations_lung_caca_20261028.json")
AUDIT = os.path.join(BASE, "cache", "recommendations", "a2_caca_extract_audit.json")

DOC_ID = "DOC-LUNG-CACA-001"
SOURCE = {
    "source_name": "CACA guidelines for holistic integrative management of lung cancer "
                   "(official English version)",
    "source_version": "2024",
    "source_file": "caca2024_lung_en.pdf",
}
UPDATED_AT = "2026-10-28"

HEAD_RE = re.compile(r"^(\d(?:\.\d{1,2}){0,2})[\s\u2002]+([A-Z(].*)$")
CONT_RE = re.compile(r"^[A-Z][A-Za-z0-9\-–,' ]{0,40}$")
ITEM_RE = re.compile(r"^\(?\d{1,2}\)[\s\u2002]+")
STOP_RE = re.compile(r"^(Notes?|Table\s*\d|Figure\s*\d|Fig\.\s*\d)\b", re.I)
MAIN_REC = "Main recommendations"

MIN_LEN = 20
MAX_LEN = 500

SCENARIO_RULES = [
    ("treatment_neoadjuvant", ("neoadjuvant", "preoperative", "pre-operative")),
    ("treatment_adjuvant", ("adjuvant",)),
    ("treatment_first_line", ("first-line", "first line", "initial treatment",
                              "treatment-naive", "treatment naive")),
    ("treatment_second_line", ("second-line", "second line")),
    ("treatment_later", ("third-line", "third line", "later-line", "maintenance")),
    ("targeted", ("targeted", "tki", "tyrosine kinase inhibitor")),
    ("immunotherapy", ("immunotherapy", "pd-1", "pd-l1", "immune checkpoint")),
    ("radiotherapy", ("radiotherapy", "radiation", "sbrt", "sabr", "port")),
    ("surgery", ("surgery", "surgical", "resection", "lobectomy", "segmentectomy",
                 "lymph node dissection")),
    ("screening", ("screening", "ldct", "low-dose")),
    ("staging", ("staging", "tnm", "ajcc")),
    ("diagnosis", ("diagnosis", "biopsy", "pathological", "pathology", "molecular testing",
                   "imaging", "pet")),
    ("supportive_care", ("palliative", "supportive care", "tcm", "traditional chinese medicine")),
    ("followup", ("follow-up", "follow up", "followup")),
    ("rehab", ("rehabilitation",)),
]

BIOMARKER_RE = re.compile(
    r"(?<![A-Za-z-])(EGFR|ALK|ROS1|KRAS|NRAS|HRAS|BRAF|HER2|BRCA|MSI-H|dMMR|"
    r"PD-L1|TMB|HRD|NTRK|RET|MET|EBV)(?![A-Za-z])"
)
STAGE_RE = re.compile(r"\bstage\s+(I|II|III|IV)[A-C]?\b", re.I)


def norm_line(s):
    """统一特殊空白与连字符，便于匹配。"""
    s = s.replace("\x07", "").replace("\u2002", " ").replace("\xa0", " ")
    s = s.replace("\u2010", "-").replace("\u2011", "-")
    return re.sub(r"[ \t]+", " ", s).strip()


def collect_lines(path):
    doc = fitz.open(path)
    out = []
    for pno, page in enumerate(doc, 1):
        for raw in page.get_text().splitlines():
            s = norm_line(raw)
            if not s or s == "Page %d of %d" % (pno, doc.page_count):
                continue
            if s.startswith("Wang and Society of Lung Cancer"):
                continue
            out.append((pno, s))
    return out


def join_block(lines):
    """合并折行：行尾连字符直接拼词，其余按空格拼接。"""
    text = ""
    for ln in lines:
        if text.endswith("-"):
            text = text[:-1] + ln.lstrip()
        elif not text:
            text = ln
        else:
            text += " " + ln
    return re.sub(r"\s+", " ", text).strip()


def split_items(lines):
    """按 1) / (1) 编号切分条目；编号前的段首文字单独成条。"""
    items, buf = [], []
    for ln in lines:
        if ITEM_RE.match(ln):
            if buf:
                items.append(buf)
            buf = [ITEM_RE.sub("", ln)]
        else:
            buf.append(ln)
    if buf:
        items.append(buf)
    return items


def infer_scenario(text):
    low = text.lower()
    # 肺癌文本中的 ER/PR 是缓解评估（partial response），不是受体，故 BIOMARKER_RE 不含 ER/PR；
    # 中医药（TCM）无独立场景枚举，按最接近的 supportive_care 归类
    if "tcm" in low or "traditional chinese medicine" in low:
        return "supportive_care"
    for name, kws in SCENARIO_RULES:
        for kw in kws:
            if kw in low:
                return name
    return None


def infer_stage(text):
    found = []
    for m in STAGE_RE.finditer(text):
        v = m.group(1).upper()
        if v not in found:
            found.append(v)
    order = ["I", "II", "III", "IV"]
    found.sort(key=lambda x: order.index(x))
    return found or None


def infer_biomarker(text):
    found = []
    for m in BIOMARKER_RE.finditer(text):
        v = m.group(1)
        if v not in found:
            found.append(v)
    return found or None


def map_evidence(text):
    """§A2 映射：CACA 英译版全文无分级，命中不到即 very_low / not_graded。"""
    pairs = [
        (r"\b1A\b", "high", "strong"),
        (r"\b1B\b", "high", "strong"),
        (r"\b2A\b", "moderate", "weak"),
        (r"\b2B\b", "moderate", "weak"),
        (r"Category\s*1\b", "high", "strong"),
    ]
    for pat, lvl, strength in pairs:
        m = re.search(pat, text)
        if m:
            return lvl, strength, m.group(0)
    return "very_low", "not_graded", None


def match_heading(line):
    """返回 (编号, 标题) 或 None；排除作者单位、统计量等数字开头的正文行。"""
    m = HEAD_RE.match(line)
    if not m:
        return None
    title = m.group(2).strip()
    if "," in title or len(line) > 120:
        return None
    return m.group(1), title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(PDF):
        sys.exit("缺少输入 PDF：%s" % PDF)

    lines = collect_lines(PDF)
    stack = []             # 当前章节栈 [(编号, 标题)]，用于拼真实 breadcrumb
    records, seen = [], set()
    skipped = {}
    by_section, blocks = {}, 0

    i = 0
    while i < len(lines):
        pno, line = lines[i]
        head = match_heading(line)
        if head:
            num, title = head
            # 标题折行：如「... of stage」+「I-IIIB LC」
            k = i + 1
            while k < len(lines) and not match_heading(lines[k][1]) \
                    and not STOP_RE.match(lines[k][1]) \
                    and not ITEM_RE.match(lines[k][1]) \
                    and not title.endswith(":") and CONT_RE.match(lines[k][1]) \
                    and len(lines[k][1].split()) <= 6:
                title += " " + lines[k][1]
                k += 1
            while stack and not num.startswith(stack[-1][0] + "."):
                stack.pop()
            stack.append((num, title.rstrip(":：")))
            i = k
            continue
        if not line.startswith(MAIN_REC):
            i += 1
            continue

        blocks += 1
        start = pno
        breadcrumb = " / ".join("%s %s" % (n, t) for n, t in stack[-2:])
        buf = []
        j = i + 1
        while j < len(lines):
            _, v = lines[j]
            if match_heading(v) or STOP_RE.match(v):
                break
            buf.append(v)
            j += 1

        for chunk in split_items(buf):
            text = join_block(chunk)
            if text.endswith(":"):
                skipped["label_fragment"] = skipped.get("label_fragment", 0) + 1
                continue
            if not text.endswith((".", "!", "?")):
                skipped["incomplete_tail"] = skipped.get("incomplete_tail", 0) + 1
                continue
            if len(text) < MIN_LEN:
                skipped["too_short"] = skipped.get("too_short", 0) + 1
                continue
            if len(text) > MAX_LEN:
                skipped["too_long"] = skipped.get("too_long", 0) + 1
                continue
            scenario = infer_scenario(text) or infer_scenario(breadcrumb)
            if not scenario:
                skipped["scenario_unknown"] = skipped.get("scenario_unknown", 0) + 1
                continue
            key = re.sub(r"\s+", " ", text).lower()
            if key in seen:
                skipped["duplicate"] = skipped.get("duplicate", 0) + 1
                continue
            seen.add(key)
            lvl, strength, original = map_evidence(text)
            records.append({
                "rec_id": "REC-LUNG-CACA-%04d" % (len(records) + 1),
                "doc_id": DOC_ID,
                "cancer_type": "lung",
                "breadcrumb": breadcrumb,
                "scenario": scenario,
                "stage": infer_stage(text),
                "biomarker": infer_biomarker(text),
                "population": None,
                "recommendation_text": text,
                "verbatim": True,
                "evidence_level": lvl,
                "evidence_level_original": original,
                "rec_strength": strength,
                "refs": None,
                "page": start,
                "source_name": SOURCE["source_name"],
                "source_version": SOURCE["source_version"],
                "source_section": breadcrumb,
                "source_file": SOURCE["source_file"],
                "updated_at": UPDATED_AT,
                "review_status": "draft",
                "reviewer": None,
                "review_date": None,
                "annotation": {
                    "annotator": "rule-extract 24_a2_caca_recommendation_extract.py",
                    "date": UPDATED_AT,
                    "status": "draft",
                    "lang": "en",
                    "note": "官方英译版原文，暂无官方中文全文对应段，跨语言检索用；未做翻译改写",
                },
            })
            by_section[breadcrumb] = by_section.get(breadcrumb, 0) + 1
        i = max(j, i + 1)

    by_scenario = {}
    for r in records:
        by_scenario[r["scenario"]] = by_scenario.get(r["scenario"], 0) + 1

    audit = {
        "generated_at": UPDATED_AT,
        "input_pdf": os.path.relpath(PDF, BASE),
        "pages": fitz.open(PDF).page_count,
        "main_recommendation_blocks": blocks,
        "records": len(records),
        "by_scenario": dict(sorted(by_scenario.items(), key=lambda kv: -kv[1])),
        "by_breadcrumb": dict(sorted(by_section.items(), key=lambda kv: -kv[1])[:20]),
        "skipped": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "lang": "en",
        "evidence_note": (
            "CACA 官方英译版全文检索 Level of evidence / Category / Grade / 1A / 2A 均 0 处，"
            "无任何证据分级，按 §A2「原文无分级 → very_low / not_graded」兜底，"
            "evidence_level_original=null；不伪造分级。"
        ),
        "extraction_note": (
            "仅抽 'Main recommendations:' 段内条目，遇下一章节标题或 Notes/Table/Figure 即止；"
            "原文整句摘录（verbatim=true），折行连字符已还原，未做翻译或改写。"
        ),
    }

    print("pages=%d blocks=%d records=%d" % (audit["pages"], blocks, len(records)))
    print("by_scenario:", json.dumps(audit["by_scenario"], ensure_ascii=False))
    print("skipped:", json.dumps(audit["skipped"], ensure_ascii=False))
    for r in records[:5]:
        print("-", r["rec_id"], r["scenario"], r["stage"], r["biomarker"],
              r["recommendation_text"][:70])

    if args.dry_run:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("written:", os.path.relpath(OUT, BASE))


if __name__ == "__main__":
    main()
