# -*- coding: utf-8 -*-
"""步骤6（kgdrug）：从 cache/kgdrug/triples.jsonl 抽取 5 癌种子图 → data/clean/kg/kgdrug/

做法：
1. 用 `jibingname` 定位疾病实体名，按需求清单 5 癌种关键词命中的疾病实体作为种子
2. 展开种子疾病实体的全部属性三元组（概述/病因/治疗/预防/并发症/症状/别名）
3. 反向补充与种子疾病相连的药物（needcure/cure/relatedisease）及其名称类属性
4. 关联症状实体补 zzname（症状名）与所属癌种
5. 输出对齐需求清单 A6「知识图谱关系」的 JSON

用法：python tools/6_filter_cancer_kg.py（需先跑步骤5）
"""
import json
import os
import re
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache", "kgdrug")
OUT_DIR = os.path.join(BASE, "data", "clean", "kg_triples")
OUT = os.path.join(OUT_DIR, "kg_cancer_subgraph.json")

SOURCE_TEXT = "gStore 医药知识图谱 kgdrug.com（2018 建库，原始 N-Triples 已缺失，由索引文件解码）"

TODAY = "2026-10-24"

# 癌种 → 疾病名关键词（对齐需求清单 §6.1 受控词表）
CANCER_KW = {
    "lung": ["肺癌", "肺腺癌", "肺鳞癌", "小细胞肺癌", "非小细胞肺癌", "支气管肺癌"],
    "breast": ["乳腺癌", "乳腺恶性肿瘤"],
    "colorectal": ["结直肠癌", "结肠癌", "直肠癌", "大肠癌", "肛管癌"],
    "gastric": ["胃癌", "胃恶性肿瘤"],
    "thyroid": ["甲状腺癌", "甲状腺恶性肿瘤"],
}
SCOPE = {"lung": "LUNG", "breast": "BREAST", "colorectal": "CRC", "gastric": "GAS", "thyroid": "THY"}

# 名称噪声：含这些词的多为术后状态/综合征/非癌病理类型，不作为癌种主实体
NOISE_KW = ["术后", "综合征", "疝", "肉瘤", "瘤病", "疑似", "筛查", "转移"]

# 谓词 → (关系名, 头实体类型, 尾实体类型)
REL_MAP = {
    "haszhengzhuang": ("has_symptom", "disease", "symptom"),
    "relatedisease": ("related_disease", "symptom", "disease"),
    "needcure": ("needs_drug", "disease", "drug"),
    "cure": ("treated_by", "disease", "drug"),
    "bingyin": ("cause", "disease", "text"),
    "gaishu": ("overview", "disease", "text"),
    "zhiliao": ("treatment", "disease", "text"),
    "yufang": ("prevention", "disease", "text"),
    "bingfazheng": ("complication", "disease", "text"),
    "jibingname": ("disease_name", "disease", "text"),
    "zzname": ("symptom_name", "symptom", "text"),
    "zzbingyin": ("symptom_cause", "symptom", "text"),
    "zzgaishu": ("symptom_overview", "symptom", "text"),
    "zzyufang": ("symptom_prevention", "symptom", "text"),
    "proname": ("drug_name", "drug", "text"),
    "gazhzh": ("drug_alias", "drug", "text"),
    "pzwh": ("drug_approval_no", "drug", "text"),
}


def local_name(uri):
    s = uri.strip("<>")
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def entity_key(uri):
    """file:///...#disease/1001176 -> disease/1001176"""
    s = uri.strip("<>")
    return s.rsplit("#", 1)[-1] if "#" in s else s


def entity_type(uri):
    k = entity_key(uri)
    t = k.split("/", 1)[0] if "/" in k else "unknown"
    return "drug" if t == "drugs" else t


def lit(text):
    return text.strip().strip('"')


def clean_text(text):
    return re.sub(r"[ \t]+", " ", lit(text)).strip()


def main():
    with open(os.path.join(CACHE, "triples.jsonl"), encoding="utf-8") as f:
        triples = [json.loads(line) for line in f]

    # 建索引：subject -> [(pred, object)]
    by_subj = defaultdict(list)
    for t in triples:
        by_subj[t["s"]].append((t["p"], t["o"]))

    # 1) 按 jibingname 找癌种疾病实体
    cand = {}           # disease uri -> cancer_type（候选）
    cand_names = {}     # disease uri -> 名称
    for t in triples:
        if local_name(t["p"]) != "jibingname":
            continue
        name = clean_text(t["o"])
        if any(k in name for k in NOISE_KW):
            continue
        for ctype, kws in CANCER_KW.items():
            if any(kw in name for kw in kws):
                cand.setdefault(t["s"], ctype)
                cand_names[t["s"]] = name
                break

    # 同名实体去重：同一癌种下同名疾病保留属性最多者
    seed, disease_names = {}, {}
    best = {}
    for uri, ctype in cand.items():
        key = (ctype, cand_names[uri])
        score = len(by_subj.get(uri, []))
        if key not in best or score > best[key][0]:
            best[key] = (score, uri)
    for (ctype, name), (_, uri) in best.items():
        seed[uri] = ctype
        disease_names[uri] = name

    # 2) 收集种子疾病全部属性
    records, rel_counter, per_cancer = [], Counter(), Counter()
    seq = Counter()
    linked_symptom_targets = set()

    def push(head_uri, pred, tail_uri=None, tail_text=None, ctype=None):
        rel, htype, ttype = REL_MAP.get(pred, (pred, "unknown", "text"))
        cn = SCOPE.get(ctype, "GEN")
        seq[cn] += 1
        head_id = entity_key(head_uri)
        rec_tail = ({"id": entity_key(tail_uri), "type": entity_type(tail_uri), "name": names.get(tail_uri, "")}
                    if tail_uri else {"text": tail_text})
        records.append({
            "relation_id": "KG-%s-%05d" % (cn, seq[cn]),
            "head": {"id": head_id, "type": htype, "name": names.get(head_uri, "")},
            "relation": rel,
            "raw_predicate": pred,
            "tail": rec_tail,
            "cancer_type": ctype,
            "source": SOURCE_TEXT,
            "origin": "kgdrug",
            "annotation": {"annotator": "自动转换", "date": TODAY, "status": "draft"},
        })
        rel_counter[rel] += 1
        per_cancer[ctype] += 1

    # 预建：症状/疾病/药物名称表
    names = {}
    for t in triples:
        p = local_name(t["p"])
        if p in ("jibingname", "zzname", "proname", "gazhzh"):
            names.setdefault(t["s"], clean_text(t["o"]))

    # 2a) 种子疾病的属性三元组（含疾病→药物、疾病→症状）
    linked_symptom_targets = set()
    linked_drug_targets = {}
    for d_uri, ctype in seed.items():
        for p_uri, o in by_subj.get(d_uri, []):
            p = local_name(p_uri)
            if p in ("type", "label") or p not in REL_MAP:
                continue
            if o.startswith("<") and o.endswith(">"):
                push(d_uri, p, tail_uri=o, ctype=ctype)
                if p == "haszhengzhuang":
                    linked_symptom_targets.add(o)
                elif p in ("needcure", "cure"):
                    linked_drug_targets.setdefault(o, ctype)
            else:
                push(d_uri, p, tail_text=clean_text(o), ctype=ctype)

    # 2b) 关联药物补名称类属性（proname/gazhzh/pzwh）
    for drug_uri, ctype in linked_drug_targets.items():
        for p_uri, o in by_subj.get(drug_uri, []):
            p = local_name(p_uri)
            if p in ("proname", "gazhzh", "pzwh"):
                push(drug_uri, p, tail_text=clean_text(o), ctype=ctype)

    # 2c) 关联症状补名称与固有属性
    for s_uri in sorted(linked_symptom_targets):
        ctype = None
        for t in by_subj.get(s_uri, []):
            if local_name(t[0]) == "relatedisease" and t[1] in seed:
                ctype = seed[t[1]]
                break
        for p_uri, o in by_subj.get(s_uri, []):
            p = local_name(p_uri)
            if p not in ("zzname", "zzgaishu", "zzbingyin", "zzyufang"):
                continue
            push(s_uri, p, tail_text=clean_text(o), ctype=ctype or "general")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print("种子疾病实体: %d" % len(seed))
    for d, c in sorted(seed.items(), key=lambda x: x[1]):
        print("  %-12s %s" % (c, disease_names.get(d, d)))
    print("\n关系总数: %d" % len(records))
    print("癌种分布:", dict(per_cancer))
    print("关系类型分布:")
    for k, v in rel_counter.most_common():
        print("  %-22s %d" % (k, v))
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
