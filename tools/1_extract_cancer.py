# -*- coding: utf-8 -*-
"""步骤1：解压 cMedQA2 原始包 → 筛选 5 大癌种相关问答 → 输出中间产物到 cache/。

用法：在项目根目录执行
    python tools/1_extract_cancer.py
"""
import csv
import os
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw", "cmedqa2")            # 输入原文件（数据集 cmedqa2）
CACHE = os.path.join(BASE, "cache", "cmedqa2")        # 中间产物缓存（按数据集分目录）
UNZIP = os.path.join(CACHE, "_unzipped")             # 解压临时目录

# 5 大癌种关键词（对齐需求清单 §6.1 受控词表；小写化以兼容 肺ca/肺CA）
KEYWORDS = {
    "lung":       ["肺癌", "肺恶性肿瘤", "肺ca", "支气管肺癌", "肺腺癌", "肺鳞癌",
                   "小细胞肺癌", "非小细胞肺癌", "肺结节", "肺占位", "肺磨玻璃", "nsclc", "sclc"],
    "breast":     ["乳腺癌", "乳腺恶性肿瘤", "乳癌", "乳腺ca", "乳腺浸润性导管癌",
                   "三阴性乳腺癌", "乳腺腺癌", "乳腺结节"],
    "colorectal": ["结直肠癌", "结肠癌", "直肠癌", "大肠癌", "肠癌", "结肠腺癌",
                   "直肠腺癌", "结肠恶性肿瘤", "直肠恶性肿瘤"],
    "gastric":    ["胃癌", "胃恶性肿瘤", "胃腺癌", "胃印戒细胞癌", "贲门癌", "胃ca"],
    "thyroid":    ["甲状腺癌", "甲状腺恶性肿瘤", "甲状腺乳头状癌", "甲状腺滤泡癌",
                   "甲状腺髓样癌", "甲状腺未分化癌", "甲状腺微小乳头状癌", "甲状腺结节"],
}


def match_types(text):
    low = text.lower()
    return [t for t, kws in KEYWORDS.items() if any(k in low for k in kws)]


def unzip_all():
    os.makedirs(UNZIP, exist_ok=True)
    for name in os.listdir(RAW):
        if name.endswith(".zip"):
            # 每个 zip 解压到以其命名的子目录（zip 内部无子目录，文件直接平铺）
            target = os.path.join(UNZIP, os.path.splitext(name)[0])
            os.makedirs(target, exist_ok=True)
            with zipfile.ZipFile(os.path.join(RAW, name)) as z:
                z.extractall(target)


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        next(r, None)  # 跳过表头
        return [row for row in r if row]


def main():
    unzip_all()
    os.makedirs(CACHE, exist_ok=True)

    # 1) 筛选问题
    qid2row = {}
    qid2types = {}
    for row in read_rows(os.path.join(UNZIP, "question", "question.csv")):
        qid = row[0].strip()
        hits = match_types(row[1] if len(row) > 1 else "")
        if hits:
            qid2row[qid] = row
            qid2types[qid] = hits
    cancer_qids = set(qid2row)

    with open(os.path.join(CACHE, "questions_cancer.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question_id", "content", "cancer_type"])
        for qid, row in qid2row.items():
            w.writerow([row[0], row[1], "|".join(sorted(qid2types[qid]))])

    # 2) 筛选答案
    with open(os.path.join(CACHE, "answers_cancer.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ans_id", "question_id", "content"])
        for row in read_rows(os.path.join(UNZIP, "answer", "answer.csv")):
            if row[1].strip() in cancer_qids:
                w.writerow(row)

    # 3) 筛选候选（train / dev / test 三种格式）
    def filter_candidates(fname, out_name, qid_col):
        with open(os.path.join(UNZIP, fname, fname + ".txt"), encoding="utf-8", newline="") as fin, \
                open(os.path.join(CACHE, out_name), "w", encoding="utf-8", newline="") as fout:
            r = csv.reader(fin)
            header = next(r)
            fout.write(",".join(header) + "\n")
            for row in r:
                if row and row[qid_col].strip() in cancer_qids:
                    fout.write(",".join(row) + "\n")

    filter_candidates("train_candidates", "train_candidates_cancer.txt", 0)
    filter_candidates("dev_candidates", "dev_candidates_cancer.txt", 0)
    filter_candidates("test_candidates", "test_candidates_cancer.txt", 0)

    print("癌症相关问题总数:", len(cancer_qids))
    print("DONE ->", CACHE)


if __name__ == "__main__":
    main()
