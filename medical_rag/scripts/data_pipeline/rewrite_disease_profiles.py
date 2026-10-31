"""A3 方案 2：把已有章节摘录改写为中文专业版 + 生成患者版（LLM，项目内通道）。

输入：data/clean/disease_profiles/<disease_id>.json（方案 1 的规则版）
输出：data/intermediate/disease_rewrite/<disease_id>.json（宿主机再回写 data/clean）

约束：
  - 只用给定摘录中的信息，禁止补充摘录未出现的药物 / 剂量 / 数字；
  - 摘录与章节主题不符或信息不足时输出空串，该节保持 null 并记缺口；
  - 患者版：句均 ≤40 字、专业词括注、不出现剂量与诊断结论；
  - 幂等：disease_rewrite_progress.json 记录已完成 (disease_id, section, kind)。

用法（容器内）：
  python scripts/data_pipeline/rewrite_disease_profiles.py --limit 2   # 试跑
  python scripts/data_pipeline/rewrite_disease_profiles.py             # 全量
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from typing import Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

PROFILE_DIR = os.path.join(BASE_DIR, "data", "clean", "disease_profiles")
OUT_DIR = os.path.join(BASE_DIR, "data", "intermediate", "disease_rewrite")
PROGRESS = os.path.join(BASE_DIR, "data", "intermediate", "disease_rewrite_progress.json")

TARGETS = ["DIS-LUNG-001", "DIS-COLORECTAL-001"]

# 章节中文名与建议字数（《医疗数据需求清单》A3 §②）
SECTIONS: Dict[str, Dict] = {
    "overview": {"label": "概述", "words": 120},
    "epidemiology": {"label": "流行病学", "words": 220},
    "etiology": {"label": "病因与危险因素", "words": 220},
    "pathophysiology": {"label": "病理生理", "words": 220},
    "pathology_subtypes": {"label": "病理分型与分子分型", "words": 300},
    "symptoms_early": {"label": "早期症状", "words": 140},
    "symptoms_late": {"label": "晚期症状", "words": 140},
    "signs": {"label": "体征", "words": 140},
    "workup": {"label": "检查与评估", "words": 250},
    "diagnosis": {"label": "诊断", "words": 300},
    "differential": {"label": "鉴别诊断", "words": 250},
    "staging": {"label": "分期", "words": 250},
    "treatment": {"label": "治疗", "words": 450},
    "complications": {"label": "并发症", "words": 180},
    "prognosis": {"label": "预后", "words": 220},
    "followup": {"label": "随访", "words": 220},
    "prevention": {"label": "预防", "words": 180},
    "screening": {"label": "筛查", "words": 180},
    "patient_education": {"label": "患者教育", "words": 220},
    "care_seeking": {"label": "就医指引", "words": 150},
}

PRO_PROMPT = """你是肿瘤学临床编辑。请依据下面的指南原文摘录，撰写「{disease}·{label}」的中文专业版介绍。

要求：
1. 只使用摘录中的信息；摘录未出现的药物名、剂量、具体数字一律不得补充；
2. 篇幅约 {words} 字；
3. 保留关键限定条件（分期、人群、证据等级），必要时在句末标注来源编号（如【来源 REC-xxx】）；
4. 若摘录与本节主题不符或信息不足以支撑本节，只输出空字符串（不要编造）。

只输出正文，不要标题、不要解释。

摘录：
{excerpt}"""

PATIENT_PROMPT = """把下面这段肿瘤专业内容改写成面向患者的通俗说明。

要求：
1. 每句不超过 40 字；
2. 专业术语后用括号给出通俗解释；
3. 不出现具体剂量、处方、检查结论或「确诊」等判断；
4. 篇幅约 {words} 字；不写标题。

只输出正文。

专业内容：
{pro}"""


def _load_progress() -> Dict[str, str]:
    if os.path.exists(PROGRESS):
        return json.load(open(PROGRESS, encoding="utf-8"))
    return {}


def _save_progress(p: Dict[str, str]) -> None:
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    json.dump(p, open(PROGRESS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _clean(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-z]*\n|```$", "", t).strip()
    t = re.sub(r"^(正文|专业版|患者版)[:：]\s*", "", t).strip()
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    return t


# kgdrug 2018 科普文本改写而来的节：必须显式标注时效与可信度，避免被当成现行指南
_KGD_MARK = "（本节依据 kgdrug 2018 科普资料改写，数据与表述可能过时，仅供背景参考）\n"


def _looks_bad(text: str) -> bool:
    """空输出、拒绝式回答或明显跑题，都视为无效改写。"""
    if len(text) < 40:
        return True
    if any(k in text[:40] for k in ("无法", "抱歉", "摘录中未", "没有提供相关信息")):
        return True
    return len(re.findall(r"[\u4e00-\u9fff]", text)) < len(text) * 0.5


def main() -> None:
    ap = argparse.ArgumentParser(description="A3 方案 2：章节中文改写 + 患者版")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个章节（试跑）")
    ap.add_argument("--retries", type=int, default=2)
    args = ap.parse_args()

    from utils.llm_client import chat

    os.makedirs(OUT_DIR, exist_ok=True)
    progress = _load_progress()

    for did in TARGETS:
        path = os.path.join(PROFILE_DIR, f"{did}.json")
        if not os.path.exists(path):
            print(f"跳过 {did}：档案不存在")
            continue
        profile = json.load(open(path, encoding="utf-8"))
        disease = profile["name_canonical"]
        out = {
            "disease_id": did,
            "name_canonical": disease,
            "sections": {},
            "patient_version": {},
            "evidence_excerpts": {},
            "failed": [],
        }
        filled = [(k, v) for k, v in (profile.get("sections") or {}).items() if v]
        if args.limit:
            filled = filled[:args.limit]

        for sec, excerpt in filled:
            meta = SECTIONS.get(sec)
            if not meta:
                continue
            key_pro = f"{did}|{sec}|pro"
            key_pat = f"{did}|{sec}|patient"
            pro_text = ""

            if progress.get(key_pro):
                pro_text = progress[key_pro] if isinstance(progress[key_pro], str) else ""
            else:
                prompt = PRO_PROMPT.format(disease=disease, label=meta["label"],
                                           words=meta["words"], excerpt=excerpt[:2500])
                for _ in range(args.retries + 1):
                    try:
                        pro_text = _clean(chat(prompt, temperature=0.2, max_tokens=900))
                        if not _looks_bad(pro_text):
                            break
                    except Exception as e:
                        print(f"    {did}/{sec} 专业版失败: {type(e).__name__} {str(e)[:60]}")
                        time.sleep(2)
                else:
                    pro_text = ""

            if not pro_text or _looks_bad(pro_text):
                out["failed"].append(f"{sec}: 专业版改写失败，保留原摘录")
                continue

            if "kgdrug" in excerpt:
                pro_text = _KGD_MARK + pro_text
            out["sections"][sec] = pro_text
            out["evidence_excerpts"][sec] = excerpt

            if progress.get(key_pat):
                patient_text = progress[key_pat] if isinstance(progress[key_pat], str) else ""
            else:
                pprompt = PATIENT_PROMPT.format(words=max(120, meta["words"] // 2), pro=pro_text[:1500])
                patient_text = _clean(chat(pprompt, temperature=0.2, max_tokens=700))
            if patient_text and not _looks_bad(patient_text):
                out["patient_version"][sec] = patient_text
            progress[key_pro] = pro_text
            progress[key_pat] = patient_text
            print(f"  ✓ {did} {meta['label']}：专业 {len(pro_text)} 字 / 患者 {len(patient_text)} 字",
                  flush=True)

        with open(os.path.join(OUT_DIR, f"{did}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        _save_progress(progress)
        print(f"{did} 输出完成：{len(out['sections'])} 节，患者版 {len(out['patient_version'])} 节，失败 {len(out['failed'])}")

    _save_progress(progress)


if __name__ == "__main__":
    main()
