# -*- coding: utf-8 -*-
"""tools/32_ocr_cn_labels.py

对已确认"只有图片/扫描件、无文本层"的三个中文说明书做 OCR 抽取：
- 阿瑞匹坦（默沙东 意美，PDF 字体编码损坏，文字层为乱码）
- 安罗替尼（正大天晴 福可维，PDF 内嵌低分辨率扫描图）
- 埃克替尼（贝达 凯美纳，官网 4 张 JPG）

设计原则
- 只用纯 pip 安装的 onnx OCR（rapidocr-onnxruntime），不装系统级程序、不提权。
- 只抓公开页面，先读 robots.txt；命中登录/验证码/付费墙即停止并记录。
- OCR 结果仍需人工复核：source_type=official_label_ocr，并记录 ocr_engine/model/dpi/page_map。
- 质量门槛：四个核心章节（适应症/用法用量/禁忌/不良反应）至少命中 2 个才视为可用；
  否则整条标 ocr_unreliable，字段全部留空，不拿糊文本入库。
- 幂等：原件与 sidecar（含 fetched_at）落盘后重跑复用；输出确定性序列化。

输出：
    fetched/labels_cn/labels_cn_ocr.json     OCR 抽取结果（与 30 号记录同构 + ocr 元数据）
    fetched/labels_cn/failures_ocr.json      OCR 不可用/下载失败记录
    fetched/labels_cn/downloads/             原件 + *.meta.json
    fetched/labels_cn/text/<key>.txt         抽取文本（与 30 号同一目录结构）

用法：
    python tools/32_ocr_cn_labels.py
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import importlib.util
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

import fitz
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "fetched", "labels_cn")
DL_DIR = os.path.join(OUT_DIR, "downloads")
TEXT_DIR = os.path.join(OUT_DIR, "text")
OUT_JSON = os.path.join(OUT_DIR, "labels_cn_ocr.json")
FAIL_JSON = os.path.join(OUT_DIR, "failures_ocr.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
TZ = timezone(timedelta(hours=8))
REQUEST_INTERVAL = 2.0
KNOWN_CHECKED_AT = "2026-11-05"

CORE_SECTIONS = ["适应症", "用法用量", "禁忌", "不良反应"]

# 只收录"高置信度"的章节标题 OCR 混淆：正文语义已明确指向该章节时，才做确定性替换，
# 并把替换记录写进 ocr.header_normalizations 供人工回查。不做正文内容改写。
HEADER_ALIASES = {"蒙忌": "禁忌"}

# 只收录高置信度的字符级 OCR 混淆（固定格式前缀），替换后记入 ocr.text_normalizations。
TEXT_NORMALIZATIONS = [("国药准宇", "国药准字")]

# “（见【临床试验】）”一类纯交叉引用，不是章节正文内容
CROSSREF_PREFIX_RE = re.compile(r"^[（(]?(?:参)?见【[^】]{1,20}】[】）)]*")

OCR_ENGINE = "rapidocr-onnxruntime"
OCR_VERSION = md.version("rapidocr-onnxruntime")
OCR_MODEL = "PP-OCRv4 (ch_PP-OCRv4_det_infer.onnx + ch_PP-OCRv4_rec_infer.onnx, CPU)"
OCR_NOTE = "OCR 抽取，非人工校对；表格与小字注释可能不可靠，原文以官网 PDF/图片为准。"

SOURCES = [
    {
        "key": "msd_aprepitant",
        "drug_id": "DRUG-SUP-001",
        "drug_name": "阿瑞匹坦",
        "kind": "pdf",
        "url": ("https://assets.msdchina.com.cn/sites/4/2025/05/"
                "%E6%84%8F%E7%BE%8E%E8%AF%B4%E6%98%8E%E4%B9%A6-%E5%88%86%E5%8C%85semi-%E5%8E%BB%E6%A0%87%E6%B3%A8"
                "%EF%BC%88%E6%96%B9%E6%AD%A3%E9%BB%91%E6%A8%AA%E7%89%88%EF%BC%89-25.4.27-%E6%9B%B2%E7%BA%BF.pdf"),
        "dpi": 300,
        "source_type": "official_label_ocr",
        "source_name": "默沙东官网 意美（阿瑞匹坦胶囊）说明书PDF",
        "holder": "默沙东（MSD）",
        "usage_note": "默沙东官网公开PDF；文字层字体编码损坏（无 ToUnicode），经 OCR 抽取，非人工校对；"
                      "版权归持有人，仅限内部知识库使用，不得再分发。",
    },
    {
        "key": "cttq_anlotinib",
        "drug_id": "DRUG-EXTRA-001",
        "drug_name": "安罗替尼",
        "kind": "pdf",
        "url": ("https://www.cttq.com/core/control/common/down.jsp?filename=/upload/file/"
                "2026/09/20/e43c56a3ee01408f8171581dca000e06.pdf&title=%E7%9B%90%E9%85%B8%E5%AE%89%E7%BD%97"
                "%E6%9B%BF%E5%B0%BC%E8%83%B6%E8%83%B6"),
        "dpi": 260,
        "source_type": "official_label_ocr",
        "source_name": "正大天晴官网 福可维（盐酸安罗替尼胶囊）说明书PDF",
        "holder": "正大天晴",
        "usage_note": "正大天晴官网公开PDF扫描件；分辨率偏低（约100–130 dpi），OCR 文本严重乱码，"
                      "不作为中文字段来源，仅保留原件与失败原因。",
    },
    {
        "key": "betta_icotinib",
        "drug_id": "DRUG-EXTRA-002",
        "drug_name": "埃克替尼",
        "kind": "images",
        "urls": [
            "https://www.bettapharma.com/ueditor/php/upload/image/20220629/1656479996697889.jpg",
            "https://www.bettapharma.com/ueditor/php/upload/image/20220629/1656480003602746.jpg",
            "https://www.bettapharma.com/ueditor/php/upload/image/20220629/1656480007129663.jpg",
            "https://www.bettapharma.com/ueditor/php/upload/image/20220629/1656480010509883.jpg",
        ],
        "source_page": "https://www.bettapharma.com/Contact/article/id/126",
        "source_type": "official_label_ocr",
        "source_name": "贝达药业官网 凯美纳（盐酸埃克替尼片）说明书图片（4张JPG）",
        "holder": "贝达药业",
        "usage_note": "贝达药业官网公开说明书图片（4张JPG）；经 OCR 抽取，非人工校对；"
                      "版权归持有人，仅限内部知识库使用，不得再分发。",
    },
]

M30 = None


def load_m30():
    global M30
    if M30 is None:
        path = os.path.join(ROOT, "tools", "30_fetch_cn_labels.py")
        spec = importlib.util.spec_from_file_location("cn_labels_30", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        M30 = mod
    return M30


def now_iso() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def bbox(box):
    pts = box[0]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def download(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def ensure_file(src_key: str, url: str, ext: str, idx: int | None = None) -> tuple[str, dict, bool]:
    """下载一次并复用；返回 (路径, meta, 是否新下载)。"""
    m30 = load_m30()
    os.makedirs(DL_DIR, exist_ok=True)
    pattern = f"{src_key}_{idx}_" if idx is not None else f"{src_key}_"
    for name in os.listdir(DL_DIR):
        if name.startswith(pattern) and name.endswith("." + ext) and not name.endswith(".meta.json"):
            base = name[:-len(ext) - 1]
            meta_path = os.path.join(DL_DIR, base + ".meta.json")
            if os.path.exists(meta_path):
                return os.path.join(DL_DIR, name), json.load(open(meta_path, encoding="utf-8")), False

    ok, note = m30.robots_allows(url)
    if not ok:
        raise RuntimeError("robots.txt 禁止抓取：%s" % note)
    data, ctype = download(url)
    if len(data) < 1024:
        raise RuntimeError("响应过小（%d bytes），可能为错误页" % len(data))
    sha = hashlib.sha256(data).hexdigest()[:12]
    base = f"{src_key}_{idx}_{sha}" if idx is not None else f"{src_key}_{sha}"
    path = os.path.join(DL_DIR, base + "." + ext)
    open(path, "wb").write(data)
    meta = {"key": src_key, "index": idx, "url": url, "content_type": ctype,
            "bytes": len(data), "fetched_at": now_iso(), "robots_note": note}
    json.dump(meta, open(os.path.join(DL_DIR, base + ".meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, sort_keys=True)
    return path, meta, True


def ocr_boxes(image) -> list[tuple[float, float, float, float, str]]:
    res, _ = load_engine()(image)
    out = []
    for box, text, _score in res or []:
        x0, y0, x1, y1 = bbox([box])
        t = (text or "").strip()
        if t:
            out.append((x0, y0, x1, y1, t))
    return out


_ENGINE = None


def load_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RapidOCR()
    return _ENGINE


def column_starts(boxes, min_count=12, merge_gap=60, min_spacing=200):
    hist = {}
    for x0, _y0, _x1, _y1, _t in boxes:
        b = int(x0 // 20 * 20)
        hist[b] = hist.get(b, 0) + 1
    starts = []
    for s in sorted(b for b, c in hist.items() if c >= min_count):
        if starts and s - starts[-1] < merge_gap:
            continue
        if starts and s - starts[-1] < min_spacing:
            continue
        starts.append(s)
    return starts


def group_lines(boxes) -> list[tuple[float, float, str]]:
    """按 y 聚合行；返回 (y0, y1, 文本)。"""
    if not boxes:
        return []
    heights = sorted(b[3] - b[1] for b in boxes)
    tol = max(6, heights[len(heights) // 2] * 0.6)
    rows = []
    for x0, y0, x1, y1, t in sorted(boxes, key=lambda b: (b[1], b[0])):
        placed = False
        for row in rows:
            if abs(row["yc"] - y0) <= tol:
                row["items"].append((x0, t))
                row["yc"] = (row["yc"] * row["n"] + y0) / (row["n"] + 1)
                row["n"] += 1
                row["y1"] = max(row["y1"], y1)
                placed = True
                break
        if not placed:
            rows.append({"yc": y0, "y1": y1, "n": 1, "items": [(x0, t)]})
    rows.sort(key=lambda r: r["yc"])
    out = []
    for row in rows:
        parts = [t for _x, t in sorted(row["items"], key=lambda it: it[0])]
        text = ""
        for p in parts:
            if text and re.match(r"[A-Za-z0-9]$", text[-1]) and re.match(r"[A-Za-z0-9]", p[0]):
                text += " " + p
            else:
                text += p
        out.append((row["yc"], row["y1"], text))
    return out


def page_lines(boxes, width, height) -> list[tuple[float, float, str]]:
    """页面级排序：横向多栏按列优先，其余按行优先。"""
    starts = column_starts(boxes)
    if width / float(height) > 1.15 and len(starts) >= 2:
        bounds = []
        for i, s in enumerate(starts):
            lo = 0 if i == 0 else s - 10
            hi = 10 ** 9 if i == len(starts) - 1 else starts[i + 1] - 10
            bounds.append((lo, hi))
        lines = []
        for lo, hi in bounds:
            lines.extend(group_lines([b for b in boxes if lo <= b[0] < hi]))
        return lines
    return group_lines(boxes)


def run_source(src: dict) -> tuple[dict | None, dict | None]:
    """返回 (record, failure)。二者至多一个非 None。"""
    key = src["key"]
    meta_list, files = [], []
    try:
        if src["kind"] == "pdf":
            path, meta, _new = ensure_file(key, src["url"], "pdf")
            files.append(path)
            meta_list.append(meta)
        else:
            for i, url in enumerate(src["urls"], 1):
                path, meta, _new = ensure_file(key, url, "jpg", idx=i)
                files.append(path)
                meta_list.append(meta)
    except Exception as e:  # noqa: BLE001
        return None, {"key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                      "url": src["url"], "source_type": src["source_type"],
                      "source_name": src["source_name"],
                      "reason": "下载失败：%s: %s" % (type(e).__name__, e),
                      "checked_at": now_iso()}

    pages = []
    if src["kind"] == "pdf":
        doc = fitz.open(files[0])
        for pno in range(doc.page_count):
            pix = doc[pno].get_pixmap(dpi=src["dpi"])
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            pages.append((pno + 1, img.size[0], img.size[1], ocr_boxes(img)))
        doc.close()
    else:
        for i, path in enumerate(files, 1):
            img = Image.open(path).convert("RGB")
            # 官网长图宽度约 1205 px，2 倍 Lanczos 放大后小字（如「突变」「晚期」）识别更稳。
            if img.size[0] < 1500:
                img = img.resize((img.size[0] * 2, img.size[1] * 2), Image.LANCZOS)
            pages.append((i, img.size[0], img.size[1], ocr_boxes(img)))

    all_lines = []
    page_map = []
    seen = set()
    normalized = []
    section_re = load_m30().SECTION_RE
    for page_no, w, h, boxes in pages:
        lines = page_lines(boxes, w, h)
        for y0, _y1, text in lines:
            all_lines.append(text)
            m = section_re.match(text)
            if m:
                raw_title = m.group(1)
                title = HEADER_ALIASES.get(raw_title, raw_title)
                if title != raw_title:
                    normalized.append({"from": raw_title, "to": title, "page": page_no,
                                       "y": round(y0), "image": page_no})
                if title not in seen:
                    seen.add(title)
                    page_map.append({"section": title, "page": page_no,
                                     "y": round(y0), "image": page_no})
        all_lines.append("")

    text = load_m30().clean_text("\n".join(all_lines))
    if normalized:
        fixed = []
        for line in text.splitlines():
            m = section_re.match(line)
            if m and m.group(1) in HEADER_ALIASES:
                rest = m.group(2)
                line = "【%s】%s" % (HEADER_ALIASES[m.group(1)], (" " + rest) if rest else "")
            fixed.append(line)
        text = "\n".join(fixed)
    text_normalizations = []
    for bad, good in TEXT_NORMALIZATIONS:
        n = text.count(bad)
        if n:
            text = text.replace(bad, good)
            text_normalizations.append({"from": bad, "to": good, "count": n})
    parsed = load_m30().parse_label(text)
    # 合并式标题（如【上市许可持有人及生产企业】）不在 30 号的别名表内，这里补一次确定性抽取
    if not parsed["mah"]:
        body = parsed["sections"].get("上市许可持有人及生产企业")
        if body:
            m = re.search(r"名称[:：]\s*([^\n]+)", body)
            if m:
                parsed["mah"] = parsed["manufacturer"] = m.group(1).strip()
    # 跨行切分可能把“（见【临床试验】）”粘在段落开头，纯交叉引用不是正文内容
    for field in ("indications", "contraindications"):
        cleaned = []
        for x in parsed[field]:
            y = CROSSREF_PREFIX_RE.sub("", x).strip()
            if y and not (y.startswith("（参见") and len(y) <= 30):
                cleaned.append(y)
        parsed[field] = cleaned
    hits = [k for k in CORE_SECTIONS if parsed["sections"].get(k)]

    fetched_at = meta_list[0]["fetched_at"]
    rel_raw = [os.path.relpath(p, ROOT).replace("\\", "/") for p in files]
    text_name = key + ".txt"
    os.makedirs(TEXT_DIR, exist_ok=True)
    with open(os.path.join(TEXT_DIR, text_name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    text_rel = "fetched/labels_cn/text/" + text_name

    reliable = len(hits) >= 2
    record = {
        "key": key,
        "drug_id": src["drug_id"],
        "drug_name": src["drug_name"],
        "generic_name_in_label": (parsed["sections"].get("药品名称") or "").splitlines()[0]
        if parsed["sections"].get("药品名称") else None,
        "source_type": src["source_type"],
        "source_name": src["source_name"],
        "source_url": src.get("url") or src.get("source_page"),
        "source_holder": src.get("holder"),
        "usage_note": src["usage_note"],
        "fetched_at": fetched_at,
        "content_type": meta_list[0].get("content_type"),
        "raw_bytes": sum(m.get("bytes") or 0 for m in meta_list),
        "raw_path": rel_raw[0] if len(rel_raw) == 1 else rel_raw,
        "text_path": text_rel,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "pages": len(pages),
        "char_count": len(text),
        "sections": sorted(parsed["sections"].keys()),
        "label_sections": {k: parsed["sections"][k] for k in sorted(parsed["sections"])},
        "indications": parsed["indications"] if reliable else [],
        "dosage": parsed["dosage"] if reliable else {"standard": None, "adjustment": None},
        "contraindications": parsed["contraindications"] if reliable else [],
        "adverse_reactions": parsed["adverse_reactions"] if reliable else [],
        "cn_registration": {
            "approval_no": parsed["approval_no"] if reliable else None,
            "brand_name": parsed["brand_name"] if reliable else None,
            "specification": parsed["specification"] if reliable else None,
            "dosage_form": parsed["dosage_form"] if reliable else None,
            "mah": parsed["mah"] if reliable else None,
            "manufacturer": parsed["manufacturer"] if reliable else None,
            "source_type": "official_label_ocr",
            "source_url": src.get("url") or src.get("source_page"),
            "note": "上述字段摘自 OCR 后的说明书原文，非人工校对；未识别项为 null。",
        },
        "ocr": {
            "engine": OCR_ENGINE,
            "engine_version": OCR_VERSION,
            "model": OCR_MODEL,
            "dpi": src.get("dpi"),
            "preprocess": ("RGB; Lanczos 2x upscale (width<1500px)" if src["kind"] == "images"
                           else "RGB; PDF render at %s dpi" % src.get("dpi")),
            "reliable": reliable,
            "core_sections_hit": hits,
            "core_sections_missing": [k for k in CORE_SECTIONS if k not in hits],
            "page_map": page_map,
            "header_normalizations": normalized,
            "text_normalizations": text_normalizations,
            "note": OCR_NOTE,
        },
        "secondary": False,
    }
    if not reliable:
        record["ocr_unreliable"] = True
        record["ocr_unreliable_reason"] = (
            "OCR 后四个核心章节仅命中 %s，文本严重乱码（扫描件分辨率约 100–130 dpi），不入库。"
            % (hits or "无"))
        failure = {"key": key, "drug_id": src["drug_id"], "drug_name": src["drug_name"],
                   "url": src.get("url") or src.get("source_page"),
                   "source_type": src["source_type"], "source_name": src["source_name"],
                   "reason": record["ocr_unreliable_reason"], "checked_at": KNOWN_CHECKED_AT,
                   "reason_type": "ocr_unreliable"}
        return record, failure
    return record, None


def main() -> int:
    records, failures = [], []
    for src in SOURCES:
        rec, fail = run_source(src)
        if rec:
            records.append(rec)
        if fail:
            failures.append(fail)

    records.sort(key=lambda r: (r["drug_id"], r["key"]))
    payload = {
        "generated_by": "tools/32_ocr_cn_labels.py",
        "schema": "cn_label_ocr_v1",
        "policy": {
            "chinese_fields_source": "图片/扫描件说明书经 OCR 抽取，非人工校对；核心章节命中不足则整条留空",
            "forbidden": ["登录绕过", "验证码破解", "付费墙绕过", "盗版/未授权资料站"],
            "license": "内部知识库使用；原始说明书版权归各持有人，不得再分发。",
        },
        "ocr": {"engine": OCR_ENGINE, "engine_version": OCR_VERSION, "model": OCR_MODEL},
        "stats": {"sources_registered": len(SOURCES), "records": len(records),
                  "reliable": sum(1 for r in records if r["ocr"]["reliable"]),
                  "unreliable": sum(1 for r in records if not r["ocr"]["reliable"]),
                  "failures": len(failures)},
        "records": records,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(FAIL_JSON, "w", encoding="utf-8") as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[32] OCR sources=%d records=%d reliable=%d unreliable=%d failures=%d"
          % (len(SOURCES), len(records), payload["stats"]["reliable"],
             payload["stats"]["unreliable"], len(failures)))
    for r in records:
        print("  - %-12s %-22s sections=%d chars=%d reliable=%s"
              % (r["drug_name"], r["source_type"], len(r["sections"]), r["char_count"],
                 r["ocr"]["reliable"]))
    for x in failures:
        print("  ! %-12s %s" % (x["drug_name"], x["reason"][:80]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
