"""患者端 API（NM-06，主方案 §4.2 方案 A，移动优先）。

患者端页面组后端支撑：
  - 用药指导：`/patient/drugs`（列表/搜索）、`/patient/drug/{drug_id}`（说明书患者版）

其余患者端页面前端直接复用既有端点，无需在此重复：
  - 疾病科普 → `GET /diseases/{id}?version=patient`
  - 患者预问诊 → `/preconsult/*`
  - 随访反馈 → `/followup/*`

**强制约束**：不给诊断结论、不给处方；输出均附免责声明与就医指引。

路由声明为同步 def：处理器内部含阻塞调用（LLM 改写、ES 查询），FastAPI 会放进线程池。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from models.schemas import APIResponse
from services.patient_service import PatientService

router = APIRouter(prefix="/patient", tags=["患者端"])
service = PatientService()

_logger = logging.getLogger(__name__)


@router.get("/drugs")
def list_drugs(
    q: str = Query("", description="按药品通用名 / 商品名搜索"),
    cancer_type: Optional[str] = Query(None, description="癌种代码（可选）"),
):
    """药品列表 / 搜索（患者端用药指导入口）。"""
    return APIResponse(success=True, data=service.list_drugs(q, cancer_type or ""))


@router.get("/drug/{drug_id}")
def get_drug(drug_id: str):
    """药品说明书结构化详情（零 LLM）：通用名/适应证/限定/黑框/警示/剂量/禁忌/
    不良反应/相互作用原文/免责。白话解读请用 /drug/{drug_id}/plain。"""
    data = service.get_drug_patient(drug_id)
    if data is None:
        return APIResponse(success=False, data=None, code=404,
                           message="未找到该药品（或说明书尚未入库）")
    return APIResponse(success=True, data=data)


@router.get("/drug/{drug_id}/plain")
def get_drug_plain(drug_id: str):
    """药品说明书白话解读（LLM 生成，ES 缓存：命中即返 cached=true）。

    生成失败返回 plain=null（前端降级为结构化要点展示），不 5xx。
    """
    data = service.get_drug_plain(drug_id)
    if data is None:
        return APIResponse(success=False, data=None, code=404,
                           message="未找到该药品（或说明书尚未入库）")
    return APIResponse(success=True, data=data)
