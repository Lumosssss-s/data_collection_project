"""文档摘要缓存服务（基于 Elasticsearch）

功能：
1. 缓存指南文档的结构化摘要，减少重复生成
2. 使用指纹（doc_hash + 正文长度）检测文档数据变化，数据不变时直接返回缓存
3. 无过期时间，仅在数据变化时失效
4. 支持缓存清除

缓存键为 doc_id（DOC 的 ES _id）；底层落在 medical_analysis_cache（cache_type=summary）。
"""
from typing import Dict, Optional
from repositories.elasticsearch import ElasticsearchRepository

# 摘要采样器版本：v2 改为「按章节分层采样」。
# 版本不一致时旧缓存（基于残缺正文生成）失效，避免继续返回覆盖不完整的速览。
SAMPLER_VERSION = 2


class SummaryCache:
    def __init__(self):
        self._repo = ElasticsearchRepository()

    def get(self, doc_id: str) -> Optional[Dict]:
        """从缓存获取摘要；不存在、文档已变化或采样器版本不符时返回 None。"""
        cached = self._repo.get_summary_cache(doc_id)
        if cached and cached.get("sampler_version") != SAMPLER_VERSION:
            return None
        return cached

    def set(self, doc_id: str, summary: Dict):
        """将摘要存入缓存（写入当前采样器版本）。"""
        summary = dict(summary)
        summary["sampler_version"] = SAMPLER_VERSION
        self._repo.save_summary_cache(doc_id, summary)

    def invalidate(self, doc_id: str):
        """清除指定文档的摘要缓存。"""
        self._repo.delete_summary_cache(doc_id)

    def invalidate_all(self):
        """清除所有摘要缓存。"""
        self._repo.delete_all_summary_cache()

    def get_cache_info(self) -> Dict:
        """获取缓存统计信息"""
        try:
            cached = self._repo.get_analysis_cache("__all__", "", "", cache_type="summary")
            total_entries = len(cached) if isinstance(cached, list) else 0
            return {
                "total_entries": total_entries,
                "valid_entries": total_entries,
                "expired_entries": 0,
                "expire_seconds": None,
                "cache_type": "elasticsearch"
            }
        except Exception:
            return {
                "total_entries": 0,
                "valid_entries": 0,
                "expired_entries": 0,
                "expire_seconds": None,
                "cache_type": "elasticsearch"
            }

    def get_cached_doc_ids(self) -> list:
        """获取所有已缓存的文档 ID 列表（缓存记录的实体键存于 topic_id 字段）"""
        try:
            cached = self._repo.get_analysis_cache("__all__", "", "", cache_type="summary")
            if isinstance(cached, list):
                return [item.get("topic_id", "") for item in cached if item.get("topic_id")]
        except Exception:
            pass
        return []


summary_cache = SummaryCache()
