"""独立运行指南摘要生成 — 在容器内执行: python run_abstracts.py [--force]

聚合主索引中 DOC 记录的 doc_id（data_type=doc），逐个生成指南摘要并写回
doc.content（C2 §3.1）。默认跳过已有摘要的文档（中断重跑只补缺，C3 I-02）；
--force 强制全部重新生成。限流 delay=2.0 沿用。
"""
import argparse

from elasticsearch import Elasticsearch

from core.config import settings
from services.abstract_service import AbstractService


def main(force: bool = False):
    es = Elasticsearch(
        hosts=settings.es_hosts,
        verify_certs=settings.es_verify_certs,
        basic_auth=(settings.es_user, settings.es_password) if settings.es_user else None,
    )

    # 聚合 DOC 记录的 doc_id（过滤 data_type=doc，避免把 REC/DRUG 的 doc_id 混入）
    resp = es.search(
        index=settings.es_index_name,
        body={
            "size": 0,
            "query": {"term": {"data_type": "doc"}},
            "aggs": {"doc_ids": {"terms": {"field": "doc_id", "size": 500}}},
        },
    )
    doc_ids = [b["key"] for b in resp["aggregations"]["doc_ids"]["buckets"]]
    print(f"Found {len(doc_ids)} docs to generate abstracts (force={force})")
    if doc_ids:
        print(f"Doc IDs: {doc_ids[:10]}... (showing first 10)")

    if not doc_ids:
        print("无 DOC 记录，跳过")
        return

    svc = AbstractService()
    svc.generate_for_docs(doc_ids, delay=2.0, force=force)
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="指南文档摘要生成脚本")
    parser.add_argument("--force", action="store_true", help="强制重新生成（忽略已有摘要）")
    args = parser.parse_args()
    main(force=args.force)
