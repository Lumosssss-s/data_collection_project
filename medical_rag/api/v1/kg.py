"""知识图谱 API（医疗，BE-12）

以「癌种」为中心的肿瘤知识图谱查询：
  - 癌种全景：某癌种相关实体与关系子图
  - 实体邻域：以某实体为中心的邻域子图
  - 实体搜索 / 实体词典浏览
  - 图谱抽取：按指南聚合其推荐条目，LLM 抽取三元组（带指纹缓存）

三元组来源为「推荐条目」（BE-12 KG-A），本体重定义见
services/kg_extraction_service.MEDICAL_ONTOLOGY（8 实体 + 9 关系）。

以下路由刻意声明为同步 def：处理器内部是阻塞调用（ES 查询、LLM 抽取），
FastAPI 会把 def 路由放进线程池；写成 async def 会让这些调用独占单进程的事件循环。
参见 api/v1/search.py。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from core.domain_enums import CANCER_TYPE_INFO, get_cancer_type_info
from models.schemas import APIResponse
from repositories.elasticsearch import ElasticsearchRepository
from services.entity_disambiguation_service import get_alias_statistics
from services.kg_extraction_service import (
    KGExtractionService, MEDICAL_ONTOLOGY, _ENTITY_COLORS, _ENTITY_SHAPES,
)

router = APIRouter(prefix="/kg", tags=["知识图谱"])
repo = ElasticsearchRepository()
# 抽取服务含 ES 客户端与 LLM 客户端，模块级单例复用，避免每请求重建连接
extractor = KGExtractionService()

_logger = logging.getLogger(__name__)

# 癌种代码 -> 标准中文名（用于构造癌种实体规范 ID）
_CODE_TO_NAME = {code: name for name, (code, _) in CANCER_TYPE_INFO.items()}


# ============================================================
#  元信息
# ============================================================

@router.get("/ontology")
def get_ontology():
    """返回医疗知识图谱本体（实体类型 + 关系类型），供前端图例与筛选使用。"""
    entities = [
        {
            "type": k,
            "label": v["label"],
            "description": v["description"],
            "color": _ENTITY_COLORS.get(k, "#6B7280"),
            "shape": _ENTITY_SHAPES.get(k, "ellipse"),
        }
        for k, v in MEDICAL_ONTOLOGY["entities"].items()
    ]
    return APIResponse(success=True, data={
        "entities": entities,
        "relations": MEDICAL_ONTOLOGY["relations"],
    })


@router.get("/statistics")
def get_kg_statistics():
    """知识层统计：三元组总数、已抽取指南数、实体总数。"""
    return APIResponse(success=True, data=repo.get_kg_statistics())


@router.get("/entities/aliases")
def get_alias_statistics_api():
    """别名表覆盖范围统计（消歧规则的规模）。"""
    return APIResponse(success=True, data=get_alias_statistics())


# ============================================================
#  实体词典浏览 / 搜索
# ============================================================

@router.get("/entities")
def list_entities(
    q: Optional[str] = Query(None, description="按规范名或别名模糊匹配"),
    entity_type: Optional[str] = Query(None, description="实体类型过滤（Cancer/Gene/Drug/…）"),
    page_size: int = Query(50, description="返回结果数", le=200),
):
    """列出实体词典条目（消歧后的规范实体，含别名与出现癌种）。"""
    return APIResponse(
        success=True,
        data=repo.list_kg_entities(q=q, entity_type=entity_type, page_size=page_size),
    )


@router.get("/entity/search")
def search_entities(
    q: str = Query(..., description="实体搜索关键词"),
    limit: int = Query(20, description="返回结果数", le=100),
):
    """按关键词搜索实体词典（规范名 / 别名模糊匹配）。"""
    entities = repo.list_kg_entities(q=q, page_size=limit)
    return APIResponse(success=True, data={"entities": entities, "count": len(entities)})


@router.get("/entity/{entity_id}")
def get_entity_neighborhood(entity_id: str):
    """实体邻域：返回实体详情 + 以该实体为中心的邻域子图。"""
    entity = repo.get_kg_entity(entity_id)
    triples = repo.get_kg_triples_by_entity(entity_id)
    if not entity and not triples:
        return APIResponse(success=False, message=f"未找到实体: {entity_id}")
    graph = extractor.format_graph(triples)
    return APIResponse(success=True, data={"entity": entity or {}, "graph": graph})


# ============================================================
#  癌种全景
# ============================================================

@router.get("/cancer/{cancer_type}")
def get_cancer_graph(cancer_type: str):
    """癌种全景：返回某癌种相关实体与关系子图（癌种代码或中文名均可）。"""
    try:
        code, _ = get_cancer_type_info(cancer_type)
    except ValueError as e:
        return APIResponse(success=False, message=str(e))

    name = _CODE_TO_NAME.get(code, cancer_type)
    entity_id = f"Cancer::{name}"
    triples = repo.get_kg_triples_by_entity(entity_id)
    graph = extractor.format_graph(triples)
    return APIResponse(success=True, data={
        "cancer_type": code,
        "cancer_name": name,
        "graph": graph,
    })


# ============================================================
#  图谱抽取（按指南）
# ============================================================

@router.get("/extract/{doc_id}")
def extract_doc_graph(
    doc_id: str,
    force_refresh: bool = Query(False, description="忽略缓存强制重新抽取（本体变更后使用）"),
):
    """
    对该指南进行实体关系抽取（返回三元组格式的知识图谱）。

    抽取输入为该指南下的推荐条目（REC）；结果持久化在 medical_kg_triples 索引中：
      - 命中缓存（指南指纹未变）时不调用 LLM，直接读 ES；
      - 指南更新后指纹变化，仅该指南自动重抽，其余指南不受影响。
    """
    recs = repo.get_doc_recs(doc_id)
    if not recs:
        return APIResponse(success=False, message="未找到该指南的推荐条目，无法抽取")

    result = extractor.get_triples_cached(doc_id, recs, force_refresh=force_refresh)
    graph = extractor.format_graph(result["triples"])
    graph["cache_hit"] = result["cache_hit"]
    return APIResponse(success=True, data=graph)
