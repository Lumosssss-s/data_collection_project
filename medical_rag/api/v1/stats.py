"""知识库运营看板统计 API

提供管理端看板所需的聚合统计（主方案 §6.5：平台自身的知识库运营与质量看板）：
- 总览：指南数 / 推荐条目数 / 术语数 / 药品说明书数 / 疾病档案数 / 覆盖癌种数
- 按癌种分布（指南 + 推荐条目）
- 主题分布（medical taxonomy）
- 指南发布年份趋势

不含「使用分析」（检索量 / 热门问题 / 未命中聚类）：该口径需检索日志采集与 B7
运营指标数据源，暂未建设，故不提供。
"""

from fastapi import APIRouter, Query, HTTPException
from typing import List, Dict, Optional, Any
from datetime import datetime

from core.config import settings
from core.domain_enums import CANCER_TYPE_INFO
from models.schemas import APIResponse
from repositories.elasticsearch import ElasticsearchRepository
from utils.doc_catalog import DocCatalog

router = APIRouter(prefix="/stats", tags=["数据统计"])

repo = ElasticsearchRepository()
catalog = DocCatalog()


# ==================== 数据获取辅助函数（不包含路由参数） ====================

def _cancer_type_label(code: str) -> str:
    """癌种代码 → 中文名（§5.7.3）；未知代码原样返回。"""
    for zh, (c, _range) in CANCER_TYPE_INFO.items():
        if c == code:
            return zh
    return code or "未知"


def _load_docs() -> List[Dict]:
    """从 catalog 载入非删除状态的指南/规范/共识文档记录。"""
    cat_data = catalog.load()
    return [d for d in cat_data.get("docs", []) if d.get("status") != "deleted"]


def _data_type_counts() -> Dict[str, int]:
    """按 data_type 统计主索引条目数（rec / drug / term 等）。"""
    try:
        resp = repo.client.search(
            index=settings.es_index_name,
            body={"size": 0, "aggs": {"by_type": {"terms": {"field": "data_type", "size": 10}}}},
        )
        buckets = resp.get("aggregations", {}).get("by_type", {}).get("buckets", [])
        return {b.get("key"): b.get("doc_count", 0) for b in buckets if b.get("key")}
    except Exception:
        return {}


def _cancer_type_item_counts() -> Dict[str, int]:
    """按癌种统计主索引条目数。

    DOC 用数组字段 cancer_types，REC/DRUG 用单值字段 cancer_type，两者取并集累加。
    """
    counts: Dict[str, int] = {}
    try:
        resp = repo.client.search(
            index=settings.es_index_name,
            body={"size": 0, "aggs": {
                "single": {"terms": {"field": "cancer_type", "size": 50}},
                "multi": {"terms": {"field": "cancer_types", "size": 50}},
            }},
        )
        aggs = resp.get("aggregations", {})
        for key in ("single", "multi"):
            for b in aggs.get(key, {}).get("buckets", []):
                ct = b.get("key")
                if ct:
                    counts[ct] = counts.get(ct, 0) + b.get("doc_count", 0)
    except Exception:
        pass
    return counts


def _disease_profile_count() -> int:
    """疾病档案索引条目数（索引存在时统计，失败返回 0）。"""
    try:
        return repo.client.count(index=settings.es_disease_index_name).get("count", 0)
    except Exception:
        return 0


def _fetch_overview_data() -> dict:
    """知识库运营总览（数字卡片）。"""
    docs = _load_docs()
    type_counts = _data_type_counts()

    # 覆盖癌种：catalog 文档的 cancer_types ∪ 主索引条目的 cancer_type
    covered = set()
    for d in docs:
        for ct in (d.get("cancer_types") or []):
            covered.add(ct)
    covered.update(_cancer_type_item_counts().keys())

    # 发布日期范围（仅 DOC 有 publish_date）
    dates = []
    for d in docs:
        ds = str(d.get("publish_date") or "").strip()
        if len(ds) >= 10:
            try:
                dates.append(datetime.strptime(ds[:10], "%Y-%m-%d"))
            except ValueError:
                continue

    date_range = {}
    if dates:
        date_range = {
            "earliest": min(dates).strftime("%Y-%m-%d"),
            "latest": max(dates).strftime("%Y-%m-%d"),
        }

    latest_ingest = None
    if docs:
        latest = sorted(docs, key=lambda x: x.get("last_updated", ""), reverse=True)[0]
        latest_ingest = {
            "doc_id": latest.get("doc_id", ""),
            "title": latest.get("title", ""),
            "date": latest.get("last_updated", ""),
        }

    return {
        "total_docs": len(docs),
        "total_items": sum(d.get("item_count", 0) or 0 for d in docs),
        "total_recs": type_counts.get("rec", 0),
        "total_drugs": type_counts.get("drug", 0),
        "total_terms": type_counts.get("term", 0),
        "disease_profiles": _disease_profile_count(),
        "cancer_type_count": len(covered),
        "cancer_types": sorted(covered),
        "date_range": date_range,
        "latest_ingest": latest_ingest,
        "last_catalog_update": catalog.load().get("last_updated", ""),
    }


def _fetch_cancer_type_data() -> list:
    """按癌种统计：指南数（catalog）与条目数（主索引）。"""
    docs = _load_docs()
    item_counts = _cancer_type_item_counts()

    doc_counts: Dict[str, int] = {}
    for d in docs:
        for ct in (d.get("cancer_types") or []):
            doc_counts[ct] = doc_counts.get(ct, 0) + 1

    all_types = sorted(set(doc_counts) | set(item_counts))
    result = [{
        "cancer_type": ct,
        "label_zh": _cancer_type_label(ct),
        "doc_count": doc_counts.get(ct, 0),
        "item_count": item_counts.get(ct, 0),
    } for ct in all_types]
    result.sort(key=lambda x: (x["doc_count"] + x["item_count"]), reverse=True)
    return result


def _fetch_topic_data(limit: int = 50) -> list:
    """主题分布（medical taxonomy，nested 聚合）。"""
    topics = repo.get_topic_statistics(limit=limit)
    return topics


def _fetch_time_data(group_by: str = "year") -> dict:
    """指南发布时间的分布趋势（DOC，按 publish_date）。"""
    docs = _load_docs()
    time_stats: Dict[str, Dict] = {}

    for d in docs:
        ds = str(d.get("publish_date") or "").strip()
        if len(ds) < 4:
            continue
        try:
            if len(ds) == 4 and ds.isdigit():
                dt = datetime.strptime(f"{ds}-01-01", "%Y-%m-%d")
            else:
                dt = datetime.strptime(ds[:10], "%Y-%m-%d")
        except ValueError:
            continue

        key = str(dt.year) if group_by == "year" else f"{dt.year}-{dt.month:02d}"
        if key not in time_stats:
            time_stats[key] = {"period": key, "total": 0, "by_cancer_type": {}, "docs": []}

        time_stats[key]["total"] += 1
        for ct in (d.get("cancer_types") or ["未知"]):
            label = _cancer_type_label(ct)
            time_stats[key]["by_cancer_type"][label] = time_stats[key]["by_cancer_type"].get(label, 0) + 1

        time_stats[key]["docs"].append({
            "doc_id": d.get("doc_id"),
            "title": d.get("title"),
            "cancer_types": d.get("cancer_types", []),
            "publish_date": ds[:10] if len(ds) >= 10 else ds,
        })

    result = list(time_stats.values())
    result.sort(key=lambda x: x["period"])

    cumulative_total = 0
    for item in result:
        cumulative_total += item["total"]
        item["cumulative_total"] = cumulative_total

    return {
        "group_by": group_by,
        "data": result,
        "summary": {
            "earliest_period": result[0]["period"] if result else "",
            "latest_period": result[-1]["period"] if result else "",
            "total_periods": len(result),
        },
    }


def _fetch_timeline_data(cancer_type: Optional[str] = None) -> dict:
    """指南发布时间轴（DOC，按 publish_date 升序；可选癌种筛选）。"""
    docs = _load_docs()
    if cancer_type:
        docs = [d for d in docs if cancer_type in (d.get("cancer_types") or [])]

    valid = []
    for d in docs:
        ds = str(d.get("publish_date") or "").strip()
        if len(ds) < 4:
            continue
        if len(ds) == 4 and ds.isdigit():
            sort_date = f"{ds}-01-01"
        elif len(ds) >= 10:
            sort_date = ds[:10]
        else:
            continue
        valid.append({**d, "sort_date": sort_date})

    valid.sort(key=lambda x: x["sort_date"])
    return {"timeline": valid, "count": len(valid), "cancer_type_filter": cancer_type}


# ==================== API 路由函数 ====================

@router.get("", summary="获取统计数据总入口")
@router.get("/", summary="获取统计数据总入口")
async def get_stats():
    """知识库运营看板总入口（供前端 /api/v1/stats 一次拉取）。"""
    try:
        overview = _fetch_overview_data()
        cancer_type_list = _fetch_cancer_type_data()
        topic_list = _fetch_topic_data(limit=30)
        time_trend = _fetch_time_data(group_by="year")

        dashboard_data = {
            "overview": {
                "total_docs": overview.get("total_docs", 0),
                "total_recs": overview.get("total_recs", 0),
                "total_terms": overview.get("total_terms", 0),
                "disease_profiles": overview.get("disease_profiles", 0),
                "cancer_type_count": overview.get("cancer_type_count", 0),
            },
            "cancer_type": cancer_type_list,
            "topics": topic_list,
            "time_trend": time_trend,
            "generated_at": datetime.now().isoformat(),
        }
        return APIResponse(success=True, data=dashboard_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计数据失败: {str(e)}")


@router.get("/overview", summary="获取知识库总览")
async def get_overview():
    """知识库运营总览数字（指南数 / 推荐条目数 / 术语数 / 疾病档案数 / 覆盖癌种数）。"""
    try:
        data = _fetch_overview_data()
        return APIResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取总览数据失败: {str(e)}")


@router.get("/by_cancer_type", summary="按癌种统计")
async def get_by_cancer_type():
    """各癌种的指南数与条目数统计。"""
    try:
        data = _fetch_cancer_type_data()
        return APIResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取癌种统计失败: {str(e)}")


@router.get("/by_topic", summary="按主题统计")
async def get_by_topic(
    limit: int = Query(50, description="返回的主题数量上限")
):
    """主题分类统计（medical taxonomy）。"""
    try:
        data = _fetch_topic_data(limit=limit)
        return APIResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取主题统计失败: {str(e)}")


@router.get("/by_time", summary="按发布时间统计")
async def get_by_time(
    group_by: str = Query("year", enum=["year", "month"], description="分组方式")
):
    """指南发布时间的分布趋势。"""
    try:
        data = _fetch_time_data(group_by=group_by)
        return APIResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取时间统计失败: {str(e)}")


@router.get("/timeline", summary="获取指南时间轴")
async def get_timeline(
    cancer_type: Optional[str] = Query(None, description="癌种筛选（lung/breast/…）")
):
    """获取指南的发布时间线列表。"""
    try:
        data = _fetch_timeline_data(cancer_type=cancer_type)
        return APIResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取时间轴数据失败: {str(e)}")


@router.get("/full_dashboard", summary="获取完整看板数据")
async def get_full_dashboard():
    """一次性获取看板全部数据（减少前端请求次数）。"""
    try:
        dashboard_data = {
            "overview": _fetch_overview_data(),
            "by_cancer_type": _fetch_cancer_type_data(),
            "by_topic": _fetch_topic_data(limit=30),
            "by_time": _fetch_time_data(group_by="year"),
            "timeline": _fetch_timeline_data(),
            "generated_at": datetime.now().isoformat(),
            "cache_ttl": 300,
        }
        return APIResponse(success=True, data=dashboard_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取完整看板数据失败: {str(e)}")
