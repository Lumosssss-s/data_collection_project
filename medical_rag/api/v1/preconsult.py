"""智能预问诊 API（NM-02，主方案 §6.1）。

多轮症状采集 → 红旗征识别 → 风险分层 → 科室建议 → 就诊准备清单。

安全约束：红旗征**宁高敏感**；输出**不给诊断结论**（仅风险提示与就医方向）。

路由声明为同步 def：处理器内部含阻塞调用（LLM 抽取），FastAPI 会放进线程池。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from models.schemas import APIResponse
from services.preconsult_service import PreconsultService

router = APIRouter(prefix="/preconsult", tags=["智能预问诊"])
service = PreconsultService()

_logger = logging.getLogger(__name__)


class SessionRequest(BaseModel):
    """创建会话请求：可选患者基本信息（如 age / sex）。"""
    patient_info: Optional[Dict[str, Any]] = Field(default=None)


class MessageRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID")
    text: str = Field(..., description="患者本轮描述")


@router.get("/readiness")
def readiness():
    """预问诊数据就绪状态（B1 红旗征 / B2 槽位 / B3 分诊映射）。"""
    return APIResponse(success=True, data=service.data_readiness())


@router.post("/session")
def create_session(req: SessionRequest):
    """创建预问诊会话，返回 session_id 与首个问题。"""
    data = service.create_session(patient_info=req.patient_info)
    return APIResponse(success=True, data=data)


@router.post("/message")
def post_message(req: MessageRequest):
    """提交一轮患者描述，返回槽位更新 / 下一问 / 红旗征 / 风险分层 / 科室建议。"""
    data = service.handle_message(req.session_id, req.text)
    if data is None:
        return APIResponse(success=False, data=None, code=404,
                           message="会话不存在或已过期")
    return APIResponse(success=True, data=data)


@router.get("/result/{session_id}")
def get_result(session_id: str):
    """预问诊摘要报告（供医生 30 秒速览）。"""
    data = service.get_result(session_id)
    if data is None:
        return APIResponse(success=False, data=None, code=404,
                           message="会话不存在或已过期")
    return APIResponse(success=True, data=data)
