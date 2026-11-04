# recommendations 结构化推荐条目目录（A2）

本目录存放 **A2 结构化推荐条目**：从 A1 指南原文按「场景 / 分期 / 生物标志物」结构化的可检索推荐，是全项目 P0 阻断级产出之一。
条目一律**原文摘录**（`verbatim=true`），不做改写、不做跨段落拼接；`recommendation_text` 超过 500 字的候选在抽取阶段即被拒收。

## 文件

| 文件 | 记录数 | 内容 | 来源 |
|---|---|---|---|
| `recommendations_lung_20261028_v3.json` | 145 | **当前版本**：v2 + 正文条目改为真实页码（`page` 逐行溯源） | 原发性肺癌诊疗指南（2022 年版），国家卫健委 国卫办医函〔2022〕104号 |
| `recommendations_lung_20261028_v2.json` | 145 | v2（含表格分支与场景修正，但 `page` 仍是章节块起始页，保留以便比对） | 同上 |
| `recommendations_lung_20261028.json` | 141 | v1（历史版本，已被 v2/v3 取代，保留以便比对；G4 不覆盖旧文件） | 同上 |
| `recommendations_lung_caca_20261028.json` | 69 | 批次一 · 肺癌 **CACA 官方英译版英文条目**（`annotation.lang=en`），独立外挂、不并入中文文件 | CACA guidelines for holistic integrative management of lung cancer，HIO 2024;3:10，**CC BY 4.0** |

`doc_id` 与 `data/clean/guidelines/` 的 `document` 元数据一一对应；本目录不复制指南正文，仅保存被抽取的推荐句与其页码。

### v1 → v2 变更（2026-10-28）

| 变更 | 说明 | 条数影响 |
|---|---|---|
| 新增表格解析分支 | 解析「表 4 非小细胞肺癌常用的二线治疗方案」4 列表格（治疗方案 / 剂量 / 用药时间 / 时间及周期），上标 `75mg/m`+`2` 合并为 `75mg/m2` | +4（`treatment_second_line`） |
| 场景判定改为原句优先 | `clean_sentence` 会剥掉「（2）二线药物治疗：」这类小标题前缀，改用未清洗原句判场景 | `treatment_second_line` +3、`targeted` −3 |
| 同上 | 「（4）术后放疗设计」由 `surgery` 更正为 `radiotherapy` | `surgery` −1、`radiotherapy` +1 |

### v2 → v3 变更（2026-10-28）

`parse_blocks` 由「每块一个页面」改为「每行带页码」，`recommendation_text` 全部不变（逐条比对一致），仅 `page` 由章节块起始页改为该句真实所在页，**126/145 条页码被修正**（修正后范围 6~72；表格行原本即为真实页码）。

**v3 页码修正（2026-11-05）**：分句拆条时，页码原按「整句起始偏移」取页，导致跨页长段落末句偏后 1 页。现改为按**本条文本自身句首**在块内定位取页。重跑后**仅 2 条 `page` 变化**——`REC-LUNG-NHC-0018` 28→29、`REC-LUNG-NHC-0090` 60→61；其余 143 条页码、全部文本、字段与顺序零漂移（逐字段 diff 核对）。复验 145 条：144 条声明页即句首所在页，1 条句首正好跨页（`0054`，p48 末起句，取起始页正确），**合计 145/145 正确**。产物 SHA-256 基线 `E849497E…253C7C9`（连跑两次一致）。

## 字段结构（`recommendation`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `rec_id` | string | `REC-<癌种>-<来源码>-<4 位序号>`，如 `REC-LUNG-NHC-0041`；批内唯一 |
| `doc_id` | string | 来源文档，关联 `guidelines/` 目录 |
| `cancer_type` | enum | `lung` / `breast` / `colorectal` / `gastric` / `thyroid` |
| `breadcrumb` | string | 章节路径，如 `四、肺癌的治疗 / （二）放射治疗` |
| `scenario` | enum | §6.1 受控词表 15 类，取值见下表 |
| `stage` | array / null | 枚举数组，取值 `0` / `I` / `II` / `III` / `IV` / `unknown`；原文未指明期别写 `null` |
| `biomarker` | array / null | §6.1 受控 19 项数组（EGFR / ALK / ROS1 / … / MET / EBV） |
| `population` | string / null | 适用人群限定语（原文有明确限定才填） |
| `recommendation_text` | string | 推荐原文，≤500 字 |
| `verbatim` | bool | 恒为 `true`（规则抽取只摘原句） |
| `evidence_level` | enum | `high` / `moderate` / `low` / `very_low` |
| `evidence_level_original` | string / null | 原文分级写法（如 `1A`、`2B`、`Ⅲ级`） |
| `rec_strength` | enum | `strong` / `weak` / `not_graded` |
| `refs` | string / null | 原文引用的参考文献编号 |
| `page` | int | PDF 页码（1 起） |
| `source_name` / `source_version` / `source_section` / `source_file` / `updated_at` | string | G6 溯源五字段 |
| `review_status` / `reviewer` / `review_date` | string / string / date | G15 审核字段，当前全部 `draft` |
| `annotation` | object | 抽取脚本名、日期、状态；表格行额外含 `extraction="table_row"`、`table`、`table_cells`（原始单元格数组） |

### 场景分布（本批 145 条）

| `scenario` | 条数 | `scenario` | 条数 |
|---|---|---|---|
| `radiotherapy` | 33 | `staging` | 8 |
| `treatment_first_line` | 23 | `treatment_second_line` | 8 |
| `surgery` | 19 | `screening` | 4 |
| `treatment_neoadjuvant` | 13 | `supportive_care` | 4 |
| `treatment_adjuvant` | 11 | `treatment_later` | 3 |
| `diagnosis` | 9 | `immunotherapy` | 2 |
| `targeted` | 8 | | |

`followup` / `rehab` 两类本批 0 条：随访章节句子短、动作词少，未被 cue+action 规则命中（见「待复核事项」第 3 条）。

## 英文外挂文件（`recommendations_lung_caca_20261028.json`，69 条）

由 `tools/24_a2_caca_recommendation_extract.py` 从 CACA 官方英译版抽取，`doc_id = DOC-LUNG-CACA-001`、`rec_id = REC-LUNG-CACA-####`、`annotation.lang = en`。**不并入中文 145 条**，定位为跨语言检索补充；中文知识库仍以 `recommendations_lung_20261028_v2.json` 为主。

| `scenario` | 条数 | `scenario` | 条数 |
|---|---|---|---|
| `surgery` | 19 | `supportive_care` | 4 |
| `diagnosis` | 13 | `rehab` | 3 |
| `followup` | 10 | `targeted` | 2 |
| `radiotherapy` | 8 | `immunotherapy` | 1 |
| `treatment_adjuvant` | 7 | `screening` / `staging` | 各 1 |

抽取口径：

1. 仅取正文 `Main recommendations:` 段内条目，按 `1)` / `(1)` 编号切条；遇下一章节标题或 `Notes:` / `Table` / `Figure` 即止。
2. 纯标签条目（以 `:` 结尾，如 `Surgery-centered LA-LC radiotherapy strategy:`）不成条（本批丢弃 12 条），其下级编号条目各自独立成条；句尾无终止标点的残句同样不成条（丢弃 2 条）。
3. **全部 69 条为 `very_low` / `not_graded`**：CACA 英译版全文检索 `Level of evidence` / `Category` / `Grade` / `1A` / `2A` 命中均为 0 处，确无证据分级，按 §A2「原文无分级」兜底，`evidence_level_original=null`，不伪造档位。
4. `biomarker` 不含 `ER` / `PR`：英文肺癌文本里的 PR 是疗效评估 `partial response`（与 CR / SD 并列），不是孕激素受体，纳入会造成系统性误标。
5. 中医药（TCM）在 15 类 `scenario` 中无对应枚举，按最接近的 `supportive_care` 归类（本批 4 条）。
6. `breadcrumb` 忠实保留原文编号层级（如 `2 Diagnosis of lung cancer / 2.5 Traditional Chinese medicine (TCM) treatment of LC`），该文编号体系与中文指南不同，不做对齐改写。

## 证据分级映射口径（§A2）

| 原文分级 | `evidence_level` | `rec_strength` |
|---|---|---|
| CSCO 1A / 1B | `high` | `strong` |
| CSCO 2A / 2B | `moderate` | `weak` |
| CSCO Ⅲ级 | `low` | `weak` |
| NCCN Category 1 | `high` | `strong` |
| 原文无分级（卫健委指南、CACA 英译版） | `very_low` | `not_graded` |

本批 145 条**全部为 `very_low` / `not_graded`**：卫健委 2022 版肺癌指南通篇不设证据等级与推荐强度，脚本按上表兜底，`evidence_level_original` 全部为 `null`。这是真实属性而非抽取缺陷。
真实 `high` / `moderate` 档位只能来自 CSCO（1A/1B、2A/2B、Ⅲ级）或 NCCN（Category 1/2A）——CSCO 正文为付费电子书未采集、NCCN 属版权受限非交付物；CACA 英译版经全文检索确认**无任何证据分级**（`Level of evidence` / `Category` / `Grade` / `1A` / `2A` 均 0 处），故补入 CACA 也不会产生 `high` / `moderate`。

## 抽取规则（`tools/21_a2_recommendation_extract.py`）

1. **章节重建**：按「一、」/「（一）」两级标题切块，生成 `breadcrumb`；单块每节仅保存前若干句，避免整章重复。
2. **句子过滤**：必须同时含「推荐/建议/首选/一线/应…」类 cue 与「治疗/手术/检测/随访…」类 action；含「发病率/死亡率/见表/注：」等背景或表格特征的句子直接丢弃。
3. **场景判定**：先看句子本身，命中不到再用 `breadcrumb` 兜底（避免「筛查」章节污染诊断句）；规则按「具体先于泛化」排序（新辅助 → 辅助 → 一线 → 二线 → 后线 → 靶向 → 免疫 → 放疗 → 手术 …）。
4. **列表拆分**：含「；」且每段都自带 cue+action、长度 ≥12 字时才拆成多条，否则保留整句，防止语义割裂。
5. **去重**：同一 `doc_id` 下 `recommendation_text` 完全相同者只保留首次出现（本批丢弃 6 条）。
6. **表格分支**：识别「表N」标题 + 四列表头（治疗方案 / 剂量 / 用药时间 / 时间及周期）的连续单元格行，按 4 列切组，上标合并（`75mg/m` + `2` → `75mg/m2`）；`recommendation_text` 为单元格以「，」连接，`verbatim=true` 仅指单元格内容逐字未改，连接符为脚本添加，原始单元格留在 `annotation.table_cells`。

抽取审计（各过滤环节丢弃计数、块数、页数）见 `cache/recommendations/a2_extract_audit.json`。

## 待复核事项

1. **`stage` / `biomarker` / `population` 大面积留空**：本批仅填充原文显式写明的期别与标志物；RAW 级别未做 T/N/M 推断，需医学审核员按临床口径回填或确认「原文未限定」。
2. **`scenario` 单一标签**：一条推荐可能同时涉及「手术 + 辅助」，受控词表单值设计下按主场景归类；跨场景检索建议在 A6 图谱层用多标签关系表达。
3. **`followup` / `rehab` 缺口**：随访章节句子短、动作词少，未被 cue+action 规则命中；`rehab` 在卫健委指南中基本无对应内容。补 CACA / CSCO 后再回归。
4. **`radiotherapy` 偏高（33 条，23%）**：放疗章节为长段落连续陈述，规则按句切分后条数自然偏多；需人工合并语义重复项。
5. **`page` 已改为逐句真实页码（v3）**：`parse_blocks` 记录每行页码；分句拆条时按**本条文本自身句首**在块内定位回溯所在页（分句跨页取该分句句首页，整句句首跨页取起始页）。表格行按单元格实际页码记录。2026-11-05 已修正 2 条跨页末句偏差，复验 145/145 正确。
6. **`treatment_second_line` 由 1 条补至 8 条**：其中 3 条来自正文「（2）二线药物治疗」，4 条来自表 4 表行，1 条来自「（五）NSCLC 的分期治疗模式」的「⑤二线治疗」。表行文本建议医学审核员按说明书核对剂量单位。
7. **`review_status`**：全部 `draft`，医学审核员逐条核对后改 `reviewed` / `approved`，并填 `reviewer` / `review_date`。
8. **英文文件（CACA）折行连字符**：还原 PDF 折行时统一去掉行尾 `-`，会把原生连字符复合词合并（如 `high-grade` → `highgrade`、`non-squamous` → `nonsquamous`），不影响语义但需审核时留意。
9. **英文文件（CACA）`page` 语义**：取 `Main recommendations:` 所在页（条目可能跨页续排），非逐条起始页。

## 复现

```bash
python tools/21_a2_recommendation_extract.py --dry-run   # 中文（卫健委）只统计不落盘
python tools/21_a2_recommendation_extract.py             # 中文 → v3 文件 + 审计
python tools/24_a2_caca_recommendation_extract.py --dry-run   # 英文（CACA）只统计不落盘
python tools/24_a2_caca_recommendation_extract.py             # 英文 → CACA 文件 + 审计
```

两个脚本均幂等：同一输入反复运行产出字节级一致（`doc_hash` 与 `source_file` 未变时 SHA-256 不变）。
