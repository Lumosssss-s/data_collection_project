"""医疗检索分析平台 - API 层 Pydantic 数据模型

检索核心 DTO（DocumentMetadata / SearchResult / SearchRequest / QARequest）已按
医疗语义重写，字段对齐 C2《ES 索引与 Mapping 规范》§3.3 与主方案 §5.7.2 / §5.7.3。
对比 / 专题 / 相似推荐类 DTO 属 P4 批次特征重设计范围（BE-08 / BE-10 / BE-12 /
BE-29），暂按原状保留，随各服务重写统一处置。
"""
from pydantic import BaseModel
from typing import Generic, TypeVar, Optional, List, Dict

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


# ========== 法规对比相关模型 ==========

class CompareClauseItem(BaseModel):
    """对比中的单条条款"""
    law_id: str = ""
    title: str = ""
    article_number: Optional[str] = None
    content: str = ""
    similarity: float = 0.0
    jurisdiction: str = ""


class ComparisonRow(BaseModel):
    """并排对比的一行（法域A vs 法域B）"""
    index: int
    jurisdiction_a: Optional[CompareClauseItem] = None
    jurisdiction_b: Optional[CompareClauseItem] = None


class ScoreDistribution(BaseModel):
    """相似度分布数据点"""
    jurisdiction: str
    similarity: float


class ComparisonTableResult(BaseModel):
    """LLM生成的对比表格结果"""
    table_markdown: str = ""
    jurisdiction_a: str = ""
    jurisdiction_b: str = ""
    topic: str = ""
    timing: Dict[str, str] = {}
    error: Optional[str] = None


class ClausesComparisonResult(BaseModel):
    """条款检索对比结果"""
    comparison_rows: List[ComparisonRow] = []
    scores_distribution: List[ScoreDistribution] = []
    jurisdiction_a: str = ""
    jurisdiction_b: str = ""
    topic: str = ""
    count_a: int = 0
    count_b: int = 0
    timing: Dict[str, str] = {}


class AISummaryResult(BaseModel):
    """AI对比总结结果"""
    summary: str = ""
    sources: List[SearchResult] = []
    retrieved_count: int = 0
    timing: Dict[str, str] = {}
    error: Optional[str] = None


class FullCompareResponse(BaseModel):
    """完整对比分析响应（一步到位）"""
    jurisdiction_a: str
    jurisdiction_b: str
    topic: str
    comparison_table: ComparisonTableResult
    clauses_comparison: ClausesComparisonResult
    ai_summary: AISummaryResult
    timing: Dict[str, str] = {}


# ========== 跨法域专题分析相关模型 ==========

class AggregatedLaw(BaseModel):
    """聚合后的单部法规摘要"""
    law_id: str = ""
    title: str = ""
    article_numbers: List[str] = []
    chunk_count: int = 0
    max_similarity: float = 0.0


class RetrievalResult(BaseModel):
    """阶段一：原始检索结果统计"""
    chunks_a_count: int = 0
    chunks_b_count: int = 0
    top_n_per_jurisdiction: int = 8


class AggregatedResult(BaseModel):
    """阶段二：聚合后的法规级结果"""
    laws_a: List[AggregatedLaw] = []
    laws_b: List[AggregatedLaw] = []
    laws_a_count: int = 0
    laws_b_count: int = 0


class TopicAnalysisResponse(BaseModel):
    """
    跨法域专题分析完整响应

    三阶段流水线：
    阶段一：语义向量检索（分别搜索两个法域，各取 Top-N）
    阶段二：按法规聚合去重（law_id 分组 + chunk_index 排序 + 拼接）
    阶段三：LLM 生成结构化对比分析报告（5个固定维度）
    """
    query: str = ""
    jurisdiction_a: str = ""
    jurisdiction_b: str = ""
    retrieval: RetrievalResult = RetrievalResult()
    aggregated: AggregatedResult = AggregatedResult()
    analysis_report: str = ""
    timing: Dict[str, str] = {}
