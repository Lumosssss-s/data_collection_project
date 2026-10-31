"""第三批 PubMed 摘要 → 主题子集文献数据（方案 B · B1）
================================================================================
从 pubmed_cancer 语料（33,802 条英文摘要）中筛出与现有 6 份指南主题对齐的子集，
转为项目 G2 格式（顶层数组）+ literature schema 字段，作为 ES 的 literature 证据层。

筛选口径（癌种锁定 lung / colorectal，与知识库一致）：
  - 丢弃空标题、摘要短于 100 字符、标题重复的记录；
  - 标题或摘要命中任一主题关键词（肺癌筛查/结节/围手术期；结直肠治疗/遗传/康复）。

输出：data/clean/literature/lit_pubmed_subset.json
运行：python scripts/data_pipeline/build_literature.py
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SRC = Path(r"e:\兴智杯\第三批\clean\corpus\pubmed_cancer\pubmed_cancer_corpus.json")
OUT_FILE = BASE_DIR / "data" / "clean" / "literature" / "lit_pubmed_subset.json"

ALLOWED_CANCERS = {"lung", "colorectal"}

TOPIC_KEYWORDS = {
    "lung": [
        # 筛查 / 结节（对应 DOC-LUNG-EPMC-001 / 003）
        "lung cancer screening", "low-dose ct", "low-dose computed tomography", "ldct",
        "pulmonary nodule", "lung nodule", "nodule management", "pack-year", "smoking cessation",
        # 围手术期（对应 DOC-LUNG-EPMC-002）
        "perioperative", "preoperative", "postoperative", "elderly patients with lung cancer",
        "frailty", "sarcopenia", "lobectomy", "segmentectomy", "thoracic surgery",
    ],
    "colorectal": [
        # 治疗（对应 DOC-COLORECTAL-EPMC-001 / 002）：只留具体治疗议题，避免「colorectal cancer」泛匹配
        "adjuvant chemotherapy", "oxaliplatin", "folfox", "folfiri", "capecitabine",
        "metastatic colorectal", "liver metastasis", "neoadjuvant chemoradiotherapy",
        "total mesorectal excision", "conversion therapy",
        # 遗传性（对应 DOC-COLORECTAL-EPMC-003）
        "hereditary colorectal", "lynch syndrome", "familial adenomatous polyposis",
        "polyposis", "mismatch repair", "msi-h", "dmmr", "germline",
        # 运动康复（对应 DOC-COLORECTAL-EPMC-001 运动章节）
        "physical activity", "exercise intervention", "exercise program",
        "surveillance colonoscopy", "postoperative surveillance",
    ],
}

MIN_ABSTRACT = 100
WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return WS.sub(" ", (text or "")).strip()


def matches_topics(cancer_type: str, text: str) -> bool:
    return any(k in text for k in TOPIC_KEYWORDS.get(cancer_type, []))


def main() -> int:
    ap = argparse.ArgumentParser(description="第三批 PubMed 摘要主题子集构建")
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(OUT_FILE))
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"❌ 源语料不存在: {src}")
        return 1

    with open(src, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    print(f"源语料 {len(corpus)} 条")

    stats: Dict[str, int] = {
        "cancer_filtered": 0, "empty_title": 0, "short_abstract": 0,
        "topic_miss": 0, "dup_title": 0, "near_dup": 0, "kept": 0,
    }
    seen_title = set()
    out: List[Dict] = []
    seq = {"lung": 0, "colorectal": 0}

    for rec in corpus:
        ct = rec.get("cancer_type")
        if ct not in ALLOWED_CANCERS:
            stats["cancer_filtered"] += 1
            continue
        title = norm(rec.get("title"))
        abstract = norm(rec.get("abstract"))
        if not title:
            stats["empty_title"] += 1
            continue
        if len(abstract) < MIN_ABSTRACT:
            stats["short_abstract"] += 1
            continue
        text = f"{title} {abstract}".lower()
        if not matches_topics(ct, text):
            stats["topic_miss"] += 1
            continue
        tkey = title.lower()[:80]
        if tkey in seen_title:
            stats["dup_title"] += 1
            continue
        seen_title.add(tkey)

        pmid = str(rec.get("pmid") or "")
        seq[ct] += 1
        out.append({
            "doc_id": f"DOC-{'LUNG' if ct == 'lung' else 'CRC'}-PUB-{seq[ct]:04d}",
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "cancer_type": ct,
            "lang": "en",
            "origin": "pubmed_cancer",
            "doc_hash": hashlib.sha256(f"{title}\n{abstract}".encode("utf-8")).hexdigest(),
            "source_name": "PubMed",
            "source_version": "2024",
            "source_section": None,
            "source_file": "pubmed_cancer_corpus.json",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            "updated_at": "2026-10-25",
            "review_status": "draft",
            "annotation": {"annotator": "自动转换", "date": "2026-10-25", "status": "draft"},
        })
        stats["kept"] += 1

    # 近重复标题剔除（与 V-01 的 V9 口径对齐：同 24 字符桶内相似度 > 0.95 视为重复）
    final: List[Dict] = []
    buckets: Dict[str, List[Dict]] = {}
    for rec in out:
        key = re.sub(r"[^a-z0-9]", "", rec["title"].lower())[:24]
        if any(difflib.SequenceMatcher(None, prev["title"].lower(),
                                       rec["title"].lower()).ratio() > 0.95
               for prev in buckets.get(key, [])):
            stats["near_dup"] += 1
            continue
        buckets.setdefault(key, []).append(rec)
        final.append(rec)

    # 剔除后重排序号，保证 doc_id 连续
    seq = {"lung": 0, "colorectal": 0}
    for rec in final:
        ct = rec["cancer_type"]
        seq[ct] += 1
        rec["doc_id"] = f"DOC-{'LUNG' if ct == 'lung' else 'CRC'}-PUB-{seq[ct]:04d}"
    out = final
    stats["kept"] = len(out)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("筛选统计:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"产出 {len(out)} 条（lung {seq['lung']} / colorectal {seq['colorectal']}）→ {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
