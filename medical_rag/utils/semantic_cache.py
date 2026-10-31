# -*- coding: utf-8 -*-
"""语义缓存（Redis 后端）。

分层命中：
    L0 精确键：normalize(问题) + 过滤条件 → 进程内索引直接命中（跨进程/跨重启有效）；
    L1 余弦初筛：bge-m3 向量在进程内矩阵上暴力比对（条目数 ≤ 300，无需向量索引）；
    L2 实体槽位守卫：癌种 / 分期 / 线数 / 拉丁术语 / 数字 / 否定词，任一冲突即判未命中。

为什么 L1 之后必须有 L2，而不是只调阈值：
    utils/search_cache.py 已记录实测 —— 良性改写「处罚规定 / 罚则是什么」0.9397，
    危险近似「通知义务 / 告知义务」0.9257，两组区间重叠；医疗侧同理
    （III 期 / IV 期、一线 / 二线、奥沙利铂 / 紫杉醇 在 bge-m3 下余弦同样在 0.92 以上）。
    因此阈值只承担「廉价预筛」，判别主力是槽位守卫。

失效：以 data/doc_catalog.json 的 mtime 作为语料版本，版本变化时整库作废
      （清空 sc:v1:* 并重设版本键）；TTL 只作为泄漏兜底。
降级：Redis 不可用 / 超时 → 冷却 30s 内所有调用直接返回未命中，由调用方回落到
      现有的进程内精确缓存（utils/search_cache.py），问答与检索链路不中断。
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from core.config import settings
from core.domain_enums import CANCER_TYPE_ALIASES, CANCER_TYPE_INFO

try:
    import redis as _redis
except Exception:  # 依赖缺失时整体降级，不影响主链路
    _redis = None

logger = logging.getLogger(__name__)

KEY_PREFIX = "sc:v1"
_VERSION_KEY = f"{KEY_PREFIX}:ver"
_HOT_KEY = f"{KEY_PREFIX}:hot"
_MISS_KEY = f"{KEY_PREFIX}:miss"

# 槽位提取用的正则（全部按「冲突即未命中」的保守口径使用）
_STAGE_ROMAN_RE = re.compile(r"(?<![A-Za-z0-9])(IV|III|II|I)(?![A-Za-z0-9])", re.IGNORECASE)
_STAGE_FULLWIDTH = {
    "\u2160": "I", "\u2161": "II", "\u2162": "III", "\u2163": "IV",  # Ⅰ Ⅱ Ⅲ Ⅳ
}
_STAGE_CN_RE = re.compile(r"[一二三四]期")
_STAGE_CN_MAP = {"一": "I", "二": "II", "三": "III", "四": "IV"}
# 阿拉伯数字分期（「3期」）：与「III期」「三期」等价。不归一的话，
# 「结肠癌III期辅助化疗方案」与「三期结肠癌术后辅助化疗方案」会因分期写法不同被误拒。
_STAGE_ARABIC_RE = re.compile(r"(?<![0-9])([1-4])\s*期")
_STAGE_ARABIC_MAP = {"1": "I", "2": "II", "3": "III", "4": "IV"}
# 全角数字归一（「３期」→「3期」）：中文输入法下很常见，不归一会漏抽分期
_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
# 纯罗马数字的词元不再进 latin 槽位：分期已由 stage 槽位统一归一，
# 若同时留在 latin 里，会出现「查询侧 III 有、条目侧三期没有」的假冲突。
_ROMAN_ONLY_RE = re.compile(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X)$")
_STAGE_WORD_RE = re.compile(r"(早期|中期|晚期|局部晚期|转移性|不可切除)")
_LINE_RE = re.compile(r"(一线|二线|三线|四线|新辅助|术后辅助|辅助治疗|维持治疗|姑息治疗)")
# 线数的同义写法归一：用户说「术前放化疗 / 手术后化疗」，指南里写「新辅助 / 术后辅助」。
# 不归一的话，守卫会把同一个治疗方案判成线数冲突（只有在低阈值下才会暴露为误拒）。
_LINE_SYNONYMS = (
    (re.compile(r"术前(放)?化疗|术前放疗|手术前(放)?化疗"), "新辅助"),
    (re.compile(r"手术后(要不要|需不需要|需要|是否)?(做|进行)?(辅助)?化疗"), "术后辅助"),
)
# 生物标志物状态：KRAS 野生型 ↔ 突变型、PD-L1 高表达 ↔ 低表达，余弦可达 0.92+，
# 但 gene 名相同，靠 latin 槽位拦不住，必须单独抽状态词。
_STATUS_RE = re.compile(r"(野生型|突变型|高表达|低表达|过表达|扩增|缺失|阳性|阴性)")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,15}")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 中性疑问结构：先剥离再判否定。「能不能用奥沙利铂」「要不要做化疗」「是否推荐靶向治疗」
# 表达的是询证意图，不是否定语义；不剥离就会把它们与「不能用奥沙利铂」判成同一类，
# 从而与肯定句误判冲突（这是此前实测到的误拒来源之一）。
# 长词在前，避免「有没有必要」被「有没有」先截断。
_QUESTION_FORM_RE = re.compile(
    r"(有没有必要|应不应该|可不可以|能不能|需不需要|要不要|用不用|该不该|"
    r"会不会|可不可能|能否|有没有|是不是|是否)"
)
# 否定判定只认明确的否定结构，不再用裸「不」「无」做子串匹配：
# 「不良反应」「无进展生存期」这类术语里的「不/无」会把正常问题误判成否定句
# （「奥沙利铂的不良反应」与「奥沙利铂副作用」曾因裸「不」被判冲突而误拒）。
_NEG_RE = re.compile(
    r"(?:不能|不可以|不可|不应(?:该)?|不宜|不适宜|不合适|不需要|不必|不用|无需|无须|没必要|没有|"
    r"未(?:能|曾|行|做|接受|进行|治疗)?|不行|不适合|不建议|不推荐|不适用|"
    r"禁忌|禁用|禁止|避免|除外)"
)

# 中文术语补丁：terminology_cancer.json 只收录 15 个药品，结直肠/肺癌高频化疗与靶向药
# 缺失（奥沙利铂、紫杉醇、伊立替康…）。这些药名互换后语义完全不同（方案差异巨大），
# 但 bge-m3 余弦仍在 0.92 以上，必须靠词表拦住。surface -> canonical。
_SUPPLEMENT_TERMS = {
    "奥沙利铂": "CHEMO-OXALIPLATIN", "oxaliplatin": "CHEMO-OXALIPLATIN",
    "紫杉醇": "CHEMO-PACLITAXEL", "paclitaxel": "CHEMO-PACLITAXEL",
    "多西他赛": "CHEMO-DOCETAXEL", "docetaxel": "CHEMO-DOCETAXEL",
    "伊立替康": "CHEMO-IRINOTECAN", "irinotecan": "CHEMO-IRINOTECAN",
    "氟尿嘧啶": "CHEMO-5FU", "5-氟尿嘧啶": "CHEMO-5FU", "5-fu": "CHEMO-5FU",
    "亚叶酸钙": "CHEMO-LEUCOVORIN", "leucovorin": "CHEMO-LEUCOVORIN",
    "贝伐珠单抗": "DRUG-BEVACIZUMAB", "bevacizumab": "DRUG-BEVACIZUMAB",
    "西妥昔单抗": "DRUG-CETUXIMAB", "cetuximab": "DRUG-CETUXIMAB",
    "帕尼单抗": "DRUG-PANITUMUMAB", "panitumumab": "DRUG-PANITUMUMAB",
    "雷莫芦单抗": "DRUG-RAMUCIRUMAB", "ramucirumab": "DRUG-RAMUCIRUMAB",
    "瑞戈非尼": "DRUG-REGORAFENIB", "regorafenib": "DRUG-REGORAFENIB",
    "呋喹替尼": "DRUG-FRUQUINTINIB", "fruquintinib": "DRUG-FRUQUINTINIB",
    "曲氟尿苷替匹嘧啶": "DRUG-TAS102", "tas-102": "DRUG-TAS102",
    "帕博利珠单抗": "ICI-PEMBROLIZUMAB", "pembrolizumab": "ICI-PEMBROLIZUMAB",
    "纳武利尤单抗": "ICI-NIVOLUMAB", "nivolumab": "ICI-NIVOLUMAB",
    "信迪利单抗": "ICI-SINTILIMAB", "sintilimab": "ICI-SINTILIMAB",
    "阿替利珠单抗": "ICI-ATEZOLIZUMAB", "atezolizumab": "ICI-ATEZOLIZUMAB",
    "度伐利尤单抗": "ICI-DURVALUMAB", "durvalumab": "ICI-DURVALUMAB",
    "培美曲塞": "CHEMO-PEMETREXED", "pemetrexed": "CHEMO-PEMETREXED",
    "吉西他滨": "CHEMO-GEMCITABINE", "gemcitabine": "CHEMO-GEMCITABINE",
    "卡铂": "CHEMO-CARBOPLATIN", "carboplatin": "CHEMO-CARBOPLATIN",
    "顺铂": "CHEMO-CISPLATIN", "cisplatin": "CHEMO-CISPLATIN",
    "依托泊苷": "CHEMO-ETOPOSIDE", "etoposide": "CHEMO-ETOPOSIDE",
}

_TERM_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "clean", "terminology", "terminology_cancer.json",
)
_DRUG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "clean", "drug_labels"
)

_lexicon: Optional[Dict[str, str]] = None
_lexicon_lock = threading.Lock()


def _get_lexicon() -> Dict[str, str]:
    """术语词表（surface -> canonical），进程内缓存一次。

    来源：terminology_cancer.json（正名/同义词/英文名）、drug_labels（通用名/商品名）、
    以及上面的 _SUPPLEMENT_TERMS。全部是本地静态数据，无网络与模型调用。
    """
    global _lexicon
    if _lexicon is not None:
        return _lexicon
    with _lexicon_lock:
        if _lexicon is not None:
            return _lexicon
        surfaces: Dict[str, str] = {}
        surfaces.update(_SUPPLEMENT_TERMS)
        try:
            with open(_TERM_PATH, "r", encoding="utf-8") as f:
                for term in json.load(f):
                    tid = term.get("term_id")
                    if not tid:
                        continue
                    # 疾病类词条不入术语槽位：癌种已由 cancer 槽位用全量别名归一
                    # （「结直肠癌 / 大肠癌 / 结直肠」都映射到 colorectal）。若两套机制都管
                    # 癌种，「结直肠癌」与同义的「大肠癌」会因映射到不同 term_id 被判冲突。
                    if term.get("category") == "disease":
                        continue
                    candidates = [term.get("canonical"), term.get("en_name")]
                    candidates.extend(term.get("synonyms") or [])
                    for s in candidates:
                        if isinstance(s, str) and len(s.strip()) >= 2:
                            surfaces.setdefault(s.strip().lower(), tid)
        except Exception as e:
            logger.warning("[语义缓存] 术语词表加载失败（%s），仅用内置补丁", e)

        try:
            for name in os.listdir(_DRUG_DIR):
                if not name.endswith(".json"):
                    continue
                with open(os.path.join(_DRUG_DIR, name), "r", encoding="utf-8") as f:
                    records = json.load(f)
                if isinstance(records, dict):
                    records = [records]
                for rec in records:
                    did = rec.get("drug_id")
                    if not did:
                        continue
                    for s in [rec.get("generic_name")] + list(rec.get("brand_names") or []):
                        if isinstance(s, str) and len(s.strip()) >= 2:
                            surfaces.setdefault(s.strip().lower(), did)
        except Exception as e:
            logger.warning("[语义缓存] 药品名称加载失败（%s）", e)

        _lexicon = surfaces
        logger.info("[语义缓存] 术语词表 %d 条", len(surfaces))
    return _lexicon

_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "doc_catalog.json"
)

# 单条载荷上限：检索结果 50 项正文合计可达百 KB，超过 256KB 直接不缓存，避免 Redis 被撑爆
_MAX_PAYLOAD_BYTES = 256 * 1024
# 进程内向量备忘的条数上限：避免未命中时重复编码同一问题
_VECTOR_MEMO_SIZE = 32


# --------------------------------------------------------------------------- 归一化


def normalize_question(text: str) -> str:
    """缓存键归一化：压缩空白 + 统一小写 + 繁→简。

    与检索链路 _normalize_query_for_cache 同口径：同一问题不因输入法/繁体写法
    重复支付一次完整链路。
    """
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    try:
        from repositories.elasticsearch import zh_convert
        return zh_convert(collapsed, "t2s")
    except Exception:
        return collapsed


def build_filter_key(filters: Optional[Dict[str, Any]]) -> str:
    """过滤条件序列化为稳定键片段（键排序、列表内排序）。"""
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


# --------------------------------------------------------------------------- 槽位


def extract_slots(text: str) -> Dict[str, Any]:
    """抽取用于判别的实体槽位（只做字面抽取，不做语义推断）。"""
    if not text:
        return {}
    lowered = text.lower()

    cancers: Set[str] = set()
    for zh, (code, _range) in CANCER_TYPE_INFO.items():
        if zh in text:
            cancers.add(code)
    for alias, code in CANCER_TYPE_ALIASES.items():
        if alias in text:
            cancers.add(code)

    normalized = "".join(_STAGE_FULLWIDTH.get(ch, ch) for ch in text)
    stages: Set[str] = set(m.upper() for m in _STAGE_ROMAN_RE.findall(normalized))
    for m in _STAGE_CN_RE.findall(text):
        stages.add(_STAGE_CN_MAP.get(m[0], m[0]))
    for m in _STAGE_ARABIC_RE.findall(text.translate(_FW_DIGITS)):
        stages.add(_STAGE_ARABIC_MAP.get(m, m))
    stages.update(_STAGE_WORD_RE.findall(text))

    lines: Set[str] = set(_LINE_RE.findall(text))
    for pattern, canonical in _LINE_SYNONYMS:
        if pattern.search(text):
            lines.add(canonical)

    # 生物标志物状态（野生型/突变型、高/低表达、阳性/阴性…）：gene 名相同但状态相反
    # 时答案完全不同，余弦却常在 0.92 以上，必须靠此槽位拦住
    statuses: Set[str] = set(_STATUS_RE.findall(text))

    # 术语（药品 / 检查 / 疾病正名）：靠词表把中英文名归一，避免「奥沙利铂 ↔ 紫杉醇」
    # 这类只差一个词的问法被余弦判成同一条
    terms: Set[str] = set()
    for surface, canonical in _get_lexicon().items():
        if surface in lowered:
            terms.add(canonical)

    # 拉丁术语：基因 / 药物 / 检查项（EGFR、ALK、PD-L1、DPYD…）统一大写比对。
    # 纯罗马数字（I/II/III/IV…）已由 stage 槽位归一，必须剔除：否则「III期」的 III
    # 会留在 latin 里，与写成「三期」的同义问题产生假冲突。
    latin = {t.upper() for t in _LATIN_RE.findall(text)
             if len(t) >= 2 and not _ROMAN_ONLY_RE.match(t.upper())}
    # 分期数字不进 num 槽位：「3期」与「III期」归一后若还留下数字 3，会再次判冲突
    numbers = set(_NUM_RE.findall(_STAGE_ARABIC_RE.sub(" ", lowered.translate(_FW_DIGITS))))
    # 先剥离中性疑问结构，再判否定：「能不能用X」不是否定，「不能用X」才是
    negative = bool(_NEG_RE.search(_QUESTION_FORM_RE.sub(" ", text)))

    return {
        "cancer": sorted(cancers),
        "stage": sorted(stages),
        "line": sorted(lines),
        "status": sorted(statuses),
        "term": sorted(terms),
        "latin": sorted(latin),
        "num": sorted(numbers),
        "neg": negative,
    }


def slot_conflict(query_slots: Dict[str, Any], entry_slots: Dict[str, Any]) -> Optional[str]:
    """比较两组槽位；冲突时返回冲突原因，否则 None。

    规则（全部是「宁可漏命中，不可错命中」）：
      - 癌种 / 术语 / 分期 / 线数 / 标志物状态 / 拉丁术语 / 数字：查询侧出现的实体必须被条目覆盖
        （查询 ⊆ 条目）。查询多了「EGFR 突变」「二线」「65 岁」而条目问题里没有这些
        约束时，条目答案必然没针对它作答，复用就是错命中；
      - 否定：出现与否必须一致（「能不能用」与「不能用」答案相反）。
    条目侧为空而查询侧非空 → 判未命中；查询侧为空（用户没提）→ 放行，
    例如「肺癌怎么治疗」可以复用「肺癌一线怎么治疗」的依据。
    """
    q = query_slots or {}
    e = entry_slots or {}

    for field_name, label in (("cancer", "癌种"), ("term", "术语"),
                              ("stage", "分期"), ("line", "线数"), ("status", "标志物状态"),
                              ("latin", "术语"), ("num", "数字")):
        a, b = set(q.get(field_name) or []), set(e.get(field_name) or [])
        if a and not a <= b:
            return f"{label}未覆盖 {sorted(a)} vs {sorted(b)}"

    if bool(q.get("neg")) != bool(e.get("neg")):
        return "否定语义不一致"

    return None


# --------------------------------------------------------------------------- 索引快照


@dataclass
class _KindIndex:
    """某一类（qa / search）在进程内的向量索引快照，按 Redis 的 idxver 增量重建。"""

    version: int = -1
    ids: List[str] = field(default_factory=list)
    exact: Dict[str, str] = field(default_factory=dict)   # fk + "\x00" + 归一化问题 -> entry id
    filter_keys: List[str] = field(default_factory=list)
    slots: List[Dict[str, Any]] = field(default_factory=list)
    matrix: Optional[np.ndarray] = None


class SemanticCache:
    """Redis 语义缓存。所有失败路径均降级为「未命中」，不抛异常。"""

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._degraded_until = 0.0
        self._degraded_reason = ""
        self._indexes: Dict[str, _KindIndex] = {}
        self._index_lock = threading.RLock()
        self._version_lock = threading.Lock()
        self._last_version_check = 0.0
        self._vector_memo: Dict[Tuple[str, str], np.ndarray] = {}
        self._vector_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._rejects = 0

    # ------------------------------------------------------------------ 连接

    def _degrade(self, exc: Exception, action: str) -> None:
        self._degraded_until = time.monotonic() + 30.0
        reason = f"{type(exc).__name__}: {exc}"
        if reason != self._degraded_reason:
            self._degraded_reason = reason
            logger.warning("[语义缓存] %s失败，降级 30s：%s", action, reason)

    def _get_client(self):
        if _redis is None or not settings.semantic_cache_enabled:
            return None
        if time.monotonic() < self._degraded_until:
            return None
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                client = _redis.Redis.from_url(
                    settings.redis_url,
                    socket_timeout=settings.redis_timeout,
                    socket_connect_timeout=settings.redis_timeout,
                    decode_responses=False,
                    health_check_interval=30,
                )
                client.ping()
                self._client = client
                self._degraded_reason = ""
                logger.info("[语义缓存] 已连接 %s", settings.redis_url)
            except Exception as e:
                self._degrade(e, "连接")
                return None
        return self._client

    def available(self) -> bool:
        """连接是否可用（供调用方决定是否值得先算向量）。"""
        return self._get_client() is not None

    # ------------------------------------------------------------------ 键与版本

    @staticmethod
    def _entry_key(kind: str, entry_id: str) -> str:
        return f"{KEY_PREFIX}:entry:{kind}:{entry_id}"

    @staticmethod
    def _index_key(kind: str) -> str:
        return f"{KEY_PREFIX}:idx:{kind}"

    @staticmethod
    def _idxver_key(kind: str) -> str:
        return f"{KEY_PREFIX}:idxver:{kind}"

    @staticmethod
    def _born_key(kind: str) -> str:
        return f"{KEY_PREFIX}:born:{kind}"

    @staticmethod
    def _pinned_key(kind: str) -> str:
        """人工预热条目的集合：_trim 只在非 pinned 里淘汰，pinned 一律保留。"""
        return f"{KEY_PREFIX}:pinned:{kind}"

    def _flush(self, client) -> None:
        try:
            keys: List[bytes] = list(client.scan_iter(match=f"{KEY_PREFIX}:*", count=200))
            for i in range(0, len(keys), 200):
                client.delete(*keys[i:i + 200])
        finally:
            with self._index_lock:
                self._indexes.clear()
            with self._vector_lock:
                self._vector_memo.clear()

    def _ensure_version(self, client) -> bool:
        """语料版本校验（最多每 2s 一次），版本变化即整库作废。"""
        if time.monotonic() - self._last_version_check < 2.0:
            return True
        with self._version_lock:
            if time.monotonic() - self._last_version_check < 2.0:
                return True
            try:
                local = _corpus_version()
                remote = client.get(_VERSION_KEY)
                remote = remote.decode() if isinstance(remote, bytes) else remote
                if remote != local:
                    if remote is not None:
                        # 只有「已存在旧版本」才整库作废；首次写入（remote 为 None）不能清，
                        # 否则先 store 后 lookup 的第一个条目会被版本初始化顺手删掉
                        logger.info("[语义缓存] 语料版本变化 %s → %s，整库作废", remote, local)
                        self._flush(client)
                    client.set(_VERSION_KEY, local)
                self._last_version_check = time.monotonic()
                return True
            except Exception as e:
                self._degrade(e, "版本校验")
                return False

    # ------------------------------------------------------------------ 索引

    def _load_index(self, kind: str, client) -> Optional[_KindIndex]:
        try:
            raw_ver = client.get(self._idxver_key(kind))
            version = int(raw_ver) if raw_ver else 0
        except Exception as e:
            self._degrade(e, "索引版本读取")
            return None

        with self._index_lock:
            cached = self._indexes.get(kind)
            if cached is not None and cached.version == version:
                return cached

            try:
                raw_ids = client.smembers(self._index_key(kind))
            except Exception as e:
                self._degrade(e, "索引读取")
                return None

            ids = sorted(i.decode() if isinstance(i, bytes) else str(i) for i in raw_ids)
            index = _KindIndex(version=version)
            if ids:
                try:
                    pipe = client.pipeline()
                    for entry_id in ids:
                        pipe.hgetall(self._entry_key(kind, entry_id))
                    rows = pipe.execute()
                except Exception as e:
                    self._degrade(e, "索引批量读取")
                    return None

                vectors: List[np.ndarray] = []
                for entry_id, row in zip(ids, rows):
                    if not row:
                        continue
                    emb = row.get(b"emb")
                    question = row.get(b"q")
                    fk = row.get(b"fk")
                    slots_raw = row.get(b"slots") or b"{}"
                    if not emb or question is None:
                        continue
                    vector = np.frombuffer(emb, dtype=np.float32)
                    if vector.size == 0:
                        continue
                    q_text = question.decode("utf-8", errors="ignore")
                    fk_text = (fk or b"").decode("utf-8", errors="ignore")
                    try:
                        slots = json.loads(slots_raw.decode("utf-8"))
                    except Exception:
                        slots = {}
                    index.ids.append(entry_id)
                    index.filter_keys.append(fk_text)
                    index.slots.append(slots)
                    index.exact[f"{fk_text}\x00{q_text}"] = entry_id
                    vectors.append(vector)

                if vectors:
                    index.matrix = np.vstack(vectors)

            self._indexes[kind] = index
            logger.info("[语义缓存] %s 索引已加载：%d 条", kind, len(index.ids))
            return index

    # ------------------------------------------------------------------ 向量

    def _embed(self, kind: str, text: str) -> Optional[np.ndarray]:
        memo_key = (kind, text)
        with self._vector_lock:
            cached = self._vector_memo.get(memo_key)
        if cached is not None:
            return cached
        try:
            import torch
            from core.model_loader import get_embedding_model

            with torch.no_grad():
                encoded = get_embedding_model().encode(
                    [text],
                    batch_size=1,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            vector = np.asarray(encoded[0], dtype=np.float32)
        except Exception as e:
            logger.warning("[语义缓存] 向量编码失败：%s", e)
            return None

        with self._vector_lock:
            if len(self._vector_memo) >= _VECTOR_MEMO_SIZE and memo_key not in self._vector_memo:
                self._vector_memo.pop(next(iter(self._vector_memo)))
            self._vector_memo[memo_key] = vector
        return vector

    # ------------------------------------------------------------------ 读写

    def _count_miss(self, client, norm: str) -> None:
        self._misses += 1
        try:
            client.zincrby(_MISS_KEY, 1, norm)
        except Exception:
            pass

    @staticmethod
    def _decode_payload(raw) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _fetch_payload(self, kind: str, client, entry_id: str) -> Optional[Dict[str, Any]]:
        try:
            raw = client.hget(self._entry_key(kind, entry_id), "payload")
        except Exception as e:
            self._degrade(e, "载荷读取")
            return None
        return self._decode_payload(raw)

    def lookup(self, kind: str, text: str,
               filters: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], float]:
        """查缓存，返回 (载荷, 相似度)；未命中返回 (None, 0.0)。

        精确命中相似度记为 1.0。语义命中通过 L1 阈值 + L2 槽位守卫才算命中。
        """
        if not _kind_enabled(kind):
            return None, 0.0
        client = self._get_client()
        if client is None:
            return None, 0.0
        if not self._ensure_version(client):
            return None, 0.0

        index = self._load_index(kind, client)
        if index is None or not index.ids:
            return None, 0.0

        norm = normalize_question(text)
        if not norm:
            return None, 0.0
        fk = build_filter_key(filters)

        # L0 精确命中
        entry_id = index.exact.get(f"{fk}\x00{norm}")
        if entry_id:
            payload = self._fetch_payload(kind, client, entry_id)
            if payload is not None:
                self._hits += 1
                try:
                    client.zincrby(_HOT_KEY, 1, entry_id)
                except Exception:
                    pass
                logger.info("[语义缓存] %s 精确命中：%s", kind, norm[:40])
                return payload, 1.0
            # 载荷缺失（TTL 到期或容量淘汰）：当作未命中，并让索引下次重建
            self._invalidate_index(kind)

        # L1 余弦初筛
        if index.matrix is None:
            self._count_miss(client, norm)
            return None, 0.0
        vector = self._embed(kind, norm)
        if vector is None:
            self._count_miss(client, norm)
            return None, 0.0

        try:
            cosines = index.matrix @ vector
        except Exception:
            self._count_miss(client, norm)
            return None, 0.0

        # 过滤条件不同视为不同问题：直接屏蔽
        allowed = np.array([fk_part == fk for fk_part in index.filter_keys], dtype=bool)
        if not allowed.any():
            self._count_miss(client, norm)
            return None, 0.0
        cosines = np.where(allowed, cosines, -1.0)

        best = int(np.argmax(cosines))
        score = float(cosines[best])
        threshold = float(settings.semantic_cache_threshold)
        # 每次未命中都会走到这里，300 条热问规模下按 info 打会刷屏；只在需要
        # 排查「为什么不命中」时用 DEBUG 打开（判定结果本身仍有 info 日志）。
        logger.debug("[语义缓存] %s 最高余弦 %.4f（阈值 %.4f，候选 %d 条）：%s",
                     kind, score, threshold, int(allowed.sum()), norm[:40])
        if score < threshold:
            self._count_miss(client, norm)
            return None, 0.0

        # L2 槽位守卫
        reason = slot_conflict(extract_slots(text), index.slots[best])
        if reason:
            self._rejects += 1
            logger.info("[语义缓存] %s 语义候选被守卫拒绝（cos=%.4f）：%s",
                        kind, score, reason)
            self._count_miss(client, norm)
            return None, 0.0

        payload = self._fetch_payload(kind, client, index.ids[best])
        if payload is None:
            self._invalidate_index(kind)
            self._count_miss(client, norm)
            return None, 0.0

        self._hits += 1
        try:
            client.zincrby(_HOT_KEY, 1, index.ids[best])
        except Exception:
            pass
        logger.info("[语义缓存] %s 语义命中（cos=%.4f）：%s", kind, score, norm[:40])
        return payload, score

    def _invalidate_index(self, kind: str) -> None:
        with self._index_lock:
            self._indexes.pop(kind, None)

    def store(self, kind: str, text: str, payload: Dict[str, Any],
              filters: Optional[Dict[str, Any]] = None,
              meta: Optional[Dict[str, Any]] = None) -> bool:
        """写入条目（同一归一化问题 + 过滤条件覆盖写）。失败静默返回 False。"""
        if not _kind_enabled(kind):
            return False
        client = self._get_client()
        if client is None:
            return False
        if not self._ensure_version(client):
            return False
        norm = normalize_question(text)
        if not norm or not payload:
            return False

        try:
            payload_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except Exception:
            return False
        if len(payload_json) > _MAX_PAYLOAD_BYTES:
            logger.info("[语义缓存] 载荷过大（%d 字节），跳过缓存", len(payload_json))
            return False

        vector = self._embed(kind, norm)
        if vector is None:
            return False

        fk = build_filter_key(filters)
        entry_id = hashlib.sha1(f"{kind}\x00{fk}\x00{norm}".encode("utf-8")).hexdigest()[:16]
        slots = extract_slots(text)
        key = self._entry_key(kind, entry_id)
        meta_map = dict(meta or {})
        # 人工预热条目用更长的 TTL：它们是真实 LLM 调用的产物，不能和运行时长尾共用 7 天
        ttl = int(settings.semantic_cache_seeded_ttl if meta_map.get("seeded")
                  else settings.semantic_cache_ttl)

        try:
            pipe = client.pipeline()
            pipe.hset(key, mapping={
                "q": norm.encode("utf-8"),
                "fk": fk.encode("utf-8"),
                "slots": json.dumps(slots, ensure_ascii=False).encode("utf-8"),
                "emb": vector.astype(np.float32).tobytes(),
                "payload": payload_json,
                "ts": str(int(time.time())).encode("utf-8"),
                "meta": json.dumps(meta_map, ensure_ascii=False).encode("utf-8"),
            })
            pipe.expire(key, ttl)
            pipe.sadd(self._index_key(kind), entry_id)
            pipe.zadd(self._born_key(kind), {entry_id: time.time()})
            if meta_map.get("pinned"):
                pipe.sadd(self._pinned_key(kind), entry_id)
            pipe.incr(self._idxver_key(kind))
            pipe.execute()
        except Exception as e:
            self._degrade(e, "写入")
            return False

        self._trim(kind, client)
        return True

    def _trim(self, kind: str, client) -> None:
        """超出容量时按「命中次数」淘汰：热度最低的先走，同热度按写入时间早的先走。

        pinned 条目（人工预热）永不参与淘汰，只在非 pinned 里挑；可淘汰条目不足时
        直接跳过并打 WARNING —— 宁可超容量，也不能为了凑数删掉预热成果。

        热度取自 sc:v1:hot（lookup 命中时 zincrby，从未命中过的条目不在表里，按 0 计）。
        不再用纯 FIFO：首批人工预热的 30 条热问写入最早，纯 FIFO 会让它们成为第一批
        被淘汰的对象，恰好把最该保留的条目优先清掉。pinned 只解决「从未被命中过的
        预热条目」这一半问题，另一半靠这里的热度排序。

        成本：用一次 ZRANGE WITHSCORES 全量读取热度后在内存排序，而不是逐条 ZSCORE。
        300 条规模下前者 1 次往返 + O(N log N) 内存排序（微秒级），后者是 N 次往返。
        且 trim 只在写入后超过上限时触发，不在每次 lookup 的热路径上。
        """
        try:
            born_key = self._born_key(kind)
            total = int(client.zcard(born_key))
            limit = int(settings.semantic_cache_max_entries)
            if total <= limit:
                return
            pinned = {m.decode() if isinstance(m, bytes) else str(m)
                      for m in client.smembers(self._pinned_key(kind))}
            born = [(m.decode() if isinstance(m, bytes) else str(m), float(s))
                    for m, s in client.zrange(born_key, 0, -1, withscores=True)]
            try:
                hot = {m.decode() if isinstance(m, bytes) else str(m): float(s)
                       for m, s in client.zrange(_HOT_KEY, 0, -1, withscores=True)}
            except Exception:
                # 热度表读失败不影响淘汰：全部按 0 计，退化为 FIFO（兜底）
                hot = {}
            candidates = [(eid, born_ts) for eid, born_ts in born if eid not in pinned]
            need = total - limit
            if len(candidates) < need:
                logger.warning(
                    "[语义缓存] %s 可淘汰条目不足（需 %d，非 pinned 仅 %d，pinned %d），"
                    "跳过淘汰，允许暂时超出上限", kind, need, len(candidates), len(pinned))
                return
            candidates.sort(key=lambda row: (hot.get(row[0], 0.0), row[1]))
            stale = candidates[:need]
            pipe = client.pipeline()
            for entry_id, _born_ts in stale:
                pipe.delete(self._entry_key(kind, entry_id))
                pipe.srem(self._index_key(kind), entry_id)
                pipe.zrem(born_key, entry_id)
                # 热度表必须同步清理：条目已删但 id 留在 hot 里会让热度表只增不减，
                # 也会让同名 id 复活时带着旧热度（id 由 kind+问题哈希决定，会复用）
                pipe.zrem(_HOT_KEY, entry_id)
            pipe.incr(self._idxver_key(kind))
            pipe.execute()
        except Exception as e:
            self._degrade(e, "容量淘汰")

    # ------------------------------------------------------------------ 运维

    def clear(self, kind: Optional[str] = None) -> bool:
        """清空缓存（指定 kind 或全部）。供脚本与人工运维使用。"""
        client = self._get_client()
        if client is None:
            return False
        try:
            if kind:
                prefix = f"{KEY_PREFIX}:entry:{kind}:"
                entry_keys = [k.decode() if isinstance(k, bytes) else str(k)
                              for k in client.scan_iter(match=f"{KEY_PREFIX}:entry:{kind}:*", count=200)]
                keys = [self._index_key(kind), self._idxver_key(kind),
                        self._born_key(kind), self._pinned_key(kind)] + entry_keys
                # 一并清掉这些 id 的热度分数：id 由 sha1 确定性生成，只删条目不清 hot 的话，
                # 同一问题重新入库会继承旧热度，把淘汰顺序带偏。只删本 kind 的 id，不动其他 kind。
                pipe = client.pipeline()
                if keys:
                    pipe.delete(*keys)
                for entry_key in entry_keys:
                    pipe.zrem(_HOT_KEY, entry_key[len(prefix):])
                pipe.execute()
                self._invalidate_index(kind)
            else:
                self._flush(client)
            return True
        except Exception as e:
            self._degrade(e, "清空")
            return False

    def stats(self) -> Dict[str, Any]:
        # 先取连接再算 connected：kinds_stats() 内部也会惰性建连，
        # 若把它放在 connected 之后求值，首次请求必然报 connected=false 再自查出 30 条条目。
        client = self._get_client()
        return {
            "enabled": settings.semantic_cache_enabled,
            "connected": client is not None,
            "hits": self._hits,
            "misses": self._misses,
            "guard_rejects": self._rejects,
            "threshold": settings.semantic_cache_threshold,
            "kinds": self.kinds_stats(),
        }

    def kinds_stats(self) -> Dict[str, Dict[str, int]]:
        """按 kind 的存活条目数 / pinned 数。

        口径一律用 EXISTS 判定 sc:v1:entry:{kind}:<id> 是否存在。idx / born / pinned
        三个集合都不会随条目 TTL 过期级联清理（Redis 不提供这种联动），所以集合基数、
        甚至「pinned ∩ born」都会把已过期条目算成存量，必须逐条 EXISTS。
        规模百条级，一次 pipeline 批量判定，百来次 EXISTS 在 1 次往返内完成。
        """
        client = self._get_client()
        empty = {kind: {"entries": 0, "pinned": 0} for kind in ("qa", "search")}
        if client is None:
            return empty
        try:
            out: Dict[str, Dict[str, int]] = {}
            for kind in ("qa", "search"):
                index_ids = {m.decode() if isinstance(m, bytes) else str(m)
                             for m in client.smembers(self._index_key(kind))}
                pinned_ids = {m.decode() if isinstance(m, bytes) else str(m)
                              for m in client.smembers(self._pinned_key(kind))}
                candidates = sorted(index_ids | pinned_ids)
                if not candidates:
                    out[kind] = {"entries": 0, "pinned": 0}
                    continue
                pipe = client.pipeline()
                for entry_id in candidates:
                    pipe.exists(self._entry_key(kind, entry_id))
                live = {eid for eid, ok in zip(candidates, pipe.execute()) if int(ok or 0)}
                out[kind] = {"entries": len(live & index_ids), "pinned": len(live & pinned_ids)}
            return out
        except Exception as e:
            self._degrade(e, "统计")
            return empty


def _corpus_version() -> str:
    try:
        return f"{os.path.getmtime(_CATALOG_PATH):.0f}"
    except OSError:
        return "0"


def _kind_enabled(kind: str) -> bool:
    if not settings.semantic_cache_enabled:
        return False
    if kind == "qa":
        return settings.semantic_cache_qa_enabled
    if kind == "search":
        return settings.semantic_cache_search_enabled
    return False


_cache: Optional[SemanticCache] = None
_cache_lock = threading.Lock()


def get_semantic_cache() -> SemanticCache:
    """进程内单例（惰性创建）。"""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = SemanticCache()
    return _cache
