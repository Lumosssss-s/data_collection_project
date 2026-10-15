"""智能预问诊服务（NM-02，主方案 §6.1）。

多轮症状采集 → 红旗征识别（安全第一）→ 风险分层 → 科室建议 → 就诊准备清单。

数据依赖（C3 §5 文件态）：
  - `triage_rules/`：B1 红旗征规则（含 `risk_level`）+ B3 分诊映射（含 `department_primary`），
    同目录靠 `record_type` 区分（缺该字段时按字段特征兜底判别）；
  - `preconsult_slots/`：B2 预问诊槽位表。

安全约束：
  - **红旗征宁高敏感**：B1 规则数据缺失时，必须显式暴露「红旗征识别不可用」（degraded），
    不得静默按「无风险」处理；
  - 输出**不给诊断结论**，仅给风险提示、就医方向与就诊准备建议。

复用：`QAService._call_llm_with_model` 做槽位/症状抽取；`EntityDisambiguationService`
做症状名归一（与 B1 规则 canonical 对齐）。

会话状态为**进程内存储**（演示级，重启丢失），与 QA 既有做法一致。
"""
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services.entity_disambiguation_service import EntityDisambiguationService
from services.qa_service import QAService
from utils.data_loader import data_status, load_dir_records

logger = logging.getLogger(__name__)

# 风险等级排序（越大越紧急）
RISK_ORDER = {"routine": 1, "urgent": 2, "emergency": 3}
RISK_LABELS = {"routine": "低风险（常规）", "urgent": "中风险（尽快就诊）",
               "emergency": "高风险（立即就医）"}

# 会话有效期（秒）；到期自动清理
_SESSION_TTL = 2 * 60 * 60

# B1/B3 记录类型判别
_RED_FLAG_TYPES = {"red_flag", "RF", "RFlAG"}
_TRIAGE_MAP_TYPES = {"triage_map", "TRI"}

# 就诊准备清单（按风险分层，静态模板）
_VISIT_PREP = {
    "emergency": [
        "保持镇静，立即前往急诊或拨打 120。",
        "携带既往病历、影像与检验报告。",
        "如咯血或呼吸困难，保持侧卧/半卧位，避免误吸。",
        "勿自行驾车前往。",
    ],
    "urgent": [
        "尽快（数日内）到相应专科门诊就诊。",
        "携带既往检查报告与用药清单。",
        "记录症状出现时间、变化与诱因。",
    ],
    "routine": [
        "可通过门诊预约就诊。",
        "整理症状描述与既往病史。",
        "如有新的不适，及时就医。",
    ],
}

DISCLAIMER = "本预问诊仅作就医方向参考，不构成诊断，具体请遵医嘱。"

_SYMPTOM_SPLIT_RE = re.compile(r"[、,，;；/\s]+")


class PreconsultService:
    """预问诊：会话管理 + 槽位填充 + 红旗征/风险分层 + 分诊建议。"""

    def __init__(self):
        self._qa = QAService()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ============================================================
    #  数据加载（文件态）
    # ============================================================
    def _load_red_flags(self) -> List[Dict]:
        return self._split_triage(load_dir_records("triage_rules"))[0]

    def _load_triage_maps(self) -> List[Dict]:
        return self._split_triage(load_dir_records("triage_rules"))[1]

    def _load_slots(self) -> List[Dict]:
        slots: List[Dict] = []
        for r in load_dir_records("preconsult_slots"):
            if isinstance(r.get("slots"), list):
                slots.extend([s for s in r["slots"] if isinstance(s, dict)])
            elif r.get("slot"):
                slots.append(r)
        return slots

    @staticmethod
    def _split_triage(records: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """把 `triage_rules/` 记录拆为（红旗征规则, 分诊映射）。

        优先按 `record_type` 判别；缺该字段时按特征兜底（含 risk_level → 红旗征；
        含 department_primary → 分诊映射）。
        """
        red_flags, triage_maps = [], []
        for r in records:
            rt = r.get("record_type")
            if rt in _RED_FLAG_TYPES or (rt is None and "risk_level" in r):
                red_flags.append(r)
            elif rt in _TRIAGE_MAP_TYPES or (rt is None and "department_primary" in r):
                triage_maps.append(r)
        return red_flags, triage_maps

    def data_readiness(self) -> Dict:
        """预问诊数据就绪状态（供 degraded 提示）。"""
        rf = data_status("triage_rules")
        slots = data_status("preconsult_slots")
        red_flags, triage_maps = self._split_triage(
            load_dir_records("triage_rules"))
        return {
            "red_flag_ready": len(red_flags) > 0,
            "triage_map_ready": len(triage_maps) > 0,
            "slots_ready": len(self._load_slots()) > 0,
            "triage_rules_dir": rf,
            "slots_dir": slots,
        }

    # ============================================================
    #  会话
    # ============================================================
    def create_session(self, patient_info: Optional[Dict] = None) -> Dict:
        sid = uuid.uuid4().hex
        readiness = self.data_readiness()
        session = {
            "session_id": sid,
            "created_at": time.time(),
            "patient_info": patient_info or {},
            "slots": dict(patient_info or {}),
            "symptoms": set(),
            "history": [],
            "red_flags": [],
            "risk_level": "routine",
        }
        with self._lock:
            self._gc_locked()
            self._sessions[sid] = session

        next_q = self._next_question(session)
        return {
            "session_id": sid,
            "next_question": next_q,
            "risk_level": session["risk_level"],
            "degraded": not readiness["slots_ready"],
            "note": "" if readiness["slots_ready"]
                    else "预问诊槽位数据未就绪（B2 槽位表待入库），无法驱动多轮采集。",
            "disclaimer": DISCLAIMER,
        }

    def handle_message(self, session_id: str, text: str) -> Optional[Dict]:
        session = self._get_session(session_id)
        if session is None:
            return None

        text = (text or "").strip()
        if text:
            session["history"].append({"role": "user", "text": text})
            self._extract_into_session(session, text)

        red_flags, risk_level = self._evaluate_red_flags(session)
        session["red_flags"] = red_flags
        session["risk_level"] = risk_level

        department = self._suggest_department(session)
        next_q = self._next_question(session)
        readiness = self.data_readiness()

        degraded = not (readiness["red_flag_ready"] and readiness["slots_ready"])
        notes = []
        if not readiness["red_flag_ready"]:
            notes.append("红旗征规则数据未就绪（B1），当前无法进行安全风险识别。")
        if not readiness["slots_ready"]:
            notes.append("预问诊槽位数据未就绪（B2），无法驱动多轮采集。")

        return {
            "session_id": session_id,
            "slots": self._public_slots(session),
            "symptoms": sorted(session["symptoms"]),
            "next_question": next_q,
            "red_flags": red_flags,
            "risk_level": risk_level,
            "risk_label": RISK_LABELS.get(risk_level, ""),
            "department": department,
            "visit_prep": _VISIT_PREP.get(risk_level, _VISIT_PREP["routine"]),
            "complete": next_q is None,
            "degraded": degraded,
            "note": " ".join(notes),
            "disclaimer": DISCLAIMER,
        }

    def get_result(self, session_id: str) -> Optional[Dict]:
        session = self._get_session(session_id)
        if session is None:
            return None
        department = self._suggest_department(session)
        return {
            "session_id": session_id,
            "patient_info": session["patient_info"],
            "slots": self._public_slots(session),
            "symptoms": sorted(session["symptoms"]),
            "red_flags": session["red_flags"],
            "risk_level": session["risk_level"],
            "risk_label": RISK_LABELS.get(session["risk_level"], ""),
            "department": department,
            "visit_prep": _VISIT_PREP.get(session["risk_level"], _VISIT_PREP["routine"]),
            "disclaimer": DISCLAIMER,
        }

    # ============================================================
    #  槽位填充（LLM + 规则兜底）
    # ============================================================
    def _extract_into_session(self, session: Dict, text: str) -> None:
        """从用户文本抽取槽位与症状（LLM 优先，失败则规则兜底）。"""
        slots_def = self._load_slots()
        slot_names = [s.get("slot") for s in slots_def if s.get("slot")]

        extracted = self._llm_extract(text, slot_names)
        if extracted is None:
            extracted = self._rule_extract(text, slots_def)

        for k, v in (extracted.get("slots") or {}).items():
            if v not in (None, "", []):
                session["slots"][k] = v
        for sym in (extracted.get("symptoms") or []):
            if sym:
                session["symptoms"].add(self._norm_symptom(sym))

    def _llm_extract(self, text: str, slot_names: List[str]) -> Optional[Dict]:
        """LLM 抽取：返回 {"slots": {...}, "symptoms": [...]}；失败返回 None。"""
        names = "、".join([n for n in slot_names if n]) or "（未定义）"
        prompt = f"""你是肿瘤预问诊信息抽取助手。请从患者描述中抽取结构化信息。

可抽取的槽位名（仅这些）：{names}
另外，请单独抽取患者提到的**症状**名称（如咳嗽、咯血、消瘦、发热、疼痛等）。

【患者描述】
{text}

请仅输出如下 JSON（不要输出任何解释、不要用代码块包裹）：
{{"slots": {{"槽位名": "值"}}, "symptoms": ["症状1", "症状2"]}}
未提及的槽位不要出现在 slots 中；没有症状则 symptoms 为空数组。"""

        try:
            raw = self._qa._call_llm_with_model(prompt)
            obj = self._parse_json(raw)
            if isinstance(obj, dict):
                return {
                    "slots": obj.get("slots") if isinstance(obj.get("slots"), dict) else {},
                    "symptoms": obj.get("symptoms") if isinstance(obj.get("symptoms"), list) else [],
                }
        except Exception as e:
            logger.warning(f"[Preconsult] LLM 抽取失败，降级为规则抽取: {e}")
        return None

    @staticmethod
    def _rule_extract(text: str, slots_def: List[Dict]) -> Dict:
        """规则兜底：把整段文本作为主诉，并按分隔符猜症状。"""
        slots: Dict[str, Any] = {}
        if text:
            slots["chief_complaint"] = text
        symptoms = [t for t in _SYMPTOM_SPLIT_RE.split(text) if len(t) >= 2]
        return {"slots": slots, "symptoms": symptoms}

    @staticmethod
    def _parse_json(raw: str) -> Optional[Any]:
        """从 LLM 输出中稳健解析 JSON（容忍代码块包裹与前后噪声）。"""
        if not raw:
            return None
        s = raw.strip()
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE).strip()
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
    #  红旗征 / 风险分层
    # ============================================================
    def _evaluate_red_flags(self, session: Dict) -> Tuple[List[Dict], str]:
        rules = self._load_red_flags()
        triggered: List[Dict] = []
        for rule in rules:
            if self._rule_matches(rule, session):
                triggered.append({
                    "rule_id": rule.get("rule_id", ""),
                    "risk_level": rule.get("risk_level", "routine"),
                    "action": rule.get("action", ""),
                    "department": rule.get("department", ""),
                })
        risk = "routine"
        for t in triggered:
            if RISK_ORDER.get(t["risk_level"], 0) > RISK_ORDER.get(risk, 0):
                risk = t["risk_level"]
        return triggered, risk

    def _rule_matches(self, rule: Dict, session: Dict) -> bool:
        """规则匹配：match[] 逐条 AND（present/absent）；conditions[] 逐条比较。

        conditions 依赖尚未采集的槽位时视为**不匹配**（不提前触发）；
        纯症状类 emergency 规则一经症状命中即触发（宁可高敏感）。
        """
        symptoms = session["symptoms"]
        for cond in rule.get("match") or []:
            sym = self._norm_symptom(cond.get("symptom", ""))
            op = cond.get("operator", "present")
            present = sym in symptoms
            if op == "present" and not present:
                return False
            if op == "absent" and present:
                return False

        for cond in rule.get("conditions") or []:
            field = cond.get("field")
            actual = session["slots"].get(field)
            if isinstance(actual, dict):
                actual = actual.get("value")
            if actual is None:
                return False
            if not self._compare(actual, cond.get("operator"), cond.get("value")):
                return False
        return True

    @staticmethod
    def _compare(actual: Any, operator: Optional[str], expected: Any) -> bool:
        """数值/字符串比较（G11：值与单位分离时比较 value）。"""
        if isinstance(expected, dict):
            expected = expected.get("value")
        try:
            a, b = float(actual), float(expected)
        except (TypeError, ValueError):
            a, b = str(actual), str(expected)
        return {
            ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b,
            "==": a == b, "!=": a != b,
        }.get(operator or "==", False)

    @staticmethod
    def _norm_symptom(name: str) -> str:
        """症状名归一（与 B1 规则 canonical 对齐）。"""
        name = (name or "").strip()
        if not name:
            return ""
        _, canonical = EntityDisambiguationService.resolve(name, "Symptom")
        return canonical or name

    # ============================================================
    #  分诊
    # ============================================================
    def _suggest_department(self, session: Dict) -> Dict:
        """科室建议：疾病映射优先于症状映射；无映射时回落红旗征规则建议科室。"""
        maps = self._load_triage_maps()

        def _find(from_type: str, value: str) -> Optional[Dict]:
            v = self._norm_symptom(value) if from_type == "symptom" else value
            for m in maps:
                if m.get("from_type") == from_type and m.get("from") == v:
                    return m
            return None

        # 1) 疾病 → 科室（有明确诊断/病名时优先）
        for key in ("disease", "diagnosis", "cancer_type", "name"):
            val = session["slots"].get(key)
            if isinstance(val, dict):
                val = val.get("value")
            if val:
                m = _find("disease", str(val))
                if m:
                    return {"primary": m.get("department_primary", ""),
                            "alt": m.get("department_alt") or [],
                            "source": "disease"}

        # 2) 症状 → 科室（仅症状时，取首个有映射的症状）
        for sym in sorted(session["symptoms"]):
            m = _find("symptom", sym)
            if m:
                return {"primary": m.get("department_primary", ""),
                        "alt": m.get("department_alt") or [],
                        "source": "symptom"}

        # 3) 回落：红旗征规则给出的建议科室
        for f in session.get("red_flags", []):
            if f.get("department"):
                return {"primary": f["department"], "alt": [], "source": "red_flag"}

        return {"primary": "", "alt": [], "source": "none"}

    # ============================================================
    #  提问 / 会话工具
    # ============================================================
    def _next_question(self, session: Dict) -> Optional[Dict]:
        """下一问：按优先级取首个「已触发且未填」的槽位。"""
        slots_def = self._load_slots()
        if not slots_def:
            return None

        active = [s for s in slots_def
                  if s.get("slot") and self._slot_active(s, session)
                  and self._is_empty(session["slots"].get(s.get("slot")))]
        if not active:
            return None

        # 优先级：会话开始类（年龄/性别/主诉）> 无触发条件 > 条件触发；同优先级保持定义顺序
        def _prio(s: Dict) -> int:
            trig = s.get("trigger")
            if isinstance(trig, str) and "会话开始" in trig:
                return 0
            if not trig:
                return 1
            if isinstance(trig, dict) and "会话开始" in json.dumps(trig, ensure_ascii=False):
                return 0
            return 2

        chosen = sorted(active, key=_prio)[0]
        return {"slot": chosen.get("slot"), "prompt": chosen.get("prompt", ""),
                "type": chosen.get("type", "string"), "required": bool(chosen.get("required"))}

    def _slot_active(self, slot: Dict, session: Dict) -> bool:
        """触发条件判定：条件触发槽位未满足触发条件时不提问。"""
        trig = slot.get("trigger")
        if not trig or isinstance(trig, str):
            return True
        if not isinstance(trig, dict):
            return True

        cc = session["slots"].get("chief_complaint")
        if "when_chief_complaint_in" in trig:
            if not cc:
                return False
            keywords = trig["when_chief_complaint_in"]
            return any(kw in str(cc) for kw in (keywords or []))
        if "when_sex_is" in trig:
            return str(session["slots"].get("sex", "")) == str(trig["when_sex_is"])
        return True

    @staticmethod
    def _is_empty(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str):
            return v.strip() == ""
        if isinstance(v, (list, dict)):
            return len(v) == 0
        return False

    def _public_slots(self, session: Dict) -> Dict:
        return {k: v for k, v in session["slots"].items() if not self._is_empty(v)}

    def _get_session(self, session_id: str) -> Optional[Dict]:
        with self._lock:
            self._gc_locked()
            return self._sessions.get(session_id)

    def _gc_locked(self) -> None:
        now = time.time()
        expired = [k for k, s in self._sessions.items()
                   if now - s.get("created_at", now) > _SESSION_TTL]
        for k in expired:
            self._sessions.pop(k, None)
