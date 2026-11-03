from typing import List, Dict, Optional, Any, Tuple, Iterable
import json
import os
import re
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
    """繁体转简体（轻量级，覆盖常见繁简对照字）"""
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
#    - 轻量表（约 200 字）服务于「实体名」规范化，其口径已被实体消歧 L1~L3 与
#      KG 抽取链路的实测调优所绑定，故保持原样不动；
#    - 本表是 OpenCC TSCharacters/STCharacters 的完整字符集（繁 4148 / 简 4012），
#      只用于检索侧的查询改写。
#
#  为什么检索侧必须改写：ES 的 IK 词典不含繁体字，繁体正文会被切成一字一 token
#  （实测 analyze("勞動關係") -> 勞/動/關/係），而简体查询经 IK 得到的是词级 token
#  （劳动/关系）。两者 token 空间不相交，导致「繁体字形语料上，简体查询的
#  BM25 召回恒为 0 条」（实测繁体语料上简体查询 BM25 召回为 0）。
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
# 落库时按此白名单从 metadata 透传，避免写入未声明字段：
#   通用层：data_type/review_status/updated_at
#   DOC 层：doc_id/doc_type/issuer/publish_date/cancer_types/license_note/file_path/doc_hash
#   REC 层：rec_id/cancer_type/breadcrumb/scenario/stage/stage_detail/biomarker/
#           population/verbatim/evidence_level/evidence_level_original/rec_strength/refs/page
#   DRUG 层：drug_id/generic_name/brand_names/aliases_zh/atc_code/approval_no/indications/dosage/
#           contraindications/adverse_reactions/adverse_reaction_terms/interactions/indication_note
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
    "sor", "soe", "consensus_rate",
    # DRUG
    "drug_id", "generic_name", "brand_names", "aliases_zh", "atc_code",
    "approval_no", "indications", "dosage", "contraindications",
    "adverse_reactions", "adverse_reaction_terms", "interactions",
    # DRUG 用药安全 v2
    "cancer_types", "guideline_use_cancers", "duplicate_of",
    "indication_note",
    "boxed_warning", "warnings", "dosage_adjustment",
    # TERM
    "term_id", "canonical", "category", "synonyms", "icd10", "icd_o3",
    "atc", "pinyin", "en_name", "mapping_status",
)


def _medical_metadata(source: Dict) -> Dict[str, Any]:
    """读侧 metadata 组装：通用字段 + §5.7.2 白名单透传（C2 §3.3）。

    与写侧 add_documents 的 _MEDICAL_DOC_FIELDS 同源，保证「写进去什么、读出来什么」；
    只透传白名单字段，不额外塞入任何未映射字段。
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


class ElasticsearchRepository:
    def __init__(self):
        self._init_client()
        self._model = None  # 懒加载，避免启动时加载大模型
        self._non_active_doc_cache = None  # 失效文档 doc_id 缓存：(mtime, ids)
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
                        # 原文分级原样字段（SoR / SoE / 共识率），与 evidence_level 分开存放，不合并
                        "sor": {"type": "keyword"},
                        "soe": {"type": "keyword"},
                        "consensus_rate": {"type": "keyword"},
                        # ---- DRUG 专属层（药品说明书）----
                        "drug_id": {"type": "keyword"},       # 亦作 ES _id
                        "generic_name": {"type": "keyword"},
                        "brand_names": {"type": "keyword"},
                        # 中文通用名别名（2026-11-02）：检索分词 + 精确匹配两用
                        "aliases_zh": {
                            "type": "text",
                            "analyzer": "chinese_analyzer",
                            "fields": {
                                "keyword": {"type": "keyword", "ignore_above": 256}
                            }
                        },
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
                        # 用药安全 v2（2026-11-02）：多癌种 + 黑框/警示/剂量调整 + 克隆标记
                        "cancer_types": {"type": "keyword"},          # 说明书适应证依据的癌种
                        "guideline_use_cancers": {"type": "keyword"},  # 指南推荐但说明书未覆盖
                        "duplicate_of": {"type": "keyword"},          # 克隆视图→主记录；ingest 跳过
                        "indication_note": {"type": "text", "analyzer": "chinese_analyzer"},  # 适应证限定说明（如仅联合方案）
                        "boxed_warning": {
                            "dynamic": False,
                            "properties": {
                                "title": {"type": "text", "analyzer": "chinese_analyzer"},
                                "text": {"type": "text", "analyzer": "chinese_analyzer"},
                                "code": {"type": "keyword"},
                            }
                        },
                        "warnings": {
                            "dynamic": False,
                            "properties": {
                                "title": {"type": "text", "analyzer": "chinese_analyzer"},
                                "text": {"type": "text", "analyzer": "chinese_analyzer"},
                                "code": {"type": "keyword"},
                            }
                        },
                        "dosage_adjustment": {"type": "object", "enabled": False},  # 整存整取，仅展示
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

    # ============================================================
    #  疾病档案（medical_disease_profiles，NM-01）
    #  一条文档 = 一个疾病 profile；检索抽平层用于检索，存储层整存整取。
    # ============================================================
    _DISEASE_LIST_SOURCE = [
        "disease_id", "name_canonical", "category", "cancer_type", "departments",
        "overview_text", "symptoms", "pathology_subtypes", "stages", "treatment_methods",
    ]

    def add_disease_profile(self, profile: Dict) -> bool:
        """写入/覆盖一条疾病档案（ES _id = disease_id），并补算 embedding。

        向量来源：overview_text（无则回落 name_canonical + 症状），与检索走同一
        bge-m3（1024 维，见 C2 §4.2 mapping）。
        """
        disease_id = str(profile.get("disease_id", "") or "").strip()
        if not disease_id:
            logger.warning("[Disease] 缺少 disease_id，跳过写入")
            return False
        if not self._ensure_disease_index():
            return False

        doc = dict(profile)
        doc["disease_id"] = disease_id
        embed_src = (
            str(doc.get("overview_text") or "").strip()
            or " ".join([str(doc.get("name_canonical", ""))] + list(doc.get("symptoms") or []))
        )
        try:
            if embed_src:
                doc["embedding"] = self._embed_texts([embed_src])[0]
            self.client.index(index=settings.es_disease_index_name, id=disease_id, document=doc)
            self.client.indices.refresh(index=settings.es_disease_index_name)
            return True
        except Exception as e:
            logger.warning(f"[Disease] 写入失败 {disease_id}: {e}")
            return False

    def get_disease_profile(self, disease_id: str) -> Optional[Dict]:
        """按 disease_id 取完整档案（含 sections / patient_version / links）。"""
        if not disease_id or not self._ensure_disease_index():
            return None
        try:
            resp = self.client.get(index=settings.es_disease_index_name, id=disease_id)
            src = resp.get("_source", {})
            src.setdefault("disease_id", resp.get("_id", disease_id))
            return src
        except NotFoundError:
            return None
        except Exception as e:
            logger.warning(f"[Disease] 读取失败 {disease_id}: {e}")
            return None

    def search_diseases_by_name(self, query: str, size: int = 20) -> List[Dict]:
        """按疾病名检索（name_canonical / synonyms / name_en / pinyin 多路匹配）。"""
        if not query or not self._ensure_disease_index():
            return []
        body = {
            "size": size,
            "query": {
                "bool": {
                    "should": [
                        {"match": {"name_canonical": {"query": query, "boost": 3}}},
                        {"match": {"synonyms": {"query": query, "boost": 2}}},
                        {"match": {"name_en": {"query": query}}},
                        {"term": {"pinyin": str(query).lower()}},
                        {"match": {"overview_text": query}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "_source": self._DISEASE_LIST_SOURCE,
        }
        try:
            resp = self.client.search(index=settings.es_disease_index_name, body=body)
            return [self._disease_hit(h) for h in resp["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"[Disease] 名称检索失败: {e}")
            return []

    def search_diseases_by_symptom(self, symptoms: List[str], size: int = 20) -> List[Dict]:
        """症状反查：抽平字段 symptoms（早期+晚期+体征全集）按 OR 匹配，按命中数排序。"""
        symptoms = [s for s in (symptoms or []) if s]
        if not symptoms or not self._ensure_disease_index():
            return []
        body = {
            "size": size,
            "query": {
                "bool": {
                    "should": [{"term": {"symptoms": s}} for s in symptoms],
                    "minimum_should_match": 1,
                }
            },
            # 命中症状数越多越相关
            "sort": [{"_score": {"order": "desc"}}],
            "_source": self._DISEASE_LIST_SOURCE,
        }
        try:
            resp = self.client.search(index=settings.es_disease_index_name, body=body)
            return [self._disease_hit(h) for h in resp["hits"]["hits"]]
        except Exception as e:
            logger.warning(f"[Disease] 症状反查失败: {e}")
            return []

    def list_diseases(self, category: Optional[str] = None,
                      cancer_type: Optional[str] = None, size: int = 200) -> Dict:
        """分类浏览：返回 {total, items, facets:{category, cancer_type}}。"""
        if not self._ensure_disease_index():
            return {"total": 0, "items": [], "facets": {"category": {}, "cancer_type": {}}}
        must = []
        if category:
            must.append({"term": {"category": category}})
        if cancer_type:
            must.append({"term": {"cancer_type": cancer_type}})
        body = {
            "size": size,
            "query": {"bool": {"filter": must}} if must else {"match_all": {}},
            "sort": [{"name_canonical.keyword": {"order": "asc"}}],
            "_source": self._DISEASE_LIST_SOURCE,
            "aggs": {
                "by_category": {"terms": {"field": "category", "size": 20}},
                "by_cancer_type": {"terms": {"field": "cancer_type", "size": 20}},
            },
        }
        try:
            resp = self.client.search(index=settings.es_disease_index_name, body=body)
            facets = {
                "category": {b["key"]: b["doc_count"]
                             for b in resp["aggregations"]["by_category"]["buckets"]},
                "cancer_type": {b["key"]: b["doc_count"]
                                for b in resp["aggregations"]["by_cancer_type"]["buckets"]},
            }
            return {
                "total": resp["hits"]["total"]["value"],
                "items": [self._disease_hit(h) for h in resp["hits"]["hits"]],
                "facets": facets,
            }
        except Exception as e:
            logger.warning(f"[Disease] 分类浏览失败: {e}")
            return {"total": 0, "items": [], "facets": {"category": {}, "cancer_type": {}}}

    def count_diseases(self) -> int:
        """疾病档案总数（无索引/无数据时为 0）。"""
        if not self._ensure_disease_index():
            return 0
        try:
            resp = self.client.count(index=settings.es_disease_index_name)
            return int(resp.get("count", 0))
        except Exception:
            return 0

    @staticmethod
    def _disease_hit(hit: Dict) -> Dict:
        """命中结构扁平化：_source + 检索分（_score）。"""
        src = dict(hit.get("_source", {}))
        src.setdefault("disease_id", hit.get("_id", ""))
        src["_score"] = hit.get("_score")
        return src

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
            # 仅落白名单字段，未映射字段一律不入库）
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
            # 相似度没有区分度（旧实现因此让前端所有条目都显示 50%）。展示分改用
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

        # 时效过滤：剔除已废止/已删除文档
        excluded = self._excluded_doc_filter()
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

        查询串会同时带上简、繁两种写法（含繁体字形的语料可被简体查询召回）：
        IK 词典不含繁体字，繁体被切成一字一 token，若只按用户输入的写法检索，
        简体查询在繁体语料上会一条都召不回。具体写法由 zh_query_variants 生成。
        """
        variants = zh_query_variants(query_text)
        analysis_query = " ".join(variants) if len(variants) > 1 else query_text
        bm25_query = {
            "multi_match": {
                "query": analysis_query,
                "fields": ["content^3", "title^5"],
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

        # 时效过滤：剔除已废止/已删除文档
        excluded = self._excluded_doc_filter()
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
        仅被 BM25 召回、未进 KNN 的条目没有余弦分，记为 None。
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
    #  文档时效过滤
    #  ------------------------------------------------------------
    #  doc_catalog.json 的 status 标记文档时效。检索层默认剔除已废止/已删除的
    #  文档，否则失效内容仍会被检索命中并被 LLM 当作现行依据引用。
    #  实现上不改 ES 文档（避免重新入库）：状态只影响检索过滤条件，
    #  按 doc_id 排除即可；catalog 文件变更后依据 mtime 自动失效缓存。
    # ================================================================

    # 不可检索的状态：repealed 已废止 / deleted 已删除 / missing 数据缺失
    # 注意 amended（已修订）表示文档仍然现行有效，只是内容被修改过，不排除
    _NON_RETRIEVABLE_STATUS = ("repealed", "deleted", "missing")

    def _non_active_doc_ids(self) -> List[str]:
        """
        读取当前不可检索的 doc_id 列表。

        按文件 mtime 缓存解析结果，避免每次检索都解析整个目录 JSON。
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

        if self._non_active_doc_cache and self._non_active_doc_cache[0] == mtime:
            return self._non_active_doc_cache[1]

        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"[时效过滤] 读取文档目录失败，本次不做时效过滤: {e}")
            return []

        docs = data.get("docs", []) if isinstance(data, dict) else data
        if isinstance(docs, dict):
            docs = list(docs.values())

        ids = [
            x.get("doc_id")
            for x in docs
            if isinstance(x, dict) and x.get("doc_id")
            and x.get("status") in self._NON_RETRIEVABLE_STATUS
        ]
        if ids:
            logger.info(f"[时效过滤] 本次排除 {len(ids)} 篇已废止/已删除文档")
        self._non_active_doc_cache = (mtime, ids)
        return ids

    def _excluded_doc_filter(self) -> Optional[Dict]:
        """构造排除失效文档的 ES 过滤子句，无失效文档时返回 None"""
        ids = self._non_active_doc_ids()
        return {"terms": {"doc_id": ids}} if ids else None

    def get(self, doc_id: str) -> Optional[Dict]:
        try:
            response = self.client.get(index=settings.es_index_name, id=doc_id)
            return response.get("_source", {})
        except NotFoundError:
            return None

    def delete_item(self, item_id: str) -> bool:
        """按业务 ID（ES _id）删除单条条目。成功或本就不存在均返回 True。"""
        if not item_id:
            return False
        try:
            self.client.delete(index=settings.es_index_name, id=item_id, refresh=True)
            return True
        except NotFoundError:
            return True
        except Exception as e:
            logger.warning(f"[Doc] 删除条目失败: {type(e).__name__}: {e}")
            return False

    def list_items(
        self,
        data_type: Optional[str] = None,
        cancer_type: Optional[str] = None,
        page_size: int = 100,
        cancer_scope: str = "label",
    ) -> List[Dict]:
        """按 data_type / 癌种列出条目（含 _id），用于管理端条目浏览。

        cancer_scope: "label"（默认）按 cancer_types（说明书适应证依据）过滤；
                      "guideline" 按 guideline_use_cancers（指南推荐但说明书未覆盖）过滤。
        """
        clauses: List[Dict] = []
        if data_type:
            clauses.append({"term": {"data_type": data_type}})
        if cancer_type:
            field = "guideline_use_cancers" if cancer_scope == "guideline" else "cancer_types"
            clauses.append({"term": {field: cancer_type}})
        query = {"bool": {"filter": clauses}} if clauses else {"match_all": {}}
        try:
            resp = self.client.search(
                index=settings.es_index_name,
                body={"query": query, "size": max(1, min(page_size, 500))},
            )
        except Exception as e:
            logger.warning(f"[Doc] 列出条目失败: {type(e).__name__}: {e}")
            return []

        items = []
        for hit in resp.get("hits", {}).get("hits", []):
            source = dict(hit.get("_source", {}))
            source["_id"] = hit.get("_id")
            items.append(source)
        return items

    def get_doc_catalog_records(self) -> List[Dict]:
        """返回 DOC 记录 + 各文档的 REC 条目数，供 doc_catalog 重建（管理端同步）。

        取代旧「按文档聚合」的目录重建实现：
        直接按 data_type=doc 取 DOC 字段，并按 data_type=rec 聚合统计每篇指南的条目数。
        """
        result: Dict[str, Dict] = {}
        for src in self.list_items(data_type="doc", page_size=500):
            did = src.get("doc_id") or src.get("_id")
            if not did:
                continue
            result[did] = {
                "doc_id": did,
                "title": src.get("title", ""),
                "doc_type": src.get("doc_type", ""),
                "issuer": src.get("issuer", ""),
                "cancer_types": src.get("cancer_types", []) or [],
                "version": src.get("version", ""),
                "publish_date": src.get("publish_date", ""),
                "item_count": 0,
            }

        # 统计每篇指南的推荐条目数（聚合 doc_id）
        try:
            resp = self.client.search(
                index=settings.es_index_name,
                body={
                    "size": 0,
                    "query": {"term": {"data_type": "rec"}},
                    "aggs": {"by_doc": {"terms": {"field": "doc_id", "size": 10000}}},
                },
            )
            for b in resp.get("aggregations", {}).get("by_doc", {}).get("buckets", []):
                did = b.get("key")
                if did in result:
                    result[did]["item_count"] = b.get("doc_count", 0)
        except Exception as e:
            logger.warning(f"[Doc] 统计指南条目数失败: {e}")

        return list(result.values())

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
        # 注：当前模型下无需按字段排序——filter-only 检索无相关度；且历史排序键
        # 在新索引 medical_knowledge 无映射，会触发 no-mapping 报错；chunk_index
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
    
    def get_all_topics(self) -> List[Dict]:
        """获取所有主题标签及计数（医疗）。

        C2 §3.3：主题字段为 nested（topics_details），需 nested 聚合包裹。
        返回格式: [{"id": "cancer_lung", "label_zh": "肺癌", "count": 42}, ...]
        """
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "nested": {"path": "topics_details"},
                    "aggs": {
                        "labels": {"terms": {"field": "topics_details.label_zh", "size": 100}}
                    },
                }
            },
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = (response.get("aggregations", {})
                   .get("topics", {}).get("labels", {}).get("buckets", []))

        result = []
        for bucket in buckets:
            label_zh = bucket.get("key", "")
            if not label_zh:
                continue
            result.append({
                "id": _label_zh_to_topic_id(label_zh),
                "label_zh": label_zh,
                "count": bucket.get("doc_count", 0),
            })

        # 按 count 降序排列
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    def get_topic_filter_values(self) -> List[str]:
        """获取所有可用的主题标签值（医疗；nested 聚合 topics_details.label_zh）"""
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "nested": {"path": "topics_details"},
                    "aggs": {
                        "labels": {"terms": {"field": "topics_details.label_zh", "size": 100}}
                    },
                }
            },
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        buckets = (response.get("aggregations", {})
                   .get("topics", {}).get("labels", {}).get("buckets", []))
        return [b.get("key") for b in buckets if b.get("key")]

    def get_doc_item_vectors(self, doc_id: str) -> List[Dict]:
        """
        获取指定指南下所有条目（REC）的向量及元数据（仅取必要字段，不返回 content）

        返回：[{"embedding": [...], "doc_id": ..., "title": ..., "cancer_type": ...,
                "chunk_index": ..., "topics_details": [...]}, ...]
        """
        query = {
            "query": {"bool": {"filter": [
                {"term": {"doc_id": doc_id}},
                {"term": {"data_type": "rec"}},
            ]}},
            "size": 1000,
            "sort": [{"chunk_index": {"order": "asc"}}, {"rec_id": {"order": "asc"}}],
            "_source": ["embedding", "doc_id", "title", "cancer_type", "chunk_index", "topics_details"],
        }

        response = self.client.search(index=settings.es_index_name, body=query)
        hits = response.get("hits", {}).get("hits", [])

        results = []
        for hit in hits:
            source = hit.get("_source", {})
            results.append({
                "embedding": source.get("embedding", []),
                "doc_id": source.get("doc_id", ""),
                "title": source.get("title", ""),
                "cancer_type": source.get("cancer_type", ""),
                "chunk_index": source.get("chunk_index", 0),
                "topics_details": source.get("topics_details", []),
            })

        return results

    def get_doc_head(self, doc_id: str) -> Dict:
        """取该指南首条 REC 的 title/cancer_type 与条目总数（轻量，不含正文与向量）。"""
        filter_q = {"bool": {"filter": [
            {"term": {"doc_id": doc_id}},
            {"term": {"data_type": "rec"}},
        ]}}
        total = self.client.count(index=settings.es_index_name,
                                  body={"query": filter_q}).get("count", 0)
        if not total:
            return {"found": False, "item_count": 0, "title": "", "cancer_type": ""}
        resp = self.client.search(index=settings.es_index_name, body={
            "query": filter_q,
            "size": 1,
            "sort": [{"chunk_index": {"order": "asc"}}, {"rec_id": {"order": "asc"}}],
            "_source": ["title", "cancer_type"],
        })
        hits = resp.get("hits", {}).get("hits", [])
        src = hits[0].get("_source", {}) if hits else {}
        return {
            "found": True,
            "item_count": total,
            "title": src.get("title", ""),
            "cancer_type": src.get("cancer_type", ""),
        }

    def get_doc_sample_vectors(self, doc_id: str, sample_size: int = 20) -> List[List[float]]:
        """等距抽取少量条目向量，供「代表向量」计算。

        原实现把该指南全部条目（最多 681 条）× 1024 维向量拉回 Python：
        实测 387 条时 ES 端 0.9s、Python 解析 3.5s，而中位数最多只需 20 个样本。
        这里按 chunk_index 顺序等距取 sample_size 条、逐条返回，避免整包解析。
        """
        filter_q = {"bool": {"filter": [
            {"term": {"doc_id": doc_id}},
            {"term": {"data_type": "rec"}},
        ]}}
        total = self.client.count(index=settings.es_index_name,
                                  body={"query": filter_q}).get("count", 0)
        if not total:
            return []
        n = min(sample_size, total)
        if n <= 1:
            offsets = [0]
        else:
            # 与 numpy.linspace(0, total-1, n, dtype=int) 同一取整方式（截断），
            # 保证与「全量向量 + linspace 采样」得到同一批条目，代表向量不漂移。
            offsets = sorted({int(i * (total - 1) / (n - 1)) for i in range(n)})
        vectors: List[List[float]] = []
        for off in offsets:
            try:
                resp = self.client.search(index=settings.es_index_name, body={
                    "query": filter_q,
                    "from": off,
                    "size": 1,
                    # chunk_index 存在重复值，必须加 rec_id 二级排序，
                    # 否则每次分页取到的条目不确定，代表向量会漂移。
                    "sort": [{"chunk_index": {"order": "asc"}},
                             {"rec_id": {"order": "asc"}}],
                    "_source": ["embedding"],
                })
                hits = resp.get("hits", {}).get("hits", [])
                if hits:
                    vec = hits[0].get("_source", {}).get("embedding")
                    if vec:
                        vectors.append(vec)
            except Exception:
                continue
        return vectors

    def get_docs_topic_counts(self, doc_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """一次 nested 聚合取多份指南的主题频次：{doc_id: {主题: 频次}}。

        topics_details 是 nested 类型，聚合只回传桶计数（实测约 150ms）；
        原实现把每份指南全部条目明细拉回 Python 再计数（候选 3 个时约 2.8s）。
        """
        if not doc_ids:
            return {}
        resp = self.client.search(index=settings.es_index_name, body={
            "size": 0,
            "query": {"bool": {"filter": [
                {"terms": {"doc_id": doc_ids}},
                {"term": {"data_type": "rec"}},
            ]}},
            "aggs": {"by_doc": {
                "terms": {"field": "doc_id", "size": max(len(doc_ids) + 10, 20)},
                "aggs": {"topics": {
                    "nested": {"path": "topics_details"},
                    "aggs": {"labels": {"terms": {"field": "topics_details.label_zh",
                                                  "size": 50}}},
                }},
            }},
        })
        out: Dict[str, Dict[str, int]] = {d: {} for d in doc_ids}
        buckets = resp.get("aggregations", {}).get("by_doc", {}).get("buckets", [])
        for b in buckets:
            labels = b.get("topics", {}).get("labels", {}).get("buckets", [])
            out[b["key"]] = {x["key"]: x["doc_count"] for x in labels}
        return out

    def knn_search_similar(
        self,
        query_vector: List[float],
        top_k: int = 20,
        exclude_doc_id: Optional[str] = None,
        cancer_type_filter: Optional[str] = None,
        data_type_filter: Optional[str] = None,
        min_score: float = 0.3,
    ) -> List[Dict]:
        """
        使用给定向量执行 KNN 相似搜索，返回去重前的原始条目结果。
        可选排除指定 doc_id（同指南自身条目）、癌种过滤、数据类型过滤、最低分数阈值。

        注意：使用 knn.filter 做预过滤（癌种 / 数据类型），用 post_filter 做后置排除（自身指南），
        确保排除逻辑严格生效而非仅降权。
        """
        # 构建 KNN 预过滤器（在向量搜索前缩小候选集）
        knn_filters = []
        if cancer_type_filter:
            knn_filters.append({"term": {"cancer_type": cancer_type_filter}})
        if data_type_filter:
            knn_filters.append({"term": {"data_type": data_type_filter}})

        knn_body = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": top_k * 5,
            "num_candidates": max(top_k * 20, 100),
        }
        if knn_filters:
            knn_body["filter"] = knn_filters

        search_body = {"knn": knn_body, "size": top_k * 5}

        # post_filter：在搜索结果上做硬性排除（确保同指南自身不被返回）
        post_filter_clauses = []
        if exclude_doc_id:
            post_filter_clauses.append({"term": {"doc_id": exclude_doc_id}})
        if post_filter_clauses:
            search_body["post_filter"] = {"bool": {"must_not": post_filter_clauses}}

        response = self.client.search(index=settings.es_index_name, body=search_body)
        hits = response.get("hits", {}).get("hits", [])

        results = []
        for hit in hits:
            source = hit.get("_source", {})
            similarity = float(hit.get("_score", 0.0))
            if similarity < min_score:
                continue

            results.append({
                "id": hit.get("_id"),
                "doc_id": source.get("doc_id", ""),
                "rec_id": source.get("rec_id", ""),
                "data_type": source.get("data_type", ""),
                "title": source.get("title", ""),
                "cancer_type": source.get("cancer_type", ""),
                "breadcrumb": source.get("breadcrumb", ""),
                "content_preview": source.get("content", "")[:150] if source.get("content") else "",
                "similarity": similarity,
            })

        return results

    def get_topic_statistics(self, limit: int = 50) -> List[Dict]:
        """主题统计（医疗）。

        C2 §3.3：主题字段为 nested（topics_details），用 nested 聚合按 label_zh 统计；
        子聚合按 data_type 给出分布（供看板主题词云 / 分布图）。
        返回: [{"topic": "cancer_lung", "label_zh": "肺癌", "count": 42,
                "by_data_type": {"rec": 40, "doc": 2}, "items": [...]}, ...]
        """
        query = {
            "size": 0,
            "aggs": {
                "topics": {
                    "nested": {"path": "topics_details"},
                    "aggs": {
                        "labels": {
                            "terms": {"field": "topics_details.label_zh", "size": limit},
                            "aggs": {
                                # data_type 是父文档字段，nested 子聚合看不到它，需 reverse_nested 回退
                                "by_type": {
                                    "reverse_nested": {},
                                    "aggs": {"types": {"terms": {"field": "data_type", "size": 10}}},
                                }
                            },
                        }
                    },
                }
            },
        }

        try:
            response = self.client.search(index=settings.es_index_name, body=query)
            buckets = (response.get("aggregations", {})
                       .get("topics", {}).get("labels", {}).get("buckets", []))

            result = []
            for bucket in buckets:
                label_zh = bucket.get("key", "")
                if not label_zh:
                    continue
                by_type = {b.get("key"): b.get("doc_count", 0)
                           for b in bucket.get("by_type", {}).get("types", {}).get("buckets", [])}

                # 示例条目（取前 3 条，供看板下钻展示）
                sample_query = {
                    "size": 3,
                    "query": {"nested": {"path": "topics_details", "query": {
                        "term": {"topics_details.label_zh": label_zh}}}},
                    "_source": ["title", "data_type"],
                }
                sample_response = self.client.search(index=settings.es_index_name, body=sample_query)
                items = [{"item_id": hit.get("_id"),
                          "title": hit.get("_source", {}).get("title", ""),
                          "data_type": hit.get("_source", {}).get("data_type", "")}
                         for hit in sample_response.get("hits", {}).get("hits", [])]

                result.append({
                    "topic": _label_zh_to_topic_id(label_zh),
                    "label_zh": label_zh,
                    "count": bucket.get("doc_count", 0),
                    "by_data_type": by_type,
                    "items": items,
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
                    # ES 字段为 target_a/b（C2 §6）。方法参数名沿用中性语义位置参数
                    # （各调用方按位置传入：compare 传两癌种代码、analysis/structured
                    # 传专题与对比对象），跨服务统一更名留待缓存键口径统一时处理。
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
    #  文档摘要缓存层（summary）
    # ================================================================

    def _summary_cache_doc_id(self, doc_id: str) -> str:
        """生成摘要缓存文档 ID"""
        return f"summary::{doc_id}::_::_"

    def compute_doc_fingerprint(self, doc_id: str) -> str:
        """计算文档指纹（doc_hash + 正文长度），用于检测数据变化。

        公开方法：除摘要缓存层内部使用外，知识层（KG）也用它判断抽取结果是否失效。
        指纹相同的含义是「该文档的内容与结构未变」，可安全复用已生成的摘要 / 三元组。
        医疗 DOC 的 doc_hash 由 G6 溯源约定给出（§5.7.2）；缺失时回落正文长度。
        """
        import hashlib
        try:
            src = self.get(doc_id) or {}
            if not src:
                return ""
            doc_hash = src.get("doc_hash") or ""
            content = src.get("content") or ""
            raw = f"{doc_hash}_{len(content)}"
            return hashlib.md5(raw.encode("utf-8")).hexdigest()
        except Exception:
            return ""

    def save_summary_cache(self, doc_id: str, summary_data: Dict) -> bool:
        """保存文档摘要缓存（无过期时间，仅在数据变化时失效）

        Args:
            doc_id: 文档 ID（DOC，= 摘要对象 ES _id）
            summary_data: 摘要数据

        Returns:
            是否保存成功
        """
        import datetime, copy
        self._ensure_cache_index()
        cache_id = self._summary_cache_doc_id(doc_id)
        fingerprint = self.compute_doc_fingerprint(doc_id)

        try:
            old_doc = self.client.get(index=self.CACHE_INDEX, id=cache_id, ignore=[404])
            if old_doc.get("found"):
                self.client.delete(index=self.CACHE_INDEX, id=cache_id)

            cache_data = copy.deepcopy(summary_data)

            self.client.index(
                index=self.CACHE_INDEX,
                id=cache_id,
                body={
                    "cache_type": "summary",
                    # topic_id 为缓存索引的通用「实体键」字段，此处存 doc_id
                    "topic_id": doc_id,
                    "target_a": "_",
                    "target_b": "_",
                    "fingerprint": fingerprint,
                    "report_data": cache_data,
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "cache_version": 1,
                },
            )
            self.client.indices.refresh(index=self.CACHE_INDEX)

            verify = self.client.get(index=self.CACHE_INDEX, id=cache_id)
            if verify["found"]:
                logger.info(f"[Cache] 已保存摘要缓存: {cache_id}, fp={fingerprint[:16] if fingerprint else '-'}...")
                return True
            else:
                logger.error(f"[Cache] 摘要缓存写入后验证失败！doc_id={cache_id}")
                return False
        except Exception as e:
            logger.error(f"[Cache] 保存摘要缓存失败: {type(e).__name__}: {e}")
            return False

    def get_summary_cache(self, doc_id: str) -> Optional[Dict]:
        """获取文档摘要缓存

        返回：
        - 如果缓存存在且文档数据未变化，返回摘要数据
        - 如果缓存不存在或数据已变化，返回 None
        """
        self._ensure_cache_index()
        cache_id = self._summary_cache_doc_id(doc_id)

        try:
            resp = self.client.get(index=self.CACHE_INDEX, id=cache_id)
            src = resp.get("_source", {})
            cached_fingerprint = src.get("fingerprint", "")
            report_data = src.get("report_data")

            if not cached_fingerprint or not report_data:
                return None

            current_fingerprint = self.compute_doc_fingerprint(doc_id)
            if current_fingerprint and cached_fingerprint != current_fingerprint:
                logger.info(f"[Cache] 摘要缓存指纹不匹配，失效。doc_id={doc_id}")
                self.client.delete(index=self.CACHE_INDEX, id=cache_id)
                return None

            logger.info(f"[Cache] 命中摘要缓存: {doc_id}")
            return report_data
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(f"[Cache] 查询摘要缓存失败: {e}")
            return None

    def delete_summary_cache(self, doc_id: str) -> bool:
        """删除指定文档的摘要缓存"""
        cache_id = self._summary_cache_doc_id(doc_id)
        try:
            self.client.delete(index=self.CACHE_INDEX, id=cache_id)
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
    #  设计要点：
    #   1. 按 source_id（指南 doc_id）组织数据：新增来源只抽新增部分，不做全量重建，
    #      这是数据量持续增长时唯一可扩展的形态；
    #   2. 三元组文档 ID 由内容哈希决定（幂等 upsert），
    #      同一来源重复抽取不会产生重复记录；
    #   3. 用源文档指纹判断缓存是否失效，指纹未变则完全跳过 LLM 抽取；
    #   4. entities 索引预留 1024 维向量字段：dense_vector 的 dims 建索引后
    #      不可修改，故此处一次性建好，供实体消歧的向量对齐使用。
    #  ES 字段：source_id / cancer_type / source_ref / head_* / tail_* / relation …
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
    def _kg_triple_doc_id(source_id: str, triple: Dict) -> str:
        """三元组文档 ID：由「来源 + 头实体 + 关系 + 尾实体 + 来源定位」哈希得到，保证幂等写入"""
        import hashlib
        head = triple.get("head", {}) or {}
        tail = triple.get("tail", {}) or {}
        raw = (
            f"{source_id}|{head.get('id', '')}|{triple.get('relation', '')}"
            f"|{tail.get('id', '')}|{triple.get('source_ref', '')}"
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def save_kg_triples(
        self,
        source_id: str,
        triples: List[Dict],
        cancer_type: str = "",
        fingerprint: str = "",
    ) -> int:
        """
        覆盖式保存某来源（指南）的实体关系三元组。

        采用「先删旧、再批量写入」而非追加：指南更新后旧抽取结果必须整体失效，
        否则引用链与实体统计会同时看到新旧两版的关系。
        写入条数成功返回条数，失败返回 -1（调用方据此判断是否降级）。
        """
        if not self._ensure_kg_indices():
            return -1

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 清除该来源的旧三元组，保证更新后不留残影。
        # 注意：即使本次抽取结果为空也要执行清除，否则来源被修订为
        # 「无可提取关系」后，旧版本的三元组会继续参与引用链与实体统计。
        self.delete_kg_triples(source_id)

        if not triples:
            return 0

        actions = []
        for t in triples:
            head = t.get("head", {}) or {}
            tail = t.get("tail", {}) or {}
            actions.append({
                "_index": self.KG_TRIPLE_INDEX,
                "_id": self._kg_triple_doc_id(source_id, t),
                "_source": {
                    "source_id": source_id,
                    "cancer_type": cancer_type or t.get("cancer_type", ""),
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
                    "source_ref": t.get("source_ref", ""),
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
                f"[KG] 三元组已落库: source_id={source_id}, 成功={success}, 失败={failed}, "
                f"fp={(fingerprint or '')[:16]}"
            )
            return int(success)
        except Exception as e:
            logger.error(f"[KG] 三元组落库失败: {type(e).__name__}: {e}")
            return -1

    @staticmethod
    def _kg_triples_from_hits(resp: Dict) -> List[Dict]:
        """把三元组索引检索结果还原为 kg_extraction_service 的输出形态。"""
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
                "source_ref": s.get("source_ref", ""),
                "cancer_type": s.get("cancer_type", ""),
                "confidence": s.get("confidence", 0.8),
            })
        return triples

    def _search_kg_triples(self, query: Dict, size: int) -> List[Dict]:
        """三元组索引通用检索（query 由调用方给出），结果还原为三元组列表。"""
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={"query": query, "size": size},
            )
        except NotFoundError:
            return []
        except Exception as e:
            logger.warning(f"[KG] 检索三元组失败: {type(e).__name__}: {e}")
            return []
        return self._kg_triples_from_hits(resp)

    def get_kg_triples(self, source_id: str, size: int = 2000) -> List[Dict]:
        """读取某来源（指南）的全部三元组，形状与实时抽取结果一致。"""
        return self._search_kg_triples({"term": {"source_id": source_id}}, size)

    def get_kg_triples_by_entity(self, entity_id: str, size: int = 1000) -> List[Dict]:
        """读取以某实体（规范 ID）为头或尾的全部三元组，用于实体邻域子图。"""
        if not entity_id:
            return []
        return self._search_kg_triples(
            {"bool": {
                "should": [
                    {"term": {"head_canonical_id": entity_id}},
                    {"term": {"tail_canonical_id": entity_id}},
                ],
                "minimum_should_match": 1,
            }},
            size,
        )

    def get_kg_triples_by_cancer(self, cancer_type: str, size: int = 2000) -> List[Dict]:
        """读取属于某癌种的全部三元组，用于癌种全景子图。"""
        if not cancer_type:
            return []
        return self._search_kg_triples({"term": {"cancer_type": cancer_type}}, size)

    def get_kg_entity(self, entity_id: str) -> Optional[Dict]:
        """按 entity_id 读取单条实体词典条目（不存在返回 None）。"""
        if not entity_id:
            return None
        try:
            resp = self.client.search(
                index=self.KG_ENTITY_INDEX,
                body={"query": {"term": {"entity_id": entity_id}}, "size": 1},
            )
        except NotFoundError:
            return None
        except Exception as e:
            logger.warning(f"[KG] 读取实体失败: {type(e).__name__}: {e}")
            return None
        hits = resp.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def get_doc_recs(self, doc_id: str, size: int = 500) -> List[Dict]:
        """读取某指南下的推荐条目（供知识图谱抽取），返回抽取所需字段。"""
        if not doc_id:
            return []
        try:
            resp = self.client.search(
                index=settings.es_index_name,
                body={
                    "query": {"bool": {"filter": [
                        {"term": {"doc_id": doc_id}},
                        {"term": {"data_type": "rec"}},
                    ]}},
                    "size": size,
                    "_source": ["rec_id", "content", "breadcrumb", "cancer_type", "title"],
                },
            )
        except Exception as e:
            logger.warning(f"[KG] 读取指南推荐条目失败: {type(e).__name__}: {e}")
            return []
        recs = []
        for hit in resp.get("hits", {}).get("hits", []):
            s = hit.get("_source", {})
            if s.get("content"):
                recs.append({
                    "rec_id": s.get("rec_id", ""),
                    "content": s.get("content", ""),
                    "breadcrumb": s.get("breadcrumb", ""),
                    "cancer_type": s.get("cancer_type", ""),
                })
        return recs

    def get_kg_cache_meta(self, source_id: str) -> Optional[Dict]:
        """
        读取某来源的知识层缓存元信息：{fingerprint, triple_count, extracted_at}。
        从未抽取过则返回 None。用于判断能否直接复用缓存、跳过 LLM 调用。
        """
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={
                    "query": {"term": {"source_id": source_id}},
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

    def delete_kg_triples(self, source_id: str) -> int:
        """删除某来源的全部三元组（来源被删除或重新抽取前调用）"""
        try:
            resp = self.client.delete_by_query(
                index=self.KG_TRIPLE_INDEX,
                body={"query": {"term": {"source_id": source_id}}},
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
        """知识层统计：三元组总数、已抽取指南数、实体总数（供管理端与验收核对）"""
        result = {"triple_count": 0, "source_count": 0, "entity_count": 0}
        try:
            resp = self.client.search(
                index=self.KG_TRIPLE_INDEX,
                body={
                    "size": 0,
                    "track_total_hits": True,
                    "aggs": {"sources": {"cardinality": {"field": "source_id"}}},
                },
            )
            result["triple_count"] = resp.get("hits", {}).get("total", {}).get("value", 0)
            result["source_count"] = resp.get("aggregations", {}).get("sources", {}).get("value", 0)
        except Exception as e:
            logger.warning(f"[KG] 三元组统计失败: {e}")
        try:
            result["entity_count"] = int(
                self.client.count(index=self.KG_ENTITY_INDEX).get("count", 0)
            )
        except Exception:
            pass
        return result

    # ---- 实体词典（medical_kg_entities）-----------------------------
    #  实体词典是「全局」的：记录规范实体名、别名集合、实体类型与出现癌种。
    #  刻意不记录 source_ids —— 指南重新抽取后该字段会失真（旧指南仍被列出），
    #  而「实体出现在哪些指南」可随时由三元组索引查询得出，无需冗余存储。

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
        合并写入实体词典：已有条目累加别名/癌种集合，新条目直接写入。

        采用「批量读 + 批量写」两次往返完成，避免逐条 read-modify-write。
        别名与癌种取并集，因此重复抽取同一指南不会产生重复项，也不会丢历史别名。
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
                # ES 字段 cancer_types；输入 dict 键同为 cancer_types（消歧服务层格式）
                "cancer_types": sorted(
                    set(old.get("cancer_types", [])) | set(ent.get("cancer_types", []))
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
