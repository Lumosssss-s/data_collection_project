"""评测图（图 9–13）生成器：沿用 E01–E04 的 matplotlib 视觉骨架，1600 px / 150 dpi。
风格参数取自 legacy/generate_eval_charts.py：白底、仅横向虚线网格、柱顶标值、
图例置下方无边框、标题加粗居中、SimHei/Microsoft YaHei。
数据全部只读仓内 JSON，不改写任何数值；分位数用 floor(n*q)。
用法：python build_eval_figures.py
"""
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FOUR = os.path.join(HERE, r'..\..\..\medical_rag\eval_data\results\20261025_144553\four_strategies_summary.json')
QA40 = os.path.join(HERE, r'..\..\..\medical_rag\data\clean\eval_sets\results\qa_med_40_20261102_214803.json')

W, DPI = 1600, 150
# Okabe-Ito 语义色：同一类量在所有图里同一颜色（与 build_figures.py 同一套）
C_BM25 = '#56B4E9'   # 仅 BM25
C_VEC = '#0072B2'    # 仅向量 / 检索主色 / 可答题 / 首帧分布
C_HYB = '#009E73'    # 混合 RRF
C_REE = '#E69F00'    # 混合 + 精排 / 冷启动离群
C_REF = '#D55E00'    # 拒答题
C_MED = '#8A5300'    # 中位等参考标注（深杏，白底可读）
C_INK = '#1A1A1A'
C_GRID = '#B0B0B0'
C_EDGE = '#000000'

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False,
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.edgecolor': C_EDGE,
    'axes.linewidth': 0.8,
    'xtick.color': C_INK, 'ytick.color': C_INK,
    'font.size': 19,
})


def load(p):
    with open(os.path.abspath(p), encoding='utf-8') as f:
        return json.load(f)


def save(fig, name, h):
    out = os.path.join(HERE, name + '.png')
    fig.savefig(out, dpi=DPI, facecolor='white')
    plt.close(fig)
    return out


def style(ax, title, ylabel=None, xlabel=None, n=None):
    ax.set_title(title, fontsize=26, fontweight='bold', color=C_INK, pad=18)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=22, color=C_INK)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=22, color=C_INK)
    ax.grid(axis='y', linestyle='--', linewidth=0.9, color=C_GRID, alpha=0.35)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=22, length=4, width=0.8)
    if n:
        ax.text(0.99, 0.94, f'n={n}', transform=ax.transAxes, ha='right',
                fontsize=19, color='#555555')


# ───────────────────────── 图 9 四策略 × {MRR, Recall@5} ─────────────────────────
def fig9():
    ov = load(FOUR)['overall_four']
    keys = ['仅BM25', '仅向量检索', '混合检索(BM25+向量+RRF)', '混合检索+重排序']
    labs = ['仅 BM25', '仅向量', '混合 RRF', '混合 + 精排']
    cols = [C_BM25, C_VEC, C_HYB, C_REE]
    mets = ['MRR', 'Recall@5']
    x = np.arange(len(mets))
    w = 0.25   # 19 pt 标签约 131 px 宽，柱距需 >140 px，故加宽柱避免数值标签相互压字
    fig, ax = plt.subplots(figsize=(W / DPI, 6.0))
    for i, k in enumerate(keys):
        vals = [ov[k][m] for m in mets]
        ax.bar(x + (i - 1.5) * w, vals, w, label=labs[i], color=cols[i],
               edgecolor='white', linewidth=0.6)
    for j, m in enumerate(mets):
        for i, k in enumerate(keys):
            v = ov[k][m]
            ax.text(j + (i - 1.5) * w, v + 0.022, f'{v:.4f}',
                    ha='center', va='bottom', fontsize=19, color='#333333')
    ax.set_xticks(x)
    ax.set_xticklabels(mets, fontsize=22)
    ax.set_ylim(0, 1.16)
    ax.set_xlim(-0.6, 1.6)
    style(ax, '四策略检索效果（n=115，文档级 gold，top_k=20）', ylabel='得分')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.10), ncol=4,
              frameon=False, fontsize=19)
    fig.subplots_adjust(left=0.125, right=0.97, top=0.88, bottom=0.21)
    return save(fig, 'fig9_strategy_compare', 900)


# ───────────────────────── 图 10 首帧延迟直方图 ─────────────────────────
def fig10():
    e = load(QA40)
    ff = sorted(x['first_frame_ms'] for x in e['detail'])
    med = e['latency']['first_frame_median_ms']
    mx = e['latency']['first_frame_max_ms']
    edges = np.arange(210, 321, 10)
    cnt = [sum(1 for v in ff if lo <= v < lo + 10) for lo in edges[:-1]]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(W / DPI, 5.6),
                                  gridspec_kw={'width_ratios': [5.2, 1.0], 'wspace': 0.06})
    ax.bar(edges[:-1] + 5, cnt, width=8.4, color=C_VEC, edgecolor='white', linewidth=0.6)
    for xx, c in zip(edges[:-1] + 5, cnt):
        if abs(xx - med) < 6:   # 与中位线同柱：计数右对齐到线左侧，避免压线或落到邻柱
            ax.text(med - 1.0, c + 0.25, str(c), ha='right', va='bottom',
                    fontsize=19, color='#333333')
        else:
            ax.text(xx, c + 0.25, str(c), ha='center', va='bottom',
                    fontsize=19, color='#333333')
    ax.axvline(med, color=C_MED, linestyle='--', linewidth=2.2)
    ax.text(med + 3, 11.6, f'中位 {med} ms', fontsize=19, color=C_MED)
    ax.set_xlim(206, 326)
    ax.set_ylim(0, 13)
    ax.set_yticks([0, 3, 6, 9, 12])
    ax.set_xticks([210, 240, 270, 300, 320])
    style(ax, '首帧延迟分布（n=40，单机单并发串行）', ylabel='题数', xlabel='首帧耗时（ms）')
    ax2.bar([0], [1], width=0.5, color=C_REE, edgecolor='white', linewidth=0.6)
    ax2.text(0, 1.25, f'{mx} ms', ha='center', va='bottom', fontsize=19, color='#333333')
    ax2.text(0, 1.95, '冷启动\n离群', ha='center', va='bottom', fontsize=19, color='#555555')
    ax2.set_xticks([])
    ax2.set_yticks([])
    ax2.set_xlim(-0.8, 0.8)
    ax2.set_ylim(0, 3)
    ax2.set_title('离群值', fontsize=20, fontweight='bold', color=C_INK, pad=18)
    ax2.spines['left'].set_visible(False)
    fig.subplots_adjust(left=0.115, right=0.97, top=0.86, bottom=0.20)
    return save(fig, 'fig10_first_frame_hist', 840)


# ───────────────────────── 图 11 整答耗时：可答 / 拒答 ─────────────────────────
def fig11():
    e = load(QA40)
    det = e['detail']
    ans = sorted(x['total_ms'] / 1000 for x in det if x['group'] == 'answerable')
    ref = sorted(x['total_ms'] / 1000 for x in det if x['group'] == 'refusal')
    gd = [v for v in ref if v <= 0.5]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(W / DPI, 5.4),
                                 gridspec_kw={'width_ratios': [1.15, 3.6], 'wspace': 0.07})
    a1.scatter(gd, np.zeros(len(gd)), s=110, color=C_REF, edgecolor='white', linewidth=1.2)
    a1.set_xlim(0.1, 0.42)
    a1.set_ylim(-0.6, 0.6)
    a1.set_yticks([])
    a1.set_title(f'守卫拦截 {len(gd)} 道', fontsize=20, fontweight='bold',
                 color=C_INK, pad=16)
    a1.set_xlabel('秒', fontsize=20)
    a1.text(0.02, 0.90, '216–316 ms', transform=a1.transAxes, fontsize=19, color='#555555')

    a2.scatter(ans, np.zeros(len(ans)) + 0.18, s=110, color=C_VEC,
               edgecolor='white', linewidth=1.2, label=f'可答题 {len(ans)} 道')
    a2.scatter([v for v in ref if v > 0.5], np.zeros(len(ref) - len(gd)) - 0.18,
               s=110, color=C_REF, edgecolor='white', linewidth=1.2,
               label=f'拒答题 {len(ref) - len(gd)} 道（另 {len(gd)} 道见左）')
    a2.set_xlim(6.6, 11.6)
    a2.set_ylim(-0.6, 0.6)
    a2.set_yticks([])
    a2.set_title(f'完整生成 {len(ans) + len(ref) - len(gd)} 道', fontsize=20,
                 fontweight='bold', color=C_INK, pad=16)
    a2.set_xlabel('秒', fontsize=20)
    a2.text(0.98, 0.90, '>1,000 ms', transform=a2.transAxes, ha='right',
            fontsize=19, color='#555555')
    a2.legend(loc='upper center', bbox_to_anchor=(0.5, -0.16), ncol=2,
              frameon=False, fontsize=19)
    for a in (a1, a2):
        a.grid(axis='x', linestyle='--', linewidth=0.9, color=C_GRID, alpha=0.35)
        a.set_axisbelow(True)
        a.tick_params(labelsize=20)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.86, bottom=0.225)
    return save(fig, 'fig11_total_ms', 820)


# ───────────────────────── 图 12 五项质量指标 ─────────────────────────
def fig12():
    m = load(QA40)['metrics']
    items = [('回答正确率', 'answer_accuracy'), ('引用准确率', 'citation_accuracy'),
             ('无幻觉率', 'no_hallucination_rate'), ('拒答·应拒', 'refusal_accuracy_should'),
             ('拒答·不应拒', 'refusal_accuracy_should_not')]
    y = np.arange(len(items))
    vals = [m[k]['value'] for _, k in items]
    fig, ax = plt.subplots(figsize=(W / DPI, 5.6))
    ax.barh(y, vals, height=0.62, color=C_VEC, edgecolor='white', linewidth=0.6)
    for yy, (lab, k) in zip(y, items):
        d = m[k]
        ax.text(d['value'] + 0.02, yy, f"{d['num']}/{d['den']}", va='center',
                fontsize=20, color='#333333')
        ax.text(-0.02, yy, lab, va='center', ha='right', fontsize=20, color=C_INK)
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.22)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(['0', '25%', '50%', '75%', '100%'], fontsize=22)
    ax.grid(axis='x', linestyle='--', linewidth=0.9, color=C_GRID, alpha=0.35)
    ax.set_axisbelow(True)
    ax.set_title('质量指标（n=40；无幻觉率分母含拒答题）', fontsize=26, fontweight='bold',
                 color=C_INK, pad=18)
    ax.tick_params(labelsize=22)
    fig.subplots_adjust(left=0.20, right=0.97, top=0.87, bottom=0.10)
    return save(fig, 'fig12_metrics', 840)


# ───────────────────────── 图 13 精排增益 ─────────────────────────
def fig13():
    ov = load(FOUR)['overall_four']
    base = ov['混合检索(BM25+向量+RRF)']
    tuned = ov['混合检索+重排序']
    mets = ['MRR', 'Recall@1', 'R-Precision', 'NDCG@10']
    d = [tuned[m] - base[m] for m in mets]
    y = np.arange(len(mets))
    fig, ax = plt.subplots(figsize=(W / DPI, 5.4))
    ax.barh(y, d, height=0.52, color=C_REE, edgecolor='white', linewidth=0.6)
    for yy, m in zip(y, mets):
        ax.text(tuned[m] - base[m] + 0.002, yy,
                f'+{tuned[m] - base[m]:.4f}  ({base[m]:.4f} → {tuned[m]:.4f})',
                va='center', fontsize=19, color='#333333')
    ax.set_yticks(y)
    ax.set_yticklabels(mets, fontsize=22)
    ax.invert_yaxis()
    ax.axvline(0, color='#888888', linewidth=1.0)
    ax.set_xlim(0, 0.195)
    ax.grid(axis='x', linestyle='--', linewidth=0.9, color=C_GRID, alpha=0.35)
    ax.set_axisbelow(True)
    ax.set_xlabel('增量（混合 RRF → 混合 + 精排）', fontsize=22)
    ax.set_title('精排增益（n=115，文档级 gold）',
                 fontsize=26, fontweight='bold', color=C_INK, pad=18)
    ax.tick_params(labelsize=22)
    fig.subplots_adjust(left=0.18, right=0.97, top=0.88, bottom=0.17)
    return save(fig, 'fig13_reranker_gain', 820)


if __name__ == '__main__':
    for fn in (fig9, fig10, fig11, fig12, fig13):
        print(fn())
