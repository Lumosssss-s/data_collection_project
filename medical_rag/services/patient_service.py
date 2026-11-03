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
import os
import re
from datetime import datetime
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
        """结构化说明书详情（零 LLM）：通用名/商品名/适应证/限定/黑框/警示/
        剂量/禁忌/不良反应/相互作用原文/免责。药品不存在返回 None。

        白话解读拆到 get_drug_plain（/patient/drug/{id}/plain），本接口不触发 LLM。
        """
        raw = self.repo.get(drug_id)
        if not raw:
            return None

        base = self._base_fields(raw)
        boxed = raw.get("boxed_warning") or None
        return {
            "drug_id": drug_id,
            "generic_name": base["generic_name"],
            "brand_names": base["brand_names"],
            "indication_note": raw.get("indication_note") or "",
            "indications": base["indications"],
            "dosage_standard": base["dosage_standard"],
            "dosage_adjustment": base["dosage_adjustment"],
            "contraindications": base["contraindications"],
            "adverse_reactions": base["adverse_reactions"],
            # 相互作用原文透传：逐字来自 ES _source，不截断/改写/翻译
            "raw_interactions": base["interactions"],
            "interaction_count": len(base["interactions"]),
            "boxed_warning": boxed,
            "has_boxed_warning": bool(boxed),
            "warnings_count": len(raw.get("warnings") or []),
            "disclaimer": DISCLAIMER,
            "seek_help": SEEK_HELP,
        }

    def get_drug_plain(self, drug_id: str) -> Optional[Dict]:
        """白话解读（LLM 生成，带 ES 缓存）。

        先读 patient_plain 缓存：命中直接返回（cached=true）；
        未命中则基于说明书生成（严守「仅基于说明书」），写前备份 _source，
        经 repo.update_fields 部分更新写回（不整文档覆盖、不重算 embedding）。
        药品不存在返回 None；生成失败返回 {"plain": None, "cached": False}。
        """
        raw = self.repo.get(drug_id)
        if not raw:
            return None

        cached = raw.get("patient_plain")
        if cached:
            # 缓存为 JSON 字符串（mapping 为 text/index:false，原样存储）
            if isinstance(cached, str):
                try:
                    cached = json.loads(cached)
                except Exception:
                    cached = None
            if cached:
                return {
                    "drug_id": drug_id,
                    "plain": cached,
                    "cached": True,
                    "patient_plain_at": raw.get("patient_plain_at") or "",
                }

        # 第二级缓存：clean JSON（重灌后 ES 缓存被覆盖时从这里回填，零 LLM）
        disk = self._load_plain_from_clean(drug_id)
        if disk:
            plain, plain_at = disk
            try:
                self.repo.update_fields(drug_id, {
                    "patient_plain": json.dumps(plain, ensure_ascii=False),
                    "patient_plain_at": plain_at,
                })
            except Exception as e:
                logger.warning(f"[Patient] clean JSON 缓存回填 ES 失败（不影响本次返回）: {e}")
            return {
                "drug_id": drug_id,
                "plain": plain,
                "cached": True,
                "patient_plain_at": plain_at,
            }

        base = self._base_fields(raw)
        plain = self._llm_plainify(base)
        if plain is None:
            return {"drug_id": drug_id, "plain": None, "cached": False}

        # 写前备份：把写回前的 _source 落地一份，防止 partial update 意外丢字段
        try:
            backup_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "backups", "patient_plain",
            )
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            with open(os.path.join(backup_dir, f"{drug_id}_{ts}.json"), "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=1)
        except Exception as e:
            logger.warning(f"[Patient] 白话写回前备份失败（继续写回）: {e}")

        try:
            self.repo.update_fields(drug_id, {
                "patient_plain": json.dumps(plain, ensure_ascii=False),
                "patient_plain_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            })
        except Exception as e:
            logger.warning(f"[Patient] 白话缓存写回失败（不影响本次返回）: {e}")

        return {"drug_id": drug_id, "plain": plain, "cached": False}

    @staticmethod
    def _load_plain_from_clean(drug_id: str) -> Optional[tuple]:
        """从 clean JSON 读白话缓存（data/clean/drug_labels/{drug_id}.json）。

        命中返回 (plain_dict, patient_plain_at)；未命中/解析失败返回 None。
        clean 文件为只读数据源，本函数不写任何内容。
        """
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, "data", "clean", "drug_labels", f"{drug_id}.json")
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)
            rec = records[0] if isinstance(records, list) and records else (records if isinstance(records, dict) else None)
            if not rec:
                return None
            cached = rec.get("patient_plain")
            if isinstance(cached, str):
                cached = json.loads(cached)
            if not cached:
                return None
            return cached, str(rec.get("patient_plain_at") or "")
        except Exception as e:
            logger.warning(f"[Patient] 读 clean JSON 白话缓存失败（{drug_id}）: {e}")
            return None

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
