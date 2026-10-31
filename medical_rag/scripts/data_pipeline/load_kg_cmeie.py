"""把 CMeIE 转换结果写入图谱索引（容器内执行）。

数据来源：data/intermediate/kg_cmeie_converted.json（convert_cmeie_kg.py 产出）。
与 derived-corpus 已有的同 (head, relation, tail) 边去重，避免同一事实重复计入。
写入采用 source_id 覆盖式，重跑幂等。
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from core.config import settings  # noqa: E402
from repositories.elasticsearch import ElasticsearchRepository  # noqa: E402

SRC = os.path.join(BASE_DIR, "data", "intermediate", "kg_cmeie_converted.json")
SOURCE_ID = "cblue-cmeie"


def main() -> None:
    payload = json.load(open(SRC, encoding="utf-8"))
    repo = ElasticsearchRepository()

    existing = {(t["head"]["id"], t["relation"], t["tail"]["id"])
                for t in repo.get_kg_triples("derived-corpus", size=5000)}
    triples = [t for t in payload["triples"]
               if (t["head"]["id"], t["relation"], t["tail"]["id"]) not in existing]
    print(f"源 {len(payload['triples'])} 条，与 derived-corpus 去重后 {len(triples)} 条")

    n_ent = repo.merge_kg_entities(payload["entities"])
    n_tri = repo.save_kg_triples(SOURCE_ID, triples)
    print(f"实体写入 {n_ent}，三元组写入 {n_tri}")

    for idx in (settings.es_kg_triples_index_name, settings.es_kg_entities_index_name):
        print(f"  {idx}: {repo.client.count(index=idx)['count']}")


if __name__ == "__main__":
    main()
