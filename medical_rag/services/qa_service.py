import logging
import re
import threading
from typing import List, Dict, Optional
import time
from repositories.elasticsearch import ElasticsearchRepository
from core.config import settings
from services.safety_guard import check_answer
from utils.llm_client import chat, stream_chat_messages
from utils.semantic_cache import get_semantic_cache

logger = logging.getLogger(__name__)


class QAService:
    """问答服务（单例）。

    单例原因：QAService 会被多处构造（api/v1/qa.py、topic_analysis_service、
    structured_analysis_service）。保证进程内只有一个实例，避免重复初始化与资源竞争。
    """

    _instance: Optional['QAService'] = None
    _instance_lock = threading.Lock()

    # 主证据库类型：文献层（literature）只作兜底，不参与主检索，避免英文摘要稀释中文检索；
    # 术语层（term）只用于实体归一，不进检索结果
    PRIMARY_DATA_TYPES: List[str] = ["doc", "rec", "drug"]

    # 知识库当前覆盖的癌种：未覆盖癌种在问答入口直接给边界说明，
    # 避免经全域回退把其他癌种条目挂到越界问题上（误挂）。
    SUPPORTED_CANCERS: Dict[str, str] = {"lung": "肺癌", "colorectal": "结直肠癌"}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return  # 单例已初始化，跳过
        self._initialized = True
        self.repo = ElasticsearchRepository()

    @staticmethod
    def _detect_cancer_types(question: str) -> List[str]:
        """从问题中识别癌种代码（复用 BE-16 别名表），作为默认检索过滤维度。

        医疗场景无「法域」概念，检索维度是癌种 / 场景 / 分期等。此处仅做「癌种」的
        轻量识别：未识别到则不自动加过滤（全域检索）；识别到多癌种则交由调用方
        （对比 / 专题）处理。
        """
        from services.query_decomposer import detect_cancer_types
        return detect_cancer_types(question)

    def _enhance_query(self, query: str) -> str:
        """查询增强（医疗）：口语化表述补全标准术语。

        仅追加标准术语（磨玻璃结节 / 手术指征等），不替换原词，常规临床表述原样返回。
        癌种别名 / 临床条件的识别由 query_decomposer 负责，不在这一层处理。
        """
        from services.query_decomposer import expand_colloquial
        return expand_colloquial(query)

    def _is_retrieval_poor(self, contexts: List[Dict], min_results: int = 2, min_similarity: float = 0.6) -> bool:
        """
        方案 E：检索质量门。
        当检索结果数量不足或最高相似度过低时，认为质量不达标。
        """
        if len(contexts) < min_results:
            return True
        return contexts[0]['similarity'] < min_similarity

    def _merge_deduplicate_contexts(self, contexts_list: List[List[Dict]]) -> List[Dict]:
        """合并多组检索结果并按条目 ID 去重，按相似度降序排列。"""
        seen = set()
        merged = []
        for contexts in contexts_list:
            for ctx in contexts:
                key = (ctx.get('metadata') or {}).get('item_id') or ctx.get('content', '')[:50]
                if key in seen:
                    continue
                seen.add(key)
                merged.append(ctx)
        merged.sort(key=lambda x: x['similarity'], reverse=True)
        return merged

    def _retrieve_contexts(self, query: str, top_k: int,
                           filters: Optional[Dict] = None,
                           expand: bool = True,
                           data_types: Optional[List[str]] = None) -> List[Dict]:
        enhanced_query = self._enhance_query(query)
        candidate_k = max(top_k * 3, 20)
        contexts = []

        # data_type 显式约束：主库检索排除 literature，文献兜底只查 literature
        where = dict(filters) if filters else {}
        if data_types:
            where["data_type"] = list(data_types)
        results = self.repo.query([enhanced_query], n_results=candidate_k, where=where or None)
        if results.get('ids') and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                distance = results['distances'][0][i]
                meta = dict(results['metadatas'][0][i])
                meta['item_id'] = results['ids'][0][i]
                contexts.append({
                    'content': results['documents'][0][i],
                    'metadata': meta,
                    'similarity': 1 / (1 + distance),
                })

        contexts.sort(key=lambda x: x['similarity'], reverse=True)

        # 按条目 ID（ES _id = item_id）去重，保留相似度最高者。
        # 医疗模型下「一个推荐条目 = 一个检索单元」（C2 §3.1），无需再按条款聚合回取全文。
        seen = set()
        deduped_contexts = []
        for ctx in contexts:
            key = (ctx.get('metadata') or {}).get('item_id') or ctx.get('content', '')[:50]
            if key in seen:
                continue
            seen.add(key)
            deduped_contexts.append(ctx)

        top_contexts = deduped_contexts[:top_k]

        # 同指南上下文扩展（BE-15 语义）：主结果之外补入同指南相邻条目。
        # 扩展项追加在尾部，不挤占主结果排序；prompt 中单独成段引用。
        if settings.reference_expand_enabled and expand:
            top_contexts = top_contexts + self._expand_contexts(top_contexts)

        return top_contexts

    def _expand_contexts(self, contexts: List[Dict]) -> List[Dict]:
        """同指南上下文扩展（BE-15 语义）：回取命中条目所在指南的相邻条目。

        医疗模型下推荐条目之间无「第X条」式互引，改为按「同 doc_id + 同节（breadcrumb
        前缀）优先」补入同指南相邻条目。扩展失败返回空列表，静默降级不影响主链路。
        """
        seeds = contexts[: settings.reference_expand_sources]
        existing = {(c.get('metadata') or {}).get('item_id') for c in contexts}
        expanded: List[Dict] = []

        for seed in seeds:
            meta = seed.get('metadata') or {}
            doc_id = meta.get('doc_id')
            if not doc_id:
                continue
            breadcrumb = meta.get('breadcrumb') or ''
            prefix = breadcrumb.rsplit('/', 1)[0] if '/' in breadcrumb else breadcrumb
            try:
                docs = self.repo.get_doc_context_recs(
                    doc_id, existing, prefix, settings.reference_expand_max
                )
            except Exception:
                continue

            for doc in docs:
                item_id = doc.get('item_id')
                if not item_id or item_id in existing:
                    continue
                existing.add(item_id)
                expanded.append({
                    'content': doc.get('content', ''),
                    'metadata': {k: v for k, v in doc.items() if k != 'content'},
                    'similarity': 0.0,
                    'retrieval_hop': 2,
                    'referenced_by': meta.get('item_id', ''),
                })
                if len(expanded) >= settings.reference_expand_max:
                    return expanded
        return expanded

    @staticmethod
    def _format_context_entries(hop_contexts: List[Dict]) -> str:
        """渲染同指南上下文条目（retrieval_hop=2），返回可拼到参考资料后的段落。

        与【来源X】分开标注「关联条目」，让模型知道这些条目是同一指南的相邻推荐、
        不是直接检索命中，避免被当作独立命中来源引用。
        """
        if not hop_contexts:
            return ""
        limit = settings.reference_expand_max_chars
        parts = []
        for i, ctx in enumerate(hop_contexts, 1):
            meta = ctx.get('metadata') or {}
            content = ctx.get('content') or ''
            if limit and len(content) > limit:
                content = content[:limit] + "……（内容较长，此处仅保留前段）"
            source = meta.get('title', '')
            breadcrumb = meta.get('breadcrumb', '')
            if breadcrumb:
                source = f"{source} {breadcrumb}".strip()
            parts.append(f"【关联条目{i}】{source}\n{content}")
        return (
            "\n\n【同指南关联条目】以下条目不是直接检索命中，而是上述来源所属指南中的"
            "相邻推荐条目，供补充参考：\n" + "\n\n".join(parts)
        )

    @staticmethod
    def _format_literature_entries(lit_contexts: List[Dict]) -> str:
        """渲染补充文献段落（data_type=literature），返回可拼到参考资料后的段落。

        文献是英文摘要、不是指南推荐，因此与【来源X】分开编号为【文献X】，并在段首
        声明其证据地位：模型可以引用，但必须标注【文献X】并说明是文献证据，
        避免把单项研究结论当成指南推荐或标准治疗。内容过长时截断，控制 prompt 开销。
        """
        if not lit_contexts:
            return ""
        limit = settings.literature_max_chars
        parts = []
        for i, ctx in enumerate(lit_contexts, 1):
            meta = ctx.get('metadata') or {}
            title = meta.get('title', '')
            doc_id = meta.get('doc_id', '')
            content = ctx.get('content') or ''
            if limit and len(content) > limit:
                content = content[:limit] + "……（摘要较长，此处截断）"
            # 文献正文本身是「标题 + 摘要」，正文已含标题时不再重复标题，只保留编号
            head = f"【文献{i}】" + (f"（文献编号: {doc_id}）" if doc_id else "")
            if title and not content.lower().startswith(title.lower()):
                head += f"\n{title}"
            parts.append(f"{head}\n{content}")
        return (
            "\n\n【补充文献（英文摘要，非指南推荐）】以下为检索命中的英文文献摘要，"
            "仅作补充证据线索，不能替代指南推荐。如需引用请标注【文献X】，并在句中明确"
            "说明其为文献证据（如「一项II期研究显示…」），不得表述为指南推荐或标准治疗。\n"
            + "\n\n".join(parts)
        )

    def _retrieve_contexts_with_fallback(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict] = None,
        allow_fallback: bool = True
    ) -> List[Dict]:
        """方案 E：检索-反馈自适应。

        先按指定过滤条件（如癌种）检索；若质量不达标且允许回退，则追加全域检索并合并去重。
        """
        contexts = self._retrieve_contexts(query, top_k, filters,
                                           data_types=self.PRIMARY_DATA_TYPES)

        if allow_fallback and filters and self._is_retrieval_poor(contexts):
            # 限定过滤条件检索结果过差，回退到全域检索
            fallback_contexts = self._retrieve_contexts(
                query, top_k, None, data_types=self.PRIMARY_DATA_TYPES)
            contexts = self._merge_deduplicate_contexts([contexts, fallback_contexts])

        # 文献证据层补充：追加在指南证据之后，不参与主库排序，避免英文摘要挤占权威证据位次
        if settings.literature_fallback_enabled:
            lit = self._retrieve_contexts(
                query, settings.literature_top_k, filters,
                expand=False, data_types=["literature"]
            )
            lit = [c for c in lit
                   if (c.get("similarity") or 0) >= settings.literature_min_similarity]
            lit = lit[: settings.literature_top_k]
            if lit:
                contexts = contexts + lit

        return contexts

    def _call_llm(self, prompt: str) -> str:
        """调用远程API（使用智能问答模型）"""
        return self._call_llm_with_model(prompt, model=settings.llm_qa_model)

    def _call_llm_with_model(self, prompt: str, model: Optional[str] = None, 
                           response_format: Optional[Dict] = None) -> str:
        """调用远程API（支持指定模型）
        
        Args:
            prompt: 提示词
            model: 模型名称，不传则使用 settings.llm_model 默认值
            response_format: 响应格式配置，如 {'type': 'json_object'}，用于结构化输出
        
        Returns:
            LLM响应内容
        """
        return chat(prompt, model=model, response_format=response_format)

    def _call_llm_stream(self, prompt: str, model: Optional[str] = None):
        """流式调用远程API（支持指定模型）

        Args:
            prompt: 提示词
            model: 模型名称，不传则使用 settings.llm_qa_model 默认值
        """
        yield from stream_chat_messages(
            [{"role": "user", "content": prompt}],
            model=model or settings.llm_qa_model,
        )

    def _call_llm_stream_with_messages(self, messages: List[Dict], model: Optional[str] = None):
        """流式调用远程API（使用标准 messages 数组）

        Args:
            messages: 标准 OpenAI 格式的 messages 数组 [{"role": "system/user/assistant", "content": "..."}]
            model: 模型名称，不传则使用 settings.llm_qa_model 默认值
        """
        yield from stream_chat_messages(messages, model=model or settings.llm_qa_model)

    def _build_messages(self, question: str, contexts: List[Dict], history: Optional[List[Dict]] = None) -> List[Dict]:
        """构建标准 messages 数组（system + history + 当前用户消息）

        Args:
            question: 当前用户问题
            contexts: 检索到的循证上下文
            history: 对话历史列表，每条包含 role 和 content

        Returns:
            标准 OpenAI 格式的 messages 数组
        """
        # 同指南上下文条目（retrieval_hop=2）与直接命中来源分开呈现
        hop_contexts = [c for c in contexts if c.get('retrieval_hop') == 2]
        # 文献层（data_type=literature）单独成段：不占指南来源的 5 个名额，
        # 也不参与【来源X】编号，避免英文摘要被当作指南推荐引用。
        literature_contexts = [
            c for c in contexts
            if (c.get('metadata') or {}).get('data_type') == 'literature'
        ][: settings.literature_top_k]
        top_contexts = [
            c for c in contexts
            if c.get('retrieval_hop') != 2
            and (c.get('metadata') or {}).get('data_type') != 'literature'
        ][:5]
        references = []

        for i, ctx in enumerate(top_contexts, 1):
            meta = ctx['metadata']
            title = meta.get('title', '')
            breadcrumb = meta.get('breadcrumb', '')
            cancer_type = meta.get('cancer_type', '') or ''
            similarity = ctx['similarity']
            content = ctx['content']
            source = f"{title} {breadcrumb}".strip()
            references.append(
                f"【来源{i}】{source}\n癌种: {cancer_type}\n相似度: {similarity:.4f}\n{content}")

        references_text = "\n\n".join(references)

        # 同指南关联条目：单独成段并标注来源，避免与直接命中的来源混淆
        references_text += self._format_context_entries(hop_contexts)

        # 补充文献：与指南来源分开编号（【文献X】），并显式声明其非指南推荐地位
        references_text += self._format_literature_entries(literature_contexts)

        # 检测是否涉及多个癌种（用于决定是否生成跨癌种对比）
        cancer_types_in_contexts = set()
        for ctx in top_contexts:
            ct = ctx['metadata'].get('cancer_type', '')
            if ct:
                cancer_types_in_contexts.add(ct)
        is_multi_cancer = len(cancer_types_in_contexts) > 1

        is_follow_up = bool(history and len(history) >= 1)

        if is_multi_cancer:
            structure_section = """
## 三、总结与建议（200-250字）
先根据参考资料对涉及的不同癌种制作简明对比表，指出推荐要点的主要差异；然后精炼总结，给出临床参考提示，并列出 2-3 条延伸提醒。"""
            total_words_hint = "总字数：1200-1800字"
        else:
            structure_section = """
## 三、总结与建议（150-200字）
精炼总结循证推荐要点，给出临床参考提示，并列出 2-3 条延伸提醒。"""
            total_words_hint = "总字数：1000-1600字"

        if is_follow_up:
            system_prompt = """你是一位肿瘤科临床决策支持助手，熟悉国内外肿瘤诊疗指南与循证医学。请严格基于【参考资料】回答用户追问，不得编造。

【重要约束 - 资料引用规则】
- 每次追问都会重新检索循证资料，请仅引用当前用户消息中【参考资料】标注的来源。
- 历史对话中提到的【来源X】是上一轮资料，已失效，不得引用。

【回答结构要求】
## 一、简要定位（1-2句话）
指出针对哪个具体问题补充说明，结合上下文明确追问意图。

## 二、循证依据详解（分点阐述，每点 200-280 字，共 3-5 个要点）
以循证推荐解读为主，指南原文仅作支撑。每个要点按以下结构展开：
1. 推荐出处：<指南/规范名称> <章/节层级（breadcrumb）>；来源标注【来源X】。
2. 推荐要点（重点）：说明适用人群、分期、分子分型等前提条件，以及推荐内容本身。
3. 证据与强度：如资料给出，注明证据等级与推荐强度。
4. 临床提示：特殊人群、注意事项或与其他推荐的衔接。

## 三、总结回顾（150-200字）
归纳核心要点，并列出 2-3 条延伸提醒。

## 四、核心结论重申（2-3句话）
用最简洁的语言重申结论和关键要点。

【写作规范】
- 使用 Markdown 层级标题，关键术语加粗。
- 回答以循证要点解读为主，不要大段复制指南原文。
- 所有论断须有资料支撑，引用标注【来源X】。
- 语言专业、面向临床，但不替代医生判断。
- 总字数要求：800-1200字。
- 严禁编造资料中没有的信息；资料不足时明确说明。"""
        else:
            system_prompt = f"""你是一位肿瘤科临床决策支持助手，熟悉国内外肿瘤诊疗指南与循证医学，擅长把指南推荐转化为清晰的临床参考。

【回答结构要求】
## 一、核心概括（80-100字）
用 1-2 句话直接回答问题的核心，给出明确结论，并简要预告涉及的主要推荐与依据。

## 二、循证依据详解（主体部分，分 4-6 个要点，每个要点 250-320字）
以循证推荐解读为主，指南原文仅作支撑。每个要点按以下结构展开：
1. 推荐出处：<指南/规范名称> <章/节层级（breadcrumb）>；来源标注【来源X】。
2. 推荐要点（重点）：说明适用人群、分期、分子分型等前提条件，以及推荐内容本身。
3. 证据与强度：如资料给出，注明证据等级与推荐强度。
4. 临床提示：特殊人群、注意事项、与其他推荐或药物的衔接。
{structure_section}

【写作规范】
- 使用清晰的 Markdown 层级标题，关键术语加粗。
- 回答以循证要点解读为主，不要大段复制指南原文。
- 不要过多使用 emoji，保持专业、简洁的排版。
- 语言风格：面向临床医生，专业、准确、可溯源。
- 字数控制：{total_words_hint}

【严格约束】
- 必须基于参考资料，所有论断有资料支撑，引用标注【来源X】。
- 严禁编造资料中没有的信息。
- 本回答仅供临床参考，不构成诊断或用药决策；涉及具体用药请以药品说明书与主管医师判断为准。
- 如遇资料不足，明确说明："关于该问题，现有循证资料暂未提供明确规定，建议查阅指南原文或咨询专科医师后再作判断。" """

        messages = [{"role": "system", "content": system_prompt}]

        if history and len(history) >= 1:
            trimmed_history = history[-6:]
            for h in trimmed_history:
                role = h.get("role", "")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        if is_follow_up:
            user_content = f"""【追问 - 以下是为当前问题重新检索的最新循证资料，历史对话中引用的来源已失效，请仅基于以下资料回答】

{references_text}

---

## 用户追问：{question}

请继续解答："""
        else:
            user_content = f"""## 参考资料（以下为指南/规范中的循证推荐条目，请严格基于此回答，不得编造或推测）：

{references_text}

---

## 用户问题：{question}

请开始解答："""

        messages.append({"role": "user", "content": user_content})
        return messages

    # 领域守卫：写作类请求 + 明确非肿瘤问题的关键词（仅在整句不含任何肿瘤线索时生效）
    _WRITING_RE = re.compile(r"(?:写|撰写|起草|生成|润色|代写).{0,10}(?:综述|论文|标书|摘要|文献回顾)")
    _NON_TUMOR_TERMS = (
        "高血压", "降压药", "低血压", "感冒", "发烧", "退烧", "糖尿病", "血糖高",
        "腰椎间盘", "颈椎病", "关节炎", "痛风", "胃炎", "胃溃疡", "胃病", "冠心病",
        "心律失常", "脑梗", "中风", "乙肝", "肝炎", "哮喘", "鼻炎", "湿疹",
        "肾结石", "骨折", "牙痛", "前列腺增生", "白内障", "痔疮",
    )
    # 只要出现任一肿瘤线索，就交回循证检索，不做领域拦截（避免误伤
    # 「肺癌患者合并高血压怎么用药」「化疗后发烧怎么办」这类正当问题）
    _ONCOLOGY_MARKERS = ("癌", "肿瘤", "化疗", "放疗", "靶向", "免疫治疗",
                         "转移", "活检", "病理", "结节", "放化疗")

    @classmethod
    def _domain_boundary(cls, question: str, filters: Optional[Dict] = None) -> Optional[str]:
        """领域守卫：非肿瘤问题与学术写作请求在生成前直接给边界说明。

        与癌种守卫互补——癌种守卫管「问题提到癌种但本库没收录」，本守卫管
        「问题压根不是肿瘤临床问题」，避免模型拿肿瘤指南硬套（如用 ACEI 1B 推荐
        回答高血压）或直接代写综述。
        """
        if filters:
            return None
        q = question or ""
        if cls._WRITING_RE.search(q):
            return ("本系统定位于肿瘤循证决策支持，可以基于指南回答临床问题，"
                    "但不提供论文、综述等学术写作代写服务。如需临床问题解答，请直接提问。")
        if any(m in q for m in cls._ONCOLOGY_MARKERS):
            return None
        hit = next((t for t in cls._NON_TUMOR_TERMS if t in q), None)
        if hit:
            return (f"本知识库聚焦肺癌与结直肠癌的循证诊疗，暂不覆盖「{hit}」等非肿瘤问题，"
                    "无法给出基于指南的建议。建议咨询相应专科医师。")
        return None

    @classmethod
    def _scope_boundary(cls, question: str, filters: Optional[Dict] = None) -> Optional[str]:
        """癌种边界守卫：问题明确指向知识库未覆盖的癌种时返回边界说明，否则 None。

        仅在未显式传 filters 时生效（对比 / 专题等调用方自行指定了检索范围）。
        多癌种问题只要有一个癌种被覆盖就不拦截，交由多癌种对比逻辑处理。
        """
        if filters:
            return None
        detected = cls._detect_cancer_types(question)
        if detected and not (set(detected) & set(cls.SUPPORTED_CANCERS)):
            covered = "、".join(cls.SUPPORTED_CANCERS.values())
            return (
                f"本知识库当前仅覆盖{covered}两类癌种，暂未收录该问题涉及的癌种，"
                "无法基于本库给出循证依据。建议查阅相应癌种的最新指南或咨询专科医师后再作判断。"
            )
        return None

    def ask_stream(self, question: str, top_k: int = 5, filters: Optional[Dict] = None,
                    history: Optional[List[Dict]] = None):
        """流式问答（医疗循证），外层套语义缓存。

        命中（Redis 有该问题或其同义改写）：直接重放已缓存答案，跳过检索 + 精排 + 生成；
        未命中：透传底层帧，并在答案完整时把「问题 + 答案 + 依据」写回 Redis。

        filters 为检索过滤条件（键=ES 字段名，如 cancer_type / scenario / stage）；
        未显式传入时，自动从问题识别癌种作为默认过滤（识别不到则全域检索）。

        settings.rag_chain_enabled 打开时走 LangChain 编排链，否则回退既有手写链路；
        两条链路共用同一检索口径与 SSE 协议。langchain 采用懒加载，未安装不影响旧链路。
        """
        eligible = (settings.semantic_cache_enabled and settings.semantic_cache_qa_enabled
                    and bool(question and question.strip()) and not history)

        if eligible:
            cache_scope = dict(filters or {})
            cache_scope["top_k"] = top_k
            payload, similarity = get_semantic_cache().lookup("qa", question, cache_scope)
            if payload:
                yield from self._replay_cached_answer(payload, similarity)
                return

        collected: Dict[str, object] = {"sources": [], "retrieved_count": 0,
                                        "cancer_types": [], "answer": "", "failed": False}
        for frame in self._ask_stream_uncached(question, top_k, filters, history):
            ftype = frame.get("type")
            if ftype == "sources":
                collected["sources"] = frame.get("sources") or []
                collected["retrieved_count"] = frame.get("retrieved_count") or 0
                collected["cancer_types"] = frame.get("cancer_types") or []
            elif ftype == "content":
                collected["answer"] = str(collected["answer"]) + str(frame.get("data") or "")
            elif ftype == "error":
                collected["failed"] = True
            elif ftype == "end":
                # 越界拦截、无依据、报错三类结果都不入缓存：
                # 它们要么极廉价，要么依赖上下文，复用价值低且会污染命中率统计
                if (eligible and not collected["failed"]
                        and collected["answer"] and collected["retrieved_count"]):
                    get_semantic_cache().store(
                        "qa", question,
                        {"answer": collected["answer"],
                         "sources": collected["sources"],
                         "retrieved_count": collected["retrieved_count"],
                         "cancer_types": collected["cancer_types"]},
                        cache_scope,
                        meta={"top_k": top_k},
                    )
            yield frame

    def _ask_stream_uncached(self, question: str, top_k: int = 5,
                             filters: Optional[Dict] = None,
                             history: Optional[List[Dict]] = None):
        """不含缓存的原始流式问答（原 ask_stream 主体）。"""
        boundary = (self._scope_boundary(question, filters)
                    or self._domain_boundary(question, filters))
        if boundary:
            yield {"type": "sources", "sources": [], "retrieved_count": 0, "cancer_types": []}
            yield {"type": "content", "data": boundary}
            yield {"type": "end", "timing": {
                "detect_cancer_types": "0.0000s", "retrieve_contexts": "0.0000s",
                "build_prompt": "0.0000s", "call_llm": "0.0000s", "total": "0.0000s"}}
            return

        if settings.rag_chain_enabled:
            yield from self._ask_stream_via_chain(question, top_k, filters, history)
        else:
            yield from self._ask_stream_legacy(question, top_k, filters, history)

    @staticmethod
    def _replay_cached_answer(payload: Dict, similarity: float):
        """把缓存条目按原 SSE 协议重放，契约与实时链路一致。

        timing 全 0 是刻意的：命中时确实没有检索与生成耗时，不能复用上一次的耗时数字。
        """
        logger.info("[语义缓存] 问答命中：相似度 %.4f", similarity)
        yield {"type": "status", "stage": "cache", "data": "命中热点问题缓存…"}
        yield {"type": "sources", "sources": payload.get("sources") or [],
               "retrieved_count": payload.get("retrieved_count") or 0,
               "cancer_types": payload.get("cancer_types") or [],
               "cache_hit": True, "similarity": round(float(similarity), 4)}
        answer = str(payload.get("answer") or "")
        for i in range(0, len(answer), 240):
            yield {"type": "content", "data": answer[i:i + 240]}
        yield {"type": "end", "cache_hit": True, "similarity": round(float(similarity), 4),
               "timing": {"detect_cancer_types": "0.0000s", "retrieve_contexts": "0.0000s",
                          "build_prompt": "0.0000s", "call_llm": "0.0000s",
                          "total": "0.0000s"}}

    @staticmethod
    def _to_lc_message(message: Dict):
        """聊天历史 dict（role/content）转为 LangChain 消息对象。"""
        from langchain_core.messages import AIMessage, HumanMessage
        if message.get("role") == "assistant":
            return AIMessage(content=message.get("content", ""))
        return HumanMessage(content=message.get("content", ""))

    def _ask_stream_via_chain(self, question: str, top_k: int = 5, filters: Optional[Dict] = None,
                              history: Optional[List[Dict]] = None):
        """LangChain 编排链流式问答（与既有链路行为等值）。

        检索经 MedicalEvidenceRetriever（BaseRetriever）、消息组装复用 _build_messages、
        生成经 ChatOpenAI；链为两段式（同步 .stream），SSE 协议帧由 rag.stream_bridge 构造。
        """
        from rag.chain import build_generation_stage, build_retrieval_stage
        from rag.documents import from_documents
        from rag.prompts import build_chat_prompt
        from rag.retriever import MedicalEvidenceRetriever
        from rag.stream_bridge import (
            content_frame, end_frame, error_frame, sources_frame, status_frame,
        )

        yield status_frame("retrieve", "正在检索循证依据…")
        total_start = time.time()

        t1 = time.time()
        if filters:
            effective_filters = filters
            allow_fallback = False
        else:
            detected = self._detect_cancer_types(question)
            effective_filters = {"cancer_type": detected[0]} if len(detected) == 1 else None
            allow_fallback = True
        t_detect = time.time() - t1

        retriever = MedicalEvidenceRetriever(
            repo=self.repo, top_k=top_k, filters=effective_filters, allow_fallback=allow_fallback
        )
        timing_holder: Dict[str, float] = {}

        def _message_builder(payload: Dict) -> Dict:
            t = time.time()
            messages = self._build_messages(question, from_documents(payload["documents"]), history)
            timing_holder["build_prompt"] = time.time() - t
            return {
                "documents": payload["documents"],
                "system_prompt": messages[0]["content"],
                "history": [self._to_lc_message(m) for m in messages[1:-1]],
                "user_message": messages[-1]["content"],
            }

        stage = build_retrieval_stage(retriever=retriever, message_builder=_message_builder)

        t2 = time.time()
        try:
            prepared = stage.invoke({"question": question})
        except Exception as e:
            yield error_frame(f"检索循证知识时发生错误：{str(e)}")
            return
        t_prompt = timing_holder.get("build_prompt", 0.0)
        t_retrieve = (time.time() - t2) - t_prompt

        documents = prepared["documents"]
        if not documents:
            yield error_frame("未找到相关的循证推荐条目，建议查阅指南原文或咨询专科医师后再作判断。")
            return

        generation = build_generation_stage(
            prompt=build_chat_prompt(), model=settings.llm_qa_model, streaming=True
        )

        yield sources_frame(from_documents(documents))
        yield status_frame("generate", "正在生成回答…")

        collected: List[str] = []
        try:
            t3 = time.time()
            for chunk in generation.stream({
                "system_prompt": prepared["system_prompt"],
                "history": prepared["history"],
                "user_message": prepared["user_message"],
            }):
                collected.append(chunk)
                yield content_frame(chunk)
            t_llm = time.time() - t3
        except Exception as e:
            yield error_frame(f"生成回答时发生错误：{str(e)}")
            return

        # 生成后安全校验：剂量 / 预后 / 缺来源，命中则追加提示（不打断已输出的正文）
        warning = check_answer(question, "".join(collected))
        if warning:
            logger.warning("生成后安全校验命中：%s", question[:40])
            yield content_frame(warning)

        total_time = time.time() - total_start
        print(
            f"【QA链式计时】总耗时: {total_time:.4f}s | 癌种识别: {t_detect:.4f}s | 检索: {t_retrieve:.4f}s | 构建Prompt: {t_prompt:.4f}s | LLM调用: {t_llm:.4f}s"
        )

        yield end_frame({
            "detect_cancer_types": f"{t_detect:.4f}s",
            "retrieve_contexts": f"{t_retrieve:.4f}s",
            "build_prompt": f"{t_prompt:.4f}s",
            "call_llm": f"{t_llm:.4f}s",
            "total": f"{total_time:.4f}s",
        })

    def _ask_stream_legacy(self, question: str, top_k: int = 5, filters: Optional[Dict] = None,
                    history: Optional[List[Dict]] = None):
        """既有手写链路（保留作回退，settings.rag_chain_enabled=False 时启用）。"""
        # 检索阶段（含 CPU 精排）是整条链路最慢的一段，若不先推送状态，前端会白屏十几秒。
        yield {"type": "status", "stage": "retrieve", "data": "正在检索循证依据…"}
        total_start = time.time()

        try:
            t1 = time.time()
            if filters:
                effective_filters = filters
                allow_fallback = False
            else:
                detected = self._detect_cancer_types(question)
                effective_filters = {"cancer_type": detected[0]} if len(detected) == 1 else None
                allow_fallback = True
            t_detect = time.time() - t1

            t2 = time.time()
            contexts = self._retrieve_contexts_with_fallback(question, top_k, effective_filters, allow_fallback)
            t_retrieve = time.time() - t2
        except Exception as e:
            yield {"type": "error", "data": f"检索循证知识时发生错误：{str(e)}"}
            return

        if not contexts:
            yield {"type": "error", "data": "未找到相关的循证推荐条目，建议查阅指南原文或咨询专科医师后再作判断。"}
            return

        sources = []
        source_cancer_types = set()
        for ctx in contexts:
            meta = ctx['metadata']
            ct = meta.get('cancer_type', '') or (meta.get('cancer_types') or [''])[0]
            if ct:
                source_cancer_types.add(ct)
            sources.append({
                "item_id": meta.get('item_id', ''),
                "data_type": meta.get('data_type', ''),
                "title": meta.get('title', ''),
                "cancer_type": ct,
                "breadcrumb": meta.get('breadcrumb', ''),
                "similarity": ctx['similarity'],
                "content": ctx['content'][:100] + "..." if len(ctx['content']) > 100 else ctx['content']
            })

        t3 = time.time()
        messages = self._build_messages(question, contexts, history)
        t_prompt = time.time() - t3

        yield {"type": "sources", "sources": sources, "retrieved_count": len(contexts),
               "cancer_types": list(source_cancer_types)}
        yield {"type": "status", "stage": "generate", "data": "正在生成回答…"}

        collected: List[str] = []
        try:
            t4 = time.time()
            llm_start_time = t4

            for chunk in self._call_llm_stream_with_messages(messages):
                collected.append(chunk)
                yield {"type": "content", "data": chunk}

            t_llm = time.time() - t4
        except Exception as e:
            yield {"type": "error", "data": f"生成回答时发生错误：{str(e)}"}
            return

        # 生成后安全校验：剂量 / 预后 / 缺来源，命中则追加提示
        warning = check_answer(question, "".join(collected))
        if warning:
            logger.warning("生成后安全校验命中：%s", question[:40])
            yield {"type": "content", "data": warning}

        total_time = time.time() - total_start
        print(
            f"【QA流式计时】总耗时: {total_time:.4f}s | 癌种识别: {t_detect:.4f}s | 检索: {t_retrieve:.4f}s | 构建Prompt: {t_prompt:.4f}s | LLM调用: {t_llm:.4f}s")

        yield {"type": "end", "timing": {
            "detect_cancer_types": f"{t_detect:.4f}s",
            "retrieve_contexts": f"{t_retrieve:.4f}s",
            "build_prompt": f"{t_prompt:.4f}s",
            "call_llm": f"{t_llm:.4f}s",
            "total": f"{total_time:.4f}s"
        }}

    def ask_stream_with_image(self, question: str, top_k: int = 5, filters: Optional[Dict] = None,
                              history: Optional[List[Dict]] = None, images: Optional[List[Dict]] = None):
        """
        支持图片的流式问答（使用智能问答模型原生多模态）

        Args:
            question: 用户问题
            top_k: 检索结果数量
            filters: 检索过滤条件（键=ES 字段名，如 cancer_type / scenario）
            history: 对话历史
            images: 图片列表，每项包含 {data: base64字符串, mime_type: 图片类型}
        """
        # 与 ask_stream 同口径：越界癌种 / 非肿瘤问题 / 写作请求在检索前拦截
        boundary = (self._scope_boundary(question, filters)
                    or self._domain_boundary(question, filters))
        if boundary:
            yield {"type": "sources", "sources": [], "retrieved_count": 0, "cancer_types": []}
            yield {"type": "content", "data": boundary}
            yield {"type": "end", "timing": {
                "detect_cancer_types": "0.0000s", "retrieve_contexts": "0.0000s",
                "call_llm": "0.0000s", "total": "0.0000s"}}
            return

        # 与 ask_stream 同理：先推送状态，避免检索期间前端长时间无反馈
        yield {"type": "status", "stage": "retrieve", "data": "正在检索循证依据…"}

        import logging
        logger = logging.getLogger(__name__)
        total_start = time.time()

        try:
            # 1. 检索循证上下文（支持自适应回退）
            t1 = time.time()
            if filters:
                effective_filters = filters
                allow_fallback = False
            else:
                detected = self._detect_cancer_types(question)
                effective_filters = {"cancer_type": detected[0]} if len(detected) == 1 else None
                allow_fallback = True
            t_detect = time.time() - t1

            t2 = time.time()
            contexts = self._retrieve_contexts_with_fallback(question, top_k, effective_filters, allow_fallback)
            t_retrieve = time.time() - t2
        except Exception as e:
            logger.error(f"[多模态QA] 检索失败: {str(e)}")
            yield {"type": "error", "data": f"检索循证知识时发生错误：{str(e)}"}
            return

        if not contexts:
            yield {"type": "error", "data": "未找到相关的循证推荐条目，建议查阅指南原文或咨询专科医师后再作判断。"}
            return

        # 2. 构建多模态消息（核心改动）
        try:
            messages = self._build_multimodal_messages(question, contexts, history, images)
        except Exception as e:
            logger.error(f"[多模态QA] 构建消息失败: {str(e)}")
            yield {"type": "error", "data": f"构建请求消息时发生错误：{str(e)}"}
            return

        # 3. 先返回sources（上下文条目不作为检索来源展示，其 similarity 为占位 0）
        sources = []
        source_cancer_types = set()
        for ctx in [c for c in contexts if c.get('retrieval_hop') != 2][:5]:
            meta = ctx['metadata']
            ct = meta.get('cancer_type', '') or (meta.get('cancer_types') or [''])[0]
            if ct:
                source_cancer_types.add(ct)
            sources.append({
                "item_id": meta.get('item_id', ''),
                "data_type": meta.get('data_type', ''),
                "title": meta.get('title', ''),
                "cancer_type": ct,
                "breadcrumb": meta.get('breadcrumb', ''),
                "similarity": ctx['similarity'],
                "content": ctx['content'][:100] + "..." if len(ctx['content']) > 100 else ctx['content']
            })

        yield {"type": "sources", "sources": sources, "retrieved_count": len(contexts),
               "cancer_types": list(source_cancer_types)}
        yield {"type": "status", "stage": "generate", "data": "正在生成回答…"}

        # 4. 流式调用智能问答模型
        collected: List[str] = []
        try:
            t3 = time.time()
            for chunk in self._call_multimodal_stream(messages):
                collected.append(chunk)
                yield {"type": "content", "data": chunk}

            t_llm = time.time() - t3
        except Exception as e:
            logger.error(f"[多模态QA] LLM调用失败: {str(e)}")
            yield {"type": "error", "data": f"生成回答时发生错误：{str(e)}"}
            return

        # 生成后安全校验：剂量 / 预后 / 缺来源，命中则追加提示
        warning = check_answer(question, "".join(collected))
        if warning:
            logger.warning("[多模态QA] 生成后安全校验命中：%s", question[:40])
            yield {"type": "content", "data": warning}

        total_time = time.time() - total_start
        print(
            f"【多模态QA流式计时】总耗时: {total_time:.4f}s | 癌种识别: {t_detect:.4f}s | 检索: {t_retrieve:.4f}s | LLM调用: {t_llm:.4f}s")

        yield {"type": "end", "timing": {
            "detect_cancer_types": f"{t_detect:.4f}s",
            "retrieve_contexts": f"{t_retrieve:.4f}s",
            "call_llm": f"{t_llm:.4f}s",
            "total": f"{total_time:.4f}s"
        }}

    def _build_multimodal_messages(self, question: str, contexts: List[Dict], history: Optional[List[Dict]] = None,
                                   images: Optional[List[Dict]] = None) -> List[Dict]:
        """
        构建多模态消息格式

        Args:
            question: 用户问题
            contexts: 检索到的循证上下文
            history: 对话历史
            images: 图片列表

        Returns:
            符合OpenAI多模态格式的messages列表
        """
        import logging
        logger = logging.getLogger(__name__)

        # System prompt
        is_follow_up = bool(history and len(history) >= 1)
        if is_follow_up:
            system_prompt = """你是一位肿瘤科临床决策支持助手，熟悉国内外肿瘤诊疗指南与循证医学。
请严格基于【参考资料】回答用户追问；如果用户上传了图片（如检验/病理/影像报告截图），请结合图片内容进行分析。
本回答仅供临床参考，不替代医生判断。

【重要约束 - 资料引用规则】
- 每次追问都会重新检索循证资料，请仅引用当前用户消息中【参考资料】标注的来源。
- 历史对话中提到的【来源X】是上一轮资料，已失效，不得引用。

【输出格式要求】请严格按照以下结构输出，使用清晰的 Markdown 标题，不要添加多余 emoji：

## 一、核心概括（80-100字）
用 1-2 句话直接给出明确结论，并简要预告涉及的主要推荐与依据。

## 二、循证依据详解（主体部分，分 4-6 个要点，每点 250-320 字）
以循证推荐解读为主，指南原文仅作支撑。每个要点按以下结构展开：
1. 推荐出处：<指南/规范名称> <章/节层级（breadcrumb）>；来源标注【来源X】。
2. 推荐要点（重点）：说明适用人群、分期、分子分型等前提条件，以及推荐内容本身。
3. 证据与强度：如资料给出，注明证据等级与推荐强度。
4. 临床提示：特殊人群、注意事项、与其他推荐或药物的衔接。

## 三、总结与建议（150-200字）
精炼总结循证要点，给出明确的临床参考提示，并列出 2-3 条延伸提醒。

【写作规范】
- 使用 Markdown 层级标题，关键术语加粗。
- 回答以循证要点解读为主，不要大段复制指南原文。
- 所有论断须有资料支撑，引用标注【来源X】。
- 语言风格：面向临床医生，专业、准确、可溯源。
- 总字数：单癌种问题 1000-1600 字，多癌种对比问题 1200-1800 字。
- 严禁编造资料中没有的信息；资料不足时明确说明。"""
        else:
            system_prompt = """你是一位肿瘤科临床决策支持助手，熟悉国内外肿瘤诊疗指南与循证医学。
请严格基于【参考资料】回答用户问题；如果用户上传了图片（如检验/病理/影像报告截图），请结合图片内容进行分析。
本回答仅供临床参考，不替代医生判断。

【输出格式要求】请严格按照以下结构输出，使用清晰的 Markdown 标题，不要添加多余 emoji：

## 一、核心概括（80-100字）
用 1-2 句话直接给出明确结论，并简要预告涉及的主要推荐与依据。

## 二、循证依据详解（主体部分，分 4-6 个要点，每点 250-320 字）
以循证推荐解读为主，指南原文仅作支撑。每个要点按以下结构展开：
1. 推荐出处：<指南/规范名称> <章/节层级（breadcrumb）>；来源标注【来源X】。
2. 推荐要点（重点）：说明适用人群、分期、分子分型等前提条件，以及推荐内容本身。
3. 证据与强度：如资料给出，注明证据等级与推荐强度。
4. 临床提示：特殊人群、注意事项、与其他推荐或药物的衔接。

## 三、总结与建议（150-200字）
精炼总结循证要点，给出明确的临床参考提示，并列出 2-3 条延伸提醒。

【写作规范】
- 使用 Markdown 层级标题，关键术语加粗。
- 回答以循证要点解读为主，不要大段复制指南原文。
- 所有论断须有资料支撑，引用标注【来源X】。
- 语言风格：面向临床医生，专业、准确、可溯源。
- 总字数：单癌种问题 1000-1600 字，多癌种对比问题 1200-1800 字。
- 严禁编造资料中没有的信息；资料不足时明确说明。"""

        # 构建参考资料文本（同指南关联条目单独成段，不占用 5 条主来源名额）
        primary_contexts = [c for c in contexts if c.get('retrieval_hop') != 2][:5]
        hop_contexts = [c for c in contexts if c.get('retrieval_hop') == 2]
        references_text = self._build_references_text_for_multimodal(primary_contexts)
        references_text += self._format_context_entries(hop_contexts)

        # 构建 messages 数组
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话（作为独立的 user/assistant 消息）
        if history and len(history) >= 1:
            trimmed_history = history[-6:]
            for h in trimmed_history:
                role = h.get("role", "")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # 当前用户消息（文本 + 图片 + 参考资料）
        user_content = []

        if is_follow_up:
            text_part = f"""【追问 - 以下是为当前问题重新检索的最新循证资料，历史对话中引用的来源已失效，请仅基于以下资料回答】

{references_text}

---
用户追问：{question}"""
        else:
            text_part = f"""## 参考资料（以下为指南/规范中的循证推荐条目）

{references_text}

---
用户问题：{question}"""

        user_content.append({"type": "text", "text": text_part})

        # 图片部分（如果有）
        if images and settings.enable_image_support:
            if len(images) > settings.max_images_per_request:
                logger.warning(f"[多模态QA] 图片数量超限：{len(images)}张，最多支持{settings.max_images_per_request}张")
                images = images[:settings.max_images_per_request]

            for idx, img in enumerate(images, 1):
                # 验证图片格式
                mime_type = img.get('mime_type', '')
                img_data = img.get('data', '')

                if not img_data:
                    logger.warning(f"[多模态QA] 第{idx}张图片数据为空，跳过")
                    continue

                # 提取格式（如 image/jpeg -> jpeg）
                format_ext = mime_type.split('/')[-1] if '/' in mime_type else mime_type
                if format_ext not in settings.supported_image_formats:
                    logger.warning(f"[多模态QA] 不支持的图片格式: {mime_type}，跳过")
                    continue

                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{img_data}",
                        "detail": "high"  # 高清模式，确保OCR准确
                    }
                })

            logger.info(f"[多模态QA] 已添加 {len([c for c in user_content if c.get('type') == 'image_url'])} 张图片")

        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_references_text_for_multimodal(self, contexts: List[Dict]) -> str:
        """为多模态场景构建参考资料文本"""
        references = []

        for i, ctx in enumerate(contexts, 1):
            meta = ctx['metadata']
            title = meta.get('title', '')
            breadcrumb = meta.get('breadcrumb', '')
            cancer_type = meta.get('cancer_type', '') or ''
            similarity = ctx['similarity']
            content = ctx['content']
            source = f"{title} {breadcrumb}".strip()

            references.append(
                f"【来源{i}】{source}\n癌种: {cancer_type}\n相似度: {similarity:.4f}\n{content}")

        return "\n\n".join(references)

    def _call_multimodal_stream(self, messages: List[Dict]):
        """
        调用多模态流式API（使用智能问答模型）

        Args:
            messages: 多模态消息列表

        Yields:
            流式文本片段
        """
        yield from stream_chat_messages(messages, model=settings.llm_qa_model)
