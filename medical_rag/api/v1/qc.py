"""病历质控 API（NM-04，主方案 §6.4）。

规则引擎（内置高确定性检查）+ B6 规则判定（LLM）→ 评分与问题清单。

路由声明为同步 def：处理器内部含阻塞调用（LLM 判定），FastAPI 会放进线程池。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from models.schemas import APIResponse
from services.qc_service import QCService

router = APIRouter(prefix="/qc", tags=["病历质控"])
service = QCService()

_logger = logging.getLogger(__name__)


class ReviewRequest(BaseModel):
    record_text: str = Field(..., description="病历文本")
    patient_id: str = Field(default="", description="患者/病历 ID（可选）")


@router.get("/readiness")
def readiness():
    """质控数据就绪状态（B6 质控规则）。"""
    return APIResponse(success=True, data=service.data_readiness())


@router.get("/rules")
def list_rules(category: Optional[str] = Query(None, description="按四类过滤（可选）")):
    """质控规则目录（B6）。"""
    return APIResponse(success=True, data=service.list_rules(category=category))


@router.post("/review")
def review(req: ReviewRequest):
    """提交病历质控审查，返回评分与问题清单。"""
    res = service.review(req.record_text, patient_id=req.patient_id)
    if not res.get("success"):
        return APIResponse(success=False, data=None, code=400,
                           message=res.get("message", "审查失败"))
    return APIResponse(success=True, data=res["report"])


@router.get("/report/{review_id}")
def get_report(review_id: str):
    """历史质控报告。"""
    data = service.get_report(review_id)
    if data is None:
        return APIResponse(success=False, data=None, code=404, message="报告不存在或已过期")
    return APIResponse(success=True, data=data)
