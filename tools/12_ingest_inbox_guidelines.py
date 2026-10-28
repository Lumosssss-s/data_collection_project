# -*- coding: utf-8 -*-
"""步骤12（guidelines）：inbox 待分类指南 → external/nccn/<癌种>/ → data/clean/guidelines/

处理用户新放入 inbox/ 的 NCCN 指南：按癌种归档到 external/nccn/（**非交付物，不进 raw/**），
复用 9 号脚本的文本自检与 SHA-256，按癌种分组合并写入元数据 JSON（G4 命名，版本位加 nccn 前缀以区分来源）。

NCCN 版权保留、禁止再分发，故原件不随竞赛交付；元数据仅用于著录与引用，引用须用其官方格式。
新增文件时在 MANIFEST 加一条即可。用法：python tools/12_ingest_inbox_guidelines.py
"""
import glob
import importlib.util
import json
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(BASE, "inbox")
EXT_ROOT = os.path.join(BASE, "external", "nccn")
OUT_DIR = os.path.join(BASE, "data", "clean", "guidelines")
CACHE_DIR = os.path.join(BASE, "cache", "guidelines")

TODAY = "2026-10-25"
ACCESSED = "October 25, 2026"
ISSUER = "National Comprehensive Cancer Network (NCCN)"


def load_tool9():
    path = os.path.join(BASE, "tools", "9_guidelines_to_json.py")
    spec = importlib.util.spec_from_file_location("g9", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def citation(name, version):
    return ("Referenced with permission from the NCCN Clinical Practice Guidelines in Oncology (NCCN Guidelines®) "
            "for %s V.%s. © National Comprehensive Cancer Network, Inc. 2026. All rights reserved. "
            "Accessed %s. To view the most recent and complete version of the guideline, go online to NCCN.org."
            % (name, version, ACCESSED))


def license_note(name, version):
    return ("【非交付物】NCCN Guidelines®（Version %s）版权归 National Comprehensive Cancer Network（NCCN）所有，"
            "PDF 首页声明 \"may not be reproduced in any form without the express written permission of NCCN\"。"
            "原件不随竞赛交付，已存放于 external/nccn/（仅项目内部评审参考）。"
            "报告/演示提及 NCCN 推荐意见时必须使用官方引用格式：%s "
            "并绝对禁止复制核心内容：Algorithm 流程图、表格、图表及大段 Discussion 文本不得进入知识库、论文或演示文稿。"
            % (version, citation(name, version)))


# 人工确认的归档与元数据（标题/发布日期取自 PDF 首页版本行）
MANIFEST = [
    {
        "inbox_name": "nscl.pdf", "raw_name": "nccn2026_nsclc.pdf", "cancer": "lung",
        "out_name": "guidelines_lung_nccn2026_20261025.json",
        "doc_id": "DOC-LUNG-NCCN-001",
        "title": "NCCN Guidelines®: Non-Small Cell Lung Cancer（Version 9.2026）",
        "publish_date": "2026-09-22", "source_version": "9.2026",
        "cancer_types": ["lung"],
    },
    {
        "inbox_name": "sclc.pdf", "raw_name": "nccn2027_sclc.pdf", "cancer": "lung",
        "out_name": "guidelines_lung_nccn2026_20261025.json",
        "doc_id": "DOC-LUNG-NCCN-002",
        "title": "NCCN Guidelines®: Small Cell Lung Cancer（Version 1.2027）",
        "publish_date": "2026-07-01", "source_version": "1.2027",
        "cancer_types": ["lung"],
    },
    {
        "inbox_name": "lung_screening.pdf", "raw_name": "nccn2027_lung_screening.pdf", "cancer": "lung",
        "out_name": "guidelines_lung_nccn2026_20261025.json",
        "doc_id": "DOC-LUNG-NCCN-003",
        "title": "NCCN Guidelines®: Lung Cancer Screening（Version 1.2027）",
        "publish_date": "2026-10-02", "source_version": "1.2027",
        "cancer_types": ["lung"],
    },
    {
        "inbox_name": "breast.pdf", "raw_name": "nccn2026_breast.pdf", "cancer": "breast",
        "out_name": "guidelines_breast_nccn2026_20261025.json",
        "doc_id": "DOC-BREAST-NCCN-001",
        "title": "NCCN Guidelines®: Breast Cancer（Version 9.2026）",
        "publish_date": "2026-10-22", "source_version": "9.2026",
        "cancer_types": ["breast"],
    },
    {
        "inbox_name": "colon.pdf", "raw_name": "nccn2026_colon.pdf", "cancer": "colorectal",
        "out_name": "guidelines_colorectal_nccn2026_20261025.json",
        "doc_id": "DOC-CRC-NCCN-001",
        "title": "NCCN Guidelines®: Colon Cancer（Version 2.2026）",
        "publish_date": "2026-04-07", "source_version": "2.2026",
        "cancer_types": ["colorectal"],
    },
    {
        "inbox_name": "rectal.pdf", "raw_name": "nccn2026_rectal.pdf", "cancer": "colorectal",
        "out_name": "guidelines_colorectal_nccn2026_20261025.json",
        "doc_id": "DOC-CRC-NCCN-002",
        "title": "NCCN Guidelines®: Rectal Cancer（Version 2.2026）",
        "publish_date": "2026-04-07", "source_version": "2.2026",
        "cancer_types": ["colorectal"],
    },
    {
        "inbox_name": "gastric.pdf", "raw_name": "nccn2026_gastric.pdf", "cancer": "gastric",
        "out_name": "guidelines_gastric_nccn2026_20261025.json",
        "doc_id": "DOC-GAS-NCCN-001",
        "title": "NCCN Guidelines®: Gastric Cancer（Version 4.2026）",
        "publish_date": "2026-09-16", "source_version": "4.2026",
        "cancer_types": ["gastric"],
    },
    {
        "inbox_name": "thyroid.pdf", "raw_name": "nccn2026_thyroid.pdf", "cancer": "thyroid",
        "out_name": "guidelines_thyroid_nccn2026_20261025.json",
        "doc_id": "DOC-THY-NCCN-001",
        "title": "NCCN Guidelines®: Thyroid Carcinoma（Version 2.2026）",
        "publish_date": "2026-06-02", "source_version": "2.2026",
        "cancer_types": ["thyroid"],
    },
]

# 官方引用格式要求填英文指南全名（见 citation()）
NCCN_NAMES = {
    "DOC-LUNG-NCCN-001": "Non-Small Cell Lung Cancer",
    "DOC-LUNG-NCCN-002": "Small Cell Lung Cancer",
    "DOC-LUNG-NCCN-003": "Lung Cancer Screening",
    "DOC-BREAST-NCCN-001": "Breast Cancer",
    "DOC-CRC-NCCN-001": "Colon Cancer",
    "DOC-CRC-NCCN-002": "Rectal Cancer",
    "DOC-GAS-NCCN-001": "Gastric Cancer",
    "DOC-THY-NCCN-001": "Thyroid Carcinoma",
}


def move_to_external(item):
    """inbox/<原名> → external/nccn/<癌种>/<归档名>；已归档则跳过，内容冲突则报错。"""
    src = os.path.join(INBOX, item["inbox_name"])
    dst_dir = os.path.join(EXT_ROOT, item["cancer"])
    dst = os.path.join(dst_dir, item["raw_name"])

    if os.path.exists(src):
        os.makedirs(dst_dir, exist_ok=True)
        if os.path.exists(dst):
            raise ValueError("目标已存在且 inbox 仍有同名文件，请先确认：%s" % dst)
        shutil.move(src, dst)
        print("外部归档 %-20s -> %s" % (item["inbox_name"], os.path.relpath(dst, BASE)))
    elif os.path.exists(dst):
        print("已归档 %-20s -> %s（跳过移动）" % (item["inbox_name"], os.path.relpath(dst, BASE)))
    else:
        raise FileNotFoundError("inbox 与 external/nccn 均未找到：%s" % item["inbox_name"])
    return dst


def recorded_hashes(skip=()):
    hashes = {}
    for f in glob.glob(os.path.join(OUT_DIR, "*.json")):
        if os.path.basename(f) in skip:
            continue
        for rec in json.load(open(f, encoding="utf-8")):
            hashes[rec["doc_hash"]] = rec["doc_id"]
    return hashes


def main():
    g9 = load_tool9()
    os.makedirs(CACHE_DIR, exist_ok=True)
    known = recorded_hashes(skip={item["out_name"] for item in MANIFEST})
    groups = {}
    audit = []

    for item in MANIFEST:
        move_to_external(item)
        rec_item = {
            "file_path": "external/nccn/%s/%s" % (item["cancer"], item["raw_name"]),
            "out_name": item["out_name"],
            "doc_id": item["doc_id"],
            "title": item["title"],
            "doc_type": "guideline",
            "issuer": ISSUER,
            "publish_date": item["publish_date"],
            "cancer_types": item["cancer_types"],
            "source_version": item["source_version"],
            "license_note": license_note(NCCN_NAMES[item["doc_id"]], item["source_version"]),
        }
        rec, pages, chars = g9.build_record(rec_item)

        if rec["doc_hash"] in known:
            raise ValueError("doc_hash 与已有记录重复：%s 已存在于 %s" % (item["raw_name"], known[rec["doc_hash"]]))
        known[rec["doc_hash"]] = rec["doc_id"]

        groups.setdefault(item["out_name"], []).append(rec)
        audit.append({"doc_id": rec["doc_id"], "file_path": rec["file_path"],
                      "doc_hash": rec["doc_hash"], "pages": pages, "chars": chars})
        print("%-18s %3d 页 %8d 字符  %s" % (rec["doc_id"], pages, chars, rec["doc_hash"][:12]))

    for out_name, recs in groups.items():
        recs.sort(key=lambda r: r["doc_id"])
        out = os.path.join(OUT_DIR, out_name)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=2)
        print("-> %s（%d 条）" % (out, len(recs)))

    manifest_path = os.path.join(CACHE_DIR, "nccn_2026_documents.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print("\n完成 %d 份 NCCN 指南入库，清单：%s" % (len(MANIFEST), manifest_path))


if __name__ == "__main__":
    main()
