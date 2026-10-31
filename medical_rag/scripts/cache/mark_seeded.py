# -*- coding: utf-8 -*-
"""一次性存量迁移：给 qa 预热条目补 pinned/seeded 标记，并把 TTL 刷新到 30 天。

背景：30 条 qa 热问是旧代码写入的，meta 里没有 pinned/seeded，TTL 仍在按 7 天倒计时。
不迁移的话，它们既会被当成长尾条目参与淘汰，也会在第 7 天准时过期。

可重复执行：已是 pinned 的条目只刷新 TTL，不重复计数。
只处理 qa；search 的 7 条是真实请求写出的条目，不是人工预热，保持原样。
用法（容器内，工作目录 /app）：python scripts/cache/mark_seeded.py [--dry-run]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis  # noqa: E402

from core.config import settings  # noqa: E402
from utils.semantic_cache import KEY_PREFIX, SemanticCache  # noqa: E402

KIND = "qa"

# 种子清单的癌种标记用确定性关键词映射得出，推断不到就留 null，不做任何猜测
_CANCER_RULES = (
    (("结直肠", "结肠", "直肠", "大肠"), "colorectal"),
    (("肺", "nsclc", "sclc"), "lung"),
)


def _infer_cancer(question: str):
    lowered = question.lower()
    for keywords, code in _CANCER_RULES:
        if any(k in lowered for k in keywords):
            return code
    return None


def _dump_seed(client, path: str) -> None:
    """把 Redis 现存的 qa 条目原样导出为种子清单（question 不做任何改写）。

    导出后 prewarm_faq.py 用同一份问题重跑即可命中同样的 id，避免重新生成时
    问法漂移、和已入库的 30 条对不上。
    """
    ids = [m.decode() if isinstance(m, bytes) else str(m)
           for m in client.smembers(f"{KEY_PREFIX}:idx:{KIND}")]
    items = []
    for entry_id in sorted(ids):
        key = f"{KEY_PREFIX}:entry:{KIND}:{entry_id}"
        raw_q = client.hget(key, "q")
        raw_meta = client.hget(key, "meta")
        raw_fk = client.hget(key, "fk")
        question = raw_q.decode("utf-8") if isinstance(raw_q, bytes) else (raw_q or "")
        fk = raw_fk.decode("utf-8") if isinstance(raw_fk, bytes) else (raw_fk or "")
        meta = {}
        if raw_meta:
            try:
                meta = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else raw_meta)
            except Exception:
                meta = {}
        items.append({
            "id": entry_id,
            "question": question,
            "cancer_type": _infer_cancer(question),
            "top_k": int(meta.get("top_k", 5)),
            "fk": fk,
        })
    payload = {
        "source": f"redis {KEY_PREFIX}:idx:{KIND}",
        "count": len(items),
        "items": items,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    nulls = sum(1 for i in items if i["cancer_type"] is None)
    print(f"已导出 {len(items)} 条到 {path}（cancer_type 推断不到为 null：{nulls} 条）")


def main() -> int:
    if "--dump-seed" in sys.argv:
        cache = SemanticCache()
        client = cache._get_client()
        if client is None:
            print("Redis 不可用，退出")
            return 1
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data", "cache", "faq_seed.json")
        _dump_seed(client, out)
        return 0

    dry = "--dry-run" in sys.argv
    cache = SemanticCache()
    client = cache._get_client()
    if client is None:
        print("Redis 不可用，退出")
        return 1

    idx_key = f"{KEY_PREFIX}:idx:{KIND}"
    pinned_key = f"{KEY_PREFIX}:pinned:{KIND}"
    ttl = int(settings.semantic_cache_seeded_ttl)
    ids = [m.decode() if isinstance(m, bytes) else str(m) for m in client.smembers(idx_key)]

    marked = already = 0
    for entry_id in sorted(ids):
        key = f"{KEY_PREFIX}:entry:{KIND}:{entry_id}"
        raw_meta = client.hget(key, "meta")
        meta = {}
        if raw_meta:
            try:
                meta = json.loads(raw_meta.decode("utf-8") if isinstance(raw_meta, bytes) else raw_meta)
            except Exception:
                meta = {}
        was_pinned = bool(meta.get("pinned"))
        meta["seeded"] = True
        meta["pinned"] = True
        raw_q = client.hget(key, "q")
        question = raw_q.decode("utf-8") if isinstance(raw_q, bytes) else (raw_q or "")
        if dry:
            print(f"[dry-run] {entry_id} {question[:24]}")
            continue
        pipe = client.pipeline()
        pipe.hset(key, "meta", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        pipe.expire(key, ttl)
        pipe.sadd(pinned_key, entry_id)
        pipe.execute()
        if was_pinned:
            already += 1
        else:
            marked += 1
        print(f"{entry_id} ttl={client.ttl(key)}s pinned={meta['pinned']} seeded={meta['seeded']} {question[:24]}")

    if dry:
        print(f"\n[dry-run] 共 {len(ids)} 条待处理，TTL 目标 {ttl}s（{ttl // 86400} 天）")
        return 0

    print(f"\n已标记（新增 pinned/seeded）{marked} 条；本就 pinned、仅刷新 TTL {already} 条；"
          f"合计 {len(ids)} 条，目标 TTL {ttl}s（{ttl // 86400} 天）")
    sample = sorted(ids)[:3]
    print("TTL 抽样：" + "，".join(f"{i}={client.ttl(f'{KEY_PREFIX}:entry:{KIND}:' + i)}s" for i in sample))
    print(f"pinned 集合基数={client.scard(pinned_key)}，qa 条目数={client.zcard(f'{KEY_PREFIX}:born:{KIND}')}")
    print(f"search 未处理（{client.zcard(f'{KEY_PREFIX}:born:search')} 条为真实请求写入，保留原 TTL）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
