# -*- coding: utf-8 -*-
"""tools/19_fetch_openfda_labels.py

从 openFDA drug/label API 抓取说明书四段英文原文（适应证/用法用量/禁忌/不良反应），
作为 A4 中文说明书补齐前的 interim 数据；中文内容由人工填写 raw/nmpa_labels/labels_zh.json 后合并，
其中适应证/用法用量可先由 20_guideline_drug_extract.py 从官方指导原则预填，模板里可留空沿用。

背景：NMPA 数据查询库（datasearch.nmpa.gov.cn）对脚本与自动化浏览器均返回 412 反爬，
人工查询页（样例见 raw/nmpa_registry/）只有注册信息——批准文号/产品名称/商品名/剂型/规格/
持有人/生产厂商/药品本位码，不含适应证/用法用量/禁忌/不良反应四段正文；故四段正文取 openFDA
公开标签（公有领域）作英文 interim，字段名不带 A4 正式字段前缀（label_en_interim），不冒充 NMPA 中文口径。

产物：
  fetched/openfda_labels/labels.json       抓取结果（未经加工）
  cache/drug_labels/openfda_match.json     匹配审计（候选打分、命中段落、未命中原因）
  cache/drug_labels/zh_override_audit.json 中文覆盖校验审计
  data/clean/drug_labels/drug_catalog.json 回写 label_en_interim / label / missing_fields
  raw/nmpa_labels/labels_zh.template.json  人工中文覆盖模板（--template 生成，不覆盖已有文件）

用法：
  python tools/19_fetch_openfda_labels.py             # 抓取缺失项 + 合并 + 应用中文覆盖
  python tools/19_fetch_openfda_labels.py --force     # 强制重抓全部
  python tools/19_fetch_openfda_labels.py --offline   # 不联网，仅用已抓结果合并
  python tools/19_fetch_openfda_labels.py --template  # 生成中文覆盖模板
"""
import argparse
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(BASE, "data", "clean", "drug_labels", "drug_catalog.json")
FETCH_DIR = os.path.join(BASE, "fetched", "openfda_labels")
FETCH_JSON = os.path.join(FETCH_DIR, "labels.json")
AUDIT = os.path.join(BASE, "cache", "drug_labels", "openfda_match.json")
OVERRIDE_AUDIT = os.path.join(BASE, "cache", "drug_labels", "zh_override_audit.json")
OVERRIDE_DIR = os.path.join(BASE, "raw", "nmpa_labels")
OVERRIDE = os.path.join(OVERRIDE_DIR, "labels_zh.json")
TEMPLATE = os.path.join(OVERRIDE_DIR, "labels_zh.template.json")

API = "https://api.fda.gov/drug/label.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
SECTIONS = [
    ("indications", "indications_and_usage"),
    ("dosage_and_administration", "dosage_and_administration"),
    ("contraindications", "contraindications"),
    ("adverse_reactions", "adverse_reactions"),
]
# 少数 INN 在 openFDA 中的写法不同（生物类似药/酸根/抗体偶联药物）
ALIAS = {
    "TRASTUZUMAB EMTANSINE": "ADO-TRASTUZUMAB EMTANSINE",
    "ZOLEDRONIC": "ZOLEDRONIC ACID",
}
A4_FIELDS = ["indications", "dosage", "contraindications", "adverse_reactions"]
APPROVAL_RE = re.compile(r"^国药准字[A-Z]?\d{8,}")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().upper()


def api_search(query, limit=50):
    """openFDA 检索；404 视为 0 条，429/5xx 退避重试。"""
    url = API + "?" + urllib.parse.urlencode({"search": query, "limit": limit})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return json.load(r), url
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"results": []}, url
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    return {"results": []}, url


def candidates(name):
    """按 精确短语 → 整词 → 成分名 → 全文 逐级放宽，按 set_id 去重。"""
    queries = [
        'openfda.generic_name:"%s"' % name,
        "openfda.generic_name:%s" % name,
        "openfda.substance_name:%s" % name,
        name,
    ]
    found, urls = {}, []
    for q in queries:
        data, url = api_search(q)
        urls.append(url)
        got = data.get("results") or []
        for it in got:
            sid = it.get("set_id") or it.get("id")
            if sid and sid not in found:
                found[sid] = it
        if len(found) >= 5 and q.startswith("openfda.generic_name"):
            break  # 已足够挑出最优候选，减少请求
        time.sleep(0.35)
    return list(found.values()), urls


def score(item, name):
    """候选打分：通用名吻合度 > 段落完整度 > 非生物类似药 > 新版本。"""
    o = item.get("openfda") or {}
    gs = [norm(x) for x in (o.get("generic_name") or [])]
    sn = [norm(x) for x in (o.get("substance_name") or [])]
    s = 0
    if any(g == name for g in gs):
        s += 100
    elif any(g.startswith(name + " ") for g in gs):
        s += 75
    elif any(name in g for g in gs):
        s += 50
    elif any(name in x for x in sn):
        s += 40
    if any(re.search(r"-[A-Z]{3,4}$", g) for g in gs):
        s -= 30  # 生物类似药后缀（如 PEGFILGRASTIM-CBQV）
    s += sum(1 for _k, tok in SECTIONS if item.get(tok)) * 8
    return s


def clean_text(value):
    if isinstance(value, list):
        value = "\n".join(str(x) for x in value)
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def pick(items, name):
    ranked = sorted(items, key=lambda it: (score(it, name), str(it.get("effective_time") or "")))
    ranked.reverse()
    for it in ranked:
        if score(it, name) >= 40 and sum(1 for _k, tok in SECTIONS if it.get(tok)) >= 2:
            return it
    return None


def fetch_one(rec, force):
    name = norm(ALIAS.get(rec["generic_name_en"].strip().upper(),
                          rec["generic_name_en"].strip().upper()))
    items, urls = candidates(name)
    best = pick(items, name)
    if not best:
        return {
            "drug_id": rec["drug_id"], "canonical_zh": rec["canonical_zh"],
            "query": name, "status": "miss", "candidates": len(items),
            "reason": "无候选或候选段落不全（候选 %d 条）" % len(items),
        }

    o = best.get("openfda") or {}
    sections = {}
    for key, token in SECTIONS:
        if best.get(token):
            sections[key] = clean_text(best[token])
    return {
        "drug_id": rec["drug_id"],
        "canonical_zh": rec["canonical_zh"],
        "query": name,
        "status": "ok",
        "candidates": len(items),
        "score": score(best, name),
        "set_id": best.get("set_id"),
        "effective_time": best.get("effective_time"),
        "generic_name": (o.get("generic_name") or [None])[0],
        "brand_name": (o.get("brand_name") or [None])[0],
        "spl_id": best.get("id"),
        "source_url": urls[0],
        "sections": sections,
    }


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def refresh_missing(rec):
    miss = []
    if not rec.get("atc"):
        miss.append("atc_code")
    for f in A4_FIELDS:
        if not rec.get(f):
            miss.append(f)
    if not rec.get("approval_no"):
        miss.append("approval_number_cn")
    if not rec.get("label"):
        miss.append("chinese_label")
    rec["missing_fields"] = miss


def apply_interim(rec, item):
    if item and item.get("status") == "ok" and item.get("sections"):
        rec["label_en_interim"] = {
            "lang": "en",
            "status": "interim_pending_zh",
            "source": "openFDA drug/label（美国 FDA 公开标签，公有领域，非 NMPA 口径）",
            "set_id": item.get("set_id"),
            "effective_time": item.get("effective_time"),
            "generic_name": item.get("generic_name"),
            "brand_name": item.get("brand_name"),
            "sections": item["sections"],
        }
    elif "label_en_interim" in rec:
        rec.pop("label_en_interim")


def validate_override(ov, rec=None):
    """校验人工中文覆盖；返回 (errors, cleaned)。rec 已有中文项时允许留空。"""
    errs = []
    if not isinstance(ov, dict):
        return ["条目不是对象"], None
    approval = str(ov.get("approval_no") or "").strip()
    if not APPROVAL_RE.match(approval):
        errs.append("approval_no 不符合「国药准字…」格式：%r" % approval)
    inds = ov.get("indications")
    if not (isinstance(inds, list) and inds) and not (rec and rec.get("indications")):
        errs.append("indications 须为非空数组（或沿用 20 号脚本已抽取的内容）")
    dosage = ov.get("dosage")
    std = str((dosage or {}).get("standard") or "").strip()
    if not std and not (rec and (rec.get("dosage") or {}).get("standard")):
        errs.append("dosage 须为 {standard, adjustment} 且 standard 非空")
    if not (isinstance(ov.get("contraindications"), list) and ov["contraindications"]):
        errs.append("contraindications 须为非空数组")
    ar = ov.get("adverse_reactions")
    if not (isinstance(ar, list) and ar):
        errs.append("adverse_reactions 须为非空数组")
    else:
        for i, x in enumerate(ar):
            if not (isinstance(x, dict) and str(x.get("term") or "").strip()
                    and str(x.get("frequency") or "").strip()):
                errs.append("adverse_reactions[%d] 须含 term/frequency" % i)
                break
    if not str(ov.get("source_name") or "").strip():
        errs.append("source_name（说明书名称）必填")
    return errs, ov


def apply_override(rec, ov):
    if ov.get("brand_names"):
        rec["brand_names"] = ov["brand_names"]
    if str(ov.get("approval_no") or "").strip():
        rec["approval_no"] = str(ov["approval_no"]).strip()
    if ov.get("indications"):
        rec["indications"] = ov["indications"]
    dosage = ov.get("dosage") or {}
    if str(dosage.get("standard") or "").strip() or str(dosage.get("adjustment") or "").strip():
        old = rec.get("dosage") or {}
        rec["dosage"] = {
            "standard": str(dosage.get("standard") or "").strip() or old.get("standard"),
            "adjustment": str(dosage.get("adjustment") or "").strip() or old.get("adjustment"),
        }
    if ov.get("contraindications"):
        rec["contraindications"] = ov["contraindications"]
    if ov.get("adverse_reactions"):
        rec["adverse_reactions"] = ov["adverse_reactions"]
    if ov.get("interactions"):
        rec["interactions"] = ov["interactions"]
    rec["label"] = {
        "lang": "zh",
        "status": "zh_from_nmpa",
        "source_name": str(ov["source_name"]).strip(),
        "source_url": str(ov.get("source_url") or "").strip() or None,
        "updated_at": str(ov.get("approved_date") or "").strip() or None,
    }


def build_template(catalog):
    drugs = {}
    for rec in catalog:
        drugs[rec["drug_id"]] = {
            "canonical_zh": rec["canonical_zh"],
            "approval_no": "",
            "brand_names": [],
            "indications": [],
            "dosage": {"standard": "", "adjustment": ""},
            "contraindications": [],
            "adverse_reactions": [{"term": "", "frequency": "", "ctcae_hint": ""}],
            "interactions": [],
            "source_name": "",
            "source_url": "",
            "approved_date": "",
        }
    doc = {
        "_说明": "按 drug_id 填写 NMPA 中文说明书要点；adverse_reactions 每项须含 term/frequency。"
                 "填完另存为 labels_zh.json（同目录），再运行 python tools/19_fetch_openfda_labels.py 合并。",
        "_来源要求": "NMPA 公开说明书（国家药品监督管理局数据查询 / 企业官网 PDF），source_name 写说明书名称",
        "drugs": drugs,
    }
    if os.path.exists(TEMPLATE):
        print("[SKIP] 模板已存在：%s" % TEMPLATE)
        return
    save_json(TEMPLATE, doc)
    print("已生成模板：%s（填写后另存为 labels_zh.json）" % TEMPLATE)


def main():
    ap = argparse.ArgumentParser(description="openFDA 说明书四段抓取 + NMPA 中文覆盖合并")
    ap.add_argument("--force", action="store_true", help="强制重抓全部药品")
    ap.add_argument("--offline", action="store_true", help="不联网，仅用已有 fetched 结果合并")
    ap.add_argument("--template", action="store_true", help="生成 NMPA 中文覆盖模板后退出")
    args = ap.parse_args()

    with open(CAT, encoding="utf-8") as f:
        catalog = json.load(f)

    if args.template:
        build_template(catalog)
        return 0

    fetched = load_json(FETCH_JSON, {"_meta": {}, "drugs": {}})
    fetched.setdefault("drugs", {})

    audit = []
    for i, rec in enumerate(catalog, 1):
        key = rec["drug_id"]
        if args.offline or (key in fetched["drugs"] and not args.force):
            item = fetched["drugs"].get(key)
            if item is None:
                audit.append({"drug_id": key, "canonical_zh": rec["canonical_zh"],
                              "status": "missing_offline"})
                continue
        else:
            item = fetch_one(rec, args.force)
            fetched["drugs"][key] = item
            save_json(FETCH_JSON, fetched)  # 逐条落盘，断点可续跑
            print("[%02d/%d] %s %s → %s" % (i, len(catalog), key, rec["canonical_zh"], item["status"]))

        apply_interim(rec, item)
        audit.append({k: item.get(k) for k in
                      ("drug_id", "canonical_zh", "query", "status", "candidates", "score",
                       "set_id", "effective_time", "generic_name", "brand_name")})
        if item.get("status") == "ok":
            audit[-1]["sections"] = sorted(item["sections"].keys())
        else:
            audit[-1]["reason"] = item.get("reason")

    fetched["_meta"] = {
        "api": API,
        "source": "openFDA drug/label（美国 FDA 公开标签，公有领域）",
        "license": "Public domain（美国政府作品）",
        "note": "英文 interim；A4 中文口径须以 NMPA 说明书人工覆盖为准",
        "drug_count": len(fetched["drugs"]),
        "ok_count": sum(1 for v in fetched["drugs"].values() if v.get("status") == "ok"),
    }
    save_json(FETCH_JSON, fetched)
    save_json(AUDIT, audit)

    # 中文覆盖
    override = load_json(OVERRIDE, {}).get("drugs", {})
    ov_audit, ov_ok = [], 0
    by_id = {r["drug_id"]: r for r in catalog}
    for key, ov in override.items():
        rec = by_id.get(key)
        errs, ok_ov = validate_override(ov, rec)
        if rec is None:
            errs = errs + ["drug_id 不在 drug_catalog 中"]
        if errs:
            ov_audit.append({"drug_id": key, "status": "invalid", "errors": errs})
            continue
        apply_override(rec, ok_ov)
        ov_audit.append({"drug_id": key, "status": "merged",
                         "source_name": rec["label"]["source_name"]})
        ov_ok += 1
    if override:
        save_json(OVERRIDE_AUDIT, ov_audit)

    for rec in catalog:
        refresh_missing(rec)

    save_json(CAT, catalog)

    ok = sum(1 for v in fetched["drugs"].values() if v.get("status") == "ok")
    miss = [v["canonical_zh"] for v in fetched["drugs"].values() if v.get("status") != "ok"]
    print("\n=== openFDA interim：命中 %d / %d，未命中 %s ===" % (
        ok, len(catalog), "、".join(miss) if miss else "无"))
    if override:
        print("中文覆盖：合并 %d 条，失败 %d 条（详见 %s）" % (
            ov_ok, len(ov_audit) - ov_ok, OVERRIDE_AUDIT))
    else:
        print("中文覆盖：未提供 %s（可用 --template 生成模板）" % OVERRIDE)
    still = sum(1 for r in catalog if r["missing_fields"])
    print("仍缺中文必填字段的药品：%d / %d（missing_fields 已更新）" % (still, len(catalog)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
