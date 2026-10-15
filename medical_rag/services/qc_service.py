"""病历质控服务（NM-04，主方案 §6.4）。

规则引擎（高确定性）+ LLM 内涵质控（few-shot），输出评分与问题清单。

数据依赖（C3 §5 文件态）：
  - `qc_rules/`：B6 质控规则（`qc_rule`，前缀 QC），四类：完整性 / 一致性 / 规范性 / 时限性
  - A5 术语字典（诊断名称规范，退化为内置别名表兜底）

两条执行路径：
  1. **规则引擎（builtin）**：代码内置的高确定性检查（口语缩写、性别-诊断矛盾、必填章节缺失），
     不依赖 B6 数据，标注 `source="builtin"`；
  2. **B6 规则判定（rule）**：把 B6 规则清单 + 病历交给 LLM 逐条判定，标注 `source="rule:{rule_id}"`。

B6 数据缺失时 `degraded=True` 并明确提示「未经 B6 规则校验」，不伪造规则。
历史报告为进程内存储（演示级）。
"""
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from services.qa_service import QAService
from utils.data_loader import data_status, load_dir_records

logger = logging.getLogger(__name__)

# B6 `category` 枚举
CATEGORY_LABELS: Dict[str, str] = {
    "completeness": "完整性",
    "consistency": "一致性",
    "standardization": "规范性",
    "timeliness": "时限性",
}

# `severity` 扣分权重
SEVERITY_PENALTY = {"high": 15, "medium": 8, "low": 3}
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}

# 报告有效期（秒）
_REPORT_TTL = 24 * 60 * 60

# 单次 LLM 判定的规则批大小（控制 prompt 规模）
_RULE_BATCH = 25

# 病历关键章节（完整性检查；含常见别名）
_SECTION_PATTERNS = [
    ("主诉", re.compile(r"主\s*诉")),
    ("现病史", re.compile(r"现\s*病\s*史")),
    ("既往史", re.compile(r"既\s*往\s*史")),
    ("诊断", re.compile(r"诊\s*断")),
]

# 内置口语缩写检查（规范性）；canonical 优先取术语字典/别名表
_BUILTIN_ABBR = [
    (re.compile(r"肺\s*CA", re.IGNORECASE), "肺CA", "肺癌"),
    (re.compile(r"胃\s*CA", re.IGNORECASE), "胃CA", "胃癌"),
    (re.compile(r"乳(?:腺)?\s*CA", re.IGNORECASE), "乳CA", "乳腺癌"),
    (re.compile(r"(?:肠|结直肠|大肠)\s*CA", re.IGNORECASE), "肠CA", "结直肠癌"),
    (re.compile(r"甲(?:状腺)?\s*CA", re.IGNORECASE), "甲CA", "甲状腺癌"),
    (re.compile(r"肝\s*CA", re.IGNORECASE), "肝CA", "肝癌"),
]

# 性别-诊断矛盾检查（一致性）
_FEMALE_ONLY = ("乳腺", "子宫", "卵巢", "宫颈", "阴道", "外阴")
_MALE_ONLY = ("前列腺", "睾丸", "阴茎", "精囊")
_MALE_HINT = re.compile(r"(?:性\s*别|性别)\s*[:：]?\s*男|患\s*者\s*[:：]?\s*男|\b男\b")
_FEMALE_HINT = re.compile(r"(?:性\s*别|性别)\s*[:：]?\s*女|患\s*者\s*[:：]?\s*女|\b女\b")

DISCLAIMER = "质控结果基于规则与模型判定，供病历质量改进参考，最终以人工复核为准。"


class QCService:
    """病历质控：规则目录 / 质控审查 / 历史报告。"""

    def __init__(self):
        self._qa = QAService()
        self._reports: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    # ============================================================
    #  数据（文件态）
    # ============================================================
    def _rules(self) -> List[Dict]:
        return [r for r in load_dir_records("qc_rules") if r.get("rule_id")]

    def data_readiness(self) -> Dict:
        st = data_status("qc_rules")
        return {"rules_ready": len(self._rules()) > 0, "rules_dir": st}

    def list_rules(self, category: Optional[str] = None) -> Dict:
        """规则目录（B6）；可按 category 过滤，并给出分类计数。"""
        rules = self._rules()
        counts: Dict[str, int] = {}
        for r in rules:
            c = r.get("category", "")
            counts[c] = counts.get(c, 0) + 1
        items = [r for r in rules if not category or r.get("category") == category]
        degraded = len(rules) == 0
        return {
            "total": len(rules),
            "items": [self._rule_brief(r) for r in items],
            "categories": [{"value": k, "label": CATEGORY_LABELS.get(k, k), "count": v}
                           for k, v in counts.items()],
            "degraded": degraded,
            "note": "" if not degraded else "质控规则数据未就绪（B6 质控规则待入库）。",
        }

    @staticmethod
    def _rule_brief(r: Dict) -> Dict:
        return {
            "rule_id": r.get("rule_id", ""),
            "category": r.get("category", ""),
            "category_label": CATEGORY_LABELS.get(r.get("category", ""), ""),
            "field_target": r.get("field_target", ""),
            "severity": r.get("severity", ""),
            "severity_label": SEVERITY_LABELS.get(r.get("severity", ""), ""),
            "logic": r.get("logic", ""),
            "reference": r.get("reference", ""),
            "message_template": r.get("message_template", ""),
        }

    # ============================================================
    #  质控审查
    # ============================================================
    def review(self, record_text: str, patient_id: str = "") -> Dict:
        record_text = (record_text or "").strip()
        if not record_text:
            return {"success": False, "message": "病历文本为空"}

        rules = self._rules()
        degraded = len(rules) == 0

        issues: List[Dict] = []
        # 1) 内置高确定性检查
        issues.extend(self._builtin_checks(record_text))
        # 2) B6 规则判定（LLM）
        if rules:
            issues.extend(self._rule_checks(record_text, rules))

        issues = self._dedup(issues)
        score = self._score(issues)

        review_id = uuid.uuid4().hex
        report = {
            "review_id": review_id,
            "patient_id": patient_id,
            "score": score,
            "grade": self._grade(score),
            "issue_count": len(issues),
            "issues": issues,
            "severity_stats": self._severity_stats(issues),
            "category_stats": self._category_stats(issues),
            "rule_count": len(rules),
            "degraded": degraded,
            "note": ("质控规则数据未就绪（B6 待入库），当前结果仅含内置通用检查，"
                     "未经 B6 规则校验。" if degraded else ""),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "disclaimer": DISCLAIMER,
        }
        with self._lock:
            self._gc_locked()
            self._reports[review_id] = report
        return {"success": True, "report": report}

    def get_report(self, review_id: str) -> Optional[Dict]:
        with self._lock:
            self._gc_locked()
            return self._reports.get(review_id)

    # ============================================================
    #  内置高确定性检查
    # ============================================================
    def _builtin_checks(self, text: str) -> List[Dict]:
        issues: List[Dict] = []

        # 规范性：口语缩写
        for pattern, abbr, suggestion in _BUILTIN_ABBR:
            m = pattern.search(text)
            if m:
                issues.append(self._issue(
                    rule_id="BUILTIN-STANDARD-ABBR", category="standardization",
                    severity="medium", field_target="诊断",
                    message=f"诊断「{m.group(0)}」为口语缩写，建议规范书写为「{suggestion}」。",
                    evidence=self._snippet(text, m.start(), m.end()), source="builtin"))

        # 一致性：性别-诊断矛盾
        is_male = bool(_MALE_HINT.search(text))
        is_female = bool(_FEMALE_HINT.search(text))
        for kw in _FEMALE_ONLY:
            if is_male and kw in text:
                issues.append(self._issue(
                    rule_id="BUILTIN-CONSIST-SEX", category="consistency",
                    severity="high", field_target="诊断",
                    message=f"性别为男性，但出现女性相关诊断「{kw}」，请核对。",
                    evidence=kw, source="builtin"))
        for kw in _MALE_ONLY:
            if is_female and kw in text:
                issues.append(self._issue(
                    rule_id="BUILTIN-CONSIST-SEX", category="consistency",
                    severity="high", field_target="诊断",
                    message=f"性别为女性，但出现男性相关诊断「{kw}」，请核对。",
                    evidence=kw, source="builtin"))

        # 完整性：关键章节缺失
        for name, pattern in _SECTION_PATTERNS:
            if not pattern.search(text):
                issues.append(self._issue(
                    rule_id="BUILTIN-COMPL-SECTION", category="completeness",
                    severity="high" if name in ("主诉", "诊断") else "medium",
                    field_target=name,
                    message=f"病历缺少「{name}」项，请补充。",
                    evidence="", source="builtin"))
        return issues

    # ============================================================
    #  B6 规则判定（LLM 批量）
    # ============================================================
    def _rule_checks(self, text: str, rules: List[Dict]) -> List[Dict]:
        issues: List[Dict] = []
        for i in range(0, len(rules), _RULE_BATCH):
            batch = rules[i:i + _RULE_BATCH]
            issues.extend(self._rule_checks_batch(text, batch))
        return issues

    def _rule_checks_batch(self, text: str, batch: List[Dict]) -> List[Dict]:
        rules_txt = "\n".join([
            f"- [{r.get('rule_id', '')}] 类别:{CATEGORY_LABELS.get(r.get('category', ''), r.get('category', ''))} "
            f"字段:{r.get('field_target', '')} 严重度:{SEVERITY_LABELS.get(r.get('severity', ''), r.get('severity', ''))} "
            f"依据:{r.get('reference', '')} 检查逻辑:{r.get('logic', '')}"
            for r in batch
        ])
        prompt = f"""你是病历质控专家。请依据下列质控规则逐条检查病历，输出**命中**的问题。

【质控规则】
{rules_txt}

【病历全文】
{text}

请仅输出 JSON 数组（不要输出解释、不要用代码块包裹），元素格式：
{{"rule_id": "命中的规则 ID", "field_target": "作用字段", "evidence": "病历中的原文片段（尽量短）", "message": "问题说明"}}
若某条规则未命中则不要输出该条；全部未命中则输出 []。"""

        try:
            raw = self._qa._call_llm_with_model(prompt)
            arr = self._parse_json_array(raw)
        except Exception as e:
            logger.warning(f"[QC] B6 规则判定失败: {e}")
            return []

        by_id = {r.get("rule_id"): r for r in batch}
        issues = []
        for item in arr or []:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("rule_id", "")).strip()
            rule = by_id.get(rid)
            if not rule:
                continue
            issues.append(self._issue(
                rule_id=rid,
                category=rule.get("category", ""),
                severity=rule.get("severity", "medium"),
                field_target=item.get("field_target") or rule.get("field_target", ""),
                message=item.get("message") or rule.get("message_template", ""),
                evidence=str(item.get("evidence", ""))[:120],
                source=f"rule:{rid}"))
        return issues

    # ============================================================
    #  工具
    # ============================================================
    @staticmethod
    def _issue(rule_id: str, category: str, severity: str, field_target: str,
               message: str, evidence: str, source: str) -> Dict:
        return {
            "issue_id": uuid.uuid4().hex,
            "rule_id": rule_id,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "severity": severity,
            "severity_label": SEVERITY_LABELS.get(severity, severity),
            "field_target": field_target,
            "message": message,
            "evidence": evidence,
            "source": source,
        }

    @staticmethod
    def _snippet(text: str, start: int, end: int, pad: int = 12) -> str:
        return text[max(0, start - pad):min(len(text), end + pad)].strip()

    @staticmethod
    def _parse_json_array(raw: str) -> Optional[List[Any]]:
        """稳健解析 LLM 返回的 JSON 数组（容忍代码块与前后噪声）。"""
        if not raw:
            return None
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, list) else None
        except Exception:
            pass
        m = re.search(r"\[[\s\S]*\]", s)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, list) else None
            except Exception:
                return None
        return None

    @staticmethod
    def _dedup(issues: List[Dict]) -> List[Dict]:
        """同一（rule_id, evidence）只保留一条。"""
        seen = set()
        out = []
        for it in issues:
            key = (it.get("rule_id"), it.get("evidence", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    @staticmethod
    def _score(issues: List[Dict]) -> int:
        penalty = sum(SEVERITY_PENALTY.get(i.get("severity", "low"), 0) for i in issues)
        return max(0, 100 - penalty)

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90:
            return "优"
        if score >= 75:
            return "良"
        if score >= 60:
            return "中"
        return "差"

    @staticmethod
    def _severity_stats(issues: List[Dict]) -> Dict[str, int]:
        stats = {"high": 0, "medium": 0, "low": 0}
        for i in issues:
            sev = i.get("severity", "low")
            stats[sev] = stats.get(sev, 0) + 1
        return stats

    @staticmethod
    def _category_stats(issues: List[Dict]) -> List[Dict]:
        counts: Dict[str, int] = {}
        for i in issues:
            c = i.get("category", "")
            counts[c] = counts.get(c, 0) + 1
        return [{"value": k, "label": CATEGORY_LABELS.get(k, k), "count": v}
                for k, v in counts.items()]

    def _gc_locked(self) -> None:
        now = time.time()
        expired = []
        for rid, rep in self._reports.items():
            try:
                ts = time.mktime(time.strptime(rep.get("created_at", ""), "%Y-%m-%d %H:%M:%S"))
            except Exception:
                ts = now
            if now - ts > _REPORT_TTL:
                expired.append(rid)
        for rid in expired:
            self._reports.pop(rid, None)
