"""P6 步骤二：把容器内产出的标注进度回写到 data/clean（宿主机执行）。

容器内 data/clean 是只读挂载，LLM 标注脚本只写
data/intermediate/rec_annotation_progress.json；本脚本读该进度文件，
把 scenario / evidence_level 填回各 *_recs.json（仅填 null 项，幂等）。

用法（宿主机）：
  python scripts/data_pipeline/apply_rec_annotations.py
"""
import argparse
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REC_DIR = os.path.join(BASE_DIR, "data", "clean", "recommendations")
PROGRESS = os.path.join(BASE_DIR, "data", "intermediate", "rec_annotation_progress.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="P6 标注回写")
    ap.add_argument("--progress", default=PROGRESS)
    ap.add_argument("--rec-dir", default=REC_DIR)
    args = ap.parse_args()

    if not os.path.exists(args.progress):
        raise SystemExit(f"进度文件不存在：{args.progress}（请先在容器内跑 annotate_recs.py）")

    progress = json.load(open(args.progress, encoding="utf-8"))
    total_changed = 0
    for name in sorted(os.listdir(args.rec_dir)):
        if not name.endswith("_recs.json"):
            continue
        path = os.path.join(args.rec_dir, name)
        recs = json.load(open(path, encoding="utf-8"))
        changed = 0
        for rec in recs:
            hit = progress.get(rec.get("rec_id", ""))
            if hit and not rec.get("scenario"):
                rec["scenario"] = hit["scenario"]
                rec["evidence_level"] = hit.get("evidence_level")
                rec["evidence_level_original"] = hit.get("evidence_level_original")
                changed += 1
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(recs, f, ensure_ascii=False, indent=1)
            total_changed += changed
            print(f"  {name}: 回填 {changed} 条")

    print(f"合计回填 {total_changed} 条（进度文件共 {len(progress)} 条）")


if __name__ == "__main__":
    main()
