"""医疗检索分析平台 - API 层 Pydantic 数据模型

检索核心 DTO（DocumentMetadata / SearchResult / SearchRequest / QARequest）已按
医疗语义重写，字段对齐 C2《ES 索引与 Mapping 规范》§3.3 与主方案 §5.7.2 / §5.7.3。
相似推荐类 DTO（SimilarGuide* / SimilarItem*）为 BE-28 医疗化产物；法规版对比 /
专题类 DTO 已随残留清理删除（对应服务已重写为医疗 schema）。
"""
from pydantic import BaseModel
from typing import Generic, TypeVar, Optional, List

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    message: str = ""
    code: int = 200


class DocumentMetadata(BaseModel):
    """检索结果元数据（doc / rec / drug / term 四类 knowledge 条目共用展示子集）

    与 C2 §3.3 主索引字段对应：
    - item_id   = 各类型主 ID（doc_id / rec_id / drug_id / term_id），等于 ES _id
    - data_type = 条目类型（doc / rec / drug / term），前端据此路由详情页
    缺失字段按 G8 语义以 None / 空列表表达，不使用占位符。
    """
    item_id: str = ""
    data_type: str = ""
    title: str = ""
    cancer_type: Optional[str] = None       # 单值癌种（rec / drug）
    cancer_types: List[str] = []            # 多值癌种（doc）
    breadcrumb: Optional[str] = None        # 指南章 / 节层级，如「第三部分/3.2 早期治疗」
    scenario: Optional[str] = None          # 场景枚举（rec，§5.7.3）
    stage: List[str] = []                   # 分期枚举（rec）
    stage_detail: Optional[str] = None      # 细分期，如 T2N1M0
    biomarker: List[str] = []               # 生物标志物枚举（rec）
    evidence_level: Optional[str] = None    # 证据等级（rec）
    rec_strength: Optional[str] = None      # 推荐强度（rec）
    chunk_index: int = 0                    # 分块序号（仅 drug 说明书分块生效，其余 = 0）
    publish_date: Optional[str] = None      # YYYY-MM-DD（G7）
    source_file: Optional[str] = None       # 原始文件名（溯源）


class SearchResult(BaseModel):
    content: str
    metadata: DocumentMetadata
    similarity: float
    # 引用链多跳扩展标记（对应主方案「指南推荐条目交叉引用 / 参考文献追溯」）：
    # retrieval_hop=2 表示该条由引用链补入，不是语义命中，此时 similarity 无意义，
    # 前端应据此标注「由 <referenced_by> 引用」。跨文档引用额外携带 cross_doc /
    # referenced_doc_*，使前端能区分「同指南引用」与「引用自另一份指南」，
    # 避免把来源条号误读成本条号。
    retrieval_hop: Optional[int] = None
    referenced_by: Optional[str] = None
    cross_doc: Optional[bool] = None
    referenced_doc_id: Optional[str] = None
    referenced_doc_name: Optional[str] = None
    # 展示用「匹配度」= 真实向量余弦相似度（0~1）。None 表示该条无余弦分
    # （仅 BM25 命中或引用扩展补入），前端此时不显示百分比，避免误示 0%/50%。
    match_score: Optional[float] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    cancer_type: Optional[str] = None      # 癌种筛选（§5.7.3）


class QARequest(BaseModel):
    question: str
    top_k: int = 5
    cancer_types: Optional[List[str]] = None   # 多癌种筛选（§5.7.3）


class QAAnswer(BaseModel):
    answer: str
    sources: List[SearchResult]
    retrieved_count: int


class DocumentCreate(BaseModel):
    content: str
    metadata: DocumentMetadata


class DocumentUpdate(BaseModel):
    content: Optional[str] = None
    metadata: Optional[DocumentMetadata] = None


class MatchedChunk(BaseModel):
    """匹配到的推荐条目片段"""
    breadcrumb: Optional[str] = None
    content_preview: str = ""
    similarity: float = 0.0


class SimilarGuideItem(BaseModel):
    """相似指南条目"""
    doc_id: str
    title: str
    cancer_type: str
    similarity: float
    composite_score: float = 0.0
    topic_overlap: float = 0.0
    match_item_count: int = 0
    shared_topics: List[str] = []
    top_matched_items: List[MatchedChunk] = []


class SimilarGuideResponse(BaseModel):
    """相似指南推荐响应"""
    query_doc_id: str
    query_title: Optional[str] = ""
    query_cancer_type: Optional[str] = ""
    query_item_count: int = 0
    query_topics: List[str] = []
    similar_guides: List[SimilarGuideItem] = []
    total_found: int = 0
    returned_count: int = 0
    message: str = ""


class SimilarItemItem(BaseModel):
    """相似推荐条目"""
    item_id: str
    doc_id: str
    rec_id: str = ""
    title: str
    cancer_type: str
    breadcrumb: Optional[str] = None
    content_preview: str = ""
    similarity: float = 0.0


class SimilarItemResponse(BaseModel):
    """相似条目推荐响应"""
    query_item_id: str
    query_content: str = ""
    query_breadcrumb: Optional[str] = None
    query_doc_id: str = ""
    similar_items: List[SimilarItemItem] = []
    total_found: int = 0
    returned_count: int = 0
    message: str = ""

