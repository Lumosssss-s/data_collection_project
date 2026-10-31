# -*- coding: utf-8 -*-
"""槽位守卫回归测试 + 修复前后同批样本命中差异（零 token，不调模型）。

用法（容器内，工作目录 /app）：
    python scripts/cache/test_slot_guard.py            # 只跑用例
    python scripts/cache/test_slot_guard.py --diff     # 用例 + 标定样本前后差异

说明：历史会话里的守卫用例是临时脚本，未落盘；本文件按既有标定样本（calib_report.json
的 negative 分组）重建 11 条回归用例，并新增疑问结构/数字写法/术语含「不」等用例。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.semantic_cache import extract_slots, slot_conflict  # noqa: E402

# (名称, 查询句, 缓存条目句, 期望是否冲突)
CASES = [
    # ---- 回归：既有 11 条（按 calib_report.json 的 negative 分组重建）----
    ("分期 III vs II", "结肠癌III期辅助化疗方案有哪些", "结肠癌II期辅助化疗方案有哪些", True),
    ("分期 III vs IV", "肺癌III期能手术吗", "肺癌IV期能手术吗", True),
    ("分期 II vs III", "结肠癌II期需要化疗吗", "结肠癌III期需要化疗吗", True),
    ("线数 一线 vs 二线", "肺癌一线治疗方案有哪些", "肺癌二线治疗方案有哪些", True),
    ("线数 新辅助 vs 术后辅助", "直肠癌新辅助放化疗方案", "直肠癌术后辅助放化疗方案", True),
    ("药品 奥沙利铂 vs 紫杉醇", "结肠癌奥沙利铂方案", "结肠癌紫杉醇方案", True),
    ("癌种 肺癌 vs 结肠癌", "肺癌一线治疗方案有哪些", "结肠癌一线治疗方案有哪些", True),
    ("标志物 KRAS 野生 vs 突变", "结肠癌KRAS野生型用西妥昔单抗", "结肠癌KRAS突变型用西妥昔单抗", True),
    ("标志物 PD-L1 高 vs 低", "肺癌PD-L1高表达免疫治疗", "肺癌PD-L1低表达免疫治疗", True),
    ("标志物 HER2 阳 vs 阴", "乳腺癌HER2阳性靶向治疗", "乳腺癌HER2阴性靶向治疗", True),
    ("线数同义归一", "直肠癌术前化疗方案", "直肠癌新辅助化疗方案", False),

    # ---- 新增：疑问结构不是否定 ----
    ("能不能用X vs 可以用X", "能不能用奥沙利铂", "可以用奥沙利铂", False),
    ("要不要做化疗 vs 需要做化疗", "要不要做化疗", "需要做化疗", False),
    ("是否推荐靶向 vs 推荐靶向", "是否推荐靶向治疗", "推荐靶向治疗", False),
    ("用不用做检查 vs 建议做检查", "用不用做基因检测", "建议做基因检测", False),
    # ---- 新增：真否定仍要拦 ----
    ("不能用X vs 可以用X", "不能用奥沙利铂", "可以用奥沙利铂", True),
    ("不建议手术 vs 可以考虑手术", "不建议手术", "可以考虑手术", True),
    # ---- 新增：分期写法归一 ----
    ("III期 vs 三期", "结肠癌III期辅助化疗方案", "三期结肠癌术后辅助化疗方案", False),
    ("3期 vs III期", "肺癌3期能手术吗", "肺癌III期能手术吗", False),
    ("Ⅲ期(全角) vs II期", "肺癌Ⅲ期能手术吗", "肺癌II期能手术吗", True),
    # ---- 新增：术语里的「不」不是否定 ----
    ("不良反应 vs 副作用", "奥沙利铂的不良反应有哪些", "奥沙利铂副作用有哪些", False),
    ("无进展生存期 归入非否定", "肺癌无进展生存期有多长", "肺癌无进展生存期有多长", False),
]

# 逐条抽取断言：(文本, 期望 neg)
NEG_CASES = [
    ("无进展生存期有多长", False),
    ("奥沙利铂的不良反应有哪些", False),
    ("这个方案不合适怎么办", True),
    ("能不能用奥沙利铂", False),
    ("不能用奥沙利铂", True),
    ("需不需要做化疗", False),
    # ---- 否定词盲区（要求 neg=True）----
    ("没必要做化疗", True),
    ("不需要做化疗", True),
    ("不宜手术", True),
    ("不应化疗", True),
    ("无须放疗", True),
    ("不能耐受化疗", True),
    ("暂不推荐手术", True),
]

# 逐条抽取断言：(文本, 期望 stage 集合)
STAGE_CASES = [
    ("结肠癌III期", {"III"}),
    ("结肠癌三期", {"III"}),
    ("结肠癌３期", {"III"}),
    ("肺癌Ⅲ期", {"III"}),
    ("肺癌ii期", {"II"}),
]


def run_cases() -> int:
    failed = 0
    for name, q, e, expect in CASES:
        reason = slot_conflict(extract_slots(q), extract_slots(e))
        got = reason is not None
        ok = got == expect
        failed += 0 if ok else 1
        flag = "PASS" if ok else "FAIL"
        detail = reason if reason else "-"
        print(f"[{flag}] {name:28s} 冲突={got!s:5s} 期望={expect!s:5s} 原因={detail}")

    print("\n---- 抽取层断言 ----")
    for text, expect_neg in NEG_CASES:
        got = extract_slots(text).get("neg")
        ok = got == expect_neg
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] neg({text})={got} 期望={expect_neg}")

    for text, expect_stage in STAGE_CASES:
        got = set(extract_slots(text).get("stage") or [])
        ok = got == expect_stage
        failed += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] stage({text})={sorted(got)} 期望={sorted(expect_stage)}")

    total = len(CASES) + len(NEG_CASES) + len(STAGE_CASES)
    print(f"\n合计 {total} 条，通过 {total - failed} 条，失败 {failed} 条")
    return failed


def run_diff(tau: float = 0.88) -> None:
    """同一批标定样本上，改动前（报告里存的 conflict）与改动后的命中差异。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "cache", "calib_report.json")
    with open(path, "r", encoding="utf-8") as f:
        report = json.load(f)

    print(f"\n---- 修复前后命中差异（tau={tau}）----")
    before_hits = after_hits = 0
    changed = []
    for group in ("positive", "negative"):
        rows = report.get("pairs", {}).get(group) or []
        for r in rows:
            cos = r["cos"]
            old_conflict = r.get("conflict")
            new_conflict = slot_conflict(extract_slots(r["a"]), extract_slots(r["b"]))
            old_hit = cos >= tau and not old_conflict
            new_hit = cos >= tau and new_conflict is None
            if group == "positive":
                before_hits += 1 if old_hit else 0
                after_hits += 1 if new_hit else 0
                if old_hit != new_hit:
                    changed.append(("positive", r["a"], r["b"], cos, old_hit, new_hit,
                                    old_conflict, new_conflict))
            elif old_hit or new_hit:
                changed.append(("negative(误命中)", r["a"], r["b"], cos, old_hit, new_hit,
                                old_conflict, new_conflict))

        total_pos = len(report.get("pairs", {}).get("positive") or [])
    print(f"正样本命中：改前 {before_hits}/{total_pos} → 改后 {after_hits}/{total_pos}")
    for group, a, b, cos, o, n, oc, nc in changed:
        print(f"  [{group}] cos={cos:.4f}\n     A={a}\n     B={b}\n     改前命中={o}（{oc or '无冲突'}）"
              f"\n     改后命中={n}（{nc or '无冲突'}）")

    # 守卫覆盖变化：负样本里「改前能拦、改后拦不住」的条目必须点名，
    # 它们只因余弦低于阈值才没误命中，属于阈值一旦下调就会暴露的潜在风险。
    print("\n---- 守卫覆盖变化（负样本）----")
    lost = 0
    for r in report.get("pairs", {}).get("negative") or []:
        old_conflict = r.get("conflict")
        new_conflict = slot_conflict(extract_slots(r["a"]), extract_slots(r["b"]))
        if old_conflict and not new_conflict:
            lost += 1
            print(f"  [守卫丢失] cos={r['cos']:.4f} A={r['a']} / B={r['b']}（改前：{old_conflict}）")
    print(f"  守卫丢失共 {lost} 条（余弦 {tau} 以下，故当前不会误命中）")


if __name__ == "__main__":
    fails = run_cases()
    if "--diff" in sys.argv:
        run_diff()
    sys.exit(1 if fails else 0)
