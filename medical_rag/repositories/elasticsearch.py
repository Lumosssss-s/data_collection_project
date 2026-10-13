from typing import List, Dict, Optional, Any, Tuple, Iterable
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError, TransportError, ApiError
from core.config import settings
from core.model_loader import get_embedding_model
from utils.topic_classifier import TopicClassifier


_ZH_T2S_MAP = {
    '網': '网', '絡': '络', '個': '个', '資': '资', '訊': '讯', '護': '护',
    '產': '产', '電': '电', '腦': '脑', '擊': '击', '竊': '窃', '盜': '盗',
    '僞': '伪', '關': '关', '係': '系', '機': '机', '構': '构', '團': '团',
    '體': '体', '監': '监', '辦': '办', '廳': '厅', '處': '处', '員': '员',
    '職': '职', '區': '区', '域': '域', '內': '内', '務': '务', '險': '险',
    '報': '报', '舉': '举', '復': '复', '製': '制', '傳': '传', '輸': '输',
    '發': '发', '佈': '布', '獲': '获', '數': '数', '據': '据', '隱': '隐',
    '私': '私', '祕': '秘', '密': '密', '條': '条', '約': '约', '規': '规',
    '則': '则', '範': '范', '圍': '围', '標': '标', '準': '准', '審': '审',
    '計': '计', '訴': '诉', '訟': '讼', '罰': '罚', '執': '执', '實': '实',
    '施': '施', '細': '细', '總': '总', '附': '附', '錄': '录', '匯': '汇',
    '兌': '兑', '幣': '币', '貨': '货', '銀': '银', '證': '证', '券': '券',
    '債': '债', '權': '权', '務': '务', '業': '业', '廠': '厂', '號': '号',
    '碼': '码', '圖': '图', '視': '视', '頻': '频', '聲': '声', '軟': '软',
    '頁': '页', '連': '连', '鏈': '链', '結': '结', '載': '载', '郵': '邮',
    '即': '即', '時': '时', '討': '讨', '論': '论', '壇': '坛',
    '購': '购', '簽': '签', '署': '署', '訂': '订', '契': '契',
    '知': '知', '識': '识', '版': '版', '專': '专', '利': '利',
    '著': '著', '營': '营', '經': '经', '照': '照', '許': '许',
    '可': '可', '書': '书', '登': '登', '記': '记', '註': '注', '冊': '册',
    '備': '备', '案': '案', '開': '开', '創': '创', '新': '新', '研': '研',
    '究': '究', '試': '试', '驗': '验', '測': '测', '檢': '检', '查': '查',
    '鑑': '鉴', '定': '定', '評': '评', '估': '估', '核': '核', '准': '准',
    '認': '认', '責': '责', '任': '任', '義': '义', '利': '利', '益': '益',
    '損': '损', '害': '害', '賠': '赔', '償': '偿', '補': '补', '助': '助',
    '獎': '奖', '勵': '励', '懲': '惩', '戒': '戒', '紀': '纪', '律': '律',
    '衛': '卫', '生': '生', '醫': '医', '療': '疗', '藥': '药', '健': '健',
    '康': '康', '環': '环', '境': '境', '汙': '污', '染': '染', '廢': '废',
    '棄': '弃', '勞': '劳', '僱': '雇', '傭': '佣', '就': '就', '薪': '薪',
    '福': '福', '休': '休', '假': '假', '解': '解', '辭': '辞', '退': '退',
    '消': '消', '費': '费', '者': '者', '兒': '儿', '童': '童', '少': '少',
    '青': '青', '老': '老', '殘': '残', '障': '障', '疾': '疾', '婦': '妇',
    '幼': '幼', '家': '家', '庭': '庭', '教': '教', '育': '育', '學': '学',
    '習': '习', '校': '校', '院': '院', '科': '科', '技': '技', '術': '术',
    '工': '工', '農': '农', '漁': '渔', '礦': '矿', '交': '交', '通': '通',
    '運': '运', '物': '物', '流': '流', '能': '能', '源': '源', '力': '力',
    '水': '水', '土': '土', '建': '建', '設': '设', '築': '筑', '屋': '屋',
    '宇': '宇', '公': '公', '共': '共', '秩': '秩', '序': '序', '國': '国',
    '家': '家', '民': '民', '族': '族', '社': '社', '會': '会', '政': '政',
    '治': '治', '軍': '军', '事': '事', '外': '外', '司': '司', '法': '法',
    '立': '立', '行': '行', '政': '政', '察': '察', '警': '警', '獄': '狱',
    '稅': '税', '海': '海', '關': '关', '財': '财', '預': '预', '算': '算',
    '統': '统', '際': '际', '地': '地', '城': '城', '市': '市', '鄉': '乡',
    '鎮': '镇', '村': '村', '莊': '庄', '歐': '欧', '盟': '盟', '聯': '联',
    '合': '合', '世': '世', '界': '界', '貿': '贸', '易': '易', '投': '投',
    '引': '引', '並': '并', '重': '重', '組': '组', '整': '整', '合': '合',
    '打': '打', '犯': '犯', '罪': '罪', '刑': '刑', '民': '民', '仲': '仲',
    '裁': '裁', '調': '调', '節': '节', '約': '约',
}


def zh_t2s(text: str) -> str:
    """繁体转简体（轻量级，覆盖法规名称常用字）"""
    if not text:
        return text
    return ''.join(_ZH_T2S_MAP.get(ch, ch) for ch in text)


def zh_s2t(text: str) -> str:
    """简体转繁体（反向映射，轻量级）"""
    if not text:
        return text
    s2t = {v: k for k, v in _ZH_T2S_MAP.items()}
    return ''.join(s2t.get(ch, ch) for ch in text)


# ================================================================
#  完整繁简字符表（检索侧查询改写用）
#  ----------------------------------------------------------------
#  与上方 _ZH_T2S_MAP 的分工：
#    - 轻量表（约 200 字）服务于「法规名/实体名」规范化，其口径已被实体消歧 L1~L3 与
#      KG 抽取链路的实测调优所绑定，故保持原样不动；
#    - 本表是 OpenCC TSCharacters/STCharacters 的完整字符集（繁 4148 / 简 4012），
#      只用于检索侧的查询改写。
#
#  为什么检索侧必须改写：ES 的 IK 词典不含繁体字，繁体正文会被切成一字一 token
#  （实测 analyze("勞動關係") -> 勞/動/關/係），而简体查询经 IK 得到的是词级 token
#  （劳动/关系）。两者 token 空间不相交，导致「澳门/香港等繁体语料上，简体查询的
#  BM25 召回恒为 0 条」（实测 BM25("劳动关系", 法域=澳门) = 0 条）。
#  做法是把同一查询的繁、简两种写法一并送入 multi_match，任一写法命中即可。
# ================================================================
_ZH_CONVERT_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _load_zh_convert() -> Dict[str, Dict[str, str]]:
    """加载完整繁简字符表；失败时降级为空表（等于不改写，不阻断检索）"""
    global _ZH_CONVERT_CACHE
    if _ZH_CONVERT_CACHE is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            os.pardir, "data", "zh_convert.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _ZH_CONVERT_CACHE = {"t2s": data.get("t2s", {}), "s2t": data.get("s2t", {})}
        except Exception as e:
            logger.warning(f"[繁简改写] 字表加载失败，本次不做改写: {e}")
            _ZH_CONVERT_CACHE = {"t2s": {}, "s2t": {}}
    return _ZH_CONVERT_CACHE


def zh_convert(text: str, direction: str) -> str:
    """按完整字表做繁简转换；direction 为 't2s'（繁→简）或 's2t'（简→繁）"""
    if not text:
        return text
    table = _load_zh_convert().get(direction) or {}
    return ''.join(table.get(ch, ch) for ch in text)


def zh_query_variants(text: str) -> List[str]:
    """返回查询的繁简写法列表（原样 / 繁转简 / 简转繁，去重、保持顺序）。

    多对一的字符（如「系」在简→繁时既可能是「系」也可能是「係」）只取 OpenCC 的
    首选候选；对 BM25 而言错误候选只是多出若干个不命中的 token，不会误伤召回。
    """
    if not text:
        return []
    variants = [text]
    for direction in ("t2s", "s2t"):
        converted = zh_convert(text, direction)
        if converted and converted not in variants:
            variants.append(converted)
    return variants


# 法域英文 -> 中文映射
_JURISDICTION_ZH_MAP: Dict[str, str] = {
    "us": "美国",
    "usa": "美国",
    "united states": "美国",
    "hk": "香港",
    "hong kong": "香港",
    "mo": "澳门",
    "macau": "澳门",
    "sg": "新加坡",
    "singapore": "新加坡",
}


def _jurisdiction_to_zh(jur: str) -> str:
    """将法域名称转换为简体中文"""
    if not jur:
        return jur
    # 如果已经是中文，直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in jur):
        return jur
    # 尝试英文映射
    lower_jur = jur.lower().strip()
    return _JURISDICTION_ZH_MAP.get(lower_jur, jur)
_TOPIC_LABEL_ZH_CACHE: Optional[Dict[str, str]] = None
# 主题标签兜底映射：BE-35 医疗化后 taxonomy_merged.json（v3.0）已覆盖全部
# 5 癌种 + 3 文档类型 + 15 场景，无需额外硬编码兜底；保留空字典作为
# _to_label_zh / _label_zh_to_topic_id 的回落占位（找不到时返回原值）。
_TOPIC_FALLBACK_ZH: Dict[str, str] = {}


def _load_topic_label_zh_mapping() -> Dict[str, str]:
    """加载 taxonomy_merged.json，返回 {id: label_zh} 映射"""
    global _TOPIC_LABEL_ZH_CACHE
    if _TOPIC_LABEL_ZH_CACHE is not None:
        return _TOPIC_LABEL_ZH_CACHE

    taxonomy_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "taxonomy_merged.json"
    )
    mapping = {}
    try:
        with open(taxonomy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for t in data.get("topics", []):
            tid = t.get("id", "")
            label = t.get("label_zh", "")
            if tid and label:
                mapping[tid] = label
    except Exception:
        pass

    _TOPIC_LABEL_ZH_CACHE = mapping
    return mapping


def _to_label_zh(topic_id: str) -> str:
    """将英文 topic_id 转为中文标签，找不到则返回原值"""
    mapping = _load_topic_label_zh_mapping()
    if topic_id in mapping:
        return mapping[topic_id]
    return _TOPIC_FALLBACK_ZH.get(topic_id, topic_id)


def _label_zh_to_topic_id(label_zh: str) -> str:
    """将中文标签转为英文 topic_id，找不到则返回原值"""
    mapping = _load_topic_label_zh_mapping()
    # 反向查找：label_zh -> id
    for tid, label in mapping.items():
        if label == label_zh:
            return tid
    # fallback 反查
    for tid, label in _TOPIC_FALLBACK_ZH.items():
        if label == label_zh:
            return tid
    return label_zh


# 嵌套字段映射：字段名 → nested path（C2 §3.3：topics_details 为 nested 类型）
_NESTED_FIELD_PATHS: Dict[str, str] = {
    "topics_details.label_zh": "topics_details",
    "topics_details.id": "topics_details",
}


def _term_clause(field: str, value: Any) -> Dict[str, Any]:
    """构造 term 过滤条件；嵌套字段自动包裹 nested 查询。

    主题字段在 C2 中为 nested（topics_details），直接 ``{"term": {"topics_details.label_zh": ...}}``
    无法命中，必须包裹为 ``{"nested": {"path": ..., "query": {"term": {...}}}}``。
    """
    term = {"term": {field: value}}
    path = _NESTED_FIELD_PATHS.get(field)
    if path:
        return {"nested": {"path": path, "query": term}}
    return term


# 主索引 structured 字段白名单（C2 §3.3 mapping ∩ 主方案 §5.7.2）。
# 落库时按此白名单从 metadata 透传，避免写入法规遗留字段或未声明字段：
#   通用层：data_type/review_status/updated_at
#   DOC 层：doc_id/doc_type/issuer/publish_date/cancer_types/license_note/file_path/doc_hash
#   REC 层：rec_id/cancer_type/breadcrumb/scenario/stage/stage_detail/biomarker/
#           population/verbatim/evidence_level/evidence_level_original/rec_strength/refs/page
#   DRUG 层：drug_id/generic_name/brand_names/atc_code/approval_no/indications/dosage/
#           contraindications/adverse_reactions/adverse_reaction_terms/interactions
#   TERM 层：term_id/canonical/category/synonyms/icd10/icd_o3/atc/pinyin/en_name/mapping_status
# 通用字段（content/embedding/title/chunk_index/topics_details/taxonomy_version）
# 由 add_documents 单独处理，不在此列。
_MEDICAL_DOC_FIELDS: Tuple[str, ...] = (
    # 通用
    "data_type", "review_status", "updated_at",
    # DOC
    "doc_id", "doc_type", "issuer", "publish_date", "cancer_types",
    "license_note", "file_path", "doc_hash",
    # REC
    "rec_id", "cancer_type", "breadcrumb", "scenario", "stage", "stage_detail",
    "biomarker", "population", "verbatim", "evidence_level",
    "evidence_level_original", "rec_strength", "refs", "page",
    # DRUG
    "drug_id", "generic_name", "brand_names", "atc_code", "approval_no",
    "indications", "dosage", "contraindications", "adverse_reactions",
    "adverse_reaction_terms", "interactions",
    # TERM
    "term_id", "canonical", "category", "synonyms", "icd10", "icd_o3",
    "atc", "pinyin", "en_name", "mapping_status",
)


def _medical_metadata(source: Dict) -> Dict[str, Any]:
    """读侧 metadata 组装：通用字段 + §5.7.2 白名单透传（C2 §3.3）。

    与写侧 add_documents 的 _MEDICAL_DOC_FIELDS 同源，保证「写进去什么、读出来什么」；
    不再给 metadata 塞 law_id / jurisdiction / article_number 等法规遗留字段。
    """
    meta: Dict[str, Any] = {
        "title": source.get("title", ""),
        "chunk_index": source.get("chunk_index", 0),
        "topics_details": source.get("topics_details", []),
    }
    for field in _MEDICAL_DOC_FIELDS:
        if source.get(field) is not None:
            meta[field] = source[field]
    return meta


# ====================================================================
#  同法规条款引用解析（组件D：引用链多跳）
#  ----------------------------------------------------------------
#  条款编号在法规内是局部的（「第 5 條」只在本法规内有意义），因此正文里的
#  「第X條」必然是同一法规的条款引用 —— 据此建边不需要解析法规名，精度高。
#  跨法规引用（如「第7/2023號法律第三十六條」）需要「法规名 -> law_id」映射，
#  且实测 KG 中 cross_refers 仅 1 条，本阶段不参与扩展。
# ====================================================================

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000,
}

# 「第X條 / 第X条」，X 为阿拉伯数字（含全角）或中文数字
_ARTICLE_REF_RE = re.compile(r"第\s*([0-9０-９]{1,4}|[零〇一二三四五六七八九十百千兩两]{1,8})\s*[條条]")

# 匹配位置前紧邻「...號法律/法令/行政法規/行政命令/批示」时，该条款号属于另一部法规
_OTHER_LAW_TAIL_RE = re.compile(
    r"號\s*(?:法律|法令|行政法規|行政命令|批示|訓令|決議|規章)[^。；;]{0,60}$"
)

# 跨法规引用（可从正文确定性推导目标 law_id）：
#   澳门「第N/YYYY號法律」→ MAC_LEI_N_YYYY，「第N/YYYY號行政法規」→ MAC_REG_N_YYYY
#   香港「第N章」→ HK_CAP_N
# 这些引用正是被上面的 _OTHER_LAW_TAIL_RE 从「同法规内引用」中剔除的部分。剔除本身是
# 正确的（它们不属于本法规），因此跨法规解析独立进行、不复用该守卫，以免相互影响。
_MAC_CROSS_LAW_RE = re.compile(r"第\s*(\d{1,4})\s*/\s*(\d{4})\s*號\s*(法律|行政法規)")
_HK_CAP_RE = re.compile(r"第\s*(\d{1,4})\s*章")
_MAC_LAW_TYPE_CODE = {"法律": "LEI", "行政法規": "REG"}
# 跨法规引用后紧随的条款号
_ARTICLE_AFTER_RE = re.compile(
    r"第\s*([0-9０-９]{1,4}|[零〇一二三四五六七八九十百千兩两]{1,8})\s*[條条]"
)

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _cn_numeral_to_int(text: str) -> Optional[int]:
    """中文/阿拉伯数字转整数。支持「十五」「二十一」「一百零三」；无法解析返回 None"""
    if not text:
        return None
    text = text.translate(_FULLWIDTH_DIGITS).strip()
    if text.isdigit():
        return int(text)
    if all(ch in ("零", "〇") for ch in text):
        return 0

    total = 0     # 已结算的更高位
    number = 0    # 当前累计的个位数
    for ch in text:
        if ch in ("零", "〇"):
            continue
        value = _CN_DIGITS.get(ch)
        if value is None:
            return None
        if value >= 10:
            # 「十五」= 1*10+5，「二十」= 2*10，「一百零三」= 100+3
            total += (number or 1) * value
            number = 0
        else:
            number = value
    return total + number


def parse_intra_law_refs(content: str, article_number: str) -> List[str]:
    """
    从条款正文解析同法规内被引用的条款号，返回数字字符串列表（如 ["2", "15"]）。

    会主动剔除三类跨法规引用的误判：
      1. 条款号落在书名号《》内部（如「《收費總表第一百一十五條》」）；
      2. 条款号紧跟在一个闭合的书名号之后（如「《收費總表》第一百一十五條」，
         该条款号属于书名号里的法规）；
      3. 条款号紧跟在「...號法律/法令/行政法規/...」之后（如「第7/2023號法律第三十六條」）。

    返回结果只表示「正文里出现了这个条款号」，目标条款是否存在由回取阶段自然过滤 ——
    这也是最后一道防线：即便前三条守卫漏判，回取不到的目标也不会进入结果。
    """
    if not content:
        return []

    self_num = str(article_number or "").strip()
    refs: List[str] = []
    seen = set()

    for match in _ARTICLE_REF_RE.finditer(content):
        prefix = content[: match.start()]
        stripped = prefix.rstrip()
        # 书名号未闭合：当前条款号位于某部法规的标题内部
        if prefix.count("《") > prefix.count("》"):
            continue
        # 条款号紧跟闭合书名号：如「《收費總表》第一百一十五條」，归书名号内的法规
        if stripped.endswith("》"):
            continue
        # 紧邻前文出现其他法规名，条款号归其所有
        if _OTHER_LAW_TAIL_RE.search(stripped[-80:]):
            continue

        number = _cn_numeral_to_int(match.group(1))
        if not number or number <= 0:
            continue

        ref = str(number)
        if ref == self_num or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)

    return refs


def parse_cross_law_refs(content: str, article_number: str,
                         law_id: str) -> List[Tuple[str, str]]:
    """解析条款正文中指向【其他法规】的引用，返回 [(目标 law_id, 目标条款号), ...]。

    只覆盖能从文本确定性推导 law_id 的模式：
      - 澳门「第N/YYYY號法律/行政法規」→ MAC_{LEI|REG}_N_YYYY
      - 香港「第N章」→ HK_CAP_N
    并要求引用后紧随一个具体条款号（间隔超过 8 个字符即视为无关），
    这样扩展出去的才是「另一部法规的具体条款」，而不是泛泛的法规名。

    目标法规/条款是否真实存在不在解析阶段校验：交给回取阶段自然过滤，
    因此不引入法规字典依赖，解析失败一律返回空、不阻断主链路。
    """
    if not content:
        return []

    self_law = law_id or ""
    self_article = str(article_number or "")
    out: List[Tuple[str, str]] = []
    seen = set()

    def _pick(target_law: str, after_pos: int) -> None:
        if not target_law or target_law == self_law:
            return  # 自引用无扩展价值
        m = _ARTICLE_AFTER_RE.search(content, after_pos, after_pos + 8)
        if not m:
            return
        # 法规名与条款号之间若出现句读分隔（逗号/顿号/分号/句号等），该条款号多半是
        # 本条款自身的条号而非被引法规的条号（如「…第5/2009號行政法規，第7條…」），
        # 直接跳过以降低误连边。合法的直引形式（「…行政法規第十七條」）间隔为空或「的」。
        gap = content[after_pos:m.start()]
        if any(ch in "，,、。；;：:！？!?…" for ch in gap):
            return
        number = _cn_numeral_to_int(m.group(1))
        if not number or number <= 0 or str(number) == self_article:
            return
        key = (target_law, str(number))
        if key in seen:
            return
        seen.add(key)
        out.append(key)

    for m in _MAC_CROSS_LAW_RE.finditer(content):
        code = _MAC_LAW_TYPE_CODE.get(m.group(3))
        if code:
            _pick(f"MAC_{code}_{int(m.group(1))}_{m.group(2)}", m.end())
    for m in _HK_CAP_RE.finditer(content):
        _pick(f"HK_CAP_{int(m.group(1))}", m.end())

    return out


class ElasticsearchRepository:
    def __init__(self):
        self._init_client()
        self._model = None  # 懒加载，避免启动时加载大模型
        self._non_active_cache = None  # 失效法规 law_id 缓存：(mtime, ids)
        self._law_title_index_cache = None  # 法规标题索引缓存：{简体归一标题: law_id}
        self._init_classifier()
        self._create_index_if_not_exists()
        # C2 §8：5 索引首次启动自动建（mapping 错误在启动时暴露，而非首次使用时）
        # cache / KG 保留懒加载 ensure（幂等），此处提前触发一次。
        self._ensure_disease_index()
        self._ensure_cache_index()
        self._ensure_kg_indices()
    
    def _init_classifier(self):
        self.classifier = TopicClassifier()
    
    def _init_client(self):
        client_kwargs: Dict[str, Any] = {
            "hosts": settings.es_hosts,
            "verify_certs": settings.es_verify_certs,
            "request_timeout": settings.es_request_timeout,
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "compatible-with": "8"
            }
        }
        
        if settings.es_user and settings.es_password:
            client_kwargs["basic_auth"] = (settings.es_user, settings.es_password)
        
        self.client = Elasticsearch(**client_kwargs)
        
        if not self.client.ping():
            raise ConnectionError("无法连接到 Elasticsearch")
    
    def _get_model(self):
        """懒加载 embedding 模型（首次使用时加载）"""
        if self._model is None:
            self._model = get_embedding_model()
        return self._model
    
    def _create_index_if_not_exists(self):
        if not self.client.indices.exists(index=settings.es_index_name):
            index_settings = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "analyzer": {
                            "text_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["lowercase", "stop"]
                            },
                            "chinese_analyzer": {
                                "type": "custom",
                                "tokenizer": "ik_max_word",
                                "filter": ["lowercase"]
                            }
                        }
                    }
                },
                "mappings": {
                    # 医疗主索引 medical_knowledge（C2《ES 索引与 Mapping 规范》§3.3）
                    # 四类 data_type（doc / rec / drug / term）共存；metadata 塞杂物
                    # 模式废止，全部结构化字段显式声明。
                    "properties": {
                        # ---- 通用层（全部 data_type 共有）----
                        "data_type": {"type": "keyword"},  # doc / rec / drug / term
                        "title": {
                            "type": "text",
                            "analyzer": "chinese_analyzer",
                            "fields": {
                                "keyword": {"type": "keyword", "ignore_above": 256}
                            }
                        },
                        "content": {
                            "type": "text",
                            "analyzer": "chinese_analyzer",
                            "fields": {
                                "keyword": {"type": "keyword", "ignore_above": 256}
                            }
                        },
                        "embedding": {
                            "type": "dense_vector",
                            "dims": 1024,
                            "index": True,
                            "similarity": "cosine"
                        },
                        "chunk_index": {"type": "integer"},  # 仅 drug 分块生效，其余 = 0
                        "review_status": {"type": "keyword"},  # draft / reviewed / approved
                        "taxonomy_version": {"type": "keyword"},
                        "topics_details": {
                            "type": "nested",
                            "properties": {
                                "id": {"type": "keyword"},
                                "label_zh": {"type": "keyword"},
                                "score": {"type": "float"},
                                "matched_keywords": {"type": "keyword"}
                            }
                        },
                        "updated_at": {"type": "date"},
                        # ---- DOC 专属层（指南 / 规范 / 共识元数据）----
                        "doc_id": {"type": "keyword"},       # 亦作 ES _id
                        "doc_type": {"type": "keyword"},      # guideline / standard / consensus
                        "issuer": {"type": "keyword"},
                        "publish_date": {"type": "date", "format": "yyyy-MM-dd||strict_date_optional_time"},
                        "cancer_types": {"type": "keyword"},
                        "license_note": {"type": "text", "index": False},  # 仅展示（D2-04）
                        "file_path": {"type": "keyword"},
                        "doc_hash": {"type": "keyword"},
                        # ---- REC 专属层（推荐条目，检索主单元）----
                        "rec_id": {"type": "keyword"},        # 亦作 ES _id
                        "cancer_type": {"type": "keyword"},
                        "breadcrumb": {"type": "keyword"},    # 如 第三部分/3.2 早期治疗
                        "scenario": {"type": "keyword"},      # 15 类场景枚举
                        "stage": {"type": "keyword"},
                        "stage_detail": {"type": "keyword"},
                        "biomarker": {"type": "keyword"},
                        "population": {"type": "text", "analyzer": "chinese_analyzer"},
                        "verbatim": {"type": "boolean"},
                        "evidence_level": {"type": "keyword"},
                        "evidence_level_original": {"type": "keyword"},
                        "rec_strength": {"type": "keyword"},
                        "refs": {"type": "keyword"},
                        "page": {"type": "integer"},
                        # ---- DRUG 专属层（药品说明书）----
                        "drug_id": {"type": "keyword"},       # 亦作 ES _id
                        "generic_name": {"type": "keyword"},
                        "brand_names": {"type": "keyword"},
                        "atc_code": {"type": "keyword"},
                        "approval_no": {"type": "keyword"},
                        "indications": {
                            "type": "text",
                            "analyzer": "chinese_analyzer",
                            "fields": {
                                "keyword": {"type": "keyword", "ignore_above": 256}
                            }
                        },
                        "dosage": {"type": "object"},          # {standard, adjustment}，仅展示
                        "contraindications": {"type": "text", "analyzer": "chinese_analyzer"},
                        "adverse_reactions": {"type": "object", "enabled": False},  # 原始 JSON 整存整取
                        "adverse_reaction_terms": {"type": "keyword"},  # 抽平：不良反应术语
                        "interactions": {"type": "text", "analyzer": "chinese_analyzer"},
                        # ---- TERM 专属层（术语字典）----
                        "term_id": {"type": "keyword"},        # 亦作 ES _id
                        "canonical": {"type": "keyword"},
                        "category": {"type": "keyword"},       # disease/drug/examination/symptom/gene/staging
                        "synonyms": {"type": "keyword"},
                        "icd10": {"type": "keyword"},
                        "icd_o3": {"type": "keyword"},
                        "atc": {"type": "keyword"},
                        "pinyin": {"type": "keyword"},
                        "en_name": {"type": "keyword"},
                        "mapping_status": {"type": "keyword"}  # confirmed / pending
                    }
                }
            }
            self.client.indices.create(index=settings.es_index_name, body=index_settings)

    def _ensure_disease_index(self) -> bool:
        """确保疾病档案索引存在（C2 §4.2：检索抽平层 + 存储层 enabled:false 分离）

        一条 ES 文档 = 一个疾病 profile；详情大 JSON（sections / patient_version /
        links）不索引、整存整取；症状 / 亚型 / 分期 / 治疗手段抽平为 keyword 数组，
        支撑疾病名检索、症状反查、分类浏览三个入口。
        失败返回 False（查询方降级为空结果，不影响启动）。
        """
        try:
            if self.client.indices.exists(index=settings.es_disease_index_name):
                return True
            self.client.indices.create(
                index=settings.es_disease_index_name,
                body={
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        # 与主索引同套分析器（C2 §3.2），中文分词检索依赖
                        "analysis": {
                            "analyzer": {
                                "text_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "standard",
                                    "filter": ["lowercase", "stop"],
                                },
                                "chinese_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "ik_max_word",
                                    "filter": ["lowercase"],
                                },
                            }
                        },
                    },
                    "mappings": {
                        "properties": {
                            # ---- 检索抽平层 ----
                            "disease_id": {"type": "keyword"},  # 亦作 ES _id
                            "name_canonical": {
                                "type": "text",
                                "analyzer": "chinese_analyzer",
                                "fields": {
                                    "keyword": {"type": "keyword", "ignore_above": 256}
                                }
                            },
                            "synonyms": {"type": "text", "analyzer": "chinese_analyzer"},
                            "pinyin": {"type": "keyword"},
                            "name_en": {"type": "text", "analyzer": "text_analyzer"},
                            "icd10": {"type": "keyword"},
                            "icd_o3": {"type": "keyword"},
                            "category": {"type": "keyword"},  # 四类枚举（disease_profile.category）
                            "body_system": {"type": "keyword"},
                            "departments": {"type": "keyword"},
                            "cancer_type": {"type": "keyword"},
                            "symptoms": {"type": "keyword"},  # 抽平：early+late+signs 全集
                            "symptom_early": {"type": "keyword"},
                            "symptom_late": {"type": "keyword"},
                            "signs": {"type": "keyword"},
                            "pathology_subtypes": {"type": "keyword"},
                            "stages": {"type": "keyword"},
                            "treatment_methods": {"type": "keyword"},
                            "overview_text": {"type": "text", "analyzer": "chinese_analyzer"},
                            "embedding": {
                                "type": "dense_vector",
                                "dims": 1024,
                                "index": True,
                                "similarity": "cosine",
                            },
                            # ---- 存储层（不索引，整存整取）----
                            "sections": {"type": "object", "enabled": False},      # 14 section 专业版
                            "patient_version": {"type": "object", "enabled": False},  # 患者版（同构）
                            "links": {"type": "object", "enabled": False},          # 图谱关联（查询走 KG 索引）
                            # ---- 管理层 ----
                            "section_gaps": {"type": "keyword"},
                            "sources": {"type": "keyword"},
                            "profile_version": {"type": "keyword"},
                            "last_updated": {"type": "date"},
                        }
                    },
                },
            )
            return True
        except Exception as e:
            logger.warning(f"[Disease] 疾病档案索引创建/检查失败: {e}")
            return False
    
    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        import torch
        import os
        with torch.no_grad():
            # 禁用 tqdm 进度条，避免与 uvicorn 日志系统冲突导致进程退出
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            embeddings = self._get_model().encode(
                texts,
                batch_size=settings.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return embeddings.tolist()
    
    def _normalize_topic_fields(self, content: str, metadata: Dict) -> Dict:
        """生成主题字段（医疗）。

        优先复用 metadata 中已有的 topics_details（由上游/分类器产出的嵌套结构），
        否则用分类器自动标注。topics_details 为 C2 §3.3 的 nested 结构
        （id/label_zh/score/matched_keywords），此处不再做 id→label 的再映射。
        """
        existing_details = metadata.get("topics_details")
        if existing_details:
            return {
                "topics_details": existing_details,
                "taxonomy_version": metadata.get("taxonomy_version", self.classifier.taxonomy_version),
            }

        auto = self.classifier.classify_document(content)
        return {
            "topics_details": auto["topics_details"],
            "taxonomy_version": auto["taxonomy_version"],
        }

    def add_documents(self, documents: List[str], metadatas: List[Dict], ids: List[str]):
        embeddings = self._embed_texts(documents)
        operations = []
        failed_docs = []

        for doc_id, content, metadata, embedding in zip(ids, documents, metadatas, embeddings):
            topic_fields = self._normalize_topic_fields(content, metadata)
            operations.append({"index": {"_index": settings.es_index_name, "_id": doc_id}})
            doc = {
                "content": content,
                "embedding": embedding,
                "title": metadata.get("title", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                # 主题字段：仅 topics_details（nested）+ taxonomy_version 入 mapping（C2 §3.3）
                "topics_details": topic_fields["topics_details"],
                "taxonomy_version": topic_fields["taxonomy_version"],
            }
            # 结构化字段按 §5.7.2 白名单透传（C2 §3.3：metadata 塞杂物模式废止，
            # 法规遗留字段 law_id/jurisdiction/article_number/passing_date 等不再落库）
            for field in _MEDICAL_DOC_FIELDS:
                if metadata.get(field) is not None:
                    doc[field] = metadata[field]
            operations.append(doc)

        response = self.client.bulk(body=operations, refresh=True)
        
        # 检查每个文档的索引状态
        if response.get("errors"):
            error_items = []
            for item in response.get("items", []):
                if "error" in item.get("index", {}):
                    error_info = item["index"]
                    error_items.append({
                        "doc_id": error_info.get("_id"),
                        "error_type": error_info.get("error", {}).get("type", ""),
                        "error_reason": error_info.get("error", {}).get("reason", "")
                    })
                    failed_docs.append(error_info.get("_id"))
            
            if error_items:
                # 重试失败的文档
                retry_operations = []
                for i, doc_id in enumerate(ids):
                    if doc_id in failed_docs:
                        # 找到对应的文档信息
                        idx = ids.index(doc_id)
                        retry_operations.append({"index": {"_index": settings.es_index_name, "_id": doc_id}})
                        retry_operations.append(operations[idx * 2 + 1])  # 文档内容在偶数索引+1位置
                
                if retry_operations:
                    retry_response = self.client.bulk(body=retry_operations, refresh=True)
                    if retry_response.get("errors"):
                        for item in retry_response.get("items", []):
                            if "error" in item.get("index", {}):
                                error_info = item["index"]
                                error_items.append({
                                    "doc_id": error_info.get("_id"),
                                    "error_type": error_info.get("error", {}).get("type", ""),
                                    "error_reason": error_info.get("error", {}).get("reason", "")
                                })
                
                raise ValueError(f"部分文档添加失败: {error_items}")
    
    def query(self, query_texts: List[str], n_results: int = 5, where: Optional[Dict] = None) -> Dict:
        results = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        
        for text in query_texts:
            query_embedding = self._embed_texts([text])[0]
            
            knn_base = {
                "field": "embedding",
                "query_vector": query_embedding,
                "k": n_results,
                "num_candidates": n_results * 10
            }
            
            if where:
                # 构建过滤条件
                filter_clauses = []
                for k, v in where.items():
                    # 支持列表值：多选主题的 OR 逻辑
                    if isinstance(v, list) and len(v) > 1:
                        filter_clauses.append({
                            "bool": {
                                "should": [(_term_clause(k, item)) for item in v],
                                "minimum_should_match": 1
                            }
                        })
                    else:
                        # 单值或单元素列表
                        actual_value = v[0] if isinstance(v, list) else v
                        filter_clauses.append(_term_clause(k, actual_value))

                # 将 filter 嵌入 KNN 内部，确保 AND 关系（同时满足向量相似 + 过滤条件）
                search_body = {
                    "knn": {
                        **knn_base,
                        "filter": [{"bool": {"filter": filter_clauses}}]
                    }
                }
            else:
                search_body = {"knn": knn_base}
            
            # 不指定 _source，获取所有字段
            response = self.client.search(index=settings.es_index_name, body=search_body)
            
            hits = response.get("hits", {}).get("hits", [])
            query_ids, query_docs, query_metas, query_distances = [], [], [], []
            
            for hit in hits:
                source = hit.get("_source", {})
                query_ids.append(hit.get("_id"))
                query_docs.append(source.get("content", ""))
                # 合并顶层字段到 metadata 中
                metadata = _medical_metadata(source)
                query_metas.append(metadata)
                score = hit.get("_score", 0)
                query_distances.append(1 - score if score > 0 else 1.0)
            
            results["ids"].append(query_ids)
            results["documents"].append(query_docs)
            results["metadatas"].append(query_metas)
            results["distances"].append(query_distances)
        
        return results

    def hybrid_search(self, query_text: str, n_results: int = 5,
                      where: Optional[Dict] = None,
                      knn_weight: float = 0.5,
                      bm25_weight: float = 0.5,
                      rrf_k: int = 60) -> Dict:
        """
        混合检索：向量检索 + BM25 全文检索，使用 ES 内置 RRF 融合。

        Args:
            query_text: 查询文本
            n_results: 返回结果数量
            where: 过滤条件（支持单值或多选）
            knn_weight: 向量检索权重（RRF 模式未使用，保留兼容）
            bm25_weight: 全文检索权重（RRF 模式未使用，保留兼容）
            rrf_k: RRF 常数，默认 60

        Returns:
            与 query() 相同格式的字典
        """
        if not query_text.strip():
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]],
                    "_scores": [[]], "_similarities": [[]]}

        query_embedding = self._embed_texts([query_text])[0]
        return self._hybrid_search_with_vector(query_text, query_embedding, n_results, where, rrf_k)

    def hybrid_search_batch(self, query_texts: List[str], n_results: int = 5,
                           where: Optional[Dict] = None, rrf_k: int = 60) -> List[Dict]:
        """
        批量混合检索：一次批量编码所有查询词，并发执行 ES 搜索。

        Args:
            query_texts: 查询文本列表
            n_results: 每个查询返回结果数量
            where: 过滤条件（共享）
            rrf_k: RRF 常数

        Returns:
            List[Dict]，每个元素与 hybrid_search() 返回格式相同
        """
        if not query_texts:
            return []
        # 一次性批量编码所有查询词（关键优化：避免 N 次独立 CPU 推理）
        embeddings = self._embed_texts(query_texts)
        # 并发执行 ES 搜索（IO 密集型）
        with ThreadPoolExecutor(max_workers=min(len(query_texts), 8)) as executor:
            futures = [
                executor.submit(self._hybrid_search_with_vector, query_text, embedding, n_results, where, rrf_k)
                for query_text, embedding in zip(query_texts, embeddings)
            ]
            results = [f.result() for f in futures]
        return results

    def _hybrid_search_with_vector(self, query_text: str, query_embedding: List[float],
                                   n_results: int = 5, where: Optional[Dict] = None,
                                   rrf_k: int = 60) -> Dict:
        """使用预计算的向量执行混合搜索（内部方法，跳过 embedding 计算）

        说明：当前 ES 许可证可能不支持内置 RRF，因此分别执行 KNN 和 BM25 搜索，
        在应用层手动计算 RRF 分数后合并排序，避免依赖 ES 付费特性。
        """
        # KNN 与 BM25 两次 ES 查询互不依赖，并行执行以只承担较大者而非两者之和
        with ThreadPoolExecutor(max_workers=2) as executor:
            knn_future = executor.submit(self._knn_search, query_embedding, n_results * 3, where)
            bm25_future = executor.submit(self._bm25_search, query_text, n_results * 3, where)
            knn_results = knn_future.result()
            bm25_results = bm25_future.result()

        # 使用 RRF 公式合并两个结果列表
        merged = self._merge_rrf_results(knn_results, bm25_results, rrf_k=rrf_k)

        # 截取前 n_results 条
        merged = merged[:n_results]

        query_ids, query_docs, query_metas, query_distances, query_scores = [], [], [], [], []
        query_similarities = []  # 真实余弦相似度（仅 KNN 命中；BM25-only 为 None），供展示用
        for item in merged:
            source = item["source"]
            query_ids.append(item["_id"])
            query_docs.append(source.get("content", ""))

            query_metas.append(_medical_metadata(source))

            rrf_score = item["rrf_score"]
            query_scores.append(rrf_score)
            # distances 仅保留兼容性：RRF 分动态范围极小（~0.016~0.05），由它反推的
            # 相似度没有区分度（旧实现因此让前端所有条款都显示 50%）。展示分改用
            # 下面的 _similarities（真实余弦），不再依赖这里。
            query_distances.append(1.0 / (1.0 + abs(rrf_score)) if rrf_score != 0 else 1.0)
            query_similarities.append(item.get("vector_similarity"))

        return {
            "ids": [query_ids],
            "documents": [query_docs],
            "metadatas": [query_metas],
            "distances": [query_distances],
            "_scores": [query_scores],
            "_similarities": [query_similarities],
        }

    def _knn_search(self, query_embedding: List[float], n_results: int,
                    where: Optional[Dict] = None) -> List[Dict]:
        """纯向量 KNN 搜索，返回原始 hits 列表。"""
        knn_base = {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": n_results,
            "num_candidates": min(n_results * 10, 10000)
        }

        filter_clauses = []
        if where:
            for k, v in where.items():
                if isinstance(v, list) and len(v) > 1:
                    filter_clauses.append({
                        "bool": {
                            "should": [(_term_clause(k, item)) for item in v],
                            "minimum_should_match": 1
                        }
                    })
                else:
                    actual_value = v[0] if isinstance(v, list) else v
                    filter_clauses.append(_term_clause(k, actual_value))

        # 时效过滤：剔除已废止/已删除法规（组件C）
        excluded = self._excluded_law_filter()
        if excluded:
            filter_clauses.append({"bool": {"must_not": [excluded]}})

        # 必须显式设置顶层 size：ES 默认 size=10，仅设 knn.k 并不会让返回条数超过 10。
        # 曾因此把向量召回硬截断在 10 条（k 请求 450 也只回 10 条），使 RRF 中向量通道
        # 几乎失效、混合检索退化为 BM25 主导，且下游只有前 10 条能拿到余弦分。
        if filter_clauses:
            search_body = {
                "size": n_results,
                "knn": {
                    **knn_base,
                    "filter": [{"bool": {"filter": filter_clauses}}]
                }
            }
        else:
            search_body = {"size": n_results, "knn": knn_base}

        response = self.client.search(index=settings.es_index_name, body=search_body)
        return response.get("hits", {}).get("hits", [])

    def _bm25_search(self, query_text: str, n_results: int,
                     where: Optional[Dict] = None) -> List[Dict]:
        """BM25 全文搜索，返回原始 hits 列表。

        查询串会同时带上繁、简两种写法：语料里澳门/香港等法域正文是繁体，而 IK 词典
        不含繁体字（繁体被切成一字一 token），若只按用户输入的写法检索，简体查询在
        繁体语料上会一条都召不回。具体写法由 zh_query_variants 生成。
        """
        variants = zh_query_variants(query_text)
        analysis_query = " ".join(variants) if len(variants) > 1 else query_text
        bm25_query = {
            "multi_match": {
                "query": analysis_query,
                "fields": ["content^3", "title^5", "article_number^2"],
                "type": "best_fields",
                "analyzer": "chinese_analyzer"
            }
        }

        filter_clauses = []
        if where:
            for k, v in where.items():
                if isinstance(v, list) and len(v) > 1:
                    filter_clauses.append({
                        "bool": {
                            "should": [(_term_clause(k, item)) for item in v],
                            "minimum_should_match": 1
                        }
                    })
                else:
                    actual_value = v[0] if isinstance(v, list) else v
                    filter_clauses.append(_term_clause(k, actual_value))

        # 时效过滤：剔除已废止/已删除法规（组件C）
        excluded = self._excluded_law_filter()
        if excluded:
            filter_clauses.append({"bool": {"must_not": [excluded]}})

        if filter_clauses:
            query_body = {
                "bool": {
                    "must": bm25_query,
                    "filter": filter_clauses
                }
            }
        else:
            query_body = bm25_query

        search_body = {
            "query": query_body,
            "size": n_results,
            "_source": True
        }

        response = self.client.search(index=settings.es_index_name, body=search_body)
        return response.get("hits", {}).get("hits", [])

    def _merge_rrf_results(self, knn_hits: List[Dict], bm25_hits: List[Dict],
                           rrf_k: int = 60) -> List[Dict]:
        """手动 RRF 融合：对 KNN 和 BM25 结果按 RRF 分数合并去重排序。

        除 RRF 分（仅用于排序）外，还附带每条命中来自 KNN 的**真实余弦相似度**：
        ES dense_vector(cosine) 的 _score 实为 (1+cos)/2（正交=0.5），故还原为
        cos = 2*_score - 1。该值供上层计算展示用「匹配度」，与排序无关。
        仅被 BM25 召回、未进 KNN 的条款没有余弦分，记为 None。
        """
        scores: Dict[str, float] = {}
        sources: Dict[str, Dict] = {}
        cosines: Dict[str, float] = {}

        for rank, hit in enumerate(knn_hits, start=1):
            doc_id = hit.get("_id")
            if not doc_id:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
            sources.setdefault(doc_id, hit.get("_source", {}))
            # KNN 已按相似度降序，首次出现即其最高分
            es_score = hit.get("_score")
            if es_score is not None:
                cosines.setdefault(doc_id, 2.0 * float(es_score) - 1.0)

        for rank, hit in enumerate(bm25_hits, start=1):
            doc_id = hit.get("_id")
            if not doc_id:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
            sources.setdefault(doc_id, hit.get("_source", {}))

        merged = []
        for doc_id, rrf_score in scores.items():
            merged.append({
                "_id": doc_id,
                "rrf_score": rrf_score,
                "vector_similarity": cosines.get(doc_id),
                "source": sources.get(doc_id, {})
            })

        merged.sort(key=lambda x: x["rrf_score"], reverse=True)
        return merged

    # ================================================================
    #  法规时效过滤（组件C）
    #  ------------------------------------------------------------
    #  doc_catalog.json 的 status 标记法规时效。检索层默认剔除已废止/已删除的
    #  法规，否则失效条款仍会被检索命中并被 LLM 当作现行法引用 —— 这在法律
    #  场景下是致命错误。
    #  实现上不改 ES 文档（避免重新入库）：状态只影响检索过滤条件，
    #  按 law_id 排除即可；catalog 文件变更后依据 mtime 自动失效缓存。
    # ================================================================

    # 不可检索的状态：repealed 已废止 / deleted 已删除 / missing 数据缺失
    # 注意 amended（已修订）表示法规仍然现行有效，只是内容被修改过，不排除
    _NON_RETRIEVABLE_STATUS = ("repealed", "deleted", "missing")

    def _non_active_law_ids(self) -> List[str]:
        """
        读取当前不可检索的 law_id 列表。

        按文件 mtime 缓存解析结果，避免每次检索都解析整个法规目录 JSON。
        目录不可读时返回空列表（降级为不过滤），保证检索本身不被阻断。
        """
        import os
        catalog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "doc_catalog.json",
        )
        try:
            mtime = os.path.getmtime(catalog_path)
        except OSError:
            return []

        if self._non_active_cache and self._non_active_cache[0] == mtime:
            return self._non_active_cache[1]

        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"[时效过滤] 读取法规目录失败，本次不做时效过滤: {e}")
            return []

        laws = data.get("docs", []) if isinstance(data, dict) else data
        if isinstance(laws, dict):
            laws = list(laws.values())

        ids = [
            x.get("doc_id")
            for x in laws
            if isinstance(x, dict) and x.get("doc_id")
            and x.get("status") in self._NON_RETRIEVABLE_STATUS
        ]
        if ids:
            logger.info(f"[时效过滤] 本次排除 {len(ids)} 部已废止/已删除法规")
        self._non_active_cache = (mtime, ids)
        return ids

    def _excluded_law_filter(self) -> Optional[Dict]:
        """构造排除失效法规的 ES 过滤子句，无失效法规时返回 None"""
        ids = self._non_active_law_ids()
        return {"terms": {"law_id": ids}} if ids else None

    def _law_title_index(self) -> Dict[str, str]:
        """{法规标题的简体归一形式: law_id}，进程内缓存（法规总数仅数百，聚合一次即可）。

        归一方向固定为「繁→简」：繁体转简体基本一一对应，可靠；反向（简→繁）存在多候选
        （如「系」可能是「系/係」），无法由简体标题反推出真实存储的繁体标题。
        """
        if self._law_title_index_cache is None:
            index: Dict[str, str] = {}
            try:
                for law in self.get_all_laws():
                    law_id = law.get("law_id")
                    law_title = law.get("title") or ""
                    if law_id and law_title:
                        index.setdefault(zh_convert(law_title, "t2s"), law_id)
            except Exception as e:
                # 构建失败不写入缓存，避免一次偶发失败把该能力永久关掉
                logger.warning(f"[法规名定位] 标题索引构建失败: {e}")
                return index
            self._law_title_index_cache = index
        return self._law_title_index_cache

    def _resolve_law_id(self, title: str) -> Optional[str]:
        """把法规名解析为 law_id：先简体归一后精确匹配，再退化为双向包含（取最长者，保证确定性）"""
        normalized = zh_convert(title, "t2s")
        if not normalized:
            return None
        index = self._law_title_index()
        if normalized in index:
            return index[normalized]
        candidates = [
            (len(key), law_id) for key, law_id in index.items()
            if key and (key in normalized or normalized in key)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][1]

    def find_article(self, title: str, article_number: str) -> Optional[Dict]:
        """按「法规名 + 条款号」精确定位一条条款，繁简写法均可。

        先把法规名经简体归一解析成 law_id，再按 (law_id, article_number) 精确查询。

        此前是拿标题字符串本身（含各家写法）去查 title.keyword，失败后退化为 match title 兜底：
        简→繁 为一对多（「关系」拼不出「關係」），拼出的变体无法命中真实标题，于是必然走兜底；
        而 IK 分词下的 match title 是 OR 语义，近乎「匹配任意含『法』的文档」，返回结果随
        set 迭代顺序漂移（实测同一简体查询时而命中「勞動關係法」，时而命中「經濟房屋法」）。
        """
        try:
            law_id = self._resolve_law_id(title)
            if not law_id:
                return None
            query_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"law_id": law_id}},
                            {"term": {"article_number": article_number}}
                        ]
                    }
                },
                "size": 1,
                "_source": True
            }
            response = self.client.search(index=settings.es_index_name, body=query_body)
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return None
            hit = hits[0]
            source = hit.get("_source", {})
            metadata = source.get("metadata", {}).copy()
            metadata["law_id"] = source.get("law_id", "")
            metadata["title"] = source.get("title", "")
            metadata["jurisdiction"] = source.get("jurisdiction", "")
            metadata["article_number"] = source.get("article_number", "")
            metadata["chunk_index"] = source.get("chunk_index", 0)
            metadata["topics_details"] = source.get("topics_details", [])
            return {
                "content": source.get("content", ""),
                "title": metadata["title"],
                "article_number": metadata["article_number"],
                "jurisdiction": _jurisdiction_to_zh(metadata.get("jurisdiction", "")),
                "score": 1.0,
                "law_id": metadata["law_id"],
                "source_file": source.get("source_file", ""),
                "chunk_index": metadata["chunk_index"],
                "topics_details": metadata["topics_details"],
            }
        except Exception as e:
            return None

    def get(self, doc_id: str) -> Optional[Dict]:
        try:
            response = self.client.get(index=settings.es_index_name, id=doc_id)
            return response.get("_source", {})
        except NotFoundError:
            return None

    def get_article_full_text(self, law_id: str, article_number: str) -> Optional[str]:
        """
        通过 law_id + article_number 聚合同一 article 下的所有 chunks，按顺序拼接为完整文本。
        用于 sub_chunk 定位后回取完整 article 上下文。
        """
        if not law_id or not article_number:
            return None
        try:
            query_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"law_id": law_id}},
                            {"term": {"article_number": article_number}}
                        ]
                    }
                },
                "sort": [{"chunk_index": "asc"}],
                "size": 1000,
                "_source": ["content", "chunk_index"]
            }
            response = self.client.search(index=settings.es_index_name, body=query_body)
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return None
            chunks = [(hit["_source"].get("chunk_index", 0), hit["_source"].get("content", "")) for hit in hits]
            chunks.sort(key=lambda x: x[0])
            return "\n\n".join(content for _, content in chunks if content)
        except Exception:
            return None

    def get_articles_full_text_batch(self, pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], str]:
        """
        批量回取多个 article 的完整文本（单次 msearch）。

        与逐条调用 get_article_full_text 结果等价，但把 N 次网络往返压缩为 1 次。
        用于检索结果按 article 去重后的批量补全。

        Args:
            pairs: [(law_id, article_number), ...]

        Returns:
            {(law_id, article_number): 完整文本}；未命中的键不出现在结果中
        """
        keys = [(lid, an) for lid, an in pairs if lid and an]
        if not keys:
            return {}

        body: List[Dict] = []
        for law_id, article_number in keys:
            body.append({"index": settings.es_index_name})
            body.append({
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"law_id": law_id}},
                            {"term": {"article_number": article_number}}
                        ]
                    }
                },
                "sort": [{"chunk_index": "asc"}],
                "size": 1000,
                "_source": ["content", "chunk_index"]
            })

        try:
            response = self.client.msearch(body=body)
        except Exception:
            return {}

        result: Dict[Tuple[str, str], str] = {}
        for key, item in zip(keys, response.get("responses", [])):
            hits = item.get("hits", {}).get("hits", [])
            if not hits:
                continue
            chunks = [(h["_source"].get("chunk_index", 0), h["_source"].get("content", "")) for h in hits]
            chunks.sort(key=lambda x: x[0])
            text = "\n\n".join(content for _, content in chunks if content)
            if text:
                result[key] = text
        return result

    def get_articles_docs_batch(self, pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], Dict]:
        """
        批量回取多个 article 的完整文档（正文 + 元信息，单次 msearch）。

        与 get_articles_full_text_batch 的区别：除拼接后的完整正文外，还返回
        title/jurisdiction/topics 等字段，供「引用链扩展」直接构造检索结果项。
        未命中的键不出现在返回值中。
        """
        keys = [(lid, an) for lid, an in pairs if lid and an]
        if not keys:
            return {}

        body: List[Dict] = []
        for law_id, article_number in keys:
            body.append({"index": settings.es_index_name})
            body.append({
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"law_id": law_id}},
                            {"term": {"article_number": article_number}}
                        ]
                    }
                },
                "sort": [{"chunk_index": "asc"}],
                "size": 1000,
                "_source": ["content", "chunk_index", "title", "jurisdiction",
                            "law_id", "article_number", "source_file",
                            "topics_details"]
            })

        try:
            response = self.client.msearch(body=body)
        except Exception:
            return {}

        result: Dict[Tuple[str, str], Dict] = {}
        for key, item in zip(keys, response.get("responses", [])):
            hits = item.get("hits", {}).get("hits", [])
            if not hits:
                continue
            source = hits[0].get("_source", {})
            chunks = [(h["_source"].get("chunk_index", 0), h["_source"].get("content", "")) for h in hits]
            chunks.sort(key=lambda x: x[0])
            content = "\n\n".join(text for _, text in chunks if text)
            if not content:
                continue
            result[key] = {
                "content": content,
                "title": source.get("title", ""),
                "article_number": source.get("article_number", ""),
                "jurisdiction": source.get("jurisdiction", ""),
                "law_id": source.get("law_id", ""),
                "source_file": source.get("source_file", ""),
                "chunk_index": source.get("chunk_index", 0),
                "topics_details": source.get("topics_details", []),
            }
        return result

    def get_referenced_articles(self, seeds: List[Tuple[str, str, str]],
                                max_refs: int = 5) -> List[Dict]:
        """
        引用链单跳扩展（组件D）：回取种子条款引用到的其他条款。

        引用来源有两种（同一批回取，不额外发起 LLM 调用）：
          - 同法规内引用（parse_intra_law_refs，正文正则，精确且优先级更高）；
          - 跨法规引用（parse_cross_law_refs，仅澳门 N/YYYY 号法律/行政法规与香港 N 章，
            由 settings.reference_expand_cross_law_enabled 控制）。

        Args:
            seeds: [(law_id, article_number, content), ...]，通常是排名靠前的检索结果
            max_refs: 本次最多补入的引用条款数，用于控制上下文膨胀

        Returns:
            被引用条款的文档列表（get_articles_docs_batch 的形状），每项额外带：
              - retrieval_hop: 固定为 2，表示这是引用链扩展来的候选
              - referenced_by: 引用方条款号
              - referenced_law_id: 引用方法规 ID
              - cross_law: 仅跨法规引用项携带，值为 True
            已在 seeds 中出现过的条款不会重复返回；回取不到的目标（条款号不存在、
            或属于跨法规引用的误判）会被静默跳过。
        """
        if not seeds or max_refs <= 0:
            return []

        seed_keys = {(law_id, str(article_number)) for law_id, article_number, _ in seeds if law_id}

        # 先按「同法规内引用 → 跨法规引用」的优先级收集候选（每个种子内部保持该顺序），
        # 再统一去重、截断：这样开启跨法规扩展时，同法规引用的优先级不受影响。
        candidates: List[Tuple[Tuple[str, str], Tuple[str, str], bool]] = []
        for law_id, article_number, content in seeds:
            if not law_id:
                continue
            for ref in parse_intra_law_refs(content, article_number):
                candidates.append(((law_id, ref), (law_id, str(article_number)), False))
            if settings.reference_expand_cross_law_enabled:
                for target_law, target_art in parse_cross_law_refs(content, article_number, law_id):
                    candidates.append(((target_law, target_art), (law_id, str(article_number)), True))

        targets: List[Tuple[str, str]] = []
        origin: Dict[Tuple[str, str], Tuple[str, str]] = {}
        cross_flag: Dict[Tuple[str, str], bool] = {}
        seen = set()
        for key, src, is_cross in candidates:
            if key in seed_keys or key in seen:
                continue
            seen.add(key)
            targets.append(key)
            origin[key] = src
            cross_flag[key] = is_cross
            if len(targets) >= max_refs:
                break

        docs = self.get_articles_docs_batch(targets)
        results = []
        for key in targets:
            doc = docs.get(key)
            if not doc:
                continue
            source_law_id, source_article = origin[key]
            doc["retrieval_hop"] = 2
            doc["referenced_by"] = source_article
            doc["referenced_law_id"] = source_law_id
            if cross_flag.get(key):
                doc["cross_law"] = True
            results.append(doc)
        return results

    def update(self, doc_id: str, content: Optional[str] = None, metadata: Optional[Dict] = None):
        update_body = {}
        if content:
            update_body["doc"] = {"content": content}
            if content:
                embedding = self._embed_texts([content])[0]
                update_body["doc"]["embedding"] = embedding
        if metadata:
            if "doc" not in update_body:
                update_body["doc"] = {}
            update_body["doc"]["metadata"] = metadata
        
        if update_body:
            self.client.update(index=settings.es_index_name, id=doc_id, body=update_body)
    
    def delete(self, doc_id: str):
        self.client.delete(index=settings.es_index_name, id=doc_id)
    
    def count(self) -> int:
        response = self.client.count(index=settings.es_index_name)
        return response.get("count", 0)
    
    def clear(self):
        index_name = settings.es_index_name
        # 判断该名称是否为 alias，并找出对应的真实索引
        is_alias = False
        concrete_indices = []
        try:
            alias_info = self.client.indices.get_alias(name=index_name)
            is_alias = True
            concrete_indices = list(alias_info.keys())
        except NotFoundError:
            is_alias = False

        if is_alias and concrete_indices:
            # 删除 alias 指向的真实索引
            self.client.indices.delete(index=",".join(concrete_indices))
            # 删除 alias 本身
            self.client.indices.delete_alias(index=concrete_indices, name=index_name)
        elif self.client.indices.exists(index=index_name):
            self.client.indices.delete(index=index_name)

        # 重新创建真实索引（名称为 es_index_name）
        self._create_index_if_not_exists()
    
    def get_all_laws(self, jurisdiction: Optional[str] = None, topics: Optional[str] = None) -> List[Dict]:
        """获取所有法规列表（按law_id聚合）"""
        query = {
            "size": 0,
            "aggs": {
                "laws": {
                    "terms": {
                        "field": "law_id",
                        "size": 10000
                    },
                    "aggs": {
                        "title": {"terms": {"field": "title.keyword", "size": 1}},
                        "jurisdiction": {"terms": {"field": "jurisdiction", "size": 1}},
                        "chunk_count": {"value_count": {"field": "chunk_index"}},
                        # 新增：统计实际条款数（按article_number去重）
                        "article_count": {
                            "cardinality": {
                                "field": "article_number"
                            }
                        }
                    }
                }
            }
        }
        
        # 构建查询条件（AND 逻辑）
        must_clauses = []
        if jurisdiction:
            must_clauses.append({"term": {"jurisdiction": jurisdiction}})
        if topics:
            for topic_label in [t.strip() for t in topics.split(",") if t.strip()]:
                must_clauses.append(_term_clause("topics_details.label_zh", topic_label))
        
        if must_clauses:
            query["query"] = {"bool": {"must": must_clauses}}
        
        response = self.client.search(index=settings.es_index_name, body=query)
        
        laws = []
        for bucket in response.get("aggregations", {}).get("laws", {}).get("buckets", []):
            law_id = bucket.get("key")
            title_buckets = bucket.get("title", {}).get("buckets", [])
            title = title_buckets[0].get("key") if title_buckets else ""
            jur_buckets = bucket.get("jurisdiction", {}).get("buckets", [])
            jur = jur_buckets[0].get("key") if jur_buckets else ""
            chunk_count = bucket.get("chunk_count", {}).get("value", 0)
            # 使用去重后的条款数
            article_count = bucket.get("article_count", {}).get("value", 0)
            
            laws.append({
                "law_id": law_id,
                "title": title,
                "jurisdiction": _jurisdiction_to_zh(jur),
                "chunk_count": chunk_count,
                "article_count": article_count if article_count > 0 else chunk_count
            })
        
        return laws
    
    def get_law_by_id(self, law_id: str) -> Optional[Dict]:
        """根据law_id获取法规的所有条款"""
        query = {
            "query": {"term": {"law_id": law_id}},
            "size": 1000,
            "sort": [{"chunk_index": {"order": "asc"}}]
        }
        
        response = self.client.search(index=settings.es_index_name, body=query)
        hits = response.get("hits", {}).get("hits", [])
        
        if not hits:
            return None
        
        chunks = []
        for hit in hits:
            source = hit.get("_source", {})
            chunks.append({
                "content": source.get("content", ""),
                "article_number": source.get("article_number", ""),
                "article_title": source.get("article_title", ""),
                "chunk_index": source.get("chunk_index", 0)
            })
        
        first_source = hits[0].get("_source", {})
        return {
            "law_id": law_id,
            "title": first_source.get("title", ""),
            "jurisdiction": _jurisdiction_to_zh(first_source.get("jurisdiction", "")),
            "passing_date": first_source.get("passing_date", ""),
            "chunks": chunks
        }
    
    def delete_by_law_id(self, law_id: str) -> int:
        """根据law_id批量删除所有相关文档"""
        query = {
            "query": {"term": {"law_id": law_id}}
        }

        response = self.client.delete_by_query(index=settings.es_index_name, body=query, refresh=True)
        return response.get("deleted", 0)

    def exists_item(self, item_id: str) -> bool:
        """按 _id 判定条目是否已入库。

        医疗主索引以各类 item id（doc_id / rec_id / drug_id / term_id）作为 ES _id，
        故「是否存在」等价于 _id 存在性，无需依赖任何类型专属字段。
        """
        if not item_id:
            return False
        try:
            return bool(self.client.exists(index=settings.es_index_name, id=item_id))
        except Exception:
            return False

    def exists_law_id(self, law_id: str) -> bool:
        """检查数据库中是否已存在指定law_id的文档"""
        query = {
            "size": 1,
            "query": {"term": {"law_id": law_id}}
        }

        try:
            response = self.client.search(index=settings.es_index_name, body=query)
            return response.get("hits", {}).get("total", {}).get("value", 0) > 0
        except Exception:
            return False

    def get_law_chunk_count(self, law_id: str) -> int:
        """获取指定law_id的文档块数量"""
        query = {
            "size": 0,
            "query": {"term": {"law_id": law_id}}
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        return response.get("hits", {}).get("total", {}).get("value", 0)
    
    def get_doc_context_recs(self, doc_id: str, exclude_ids: Optional[Iterable[str]] = None,
                             breadcrumb_prefix: str = "", max_n: int = 5) -> List[Dict]:
        """同指南上下文条目（BE-15 上下文扩展）。

        取同一 doc_id 下的推荐条目（data_type=rec），排除已命中条目，作为「相邻条目 /
        同指南条目」补入检索结果尾部。优先返回与种子同节（breadcrumb 前缀相同）的
        兄弟条目，不足时再按 breadcrumb / page 顺序补同指南的其他条目。

        返回项形状与检索结果一致：{item_id, content} + _medical_metadata(source)。
        """
        if not doc_id or max_n <= 0:
            return []

        exclude = [x for x in (exclude_ids or []) if x]
        must_not = [{"ids": {"values": exclude}}] if exclude else []
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"data_type": "rec"}},
                    ],
                    "must_not": must_not,
                }
            },
            # 多取候选：先筛「同节」，不足再补齐，故候选需大于最终条数
            "size": max(max_n * 4, 20),
        }

        try:
            response = self.client.search(index=settings.es_index_name, body=body)
        except Exception:
            return []

        same_section: List[Dict] = []
        others: List[Dict] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            item = {"item_id": hit.get("_id"), "content": source.get("content", "")}
            item.update(_medical_metadata(source))
            breadcrumb = source.get("breadcrumb") or ""
            if breadcrumb_prefix and breadcrumb.startswith(breadcrumb_prefix):
                same_section.append(item)
            else:
                others.append(item)

        order_key = lambda d: (d.get("breadcrumb") or "", d.get("page") or 0)
        same_section.sort(key=order_key)
        others.sort(key=order_key)
        return (same_section + others)[:max_n]

    def query_with_filters(self, n_results: int = 10, where: Optional[Dict] = None) -> Dict:
        """仅按筛选条件检索，不进行语义搜索"""
        results = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        
        search_body = {}

        if where:
            # 构建过滤条件（支持多值 OR 逻辑）
            filter_clauses = []
            for k, v in where.items():
                if isinstance(v, list) and len(v) > 1:
                    # 多选主题的 OR 逻辑
                    filter_clauses.append({
                        "bool": {
                            "should": [(_term_clause(k, item)) for item in v],
                            "minimum_should_match": 1
                        }
                    })
                else:
                    actual_value = v[0] if isinstance(v, list) else v
                    filter_clauses.append(_term_clause(k, actual_value))
            search_body["query"] = {"bool": {"filter": filter_clauses}}
        else:
            search_body["query"] = {"match_all": {}}
        
        search_body["size"] = n_results
        # 不指定 _source，获取所有字段
        # 注：医疗模型下无需按字段排序——filter-only 检索无相关度；原 [law_id, chunk_index]
        # 中的 law_id 在新索引 medical_knowledge 无映射，会触发 no-mapping 报错；chunk_index
        # 对 rec/doc/term 恒为 0，排序无实际效果。省略 sort，交由 ES 隐式 _doc 序返回；
        # 医学语义排序（如按 publish_date / evidence_level）留给 BE-15 统一设计。

        response = self.client.search(index=settings.es_index_name, body=search_body)
        
        hits = response.get("hits", {}).get("hits", [])
        query_ids, query_docs, query_metas, query_distances = [], [], [], []
        
        for hit in hits:
            source = hit.get("_source", {})
            query_ids.append(hit.get("_id"))
            query_docs.append(source.get("content", ""))
            # 合并顶层字段到 metadata 中
            metadata = _medical_metadata(source)
            query_metas.append(metadata)
            query_distances.append(0.0)
        
        results["ids"].append(query_ids)
        results["documents"].append(query_docs)
        results["metadatas"].append(query_metas)
        results["distances"].append(query_distances)
        
        return results
    
    def get_all_jurisdictions(self) -> List[str]:
        """获取所有法域列表（返回简体中文）"""
        query = {
            "size": 0,
            "aggs": {
                "jurisdictions": {
                    "terms": {
                        "field": "jurisdiction",
                        "size": 100
                    }
                }
            }
        }
        
        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = response.get("aggregations", {}).get("jurisdictions", {}).get("buckets", [])
        
        # 转换为中文并去重
        zh_jurisdictions = set()
        result = []
        for bucket in buckets:
            jur = bucket.get("key")
            zh_jur = _jurisdiction_to_zh(jur)
            if zh_jur not in zh_jurisdictions:
                zh_jurisdictions.add(zh_jur)
                result.append(zh_jur)
        
        return result

    def sample_documents(self, jurisdiction: str, size: int = 200,
                         fields: Optional[List[str]] = None) -> List[Dict]:
        """按法域随机采样文档，用于构建法域语义向量。

        Args:
            jurisdiction: 法域名称（简体中文）
            size: 采样数量
            fields: 返回字段，默认 ['title', 'content']

        Returns:
            [{'title': ..., 'content': ...}, ...]
        """
        if fields is None:
            fields = ['title', 'content']

        # 使用 random_score 函数实现随机采样
        query = {
            "size": size,
            "query": {
                "function_score": {
                    "query": {"term": {"jurisdiction": jurisdiction}},
                    "random_score": {"seed": int(time.time()), "field": "_seq_no"},
                    "boost_mode": "replace"
                }
            },
            "_source": fields
        }

        try:
            response = self.client.search(index=settings.es_index_name, body=query)
            hits = response.get("hits", {}).get("hits", [])
            return [hit["_source"] for hit in hits]
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"采样法域 {jurisdiction} 文档失败: {e}")
            return []

    def get_all_topics(self) -> List[Dict]:
        """获取所有主题列表（含统计信息）

        返回格式:
        [
            {
                "id": "cybersecurity",
                "label_zh": "网络安全",
                "count": 15,
                "by_jurisdiction": {"澳门": 10, "新加坡": 5}
            },
            ...
        ]
        """
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "terms": {
                        "field": "topic_labels",
                        "size": 100
                    },
                    "aggs": {
                        "jurisdiction_breakdown": {
                            "terms": {"field": "jurisdiction", "size": 10}
                        }
                    }
                }
            }
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = response.get("aggregations", {}).get("topics", {}).get("buckets", [])

        result = []
        for bucket in buckets:
            raw_label = bucket.get("key", "")
            count = bucket.get("doc_count", 0)

            # 确保返回中文标签：如果是英文ID则转换
            label_zh = _to_label_zh(raw_label) if raw_label and raw_label[0].islower() and '_' in raw_label else raw_label

            # 统计各法域分布
            by_jur = {}
            for jur_bucket in bucket.get("jurisdiction_breakdown", {}).get("buckets", []):
                by_jur[jur_bucket["key"]] = jur_bucket["doc_count"]

            result.append({
                "id": _label_zh_to_topic_id(label_zh),
                "label_zh": label_zh,
                "count": count,
                "by_jurisdiction": by_jur
            })

        # 按 count 降序排列
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    def get_topic_filter_values(self) -> List[str]:
        """获取所有可用的主题标签值（用于下拉筛选的简单列表，返回中文）"""
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "terms": {
                        "field": "topic_labels",
                        "size": 100
                    }
                }
            }
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = response.get("aggregations", {}).get("topics", {}).get("buckets", [])

        result = []
        for bucket in buckets:
            raw_label = bucket.get("key", "")
            if not raw_label:
                continue
            # 确保返回中文标签：如果是英文ID则转换
            label_zh = _to_label_zh(raw_label) if raw_label[0].islower() and '_' in raw_label else raw_label
            result.append(label_zh)
        return result

    def get_topic_frequencies(self) -> Dict[str, int]:
        """
        获取所有主题标签的出现频次（用于 IDF 加权）
        返回: {"数据保护": 120, "网络安全": 85, ...}
        """
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "terms": {
                        "field": "topic_labels",
                        "size": 200
                    }
                }
            }
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = response.get("aggregations", {}).get("topics", {}).get("buckets", [])

        return {bucket.get("key"): bucket.get("doc_count", 0) for bucket in buckets if bucket.get("key")}

    def get_law_chunk_vectors(self, law_id: str) -> List[Dict]:
        """
        获取指定法规所有 chunk 的向量及元数据（仅取必要字段，不返回 content）
        返回格式：[{"embedding": [...], "law_id": ..., "title": ..., "jurisdiction": ..., "topics_details": [...]}, ...]
        """
        query = {
            "query": {"term": {"law_id": law_id}},
            "size": 1000,
            "sort": [{"chunk_index": {"order": "asc"}}],
            "_source": ["embedding", "law_id", "title", "jurisdiction", "chunk_index", "topics_details"]
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            return []

        results = []
        for hit in hits:
            source = hit.get("_source", {})
            results.append({
                "embedding": source.get("embedding", []),
                "law_id": source.get("law_id", ""),
                "title": source.get("title", ""),
                "jurisdiction": source.get("jurisdiction", ""),
                "chunk_index": source.get("chunk_index", 0),
                "topics_details": source.get("topics_details", []),
            })

        return results

    def knn_search_similar(
        self,
        query_vector: List[float],
        top_k: int = 20,
        exclude_law_id: Optional[str] = None,
        jurisdiction_filter: Optional[str] = None,
        min_score: float = 0.3
    ) -> List[Dict]:
        """
        使用给定向量执行 KNN 相似搜索，返回去重前的原始 chunk 结果。
        排除指定 law_id，可选法域过滤和最低分数阈值。

        注意：使用 knn.filter 做预过滤（法域），用 post_filter 做后置排除（自身），
        确保排除逻辑严格生效而非仅降权。
        """
        # 构建 KNN 预过滤器（在向量搜索前缩小候选集）
        knn_filters = []
        if jurisdiction_filter:
            knn_filters.append({"term": {"jurisdiction": jurisdiction_filter}})

        knn_body = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": top_k * 5,
            "num_candidates": max(top_k * 20, 100)
        }
        if knn_filters:
            knn_body["filter"] = knn_filters

        search_body = {"knn": knn_body, "size": top_k * 5}

        # post_filter：在搜索结果上做硬性排除（确保自身不被返回）
        post_filter_clauses = []
        if exclude_law_id:
            post_filter_clauses.append({"term": {"law_id": exclude_law_id}})
        if post_filter_clauses:
            search_body["post_filter"] = {"bool": {"must_not": post_filter_clauses}}

        response = self.client.search(index=settings.es_index_name, body=search_body)
        hits = response.get("hits", {}).get("hits", [])

        results = []
        for hit in hits:
            source = hit.get("_source", {})
            score = hit.get("_score", 0.0)
            # cosine similarity: ES dense_vector with cosine similarity returns cosine value as _score
            similarity = float(score)

            if similarity < min_score:
                continue

            results.append({
                "id": hit.get("_id"),
                "law_id": source.get("law_id", ""),
                "title": source.get("title", ""),
                "jurisdiction": source.get("jurisdiction", ""),
                "article_number": source.get("article_number", ""),
                "content_preview": source.get("content", "")[:150] if source.get("content") else "",
                "similarity": similarity,
            })

        return results

    def get_topic_statistics(self, limit: int = 50) -> List[Dict]:
        """
        获取主题统计信息，包括各法域的分布
        
        用于可视化看板的主题词云、热力图等
        """
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "terms": {
                        "field": "topics",
                        "size": limit
                    },
                    "aggs": {
                        "by_jurisdiction": {
                            "terms": {
                                "field": "jurisdiction",
                                "size": 10
                            }
                        }
                    }
                }
            }
        }

        try:
            response = self.client.search(index=settings.es_index_name, body=query)
            topic_buckets = response.get("aggregations", {}).get("topics", {}).get("buckets", [])

            result = []
            for bucket in topic_buckets:
                topic_name = bucket.get("key", "")
                total_count = bucket.get("doc_count", 0)

                # 获取各法域的分布
                jur_buckets = bucket.get("by_jurisdiction", {}).get("buckets", [])
                by_jurisdiction = {b.get("key"): b.get("doc_count") for b in jur_buckets}

                # 获取示例法律（取前3个）
                sample_query = {
                    "size": 3,
                    "query": {"term": {"topic_labels": topic_name}},
                    "_source": ["law_id", "title", "jurisdiction"]
                }
                sample_response = self.client.search(index=settings.es_index_name, body=sample_query)
                samples = []
                for hit in sample_response.get("hits", {}).get("hits", []):
                    source = hit.get("_source", {})
                    samples.append({
                        "law_id": source.get("law_id"),
                        "law_name_zh": source.get("title"),
                        "jurisdiction": source.get("jurisdiction")
                    })

                result.append({
                    "topic": topic_name,
                    "label_zh": _to_label_zh(topic_name),
                    "count": total_count,
                    "by_jurisdiction": by_jurisdiction,
                    "laws": samples[:5]
                })

            return result

        except Exception as e:
            print(f"⚠️ 获取主题统计失败: {e}")
            return []

    # ================================================================
    #  专题分析缓存层（medical_analysis_cache，C2 §6）
    # ================================================================

    CACHE_INDEX = settings.es_cache_index_name

    def _ensure_cache_index(self):
        """确保缓存索引存在，不存在则自动创建（静默失败）"""
        try:
            if self.client.indices.exists(index=self.CACHE_INDEX):
                return
            self.client.indices.create(
                index=self.CACHE_INDEX,
                body={
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {
                        "properties": {
                            "cache_type": {"type": "keyword"},  # "analysis" | "compare" | "summary"
                            "topic_id": {"type": "keyword"},
                            "target_a": {"type": "keyword"},
                            "target_b": {"type": "keyword"},
                            "fingerprint": {"type": "keyword"},
                            "report_data": {"type": "object", "enabled": False},
                            "created_at": {"type": "date"},
                            "updated_at": {"type": "date"},
                            "cache_version": {"type": "integer"},
                        }
                    },
                }
            )
        except Exception as e:
            print(f"[Cache] 索引创建/检查失败（缓存功能将不可用）: {e}")

    def _cache_doc_id(self, cache_type: str, topic_id: str, jurisdiction_a: str, jurisdiction_b: str) -> str:
        """生成缓存文档 ID（沿用 {cache_type}::{topic_id}::{a}::{b} 格式）"""
        return f"{cache_type}::{topic_id}::{jurisdiction_a}::{jurisdiction_b}"

    def save_analysis_cache(
        self,
        topic_id: str,
        jurisdiction_a: str,
        jurisdiction_b: str,
        fingerprint: str,
        report_data: Dict,
        cache_type: str = "analysis",
    ) -> bool:
        """保存/更新缓存（upsert），支持 analysis 和 compare 两种类型
        
        增强功能：写入前自动清除旧缓存，确保数据一致性
        """
        import datetime, copy
        self._ensure_cache_index()
        doc_id = self._cache_doc_id(cache_type, topic_id, jurisdiction_a, jurisdiction_b)

        # ===== 自动清除旧缓存（确保最新结果）=====
        try:
            old_doc = self.client.get(index=self.CACHE_INDEX, id=doc_id, ignore=[404])
            if old_doc.get("found"):
                self.client.delete(index=self.CACHE_INDEX, id=doc_id)
                self.client.indices.refresh(index=self.CACHE_INDEX)
                logger.info(f"[Cache] 已清除旧缓存: {doc_id} (准备写入新数据)")
        except Exception as e:
            logger.warning(f"[Cache] 清除旧缓存失败（不影响后续写入）: {e}")

        # 深拷贝 + 剥离运行时内部字段（不存入缓存）
        cache_data = copy.deepcopy(report_data)
        for key in ("_raw_response_a", "_raw_response_b", "_cache_hit", "_cache_fingerprint", "timing"):
            cache_data.pop(key, None)
        # extraction 中的 _raw_response 也剥离
        ext = cache_data.get("extraction", {})
        if isinstance(ext, dict):
            for side_key in list(ext.keys()):
                if side_key.startswith("_"):
                    ext.pop(side_key, None)
                elif isinstance(ext[side_key], dict):
                    ext[side_key].pop("_raw_response", None)

        # 修复：将 topic 对象转换为 JSON 字符串（ES字段定义为text类型，不支持对象）
        # compare类型存储的是纯字符串（如"数据保护"），analysis类型传入的是字典对象
        import json
        topic_data = cache_data.get("topic")
        if isinstance(topic_data, dict):
            # 完整序列化为JSON字符串，保留所有字段（name、id、dimensions等）
            cache_data["topic"] = json.dumps(topic_data, ensure_ascii=False)
            logger.info(f"[Cache] topic对象已转换为JSON字符串: {cache_data['topic'][:80]}...")

        try:
            self.client.index(
                index=self.CACHE_INDEX,
                id=doc_id,
                body={
                    "cache_type": cache_type,
                    "topic_id": topic_id,
                    # ES 字段为 target_a/b（C2 §6）；方法签名沿用旧参数名，
                    # 待 BE-08 服务重写时统一更名。
                    "target_a": jurisdiction_a,
                    "target_b": jurisdiction_b,
                    "fingerprint": fingerprint,
                    "report_data": cache_data,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "cache_version": 1,
                },
            )
            self.client.indices.refresh(index=self.CACHE_INDEX)

            # 验证写入：立即读回确认
            verify = self.client.get(index=self.CACHE_INDEX, id=doc_id)
            if verify["found"]:
                logger.info(f"[Cache] 已保存并验证[{cache_type}]: {doc_id}, fp={fingerprint[:16]}...")
                return True
            else:
                logger.error(f"[Cache] 写入后验证失败！doc_id={doc_id}")
                return False
        except Exception as e:
            logger.error(f"[Cache] 保存失败: {type(e).__name__}: {e}")
            return False

    def get_analysis_cache(
        self,
        topic_id: str,
        jurisdiction_a: str,
        jurisdiction_b: str,
        cache_type: str = "analysis",
    ) -> Optional[Dict]:
        """
        查询缓存。返回 {fingerprint, report_data, updated_at} 或 None。
        特殊：topic_id="__all__" 时返回该类型的全部记录列表。
        """
        self._ensure_cache_index()

        # 特殊模式：返回全部记录
        if topic_id == "__all__":
            try:
                resp = self.client.search(
                    index=self.CACHE_INDEX,
                    body={"query": {"term": {"cache_type": cache_type}}, "size": 50},
                )
                return [hit["_source"] for hit in resp["hits"]["hits"]]
            except Exception as e:
                logger.error(f"[Cache] 批量查询失败: {e}")
                return []

        doc_id = self._cache_doc_id(cache_type, topic_id, jurisdiction_a, jurisdiction_b)
        try:
            resp = self.client.get(index=self.CACHE_INDEX, id=doc_id)
            src = resp.get("_source", {})
            return {
                "fingerprint": src.get("fingerprint"),
                "report_data": src.get("report_data"),
                "updated_at": src.get("updated_at"),
            }
        except NotFoundError:
            return None
        except Exception as e:
            print(f"[Cache] 查询失败: {e}")
            return None

    def delete_analysis_cache(
        self,
        topic_id: str,
        jurisdiction_a: str,
        jurisdiction_b: str,
        cache_type: str = "analysis",
    ) -> bool:
        """删除指定缓存"""
        doc_id = self._cache_doc_id(cache_type, topic_id, jurisdiction_a, jurisdiction_b)
        try:
            self.client.delete(index=self.CACHE_INDEX, id=doc_id)
            return True
        except NotFoundError:
            return True
        except Exception as e:
            print(f"[Cache] 删除失败: {e}")
            return False

    # ================================================================
    #  法规摘要缓存层（summary）
    # ================================================================

    def _summary_cache_doc_id(self, law_id: str) -> str:
        """生成摘要缓存文档 ID"""
        return f"summary::{law_id}::_::_"

    def compute_law_fingerprint(self, law_id: str) -> str:
        """
        计算法规指纹（标题 + 条款数 + 通过日期），用于检测数据变化。

        公开方法：除缓存层内部使用外，知识层（KG）也用它判断抽取结果是否失效。
        指纹相同的含义是「该法规的内容与结构未变」，可安全复用已抽取的三元组。
        """
        import hashlib
        try:
            law = self.get_law_by_id(law_id)
            if law:
                chunk_count = len(law.get("chunks", []))
                title = law.get("title", "")
                passing_date = law.get("passing_date", "")
                raw = f"{title}_{chunk_count}_{passing_date}"
                return hashlib.md5(raw.encode("utf-8")).hexdigest()
        except Exception:
            pass
        return ""

    def save_summary_cache(self, law_id: str, summary_data: Dict) -> bool:
        """
        保存法规摘要缓存（无过期时间，仅在数据变化时失效）
        
        Args:
            law_id: 法规ID
            summary_data: 摘要数据
        
        Returns:
            是否保存成功
        """
        import datetime, copy
        self._ensure_cache_index()
        doc_id = self._summary_cache_doc_id(law_id)
        fingerprint = self.compute_law_fingerprint(law_id)

        try:
            old_doc = self.client.get(index=self.CACHE_INDEX, id=doc_id, ignore=[404])
            if old_doc.get("found"):
                self.client.delete(index=self.CACHE_INDEX, id=doc_id)

            cache_data = copy.deepcopy(summary_data)

            self.client.index(
                index=self.CACHE_INDEX,
                id=doc_id,
                body={
                    "cache_type": "summary",
                    "topic_id": law_id,
                    "target_a": "_",
                    "target_b": "_",
                    "fingerprint": fingerprint,
                    "report_data": cache_data,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "cache_version": 1,
                },
            )
            self.client.indices.refresh(index=self.CACHE_INDEX)

            verify = self.client.get(index=self.CACHE_INDEX, id=doc_id)
            if verify["found"]:
                logger.info(f"[Cache] 已保存摘要缓存: {doc_id}, fp={fingerprint[:16]}...")
                return True
            else:
                logger.error(f"[Cache] 摘要缓存写入后验证失败！doc_id={doc_id}")
                return False
        except Exception as e:
            logger.error(f"[Cache] 保存摘要缓存失败: {type(e).__name__}: {e}")
            return False

    def get_summary_cache(self, law_id: str) -> Optional[Dict]:
        """
        获取法规摘要缓存
        
        返回：
        - 如果缓存存在且数据未变化，返回摘要数据
        - 如果缓存不存在或数据已变化，返回 None
        
        Args:
            law_id: 法规ID
        
        Returns:
            摘要数据或 None
        """
        self._ensure_cache_index()
        doc_id = self._summary_cache_doc_id(law_id)
        
        try:
            resp = self.client.get(index=self.CACHE_INDEX, id=doc_id)
            src = resp.get("_source", {})
            cached_fingerprint = src.get("fingerprint", "")
            report_data = src.get("report_data")
            
            if not cached_fingerprint or not report_data:
                return None
            
            current_fingerprint = self.compute_law_fingerprint(law_id)
            if current_fingerprint and cached_fingerprint != current_fingerprint:
                logger.info(f"[Cache] 摘要缓存指纹不匹配，失效。law_id={law_id}")
                self.client.delete(index=self.CACHE_INDEX, id=doc_id)
                return None
            
            logger.info(f"[Cache] 命中摘要缓存: {law_id}")
            return report_data
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(f"[Cache] 查询摘要缓存失败: {e}")
            return None

    def delete_summary_cache(self, law_id: str) -> bool:
        """删除指定法规的摘要缓存"""
        doc_id = self._summary_cache_doc_id(law_id)
        try:
            self.client.delete(index=self.CACHE_INDEX, id=doc_id)
            return True
        except NotFoundError:
            return True
        except Exception as e:
            logger.error(f"[Cache] 删除摘要缓存失败: {e}")
            return False

    def delete_all_summary_cache(self) -> bool:
        """删除所有摘要缓存"""
        try:
            query = {"query": {"term": {"cache_type": "summary"}}}
            response = self.client.delete_by_query(index=self.CACHE_INDEX, body=query, refresh=True)
            logger.info(f"[Cache] 已删除 {response.get('deleted', 0)} 条摘要缓存")
            return True
        except Exception as e:
            logger.error(f"[Cache] 删除所有摘要缓存失败: {e}")
            return False

    # ================================================================
    #  医疗知识层（KG）持久化 — medical_kg_triples / medical_kg_entities（C2 §5）
    #  ------------------------------------------------------------
    #  设计要点（沿用法规版架构，仅字段医疗化）：
    #   1. 按 source_id 组织数据：新增来源只抽新增部分，不做全量重建，
    #      这是数据量持续增长时唯一可扩展的形态；
    #   2. 三元组文档 ID 由内容哈希决定（幂等 upsert），
    #      同一来源重复抽取不会产生重复记录；
    #   3. 用源文档指纹判断缓存是否失效，指纹未变则完全跳过 LLM 抽取；
    #   4. entities 索引预留 1024 维向量字段：dense_vector 的 dims 建索引后
    #      不可修改，故此处一次性建好，供实体消歧的跨语言向量对齐使用。
    #  字段映射：law_id->source_id / jurisdiction->cancer_type /
    #           source_article->source_ref / jurisdictions->cancer_types
    #  方法签名（参数名）沿用旧名，待 BE-20/BE-21 服务重写时统一更名。
    # ================================================================

    KG_TRIPLE_INDEX = settings.es_kg_triples_index_name
    KG_ENTITY_INDEX = settings.es_kg_entities_index_name

    def _ensure_kg_indices(self) -> bool:
        """确保知识层索引存在，不存在则创建（失败时返回 False，调用方降级为实时抽取）"""
        try:
            if not self.client.indices.exists(index=self.KG_TRIPLE_INDEX):
                self.client.indices.create(
                    index=self.KG_TRIPLE_INDEX,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "source_id": {"type": "keyword"},
                                "cancer_type": {"type": "keyword"},
                                "fingerprint": {"type": "keyword"},
                                "head_id": {"type": "keyword"},
                                "head_type": {"type": "keyword"},
                                "head_name": {"type": "keyword"},
                                # canonical_* 由实体消歧回填；未消歧时等于 head_id / tail_id
                                "head_canonical_id": {"type": "keyword"},
                                "tail_id": {"type": "keyword"},
                                "tail_type": {"type": "keyword"},
                                "tail_name": {"type": "keyword"},
                                "tail_canonical_id": {"type": "keyword"},
                                "relation": {"type": "keyword"},
                                "source_ref": {"type": "keyword"},
                                "confidence": {"type": "float"},
                                "extracted_at": {"type": "date"},
                            }
                        },
                    },
                )
            if not self.client.indices.exists(index=self.KG_ENTITY_INDEX):
                self.client.indices.create(
                    index=self.KG_ENTITY_INDEX,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "entity_id": {"type": "keyword"},
                                "name": {"type": "keyword"},
                                "type": {"type": "keyword"},
                                "aliases": {"type": "keyword"},
                                "cancer_types": {"type": "keyword"},
                                "embedding": {
                                    "type": "dense_vector",
                                    "dims": 1024,
                                    "index": True,
                                    "similarity": "cosine",
                                },
                                "updated_at": {"type": "date"},
                            }
                        },
                    },
                )
            return True
        except Exception as e:
            logger.warning(f"[KG] 知识层索引创建/检查失败（本次将降级为实时抽取）: {e}")
            return False

    @staticmethod
    def _kg_triple_doc_id(law_id: str, triple: Dict) -> str:
        """三元组文档 ID：由「法规 + 头实体 + 关系 + 尾实体 + 来源条款」哈希得到，保证幂等写入"""
        import hashlib
        head = triple.get("head", {}) or {}
        tail = triple.get("tail", {}) or {}
        raw = (
            f"{law_id}|{head.get('id', '')}|{triple.get('relation', '')}"
            f"|{tail.get('id', '')}|{triple.get('source_article', '')}"
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def save_kg_triples(
        self,
        law_id: str,
        triples: List[Dict],
        jurisdiction: str = "",
        fingerprint: str = "",
    ) -> int:
        """
        覆盖式保存某法规的实体关系三元组。

        采用「先删旧、再批量写入」而非追加：法规被修订后旧抽取结果必须整体失效，
        否则引用链与实体统计会同时看到新旧两版条款的关系。
        写入条数成功返回条数，失败返回 -1（调用方据此判断是否降级）。
        """
        if not self._ensure_kg_indices():
            return -1

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 清除该法规的旧三元组，保证修订后不留残影。
        # 注意：即使本次抽取结果为空也要执行清除，否则法规被修订为
        # 「无可提取关系」后，旧版本的三元组会继续参与引用链与实体统计。
        self.delete_kg_triples(law_id)

        if not triples:
            return 0

        actions = []
        for t in triples:
            head = t.get("head", {}) or {}
            tail = t.get("tail", {}) or {}
            actions.append({
                "_index": self.KG_TRIPLE_INDEX,
                "_id": self._kg_triple_doc_id(law_id, t),
                "_source": {
                    "source_id": law_id,
                    "cancer_type": jurisdiction or t.get("source_jurisdiction", ""),
                    "fingerprint": fingerprint,
                    "head_id": head.get("id", ""),
                    "head_type": head.get("type", ""),
                    "head_name": head.get("name", ""),
                    "head_canonical_id": head.get("canonical_id") or head.get("id", ""),
                    "tail_id": tail.get("id", ""),
                    "tail_type": tail.get("type", ""),
                    "tail_name": tail.get("name", ""),
                    "tail_canonical_id": tail.get("canonical_id") or tail.get("id", ""),
                    "relation": t.get("relation", ""),
                    "source_ref": t.get("source_article", ""),
                    "confidence": float(t.get("confidence", 0.8)),
                    "extracted_at": now,
                },
            })

        try:
            from elasticsearch.helpers import bulk
            success, failed = bulk(
                self.client, actions, refresh=True,
                raise_on_error=False, stats_only=True,
            )
            logger.info(
                f"[KG] 三元组已落库: law_id={law_id}, 成功={success}, 失败={failed}, "
                f"fp={(fingerprint or '')[:16]}"
            )
            return int(success)
        except Exception as e:
            logger.error(f"[KG] 三元组落库失败: {type(e).__name__}: {e}")
            return -1

    def get_kg_triples(self, law_id: str, size: int = 2000) -> List[Dict]:
        """
        读取某法规的全部三元组，还原为 kg_extraction_service 的输出格式，
        使调用方对「读缓存」与「实时抽取」得到的结果形态完全一致。
        """
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={
                    "query": {"term": {"source_id": law_id}},
                    "size": size,
                    "sort": [{"source_ref": "asc"}, {"confidence": "desc"}],
                },
            )
        except NotFoundError:
            return []
        except Exception as e:
            logger.warning(f"[KG] 读取三元组失败: {e}")
            return []

        triples: List[Dict] = []
        for hit in resp.get("hits", {}).get("hits", []):
            s = hit.get("_source", {})
            triples.append({
                "head": {
                    "id": s.get("head_id", ""),
                    "type": s.get("head_type", ""),
                    "name": s.get("head_name", ""),
                    "canonical_id": s.get("head_canonical_id", ""),
                },
                "relation": s.get("relation", ""),
                "tail": {
                    "id": s.get("tail_id", ""),
                    "type": s.get("tail_type", ""),
                    "name": s.get("tail_name", ""),
                    "canonical_id": s.get("tail_canonical_id", ""),
                },
                "source_article": s.get("source_ref", ""),
                "source_jurisdiction": s.get("cancer_type", ""),
                "confidence": s.get("confidence", 0.8),
            })
        return triples

    def get_kg_cache_meta(self, law_id: str) -> Optional[Dict]:
        """
        读取某法规的知识层缓存元信息：{fingerprint, triple_count, extracted_at}。
        从未抽取过则返回 None。用于判断能否直接复用缓存、跳过 LLM 调用。
        """
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={
                    "query": {"term": {"source_id": law_id}},
                    "size": 1,
                    "sort": [{"extracted_at": "desc"}],
                    "_source": ["fingerprint", "extracted_at"],
                    "track_total_hits": True,
                },
            )
        except NotFoundError:
            return None
        except Exception as e:
            logger.warning(f"[KG] 读取缓存元信息失败: {e}")
            return None

        hits = resp.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        if not total:
            return None
        src = (hits.get("hits") or [{}])[0].get("_source", {})
        return {
            "fingerprint": src.get("fingerprint", ""),
            "triple_count": total,
            "extracted_at": src.get("extracted_at", ""),
        }

    def delete_kg_triples(self, law_id: str) -> int:
        """删除某法规的全部三元组（法规被删除或重新抽取前调用）"""
        try:
            resp = self.client.delete_by_query(
                index=self.KG_TRIPLE_INDEX,
                body={"query": {"term": {"source_id": law_id}}},
                refresh=True,
                conflicts="proceed",
            )
            return resp.get("deleted", 0)
        except NotFoundError:
            return 0
        except Exception as e:
            logger.warning(f"[KG] 删除三元组失败: {e}")
            return 0

    def get_kg_statistics(self) -> Dict:
        """知识层统计：三元组总数、已抽取法规数、实体总数（供管理端与验收核对）"""
        result = {"triple_count": 0, "law_count": 0, "entity_count": 0}
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={
                    "size": 0,
                    "track_total_hits": True,
                    "aggs": {"laws": {"cardinality": {"field": "source_id"}}},
                },
            )
            result["triple_count"] = resp.get("hits", {}).get("total", {}).get("value", 0)
            result["law_count"] = resp.get("aggregations", {}).get("laws", {}).get("value", 0)
        except Exception as e:
            logger.warning(f"[KG] 三元组统计失败: {e}")
        try:
            result["entity_count"] = int(
                self.client.count(index=self.KG_ENTITY_INDEX).get("count", 0)
            )
        except Exception:
            pass
        return result

    # ---- 实体词典（legal_kg_entities）-------------------------------
    #  实体词典是「全局」的：记录规范实体名、别名集合、实体类型与出现法域。
    #  刻意不记录 law_ids —— 法规重新抽取后该字段会失真（旧法规仍被列出），
    #  而「实体出现在哪些法规」可随时由三元组索引查询得出，无需冗余存储。

    def get_kg_entities_batch(self, entity_ids: List[str]) -> Dict[str, Dict]:
        """按 entity_id 批量读取实体词典条目（单次 msearch），返回 {entity_id: 文档}"""
        keys = [e for e in entity_ids if e]
        if not keys:
            return {}

        body: List[Dict] = []
        for entity_id in keys:
            body.append({"index": self.KG_ENTITY_INDEX})
            body.append({"query": {"term": {"entity_id": entity_id}}, "size": 1})

        try:
            response = self.client.msearch(body=body)
        except NotFoundError:
            return {}
        except Exception as e:
            logger.warning(f"[KG] 批量读取实体失败: {e}")
            return {}

        result: Dict[str, Dict] = {}
        for entity_id, item in zip(keys, response.get("responses", [])):
            hits = item.get("hits", {}).get("hits", [])
            if hits:
                result[entity_id] = hits[0].get("_source", {})
        return result

    def merge_kg_entities(self, entities: List[Dict]) -> int:
        """
        合并写入实体词典：已有条目累加别名/法域集合，新条目直接写入。

        采用「批量读 + 批量写」两次往返完成，避免逐条 read-modify-write。
        别名与法域取并集，因此重复抽取同一法规不会产生重复项，也不会丢历史别名。
        返回写入条数，失败返回 -1。
        """
        if not entities:
            return 0
        if not self._ensure_kg_indices():
            return -1

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        existing = self.get_kg_entities_batch([e.get("entity_id", "") for e in entities])

        actions = []
        for ent in entities:
            entity_id = ent.get("entity_id", "")
            if not entity_id:
                continue
            old = existing.get(entity_id, {})
            merged = {
                "entity_id": entity_id,
                "name": ent.get("name", "") or old.get("name", ""),
                "type": ent.get("type", "") or old.get("type", ""),
                "aliases": sorted(set(old.get("aliases", [])) | set(ent.get("aliases", []))),
                # ES 字段 cancer_types；输入 dict 键沿用 jurisdictions（消歧服务
                # 层格式，BE-21 重写时统一更名）
                "cancer_types": sorted(
                    set(old.get("cancer_types", [])) | set(ent.get("jurisdictions", []))
                ),
                "updated_at": now,
            }
            # 保留既有向量（L3 向量对齐写入后不应被覆盖为空）
            if old.get("embedding"):
                merged["embedding"] = old["embedding"]
            elif ent.get("embedding"):
                merged["embedding"] = ent["embedding"]
            actions.append({
                "_index": self.KG_ENTITY_INDEX,
                "_id": entity_id,
                "_source": merged,
            })

        if not actions:
            return 0

        try:
            from elasticsearch.helpers import bulk
            success, failed = bulk(
                self.client, actions, refresh=True,
                raise_on_error=False, stats_only=True,
            )
            logger.info(f"[KG] 实体词典已合并: 成功={success}, 失败={failed}")
            return int(success)
        except Exception as e:
            logger.error(f"[KG] 实体词典合并失败: {type(e).__name__}: {e}")
            return -1

    def list_kg_entities(
        self,
        q: Optional[str] = None,
        entity_type: Optional[str] = None,
        page_size: int = 50,
    ) -> List[Dict]:
        """列出实体词典条目，可按规范名/别名关键词与实体类型过滤"""
        clauses: List[Dict] = []
        if q:
            # name 与 aliases 均为 keyword，用通配匹配实现子串检索
            clauses.append({
                "bool": {
                    "should": [
                        {"wildcard": {"name": f"*{q}*"}},
                        {"wildcard": {"aliases": f"*{q}*"}},
                    ],
                    "minimum_should_match": 1,
                }
            })
        if entity_type:
            clauses.append({"term": {"type": entity_type}})

        query = {"bool": {"filter": clauses}} if clauses else {"match_all": {}}
        try:
            resp = self.client.search(
                index=self.KG_ENTITY_INDEX,
                body={"query": query, "size": page_size, "sort": [{"entity_id": "asc"}]},
            )
        except NotFoundError:
            return []
        except Exception as e:
            logger.warning(f"[KG] 查询实体词典失败: {e}")
            return []

        return [hit.get("_source", {}) for hit in resp.get("hits", {}).get("hits", [])]

    def get_kg_entities_with_vectors(
        self,
        exclude_types: Optional[List[str]] = None,
        size: int = 5000,
    ) -> Optional[List[Dict]]:
        """
        读取实体词典（含 embedding），供 L3 向量对齐在内存中做同类型比对。

        一次性取回而非逐条 KNN，原因：实体词典规模在数千以内，一次搜索即可覆盖，
        后续同类型比较用矩阵运算完成，避免「每个待对齐实体一次 ES 往返」。
        失败返回 None（调用方据此降级为不使用向量对齐，而非当成「词典为空」）。
        """
        query: Dict = {"match_all": {}}
        if exclude_types:
            query = {"bool": {"must_not": [{"terms": {"type": exclude_types}}]}}
        try:
            resp = self.client.search(
                index=self.KG_ENTITY_INDEX,
                body={
                    "query": query,
                    "size": size,
                    "_source": ["entity_id", "name", "type", "aliases",
                                "cancer_types", "embedding"],
                },
            )
        except NotFoundError:
            return []
        except Exception as e:
            logger.warning(f"[KG] 读取实体向量失败: {type(e).__name__}: {e}")
            return None

        return [hit.get("_source", {}) for hit in resp.get("hits", {}).get("hits", [])]

    def delete_kg_entities(self) -> int:
        """清空实体词典（别名表或本体调整后重建用）"""
        try:
            resp = self.client.delete_by_query(
                index=self.KG_ENTITY_INDEX,
                body={"query": {"match_all": {}}},
                refresh=True,
                conflicts="proceed",
            )
            return resp.get("deleted", 0)
        except NotFoundError:
            return 0
        except Exception as e:
            logger.warning(f"[KG] 清空实体词典失败: {e}")
            return 0


# 日志别名
import logging
logger = logging.getLogger(__name__)
