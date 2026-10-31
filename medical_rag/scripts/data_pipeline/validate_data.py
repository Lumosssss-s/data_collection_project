"""V-01 validate_data.py —— data/clean 全量自动校验（入库闸门）

对应《医疗赛道系统改造方案》§5.7.4 V1~V9 与《数据处理校验评测脚本交付清单》V-01 契约：

    V1 JSON 可解析 + 结构/类型校验（schema 子集，随脚本维护于 schemas/*.json）
    V2 必填字段完整率 100%（缺失 / null / 占位符均计失败）
    V3 ID 命名正则（G5）+ 主键唯一（跨文件全局）
    V4 枚举合法性（G12 / 受控词表 §5.7.3，与 BE-04 domain_enums 同源）
    V5 引用完整性（REC.doc_id -> DOC；悬空输出清单；目标类型无数据时跳过并注明）
    V6 溯源五要素完整率（G6：source_name/source_version/source_section/source_file/updated_at）
    V7 格式（UTF-8 无 BOM / 日期 YYYY-MM-DD / 无占位符空值 G8 / 无全角数字字母混入 G10）
    V8 脱敏正则扫描（G13：身份证 / 手机号 / 住院号 / 姓名标签，0 命中）
    V9 去重（正文相似度 >0.95 重复对清单；同类型分块后 difflib 精算）

输出:
    data/reports/validation_<时间戳>.json   逐项 {通过数, 失败清单(记录 ID + 字段 + 原因)}
    stdout 摘要；**exit code != 0 即失败**（I-01 --precheck 依赖此约定）

用法:
    python scripts/data_pipeline/validate_data.py                 # 校验全部已知类型
    python scripts/data_pipeline/validate_data.py --types rec     # 只校验推荐条目
    python scripts/data_pipeline/validate_data.py --fail-fast     # 首个失败即停（CI 用）

说明:
    - 未安装 jsonschema，故内置 schema 子集校验器（type/required/enum/pattern/maxLength/
      nullable/items），schema 文件采用 JSON Schema 子集格式，后续如引入 jsonschema 库可直接复用。
    - 文件态 8 目录（triage_rules 等）与 disease_profiles/kg_triples 不在本轮范围，
      在 skipped 中登记。
"""
import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]   # medical_rag/
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
DEFAULT_CLEAN_DIR = BASE_DIR / "data" / "clean"
DEFAULT_REPORT_DIR = BASE_DIR / "data" / "reports"

# 目录 -> 类型（与 ingest.py _ES_ROUTED_DIRS 同源）
ROUTED_DIRS: Dict[str, str] = {
    "guidelines": "doc",
    "recommendations": "rec",
    "drug_labels": "drug",
    "terminology": "term",
    "literature": "literature",
}
# 延后/文件态目录（登记但不校验）
SKIPPED_DIRS: Dict[str, str] = {
    "disease_profiles": "本轮延后（P-03 未产出）",
    "kg_triples": "本轮延后（P-06 未产出）",
    "triage_rules": "文件态（C3 §5）",
    "preconsult_slots": "文件态（C3 §5）",
    "followup_templates": "文件态（C3 §5）",
    "patient_messages": "文件态（C3 §5）",
    "qc_rules": "文件态（C3 §5）",
    "eval_sets": "文件态（C3 §5）",
    "mock_cases": "文件态（C3 §5）",
    "ops_metrics": "文件态（C3 §5）",
}

G8_PLACEHOLDERS = {"", "无", "N/A", "NA", "n/a", "null", "None", "-", "待补", "未知"}
FULLWIDTH_RE = re.compile(r"[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# G13 脱敏
DEIDENT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("住院号/病案号", re.compile(r"(住院号|病案号|门诊号)\s*[:：]?\s*[A-Za-z0-9]{5,}")),
    ("姓名标签", re.compile(r"姓名\s*[:：]\s*[一-龥]{2,4}")),
]
MAX_FAILURES = 200          # 报告内每项失败清单上限（防报告膨胀）
SIM_BLOCK_LEN = 24          # V9 分块键长度
SIM_THRESHOLD = 0.95
HASH_FIELDS = {"doc_hash"}  # V8 跳过：哈希串不承载个人身份信息
HASH_RE = re.compile(r"^[0-9a-f]{32,64}$")


class Check:
    """单项校验（V1~V9）的失败收集器。"""

    def __init__(self, code: str, name: str):
        self.code = code
        self.name = name
        self.passed = 0
        self.failures: List[Dict] = []
        self.truncated = False

    def ok(self):
        self.passed += 1

    def fail(self, file: str, rec_id: str, field: str, reason: str):
        if len(self.failures) >= MAX_FAILURES:
            self.truncated = True
            return
        self.failures.append({"file": file, "record": rec_id, "field": field, "reason": reason})

    @property
    def failed(self) -> int:
        return len(self.failures) + (1 if self.truncated else 0)


def load_schemas() -> Dict[str, Dict]:
    schemas = {}
    for p in sorted(SCHEMA_DIR.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            schema = json.load(f)
        schemas[schema["type"]] = schema
    return schemas


# ---------------- V1 结构/类型（schema 子集校验器） ----------------

def _check_type(value: Any, spec: Dict) -> Optional[str]:
    """返回类型错误原因，合法返回 None。null 仅在 nullable 时合法（由调用方处理）。"""
    t = spec.get("type")
    if t == "string":
        if not isinstance(value, str):
            return f"应为 string，实际 {type(value).__name__}"
        pat = spec.get("pattern")
        if pat and not re.match(pat, value):
            return f"不匹配格式 {pat}"
        ml = spec.get("maxLength")
        if ml and len(value) > ml:
            return f"长度 {len(value)} 超上限 {ml}"
    elif t == "boolean":
        if not isinstance(value, bool):
            return f"应为 boolean，实际 {type(value).__name__}"
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"应为 integer，实际 {type(value).__name__}"
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"应为 number，实际 {type(value).__name__}"
    elif t == "array":
        if not isinstance(value, list):
            return f"应为 array，实际 {type(value).__name__}"
        item_spec = spec.get("items")
        if item_spec:
            for i, item in enumerate(value):
                err = _check_type(item, item_spec)
                if err:
                    return f"[{i}] {err}"
    elif t == "object":
        if not isinstance(value, dict):
            return f"应为 object，实际 {type(value).__name__}"
    return None


def _check_enum(value: Any, spec: Dict) -> Optional[str]:
    allowed = spec.get("enum")
    if allowed is None:
        return None
    if value not in allowed:
        return f"值 {value!r} 不在受控词表 {allowed}"
    return None


def load_g2_records(path: Path) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """读取 G2 文件（顶层 JSON 数组）。返回 (records, error)。"""
    try:
        raw = path.read_bytes()
    except Exception as e:                                  # noqa: BLE001
        return None, f"读取失败: {e}"
    try:
        data = json.loads(raw.decode("utf-8-sig"))          # BOM 由 V7 单独报告
    except UnicodeDecodeError as e:
        return None, f"非 UTF-8 编码: {e}"
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e}"
    if not isinstance(data, list):
        return None, "顶层非数组（违反 G2）"
    return data, None


# ---------------- 校验主流程 ----------------

def validate(clean_dir: Path, types: Optional[List[str]]) -> Dict:
    schemas = load_schemas()
    checks = {
        "V1": Check("V1", "JSON 可解析 + 结构/类型校验"),
        "V2": Check("V2", "必填字段完整率"),
        "V3": Check("V3", "ID 命名正则（G5）与唯一性"),
        "V4": Check("V4", "枚举合法性（G12/受控词表）"),
        "V5": Check("V5", "引用完整性"),
        "V6": Check("V6", "溯源五要素（G6）"),
        "V7": Check("V7", "格式（BOM/日期/占位符/全角）"),
        "V8": Check("V8", "脱敏正则扫描（G13）"),
        "V9": Check("V9", "去重（主键 + 相似度>0.95）"),
    }
    skipped: List[Dict] = []
    files_scanned = 0
    records_total = 0
    review_stats: Dict[str, int] = {}

    # 收集各类型全部记录（供 V5 引用 / V3 全局唯一 / V9 相似度）
    loaded: Dict[str, List[Tuple[str, Dict]]] = {t: [] for t in schemas}

    if not clean_dir.exists():
        skipped.append({"dir": str(clean_dir), "reason": "目录不存在"})
        return _report(checks, skipped, files_scanned, records_total, review_stats, clean_dir)

    for sub in sorted(clean_dir.iterdir()):
        if not sub.is_dir():
            continue
        name = sub.name
        if name in SKIPPED_DIRS:
            skipped.append({"dir": name, "reason": SKIPPED_DIRS[name]})
            continue
        dtype = ROUTED_DIRS.get(name)
        if dtype is None:
            skipped.append({"dir": name, "reason": "不在 G3 14 目录内"})
            continue
        if types and dtype not in types:
            skipped.append({"dir": name, "reason": f"未选择类型 {dtype}"})
            continue
        schema = schemas.get(dtype)
        if schema is None:
            skipped.append({"dir": name, "reason": "无 schema"})
            continue

        json_files = sorted(sub.glob("*.json")) + sorted(sub.glob("*.jsonl"))
        if not json_files:
            skipped.append({"dir": name, "reason": "无数据文件"})
            continue

        for jf in json_files:
            files_scanned += 1
            records, err = load_g2_records(jf)
            if err:
                checks["V1"].fail(jf.name, "-", "-", err)
                continue
            for idx, rec in enumerate(records):
                rid = str(rec.get(schema["id_field"], "") or f"#{idx}") if isinstance(rec, dict) else f"#{idx}"
                _validate_record(rec, schema, jf.name, rid, checks)
                if isinstance(rec, dict):
                    loaded[dtype].append((jf.name, rec))
                    rs = rec.get("review_status")
                    if isinstance(rs, str):
                        review_stats[rs] = review_stats.get(rs, 0) + 1
                    records_total += 1

    # V5 引用完整性（跨文件；目标类型无数据时跳过）
    doc_ids = {r.get("doc_id") for _, r in loaded.get("doc", [])}
    if loaded.get("rec"):
        if doc_ids:
            for fname, rec in loaded["rec"]:
                did = rec.get("doc_id")
                if did and did not in doc_ids:
                    checks["V5"].fail(fname, str(rec.get("rec_id", "-")), "doc_id",
                                      f"悬空引用：DOC 集合中不存在 {did}")
                else:
                    checks["V5"].ok()
        else:
            skipped.append({"dir": "V5/rec->doc", "reason": "无 DOC 记录，引用校验跳过"})
    if not loaded.get("rec"):
        skipped.append({"dir": "V5/rec->doc", "reason": "无 REC 记录"})

    # V3 全局唯一性（各类内部跨文件）
    for dtype, recs in loaded.items():
        id_field = schemas[dtype]["id_field"]
        seen: Dict[str, str] = {}
        for fname, rec in recs:
            rid = str(rec.get(id_field, "") or "")
            if not rid:
                continue
            if rid in seen:
                checks["V3"].fail(fname, rid, id_field, f"主键重复（首现于 {seen[rid]}）")
            else:
                seen[rid] = fname

    # V9 正文相似度 >0.95 重复对
    for dtype, recs in loaded.items():
        text_fields = {"rec": ["recommendation_text"], "doc": ["title"],
                       "drug": ["generic_name"], "term": ["canonical"],
                       "literature": ["title"]}[dtype]
        items = []
        for fname, rec in recs:
            txt = " ".join(str(rec.get(f, "") or "") for f in text_fields).strip()
            rid = str(rec.get(schemas[dtype]["id_field"], "-"))
            if txt:
                # 第 4 位存癌种：药品同名跨癌种视图记录不算重复（见下方跳过逻辑）
                items.append((fname, rid, txt, str(rec.get("cancer_type") or "")))
        buckets: Dict[str, List[Tuple[str, str, str, str]]] = {}
        for it in items:
            key = re.sub(r"\s+", "", it[2])[:SIM_BLOCK_LEN].lower()
            buckets.setdefault(key, []).append(it)
        reported_pairs = set()
        for group in buckets.values():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    pair_key = tuple(sorted((a[1], b[1])))
                    if pair_key in reported_pairs:
                        continue
                    ratio = SequenceMatcher(None, a[2], b[2]).ratio()
                    if ratio > SIM_THRESHOLD:
                        # 药品：同一说明书按癌种拆成多条视图记录（如帕博利珠单抗同时服务
                        # 肺癌与结直肠癌）属有意设计，癌种不同时不计为重复。
                        if dtype == "drug" and a[3] != b[3]:
                            continue
                        reported_pairs.add(pair_key)
                        checks["V9"].fail(a[0], f"{a[1]} ↔ {b[1]}", "正文",
                                          f"相似度 {ratio:.4f} > {SIM_THRESHOLD}")
        checks["V9"].passed += len(items) - len(reported_pairs)

    return _report(checks, skipped, files_scanned, records_total, review_stats, clean_dir)


def _validate_record(rec: Any, schema: Dict, fname: str, rid: str, checks: Dict[str, Check]):
    if not isinstance(rec, dict):
        checks["V1"].fail(fname, rid, "-", "记录非 JSON 对象")
        return

    # V1 结构/类型
    type_ok = True
    for field, spec in schema.get("properties", {}).items():
        if field not in rec:
            continue
        value = rec[field]
        if value is None:
            if not spec.get("nullable") and field not in schema.get("nullable_required", []):
                checks["V1"].fail(fname, rid, field, "非可空字段取值 null")
                type_ok = False
            continue
        err = _check_type(value, spec)
        if err:
            checks["V1"].fail(fname, rid, field, err)
            type_ok = False
    # V2 必填完整
    for field in schema.get("required", []):
        if field not in rec:
            checks["V2"].fail(fname, rid, field, "必填字段缺失")
        else:
            v = rec[field]
            if v is None and field in schema.get("nullable_required", []):
                checks["V2"].ok()      # 来源豁免（如 FDA 无国药准字）：null 为合规缺值表达
            elif v is None:
                checks["V2"].fail(fname, rid, field, "必填字段为 null")
            elif isinstance(v, str) and v.strip() in G8_PLACEHOLDERS:
                checks["V2"].fail(fname, rid, field, f"必填字段为占位符 {v!r}")
            elif isinstance(v, (list, dict)) and len(v) == 0:
                checks["V2"].fail(fname, rid, field, "必填字段为空集合")
            else:
                checks["V2"].ok()
    if type_ok:
        checks["V1"].ok()

    # V3 ID 正则
    id_field = schema["id_field"]
    rid_val = rec.get(id_field)
    if isinstance(rid_val, str) and rid_val:
        if re.match(schema["id_pattern"], rid_val):
            checks["V3"].ok()
        else:
            checks["V3"].fail(fname, rid, id_field, f"不匹配 G5 规则 {schema['id_pattern']}")
    # 注意：唯一性在批量加载后全局比对

    # V4 枚举
    enum_fields = {f: s for f, s in schema.get("properties", {}).items() if s.get("enum")}
    v4_total = len(enum_fields)
    v4_bad = 0
    for field, spec in enum_fields.items():
        if field not in rec or rec[field] is None:
            continue
        err = _check_enum(rec[field], spec)
        if err:
            checks["V4"].fail(fname, rid, field, err)
            v4_bad += 1
    checks["V4"].passed += v4_total - v4_bad

    # V5 引用（单条注册由调用方在批量阶段处理，这里仅处理 schema 内静态 ref）
    for ref in schema.get("ref_checks", []):
        if ref["field"] in rec:
            checks["V5"].ok()      # 实际悬空比对在批量阶段完成，这里仅记存在性

    # V6 溯源五要素
    if schema.get("g6_required"):
        for field in schema.get("g6_fields", []):
            v = rec.get(field)
            if field not in rec or v is None or (isinstance(v, str) and v.strip() in G8_PLACEHOLDERS):
                checks["V6"].fail(fname, rid, field, "溯源字段缺失或为占位符")
            elif field in schema.get("g6_date_fields", []) and isinstance(v, str) and not DATE_RE.match(v):
                checks["V6"].fail(fname, rid, field, f"日期格式非 YYYY-MM-DD: {v!r}")
            else:
                checks["V6"].ok()

    # V7 格式（BOM 在文件级检查，见下）
    for field, value in _walk_strings(rec):
        if isinstance(value, str):
            if value in G8_PLACEHOLDERS and field in schema.get("required", []):
                continue                                # 已在 V2 计入
            if value in G8_PLACEHOLDERS - {""} :
                checks["V7"].fail(fname, rid, field, f"占位符值 {value!r}（G8 禁止）")
            elif value == "" and field in schema.get("properties", {}) and field not in schema.get("required", []):
                if schema["properties"][field].get("nullable"):
                    checks["V7"].fail(fname, rid, field, "空字符串应写 null（G8）")
            if FULLWIDTH_RE.search(value):
                checks["V7"].fail(fname, rid, field, "混入全角数字/字母（G10/V7）")
            if field in ("publish_date", "updated_at", "review_date") and value and not DATE_RE.match(value):
                checks["V7"].fail(fname, rid, field, f"日期格式非 YYYY-MM-DD: {value!r}")
        elif value is not None and field in ("publish_date", "updated_at", "review_date"):
            checks["V7"].fail(fname, rid, field, "日期字段非字符串（null 除外，G8 缺值用 null）")

    # V8 脱敏（哈希类字段跳过：64 位十六进制串会随机命中手机号/身份证正则）
    v8_hit = False
    for field, value in _walk_strings(rec):
        if not isinstance(value, str):
            continue
        if field in HASH_FIELDS or HASH_RE.fullmatch(value):
            continue
        for pname, pat in DEIDENT_PATTERNS:
            m = pat.search(value)
            if m:
                checks["V8"].fail(fname, rid, field, f"疑似{pname}: {m.group(0)[:12]}…")
                v8_hit = True
    if not v8_hit:
        checks["V8"].ok()


def _walk_strings(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def _report(checks, skipped, files_scanned, records_total, review_stats, clean_dir) -> Dict:
    # V7 文件级 BOM 检查结果已并入记录级；此处汇总
    out_checks = {}
    total_failed = 0
    for code in sorted(checks):
        c = checks[code]
        out_checks[code] = {
            "name": c.name,
            "passed": c.passed,
            "failed": c.failed,
            "failures": c.failures,
            "truncated": c.truncated,
        }
        total_failed += c.failed
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "clean_dir": str(clean_dir),
        "files_scanned": files_scanned,
        "records_total": records_total,
        "review_status_distribution": review_stats,
        "checks": out_checks,
        "skipped": skipped,
        "result": "PASS" if total_failed == 0 else "FAIL",
        "total_failures": total_failed,
    }


def check_bom(clean_dir: Path, types: Optional[List[str]], report: Dict):
    """V7 文件级：UTF-8 BOM 扫描（记录级无法发现 BOM）。"""
    bom_files = []
    for sub in sorted(clean_dir.iterdir()) if clean_dir.exists() else []:
        if not sub.is_dir() or sub.name not in ROUTED_DIRS:
            continue
        dtype = ROUTED_DIRS[sub.name]
        if types and dtype not in types:
            continue
        for jf in sorted(sub.glob("*.json")):
            if jf.read_bytes().startswith(b"\xef\xbb\xbf"):
                bom_files.append(f"{sub.name}/{jf.name}")
    if bom_files:
        report["checks"]["V7"]["failed"] += len(bom_files)
        report["checks"]["V7"]["failures"].append(
            {"file": ",".join(bom_files[:10]), "record": "-", "field": "-", "reason": "文件含 UTF-8 BOM（G1）"})
        report["result"] = "FAIL"
        report["total_failures"] += len(bom_files)


def selftest() -> int:
    """V-01 验收自测：3 组构造坏数据全部拦截 + 好数据零误报（清单 §2 V-01 验收）。

    临时目录内构造: 缺字段 / 非法枚举 / 悬空引用 三组坏数据 + 一组全绿数据，
    断言坏数据命中对应检查项、好数据不产生任何失败。
    """
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="v01_selftest_"))
    try:
        (tmp / "guidelines").mkdir(parents=True)
        (tmp / "recommendations").mkdir(parents=True)
        sha = "a" * 64

        good_doc = {
            "doc_id": "DOC-LUNG-SELF-001", "title": "自测肺癌指南（2025）", "doc_type": "guideline",
            "issuer": "测试机构", "publish_date": "2025-01-01", "cancer_types": ["lung"],
            "license_note": "公开版", "file_path": "raw/guidelines/self.xml", "doc_hash": sha,
            "summary": "自测摘要。",
            "source_name": "自测肺癌指南（2025）", "source_version": "2025", "source_section": "全文",
            "source_file": "self.xml", "updated_at": "2026-10-20",
            "review_status": "approved", "reviewer": "自测", "review_date": "2026-10-20",
        }
        good_rec = {
            "rec_id": "REC-LUNG-SELF-0001", "doc_id": "DOC-LUNG-SELF-001", "cancer_type": "lung",
            "breadcrumb": "第一部分/1.1 筛查", "scenario": "screening", "stage": None, "biomarker": None,
            "population": "高危人群", "recommendation_text": "对高危人群应每年行低剂量 CT 筛查。",
            "verbatim": True, "evidence_level": "high", "rec_strength": "strong",
            "refs": None, "page": None,
            "source_name": "自测肺癌指南（2025）", "source_version": "2025", "source_section": "1.1",
            "source_file": "self.xml", "updated_at": "2026-10-20",
            "review_status": "approved", "reviewer": "自测", "review_date": "2026-10-20",
        }
        bad_missing = {                       # 组1：缺必填字段
            "doc_type": "guideline", "issuer": "测试机构", "cancer_types": ["lung"],
            "publish_date": "2025-01-01", "license_note": "x", "file_path": "x", "doc_hash": sha,
        }
        bad_enum = dict(good_rec, rec_id="REC-LUNG-SELF-0002",
                        cancer_type="肺癌", scenario="treatment",        # 组2：非法枚举（中文癌种/自造场景）
                        recommendation_text="坏数据组2专用文本，避免与好数据构成重复对。")
        bad_dangling = dict(good_rec, rec_id="REC-LUNG-SELF-0003",
                            doc_id="DOC-LUNG-XXX-999",                   # 组3：悬空引用
                            recommendation_text="坏数据组3专用文本，避免与好数据构成重复对。")

        def dump(path: Path, records: list):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False)

        dump(tmp / "guidelines" / "good.json", [good_doc])
        dump(tmp / "guidelines" / "bad_missing.json", [bad_missing])
        dump(tmp / "recommendations" / "good.json", [good_rec])
        dump(tmp / "recommendations" / "bad_enum.json", [bad_enum])
        dump(tmp / "recommendations" / "bad_dangling.json", [bad_dangling])

        report = validate(tmp, None)
        checks = report["checks"]

        def files_of(code: str) -> set:
            return {f["file"] for f in checks[code]["failures"]}

        cases = [
            ("组1 缺字段被 V2 拦截", "bad_missing.json" in files_of("V2")),
            ("组2 非法枚举被 V4 拦截", "bad_enum.json" in files_of("V4")),
            ("组3 悬空引用被 V5 拦截", "bad_dangling.json" in files_of("V5")),
            ("好数据零误报", not any(
                "good.json" in f["file"] for c in checks.values() for f in c["failures"])),
        ]
        all_ok = True
        for name, ok in cases:
            print(f"  {'✓' if ok else '✗'} {name}")
            all_ok = all_ok and ok
        print(f"V-01 自测: {'PASS' if all_ok else 'FAIL'}")
        return 0 if all_ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="V-01 数据校验（入库闸门）")
    ap.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    ap.add_argument("--types", default="", help="逗号分隔，如 doc,rec,drug,term（空=全部）")
    ap.add_argument("--fail-fast", action="store_true", help="存在任一失败即早停（仅影响退出码报告时机）")
    ap.add_argument("--selftest", action="store_true", help="运行 V-01 验收自测（坏数据拦截 + 好数据零误报）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    types = [t.strip() for t in args.types.split(",") if t.strip()] or None
    clean_dir = Path(args.clean_dir)
    report = validate(clean_dir, types)
    check_bom(clean_dir, types, report)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = report_dir / f"validation_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 摘要
    print(f"V-01 校验: {report['result']}  （文件 {report['files_scanned']}，记录 {report['records_total']}）")
    for code in sorted(report["checks"]):
        c = report["checks"][code]
        flag = "✓" if c["failed"] == 0 else "✗"
        print(f"  {flag} {code} {c['name']}: 通过 {c['passed']} / 失败 {c['failed']}")
        for fl in c["failures"][:5]:
            print(f"      - {fl['file']} | {fl['record']} | {fl['field']}: {fl['reason']}")
        if c["failed"] > 5:
            print(f"      … 其余 {c['failed'] - 5} 条见报告")
    if report["review_status_distribution"]:
        print(f"  review_status 分布: {report['review_status_distribution']}")
    if report["skipped"]:
        print(f"  跳过: {', '.join(s['dir'] for s in report['skipped'])}")
    print(f"报告: {out_path}")

    if report["result"] != "PASS" and args.fail_fast:
        return 1
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
