# -*- coding: utf-8 -*-
"""步骤5（kgdrug）：解码 gStore 建库二进制 → cache/kgdrug/triples.jsonl

格式（已逆向并经 nodes.dat 交叉验证）：
- nodes.dat: 顺序 [4字节大端长度][UTF-8 字符串]，字符串起始偏移即三元组中引用的"地址"
- SPO.dat / POS.dat / OSP.dat: 8 字节页头 + 24 字节定长记录（3 个 8 字节大端 = nodes.dat 偏移）
  页头/空闲区用谓词白名单 + "三个偏移均必须命中 nodes.dat 字符串起点"做过滤

用法：python tools/5_decode_kgdrug.py
"""
import json
import os
import struct
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw", "kgdrug")
CACHE = os.path.join(BASE, "cache", "kgdrug")

# 需求清单 §6.1 之外的 gStore 内部元数据谓词，一并保留
PRED_LOCAL = {
    "type", "label", "subClassOf", "sameAs",
    "proname", "gazhzh", "zhiliao", "zzname", "haszhengzhuang", "needcure",
    "zzyufang", "bingyin", "cure", "relatedisease", "pzwh", "jibingname",
    "gaishu", "zzbingyin", "zzgaishu", "bingfazheng", "yufang",
}


def parse_nodes(path):
    """返回 (offset→字符串 dict, 文件大小)"""
    with open(path, "rb") as f:
        data = f.read()
    off2str, off, n = {}, 0, len(data)
    while off + 4 <= n:
        ln = struct.unpack_from(">I", data, off)[0]
        if ln == 0 or off + 4 + ln > n:
            break
        off2str[off] = data[off + 4:off + 4 + ln].decode("utf-8", "replace")
        off += 4 + ln
    return off2str, n


def local_name(uri):
    s = uri.strip("<>")
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def decode_index(path, off2str):
    """按 8 字节步进扫描，命中即前进 24 字节（记录），否则前进 8 字节（页头/空闲区）"""
    with open(path, "rb") as f:
        raw = f.read()
    n, pos, out = len(raw), 0, []
    while pos + 24 <= n:
        a, b, c = struct.unpack_from(">QQQ", raw, pos)
        if a in off2str and b in off2str and c in off2str:
            ps = off2str[b]
            if ps.startswith("<") and ps.endswith(">") and local_name(ps) in PRED_LOCAL:
                out.append((a, b, c))
                pos += 24
                continue
        pos += 8
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    off2str, ndsize = parse_nodes(os.path.join(RAW, "nodes.dat"))
    print("nodes.dat: %d 个节点字符串, %d 字节" % (len(off2str), ndsize))

    sets = {}
    for fn in ["SPO.dat", "POS.dat", "OSP.dat"]:
        recs = decode_index(os.path.join(RAW, fn), off2str)
        sets[fn] = set(recs)
        print("  %-8s 解码 %d 条（去重 %d）" % (fn, len(recs), len(sets[fn])))

    spo = sets["SPO.dat"]
    # 交叉校验：POS/OSP 是同一批三元组的排列，按各自顺序还原后应一致
    pos_perm = {(s, p, o) for (p, o, s) in sets["POS.dat"]}
    osp_perm = {(s, p, o) for (o, s, p) in sets["OSP.dat"]}
    print("  一致性: SPO=%d, POS还原=%d, OSP还原=%d, 交集=%d"
          % (len(spo), len(pos_perm), len(osp_perm), len(spo & pos_perm & osp_perm)))

    records = []
    for (a, b, c) in sorted(spo):
        records.append({"s": off2str[a], "p": off2str[b], "o": off2str[c]})

    out = os.path.join(CACHE, "triples.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pred = Counter(r["p"] for r in records)
    print("\n三元组总数: %d" % len(records))
    print("谓词分布:")
    for k, v in pred.most_common():
        print("  %-22s %d" % (local_name(k), v))
    print("DONE ->", out)


if __name__ == "__main__":
    sys.exit(main())
