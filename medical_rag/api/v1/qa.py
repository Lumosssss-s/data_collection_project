from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from fastapi import Request
from typing import Optional
from models.schemas import APIResponse
from services.qa_service import QAService
import json

router = APIRouter(prefix="/qa", tags=["问答"])
qa_service = QAService()


def _parse_history(history_str: Optional[str]) -> Optional[list]:
    """解析对话历史JSON字符串"""
    if not history_str or not history_str.strip():
        return None
    try:
        parsed = json.loads(history_str)
        if isinstance(parsed, list) and len(parsed) > 0:
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


@router.get("/stream")
async def ask_stream(
    question: str = Query(..., description="用户问题"),
    top_k: int = Query(5, description="检索结果数量"),
    cancer_type: str = Query(None, description="癌种筛选（lung/breast/colorectal/gastric/thyroid）"),
    scenario: str = Query(None, description="场景筛选，多个用逗号分隔"),
    history: str = Query(None, description="对话历史，JSON数组格式：[{role,content}]")
):
    """流式问答接口（支持追问/多轮对话）"""
    filters = {}
    if cancer_type:
        # 支持多选（逗号分隔），多值按 OR 过滤（与 scenario 一致）
        cancers = [c.strip() for c in cancer_type.split(",") if c.strip()]
        if cancers:
            filters["cancer_type"] = cancers[0] if len(cancers) == 1 else cancers
    if scenario:
        scenarios = [s.strip() for s in scenario.split(",") if s.strip()]
        if scenarios:
            filters["scenario"] = scenarios[0] if len(scenarios) == 1 else scenarios

    history_list = _parse_history(history)

    def generate():
        for chunk in qa_service.ask_stream(question, top_k, filters or None, history_list):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/stream")
async def ask_stream_multimodal(request: Request):
    """
    支持图片的多模态流式问答（POST接口）

    请求体格式：
    {
        "question": "用户问题（必填）",
        "top_k": 5,
        "filters": {"cancer_type": "lung", "scenario": "treatment_first_line"},
        "history": [{"role": "user", "content": "..."}],
        "images": [
            {
                "data": "base64编码的图片数据",
                "mime_type": "image/jpeg"
            }
        ]
    }
    """
    try:
        data = await request.json()
    except Exception:
        return APIResponse(success=False, message="无效的JSON数据")

    question = data.get("question", "")
    if not question or not question.strip():
        return APIResponse(success=False, message="问题不能为空")

    top_k = data.get("top_k", 5)
    filters = data.get("filters")  # {cancer_type / scenario / ...}，键为 ES 字段名
    if not isinstance(filters, dict) or not filters:
        filters = None
    history = data.get("history")
    images = data.get("images", [])  # 图片列表

    history_list = None
    if history and isinstance(history, list) and len(history) > 0:
        history_list = history

    def generate():
        for chunk in qa_service.ask_stream_with_image(
            question=question,
            top_k=top_k,
            filters=filters,
            history=history_list,
            images=images
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
