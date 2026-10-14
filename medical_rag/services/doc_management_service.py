"""知识库文档管理服务（医疗，BE-13 + BE-25）

按业务 ID 管理 medical_knowledge（主索引）中的条目：doc / rec / drug / term。
与 ingest.py（BE-37）的入库契约一致——**一条记录 = 一个检索单元，不做切分**
（切分/条目化归 chunker BE-34 与入库脚本，管理端只负责单条 CRUD）。

职责：
    - 新增 / 更新：按 §5.7.2 白名单落库（由 repositories.add_documents 统一裁剪）
    - 删除：按 ES _id 删除，doc 类型同步目录
    - 目录：doc_catalog.json（DocCatalog）为权威，仅在 doc 类型增删/同步时维护

设计说明：
    - 不再使用「法规 JSON 文件夹 + chunk_from_structure」旧模型；
    - 正文抽取复用 ingest.py 的 _extract_content / _default_title（单一事实源），
      避免同一套「按类型取正文」逻辑在两处漂移；
    - 摘要生成按医疗流程单独批处理（run_abstracts.py / BE-38），管理端创建时不自动生成。
"""
import logging
from typing import Dict, List, Optional

from repositories.elasticsearch import ElasticsearchRepository
from utils.doc_catalog import DocCatalog
# 复用入库脚本的按类型取正文逻辑（医疗入库契约的单一事实源）
from ingest import _extract_content, _default_title

logger = logging.getLogger(__name__)

# 可管理的条目类型（C2 §3.3：主索引四类 data_type）
VALID_DATA_TYPES = ("doc", "rec", "drug", "term")

# 各类型业务 ID 字段（= ES _id）
ID_FIELD: Dict[str, str] = {
    "doc": "doc_id", "rec": "rec_id", "drug": "drug_id", "term": "term_id",
}


class DocManagementService:
    """知识库条目管理服务（新增 / 更新 / 删除 / 查询 / 目录同步）"""

    def __init__(self):
        self.repo = ElasticsearchRepository()
        self.catalog = DocCatalog()

    # ===== 内部工具 =====

    @staticmethod
    def _validate(data_type: str, record: Dict) -> str:
        """校验 data_type 与业务 ID，返回业务 ID。"""
        data_type = (data_type or "").strip()
        if data_type not in VALID_DATA_TYPES:
            raise ValueError(
                f"非法 data_type：{data_type!r}（合法值：{', '.join(VALID_DATA_TYPES)}）"
            )
        if not isinstance(record, dict):
            raise ValueError("record 必须为对象")
        id_field = ID_FIELD[data_type]
        item_id = str(record.get(id_field) or "").strip()
        if not item_id:
            raise ValueError(f"记录缺少业务 ID 字段 {id_field}")
        return item_id

    @staticmethod
    def _build_content_and_meta(data_type: str, record: Dict, item_id: str):
        """按类型抽取正文并补齐 title（正文抽取与入库脚本同源）。"""
        content = _extract_content(data_type, record) or item_id
        meta = dict(record)
        meta["data_type"] = data_type
        if not meta.get("title"):
            meta["title"] = _default_title(data_type, record)
        return content, meta

    def _sync_doc_catalog(self, doc_id: str, meta: Dict) -> None:
        """把 DOC 记录同步进 doc_catalog.json（目录以 doc_id 为唯一键）。"""
        try:
            self.catalog.add_or_update(
                doc_id=doc_id,
                title=meta.get("title", ""),
                doc_type=meta.get("doc_type", ""),
                issuer=meta.get("issuer", ""),
                cancer_types=meta.get("cancer_types") or [],
                item_count=meta.get("item_count", 0),
                version=meta.get("version", ""),
                publish_date=meta.get("publish_date", ""),
                file_path=meta.get("file_path", ""),
                status="active",
            )
        except Exception as e:
            logger.warning(f"[DocMgmt] 同步目录失败（不影响入库）: doc_id={doc_id}, {e}")

    # ===== 增 / 改 / 删 / 查 =====

    def create_item(self, data_type: str, record: Dict) -> Dict:
        """新增（或按业务 ID 覆盖）一个条目。"""
        item_id = self._validate(data_type, record)
        content, meta = self._build_content_and_meta(data_type, record, item_id)

        self.repo.add_documents([content], [meta], [item_id])

        if data_type == "doc":
            self._sync_doc_catalog(item_id, meta)

        return {
            "item_id": item_id,
            "data_type": data_type,
            "message": "条目已入库",
        }

    def update_item(self, item_id: str, updates: Dict, data_type: Optional[str] = None) -> Dict:
        """更新条目：与现有记录合并后按业务 ID 覆盖写回。"""
        existing = self.repo.get(item_id)
        if not existing:
            raise FileNotFoundError(f"条目不存在: {item_id}")

        dt = data_type or existing.get("data_type") or "rec"
        if dt not in VALID_DATA_TYPES:
            raise ValueError(f"无法确定 data_type（原记录或参数均非法）：{dt!r}")

        merged = {**existing, **(updates or {})}
        merged[ID_FIELD[dt]] = item_id  # 业务 ID 不可被 updates 改写

        result = self.create_item(dt, merged)
        result["message"] = "条目已更新"
        return result

    def delete_item(self, item_id: str) -> Dict:
        """删除条目（doc 类型同时标记目录删除）。"""
        existing = self.repo.get(item_id)
        if not existing:
            raise FileNotFoundError(f"条目不存在: {item_id}")

        deleted = self.repo.delete_item(item_id)
        if existing.get("data_type") == "doc":
            try:
                self.catalog.delete(item_id)
            except Exception as e:
                logger.warning(f"[DocMgmt] 标记目录删除失败: doc_id={item_id}, {e}")

        return {"item_id": item_id, "deleted": deleted, "message": "条目已删除"}

    def get_item(self, item_id: str) -> Optional[Dict]:
        """读取条目详情（不存在返回 None）。"""
        return self.repo.get(item_id)

    def list_items(
        self,
        data_type: Optional[str] = None,
        cancer_type: Optional[str] = None,
        page_size: int = 100,
    ) -> List[Dict]:
        """按类型 / 癌种列出条目（走 ES，返回 §5.7.2 白名单字段）。"""
        return self.repo.list_items(
            data_type=data_type, cancer_type=cancer_type, page_size=page_size
        )

    def list_docs(
        self,
        doc_type: Optional[str] = None,
        cancer_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """列出指南文档目录（doc_catalog.json 为权威，供管理端文档列表）。"""
        return self.catalog.get_all_docs(
            doc_type=doc_type, cancer_type=cancer_type, status=status
        )

    def sync_catalog(self) -> Dict:
        """从 ES 重建 doc_catalog.json（修复目录与索引不一致）。"""
        return self.catalog.rebuild_from_es(self.repo)
