"""P6：为章节级 REC 回填 scenario / evidence_level（LLM 批量标注）。

背景：P-02-lite 规则抽取无法判定临床场景与证据等级，schema 对这两个字段做了
nullable 豁免（1,513 条全部为 null）。本脚本用项目内 LLM 通道（utils.llm_client →
DeepSeek，与问答服务同模型同 key）批量回填。

约束：
  - 只改 scenario / evidence_level，正文、溯源字段、rec_strength 一律不动；
  - 枚举强校验：scenario 15 值、evidence_level 4 值，非法输出丢弃并记 null；
  - 幂等：进度文件 data/intermediate/rec_annotation_progress.json 记录已标注项，
    重跑只处理剩余条目；
  - review_status 仍为 draft（LLM 标注未经医学审核）。

用法（容器内）：
  python scripts/data_pipeline/annotate_recs.py --limit 30   # 试跑
  python scripts/data_pipeline/annotate_recs.py             # 全量
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)  # 以脚本路径运行时，保证能 import utils / core
REC_DIR = os.path.join(BASE_DIR, "data", "clean", "recommendations")
PROGRESS = os.path.join(BASE_DIR, "data", "intermediate", "rec_annotation_progress.json")

SCENARIOS = ["screening", "diagnosis", "staging", "treatment_neoadjuvant",
             "treatment_adjuvant", "treatment_first_line", "treatment_second_line",
             "treatment_later", "surgery", "radiotherapy", "targeted",
             "immunotherapy", "followup", "supportive_care", "rehab"]
LEVELS = ["high", "moderate", "low", "very_low"]

PROMPT = """你是肿瘤临床指南的结构化标注员。下面给出若干条指南推荐条目（英文）。

请为每条标注两个字段：
1. scenario —— 从下列受控值中选最贴切的一个：
{s}
2. evidence_level —— 仅当正文中**明确出现**证据等级标注时给出，否则填 null：
   1A→high、1B/2A→moderate、2B/2C→low、3/4→very_low。
   **严禁根据语气猜测**：没有原文等级就填 null（医学场景中凭空判级会误导使用者）。
3. evidence_level_original —— 原文等级字样（如 "1A"、"2B"、"3"）；无法确定时填 null。

只输出 JSON 对象，格式为
{{"items":[{{"id":"...","scenario":"...","evidence_level":"high|moderate|low|very_low|null","evidence_level_original":"1A|null"}}]}}，
不要输出解释或多余文本。条目如下：

{items}"""


def _load(path: str) -> List[Dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, records: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)


def _parse(text: str) -> Dict[str, Dict]:
    """从模型输出中取 {id: {scenario, evidence_level}}，非法枚举直接丢弃。"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    out: Dict[str, Dict] = {}
    for item in data.get("items", []):
        rid = str(item.get("id") or "")
        sc = item.get("scenario")
        lv = item.get("evidence_level") or None
        grade = item.get("evidence_level_original") or None
        if not rid or sc not in SCENARIOS:
            continue
        if lv is not None and lv not in LEVELS:
            continue
        out[rid] = {"scenario": sc, "evidence_level": lv,
                    "evidence_level_original": grade if lv else None}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="P6：REC 场景与证据等级标注")
    ap.add_argument("--batch-size", type=int, default=15)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（试跑）")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--rec-dir", default=REC_DIR,
                    help="REC 目录（默认 data/clean/recommendations；新批次可用独立目录）")
    ap.add_argument("--progress", default=PROGRESS,
                    help="进度文件路径（默认 data/intermediate/rec_annotation_progress.json）")
    ap.add_argument("--only-method", default="",
                    help="只处理 extraction_method 等于该值的条目（如 table_statement）")
    ap.add_argument("--write-clean", action="store_true",
                    help="直接回写 data/clean（仅在可写环境中使用；容器内该目录为只读）")
    args = ap.parse_args()

    from utils.llm_client import chat

    os.makedirs(os.path.dirname(args.progress), exist_ok=True)
    progress: Dict[str, Dict] = {}
    if os.path.exists(args.progress):
        progress = json.load(open(args.progress, encoding="utf-8"))

    files = sorted(f for f in os.listdir(args.rec_dir) if f.endswith("_recs.json"))
    loaded = {f: _load(os.path.join(args.rec_dir, f)) for f in files}

    pending: List[tuple] = []
    for f, recs in loaded.items():
        for rec in recs:
            rid = rec.get("rec_id", "")
            if rid in progress or rec.get("scenario"):
                continue
            if args.only_method and rec.get("extraction_method") != args.only_method:
                continue
            pending.append((f, rec))
    if args.limit:
        pending = pending[:args.limit]

    print(f"待标注 {len(pending)} 条（已完成 {len(progress)} 条），批大小 {args.batch_size}")

    est_in, est_out = 0, 0
    filled = 0
    t0 = time.time()
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        items = [{"id": rec["rec_id"], "breadcrumb": rec.get("breadcrumb", ""),
                  "text": (rec.get("recommendation_text") or "")[:450]} for _, rec in batch]
        prompt = PROMPT.format(s="、".join(SCENARIOS), l="、".join(LEVELS),
                               items=json.dumps(items, ensure_ascii=False))
        est_in += len(prompt) // 4

        result: Dict[str, Dict] = {}
        for attempt in range(args.retries + 1):
            try:
                text = chat(prompt, model=None, temperature=0,
                            response_format={"type": "json_object"})
                est_out += len(text) // 4
                result = _parse(text)
                if result:
                    break
            except Exception as e:
                print(f"  批次 {start//args.batch_size+1} 第 {attempt+1} 次失败: {type(e).__name__} {str(e)[:80]}")
                time.sleep(2)

        for _, rec in batch:
            hit = result.get(rec["rec_id"])
            if hit:
                progress[rec["rec_id"]] = hit
                filled += 1

        if (start // args.batch_size + 1) % 10 == 0:
            done = start + len(batch)
            print(f"  进度 {done}/{len(pending)}，已标注 {filled}，"
                  f"耗时 {time.time()-t0:.0f}s，估算 token {est_in+est_out}", flush=True)

    # 容器内 data/clean 为只读挂载（防止服务写数据），因此默认只落进度文件，
    # 回写由宿主机脚本 apply_rec_annotations.py 完成；--write-clean 供可写环境使用。
    if args.write_clean:
        for f, recs in loaded.items():
            changed = 0
            for rec in recs:
                hit = progress.get(rec.get("rec_id", ""))
                if hit and not rec.get("scenario"):
                    rec["scenario"] = hit["scenario"]
                    rec["evidence_level"] = hit["evidence_level"]
                    rec["evidence_level_original"] = hit.get("evidence_level_original")
                    changed += 1
            if changed:
                _save(os.path.join(args.rec_dir, f), recs)
                print(f"  写回 {f}: {changed} 条")

    with open(args.progress, "w", encoding="utf-8") as fh:
        json.dump(progress, fh, ensure_ascii=False, indent=1)

    print(f"\n完成：标注 {filled} 条，累计进度 {len(progress)} 条；"
          f"估算 token 输入 {est_in} / 输出 {est_out}；总耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
