# -*- coding: utf-8 -*-
"""WHO ATC/DDD Index → L01（抗肿瘤药）/ L02（内分泌治疗）等 5 级码 CSV。

路径：顶级页 → 3 级分组 → 4 级分组 → 5 级码表页，全部抓取后写入 fetched/atc/atc_oncology.csv
      （抓取结果属「未经处理的数据」，入 fetched/；cache/ 只放脚本中间件）

运行：python tools/15_fetch_atc.py
依赖：标准库（ssl / urllib.request / csv）。不需要 py7zr / openpyxl。
"""
import os
import re
import ssl
import csv
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "fetched", "atc")
OUT = os.path.join(OUT_DIR, "atc_oncology.csv")

INDEX_URL = "https://atcddd.fhi.no/atc_ddd_index/"
# 5 癌种相关：L01/L02 是核心抗肿瘤，L03 免疫调节剂，H02 糖皮质激素，
# H03 甲状腺药，M05 骨病（双膦酸盐/地舒单抗），A11 维生素，A12 矿物质，
# A04 止吐（昂丹司琼 A04AA01 / 阿瑞匹坦 A04AD12，A4 药单中仅这两种止吐药），
# G03 性激素（雷洛昔芬 G03XC01 属 SERM，不在 L02 组）
TOP_GROUPS = ("L01", "L02", "L03", "H02", "H03", "M05", "A11", "A12", "A04", "G03")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

LINK = re.compile(r'href="\./\?code=([A-Z0-9]+)&showdescription=\w+"')
ROW = re.compile(r"<tr><td>([A-Z]\d{2}[A-Z]{2}\d{2})&nbsp;</td><td>.*?>(.*?)</a>", re.S)


def fetch(code):
    url = "%s?code=%s&showdescription=no" % (INDEX_URL, code)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
        return r.read().decode("latin-1")


def clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def main():
    rows = {}  # code → {code, name_en, group, parent}
    for top in TOP_GROUPS:
        html = fetch(top)
        lv3 = sorted({c for c in LINK.findall(html) if len(c) == 4 and c.startswith(top)})
        print("%s → 3 级分组 %d 个: %s" % (top, len(lv3), lv3))
        lv4 = []
        for g in lv3:
            ghtml = fetch(g)
            kids = sorted({c for c in LINK.findall(ghtml) if len(c) == 5 and c.startswith(g)})
            lv4.extend(kids or [g])
        lv4 = sorted(set(lv4))
        print("  4 级分组 %d 个" % len(lv4))
        for g in lv4:
            try:
                ghtml = fetch(g)
            except Exception as e:
                print("  跳过", g, e)
                continue
            found = ROW.findall(ghtml)
            for code, name in found:
                rows[code] = {"code": code, "name_en": clean(name), "group": g, "parent": top}
            print("  %s → %d 条" % (g, len(found)))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name_en", "group", "parent"])
        w.writeheader()
        for code in sorted(rows):
            w.writerow(rows[code])

    print("\n合计 %d 条 → %s" % (len(rows), OUT))
    print("样例:", [(c, rows[c]["name_en"]) for c in list(sorted(rows))[:8]])


if __name__ == "__main__":
    main()
