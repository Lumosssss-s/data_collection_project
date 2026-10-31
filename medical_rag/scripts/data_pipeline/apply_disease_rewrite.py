"""A3 方案 2 步骤二：把 LLM 改写结果合并回 data/clean/disease_profiles（宿主机执行）。

只覆盖 sections / patient_version / section_evidence，保留原溯源字段；
未改写成功的节保留原英文摘录，缺口仍记在 section_gaps。
"""
import argparse
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE_DIR = os.path.join(BASE_DIR, "data", "clean", "disease_profiles")
REWRITE_DIR = os.path.join(BASE_DIR, "data", "intermediate", "disease_rewrite")


def main() -> None:
    ap = argparse.ArgumentParser(description="合并 LLM 改写结果")
    ap.add_argument("--profile-dir", default=PROFILE_DIR)
    ap.add_argument("--rewrite-dir", default=REWRITE_DIR)
    args = ap.parse_args()

    for name in sorted(os.listdir(args.rewrite_dir)):
        if not name.endswith(".json"):
            continue
        rewrite = json.load(open(os.path.join(args.rewrite_dir, name), encoding="utf-8"))
        did = rewrite["disease_id"]
        path = os.path.join(args.profile_dir, f"{did}.json")
        profile = json.load(open(path, encoding="utf-8"))

        secs = profile.setdefault("sections", {})
        patient = profile.setdefault("patient_version", {})
        evidence = {}
        for sec, text in rewrite.get("sections", {}).items():
            secs[sec] = text
        for sec, text in rewrite.get("patient_version", {}).items():
            patient[sec] = text
        evidence = rewrite.get("evidence_excerpts", {})
        if evidence:
            profile["section_evidence"] = evidence

        profile["profile_version"] = "2026.10-llm-draft"
        sources = set(profile.get("sources") or [])
        sources.add("LLM改写（基于指南/kgdrug 摘录，未经医学审核）")
        profile["sources"] = sorted(sources)

        # 刷新缺口：已补齐的节从缺口清单移除
        gaps = []
        for gap in profile.get("section_gaps") or []:
            key = gap.split(":", 1)[0]
            if secs.get(key):
                continue
            gaps.append(gap)
        profile["section_gaps"] = gaps

        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=1)
        print(f"  {did}: 中文节 {sum(1 for v in secs.values() if v)}/20，"
              f"患者版 {sum(1 for v in patient.values() if v)}/20，缺口 {len(gaps)}")


if __name__ == "__main__":
    main()
