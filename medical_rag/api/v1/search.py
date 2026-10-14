from fastapi import APIRouter, Query
from typing import List, Optional
from models.schemas import APIResponse, SearchResult, DocumentMetadata, SimilarLawResponse, SimilarChunkResponse
from services.retriever_service import RetrieverService
from services.similar_law_service import SimilarLawService
from services.summary_service import SummaryService
from repositories.elasticsearch import ElasticsearchRepository
from utils.doc_catalog import DocCatalog
from core.domain_enums import CANCER_TYPE_INFO

router = APIRouter(prefix="/search", tags=["搜索"])
retriever = RetrieverService()
repo = ElasticsearchRepository()
similar_service = SimilarLawService()
summary_service = SummaryService()
catalog = DocCatalog()


def _csv_multi(value: Optional[str]):
    """逗号分隔的多值参数 → 单值字符串或列表（供 ES where 的单值/OR 语义使用）。"""
    if not value:
        return None
    items = [x.strip() for x in value.split(",") if x.strip()]
    if not items:
        return None
    return items[0] if len(items) == 1 else items


@router.get("")
@router.get("/")
def search(
    query: str = Query("", description="搜索关键词（为空时仅按筛选条件检索）"),
    top_k: int = Query(50, description="返回结果数量"),
    cancer_type: str = Query(None, description="癌种筛选（lung/breast/colorectal/gastric/thyroid）"),
    doc_type: str = Query(None, description="文档类型（guideline/standard/consensus）"),
    source: str = Query(None, description="来源机构（对应 issuer，如：中国抗癌协会）"),
    scenario: Optional[str] = Query(None, description="场景筛选（多选用逗号分隔，如：treatment_first_line,immunotherapy）"),
    stage: Optional[str] = Query(None, description="分期筛选（多选用逗号分隔，如：III,IV）"),
    biomarker: Optional[str] = Query(None, description="生物标志物筛选（多选用逗号分隔，如：EGFR,ALK）"),
    data_type: str = Query(None, description="条目类型（doc/rec/drug/term）"),
    topic: Optional[str] = Query(None, description="主题标签筛选（多选用逗号分隔，如：肺癌,一线治疗）"),
):
    # 组装过滤条件（键为 ES 字段名；多值按 OR）
    filters = {}
    if cancer_type:
        filters["cancer_type"] = cancer_type
    if doc_type:
        filters["doc_type"] = doc_type
    if source:
        filters["issuer"] = source
    if data_type:
        filters["data_type"] = data_type
    for field, value in (("scenario", scenario), ("stage", stage), ("biomarker", biomarker)):
        parsed = _csv_multi(value)
        if parsed:
            filters[field] = parsed
    topic_parsed = _csv_multi(topic)
    if topic_parsed:
        filters["topics_details.label_zh"] = topic_parsed

    results = retriever.hybrid_search(query, top_k, filters or None)

    search_results = []
    for result in results:
        # 结果 dict 由检索服务按 §5.7.2 白名单直供（BE-15）；统一 .get 防御取值。
        search_results.append(SearchResult(
            content=result.get('content', ''),
            metadata=DocumentMetadata(
                item_id=result.get('item_id', ''),
                data_type=result.get('data_type', ''),
                title=result.get('title', ''),
                cancer_type=result.get('cancer_type'),
                cancer_types=result.get('cancer_types', []),
                breadcrumb=result.get('breadcrumb'),
                scenario=result.get('scenario'),
                stage=result.get('stage') or [],
                stage_detail=result.get('stage_detail'),
                biomarker=result.get('biomarker') or [],
                evidence_level=result.get('evidence_level'),
                rec_strength=result.get('rec_strength'),
                chunk_index=result.get('chunk_index', 0),
                publish_date=result.get('publish_date'),
                source_file=result.get('file_path'),
            ),
            similarity=result.get('score', 0.0),
            retrieval_hop=result.get('retrieval_hop'),
            referenced_by=result.get('referenced_by'),
            cross_doc=result.get('cross_doc'),
            referenced_doc_id=result.get('referenced_doc_id'),
            referenced_doc_name=result.get('referenced_doc_name'),
            match_score=result.get('match_score'),
        ))

    return APIResponse(success=True, data=search_results)


@router.get("/docs")
def get_docs(
    doc_type: str = Query(None, description="文档类型筛选（guideline/standard/consensus）"),
    cancer_type: str = Query(None, description="癌种筛选（lung/breast/colorectal/gastric/thyroid）"),
    status: str = Query(None, description="状态筛选（active/superseded/deleted）"),
):
    """获取知识库文档列表

    以 DocCatalog (data/doc_catalog.json) 为权威数据源，返回已入库指南/规范/共识的元信息
    （doc_id / title / doc_type / issuer / cancer_types / item_count / version / publish_date …）。
    默认仅返回非删除状态。
    """
    docs = catalog.get_all_docs(doc_type=doc_type, cancer_type=cancer_type)
    if status:
        docs = [d for d in docs if d.get("status") == status]
    else:
        docs = [d for d in docs if d.get("status") != "deleted"]
    return APIResponse(success=True, data=docs)


@router.get("/doc/{doc_id}")
def get_doc(doc_id: str):
    """根据条目 ID（doc_id / rec_id / drug_id / term_id，即 ES _id）获取条目详情。"""
    item = repo.get(doc_id)
    if item is None:
        return APIResponse(success=False, message="条目不存在")
    return APIResponse(success=True, data=item)


@router.get("/cancer_types")
@router.get("/cancer_types/")
def get_cancer_types():
    """获取受控癌种列表（§5.7.3），供前端筛选下拉使用。

    返回格式: [{"code": "lung", "label_zh": "肺癌"}, ...]
    """
    data = [{"code": code, "label_zh": zh}
            for zh, (code, _range_code) in CANCER_TYPE_INFO.items()]
    return APIResponse(success=True, data=data)


@router.get("/topics")
@router.get("/topics/")
def get_topics():
    """获取所有主题标签及计数（医疗 taxonomy，用于筛选下拉框）

    返回格式: [{"id": "cancer_lung", "label_zh": "肺癌", "count": 42}, ...]
    """
    topics = repo.get_all_topics()
    return APIResponse(success=True, data=topics)


@router.get("/topics/simple")
@router.get("/topics/simple/")
def get_topics_simple():
    """获取简单主题标签列表（仅名称，用于轻量级场景）"""
    topics = repo.get_topic_filter_values()
    return APIResponse(success=True, data=topics)


@router.get("/law/{law_id}/similar")
def get_similar_laws(
    law_id: str,
    top_k: int = Query(5, ge=1, le=20, description="推荐数量（1-20）"),
    jurisdiction: str = Query(None, description="法域过滤（如：澳门/新加坡），不填则跨法域推荐")
):
    """
    相似法规推荐接口

    根据当前浏览的法规，推荐最相似的 Top-N 部法规。

    内部流程：
    1. 获取该法规所有 chunk 的向量，计算平均向量作为"核心语义"
    2. 用平均向量在 ES 中执行 KNN 相似搜索
    3. 排除自身，按 law_id 聚合去重
    4. 返回去重后的法规级推荐列表
    """
    result = similar_service.get_similar_laws(
        query_law_id=law_id,
        top_k=top_k,
        jurisdiction_filter=jurisdiction
    )
    return APIResponse(success=True, data=result)


@router.get("/chunk/{chunk_id}/similar")
def get_similar_chunks(
    chunk_id: str,
    top_k: int = Query(10, ge=1, le=30, description="推荐条款数量（1-30）"),
    jurisdiction: str = Query(None, description="法域过滤")
):
    """
    相似条款推荐接口

    根据当前浏览的某一条具体条款，推荐最相似的条款片段。
    直接使用该 chunk 的向量进行搜索，不做平均。
    """
    result = similar_service.get_similar_chunks(
        query_chunk_id=chunk_id,
        top_k=top_k,
        jurisdiction_filter=jurisdiction
    )
    return APIResponse(success=True, data=result)


@router.get("/doc/{doc_id}/summary")
def get_doc_summary(doc_id: str):
    """
    指南结构化速览接口（带缓存）

    根据指南 doc_id 生成结构化速览，帮助用户快速了解该指南的核心推荐。
    支持缓存：第二次访问直接读缓存；文档数据变化（指纹变化）时自动失效重生成。

    返回格式：
    {
      "basic_info": {"guide_name": "...", "issuer": "...", "doc_type": "...",
                     "cancer_types": [...], "publish_date": "...", "version": "...", "item_count": N},
      "overview": "指南概要",
      "key_recommendations": ["核心推荐要点1", ...],
      "evidence_notes": "证据特点",
      "keywords": {"core": [...], "cancers": [...], "scenarios": [...]},
      "from_cache": true/false
    }
    """
    try:
        summary = summary_service.generate_summary_with_cache(doc_id)
        return APIResponse(success=True, data=summary)
    except ValueError as e:
        return APIResponse(success=False, message=f"指南不存在：{str(e)}")
    except Exception as e:
        error_type = type(e).__name__
        error_detail = str(e)[:200]
        print(f"[摘要API错误] {error_type}: {error_detail}")
        if "timeout" in str(e).lower() or "timed out" in str(e).lower():
            return APIResponse(success=False, message="摘要生成超时，请稍后重试")
        elif "connection" in str(e).lower():
            return APIResponse(success=False, message="无法连接到AI服务")
        else:
            return APIResponse(success=False, message=f"生成摘要失败：{error_type}")


@router.get("/summary/cache/info")
def get_summary_cache_info():
    """
    获取摘要缓存统计信息

    返回缓存的总体状态，包括缓存条目数、有效条目数等。
    """
    from services.summary_cache import summary_cache
    info = summary_cache.get_cache_info()
    return APIResponse(success=True, data=info)


@router.delete("/summary/cache/{doc_id}")
def invalidate_summary_cache(doc_id: str):
    """
    清除指定指南的摘要缓存

    当文档数据发生变化时调用此接口，下次访问时将重新生成速览。

    Args:
        doc_id: 指南文档 ID（DOC）
    """
    from services.summary_cache import summary_cache
    summary_cache.invalidate(doc_id)
    return APIResponse(success=True, message=f"已清除指南 {doc_id} 的摘要缓存")


@router.delete("/summary/cache")
def invalidate_all_summary_cache():
    """
    清除所有指南摘要缓存

    适用于批量更新文档数据后，需要重新生成所有速览的场景。
    """
    from services.summary_cache import summary_cache
    summary_cache.invalidate_all()
    return APIResponse(success=True, message="已清除所有指南摘要缓存")
