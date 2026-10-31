"""把派生图谱写入 medical_kg_triples / medical_kg_entities（容器内执行）。

ingest.py 对 kg_triples 目录标注「图谱抽取链路 BE-20 延后」，因此单独提供本脚本。
数据来源：data/intermediate/kg_derived.json（由 build_kg_from_corpus.py 生成）。
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from core.config import settings  # noqa: E402
from repositories.elasticsearch import ElasticsearchRepository  # noqa: E402

SRC = os.path.join(BASE_DIR, "data", "intermediate", "kg_derived.json")
SOURCE_ID = "derived-corpus"


def main() -> None:
    payload = json.load(open(SRC, encoding="utf-8"))
    repo = ElasticsearchRepository()

    # 图谱为本项目自建的派生数据，重灌前清空实体词典，避免旧 ID 约定残留
    repo.delete_kg_entities()
    n_ent = repo.merge_kg_entities(payload["entities"])
    n_tri = repo.save_kg_triples(SOURCE_ID, payload["triples"], cancer_type="")
    print(f"实体写入 {n_ent}，三元组写入 {n_tri}")

    for idx in (settings.es_kg_triples_index_name, settings.es_kg_entities_index_name):
        count = repo.client.count(index=idx)["count"]
        print(f"  {idx}: {count}")


if __name__ == "__main__":
    main()
