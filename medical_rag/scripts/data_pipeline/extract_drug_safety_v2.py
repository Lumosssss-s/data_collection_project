"""P6：用药安全字段重抽 v2 —— warnings / boxed_warning / dosage_adjustment（零 token，纯规则）。

主生产线 = 本地 SPL XML（data/raw/drug_labels/*.xml）。openFDA 不用于生产（其 warnings_and_cautions
为扁平长文本，丢失 8.6/8.7 子节结构），仅可作事后字段核验旁证。

口径（定稿）：
  warnings            : code ∈ {43685-7(新), 34071-1(旧)} 的最外层节，只取**直接子节**（5.x 顶层编号节），
                        禁止父节与叶子节重复成条；无子节时整节为一条。
  boxed_warning       : code = 34066-1，独立字段，不混入 warnings。
  dosage_adjustment   : {renal, hepatic, toxicity_modification} 三个子字段，
                        限定 D&A(34068-7)/USP(43684-0)/PRECAUTIONS(42232-9) 树下，排除 W&P 树；
                        renal/hepatic 按 code(88828-9/88829-7) 或 title 关键词（万金油 42229-5 必须 title 命中）；
                        toxicity_modification 按 title 含 dosage/dose modification/adjustment；
                        每个子字段识别不到时 located=false + reason，不留空。
  溯源                : 每条带 source_section_code / source_title / source_xml / match_by_title。
                        match_by_title=false 表示仅靠精确 code 命中（88828-9/88829-7 等），
                        match_by_title=true 表示 code 为万金油（42229-5 等）靠 title 关键词判定。

用法：
  python extract_drug_safety_v2.py --sample   # 5 份抽样 + 逐字校验，不写任何文件
  python extract_drug_safety_v2.py --full     # 备份 clean/drug_labels 后写回新字段 + 落 intermediate 产出
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "drug_labels")
CLEAN_DIR = os.path.join(BASE_DIR, "data", "clean", "drug_labels")
OUT_DIR = os.path.join(BASE_DIR, "data", "intermediate", "drug_safety_v2")

WARN_CODES = {"43685-7", "34071-1"}
BOXED_CODE = "34066-1"
SCOPE_TREES = {"34068-7", "43684-0", "42232-9"}   # D&A / USP / PRECAUTIONS
RENAL_CODE, HEPATIC_CODE = "88828-9", "88829-7"

RENAL_T = re.compile(r"\brenal\b|\bkidney\b", re.I)
HEPATIC_T = re.compile(r"\bhepatic\b|\bliver\b", re.I)
MODIF_T = re.compile(r"(dosage|dose)\s+(modification|adjustment)s?|modifications?\s+for\s+adverse", re.I)
EXCLUDE_T = re.compile(r"fertility|carcinogenesis", re.I)

MIN_LEN = 15
MAX_CHARS = 20000  # 单条截断上限（防御性，正常远低于此）

SAMPLE_FILES = [  # (xml, 说明)；TAMOXIFEN/TRAMETINIB 不在库，第 5 份用旧格式 ETOPOSIDE
    "DRUG-LUNG-FDA-001.xml",      # OSIMERTINIB 新格式 TKI
    "DRUG-LUNG-FDA-008.xml",      # CARBOPLATIN 旧格式（not_located 路径）
    "DRUG-LUNG-FDA-007.xml",      # ATEZOLIZUMAB 新格式单抗（嵌套修复验证）
    "DRUG-COLORECTAL-FDA-001.xml",# CAPECITABINE 新格式（多 renal 节去重）
    "DRUG-LUNG-FDA-013.xml",      # ETOPOSIDE 旧格式（PRECAUTIONS 树下 renal）
]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _is_boilerplate(text: str) -> bool:
    stripped = re.sub(r"\[[^\]]*\]", "", text).strip(" .;:()")
    return len(stripped) < MIN_LEN


class SplDoc:
    def __init__(self, xml_path: str):
        self.xml_name = os.path.basename(xml_path)
        self.root = ET.parse(xml_path).getroot()
        self.parent = {id(ch): p for p in self.root.iter() for ch in p}
        self.sections = []  # (elem, code, title, ancestor_codes)
        for sec in self.root.iter():
            if _local(sec.tag) != "section":
                continue
            code = title = None
            for ch in sec:
                t = _local(ch.tag)
                if t == "code" and code is None:
                    code = ch.get("code")
                elif t == "title" and title is None:
                    title = _norm("".join(ch.itertext()))
            anc, p = [], self.parent.get(id(sec))
            while p is not None:
                if _local(p.tag) == "section":
                    c = next((ch.get("code") for ch in p if _local(ch.tag) == "code"), None)
                    anc.append(c)
                p = self.parent.get(id(p))
            self.sections.append((sec, code, title, anc))

    def direct_child_sections(self, sec):
        """sec 的直接 section 后代（中间不再隔其他 section；穿过 component 包装层）。"""
        out = []
        for desc in sec.iter():
            if desc is sec or _local(desc.tag) != "section":
                continue
            p, is_direct = self.parent.get(id(desc)), True
            while p is not None and p is not sec:
                if _local(p.tag) == "section":
                    is_direct = False
                    break
                p = self.parent.get(id(p))
            if is_direct:
                out.append(desc)
        return out

    def paragraphs_of(self, sec):
        """该节（含后代）全部 paragraph/tr 文本，归一空白、剔样板、去重保序。"""
        seen, out = set(), []
        for node in sec.iter():
            if _local(node.tag) not in ("paragraph", "tr"):
                continue
            t = _norm("".join(node.itertext()))
            if not t or _is_boilerplate(t):
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
        return out

    def own_paragraphs(self, sec, children):
        """sec 自身段落（排除所有后代 section 内的段落）。"""
        excluded = set()
        for ch in self.direct_child_sections(sec):
            for d in ch.iter():
                excluded.add(id(d))
        seen, out = set(), []
        for node in sec.iter():
            if id(node) in excluded or _local(node.tag) not in ("paragraph", "tr"):
                continue
            t = _norm("".join(node.itertext()))
            if not t or _is_boilerplate(t):
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
        return out

    def sec_meta(self, sec):
        code = title = None
        for ch in sec:
            t = _local(ch.tag)
            if t == "code" and code is None:
                code = ch.get("code")
            elif t == "title" and title is None:
                title = _norm("".join(ch.itertext()))
        return code, title


def _entry(code, title, text, xml_name, match_by_title):
    return {
        "code": code,
        "title": title,
        "text": text[:MAX_CHARS],
        "char_len": len(text[:MAX_CHARS]),
        "source_section_code": code,
        "source_title": title,
        "source_xml": xml_name,
        "match_by_title": match_by_title,
    }


def extract(doc: SplDoc) -> dict:
    xml_name = doc.xml_name
    boxed, warnings = [], []

    for sec, code, title, anc in doc.sections:
        if code == BOXED_CODE and BOXED_CODE not in anc:
            paras = doc.paragraphs_of(sec)
            if paras:
                text = f"{title}: {' '.join(paras)}" if title else " ".join(paras)
                boxed.append(_entry(code, title, text, xml_name, False))

        if code in WARN_CODES and not any(a in WARN_CODES for a in anc):
            children = doc.direct_child_sections(sec)
            if children:
                # 父节自有段落（不属于任何子节）先成条，防止旧格式正文丢失
                own = doc.own_paragraphs(sec, children)
                if own:
                    text = f"{title}: {' '.join(own)}" if title else " ".join(own)
                    warnings.append(_entry(code, title, text, xml_name, False))
                for ch in children:
                    c_code, c_title = doc.sec_meta(ch)
                    paras = doc.paragraphs_of(ch)
                    if not paras:
                        continue
                    text = f"{c_title}: {' '.join(paras)}" if c_title else " ".join(paras)
                    warnings.append(_entry(c_code, c_title, text, xml_name, False))
            else:
                paras = doc.paragraphs_of(sec)
                if paras:
                    text = f"{title}: {' '.join(paras)}" if title else " ".join(paras)
                    warnings.append(_entry(code, title, text, xml_name, False))

    # ---- dosage_adjustment ----
    renal, hepatic, toxmod = [], [], []
    for sec, code, title, anc in doc.sections:
        t = title or ""
        if not t or EXCLUDE_T.search(t):
            continue
        in_scope = code in SCOPE_TREES or any(a in SCOPE_TREES for a in anc)
        in_warn = code in WARN_CODES or any(a in WARN_CODES for a in anc)
        if not in_scope or in_warn:
            continue
        paras = doc.paragraphs_of(sec)
        if not paras:
            continue
        text = f"{t}: {' '.join(paras)}"
        if code == RENAL_CODE:
            renal.append(_entry(code, title, text, xml_name, False))       # 精确 code 命中
        elif code == HEPATIC_CODE:
            hepatic.append(_entry(code, title, text, xml_name, False))
        elif RENAL_T.search(t) and "impair" in t.lower():
            renal.append(_entry(code, title, text, xml_name, True))        # 万金油 code + title 判定
        elif HEPATIC_T.search(t) and "impair" in t.lower():
            hepatic.append(_entry(code, title, text, xml_name, True))
        elif MODIF_T.search(t):
            toxmod.append(_entry(code, title, text, xml_name, True))

    def sub(items, reason):
        return {"located": bool(items), "reason": None if items else reason, "items": items}

    dosage_adjustment = {
        "renal": sub(renal, "D&A/USP/PRECAUTIONS 树下无标题含 renal impairment 的子节（调整信息可能在正文无标题段落）"),
        "hepatic": sub(hepatic, "D&A/USP/PRECAUTIONS 树下无标题含 hepatic impairment 的子节（调整信息可能在正文无标题段落）"),
        "toxicity_modification": sub(toxmod, "D&A 树下无标题含 dosage/dose modification 的子节"),
    }
    return {
        "warnings": warnings or None,
        "boxed_warning": boxed or None,
        "dosage_adjustment": dosage_adjustment,
    }


# ---------------- 逐字校验（抽样闸门） ----------------
def verify_entry(doc: SplDoc, entry: dict) -> str:
    """按 (code,title) 重新定位原文节，重建期望文本比对。返回 一致/归一空白后一致/不一致。"""
    candidates = []
    for sec, code, title, anc in doc.sections:
        if code == entry["source_section_code"] and (title or "") == (entry["source_title"] or ""):
            candidates.append(sec)
    if not candidates:
        # 顶层节 text 带 title 前缀；按 title 再松匹配一次
        for sec, code, title, anc in doc.sections:
            if (title or "") == (entry["source_title"] or ""):
                candidates.append(sec)
    for sec in candidates:
        _, title = doc.sec_meta(sec)
        variants = []
        paras = doc.paragraphs_of(sec)
        if paras:
            variants.append(f"{title}: {' '.join(paras)}" if title else " ".join(paras))
        children = doc.direct_child_sections(sec)
        if children:
            own = doc.own_paragraphs(sec, children)
            if own:
                variants.append(f"{title}: {' '.join(own)}" if title else " ".join(own))
        for expected in variants:
            if expected == entry["text"]:
                return "一致"
            if _norm(expected) == _norm(entry["text"]):
                return "归一空白后一致"
    return "不一致"


def run_sample():
    print("=" * 112)
    print("抽样校验（5 份）：逐字比对，出现 1 条非空白不一致即中止")
    print("=" * 112)
    bad = 0
    for fname in SAMPLE_FILES:
        path = os.path.join(RAW_DIR, fname)
        if not os.path.exists(path):
            print(f"\n### {fname}  XML 不存在，跳过"); continue
        doc = SplDoc(path)
        res = extract(doc)
        w = res["warnings"] or []
        b = res["boxed_warning"] or []
        da = res["dosage_adjustment"]
        print(f"\n### {fname}")
        print(f"  boxed_warning: {len(b)} 条 | warnings: {len(w)} 条 | "
              f"renal={len(da['renal']['items'])} hepatic={len(da['hepatic']['items'])} toxmod={len(da['toxicity_modification']['items'])}")
        for group, entries in (("boxed", b), ("warnings", w),
                               ("renal", da["renal"]["items"]), ("hepatic", da["hepatic"]["items"]),
                               ("toxmod", da["toxicity_modification"]["items"])):
            for i, e in enumerate(entries):
                verdict = verify_entry(doc, e)
                if verdict == "不一致":
                    bad += 1
                print(f"    [{group}#{i}] code={e['code']} mbt={e['match_by_title']} "
                      f"len={e['char_len']:>6} 比对={verdict}  title={(e['title'] or '')[:60]}")
        for k in ("renal", "hepatic", "toxicity_modification"):
            if not da[k]["located"]:
                print(f"    [not_located] {k}: {da[k]['reason']}")
    print("\n" + ("!! 存在非空白不一致，禁止全量" if bad else ">> 5 份全部通过（一致或仅空白差异）"))
    return bad == 0


def run_full():
    today = datetime.date.today().strftime("%Y%m%d")
    backup = os.path.join(os.path.dirname(CLEAN_DIR), f"drug_labels_backup_{today}")
    if not os.path.exists(backup):
        shutil.copytree(CLEAN_DIR, backup)
    print(f"备份目录: {backup}")
    os.makedirs(OUT_DIR, exist_ok=True)

    stats, outputs = [], {}
    for fname in sorted(os.listdir(CLEAN_DIR)):
        if not fname.endswith(".json"):
            continue
        clean_path = os.path.join(CLEAN_DIR, fname)
        records = json.load(open(clean_path, encoding="utf-8"))
        if not isinstance(records, list) or not records:
            continue
        xml_path = os.path.join(RAW_DIR, fname.replace(".json", ".xml"))
        if os.path.exists(xml_path):
            doc = SplDoc(xml_path)
            res = extract(doc)
        else:
            reason = "source XML missing（无原始 XML，无法规则抽取）"
            res = {"warnings": None, "boxed_warning": None,
                   "dosage_adjustment": {k: {"located": False, "reason": reason, "items": []}
                                         for k in ("renal", "hepatic", "toxicity_modification")}}
        for rec in records:
            rec["warnings"] = res["warnings"]
            rec["boxed_warning"] = res["boxed_warning"]
            rec["dosage_adjustment"] = res["dosage_adjustment"]
            rec["safety_extraction_meta"] = {
                "extractor": "extract_drug_safety_v2.py",
                "extracted_at": str(datetime.date.today()),
                "source_xml": fname.replace(".json", ".xml"),
                "xml_present": os.path.exists(xml_path),
            }
        with open(clean_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
        outputs[fname] = res

        da = res["dosage_adjustment"]
        stats.append({
            "file": fname,
            "warnings_n": len(res["warnings"] or []),
            "boxed": bool(res["boxed_warning"]),
            "renal_n": len(da["renal"]["items"]),
            "hepatic_n": len(da["hepatic"]["items"]),
            "toxmod_n": len(da["toxicity_modification"]["items"]),
            "not_located": [k for k in ("renal", "hepatic", "toxicity_modification") if not da[k]["located"]],
        })

    json.dump(outputs, open(os.path.join(OUT_DIR, "extraction_output.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(stats, open(os.path.join(OUT_DIR, "stats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    n = len(stats)
    print(f"\n{'file':<32} {'warn':>5} {'boxed':>6} {'renal':>6} {'hep':>5} {'toxmod':>7}  not_located")
    for s in stats:
        print(f"{s['file']:<32} {s['warnings_n']:>5} {str(s['boxed']):>6} {s['renal_n']:>6} "
              f"{s['hepatic_n']:>5} {s['toxmod_n']:>7}  {','.join(s['not_located']) or '-'}")
    print(f"\n【全量统计】文件数={n}")
    print(f"  warnings>=1 条        : {sum(1 for s in stats if s['warnings_n'] > 0)}/{n}")
    print(f"  boxed_warning 有      : {sum(1 for s in stats if s['boxed'])}/{n}")
    print(f"  renal located         : {sum(1 for s in stats if s['renal_n'] > 0)}/{n}")
    print(f"  hepatic located       : {sum(1 for s in stats if s['hepatic_n'] > 0)}/{n}")
    print(f"  toxicity_mod located  : {sum(1 for s in stats if s['toxmod_n'] > 0)}/{n}")
    print(f"\n产出: {os.path.join(OUT_DIR, 'extraction_output.json')} / stats.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    if args.sample:
        sys.exit(0 if run_sample() else 1)
    elif args.full:
        run_full()
    else:
        ap.print_help()
