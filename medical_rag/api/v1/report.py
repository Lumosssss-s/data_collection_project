"""报告智能解析 API（NM-05，主方案 §6.6；P1 演示级）。

仅做报告**文本**解析：结构化字段 + 关键征象 + 循证随访建议 + 历次对比。
不做影像判读、不做 OCR。

路由声明为同步 def：处理器内部含阻塞调用（LLM 抽取、检索），FastAPI 会放进线程池。
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from models.schemas import APIResponse
from services.report_parse_service import ReportParseService

router = APIRouter(prefix="/report", tags=["报告智能解析"])
service = ReportParseService()

_logger = logging.getLogger(__name__)


class ParseRequest(BaseModel):
    text: str = Field(..., description="报告文本（不做 OCR，须为已提取的文本）")
    patient_id: str = Field(default="", description="患者 ID（可选；用于历次对比）")


@router.post("/parse")
def parse_report(req: ParseRequest):
    """解析报告文本，返回结构化字段 / 关键征象 / 随访建议 / 历次对比。"""
    res = service.parse(req.text, patient_id=req.patient_id)
    if not res.get("success"):
        return APIResponse(success=False, data=None, code=400,
                           message=res.get("message", "解析失败"))
    return APIResponse(success=True, data=res["report"])
