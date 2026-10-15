"""生成 4 张评估图表（医疗 · C1 BE-45 / C3 E-07）
================================================
检索评估: ① 四策略分组柱状图 ② Recall@K 趋势折线图
问答评估: ③ 三指标概览 ④ 忠实度分布堆叠柱状图

输入取自统一结果目录（C3 §6.3 #3）：<results-dir>/enhanced_viz_data.json（run_enhanced_eval）
与 <results-dir>/qa_summary.json（run_qa_eval）；未指定时自动取 results/ 下最新时间戳目录。

运行方式（C3 §6.1，容器内）：
  cd medical_rag
  python eval_data/generate_4charts.py --results-dir eval_data/results/<时间戳>
"""
import argparse
import datetime
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 200

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STRATEGY_LABELS = ['仅BM25', '纯向量', '混合(RRF)', '混合+重排']
STRATEGY_COLORS = ['#8ECFC9', '#FFBE7A', '#FA7F6F', '#82B0D2']
STRATEGY_KEYS = ['bm25', 'vector', 'hybrid', 'hybrid+reranker']


def _resolve_results_dir(arg: str) -> str:
    """未指定时取 results/ 下最新时间戳子目录。"""
    if arg:
        return arg
    root = os.path.join(BASE_DIR, "results")
    if not os.path.isdir(root):
        raise SystemExit(f"[ERROR] 结果根目录不存在: {root}（请先运行评测脚本）")
    subs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    if not subs:
        raise SystemExit(f"[ERROR] {root} 下无结果子目录（请先运行评测脚本）")
    return os.path.join(root, sorted(subs)[-1])


def report_vintage(viz_path: str, qa_path: str) -> None:
    """打印两组输入数据的产出时点，相差超过 1 天时告警。

    图表①②取自 run_enhanced_eval.py 的检索结果，图表③④取自 run_qa_eval.py 的问答
    结果，两份 JSON 各自独立产出。历史上出现过「检索基线已重跑、问答结果仍是旧批次」
    的情况：四张图看起来成套，实则横跨两个时点。这里把它显式暴露出来。
    """
    def fmt(p: str) -> str:
        return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")

    print(f"  数据时点: 检索基线 {fmt(viz_path)} | 问答结果 {fmt(qa_path)}")
    gap_days = abs(os.path.getmtime(viz_path) - os.path.getmtime(qa_path)) / 86400
    if gap_days > 1:
        print(f"  [告警] 两组数据相差 {gap_days:.1f} 天，①② 与 ③④ 并非同一批次；")
        print("         请先重跑 run_enhanced_eval.py 与 run_qa_eval.py，再引用这四张图。")


# ========== ① 四策略分组柱状图 ==========
def chart1_grouped_bar(viz_data, output_dir):
    overall = viz_data["overall"]
    metrics = ['MRR', 'Recall@10', 'Precision@5', 'NDCG@10']
    x = np.arange(len(metrics))
    width = 0.18

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for i, sk in enumerate(STRATEGY_KEYS):
        vals = [overall[sk][m] for m in metrics]
        offset = (i - 1.5) * width
        bars = ax.bar(x + offset, vals, width, label=STRATEGY_LABELS[i],
                      color=STRATEGY_COLORS[i], edgecolor='white', linewidth=0.5)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.012,
                    f'{v:.3f}', ha='center', va='bottom', fontsize=9, fontweight='bold',
                    rotation=0, color='#333333')

    ax.set_xticks(x)
    ax.set_xticklabels(metrics, fontsize=12)
    ax.set_ylabel('得分', fontsize=12)
    ax.set_title('① 四检索策略核心指标对比', fontsize=14, fontweight='bold', pad=15)
    ax.legend(fontsize=10, loc='upper right', borderaxespad=1.2, handlelength=1.5,
              handletextpad=0.8, labelspacing=0.8)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout(pad=1.5)
    fig.savefig(os.path.join(output_dir, '01_grouped_bar.png'), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✓ 01_grouped_bar.png")


# ========== ② Recall@k 趋势折线图 ==========
def chart2_recall_curve(viz_data, output_dir):
    overall = viz_data["overall"]
    k_values = [5, 10, 20]
    markers = ['o', 's', 'D', '^']
    linestyles = ['-', '--', '-', '-']

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for i, sk in enumerate(STRATEGY_KEYS):
        recalls = [overall[sk][f'Recall@{k}'] for k in k_values]
        ax.plot(k_values, recalls, marker=markers[i], linestyle=linestyles[i],
                label=STRATEGY_LABELS[i], color=STRATEGY_COLORS[i],
                linewidth=2.5, markersize=9)
        for k, v in zip(k_values, recalls):
            ax.annotate(f'{v:.3f}', (k, v), textcoords="offset points",
                        xytext=(0, 12), ha='center', fontsize=8.5,
                        fontweight='bold', color='#1a1a1a',
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='white',
                                  edgecolor='#cccccc', alpha=0.9))

    # BM25 与纯向量在 K=10 处对比标注
    bm25_r10 = overall['bm25']['Recall@10']
    vec_r10 = overall['vector']['Recall@10']
    ax.annotate(f'BM25={bm25_r10:.3f}\n向量={vec_r10:.3f}', xy=(10, (bm25_r10 + vec_r10)/2),
                xytext=(8, (bm25_r10 + vec_r10)/2 + 0.04),
                fontsize=8, fontweight='bold', color='#555555',
                arrowprops=dict(arrowstyle='->', color='#888888', lw=1),
                bbox=dict(boxstyle='round,pad=0.25', facecolor='white',
                          edgecolor='#cccccc', alpha=0.95))

    ax.set_xlabel('K', fontsize=12)
    ax.set_ylabel('Recall@K', fontsize=12)
    ax.set_xticks(k_values)
    ax.set_title('② 四策略 Recall@K 趋势折线图', fontsize=14, fontweight='bold', pad=15)
    ax.legend(fontsize=10, loc='lower right', borderaxespad=1.0)
    ax.grid(alpha=0.3)
    fig.tight_layout(pad=1.5)
    fig.savefig(os.path.join(output_dir, '02_recall_curve.png'), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✓ 02_recall_curve.png")


# ========== ③ 三指标概览柱状图 ==========
def chart3_overview(qa_summary, output_dir):
    """问答三核心指标（医疗口径）：检索命中@K / 引用正确率 / 无幻觉率"""
    hit = qa_summary.get('retrieval_hit_at_k', 0) or 0
    cite = qa_summary.get('citation_accuracy')
    nohall = qa_summary.get('no_hallucination_rate')
    cite_v = cite if cite is not None else 0
    nohall_v = nohall if nohall is not None else 0

    labels = ['检索命中@K', '引用正确率', '无幻觉率']
    values = [hit, cite_v, nohall_v]
    raw_labels = [f'{hit:.1%}', f'{cite:.1%}' if cite is not None else 'N/A',
                  f'{nohall:.1%}' if nohall is not None else 'N/A']
    colors = ['#82B0D2', '#8ECFC9', '#FA7F6F']

    fig, ax = plt.subplots(figsize=(7, 5.5))
    bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=0.8, width=0.5)
    for bar, v, r in zip(bars, values, raw_labels):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.025,
                r, ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_ylabel('比例', fontsize=11)
    ax.set_ylim(0, 1.15)
    ax.set_title('③ 问答评估三核心指标概览', fontsize=14, fontweight='bold', pad=15)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout(pad=1.5)
    fig.savefig(os.path.join(output_dir, '03_overview.png'), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✓ 03_overview.png")


# ========== ④ 忠实度分布堆叠柱状图 ==========
def chart4_stacked_distribution(qa_summary, output_dir):
    faith = qa_summary.get('faithfulness_distribution', {})
    faith_vals = [faith.get('1-2分', 0), faith.get('3分', 0), faith.get('4-5分', 0)]

    x = np.arange(1)
    width = 0.45
    colors = ['#7FB3D8', '#5B8DB8', '#2C5F8A']
    labels = ['1-2分 (低)', '3分 (中)', '4-5分 (高)']

    fig, ax = plt.subplots(figsize=(6, 5.5))
    bottom = 0
    for i in range(3):
        ax.bar(x[0], faith_vals[i], width, bottom=bottom, color=colors[i],
               edgecolor='white', linewidth=0.5, label=labels[i])
        if faith_vals[i] > 0:
            pct = faith_vals[i] / sum(faith_vals) * 100
            ax.text(x[0], bottom + faith_vals[i]/2, f'{faith_vals[i]}条\n({pct:.0f}%)',
                    ha='center', va='center', fontsize=9, fontweight='bold', color='white')
        else:
            ax.text(x[0], bottom + 2, '0 条\n(0%)', ha='center', va='center',
                    fontsize=8, color='#999999', fontstyle='italic')
        bottom += faith_vals[i]

    ax.set_xticks(x)
    ax.set_xticklabels(['Faithfulness\n(忠实度)'], fontsize=11)
    ax.set_ylabel('查询数量', fontsize=12)
    ax.set_title('④ 问答忠实度分布堆叠柱状图', fontsize=14, fontweight='bold', pad=15)
    ax.legend(fontsize=9, loc='upper right', borderaxespad=1.0)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout(pad=1.5)
    fig.savefig(os.path.join(output_dir, '04_stacked_distribution.png'), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✓ 04_stacked_distribution.png")


def main():
    parser = argparse.ArgumentParser(description="生成医疗评估图表（4 张）")
    parser.add_argument("--results-dir", default=None,
                        help="评测结果目录（含 enhanced_viz_data.json + qa_summary.json）；"
                             "缺省取 eval_data/results/ 下最新时间戳目录")
    parser.add_argument("--out-dir", default=None,
                        help="图表输出目录（缺省 = <results-dir>/charts）")
    args = parser.parse_args()

    results_dir = _resolve_results_dir(args.results_dir)
    viz_path = os.path.join(results_dir, "enhanced_viz_data.json")
    qa_path = os.path.join(results_dir, "qa_summary.json")
    output_dir = args.out_dir or os.path.join(results_dir, "charts")
    os.makedirs(output_dir, exist_ok=True)

    for p in (viz_path, qa_path):
        if not os.path.exists(p):
            raise SystemExit(f"[ERROR] 缺少输入文件: {p}")

    with open(viz_path, "r", encoding="utf-8") as f:
        viz_data = json.load(f)
    with open(qa_path, "r", encoding="utf-8") as f:
        qa_summary = json.load(f)

    print(f"\n  {'='*45}")
    print(f"  结果目录: {results_dir}")
    print(f"  图表输出: {output_dir}")
    print(f"  {'='*45}\n")

    report_vintage(viz_path, qa_path)

    print("  [检索评估]")
    chart1_grouped_bar(viz_data, output_dir)
    chart2_recall_curve(viz_data, output_dir)

    print("\n  [问答评估]")
    chart3_overview(qa_summary, output_dir)
    chart4_stacked_distribution(qa_summary, output_dir)

    n = len([f for f in os.listdir(output_dir) if f.endswith('.png')])
    print(f"\n  {'='*45}")
    print(f"  完成! 共生成 {n} 张图表")
    print(f"  {'='*45}")


if __name__ == "__main__":
    main()
