"""双癌种循证对比服务（医疗，BE-08 + BE-19）

核心能力：分别检索两个癌种在固定临床维度上的推荐条目 → 按维度聚合 → 结构化展示 +
自动总结。与「跨癌种专题分析（BE-09/27）」的区别：专题分析调用 LLM 生成深度报告；
本对比以检索 + 结构化展示为主，轻量、秒级，可选 LLM 深度增强。

对比维度（简版，固定 5 维）：
    症状与临床表现 / 病理与分子特征 / 诊断与分期 / 治疗推荐 / 预后与随访
"""
import hashlib
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

from core.domain_enums import CANCER_TYPE_INFO, get_cancer_type_info
from repositories.elasticsearch import ElasticsearchRepository

logger = logging.getLogger(__name__)

# 癌种代码 -> 标准中文名
_CODE_TO_NAME = {code: name for name, (code, _) in CANCER_TYPE_INFO.items()}


class CompareService:
    """双癌种临床维度对比服务"""

    # 固定对比维度：key 稳定（前端用于定位），query 为该维度的检索词
    DIMENSIONS: List[Dict[str, str]] = [
        {"key": "symptom",   "label": "症状与临床表现", "query": "症状 临床表现 体征"},
        {"key": "pathology", "label": "病理与分子特征", "query": "病理 分子分型 基因突变 免疫组化 标志物"},
        {"key": "diagnosis", "label": "诊断与分期",     "query": "诊断 影像 病理活检 检查 分期"},
        {"key": "treatment", "label": "治疗推荐",       "query": "治疗 靶向 免疫 化疗 放疗 手术 推荐"},
        {"key": "prognosis", "label": "预后与随访",     "query": "预后 生存 复发 随访"},
    ]

    # 每个维度、每个癌种最多保留的条目数
    MAX_ITEMS_PER_DIMENSION = 5

    def __init__(self):
        self.repo = ElasticsearchRepository()
        self._retriever = None  # 懒加载，避免导入期加载大模型

    @property
    def retriever(self):
        if self._retriever is None:
            from services.retriever_service import RetrieverService
            self._retriever = RetrieverService()
        return self._retriever

    # ================================================================
    #  缓存指纹机制
    # ================================================================

    def _compute_fingerprint(self, code_a: str, code_b: str, topic: str) -> str:
        """生成对比指纹（MD5）：仅基于稳定输入（两癌种 + 主题 + 维度集合）。"""
        raw = json.dumps({
            "cancer_type_a": code_a,
            "cancer_type_b": code_b,
            "topic": topic,
            "dimensions": [d["key"] for d in self.DIMENSIONS],
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _cache_key(self, code_a: str, code_b: str, topic: str) -> Tuple[str, str, str]:
        """缓存三元键（topic_id / target_a / target_b），与 redis 无关，仅用于 ES 缓存文档 ID。"""
        return code_a, code_b, (topic or "_")

    def _try_get_cached(self, code_a: str, code_b: str, topic: str, current_fp: str) -> Optional[Dict]:
        """尝试从缓存获取有效结果，返回 report_data 或 None。"""
        t_id, t_a, t_b = self._cache_key(code_a, code_b, topic)
        cached = self.repo.get_analysis_cache(t_id, t_a, t_b, cache_type="compare")
        if not cached or not isinstance(cached, dict):
            return None
        if cached.get("fingerprint", "") != current_fp:
            logger.info("[Compare-Cache] 指纹不匹配，失效")
            return None
        report_data = cached.get("report_data")
        if not isinstance(report_data, dict):
            return None
        logger.info(f"[Compare-Cache] 命中！{code_a} vs {code_b}, topic={topic or '-'}")
        return report_data

    # ================================================================
    #  检索与聚合
    # ================================================================

    def _search_cancer(self, code: str, topic: str) -> List[Dict]:
        """检索某癌种在全部维度上的推荐条目，按维度聚合（跨维度去重）。

        Returns:
            [{"dimension_key", "dimension_label", "items": [item, ...]}, ...]
        """
        seen_ids = set()
        blocks: List[Dict] = []

        for dim in self.DIMENSIONS:
            query = dim["query"] + (f" {topic}" if topic else "")
            try:
                raw = self.retriever.hybrid_search(
                    query, top_k=self.MAX_ITEMS_PER_DIMENSION,
                    filters={"cancer_type": code},
                )
            except Exception as e:
                logger.warning(f"[Compare] 检索失败 {code}/{dim['key']}: {type(e).__name__}: {e}")
                raw = []

            items: List[Dict] = []
            for r in raw:
                item_id = r.get("item_id") or ""
                if item_id and item_id in seen_ids:
                    continue  # 同一层级已归入更靠前的维度，避免重复
                if item_id:
                    seen_ids.add(item_id)
                items.append(self._format_item(r))
                if len(items) >= self.MAX_ITEMS_PER_DIMENSION:
                    break

            blocks.append({
                "dimension_key": dim["key"],
                "dimension_label": dim["label"],
                "items": items,
            })

        return blocks

    @staticmethod
    def _format_item(r: Dict) -> Dict:
        """把检索结果裁剪为对比展示所需字段。"""
        return {
            "item_id": r.get("item_id", ""),
            "rec_id": r.get("rec_id", ""),
            "title": r.get("title", ""),
            "content": (r.get("content") or "")[:500],
            "score": round(float(r.get("score", 0.0)), 4),
            "cancer_type": r.get("cancer_type", ""),
            "scenario": r.get("scenario", ""),
            "evidence_level": r.get("evidence_level", ""),
            "rec_strength": r.get("rec_strength", ""),
            "breadcrumb": r.get("breadcrumb", ""),
        }

    def _build_stats(self, blocks_a: List[Dict], blocks_b: List[Dict],
                     name_a: str, name_b: str) -> Dict:
        """构建对比统计：各维度条目数 + 总条目数。"""
        by_dim: Dict[str, Dict[str, int]] = {}
        for ba, bb in zip(blocks_a, blocks_b):
            label = ba["dimension_label"]
            by_dim[label] = {"a": len(ba["items"]), "b": len(bb["items"])}

        total_a = sum(len(b["items"]) for b in blocks_a)
        total_b = sum(len(b["items"]) for b in blocks_b)
        return {
            "dimension_item_counts": by_dim,
            "total_items": {"a": total_a, "b": total_b},
            "names": {"a": name_a, "b": name_b},
        }

    def _build_auto_summary(self, blocks_a: List[Dict], blocks_b: List[Dict],
                            name_a: str, name_b: str, topic: str) -> str:
        """基于检索结果生成自动对比总结（不调用 LLM）。"""
        total_a = sum(len(b["items"]) for b in blocks_a)
        total_b = sum(len(b["items"]) for b in blocks_b)
        if total_a == 0 and total_b == 0:
            scope = f"关于「{topic}」的" if topic else ""
            return f"未检索到{name_a}与{name_b}{scope}相关推荐条目。"

        scope = f"围绕「{topic}」，" if topic else ""
        parts = [f"本次{scope}对比了{name_a}与{name_b}的循证推荐要点。"]

        def _covered(blocks: List[Dict]) -> List[str]:
            return [b["dimension_label"] for b in blocks if b["items"]]

        cov_a, cov_b = _covered(blocks_a), _covered(blocks_b)
        parts.append(
            f"{name_a}覆盖 {total_a} 条推荐"
            + (f"，集中于{'、'.join(cov_a)}。" if cov_a else "，暂无相关内容。")
        )
        parts.append(
            f"{name_b}覆盖 {total_b} 条推荐"
            + (f"，集中于{'、'.join(cov_b)}。" if cov_b else "，暂无相关内容。")
        )
        if cov_a and cov_b:
            common = [x for x in cov_a if x in cov_b]
            if common:
                parts.append(f"两者在「{'、'.join(common)}」等维度均有可对照的推荐，详见下方逐维度对照。")
            else:
                parts.append("两者覆盖维度差异较大，建议结合下方对照进一步比较。")
        return "".join(parts)

    # ================================================================
    #  主流程
    # ================================================================

    def compare(
        self,
        cancer_type_a: str,
        cancer_type_b: str,
        topic: str = "",
        top_k: int = MAX_ITEMS_PER_DIMENSION,
    ) -> Dict:
        """
        执行双癌种对比分析（带缓存）。

        参数:
            cancer_type_a / cancer_type_b: 癌种代码或中文名（受控词表，§5.7.3）
            topic: 可选对比主题（如「免疫治疗」「靶向治疗」）
            top_k: 每个维度、每个癌种返回的条目数上限

        Returns:
            {
              "cancer_type_a", "cancer_type_b", "cancer_name_a", "cancer_name_b",
              "topic", "dimensions": [{key,label}, ...],
              "results_a": [{dimension_key, dimension_label, items}, ...],
              "results_b": [...],
              "stats": {...}, "auto_summary": str,
              "elapsed_seconds": float, "_cache_hit": bool
            }
        """
        code_a, _ = get_cancer_type_info(cancer_type_a)
        code_b, _ = get_cancer_type_info(cancer_type_b)
        name_a = _CODE_TO_NAME.get(code_a, cancer_type_a)
        name_b = _CODE_TO_NAME.get(code_b, cancer_type_b)

        overall_start = time.time()
        self.MAX_ITEMS_PER_DIMENSION = max(1, top_k)

        # 步骤1：指纹 + 缓存
        current_fp = self._compute_fingerprint(code_a, code_b, topic)
        cached = self._try_get_cached(code_a, code_b, topic, current_fp)
        if cached is not None:
            cached["_cache_hit"] = True
            cached["elapsed_seconds"] = round(time.time() - overall_start, 2)
            return cached

        # 步骤2：分别检索两个癌种并按维度聚合
        blocks_a = self._search_cancer(code_a, topic)
        blocks_b = self._search_cancer(code_b, topic)

        stats = self._build_stats(blocks_a, blocks_b, name_a, name_b)
        auto_summary = self._build_auto_summary(blocks_a, blocks_b, name_a, name_b, topic)

        resp = {
            "cancer_type_a": code_a,
            "cancer_type_b": code_b,
            "cancer_name_a": name_a,
            "cancer_name_b": name_b,
            "topic": topic,
            "dimensions": [{"key": d["key"], "label": d["label"]} for d in self.DIMENSIONS],
            "results_a": blocks_a,
            "results_b": blocks_b,
            "stats": stats,
            "auto_summary": auto_summary,
            "elapsed_seconds": round(time.time() - overall_start, 2),
            "_cache_hit": False,
        }

        # 步骤3：写缓存（失败不影响结果）
        total = stats["total_items"]["a"] + stats["total_items"]["b"]
        if total > 0:
            try:
                t_id, t_a, t_b = self._cache_key(code_a, code_b, topic)
                self.repo.save_analysis_cache(t_id, t_a, t_b, current_fp, resp, cache_type="compare")
            except Exception as e:
                logger.warning(f"[Compare-Cache] 写入缓存失败（不影响结果）: {e}")

        logger.info(
            f"[Compare] {name_a}({stats['total_items']['a']}条) vs "
            f"{name_b}({stats['total_items']['b']}条), 耗时 {resp['elapsed_seconds']}s"
        )
        return resp
