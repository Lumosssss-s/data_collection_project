# -*- coding: utf-8 -*-
"""tools/26_fetch_cmkb_drugs.py

按 CMKB（临床医学知识库，中国医学科学院医学信息研究所/图书馆，http://www.cmkb.cn）
前端检索接口抓取药物库的**目录级字段**：药物名、类别、适应证、禁忌症、药物相互作用。

接口来源（逆向自 /bootstrop/js/date/serachlist.js）：
  POST /front/date/pagelist
  body 为前端拼的 JS 字面量字符串（非标准 JSON），字段：
    commonSerach / draw / currpage（0 基）/ pagesize / serachType=common / tableType / letter / order
  响应 JSON：{data:[...], draw, recordsFiltered, recordsTotal}
  tableType=yw 覆盖全部药物（hxyw 化学药 1164 + zcy 中成药 1560，共 2724）。

限制（必须在采集说明中同步记录）：
  1. 详情页 /view/disease/todetail 的正文（成分、药理、临床应用、不良反应等）由登录态渲染，
     未登录只能拿到目录级字段；本脚本不尝试绕过登录。
  2. 站点版权声明 © 中国医学科学院 北京协和医学院医学信息研究所/图书馆 版权所有（京ICP备10218182号-12），
     无 robots.txt，也未提供开放数据许可。抓取结果仅作内部参考资料，输出到 fetched/（非 data/clean/ 交付目录），
     对外分发或入库前需向 sinomed@imicams.ac.cn 取得书面授权。
  3. 默认 1.5s 间隔、可按 --delay 调整；禁止高并发，避免给对方站点造成压力。

产物：
  fetched/cmkb_drugs/drugs.json     药物目录（按 cmkb_id 排序，重复运行字节级一致）
  fetched/cmkb_drugs/manifest.json  抓取参数与条数审计

用法：
  python tools/26_fetch_cmkb_drugs.py                       # 全量 2724 条
  python tools/26_fetch_cmkb_drugs.py --query 阿司匹林       # 关键词检索
  python tools/26_fetch_cmkb_drugs.py --max-pages 3 --pagesize 50   # 试运行
  python tools/26_fetch_cmkb_drugs.py --force               # 覆盖已存在产物
"""
import argparse
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "fetched", "cmkb_drugs")
OUT_JSON = os.path.join(OUT_DIR, "drugs.json")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

HOST = "http://www.cmkb.cn"
LIST_API = HOST + "/front/date/pagelist"
DETAIL = HOST + "/view/disease/todetail?id={id}&tabletype={type}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
DRUG_KINDS = ("hxyw", "zcy")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def build_opener():
    """带 CookieJar 的 opener：接口需要一次首页访问拿到 JSESSIONID 才不返回 500。"""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=CTX)
    )


def sanitize(s):
    """前端把关键词直接拼进 JS 字面量，去掉会破坏语法的字符。"""
    return re.sub(r'["\\\r\n]', "", str(s or "")).strip()


def fetch_page(opener, table_type, keyword, currpage, pagesize, retries=3):
    payload = (
        '{{commonSerach:"{kw}",draw:"1",currpage:"{page}",pagesize:"{size}",'  # currpage 为 1 基
        'serachType:"common",tableType:"{tt}",letter:"",order:""}}'
    ).format(kw=sanitize(keyword), page=currpage, size=pagesize, tt=table_type)
    req = urllib.request.Request(
        LIST_API,
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": HOST + "/view/disease/tolist?tabletype=" + table_type,
            "User-Agent": UA,
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with opener.open(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # 5xx / 超时退避重试
            if attempt == retries - 1:
                raise
            print("  重试 %d/%d：%s" % (attempt + 1, retries, exc), file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def normalize(row, table_type):
    cid = row.get("ID") or ""
    kind = row.get("ZYCATE") or table_type
    return {
        "cmkb_id": cid,
        "generic_name_zh": row.get("CHINESENAME") or "",
        "drug_kind": kind,
        "indications": row.get("INDICATIONSONE") or "",
        "indications_extra": row.get("INDICATIONSTWO") or "",
        "contraindications": row.get("CONTRAINDICATIONS") or "",
        "interactions": row.get("INTERACTIONDRUG") or "",
        "source": "CMKB",
        "source_url": DETAIL.format(id=urllib.parse.quote(cid), type=kind),
        "detail_available": False,  # 正文需登录，见文件头限制说明
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="", help="关键词检索，留空为全量")
    ap.add_argument("--table-type", default="yw", choices=["yw", "hxyw", "zcy", "all"])
    ap.add_argument("--pagesize", type=int, default=100, help="每页条数（服务端支持 100）")
    ap.add_argument("--max-pages", type=int, default=0, help="最多抓取页数，0 为不限")
    ap.add_argument("--delay", type=float, default=1.5, help="翻页间隔秒数")
    ap.add_argument("--force", action="store_true", help="覆盖已存在产物")
    args = ap.parse_args()

    if os.path.exists(OUT_JSON) and not args.force:
        print("已存在 %s，加 --force 覆盖" % OUT_JSON)
        return 0

    opener = build_opener()
    req = urllib.request.Request(HOST + "/index", headers={"User-Agent": UA})
    with opener.open(req, timeout=30) as r:
        r.read()

    rows, total, page = {}, None, 1
    while True:
        js = fetch_page(opener, args.table_type, args.query, page, args.pagesize)
        data = js.get("data") or []
        if total is None:
            total = js.get("recordsTotal")
            print("命中 %s 条（关键词=%r，tableType=%s）" % (total, args.query, args.table_type))
        added = 0
        for row in data:
            kind = row.get("ZYCATE")
            if args.table_type == "all" and kind not in DRUG_KINDS:
                continue
            rec = normalize(row, args.table_type)
            if rec["cmkb_id"] and rec["cmkb_id"] not in rows:
                rows[rec["cmkb_id"]] = rec
                added += 1
        print("  第 %d 页：返回 %d 条，新增 %d 条，累计 %d" % (page, len(data), added, len(rows)))
        if not data or added == 0:
            break
        if args.max_pages and page >= args.max_pages:
            break
        if total and len(rows) >= int(total):
            break
        page += 1
        time.sleep(args.delay)

    os.makedirs(OUT_DIR, exist_ok=True)
    records = [rows[k] for k in sorted(rows)]
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "CMKB",
                "endpoint": LIST_API,
                "table_type": args.table_type,
                "query": args.query,
                "pagesize": args.pagesize,
                "fetched_count": len(records),
                "server_total": int(total) if total else None,
                "fields": ["cmkb_id", "generic_name_zh", "drug_kind", "indications",
                           "indications_extra", "contraindications", "interactions"],
                "warning": "详情正文需登录；站点版权所有，仅限内部参考，对外分发需授权",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
    print("写入 %s（%d 条）" % (OUT_JSON, len(records)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
