# guidelines 指南与规范原文目录

本目录存放 **A1 指南与规范原文**（P0 阻断级）的 `document` 元数据，是全部结构化知识（A2 条目 / A3 档案 / A4 说明书 / A6 图谱）的唯一权威来源。
原文文件（PDF / DOCX）存放在 `raw/guidelines/<癌种|all>/`（超出 5 癌种的 17 份在 `raw/_deprecated/guidelines/other/`），本目录只放元数据，**不含正文**。
NCCN 指南原件因版权限制**不属于交付物**，存放于 `external/nccn/<癌种>/`，仅作著录与引用，使用规则见文末「NCCN 资料使用规则」。

## 文件

| 文件 | 记录数 | 内容 | 来源（`source_name` / `license_note`） |
|---|---|---|---|
| `guidelines_lung_2022_20261025.json` | 1 | 原发性肺癌诊疗指南（2022 年版），74 页 | 国家卫健委 国卫办医函〔2022〕104号，公开可引用 |
| `guidelines_gastric_2022_20261025.json` | 1 | 胃癌诊疗指南（2022 年版），93 页 | 同上 |
| `guidelines_breast_2022_20261025.json` | 1 | 乳腺癌诊疗指南（2022 年版），113 页 | 同上 |
| `guidelines_thyroid_2022_20261025.json` | 1 | 甲状腺癌诊疗指南（2022 版），65 页 | 同上 |
| `guidelines_colorectal_2015_20261025.json` | 1 | 结直肠癌诊疗规范（2015 年版），.doc 转 .docx | 国家卫计委医政医管局 国卫医医护便函〔2015〕292号 |
| `guidelines_colorectal_2024_20261025.json` | 1 | 结直肠癌筛查与早诊早治方案（2024 年版），网页正文转录 | 国家卫健委办公厅 国卫办医急函〔2024〕281号 |
| `guidelines_all_2025_20261025.json` | 1 | 新型抗肿瘤药物临床应用指导原则（2025 年版），605 页 | 国家卫健委，公开可引用 |
| `guidelines_lung_nccn2026_20261025.json` | 3 | NCCN 非小细胞肺癌（9.2026）/ 小细胞肺癌（1.2027）/ 肺癌筛查（1.2027），**非交付物** | NCCN，版权保留、禁止再分发 |
| `guidelines_lung_caca2024_20261028.json` | 2 | CACA 肺癌指南**官方英译版**全文（44 页）+ 官方**中文摘要**（非全文），详见下节 | 中国抗癌协会；英译版 CC BY 4.0 开放获取 |
| `guidelines_lung_csco2025_20261028.json` | 1 | CSCO 非小细胞肺癌诊疗指南 2025，**仅书目元数据，正文未采集** | 人民卫生出版社付费电子书 |
| `guidelines_breast_nccn2026_20261025.json` | 1 | NCCN 乳腺癌（9.2026），278 页，**非交付物** | 同上 |
| `guidelines_colorectal_nccn2026_20261025.json` | 2 | NCCN 结肠癌（2.2026）/ 直肠癌（2.2026），**非交付物** | 同上 |
| `guidelines_gastric_nccn2026_20261025.json` | 1 | NCCN 胃癌（4.2026），140 页，**非交付物** | 同上 |
| `guidelines_thyroid_nccn2026_20261025.json` | 1 | NCCN 甲状腺癌（2.2026），159 页，**非交付物** | 同上 |

同一批次（2022-04-11 公开）通知页共 **21 份** PDF，已全部下载归档；其中仅上述 4 份落在项目 5 癌种范围，其余 17 份（膀胱癌 / 食管癌 / 胰腺癌 / 肾癌 / 子宫内膜癌 / 宫颈癌 / 卵巢癌 / 前列腺癌 / 脑胶质瘤 / 淋巴瘤 / 黑色素瘤 / 血液病等）存于 `raw/_deprecated/guidelines/other/`，**不录入**。

## 字段结构（`document`，承袭方案 §5.7.2(1)）

| 字段 | 类型 | 说明 |
|---|---|---|
| `doc_id` | string | `DOC-<范围码>-<来源码>-<序号>`，如 `DOC-LUNG-NHC-001` |
| `title` | string | 全称，含年份 |
| `doc_type` | enum | `guideline` / `standard` / `consensus` |
| `issuer` | string | 发布机构 |
| `publish_date` | date | `YYYY-MM-DD` |
| `cancer_types` | array | §5.7.3 枚举（`lung`/`breast`/`colorectal`/`gastric`/`thyroid`） |
| `license_note` | string | 版权与获取说明（含通知文号与原文 URL） |
| `file_path` | string | 相对项目根的原文路径 |
| `doc_hash` | string | 原文 **SHA-256**（非 MD5） |
| `source_name` / `source_version` / `source_section` / `source_file` / `updated_at` | string | G6 溯源五字段，`source_section` 固定「全文」 |
| `review_status` / `reviewer` / `review_date` | string / string / date | G15 审核字段，当前 `draft` |

## 质量自检结果（A1 文本可提取性自检，PDF 用 PyMuPDF / DOCX 用 python-docx）

| doc_id | 页数 | 文本字符数 | 结论 |
|---|---|---|---|
| `DOC-LUNG-NHC-001` | 74 | 40,441 | 通过 |
| `DOC-GAS-NHC-001` | 93 | 45,153 | 通过 |
| `DOC-BREAST-NHC-001` | 113 | 53,414 | 通过 |
| `DOC-THY-NHC-001` | 65 | 31,557 | 通过 |
| `DOC-CRC-NHC-001` | .docx | 17,915 | 通过（Word 转换件） |
| `DOC-CRC-NHC-002` | .docx | 2,535 | 通过（网页正文转录件） |
| `DOC-ALL-NHC-001` | 605 | 344,337 | 通过 |
| `DOC-LUNG-NCCN-001` | 303 | 1,241,312 | 通过 |
| `DOC-LUNG-NCCN-002` | 93 | 347,687 | 通过 |
| `DOC-LUNG-NCCN-003` | 98 | 368,743 | 通过 |
| `DOC-BREAST-NCCN-001` | 278 | 1,140,940 | 通过 |
| `DOC-CRC-NCCN-001` | 249 | 1,052,014 | 通过 |
| `DOC-CRC-NCCN-002` | 166 | 641,072 | 通过 |
| `DOC-GAS-NCCN-001` | 140 | 540,925 | 通过 |
| `DOC-THY-NCCN-001` | 159 | 586,684 | 通过 |
| `DOC-LUNG-CACA-001` | 44 | 223,493 | 通过（官方英译版，CC BY 4.0） |
| `DOC-LUNG-CACA-002` | .docx | 382 | 通过（官网正文转录，5 段） |
| `DOC-LUNG-CSCO-001` | — | — | 不适用（无原件，仅书目元数据） |

2022 批次全部 21 份附件均通过自检（最低 5,463 字符，无扫描件）。
两份结直肠癌文档非 PDF：2015 版为官网提供的 `.doc`，经 Word COM 转为 `.docx` 后入库（页数位不适用，记 `.docx`）；2024 版通知页**未提供附件文件**，正文即附件全文，按官网正文逐字转录为 `.docx`（`license_note` 已注明）。
NCCN 批次 8 份均为原生 PDF（含文本层），覆盖肺部 3 份（NSCLC / SCLC / 筛查）、结直肠 2 份（结肠 / 直肠）、乳腺 / 胃 / 甲状腺各 1 份；原件存放于 `external/nccn/`，**不进入 `raw/`、不随竞赛交付**。

## 待复核事项

1. **`publish_date`（已回填）**：2022 批次统一填通知公开日 `2022-04-11`（文件签发日为 2022-04-03）；《新型抗肿瘤药物临床应用指导原则（2025 年版）》的 `publish_date` 已回填 **2026-01-26**（医政司发布，国卫办医政函〔2026〕21 号，成文日期 **2026-01-19**；通知页 <https://www.nhc.gov.cn/yzygj/c100067/202601/460c2377aa294b55baacd339b8b19eb8.shtml>，2026-11-05 复核）。该日期写在 `tools/9_guidelines_to_json.py` 的 MANIFEST 源字段并由脚本重出 JSON，未手改数据；`license_note` 同步记录通知页与文号，`source_version` 保持 `2025`。
2. **`DOC-ALL-NHC-001` 范围码**：覆盖各系统肿瘤用药、非单一癌种，故 `cancer_types` 填全部 5 个癌种、范围码用 `ALL`；属对 §0.5 编号体系的扩展，需入库前确认。
3. **章节覆盖**：`DOC-ALL-NHC-001` 属用药指导类，天然缺 流行病学 / 病理分型 / 诊断分期 / 随访，下游 A2 抽取须在抽取说明中登记 section_gaps。
4. **肺癌指南已换成官网原生 PDF**：原 CNKI 版式转载件（`doc_hash` 94c369de…）已删除，现为官网附件（74 页，`doc_hash` 见 JSON），`doc_hash` 与官方文件一致。
5. **数量与来源结构**：元数据现共 **18 条**（NHC 7 + NCCN 8 + CACA 2 + CSCO 1）；其中 NCCN 8 条为非交付物、CSCO 1 条无正文，**可交付原件 9 份**（NHC 7 + CACA 英译版 + CACA 中文摘要），仍低于 A1「10~20 份」要求。**中文完整指南仍只有 NHC 一家**：CACA 中文原版与 CSCO 正文均未获取（限制见下节），下游中文 RAG 与 A2 条目抽取不能依赖 NCCN 或 CSCO。
6. **结直肠癌版本**：2015 版诊疗规范已被《中国结直肠癌诊疗规范（2023 版）》（2023-09-23 发布，国家卫健委医政司 / 中华医学会肿瘤学分会）取代；本库**尚未收录 2023 版正文**（待补采）。2024 版为筛查与早诊早治方案，不覆盖全流程诊疗，两份合起来仍不等于一份完整诊疗指南。
7. **NCCN 版权处理（已定案）**：8 份原件已移出 `raw/` 至 `external/nccn/`，不随竞赛交付，仅保留元数据用于著录与引用；报告中提及 NCCN 推荐意见必须使用官方引用格式，并禁止复制核心内容——详见下节「NCCN 资料使用规则」。
8. **`review_status`**：全部 `draft`，医学审核员核对版本年份与机构后改 `approved`。

## CACA / CSCO 中文指南获取限制（2026-10-28 实测）

CACA 与 CSCO 是国内两大权威指南来源，但**中文全文均无法通过公开自动化渠道获取**。本目录按「可核查的替代路径」落库，不伪造、不拼接替代全文：

| 来源 | 中文全文渠道 | 实测结果 | 本目录处理 |
|---|---|---|---|
| CACA 整合诊治指南 · 肺癌 | `cacaguidelines.cacakp.com`（会员） | HTTP 200，页面提示「下载指南请先完成登录」；`pdflist?guide_id=1008` 仅列书目，无公开 PDF 直链 | 采**官方英译版**全文（`DOC-LUNG-CACA-001`）+ 官网**中文摘要**（`DOC-LUNG-CACA-002`） |
| CSCO 非小细胞肺癌诊疗指南 2025 | 人卫助手 / 微信扫码付费电子书（￥298） | 付费墙；官网仅「购书渠道」说明 | **仅著录书目元数据**（`DOC-LUNG-CSCO-001`），`file_path=null` |
| 中华医学会肺癌临床诊疗指南 2024 | 中华医学杂志（`rs.yiigle.com`） | 全文页 1.19 MB HTML，正文仅 **721 个中文字符**（摘要页），全文需订阅 | 未入库，待合法获取 |

**降级使用的口径**：

1. `DOC-LUNG-CACA-001` 为**英文**。A2 抽取若引用该件，条目说明须显式标注「英文官方译本」，不得与 NHC 中文条目混同统计。
2. `DOC-LUNG-CACA-002` 仅 382 字符的官方摘要（覆盖范围与更新说明），**不是指南正文**，不可作为 A2 / A3 抽取素材；`doc_type` 在 §A1 三值枚举（`guideline` / `standard` / `consensus`）中权宜归入 `consensus`，待需求方确认。
3. `DOC-LUNG-CSCO-001` 无正文、无 `doc_hash`，不得计入「可抽取原文」统计；如后续取得合法 PDF，按 `tools/12_ingest_inbox_guidelines.py` 归档流程补录并升 `version`。
4. 如需 CACA / CSCO 的中文完整指南，唯一合规路径是**由有会员或购买权限的人员下载后放入 `inbox/`**，再用 `tools/23_fetch_caca_csco_guidelines.py --force` 或 12 号脚本重新录入。


## NCCN 资料使用规则（必读）

NCCN 指南版权归 National Comprehensive Cancer Network（NCCN）所有，本项目仅按「合理引用」使用：原件存 `external/nccn/`，**不进入 `raw/`、不随竞赛交付**。

1. **引用格式**：报告/演示中提及 NCCN 推荐意见，必须逐字使用其官方格式（不得改写、简写）：

> Referenced with permission from the NCCN Clinical Practice Guidelines in Oncology (NCCN Guidelines®) for [Guideline Name] V.X.202X. © National Comprehensive Cancer Network, Inc. 202X. All rights reserved. Accessed [Month and Day, Year]. To view the most recent and complete version of the guideline, go online to NCCN.org.

2. **占位符填写**：`[Guideline Name]` 用下表英文全名；`V.X.202X` 用所引版本（如 `V.9.2026`）；`© 202X` 为版权年份；`Accessed` 填实际查阅日（本批统一 `October 25, 2026`）。每条记录的 `license_note` 已内置填好的完整引用串，可直接取用。
3. **绝对禁止复制核心内容**：Algorithm 流程图、表格、图表、大段 "Discussion" 文本均**不得**复制到知识库、论文、演示文稿或任何交付物。确需转述时用自身语言概括，并按上表标注「据 NCCN Guidelines® <Guideline Name> V<Version>」。
4. **知识库范围**：本目录只保留书目元数据（标题/版本/日期/引用串），**不含正文**；A2 条目抽取不得以 NCCN 原文为素材。

| doc_id | Guideline Name | Version | 发布日期 |
|---|---|---|---|
| `DOC-LUNG-NCCN-001` | Non-Small Cell Lung Cancer | 9.2026 | 2026-09-22 |
| `DOC-LUNG-NCCN-002` | Small Cell Lung Cancer | 1.2027 | 2026-07-01 |
| `DOC-LUNG-NCCN-003` | Lung Cancer Screening | 1.2027 | 2026-10-02 |
| `DOC-BREAST-NCCN-001` | Breast Cancer | 9.2026 | 2026-10-22 |
| `DOC-CRC-NCCN-001` | Colon Cancer | 2.2026 | 2026-04-07 |
| `DOC-CRC-NCCN-002` | Rectal Cancer | 2.2026 | 2026-04-07 |
| `DOC-GAS-NCCN-001` | Gastric Cancer | 4.2026 | 2026-09-16 |
| `DOC-THY-NCCN-001` | Thyroid Carcinoma | 2.2026 | 2026-06-02 |

## 复现

```bash
python tools/10_fetch_nhc_guidelines.py   # 卫健委通知页 21 份附件 → raw/guidelines/，5 癌种范围录入本目录
python tools/10_fetch_nhc_guidelines.py --no-download   # 已下载时只重新录入
python tools/11_fetch_colorectal_guidelines.py   # 结直肠癌 2015 诊疗规范（.doc→.docx）+ 2024 筛查方案（正文转录）→ 本目录
python tools/12_ingest_inbox_guidelines.py   # inbox/ 新文件按癌种归档到 external/nccn/（非交付物）并录入（本批为 NCCN 8 份）
python tools/9_guidelines_to_json.py      # 人工指定元数据的文档（如 2025 药物指导原则）
python tools/23_fetch_caca_csco_guidelines.py   # CACA 英译版 PDF 下载 + 官网中文摘要转录 + CSCO 书目元数据
```

说明：通知页 HTML 有 WAF 脚本防护（直接 GET 返回 412），附件 PDF/DOC 可直连下载；脚本内置与原页逐条核对的附件清单，页面可解析时以页内结果为准。附件清单与哈希记录在 `cache/guidelines/nhc_2022_attachments.json`。
`tools/11_fetch_colorectal_guidelines.py` 依赖 `tools/word_to_docx.ps1`（PowerShell + Word COM）做 `.doc` → `.docx` 转换；2024 版无附件文件，脚本读取 `raw/guidelines/colorectal/nhc2024_02_colorectal_screening.txt`（官网正文快照）转录为 `.docx` 后再计算哈希。
`tools/12_ingest_inbox_guidelines.py` 从 `inbox/` 读取新文件、按 MANIFEST 归档到 `external/nccn/<癌种>/`（非交付物），再将同癌种记录合并写入一个 JSON；本批归档清单与哈希见 `cache/guidelines/nccn_2026_documents.json`。
