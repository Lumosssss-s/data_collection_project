"""相似推荐服务（医疗，BE-28）

两类相似推荐：
  - 相似指南：以指南的代表向量（各条目向量中位数）+ 主题重叠度，推荐同主题的其它指南
  - 相似条目：以单条推荐条目的向量，推荐语义相近的其它条目

核心思路（「主题优先 + 向量为辅」框架）：
  1. 主题硬过滤：只推荐与查询对象有主题重叠的结果（相似条目不做主题过滤）
  2. 主题加权排序：主题重叠度作为主要排序因子（加权 Jaccard）
  3. 向量相似度作为次要因子
  4. 多样性：跨癌种优先
"""
import logging
from typing import Dict, List, Optional

import numpy as np

from repositories.elasticsearch import ElasticsearchRepository

logger = logging.getLogger(__name__)


class SimilarGuideService:
    """相似指南 / 相似条目推荐服务（主题感知版）"""

    def __init__(self):
        self.repo = ElasticsearchRepository()

    # ===== 主题分析 =====

    @staticmethod
    def _compute_topic_overlap(query_topics: Dict[str, int], candidate_topics: Dict[str, int]) -> float:
        """加权 Jaccard 主题重叠度（高频主题的重叠更有意义），返回 0~1。"""
        if not query_topics or not candidate_topics:
            return 0.0
        common = set(query_topics) & set(candidate_topics)
        if not common:
            return 0.0
        weighted_intersection = sum(min(query_topics[t], candidate_topics[t]) for t in common)
        all_topics = set(query_topics) | set(candidate_topics)
        weighted_union = sum(max(query_topics.get(t, 0), candidate_topics.get(t, 0)) for t in all_topics)
        if weighted_union == 0:
            return 0.0
        return weighted_intersection / weighted_union

    # ===== 向量计算 =====

    @staticmethod
    def _compute_median_vector(items: List[Dict]) -> Optional[List[float]]:
        """对象所有条目向量的中位数向量（比均值更鲁棒），并做 L2 归一化。"""
        vectors = [it.get("embedding") for it in items if it.get("embedding")]
        if not vectors:
            return None
        arr = np.array(vectors, dtype=np.float32)
        median_vec = np.median(arr, axis=0)
        norm = np.linalg.norm(median_vec)
        if norm > 0:
            median_vec = median_vec / norm
        return median_vec.tolist()

    def _compute_representative_vector(self, items: List[Dict]) -> Optional[List[float]]:
        """代表性向量：均匀采样最多 20 个条目（避免长指南主导）后取中位数。"""
        if not items:
            return None
        sample_size = min(20, len(items))
        if sample_size >= len(items):
            sampled = items
        else:
            indices = np.linspace(0, len(items) - 1, sample_size, dtype=int)
            sampled = [items[i] for i in indices]
        return self._compute_median_vector(sampled)

    # ===== 核心方法：相似指南 =====

    def get_similar_guides(
        self,
        query_doc_id: str,
        top_k: int = 5,
        cancer_type_filter: Optional[str] = None,
    ) -> Dict:
        """
        根据 doc_id 查找最相似的 top_k 个指南（主题感知版）。

        算法：取查询指南各条目向量计算代表向量 → KNN 召回候选条目 → 按 doc_id 聚合
        → 主题硬过滤 → 主题重叠(60%) + 向量相似(40%) 综合排序 → 跨癌种多样性选择。
        """
        # 只取轻量元信息 + 主题计数 + 少量采样向量：
        # 全量向量与明细在 Python 侧解析要数秒，而代表向量最多只需 20 个样本、
        # 主题频次可由 ES nested 聚合直接算出。
        head = self.repo.get_doc_head(query_doc_id)
        if not head.get("found"):
            return {
                "query_doc_id": query_doc_id, "similar_guides": [],
                "total_found": 0, "message": "未找到该指南的条目向量数据",
            }

        query_title = head.get("title", "")
        query_cancer = head.get("cancer_type", "")
        item_count = head.get("item_count", 0)

        query_topic_dist = self.repo.get_docs_topic_counts([query_doc_id]).get(query_doc_id, {})
        query_topics_set = set(query_topic_dist.keys())

        sample_vecs = self.repo.get_doc_sample_vectors(query_doc_id, 20)
        rep_vector = (self._compute_representative_vector(
            [{"embedding": v} for v in sample_vecs]) if sample_vecs else None)
        if rep_vector is None:
            return {
                "query_doc_id": query_doc_id, "similar_guides": [],
                "total_found": 0, "message": "无法计算指南的代表性向量",
            }

        # KNN 召回候选条目（多取，后续过滤；限 REC，避免指南摘要文档混入条目推荐）
        raw = self.repo.knn_search_similar(
            query_vector=rep_vector,
            top_k=top_k * 8,
            exclude_doc_id=query_doc_id,
            cancer_type_filter=cancer_type_filter,
            data_type_filter="rec",
            min_score=0.2,
        )
        if not raw:
            return {
                "query_doc_id": query_doc_id, "similar_guides": [],
                "total_found": 0, "message": "未找到相似的指南",
            }

        # 按 doc_id 聚合
        doc_max_sim: Dict[str, float] = {}
        doc_items: Dict[str, List[Dict]] = {}
        doc_meta: Dict[str, Dict] = {}
        for it in raw:
            did = it["doc_id"]
            sim = it["similarity"]
            if did not in doc_max_sim:
                doc_max_sim[did] = sim
                doc_items[did] = []
                doc_meta[did] = {"title": it.get("title", ""), "cancer_type": it.get("cancer_type", "")}
            if sim > doc_max_sim[did]:
                doc_max_sim[did] = sim
            doc_items[did].append({
                "breadcrumb": it.get("breadcrumb", ""),
                "content_preview": it.get("content_preview", ""),
                "similarity": sim,
            })

        cand_topics = self.repo.get_docs_topic_counts(list(doc_max_sim.keys()))

        scored = []
        for did, max_sim in doc_max_sim.items():
            ct = cand_topics.get(did, {})
            # 主题硬过滤：必须有至少一个主题重叠（仅在有主题信息时启用）
            if query_topics_set and ct and not (query_topics_set & set(ct)):
                continue
            topic_overlap = self._compute_topic_overlap(query_topic_dist, ct) if ct else 0.0
            normalized_sim = (max_sim - 0.2) / 0.8 if max_sim > 0.2 else 0.0
            normalized_sim = max(0.0, min(1.0, normalized_sim))
            composite = 0.6 * topic_overlap + 0.4 * normalized_sim
            top_items = sorted(doc_items[did], key=lambda x: x["similarity"], reverse=True)[:3]
            scored.append({
                "doc_id": did,
                "title": doc_meta[did]["title"],
                "cancer_type": doc_meta[did]["cancer_type"],
                "similarity": round(max_sim, 4),
                "topic_overlap": round(topic_overlap, 4),
                "composite_score": round(composite, 4),
                "match_item_count": len(doc_items[did]),
                "top_matched_items": top_items,
                "shared_topics": list(query_topics_set & set(ct)),
            })

        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        selected = self._select_diverse_by_cancer(scored, top_k, query_cancer)

        similar_guides = [{
            "doc_id": e["doc_id"],
            "title": e["title"],
            "cancer_type": e["cancer_type"],
            "similarity": e["similarity"],
            "composite_score": e["composite_score"],
            "topic_overlap": e["topic_overlap"],
            "match_item_count": e["match_item_count"],
            "shared_topics": e["shared_topics"],
            "top_matched_items": e["top_matched_items"],
        } for e in selected]

        return {
            "query_doc_id": query_doc_id,
            "query_title": query_title,
            "query_cancer_type": query_cancer,
            "query_item_count": item_count,
            "query_topics": list(query_topics_set),
            "similar_guides": similar_guides,
            "total_found": len(scored),
            "returned_count": len(similar_guides),
        }

    @staticmethod
    def _select_diverse_by_cancer(scored: List[Dict], top_k: int, query_cancer: str) -> List[Dict]:
        """从评分结果中选择 top_k，优先跨癌种多样性（先取非查询癌种，再补同癌种）。"""
        if not scored:
            return []
        by_cancer: Dict[str, List[Dict]] = {}
        for entry in scored:
            by_cancer.setdefault(entry["cancer_type"], []).append(entry)

        selected: List[Dict] = []
        used = set()
        other = [c for c in by_cancer if c != query_cancer]
        same = [c for c in by_cancer if c == query_cancer]

        for c in other + same:
            cands = by_cancer[c]
            if cands and cands[0]["doc_id"] not in used:
                selected.append(cands[0])
                used.add(cands[0]["doc_id"])
            if len(selected) >= top_k:
                break

        if len(selected) < top_k:
            for entry in scored:
                if len(selected) >= top_k:
                    break
                if entry["doc_id"] not in used:
                    selected.append(entry)
                    used.add(entry["doc_id"])

        return selected[:top_k]

    # ===== 核心方法：相似条目 =====

    def get_similar_items(
        self,
        query_item_id: str,
        top_k: int = 10,
        cancer_type_filter: Optional[str] = None,
    ) -> Dict:
        """基于单条推荐条目的相似条目推荐（纯向量 KNN，排除同指南自身条目）。"""
        doc = self.repo.get(query_item_id)
        if not doc:
            return {"query_item_id": query_item_id, "similar_items": [], "message": "未找到该条目"}

        query_vector = doc.get("embedding")
        if not query_vector:
            return {"query_item_id": query_item_id, "similar_items": [], "message": "该条目没有向量数据"}

        query_doc_id = doc.get("doc_id", "")

        raw = self.repo.knn_search_similar(
            query_vector=query_vector,
            top_k=top_k,
            exclude_doc_id=query_doc_id,
            cancer_type_filter=cancer_type_filter,
            data_type_filter="rec",
            min_score=0.2,
        )

        similar_items = [{
            "item_id": it["id"],
            "doc_id": it["doc_id"],
            "rec_id": it["rec_id"],
            "title": it["title"],
            "cancer_type": it["cancer_type"],
            "breadcrumb": it["breadcrumb"],
            "content_preview": it["content_preview"],
            "similarity": round(it["similarity"], 4),
        } for it in raw[:top_k]]

        return {
            "query_item_id": query_item_id,
            "query_content": doc.get("content", "")[:200],
            "query_breadcrumb": doc.get("breadcrumb", ""),
            "query_doc_id": query_doc_id,
            "similar_items": similar_items,
            "total_found": len(raw),
            "returned_count": len(similar_items),
        }
