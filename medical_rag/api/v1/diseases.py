"""疾病知识库 API（NM-01，主方案 §6.7）。

以「疾病」为中心的知识库：
  - 名称归一检索 / 症状反查（`/diseases/search`）
  - 分类浏览 + 分面计数（`/diseases`）
  - 详情双版本切换（`/diseases/{disease_id}?version=pro|patient`）

路由声明顺序注意：`/diseases/search` 必须早于 `/diseases/{disease_id}`，
否则会被路径参数路由捕获（二者同为两段路径）。

以下路由刻意声明为同步 def：处理器内部是阻塞调用（ES 查询），FastAPI 会放进
线程池；写成 async def 会独占单进程事件循环。参见 api/v1/search.py。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query

from models.schemas import APIResponse
from services.disease_service import DiseaseService

router = APIRouter(prefix="/diseases", tags=["疾病知识库"])
service = DiseaseService()

_logger = logging.getLogger(__name__)


@router.get("/search")
def search_diseases(
    q: str = Query(..., description="检索词（疾病名或症状）"),
    mode: str = Query("name", description="name=名称检索 / symptom=症状反查"),
    size: int = Query(20, ge=1, le=50),
):
    """疾病检索：mode=name 名称归一检索；mode=symptom 症状反查。"""
    mode = "symptom" if mode == "symptom" else "name"
    data = service.search(q, mode=mode, size=size)
    return APIResponse(success=True, data=data)


@router.get("")
def browse_diseases(
    category: Optional[str] = Query(None, description="收录类别（§5.7.3 DiseaseCategory）"),
    cancer_type: Optional[str] = Query(None, description="癌种代码"),
    size: int = Query(200, ge=1, le=500),
):
    """分类浏览 / 分面计数。"""
    data = service.browse(category=category, cancer_type=cancer_type, size=size)
    return APIResponse(success=True, data=data)


@router.get("/{disease_id}")
def get_disease(
    disease_id: str,
    version: str = Query("pro", description="pro=专业版 / patient=患者版"),
):
    """疾病详情（双版本切换）。"""
    data = service.get(disease_id, version=version)
    if data is None:
        return APIResponse(success=False, data=None, code=404,
                           message="未找到该疾病（或疾病档案尚未入库）")
    return APIResponse(success=True, data=data)
