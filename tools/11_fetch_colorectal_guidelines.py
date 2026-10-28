# -*- coding: utf-8 -*-
"""步骤11（guidelines）：结直肠癌诊疗规范（2015 年版）+ 结直肠癌筛查与早诊早治方案（2024 年版）抓取录入。

两个来源（用户指定，均为国家卫健委官网）：
1. 2015 年版诊疗规范：通知页 https://www.nhc.gov.cn/yzygj/c100068/201510/922e2426eb02416e8344715cab601f2e.shtml
   附件为 .doc（可直连下载）。python-docx 读不了 .doc，故用 Word COM 转成 .docx 后入库：
   原始 .doc 与转换件 .docx 同目录保留，`doc_hash` 对应 file_path（.docx）。
2. 2024 年版筛查方案：通知页 https://www.nhc.gov.cn/ylyjs/gzdt/202408/42f43b5f0c4c4ebe90c78ee127959b92.shtml
   该通知**没有附件文件**，正文直接内嵌在网页（页面有 WAF，脚本无法留存原始字节）；
   因此以官网正文快照（同目录 .txt）为输入，逐字转录为 .docx 后入库，并在 note 中标注。

用法：
    python tools/11_fetch_colorectal_guidelines.py
"""
import os
import subprocess

import docx as docxlib
import requests

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(TOOLS_DIR)
RAW = os.path.join(BASE, "raw", "guidelines", "colorectal")
PS1 = os.path.join(TOOLS_DIR, "word_to_docx.ps1")

DOC_DATE_TAG = "20261025"
ISSUER_2015 = "国家卫生计生委医政医管局"
ISSUER_2024 = "中华人民共和国国家卫生健康委员会办公厅"

URL_2015_NOTICE = ("https://www.nhc.gov.cn/yzygj/c100068/201510/"
                   "922e2426eb02416e8344715cab601f2e.shtml")
URL_2015_FILE = ("https://www.nhc.gov.cn/yzygj/c100068/201510/"
                 "922e2426eb02416e8344715cab601f2e/files/1732864173138_55436.doc")
URL_2024_NOTICE = ("https://www.nhc.gov.cn/ylyjs/gzdt/202408/"
                   "42f43b5f0c4c4ebe90c78ee127959b92.shtml")

DOC_2015 = "nhc2015_01_colorectal"
SNAP_2024 = "nhc2024_02_colorectal_screening"

NOTE_2015 = (
    "国家卫生计生委医政医管局公开文件（国卫医医护便函〔2015〕292号，2015-10-21 公开），"
    "公开可引用，引用需标注出处；仅限非商业竞赛使用。原件为 .doc 附件，经 Word 转换为 .docx 入库，"
    "原始 .doc 与转换件同目录保留，doc_hash 对应转换件。原文：%s" % URL_2015_NOTICE
)
NOTE_2024 = (
    "国家卫生健康委办公厅公开文件（国卫办医急函〔2024〕281号，2024-08-27 公开），"
    "公开可引用，引用需标注出处；仅限非商业竞赛使用。该通知附件为网页正文、未提供附件文件，"
    "本件由官网正文逐字转录为 .docx，正文快照 %s.txt 同目录保留，doc_hash 对应转录件。原文：%s"
    % (SNAP_2024, URL_2024_NOTICE)
)


def load_mod(name, filename):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_doc(url, dest):
    """下载 .doc（OLE2 复合文档），校验文件头。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 50 * 1024:
        print("[cached] %s" % dest)
        return
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": URL_2015_NOTICE},
                     timeout=120)
    r.raise_for_status()
    if not r.content.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("返回内容不是 OLE2 .doc（首字节 %r）" % r.content[:4])
    with open(dest, "wb") as f:
        f.write(r.content)
    print("[downloaded] %s (%d 字节)" % (dest, len(r.content)))


def doc_to_docx(src, dst):
    """Word COM 转 docx（tools/word_to_docx.ps1）。"""
    if os.path.exists(dst) and os.path.getsize(dst) > 10 * 1024:
        print("[cached] %s" % dst)
        return
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1, src, dst]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("Word 转换失败：%s" % ((p.stderr or p.stdout or "").strip()[:300]))
    print("[converted] %s" % dst)


def txt_to_docx(src, dst):
    """把正文快照 .txt 逐字转录为 .docx（空行分段）。"""
    with open(src, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.read().splitlines()]
    d = docxlib.Document()
    for ln in lines:
        if ln:
            d.add_paragraph(ln)
    d.save(dst)
    print("[transcribed] %s (%d 段)" % (dst, sum(1 for ln in lines if ln)))


def main():
    os.makedirs(RAW, exist_ok=True)
    g9 = load_mod("g9", "9_guidelines_to_json.py")

    # 1) 2015 年版诊疗规范：.doc → .docx
    doc_path = os.path.join(RAW, DOC_2015 + ".doc")
    docx_2015 = os.path.join(RAW, DOC_2015 + ".docx")
    fetch_doc(URL_2015_FILE, doc_path)
    doc_to_docx(doc_path, docx_2015)

    # 2) 2024 年版筛查方案：正文快照 → .docx
    snap = os.path.join(RAW, SNAP_2024 + ".txt")
    if not os.path.exists(snap):
        raise FileNotFoundError("缺少 2024 年版正文快照：" + snap)
    docx_2024 = os.path.join(RAW, SNAP_2024 + ".docx")
    txt_to_docx(snap, docx_2024)

    # 3) 生成 document 元数据
    items = [
        {
            "file_path": "raw/guidelines/colorectal/%s.docx" % DOC_2015,
            "out_name": "guidelines_colorectal_2015_%s.json" % DOC_DATE_TAG,
            "doc_id": "DOC-CRC-NHC-001",
            "title": "结直肠癌诊疗规范（2015年版）",
            "doc_type": "standard",
            "issuer": ISSUER_2015,
            "publish_date": "2015-10-21",
            "cancer_types": ["colorectal"],
            "source_version": "2015",
            "license_note": NOTE_2015,
        },
        {
            "file_path": "raw/guidelines/colorectal/%s.docx" % SNAP_2024,
            "out_name": "guidelines_colorectal_2024_%s.json" % DOC_DATE_TAG,
            "doc_id": "DOC-CRC-NHC-002",
            "title": "结直肠癌筛查与早诊早治方案（2024年版）",
            "doc_type": "standard",
            "issuer": ISSUER_2024,
            "publish_date": "2024-08-27",
            "cancer_types": ["colorectal"],
            "source_version": "2024",
            "license_note": NOTE_2024,
        },
    ]

    print()
    for item in items:
        rec, pages, chars = g9.build_record(item)
        out = os.path.join(BASE, "data", "clean", "guidelines", item["out_name"])
        import json

        with open(out, "w", encoding="utf-8") as f:
            json.dump([rec], f, ensure_ascii=False, indent=2)
        print("%-18s %-28s %6d 字符  %s" % (rec["doc_id"], rec["title"][:24], chars, rec["doc_hash"][:12]))
        print("   ->", out)


if __name__ == "__main__":
    main()
