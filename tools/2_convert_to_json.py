# -*- coding: utf-8 -*-
"""步骤2：读取 cache/ 中间产物 → 生成对齐需求清单 task_type=qa 的 JSON 到 data/clean/eval_sets/。

用法：在项目根目录执行（需先跑步骤1）
    python tools/2_convert_to_json.py
"""
import csv
import json
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache", "cmedqa2")       # 中间产物缓存（数据集 cmedqa2）
OUT = os.path.join(BASE, "data", "clean", "eval_sets", "eval_qa_cancer.json")

SOURCE_TEXT = "cMedQA2 v2.0（GitHub zhangsheng93/cMedQA2，中文社区医疗问答，仅限非商业研究）"


def read_questions():
    with open(os.path.join(CACHE, "questions_cancer.csv"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_answers_by_q():
    ans_map = {}
    q_ans = {}
    with open(os.path.join(CACHE, "answers_cancer.csv"), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            aid = row["ans_id"].strip()
            qid = row["question_id"].strip()
            ans_map[aid] = row["content"]
            q_ans.setdefault(qid, [])
            if aid not in q_ans[qid]:
                q_ans[qid].append(aid)
    return ans_map, q_ans


def collect_positive(fname, mode):
    """mode='train' 取 pos_ans_id 列；mode='cand' 取 label==1 行。"""
    pos = {}
    with open(os.path.join(CACHE, fname), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            qid = row["question_id"].strip()
            if mode == "train":
                ans = row["pos_ans_id"].strip()
            else:
                if row.get("label", "").strip() != "1":
                    continue
                ans = row["ans_id"].strip()
            pos.setdefault(qid, [])
            if ans not in pos[qid]:
                pos[qid].append(ans)
    return pos


def main():
    questions = read_questions()
    ans_map, q_ans = read_answers_by_q()

    pos = {}
    for fname, mode in [("train_candidates_cancer.txt", "train"),
                        ("dev_candidates_cancer.txt", "cand"),
                        ("test_candidates_cancer.txt", "cand")]:
        for qid, lst in collect_positive(fname, mode).items():
            pos.setdefault(qid, [])
            for a in lst:
                if a not in pos[qid]:
                    pos[qid].append(a)

    records = []
    labeled = fallback = 0
    for i, q in enumerate(questions, 1):
        qid = q["question_id"].strip()
        types = [t.strip() for t in q["cancer_type"].split("|") if t.strip()]
        primary = types[0] if types else None

        ans_ids = pos.get(qid, [])
        if ans_ids and ans_map.get(ans_ids[0]):
            answer = ans_map[ans_ids[0]]
            gold_labeled = True
            labeled += 1
        else:
            fb = q_ans.get(qid, [])
            answer = ans_map.get(fb[0], "") if fb else ""
            gold_labeled = False
            fallback += 1

        records.append({
            "qid": "EVAL-QA-CMEDQA-%04d" % i,
            "task_type": "qa",
            "input": q["content"],
            "gold": {"answer": answer},
            "gold_labeled": gold_labeled,
            "cancer_type": primary,
            "source": SOURCE_TEXT,
            "origin": "cMedQA2",
            "annotation": {"annotator": "自动转换", "date": "2026-10-23", "status": "draft"},
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print("总记录数:", len(records))
    print("来自候选标签的gold(labeled):", labeled)
    print("来自首个可用回答的gold(需人工复核):", fallback)
    print("癌种分布:", dict(Counter(r["cancer_type"] for r in records)))
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
