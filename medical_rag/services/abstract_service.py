"""指南文档摘要服务（医疗版）。

为 DOC（指南 / 规范 / 共识）记录生成摘要，写回主索引 doc 记录的 `content` 字段
（C2 §3.1：doc 的 content 即文档摘要文本，也是其向量来源），并同步刷新 `embedding`。

摘要来源：该指南下的推荐条目（REC，按 doc_id 聚合）的正文（recommendation_text）；
无 REC 时回落到 doc 记录自身 content。

幂等（C3 I-02「中断重跑只补缺」）：content 长度 >= MIN_ABSTRACT_LEN 视为已有摘要
（数据自带或此前已生成），非 force 时跳过。
"""
import os
import time
import json
from datetime import datetime
from typing import Dict, List, Tuple

from openai import OpenAI
from elasticsearch import Elasticsearch

from core.config import settings
from core.model_loader import get_embedding_model

INDEX_NAME = settings.es_index_name


class AbstractService:
    MAX_INPUT_CHARS = 40000
    # 视为「已有摘要」的 content 长度下限：入库回落值（title）通常远短于此，
    # 而生成的摘要为 150-300 字，据此区分「需生成」与「已有」
    MIN_ABSTRACT_LEN = 100

    def __init__(self):
        self.client = self._init_es_client()
        self.llm_client = self._init_llm_client()
        self.model = settings.llm_deepseek_model or "deepseek-flash"

    def _init_es_client(self):
        client_kwargs = {
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

        return Elasticsearch(**client_kwargs)

    def _init_llm_client(self):
        base_url = settings.llm_deepseek_api_base_url or "https://api.deepseek.com/v1"
        api_key = settings.llm_deepseek_api_key or ""

        if not api_key:
            raise ValueError("DeepSeek API Key 未配置，请设置 settings.llm_deepseek_api_key")

        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
            max_retries=2
        )

    def _build_abstract_prompt(self, title: str, issuer: str, source_text: str) -> str:
        return f"""请阅读以下肿瘤诊疗指南的推荐内容，用中文生成一段 150-300 字的简明摘要，包含该指南的适用范围、核心诊疗推荐与证据要点。

## 指南信息
- 名称：{title}
- 发布机构：{issuer}

## 要求
1. 用一段话概括，不要分段
2. 字数控制在 150-300 字之间
3. 语言简洁明了，突出临床要点
4. 不要输出任何格式标记或标题

## 指南推荐内容：
{source_text}"""

    def _get_doc_meta(self, doc_id: str) -> Dict:
        """读取 DOC 记录（doc_id 即 ES _id）。不存在时返回空 dict。"""
        try:
            return self.client.get(index=INDEX_NAME, id=doc_id)["_source"]
        except Exception:
            return {}

    def _gather_doc_source(self, doc_id: str) -> Tuple[str, Dict]:
        """汇总该指南的摘要来源文本。

        优先取该 doc 下全部 REC 的正文（C2 §3.1：指南摘要即对其推荐条目的概括）；
        无 REC 时回落到 doc 记录自身 content。
        """
        meta = self._get_doc_meta(doc_id)
        title = meta.get("title", "")
        issuer = meta.get("issuer", "")

        resp = self.client.search(
            index=INDEX_NAME,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"doc_id": doc_id}},
                            {"term": {"data_type": "rec"}},
                        ]
                    }
                },
                "size": 1000,
                "_source": ["content", "breadcrumb"],
            },
        )
        hits = resp.get("hits", {}).get("hits", [])

        if hits:
            parts = []
            for hit in hits:
                src = hit.get("_source", {})
                text = (src.get("content") or "").strip()
                if text:
                    parts.append(text)
            source_text = "\n".join(parts)
        else:
            source_text = (meta.get("content") or "").strip()

        return source_text, {"title": title, "issuer": issuer}

    def _call_llm_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        last_error = None

        for attempt in range(max_retries):
            try:
                create_kwargs = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                    "stream": False
                }
                extra_body = settings.llm_extra_body()
                if extra_body:
                    create_kwargs["extra_body"] = extra_body
                response = self.llm_client.chat.completions.create(**create_kwargs)
                return (response.choices[0].message.content or "").strip()
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    print(f"[AbstractService] {self.model} 调用失败 ({attempt+1}/{max_retries}): {e}, 等待 {wait_time}s 重试...")
                    time.sleep(wait_time)
                else:
                    print(f"[AbstractService] {self.model} 调用失败，已重试 {max_retries} 次: {e}")

        if last_error:
            raise Exception(f"LLM调用失败，{self.model} 重试 {max_retries} 次后仍失败: {last_error}")
        raise Exception("LLM调用失败，所有模型均已尝试")

    def _check_abstract_exists(self, doc_id: str) -> bool:
        """content 长度达阈值即视为已有摘要（数据自带或此前已生成）。"""
        meta = self._get_doc_meta(doc_id)
        return len((meta.get("content") or "").strip()) >= self.MIN_ABSTRACT_LEN

    def _update_doc_abstract(self, doc_id: str, abstract_text: str) -> bool:
        """把摘要写回 doc 记录的 content，并同步刷新 embedding 与 updated_at。"""
        try:
            model = get_embedding_model()
            vector = model.encode(
                [abstract_text], normalize_embeddings=True, show_progress_bar=False
            )[0].tolist()
        except Exception as e:
            print(f"[AbstractService] {doc_id} 摘要向量化失败: {e}")
            return False

        try:
            self.client.update(
                index=INDEX_NAME,
                id=doc_id,
                body={
                    "doc": {
                        "content": abstract_text,
                        "embedding": vector,
                        "updated_at": datetime.now().isoformat(),
                    }
                },
                refresh=True,
            )
            print(f"[AbstractService] 已更新 {doc_id} 的摘要（doc.content）")
            return True
        except Exception as e:
            print(f"[AbstractService] 更新 {doc_id} 摘要失败: {e}")
            return False

    def generate_for_doc(self, doc_id: str, force: bool = False) -> bool:
        """为单个指南文档（DOC）生成摘要。

        Args:
            doc_id: 指南文档 ID（= ES _id）
            force: 是否强制重新生成（忽略已有摘要）

        Returns:
            bool: 是否成功
        """
        try:
            print(f"[AbstractService] 开始生成摘要: {doc_id}")

            if not force and self._check_abstract_exists(doc_id):
                print(f"[AbstractService] 跳过 {doc_id}（已有摘要）")
                return True

            source_text, meta = self._gather_doc_source(doc_id)
            if not source_text:
                print(f"[AbstractService] {doc_id} 无可用于生成摘要的内容，跳过")
                return False

            if len(source_text) > self.MAX_INPUT_CHARS:
                source_text = source_text[:self.MAX_INPUT_CHARS]
                print(f"[AbstractService] {doc_id} 文本过长，已截断至 {self.MAX_INPUT_CHARS} 字符")

            prompt = self._build_abstract_prompt(
                meta.get("title", ""), meta.get("issuer", ""), source_text
            )
            abstract_text = self._call_llm_with_retry(prompt).strip()
            if not abstract_text:
                raise ValueError("生成的摘要为空")

            print(f"[AbstractService] {doc_id} 生成摘要: {abstract_text[:60]}...")

            if not self._update_doc_abstract(doc_id, abstract_text):
                raise ValueError("更新摘要失败")

            print(f"[AbstractService] {doc_id} 摘要生成成功")
            return True

        except Exception as e:
            print(f"[AbstractService] ❌ {doc_id} 摘要生成失败: {e}")
            return False

    def generate_for_docs(self, doc_ids: List[str], delay: float = 2.0,
                          force: bool = False) -> Dict[str, bool]:
        """批量为多个指南文档生成摘要。

        Args:
            doc_ids: 指南文档 ID 列表
            delay: 每次调用之间的延迟（秒），用于避免 LLM 限流
            force: 是否强制重新生成

        Returns:
            Dict: 每个 doc_id 对应的生成结果（True/False）
        """
        results = {}
        success_count = 0
        failed_count = 0
        failed_docs = []

        print(f"[AbstractService] 开始批量生成 {len(doc_ids)} 个指南的摘要")

        for i, doc_id in enumerate(doc_ids, 1):
            print(f"\n[{i}/{len(doc_ids)}] 处理: {doc_id}")
            try:
                success = self.generate_for_doc(doc_id, force=force)
                results[doc_id] = success
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    failed_docs.append(doc_id)
            except Exception as e:
                print(f"[AbstractService] ❌ {doc_id} 处理异常: {e}")
                results[doc_id] = False
                failed_count += 1
                failed_docs.append(doc_id)

            if i < len(doc_ids):
                time.sleep(delay)

        print(f"\n[AbstractService] 批量生成完成: 成功 {success_count}, 失败 {failed_count}")

        if failed_docs:
            log_path = os.path.join(
                os.path.dirname(__file__),
                f"../logs/abstract_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(failed_docs, f, ensure_ascii=False, indent=2)
            print(f"[AbstractService] 失败日志已保存至: {log_path}")

        return results
