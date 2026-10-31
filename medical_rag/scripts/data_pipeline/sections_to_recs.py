"""P-02-lite：指南章节树 → 章节级推荐单元 REC（规则版，零 LLM，零 token）
================================================================================
用途：时间受限场景下，把 P-01 产出的章节树直接转为 REC 检索主单元，使指南全文
      可被检索与逐段溯源；后续接真实 P-02（LLM 抽取）时可整体覆盖。

输入：data/intermediate/<doc_id>_tree.json（P-01 产物）
      data/clean/guidelines/*.json（DOC 元数据，供 G6 溯源五字段）
输出：data/clean/recommendations/<doc_id>_recs.json（G2 顶层数组）

规则：
  1. 剔除无临床信息的章节（Introduction / Methods / References / Funding 等）；
  2. 正文按句切分并合并为 ≤500 字的检索单元（契约 recommendation_text.maxLength）；
  3. 章节路径写入 breadcrumb 与 source_section，保留完整溯源链；
  4. evidence_level / scenario 置 null（规则化抽取无法判定，schema 已豁免），
     rec_strength 置 not_graded 表示未经证据分级；
  5. 全文去重（同文本仅保留首条），保证 V9 相似度检查通过。

运行：python scripts/data_pipeline/sections_to_recs.py
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
INTERMEDIATE_DIR = BASE_DIR / "data" / "intermediate"
GUIDELINES_DIR = BASE_DIR / "data" / "clean" / "guidelines"
OUT_DIR = BASE_DIR / "data" / "clean" / "recommendations"

# 无临床信息章节（按 sec_path 任一层级名命中即剔除）
SKIP_TITLE_KEYWORDS = (
    "introduction", "background", "methods", "method", "references", "reference",
    "abbreviations", "funding", "conflict", "disclosure", "acknowledgement",
    "author contributions", "supporting information", "footnotes", "compliance",
    "guarantor", "statistics and biometry", "informed consent", "ethical approval",
    "study subjects", "methodology",
)

MAX_LEN = 350          # 检索单元目标长度（低于契约上限 500，切得更细以提升定位精度）
MIN_LEN = 60           # 过短片段不成句，丢弃
SENT_SPLIT = re.compile(r"(?<=[.;!?。；！？])\s*")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _join(a: str, b: str) -> str:
    """拼接句子：中文之间不插空格，其余用单空格。"""
    if not a:
        return b
    if CJK_RE.match(a[-1]) or CJK_RE.match(b[0]):
        return a + b
    return a + " " + b


def chunk_text(text: str, max_len: int = MAX_LEN) -> List[str]:
    """按句切分并贪心合并为不超过 max_len 的片段；超长句硬切。"""
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    chunks: List[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_len:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(s[i:i + max_len] for i in range(0, len(s), max_len))
            continue
        if cur and len(_join(cur, s)) > max_len:
            chunks.append(cur)
            cur = s
        else:
            cur = _join(cur, s)
    if cur:
        chunks.append(cur)
    return chunks


def is_clinical(sec_path: str) -> bool:
    """章节路径任一层级命中黑名单即视为非临床章节。"""
    for part in sec_path.split("/"):
        low = part.strip().lower()
        if any(k in low for k in SKIP_TITLE_KEYWORDS):
            return False
    return True


def load_doc_meta() -> Dict[str, Dict]:
    """读取 DOC 记录，供 rec 复用 G6 溯源字段与癌种。"""
    metas: Dict[str, Dict] = {}
    for jf in sorted(GUIDELINES_DIR.glob("*.json")):
        with open(jf, "r", encoding="utf-8-sig") as f:
            for rec in json.load(f):
                doc_id = rec.get("doc_id")
                if not doc_id:
                    continue
                cancer_types = rec.get("cancer_types") or []
                metas[doc_id] = {
                    "cancer_type": cancer_types[0] if cancer_types else None,
                    "source_name": rec.get("source_name") or rec.get("title") or "",
                    "source_version": rec.get("source_version") or "",
                    "source_file": rec.get("source_file") or "",
                    "updated_at": rec.get("updated_at") or "",
                }
    return metas


def build_records(tree: Dict, meta: Dict, stats: Dict, counters: Dict[str, int],
                  max_len: int = MAX_LEN, min_len: int = MIN_LEN) -> List[Dict]:
    """章节树 → REC 记录列表。

    rec_id 采用「范围码-来源码-全局序号」：同一前缀跨文件连续编号，避免主键冲突。
    """
    doc_id = tree["doc_id"]
    parts = doc_id.split("-")          # DOC-LUNG-EPMC-001
    range_code = parts[1] if len(parts) > 2 else "GEN"
    source_code = parts[2] if len(parts) > 2 else "GEN"
    prefix = f"{range_code}-{source_code}"

    records: List[Dict] = []
    seen_text = set()
    for sec in tree.get("sections", []):
        sec_path = sec.get("sec_path") or ""
        text = (sec.get("text") or "").strip()
        if not is_clinical(sec_path):
            stats["skipped_sections"] += 1
            continue
        if len(text) < min_len:
            stats["skipped_short"] += 1
            continue
        stats["kept_sections"] += 1
        for chunk in chunk_text(text, max_len=max_len):
            if len(chunk) < min_len:
                stats["skipped_short"] += 1
                continue
            key = re.sub(r"\s+", "", chunk)[:120]
            if key in seen_text:
                stats["skipped_dup"] += 1
                continue
            seen_text.add(key)
            counters[prefix] = counters.get(prefix, 0) + 1
            records.append({
                "rec_id": f"REC-{prefix}-{counters[prefix]:04d}",
                "doc_id": doc_id,
                "cancer_type": meta.get("cancer_type"),
                "breadcrumb": sec_path,
                "scenario": None,
                "stage": None,
                "biomarker": None,
                "population": None,
                "recommendation_text": chunk,
                "verbatim": True,
                "evidence_level": None,
                "evidence_level_original": None,
                "rec_strength": "not_graded",
                "refs": [],
                "page": sec.get("page"),
                "review_status": "draft",
                "source_name": meta.get("source_name", ""),
                "source_version": meta.get("source_version", ""),
                "source_section": sec_path,
                "source_file": meta.get("source_file", ""),
                "updated_at": meta.get("updated_at", ""),
            })
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="P-02-lite：章节树 → 章节级 REC")
    ap.add_argument("--intermediate-dir", default=str(INTERMEDIATE_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--max-len", type=int, default=MAX_LEN,
                    help="单个检索单元的目标最大字符数（契约上限 500）")
    ap.add_argument("--min-len", type=int, default=MIN_LEN, help="过短片段丢弃阈值")
    args = ap.parse_args()

    inter_dir = Path(args.intermediate_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metas = load_doc_meta()
    trees = sorted(inter_dir.glob("*_tree.json"))
    if not trees:
        print(f"❌ 未找到章节树：{inter_dir}")
        return 1

    total = 0
    counters: Dict[str, int] = {}
    print(f"{'文档':<26}{'章节保留':>8}{'剔除非临床':>12}{'REC 条数':>10}")
    print("-" * 58)
    for tp in trees:
        with open(tp, "r", encoding="utf-8") as f:
            tree = json.load(f)
        doc_id = tree.get("doc_id")
        meta = metas.get(doc_id)
        if not meta:
            print(f"⚠️  {doc_id} 缺少 DOC 元数据，跳过")
            continue
        stats = {"kept_sections": 0, "skipped_sections": 0,
                 "skipped_short": 0, "skipped_dup": 0}
        records = build_records(tree, meta, stats, counters,
                               max_len=args.max_len, min_len=args.min_len)
        if not records:
            print(f"⚠️  {doc_id} 无可用章节，跳过")
            continue
        out_path = out_dir / f"{doc_id}_recs.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        total += len(records)
        print(f"{doc_id:<26}{stats['kept_sections']:>8}{stats['skipped_sections']:>12}{len(records):>10}")

    print("-" * 58)
    print(f"合计 REC 记录: {total} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
