"""乳腺癌 001：JBCS 指南 Table 1-3 分级解析（零 token）

输入  data/raw/guidelines/breast/DOC-BREAST-EPMC-001.xml（JATS，表格为文本表）
      data/clean/recommendations_breast_staging/DOC-BREAST-EPMC-001_recs.json（规则切块产物）
输出  data/intermediate/DOC-BREAST-EPMC-001_table_recs.json（表格结构化推荐）
      data/clean/recommendations_breast_staging/DOC-BREAST-EPMC-001_recs.json（原地补字段）

纪律：
  1. SoR（1 / 2 / 1–2）与 SoE（Strong / Moderate / Weak）原样保存为两个独立字段，
     不合并、不改写；共识率同样原样保留。
  2. 空单元格一律置 null，不继承上一行（原文留空即原文未给）。
  3. evidence_level 为**本项目映射**（Strong→high / Moderate→moderate / Weak→low），
     非原文等级；一个 chunk 命中多条不同 SoE 时不映射，置 null。
  4. 表格单元格文本与 chunk 文本做空白归一的字面定位，不做模糊匹配。
"""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
SPACE_RE = re.compile(r"\s+")
QID_RE = re.compile(r"^(?:CQ|BQ)\.\s?(\d+)")   # 允许 "CQ.33 (former FRQ.5)" 这类带后缀写法
STATE_RE = re.compile(r"^(?:Statement|Recommendation)$", re.I)

# 本项目映射（非原文等级）：SoE 三档 → 四档 certainty
SOE_TO_LEVEL = {"strong": "high", "moderate": "moderate", "weak": "low"}


def _local(tag: str) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _text(elem) -> str:
    return SPACE_RE.sub(" ", "".join(elem.itertext())).strip() if elem is not None else ""


def _norm(s: str) -> str:
    return SPACE_RE.sub(" ", s or "").strip()


def parse_tables(xml_path: Path) -> List[Dict]:
    """解析所有文本表 → 每个问题一组的推荐条目列表（原样 grades）。"""
    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    out: List[Dict] = []
    for tw in [e for e in root.iter() if _local(e.tag) == "table-wrap"]:
        label = _text(next((c for c in tw if _local(c.tag) == "label"), None)) or "Table"
        rows = [[_text(c) for c in r if _local(c.tag) in ("td", "th")]
                for r in [e for e in tw.iter() if _local(e.tag) == "tr"]]
        rows = [r for r in rows if r]
        # 列结构：找表头行里的 SoR / SoE / Consensus 位置（无表头的表 = Table 1 两列布局）
        sor_i = soe_i = con_i = None
        for r in rows:
            low = [c.lower() for c in r]
            if "sor" in low:
                sor_i = low.index("sor")
                soe_i = low.index("soe") if "soe" in low else None
                con_i = next((i for i, c in enumerate(low) if "consensus" in c), None)
                break
        cur_group = ""
        cur_q: Optional[Dict] = None
        for r in rows:
            cells = r + [""] * (5 - len(r))
            first = cells[0].strip()
            second = cells[1].strip()
            if sor_i is not None and first.lower() == "sor":
                continue
            if not first and not second:
                continue
            m_q = QID_RE.match(first)
            if m_q:
                cur_q = {"question_id": first[:m_q.end()].replace(" ", ""), "group": cur_group,
                         "question": second, "statements": [], "table": label}
                out.append(cur_q)
                continue
            if STATE_RE.match(first) or (not first and second and cur_q):
                if cur_q is None:
                    continue
                grades = (cells[sor_i] if sor_i is not None else "",
                          cells[soe_i] if soe_i is not None else "",
                          cells[con_i] if con_i is not None else "")
                cur_q["statements"].append({
                    "statement": second,
                    "sor": grades[0] or None,
                    "soe": grades[1] or None,
                    "consensus_rate": grades[2] or None,
                })
                continue
            # 单格行：分组标记（如 "Early breast cancer (EBC)"）
            if first and not second:
                cur_group = first
    return out


def locate_chunks(tree_path: Path, recs_path: Path) -> Dict[str, Dict]:
    """给每个 rec 回填其在所属章节正文中的起始偏移（用字面定位，不做模糊匹配）。"""
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    recs = json.loads(recs_path.read_text(encoding="utf-8"))
    sec_text = {s["sec_path"]: _norm(s.get("text") or "") for s in tree["sections"]}
    by_path: Dict[str, List[Dict]] = {}
    for rec in recs:
        by_path.setdefault(rec.get("breadcrumb") or "", []).append(rec)
    for path, group in by_path.items():
        text = sec_text.get(path, "")
        cursor = 0
        for rec in group:
            piece = _norm(rec.get("recommendation_text") or "")
            pos = text.find(piece, cursor)
            if pos < 0:
                pos = text.find(piece)
            if pos >= 0:
                rec["_section"] = path
                rec["_offset"] = pos
                rec["_end"] = pos + len(piece)
                cursor = pos + len(piece)
    return {"recs": recs, "sections": sec_text}


_MARK_RE = re.compile(r"(?:CQ|BQ)\.\s?\d+")


def _resolve_qids(rec: Dict, section_text: str, q_by_id: Dict[str, Dict]) -> List[str]:
    """chunk → 问题号：优先章节路径自带的 CQ/BQ，其次 chunk 内锚点，回落到起始位置前最近的锚点。"""
    qids: List[str] = []
    for seg in (rec.get("sec_path") or rec.get("breadcrumb") or "").split("/"):
        for m in _MARK_RE.finditer(seg):
            if m.group(0) in q_by_id and m.group(0) not in qids:
                qids.append(m.group(0))
    for m in _MARK_RE.finditer(_norm(rec.get("recommendation_text") or "")):
        if m.group(0) in q_by_id and m.group(0) not in qids:
            qids.append(m.group(0))
    if qids:
        return qids
    start = rec.get("_offset", -1)
    if start < 0:
        return []
    best = None
    for m in _MARK_RE.finditer(section_text):
        if m.start() <= start:
            qid = m.group(0)
            if qid in q_by_id:
                best = qid
    return [best] if best else []


def attach(questions: List[Dict], located: Dict) -> Dict[str, int]:
    """把表格 Statement 按所属问题块挂到 chunk 上；返回统计。"""
    stats = {"statements": 0, "attached": 0, "unmatched": 0,
             "chunks_with_grades": 0, "chunks_unresolved": 0}
    recs = located["recs"]
    q_by_id = {q["question_id"]: q for q in questions}
    stats["statements"] = sum(len(q["statements"]) for q in questions)
    for rec in recs:
        section_text = located["sections"].get(rec.get("_section") or "", "")
        qids = _resolve_qids(rec, section_text, q_by_id)
        if not qids:
            stats["chunks_unresolved"] += 1
            continue
        rows = []
        for qid in qids:
            for st in q_by_id[qid]["statements"]:
                rows.append({
                    "table": q_by_id[qid]["table"], "question_id": qid,
                    "question": q_by_id[qid]["question"],
                    "statement": st["statement"], "sor": st["sor"],
                    "soe": st["soe"], "consensus_rate": st["consensus_rate"],
                })
        if rows:
            rec["table_rows"] = rows
    stats["attached"] = sum(1 for r in recs if r.get("table_rows"))
    stats["unmatched"] = 0 if stats["attached"] else stats["statements"]
    for rec in recs:
        rows = rec.get("table_rows") or []
        if not rows:
            continue
        stats["chunks_with_grades"] += 1
        sor = sorted({r["sor"] for r in rows if r["sor"]})
        soe = sorted({r["soe"] for r in rows if r["soe"]})
        con = sorted({r["consensus_rate"] for r in rows if r["consensus_rate"]})
        rec["sor"] = "; ".join(sor) if sor else None
        rec["soe"] = "; ".join(soe) if soe else None
        rec["consensus_rate"] = "; ".join(con) if con else None
        rec["source_table"] = rows[0]["table"]
        rec["question_ids"] = sorted({r["question_id"] for r in rows})
        levels = {SOE_TO_LEVEL[s.lower()] for s in soe if s.lower() in SOE_TO_LEVEL}
        rec["evidence_level"] = levels.pop() if len(levels) == 1 else None
        if soe:
            rec["evidence_level_original"] = " | ".join(
                f"{r['question_id']}: SoR {r['sor'] or 'n/a'}; SoE {r['soe'] or 'n/a'}; "
                f"consensus {r['consensus_rate'] or 'n/a'}" for r in rows)
        else:
            rec["evidence_level_original"] = None
    return stats


def build_statement_recs(questions: List[Dict], recs: List[Dict]) -> int:
    """把表格 Statement 逐条转为 REC（表格真相行，含原样 SoR/SoE/共识率）。

    说明：规则切块的章节黑名单会剔除背景/引言类章节，本指南把 44 个问题全部放在
    "Background questions (BQs) and clinical questions (CQs)" 章节下，该章节被
    "background" 关键字整章剔除 → 表格推荐语句不会进入 REC。因此这里补出
    Statement 级 REC，保证 44 个问题的推荐结论可检索、可溯源。
    """
    base_meta = recs[0]
    max_no = max(int(r["rec_id"].rsplit("-", 1)[1]) for r in recs)
    added = 0
    for q in questions:
        for st in q["statements"]:
            max_no += 1
            added += 1
            soe = st["soe"]
            level = SOE_TO_LEVEL.get(soe.lower()) if soe else None
            recs.append({
                "rec_id": f"REC-BREAST-EPMC-{max_no:04d}",
                "doc_id": "DOC-BREAST-EPMC-001",
                "cancer_type": "breast",
                "breadcrumb": f"{q['table']}/{q['question_id']} {q['question']}",
                "scenario": None,
                "stage": None,
                "biomarker": None,
                "population": None,
                "recommendation_text": st["statement"],
                "verbatim": True,
                "evidence_level": level,
                "evidence_level_original": (
                    f"SoR {st['sor'] or 'n/a'}; SoE {st['soe'] or 'n/a'}; "
                    f"consensus {st['consensus_rate'] or 'n/a'}" if st["soe"] else None),
                "rec_strength": "not_graded",
                "refs": [],
                "page": None,
                "review_status": "draft",
                "source_name": base_meta.get("source_name", ""),
                "source_version": base_meta.get("source_version", ""),
                "source_section": f"{q['table']} {q['question_id']}",
                "source_file": base_meta.get("source_file", ""),
                "updated_at": base_meta.get("updated_at", ""),
                "sor": st["sor"],
                "soe": st["soe"],
                "consensus_rate": st["consensus_rate"],
                "source_table": q["table"],
                "question_ids": [q["question_id"]],
                "table_question": q["question"],
                "extraction_method": "table_statement",
            })
    for rec in recs:
        rec.setdefault("extraction_method", "section_chunk")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description="JBCS 表格分级解析（零 token）")
    ap.add_argument("--xml", default=str(BASE_DIR / "data" / "raw" / "guidelines" / "breast"
                                         / "DOC-BREAST-EPMC-001.xml"))
    ap.add_argument("--tree", default=str(BASE_DIR / "data" / "intermediate"
                                          / "DOC-BREAST-EPMC-001_tree.json"))
    ap.add_argument("--recs", default=str(BASE_DIR / "data" / "clean"
                                          / "recommendations_breast_staging"
                                          / "DOC-BREAST-EPMC-001_recs.json"))
    ap.add_argument("--out", default=str(BASE_DIR / "data" / "intermediate"
                                         / "DOC-BREAST-EPMC-001_table_recs.json"))
    args = ap.parse_args()

    questions = parse_tables(Path(args.xml))
    n_st = sum(len(q["statements"]) for q in questions)
    print(f"解析表格：问题 {len(questions)} 个，Statement {n_st} 条")
    for q in questions:
        print(f"  [{q['table']}] {q['question_id']} 语句 {len(q['statements'])} 条")

    located = locate_chunks(Path(args.tree), Path(args.recs))
    stats = attach(questions, located)
    print(f"\n挂载：statement {stats['statements']}，已挂 {stats['attached']}，"
          f"未匹配 {stats['unmatched']}，带分级的 chunk {stats['chunks_with_grades']}")

    recs = located["recs"]
    for rec in recs:
        rec.pop("_section", None), rec.pop("_offset", None), rec.pop("_end", None)
    added = build_statement_recs(questions, recs)
    print(f"补出 Statement 级 REC: {added} 条（合计 {len(recs)} 条）")
    Path(args.recs).write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.out).write_text(json.dumps(
        {"doc_id": "DOC-BREAST-EPMC-001", "questions": questions,
         "parse_stats": stats}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写出：{args.recs}\n写出：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
