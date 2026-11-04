# -*- coding: utf-8 -*-
"""tools/34_validate_virtual_cases.py

虚拟病例结构校验（只读，不修改数据）：
  1. 字段完整：公共字段、triage_case / mock_case 各自的强制字段
  2. 受控值合法：case_type / task_type / origin / risk_level / scenario / stage / status
  3. ID 可解析：disease_id 必须存在于 A3 疾病档案；related_recommendations
     必须全部存在于 A2 推荐条目，不允许悬空
  4. 用药可追溯：病例文本中出现的药名必须能在 drug_catalog 中命中，
     不允许自造药名（先按目录药名做最长匹配屏蔽，再扫描常见药名后缀）
  5. 无禁忌标识：真实姓名/身份证/手机号/住院号/具体医院名/含数字编号
  6. C4 叙述长度 80~200 字；C6 narrative 与 structured 固定六项齐全
  7. 合成标识：synthetic=true 且 disclaimer 为固定文案

用法：
  python tools/34_validate_virtual_cases.py
退出码 0 表示全部通过，1 表示存在错误。
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(BASE, "data", "virtual_cases", "virtual_cases_20261105.json")
A3 = os.path.join(BASE, "data", "clean", "disease_profiles", "disease_profiles_lung_20261028_v2.json")
A2 = os.path.join(BASE, "data", "clean", "recommendations", "recommendations_lung_20261028_v3.json")
DRUG = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog_v2.json")
TERM = os.path.join(BASE, "data", "clean", "terminology", "terminology_cancer.json")

DISCLAIMER = "本病例为合成数据，非真实患者，不构成医疗建议"
CASE_TYPE = {"triage_case", "mock_case"}
RISK = {"routine", "urgent", "emergency"}
SCENARIO = {"initial", "revisit", "followup", "emergency"}
STAGE = {"0", "I", "II", "III", "IV", "unknown", None}
QC_TYPE = {"completeness", "consistency", "standardization", "timeliness"}
SEVERITY = {"high", "medium", "low"}
COMMON_FIELDS = [
    "case_id", "case_type", "cancer_type", "stage", "origin", "synthetic",
    "disclaimer", "disease_id", "related_recommendations", "annotation",
    "version", "last_updated",
]
TRIAGE_FIELDS = ["qid", "task_type", "input", "gold", "difficulty"]
MOCK_FIELDS = ["scenario", "narrative", "structured", "labels"]
STRUCTURED_KEYS = ["主诉", "现病史", "既往史", "检查", "诊断", "医嘱"]

# 药名后缀：用来自造药名兜底扫描
DRUG_SUFFIX = re.compile(
    r"(?:[A-Za-z\u4e00-\u9fa5]{2,8}(?:单抗|替尼|曲塞|泊苷|司亭|替康|紫杉醇|氟尿嘧啶"
    r"|唑来膦酸|环磷酰胺|柔比星|司琼|曲唑|米特|瑞滨|他滨))"
)
# 禁忌标识
FORBIDDEN = [
    (re.compile(r"\d{17}[\dXx]"), "疑似身份证号"),
    (re.compile(r"(?<!\d)(?:1[3-9]\d{9})(?!\d)"), "疑似手机号"),
    (re.compile(r"(住院号|病历号|门诊号|床号|病案号)"), "疑似住院/病历编号"),
    (re.compile(r"[A-Za-z\u4e00-\u9fa5]{2,10}医院"), "出现具体医院名称"),
    (re.compile(r"\d{8,}"), "出现长数字串（编号/日期等）"),
    (re.compile(r"(患者姓名|姓名[：:]|身份证)"), "出现姓名/身份证字段"),
]


def load_list(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d if isinstance(d, list) else d.get("records", d)


def text_of(case):
    """汇总病例中所有可能承载内容的文本字段。"""
    parts = []
    for k in ("input", "narrative"):
        if isinstance(case.get(k), str):
            parts.append(case[k])
    for v in (case.get("structured") or {}).values():
        if isinstance(v, str):
            parts.append(v)
    gold = case.get("gold") or {}
    for v in gold.values():
        if isinstance(v, str):
            parts.append(v)
    tri = (case.get("labels") or {}).get("expected_triage") or {}
    for v in tri.values():
        if isinstance(v, str):
            parts.append(v)
    return "\n".join(parts)


def main():
    errors = []
    cases = load_list(CASES)
    diseases = {d["disease_id"] for d in load_list(A3)}
    rec_ids = {r["rec_id"] for r in load_list(A2)}
    drugs = {d["generic_name"] for d in load_list(DRUG)}
    brands = set()
    for d in load_list(DRUG):
        brands |= set(d.get("brand_names") or [])
    known_drug = sorted(drugs | brands, key=len, reverse=True)
    symptoms = {}
    for t in load_list(TERM):
        if t.get("category") == "symptom":
            symptoms[t["canonical"]] = (t["term_id"], t.get("mapping_status"))

    if not isinstance(cases, list) or not cases:
        print("FAIL 病例文件为空或不是数组")
        return 1

    ids = [c.get("case_id") for c in cases]
    if len(ids) != len(set(ids)):
        errors.append("case_id 存在重复：%s" % sorted({i for i in ids if ids.count(i) > 1}))

    triage_n = mock_n = 0
    risk_count = {}
    scen_count = {}
    for c in cases:
        cid = c.get("case_id", "<无 case_id>")
        if c.get("case_type") not in CASE_TYPE:
            errors.append("%s case_type 非法：%r" % (cid, c.get("case_type")))

        for f in COMMON_FIELDS:
            if f not in c:
                errors.append("%s 缺少字段 %s" % (cid, f))

        if c.get("synthetic") is not True:
            errors.append("%s synthetic 必须为 true" % cid)
        if c.get("disclaimer") != DISCLAIMER:
            errors.append("%s disclaimer 与固定文案不一致" % cid)
        if c.get("origin") != "self_built":
            errors.append("%s origin 应为 self_built：%r" % (cid, c.get("origin")))
        if c.get("cancer_type") != "lung":
            errors.append("%s cancer_type 应为 lung：%r" % (cid, c.get("cancer_type")))
        if c.get("stage") not in STAGE:
            errors.append("%s stage 非法：%r" % (cid, c.get("stage")))
        ann = c.get("annotation") or {}
        if ann.get("status") not in {"draft", "reviewed"}:
            errors.append("%s annotation.status 非法：%r" % (cid, ann.get("status")))
        if not ann.get("author") or not ann.get("date"):
            errors.append("%s annotation 缺少 author/date" % cid)
        rft = ann.get("red_flag_terms")
        if not isinstance(rft, list):
            errors.append("%s annotation.red_flag_terms 应为数组" % cid)
            rft = []
        for it in rft:
            if not isinstance(it, dict) or set(it) != {"raw", "canonical", "term_id", "mapping_status"}:
                errors.append("%s red_flag_terms 元素结构不符：%r" % (cid, it))
                continue
            if it["canonical"] is None:
                if it["term_id"] is not None or it["mapping_status"] is not None:
                    errors.append("%s 未映射红旗征不得带 term_id/status：%r" % (cid, it["raw"]))
            elif it["canonical"] not in symptoms:
                errors.append("%s canonical 不在 A5：%r" % (cid, it["canonical"]))
            elif symptoms[it["canonical"]][0] != it["term_id"]:
                errors.append("%s term_id 与 A5 不一致：%r" % (cid, it["canonical"]))
            elif symptoms[it["canonical"]][1] != it["mapping_status"]:
                errors.append("%s mapping_status 与 A5 不一致：%r" % (cid, it["canonical"]))
        if c.get("version") != "v1":
            errors.append("%s version 应为 v1：%r" % (cid, c.get("version")))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("last_updated"))):
            errors.append("%s last_updated 格式非法：%r" % (cid, c.get("last_updated")))

        if c.get("disease_id") not in diseases:
            errors.append("%s disease_id 悬空：%r" % (cid, c.get("disease_id")))
        recs = c.get("related_recommendations")
        if not isinstance(recs, list) or not recs:
            errors.append("%s related_recommendations 为空或非数组" % cid)
        else:
            for r in recs:
                if r not in rec_ids:
                    errors.append("%s related_recommendations 悬空：%r" % (cid, r))

        # 禁忌标识与自造药名
        text = text_of(c)
        for pat, label in FORBIDDEN:
            m = pat.search(text)
            if m:
                errors.append("%s %s：%r" % (cid, label, m.group(0)))
        masked = text
        for name in known_drug:
            masked = masked.replace(name, "□")
        for m in DRUG_SUFFIX.finditer(masked):
            errors.append("%s 出现目录外药名：%r" % (cid, m.group(0)))

        if c.get("case_type") == "triage_case":
            triage_n += 1
            for f in TRIAGE_FIELDS:
                if f not in c:
                    errors.append("%s 缺少 triage 字段 %s" % (cid, f))
            if c.get("task_type") != "triage":
                errors.append("%s task_type 应为 triage" % cid)
            if c.get("case_id") != c.get("qid"):
                errors.append("%s case_id 与 qid 不一致" % cid)
            if not re.fullmatch(r"EVAL-TRIAGE-\d{4}", str(c.get("qid"))):
                errors.append("%s qid 格式非法：%r" % (cid, c.get("qid")))
            n = len(c.get("input") or "")
            if not 80 <= n <= 200:
                errors.append("%s input 长度 %d，不在 80~200" % (cid, n))
            gold = c.get("gold") or {}
            if set(gold) != {"red_flags", "department", "risk_level"}:
                errors.append("%s gold 字段应为 red_flags/department/risk_level：%r" % (cid, list(gold)))
            if gold.get("risk_level") not in RISK:
                errors.append("%s risk_level 非法：%r" % (cid, gold.get("risk_level")))
            if not isinstance(gold.get("red_flags"), list):
                errors.append("%s red_flags 应为数组" % cid)
            for flag in gold.get("red_flags") or []:
                if flag in symptoms:
                    continue
                if not any(x.get("raw") == flag and x.get("canonical") is None for x in rft):
                    errors.append("%s red_flag 未映射且未登记待映射：%r" % (cid, flag))
            if not isinstance(gold.get("department"), str) or not gold.get("department"):
                errors.append("%s department 为空" % cid)
            risk_count[gold.get("risk_level")] = risk_count.get(gold.get("risk_level"), 0) + 1
        else:
            mock_n += 1
            for f in MOCK_FIELDS:
                if f not in c:
                    errors.append("%s 缺少 mock 字段 %s" % (cid, f))
            if not re.fullmatch(r"CASE-\d{4}", str(cid)):
                errors.append("%s case_id 格式非法" % cid)
            if c.get("scenario") not in SCENARIO:
                errors.append("%s scenario 非法：%r" % (cid, c.get("scenario")))
            if not isinstance(c.get("narrative"), str) or len(c["narrative"]) < 20:
                errors.append("%s narrative 缺失或过短" % cid)
            st = c.get("structured") or {}
            if list(st.keys()) != STRUCTURED_KEYS:
                errors.append("%s structured 键不符：%r" % (cid, list(st.keys())))
            for k, v in st.items():
                if not isinstance(v, str) or not v.strip():
                    errors.append("%s structured.%s 为空" % (cid, k))
            lab = c.get("labels") or {}
            if set(lab) != {"expected_triage", "qc_issues"}:
                errors.append("%s labels 字段不符：%r" % (cid, list(lab)))
            et = lab.get("expected_triage") or {}
            if set(et) != {"red_flags", "department", "risk_level"}:
                errors.append("%s labels.expected_triage 字段不符" % cid)
            if et.get("risk_level") not in RISK:
                errors.append("%s labels.risk_level 非法：%r" % (cid, et.get("risk_level")))
            if not isinstance(lab.get("qc_issues"), list):
                errors.append("%s labels.qc_issues 应为数组" % cid)
            for it in lab.get("qc_issues") or []:
                if not isinstance(it, dict) or set(it) != {"field", "type", "severity"}:
                    errors.append("%s qc_issues 元素结构不符：%r" % (cid, it))
                    continue
                if not str(it["field"]).strip():
                    errors.append("%s qc_issues.field 为空" % cid)
                if it["type"] not in QC_TYPE:
                    errors.append("%s qc_issues.type 非法：%r" % (cid, it["type"]))
                if it["severity"] not in SEVERITY:
                    errors.append("%s qc_issues.severity 非法：%r" % (cid, it["severity"]))
            scen_count[c.get("scenario")] = scen_count.get(c.get("scenario"), 0) + 1

    print("病例总数 %d（triage %d / mock %d）" % (len(cases), triage_n, mock_n))
    print("triage 风险分布：%s" % dict(sorted(risk_count.items())))
    print("mock 场景分布：%s" % dict(sorted(scen_count.items())))
    print("解析：disease %d 条 / recommendation %d 条 / 药名 %d 个"
          % (len(diseases), len(rec_ids), len(drugs)))

    if errors:
        print("\n校验未通过，共 %d 项：" % len(errors))
        for e in errors[:40]:
            print(" - " + e)
        if len(errors) > 40:
            print(" ... 其余 %d 项省略" % (len(errors) - 40))
        return 1
    print("\nPASS 全部校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
