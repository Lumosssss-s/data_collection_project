# -*- coding: utf-8 -*-
"""淘汰策略验证（零 token，不调模型）。

隔离说明：直接连 Redis 15 号库构造条目，绕过生产库 0；跑完 flushdb 并恢复容量配置。
覆盖四个断言：
  1) 容量 2、写入 A(早, 命中3) / B(晚, 命中0)，再写 C 触发淘汰 → 被淘汰的是 B，A 保留；
  2) 两条命中次数都为 0 时，按写入时间淘汰更早的那条（FIFO 兜底）；
  3) 容量 2、3 条非 pinned + 2 条 pinned（pinned 写入更早，纯 FIFO 会先删它们）→ 只淘汰非 pinned；
  4) 全部 pinned 时触发淘汰 → 只打 WARNING、跳过淘汰、不删 pinned、不抛异常。
用法（容器内，工作目录 /app）：python scripts/cache/test_trim_eviction.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis  # noqa: E402

from core.config import settings  # noqa: E402
from utils.semantic_cache import KEY_PREFIX, _HOT_KEY, SemanticCache  # noqa: E402

TEST_URL = "redis://redis:6379/15"
KIND = "qa"


def _client() -> "redis.Redis":
    client = redis.Redis.from_url(TEST_URL, socket_timeout=2, decode_responses=False)
    client.ping()
    return client


def _add(client, entry_id: str, born: float, hits: int = 0, pinned: bool = False) -> None:
    """按 store() 的键格式写一条条目；hits>0 写热度表，pinned 写 pinned 集合。"""
    pipe = client.pipeline()
    pipe.hset(f"{KEY_PREFIX}:entry:{KIND}:{entry_id}", mapping={
        "q": entry_id.encode(), "fk": b"", "slots": b"{}",
        "payload": b"{}", "ts": b"0", "meta": b"{}",
    })
    pipe.sadd(f"{KEY_PREFIX}:idx:{KIND}", entry_id)
    pipe.zadd(f"{KEY_PREFIX}:born:{KIND}", {entry_id: born})
    if pinned:
        pipe.sadd(f"{KEY_PREFIX}:pinned:{KIND}", entry_id)
    pipe.incr(f"{KEY_PREFIX}:idxver:{KIND}")
    pipe.execute()
    if hits:
        client.zincrby(_HOT_KEY, hits, entry_id)


def _alive(client, entry_id: str) -> bool:
    return bool(client.exists(f"{KEY_PREFIX}:entry:{KIND}:{entry_id}"))


def _members(client) -> list:
    return [m.decode() for m in client.zrange(f"{KEY_PREFIX}:born:{KIND}", 0, -1)]


def _summary(client) -> str:
    hot = {m.decode(): float(s) for m, s in client.zrange(_HOT_KEY, 0, -1, withscores=True)}
    return f"存活={sorted(_members(client))} 热度={hot}"


def main() -> int:
    client = _client()
    client.flushdb()
    cache = SemanticCache()
    cache._client = client
    old_limit = settings.semantic_cache_max_entries
    failed = 0
    try:
        settings.semantic_cache_max_entries = 2
        print(f"容量上限临时设为 {settings.semantic_cache_max_entries}")

        print("\n-- 场景 1：写入 A(早,3 次命中)、B(晚,0 次命中) --")
        _add(client, "A", born=100, hits=3)
        _add(client, "B", born=200, hits=0)
        cache._trim(KIND, client)
        print(f"未超限不淘汰：{_summary(client)}")
        ok = _alive(client, "A") and _alive(client, "B")
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] A、B 均保留")

        print("\n-- 场景 1：再写 C(较新,0 次命中)，触发淘汰 --")
        _add(client, "C", born=300, hits=0)
        cache._trim(KIND, client)
        print(f"淘汰后：{_summary(client)}")
        b_gone = not _alive(client, "B")
        a_kept = _alive(client, "A") and _alive(client, "C")
        failed += 0 if (b_gone and a_kept) else 1
        print(f"[{'PASS' if b_gone else 'FAIL'}] 低命中且较新的 B 被淘汰")
        print(f"[{'PASS' if a_kept else 'FAIL'}] 高命中的 A 与最新的 C 被保留")
        hot_clean = client.zcard(_HOT_KEY) == 1
        failed += 0 if hot_clean else 1
        print(f"[{'PASS' if hot_clean else 'FAIL'}] 热度表清理同步（仅剩 A，zcard={client.zcard(_HOT_KEY)}）")

        print("\n-- 场景 2：同为零命中，按写入时间淘汰更早的 --")
        client.flushdb()
        settings.semantic_cache_max_entries = 1
        _add(client, "P", born=10, hits=0)
        _add(client, "Q", born=20, hits=0)
        cache._trim(KIND, client)
        print(f"淘汰后：{_summary(client)}")
        p_gone = not _alive(client, "P") and _alive(client, "Q")
        failed += 0 if p_gone else 1
        print(f"[{'PASS' if p_gone else 'FAIL'}] 零命中时较早写入的 P 被淘汰（FIFO 兜底）")

        print("\n-- 场景 3：容量 2，3 条非 pinned + 2 条 pinned（pinned 写入更早） --")
        client.flushdb()
        settings.semantic_cache_max_entries = 2
        _add(client, "P1", born=1, pinned=True)
        _add(client, "P2", born=2, pinned=True)
        _add(client, "N1", born=10)
        _add(client, "N2", born=20)
        _add(client, "N3", born=30)
        cache._trim(KIND, client)
        print(f"淘汰后：{_summary(client)} pinned={sorted(m.decode() for m in client.smembers(f'{KEY_PREFIX}:pinned:{KIND}'))}")
        nonpinned_gone = not any(_alive(client, i) for i in ("N1", "N2", "N3"))
        pinned_kept = all(_alive(client, i) for i in ("P1", "P2"))
        failed += 0 if nonpinned_gone else 1
        print(f"[{'PASS' if nonpinned_gone else 'FAIL'}] 3 条非 pinned 全部被淘汰")
        failed += 0 if pinned_kept else 1
        print(f"[{'PASS' if pinned_kept else 'FAIL'}] 2 条 pinned 全留（它们是写入最早的一批）")

        print("\n-- 场景 4：全部 pinned 时触发淘汰（边界） --")
        client.flushdb()
        settings.semantic_cache_max_entries = 1
        records = []

        class _Grab(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Grab()
        log = logging.getLogger("utils.semantic_cache")
        log.addHandler(handler)
        old_level = log.level
        log.setLevel(logging.WARNING)
        try:
            _add(client, "Q1", born=5, pinned=True)
            _add(client, "Q2", born=6, pinned=True)
            crashed = False
            try:
                cache._trim(KIND, client)
            except Exception as exc:  # noqa: BLE001 边界用例：不允许抛异常
                crashed = True
                print(f"[FAIL] _trim 抛出异常：{exc}")
            failed += 0 if not crashed else 1
            both = _alive(client, "Q1") and _alive(client, "Q2")
            failed += 0 if both else 1
            print(f"[{'PASS' if both else 'FAIL'}] pinned 未被删除（存活={sorted(_members(client))}，超限仍保留）")
            warned = any("跳过淘汰" in r.getMessage() for r in records)
            failed += 0 if warned else 1
            print(f"[{'PASS' if warned else 'FAIL'}] 打出 WARNING 跳过淘汰："
                  f"{[r.getMessage() for r in records]}")
        finally:
            log.removeHandler(handler)
            log.setLevel(old_level)
    finally:
        settings.semantic_cache_max_entries = old_limit
        client.flushdb()
        print(f"\n已恢复容量上限={old_limit} 并清空 15 号测试库；失败 {failed} 条")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
