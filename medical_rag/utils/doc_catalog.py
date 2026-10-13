"""
文档目录管理模块 (doc_catalog.json)

功能：
- 维护文档级别的元信息索引文件（指南 / 规范 / 共识）
- 支持新增、更新、查询文档目录记录
- 与 ES 数据保持同步

数据结构（记录口径对齐 C2 主索引 DOC 域 / C4 文档目录口径）：
{
  "version": "1.0",
  "last_updated": "2026-10-13T10:00:00",
  "total_docs": 1,
  "docs": [
    {
      "doc_id": "DOC-LUNG-CACA-2025",
      "title": "CACA 肺癌诊疗指南（2025 版）",
      "doc_type": "guideline",
      "issuer": "中国抗癌协会",
      "cancer_types": ["lung"],
      "item_count": 128,
      "version": "2025",
      "publish_date": "2025-01-01",
      "file_path": "data/clean/guidelines/DOC-LUNG-CACA-2025.json",
      "status": "active",
      "ingest_date": "2026-10-13",
      "last_updated": "2026-10-13"
    }
  ]
}
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any


class DocCatalog:
    """文档目录管理器（记录口径：C2 DOC 域）"""

    def __init__(self, catalog_path: str = None):
        """
        初始化目录管理器

        参数:
            catalog_path: catalog 文件路径，默认为 data/doc_catalog.json
        """
        if catalog_path:
            self.catalog_path = Path(catalog_path)
        else:
            # 默认路径：与 data 目录同级
            self.catalog_path = Path(__file__).parent.parent / "data" / "doc_catalog.json"

        self._ensure_catalog_exists()

    def _ensure_catalog_exists(self):
        """确保 catalog 文件存在"""
        if not self.catalog_path.exists():
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self._write({
                "version": "1.0",
                "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "total_docs": 0,
                "docs": []
            })

    def _write(self, data: Dict):
        """落盘（内部工具，不重算统计）"""
        with open(self.catalog_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> Dict:
        """加载 catalog 数据"""
        try:
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  加载 doc_catalog.json 失败: {e}")
            return {"version": "1.0", "last_updated": "", "total_docs": 0, "docs": []}

    def save(self, data: Dict):
        """保存 catalog 数据（自动刷新 last_updated 与 total_docs）"""
        data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        data["total_docs"] = len(data.get("docs", []))
        self._write(data)

    def find_by_doc_id(self, doc_id: str) -> Optional[Dict]:
        """根据 doc_id 查找文档记录"""
        catalog = self.load()
        for doc in catalog.get("docs", []):
            if doc.get("doc_id") == doc_id:
                return doc
        return None

    def add_or_update(
        self,
        doc_id: str,
        title: str,
        doc_type: str = "",
        issuer: str = "",
        cancer_types: List[str] = None,
        item_count: int = 0,
        version: str = "",
        publish_date: str = "",
        file_path: str = "",
        status: str = "active",
    ) -> Dict:
        """
        新增或更新文档目录记录

        参数:
            doc_id: 文档 ID（指南 / 规范 / 共识）
            title: 文档标题
            doc_type: 文档类型（guideline / standard / consensus）
            issuer: 发布机构
            cancer_types: 适用癌种数组（lung / breast / colorectal / gastric / thyroid）
            item_count: 该文档切分出的推荐条目数
            version: 文档版本（如 2025）
            publish_date: 发布日期
            file_path: 源文件相对路径
            status: 状态（active / superseded / deleted）

        返回:
            更新后的文档记录
        """
        catalog = self.load()
        now = datetime.now().strftime("%Y-%m-%d")

        existing_record = self.find_by_doc_id(doc_id)

        new_record = {
            "doc_id": doc_id,
            "title": title,
            "doc_type": doc_type,
            "issuer": issuer,
            "cancer_types": cancer_types or [],
            "item_count": item_count,
            "version": version,
            "publish_date": publish_date,
            "file_path": file_path,
            "ingest_date": now,
            "last_updated": now,
            "status": status,
        }

        if existing_record:
            index = next(i for i, d in enumerate(catalog["docs"]) if d.get("doc_id") == doc_id)

            # 状态变化（如 active → superseded）时保留旧版本快照，便于版本追溯
            if existing_record.get("status") != status and status != "deleted":
                if "previous_versions" not in existing_record:
                    existing_record["previous_versions"] = []

                existing_record["previous_versions"].append({
                    "version_date": existing_record.get("last_updated", ""),
                    "status": existing_record.get("status"),
                    "item_count": existing_record.get("item_count", 0),
                })

            # 合并新数据：首次入库日期不变
            new_record["ingest_date"] = existing_record.get("ingest_date", now)
            catalog["docs"][index] = new_record

            print(f"📝 更新 catalog 记录: {doc_id} ({title})")
        else:
            catalog["docs"].append(new_record)
            print(f"➕ 新增 catalog 记录: {doc_id} ({title})")

        self.save(catalog)
        return new_record

    def update_from_docs(self, docs_data: List[Dict]) -> Dict:
        """
        从同一文档的条目数据中提取元信息并更新 catalog

        参数:
            docs_data: 同一文档的条目列表（入库时该文档下的 chunk / 条目记录）

        返回:
            更新后的文档记录
        """
        if not docs_data:
            return {}

        first = docs_data[0]
        meta = first.get("metadata", {}) or {}
        inner = first.get("_meta", {}) or {}

        return self.add_or_update(
            doc_id=inner.get("doc_id") or meta.get("doc_id") or first.get("doc_id", ""),
            title=inner.get("title") or meta.get("title", ""),
            doc_type=meta.get("doc_type", ""),
            issuer=meta.get("issuer", ""),
            cancer_types=meta.get("cancer_types", []) or [],
            item_count=len(docs_data),
            version=meta.get("version", ""),
            publish_date=meta.get("publish_date", ""),
            file_path=meta.get("file_path", ""),
            status="active",
        )

    def delete(self, doc_id: str) -> bool:
        """
        标记删除文档记录

        参数:
            doc_id: 要删除的文档 ID

        返回:
            是否成功标记删除
        """
        catalog = self.load()

        # 标记为 deleted 而非物理删除（便于审计）
        for i, doc in enumerate(catalog.get("docs", [])):
            if doc.get("doc_id") == doc_id:
                catalog["docs"][i]["status"] = "deleted"
                catalog["docs"][i]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
                print(f"🗑️  标记删除 catalog 记录: {doc_id}")
                self.save(catalog)
                return True

        print(f"⚠️  未找到 catalog 记录: {doc_id}")
        return False

    def get_all_docs(
        self,
        doc_type: str = None,
        cancer_type: str = None,
        status: str = None,
    ) -> List[Dict]:
        """
        获取所有文档记录（支持筛选）

        参数:
            doc_type: 文档类型筛选（可选：guideline / standard / consensus）
            cancer_type: 癌种筛选（可选，命中 cancer_types 数组即算匹配）
            status: 状态筛选（可选）

        返回:
            文档记录列表
        """
        catalog = self.load()
        docs = catalog.get("docs", [])

        if doc_type:
            docs = [d for d in docs if d.get("doc_type") == doc_type]

        if cancer_type:
            docs = [d for d in docs if cancer_type in (d.get("cancer_types") or [])]

        if status:
            docs = [d for d in docs if d.get("status") == status]

        return docs

    def get_statistics(self) -> Dict:
        """
        获取统计信息

        返回:
            包含文档总数、类型分布、癌种覆盖、状态分布、年份分布、条目总数的字典
        """
        catalog = self.load()
        docs = [d for d in catalog.get("docs", []) if d.get("status") != "deleted"]

        stats = {
            "total_docs": len(docs),
            "total_items": sum(d.get("item_count", 0) for d in docs),
            "by_doc_type": {},
            "by_cancer_type": {},
            "by_status": {},
            "by_year": {},
        }

        for doc in docs:
            dtype = doc.get("doc_type", "未知")
            stats["by_doc_type"][dtype] = stats["by_doc_type"].get(dtype, 0) + 1

            for ct in doc.get("cancer_types") or []:
                stats["by_cancer_type"][ct] = stats["by_cancer_type"].get(ct, 0) + 1

            status_val = doc.get("status", "未知")
            stats["by_status"][status_val] = stats["by_status"].get(status_val, 0) + 1

            year = doc.get("publish_date", "")[:4] if doc.get("publish_date") else "未知"
            stats["by_year"][year] = stats["by_year"].get(year, 0) + 1

        return stats

    def rebuild_from_es(self, es_repo) -> Dict:
        """
        从 ES 重建 catalog（用于修复损坏或丢失的 catalog）

        参数:
            es_repo: ElasticsearchRepository 实例

        返回:
            重建后的统计数据

        说明:
            仓库层方法名（get_all_laws / get_law_by_id）为法规遗留命名，其医疗化
            归 BE-31 / BE-06 批次（涉及 D-03 冻结文件，本批次不改名）。此处仅按
            C2 DOC 域字段读取，仓库层未同步前 doc_type / issuer 等字段为空。
        """
        print("🔄 开始从 ES 重建 doc_catalog.json...")

        all_docs = es_repo.get_all_laws()
        catalog = {"version": "1.0", "last_updated": "", "total_docs": 0, "docs": []}
        now = datetime.now().strftime("%Y-%m-%d")

        for doc_info in all_docs:
            doc_id = doc_info.get("doc_id")
            if not doc_id:
                continue

            doc_detail = es_repo.get_law_by_id(doc_id) or {}
            catalog["docs"].append({
                "doc_id": doc_id,
                "title": doc_detail.get("title", "") or doc_info.get("title", ""),
                "doc_type": doc_info.get("doc_type", ""),
                "issuer": doc_info.get("issuer", ""),
                "cancer_types": doc_info.get("cancer_types", []) or [],
                "item_count": doc_info.get("item_count", 0),
                "version": doc_info.get("version", ""),
                "publish_date": doc_info.get("publish_date", ""),
                "file_path": "",
                "ingest_date": now,
                "last_updated": now,
                "status": "active",
            })

        self.save(catalog)
        stats = self.get_statistics()

        print("✅ Catalog 重建完成:")
        print(f"   - 总文档数: {stats['total_docs']}")
        print(f"   - 总条目数: {stats['total_items']}")

        return stats


# 全局单例实例
_catalog_instance = None

def get_catalog() -> DocCatalog:
    """获取全局 catalog 实例"""
    global _catalog_instance
    if _catalog_instance is None:
        _catalog_instance = DocCatalog()
    return _catalog_instance
