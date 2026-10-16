"""报告智能解析服务（NM-05，主方案 §6.6；P1 演示级）。

仅做报告**文本**结构化解析：抽取影像描述字段（部位/大小/密度/边界/淋巴结）→
关键征象 → 检索循证条目给出随访建议 → 与同一患者历次解析结果对比（`diff_prev`）。

**边界**（数据清单 D4 组）：不做影像判读、不做 OCR；输入必须是文本。

数据依赖：A1/A2（肺结节共识等条目，经 `RetrieverService.hybrid_search` 检索）。
历次对比为**进程内存储**（演示级，按 patient_id 保留最近一次）。

安全：输出不给诊断结论，仅结构化描述 + 随访方向 + 免责声明。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from services.qa_service import QAService
from services.retriever_service import RetrieverService

logger = logging.getLogger(__name__)

# 结构化抽取的字段（C1 §5 NM-05）
FINDING_FIELDS = [
    ("site", "部位"),
    ("size", "大小"),
    ("density", "密度"),
    ("margin", "边界"),
    ("lymph_nodes", "淋巴结"),
]

DISCLAIMER = "本解析仅对报告文本做结构化整理，不构成影像判读与诊断结论，具体请以报告原文与医生判断为准。"

# 数值抽取（大小：如 12mm / 1.2cm / 8*6mm）
_SIZE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:×|\*|x)?\s*\d*(?:\.\d+)?\s*(?:mm|cm|毫米|厘米)", re.IGNORECASE)


class ReportParseService:
    """报告文本解析 → 结构化字段 + 关键征象 + 随访建议 + 历次对比。"""

    def __init__(self):
        self._qa = QAService()
        self._retriever = RetrieverService()
        # patient_id -> 最近一次解析结果（演示级）
        self._last_by_patient: Dict[str, Dict] = {}

    # ============================================================
    #  主入口
    # ============================================================
    def parse(self, text: str, patient_id: str = "") -> Dict:
        text = (text or "").strip()
        if not text:
            return {"success": False, "message": "报告文本为空"}

        extracted = self._llm_extract(text)
        if extracted is None:
            extracted = self._rule_extract(text)

        findings = self._normalize_findings(extracted.get("findings") or [])
        key_signs = [s for s in (extracted.get("key_signs") or []) if s]
        impression = str(extracted.get("impression") or "").strip()

        followup = self._followup_suggestions(text, findings, key_signs)
        diff_prev = self._diff_with_prev(patient_id, findings) if patient_id else None

        report = {
            "findings": findings,
            "key_signs": key_signs,
            "impression": impression,
            "followup_suggestions": followup["suggestions"],
            "followup_evidence": followup["evidence"],
            "diff_prev": diff_prev,
            "degraded": followup["degraded"],
            "note": followup["note"],
            "disclaimer": DISCLAIMER,
        }
        if patient_id:
            self._last_by_patient[patient_id] = {"findings": findings}
        return {"success": True, "report": report}

    # ============================================================
    #  抽取
    # ============================================================
    def _llm_extract(self, text: str) -> Optional[Dict]:
        fields_desc = "、".join([f"{k}（{label}）" for k, label in FINDING_FIELDS])
        prompt = f"""你是医学报告结构化助手。请从下列报告文本中抽取结构化信息。

【报告文本】
{text}

请仅输出如下 JSON（不要输出解释、不要用代码块包裹）：
{{
  "findings": [{{"site": "部位", "size": "大小", "density": "密度", "margin": "边界", "lymph_nodes": "淋巴结"}}],
  "key_signs": ["关键征象1", "关键征象2"],
  "impression": "报告印象/结论的简短复述"
}}
要求：
1. findings 每项对应一处病灶描述，字段缺失填空字符串 ""，不要编造；
2. 抽取字段包括：{fields_desc}；
3. key_signs 为报告中提示需关注的征象（如分叶、毛刺、胸膜牵拉、实性成分等）；
4. 不给出诊断结论，只复述报告内容。"""

        try:
            raw = self._qa._call_llm_with_model(prompt)
            obj = self._parse_json(raw)
            if isinstance(obj, dict):
                return {
                    "findings": obj.get("findings") if isinstance(obj.get("findings"), list) else [],
                    "key_signs": obj.get("key_signs") if isinstance(obj.get("key_signs"), list) else [],
                    "impression": obj.get("impression") or "",
                }
        except Exception as e:
            logger.warning(f"[Report] LLM 抽取失败，降级为规则抽取: {e}")
        return None

    @staticmethod
    def _rule_extract(text: str) -> Dict:
        """规则兜底：按行扫描，抽出含尺寸/密度等关键词的片段作为一条 finding。"""
        findings: List[Dict] = []
        for line in re.split(r"[\n。；;]", text):
            line = line.strip()
            if not line:
                continue
            if _SIZE_RE.search(line) or any(k in line for k in ("密度", "边界", "淋巴结", "结节", "占位", "灶")):
                size = _SIZE_RE.search(line)
                findings.append({
                    "site": line[:24],
                    "size": size.group(0) if size else "",
                    "density": "磨玻璃" if "磨玻璃" in line else ("实性" if "实性" in line else ""),
                    "margin": "毛刺" if "毛刺" in line else ("光滑" if "光滑" in line else ""),
                    "lymph_nodes": line if "淋巴结" in line else "",
                })
        return {"findings": findings, "key_signs": [], "impression": ""}

    @staticmethod
    def _normalize_findings(findings: List[Any]) -> List[Dict]:
        """规范化 findings：字段对齐 + 丢弃全空项。"""
        out: List[Dict] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            item = {k: str(f.get(k) or "").strip() for k, _ in FINDING_FIELDS}
            item["label"] = "；".join(
                f"{label}：{item[k]}" for k, label in FINDING_FIELDS if item[k]
            )
            if item["label"]:
                out.append(item)
        return out

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

    # ============================================================
    #  随访建议（检索循证条目）
    # ============================================================
    def _followup_suggestions(self, text: str, findings: List[Dict],
                              key_signs: List[str]) -> Dict:
        """以关键征象 + 报告关键句为查询，检索 A1/A2 循证条目作为随访建议依据。"""
        query = " ".join(key_signs) or " ".join([f["label"] for f in findings]) or text[:100]
        try:
            hits = self._retriever.hybrid_search(query=query, top_k=5)
        except Exception as e:
            logger.warning(f"[Report] 随访依据检索失败: {e}")
            hits = []

        suggestions: List[Dict] = []
        evidence: List[Dict] = []
        for h in hits:
            content = (h.get("content") or "").strip()
            if content:
                suggestions.append({
                    "text": content[:300],
                    "source": h.get("title") or h.get("doc_id") or "",
                    "breadcrumb": h.get("breadcrumb", ""),
                    "evidence_level": h.get("evidence_level", ""),
                    "rec_strength": h.get("rec_strength", ""),
                })
            evidence.append({
                "item_id": h.get("item_id") or h.get("rec_id") or h.get("doc_id") or "",
                "title": h.get("title") or "",
                "cancer_type": h.get("cancer_type", ""),
                "breadcrumb": h.get("breadcrumb", ""),
            })

        degraded = len(suggestions) == 0
        return {
            "suggestions": suggestions[:5],
            "evidence": evidence[:5],
            "degraded": degraded,
            "note": "" if not degraded else
                    "未检索到匹配的循证随访条目（指南/推荐条目数据未就绪或未命中），"
                    "建议结合报告原文与临床判断。",
        }

    # ============================================================
    #  历次对比
    # ============================================================
    def _diff_with_prev(self, patient_id: str, findings: List[Dict]) -> Optional[Dict]:
        """与同一患者上次解析对比。

        以**部位**为匹配键（而非整条描述）：同一部位的大小变化属「同一病灶变化」，
        不应被误报为「新增一处 + 消失一处」。同部位大小不同则单列 size_changes。
        演示级：按 patient_id 保留最近一次，进程内存储。
        """
        prev = self._last_by_patient.get(patient_id)
        if not prev:
            return None

        prev_map = self._index_by_site(prev.get("findings", []))
        cur_map = self._index_by_site(findings)

        added = [k for k in cur_map if k not in prev_map]
        removed = [k for k in prev_map if k not in cur_map]
        unchanged = [k for k in cur_map if k in prev_map]

        size_changes: List[Dict] = []
        for k in unchanged:
            before = (prev_map[k].get("size") or "").strip()
            after = (cur_map[k].get("size") or "").strip()
            if before and after and before != after:
                size_changes.append({"site": k, "before": before, "after": after})

        return {
            "previous_count": len(prev_map),
            "current_count": len(cur_map),
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
            "size_changes": size_changes,
        }

    @staticmethod
    def _index_by_site(findings: List[Dict]) -> Dict[str, Dict]:
        """按部位建索引（部位缺失时回落整条描述）；同部位重复时保留首条。"""
        out: Dict[str, Dict] = {}
        for f in findings or []:
            key = (f.get("site") or "").strip() or (f.get("label") or "").strip()
            if key and key not in out:
                out[key] = f
        return out
