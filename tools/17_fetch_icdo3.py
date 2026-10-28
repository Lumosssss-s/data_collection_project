# -*- coding: utf-8 -*-
"""tools/17_fetch_icdo3.py

抓取并校验国家卫健委 HQMS 2.0 资料包中的《肿瘤形态学编码（M码）国家临床版2.0》，
落地到 fetched/codetables/nhc/，作为 ICD-O-3 补码的唯一数据源（供 18_icdo3_mapping.py 读取）。

步骤：
  1) 下载资料包 → fetched/codetables/hqms_2.0.rar
  2) 解压              → cache/codetables/_unzipped/（bsdtar 支持 rar；无则退回 7z）
  3) 定位「（3）肿瘤形态学编码（M码）…xlsx」并校验表头 / 编码格式 / 名称 / 行为码 / 行数
  4) 校验通过 → 复制到 fetched/codetables/nhc/
  5) 校验报告（含 SHA-256）→ cache/codetables/icdo3_source_check.json

幂等：本地已有且校验通过时跳过下载；加 --force 强制重新下载。
运行：python tools/17_fetch_icdo3.py [--force]
依赖：openpyxl（读 xlsx）；tar（Windows 自带 bsdtar）或 7z
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

from openpyxl import load_workbook

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FETCH_DIR = os.path.join(BASE, "fetched", "codetables")
RAR_PATH = os.path.join(FETCH_DIR, "hqms_2.0.rar")
XLSX_DIR = os.path.join(FETCH_DIR, "nhc")
XLSX_PATH = os.path.join(XLSX_DIR, "（3）肿瘤形态学编码（M码）-国家临床版2.0.xlsx")
WORK_DIR = os.path.join(BASE, "cache", "codetables", "_unzipped")
REPORT = os.path.join(BASE, "cache", "codetables", "icdo3_source_check.json")

SOURCE_PAGE = "https://www.hqms.org.cn/usp/downFile.html"
SOURCE_URL = "https://doc.hqms.org.cn/医院质量监测系统（HQMS）2.0页面下载资料包.rar"
SOURCE_NAME = "医院质量监测系统（HQMS）2.0页面下载资料包"

# 2026-10-27 版基线：1,427 条；行数变化只告警，不判失败（官方可能更新）
EXPECTED_ROWS = 1427
# 2026-10-27 版文件 SHA-256；与基线不一致时提示复核下游映射
BASELINE_SHA256 = "52d994d3dca95a5f16199ae9eb898eafae96d262e4e91384d241cde81079f7c2"

CODE_RE = re.compile(r"^M(\d{5})/(\d)$")
BEHAVIOR_OK = {"0", "1", "2", "3", "6"}  # 良性/动态未定/原位/恶性/转移
NAME_KEY = "肿瘤形态学"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download():
    """下载 rar 到 fetched/codetables/，先写 .part 再改名，避免半截文件。"""
    os.makedirs(FETCH_DIR, exist_ok=True)
    url = urllib.parse.quote(SOURCE_URL, safe=":/")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    part = RAR_PATH + ".part"
    print("下载 %s" % SOURCE_URL)
    with urllib.request.urlopen(req, timeout=90, context=CTX) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        with open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
    if total and got != total:
        raise SystemExit("下载不完整：%d/%d 字节，请重试或改用 --force" % (got, total))
    os.replace(part, RAR_PATH)
    print("  已保存 %s（%d 字节）" % (RAR_PATH, got))


def extract_rar():
    """解压到 cache/codetables/_unzipped/，返回解压目录。"""
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    tar = shutil.which("tar")
    if tar:
        p = subprocess.run([tar, "-xf", RAR_PATH, "-C", WORK_DIR],
                           capture_output=True, text=True, errors="replace")
        if p.returncode == 0:
            return WORK_DIR
        tar_err = (p.stderr or "").strip().splitlines()
        tar_err = tar_err[-1] if tar_err else "returncode=%d" % p.returncode
    else:
        tar_err = "未找到 tar"

    seven = shutil.which("7z") or shutil.which("7za")
    if seven:
        p = subprocess.run([seven, "x", RAR_PATH, "-o" + WORK_DIR, "-y"],
                           capture_output=True, text=True, errors="replace")
        if p.returncode == 0:
            return WORK_DIR
        seven_err = (p.stderr or "").strip().splitlines()
        seven_err = seven_err[-1] if seven_err else "returncode=%d" % p.returncode
    else:
        seven_err = "未找到 7z"

    raise SystemExit(
        "解压失败（tar: %s；7z: %s）。\n"
        "请手动解压 %s，把「（3）肿瘤形态学编码（M码）…xlsx」放到 %s 后重跑本脚本做校验。"
        % (tar_err, seven_err, RAR_PATH, XLSX_PATH))


def find_mcode(work):
    """在解压目录中按文件名关键字定位 M 码 xlsx。"""
    for root, _dirs, files in os.walk(work):
        for fn in files:
            if NAME_KEY in fn and fn.lower().endswith(".xlsx") and not fn.startswith("~$"):
                return os.path.join(root, fn)
    raise SystemExit("解压目录中未找到含「%s」的 xlsx：%s" % (NAME_KEY, work))


def validate(path):
    """校验表头、编码格式、名称、行为码、行数；返回结构化结果。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = wb.sheetnames[0]
        rows = wb[sheet].iter_rows(values_only=True)
        header = next(rows, (None, None))
        header = (header + (None, None))[:2]
        header_ok = NAME_KEY in str(header[0] or "") and "名称" in str(header[1] or "")

        data, empty_names, invalid = 0, 0, []
        behavior = Counter()
        for r in rows:
            code = str(r[0]).strip() if r and r[0] else ""
            name = str(r[1]).strip() if len(r) > 1 and r[1] else ""
            if not code and not name:
                continue  # 跳过尾部空行
            data += 1
            if not name:
                empty_names += 1
            m = CODE_RE.match(code)
            if not m:
                invalid.append({"code": code, "name": name, "reason": "编码格式非 M#####/x"})
                continue
            behavior[m.group(2)] += 1
            if m.group(2) not in BEHAVIOR_OK:
                invalid.append({"code": code, "name": name, "reason": "行为码不在 /0 /1 /2 /3 /6"})
    finally:
        wb.close()

    ok = header_ok and not invalid and empty_names == 0 and data > 0
    return {
        "path": path,
        "sheet": sheet,
        "header": [str(x) if x is not None else "" for x in header],
        "header_ok": header_ok,
        "data_rows": data,
        "rows_expected": EXPECTED_ROWS,
        "rows_match_expected": data == EXPECTED_ROWS,
        "empty_names": empty_names,
        "invalid_count": len(invalid),
        "invalid_examples": invalid[:5],
        "behavior_counts": dict(sorted(behavior.items())),
        "ok": ok,
    }


def write_report(info, status):
    archive = {
        "path": RAR_PATH,
        "bytes": os.path.getsize(RAR_PATH) if os.path.exists(RAR_PATH) else None,
        "sha256": sha256(RAR_PATH) if os.path.exists(RAR_PATH) else None,
    }
    table = dict(info)
    table["bytes"] = os.path.getsize(info["path"])
    table["sha256"] = sha256(info["path"])
    table["matches_baseline_sha256"] = table["sha256"] == BASELINE_SHA256

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "source_page": SOURCE_PAGE,
        "source_url": SOURCE_URL,
        "source_name": SOURCE_NAME,
        "baseline": {"rows": EXPECTED_ROWS, "sha256": BASELINE_SHA256},
        "archive": archive,
        "code_table": table,
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def print_summary(table):
    print("M 码表：%s" % table["path"])
    print("  工作表        : %s" % table["sheet"])
    print("  表头          : %s" % " / ".join(table["header"]))
    print("  数据行        : %d（基线 %d）%s" % (
        table["data_rows"], table["rows_expected"],
        "" if table["rows_match_expected"] else " ← 与基线不一致，请复核"))
    print("  行为码分布    : %s" % ", ".join("/%s %d" % (k, v) for k, v in table["behavior_counts"].items()))
    print("  编码格式/名称 : %s" % (
        "全部合法" if table["invalid_count"] == 0 and table["empty_names"] == 0
        else "非法 %d 条 / 空名称 %d 条" % (table["invalid_count"], table["empty_names"])))
    print("  SHA-256       : %s%s" % (
        table["sha256"],
        "" if table["matches_baseline_sha256"] else "（与基线不同，官方码表可能已更新）"))
    print("  校验报告      : %s" % REPORT)


def main():
    ap = argparse.ArgumentParser(description="抓取并校验 NHC 肿瘤形态学（M 码）表")
    ap.add_argument("--force", action="store_true", help="忽略本地缓存，强制重新下载")
    args = ap.parse_args()

    # 1) 本地已有且校验通过 → 直接复用，不联网
    if os.path.exists(XLSX_PATH) and not args.force:
        info = validate(XLSX_PATH)
        if info["ok"]:
            print("[SKIP] 本地 M 码表已存在且校验通过，跳过下载（--force 可强制重下）")
            print_summary(write_report(info, "cached")["code_table"])
            return 0
        print("[WARN] 本地文件校验未通过（%s），重新抓取" % XLSX_PATH)

    # 2) 确保压缩包存在 → 解压定位 → 校验 → 落地
    if args.force or not os.path.exists(RAR_PATH):
        download()
    else:
        print("[SKIP] 复用已下载压缩包 %s（--force 可强制重下）" % RAR_PATH)

    src = find_mcode(extract_rar())
    info = validate(src)
    if not info["ok"]:
        print_summary(write_report(info, "failed")["code_table"])
        for bad in info["invalid_examples"]:
            print("  [FAIL] %s %s — %s" % (bad["code"], bad["name"], bad["reason"]))
        print("\n校验未通过，未写入 %s" % XLSX_PATH)
        return 1

    os.makedirs(XLSX_DIR, exist_ok=True)
    shutil.copy2(src, XLSX_PATH)
    print_summary(write_report(validate(XLSX_PATH), "ok")["code_table"])
    shutil.rmtree(WORK_DIR, ignore_errors=True)  # 资料包内还有 exe/doc 等无关文件，用完即删
    print("\n已写入 %s" % XLSX_PATH)
    print("下一步：python tools/18_icdo3_mapping.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
