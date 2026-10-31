"""方案 A：按 FDA NDC 药品目录从 DailyMed 拉取说明书，补齐 A4 药品记录（零 token）。

输入：
  第四批 drug_catalog.json（48 种抗肿瘤药，FDA NDC 公开数据）
  —— 该目录只有药品身份（通用名/中文名/类别/NDA 号），indications、dosage、
     contraindications、adverse_reactions、interactions 全缺。

做法：
  1. 只取 cancer_type 含 lung / colorectal 的药，按通用名去重；
  2. 跳过库内已有的 5 种（奥希替尼 / 帕博利珠单抗 / 贝伐珠单抗 / 培美曲塞 / 克唑替尼）；
  3. 用 DailyMed SPL 接口按通用名检索，取首个标题匹配的说明书 XML；
  4. 按 LOINC 章节码抽取：适应证 34067-9 / 用法用量 34068-7 / 禁忌 34070-3 /
     不良反应 34084-4 / 相互作用 34073-7；
  5. 原始 XML 落地 data/raw/drug_labels/，清洗记录写 data/clean/drug_labels/（review_status=draft）。

用法：
  python scripts/data_pipeline/fetch_dailymed_labels.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOG = r"e:/兴智杯/第四批/data/clean/drug_labels/drug_catalog.json"
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "drug_labels")
CLEAN_DIR = os.path.join(BASE_DIR, "data", "clean", "drug_labels")
UA = {"User-Agent": "medical-rag-research/1.0 (academic use)"}
SPL_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name={}"
SPL_XML = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{}.xml"

TARGET_CANCERS = ("lung", "colorectal")
# 已入库的 5 种（按通用名跳过，避免重复记录）
EXISTING = {"OSIMERTINIB", "PEMBROLIZUMAB", "BEVACIZUMAB", "PEMETREXED", "CRIZOTINIB"}

# ATC 编码（解剖治疗学分类，人工核对；schema 要求必填且校验 pattern）
ATC = {
    "ALECTINIB": "L01ED03", "ATEZOLIZUMAB": "L01FF05", "CARBOPLATIN": "L01XA02",
    "CISPLATIN": "L01XA01", "DOCETAXEL": "L01CD02", "DURVALUMAB": "L01FF03",
    "ERLOTINIB": "L01EB02", "ETOPOSIDE": "L01CB01", "GEFITINIB": "L01EB01",
    "GEMCITABINE": "L01BC05", "NIVOLUMAB": "L01FF01", "PACLITAXEL": "L01CD01",
    "RAMUCIRUMAB": "L01FG02",
    "CETUXIMAB": "L01FE01", "FLUOROURACIL": "L01BC02", "IRINOTECAN": "L01XX19",
    "OXALIPLATIN": "L01XA03", "PANITUMUMAB": "L01FE02", "REGORAFENIB": "L01EX05",
    "CAPECITABINE": "L01BC06",
}

# 章节 LOINC 码
SEC = {"indications": "34067-9", "dosage": "34068-7", "contraindications": "34070-3",
       "adverse": "34084-4", "interactions": "34073-7"}

MAX_IND = 10
MAX_ADV = 20
MIN_PARA = 20


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node) -> str:
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _paragraphs(sec, min_len: int = MIN_PARA) -> List[str]:
    out: List[str] = []
    for node in sec.iter():
        if _local(node.tag) in ("paragraph", "tr"):
            t = _text(node)
            if len(t) >= min_len:
                out.append(t)
    return list(dict.fromkeys(out))


def _section_paragraphs(root, code: str, min_len: int = MIN_PARA,
                        title_kw: str = "") -> List[str]:
    """按 LOINC 码取章节；码缺失时按标题关键词兜底（不同厂家的 SPL 结构有差异）。"""
    for sec in root.iter():
        if _local(sec.tag) != "section":
            continue
        if code in {c.get("code") for c in sec.iter() if _local(c.tag) == "code"}:
            return _paragraphs(sec, min_len)
    if title_kw:
        for sec in root.iter():
            if _local(sec.tag) != "section":
                continue
            title = next((_text(c) for c in sec if _local(c.tag) == "title"), "")
            if title_kw in title.upper():
                return _paragraphs(sec, min_len)
    return []


_NONE_RE = re.compile(r"^none\.?(\s*\(\d+\))?$", re.IGNORECASE)


def _normalize_contraindications(items: List[str]) -> List[str]:
    """FDA 说明书常把禁忌写成「None.」，归一为可读表述；其余照原文保留。"""
    kept = [x for x in items if not _NONE_RE.match(x.strip())]
    if kept:
        return kept[:10]
    return ["无（FDA 说明书原文标注 None，未列出禁忌证）"]


def _search_spls(generic: str, limit: int = 6) -> List[Dict]:
    """返回候选 SPL 列表：优先标题以通用名开头的（原研/主要标签），最多 limit 个。

    同一通用名在 DailyMed 下常有几十个 ANDA 标签，结构差异很大（有的缺章节），
    因此按顺序逐个尝试，取第一份章节齐全的。
    """
    url = SPL_API.format(urllib.parse.quote(generic))
    try:
        data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
    except Exception as e:
        print(f"    检索失败: {type(e).__name__} {str(e)[:80]}")
        return []
    items = data.get("data", [])
    matched = [i for i in items if (i.get("title") or "").upper().startswith(generic.upper())]
    return (matched or items)[:limit]


def _iso_date(s: str) -> Optional[str]:
    """DailyMed 返回「Jul 23, 2026」，契约要求 YYYY-MM-DD（V7）。"""
    from datetime import datetime
    s = (s or "").strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _download_xml(setid: str) -> Optional[bytes]:
    try:
        return urllib.request.urlopen(urllib.request.Request(SPL_XML.format(setid), headers=UA),
                                      timeout=90).read()
    except Exception as e:
        print(f"    下载失败: {type(e).__name__} {str(e)[:80]}")
        return None


def build_record(generic: str, cancer: str, drug_id: str, setid: str, xml_bytes: bytes,
                 published: str) -> Dict:
    root = ET.fromstring(xml_bytes)
    ind = _section_paragraphs(root, SEC["indications"], title_kw="INDICATIONS")
    dose = _section_paragraphs(root, SEC["dosage"], title_kw="DOSAGE")
    # 禁忌章节常见「None.」短句，需放宽最小长度再归一化
    contra = _normalize_contraindications(
        _section_paragraphs(root, SEC["contraindications"], min_len=2,
                            title_kw="CONTRAINDICATION"))
    adv = _section_paragraphs(root, SEC["adverse"], title_kw="ADVERSE REACTIONS")
    inter = _section_paragraphs(root, SEC["interactions"], title_kw="DRUG INTERACTIONS")

    standard = " ".join(dose)[:1800] if dose else None
    adjustment = " ".join(dose[3:])[:1200] if len(dose) > 3 else None

    adv_items = []
    for t in adv[:MAX_ADV]:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", t)
        adv_items.append({"term": t[:160], "frequency": m.group(0) if m else None,
                          "ctcae_hint": None})

    iso = _iso_date(published)
    year = (iso or "2024")[:4]
    title = f"{generic} 说明书（FDA DailyMed）"
    return {
        "drug_id": drug_id,
        "generic_name": generic,
        "brand_names": [],
        "title": title,
        "indications": ind[:MAX_IND],
        "dosage": {"standard": standard, "adjustment": adjustment},
        "contraindications": contra,
        "adverse_reactions": adv_items,
        "cancer_type": cancer,
        "doc_type": "drug_label",
        "issuer": "FDA / DailyMed",
        "publish_date": iso,
        "license_note": "FDA DailyMed public label（公有领域，可引用）",
        "file_path": f"raw/drug_labels/{drug_id}.xml",
        "doc_hash": hashlib.sha256(xml_bytes).hexdigest(),
        "review_status": "draft",
        "_source": "dailymed",
        "_setid": setid,
        "_source_url": SPL_XML.format(setid),
        "atc_code": ATC[generic],
        "approval_no": None,
        "source_name": title,
        "source_version": year,
        "source_section": "全文",
        "source_file": f"{drug_id}.xml",
        "updated_at": "2026-10-26",
        "interactions": inter[:30] or None,
    }


# 同一份说明书同时服务两个癌种时，按癌种建独立记录：
# 贝伐珠单抗、帕博利珠单抗的适应证涵盖结直肠癌，但主记录挂在 lung 下，
# 按 cancer_type 过滤时会被排除，故补一条 colorectal 视图记录（正文与 XML 复用）。
EXTRA_COLORECTAL = {
    "PEMBROLIZUMAB": ("DRUG-LUNG-FDA-002", "DRUG-COLORECTAL-FDA-008"),
    "BEVACIZUMAB": ("DRUG-LUNG-FDA-003", "DRUG-COLORECTAL-FDA-009"),
}


def link_colorectal_views() -> None:
    """为跨癌种药物生成结直肠视图记录（复用同一份原始 XML，不改正文）。"""
    for generic, (src_id, dst_id) in EXTRA_COLORECTAL.items():
        src = os.path.join(CLEAN_DIR, f"{src_id}.json")
        if not os.path.exists(src):
            print(f"  [跳过] {src_id} 不存在")
            continue
        rec = json.load(open(src, encoding="utf-8"))[0]
        rec["drug_id"] = dst_id
        rec["cancer_type"] = "colorectal"
        rec["title"] = f"{generic} 说明书（FDA DailyMed，结直肠癌适应证）"
        rec["source_name"] = rec["title"]
        rec["review_status"] = "draft"
        rec["updated_at"] = "2026-10-26"
        with open(os.path.join(CLEAN_DIR, f"{dst_id}.json"), "w", encoding="utf-8") as f:
            json.dump([rec], f, ensure_ascii=False, indent=1)
        print(f"  ✓ {generic}: {src_id} → {dst_id}（cancer_type=colorectal，复用同一 XML）")


def main() -> None:
    ap = argparse.ArgumentParser(description="DailyMed 说明书补齐（A4）")
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个（调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不下载")
    ap.add_argument("--link-extras", action="store_true",
                    help="只补跨癌种药物的结直肠视图记录（不联网）")
    args = ap.parse_args()

    if args.link_extras:
        link_colorectal_views()
        return

    catalog = json.load(open(args.catalog, encoding="utf-8"))
    plan: List[Dict] = []
    seen = set(EXISTING)
    for item in catalog:
        cancers = item.get("cancer_type") or []
        if not (set(cancers) & set(TARGET_CANCERS)):
            continue
        generic = (item.get("generic_name_en") or "").strip().upper()
        if not generic or generic in seen:
            continue
        if generic not in ATC:
            print(f"  [跳过] {generic} 缺 ATC 编码")
            continue
        seen.add(generic)
        cancer = "colorectal" if "colorectal" in cancers else "lung"
        plan.append({"generic": generic, "cancer": cancer})

    if args.limit:
        plan = plan[:args.limit]

    # 肺侧已存在 DRUG-LUNG-FDA-001~005，新记录从 006 起编号，避免主键冲突
    counters = {"lung": 5, "colorectal": 0}
    for item in plan:
        counters[item["cancer"]] += 1
        item["drug_id"] = f"DRUG-{item['cancer'].upper()}-FDA-{counters[item['cancer']]:03d}"

    print(f"计划抓取 {len(plan)} 份说明书：")
    for p in plan:
        print(f"  {p['drug_id']:<24}{p['generic']:<16}{p['cancer']}")
    if args.dry_run:
        return

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(CLEAN_DIR, exist_ok=True)

    ok, failed = 0, []
    for p in plan:
        print(f"\n[{p['drug_id']}] {p['generic']}")
        candidates = _search_spls(p["generic"])
        if not candidates:
            failed.append((p["generic"], "未检索到 SPL"))
            continue

        rec, spl, xml_bytes, last_reason = None, None, None, "全部候选均缺章节"
        for cand in candidates:
            xml_bytes = _download_xml(cand["setid"])
            if not xml_bytes:
                last_reason = "XML 下载失败"
                continue
            try:
                trial = build_record(p["generic"], p["cancer"], p["drug_id"], cand["setid"],
                                     xml_bytes, cand.get("published_date", "") or "")
            except ET.ParseError as e:
                last_reason = f"XML 解析失败 {e}"
                continue
            missing = [k for k in ("indications", "dosage", "contraindications",
                                   "adverse_reactions") if not trial.get(k) or
                       (k == "dosage" and not trial["dosage"].get("standard"))]
            if missing:
                last_reason = f"章节缺失 {missing}"
                continue
            rec, spl = trial, cand
            break

        if rec is None:
            failed.append((p["generic"], last_reason))
            print(f"  ✗ {last_reason}")
            continue

        with open(os.path.join(RAW_DIR, f"{p['drug_id']}.xml"), "wb") as f:
            f.write(xml_bytes)
        with open(os.path.join(CLEAN_DIR, f"{p['drug_id']}.json"), "w", encoding="utf-8") as f:
            json.dump([rec], f, ensure_ascii=False, indent=1)
        ok += 1
        print(f"  ✓ 适应证 {len(rec['indications'])} 段 / 用法 {len(rec['dosage']['standard'] or '')} 字 / "
              f"禁忌 {len(rec['contraindications'])} / 不良反应 {len(rec['adverse_reactions'])} / "
              f"相互作用 {len(rec['interactions'] or [])}")
        time.sleep(0.4)

    print(f"\n完成：成功 {ok} 份，失败 {len(failed)} 份")
    for g, why in failed:
        print(f"  - {g}: {why}")


if __name__ == "__main__":
    main()
