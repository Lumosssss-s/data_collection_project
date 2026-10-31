"""语义缓存观测 API（只读）。

只暴露计数与配置，不提供任何清空/写入/预热入口，避免误操作把 30 条预热成果清掉。
统计口径见 SemanticCache.kinds_stats()：条目数一律按 entry 哈希 EXISTS 判定，
不用 idx/born/pinned 集合基数（它们不随 TTL 过期级联清理）。

同步 def：处理器内部是阻塞 Redis 调用，FastAPI 会放进线程池（与 api/v1/search.py 一致）。
"""
from fastapi import APIRouter

from models.schemas import APIResponse
from utils.semantic_cache import get_semantic_cache

router = APIRouter(prefix="/cache", tags=["语义缓存"])


@router.get("/stats")
def cache_stats():
    """缓存运行状态：命中计数、阈值、按 kind 的存活条目数 / pinned 数。"""
    return APIResponse(success=True, data=get_semantic_cache().stats())
