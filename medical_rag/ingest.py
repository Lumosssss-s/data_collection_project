"""医疗知识库入库脚本 —— 容器内执行: python ingest.py [--rebuild] [--force] [--batch-size N]

按 C2 §2 路由表 + C3 §5 目录/前缀/归宿权威表，把 data/clean/ 下 G3 固定目录的数据
导入 ES：

    guidelines/       DOC  -> medical_knowledge (data_type=doc，元数据)
    recommendations/  REC  -> medical_knowledge (data_type=rec，检索主单元)
    drug_labels/      DRUG -> medical_knowledge (data_type=drug)
    terminology/      TERM -> medical_knowledge (data_type=term)
    disease_profiles/ DIS  -> medical_disease_profiles（写入方法待建，本轮延后）
    kg_triples/       KG   -> medical_kg_triples(+entities)（图谱链路，见 BE-20，本轮延后）
    其余 8 目录为文件态（C3 §5），不入 ES。

要点（C3 I-01）：ES _id = 业务 ID（doc_id / rec_id / drug_id / term_id），幂等重灌；
--rebuild 清空重建、默认增量 upsert；只认 G2 格式（.json 顶层数组 / .jsonl 每行一条），
不做旧格式兼容（原「新旧格式兼容 / law_id 推断」逻辑已整体移除）。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from core.config import settings
from repositories.elasticsearch import ElasticsearchRepository
from utils.doc_catalog import DocCatalog
from utils.topic_classifier import TopicClassifier


# 目录 -> data_type（C3 §5 / C2 §2 路由表）
_ES_ROUTED_DIRS: Dict[str, str] = {
    "guidelines": "doc",
    "recommendations": "rec",
    "drug_labels": "drug",
    "terminology": "term",
    "literature": "literature",
}

# 各类型业务 ID 字段（= ES _id）与 G5 前缀（用于前缀一致性校验）
_ID_FIELD: Dict[str, str] = {
    "doc": "doc_id", "rec": "rec_id", "drug": "drug_id", "term": "term_id",
    "literature": "doc_id",
}
_ID_PREFIX: Dict[str, str] = {
    "doc": "DOC-", "rec": "REC-", "drug": "DRUG-", "term": "TERM-",
    "literature": "DOC-",
}

# 已登记但本轮延后（有 ES 归宿，尚缺写入方法 / 链路）
_DEFERRED_DIRS: Dict[str, str] = {
    "disease_profiles": "medical_disease_profiles（疾病档案写入方法待建，延后）",
    "kg_triples": "medical_kg_triples + medical_kg_entities（图谱抽取链路 BE-20，延后）",
}

# 文件态目录（C3 §5：不入 ES，仅供对应模块直读）
_FILE_STATE_DIRS: Tuple[str, ...] = (
    "triage_rules", "preconsult_slots", "followup_templates", "patient_messages",
    "qc_rules", "eval_sets", "mock_cases", "ops_metrics",
)


def _join_nonempty(values) -> str:
    """把标量 / 数组拼成一段文本，过滤空值。"""
    parts: List[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            parts.extend(str(x).strip() for x in v if x is not None and str(x).strip())
        elif str(v).strip():
            parts.append(str(v).strip())
    return " ".join(parts).strip()


def _extract_content(data_type: str, record: Dict) -> str:
    """按类型抽取进入向量检索的正文。"""
    if data_type == "rec":
        # 推荐条目：检索主单元，正文即推荐结论原文
        return _join_nonempty([record.get("recommendation_text")])
    if data_type == "term":
        # 术语：规范名 + 同义词，支撑「简称/别名」检索与实体归一
        return _join_nonempty([record.get("canonical"), record.get("synonyms")])
    if data_type == "drug":
        # 说明书：通用名 + 适应证 + 禁忌 + 用法用量（截断）+ 相互作用（前 2 条）
        # 用法用量是「剂量/给药」类问题的直接命中依据，不截断会挤占向量篇幅，取前 800 字。
        dosage = record.get("dosage") or {}
        standard = dosage.get("standard") if isinstance(dosage, dict) else None
        return _join_nonempty([
            record.get("generic_name"),
            record.get("indications"),
            record.get("contraindications"),
            (standard or "")[:800],
            (record.get("interactions") or [])[:2],
        ])
    if data_type == "literature":
        # 文献证据层：题名 + 英文摘要（跨语言向量检索命中，作为二级证据）
        return _join_nonempty([record.get("title"), record.get("abstract")])
    # doc：文档级元数据记录，正文取指南名（若数据含摘要字段则优先）
    return _join_nonempty([
        record.get("summary"), record.get("abstract"), record.get("title"),
    ])


def _default_title(data_type: str, record: Dict) -> str:
    """按类型给出展示用标题（各类型无统一 title 字段时回落到代表性字段）。"""
    if data_type == "rec":
        return record.get("breadcrumb", "") or record.get("doc_id", "") or ""
    if data_type == "drug":
        return record.get("generic_name", "") or ""
    if data_type == "term":
        return record.get("canonical", "") or ""
    return record.get("title", "") or ""


def _build_metadata(data_type: str, record: Dict) -> Dict:
    """构造入库 metadata：整条记录 + data_type，并补齐 title。

    结构化字段的白名单落库由 repositories.add_documents 统一裁剪（§5.7.2 ∩ C2 §3.3）。
    """
    meta = dict(record)
    meta["data_type"] = data_type
    if not meta.get("title"):
        meta["title"] = _default_title(data_type, record)
    return meta


def _load_records(path: Path) -> List[Dict]:
    """读取 G2 格式记录（.json 顶层数组 / .jsonl 每行一条）。

    只认 G2，不做旧格式兼容：顶层非数组即视为不合格并跳过。
    """
    try:
        if path.suffix == ".jsonl":
            records: List[Dict] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            return records
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"⚠️  {path.name} 顶层非数组（不符 G2），跳过")
            return []
        return data
    except Exception as e:
        print(f"⚠️  {path.name} 解析失败: {e}")
        return []


def process_json_file(
    json_file: Path, data_type: str, repo, skip_existing: bool = True
) -> Iterator[Tuple[str, Dict, str]]:
    """解析单个 JSON 文件，产出 (正文, metadata, 业务 ID) 三元组。

    参数:
        data_type: 由目录决定（guidelines->doc / recommendations->rec /
                   drug_labels->drug / terminology->term）
        skip_existing: True 时按业务 ID 跳过已存在记录（幂等重灌）
    """
    print(f"处理 {json_file.name}（data_type={data_type}）...")
    records = _load_records(json_file)
    if not records:
        return

    id_field = _ID_FIELD[data_type]
    expected_prefix = _ID_PREFIX[data_type]

    for record in records:
        if not isinstance(record, dict):
            print(f"⚠️  {json_file.name} 含非对象记录，跳过")
            continue

        item_id = str(record.get(id_field, "") or "").strip()
        if not item_id:
            print(f"⚠️  {json_file.name} 记录缺少 {id_field}，跳过")
            continue
        if not item_id.startswith(expected_prefix):
            print(f"⚠️  {item_id} 前缀与目录类型 {data_type}（期望 {expected_prefix}）不一致，仍入库")

        if skip_existing and repo.exists_item(item_id):
            print(f"⏭️  跳过已存在: {item_id}")
            continue

        content = _extract_content(data_type, record) or item_id
        yield content, _build_metadata(data_type, record), item_id


def load_json_files(
    clean_dir: Path, repo, skip_existing: bool = True
) -> Iterator[Tuple[str, Dict, str]]:
    """遍历 data/clean/ 的 G3 固定目录，按路由表分流。"""
    if not clean_dir.exists():
        print(f"⚠️  清洗数据目录不存在: {clean_dir}")
        return

    for sub in sorted(clean_dir.iterdir()):
        if not sub.is_dir():
            continue
        name = sub.name

        if name in _FILE_STATE_DIRS:
            print(f"⏭️  跳过文件态目录 {name}/（C3 §5：不入 ES）")
            continue
        if name in _DEFERRED_DIRS:
            print(f"⏸️  延后目录 {name}/：{_DEFERRED_DIRS[name]}")
            continue

        data_type = _ES_ROUTED_DIRS.get(name)
        if data_type is None:
            print(f"⚠️  目录 {name}/ 不在 G3 14 目录内，跳过")
            continue

        for json_file in sorted(sub.glob("*.json")) + sorted(sub.glob("*.jsonl")):
            yield from process_json_file(json_file, data_type, repo, skip_existing)


def _print_type_counts(repo: ElasticsearchRepository):
    """按 data_type 输出 ES 对账表（C3 I-01 ④）。"""
    try:
        resp = repo.client.search(
            index=settings.es_index_name,
            body={"size": 0, "aggs": {"by_type": {"terms": {"field": "data_type", "size": 20}}}},
        )
        buckets = resp["aggregations"]["by_type"]["buckets"]
        print("按 data_type 对账:")
        for b in buckets:
            print(f"   • {b['key']}: {b['doc_count']}")
        print(f"   索引总条数: {repo.count()}")
    except Exception as e:
        print(f"⚠️  统计失败: {e}")


def ingest_data(batch_size: int = 32, clear_index: bool = False, force: bool = False):
    """入库 data/clean/ 到 ES。

    参数:
        batch_size: 批量写入大小
        clear_index: 清空主索引后重建（--rebuild）
        force: 忽略幂等跳过，强制覆盖
    """
    print("开始加载医疗数据...")

    repo = ElasticsearchRepository()
    catalog = DocCatalog()

    if clear_index:
        print("清空主索引并重建空 catalog...")
        repo.clear()
        catalog.save({"version": "1.0", "last_updated": "", "total_docs": 0, "docs": []})
        print("索引与 catalog 已清空")

    total = 0
    doc_metas: Dict[str, Dict] = {}   # doc_id -> DOC 记录（供 catalog 更新）
    rec_counts: Dict[str, int] = {}   # doc_id -> 推荐条目数（供 catalog item_count）

    documents_batch: List[str] = []
    metadatas_batch: List[Dict] = []
    ids_batch: List[str] = []

    for content, meta, item_id in load_json_files(
        Path(settings.clean_data_dir), repo, skip_existing=not force
    ):
        documents_batch.append(content)
        metadatas_batch.append(meta)
        ids_batch.append(item_id)

        data_type = meta.get("data_type")
        if data_type == "doc":
            doc_metas[item_id] = meta
        elif data_type == "rec":
            doc_id = meta.get("doc_id")
            if doc_id:
                rec_counts[doc_id] = rec_counts.get(doc_id, 0) + 1

        if len(documents_batch) >= batch_size:
            print(f"写入第 {total + 1} - {total + len(documents_batch)} 条...")
            repo.add_documents(documents_batch, metadatas_batch, ids_batch)
            total += len(documents_batch)
            documents_batch, metadatas_batch, ids_batch = [], [], []

    if documents_batch:
        print(f"写入第 {total + 1} - {total + len(documents_batch)} 条...")
        repo.add_documents(documents_batch, metadatas_batch, ids_batch)
        total += len(documents_batch)

    # 更新 doc_catalog.json（仅 DOC 记录入目录；item_count 取该文档的 REC 条数）
    print("\n📋 更新文档目录 (doc_catalog.json)...")
    for doc_id, meta in doc_metas.items():
        try:
            catalog.add_or_update(
                doc_id=doc_id,
                title=meta.get("title", ""),
                doc_type=meta.get("doc_type", ""),
                issuer=meta.get("issuer", ""),
                cancer_types=meta.get("cancer_types") or [],
                item_count=rec_counts.get(doc_id, 0),
                version=meta.get("version", ""),
                publish_date=meta.get("publish_date", ""),
                file_path=meta.get("file_path", ""),
                status="active",
            )
        except Exception as e:
            print(f"⚠️  更新 {doc_id} 的 catalog 记录失败: {e}")

    print("\n" + "=" * 60)
    print("📊 入库完成统计")
    print("=" * 60)
    print(f"✅ 成功写入条目数: {total}")
    print(f"📚 文档目录记录数: {len(doc_metas)}")
    _print_type_counts(repo)

    # 重新标注主题（topics_details）
    print("\n🔄 开始重新标注主题...")
    reannotate_all_data(repo)

    print("\n🧾 指南摘要请单独运行 run_abstracts.py（BE-38）")


def reannotate_all_data(repo: ElasticsearchRepository):
    """重新标注所有数据的主题字段"""
    print("初始化主题分类器...")
    classifier = TopicClassifier()
    print(f"加载词表版本: {classifier.taxonomy_version}, 主题数: {len(classifier.topics)}")

    total_docs = repo.count()
    print(f"开始处理 {total_docs} 条数据...")

    batch_size = 100
    processed = 0
    labeled = 0

    # 使用 scroll 游标遍历全部文档, 避免 from+size 超过 10000 限制
    results = repo.client.search(
        index=settings.es_index_name,
        body={"query": {"match_all": {}}, "size": batch_size},
        scroll="2m",
    )
    scroll_id = results.get("_scroll_id")

    try:
        while True:
            hits = results["hits"]["hits"]
            if not hits:
                break

            bulk_actions = []
            for hit in hits:
                doc_id = hit["_id"]
                source = hit["_source"]

                text = source.get("content", "")
                topics_info = classifier.classify_document(text)

                update_action = {
                    "_op_type": "update",
                    "_index": settings.es_index_name,
                    "_id": doc_id,
                    "doc": {
                        # C2 §3.3：主题字段仅 topics_details（nested）+ taxonomy_version
                        "topics_details": topics_info["topics_details"],
                        "taxonomy_version": topics_info["taxonomy_version"],
                    },
                }
                bulk_actions.append(update_action)

                if topics_info["topics_details"]:
                    labeled += 1

            if bulk_actions:
                from elasticsearch.helpers import bulk
                bulk(repo.client, bulk_actions)
                repo.client.indices.refresh(index=settings.es_index_name)

            processed += len(hits)
            print(f"  已处理 {processed}/{total_docs} 条数据...")

            results = repo.client.scroll(scroll_id=scroll_id, scroll="2m")
            scroll_id = results.get("_scroll_id")
    finally:
        if scroll_id:
            repo.client.clear_scroll(scroll_id=scroll_id)

    print(f"重新标注完成: {processed} 条数据, 有主题标签: {labeled} 条")

    # 主题分布（C2 §3.3：topics_details 为 nested，需 nested 聚合包裹）
    aggs = {
        "size": 0,
        "aggs": {
            "by_topic": {
                "nested": {"path": "topics_details"},
                "aggs": {"labels": {"terms": {"field": "topics_details.label_zh", "size": 20}}},
            }
        },
    }
    resp = repo.client.search(index=settings.es_index_name, body=aggs)
    print("\n主题分布 TOP20:")
    for bucket in resp["aggregations"]["by_topic"]["labels"]["buckets"]:
        print(f"  {bucket['key']}: {bucket['doc_count']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="医疗知识库入库脚本")
    parser.add_argument("--rebuild", "--clear", dest="rebuild", action="store_true",
                        help="清空主索引后重建（删索引 → 自动重建 → 全量灌入）")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有数据（不跳过重复）")
    parser.add_argument("--batch-size", type=int, default=32, help="批量写入大小")
    parser.add_argument("--precheck", action="store_true",
                        help="入库前强制执行 V-01 校验（scripts/data_pipeline/validate_data.py），不通过拒绝灌入")

    args = parser.parse_args()

    if args.precheck:
        import subprocess
        validator = Path(__file__).resolve().parent / "scripts" / "data_pipeline" / "validate_data.py"
        print("🚧 V-01 入库前置校验（--precheck）...")
        ret = subprocess.call([sys.executable, str(validator)])
        if ret != 0:
            print("❌ V-01 校验未通过，拒绝灌入（详见 data/reports/validation_*.json）")
            raise SystemExit(1)

    ingest_data(batch_size=args.batch_size, clear_index=args.rebuild, force=args.force)
