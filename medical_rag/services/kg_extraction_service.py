"""
LLM 实体关系抽取服务（医疗 v2.0）
--------------------------------
从肿瘤循证推荐条目文本中自动提取 {实体类型, 关系类型, 实体类型} 三元组，
用于构建以「癌种」为中心的肿瘤知识图谱。

使用方式：
    service = KGExtractionService()
    triples = service.extract_from_recs(recs)
"""

import json
import logging
import re
from typing import List, Dict

from openai import OpenAI

from core.config import settings
from repositories.elasticsearch import ElasticsearchRepository
from services.entity_disambiguation_service import EntityDisambiguationService

logger = logging.getLogger(__name__)

# ---- 肿瘤知识图谱本体定义（BE-12：8 类实体 + 9 类关系）----
# 实体为「全局」概念（癌种/基因/药物等跨指南唯一），故消歧时不做来源内局部化。
MEDICAL_ONTOLOGY = {
    "entities": {
        "Cancer":          {"label": "癌种",       "description": "肿瘤类型（如肺癌、乳腺癌、结直肠癌）"},
        "Gene":            {"label": "基因/标志物", "description": "驱动基因或分子标志物（如 EGFR、ALK、HER2、PD-L1、MSI）"},
        "Drug":            {"label": "药物",       "description": "抗肿瘤药物（如奥希替尼、帕博利珠单抗）"},
        "Treatment":       {"label": "治疗方式",   "description": "治疗手段（如靶向治疗、免疫治疗、化疗、放疗、手术）"},
        "Stage":           {"label": "分期",       "description": "肿瘤分期（如 I 期、II 期、III 期、IV 期、TNM）"},
        "Symptom":         {"label": "症状",       "description": "症状或体征（如咳嗽、咯血、胸痛、消瘦）"},
        "Examination":     {"label": "检查",       "description": "诊断或监测手段（如 CT、MRI、病理活检、基因检测）"},
        "AdverseReaction": {"label": "不良反应",   "description": "药物或治疗引发的不良反应（如皮疹、腹泻、间质性肺炎）"},
    },
    "relations": [
        {"type": "has_symptom",          "label": "表现为症状", "description": "癌种可表现出某症状（Cancer → Symptom）"},
        {"type": "diagnosed_by",         "label": "通过检查诊断", "description": "癌种通过某检查确诊或评估（Cancer → Examination）"},
        {"type": "has_stage",            "label": "分为分期",   "description": "癌种按某分期系统划分（Cancer → Stage）"},
        {"type": "treated_by",           "label": "采用治疗",   "description": "癌种采用某治疗方式（Cancer → Treatment）"},
        {"type": "uses_drug",            "label": "可用药物",   "description": "癌种可应用某药物（Cancer → Drug）"},
        {"type": "targets",              "label": "作用靶点",   "description": "药物作用于某基因/靶点（Drug → Gene）"},
        {"type": "biomarker_of",         "label": "标志物",     "description": "基因/标志物是某癌种的标志物（Gene → Cancer）"},
        {"type": "has_adverse_reaction", "label": "引发不良反应", "description": "药物引发某不良反应（Drug → AdverseReaction）"},
        {"type": "combined_with",        "label": "联合用药",   "description": "药物与另一药物联合使用（Drug → Drug）"},
    ],
}

_ENTITY_TYPES = set(MEDICAL_ONTOLOGY["entities"])
_RELATION_TYPES = {r["type"] for r in MEDICAL_ONTOLOGY["relations"]}


class KGExtractionService:
    """基于 LLM 的实体关系抽取服务（医疗）"""

    def __init__(self):
        self.api_key = settings.llm_api_key or ""
        self.base_url = settings.llm_api_base_url or "https://api.deepseek.com/v1"
        self.model = settings.llm_extraction_model or "deepseek-flash"
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.repo = ElasticsearchRepository()

    def extract_from_recs(self, recs: List[Dict], batch_size: int = 5) -> List[Dict]:
        """
        对一批推荐条目批量抽取实体关系三元组

        Args:
            recs: 推荐条目列表，每项需包含：
                - rec_id: 推荐条目编号（作为 source_ref）
                - content: 条目正文
                - breadcrumb: (可选) 章节定位（如「第四章 晚期NSCLC治疗 > 靶向治疗」）
                - cancer_type: (可选) 所属癌种
            batch_size: 每批送入 LLM 的条目数（默认 5）

        Returns:
            三元组列表，格式：
            [{
                "head": {"id": str, "type": str, "name": str},
                "relation": str,
                "tail": {"id": str, "type": str, "name": str},
                "source_ref": str,
                "cancer_type": str,
                "confidence": float
            }, ...]
        """
        if not recs:
            return []

        all_triples: List[Dict] = []
        for i in range(0, len(recs), batch_size):
            batch = recs[i:i + batch_size]
            try:
                triples = self._extract_batch(batch)
                all_triples.extend(triples)
                logger.info(f"[KGExtraction] 批次 {i // batch_size + 1}: 提取 {len(triples)} 个三元组")
            except Exception as e:
                logger.warning(f"[KGExtraction] 批次 {i // batch_size + 1} 提取失败: {e}")
                # 单个批次失败不影响整体
                continue

        # 去重
        all_triples = self._deduplicate(all_triples)
        logger.info(f"[KGExtraction] 总计提取 {len(all_triples)} 个唯一三元组")
        return all_triples

    def _extract_batch(self, batch: List[Dict]) -> List[Dict]:
        """调用 LLM 抽取单个批次的三元组"""
        prompt = self._build_prompt(batch)

        create_kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        extra_body = settings.llm_extra_body()
        if extra_body:
            create_kwargs["extra_body"] = extra_body
        response = self.client.chat.completions.create(**create_kwargs)
        text = response.choices[0].message.content

        return self._parse_response(text, batch)

    def _build_prompt(self, batch: List[Dict]) -> str:
        """构建抽取提示词（输入为推荐条目）"""
        recs_text = ""
        for i, rec in enumerate(batch):
            breadcrumb = rec.get("breadcrumb", "")
            content = rec.get("content", "")
            recs_text += f"<rec index=\"{i}\">\n"
            if breadcrumb:
                recs_text += f"章节：{breadcrumb}\n"
            recs_text += f"内容：{content}\n"
            recs_text += "</rec>\n\n"

        entity_types_str = "\n".join([
            f"  - {k}: {v['label']} — {v['description']}"
            for k, v in MEDICAL_ONTOLOGY["entities"].items()
        ])
        relation_types_str = "\n".join([
            f"  - {r['type']}: {r['label']} — {r['description']}"
            for r in MEDICAL_ONTOLOGY["relations"]
        ])

        prompt = f"""你是肿瘤学知识工程专家。请从以下肿瘤循证推荐条目中提取医学实体和关系，构建肿瘤知识图谱。

实体类型定义：
{entity_types_str}

关系类型定义（括号内为头实体→尾实体的类型约束）：
{relation_types_str}

请分析每一条推荐条目，提取其中包含的实体和关系，输出 JSON 格式的三元组列表。
每条推荐条目可能产出 1-5 个三元组。

注意：
1. 实体名称尽量使用规范通用名（如「非小细胞肺癌」统一为「肺癌」、「泰瑞沙」统一为「奥希替尼」）
2. 置信度 (confidence) 在 0.0-1.0 之间，明确匹配给 0.9+，推断匹配给 0.6-0.8
3. 严格遵循关系定义中的头尾实体类型约束；不适配的关系请勿输出
4. 如果条目内容不包含任何可提取的实体关系，输出空列表 []
5. 同一实体在不同条目中重复出现时，使用相同的实体 name

{recs_text}

请严格按照以下 JSON 格式输出（不要包含 markdown 代码块标记，直接输出 JSON）：
{{
    "triples": [
        {{
            "head": {{"name": "实体名称", "type": "实体类型"}},
            "relation": "关系类型",
            "tail": {{"name": "实体名称", "type": "实体类型"}},
            "rec_index": 0,
            "confidence": 0.95
        }}
    ]
}}"""
        return prompt

    def _parse_response(self, text: str, batch: List[Dict]) -> List[Dict]:
        """解析 LLM 返回的 JSON 结果"""
        # 清理可能的 markdown 包裹
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 部分
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.warning(f"[KGExtraction] JSON 解析失败，原始响应: {text[:200]}")
                    return []
            else:
                return []

        triples = data.get("triples", [])
        if not isinstance(triples, list):
            return []

        results = []
        for t in triples:
            if not isinstance(t, dict):
                continue
            head = t.get("head", {})
            tail = t.get("tail", {})
            relation = t.get("relation", "")
            rec_idx = t.get("rec_index", 0)

            if not head or not tail or not relation:
                continue

            # 校验实体类型：不在本体内的丢弃（医疗本体为受控词表，不做兜底归类）
            head_type = head.get("type", "")
            tail_type = tail.get("type", "")
            if head_type not in _ENTITY_TYPES or tail_type not in _ENTITY_TYPES:
                logger.debug(f"[KGExtraction] 丢弃未知实体类型: {head_type}/{tail_type}")
                continue

            # 校验关系类型
            if relation not in _RELATION_TYPES:
                continue

            # 定位来源推荐条目
            source_ref = ""
            cancer_type = ""
            if isinstance(rec_idx, int) and 0 <= rec_idx < len(batch):
                source_ref = batch[rec_idx].get("rec_id", "")
                cancer_type = batch[rec_idx].get("cancer_type", "")

            confidence = t.get("confidence", 0.8)
            if not isinstance(confidence, (int, float)):
                confidence = 0.8
            confidence = max(0.0, min(1.0, float(confidence)))

            results.append({
                "head": {
                    "id": self._make_entity_id(head.get("name", ""), head_type),
                    "type": head_type,
                    "name": head.get("name", ""),
                },
                "relation": relation,
                "tail": {
                    "id": self._make_entity_id(tail.get("name", ""), tail_type),
                    "type": tail_type,
                    "name": tail.get("name", ""),
                },
                "source_ref": source_ref,
                "cancer_type": cancer_type,
                "confidence": confidence,
            })

        return results

    @staticmethod
    def _make_entity_id(name: str, etype: str) -> str:
        """生成规范化实体 ID"""
        clean = re.sub(r'[^\w\u4e00-\u9fff]', '_', name.strip())
        clean = re.sub(r'_+', '_', clean).strip('_')
        return f"{etype}::{clean}" if clean else f"{etype}::unknown"

    @staticmethod
    def _deduplicate(triples: List[Dict]) -> List[Dict]:
        """去重：相同 head-relation-tail 只保留置信度最高的"""
        seen = {}
        for t in triples:
            key = (t["head"]["id"], t["relation"], t["tail"]["id"])
            if key not in seen or t["confidence"] > seen[key]["confidence"]:
                seen[key] = t
        return list(seen.values())

    def get_triples_cached(
        self,
        source_id: str,
        recs: List[Dict],
        force_refresh: bool = False,
    ) -> Dict:
        """
        获取某来源（指南）的三元组：优先读知识层缓存，未命中才调用 LLM 抽取。

        命中条件为「缓存指纹 == 当前来源指纹」，因此：
          - 新增指南：只对新 source_id 抽取，已有指南零 LLM 调用；
          - 指南更新：只有该指南指纹变化并重抽，其余指南不受影响；
          - 重复访问：直接读 ES，不再触发一次完整抽取。

        说明：抽取结果为空时不写缓存元信息（无文档即无指纹），
        下次请求会重抽。这一行为是有意为之 —— LLM 批次失败或响应异常
        时同样返回空列表，重抽等价于自动重试。

        Args:
            source_id: 来源 ID（指南 doc_id）
            recs: 推荐条目列表（仅在缓存未命中时使用）
            force_refresh: 为 True 时忽略缓存，强制重新抽取（本体变更后使用）

        Returns:
            {"triples": List[Dict], "cache_hit": bool, "fingerprint": str}
        """
        repo = self.repo
        fingerprint = repo.compute_doc_fingerprint(source_id)

        # 指纹为空说明来源不存在，无法判断失效，直接走实时抽取
        if not force_refresh and fingerprint:
            meta = repo.get_kg_cache_meta(source_id)
            if meta and meta.get("fingerprint") == fingerprint and meta.get("triple_count"):
                logger.info(
                    f"[KGExtraction] 命中知识层缓存: source_id={source_id}, "
                    f"复用 {meta['triple_count']} 条三元组，跳过 LLM 抽取"
                )
                return {
                    "triples": repo.get_kg_triples(source_id),
                    "cache_hit": True,
                    "fingerprint": fingerprint,
                }

        triples = self.extract_from_recs(recs)

        # 抽取结果为空时不能直接覆盖已有结果：LLM 输出存在抖动
        # （实测同一段文本两次抽取结果条数可能不同），
        # 若此时清空，一次抖动就会把已建好的图谱整体抹掉。
        # 因此：旧结果存在且指纹未变 -> 判定为抖动，保留旧结果；
        #       指纹已变（来源被修订为无可提取关系）或旧结果不存在 -> 正常走落库（含清除）。
        if not triples:
            meta = repo.get_kg_cache_meta(source_id)
            if meta and meta.get("triple_count") and meta.get("fingerprint") == fingerprint:
                logger.warning(
                    f"[KGExtraction] 本次抽取为空但缓存指纹未变，保留已有 "
                    f"{meta['triple_count']} 条三元组: source_id={source_id}"
                )
                return {
                    "triples": repo.get_kg_triples(source_id),
                    "cache_hit": True,
                    "fingerprint": fingerprint,
                }

        cancer_type = recs[0].get("cancer_type", "") if recs else ""

        # 实体消歧（L1 规范化 + L2 别名表 + L3 向量对齐 + L4 类型约束）：
        # 就地补写 head/tail 的 canonical_id，并把规范实体同步到实体词典。
        # 消歧失败不阻断抽取结果落库 —— 此时 canonical_id 退化为原始 id，
        # 检索与图谱展示仍可用，只是未做归并。
        try:
            disambiguator = EntityDisambiguationService(self.repo)
            result = disambiguator.canonicalize_and_index(triples, source_id, cancer_type)
            stats = result["stats"]
            logger.info(
                f"[KGExtraction] 实体消歧完成: source_id={source_id}, "
                f"{stats['raw_entities']} -> {stats['merged_entities']} 个实体"
                f"（L3 向量归并 {stats.get('vector_aligned', 0)} 个，"
                f"候选待人工确认 {stats.get('vector_candidates', 0)} 个）"
            )
        except Exception as e:
            logger.warning(f"[KGExtraction] 实体消歧失败，本次以原始实体落库: {e}")

        saved = repo.save_kg_triples(
            source_id,
            triples,
            cancer_type=cancer_type,
            fingerprint=fingerprint,
        )
        if saved < 0:
            logger.warning(f"[KGExtraction] 三元组落库失败，本次结果未缓存: source_id={source_id}")

        return {"triples": triples, "cache_hit": False, "fingerprint": fingerprint}

    def extract_and_format_for_graph(self, recs: List[Dict]) -> Dict:
        """
        抽取实体关系并格式化为图谱数据结构
        """
        return self.format_graph(self.extract_from_recs(recs))

    def format_graph(self, triples: List[Dict]) -> Dict:
        """将三元组列表格式化为前端图谱数据结构（无副作用，不发 LLM 请求）"""
        # 构建节点
        entity_map = {}
        for t in triples:
            for side in ("head", "tail"):
                ent = t[side]
                eid = ent["id"]
                if eid not in entity_map:
                    entity_map[eid] = {
                        "id": eid,
                        "label": ent["name"],
                        "title": ent["name"],
                        "entity_type": ent["type"],
                        "entity_label": MEDICAL_ONTOLOGY["entities"].get(ent["type"], {}).get("label", "实体"),
                        "entity_color": _ENTITY_COLORS.get(ent["type"], "#6B7280"),
                        "entity_shape": _ENTITY_SHAPES.get(ent["type"], "ellipse"),
                        "degree": 0,
                        "importance_score": 0,
                        "is_core": False,
                    }

        # 构建边
        edge_list = []
        for t in triples:
            edge_list.append({
                "from": t["head"]["id"],
                "to": t["tail"]["id"],
                "type": t["relation"],
                "relation_type": t["relation"],
                "relation_label": _RELATION_LABELS.get(t["relation"], "关联"),
                "label": _RELATION_LABELS.get(t["relation"], "关联"),
                "similarity": t["confidence"],
                "weight": max(1, round(t["confidence"] * 5)),
                "color": "#A78BFA",
                "source_ref": t.get("source_ref", ""),
                "cancer_type": t.get("cancer_type", ""),
            })

        # 计算度数
        nodes = list(entity_map.values())
        deg = {n["id"]: 0 for n in nodes}
        for e in edge_list:
            deg[e["from"]] = deg.get(e["from"], 0) + 1
            deg[e["to"]] = deg.get(e["to"], 0) + 1
        for n in nodes:
            n["degree"] = deg.get(n["id"], 0)
            n["importance_score"] = round(min(1.0, n["degree"] / max(max(deg.values(), default=1), 1)), 3)

        return {
            "nodes": nodes,
            "edges": edge_list,
            "node_count": len(nodes),
            "edge_count": len(edge_list),
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edge_list),
                "entity_type_distribution": {
                    et: len([n for n in nodes if n["entity_type"] == et])
                    for et in {n["entity_type"] for n in nodes}
                },
                "schema_version": "extraction-v2",
            },
            "schema_version": "extraction-v2",
        }


# ---- 颜色/形状映射（按实体类型着色，医疗本体）----
_ENTITY_COLORS = {
    "Cancer": "#DC2626",           # 癌种：红
    "Gene": "#7C3AED",             # 基因：紫
    "Drug": "#2563EB",             # 药物：蓝
    "Treatment": "#059669",        # 治疗：绿
    "Stage": "#D97706",            # 分期：橙
    "Symptom": "#0891B2",          # 症状：青
    "Examination": "#4F46E5",      # 检查：靛
    "AdverseReaction": "#BE123C",  # 不良反应：玫红
}
_ENTITY_SHAPES = {
    "Cancer": "ellipse",
    "Gene": "diamond",
    "Drug": "roundRect",
    "Treatment": "roundRect",
    "Stage": "triangle",
    "Symptom": "ellipse",
    "Examination": "roundRect",
    "AdverseReaction": "triangle",
}
_RELATION_LABELS = {
    "has_symptom": "表现为症状",
    "diagnosed_by": "通过检查诊断",
    "has_stage": "分为分期",
    "treated_by": "采用治疗",
    "uses_drug": "可用药物",
    "targets": "作用靶点",
    "biomarker_of": "标志物",
    "has_adverse_reaction": "引发不良反应",
    "combined_with": "联合用药",
}
