# -*- coding: utf-8 -*-
"""步骤9（guidelines）：A1 指南与规范原文录入 → data/clean/guidelines/

对 raw/guidelines/ 下的原生 PDF 执行需求清单 A1 要求的「文本可提取性自检」
（PyMuPDF 抽文本，空文本/乱码视为扫描件直接判不合格），计算 SHA-256，
按 document 字段结构生成元数据 JSON（G4 命名：guidelines_<范围>_<版本>_<日期>.json）。

新增指南时在 MANIFEST 里加一条即可，其余字段自动计算。
用法：python tools/9_guidelines_to_json.py
"""
import hashlib
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "data", "clean", "guidelines")

TODAY = "2026-10-25"
UPDATED_AT = "2026-10-25"

# 人工确认的元数据（title / issuer / publish_date 需按封面页、发布页复核）
# 说明：国家卫健委 2022 年版诊疗指南批次由 tools/10_fetch_nhc_guidelines.py 自动抓取并录入，
#      本表只保留需人工指定元数据的文档。
MANIFEST = [
    {
        "file_path": "raw/guidelines/all/new_antitumor_drug_principles_nhc_2025.pdf",
        "out_name": "guidelines_all_2025_20261025.json",
        "doc_id": "DOC-ALL-NHC-001",
        "title": "新型抗肿瘤药物临床应用指导原则（2025年版）",
        "doc_type": "guideline",
        "issuer": "中华人民共和国国家卫生健康委员会",
        "publish_date": "2025-01-01",
        "cancer_types": ["lung", "breast", "colorectal", "gastric", "thyroid"],
        "source_version": "2025",
        "license_note": "国家卫健委官网公开文件，公开可引用，引用需标注出处；仅限非商业竞赛使用。"
                        "PDF 仅标注 2025 年版、未标注具体发布日，publish_date 暂以年份起始日记，待医学审核员复核。",
    },
]

MIN_TEXT_CHARS = 1000   # 低于此值视为无有效文本层（扫描件/图片型 PDF）


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_text(path):
    """A1 文本可提取性自检：返回 (页数, 文本字符数)。

    PDF 用 PyMuPDF；DOCX 用 python-docx（DOCX 无页码概念，页数位返回 0）。
    """
    if path.lower().endswith(".docx"):
        import docx

        d = docx.Document(path)
        chars = sum(len(p.text) for p in d.paragraphs)
        chars += sum(len(cell.text) for t in d.tables for row in t.rows for cell in row.cells)
        return 0, chars

    import fitz

    doc = fitz.open(path)
    try:
        pages = doc.page_count
        chars = sum(len(page.get_text()) for page in doc)
    finally:
        doc.close()
    return pages, chars


def build_record(item):
    path = os.path.join(BASE, item["file_path"].replace("/", os.sep))
    if not os.path.exists(path):
        raise FileNotFoundError("缺少原文件：" + item["file_path"])

    pages, chars = check_text(path)
    if chars < MIN_TEXT_CHARS:
        raise ValueError("文本可提取性自检不通过（%s，%d 字符），疑似扫描件，退回不采" % (item["file_path"], chars))

    fname = os.path.basename(path)
    rec = {
        "doc_id": item["doc_id"],
        "title": item["title"],
        "doc_type": item["doc_type"],
        "issuer": item["issuer"],
        "publish_date": item["publish_date"],
        "cancer_types": item["cancer_types"],
        "license_note": item["license_note"],
        "file_path": item["file_path"],
        "doc_hash": sha256(path),
        "source_name": item["title"],
        "source_version": item["source_version"],
        "source_section": "全文",
        "source_file": fname,
        "updated_at": UPDATED_AT,
        "review_status": "draft",
        "reviewer": None,
        "review_date": None,
    }
    return rec, pages, chars


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    seen_hashes = {}

    for item in MANIFEST:
        rec, pages, chars = build_record(item)
        if rec["doc_hash"] in seen_hashes:
            raise ValueError("doc_hash 重复：%s 与 %s" % (item["file_path"], seen_hashes[rec["doc_hash"]]))
        seen_hashes[rec["doc_hash"]] = item["file_path"]

        out = os.path.join(OUT_DIR, item["out_name"])
        with open(out, "w", encoding="utf-8") as f:
            json.dump([rec], f, ensure_ascii=False, indent=2)

        print("%-14s %-40s %3d 页 %7d 字符  %s" % (rec["doc_id"], rec["title"], pages, chars, rec["doc_hash"][:12]))
        print("   ->", out)

    print("\n完成 %d 份指南录入，目录：%s" % (len(MANIFEST), OUT_DIR))


if __name__ == "__main__":
    main()
