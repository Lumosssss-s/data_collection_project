# disease_profiles 疾病档案目录（A3）

本目录存放 **A3 疾病档案**：面向患者问答的「疾病全景画像」，一个疾病一条记录，专业版为原文摘录，患者版由人工 / LLM 通俗改写。
本批为批次一 · 肺癌试点，输入同为 `DOC-LUNG-NHC-001`（原发性肺癌诊疗指南 2022 年版）。

## 文件

| 文件 | 记录数 | 内容 | 来源 |
|---|---|---|---|
| `disease_profiles_lung_20261028_v2.json` | 6 | **当前版本**：1 个主体档案（肺恶性肿瘤）+ 5 个亚型档案（非小细胞肺癌 / 小细胞肺癌 / 肺腺癌 / 肺鳞状细胞癌 / 微浸润性腺癌），`icd10` 已改 4 位 WHO 码 | 原发性肺癌诊疗指南（2022 年版） |
| `disease_profiles_lung_20261028.json` | 6 | v1（`icd10` 为国家临床版 5 位码 `C34.901`，按 G4 保留比对，下游已不再读取） | 同上 |

赛程内要求「肺癌 ≥20 个 profile」，本批 6 条为骨架，亚型与并发症档案待后续批次补足。

## 字段结构（`disease_profile`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `disease_id` | string | `DIS-<范围码>-<4 位序号>`，如 `DIS-LUNG-0001` |
| `name_canonical` | string | 规范中文名（优先取 A5 `terminology` canonical） |
| `synonyms` | array / null | 别名（如「肺癌」「原发性支气管肺癌」） |
| `name_en` | string / null | 英文名 |
| `icd10` | string / null | ICD-10 编码（4 位 WHO 口径优先，国家临床版 5 位码留在 `annotation`） |
| `icd_o3` | string / null | ICD-O-3 形态学码（`Mxxxx/x`） |
| `category` | enum | `primary_cancer` / `precancerous_lesion` / `borderline_benign_tumor` / `tumor_complication` |
| `body_system` | string | 解剖系统 |
| `department` | array | 建议就诊科室 |
| `sections` | object | 20 个 section 键**全部存在**，无内容写 `null`（不写 `[]` / `""`） |
| `patient_version` | object / null | 患者版通俗改写；规则脚本不生成，恒为 `null` |
| `links` | object | 关联实体：`symptoms` / `drugs` / `checks` / `diseases` / `genes` / `biomarkers` / `guidelines` |
| `section_gaps` | array | 缺口登记，每项 `{section, reason}`；`sections[k]=null` 时必有对应条目 |
| `sources` | array | 来源文档名 + 发文号 |
| `version` / `last_updated` | string / date | G4 版本号（变更时 +1，不覆盖旧文件） |
| `annotation` | object | 抽取脚本名、日期、状态 |

### 20 个 section 键

`overview` / `epidemiology` / `etiology` / `pathophysiology` / `pathology_subtypes` /
`symptoms_early` / `symptoms_late` / `signs` / `workup` / `diagnosis` /
`differential` / `staging` / `treatment` / `complications` / `prognosis` /
`followup` / `prevention` / `screening` / `patient_education` / `care_seeking`

主体档案 `DIS-LUNG-0001` 已填 **17 / 20**，缺口 3 项 + 患者版 1 项：

| 缺口 | 原因 |
|---|---|
| `staging` | 同一疾病跨多个期别，单值 AJCC8 分期不适用；待按 T/N/M 组合建分期映射表 |
| `patient_education` | 指南无患者教育章节，待 CACA / CSCO 或科普来源补齐 |
| `care_seeking` | 指南无就诊指引章节，待补充 |
| `patient_version` | 患者版需 LLM / 人工通俗改写（句均长 ≤40 字、术语括注），规则脚本不生成 |

亚型档案仅 `overview` 与 `pathology_subtypes` 有值，其余 18 项全部 `null` 并在 `section_gaps` 登记「该亚型仅指南病理章节有片段描述，其余 section 待 A1 扩充后抽取」。

### 主体档案取值示例

| 字段 | 值 |
|---|---|
| `disease_id` | `DIS-LUNG-0001` |
| `name_canonical` | 肺恶性肿瘤 |
| `icd10` / `icd_o3` | `C34.9` / `M8010/3`（`annotation.icd10_national = C34.901` 保留国家临床版原码） |
| `category` / `body_system` | `primary_cancer` / 呼吸系统 |
| `department` | 肿瘤内科 / 胸外科 / 放疗科 |
| `links.drugs` | 18 个（阿来替尼 / 奥希替尼 / 帕博利珠单抗 …） |
| `links.genes` | EGFR / ALK / ROS1 / RET / KRAS / BRAF / HER2 / NTRK / PD-L1 / MET |
| `links.checks` | 胸部CT / MRI / 支气管镜 / 纵隔镜 / 胸腔镜 / 痰脱落细胞学检查 / 骨核素扫描 |

## 抽取规则（`tools/22_a3_disease_profile.py`）

1. **章节映射**：`overview` ← 「一、概述」；`etiology` ← 「（一）危险因素」；`workup` ← 「（四）辅助检查」+「（六）病理组织学检查」；`prognosis` ← 「五、预后」；`followup` ← 「六、随访」等。
2. **症状结构化**：15 组关键词匹配，`type` 由「转移 / 侵犯 / 压迫」判 `late`、「肺外 / 副肿瘤 / 杵状指」判 `sign`，其余 `early`；`frequency` 仅在原文出现「常见 / 少见 / 罕见」时填值，否则 `null`（不臆测）。
3. **亚型画像**：`overview` 从「概述 + 组织学分型 + 病理组织学检查」三处候选句择优——占比陈述 > 定义 > 一般描述 > 列举；含其他亚型名、MIA/AIS 专指或治疗检查类表述的句子一律排除，WHO 分型表被挤出的无标点长串由 `is_table_fragment()` 过滤。
4. **实体链接**：药名取 A4 `drug_catalog.generic_name` 全篇匹配；基因取 §6.1 受控词表正则；检查项从完整 workup 原文匹配（避免截断漏项）。
5. **缺口不伪造**：`null` 必须配 `section_gaps` 条目；患者版明确不生成。

抽取审计见 `cache/disease_profiles/a3_extract_audit.json`。

## 待复核事项

1. **亚型档案仅 6 条**：距「肺癌 ≥20 profile」缺口较大，需补 `DIS-LUNG-0007` 起的亚型（大细胞癌 / 腺鳞癌 / 类癌 等）与并发症档案（恶性胸腔积液 / 上腔静脉阻塞综合征 / 骨转移 等）。
2. **`icd10` 口径（已修复）**：v1 主字段曾用国家临床版 5 位码 `C34.901`；v2 起按项目规范改为 WHO 4 位码 `C34.9`，原 5 位码留在 `annotation.icd10_national`，`icd_o3` 仍为 4 位 WHO 写法 `M8010/3`。
3. **`symptoms_early` 仅 3 条**：原文临床表现段落以「咳嗽 / 咯血 / 发热」起句，其余症状散落在转移相关段落被判 `late`，需人工复核早晚期归类。
4. **`pathology_subtypes` 的 `frequency` 全为 `null`**：除鳞癌 / 腺癌 / 小细胞癌外，其余亚型原文未给占比，按规则留空。
5. **`treatment` 为多段拼接**：从外科 / 放疗 / 药物 / 分期治疗模式各取 2 句，语义不连贯，仅作概览；细则以 A2 条目为准。
6. **`review_status`**：全部 `draft`，需医学审核员复核后改 `approved`。

## 复现

```bash
python tools/22_a3_disease_profile.py --dry-run   # 只打印统计与亚型画像，不落盘
python tools/22_a3_disease_profile.py             # 写入本目录 + 审计
```

依赖：`raw/guidelines/lung/nhc2022_01_lung.pdf`、`data/clean/terminology/terminology_cancer.json`、`data/clean/drug_labels/drug_catalog_v2.json`。
脚本幂等：输入不变时重复运行产出字节级一致。
