"""跨癌种专题分析 API（医疗，BE-09）

针对一个临床专题，分别检索两个癌种的推荐条目并聚合，由 LLM 生成跨癌种专题分析报告：
  - POST /topic-analysis            执行完整专题分析（检索 + 聚合 + LLM 报告）
  - POST /topic-analysis/follow-up  基于已生成报告追问

本文件的路由刻意声明为同步 def：处理器内部要跑完整分析流程（双癌种检索 + LLM 报告），
属阻塞调用。FastAPI 会把 def 路由放进线程池；若写成 async def，实测会导致事件
循环被独占约 20 秒，期间连 31ms 的统计接口都要等到分析结束才能返回。参见 api/v1/search.py。
"""
from fastapi import APIRouter, Body, Query

from models.schemas import APIResponse
from services.topic_analysis_service import TopicAnalysisService

router = APIRouter(prefix="/topic-analysis", tags=["跨癌种专题分析"])
analysis_service = TopicAnalysisService()


@router.post("")
def run_topic_analysis(
    query: str = Query(..., description="分析专题（如：PD-1 抑制剂的适应证与证据）"),
    cancer_type_a: str = Query(..., description="癌种A（代码或中文名，如 lung / 肺癌）"),
    cancer_type_b: str = Query(..., description="癌种B（代码或中文名，如 breast / 乳腺癌）"),
    top_n: int = Query(8, ge=3, le=20, description="每个癌种检索条目数（3-20）"),
):
    """
    跨癌种专题分析（完整流程，一步到位）

    三阶段流水线：
    1. 混合检索：分别对两个癌种执行检索，各取 Top-N 推荐条目
       （分开检索确保每个癌种都有足够素材，避免被另一个癌种"淹没"）
    2. 结果聚合：按 doc_id（指南）分组 → 拼接为指南级结构化文本
    3. LLM 专题报告：基于聚合后的两癌种推荐条目，从固定维度生成跨癌种分析报告
    """
    try:
        result = analysis_service.analyze(
            query=query,
            cancer_type_a=cancer_type_a,
            cancer_type_b=cancer_type_b,
            top_n_per_cancer=top_n,
        )
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, message=str(e))
    except Exception as e:
        return APIResponse(success=False, message=f"专题分析失败: {str(e)}")


@router.post("/follow-up")
def follow_up(
    original_analysis: dict = Body(..., description="原始分析结果"),
    follow_up_question: str = Query(..., description="用户追问问题"),
):
    """
    专题分析追问接口：基于已生成的分析报告，回答用户的后续问题。

    核心报告已经生成后，用户可以在此基础上继续追问，获得补充信息。
    """
    try:
        result = analysis_service.follow_up(
            original_analysis=original_analysis,
            follow_up_question=follow_up_question,
        )
        return APIResponse(success=True, data=result)
    except Exception as e:
        return APIResponse(success=False, message=f"追问失败: {str(e)}")
