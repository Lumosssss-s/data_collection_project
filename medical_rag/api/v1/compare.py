"""对比分析 API（医疗，BE-08）

双癌种临床维度对比（简版）：
  - GET  /compare               轻量对比（检索 + 结构化展示，不调用 LLM）
  - POST /compare/deep-analysis 可选 LLM 深度对比报告（流式，默认由前端按需触发）
  - POST /compare/cache-ai      将前端生成的 AI 报告回写缓存
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.config import settings
from core.domain_enums import get_cancer_type_info
from models.schemas import APIResponse
from services.compare_service import CompareService
from utils.llm_client import stream_chat_messages

router = APIRouter(prefix="/compare", tags=["癌种对比"])
compare_service = CompareService()


class DeepAnalysisRequest(BaseModel):
    """AI 深度对比分析请求体"""
    cancer_type_a: str
    cancer_type_b: str
    topic: str = ""
    context_a: str  # 癌种A的推荐条目摘要
    context_b: str  # 癌种B的推荐条目摘要


def _safe_name(cancer_type: str, fallback: str) -> str:
    """把癌种代码/中文名转为标准中文名，非法值原样返回（避免 500）。"""
    try:
        from core.domain_enums import CANCER_TYPE_INFO
        code, _ = get_cancer_type_info(cancer_type)
        return {c: n for n, (c, _) in CANCER_TYPE_INFO.items()}.get(code, fallback)
    except ValueError:
        return fallback


@router.get("")
def compare_cancers(
    cancer_type_a: str = Query(..., description="癌种A（代码或中文名，如 lung / 肺癌）"),
    cancer_type_b: str = Query(..., description="癌种B（代码或中文名，如 breast / 乳腺癌）"),
    topic: str = Query("", description="可选对比主题（如：免疫治疗、靶向治疗）"),
    top_k: int = Query(5, ge=1, le=20, description="每个维度每个癌种检索条目数（1-20）"),
):
    """
    双癌种对比（轻量版，不调用 LLM，秒级响应）

    分别检索两个癌种在固定临床维度（症状/病理分子/诊断/治疗/预后）上的推荐条目，
    按维度聚合 → 结构化对照 + 自动总结。
    如需 LLM 深度分析报告，请使用 `POST /compare/deep-analysis`。
    """
    try:
        result = compare_service.compare(
            cancer_type_a=cancer_type_a,
            cancer_type_b=cancer_type_b,
            topic=topic,
            top_k=top_k,
        )
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, message=str(e))
    except Exception as e:
        return APIResponse(success=False, message=f"对比失败: {str(e)}")


@router.post("/deep-analysis")
def deep_analysis(req: DeepAnalysisRequest):
    """
    AI 深度对比分析（调用 LLM，流式输出）

    基于两个癌种的检索结果，由 LLM 生成专业的双癌种临床维度深度对比报告，流式输出。
    """
    try:
        from fastapi.responses import StreamingResponse
        import json

        name_a = _safe_name(req.cancer_type_a, req.cancer_type_a)
        name_b = _safe_name(req.cancer_type_b, req.cancer_type_b)
        topic = req.topic or "综合对比"

        prompt = f"""你是肿瘤科临床决策支持助手。请对比{name_a}与{name_b}在「{topic}」方面的循证差异。

## {name_a}
{req.context_a[:2000]}

## {name_b}
{req.context_b[:2000]}

请严格按以下格式输出（Markdown），不要输出其他内容：

### 差异总览
一段话概括两者在「{topic}」方面的核心差异。

### 逐维度对比表
| 维度 | {name_a} | {name_b} |
|------|------|------|
| 症状与临床表现 | | |
| 病理与分子特征 | | |
| 诊断与分期 | | |
| 治疗推荐 | | |
| 预后与随访 | | |

### 关键差异要点
1. **差异点1**：描述 → 临床意义
2. **差异点2**：描述 → 临床意义
3. **差异点3**：描述 → 临床意义

### 临床提示
给出 3 条面向临床实践的提示；如涉具体用药，需注明以权威指南与药品说明书为准。
"""

        model = settings.llm_comparison_model or "deepseek-flash"

        def generate():
            for content in stream_chat_messages(
                [{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
            ):
                yield f"data: {json.dumps({'type': 'chunk', 'data': content})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        import json
        from fastapi.responses import StreamingResponse
        def generate_error():
            yield f"data: {json.dumps({'type': 'error', 'data': f'深度分析失败: {str(e)}'})}\n\n"
        return StreamingResponse(generate_error(), media_type="text/event-stream")


class CacheAIRequest(BaseModel):
    """AI 分析结果回写缓存请求"""
    cancer_type_a: str
    cancer_type_b: str
    topic: str = ""
    ai_analysis: str


@router.post("/cache-ai")
def cache_ai_analysis(req: CacheAIRequest):
    """
    将前端生成的 AI 深度分析报告回写到 ES 缓存中。
    前端在首次生成 AI 报告后异步调用此接口，后续缓存命中时直接返回。
    """
    try:
        code_a, _ = get_cancer_type_info(req.cancer_type_a)
        code_b, _ = get_cancer_type_info(req.cancer_type_b)
        t_id, t_a, t_b = compare_service._cache_key(code_a, code_b, req.topic)

        cached = compare_service.repo.get_analysis_cache(t_id, t_a, t_b, cache_type="compare")
        if not cached or not isinstance(cached, dict):
            return APIResponse(success=False, message="缓存不存在，无法回写")

        report_data = cached.get("report_data", {})
        if not isinstance(report_data, dict):
            report_data = {}
        report_data["ai_analysis"] = req.ai_analysis

        fingerprint = cached.get("fingerprint", "")
        compare_service.repo.save_analysis_cache(
            t_id, t_a, t_b, fingerprint, report_data, cache_type="compare"
        )
        return APIResponse(success=True, message="AI 报告已写入缓存")

    except ValueError as e:
        return APIResponse(success=False, message=str(e))
    except Exception as e:
        return APIResponse(success=False, message=f"缓存回写失败: {str(e)}")
