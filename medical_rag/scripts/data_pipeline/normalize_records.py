"""数据归一化修复 —— 采集产物 -> 合规 G5/G6/G8/A4 字段结构（幂等）

对应用户已确认的两个修复方案：
  决策1 方案A：
    A1 doc_hash 由 MD5 重算为 SHA-256(raw 原文件)
    A2 回填 G6 溯源五字段（source_name/source_version/source_section/source_file/updated_at）
  决策2 方案X：
    X1 drug.indications      字符串 -> 数组（按 SPL 项目符号 • 拆分）
    X2 drug.contraindications 字符串 -> 数组（句拆；原文 None 语义化为中文表述）
    X3 drug.adverse_reactions {text} -> [{term, frequency, ctcae_hint}]（bullet 拆分 + 百分比频率）
    X4 drug.atc_code         按 WHO ATC 官方索引（whocc.no，2026-10-21 核实）映射
    X5 drug.approval_no      缺失置 null（FDA 来源无国药准字；schema 以 nullable_required 豁免）

用法:
    python scripts/data_pipeline/normalize_records.py [--dry-run]

流程位：collect（采集）→ **normalize（本脚本）** → validate（V-01 闸门）→ ingest --precheck
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]        # medical_rag/
DEFAULT_CLEAN_DIR = BASE_DIR / "data" / "clean"

# X4: 通用名 -> ATC（来源 WHO ATC/DDD Index whocc.no，逐码核实）
ATC_MAP: Dict[str, str] = {
    "OSIMERTINIB": "L01EB04",
    "PEMBROLIZUMAB": "L01FF02",
    "BEVACIZUMAB": "L01FG01",
    "PEMETREXED": "L01BA04",
    "CRIZOTINIB": "L01ED01",
}

LEAD_REF_RE = re.compile(r"\s*\(\s*[\d][\d\.,\s]*\)\s*$")      # 尾部章节交叉引用 "( 1.1 , 2.2 )"
SEE_REF_RE = re.compile(r"\s*\[see[^\]]*\]", re.I)             # "[see Warnings ...]"
SECTION_REF_RE = re.compile(r"\s*see\s+\w[\w\s]*\(\d[\d\.\s,]*\)", re.I)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
SPACE_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = SEE_REF_RE.sub("", text)
    text = SECTION_REF_RE.sub("", text)
    text = LEAD_REF_RE.sub("", text)
    return SPACE_RE.sub(" ", text).strip(" \t\n·")


def _split_bullets(text: str) -> List[str]:
    """按 SPL 项目符号拆分；去首段导语、去空项。"""
    parts = [p.strip() for p in text.split("•")]
    items = [_clean(p) for p in parts[1:]] if len(parts) > 1 else [_clean(parts[0])]
    return [i for i in items if i]


def fix_indications(value) -> list:
    if isinstance(value, list):
        return value
    items = _split_bullets(str(value))
    return items or [_clean(str(value))]


def fix_contraindications(value) -> list:
    if isinstance(value, list):
        return value
    body = re.sub(r"^\d+\s+CONTRAINDICATIONS\s*", "", str(value), flags=re.I)
    body = _clean(body)
    sentences = [_clean(s) for s in re.split(r"(?<=[。.])\s+", body) if _clean(s)]
    uniq = list(dict.fromkeys(sentences))                  # 去重且保序（SPL 常见 "None. None." 重复）
    if uniq and all(s.lower().rstrip(".") == "none" for s in uniq):
        return ["尚无禁忌（FDA 说明书原文：None）"]
    return uniq or [body]


def fix_adverse_reactions(value) -> list:
    """{text} -> [{term, frequency, ctcae_hint}]；frequency 取条目内首个百分比，无则 null。"""
    if isinstance(value, list):
        return value
    text = value.get("text", "") if isinstance(value, dict) else str(value)
    body = re.sub(r"^\d+\s+ADVERSE REACTIONS\s*", "", text, flags=re.I)
    items = _split_bullets(body)
    out: List[Dict] = []
    seen: Dict[str, int] = {}
    for item in items:
        pct = PCT_RE.search(item)
        term = item
        freq = f"{pct.group(1)}%" if pct else None
        key = term.lower()
        if key in seen:                                  # 去重：保留先出现者，若后条含频率则补频率
            if freq and out[seen[key]]["frequency"] is None:
                out[seen[key]]["frequency"] = freq
            continue
        seen[key] = len(out)
        out.append({"term": term, "frequency": freq, "ctcae_hint": None})
    return out or [{"term": _clean(body) or "见说明书第 6 节", "frequency": None, "ctcae_hint": None}]


def backfill_g6(rec: Dict, source_file: str, publish_date: Optional[str],
                extra_version: Optional[str]) -> List[str]:
    """G6 溯源五字段回填（已有值不动，保证幂等）。"""
    changed = []
    today = time.strftime("%Y-%m-%d")
    src_name = rec.get("title") or rec.get("generic_name") or ""
    version = None
    if publish_date and re.match(r"^\d{4}", str(publish_date)):
        version = str(publish_date)[:4]
    elif extra_version:
        version = extra_version
    defaults = {
        "source_name": src_name or None,
        "source_version": version,
        "source_section": "全文",
        "source_file": source_file or None,
        "updated_at": today,
    }
    for k, v in defaults.items():
        if k not in rec or rec[k] in (None, ""):
            if v is not None:
                rec[k] = v
                changed.append(k)
    return changed


def fix_doc_hash(rec: Dict) -> Optional[str]:
    """A1: doc_hash 重算 SHA-256（raw 原文件）。64 位十六进制视为已合规。"""
    current = str(rec.get("doc_hash", "") or "")
    if re.match(r"^[0-9a-fA-F]{64}$", current):
        return None
    rel = rec.get("file_path")
    if not rel:
        return None
    raw = BASE_DIR / "data" / str(rel)
    if not raw.exists():
        print(f"  ⚠️  raw 文件不存在，无法重算: {raw}")
        return None
    rec["doc_hash"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    return rec["doc_hash"]


def xml_effective_year(raw: Path) -> Optional[str]:
    """X2 辅助: 从 SPL/JATS XML 提取 effectiveTime 年份作 source_version。"""
    try:
        head = raw.read_text(encoding="utf-8", errors="ignore")[:20000]
    except Exception:
        return None
    m = re.search(r'<effectiveTime[^>]*value="(\d{4})', head)
    return m.group(1) if m else None


def normalize_file(path: Path, dry_run: bool) -> int:
    try:
        records = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠️  跳过 {path.name}: {e}")
        return 0
    if not isinstance(records, list):
        print(f"  ⚠️  跳过 {path.name}: 顶层非数组（G2）")
        return 0

    is_drug = path.parent.name == "drug_labels"
    changed_total = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        changes: List[str] = []

        # A1 doc_hash
        if "doc_hash" in rec:
            new_hash = fix_doc_hash(rec)
            if new_hash:
                changes.append("doc_hash->sha256")

        # X4/X5 药品专用
        if is_drug:
            atc = ATC_MAP.get(str(rec.get("generic_name", "")).upper())
            if atc and not rec.get("atc_code"):
                rec["atc_code"] = atc
                changes.append("atc_code")
            if "approval_no" not in rec:
                rec["approval_no"] = None                   # G8：缺值置 null（schema 豁免 FDA 来源）
                changes.append("approval_no=null")
            if "indications" in rec and not isinstance(rec["indications"], list):
                rec["indications"] = fix_indications(rec["indications"])
                changes.append("indications[]")
            if "contraindications" in rec:
                cur = rec["contraindications"]
                if not isinstance(cur, list):
                    rec["contraindications"] = fix_contraindications(cur)
                    changes.append("contraindications[]")
                elif cur and all(isinstance(i, str) and i.lower().rstrip(".") == "none" for i in cur):
                    rec["contraindications"] = ["尚无禁忌（FDA 说明书原文：None）"]
                    changes.append("contraindications[None->语义化]")
            if "adverse_reactions" in rec and not isinstance(rec["adverse_reactions"], list):
                rec["adverse_reactions"] = fix_adverse_reactions(rec["adverse_reactions"])
                changes.append("adverse_reactions[]")

        # A2 G6 回填
        rel = str(rec.get("file_path", "") or "")
        raw = BASE_DIR / "data" / rel if rel else None
        extra_ver = xml_effective_year(raw) if (raw and raw.exists() and is_drug) else None
        g6 = backfill_g6(rec, Path(rel).name if rel else "", rec.get("publish_date"), extra_ver)
        if g6:
            changes.append("G6(" + ",".join(g6) + ")")

        if changes:
            changed_total += 1
            print(f"  {'[dry] ' if dry_run else '✔'} {path.name} | {rec.get('doc_id') or rec.get('drug_id') or '?'}: {', '.join(changes)}")

    if changed_total and not dry_run:
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed_total


def main() -> int:
    ap = argparse.ArgumentParser(description="采集产物归一化修复（幂等）")
    ap.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    ap.add_argument("--dry-run", action="store_true", help="只报告将修改的内容，不落盘")
    args = ap.parse_args()

    clean = Path(args.clean_dir)
    total = 0
    for sub in sorted(clean.iterdir()):
        if sub.is_dir() and sub.name in ("guidelines", "drug_labels", "recommendations", "terminology"):
            for jf in sorted(sub.glob("*.json")):
                total += normalize_file(jf, args.dry_run)
    print(f"\n{'[dry-run] 预计修改记录' if args.dry_run else '已修复记录'}: {total}")
    if not args.dry_run and total:
        print("下一步: python scripts/data_pipeline/validate_data.py 复验")
    return 0


if __name__ == "__main__":
    sys.exit(main())
