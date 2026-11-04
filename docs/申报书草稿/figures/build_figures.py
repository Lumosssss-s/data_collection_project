"""申报书配图生成器（1600px 宽 / 150dpi）。
只读：读取本地截图与既有数据，不访问网络、不改仓库其他文件。
用法：python build_figures.py
"""
import os, subprocess, sys, math, json

HERE = os.path.dirname(os.path.abspath(__file__))
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
UD = os.path.join(os.environ.get('TEMP', '.'), 'fig_ud')

# Okabe-Ito 语义色（同一类量在所有图里同一颜色；黄 #F0E442 白底对比不足，未使用）
BG = '#FFFFFF'; CARD = '#F7F7F7'        # 白底 / 极浅中性灰卡片
PRI = '#0072B2'; PRI_T = '#DCEBF5'      # 检索 / 结构 / 计数
GEN = '#D55E00'; GEN_L = '#E8875A'; GEN_L2 = '#F2B296'; GEN_T = '#FBE7DB'  # 生成（LLM）
CACHE = '#56B4E9'; CACHE_T = '#DFF1FB'  # 缓存
RANK = '#009E73'                        # 融合 / 术语
INK = '#1A1A1A'; MUT = '#555555'; BORDER = '#9AA0A6'; GRID = '#D9D9D9'
ACC = '#E69F00'; ACC_T = '#FCEFD8'; ACC_D = '#8A5300'   # 杏色：填充用 ACC，文字与细线用 ACC_D
VIOLET = '#CC79A7'                      # Okabe 红紫：指南文档 doc 类目（仅作填充，不承载文字）
W = 1600
FONT = 'Microsoft YaHei'

def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

def tw(s, fs):
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o > 0x2E80:
            w += fs
        elif ch == ' ':
            w += fs * 0.30
        else:
            w += fs * 0.56
    return w

def t(x, y, s, fs=34, fill=INK, bold=False, anchor='start', mono=False, op=1, serif=False):
    fam = 'Consolas, monospace' if mono else ('Times New Roman, serif' if serif else FONT)
    wgt = 'bold' if bold else 'normal'
    return (f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{fs}" font-weight="{wgt}" '
            f'fill="{fill}" text-anchor="{anchor}" dominant-baseline="central" opacity="{op}">{esc(s)}</text>')

def box(x, y, w, h, fill=CARD, stroke=BORDER, r=12, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

def chip(x, y, w, h, s, fs=34, fill=CARD, stroke=BORDER, bold=False, tc=INK):
    return box(x, y, w, h, fill, stroke, 10, 2) + t(x + w / 2, y + h / 2, s, fs, tc, bold, 'middle')

def vline(x, y1, y2, color=PRI, sw=3):
    return f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="{sw}"/>'

def hline(x1, x2, y, color=BORDER, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{sw}"{d}/>'

def head(num, title, sub='', badge=''):
    out = [t(40, 96, title, 46, INK, True)]
    if sub:
        out.append(t(40, 154, sub, 38, MUT))
    if badge:
        bw = tw(badge, 38) + 44
        out.append(box(W - 40 - bw, 88, bw, 46, ACC_T, ACC, 8, 2))
        out.append(t(W - 40 - bw / 2, 111, badge, 38, ACC_D, False, 'middle'))
    return ''.join(out)


def foot(extra=''):
    s = f'<line x1="40" y1="{H}" x2="{W - 40}" y2="{H}" stroke="{BORDER}" stroke-width="2"/>'
    return s

def save_svg(name, body, h):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">'
           f'{body}</svg>')
    p = os.path.join(HERE, name + '.svg')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(svg)
    return p

def render(name, h):
    svg = os.path.join(HERE, name + '.svg')
    html = os.path.join(HERE, '_wrap.html')
    with open(html, 'w', encoding='utf-8') as f:
        f.write(f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>html,body{{margin:0;padding:0;'
                f'background:{BG};}}img{{display:block;width:{W}px;height:{h}px;}}</style></head>'
                f'<body><img src="{name}.svg"></body></html>')
    shot = os.path.join(HERE, '_raw.png')
    if os.path.exists(shot):
        os.remove(shot)
    subprocess.run([EDGE, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--force-device-scale-factor=2', f'--window-size={W},{h}',
                    '--virtual-time-budget=4000', f'--user-data-dir={UD}',
                    f'--screenshot={shot}', 'file:///' + html.replace('\\', '/')],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    from PIL import Image
    im = Image.open(shot).convert('RGB')
    if im.size[0] != W * 2:
        im = im.resize((W * 2, int(im.height * W * 2 / im.width)), Image.LANCZOS)
    im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
    out = os.path.join(HERE, name + '.png')
    im.save(out, dpi=(150, 150))
    os.remove(html)
    if os.path.exists(shot):
        os.remove(shot)
    return out, im.size


# ───────────────────────── 图 1 系统总体架构 ─────────────────────────
def fig1():
    global H
    H = 1180
    b = [head(1, '系统总体架构', '五个功能层：数据 → 检索 → 缓存 → 生成 → 应用')]
    bx, bw = 40, 1520
    y = 186

    def band(hh, name, fill=PRI, tc='#FFFFFF'):
        s = box(bx, y, bw, hh)
        s += box(bx + 18, y + 20, 176, 54, fill, fill, 8, 2)
        s += t(bx + 106, y + 47, name, 38, tc, True, 'middle')
        return s

    def chips(items, yy, x0=240, gap=20, fill=CARD, stroke=BORDER, bold=False, tc=INK):
        s, x = '', x0
        for it in items:
            w = tw(it, 38) + 44
            s += chip(x, yy, w, 54, it, 38, fill, stroke, bold, tc)
            x += w + gap
        return s

    # 数据层
    b.append(band(210, '数据层'))
    for i, s in enumerate(['临床指南', '药品说明书', '科普库']):
        w = tw(s, 38) + 44
        b.append(chip(240, y + 18 + i * 66, w, 54, s, 38))
    b.append(box(560, y + 18, 980, 174, '#FFFFFF', BORDER, 10, 2))
    b.append(t(584, y + 54, 'Elasticsearch · 5 个索引', 38, PRI, True))
    for (cx, yy, s) in ((584, y + 108, '知识库'), (904, y + 108, '疾病档案'),
                        (1224, y + 108, '语义缓存'), (584, y + 156, 'KG 三元组'),
                        (904, y + 156, 'KG 实体')):
        b.append(t(cx, yy, s, 38, MUT))

    # 检索层
    y += 210 + 26
    b.append(band(190, '检索层'))
    b.append(chips(['查询改写', 'BM25 召回', '向量召回 bge-m3'], y + 26))
    b.append(chips(['RRF 融合 k=60', '精排 reranker', '上下文扩展', '时效过滤'], y + 96))

    # 缓存层
    y += 190 + 26
    b.append(band(170, '缓存层', CACHE, INK))
    b.append(chips(['L0 精确键', 'L1 余弦 ≥0.95', 'L2 槽位守卫'], y + 26,
                   fill=CACHE_T, stroke=CACHE, bold=True))
    b.append(t(240, y + 118, '槽位：癌种 / 线数 / 分期 / 标志物 / 药名', 38, MUT))

    # 生成层
    y += 170 + 26
    b.append(band(140, '生成层', GEN))
    b.append(chip(240, y + 26, tw('LLM 生成', 38) + 44, 54, 'LLM 生成', 38,
                  GEN, GEN, True, '#FFFFFF'))
    x = 240 + tw('LLM 生成', 38) + 64
    b.append(chip(x, y + 26, tw('SSE 分片推送', 38) + 44, 54, 'SSE 分片推送', 38))
    b.append(t(x + tw('SSE 分片推送', 38) + 84, y + 53, '缓存命中直接重放', 38, MUT))

    # 应用层
    y += 140 + 26
    b.append(band(140, '应用层', BORDER))
    b.append(chips(['专业视角', '患者视角', '证据检索', '随访管理', '报告解读'], y + 26))

    save_svg('fig1_architecture', ''.join(b), H)


# ───────────────────────── 图 2 检索链路时序 ─────────────────────────
def fig2():
    global H
    rows = [
        ('用户提问', '中文自然语言'),
        ('查询改写', '槽位抽取'),
        ('双路召回', 'BM25 + bge-m3'),
        ('RRF 融合', 'k=60 倒数加权'),
        ('精排', 'reranker 交叉打分'),
        ('上下文扩展', '补齐邻接段落'),
        ('时效过滤', '按年份降权'),
        ('缓存判定', 'L0 / L1 / L2'),
        ('生成 / 重放', '未命中调 LLM'),
        ('SSE 分片推送', '首帧即反馈'),
    ]
    H = 1010
    b = [head(2, '检索链路时序：从提问到分片输出', '十个处理环节；右侧为后端链式计时实测（2026-11-02～11-04）')]
    top, step = 216, 74
    for i, (s, note) in enumerate(rows):
        cy = top + i * step
        b.append(t(96, cy, f'{i + 1:02d}', 38, PRI, True, 'end', mono=True))
        b.append(box(120, cy - 30, 470, 60))
        b.append(t(146, cy, s, 38, INK, True))
        b.append(t(630, cy, note, 38, MUT))
        if i < len(rows) - 1:
            b.append(vline(96, cy + 30, cy + step - 30, BORDER, 2))

    def bracket(i1, i2, label, color=PRI):
        y1 = top + i1 * step - 30
        y2 = top + i2 * step + 30
        s = f'<line x1="1120" y1="{y1}" x2="1120" y2="{y2}" stroke="{color}" stroke-width="3"/>'
        s += f'<line x1="1120" y1="{y1}" x2="1140" y2="{y1}" stroke="{color}" stroke-width="3"/>'
        s += f'<line x1="1120" y1="{y2}" x2="1140" y2="{y2}" stroke="{color}" stroke-width="3"/>'
        s += t(1560, (y1 + y2) / 2, label, 38, color, True, 'end')
        return s

    b.append(bracket(1, 6, '检索 0.67 s'))
    b.append(bracket(8, 8, '生成 7.85 s', GEN))
    b.append(t(1560, 960, '合计 8.52 s（后端链式计时）', 38, MUT, True, 'end'))
    save_svg('fig2_pipeline', ''.join(b), H)


# ───────────────────────── 图 3 语义缓存判定 ─────────────────────────
def fig3():
    global H
    H = 950
    b = [head(3, '语义缓存判定：三层判定与降级路径', '阈值 0.95（2026-11-04 生效，取代原 0.88）；零误命中优先于命中率')]
    nodes = [
        ('查询规范化', '去噪/同义词归一'),
        ('L0 精确键匹配', '逐字一致'),
        ('L1 语义相似度', '余弦 ≥0.95'),
        ('L2 槽位守卫', '槽位比对；拦截 1 例'),
    ]
    x, w = 160, 420
    top, gap = 216, 24
    for i, (s, note) in enumerate(nodes):
        cy = top + i * (104 + gap)
        b.append(box(x, cy, w, 104, CACHE_T, CACHE, 12, 3))
        b.append(t(x + 24, cy + 34, s, 38, INK, True))
        b.append(t(x + 24, cy + 78, note, 38, MUT))
        if i < 3:
            b.append(vline(x + w / 2, cy + 104, cy + 104 + gap, CACHE, 3))
    # 右侧分支：与各判定节点同高
    branches = [
        (1, '命中 → 重放 419–711 ms', CACHE_T, CACHE, INK, CACHE),
        (2, '余弦 < 0.95 → 进入生成', GEN_T, GEN, INK, GEN),
        (3, '一致 → 重放 / 冲突 → 不命中', CARD, BORDER, INK, BORDER),
    ]
    for i, txt, fill, st, col, ln in branches:
        cy = top + i * (104 + gap) + 52
        b.append(f'<line x1="{x + w}" y1="{cy}" x2="780" y2="{cy}" stroke="{ln}" stroke-width="3"/>')
        b.append(box(780, cy - 36, 640, 72, fill, st, 10, 2))
        b.append(t(804, cy, txt, 38, col))
    # 降级
    dy = top + 4 * (104 + gap)
    b.append(box(x, dy, 1260, 72, '#FFFFFF', BORDER, 12, 2, '10 6'))
    b.append(t(x + 24, dy + 36, '降级：Redis 不可用 → 仅进程内 L0，不阻断问答', 38, MUT))
    b.append(t(x, 852, '实测 1｜意图类负样本余弦上界 0.9187，全部低于阈值 0.95。', 38, MUT))
    b.append(t(x, 906, '实测 2｜阈值之上仅 1 例被 L2 拦截：cos 0.9673，槽位冲突 → 不命中。', 38, MUT))
    save_svg('fig3_cache_flow', ''.join(b), H)


# ───────────────────────── 图 4 阈值-召回-误合并 ─────────────────────────
def fig4():
    global H
    H = 1030
    pts = [(0.80, 0.923, 6), (0.83, 0.923, 2), (0.85, 0.808, 2), (0.88, 0.692, 2),
           (0.90, 0.692, 2), (0.92, 0.577, 0), (0.95, 0.346, 0)]
    x0, x1 = 200, 1150
    y0, y1 = 300, 760
    b = [head(4, '阈值—召回—误合并：新批标定的完整曲线', '新批 26 正 / 43 负 / 16 探针，2026-11-04；左轴召回率，右轴误合并例数')]

    def X(v): return x0 + (v - 0.78) / (0.97 - 0.78) * (x1 - x0)
    def Y(v): return y1 - v * (y1 - y0)
    def Yr(v): return y1 - v / 6 * (y1 - y0)

    for v in (0.0, 0.5, 1.0):
        yy = Y(v)
        b.append(hline(x0, x1, yy, GRID, 2))
        b.append(t(x0 - 18, yy, f'{v:.1f}', 38, MUT, False, 'end'))
    for v in (0, 3, 6):
        b.append(t(x1 + 18, Yr(v), f'{v}', 38, MUT))
    b.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{MUT}" stroke-width="2"/>')
    b.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="{MUT}" stroke-width="2"/>')
    b.append(f'<line x1="{x1}" y1="{y0}" x2="{x1}" y2="{y1}" stroke="{MUT}" stroke-width="2"/>')
    for v in (0.80, 0.83, 0.85, 0.88, 0.90, 0.92, 0.95):
        b.append(t(X(v), y1 + 34, f'{v:.2f}', 38, MUT, False, 'middle'))
    b.append(t((x0 + x1) / 2, y1 + 82, '余弦阈值 τ', 40, INK, False, 'middle'))
    b.append(f'<text x="{x0 - 96}" y="{(y0 + y1) / 2}" font-family="{FONT}" font-size="40" fill="{INK}" '
             f'text-anchor="middle" transform="rotate(-90 {x0 - 96} {(y0 + y1) / 2})">召回率</text>')
    b.append(f'<text x="{x1 + 104}" y="{(y0 + y1) / 2}" font-family="{FONT}" font-size="40" fill="{INK}" '
             f'text-anchor="middle" transform="rotate(90 {x1 + 104} {(y0 + y1) / 2})">误合并（例）</text>')

    # 曲线
    rl = ' '.join(f'{X(v):.1f},{Y(r):.1f}' for v, r, _ in pts)
    cx = ' '.join(f'{X(v):.1f},{Yr(c):.1f}' for v, _, c in pts)
    b.append(f'<polyline points="{rl}" fill="none" stroke="{PRI}" stroke-width="5"/>')
    b.append(f'<polyline points="{cx}" fill="none" stroke="{ACC}" stroke-width="5" stroke-dasharray="12 8"/>')
    for v, r, c in pts:
        b.append(f'<circle cx="{X(v):.1f}" cy="{Y(r):.1f}" r="10" fill="#FFFFFF" stroke="{PRI}" stroke-width="4"/>')
        b.append(f'<rect x="{X(v) - 9:.1f}" y="{Yr(c) - 9:.1f}" width="18" height="18" fill="{ACC}" opacity="0.85"/>')
    # 两条基准线
    b.append(f'<line x1="{X(0.88)}" y1="{y0}" x2="{X(0.88)}" y2="{y1}" stroke="{MUT}" stroke-width="2" stroke-dasharray="8 8"/>')
    b.append(f'<line x1="{X(0.95)}" y1="{y0}" x2="{X(0.95)}" y2="{y1}" stroke="{PRI}" stroke-width="3" stroke-dasharray="8 8"/>')
    b.append(t(X(0.88) - 14, y0 + 34, '0.88 原值', 38, MUT, False, 'end'))
    b.append(t(X(0.95) - 14, y0 + 34, '0.95 现值', 38, PRI, True, 'end'))
    # 图例
    ly = 248
    b.append(f'<line x1="620" y1="{ly}" x2="676" y2="{ly}" stroke="{PRI}" stroke-width="5"/>')
    b.append(f'<circle cx="648" cy="{ly}" r="9" fill="#FFFFFF" stroke="{PRI}" stroke-width="4"/>')
    b.append(t(694, ly, '召回率（左轴）', 38, INK))
    b.append(f'<line x1="950" y1="{ly}" x2="1006" y2="{ly}" stroke="{ACC}" stroke-width="5" stroke-dasharray="12 8"/>')
    b.append(t(1022, ly, '误合并例数（右轴）', 38, INK))
    # 结论标注（现行阈值）
    b.append(box(200, 876, 1240, 110, ACC_T, ACC, 12, 2))
    b.append(t(226, 908, 'τ=0.95 现行阈值', 38, ACC_D, True))
    b.append(t(226, 952, '召回 0.346 · 误合并 0 例', 38, ACC_D))
    save_svg('fig4_threshold', ''.join(b), H)


# ───────────────────────── 图 5 延迟分解 ─────────────────────────
def fig5():
    global H
    H = 1140
    b = [head(5, '端到端延迟四组实测：首帧、首字、整答、缓存', '首帧 n=40；其余单次 n=1；冷启动 2,597 ms 单列，不并入中位数')]
    b.append(t(40, 206, 'A · 首帧与缓存命中', 40, PRI, True))
    ax0, ax1 = 470, 1450

    def AX(v): return ax0 + v / 1.2 * (ax1 - ax0)

    # 首帧（n=40 区间条）
    b.append(t(40, 250, '首个状态反馈帧（n=40）', 38, INK))
    b.append(f'<rect x="{AX(0.215)}" y="242" width="{AX(1.048) - AX(0.215)}" height="36" fill="{PRI_T}" stroke="{PRI}" stroke-width="2"/>')
    b.append(f'<line x1="{AX(0.256)}" y1="234" x2="{AX(0.256)}" y2="286" stroke="{ACC_D}" stroke-width="5"/>')
    b.append(t(AX(0.215), 224, '215.1', 38, MUT, False, 'middle'))
    b.append(t(AX(1.048), 224, '1,048 ms', 38, MUT, False, 'middle'))
    b.append(t(AX(0.256) + 12, 304, '中位 256 ms', 38, ACC_D, True))
    # 缓存命中
    b.append(t(40, 346, '缓存命中（整答）', 38, INK))
    b.append(f'<rect x="{AX(0.419)}" y="338" width="{AX(0.711) - AX(0.419)}" height="36" fill="{CACHE_T}" stroke="{CACHE}" stroke-width="2"/>')
    b.append(t(AX(0.711) + 16, 356, '419–711 ms', 38, INK, True))
    b.append(f'<line x1="{ax0}" y1="406" x2="{ax1}" y2="406" stroke="{MUT}" stroke-width="2"/>')
    for k in range(7):
        xx = AX(k * 0.2)
        b.append(f'<line x1="{xx}" y1="406" x2="{xx}" y2="416" stroke="{MUT}" stroke-width="2"/>')
        b.append(t(xx, 438, f'{k * 0.2:.1f}', 38, MUT, False, 'middle'))
    b.append(t(ax1 + 56, 438, '秒', 38, MUT))

    b.append(t(40, 484, 'B · 首字、整答、冷启动', 40, PRI, True))

    def BX(v): return ax0 + v / 14 * (ax1 - ax0)

    b.append(t(40, 534, '首个正文字符（n=1）', 38, INK))
    b.append(box(BX(0), 522, BX(5.428) - BX(0), 36, GEN_L, GEN_L, 6, 0))
    b.append(t(BX(5.428) + 16, 540, '5,428 ms', 38, INK, True))
    b.append(t(40, 632, '完整回答（n=1）', 38, INK))
    b.append(box(BX(0), 620, BX(13.238) - BX(0), 36, GEN, GEN, 6, 0))
    b.append(t(BX(13.238) - 16, 638, '13,238 ms', 38, '#FFFFFF', True, 'end'))
    b.append(t(40, 730, '热态完整回答（n=1）', 38, INK))
    b.append(box(BX(0), 718, BX(8.52) - BX(0), 24, GEN_L2, GEN_L2, 4, 0))
    b.append(t(BX(8.52) + 16, 730, '8.52 s', 38, MUT, True))
    # 冷启动
    b.append(t(40, 798, '冷启动（n=1）', 38, INK))
    b.append(f'<line x1="{BX(2.597)}" y1="780" x2="{BX(2.597)}" y2="866" stroke="{ACC}" stroke-width="6"/>')
    b.append(t(BX(2.597) + 18, 812, '2,597 ms（含 bge-m3 加载）', 38, ACC_D))
    b.append(f'<line x1="{ax0}" y1="892" x2="{ax1}" y2="892" stroke="{MUT}" stroke-width="2"/>')
    for k in range(8):
        xx = BX(k * 2)
        b.append(f'<line x1="{xx}" y1="892" x2="{xx}" y2="902" stroke="{MUT}" stroke-width="2"/>')
        b.append(t(xx, 924, f'{k * 2}', 38, MUT, False, 'middle'))
    b.append(t(ax1 + 56, 924, '秒', 38, MUT))
    b.append(t(40, 970, '口径：A/B 两区均为后端链式计时（接收请求 → 首个 SSE 状态帧 / 正文 token / 末帧）。', 38, MUT))
    b.append(t(40, 1024, '首帧中位取自 40 题（首题含冷启动，逐题区间 215.1–319.3 ms）。', 38, MUT))
    b.append(t(40, 1078, '其余各点均为单次实测，不与中位数混算。', 38, MUT))
    save_svg('fig5_latency', ''.join(b), H)


# ───────────────────────── 图 6 数据规模与覆盖 ─────────────────────────
def fig6():
    global H
    H = 920
    b = [head(6, '数据规模与癌种覆盖', 'ES 根文档计数（medical_knowledge），2026-11-04；四癌种分布按记录归属统计')]
    # 左：五类根文档
    b.append(t(40, 232, 'A · 五类根文档', 40, PRI, True))
    kinds = [('指南文档 doc', 10, VIOLET), ('推荐条目 rec', 1863, PRI), ('药品说明书 drug', 36, CACHE),
             ('术语词条 term', 377, RANK), ('文献摘要 literature', 2076, PRI)]
    lx, lw = 40, 480
    for i, (s, v, col) in enumerate(kinds):
        yy = 280 + i * 104
        b.append(t(lx, yy, s, 38, INK))
        bw = max(4, v / 2200 * lw)
        b.append(box(lx, yy + 44, bw, 24, col, col, 4, 0))
        b.append(t(lx + bw + 18, yy + 56, f'{v:,}', 38, INK, True))
    b.append(f'<line x1="{lx}" y1="792" x2="{lx + lw}" y2="792" stroke="{MUT}" stroke-width="2"/>')
    b.append(t(lx + lw, 822, '0–2,200 条（线性）', 38, MUT, False, 'end'))

    # 右：四癌种矩阵
    b.append(t(700, 232, 'B · 四癌种分布', 40, PRI, True))
    cols = [('rec 条目', [546, 1112, 173, 32], 'rec 推荐条目'),
            ('drug 药品', [18, 7, 10, 8], 'drug 药品'),
            ('doc 指南', [4, 3, 2, 1], 'doc 指南文档')]
    rows = ['肺癌', '结直肠癌', '乳腺癌', '胃癌']
    cw = 210
    colmap = (PRI, CACHE, VIOLET)
    for j, (lab, vals, _full) in enumerate(cols):
        b.append(t(880 + j * cw, 288, lab, 38, MUT, True))
    for i, r in enumerate(rows):
        yy = 350 + i * 112
        b.append(t(700, yy, r, 38, INK, True))
        for j, (lab, vals, _full) in enumerate(cols):
            cx = 880 + j * cw
            mx = max(vals)
            v = vals[i]
            b.append(t(cx + 8, yy, f'{v:,}', 38, INK, True))
            bw = max(3, v / mx * (cw - 30))
            b.append(box(cx + 8, yy + 26, bw, 20, colmap[j], colmap[j], 4, 0))
    b.append(t(40, 872, '注：drug 按 cancer_types 多标签计数，同一药品可计入多个癌种（合计 43 > 去重 36）。', 38, MUT))
    save_svg('fig6_data_scale', ''.join(b), H)


# ───────────────────────── 图 8 证据链溯源 ─────────────────────────
def fig8():
    global H
    H = 880
    b = [head(8, '证据链：章节 → 条目 → 档案段落')]
    # ① 章节
    b.append(box(200, 160, 1000, 170, CARD, BORDER, 14, 2))
    b.append(t(228, 200, '01 章节', 40, MUT, True))
    b.append(t(228, 252, 'DOC-BREAST-EPMC-001', 42, PRI, True, mono=True))
    b.append(t(228, 302, 'Table 2 · CQ.2', 38, MUT))
    # ② 条目 + 强度色块
    b.append(box(300, 390, 800, 210, PRI_T, PRI, 14, 2))
    b.append(t(328, 432, '02 推荐条目', 40, INK, True))
    b.append(t(328, 484, 'REC-BREAST-EPMC-0110', 42, PRI, True, mono=True))
    for (x, w, s, fill) in ((328, 200, 'SoR 1', '#DCEBF5'),
                            (546, 260, 'SoE Strong', '#AFD3EB'),
                            (824, 248, '共识 100%', '#7FB6DC')):
        b.append(box(x, 515, w, 60, fill, PRI, 8, 2))
        b.append(t(x + w / 2, 545, s, 38, INK, True, 'middle'))
    # ③ 档案段落
    b.append(box(400, 640, 700, 190, CARD, BORDER, 14, 2))
    b.append(t(428, 678, '03 档案段落', 40, MUT, True))
    b.append(t(428, 724, 'DIS-BREAST-001 / treatment', 40, PRI, True))
    b.append(t(428, 778, '【来源 REC-BREAST-EPMC-0110】', 38, INK))
    # 下行箭头
    for (x, y1, y2) in ((700, 330, 390), (700, 600, 640)):
        b.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{PRI}" stroke-width="4"/>')
        b.append(f'<path d="M{x - 12},{y2 - 16} L{x},{y2 - 2} L{x + 12},{y2 - 16}" fill="{PRI}"/>')
    # 回查箭头（虚线，自③回到①）
    b.append(f'<line x1="1250" y1="760" x2="1250" y2="240" stroke="{ACC}" stroke-width="4" stroke-dasharray="14 10"/>')
    b.append(f'<path d="M1262,256 L1250,240 L1238,256" stroke="{ACC}" stroke-width="4" fill="none"/>')
    b.append(t(1270, 500, '可回查', 38, ACC_D, True))
    save_svg('fig8_evidence_chain', ''.join(b), H)


if __name__ == '__main__':
    names = ['fig1_architecture', 'fig2_pipeline', 'fig3_cache_flow', 'fig4_threshold',
             'fig5_latency', 'fig6_data_scale', 'fig8_evidence_chain']
    for fn in (fig1, fig2, fig3, fig4, fig5, fig6, fig8):
        fn()
        print('svg saved:', fn.__name__)
    import re
    for nm in names:
        sp = os.path.join(HERE, nm + '.svg')
        with open(sp, encoding='utf-8') as f:
            h = int(re.search(r'height="(\d+)"', f.read()).group(1))
        out, size = render(nm, h)
        print('png:', os.path.basename(out), size)
