"""C1 检索评测集扩充：40 → 115 条（零 token，人工编题 + 章节对照校验）。

构造方式：
  1. 人工按 6 份指南的章节结构编写 75 条中文/英文临床查询（query_type 覆盖
     单条件 / 多条件 / 口语化 / 英文），gold = 该主题所在指南的 doc_id。
  2. 每条查询附带英文校验词（verify），脚本逐条检查这些词确实出现在该指南的
     推荐条目文本中；校验失败的条目不写入，避免「编出来的题指南里根本没讲」。
  3. 与自建的 40 条做近重复（>0.9）过滤，最后追加到 eval_retrieval.json。

为什么不直接用 cmedQA2 问题：cmedQA2 是患者口述的症状/预后提问（「便血是不是
肠癌」「晚期还能活多久」），本库 6 份指南不覆盖这些主题，强行配 gold 会产生错误
标注；cmedQA2 更适合用于 C2 问答评测（另见 P2 的问答侧规划）。
"""
from __future__ import annotations

import difflib
import json
import os
import re
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REC_DIR = os.path.join(BASE_DIR, "data", "clean", "recommendations")
EVAL_PATH = os.path.join(BASE_DIR, "data", "clean", "eval_sets", "eval_retrieval.json")

DOC_CANCER = {
    "DOC-LUNG-EPMC-001": "lung", "DOC-LUNG-EPMC-002": "lung", "DOC-LUNG-EPMC-003": "lung",
    "DOC-COLORECTAL-EPMC-001": "colorectal",
    "DOC-COLORECTAL-EPMC-002": "colorectal",
    "DOC-COLORECTAL-EPMC-003": "colorectal",
}

# (doc_id, 查询, 题型, 难度, 校验词[必须在该指南推荐文本中出现])
CURATED: List[Tuple[str, str, str, str, List[str]]] = [
    # ---- DOC-LUNG-EPMC-001 澳大利亚国家肺癌筛查项目 ----
    ("DOC-LUNG-EPMC-001", "肺癌筛查项目的纳入人群资格标准是什么？", "单条件", "easy",
     ["eligibility", "risk"]),
    ("DOC-LUNG-EPMC-001", "澳大利亚国家肺癌筛查项目低剂量CT申请条件", "多条件", "medium",
     ["low-dose ct", "request"]),
    ("DOC-LUNG-EPMC-001", "肺癌筛查结果出来后下一步怎么安排随访？", "多条件", "medium",
     ["report", "follow-up"]),
    ("DOC-LUNG-EPMC-001", "肺癌筛查项目里怎么开展戒烟干预？", "多条件", "medium",
     ["smoking cessation"]),
    ("DOC-LUNG-EPMC-001", "参加肺癌筛查要抽多少包年吸烟史才够条件？", "单条件", "easy",
     ["pack-year"]),
    ("DOC-LUNG-EPMC-001", "肺癌筛查项目怎么招募和登记受检者？", "单条件", "medium",
     ["recruit"]),
    ("DOC-LUNG-EPMC-001", "筛查发现肺结节以后下一步做什么检查？", "多条件", "medium",
     ["nodule", "next"]),
    ("DOC-LUNG-EPMC-001", "low-dose CT eligibility criteria in the national lung cancer screening program",
     "英文", "medium", ["eligibility", "low-dose ct"]),
    ("DOC-LUNG-EPMC-001", "smoking cessation support within a lung cancer screening program",
     "英文", "medium", ["smoking cessation"]),
    ("DOC-LUNG-EPMC-001", "肺癌筛查报告里需要写哪些内容？", "单条件", "medium",
     ["report"]),

    # ---- DOC-LUNG-EPMC-002 老年肺癌围手术期综合管理 ----
    ("DOC-LUNG-EPMC-002", "老年肺癌患者术前衰弱怎么评估？", "单条件", "easy",
     ["frailty"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌病人合并肌少症怎么处理？", "单条件", "medium",
     ["sarcopenia"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌合并糖尿病和慢性肾病，围手术期降糖药怎么调整？", "多条件", "medium",
     ["sglt2", "ckd"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌术后谵妄如何预防？", "单条件", "easy",
     ["delirium"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌术前综合老年评估包含哪些内容？", "单条件", "easy",
     ["comprehensive geriatric assessment"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌患者术后肺部并发症怎么预防？", "多条件", "medium",
     ["pulmonary complications"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌手术能不能用加速康复外科路径？", "多条件", "medium",
     ["enhanced recovery"]),
    ("DOC-LUNG-EPMC-002", "80岁肺癌老人做肺叶切除风险大吗？", "口语化", "hard",
     ["lobectomy"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌术前预康复训练包括什么？", "单条件", "medium",
     ["prehabilitation"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌术后跌倒和营养不良怎么防？", "多条件", "medium",
     ["falls", "nutrition"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌合并心血管疾病，围手术期用药要不要停？", "多条件", "medium",
     ["cardiovascular"]),
    ("DOC-LUNG-EPMC-002", "老年肺癌选肺段切除还是肺叶切除？", "多条件", "hard",
     ["segmentectomy", "lobectomy"]),

    # ---- DOC-LUNG-EPMC-003 ESR 低剂量CT 筛查要点 ----
    ("DOC-LUNG-EPMC-003", "低剂量CT筛查肺癌的辐射剂量要求是多少？", "多条件", "medium",
     ["radiation dose"]),
    ("DOC-LUNG-EPMC-003", "肺癌筛查的阳性、阴性、不确定结果怎么定义？", "多条件", "medium",
     ["positive", "indeterminate"]),
    ("DOC-LUNG-EPMC-003", "亚实性结节和磨玻璃结节应该怎么随访？", "多条件", "medium",
     ["subsolid"]),
    ("DOC-LUNG-EPMC-003", "肺癌筛查多久查一次合适？", "口语化", "easy",
     ["interval"]),
    ("DOC-LUNG-EPMC-003", "AI软件在肺癌筛查阅片中起什么作用？", "单条件", "medium",
     ["artificial intelligence"]),
    ("DOC-LUNG-EPMC-003", "肺内淋巴结这类良性表现怎么判断？", "多条件", "hard",
     ["intrapulmonary lymph node"]),
    ("DOC-LUNG-EPMC-003", "低剂量CT筛查设备的技术参数有什么要求？", "单条件", "medium",
     ["technical requirement"]),
    ("DOC-LUNG-EPMC-003", "肺癌筛查结构化报告模板要写哪些内容？", "多条件", "medium",
     ["structured report"]),
    ("DOC-LUNG-EPMC-003", "磨玻璃结节过度诊断的风险怎么控制？", "多条件", "hard",
     ["overdiagnosis"]),
    ("DOC-LUNG-EPMC-003", "lung cancer screening eligibility and screening intervals with low-dose CT",
     "英文", "medium", ["eligibility", "interval"]),
    ("DOC-LUNG-EPMC-003", "technical requirements and radiation dose of low-dose CT screening",
     "英文", "medium", ["technical", "radiation dose"]),

    # ---- DOC-COLORECTAL-EPMC-001 ESMO II/III 期治疗更新 ----
    ("DOC-COLORECTAL-EPMC-001", "II期和III期结肠癌辅助化疗方案怎么选？", "多条件", "medium",
     ["adjuvant", "stage ii"], ["DOC-COLORECTAL-EPMC-002"]),
    ("DOC-COLORECTAL-EPMC-001", "结肠癌术后化疗要打几次啊？", "口语化", "medium",
     ["months", "adjuvant"], ["DOC-COLORECTAL-EPMC-002"]),
    ("DOC-COLORECTAL-EPMC-001", "III期结肠癌用奥沙利铂还是卡培他滨？", "多条件", "medium",
     ["oxaliplatin", "capecitabine"], ["DOC-COLORECTAL-EPMC-002"]),
    ("DOC-COLORECTAL-EPMC-001", "结肠癌辅助治疗前要不要做MSI检测？", "多条件", "medium",
     ["msi"], ["DOC-COLORECTAL-EPMC-002", "DOC-COLORECTAL-EPMC-003"]),
    ("DOC-COLORECTAL-EPMC-001", "高危II期结肠癌需要辅助化疗吗？", "单条件", "medium",
     ["high-risk", "stage ii"], ["DOC-COLORECTAL-EPMC-002"]),
    ("DOC-COLORECTAL-EPMC-001", "70岁以上结肠癌患者辅助化疗要不要减量？", "多条件", "medium",
     ["age", "adjuvant"], ["DOC-COLORECTAL-EPMC-002"]),
    ("DOC-COLORECTAL-EPMC-001", "stage II and III colon cancer adjuvant chemotherapy recommendations",
     "英文", "medium", ["adjuvant", "stage iii"]),
    ("DOC-COLORECTAL-EPMC-001", "结肠癌辅助化疗的疗程和方案怎么定？", "单条件", "medium",
     ["adjuvant chemotherapy"]),

    # ---- DOC-COLORECTAL-EPMC-002 JSCCR 结直肠癌治疗指南 ----
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌肝转移能手术切除吗？", "单条件", "easy",
     ["liver metastasis", "resection"]),
    ("DOC-COLORECTAL-EPMC-002", "直肠癌新辅助放化疗后什么时候手术？", "多条件", "medium",
     ["neoadjuvant", "chemoradiotherapy"]),
    ("DOC-COLORECTAL-EPMC-002", "直肠癌全直肠系膜切除的原则是什么？", "单条件", "easy",
     ["total mesorectal excision"]),
    ("DOC-COLORECTAL-EPMC-002", "直肠癌侧方淋巴结清扫什么时候做？", "单条件", "medium",
     ["lateral lymph node"]),
    ("DOC-COLORECTAL-EPMC-002", "肠癌做完手术多久复查一次啊？", "口语化", "medium",
     ["follow-up", "surveillance"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌化疗方案FOLFOX和FOLFIRI怎么选？", "多条件", "medium",
     ["folfox", "folfiri"]),
    ("DOC-COLORECTAL-EPMC-002", "不可切除的结直肠癌肝转移转化治疗怎么做？", "多条件", "medium",
     ["conversion", "liver metastasis"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌术后肠镜复查安排在什么时候？", "单条件", "medium",
     ["colonoscopy"]),
    ("DOC-COLORECTAL-EPMC-002", "直肠癌术前放化疗的剂量和疗程怎么定？", "多条件", "medium",
     ["radiation", "dose"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌梗阻或穿孔需要急诊手术吗？", "多条件", "medium",
     ["obstruction", "perforation"]),
    ("DOC-COLORECTAL-EPMC-002", "局部复发的直肠癌怎么治疗？", "单条件", "medium",
     ["recurrence"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌腹膜转移怎么处理？", "单条件", "medium",
     ["peritoneal"]),
    ("DOC-COLORECTAL-EPMC-002", "结肠癌手术的淋巴结清扫范围怎么定？", "单条件", "hard",
     ["lymph node", "dissection"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌术后辅助化疗什么时候开始？", "单条件", "medium",
     ["adjuvant chemotherapy"]),
    ("DOC-COLORECTAL-EPMC-002", "直肠癌还能不能保住肛门？", "口语化", "hard",
     ["sphincter"]),
    ("DOC-COLORECTAL-EPMC-002", "colorectal cancer liver metastasis resection criteria",
     "英文", "medium", ["liver metastasis", "resection"]),
    ("DOC-COLORECTAL-EPMC-002", "老人肠癌化疗受不了怎么办？", "口语化", "hard",
     ["elderly", "chemotherapy"]),
    ("DOC-COLORECTAL-EPMC-002", "肠癌化疗失败以后还能换什么方案？", "口语化", "hard",
     ["second-line", "chemotherapy"]),
    ("DOC-COLORECTAL-EPMC-002", "结直肠癌手术切缘要求是多少？", "单条件", "medium",
     ["margin"]),

    # ---- DOC-COLORECTAL-EPMC-003 JSCCR 遗传性结直肠癌 ----
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征怎么诊断？", "单条件", "easy",
     ["lynch syndrome", "diagnosis"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征结肠镜监测多久一次？", "多条件", "medium",
     ["lynch syndrome", "surveillance"]),
    ("DOC-COLORECTAL-EPMC-003", "家族性腺瘤性息肉病什么时候开始肠镜监测？", "多条件", "medium",
     ["adenomatous polyposis", "surveillance"]),
    ("DOC-COLORECTAL-EPMC-003", "遗传性结直肠癌需要做基因检测吗？", "单条件", "easy",
     ["genetic testing"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征要不要预防性切除子宫和卵巢？", "多条件", "medium",
     ["hysterectomy", "salpingo-oophorectomy"]),
    ("DOC-COLORECTAL-EPMC-003", "结直肠癌患者都要做错配修复缺陷筛查吗？", "多条件", "medium",
     ["universal screening", "mismatch repair"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征用阿司匹林做化学预防有效吗？", "多条件", "medium",
     ["chemoprevention", "aspirin"]),
    ("DOC-COLORECTAL-EPMC-003", "家族性腺瘤性息肉病什么时候做预防性结肠切除？", "多条件", "medium",
     ["colectomy", "polyposis"]),
    ("DOC-COLORECTAL-EPMC-003", "遗传性结直肠癌的家系成员怎么管理？", "单条件", "medium",
     ["relatives"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征患者要不要查幽门螺杆菌？", "多条件", "hard",
     ["helicobacter", "lynch"]),
    ("DOC-COLORECTAL-EPMC-003", "Lynch syndrome surveillance intervals and risk-reducing surgery",
     "英文", "medium", ["lynch syndrome", "risk-reducing"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征相关的子宫内膜癌怎么筛查？", "单条件", "medium",
     ["endometrial"]),
    ("DOC-COLORECTAL-EPMC-003", "遗传性结直肠癌的遗传咨询流程是什么？", "单条件", "medium",
     ["genetic counseling"]),
    ("DOC-COLORECTAL-EPMC-003", "家里有人得肠癌，我要不要去做基因检测？", "口语化", "hard",
     ["relatives", "genetic"]),
    ("DOC-COLORECTAL-EPMC-003", "林奇综合征肠镜到底多久查一次合适？", "口语化", "medium",
     ["lynch syndrome", "colonoscopy"]),
]


_DASHES = {"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-"}


def _norm_text(text: str) -> str:
    """统一小写并折算各种 Unicode 连字符——指南原文用 U+2010（low‐dose），
    不折算会让「low-dose CT」这类校验词全部落空。"""
    out = (text or "").lower()
    for src, dst in _DASHES.items():
        out = out.replace(src, dst)
    return out


def _load_doc_text() -> Dict[str, str]:
    """把每份指南的全部推荐条目文本拼成大文本，用于校验词命中。"""
    out: Dict[str, str] = {}
    for name in os.listdir(REC_DIR):
        if not name.endswith("_recs.json"):
            continue
        doc_id = name.replace("_recs.json", "")
        items = json.load(open(os.path.join(REC_DIR, name), encoding="utf-8"))
        out[doc_id] = _norm_text(" ".join(
            str(it.get(k) or "") for it in items
            for k in ("recommendation_text", "verbatim", "breadcrumb")
        ))
    return out


def main() -> None:
    existing = [it for it in json.load(open(EVAL_PATH, encoding="utf-8"))
                if it.get("origin") != "corpus_derived"]
    doc_text = _load_doc_text()

    generated: List[Dict] = []
    rejected: List[str] = []
    for row in CURATED:
        doc_id, query, qtype, difficulty, verify = row[:5]
        # 同一临床主题可能同时被多份指南覆盖（ESMO 更新版 + JSCCR 治疗指南），
        # 这些题目的 gold 同时收录同癌种的其他指南，避免把「换一份指南命中」判为失败。
        extra_docs = list(row[5]) if len(row) > 5 else []
        if not all(re.search(re.escape(k.lower()), doc_text.get(doc_id, "")) for k in verify):
            rejected.append(f"{doc_id} | {query} | 未命中校验词 {verify}")  # noqa: E501
            continue
        if any(difflib.SequenceMatcher(None, query, it["query"]).ratio() > 0.9 for it in existing):
            rejected.append(f"{doc_id} | {query} | 与既有条目近重复")
            continue
        generated.append({
            "id": "", "qid": "", "task_type": "retrieval", "query_type": qtype,
            "query": query, "input": query,
            "relevant": [{"doc_id": doc_id, "relevance": 2}] +
                        [{"doc_id": d, "relevance": 1} for d in extra_docs],
            "gold": {"rec_ids": [], "doc_ids": [doc_id] + extra_docs},
            "difficulty": difficulty,
            "cancer_type": DOC_CANCER[doc_id],
            "origin": "corpus_derived",
            "annotation": {
                "annotator": "人工编题-工程（章节对照 + 校验词核验）",
                "date": "2026-10-25",
                "status": "draft",
                "mapping_note": "gold 为题目主题所在指南；已用英文校验词核验该主题确在该指南推荐条目中出现",
            },
        })

    for i, item in enumerate(generated, start=len(existing) + 1):
        item["id"] = f"EVAL-RETRIEVAL-{i:04d}"
        item["qid"] = item["id"]

    merged = existing + generated
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join("  " + json.dumps(it, ensure_ascii=False) for it in merged))
        f.write("\n]\n")

    from collections import Counter
    print(f"新增 {len(generated)} 条，合并后 {len(merged)} 条；剔除 {len(rejected)} 条")
    print("query_type:", dict(Counter(it["query_type"] for it in generated)))
    print("doc:", dict(Counter(it["relevant"][0]["doc_id"] for it in generated)))
    print("difficulty:", dict(Counter(it["difficulty"] for it in generated)))
    if rejected:
        print("\n剔除明细：")
        for line in rejected:
            print("  -", line)


if __name__ == "__main__":
    main()
