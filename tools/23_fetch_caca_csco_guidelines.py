# -*- coding: utf-8 -*-
"""tools/23_fetch_caca_csco_guidelines.py

A1 补源（CACA / CSCO 中文权威指南）。

现状核查（2026-10-28 实测）：
  - CACA 中文全文：cacaguidelines.cacakp.com 页面明示「下载指南请先完成登录」，需会员，脚本不可得；
  - CSCO 指南：人民卫生出版社付费电子书（人卫助手 / 扫码购买），脚本不可得；
  - 中华医学会肺癌临床诊疗指南（2024 版）：中华医学杂志全文页仅 721 个中文字符（摘要页），全文需订阅。
故本脚本不伪造、不拼接替代全文，改为三条可核查的落库路径：
  1. CACA 肺癌指南官方英译版全文（Springer HIO，Open Access CC BY 4.0，44 页）→ 可入库、可交付；
  2. CACA 官方中文摘要（caca.org.cn，官方发布，含摘要与全文链接）→ 转录 .docx，非指南全文；
  3. CSCO 非小细胞肺癌诊疗指南 2025 → 仅著录书目元数据，正文未采集（file_path=null）。

产物：
  raw/guidelines/lung/caca2024_lung_en.pdf             英译版全文
  raw/guidelines/lung/caca2024_lung_zh_abstract.docx   官方中文摘要（转录）
  data/clean/guidelines/guidelines_lung_caca2024_20261028.json   2 条（CACA-001 / CACA-002）
  data/clean/guidelines/guidelines_lung_csco2025_20261028.json   1 条（CSCO-001）
  cache/guidelines/caca_csco_20261028.json             下载 / 转录 / 校验审计

用法：
  python tools/23_fetch_caca_csco_guidelines.py
  python tools/23_fetch_caca_csco_guidelines.py --force   # 重新下载与转录
"""
import argparse
import hashlib
import html
import json
import os
import re
import ssl
import sys
import urllib.request

try:
    import fitz
except ImportError:
    sys.exit("缺少 PyMuPDF：pip install pymupdf")

try:
    from docx import Document
except ImportError:
    sys.exit("缺少 python-docx：pip install python-docx")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_LUNG = os.path.join(BASE, "raw", "guidelines", "lung")
EN_PDF = os.path.join(RAW_LUNG, "caca2024_lung_en.pdf")
ZH_DOCX = os.path.join(RAW_LUNG, "caca2024_lung_zh_abstract.docx")
OUT_CACA = os.path.join(BASE, "data", "clean", "guidelines",
                        "guidelines_lung_caca2024_20261028.json")
OUT_CSCO = os.path.join(BASE, "data", "clean", "guidelines",
                        "guidelines_lung_csco2025_20261028.json")
AUDIT = os.path.join(BASE, "cache", "guidelines", "caca_csco_20261028.json")

EN_PDF_URL = "https://link.springer.com/content/pdf/10.1007/s44178-024-00069-w.pdf"
ZH_PAGE_URL = "http://www.caca.org.cn/system/2024/03/12/030083281.shtml"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
UPDATED_AT = "2026-10-28"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def download_pdf(force):
    if os.path.exists(EN_PDF) and not force:
        return "reused"
    data = fetch(EN_PDF_URL)
    if not data.startswith(b"%PDF-"):
        sys.exit("下载内容不是 PDF：%s" % EN_PDF_URL)
    os.makedirs(RAW_LUNG, exist_ok=True)
    with open(EN_PDF, "wb") as f:
        f.write(data)
    return "downloaded"


def strip_tags(raw):
    """HTML → 按行文本；页面为 GBK 编码。"""
    text = raw.decode("gbk", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def extract_abstract(lines):
    """截取「中国肺癌整合诊治指南」正文段到「全文浏览链接」之间，含关键词校验。"""
    start = end = None
    for i, ln in enumerate(lines):
        if start is None and ln.startswith("中国肺癌整合诊治指南"):
            start = i
        elif start is not None and ln.startswith("全文浏览链接"):
            end = i
            break
    if start is None or end is None:
        sys.exit("官网摘要页结构变动：未定位到正文边界，请人工核查 %s" % ZH_PAGE_URL)
    body = lines[start:end]
    joined = "".join(body)
    for kw in ("肺癌", "非小细胞肺癌", "小细胞肺癌"):
        if kw not in joined:
            sys.exit("摘要正文缺少关键词「%s」，疑似抓取到错误页面" % kw)
    return body


def build_docx(body, force):
    if os.path.exists(ZH_DOCX) and not force:
        return "reused"
    doc = Document()
    doc.add_heading(body[0], level=1)
    for ln in body[1:]:
        doc.add_paragraph(ln)
    os.makedirs(RAW_LUNG, exist_ok=True)
    doc.save(ZH_DOCX)
    return "transcribed"


def docx_stats(path):
    doc = Document(path)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return {"paragraphs": len(paras), "chars": sum(len(p) for p in paras)}


def pdf_stats(path):
    d = fitz.open(path)
    chars = sum(len(p.get_text()) for p in d)
    return {"pages": d.page_count, "chars": chars}


def caca_records(pdf_stats_, docx_stats_):
    en = {
        "doc_id": "DOC-LUNG-CACA-001",
        "title": "CACA Guidelines for Holistic Integrative Management of Lung Cancer"
                 "（中国肺癌整合诊治指南 官方英译版）",
        "doc_type": "guideline",
        "issuer": "中国抗癌协会肺癌专业委员会（Society of Lung Cancer of "
                  "China Anti-Cancer Association）",
        "publish_date": "2024-03-08",
        "cancer_types": ["lung"],
        "license_note": (
            "Open Access（CC BY 4.0）：© The Author(s) 2024，发表于 Holistic Integrative "
            "Oncology 2024;3:10（DOI 10.1007/s44178-024-00069-w），可复制、分发与改编，"
            "须署名原作者并标明来源。本件为《中国肺癌整合诊治指南》的**官方英译版**，"
            "非中文原版；中文全文见 cacaguidelines.cacakp.com（需会员登录），本项目未获取。"
            "原文 URL：https://link.springer.com/article/10.1007/s44178-024-00069-w"
        ),
        "file_path": "raw/guidelines/lung/caca2024_lung_en.pdf",
        "doc_hash": sha256(EN_PDF),
        "source_name": "CACA Guidelines for Holistic Integrative Management of Lung Cancer",
        "source_version": "2024",
        "source_section": "全文",
        "source_file": "caca2024_lung_en.pdf",
        "updated_at": UPDATED_AT,
        "review_status": "draft",
        "reviewer": None,
        "review_date": None,
        "annotation": {
            "lang": "en",
            "note": "官方英译版；%d 页 / %d 字符；用于补足中文指南不可得时的权威来源，"
                    "抽取条目须在 source_section 标注英文版" % (pdf_stats_["pages"],
                                                       pdf_stats_["chars"]),
        },
    }
    zh = {
        "doc_id": "DOC-LUNG-CACA-002",
        "title": "HIO肺癌专题：中国肺癌整合诊治指南（官方中文摘要）",
        "doc_type": "consensus",
        "issuer": "中国抗癌协会",
        "publish_date": "2024-03-08",
        "cancer_types": ["lung"],
        "license_note": (
            "中国抗癌协会官网（www.caca.org.cn）公开发布的中文摘要页，"
            "原文 URL：http://www.caca.org.cn/system/2024/03/12/030083281.shtml。"
            "本件为官方摘要（约 500 字，含本位指南的定位、覆盖范围与更新说明），"
            "**非指南全文**，不可当作 A1 原文使用；`doc_type` 在 §A1 三值枚举"
            "（guideline/standard/consensus）中权宜归入 consensus，待需求方确认。"
        ),
        "file_path": "raw/guidelines/lung/caca2024_lung_zh_abstract.docx",
        "doc_hash": sha256(ZH_DOCX),
        "source_name": "HIO肺癌专题：中国肺癌整合诊治指南（官方中文摘要）",
        "source_version": "2024",
        "source_section": "中文摘要",
        "source_file": "caca2024_lung_zh_abstract.docx",
        "updated_at": UPDATED_AT,
        "review_status": "draft",
        "reviewer": None,
        "review_date": None,
        "annotation": {
            "lang": "zh",
            "note": "官网正文逐字转录为 .docx（%d 段 / %d 字符），仅作中文补充语料，"
                    "不参与 A2 条目抽取" % (docx_stats_["paragraphs"], docx_stats_["chars"]),
        },
    }
    return [en, zh]


def csco_records():
    return [{
        "doc_id": "DOC-LUNG-CSCO-001",
        "title": "中国临床肿瘤学会（CSCO）非小细胞肺癌诊疗指南 2025",
        "doc_type": "guideline",
        "issuer": "中国临床肿瘤学会指南工作委员会",
        "publish_date": "2025-04-11",
        "cancer_types": ["lung"],
        "license_note": (
            "人民卫生出版社 2025-04-11 出版，ISBN 9787117377959，第 1 版，中文。"
            "电子版经人卫助手 / 微信扫码付费获取（《CSCO 常见恶性肿瘤诊疗指南 2025》"
            "电子书 ￥298.00），**本仓库未采集正文**，仅著录书目元数据。"
            "小细胞肺癌分册（同系列 2025 版）尚未著录，待补。"
        ),
        "file_path": None,
        "doc_hash": None,
        "source_name": "中国临床肿瘤学会（CSCO）非小细胞肺癌诊疗指南 2025",
        "source_version": "2025",
        "source_section": "未采集",
        "source_file": None,
        "updated_at": UPDATED_AT,
        "review_status": "draft",
        "reviewer": None,
        "review_date": None,
        "annotation": {
            "lang": "zh",
            "note": "付费电子书，正文不可得；不伪造内容。A2 若需 CSCO 分级（1A/2A 等），"
                    "须待合法获取正文或由人工录入指定章节。",
        },
    }]


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制重新下载与转录")
    args = ap.parse_args()

    pdf_state = download_pdf(args.force)
    body = extract_abstract(strip_tags(fetch(ZH_PAGE_URL, timeout=45)))
    docx_state = build_docx(body, args.force)

    ps, ds = pdf_stats(EN_PDF), docx_stats(ZH_DOCX)
    caca = caca_records(ps, ds)
    csco = csco_records()

    save_json(OUT_CACA, caca)
    save_json(OUT_CSCO, csco)
    save_json(AUDIT, {
        "generated_at": UPDATED_AT,
        "source_urls": {"caca_en_pdf": EN_PDF_URL, "caca_zh_page": ZH_PAGE_URL},
        "caca_en_pdf": dict(ps, state=pdf_state, sha256=sha256(EN_PDF)),
        "caca_zh_abstract": dict(ds, state=docx_state, sha256=sha256(ZH_DOCX)),
        "blocked": {
            "caca_fulltext_zh": "cacaguidelines.cacakp.com 需会员登录，页面明示「下载指南请先完成登录」",
            "csco_fulltext_zh": "人民卫生出版社付费电子书（￥298），未采集正文",
            "cma_lung_2024": "中华医学杂志全文页仅 721 个中文字符（摘要页），全文需订阅",
        },
        "records": {"caca": len(caca), "csco": len(csco)},
    })

    print("CACA 英译版 PDF: %s（%d 页 / %d 字符）"
          % (pdf_state, ps["pages"], ps["chars"]))
    print("CACA 中文摘要 DOCX: %s（%d 段 / %d 字符）"
          % (docx_state, ds["paragraphs"], ds["chars"]))
    print("写入:", os.path.relpath(OUT_CACA, BASE), "+", os.path.relpath(OUT_CSCO, BASE))


if __name__ == "__main__":
    main()
