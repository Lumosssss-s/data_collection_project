"""P-01 pdf_extract.py —— 指南原文 → 结构化章节树（零 token）

对应《数据处理校验评测脚本交付清单》P-01 契约（主方案 §5.3 流水线第一环）：

    输入   data/raw/guidelines/ 原生文件
             - *.xml  JATS 全文（Europe PMC 批次，本脚本当前主路径）
             - *.pdf  原生 PDF（需 PyMuPDF；正式 PDF 批次到货后增补 requirements 并重建镜像）
    输出   data/intermediate/<doc_id>_tree.json
           {doc_id, title, toc[], sections[{sec_path, level, text, page}], doc_hash, extract_meta}
    要点   ① sec_path = breadcrumb 完整层级路径（REC 溯源依赖，/ 分隔）
           ② 每段带 page（JATS 无页码 → null，记入 extract_meta.warnings，不中断）
           ③ doc_hash = 原文件 SHA-256（与 clean 指南记录 doc_hash 复核一致性）
           ④ 失败章节记 warnings 不中断；PDF 无文本层（扫描件）直接报错退出（硬口径 1）

用法:
    python scripts/data_pipeline/pdf_extract.py                 # 处理全部
    python scripts/data_pipeline/pdf_extract.py --only DOC-LUNG  # 按 doc_id 前缀过滤
"""
import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]            # medical_rag/
DEFAULT_RAW_DIR = BASE_DIR / "data" / "raw" / "guidelines"
DEFAULT_CLEAN_DIR = BASE_DIR / "data" / "clean" / "guidelines"
DEFAULT_OUT_DIR = BASE_DIR / "data" / "intermediate"

SPACE_RE = re.compile(r"\s+")


def _local(tag: str) -> str:
    """剥离 XML 命名空间。"""
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _text(elem) -> str:
    """拼接元素全部文本并按 G10 折叠空白。"""
    if elem is None:
        return ""
    return SPACE_RE.sub(" ", "".join(elem.itertext())).strip()


def _sec_title(sec) -> str:
    for child in sec:
        if _local(child.tag) == "title":
            return _text(child)
    return ""


def _sec_own_text(sec) -> str:
    """章节自身正文（直接子级 p/list-item/table-wrap/fig 文本，不含嵌套 sec）。"""
    parts: List[str] = []
    for child in sec:
        tag = _local(child.tag)
        if tag == "sec":
            continue
        if tag in ("p", "list", "list-item", "disp-quote", "boxed-text", "statement",
                   "def-list", "fn-group", "ref-list"):
            t = _text(child)
            if t:
                parts.append(t)
        elif tag == "table-wrap":
            t = _text(child)
            if t:
                parts.append(t)
        elif tag == "fig":
            t = _text(child)
            if t:
                parts.append(t)
    return "\n".join(parts)


def extract_jats(xml_path: Path) -> Dict:
    """JATS XML → 章节树。返回与 P-01 契约一致的结构。"""
    warnings: List[str] = []
    try:
        root = ET.fromstring(xml_path.read_text(encoding="utf-8", errors="strict"))
    except ET.ParseError as e:
        raise SystemExit(f"❌ XML 解析失败（退出）: {xml_path.name}: {e}")

    # 标题
    title = ""
    for el in root.iter():
        if _local(el.tag) == "article-title":
            title = _text(el)
            break
    if not title:
        warnings.append("front 缺 article-title，回落文件名")
        title = xml_path.stem

    # 定位 body
    body = None
    for el in root.iter():
        if _local(el.tag) == "body":
            body = el
            break
    if body is None:
        raise SystemExit(f"❌ 无 <body>（无可抽取正文，硬口径 1）: {xml_path.name}")

    sections: List[Dict] = []
    toc: List[Dict] = []

    def walk(parent, parent_path: List[str], level: int, is_body: bool = False):
        stray: List[str] = []
        for child in parent:
            tag = _local(child.tag)
            if tag == "sec":
                st = _sec_title(child)
                path = parent_path + ([st] if st else [])
                text = _sec_own_text(child)
                sec_path = "/".join(path) if path else title
                if not st:
                    warnings.append(f"level {level} 缺标题章节，breadcrumb 回落上级")
                sections.append({
                    "sec_path": sec_path,
                    "level": level,
                    "text": text,
                    "page": None,                      # JATS 无页码（记 warning 不中断）
                })
                toc.append({"sec_path": sec_path, "level": level})
                walk(child, path, level + 1)
            elif tag == "p" and is_body:
                # 仅 body 直属段落按散段收录；sec 内段落由 _sec_own_text 负责，避免重复
                t = _text(child)
                if t:
                    stray.append(t)
        if stray:
            sec_path = "/".join(parent_path) if parent_path else f"{title}（正文散段）"
            sections.append({"sec_path": sec_path, "level": level,
                             "text": "\n".join(stray), "page": None})
            toc.append({"sec_path": sec_path, "level": level})
            if not parent_path:
                warnings.append("body 直属段落无章节归属，已归入散段节")

    walk(body, [], 1, is_body=True)

    if not any(s["text"] for s in sections):
        raise SystemExit(f"❌ 章节树无任何正文文本（疑似空/扫描件）: {xml_path.name}")

    # 正文覆盖审计：抽取正文 / body 全文（itertext），应接近 1.0（低覆盖说明有标签未收录）
    body_chars = len(SPACE_RE.sub(" ", "".join(body.itertext())).strip())
    captured = sum(len(s["text"]) for s in sections)
    coverage = round(captured / body_chars, 3) if body_chars else 0.0
    if coverage < 0.9:
        warnings.append(f"正文覆盖率 {coverage} < 0.9，可能有未收录标签（body {body_chars} 字符）")

    if not any(s["page"] is not None for s in sections):
        warnings.append("JATS 源无页码，全部 section.page=null（REC.page 待 PDF 批次补齐）")

    return {
        "title": title,
        "toc": toc,
        "sections": sections,
        "warnings": warnings,
        "extract_meta": {
            "source_type": "jats_xml",
            "parser": "pdf_extract.py/jats",
            "sections_count": len(sections),
            "chars_total": sum(len(s["text"]) for s in sections),
            "coverage": coverage,
            "body_chars": body_chars,
            "extracted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": warnings,
        },
    }


def extract_pdf(pdf_path: Path) -> Dict:
    """PDF 后端（占位）：正式 PDF 批次到货后增补 requirements.txt（PyMuPDF）并重建镜像。"""
    raise SystemExit(
        f"❌ PDF 后端未启用: {pdf_path.name}\n"
        "   需 PyMuPDF：待方案X 正式 PDF 批次到货后，增补 requirements.txt 并重建镜像再启用。")


def load_doc_map(clean_dir: Path) -> Dict[str, Dict]:
    """raw 文件名 -> clean DOC 记录（按 file_path 匹配），提供 doc_id 与 doc_hash 复核。"""
    out: Dict[str, Dict] = {}
    if not clean_dir.exists():
        return out
    for jf in sorted(clean_dir.glob("*.json")):
        try:
            records = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for rec in records if isinstance(records, list) else []:
            if isinstance(rec, dict) and rec.get("file_path"):
                out[Path(str(rec["file_path"])).name] = rec
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="P-01 指南原文 → 章节树")
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    ap.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--only", default="", help="按 doc_id / 文件名前缀过滤")
    args = ap.parse_args()

    raw_dir, out_dir = Path(args.raw_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc_map = load_doc_map(Path(args.clean_dir))

    files = sorted(raw_dir.glob("*.xml")) + sorted(raw_dir.glob("*.pdf"))
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        print(f"⚠️  无输入文件: {raw_dir}")
        return 1

    ok, failed = 0, 0
    for fp in files:
        # doc_id 定位：优先 clean 记录 file_path 匹配，回落文件名主干
        rec = doc_map.get(fp.name, {})
        doc_id = rec.get("doc_id") or fp.stem
        file_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
        hash_mismatch = rec.get("doc_hash") and rec["doc_hash"] != file_hash

        try:
            tree = extract_jats(fp) if fp.suffix.lower() == ".xml" else extract_pdf(fp)
        except SystemExit as e:
            print(e)
            failed += 1
            continue

        if hash_mismatch:
            tree["extract_meta"]["warnings"].append(
                f"doc_hash 与 clean 记录不一致: 记录={rec.get('doc_hash')} 实际={file_hash}")

        out = {
            "doc_id": doc_id,
            "title": tree["title"],
            "toc": tree["toc"],
            "sections": tree["sections"],
            "doc_hash": file_hash,
            "extract_meta": tree["extract_meta"],
        }
        out_path = out_dir / f"{doc_id}_tree.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        ok += 1
        m = tree["extract_meta"]
        warn = f"  ⚠️  {len(m['warnings'])} warnings" if m["warnings"] else ""
        print(f"✔ {fp.name} -> {out_path.name}: 章节 {m['sections_count']}, "
              f"正文 {m['chars_total']} 字符{warn}")

    print(f"\nP-01 完成: 成功 {ok} / 失败 {failed}，输出目录 {out_dir}")
    if ok:
        # 抽样 3 段打印，供人工逐字比对原文（清单 P-01 验收②）
        sample = sorted(out_dir.glob("*_tree.json"))[0]
        data = json.loads(sample.read_text(encoding="utf-8"))
        picks = [s for s in data["sections"] if s["text"]][:3]
        print(f"\n抽样比对（{sample.name}，应与原文逐字一致）:")
        for s in picks:
            print(f"  [{s['sec_path'][:60]}] {s['text'][:80]}…")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
