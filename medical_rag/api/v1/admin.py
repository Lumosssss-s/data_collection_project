"""知识库管理 API（医疗，BE-13）

知识库运营管理（Token 鉴权）：
  - 条目管理：按业务 ID 管理 medical_knowledge 中的条目（doc / rec / drug / term）
  - 文档目录：doc_catalog.json 的浏览 / 编辑 / 删除 / 从 ES 重建（DocCatalog 为权威）

Token 鉴权机制保留（MEDICAL_ADMIN_TOKEN）；本模块仅管理人已入库数据，
批量文件入库请使用 ingest.py（BE-37）。
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from typing import Any, Dict, List, Optional

from core.config import settings
from models.schemas import APIResponse
from services.doc_management_service import DocManagementService
from utils.doc_catalog import DocCatalog

router = APIRouter(prefix="/admin", tags=["知识库管理"])

doc_service = DocManagementService()
catalog = DocCatalog()

# 管理员Token，从环境变量 MEDICAL_ADMIN_TOKEN 读取（见 core/config.py 的 admin_token）
# 默认值仅供本地开发使用，生产环境务必在 .env 中覆盖
ADMIN_TOKEN = settings.admin_token


def verify_admin_token(authorization: Optional[str] = Header(None)) -> bool:
    """验证管理员Token（支持 Bearer 前缀）"""
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证令牌", headers={"WWW-Authenticate": "Bearer"})

    token = authorization[7:].strip() if authorization.startswith("Bearer ") else authorization.strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="无效的认证令牌")

    return True


# ==================== 条目管理 (Items) ====================

@router.post("/item", summary="新增/覆盖条目")
async def create_item(
    data: Dict[str, Any],
    data_type: str = Query(..., description="条目类型：doc / rec / drug / term"),
    _: bool = Depends(verify_admin_token),
):
    """
    新增（或按业务 ID 覆盖）一个条目。

    请求体为条目记录本身（须含对应业务 ID 字段：doc_id / rec_id / drug_id / term_id）。
    结构化字段按 §5.7.2 白名单落库；doc 类型会同步 doc_catalog.json。
    """
    try:
        result = doc_service.create_item(data_type, data)
        return APIResponse(success=True, data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"条目入库失败: {str(e)}")


@router.post("/items/batch", summary="批量导入条目")
async def batch_import_items(
    files_data: List[Dict[str, Any]],
    _: bool = Depends(verify_admin_token),
):
    """
    批量导入条目。每一项为 {"data_type": "rec", "data": {...}}。

    逐条独立处理，单条失败不影响其余；返回成功/失败计数与失败明细。
    """
    try:
        success_count = 0
        failed_list: List[Dict] = []

        for file_item in files_data:
            data_type = file_item.get("data_type", "")
            data = file_item.get("data", {})
            try:
                doc_service.create_item(data_type, data)
                success_count += 1
            except Exception as e:
                failed_list.append({
                    "data_type": data_type,
                    "item_id": (data.get("doc_id") or data.get("rec_id")
                                or data.get("drug_id") or data.get("term_id") or ""),
                    "error": str(e),
                })

        return APIResponse(success=True, data={
            "success_count": success_count,
            "failed_count": len(failed_list),
            "failed": failed_list,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量导入失败: {str(e)}")


@router.get("/item/{item_id}", summary="获取条目详情")
async def get_item(
    item_id: str,
    _: bool = Depends(verify_admin_token),
):
    """根据业务 ID（= ES _id）获取条目详情。"""
    try:
        item = doc_service.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"条目不存在: {item_id}")
        return APIResponse(success=True, data=item)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取条目失败: {str(e)}")


@router.put("/item/{item_id}", summary="更新条目")
async def update_item(
    item_id: str,
    updates: Dict[str, Any],
    data_type: Optional[str] = Query(None, description="条目类型（缺省时按原记录 data_type）"),
    _: bool = Depends(verify_admin_token),
):
    """更新条目：与现有记录合并后按业务 ID 覆盖写回。"""
    try:
        result = doc_service.update_item(item_id, updates, data_type=data_type)
        return APIResponse(success=True, data=result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新条目失败: {str(e)}")


@router.delete("/item/{item_id}", summary="删除条目")
async def delete_item(
    item_id: str,
    _: bool = Depends(verify_admin_token),
):
    """删除条目（doc 类型同时标记目录删除）。"""
    try:
        result = doc_service.delete_item(item_id)
        return APIResponse(success=True, data=result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除条目失败: {str(e)}")


@router.get("/items", summary="列出条目")
async def list_items(
    data_type: Optional[str] = Query(None, description="条目类型筛选：doc / rec / drug / term"),
    cancer_type: Optional[str] = Query(None, description="癌种筛选（lung/breast/…）"),
    page_size: int = Query(100, ge=1, le=500, description="返回条数（1-500）"),
    _: bool = Depends(verify_admin_token),
):
    """按类型 / 癌种列出条目。"""
    try:
        items = doc_service.list_items(data_type=data_type, cancer_type=cancer_type, page_size=page_size)
        return APIResponse(success=True, data={"items": items, "count": len(items)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取条目列表失败: {str(e)}")


@router.get("/docs", summary="获取指南文档列表")
async def list_docs(
    doc_type: Optional[str] = Query(None, description="文档类型：guideline / standard / consensus"),
    cancer_type: Optional[str] = Query(None, description="癌种筛选"),
    status: Optional[str] = Query(None, description="状态：active / superseded / deleted"),
    _: bool = Depends(verify_admin_token),
):
    """获取指南文档目录列表（doc_catalog.json 为权威）。"""
    try:
        docs = doc_service.list_docs(doc_type=doc_type, cancer_type=cancer_type, status=status)
        return APIResponse(success=True, data=docs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


@router.post("/sync", summary="同步目录与索引")
async def sync_catalog(
    _: bool = Depends(verify_admin_token),
):
    """从 ES 重建 doc_catalog.json（修复目录与索引不一致）。"""
    try:
        stats = doc_service.sync_catalog()
        return APIResponse(success=True, data={"message": "目录已从 ES 重建完成", "statistics": stats})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


# ==================== 文档目录 (Doc Catalog) ====================

@router.get("/catalog", summary="获取文档目录")
async def get_catalog(
    cancer_type: Optional[str] = Query(None, description="癌种筛选"),
    status: Optional[str] = Query(None, description="状态筛选 (active/superseded/deleted)"),
    _: bool = Depends(verify_admin_token),
):
    """获取文档目录列表（支持按癌种 / 状态筛选），含统计信息与目录路径。"""
    try:
        docs = catalog.get_all_docs(cancer_type=cancer_type, status=status)
        stats = catalog.get_statistics()
        return APIResponse(success=True, data={
            "docs": docs,
            "statistics": stats,
            "catalog_path": str(catalog.catalog_path),
            "last_updated": catalog.load().get("last_updated"),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档目录失败: {str(e)}")


@router.get("/catalog/statistics", summary="获取文档目录统计信息")
async def get_catalog_statistics(
    _: bool = Depends(verify_admin_token),
):
    """获取目录统计：总文档数、按类型 / 癌种 / 年份 / 状态分布等。"""
    try:
        return APIResponse(success=True, data=catalog.get_statistics())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/catalog/{doc_id}", summary="获取单个文档目录记录")
async def get_catalog_record(
    doc_id: str,
    _: bool = Depends(verify_admin_token),
):
    """根据 doc_id 获取单个文档的目录记录。"""
    try:
        record = catalog.find_by_doc_id(doc_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"未找到文档 {doc_id} 的目录记录")
        return APIResponse(success=True, data=record)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取目录记录失败: {str(e)}")


@router.put("/catalog/{doc_id}", summary="手动更新文档目录记录")
async def update_catalog_record(
    doc_id: str,
    updates: Dict[str, Any],
    _: bool = Depends(verify_admin_token),
):
    """
    手动更新指定文档的目录记录。

    可更新字段：title / doc_type / issuer / cancer_types / item_count / version / publish_date / status。
    """
    try:
        existing = catalog.find_by_doc_id(doc_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"未找到文档 {doc_id}")

        updated_record = catalog.add_or_update(
            doc_id=doc_id,
            title=updates.get("title", existing.get("title", "")),
            doc_type=updates.get("doc_type", existing.get("doc_type", "")),
            issuer=updates.get("issuer", existing.get("issuer", "")),
            cancer_types=updates.get("cancer_types", existing.get("cancer_types", [])),
            item_count=updates.get("item_count", existing.get("item_count", 0)),
            version=updates.get("version", existing.get("version", "")),
            publish_date=updates.get("publish_date", existing.get("publish_date", "")),
            file_path=existing.get("file_path", ""),
            status=updates.get("status", existing.get("status", "active")),
        )
        return APIResponse(success=True, data=updated_record)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新目录记录失败: {str(e)}")


@router.delete("/catalog/{doc_id}", summary="删除/标记删除文档目录记录")
async def delete_catalog_record(
    doc_id: str,
    _: bool = Depends(verify_admin_token),
):
    """
    删除或标记删除文档目录记录（仅标记 deleted，不物理删除，便于审计）。
    """
    try:
        success = catalog.delete(doc_id)
        if success:
            return APIResponse(success=True, message=f"已标记删除 {doc_id}")
        raise HTTPException(status_code=404, detail=f"未找到文档 {doc_id} 的目录记录")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除目录记录失败: {str(e)}")


@router.post("/catalog/rebuild", summary="从 ES 重建文档目录")
async def rebuild_catalog(
    _: bool = Depends(verify_admin_token),
):
    """从 ES 重建 doc_catalog.json（覆盖现有目录数据）。"""
    try:
        from repositories.elasticsearch import ElasticsearchRepository
        stats = catalog.rebuild_from_es(ElasticsearchRepository())
        return APIResponse(success=True, data={
            "message": "Catalog 已从 ES 重建完成",
            "statistics": stats,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建目录失败: {str(e)}")
