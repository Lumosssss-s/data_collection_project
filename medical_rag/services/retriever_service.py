import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from repositories.elasticsearch import ElasticsearchRepository, _medical_metadata, zh_convert
from core.config import settings
from services.query_decomposer import decompose_query
from utils.search_cache import get_search_cache


logger = logging.getLogger(__name__)


def _normalize_query_for_cache(query: str) -> str:
    """检索缓存的查询归一化：压缩空白 + 统一小写 + 繁→简。

    繁→简保证「澳門 勞動關係法」与「澳门劳动关系法」落到同一个缓存键，
    避免同一问题因输入法差异重复支付一次完整检索。
    """
    if not query:
        return ""
    collapsed = re.sub(r"\s+", " ", query).strip().lower()
    return zh_convert(collapsed, "t2s")


def _canonical_filters(filters: Optional[Dict[str, Any]]) -> str:
    """把过滤条件序列化为稳定的缓存键片段（键排序、列表内排序）。"""
    if not filters:
        return ""
    parts = []
    for k in sorted(filters):
        v = filters[k]
        if isinstance(v, (list, tuple, set)):
            parts.append(f"{k}={','.join(sorted(str(x) for x in v))}")
        elif v is not None:
            parts.append(f"{k}={v}")
    return "&".join(parts)


class RetrieverService:
    def __init__(self):
        self.repo = ElasticsearchRepository()
        self._reranker = None

    def _get_reranker(self):
        """延迟获取 reranker 实例"""
        if not settings.reranker_enabled:
            return None
        if self._reranker is None:
            from services.reranker_service import ReRankerService
            self._reranker = ReRankerService()
        return self._reranker

    def _rerank_two_stage(self, query: str, candidates: List[Dict]) -> List[Dict]:
        """
        两阶段重排：只精排前 reranker_window 条，其余候选按 RRF 顺序拼在尾部。

        与「全量精排后截断」的区别在于尾部候选不再被丢弃：窗口从 50 降到 20 后，
        排在 20 名之后的 30 条仍以原始 RRF 次序参与最终排序，因此 top_k 较大时
        （如问答取 50 条候选）不会因为不进精排窗口而整体消失。
        收益是 reranker 对数减半，CPU 推理耗时同步下降（reranker 占检索延迟约 93%）。

        精排模型不可用时原样返回 candidates（保持 RRF 顺序），不阻断检索。
        """
        reranker = self._get_reranker()
        if not reranker or not candidates:
            return candidates

        window = min(len(candidates), settings.reranker_window)
        if window <= 0:
            return candidates

        head = candidates[:window]
        tail = candidates[window:]
        # top_k 传窗口大小而非调用方的 top_k，确保窗口内 20 条全部拿到精排分数，
        # 否则 rerank 内部按 top_k 截断会让尾部候选的排序基准与头部不一致。
        reranked = reranker.rerank(query=query, candidates=head, top_k=window)

        # rerank 会跳过 content 为空的候选（不产生 rerank_score），
        # 这些条目按原 RRF 顺序归入尾部，避免被静默丢弃。
        reranked_ids = {id(doc) for doc in reranked}
        skipped = [doc for doc in head if id(doc) not in reranked_ids]
        return reranked + skipped + tail

    @staticmethod
    def _attach_match_scores(results: List[Dict]) -> List[Dict]:
        """为每条结果计算展示用「匹配度」match_score ∈ [0,1]，缺失置 None。

        取值优先级：
          1. 真实向量余弦相似度（`_cosine`）：语义明确、有界、可跨查询比较；
          2. 都没有 → None，前端不显示百分比。

        说明：曾考虑用精排分 sigmoid 作为优先项，但实测 bge-reranker-v2-m3 的
        logit 在本语料整体偏负（相关知识条款中位数 ≈ -4.5），sigmoid 后会得到
        ~1% 的荒谬值，故不采用。精排分只用于排序，不参与展示。
        另外，旧实现用 RRF 分反推相似度（1/(1+1/(1+rrf))），因 RRF 分动态范围极小，
        导致所有条款都显示约 50%，这里一并修正。
        """
        for r in results:
            cos = r.get("_cosine")
            if cos is not None:
                r["match_score"] = round(max(0.0, min(1.0, float(cos))), 4)
            else:
                r["match_score"] = None
        return results

    def _deduplicate_by_id(self, raw_results: Dict, top_k: int) -> Dict:
        """按 ES `_id` 去重并截断到 top_k，各分数数组与文档保持下标对齐。

        医疗模型下「一个推荐条目 = 一个检索单元」（C2 §3.1），入库 _id 即业务 ID
        （rec_id / doc_id / drug_id / term_id），天然唯一，无需再按 (law_id, article_number)
        聚合回取整篇原文（原法规版逻辑已随 BE-15 移除）。
        """
        ids = raw_results.get('ids')
        if not ids or not ids[0]:
            return raw_results

        seen = set()
        picked: List[int] = []
        for i in range(len(ids[0])):
            key = ids[0][i]
            if key in seen:
                continue
            seen.add(key)
            picked.append(i)
            if len(picked) >= top_k:
                break

        def _pick(array_key: str):
            arr = raw_results.get(array_key)
            if not arr or not arr[0]:
                return None
            return [[arr[0][j] for j in picked]]

        result = {
            'ids': _pick('ids'),
            'documents': _pick('documents'),
            'metadatas': _pick('metadatas'),
            'distances': _pick('distances'),
        }
        if raw_results.get('_scores') and raw_results['_scores'][0]:
            result['_scores'] = _pick('_scores')
        if raw_results.get('_similarities') and raw_results['_similarities'][0]:
            result['_similarities'] = _pick('_similarities')
        return result

    @staticmethod
    def _format_results(results: Dict) -> List[Dict]:
        """把 repo 的检索结果字典转为统一的展示结构（医疗字段）。

        结果字段 = 通用字段（content / item_id / score / _cosine）+ metadata 全文
        （metadata 已由仓库层按 §5.7.2 白名单裁剪，含 data_type / cancer_type /
        scenario / evidence_level / rec_strength / breadcrumb / refs / topics_details 等）。
        """
        formatted: List[Dict] = []
        ids = results.get('ids')
        if not ids or not ids[0]:
            return formatted

        sims = results.get('_similarities')
        for i in range(len(ids[0])):
            distance = results['distances'][0][i]
            similarity = 1 / (1 + distance)
            cosine = sims[0][i] if (sims and sims[0] and i < len(sims[0])) else None
            metadata = results['metadatas'][0][i]

            item = {
                'content': results['documents'][0][i],
                'item_id': ids[0][i],
                'score': similarity,
                '_cosine': cosine,
            }
            item.update(metadata)
            formatted.append(item)

        return formatted

    def _enhance_query(self, query: str) -> str:
        """查询增强（医疗）。

        当前直接返回原查询：癌种别名 / 临床条件（分期 / 分子 / 治疗线数）的扩展归
        BE-16（query_decomposer）；此处保留方法作为唯一扩展点，避免调用方改动。
        """
        return query

    def _rrf_merge_results(self, results_list: List[List[Dict]], rrf_k: int = 60) -> List[Dict]:
        """RRF 合并多组结果（按 item_id 归一，缺失时回落 content）。"""
        scores: Dict[str, float] = {}
        sources: Dict[str, Dict] = {}

        for results in results_list:
            for rank, doc in enumerate(results, start=1):
                key = doc.get('item_id') or doc.get('content', '')
                scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
                if key not in sources:
                    sources[key] = doc

        merged = []
        for key, rrf_score in scores.items():
            doc = sources[key]
            doc["rrf_score"] = rrf_score
            merged.append(doc)

        merged.sort(key=lambda x: x["rrf_score"], reverse=True)
        return merged

    def _expand_context(self, results: List[Dict]) -> List[Dict]:
        """同指南上下文扩展（BE-15）：把命中条目所在指南的「相邻条目」补到结果尾部。

        医疗模型下推荐条目之间无「第X条」式互引（原法规版引用链已移除），改为按
        「同 doc_id + 同节（breadcrumb 前缀）优先」补齐同指南的相邻条目，帮助用户
        在不改查询的情况下看到同一节/同一指南的关联推荐。

        扩展项追加在原有结果之后且 score 置 0，不挤占主结果排序位置；单次最多补入
        settings.reference_expand_max 条。扩展失败静默降级为不扩展，不影响主检索链路。
        """
        if not settings.reference_expand_enabled or not results:
            return results

        seeds = results[: settings.reference_expand_sources]
        existing = {r.get("item_id") for r in results if r.get("item_id")}
        expanded: List[Dict] = []

        for seed in seeds:
            doc_id = seed.get("doc_id")
            if not doc_id:
                continue
            breadcrumb = seed.get("breadcrumb") or ""
            # 同节前缀：去掉最后一段（本节的条目视为兄弟），无「/」时用整段
            prefix = breadcrumb.rsplit("/", 1)[0] if "/" in breadcrumb else breadcrumb

            try:
                docs = self.repo.get_doc_context_recs(
                    doc_id, existing, prefix, settings.reference_expand_max
                )
            except Exception:
                continue

            for doc in docs:
                item_id = doc.get("item_id")
                if not item_id or item_id in existing:
                    continue
                existing.add(item_id)
                # 上下文条目不是语义命中：score 置 0、无余弦（前端不显示百分比）
                doc["score"] = 0.0
                doc["_cosine"] = None
                doc["match_type"] = "context"
                doc["retrieval_hop"] = 2
                doc["referenced_by"] = seed.get("item_id") or breadcrumb
                doc["cross_doc"] = False
                expanded.append(doc)
                if len(expanded) >= settings.reference_expand_max:
                    return results + expanded

        return results + expanded

    def search(self, query: str, top_k: int = 5,
               filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        搜索知识库内容（纯向量检索路径）。

        参数:
            query: 搜索关键词
            top_k: 返回数量
            filters: 过滤条件字典（键为 ES 字段名，如 cancer_type / doc_type / scenario /
                     stage / biomarker / data_type / "topics_details.label_zh"；多值列表按 OR）
        """
        where_filter = dict(filters) if filters else {}

        if query.strip():
            enhanced_query = self._enhance_query(query)
            results = self.repo.query([enhanced_query], n_results=max(top_k * 3, 20), where=where_filter)
        else:
            results = self.repo.query_with_filters(n_results=max(top_k * 3, 20), where=where_filter)

        # 候选窗口扩展：有 reranker 时保留更多候选供精排
        reranker_available = settings.reranker_enabled
        dedup_k = max(top_k * 3, 50) if reranker_available else top_k
        results = self._deduplicate_by_id(results, dedup_k)
        formatted_results = self._format_results(results)

        # 两阶段精排：前 reranker_window 条精排，其余按 RRF 顺序拼接
        formatted_results = self._rerank_two_stage(query=query, candidates=formatted_results)
        return self._attach_match_scores(formatted_results)

    def bm25_search(self, query: str, top_k: int = 20,
                    filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """仅 BM25 全文检索"""
        settings.reranker_enabled = False

        where_filter = dict(filters) if filters else {}
        enhanced_query = self._enhance_query(query)
        bm25_results = self.repo._bm25_search(enhanced_query, top_k, where_filter)

        formatted_results = []
        for hit in bm25_results:
            src = hit.get("_source", {})
            item = {
                'content': src.get('content', ''),
                'item_id': hit.get('_id'),
                'score': hit.get('_score', 0),
            }
            item.update(_medical_metadata(src))
            formatted_results.append(item)
        return formatted_results

    def _decompose_query(self, query: str) -> List[str]:
        """多跳 B：把复合查询拆成子查询列表（含锚定的原查询）。无需分解返回 []。

        锚定原查询是「不退化」的关键：分解只往候选池里加条目，原有召回的文档仍在
        池中，最终排序由统一的精排决定，不会因为某条子查询拆得不好而丢失主召回。
        """
        parts = decompose_query(query)
        if len(parts) < 2:
            return []
        uniq: List[str] = []
        for p in [query.strip()] + parts:
            if p and p not in uniq:
                uniq.append(p)
        return uniq if len(uniq) > 1 else []

    def _decomposed_search(self, sub_queries: List[str], top_k: int,
                           filters: Optional[Dict[str, Any]]) -> Optional[List[Dict]]:
        """并行执行各子查询检索（跳过精排）→ RRF 合并 → 合并后精排一次。

        子查询跳过精排是为了不把 cross-encoder 成本乘上子查询数：子查询只负责
        「多召回」，排序质量交给合并后的这一次精排。任一步失败返回 None，调用方降级单跳。
        """
        lists: List[List[Dict]] = []
        max_workers = max(1, min(len(sub_queries), settings.multihop_decompose_max_subqueries))
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [
                    ex.submit(self.hybrid_search, sq, top_k, filters, False, False)
                    for sq in sub_queries
                ]
                for f in futures:
                    try:
                        res = f.result()
                        if res:
                            lists.append(res)
                    except Exception as e:
                        logger.warning("子查询检索失败，忽略该子查询: %s", e)
        except Exception as e:
            logger.warning("查询分解并行检索失败，降级单跳: %s", e)
            return None

        if not lists:
            return None
        merged = self._rrf_merge_results(lists, rrf_k=60)
        # 统一用「原查询」做精排，保证与单跳路径同一打分基准（sub_queries[0] 即锚点）
        merged = self._rerank_two_stage(query=sub_queries[0], candidates=merged)
        merged = merged[:top_k]
        # 合并后补同指南上下文条目（不占 top_k 名额），再统一补齐展示分
        merged = self._expand_context(merged)
        return self._attach_match_scores(merged)

    def hybrid_search(self, query: str, top_k: int = 5,
                      filters: Optional[Dict[str, Any]] = None,
                      _decompose: bool = True,
                      _rerank: bool = True) -> List[Dict]:
        """
        混合检索（向量 + BM25 + RRF 融合），返回格式与 search() 完全一致。

        参数:
            query: 搜索关键词
            top_k: 返回数量
            filters: 过滤条件字典（键为 ES 字段名；多值列表按 OR）

        _decompose / _rerank 为内部参数：子查询检索时置 False，用于关闭「再分解」
        与「精排」，避免递归与成本放大；外部调用方无需传。
        """
        # 子查询检索跳过缓存：其缓存键用的是全局精排开关，与子查询实际关闭精排的
        # 口径不一致，读写都可能污染主查询结果，故直接绕过。
        use_cache = settings.search_cache_enabled and _rerank
        cache = get_search_cache() if use_cache else None
        cache_key = None
        if cache is not None:
            cache_key, cached = self._cache_lookup(query, top_k, filters)
            if cached is not None:
                return cached

        # 多跳 B：复合查询分解（仅顶层调用、且未关闭精排时触发；子查询不再分解）
        if _decompose and _rerank and settings.multihop_decompose_enabled:
            try:
                sub_queries = self._decompose_query(query)
            except Exception as e:
                logger.warning("查询分解失败，降级单跳: %s", e)
                sub_queries = []
            if len(sub_queries) > 1:
                merged = self._decomposed_search(sub_queries, top_k, filters)
                if merged:
                    if cache is not None and cache_key is not None:
                        cache.set(cache_key, merged)
                    return merged

        search_query = self._enhance_query(query) or query
        where_filter = dict(filters) if filters else {}

        if search_query.strip():
            results = self.repo.hybrid_search(
                query_text=search_query,
                n_results=max(top_k * 3, 20),
                where=where_filter or None,
            )
        else:
            results = self.repo.query_with_filters(n_results=max(top_k * 3, 20), where=where_filter)

        # 候选窗口扩展：有 reranker 时保留更多候选供精排（子查询关闭精排，收窄窗口）
        reranker_available = settings.reranker_enabled and _rerank
        dedup_k = max(top_k * 3, 50) if reranker_available else top_k
        results = self._deduplicate_by_id(results, dedup_k)
        formatted_results = self._format_results(results)

        # 两阶段精排：前 reranker_window 条精排，其余按 RRF 顺序拼接（子查询关闭时跳过）
        if _rerank:
            formatted_results = self._rerank_two_stage(query=search_query, candidates=formatted_results)

        # 主结果按 top_k 截断：上面的 dedup_k 只是为精排保留的候选余量，不应外泄。
        formatted_results = formatted_results[:top_k]

        # 上下文扩展在其后追加：扩展项是「同指南相邻条目」而非排名结果，不计入 top_k 名额。
        # 若先追加再截断，因主结果始终填满 top_k，扩展项会被永久截掉（多跳在检索页失效）。
        if _rerank:
            formatted_results = self._expand_context(formatted_results)

        # 展示用匹配度（真实余弦）统一计算：扩展补入的条目无余弦，置 None
        formatted_results = self._attach_match_scores(formatted_results)

        if cache is not None:
            cache.set(cache_key, formatted_results)

        return formatted_results

    def _cache_lookup(self, query: str, top_k: int,
                      filters: Optional[Dict[str, Any]]):
        """缓存查询，返回 (缓存键, 命中结果或 None)。

        键由「过滤条件 + 结果相关开关 + 归一化查询」构成：只按查询串比对会让
        「同一问题 + 不同过滤条件」错误复用结果；而评测脚本会在同一进程内切换
        reranker_enabled，若不把开关计入键，先跑的「无精排」结果会被「有精排」
        那轮直接命中，得到未精排的错误顺序。
        """
        if not query or not query.strip():
            return None, None

        filter_key = "|".join([
            f"top_k={top_k}",
            f"filters={_canonical_filters(filters)}",
            f"rerank={int(settings.reranker_enabled)}:{settings.reranker_window}",
            f"mhdec={int(settings.multihop_decompose_enabled)}",
        ])
        key = (filter_key, _normalize_query_for_cache(query))
        return key, get_search_cache().get(key)
