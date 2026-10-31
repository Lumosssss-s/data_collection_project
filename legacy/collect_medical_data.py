"""小规模医疗指南采集 → 清洗为 G2 格式（欧洲 PMC 开放获取 API）

用途：在正式数据到位前，先为项目注入**真实、可溯源**的少量指南数据，打通
「采集 → 清洗 → 入库 → 检索」链路，避免项目空转。

合规约束（务必遵守）：
- 只走 **Europe PMC 官方 REST API**（https://europepmc.org/RestfulWebService）
- 只采 **OPEN_ACCESS:Y** 且许可明确的条目
- **限流**：请求间固定 sleep，单次运行总量上限内置
- 不绕过任何登录/付费/WAF，不做页面硬爬

输出（G2 格式，顶层数组）：
    medical_rag/data/raw/guidelines/<doc_id>.xml     # 原始 JATS 全文（溯源）
    medical_rag/data/clean/guidelines/<doc_id>.json  # 清洗后 G2 记录数组

字段对齐 ingest.py（DOC 层白名单，C2 §3.3）：
    doc_id / doc_type / issuer / publish_date / cancer_types /
    license_note / file_path / doc_hash / review_status / title + summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UA = "MedicalRAG-CompetitionBot/1.0 (non-commercial; contact: project-team)"

# 单次运行硬上限（防误抓过多）
HARD_MAX_TOTAL = 12
SLEEP_SEC = 1.2

# 癌种 -> (查询式, 癌种枚举, doc_id 代号)
CANCER_QUERY: Dict[str, tuple] = {
    "lung": ('TITLE:"lung cancer"', ["lung"], "LUNG"),
    "colorectal": ('(TITLE:"colorectal cancer" OR TITLE:"colon cancer")', ["colorectal"], "COLORECTAL"),
}

_GUIDELINE_PUB_TYPES = ('PUB_TYPE:"Practice Guideline" OR PUB_TYPE:"Guideline"')

_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = _ROOT / "medical_rag" / "data" / "raw" / "guidelines"
CLEAN_DIR = _ROOT / "medical_rag" / "data" / "clean" / "guidelines"


def _get(url: str, *, binary: bool = False, retries: int = 3):
    """带 UA 与重试的 GET（限流友好）。"""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            time.sleep(SLEEP_SEC)
            return data if binary else data.decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 — 网络类异常统一重试
            last_err = e
            time.sleep(SLEEP_SEC * (attempt + 1))
    raise RuntimeError(f"GET 失败 {url}: {last_err}")


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def search_guidelines(cancer: str, per_cancer: int) -> List[Dict]:
    """检索某癌种的 OA 指南条目（元数据）。"""
    q = f'{CANCER_QUERY[cancer][0]} AND ({_GUIDELINE_PUB_TYPES}) AND OPEN_ACCESS:Y'
    url = (f"{REST}/search?query={urllib.parse.quote(q)}"
           f"&format=json&pageSize={per_cancer * 3}&resultType=core")
    payload = json.loads(_get(url))
    hits = payload.get("resultList", {}).get("result", [])
    return [h for h in hits if h.get("pmcid")]


def parse_jats(xml_text: str) -> Dict:
    """解析 JATS XML，抽取标题/摘要/期刊/日期/DOI/许可。"""
    root = ET.fromstring(xml_text)
    out: Dict = {"title": "", "abstract": "", "journal": "", "date": "", "doi": "", "license": ""}

    # 标题
    for el in root.iter():
        if _strip_ns(el.tag) == "article-title" and el.text and not out["title"]:
            out["title"] = "".join(el.itertext()).strip()

    # 摘要（可能有多段，拼接）
    abs_parts: List[str] = []
    for el in root.iter():
        if _strip_ns(el.tag) == "abstract":
            txt = " ".join(" ".join(el.itertext()).split())
            if txt:
                abs_parts.append(txt)
    out["abstract"] = " ".join(abs_parts)[:6000]

    # 期刊名
    for el in root.iter():
        if _strip_ns(el.tag) == "journal-title" and el.text:
            out["journal"] = el.text.strip()
            break

    # 出版日期（优先 year+month+day）
    ym = {"year": "", "month": "", "day": ""}
    for el in root.iter():
        t = _strip_ns(el.tag)
        if t in ym and el.text and not ym[t]:
            ym[t] = el.text.strip()
    if ym["year"]:
        out["date"] = "-".join(p for p in [ym["year"], ym["month"].zfill(2) if ym["month"] else "",
                                           ym["day"].zfill(2) if ym["day"] else ""] if p)

    # DOI / 许可
    for el in root.iter():
        t = _strip_ns(el.tag)
        if t == "article-id" and el.get("pub-id-type") == "doi" and el.text:
            out["doi"] = el.text.strip()
        if t == "license" and not out["license"]:
            lic = el.get("license-type") or ""
            href = ""
            for sub in el.iter():
                if _strip_ns(sub.tag) == "ext-link" and sub.get("href"):
                    href = sub.get("href")
            out["license"] = (lic + (" " + href if href else "")).strip()
    return out


def build_clean_record(meta: Dict, jats: Dict, cancer: str, seq: int) -> Dict:
    """组装符合 ingest.py DOC 白名单的 G2 记录。"""
    code = CANCER_QUERY[cancer][2]
    doc_id = f"DOC-{code}-EPMC-{seq:03d}"
    xml_bytes = meta["_xml"].encode("utf-8")
    doc_hash = hashlib.sha256(meta["pmcid"].encode()).hexdigest()[:32]
    summary = (jats["abstract"] or meta.get("title") or "").strip()

    return {
        # —— ingest 直接消费 ——
        "doc_id": doc_id,
        "title": (jats["title"] or meta.get("title") or "")[:300],
        "summary": summary,
        # —— DOC 层白名单字段 ——
        "doc_type": "guideline",
        "issuer": (jats["journal"] or meta.get("journalTitle") or "Europe PMC")[:200],
        "publish_date": jats["date"] or str(meta.get("pubYear") or ""),
        "cancer_types": CANCER_QUERY[cancer][1],
        "license_note": (jats["license"] or "Open Access (Europe PMC)")[:200],
        "file_path": f"raw/guidelines/{doc_id}.xml",
        "doc_hash": doc_hash,
        "review_status": "approved",
        # —— 溯源（非白名单，入库前会被裁剪；保留在 clean 便于人工核对）——
        "_source": "europepmc",
        "_pmid": meta.get("pmid", ""),
        "_pmcid": meta["pmcid"],
        "_doi": jats["doi"],
        "_source_url": f"{REST}/{meta['pmcid']}/fullTextXML",
        "_xml_bytes": len(xml_bytes),
    }


def collect(cancers: List[str], per_cancer: int, limit_total: int) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    summary_rows: List[tuple] = []
    seen_ids: set = set()

    for cancer in cancers:
        print(f"\n=== 癌种 {cancer} ===")
        hits = search_guidelines(cancer, per_cancer)
        print(f"  检索命中候选 {len(hits)} 条")
        got = 0
        for h in hits:
            if got >= per_cancer or total >= limit_total:
                break
            pmcid = h["pmcid"]
            if pmcid in seen_ids:
                continue
            try:
                xml_text = _get(f"{REST}/{pmcid}/fullTextXML")
            except Exception as e:  # noqa: BLE001
                print(f"  ! 全文取回失败 {pmcid}: {str(e)[:60]}")
                continue
            if "<article" not in xml_text[:2000]:
                print(f"  ! {pmcid} 非 JATS 全文（可能未开放），跳过")
                continue
            try:
                jats = parse_jats(xml_text)
            except Exception as e:  # noqa: BLE001
                print(f"  ! XML 解析失败 {pmcid}: {str(e)[:60]}")
                continue
            if not jats["abstract"]:
                print(f"  ! {pmcid} 无摘要，跳过（避免入库空正文）")
                continue

            h["_xml"] = xml_text
            rec = build_clean_record(h, jats, cancer, got + 1)
            (RAW_DIR / f"{rec['doc_id']}.xml").write_text(xml_text, encoding="utf-8")
            (CLEAN_DIR / f"{rec['doc_id']}.json").write_text(
                json.dumps([rec], ensure_ascii=False, indent=2), encoding="utf-8")

            seen_ids.add(pmcid)
            got += 1
            total += 1
            summary_rows.append((rec["doc_id"], cancer, len(jats["abstract"]),
                                 len(xml_text), rec["publish_date"], rec["title"][:52]))
            print(f"  ✓ {rec['doc_id']}  摘要 {len(jats['abstract'])} 字  全文 {len(xml_text)} 字")

    print("\n" + "=" * 88)
    print(f"采集完成：{total} 条（raw → {RAW_DIR}）")
    print("%-22s %-11s %8s %9s %-12s %s" % ("doc_id", "cancer", "摘要字数", "全文长度", "publish_date", "title"))
    for r in summary_rows:
        print("%-22s %-11s %8d %9d %-12s %s" % r)
    print("=" * 88)


# =========================== 药品说明书（DailyMed / FDA） ===========================

DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
DRUG_RAW_DIR = _ROOT / "medical_rag" / "data" / "raw" / "drug_labels"
DRUG_CLEAN_DIR = _ROOT / "medical_rag" / "data" / "clean" / "drug_labels"

# 肺癌核心靶向/免疫药：通用名 -> (品牌查询词, 代号)
# 必须按品牌名精确检索，否则会命中同通用名的其它剂型
# （实例：bevacizumab 按通用名检索会先命中眼科创剂 LYTENAVA）
LUNG_DRUGS: Dict[str, tuple] = {
    "osimertinib": ("TAGRISSO", "OSIMERTINIB"),
    "pembrolizumab": ("KEYTRUDA", "PEMBROLIZUMAB"),
    "bevacizumab": ("AVASTIN", "BEVACIZUMAB"),
    "pemetrexed": ("ALIMTA", "PEMETREXED"),
    "crizotinib": ("XALKORI", "CRIZOTINIB"),
}

# 适应证相关性闸门：说明书适应证须含肺癌关键词，剔除同通用名的非肿瘤剂型
_LUNG_IND_RE = re.compile(r"\b(lung|NSCLC|non-small cell)\b", re.I)
_MAX_CANDIDATES = 4   # 每个药最多尝试的候选说明书数（限流友好）

# LOINC 章节码 -> 目标字段
_LOINC_MAP = {
    "34067-9": ("indications", 4000),          # Indications & Usage
    "34068-7": ("dosage", 4000),               # Dosage & Administration
    "34070-3": ("contraindications", 2500),    # Contraindications
    "34084-4": ("adverse_reactions", 3000),    # Adverse Reactions
}


def _iso_date(value) -> Optional[str]:
    """只保留合法 YYYY-MM-DD / YYYY-MM / YYYY，否则返回 None（ES date 拒绝空串）。"""
    s = str(value or "").strip()
    return s if re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", s) else None


def _section_text(el) -> str:
    """把 <section>/<text> 的可见文本压平。"""
    return " ".join(" ".join(el.itertext()).split())


def parse_spl(xml_text: str) -> Dict[str, str]:
    """按 LOINC 章节码从 SPL XML 抽取说明书关键章节。"""
    root = ET.fromstring(xml_text)
    out: Dict[str, str] = {}
    for sec in root.iter():
        if _strip_ns(sec.tag) != "section":
            continue
        code = ""
        for child in sec:
            if _strip_ns(child.tag) == "code" and child.get("code"):
                code = child.get("code")
                break
        if code not in _LOINC_MAP:
            continue
        field, cap = _LOINC_MAP[code]
        if field in out:
            continue
        txt = _section_text(sec)
        if txt:
            out[field] = txt[:cap]
    return out


def collect_drugs(limit: int) -> None:
    DRUG_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DRUG_CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    rows: List[tuple] = []
    for seq, (generic, (brand, code)) in enumerate(LUNG_DRUGS.items(), start=1):
        if total >= limit:
            break
        print(f"\n=== 药品 {generic}（品牌 {brand}）===")
        try:
            meta = json.loads(_get(f"{DAILYMED}/spls.json?drug_name={urllib.parse.quote(brand)}"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! 检索失败: {str(e)[:70]}")
            continue
        items = meta.get("data", [])
        if not items:
            print("  ! 无匹配说明书")
            continue

        # 逐个候选取回，做「肺癌适应证」闸门校验，命中即采用
        spl = None
        xml_text = ""
        secs: Dict[str, str] = {}
        for cand in items[:_MAX_CANDIDATES]:
            cand_id = cand.get("setid")
            if not cand_id:
                continue
            try:
                xml_text = _get(f"{DAILYMED}/spls/{cand_id}.xml")
                secs = parse_spl(xml_text)
            except Exception as e:  # noqa: BLE001
                print(f"  ! 候选 {cand_id} 取回/解析失败: {str(e)[:50]}")
                continue
            ind = secs.get("indications", "")
            if ind and _LUNG_IND_RE.search(ind):
                spl = cand
                break
            print(f"  · 候选 {cand_id} 适应证不含肺癌关键词，跳过")
        if spl is None:
            print("  ! 未找到含肺癌适应证的说明书，跳过该药")
            continue
        setid = spl.get("setid")

        drug_id = f"DRUG-LUNG-FDA-{seq:03d}"
        rec = {
            "drug_id": drug_id,
            "generic_name": generic.upper(),
            "brand_names": [spl.get("title", "").split(" (")[0]] if spl.get("title") else [],
            "title": f"{generic.upper()} 说明书（FDA DailyMed）",
            "indications": secs.get("indications", ""),
            # ES mapping：dosage = object {standard, adjustment}；adverse_reactions = object
            "dosage": {"standard": secs.get("dosage", ""), "adjustment": ""},
            "contraindications": secs.get("contraindications", ""),
            "adverse_reactions": {"text": secs.get("adverse_reactions", "")},
            "cancer_type": "lung",
            "doc_type": "drug_label",
            "issuer": "FDA / DailyMed",
            "publish_date": _iso_date(spl.get("published_date")),
            "license_note": "FDA DailyMed public label",
            "file_path": f"raw/drug_labels/{drug_id}.xml",
            "doc_hash": hashlib.sha256(str(setid).encode()).hexdigest()[:32],
            "review_status": "approved",
            "_source": "dailymed",
            "_setid": setid,
            "_source_url": f"{DAILYMED}/spls/{setid}.xml",
        }
        (DRUG_RAW_DIR / f"{drug_id}.xml").write_text(xml_text, encoding="utf-8")
        (DRUG_CLEAN_DIR / f"{drug_id}.json").write_text(
            json.dumps([rec], ensure_ascii=False, indent=2), encoding="utf-8")

        total += 1
        rows.append((drug_id, generic, len(rec["indications"]),
                     len(rec["dosage"]), len(rec["contraindications"]), len(xml_text)))
        print(f"  ✓ {drug_id}  适应证 {len(rec['indications'])} 字  "
              f"用法 {len(rec['dosage'])} 字  全文 {len(xml_text)} 字")

    print("\n" + "=" * 88)
    print(f"药品采集完成：{total} 条（raw → {DRUG_RAW_DIR}）")
    print("%-20s %-16s %8s %8s %10s %10s" % ("drug_id", "generic", "适应证", "用法", "禁忌", "XML长度"))
    for r in rows:
        print("%-20s %-16s %8d %8d %10d %10d" % r)
    print("=" * 88)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="小规模医疗数据采集（Europe PMC 指南 + DailyMed 药品）")
    ap.add_argument("--kind", choices=["guidelines", "drugs", "all"], default="all",
                    help="采集类别")
    ap.add_argument("--cancers", nargs="+", default=["lung", "colorectal"],
                    choices=list(CANCER_QUERY), help="目标癌种（仅 guidelines）")
    ap.add_argument("--per-cancer", type=int, default=3, help="每癌种采集条数")
    ap.add_argument("--drug-limit", type=int, default=5, help="药品条数上限")
    ap.add_argument("--limit-total", type=int, default=HARD_MAX_TOTAL, help="指南总上限")
    a = ap.parse_args()
    if a.kind in ("guidelines", "all"):
        collect(a.cancers, a.per_cancer, min(a.limit_total, HARD_MAX_TOTAL))
    if a.kind in ("drugs", "all"):
        collect_drugs(min(a.drug_limit, len(LUNG_DRUGS)))
