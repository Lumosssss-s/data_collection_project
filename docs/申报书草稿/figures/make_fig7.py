# -*- coding: utf-8 -*-
"""
图 7 双视角对照（真实截图合成）
输入：src/panel_pro.png、src/panel_patient.png（PC 端实际页面裁切，1520×823，已同宽同缩放）
输出：fig7_dual_view.png（1600px 宽，150dpi）

说明：两张面板来自同一页面（DIS-COLORECTAL-001 · 02 流行病学），
左右两个版本用同一裁切框（CSS x 235–1010、宽 775）、同一缩放比，
此处仅做纵向排布 + 边框 + 标注，不对页面内容做任何删改。
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'src')

BG = (237, 240, 233)      # #EDF0E9
CARD = (247, 249, 243)    # #F7F9F3
PRI = (36, 92, 99)        # #245C63
PRI_T = (225, 237, 234)   # #E1EDEA
INK = (31, 42, 38)        # #1F2A26
MUT = (78, 92, 84)        # #4E5C54
BORDER = (207, 216, 201)  # #CFD8C9
ACC = (200, 154, 91)      # #C89A5B
ACC_T = (243, 231, 211)   # #F3E7D3

W = 1600
M = 40
PW = W - 2 * M            # 1520
REG = r'C:\Windows\Fonts\msyh.ttc'
BLD = r'C:\Windows\Fonts\msyhbd.ttc'


def f(size, bold=False):
    return ImageFont.truetype(BLD if bold else REG, size)


def tw(draw, s, font):
    return draw.textlength(s, font=font)


def text(draw, x, y, s, font, fill):
    draw.text((x, y), s, font=font, fill=fill, anchor='lm')


def rrect(draw, box, radius, fill, outline, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build():
    pro = Image.open(os.path.join(SRC, 'panel_pro.png')).convert('RGB')
    pat = Image.open(os.path.join(SRC, 'panel_patient.png')).convert('RGB')
    assert pro.size == pat.size, '两面板必须同尺寸（同宽裁切、同缩放）'
    ph = pro.size[1]

    y_lab1, y_pan1 = 224, 246
    y_lab2 = y_pan1 + ph + 58
    y_pan2 = y_lab2 + 22
    y_note = y_pan2 + ph + 46
    H = y_note + 126

    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)

    # ── 页眉（与其余各图同版式）──
    text(d, M, 74, '图 7', f(34, True), PRI)
    text(d, M, 124, '双视角对照：同一章节的专业表述与患者表述', f(46, True), INK)
    text(d, M, 172, 'DIS-COLORECTAL-001 · 02 流行病学 · PC 端实拍 2026-11-04', f(33), MUT)

    # 右上角徽章
    badge = '实拍截图（非绘制）'
    bf = f(33)
    bw = tw(d, badge, bf) + 44
    rrect(d, (W - M - bw, 88, W - M, 134), 8, ACC_T, ACC, 2)
    d.text((W - M - bw / 2, 111), badge, font=bf, fill=(122, 91, 46), anchor='mm')

    # ── 两个面板 ──
    for panel, y_lab, y_pan, tag, desc in (
            (pro, y_lab1, y_pan1, '专业视角', '就地内联【来源 REC-…】标注，供临床读者即时核对'),
            (pat, y_lab2, y_pan2, '患者视角', '通俗改写，正文不含【来源】标记，故无角标')):
        tagf, desf = f(34, True), f(33)
        tw_tag, tw_des = tw(d, tag, tagf), tw(d, desc, desf)
        rrect(d, (M, y_lab - 22, M + tw_tag + 36, y_lab + 22), 8, PRI_T, PRI, 2)
        d.text((M + 18, y_lab), tag, font=tagf, fill=PRI, anchor='lm')
        text(d, M + tw_tag + 36 + 20, y_lab, desc, desf, MUT)
        img.paste(panel, (M, y_pan))
        d.rectangle((M - 1, y_pan - 1, M + PW, y_pan + ph), outline=BORDER, width=2)

    # ── 脚注 ──
    nf = f(33)
    text(d, M, y_note, '两图同一裁切框（文本列宽 775 CSS px）、同一缩放比，未对页面内容做任何增删。', nf, MUT)
    text(d, M, y_note + 42, '患者版为通俗改写：不带溯源角标，也不生成节末「本节来源对照」折叠表。', nf, MUT)
    d.text((W - M, H - 30), '实拍截图', font=nf, fill=MUT, anchor='rm')

    out = os.path.join(HERE, 'fig7_dual_view.png')
    img.save(out, dpi=(150, 150))
    print('png:', os.path.basename(out), img.size)


if __name__ == '__main__':
    build()
