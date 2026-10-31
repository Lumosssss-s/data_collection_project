# -*- coding: utf-8 -*-
"""FAQ 预热入口（写答案进语义缓存，标记 seeded + pinned）。

⚠ 成本：单条约 1 万 tokens（12 条依据上下文 + 约 2000 字答案），30 条约 30 万 tokens。
   本脚本默认是 dry-run，不会调用任何模型。**执行前务必先跑一次 dry-run**，
   确认「将处理 N 条 / 已存在跳过 M 条」符合预期，再显式加 --yes 真正执行。

用法（容器内，工作目录 /app）：
    python scripts/cache/prewarm_faq.py                       # 默认 dry-run，只打印
    python scripts/cache/prewarm_faq.py --limit 5             # 只预览前 5 条
    python scripts/cache/prewarm_faq.py --only-missing        # 跳过 Redis 里已有同 id 条目
    python scripts/cache/prewarm_faq.py --only-missing --yes  # 真正执行（产生 LLM 调用）

种子来源：data/cache/faq_seed.json，由 `mark_seeded.py --dump-seed` 从 Redis 现存条目
原样导出（问法不改写），因此重跑会命中同一批 id，不会与已入库条目错位。

预检：进入计划与生成之前，脚本会先在本进程做一次 bge-m3 编码自检（0 token）。
后端容器仍在运行时，新进程再加载一份 2.27GB 模型通常会失败（实测 `Unable to load
weights`）；失败即打印异常类型并退出码 2，不会打印计划、不会调用 LLM。
正确姿势：先 `docker compose stop backend`，再
`docker compose run --rm backend python scripts/cache/prewarm_faq.py --limit 1 --yes`。

写入口径与 services/qa_service.py 完全一致：payload = {answer, sources, retrieved_count,
cancer_types}，缓存作用域 = {top_k}，另加 meta {seeded: true, pinned: true} ——
seeded 让 TTL 走 30 天，pinned 让 _trim 永不淘汰它们。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.config import settings  # noqa: E402
from utils.semantic_cache import (KEY_PREFIX, build_filter_key,  # noqa: E402
                                  get_semantic_cache, normalize_question)

SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "cache", "faq_seed.json")
KIND = "qa"
# 单条答案的 token 估算，仅用于执行前给出总成本提示，不是精确计数
TOKENS_PER_ITEM = 10000


def _entry_id(question: str, top_k: int) -> str:
    """与 SemanticCache.store 相同的 id 计算，用于判断条目是否已存在。"""
    import hashlib
    fk = build_filter_key({"top_k": top_k})
    norm = normalize_question(question)
    return hashlib.sha1(f"{KIND}\x00{fk}\x00{norm}".encode("utf-8")).hexdigest()[:16]


def _preflight() -> bool:
    """编码自检：进入生成流程前，先确认 bge-m3 能在**本进程**加载并编码。

    背景：预热脚本是新进程，会再加载一份 2.27GB 的 bge-m3。若后端容器仍在运行
    （已占一份模型），宿主机可用内存不足时加载会失败，而 transformers 会把真实
    异常统一包装成「Unable to load weights ...」。
    实测已发生过一次：生成成功（已是约 1 万 tokens），到 store 阶段才因编码失败
    写不进去，答案被丢弃。故预检放在 --yes 生效之前，dry-run 也执行。
    这里刻意直接调用 _embed 内部同一个加载器（get_embedding_model），
    以便打印真实异常类型，而不是只拿到 SemanticCache 吞掉异常后的 None。
    """
    try:
        import torch
        from core.model_loader import get_embedding_model

        with torch.no_grad():
            encoded = get_embedding_model().encode(
                ["预检"], batch_size=1, normalize_embeddings=True, show_progress_bar=False)
        print(f"[preflight] 编码自检通过（维度 {len(encoded[0])}），可以继续")
        return True
    except Exception as e:
        print(f"[preflight] 编码自检失败：{type(e).__name__}: {e}")
        print("[preflight] 已退出：未生成任何答案，未产生任何 LLM 调用。")
        print("[preflight] 若后端容器仍在运行，请先 docker compose stop backend，"
              "再用 docker compose run --rm backend python scripts/cache/prewarm_faq.py ...")
        return False


def _plan(items, only_missing: bool):
    cache = get_semantic_cache()
    client = cache._get_client()
    if client is None:
        print("Redis 不可用，退出（预热必须写进 Redis）")
        return None, None, None
    todo, skipped, mismatch = [], [], []
    for item in items:
        question = item["question"]
        top_k = int(item.get("top_k", 5))
        entry_id = _entry_id(question, top_k)
        if item.get("id") and entry_id != item["id"]:
            # 种子里的 id 是导出时 Redis 里的真实 id；对不上说明问题文本被改过或作用域变了
            mismatch.append((item["id"], entry_id, question))
            continue
        exists = bool(client.exists(f"{KEY_PREFIX}:entry:{KIND}:{entry_id}"))
        if exists and only_missing:
            skipped.append((entry_id, question))
        else:
            todo.append({"id": entry_id, "question": question, "top_k": top_k, "exists": exists})
    return todo, skipped, mismatch


def _generate(question: str, top_k: int) -> dict:
    """跑一次真实问答（含检索 + 精排 + LLM），收集重放所需的四项内容。"""
    from services.qa_service import QAService
    service = QAService()
    collected = {"answer": "", "sources": [], "retrieved_count": 0, "cancer_types": [], "failed": False}
    for frame in service.ask_stream(question, top_k=top_k):
        ftype = frame.get("type")
        if ftype == "sources":
            collected["sources"] = frame.get("sources") or []
            collected["retrieved_count"] = frame.get("retrieved_count") or 0
            collected["cancer_types"] = frame.get("cancer_types") or []
        elif ftype == "content":
            collected["answer"] += str(frame.get("data") or "")
        elif ftype == "error":
            collected["failed"] = True
    if collected["failed"] or not collected["answer"] or not collected["retrieved_count"]:
        collected["ok"] = False
    else:
        collected["ok"] = True
    return collected


def main() -> int:
    yes = "--yes" in sys.argv
    only_missing = "--only-missing" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    # 预检先于「待处理 N 条」的计划输出，也先于任何生成：失败即非零退出（2），
    # 既不会打印诱导加 --yes 的计划，也绝不会进入 LLM 生成。
    if not _preflight():
        return 2

    with open(SEED_PATH, "r", encoding="utf-8") as f:
        seed = json.load(f)
    items = seed.get("items") or []
    if limit:
        items = items[:limit]

    todo, skipped, mismatch = _plan(items, only_missing)
    if todo is None:
        return 1

    mode = "执行" if yes else "dry-run"
    print(f"[{mode}] 种子 {len(items)} 条：待处理 {len(todo)} 条，已存在跳过 {len(skipped)} 条，id 不匹配 {len(mismatch)} 条")
    for entry_id, question in skipped:
        print(f"  跳过（已存在）{entry_id} {question}")
    for expect, actual, question in mismatch:
        print(f"  [WARN] id 不匹配 种子={expect} 计算={actual} {question}（已跳过，不覆盖）")
    for item in todo:
        flag = "覆盖已有条目" if item["exists"] else "新增"
        print(f"  {item['id']} top_k={item['top_k']} [{flag}] {item['question']}")

    if not yes:
        est = len(todo) * TOKENS_PER_ITEM
        print(f"\n[dry-run] 未调用任何模型。真正执行约 {len(todo)} 条 × {TOKENS_PER_ITEM} tokens ≈ {est} tokens。")
        print("确认无误后加 --yes 执行（建议同时加 --only-missing 避免重烧）。")
        return 0

    if not settings.semantic_cache_enabled:
        print("semantic_cache_enabled=false，预热写入无意义，退出")
        return 1

    cache = get_semantic_cache()
    ok = fail = 0
    for item in todo:
        result = _generate(item["question"], item["top_k"])
        if not result["ok"]:
            fail += 1
            print(f"  [FAIL] 生成不完整（failed/空答案/无依据），不入缓存：{item['question']}")
            continue
        stored = cache.store(
            KIND, item["question"],
            {"answer": result["answer"], "sources": result["sources"],
             "retrieved_count": result["retrieved_count"],
             "cancer_types": result["cancer_types"]},
            {"top_k": item["top_k"]},
            meta={"top_k": item["top_k"], "seeded": True, "pinned": True},
        )
        if stored:
            ok += 1
            print(f"  [OK] {item['id']} 已写入（seeded+pinned，TTL {settings.semantic_cache_seeded_ttl}s）")
        else:
            fail += 1
            print(f"  [FAIL] store 返回 False：{item['question']}")
    print(f"\n完成：成功 {ok} 条，失败 {fail} 条")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
