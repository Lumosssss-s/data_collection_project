# -*- coding: utf-8 -*-
"""tools/18_icdo3_mapping.py

以《肿瘤形态学编码（M码）国家临床版2.0》为源，为 A5 术语字典的 disease 条目回补 icd_o3。

格式说明（重要）：
  - NHC 原码为 5 位：M + 5 位数字 + "/" + 行为码，第 5 位是本地亚型细分序号
    （如 M81400/3 = WHO 基础码 M8140/3，M80411/3 = 小细胞神经内分泌癌）。
  - 需求清单 §A3⑦ 硬性要求 `icd_o3` 格式为 `Mxxxx/x`（4 位 WHO 标准写法），
    并明确「缺 M 前缀或行为码」属错误清单。
  - 本脚本统一输出 4 位标准码，NHC 原 5 位码保留在 annotation.icd_o3_source 便于溯源。

匹配顺序：
  1) 名称精确命中 M 码表 → 直接取该码
  2) 形态学关键词规则（长词优先，如「黏液腺癌」先于「腺癌」）
  3) 部位性诊断兜底（恶性肿瘤 → M8010/3，原位 → /2，继发/转移 → /6，良性 → M8000/0）
  4) 非肿瘤性诊断（甲状腺肿/息肉/囊肿/积液/骨折等）→ 保持 null 并记录原因

用法：python tools/18_icdo3_mapping.py
前置：13_cblue_terminology.py 已生成 data/clean/terminology/terminology_cancer.json，
      17_fetch_icdo3.py 已抓取并校验码表到 fetched/codetables/nhc/（13 → 17 → 18 顺序执行）
"""
import json
import os
import re
import sys
from collections import Counter

from openpyxl import load_workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M_SRC = os.path.join(BASE, "fetched", "codetables", "nhc", "（3）肿瘤形态学编码（M码）-国家临床版2.0.xlsx")
TERM_PATH = os.path.join(BASE, "data", "clean", "terminology", "terminology_cancer.json")
AUDIT_PATH = os.path.join(BASE, "cache", "codetables", "icdo3_mapping.json")

CODE_RE = re.compile(r"^M(\d{5})/(\d)$")


def to_who(nhc_code):
    """M81400/3 -> M8140/3（丢第 5 位本地细分序号）"""
    m = CODE_RE.match(nhc_code)
    if not m:
        raise ValueError("非法 M 码: %r" % nhc_code)
    return "M%s/%s" % (m.group(1)[:4], m.group(2))


def load_m_table():
    """返回 {名称: NHC 原码}，并按 4 位码去重保留首个"""
    wb = load_workbook(M_SRC, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    by_name, by_who = {}, {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        code = str(row[0]).strip() if row[0] else ""
        name = str(row[1]).strip() if row[1] else ""
        if not code or not name or not CODE_RE.match(code):
            continue
        by_name.setdefault(name, code)
        by_who.setdefault(to_who(code), code)
    wb.close()
    return by_name, by_who


# 形态学关键词 → NHC 原码（按关键词长度倒序匹配，避免「腺癌」抢先命中「黏液腺癌」）
MORPH_RULES = [
    # 乳腺
    ("浸润性导管癌", "M85000/3"),
    ("导管内原位癌", "M85000/2"),
    ("导管原位癌", "M85000/2"),
    ("原位导管癌", "M85000/2"),
    ("导管内癌", "M85000/2"),
    ("浸润性小叶癌", "M85200/3"),
    ("小叶原位癌", "M85200/2"),
    ("原位小叶癌", "M85200/2"),
    # 肺
    ("非小细胞肺癌", "M80460/3"),
    ("非小细胞癌", "M80460/3"),
    ("小细胞肺癌", "M80410/3"),
    ("小细胞癌", "M80410/3"),
    ("大细胞癌", "M80120/3"),
    # 甲状腺
    ("甲状腺乳头状癌", "M82600/3"),
    ("乳头状腺癌", "M82600/3"),
    ("乳头状癌", "M80500/3"),
    ("滤泡性腺癌", "M83300/3"),
    ("滤泡状腺癌", "M83300/3"),
    ("滤泡癌", "M83300/3"),
    ("滤泡状癌", "M83300/3"),
    ("滤泡性腺瘤", "M83300/0"),
    ("滤泡性肿瘤", "M83300/0"),
    ("髓样癌", "M85100/3"),
    # 消化道
    ("黏液腺癌", "M84800/3"),
    ("粘液腺癌", "M84800/3"),
    ("印戒细胞癌", "M84900/3"),
    ("腺鳞癌", "M85600/3"),
    ("鳞状细胞癌", "M80700/3"),
    ("鳞癌", "M80700/3"),
    ("家族性息肉病", "M82200/0"),
    # 神经内分泌
    ("神经内分泌癌", "M82460/3"),
    ("神经内分泌肿瘤", "M82402/1"),
    ("类癌", "M82400/3"),
    # 通用形态学
    ("未分化癌", "M80200/3"),
    ("原位腺癌", "M81400/2"),
    ("腺癌", "M81400/3"),
    ("腺瘤", "M81400/0"),
    ("原位癌", "M80100/2"),
    ("恶性黑色素瘤", "M87200/3"),
    ("黑色素瘤", "M87200/3"),
    ("霍奇金淋巴瘤", "M96500/3"),
    ("淋巴瘤", "M95900/3"),
    ("平滑肌肉瘤", "M88900/3"),
    ("肉瘤", "M88000/3"),
    # 其他实体
    ("嗜铬细胞瘤", "M87000/0"),
    ("神经纤维瘤", "M95400/0"),
    ("黏膜神经瘤", "M95700/0"),
    ("神经瘤", "M95700/0"),
]
MORPH_RULES.sort(key=lambda kv: len(kv[0]), reverse=True)

# 英文缩写 → 中文形态学名（术语字典中 CMeIE 抽出的缩写条目）
ALIAS = {
    "DCIS": "导管原位癌",
    "LCIS": "小叶原位癌",
}

# 「腺癌」是弱关键词：乳腺/甲状腺/前列腺癌 是部位性诊断，不能命中「乳腺+癌=腺癌」
WEAK_KW = "腺癌"
WEAK_GUARD = ("乳腺", "甲状腺", "前列腺")

# 非肿瘤性/非形态学诊断：保持 null
NON_MORPH_KEYS = ("甲状腺肿", "囊肿", "息肉", "积液", "高钙血症", "肿瘤溶解综合征",
                  "淋巴水肿", "病理性骨折", "恶病质")


def behavior(code, name):
    """按名称调整行为码：原位→2，继发/转移→6"""
    if "原位" in name:
        return re.sub(r"/\d$", "/2", code)
    if "继发" in name or "转移" in name:
        return re.sub(r"/\d$", "/6", code)
    return code


def map_one(name, by_name):
    """返回 (icd_o3, nhc_source, basis)；无合适映射返回 (None, None, reason)"""
    name = ALIAS.get(name, name)
    nhc = by_name.get(name)
    if nhc:
        c = to_who(nhc)
        return behavior(c, name), nhc, "exact:" + name

    for kw, nhc in MORPH_RULES:
        if kw not in name:
            continue
        if kw == WEAK_KW and any(s in name for s in WEAK_GUARD):
            continue
        c = to_who(nhc)
        return behavior(c, name), nhc, "morph:" + kw

    # 部位性诊断兜底
    if "继发" in name or "转移" in name:
        return "M8010/6", "M80100/6", "site:继发/转移"
    if "原位" in name:
        return "M8010/2", "M80100/2", "site:原位"
    if "良性肿瘤" in name:
        return "M8000/0", "M80000/0", "site:良性"
    if "恶性肿瘤" in name:
        return "M8010/3", "M80100/3", "site:恶性肿瘤"
    if "癌" in name:
        return "M8010/3", "M80100/3", "site:癌 NOS"

    for kw in NON_MORPH_KEYS:
        if kw in name:
            return None, None, "skip:非形态学(%s)" % kw
    return None, None, "skip:无法判定"


def main():
    if not os.path.exists(M_SRC):
        raise SystemExit("缺少 M 码表：%s\n请先运行 python tools/17_fetch_icdo3.py" % M_SRC)
    by_name, _ = load_m_table()
    print("M 码表载入: %d 个名称" % len(by_name))

    with open(TERM_PATH, encoding="utf-8") as f:
        terms = json.load(f)

    audit, stat = [], Counter()
    for t in terms:
        if t.get("category") != "disease":
            continue
        name = t.get("canonical")
        code, nhc_src, basis = map_one(name, by_name)
        t["icd_o3"] = code
        ann = t.setdefault("annotation", {})
        if code:
            ann["icd_o3_source"] = nhc_src
            ann["icd_o3_basis"] = basis
            ann.pop("icd_o3_note", None)
            stat["mapped"] += 1
            stat[basis.split(":")[0]] += 1
        else:
            ann.pop("icd_o3_source", None)
            ann.pop("icd_o3_basis", None)
            ann["icd_o3_note"] = "不适用肿瘤形态学编码：" + basis.split(":", 1)[1]
            stat["null"] += 1
        audit.append({"canonical": name, "icd_o3": code,
                      "nhc_source": nhc_src, "basis": basis,
                      "mapping_status": t.get("mapping_status")})

    with open(TERM_PATH, "w", encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    total = stat["mapped"] + stat["null"]
    print("disease 条目: %d，已映射 %d（%.1f%%），未映射 %d" % (
        total, stat["mapped"], 100.0 * stat["mapped"] / total, stat["null"]))
    print("映射依据分布:", dict(stat))
    print("审计明细:", AUDIT_PATH)

    # 未映射清单，便于人工判断是否需要补规则
    print("\n未映射条目：")
    for a in audit:
        if not a["icd_o3"]:
            print("  [%s] %s — %s" % (a["mapping_status"], a["canonical"], a["basis"]))


if __name__ == "__main__":
    sys.exit(main())
