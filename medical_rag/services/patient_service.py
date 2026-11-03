"""患者端服务（NM-06，主方案 §4.2 方案 A，移动优先）。

患者端页面组共用能力：
  - 用药指导：药品说明书（A4）→ 患者可读话术（LLM 改写，严守「仅基于说明书」）
  - 药物列表 / 搜索（供患者端用药指导页入口）

其余患者端页面复用既有模块：
  - 疾病科普 → `GET /diseases/{id}?version=patient`（NM-01 已提供患者版）
  - 患者预问诊 → `/preconsult/*`（NM-02）
  - 随访反馈 → `/followup/*`（NM-03）

**强制约束**：不给诊断结论、不给处方；输出附免责声明与就医指引。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from repositories.elasticsearch import ElasticsearchRepository
from services.qa_service import QAService

logger = logging.getLogger(__name__)

# A4 `adverse_reactions[].frequency` 枚举 → 中文
FREQ_LABELS: Dict[str, str] = {
    "very_common": "很常见",
    "common": "常见",
    "uncommon": "不常见",
    "rare": "罕见",
    "very_rare": "很罕见",
}

DISCLAIMER = "本条信息仅供参考，不构成诊断，也不构成用药建议，具体请遵医嘱。"

# 就医指引（患者端固定展示）
SEEK_HELP = "如出现严重不适、症状加重或任何让您担心的情况，请及时联系医生或前往医院就诊。"


class PatientService:
    """患者端：用药说明书患者版 + 药物列表。"""

    def __init__(self, repo: Optional[ElasticsearchRepository] = None):
        self.repo = repo or ElasticsearchRepository()
        self._qa = QAService()

    # ============================================================
    #  药物列表 / 搜索
    # ============================================================
    def list_drugs(self, query: str = "", cancer_type: str = "") -> Dict:
        """药物列表（可按药名搜索 / 癌种过滤），仅供患者端选择入口。"""
        try:
            items = self.repo.list_items(data_type="drug", cancer_type=cancer_type or None)
        except Exception as e:
            logger.warning(f"[Patient] 药物列表失败: {e}")
            items = []

        query = (query or "").strip().lower()
        out = []
        for it in items or []:
            name = str(it.get("generic_name") or it.get("title") or "").strip()
            brand = "、".join(it.get("brand_names") or [])
            aliases_zh = [str(a) for a in (it.get("aliases_zh") or []) if a]
            alias_joined = "、".join(aliases_zh)
            if (query and query not in name.lower()
                    and query not in brand.lower()
                    and query not in alias_joined.lower()):
                continue
            out.append({
                "drug_id": it.get("drug_id") or it.get("item_id") or "",
                "generic_name": name,
                "brand_names": it.get("brand_names") or [],
                "cancer_type": it.get("cancer_type", ""),
                # 用药安全 v2 字段透传（2026-11-02，零 LLM）：
                # has_boxed_warning 由 boxed_warning 非空推导；列表不返回整段
                # 警示文本，避免 payload 膨胀。
                "cancer_types": it.get("cancer_types") or [],
                "guideline_use_cancers": it.get("guideline_use_cancers") or [],
                "has_boxed_warning": bool(it.get("boxed_warning")),
                "aliases_zh": aliases_zh,
            })

        degraded = len(items or []) == 0
        return {
            "total": len(out),
            "items": out[:100],
            "degraded": degraded,
            "note": "" if not degraded else "药品说明书数据未就绪（A4 待入库）。",
        }

    # ============================================================
    #  说明书患者版
    # ============================================================
    def get_drug_patient(self, drug_id: str) -> Optional[Dict]:
        """取说明书患者版；药品不存在返回 None。"""
        raw = self.repo.get(drug_id)
        if not raw:
            return None

        base = self._base_fields(raw)
        plain = self._llm_plainify(base)

        # LLM 失败时降级为「结构化直出 + 频率中文」，仍可用
        degraded = plain is None
        if plain is None:
            plain = self._fallback_plain(base)

        # 说明书相互作用原文透传：逐字来自 ES _source，不截断/改写/翻译，
        # 仅供前端折叠层溯源展示，不参与上方白话生成逻辑。
        raw_interactions = list(raw.get("interactions") or [])

        return {
            "drug_id": drug_id,
            "generic_name": base["generic_name"],
            "brand_names": base["brand_names"],
            "indication_note": raw.get("indication_note") or "",
            "plain": plain,
            "raw_interactions": raw_interactions,
            "interaction_count": len(raw_interactions),
            "disclaimer": DISCLAIMER,
            "seek_help": SEEK_HELP,
            "degraded": degraded,
            "note": "" if not degraded else "患者版话术生成失败，已按说明书结构化展示。",
        }

    @staticmethod
    def _base_fields(raw: Dict) -> Dict:
        dosage = raw.get("dosage") or {}
        if not isinstance(dosage, dict):
            dosage = {"standard": str(dosage)}
        ars = []
        for a in raw.get("adverse_reactions") or []:
            if isinstance(a, dict):
                ars.append({
                    "term": a.get("term") or "",
                    "frequency": FREQ_LABELS.get(a.get("frequency") or "", a.get("frequency") or ""),
                    "ctcae_hint": a.get("ctcae_hint") or "",
                })
        return {
            "generic_name": raw.get("generic_name") or raw.get("title") or "",
            "brand_names": raw.get("brand_names") or [],
            "indications": raw.get("indications") or [],
            "dosage_standard": dosage.get("standard", ""),
            "dosage_adjustment": dosage.get("adjustment", ""),
            "contraindications": raw.get("contraindications") or [],
            "adverse_reactions": ars,
            "interactions": raw.get("interactions") or [],
        }

    def _llm_plainify(self, base: Dict) -> Optional[Dict]:
        """LLM 改成患者可读话术：**仅基于给定说明书内容**，不得新增或推断。"""
        prompt = f"""你是面向患者用药科普的助手。请把下面药品说明书内容改写成**患者能看懂**的话。

【药品说明书内容】
通用名：{base['generic_name']}
商品名：{'、'.join(base['brand_names']) or '无'}
适应证：{'；'.join(base['indications']) or '未提供'}
常规用法：{base['dosage_standard'] or '未提供'}
剂量调整：{base['dosage_adjustment'] or '未提供'}
禁忌：{'；'.join(base['contraindications']) or '未提供'}
常见不良反应：{'；'.join(a['term'] + '(' + a['frequency'] + ',' + a['ctcae_hint'] + ')' for a in base['adverse_reactions']) or '未提供'}
相互作用：{'；'.join(base['interactions']) or '未提供'}

要求：
1. **只能依据上述内容**改写，不得新增、推断或补充任何未提供的信息；
2. 语言通俗、温和、正向，每句不超过 40 字；
3. 不给出诊断结论，不给出具体用药建议（如「你应该吃多少」），只陈述说明书内容；
4. 不恐吓，但如实说明需就医的情况。

请仅输出如下 JSON（不要解释、不要用代码块包裹）：
{{
  "what_is_it": "这个药是做什么用的（通俗一句话）",
  "how_to_use": "说明书中的常规用法（通俗）",
  "cautions": ["注意事项，逐条"],
  "side_effects": [{{"term": "不良反应名称", "plain": "通俗说明", "when_to_seek_help": "何时需就医"}}],
  "seek_help": "出现哪些情况需要及时就医"
}}"""

        try:
            raw = self._qa._call_llm_with_model(prompt)
            obj = self._parse_json(raw)
            if isinstance(obj, dict):
                return {
                    "what_is_it": str(obj.get("what_is_it") or "").strip(),
                    "how_to_use": str(obj.get("how_to_use") or "").strip(),
                    "cautions": [str(x) for x in (obj.get("cautions") or []) if x],
                    "side_effects": [
                        {
                            "term": str(s.get("term") or ""),
                            "plain": str(s.get("plain") or ""),
                            "when_to_seek_help": str(s.get("when_to_seek_help") or ""),
                        }
                        for s in (obj.get("side_effects") or []) if isinstance(s, dict)
                    ],
                    "seek_help": str(obj.get("seek_help") or "").strip(),
                }
        except Exception as e:
            logger.warning(f"[Patient] 患者版改写失败: {e}")
        return None

    @staticmethod
    def _fallback_plain(base: Dict) -> Dict:
        """降级：结构化直出（不做 LLM 改写），仍遵守通俗性原则。"""
        return {
            "what_is_it": "；".join(base["indications"]) if base["indications"] else "",
            "how_to_use": base["dosage_standard"],
            "cautions": base["contraindications"] + ([base["dosage_adjustment"]] if base["dosage_adjustment"] else []),
            "side_effects": [
                {"term": a["term"], "plain": a["frequency"], "when_to_seek_help": a["ctcae_hint"]}
                for a in base["adverse_reactions"]
            ],
            "seek_help": "",
        }

    @staticmethod
    def _parse_json(raw: str) -> Optional[Any]:
        if not raw:
            return None
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None
