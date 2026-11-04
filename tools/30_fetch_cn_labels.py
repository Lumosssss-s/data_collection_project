# -*- coding: utf-8 -*-
"""
30_fetch_cn_labels.py

从上市许可持有人/生产企业官网公开挂出的中文说明书（PDF/HTML）采集 A4 药品说明书原文。

设计原则
- 只使用无需登录、无验证码、无付费墙的公开页面；命中登录墙/验证码/无全文时停止并在 failures 中记录。
- 每个来源先读 robots.txt，若路径被 Disallow 则跳过。
- 单主机串行 + 固定间隔，低频抓取。
- 首次下载成功后把 fetched_at 写入 sidecar meta；重跑复用，保证产出字节级一致。
- 中文说明书字段只来自说明书原文；注册库字段不混入本文件。
- 产出：fetched/labels_cn/labels_cn.json、fetched/labels_cn/failures.json、下载原件。

用法：
    python tools/30_fetch_cn_labels.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "fetched", "labels_cn")
DL_DIR = os.path.join(OUT_DIR, "downloads")
TEXT_DIR = os.path.join(OUT_DIR, "text")
OUT_JSON = os.path.join(OUT_DIR, "labels_cn.json")
FAIL_JSON = os.path.join(OUT_DIR, "failures.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))
REQUEST_INTERVAL = 2.0  # 秒，同一主机
KNOWN_CHECKED_AT = "2026-11-04"  # 已核实不可用来源的人工核验日期

# ---------------------------------------------------------------------------
# 来源注册表
# source_type:
#   mah_official_label  上市许可持有人官网说明书（原研/持证人）
#   domestic_generic_label 国产同通用名企业官网说明书（非原研）
# usage_note: 该来源的使用限制说明
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "key": "roche_alectinib",
        "drug_id": "DRUG-LUNG-001",
        "drug_name": "阿来替尼",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/9a37ab8aac/yansuanalaitinijiaonang_20250509.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "roche_atezolizumab",
        "drug_id": "DRUG-LUNG-002",
        "drug_name": "阿替利珠单抗",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/54dbc6441f/atilizhudankangzhusheye_20260401.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "roche_bevacizumab",
        "drug_id": "DRUG-LUNG-003",
        "drug_name": "贝伐珠单抗",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/adf32e4105/beifazhudankangzhusheye_20260211.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "roche_pertuzumab",
        "drug_id": "DRUG-BREAST-010",
        "drug_name": "帕妥珠单抗",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/860634fd47/patuozhudankangzhusheye_20251028.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "roche_trastuzumab",
        "drug_id": "DRUG-BREAST-012",
        "drug_name": "曲妥珠单抗",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/ed584d17d7/zhusheyongqutuozhu-dankang_20250220.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "roche_tdm1",
        "drug_id": "DRUG-BREAST-013",
        "drug_name": "曲妥珠单抗-emtansine",
        "kind": "pdf",
        "url": "https://assets.roche.com/f/249469/x/37c9ff5886/zhusheyongenmeiqutuozhudankang_20260224.pdf",
        "source_type": "mah_official_label",
        "source_name": "上海罗氏制药有限公司官网产品说明书",
        "holder": "Roche",
        "usage_note": "罗氏官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "lilly_pemetrexed",
        "drug_id": "DRUG-LUNG-017",
        "drug_name": "培美曲塞",
        "kind": "pdf",
        "url": ("https://www.lillymedical.cn/file/raw/86e07c09-4783-4f99-aa24-6599681ab758/"
                "Alimta-CN-%20PI_master%20truth%20copy-%E6%A0%BC%E5%BC%8F%E8%B0%83%E6%95%B4%E5%90%8E.pdf"),
        "source_type": "mah_official_label",
        "source_name": "礼来医学网 力比泰说明书",
        "holder": "Eli Lilly",
        "usage_note": "礼来医学网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发或商用。",
    },
    {
        "key": "pfizer_exemestane",
        "drug_id": "DRUG-BREAST-006",
        "drug_name": "依西美坦",
        "kind": "html",
        "url": "https://www.pfizermedicalinformation.cn/products/package-insert/aromasin",
        "source_type": "mah_official_label",
        "source_name": "辉瑞医学信息网 阿诺新（依西美坦片）说明书",
        "holder": "Pfizer",
        "usage_note": "辉瑞医学信息网公开说明书页面；版权归持有人，仅限内部知识库使用，不得再分发。",
    },
    {
        "key": "innovent_sintilimab",
        "drug_id": "DRUG-EXTRA-003",
        "drug_name": "信迪利单抗",
        "kind": "pdf",
        "url": "https://img.innoventbio.com/PackageInsert/sintilimab.pdf",
        "source_type": "mah_official_label",
        "source_name": "信达生物 达伯舒（信迪利单抗注射液）说明书",
        "holder": "信达生物制药（苏州）有限公司",
        "usage_note": "信达生物官网公开PDF；版权归持有人，仅限内部知识库使用，不得再分发。",
    },
    {
        "key": "pfizer_crizotinib",
        "drug_id": "DRUG-LUNG-006",
        "drug_name": "克唑替尼",
        "kind": "html",
        "url": "https://www.pfizermedicalinformation.cn/products/package-insert/xalkori",
        "source_type": "mah_official_label",
        "source_name": "辉瑞医学信息网 赛可瑞（克唑替尼胶囊）说明书",
        "holder": "Pfizer",
        "usage_note": "辉瑞医学信息网公开说明书页面；版权归持有人，仅限内部知识库使用，不得再分发。",
    },
    {
        "key": "hansoh_fulvestrant",
        "drug_id": "DRUG-BREAST-007",
        "drug_name": "氟维司群",
        "kind": "pdf",
        "url": "https://www.hansoh.cn/upload/file/2024/01/23/eb1528835f9c43ebaed72eab433ee992.pdf",
        "source_type": "domestic_generic_label",
        "source_name": "江苏豪森药业 普来和（氟维司群注射液）说明书",
        "holder": "江苏豪森药业集团有限公司",
        "usage_note": "国产同通用名企业官网公开PDF（非原研）；仅限内部知识库使用。",
    },
    {
        "key": "hansoh_gemcitabine",
        "drug_id": "DRUG-LUNG-012",
        "drug_name": "吉西他滨",
        "kind": "pdf",
        "url": "https://www.hansoh.cn/upload/file/2025/11/20/5029add79bb846ef9432eafd70ab062b.pdf",
        "source_type": "domestic_generic_label",
        "source_name": "江苏豪森药业 泽菲（注射用盐酸吉西他滨）说明书",
        "holder": "江苏豪森药业集团有限公司",
        "usage_note": "国产同通用名企业官网公开PDF（非原研）；仅限内部知识库使用。",
    },
    {
        "key": "hansoh_cisplatin",
        "drug_id": "DRUG-LUNG-005",
        "drug_name": "顺铂",
        "kind": "pdf",
        "url": "https://www.hansoh.cn/upload/file/2025/04/15/ea09d04587aa42be8753e15a0a8c5478.pdf",
        "source_type": "domestic_generic_label",
        "source_name": "江苏豪森药业 诺欣（顺铂注射液）说明书",
        "holder": "江苏豪森药业集团有限公司",
        "usage_note": "国产同通用名企业官网公开PDF（非原研）；仅限内部知识库使用。",
    },
    {
        "key": "hansoh_pemetrexed",
        "drug_id": "DRUG-LUNG-017",
        "drug_name": "培美曲塞",
        "kind": "pdf",
        "url": "https://www.hansoh.cn/upload/file/2023/03/06/1a0026f0240d4d92a7caa07f91c711e8.pdf",
        "source_type": "domestic_generic_label",
        "source_name": "江苏豪森药业 普来乐（注射用培美曲塞二钠）说明书",
        "holder": "江苏豪森药业集团有限公司",
        "usage_note": "国产同通用名企业官网公开PDF（非原研）；仅作原研说明书的交叉核对，不作为主记录。",
        "secondary": True,
    },
]

# 已核实但本轮不可用的来源（写入 failures，说明原因）
KNOWN_UNAVAILABLE = [
    {
        "drug_id": "DRUG-SUP-001", "drug_name": "阿瑞匹坦",
        "url": "https://www.msdchina.com.cn/",
        "source_type": "mah_official_label",
        "source_name": "默沙东 意美（阿瑞匹坦胶囊）说明书PDF",
        "reason": "官方PDF为扫描图片，无文本层；本机未安装OCR（tesseract），无法提取原文。",
    },
    {
        "drug_id": "DRUG-CRC-005", "drug_name": "帕尼单抗",
        "url": "https://www.amgen.cn/",
        "source_type": "mah_official_label",
        "source_name": "安进中国官网",
        "reason": "官网未检索到可公开下载的中文说明书全文；robots.txt 返回404，无法据此判断授权范围。",
    },
    {
        "drug_id": "DRUG-SUP-002", "drug_name": "地舒单抗",
        "url": "https://www.amgen.cn/",
        "source_type": "mah_official_label",
        "source_name": "安进中国官网",
        "reason": "官网未检索到可公开下载的中文说明书全文。",
    },
    {
        "drug_id": "DRUG-THY-001", "drug_name": "仑伐替尼",
        "url": "https://www.eisai.com.cn/",
        "source_type": "mah_official_label",
        "source_name": "卫材中国官网",
        "reason": "官网仅有新闻与产品简介页，未挂出说明书PDF/全文。",
    },
    {
        "drug_id": "DRUG-THY-003", "drug_name": "索拉非尼",
        "url": "https://www.bayer.com.cn/",
        "source_type": "mah_official_label",
        "source_name": "拜耳中国官网",
        "reason": "官网产品页仅提供简介，说明书全文需向企业索取，未公开挂出。",
    },
    {
        "drug_id": "DRUG-BREAST-005", "drug_name": "表柔比星",
        "url": "https://www.pfizermedicalinformation.cn/products/package-insert/pharmorubicin-rd",
        "source_type": "mah_official_label",
        "source_name": "辉瑞医学信息网 法玛新说明书",
        "reason": "页面标注仅供医疗卫生专业人士使用，正文未在公开HTML中渲染（需登录/权限），本轮停止。",
    },
    {
        "drug_id": "DRUG-LUNG-018", "drug_name": "雷莫西尤单抗",
        "url": "https://www.lillymedical.cn/zh-cn/oncology/Cyramza",
        "source_type": "mah_official_label",
        "source_name": "礼来医学网 希冉择说明书",
        "reason": "说明书条目 BookLink 指向信达生物 SPA 页面，无直接PDF/全文，脚本无法稳定获取。",
    },
    {
        "drug_id": "DRUG-EXTRA-001", "drug_name": "安罗替尼",
        "url": "https://www.cttq.com/",
        "source_type": "mah_official_label",
        "source_name": "正大天晴 福可维（安罗替尼）说明书PDF",
        "reason": "官方PDF为扫描件，无文本层；本机未安装OCR，无法提取原文。",
    },
    {
        "drug_id": "DRUG-EXTRA-002", "drug_name": "埃克替尼",
        "url": "https://www.bettapharma.com/Contact/article/id/126",
        "source_type": "mah_official_label",
        "source_name": "贝达药业 凯美纳（盐酸埃克替尼片）说明书",
        "reason": "贝达官网仅提供说明书扫描图片（4张JPG），无文本层；本机未安装OCR，无法提取原文。",
    },
]


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def download(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/pdf,text/html,application/xhtml+xml,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        data = resp.read()
        return data, resp.headers.get("Content-Type", "")


def robots_allows(url: str) -> tuple[bool, str]:
    """读取 robots.txt，判断 URL 路径是否被 User-agent:* 的 Disallow 覆盖。
    返回 (allowed, 说明)。读取失败时不阻断，但记录说明。"""
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": UA})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            text = resp.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return True, f"robots.txt 不可用（{type(e).__name__}），按公开静态页低频访问"

    disallows = []
    agents = []
    current_star = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("user-agent:"):
            agents.append(line.split(":", 1)[1].strip())
            current_star = "*" in line.split(":", 1)[1]
        elif low.startswith("disallow:") and current_star:
            path = line.split(":", 1)[1].strip()
            if path:
                disallows.append(path)
    for d in disallows:
        if d == "/" or parsed.path.startswith(d.rstrip("*")):
            return False, f"robots.txt 对 * 禁止 {d}"
    return True, "robots.txt 未禁止该路径"


CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
SPACE_AROUND_CJK_RE = re.compile(r"(?<=[%s（）：；，。、”“])[ \t]+|[ \t]+(?=[%s（）：；，。、”“])" % (CJK, CJK))


def pdf_to_text_columns(data: bytes) -> tuple[str, dict]:
    """折叠多栏（A3 横向多面板）PDF 的按列重排回退方案。

    说明书常见版式为一整张纸折成 5 个面板，每面板一栏。pdfplumber 直接抽取会
    按 PDF 内容流顺序串栏。此处用 PyMuPDF 的行 bbox 做列聚类：先按 x0 直方图
    找列起点，再把整行归入其起点所在列，列内按 y0 排序，保证行不被列边界截断。
    """
    import fitz
    meta = {"extractor": "pymupdf_columns"}
    out_pages = []
    doc = fitz.open(stream=data, filetype="pdf")
    meta["pages"] = doc.page_count
    for page in doc:
        lines = []
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                if abs(ln["dir"][1]) > 0.01:      # 旋转水印
                    continue
                txt = "".join(sp["text"] for sp in ln["spans"]).strip()
                if not txt:
                    continue
                if max(sp["size"] for sp in ln["spans"]) > 40:  # 超大字号水印
                    continue
                lines.append((ln["bbox"][0], ln["bbox"][1], txt))
        if not lines:
            continue
        hist: dict[int, int] = {}
        for x0, _, _ in lines:
            b = int(x0 // 10 * 10)
            hist[b] = hist.get(b, 0) + 1
        threshold = max(20, int(0.35 * max(hist.values())))
        starts: list[int] = []
        for s in sorted(b for b, c in hist.items() if c >= threshold):
            if starts and s - starts[-1] < 70:
                continue
            if starts and s - starts[-1] < 200:
                continue
            starts.append(s)
        if not starts:
            starts = [0]
        bounds = []
        for i, s in enumerate(starts):
            lo = 0 if i == 0 else (starts[i - 1] + s) // 2
            hi = 10 ** 9 if i == len(starts) - 1 else (s + starts[i + 1]) // 2
            bounds.append((lo, hi))
        for lo, hi in bounds:
            for _, _, txt in sorted([x for x in lines if lo <= x[0] < hi], key=lambda z: z[1]):
                out_pages.append(txt)
            out_pages.append("")
    doc.close()
    text = "\n".join(out_pages)
    text = SPACE_AROUND_CJK_RE.sub("", text)
    return text, meta


def section_count(text: str) -> int:
    """行首【标题】的去重数量；正文内『见【xx】』类引用不计。"""
    return len({m.group(1) for line in text.splitlines() for m in [SECTION_RE.match(line)] if m})


def pdf_to_text(data: bytes) -> tuple[str, dict]:
    import pdfplumber
    meta = {}
    lines = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        meta["pages"] = len(pdf.pages)
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt:
                lines.append(txt)
    text = "\n".join(lines)
    # 折叠多栏版式下 pdfplumber 会串栏；若章节标题明显偏少则改用按列重排并择优
    if section_count(text) < 8:
        try:
            alt, alt_meta = pdf_to_text_columns(data)
        except Exception:  # noqa: BLE001
            return text, meta
        if section_count(alt) > section_count(text):
            meta.update(alt_meta)
            meta["fallback"] = "pymupdf_columns"
            return alt, meta
    return text, meta


def html_to_text(html: str) -> str:
    import html as htmlmod
    s = html
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|tr|h[1-6]|table|section)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ ]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


WATERMARK_RE = re.compile(r"^(?:[准为书明说附所中装包以请，考参供仅]\s*){3,}$")
# 竖排水印逐字散落在正文行间（如礼来 PDF「仅供参考，请以实际说明书为准」），
# 单独成行的水印字若不剔除会把词切断（"反映出"→"反映/请/出"）。
WATERMARK_CHARS = set("准为书明说附所中装包以请，考参供仅")
FOOTER_RE = re.compile(r"^\s*(?:第\s*\d+\s*页(?:\s*/?\s*共\s*\d+\s*页)?|\d{1,4}\s*/\s*\d{1,4})\s*$")


def clean_text(t: str) -> str:
    out = []
    for line in t.splitlines():
        line = line.strip()
        if not line:
            continue
        if WATERMARK_RE.match(line):
            continue
        if len(line) <= 2 and all(ch in WATERMARK_CHARS for ch in line):
            continue
        if FOOTER_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


SECTION_RE = re.compile(r"^【([^】\n]{2,20})】\s*(.*)$")
NEXT_SECTION_RE = re.compile(r"^(【[^】\n]{2,20}】)")


def split_sections(text: str) -> dict:
    """按【标题】切分。同名标题重复出现时保留第一次（正文中常有『见【禁忌】』类引用）。"""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if current and current not in sections:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = [m.group(2).strip()] if m.group(2).strip() else []
        else:
            if current:
                buf.append(line)
    if current and current not in sections:
        sections[current] = "\n".join(buf).strip()
    return sections


SECTION_ALIASES = {
    "适应症": ["适应症", "适应证"],
    "批准文号": ["批准文号", "药品批准文号"],
    "药品上市许可持有人": ["药品上市许可持有人", "上市许可持有人"],
    "生产企业": ["生产企业", "生产厂商"],
    "成份": ["成份", "成分"],
}


def get_section(sections: dict, name: str) -> str | None:
    for k in SECTION_ALIASES.get(name, [name]):
        if k in sections and sections[k]:
            return sections[k]
    return None


BULLET_RE = re.compile(r"^(?:[\uf000-\uf8ff•●·\-–—－\u2022]|\d{1,2}[.．、])\s*")
SUBTITLE_NEXT = ("本品", "赫赛莱", "帕妥珠单抗", "阿替利珠单抗", "贝伐珠单抗")


def is_heading_line(ln: str) -> bool:
    """短、无句读、且不以「本品」开头的行，视为小标题（癌种名等）。"""
    ln = ln.strip()
    return bool(ln) and len(ln) <= 20 and not re.search(r"[。；，,：:]", ln) and not ln.startswith("本品")


def paragraph_items(body: str) -> list[str]:
    """把说明书正文拆成条目，尽量保留原文并处理跨行断句。

    - 以「：」结尾的行、或短小且下一行以「本品」等开头的疾病名行，视为小标题，不单独成条；
    - 上一行未以句末标点结束时，与下一行合并（处理 PDF 换行）；
    - 以 •/●/数字/短横 开头的行作为新条目，若上一条尚未结束则并入上一条；
    - 最后按 。；; 断句。
    """
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    blocks: list[str] = []
    cur = ""
    for idx, ln in enumerate(lines):
        is_bullet = bool(BULLET_RE.match(ln))
        text_ln = BULLET_RE.sub("", ln).strip()
        if not text_ln:
            continue
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        if re.search(r"[：:]$", text_ln):
            # 纯癌种小标题（如「转移性乳腺癌：」）丢弃；「…禁用于以下患者：」这类主句保留
            if len(text_ln) <= 14 and nxt.startswith(("本品", "赫赛莱", "帕妥珠单抗", "阿替利珠单抗", "贝伐珠单抗")):
                if cur:
                    blocks.append(cur)
                    cur = ""
                continue
            if cur:
                cur += text_ln
            else:
                cur = text_ln
            continue
        if is_heading_line(text_ln) and (is_heading_line(nxt) or nxt.startswith(SUBTITLE_NEXT)):
            if cur:
                blocks.append(cur)
                cur = ""
            continue
        if is_bullet:
            if cur and not re.search(r"[。；;]$", cur):
                cur += text_ln
            else:
                if cur:
                    blocks.append(cur)
                cur = text_ln
            continue
        if cur and not re.search(r"[。；;]$", cur):
            cur += text_ln
        else:
            if cur:
                blocks.append(cur)
            cur = text_ln
    if cur:
        blocks.append(cur)

    items: list[str] = []
    for b in blocks:
        for p in re.split(r"(?<=[。；;])", b):
            p = p.strip()
            if len(p) >= 6 and not re.match(r"^[）)。；，、]", p):
                items.append(p)
    return items


FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
APPROVAL_RE = re.compile(r"国药准字\s*(?:HJ|HS|SJ|ZS|BJ|H|S|Z|J)?\s*\d{8,}")


def parse_label(text: str) -> dict:
    sections = split_sections(text)
    indications_body = get_section(sections, "适应症")
    dosage_body = get_section(sections, "用法用量")
    ci_body = get_section(sections, "禁忌")
    ar_body = get_section(sections, "不良反应")
    name_body = get_section(sections, "药品名称")
    spec_body = get_section(sections, "规格")
    appr_body = get_section(sections, "批准文号")
    mah_body = get_section(sections, "药品上市许可持有人")
    mfr_body = get_section(sections, "生产企业")

    brand = None
    if name_body:
        m = re.search(r"商\s*品\s*名(?:称)?[:：]\s*([^\n]+)", name_body)
        if m:
            brand = m.group(1).strip()

    approval = None
    if appr_body:
        found = [re.sub(r"\s+", "", x) for x in APPROVAL_RE.findall(appr_body)]
        if found:
            approval = "；".join(dict.fromkeys(found))
    if not approval and text:
        found = [re.sub(r"\s+", "", x) for x in APPROVAL_RE.findall(text)]
        if found:
            approval = "；".join(dict.fromkeys(found))

    mah = None
    if mah_body:
        m = re.search(r"(?:公司|企业)?名称[:：]\s*([^\n]+)", mah_body)
        mah = m.group(1).strip() if m else mah_body.splitlines()[0].strip()
    if mah:
        mah = re.sub(r"^(?:药品)?上市许可持有人[:：]\s*", "", mah).strip()
        mah = re.sub(r"^名称\s*[:：]\s*", "", mah).strip()
        mah = re.sub(r"\s*为$", "", mah).strip()
    mfr = None
    if mfr_body:
        m = re.search(r"(?:公司|企业)?名称[:：]\s*([^\n]+)", mfr_body)
        mfr = m.group(1).strip() if m else mfr_body.splitlines()[0].strip()
    if mfr:
        mfr = re.sub(r"^(?:生产)?企业名称[:：]\s*", "", mfr).strip()

    spec = None
    if spec_body:
        lines = [ln.strip() for ln in spec_body.splitlines() if ln.strip()]
        for ln in lines:
            if re.search(r"\d+(?:\.\d+)?\s*(?:mg|g|ml|mL|μg|µg|ug|IU|万单位|单位|%|片|粒|支|瓶|袋|丸|胶囊)", ln):
                spec = ln
                break
        if spec is None and lines:
            spec = lines[0]

    ar_items = []
    if ar_body:
        for s in paragraph_items(ar_body):
            m = FREQ_RE.search(s)
            ar_items.append({
                "term": s,
                "frequency": f"{m.group(1)}%" if m else None,
                "ctcae_hint": None,
                "lang": "zh",
                "status": "zh_from_official_label",
            })

    dosage_adjust = None
    if dosage_body:
        m = re.search(r"剂量调整", dosage_body)
        if m:
            dosage_adjust = dosage_body[m.start():].strip()

    return {
        "sections": sections,
        "indications": paragraph_items(indications_body) if indications_body else [],
        "dosage": {
            "standard": dosage_body,
            "adjustment": dosage_adjust,
        } if dosage_body else None,
        "contraindications": paragraph_items(ci_body) if ci_body else [],
        "adverse_reactions": ar_items,
        "approval_no": approval,
        "brand_name": brand,
        "specification": spec,
        "dosage_form": None,
        "mah": mah,
        "manufacturer": mfr,
    }


def main() -> int:
    ensure_dir(OUT_DIR)
    ensure_dir(DL_DIR)

    # 汇总所有已有 meta，保持 fetched_at 稳定
    records = []
    failures = []
    last_host = None
    last_time = 0.0

    for src in SOURCES:
        key = src["key"]
        host = urllib.parse.urlparse(src["url"]).netloc
        allowed, robots_note = robots_allows(src["url"])
        if not allowed:
            failures.append({
                "key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                "url": src["url"], "source_type": src["source_type"],
                "source_name": src["source_name"],
                "reason": robots_note, "checked_at": now_iso(),
            })
            continue

        ext = ".pdf" if src["kind"] == "pdf" else ".html"
        digest = hashlib.sha1(src["url"].encode("utf-8")).hexdigest()[:12]
        base = f"{key}_{digest}"
        raw_path = os.path.join(DL_DIR, base + ext)
        meta_path = os.path.join(DL_DIR, base + ".meta.json")

        if os.path.exists(raw_path) and os.path.exists(meta_path):
            meta = json.load(open(meta_path, encoding="utf-8"))
            data = open(raw_path, "rb").read()
        else:
            if last_host == host:
                wait = REQUEST_INTERVAL - (time.time() - last_time)
                if wait > 0:
                    time.sleep(wait)
            try:
                data, ctype = download(src["url"])
            except Exception as e:  # noqa: BLE001
                failures.append({
                    "key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                    "url": src["url"], "source_type": src["source_type"],
                    "source_name": src["source_name"],
                    "reason": f"下载失败：{type(e).__name__}: {e}",
                    "checked_at": now_iso(),
                })
                continue
            last_host, last_time = host, time.time()
            if len(data) < 1024:
                failures.append({
                    "key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                    "url": src["url"], "source_type": src["source_type"],
                    "source_name": src["source_name"],
                    "reason": f"响应过小（{len(data)} bytes），可能为错误页。",
                    "checked_at": now_iso(),
                })
                continue
            open(raw_path, "wb").write(data)
            meta = {
                "key": key, "url": src["url"], "content_type": ctype,
                "bytes": len(data), "fetched_at": now_iso(), "robots_note": robots_note,
            }
            json.dump(meta, open(meta_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2, sort_keys=True)

        try:
            if src["kind"] == "pdf":
                text, pdf_meta = pdf_to_text(data)
            else:
                text, pdf_meta = html_to_text(data.decode("utf-8", "ignore")), {}
        except Exception as e:  # noqa: BLE001
            failures.append({
                "key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                "url": src["url"], "source_type": src["source_type"],
                "source_name": src["source_name"],
                "reason": f"文本提取失败：{type(e).__name__}: {e}",
                "checked_at": meta.get("fetched_at") or now_iso(),
            })
            continue

        text = clean_text(text)
        parsed = parse_label(text)
        core_hit = sum(bool(parsed["sections"].get(k)) for k in
                       ["适应症", "用法用量", "禁忌", "不良反应"])
        if core_hit == 0:
            failures.append({
                "key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                "url": src["url"], "source_type": src["source_type"],
                "source_name": src["source_name"],
                "reason": "未解析到任何【适应症/用法用量/禁忌/不良反应】章节，可能为扫描件或结构不符。",
                "checked_at": meta.get("fetched_at") or now_iso(),
            })
            continue

        rel_raw = os.path.relpath(raw_path, ROOT).replace("\\", "/")
        os.makedirs(TEXT_DIR, exist_ok=True)
        text_name = key + ".txt"
        with open(os.path.join(TEXT_DIR, text_name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        text_rel = "fetched/labels_cn/text/" + text_name
        records.append({
            "key": key,
            "drug_id": src["drug_id"],
            "drug_name": src["drug_name"],
            "generic_name_in_label": (parsed["sections"].get("药品名称") or "").splitlines()[0]
            if parsed["sections"].get("药品名称") else None,
            "source_type": src["source_type"],
            "source_name": src["source_name"],
            "source_url": src["url"],
            "source_holder": src.get("holder"),
            "usage_note": src["usage_note"],
            "fetched_at": meta.get("fetched_at"),
            "content_type": meta.get("content_type"),
            "raw_bytes": meta.get("bytes"),
            "raw_path": rel_raw,
            "text_path": text_rel,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "pages": pdf_meta.get("pages"),
            "char_count": len(text),
            "sections": sorted(parsed["sections"].keys()),
            "label_sections": {k: parsed["sections"][k] for k in sorted(parsed["sections"])},
            "indications": parsed["indications"],
            "dosage": parsed["dosage"],
            "contraindications": parsed["contraindications"],
            "adverse_reactions": parsed["adverse_reactions"],
            "cn_registration": {
                "approval_no": parsed["approval_no"],
                "brand_name": parsed["brand_name"],
                "specification": parsed["specification"],
                "dosage_form": parsed["dosage_form"],
                "mah": parsed["mah"],
                "manufacturer": parsed["manufacturer"],
                "source_type": "official_label_text",
                "source_url": src["url"],
                "note": "上述字段摘自说明书原文，不使用注册库字段；未核实项为 null。",
            },
            "secondary": bool(src.get("secondary")),
        })

    # 追加已核实但不可用的来源（checked_at 用固定核验日期，保证重跑字节级一致）
    for f in KNOWN_UNAVAILABLE:
        failures.append({**f, "reason_type": "source_unavailable", "checked_at": KNOWN_CHECKED_AT})

    # 去重：同一 drug_id 有主/次来源，主记录保留在 records，secondary 另存
    records.sort(key=lambda r: (r["drug_id"], r["secondary"], r["key"]))
    payload = {
        "generated_by": "tools/30_fetch_cn_labels.py",
        "schema": "cn_label_v1",
        "policy": {
            "chinese_fields_source": "仅说明书原文；注册库字段与说明书正文分开存放",
            "forbidden": ["登录绕过", "验证码破解", "付费墙绕过", "盗版/未授权资料站"],
            "license": "内部知识库使用；原始说明书版权归各持有人，不得再分发。",
        },
        "stats": {
            "sources_registered": len(SOURCES),
            "records": len(records),
            "unique_drugs": len({r["drug_id"] for r in records}),
            "failures": len(failures),
        },
        "records": records,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    failures.sort(key=lambda r: (r["drug_id"], r["key"] if "key" in r else r["source_name"]))
    with open(FAIL_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "generated_by": "tools/30_fetch_cn_labels.py",
            "count": len(failures),
            "failures": failures,
        }, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[30] records={len(records)} unique_drugs={payload['stats']['unique_drugs']} failures={len(failures)}")
    for r in records:
        print(f"  - {r['drug_name']:12s} {r['source_type']:24s} sections={len(r['sections'])} chars={r['char_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
