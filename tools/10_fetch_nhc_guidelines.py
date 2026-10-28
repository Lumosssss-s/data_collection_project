# -*- coding: utf-8 -*-
"""步骤10（guidelines）：抓取国家卫健委「肿瘤和血液病相关病种诊疗指南（2022年版）」通知页全部附件
→ raw/guidelines/<5 癌种>/（超出 5 癌种者 → raw/_deprecated/guidelines/other/），
  并把 5 癌种范围的文件录入 data/clean/guidelines/。

数据源：https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930.shtml
        国家卫生健康委办公厅 国卫办医函〔2022〕104号，2022-04-11 公开，共 21 份附件 PDF。

说明：
- 通知页 HTML 有 WAF 脚本防护（直接 GET 返回 412），但附件 PDF 可直连下载；
  因此脚本内置附件清单（与原页逐条核对），仅在页内解析成功时用页内结果覆盖。
- 全部 21 份都下载归档；只对 lung / breast / gastric / thyroid（+ 项目 5 癌种范围）生成元数据，
  其余癌种与血液病指南存入 raw/_deprecated/guidelines/other/，不录入（超出「仅 5 癌种」硬口径，
  且按项目约定「无产出文件一律入 _deprecated」，便于区分与清理）。
- 元数据复用 tools/9_guidelines_to_json.py 的 build_record（字段结构、SHA-256、文本自检一致）。

用法：
    python tools/10_fetch_nhc_guidelines.py            # 下载 + 录入
    python tools/10_fetch_nhc_guidelines.py --no-download   # 只用已下载文件重新录入
"""
import json
import os
import re
import sys

import requests

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(TOOLS_DIR)
RAW_DIR = os.path.join(BASE, "raw", "guidelines")
CACHE_DIR = os.path.join(BASE, "cache", "guidelines")
MANIFEST_OUT = os.path.join(CACHE_DIR, "nhc_2022_attachments.json")

PAGE_URL = "https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930.shtml"
FILE_PREFIX = "https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930/files/"

ISSUER = "中华人民共和国国家卫生健康委员会"
PUBLISH_DATE = "2022-04-11"      # 通知公开时间；文件签发日为 2022-04-03
SOURCE_VERSION = "2022"
DOC_DATE_TAG = "20261025"

LICENSE_NOTE = ("国家卫健委官网公开文件（国卫办医函〔2022〕104号，2022-04-11 公开），公开可引用，"
                "引用需标注出处；仅限非商业竞赛使用。原文：%s" % PAGE_URL)

# (原页附件序号, 标题, PDF 文件名, 英文短名, 癌种码或 None)
ATTACHMENTS = [
    (1, "原发性肺癌诊疗指南（2022年版）", "1732863054387_68585.pdf", "lung", "lung"),
    (2, "膀胱癌诊疗指南（2022年版）", "1732863054293_85916.pdf", "bladder", None),
    (3, "胃癌诊疗指南（2022年版）", "1732863054755_83603.pdf", "gastric", "gastric"),
    (4, "食管癌诊疗指南（2022年版）", "1732863055411_46079.pdf", "esophagus", None),
    (5, "胰腺癌诊治指南（2022年版）", "1732863054816_84219.pdf", "pancreas", None),
    (6, "肾癌诊疗指南（2022年版）", "1732863054641_51509.pdf", "kidney", None),
    (7, "乳腺癌诊疗指南（2022年版）", "1732863054702_65919.pdf", "breast", "breast"),
    (8, "子宫内膜癌诊疗指南（2022年版）", "1732863054971_19139.pdf", "endometrium", None),
    (9, "宫颈癌诊疗指南（2022年版）", "1732863055490_18566.pdf", "cervix", None),
    (10, "卵巢癌诊疗指南（2022年版）", "1732863054558_17204.pdf", "ovary", None),
    (11, "前列腺癌诊疗指南（2022年版）", "1732863055004_37946.pdf", "prostate", None),
    (12, "甲状腺癌诊疗指南（2022版）", "1732863055520_88237.pdf", "thyroid", "thyroid"),
    (13, "脑胶质瘤诊疗指南（2022年版）", "1732863055155_82056.pdf", "glioma", None),
    (14, "淋巴瘤诊疗指南（2022年版）", "1732863055082_17747.pdf", "lymphoma", None),
    (15, "黑色素瘤诊疗指南（2022年版）", "1732863054447_72541.pdf", "melanoma", None),
    (16, "弥漫性大B细胞淋巴瘤诊疗指南（2022年版）", "1732863055344_39697.pdf", "dlbcl", None),
    (17, "骨髓增生异常综合征伴原始细胞增多（MDS-EB）诊疗指南（2022年版）", "1732863055128_24413.pdf", "mds_eb", None),
    (18, "慢性髓性白血病诊疗指南（2022年版）", "1732863054519_15977.pdf", "cml", None),
    (19, "血友病A诊疗指南（2022年版）", "1732863055262_86253.pdf", "hemophilia_a", None),
    (20, "慢性淋巴细胞白血病-小淋巴细胞淋巴瘤诊疗指南（2022年版）", "1732863055385_61833.pdf", "cll_sll", None),
    (21, "自身免疫性溶血性贫血诊疗指南（2022年版）", "1732863054931_49765.pdf", "aiha", None),
]

SCOPE_CODE = {"lung": "LUNG", "breast": "BREAST", "colorectal": "CRC",
              "gastric": "GAS", "thyroid": "THY"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": PAGE_URL,
}


def load_tool9():
    """复用步骤9 的 build_record（字段结构 / SHA-256 / 文本自检保持同源）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "g9", os.path.join(TOOLS_DIR, "9_guidelines_to_json.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_page(url):
    """尝试从通知页解析附件清单；页面被 WAF 拦截时返回空列表（脚本改用内置清单）。"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        print("[warn] 通知页请求失败（%s），改用内置附件清单" % exc)
        return []
    if r.status_code != 200 or "$_ts" in r.text[:2000]:
        print("[warn] 通知页遭 WAF 拦截（HTTP %d），改用内置附件清单" % r.status_code)
        return []
    links = re.findall(r'href="([^"]*/files/[A-Za-z0-9_]+\.pdf)"[^>]*>([^<]+)</a>', r.text)
    out = []
    for href, title in links:
        out.append((title.strip(), href if href.startswith("http") else "https://www.nhc.gov.cn" + href))
    print("通知页解析到 %d 个附件" % len(out))
    return out


def download(url, dest):
    """下载 PDF，校验 %PDF 头与大小，返回字节数；失败抛异常。"""
    tmp = dest + ".part"
    with requests.get(url, headers=HEADERS, timeout=120, stream=True) as r:
        r.raise_for_status()
        total = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                total += len(chunk)
    with open(tmp, "rb") as f:
        head = f.read(8)
    if not head.startswith(b"%PDF"):
        os.remove(tmp)
        raise ValueError("返回内容不是 PDF（首字节 %r）" % head)
    if total < 50 * 1024:
        os.remove(tmp)
        raise ValueError("文件过小（%d 字节），疑似非正文" % total)
    os.replace(tmp, dest)
    return total


def main():
    no_download = "--no-download" in sys.argv
    g9 = load_tool9()
    os.makedirs(CACHE_DIR, exist_ok=True)

    page_links = [] if no_download else parse_page(PAGE_URL)
    if len(page_links) >= 10:
        # 页内解析成功：标题匹配内置表拿到文件名/癌种，未匹配的归入 other
        by_title = {a[1]: a for a in ATTACHMENTS}
        items = []
        for i, (title, url) in enumerate(page_links, 1):
            hit = by_title.get(title)
            if hit:
                items.append((i, title, hit[2], hit[3], hit[4]))
            else:
                items.append((i, title, url.rsplit("/", 1)[-1], "other_%02d" % i, None))
    else:
        items = ATTACHMENTS

    manifest, records_written, failures = [], [], []

    for idx, title, fname, slug, ctype in items:
        url = FILE_PREFIX + fname
        if ctype:
            dest_dir = os.path.join(RAW_DIR, ctype)
        else:
            # 超出 5 癌种：不录入、无产出 → 统一归入 _deprecated
            dest_dir = os.path.join(BASE, "raw", "_deprecated", "guidelines", "other")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "nhc2022_%02d_%s.pdf" % (idx, slug))
        rel_path = os.path.relpath(dest, BASE).replace(os.sep, "/")

        entry = {"index": idx, "title": title, "url": url, "file_path": rel_path,
                 "cancer_type": ctype, "status": ""}

        if os.path.exists(dest) and os.path.getsize(dest) > 50 * 1024:
            entry["status"] = "cached"
        elif no_download:
            entry["status"] = "missing"
            failures.append((title, "本地无文件"))
            manifest.append(entry)
            continue
        else:
            try:
                size = download(url, dest)
                entry["status"] = "downloaded"
                entry["bytes"] = size
            except Exception as exc:                      # noqa: BLE001 下载失败不中断整批
                entry["status"] = "failed"
                entry["error"] = str(exc)
                failures.append((title, str(exc)))
                manifest.append(entry)
                print("[fail] %-24s %s" % (slug, exc))
                continue

        pages, chars = g9.check_text(dest)
        entry.update({"pages": pages, "chars": chars,
                      "doc_hash": g9.sha256(dest)})

        if ctype:
            # 仅 5 癌种子集录入；文本自检不通过者退回
            if chars < g9.MIN_TEXT_CHARS:
                entry["status"] += "/text_fail"
                failures.append((title, "文本可提取性自检不通过（%d 字符）" % chars))
            else:
                seq = sum(1 for m in manifest if m.get("cancer_type") == ctype) + 1
                item = {
                    "file_path": rel_path,
                    "doc_id": "DOC-%s-NHC-%03d" % (SCOPE_CODE[ctype], seq),
                    "title": title,
                    "doc_type": "standard",
                    "issuer": ISSUER,
                    "publish_date": PUBLISH_DATE,
                    "cancer_types": [ctype],
                    "source_version": SOURCE_VERSION,
                    "license_note": LICENSE_NOTE,
                }
                rec, _, _ = g9.build_record(item)
                out_name = "guidelines_%s_%s_%s.json" % (ctype, SOURCE_VERSION, DOC_DATE_TAG)
                out = os.path.join(BASE, "data", "clean", "guidelines", out_name)
                with open(out, "w", encoding="utf-8") as f:
                    json.dump([rec], f, ensure_ascii=False, indent=2)
                records_written.append((rec["doc_id"], title, out))
                entry["doc_id"] = rec["doc_id"]
                entry["status"] += "/recorded"

        print("[%s] %-2d %-30s %3d 页 %7d 字符" % (entry["status"], idx, title, pages, chars))
        manifest.append(entry)

    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n附件总数: %d | 下载成功: %d | 录入: %d | 失败: %d" % (
        len(manifest),
        sum(1 for m in manifest if "downloaded" in m["status"] or m["status"] == "cached"),
        len(records_written), len(failures)))
    for doc_id, title, out in records_written:
        print("  %-18s %s" % (doc_id, os.path.basename(out)))
    for title, why in failures:
        print("  [未完成] %-30s %s" % (title, why))
    print("\n清单 ->", MANIFEST_OUT)


if __name__ == "__main__":
    main()
