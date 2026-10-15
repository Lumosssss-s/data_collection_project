"""智能随访 API（NM-03，主方案 §6.3）。

随访计划生成 → 任务下发/反馈 → CTCAE 分级与异常预警。

路由声明为同步 def：处理器内部含阻塞调用（LLM 分级），FastAPI 会放进线程池。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from models.schemas import APIResponse
from services.followup_service import FollowUpService

router = APIRouter(prefix="/followup", tags=["智能随访"])
service = FollowUpService()

_logger = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    case_id: str = Field(..., description="随访病例 ID")
    cancer_type: str = Field(..., description="癌种代码（§5.7.3）")
    phase: str = Field(..., description="阶段：postoperative / on_treatment / rehabilitation / survivorship")
    stage: Optional[List[str]] = Field(default=None, description="适用分期（可选）")
    patient_id: str = Field(default="", description="患者 ID（可选）")


class RecordRequest(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    responses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="反馈项：[{term, grade?, severity?, text?}]，grade 缺省时按严重度/文本/LLM 判定")


@router.get("/readiness")
def readiness():
    """随访数据就绪状态（B4 模板 / B5 消息）。"""
    return APIResponse(success=True, data=service.data_readiness())


@router.post("/plan")
def create_plan(req: PlanRequest):
    """生成随访计划（模板驱动）。"""
    data = service.create_plan(req.case_id, req.cancer_type, req.phase,
                               stage=req.stage, patient_id=req.patient_id)
    return APIResponse(success=True, data=data)


@router.get("/tasks")
def list_tasks(patient_id: Optional[str] = Query(None),
               case_id: Optional[str] = Query(None)):
    """任务列表（标出到期 / 待反馈）。"""
    return APIResponse(success=True, data=service.list_tasks(patient_id=patient_id, case_id=case_id))


@router.post("/record")
def record(req: RecordRequest):
    """提交反馈：CTCAE 分级 + 预警标记（≥3 级）。"""
    data = service.record(req.task_id, req.responses)
    if data is None:
        return APIResponse(success=False, data=None, code=404, message="任务不存在")
    return APIResponse(success=True, data=data)


@router.get("/alerts")
def list_alerts(patient_id: Optional[str] = Query(None)):
    """异常预警列表。"""
    return APIResponse(success=True, data=service.list_alerts(patient_id=patient_id))


@router.get("/compliance")
def compliance():
    """依从性粗统计（供运营看板参考）。"""
    return APIResponse(success=True, data=service.compliance_summary())
