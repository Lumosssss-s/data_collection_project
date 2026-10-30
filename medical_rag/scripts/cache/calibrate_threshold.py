# -*- coding: utf-8 -*-
"""语义缓存阈值校准（离线，0 token）。

做什么：
    把「正样本（同义改写，应命中）」与「负样本（必须判成不同问题）」全部编码，
    扫描余弦阈值与守卫组合，在「负样本零误命中」约束下最大化正样本召回，
    输出可复核的曲线与最终参数。

判定口径（与运行时 utils/semantic_cache.py 完全一致）：
    命中 = cos >= tau 且 槽位守卫无冲突

为什么不是「只调一个阈值」：
    正负样本的余弦区间会重叠（utils/search_cache.py 已记录过 0.9397 vs 0.9257），
    本脚本把「同癌种同线数但意图不同」（intent_negative）单独分组统计，
    用来暴露单阈值/纯守卫方案仍会漏拦的那一类。

用法（模型在容器内 /models/bge-m3，本机不需要装环境）：
    docker compose exec -T backend python /app/scripts/cache/calibrate_threshold.py
产出：
    控制台表格 + data/cache/calib_report.json
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.semantic_cache import extract_slots, normalize_question, slot_conflict  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PAIRS_PATH = os.path.join(_HERE, "..", "..", "data", "cache", "calib_pairs.json")
_REPORT_PATH = os.path.join(_HERE, "..", "..", "data", "cache", "calib_report.json")

# 阈值扫描网格：0.80–0.98，步长 0.01（守卫始终执行，tau 是唯一自由参数）
TAU_GRID = [round(x, 3) for x in np.arange(0.80, 0.981, 0.01)]
# 单阈值基线（当前线上配置）
BASELINE_TAU = 0.92


def _encode(texts):
    import torch
    from core.model_loader import get_embedding_model

    model = get_embedding_model()
    with torch.no_grad():
        vectors = model.encode(texts, batch_size=16, normalize_embeddings=True,
                               show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def _cos(a, b):
    return float(np.dot(a, b))


def main():
    with open(_PAIRS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    positives = data["positive"]
    negatives = data["negative"]

    texts = []
    for a, b in positives:
        texts.extend([a, b])
    for item in negatives:
        texts.extend([item["a"], item["b"]])

    normed = [normalize_question(t) for t in texts]
    print(f"[校准] 编码 {len(normed)} 条样本（bge-m3, 归一化）…")
    vectors = _encode(normed)

    rows = {"positive": [], "negative": []}
    idx = 0
    for a, b in positives:
        va, vb = vectors[idx], vectors[idx + 1]
        idx += 2
        cos = _cos(va, vb)
        conflict = slot_conflict(extract_slots(a), extract_slots(b))
        rows["positive"].append({"a": a, "b": b, "cos": cos, "conflict": conflict})

    for item in negatives:
        va, vb = vectors[idx], vectors[idx + 1]
        idx += 2
        cos = _cos(va, vb)
        conflict = slot_conflict(extract_slots(item["a"]), extract_slots(item["b"]))
        rows["negative"].append({"kind": item["kind"], "a": item["a"], "b": item["b"],
                                 "cos": cos, "conflict": conflict})

    pos_cos = np.array([r["cos"] for r in rows["positive"]])
    neg_cos = np.array([r["cos"] for r in rows["negative"]])

    print("\n=== 正样本（同义改写）余弦 ===")
    print(f"  n={len(pos_cos)} min={pos_cos.min():.4f} p10={np.percentile(pos_cos,10):.4f} "
          f"median={np.median(pos_cos):.4f} max={pos_cos.max():.4f}")
    print("\n=== 负样本余弦（按类型） ===")
    kinds = sorted({r["kind"] for r in rows["negative"]})
    kind_stats = {}
    for kind in kinds:
        vals = np.array([r["cos"] for r in rows["negative"] if r["kind"] == kind])
        guarded = sum(1 for r in rows["negative"] if r["kind"] == kind and r["conflict"])
        kind_stats[kind] = {"n": len(vals), "min": float(vals.min()),
                            "max": float(vals.max()), "median": float(np.median(vals)),
                            "guarded": guarded}
        print(f"  {kind:16} n={len(vals):2} min={vals.min():.4f} median={np.median(vals):.4f} "
              f"max={vals.max():.4f} 守卫可拦={guarded}/{len(vals)}")

    # ---------------- 单阈值基线（当前线上：cos >= 0.92 且守卫无冲突）
    baseline_hits = [r for r in rows["negative"]
                     if r["cos"] >= BASELINE_TAU and not r["conflict"]]
    baseline_recall = float(np.mean([r["cos"] >= BASELINE_TAU and not r["conflict"]
                                     for r in rows["positive"]]))
    print(f"\n=== 基线 tau={BASELINE_TAU}（守卫 + 单阈值） ===")
    print(f"  正样本召回={baseline_recall:.3f}  负样本误命中={len(baseline_hits)}/{len(rows['negative'])}")
    for r in baseline_hits:
        print(f"    误命中[{r['kind']}] cos={r['cos']:.4f}  {r['a']}  ||  {r['b']}")

    # ---------------- 阈值扫描
    # 守卫永远执行（与运行时一致：先阈值、后守卫，守卫不会被高余弦绕过）。
    # 因此只有一个自由参数：余弦阈值 tau。
    def sweep():
        out = []
        for tau in TAU_GRID:
            def hit(r):
                return r["cos"] >= tau and not r["conflict"]

            tpr = float(np.mean([hit(r) for r in rows["positive"]]))
            fp = [r for r in rows["negative"] if hit(r)]
            out.append({"tau": tau, "recall": round(tpr, 4), "false_merges": len(fp),
                        "false_merge_kinds": sorted({r["kind"] for r in fp})})
        return out

    sweep_now = sweep()

    print("\n=== 阈值扫描（守卫始终执行） ===")
    zero_now = [g for g in sweep_now if g["false_merges"] == 0]
    best_now = None
    if zero_now:
        best_now = min(zero_now, key=lambda g: g["tau"])
        print(f"  零误命中最低阈值 tau={best_now['tau']} 召回={best_now['recall']}")
    for g in sweep_now:
        if g["tau"] in (0.83, 0.85, 0.88, 0.90, 0.92, 0.93, 0.95):
            print(f"  tau={g['tau']:.3f} 召回={g['recall']:.3f} 误命中={g['false_merges']} "
                  f"{g['false_merge_kinds']}")

    # ---------------- 分组诊断：意图类负样本的最佳可分离性
    intent_neg = [r for r in rows["negative"] if r["kind"] == "intent_negative"]
    intent_cos = np.array([r["cos"] for r in intent_neg]) if intent_neg else np.array([])
    if intent_cos.size:
        print("\n=== intent_negative（同癌种同线数、不同意图）诊断 ===")
        print(f"  n={intent_cos.size} min={intent_cos.min():.4f} max={intent_cos.max():.4f} "
              f"守卫可拦={sum(1 for r in intent_neg if r['conflict'])}/{len(intent_neg)}")
        overlap = [r for r in intent_neg
                   if r["cos"] >= pos_cos.min() and r["cos"] >= BASELINE_TAU]
        print(f"  余弦 ≥ {BASELINE_TAU} 且无守卫可拦的条数={len(overlap)} "
              f"→ 这部分是「单一/双阈值都拦不住」的错命中来源")

    # ---------------- 探针：真实评测集查询对之间的余弦（只做分布参考，不标注）
    probes = data.get("probe") or []
    probe_cos = []
    if probes:
        pv = _encode([normalize_question(t) for t in probes])
        for i in range(len(probes)):
            for j in range(i + 1, len(probes)):
                probe_cos.append((_cos(pv[i], pv[j]), probes[i], probes[j]))
        vals = np.array([c for c, _, _ in probe_cos])
        print("\n=== 真实查询探针（不同问题之间的余弦，用于看「自然相似度」上限） ===")
        print(f"  pairs={len(vals)} max={vals.max():.4f} median={np.median(vals):.4f} "
              f"p90={np.percentile(vals,90):.4f}")
        top = sorted(probe_cos, reverse=True)[:5]
        for c, a, b in top:
            print(f"    {c:.4f}  {a}  ||  {b}")

    # ---------------- 落盘
    recommended = ({"tau": best_now["tau"], "recall": best_now["recall"],
                    "basis": "现状守卫（含标志物状态槽位），零误命中下的最低阈值"}
                   if zero_now else None)
    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "samples": {"positive": len(rows["positive"]), "negative": len(rows["negative"]),
                    "probe": len(probes)},
        "baseline": {"tau": BASELINE_TAU, "recall": round(baseline_recall, 4),
                     "false_merges": len(baseline_hits),
                     "false_merge_pairs": [{k: r[k] for k in ("kind", "a", "b", "cos")}
                                           for r in baseline_hits]},
        "kind_stats": kind_stats,
        "distribution": {
            "positive": {"min": float(pos_cos.min()), "p10": float(np.percentile(pos_cos, 10)),
                         "median": float(np.median(pos_cos)), "max": float(pos_cos.max())},
            "negative": {"min": float(neg_cos.min()), "median": float(np.median(neg_cos)),
                         "max": float(neg_cos.max())},
            "intent_negative": ({"min": float(intent_cos.min()), "max": float(intent_cos.max())}
                                if intent_cos.size else None),
            "probe_pairs": ({"median": float(np.median([c for c, _, _ in probe_cos])),
                             "max": float(max(c for c, _, _ in probe_cos))}
                            if probe_cos else None)
        },
        "sweep": sweep_now,
        "recommended": recommended,
        "pairs": rows,
    }
    os.makedirs(os.path.dirname(_REPORT_PATH), exist_ok=True)
    with open(_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[校准] 报告已写入 {os.path.abspath(_REPORT_PATH)}")


if __name__ == "__main__":
    main()
