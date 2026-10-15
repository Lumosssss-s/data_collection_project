"""智能随访服务（NM-03，主方案 §6.3）。

随访计划生成（模板驱动）→ 任务下发 → 反馈分级（CTCAE）→ 异常预警。

数据依赖（C3 §5 文件态）：
  - `followup_templates/`：B4 随访模板（`followup_template`，前缀 TPL）
  - `patient_messages/`：B5 患者消息模板（`msg`，前缀 MSG）

CTCAE 5.0 分级：反馈项按「显式 grade > 严重度关键词映射 > LLM 判定」三级判定；
**≥3 级触发预警**（B4 §⑥ 要求）。

数据未就绪时优雅降级（`degraded=True` + 提示），不抛异常。
计划 / 任务 / 预警为**进程内存储**（演示级，重启丢失）。
"""
import json
import logging
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from services.qa_service import QAService
from utils.data_loader import data_status, load_dir_records

logger = logging.getLogger(__name__)

# B4 `phase` 枚举（§5.7.3）
PHASE_LABELS: Dict[str, str] = {
    "postoperative": "术后",
    "on_treatment": "治疗中",
    "rehabilitation": "康复期",
    "survivorship": "长期生存",
}

# B5 `msg_type` 枚举
MSG_TYPE_LABELS: Dict[str, str] = {
    "followup_reminder": "随访提醒",
    "abnormal_alert": "异常预警",
    "health_education": "健康教育",
    "adherence": "依从性",
}

# 预警等级（CTCAE ≥3 级）：3=urgent，4/5=emergency
ALERT_LEVEL = {3: "urgent", 4: "emergency", 5: "emergency"}
ALERT_LABELS = {"urgent": "尽快就诊", "emergency": "立即就医"}

DISCLAIMER = "本条信息仅供参考，不构成诊断，具体请遵医嘱。"

# 严重度关键词 → CTCAE 等级（顺序敏感：先匹配高级别）
_SEVERITY_GRADE = [
    (("危及生命", "危重", "病危", "5级", "5 级"), 5),
    (("严重", "重度", "剧烈", "severe", "4级", "4 级"), 4),
    (("中度", "moderate", "3级", "3 级"), 3),
    (("轻度", "轻微", "mild", "1级", "1 级", "2级", "2 级"), 1),
]

_GRADE_RE = re.compile(r"(?:grade\s*|ctcae\s*|CTCAE\s*)?([1-5])\s*级", re.IGNORECASE)


class FollowUpService:
    """随访计划 / 任务 / 反馈分级 / 预警。"""

    def __init__(self):
        self._qa = QAService()
        self._plans: Dict[str, Dict] = {}
        self._tasks: Dict[str, Dict] = {}
        self._alerts: List[Dict] = []
        self._lock = threading.RLock()

    # ============================================================
    #  数据（文件态）
    # ============================================================
    def _templates(self) -> List[Dict]:
        return [t for t in load_dir_records("followup_templates") if t.get("tpl_id")]

    def _messages(self) -> List[Dict]:
        return [m for m in load_dir_records("patient_messages") if m.get("msg_id")]

    def data_readiness(self) -> Dict:
        tpl = data_status("followup_templates")
        msg = data_status("patient_messages")
        return {
            "templates_ready": len(self._templates()) > 0,
            "messages_ready": len(self._messages()) > 0,
            "templates_dir": tpl,
            "messages_dir": msg,
        }

    # ============================================================
    #  计划
    # ============================================================
    def create_plan(self, case_id: str, cancer_type: str, phase: str,
                    stage: Optional[List[str]] = None, patient_id: str = "") -> Dict:
        """按癌种 + 阶段（+ 可选分期）匹配 B4 模板，生成日程计划与任务。"""
        phase = (phase or "").strip()
        tpl = self._match_template(cancer_type, phase, stage)
        readiness = self.data_readiness()

        if tpl is None:
            return {
                "plan_id": "",
                "case_id": case_id,
                "cancer_type": cancer_type,
                "phase": phase,
                "phase_label": PHASE_LABELS.get(phase, phase),
                "tasks": [],
                "messages": [],
                "degraded": True,
                "note": ("随访模板数据未就绪（B4 随访模板待入库），无法生成随访计划。"
                         if not readiness["templates_ready"]
                         else f"未找到匹配模板（癌种={cancer_type} / 阶段={phase}）。"),
                "disclaimer": DISCLAIMER,
            }

        plan_id = uuid.uuid4().hex
        base = date.today()
        tasks: List[Dict] = []
        for idx, item in enumerate(tpl.get("schedule") or []):
            interval = item.get("interval_days")
            due = base + timedelta(days=int(interval)) if isinstance(interval, (int, float)) else base
            task_id = uuid.uuid4().hex
            task = {
                "task_id": task_id,
                "plan_id": plan_id,
                "case_id": case_id,
                "patient_id": patient_id,
                "tpl_id": tpl.get("tpl_id", ""),
                "timepoint": item.get("timepoint", f"第{idx + 1}次"),
                "interval_days": interval,
                "items": item.get("items") or [],
                "due_date": due.isoformat(),
                "status": "pending",
                "responses": [],
                "grade": 0,
            }
            tasks.append(task)
            with self._lock:
                self._tasks[task_id] = task

        plan = {
            "plan_id": plan_id,
            "case_id": case_id,
            "patient_id": patient_id,
            "cancer_type": cancer_type,
            "phase": phase,
            "phase_label": PHASE_LABELS.get(phase, phase),
            "stage": tpl.get("stage") or [],
            "tpl_id": tpl.get("tpl_id", ""),
            "tasks": tasks,
            "messages": self._render_template_messages(tpl),
            "ae_monitoring": tpl.get("ae_monitoring") or [],
            "degraded": not readiness["messages_ready"],
            "note": "" if readiness["messages_ready"]
                    else "患者消息模板未就绪（B5 待入库），计划中暂无提醒消息。",
            "disclaimer": DISCLAIMER,
        }
        with self._lock:
            self._plans[plan_id] = plan
        return plan

    def _match_template(self, cancer_type: str, phase: str,
                        stage: Optional[List[str]]) -> Optional[Dict]:
        """模板匹配：癌种 + 阶段必匹配；给分期时需落在模板 stage 内（否则不匹配）。"""
        for tpl in self._templates():
            if tpl.get("cancer_type") != cancer_type:
                continue
            if tpl.get("phase") != phase:
                continue
            if stage:
                tpl_stage = tpl.get("stage") or []
                if tpl_stage and not set(stage) & set(tpl_stage):
                    continue
            return tpl
        return None

    def _render_template_messages(self, tpl: Dict) -> List[Dict]:
        """渲染模板引用的 B5 消息（返回模板原文与占位符，渲染交由调用方填值）。"""
        ref_ids = tpl.get("patient_messages") or []
        if not ref_ids:
            return []
        by_id = {m.get("msg_id"): m for m in self._messages()}
        out = []
        for mid in ref_ids:
            m = by_id.get(mid)
            if not m:
                continue
            out.append({
                "msg_id": m.get("msg_id", ""),
                "msg_type": m.get("msg_type", ""),
                "msg_type_label": MSG_TYPE_LABELS.get(m.get("msg_type", ""), ""),
                "template": m.get("template", ""),
                "placeholders": m.get("placeholders") or [],
                "audience": m.get("audience", "patient"),
            })
        return out

    def render_message(self, template: str, values: Dict[str, Any]) -> str:
        """用 values 填充 {占位符}；未提供的占位符保留原文，避免出现空洞。"""
        def _sub(match):
            key = match.group(1)
            if key in values and values[key] not in (None, ""):
                return str(values[key])
            return match.group(0)
        return re.sub(r"\{([^{}]+)\}", _sub, template or "")

    # ============================================================
    #  任务
    # ============================================================
    def list_tasks(self, patient_id: Optional[str] = None,
                   case_id: Optional[str] = None) -> Dict:
        """任务列表：标出「到期（due_date <= 今日）」与「待反馈」。"""
        today = date.today().isoformat()
        with self._lock:
            tasks = list(self._tasks.values())
        if patient_id:
            tasks = [t for t in tasks if t.get("patient_id") == patient_id]
        if case_id:
            tasks = [t for t in tasks if t.get("case_id") == case_id]

        out = []
        for t in sorted(tasks, key=lambda x: x.get("due_date", "")):
            out.append({
                **t,
                "due": t.get("due_date", "") <= today,
                "phase_label": PHASE_LABELS.get(
                    self._plans.get(t.get("plan_id", ""), {}).get("phase", ""), ""),
            })
        return {
            "total": len(out),
            "due_count": sum(1 for t in out if t["due"] and t["status"] == "pending"),
            "tasks": out,
        }

    def get_task(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            return self._tasks.get(task_id)

    # ============================================================
    #  反馈 → CTCAE 分级 → 预警
    # ============================================================
    def record(self, task_id: str, responses: List[Dict]) -> Optional[Dict]:
        task = self.get_task(task_id)
        if task is None:
            return None

        graded: List[Dict] = []
        for r in responses or []:
            if not isinstance(r, dict):
                continue
            term = str(r.get("term") or r.get("ctcae_term") or r.get("name") or "").strip()
            grade = self._decide_grade(r)
            graded.append({
                "term": term,
                "grade": grade,
                "grade_label": self._grade_label(grade),
                "text": str(r.get("text") or r.get("description") or "").strip(),
            })

        max_grade = max([g["grade"] for g in graded], default=0)
        alerts = self._make_alerts(task, graded)

        with self._lock:
            task["responses"] = graded
            task["grade"] = max_grade
            task["status"] = "done"
            task["submitted_at"] = datetime.now().isoformat(timespec="seconds")
            if alerts:
                self._alerts.extend(alerts)

        return {
            "task_id": task_id,
            "max_grade": max_grade,
            "grade_label": self._grade_label(max_grade),
            "responses": graded,
            "alerts": alerts,
            "alert_level": alerts[0]["level"] if alerts else "",
            "disclaimer": DISCLAIMER,
        }

    def _decide_grade(self, r: Dict) -> int:
        """CTCAE 分级：显式 grade > 严重度关键词 > 文本中「N 级」 > LLM 判定。"""
        explicit = r.get("grade")
        if isinstance(explicit, (int, float)) and 1 <= int(explicit) <= 5:
            return int(explicit)

        sev = str(r.get("severity") or "").strip()
        for keywords, g in _SEVERITY_GRADE:
            if any(k in sev for k in keywords):
                return g

        text = f"{sev} {r.get('text') or r.get('description') or ''}"
        m = _GRADE_RE.search(text)
        if m:
            return max(1, min(5, int(m.group(1))))

        return self._llm_grade(r)

    def _llm_grade(self, r: Dict) -> int:
        """LLM 兜底判定 CTCAE 等级；失败返回 0（不误报为高档）。"""
        term = r.get("term") or r.get("ctcae_term") or ""
        desc = r.get("text") or r.get("description") or r.get("severity") or ""
        prompt = f"""你是肿瘤随访症状分级助手。请依据 CTCAE 5.0 判断下列不良反应的严重程度等级。

不良反应：{term}
患者描述：{desc}

请仅输出一个 1~5 的整数（1=轻度，2=中度，3=重度，4=危及生命，5=死亡）。无法判断时输出 0。"""
        try:
            raw = self._qa._call_llm_with_model(prompt)
            for ch in (raw or "").strip():
                if ch.isdigit():
                    g = int(ch)
                    return g if 0 <= g <= 5 else 0
        except Exception as e:
            logger.warning(f"[FollowUp] LLM 分级失败: {e}")
        return 0

    def _make_alerts(self, task: Dict, graded: List[Dict]) -> List[Dict]:
        """≥3 级触发预警（B4 §⑥）。"""
        alerts = []
        for g in graded:
            if g["grade"] >= 3:
                alerts.append({
                    "alert_id": uuid.uuid4().hex,
                    "task_id": task["task_id"],
                    "plan_id": task.get("plan_id", ""),
                    "case_id": task.get("case_id", ""),
                    "patient_id": task.get("patient_id", ""),
                    "timepoint": task.get("timepoint", ""),
                    "term": g["term"],
                    "grade": g["grade"],
                    "grade_label": g["grade_label"],
                    "level": ALERT_LEVEL.get(g["grade"], "urgent"),
                    "level_label": ALERT_LABELS.get(ALERT_LEVEL.get(g["grade"], "urgent"), ""),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
        return alerts

    @staticmethod
    def _grade_label(grade: int) -> str:
        return {0: "未分级", 1: "1 级（轻度）", 2: "2 级（中度）", 3: "3 级（重度）",
                4: "4 级（危及生命）", 5: "5 级（死亡）"}.get(grade, "未分级")

    # ============================================================
    #  预警
    # ============================================================
    def list_alerts(self, patient_id: Optional[str] = None) -> Dict:
        with self._lock:
            alerts = list(self._alerts)
        if patient_id:
            alerts = [a for a in alerts if a.get("patient_id") == patient_id]
        alerts.sort(key=lambda a: a.get("created_at", ""), reverse=True)
        return {"total": len(alerts), "alerts": alerts}

    def compliance_summary(self) -> Dict:
        """依从性粗统计（供运营看板参考；B7 口径细化待数据）。"""
        with self._lock:
            tasks = list(self._tasks.values())
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "done")
        return {
            "total_tasks": total,
            "completed": done,
            "compliance_rate": round(done / total, 4) if total else None,
        }
