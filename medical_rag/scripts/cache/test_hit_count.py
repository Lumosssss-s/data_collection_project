# -*- coding: utf-8 -*-
"""命中计数验证（零 token，不调 LLM）。

验证 store() 后两条路径都会累加 sc:v1:hot：
  L0 精确命中（原样问题）→ 应 +1
  L1 语义命中（同义改写）→ 应 +1
隔离：Redis 15 号库，跑完 flushdb，不影响生产库。
用法（容器内，工作目录 /app）：python scripts/cache/test_hit_count.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis  # noqa: E402

from utils.semantic_cache import KEY_PREFIX, _HOT_KEY, SemanticCache  # noqa: E402

TEST_URL = "redis://redis:6379/15"
QUESTION = "肺癌一线治疗有哪些方案"
PARAPHRASE = "肺癌一线治疗方案都有哪些"


def main() -> int:
    client = redis.Redis.from_url(TEST_URL, socket_timeout=3, decode_responses=False)
    client.ping()
    client.flushdb()

    cache = SemanticCache()
    cache._client = client

    payload = {"answer": "测试答案", "sources": [], "retrieved_count": 1}
    ok_store = cache.store("qa", QUESTION, payload, {"top_k": 5}, meta={"test": True})
    print(f"store={ok_store}")

    ids = [m.decode() for m in client.smembers(f"{KEY_PREFIX}:idx:qa")]
    print(f"idx={ids}")
    assert len(ids) == 1, "测试条目必须只有一条"
    entry_id = ids[0]

    def hot() -> str:
        raw = client.zscore(_HOT_KEY, entry_id)
        return "None(不计)" if raw is None else f"{float(raw):.0f}"

    print(f"\n写入后 hot = {hot()}（期望 None/0）")

    got, sim = cache.lookup("qa", QUESTION, {"top_k": 5})
    print(f"\nL0 原样查询：命中={got is not None} similarity={sim} → hot = {hot()}（期望 1）")
    l0_ok = got is not None and hot() == "1"

    got2, sim2 = cache.lookup("qa", PARAPHRASE, {"top_k": 5})
    print(f"L1 同义改写：命中={got2 is not None} similarity={sim2:.4f} → hot = {hot()}（期望 2）")
    l1_ok = got2 is not None and hot() == "2"

    print(f"\n[{'PASS' if l0_ok else 'FAIL'}] L0 精确命中累加热度")
    print(f"[{'PASS' if l1_ok else 'FAIL'}] L1 语义命中累加热度")

    client.flushdb()
    print("\n已清空 15 号测试库")
    return 0 if (l0_ok and l1_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
