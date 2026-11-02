# -*- coding: utf-8 -*-
"""tools/21_a2_recommendation_extract.py

A2 结构化推荐条目抽取（批次一 · 肺癌试点）。

输入：raw/guidelines/lung/nhc2022_01_lung.pdf（原发性肺癌诊疗指南 2022 年版）
输出：data/clean/recommendations/recommendations_lung_20261028.json（顶层数组）
审计：cache/recommendations/a2_extract_audit.json（分节计数、跳过原因、证据分级说明）

方法：PyMuPDF 取文本 → 按「一、」/「（一）」重建章/节 breadcrumb → 按句切分 →
规则判定纳入（含推荐线索 + 诊疗动作）、排除（流行病学/表格/注/参考文献）→
按「；」拆分多条独立动作 → 推断 scenario / stage / biomarker → 映射 evidence_level。

口径与限制：
  - 只做规则抽取，不做 LLM 改写；recommendation_text 为原文整句摘录，verbatim=true。
  - 卫健委指南正文不带 CSCO/NCCN 式分级，按需求清单 §A2 映射表「未分级 → very_low /
    not_graded」，evidence_level_original 记 null；补 CACA/CSCO 指南后重跑可获得真实分级。
  - scenario 无法判定（不在 15 类枚举内）的句子直接跳过并计入审计，不做猜测。
  - stage / biomarker 无值写 null（G8），不写 []。

用法：
  python tools/21_a2_recommendation_extract.py            # 抽取并写盘
  python tools/21_a2_recommendation_extract.py --dry-run  # 只打印统计与样例
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
PDF = os.path.join(BASE, "raw", "guidelines", "lung", "nhc2022_01_lung.pdf")
OUT_DIR = os.path.join(BASE, "data", "clean", "recommendations")
OUT = os.path.join(OUT_DIR, "recommendations_lung_20261028_v3.json")
PREV = os.path.join(OUT_DIR, "recommendations_lung_20261028_v2.json")
AUDIT = os.path.join(BASE, "cache", "recommendations", "a2_extract_audit.json")

DOC_ID = "DOC-LUNG-NHC-001"
SOURCE = {
    "source_name": "原发性肺癌诊疗指南（2022年版）",
    "source_version": "2022",
    "source_file": "nhc2022_01_lung.pdf",
}
UPDATED_AT = "2026-10-28"

L1_RE = re.compile(r"^([一二三四五六七八九十]+)、\s*(.+)$")
L2_RE = re.compile(r"^（([一二三四五六七八九十]+)）\s*(.+)$")
DROP_RE = re.compile(r"^(\d{1,3}|第\s*\d+\s*页|[—\-]?\s*\d+\s*[—\-]?)$")

CUE_RE = re.compile(
    r"推荐|建议|首选|可选|可考虑|考虑|适用于|不推荐|不宜|禁忌|一线|二线|三线|"
    r"新辅助|辅助治疗|维持治疗|应当|应予|应行|应进行|应选择|应使用|应定期|应避免|"
    r"需行|需要|须"
)
ACTION_RE = re.compile(
    r"治疗|手术|切除|化疗|放疗|放射|靶向|免疫|筛查|检测|活检|分期|评估|随访|复查|"
    r"用药|剂量|方案|检查|清扫|照射"
)
EXCLUDE_RE = re.compile(
    r"发病率|死亡率|患病率|万例|构成比|参考文献|基金项目|通信作者|"
    r"^表\s*\d|^图\s*\d|见表|^注[:：]|资料来源"
)
TOO_LONG = 500

# 表格分支：正文中以「表N / 标题 / 表头 / 单元格逐行」排版的方案表（如「表4」二线方案）
TABLE_TITLE_RE = re.compile(r"^表\s*(\d{1,2})$")
TABLE_COLS = ("治疗方案", "剂量", "用药时间", "时间及周期")
SUPERSCRIPT_RE = re.compile(r"^\d{1,2}$")
DOSE_TAIL_RE = re.compile(r"mg/(?:m|kg)$")
CELL_STOP_RE = re.compile(r"[。；]$")
L3_RE = re.compile(r"^\d{1,2}[.．][^\d]")

SCENARIO_RULES = [
    ("treatment_neoadjuvant", ("新辅助", "术前化疗", "术前")),
    ("treatment_adjuvant", ("术后辅助", "辅助化疗", "辅助治疗", "辅助放疗")),
    ("treatment_first_line", ("一线", "初治", "首选")),
    ("treatment_second_line", ("二线",)),
    ("treatment_later", ("三线", "后线", "多线", "维持治疗")),
    ("targeted", ("靶向", "TKI", "EGFR-TKI", "ALK抑制剂")),
    ("immunotherapy", ("免疫治疗", "PD-1", "PD-L1", "免疫检查点")),
    ("radiotherapy", ("放疗", "放射治疗", "SBRT", "照射")),
    ("surgery", ("手术", "切除", "术式", "淋巴结清扫", "肺叶", "肺段")),
    ("screening", ("筛查", "低剂量", "LDCT", "高危人群")),
    ("staging", ("分期", "TNM", "AJCC")),
    ("diagnosis", ("诊断", "鉴别诊断", "活检", "病理", "检测", "影像", "PET", "CT")),
    ("supportive_care", ("支持治疗", "姑息", "止痛", "镇痛", "营养", "对症")),
    ("followup", ("随访", "复查")),
    ("rehab", ("康复",)),
]

# 这些二级章节属于 A3 疾病档案（病因/症状/体征），不作为 A2 推荐条目
SKIP_SECTIONS = ("危险因素", "临床表现", "体格检查", "病因")

STAGE_RE = re.compile(r"(Ⅰ|Ⅱ|Ⅲ|Ⅳ)[A-C]?期|\b(I|II|III|IV)[A-C]?\s*期")
STAGE_MAP = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV",
             "I": "I", "II": "II", "III": "III", "IV": "IV"}
BIOMARKER_RE = re.compile(
    r"(?<![A-Za-z-])(EGFR|ALK|ROS1|KRAS|NRAS|HRAS|BRAF|HER2|BRCA|MSI-H|dMMR|"
    r"PD-L1|TMB|HRD|NTRK|RET|MET|EBV)(?![A-Za-z])"
)


def norm_text(s):
    return re.sub(r"\s+", "", str(s or ""))


def join_lines(pairs):
    """合并折行。pairs 为 [(page, line)]，返回 (text, [(start_offset, page)])。"""
    out, spans = "", []
    for pno, ln in pairs:
        spans.append((len(out), pno))
        if not out:
            out = ln
        elif re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", ln):
            out += " " + ln
        else:
            out += ln
    return out, spans


def page_at(spans, offset):
    """按字符偏移取真实页码（跨页句子取起始页）。"""
    page = spans[0][1] if spans else None
    for start, pno in spans:
        if start <= offset:
            page = pno
        else:
            break
    return page


def split_sentences(text):
    """切句并保留每句在原文中的起始偏移，用于回溯页码。"""
    out = []
    for m in re.finditer(r"[^。！？]*[。！？]|[^。！？]+$", text):
        s = m.group(0).strip()
        if s:
            out.append((s, m.start()))
    return out


def clean_sentence(s):
    """去掉句首列表编号与「小标题：」前缀，避免把目录式文本当成推荐句。"""
    s = re.sub(r"^[（(]?\d{1,2}[）)]?\s*[.．、]?", "", s)
    s = re.sub(r"[（(]\d{1,2}[）)]", "", s)
    s = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", s)
    if "：" in s[:24]:
        head, tail = s.split("：", 1)
        if len(head) <= 20 and len(tail) >= 12:
            s = tail
    return s.strip()


def parse_blocks(path):
    doc = fitz.open(path)
    blocks, cur = [], None
    pages = doc.page_count
    for pno, page in enumerate(doc, 1):
        for raw in page.get_text().splitlines():
            line = raw.strip()
            if not line or DROP_RE.match(line):
                continue
            if L1_RE.match(line):
                cur = {"l1": line.rstrip("。．."), "l2": None, "page": pno, "lines": []}
                blocks.append(cur)
                continue
            if L2_RE.match(line):
                cur = {"l1": (cur or {}).get("l1", ""), "l2": line.rstrip("。．."),
                       "page": pno, "lines": []}
                blocks.append(cur)
                continue
            if cur is None:
                cur = {"l1": "", "l2": None, "page": pno, "lines": []}
                blocks.append(cur)
            cur["lines"].append((pno, line))
    return blocks, pages


def parse_tables(path):
    """解析四列方案表（治疗方案 / 剂量 / 用药时间 / 时间及周期）。

    返回 [{"table": "表4", "title": ..., "breadcrumb": ..., "rows": [(page, [4 cells])]}]
    说明：PDF 把表格逐单元格打散成行，剂量里的上标（如 75mg/m 后的 2）单独成行，
    这里按「剂量尾 + 纯数字」合并回 mg/m2。
    """
    doc = fitz.open(path)
    items = []
    for pno, page in enumerate(doc, 1):
        for raw in page.get_text().splitlines():
            line = raw.strip()
            if not line or line == str(pno):
                continue  # 页眉/页脚页码；纯数字的单元格（剂量上标）需保留
            if not line.isdigit() and DROP_RE.match(line):
                continue
            items.append((pno, line))

    tables, i, l1, l2 = [], 0, "", None
    while i < len(items):
        pno, line = items[i]
        if L1_RE.match(line):
            l1, l2 = line.rstrip("。．."), None
        elif L2_RE.match(line):
            l2 = line.rstrip("。．.")
        m = TABLE_TITLE_RE.match(line)
        if not m or i + 1 >= len(items):
            i += 1
            continue
        title = items[i + 1][1]
        j = i + 2
        if j + len(TABLE_COLS) > len(items) or \
                tuple(items[j + k][1] for k in range(len(TABLE_COLS))) != TABLE_COLS:
            i += 1
            continue
        j += len(TABLE_COLS)
        cells = []
        while j < len(items):
            p, v = items[j]
            if v in TABLE_COLS or v == title or TABLE_TITLE_RE.match(v):
                break
            if CELL_STOP_RE.search(v) or L3_RE.match(v) or L1_RE.match(v) or L2_RE.match(v):
                break
            if cells and DOSE_TAIL_RE.search(cells[-1][1]) and SUPERSCRIPT_RE.match(v):
                cells[-1] = (cells[-1][0], cells[-1][1] + v)
            else:
                cells.append((p, v))
            j += 1
        rows = [{"page": cells[k][0], "cells": [c[1] for c in cells[k:k + len(TABLE_COLS)]]}
                for k in range(0, len(cells) - len(cells) % len(TABLE_COLS), len(TABLE_COLS))]
        if rows:
            tables.append({"table": m.group(0), "title": title,
                           "breadcrumb": " / ".join([x for x in (l1, l2) if x]),
                           "rows": rows})
        i = j
    return tables


def infer_scenario(text):
    for name, kws in SCENARIO_RULES:
        for kw in kws:
            if kw in text:
                return name
    return None


def infer_stage(text):
    found = []
    for m in STAGE_RE.finditer(text):
        v = STAGE_MAP.get(m.group(1))
        if v and v not in found:
            found.append(v)
    order = ["0", "I", "II", "III", "IV"]
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
    """原文分级 → (evidence_level, rec_strength, evidence_level_original)。"""
    pairs = [
        (r"1A\s*类|Ⅰ级推荐", "high", "strong"),
        (r"1B\s*类", "high", "strong"),
        (r"2A\s*类|Ⅱ级推荐", "moderate", "weak"),
        (r"2B\s*类", "moderate", "weak"),
        (r"Ⅲ级推荐", "low", "weak"),
        (r"Category\s*1", "high", "strong"),
        (r"Category\s*2A", "moderate", "strong"),
    ]
    for pat, lvl, strength in pairs:
        m = re.search(pat, text)
        if m:
            return lvl, strength, m.group(0).replace(" ", "")
    return "very_low", "not_graded", None


def split_clauses(sent):
    """「；」连接的多个独立动作拆条；拆分后任一段不成立则保留整句。"""
    if "；" not in sent:
        return [sent]
    parts = [p.strip() for p in sent.split("；") if p.strip()]
    if len(parts) < 2:
        return [sent]
    if all(len(p) >= 12 and CUE_RE.search(p) and ACTION_RE.search(p) for p in parts):
        return [p if p.endswith("。") else p + "。" for p in parts]
    return [sent]


def build_record(idx, breadcrumb, scenario, text, page):
    lvl, strength, original = map_evidence(text)
    return {
        "rec_id": "REC-LUNG-NHC-%04d" % idx,
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
        "page": page,
        "source_name": SOURCE["source_name"],
        "source_version": SOURCE["source_version"],
        "source_section": breadcrumb,
        "source_file": SOURCE["source_file"],
        "updated_at": UPDATED_AT,
        "review_status": "draft",
        "reviewer": None,
        "review_date": None,
        "annotation": {
            "annotator": "rule-extract 21_a2_recommendation_extract.py",
            "date": UPDATED_AT,
            "status": "draft",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(PDF):
        sys.exit("缺少输入 PDF：%s" % PDF)

    blocks, pages = parse_blocks(PDF)
    records, seen = [], set()
    skipped = {}
    by_section = {}

    for b in blocks:
        breadcrumb = " / ".join([x for x in (b["l1"], b["l2"]) if x])
        if not breadcrumb:
            continue
        if b["l2"] and any(k in b["l2"] for k in SKIP_SECTIONS):
            skipped["section_belongs_to_a3"] = skipped.get("section_belongs_to_a3", 0) + 1
            continue
        text, spans = join_lines(b["lines"])
        for raw, offset in split_sentences(text):
            sent = clean_sentence(raw)
            raw_len = len(sent)
            if raw_len < 15:
                continue
            if EXCLUDE_RE.search(sent):
                skipped["background_or_table"] = skipped.get("background_or_table", 0) + 1
                continue
            if not CUE_RE.search(sent):
                skipped["no_recommendation_cue"] = skipped.get("no_recommendation_cue", 0) + 1
                continue
            if not ACTION_RE.search(sent):
                skipped["no_clinical_action"] = skipped.get("no_clinical_action", 0) + 1
                continue
            # 原句优先：clean_sentence 会剥掉「（2）二线药物治疗：」这类小标题前缀，
            # 先用未清洗的原句判场景，避免丢掉「二线」「术后放疗」等关键限定词
            scenario = infer_scenario(raw) or infer_scenario(sent) or infer_scenario(breadcrumb)
            if not scenario:
                skipped["scenario_unknown"] = skipped.get("scenario_unknown", 0) + 1
                continue
            for part in split_clauses(sent):
                if len(part) > TOO_LONG:
                    skipped["too_long"] = skipped.get("too_long", 0) + 1
                    continue
                key = norm_text(part)
                if key in seen:
                    skipped["duplicate"] = skipped.get("duplicate", 0) + 1
                    continue
                seen.add(key)
                records.append(build_record(len(records) + 1, breadcrumb, scenario,
                                            part, page_at(spans, offset)))
                by_section[breadcrumb] = by_section.get(breadcrumb, 0) + 1

    # 表格分支：表 4「非小细胞肺癌常用的二线治疗方案」等四列方案表
    tables = parse_tables(PDF)
    table_rows = 0
    for tb in tables:
        scenario = infer_scenario(tb["title"]) or infer_scenario(tb["breadcrumb"])
        if not scenario:
            skipped["table_scenario_unknown"] = skipped.get("table_scenario_unknown", 0) + 1
            continue
        for row in tb["rows"]:
            text = "，".join(row["cells"]) + "。"
            key = norm_text(text)
            if key in seen:
                skipped["duplicate"] = skipped.get("duplicate", 0) + 1
                continue
            seen.add(key)
            rec = build_record(len(records) + 1, tb["breadcrumb"], scenario,
                               text, row["page"])
            rec["annotation"]["extraction"] = "table_row"
            rec["annotation"]["table"] = "%s %s" % (tb["table"], tb["title"])
            rec["annotation"]["table_cells"] = row["cells"]
            records.append(rec)
            table_rows += 1
            by_section[tb["breadcrumb"]] = by_section.get(tb["breadcrumb"], 0) + 1

    audit = {
        "generated_at": UPDATED_AT,
        "input_pdf": os.path.relpath(PDF, BASE),
        "pages": pages,
        "blocks": len(blocks),
        "records": len(records),
        "table_rows": table_rows,
        "tables": [{"table": t["table"], "title": t["title"],
                    "breadcrumb": t["breadcrumb"], "rows": len(t["rows"])} for t in tables],
        "prev_file": os.path.relpath(PREV, BASE) if os.path.exists(PREV) else None,
        "by_scenario": {},
        "by_breadcrumb": dict(sorted(by_section.items(),
                                     key=lambda kv: -kv[1])[:20]),
        "skipped": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "evidence_note": (
            "卫健委指南正文无 CSCO/NCCN 式分级，按 §A2 映射表统一记 very_low / not_graded，"
            "evidence_level_original=null；补入 CACA/CSCO 指南后重跑可取到真实分级。"
        ),
        "extraction_note": (
            "规则抽取：原文整句摘录（verbatim=true），未做 LLM 改写；"
            "scenario 无法判定者直接跳过，未做猜测。"
        ),
    }
    for r in records:
        audit["by_scenario"][r["scenario"]] = audit["by_scenario"].get(r["scenario"], 0) + 1

    print("pages=%d blocks=%d records=%d" % (pages, len(blocks), len(records)))
    print("by_scenario:", json.dumps(audit["by_scenario"], ensure_ascii=False))
    print("skipped:", json.dumps(audit["skipped"], ensure_ascii=False))
    for r in records[:5]:
        print("-", r["rec_id"], r["scenario"], r["stage"], r["biomarker"],
              r["recommendation_text"][:60])

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
