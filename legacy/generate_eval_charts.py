"""E-07：评测图表生成（零 token，离线读取已有结果 JSON）。

产出 4 张图，全部基于真实评测产物，不做任何数值改写：
  ① 四策略指标对比（E-04：BM25 / 向量 / 混合 RRF / 混合+精排）
  ② 精排增益（E-03：混合 → 混合+精排 的四项指标增量）
  ③ 拒答拦截分层（E-02-lite guard 模式：按类别统计生成前拦截情况）
  ④ REC 粒度对照（1,025 → 1,513 条时的记录量与 E-01 指标变化）

用法（宿主机或容器内均可，需中文字体）：
  python eval_data/generate_eval_charts.py \
      --four eval_data/results/20261025_144553/four_strategies_summary.json \
      --e01-before eval_data/results/20261025_111029/eval_pipeline_summary.json \
      --e01-after  eval_data/results/20261025_141148/eval_pipeline_summary.json \
      --refusal   eval_data/results/refusal_eval_guard.json \
      --out "e:/兴智杯/评测图表"
"""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

STRATEGY_KEYS = ["仅BM25", "仅向量检索", "混合检索(BM25+向量+RRF)", "混合检索+重排序"]
STRATEGY_LABELS = ["仅 BM25", "仅向量", "混合 RRF", "混合 + 精排"]
COLORS = ["#9DC3E6", "#FFC000", "#ED7D31", "#4472C4"]
BEHAVIOR_ZH = {
    "refuse_out_of_scope": "越界/非肿瘤",
    "refuse_individualized_dose": "个体化剂量",
    "refuse_prognosis": "预后预测",
    "refuse_unsafe": "危险诱导",
}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _annotate(ax, bars, fmt="{:.3f}"):
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h + 0.012, fmt.format(h),
                ha="center", va="bottom", fontsize=8.5, color="#333333")


def chart1_four_strategies(summary, out_dir):
    overall = summary["overall_four"]
    metrics = ["MRR", "Recall@5", "Precision@5", "NDCG@10"]
    x = np.arange(len(metrics))
    width = 0.2

    fig, ax = plt.subplots(figsize=(10, 5.4))
    for i, key in enumerate(STRATEGY_KEYS):
        vals = [overall[key][m] for m in metrics]
        bars = ax.bar(x + (i - 1.5) * width, vals, width, label=STRATEGY_LABELS[i],
                      color=COLORS[i], edgecolor="white", linewidth=0.6)
        _annotate(ax, bars)
    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=11)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("得分", fontsize=11)
    ax.set_title("检索策略消融对比（C1 评测集 115 题，文档级）", fontsize=13, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=4, frameon=False)
    fig.tight_layout()
    p = os.path.join(out_dir, "E04_四策略对比.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return p


def chart2_reranker_gain(summary, out_dir):
    base = summary["overall_four"]["混合检索(BM25+向量+RRF)"]
    tuned = summary["overall_four"]["混合检索+重排序"]
    metrics = [("MRR", "MRR"), ("Recall@1", "Recall@1"),
               ("R-Precision", "R-Precision"), ("NDCG@10", "NDCG@10")]
    labels = [m[1] for m in metrics]
    deltas = [tuned[k] - base[k] for k, _ in metrics]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = np.arange(len(labels))
    bars = ax.barh(y, deltas, color="#4472C4", height=0.5)
    for b, d, (k, _) in zip(bars, deltas, metrics):
        ax.text(b.get_width() + 0.004, b.get_y() + b.get_height() / 2,
                f"+{d:.4f}  ({base[k]:.4f} → {tuned[k]:.4f})",
                va="center", fontsize=9, color="#333333")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=11)
    ax.invert_yaxis()
    ax.axvline(0, color="#888888", linewidth=0.8)
    ax.set_xlim(0, max(deltas) * 1.9)
    ax.set_xlabel("精排带来的增量", fontsize=11)
    ax.set_title("精排增益（混合 RRF → 混合 + 精排）", fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    fig.tight_layout()
    p = os.path.join(out_dir, "E03_精排增益.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return p


def chart3_refusal(refusal, out_dir):
    rows = refusal["rows"]
    behaviors = list(BEHAVIOR_ZH)
    passed = {b: 0 for b in behaviors}
    failed = {b: 0 for b in behaviors}
    for r in rows:
        b = r["behavior"]
        if r["pass"]:
            passed[b] += 1
        else:
            failed[b] += 1

    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(behaviors))
    p_bars = ax.bar(x, [passed[b] for b in behaviors], 0.5,
                    label="生成前已拦截", color="#4472C4")
    f_bars = ax.bar(x, [failed[b] for b in behaviors], 0.5,
                    bottom=[passed[b] for b in behaviors],
                    label="转入生成阶段", color="#D9D9D9")
    for i, b in enumerate(behaviors):
        total = passed[b] + failed[b]
        ax.text(i, total + 0.15, f"{passed[b]}/{total}", ha="center",
                fontsize=10, fontweight="bold", color="#333333")
    ax.set_xticks(x)
    ax.set_xticklabels([BEHAVIOR_ZH[b] for b in behaviors], fontsize=11)
    ax.set_ylabel("题目数", fontsize=11)
    rate = refusal["pass_rate"]
    ax.set_title(f"拒答防护：生成前拦截率 {rate:.0%}（n={refusal['total']}）",
                 fontsize=13, fontweight="bold")
    # 按最大类别题数收窄纵轴，避免小类别的柱子被压成一条线（总题数仍在标题里标注）
    ax.set_ylim(0, max(passed[b] + failed[b] for b in behaviors) + 2)
    ax.legend(frameon=False, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    p = os.path.join(out_dir, "E02_拒答拦截.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return p


def chart4_rec_granularity(before, after, out_dir):
    metrics = ["MRR", "Recall@5", "NDCG@10"]
    vals_b = [before[m] for m in metrics]
    vals_a = [after[m] for m in metrics]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6),
                             gridspec_kw={"width_ratios": [1, 2.2]})
    axes[0].bar(["1,025 条", "1,513 条"], [1025, 1513], color=["#9DC3E6", "#4472C4"], width=0.55)
    for i, v in enumerate([1025, 1513]):
        axes[0].text(i, v + 20, str(v), ha="center", fontsize=10, fontweight="bold")
    axes[0].set_title("REC 检索单元数量", fontsize=12, fontweight="bold")
    axes[0].set_ylim(0, 1750)
    axes[0].grid(axis="y", linestyle="--", alpha=0.35)

    x = np.arange(len(metrics))
    width = 0.34
    b1 = axes[1].bar(x - width / 2, vals_b, width, label="1,025 条", color="#9DC3E6")
    b2 = axes[1].bar(x + width / 2, vals_a, width, label="1,513 条", color="#4472C4")
    for bars in (b1, b2):
        for bar in bars:
            axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.006,
                         f"{bar.get_height():.4f}", ha="center", va="bottom", fontsize=8.5)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(metrics, fontsize=11)
    axes[1].set_ylim(0.85, 1.02)
    axes[1].set_title("E-01 检索指标变化", fontsize=12, fontweight="bold")
    axes[1].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    axes[1].grid(axis="y", linestyle="--", alpha=0.35)

    fig.suptitle("REC 粒度细化：召回上升、排序略降", fontsize=13, fontweight="bold")
    fig.tight_layout()
    p = os.path.join(out_dir, "E01_REC粒度对照.png")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return p


def main():
    ap = argparse.ArgumentParser(description="E-07 评测图表生成")
    ap.add_argument("--four", required=True, help="E-04 四策略汇总 JSON")
    ap.add_argument("--e01-before", required=True, help="REC 细化前的 E-01 汇总 JSON")
    ap.add_argument("--e01-after", required=True, help="REC 细化后的 E-01 汇总 JSON")
    ap.add_argument("--refusal", required=True, help="拒答评测结果 JSON（guard 模式）")
    ap.add_argument("--out", default=os.path.join("e:/兴智杯/评测图表"), help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    four = _load(args.four)
    before = _load(args.e01_before)
    after = _load(args.e01_after)
    refusal = _load(args.refusal)

    paths = [
        chart1_four_strategies(four, args.out),
        chart2_reranker_gain(four, args.out),
        chart3_refusal(refusal, args.out),
        chart4_rec_granularity(before, after, args.out),
    ]
    for p in paths:
        print(f"  ✓ {p}")
    print(f"  共 {len(paths)} 张图 → {args.out}")


if __name__ == "__main__":
    main()
