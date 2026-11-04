# 医疗创新应用赛 · 数据采集与清洗工作区

> 本工作区依据《[医疗数据需求清单.md](医疗数据需求清单.md)》完成数据的采集、清洗与交付。
> 本 README 定义工作区结构与标准工作流程，**新增数据集时照此执行**。

## 1. 目录结构与职责

| 目录 | 职责 | 规则 |
|---|---|---|
| `inbox/` | **收件箱**：新找到的文件暂存，尚未分类 | 只做中转：确认癌种/功能类型后移入 `raw/`，本目录平时保持为空；不做任何加工 |
| `fetched/` | **抓取存放**：脚本或人工从网站抓回、**尚未加工**的数据（HTML 解析结果、下载件） | 只放抓取原样结果，不改写；由 `tools/` 里的抓取脚本写入，供下游清洗脚本读取；可按来源建子目录（`atc/`、`codetables/`、`openfda_labels/`） |
| `raw/` | **输入**：已分类、可直接供流水线读取的源数据，**按数据集 id 分目录**，只读不改 | 原文件永不修改、不解压后回写；处理一律走脚本。**已评估为弃用/无产出的文件，一律移入 `raw/_deprecated/<数据集>/`**，不删除、也不留在可直接读取的目录 |
| `tools/` | **工具**：清洗/抓取脚本，按流水线步骤编号（`1_`、`2_`…） | 每个数据集自己的脚本；输入读 `raw/` 或 `fetched/`，中间写 `cache/`，成品写 `data/clean/` |
| `cache/` | **处理缓存**：脚本运行中间产物，**按数据集 id 分目录** | 可随时整体删除，重跑脚本即可再生；**不放源数据，也不放最终成品** |
| `data/clean/` | **输出**：最终交付 JSON，**按功能类型分目录**（`eval_sets/`、`corpus/`、`kg_triples/`、`drug_labels/`…），**不再按数据集分子目录** | 只放对齐字段结构的成品；每个功能目录一份 README；数据来源写入每条记录的 `source`（文字说明）与 `origin`（短码）字段 |
| `external/` | **不可交付**：版权受限的第三方资料（如 NCCN 指南、CC BY-NC-ND 类数据集） | 不进入 `raw/`、不随竞赛交付、不做清洗输出；报告中只能按官方格式引用其推荐意见，禁止复制 Algorithm 流程图、表格、图表与大段 Discussion 文本 |

**数据流（单向，不可逆向回写）**

```
网页/人工 ─→ inbox/（待分类）─→ raw/（输入，已分类）
网页脚本 ─→ fetched/（抓取，未加工）─┐
                                     ├─→ tools/（脚本处理）─→ cache/（中间件）─→ data/clean/（输出）
raw/ ────────────────────────────────┘
版权受限资料 ─→ external/（不可交付，只引用不输出）
```

**目录归属判别**：① 人工/官方**下载原件** → `raw/`；② **抓回来还没加工** → `fetched/`；③ 脚本**跑出来的中间件**（解压临时目录、解析中间态、映射审计）→ `cache/`；④ **交付物** → `data/clean/`；⑤ **不能对外** → `external/`；⑥ **评估后弃用/无产出** → `raw/_deprecated/<数据集>/`（保留原件以便复核，但不参与流水线）。

> `raw/_deprecated/` 的判定标准：已逐项评估且**不会进入 `data/clean/` 任何成品**（癌种超范围、内容与需求类别不对应、数据质量不达标、授权不允许）。移入时保持原数据集路径，例如 `raw/_deprecated/cblue/`、`raw/_deprecated/codetables/nhc/`。整个目录可直接删除以清理空间。

**数据集 id 约定**：全小写短名（如 `cmedqa2`），在 `raw/`、`cache/` 两处保持一致，后续新数据集照此命名，互不混淆；`tools/` 内脚本编号递增但不带数据集前缀，`data/clean/` 按功能类型归类，来源只体现在记录字段里。

```
data_collection_project/
├── inbox/                          # 【收件箱】新找到、尚未判定癌种/功能类型的文件先放这里，分类后移入 raw/ 或 external/
├── fetched/                        # 【抓取存放】抓回来尚未加工的数据，只由抓取脚本写入
│   ├── atc/                        #   WHO ATC 抓取结果（15 号脚本）
│   │   ├── atc_oncology.csv        #     750 条 5 级码（code / name_en / group / parent），未做任何映射
│   │   └── zh_en_inn.json          #     16 号脚本写出的中文→INN 人工对照表（7 条）
│   ├── codetables/                 #   NHC 官方资料包抓取结果（17 号脚本）
│   │   ├── hqms_2.0.rar            #     HQMS 2.0 资料包原件（5.5 MB，脚本下载）
│   │   └── nhc/                    #     解出的（3）肿瘤形态学编码（M码）2.0.xlsx（1,427 条，18 号读取）
│   ├── openfda_labels/             #   openFDA drug/label 抓取结果（19 号脚本）
│   │   └── labels.json             #     48 种药的说明书四段英文（45 命中，3 未命中）
│   ├── cmkb_drugs/                 #   CMKB 药物库抓取结果（26 号脚本）+ a4_interim.json（29 号，内部参考，带来源/时间/license_status；站点版权保留、**不入 Git**）
│       ├── drugs.json              #     2,724 条药物目录级字段（名称/类别/适应证/禁忌/相互作用）
│       ├── a4_interim.json         #     29 号：21 药 A4 缺口 interim（source/URL/时间/license_status=restricted_internal_only，内部参考）
│       └── manifest.json           #     抓取参数与条数审计
│   ├── labels_cn/                  #   企业官网中文说明书（30 号脚本）
│   │   ├── labels_cn.json          #     13 药抽取文本 + 元数据（lang=zh，含 source_url/fetched_at/usage_note）
│   │   ├── failures.json           #     未获取来源与原因（扫描件/登录墙/仅图片等）
│   │   ├── text/                   #     13 份抽取后的说明书文本（入库）
│   │   └── downloads/              #     PDF/HTML 原件 + sidecar meta（**版权归持有人，不入 Git**）
├── raw/                            # 【输入】已分类、可直接供流水线读取，按数据集 id 分目录，只读不改
│   ├── cmedqa2/                    # 数据集1：cMedQA2 v2.0 原始 zip + LICENSE
│   ├── pubmed_cancer/              # 数据集2：PubMed-Cancer-NLP 4 个癌种 CSV + README
│   ├── kgdrug/                     # 数据集3：gStore 医药知识图谱建库目录（约 295MB 二进制索引）
│   ├── fda_ndc/                    # 数据集4：FDA NDC 药品目录 product.txt（38MB）+ README
│   ├── cblue/                      # 数据集6：CBLUE 已采用子集（CHIP-CDN.zip、CMeIE-V2.zip）+ 上游 README
│   ├── codetables/                 # 码表来源说明（原件由 17 号脚本抓取至 fetched/codetables/，raw 不留副本）
│   │   └── README.md               #   NHC M 码 / WHO ATC 来源、授权、补码进度与复现命令
│   ├── nmpa_labels/                # 数据集7：A4 中文覆盖（人工按说明书填写）
│   │   ├── labels_zh.template.json #   19 号脚本生成的空模板（48 药 × 11 字段）
│   │   └── labels_zh.json          #   人工填写后的中文覆盖文件（待补，19 号脚本校验并合并）
│   ├── nmpa_registry/              # 数据集8：NMPA 注册信息人工查询样例（无说明书正文）
│   │   ├── README.md               #   查询页字段清单、限制说明与录入注意
│   │   └── nmpa_registry_alectinib_HJ20180047.pdf  # 阿来替尼注册信息查询页（4 页样例）
│   ├── guidelines/                 # 数据集5：A1 指南与规范原文，按癌种分目录
│   │   ├── lung/                   #   nhc2022_01_lung.pdf（卫健委 2022 版）；caca2024_lung_en.pdf（CACA 官方英译版，CC BY 4.0）；caca2024_lung_zh_abstract.docx（CACA 官方中文摘要转录）
│   │   ├── breast/                 #   nhc2022_07_breast.pdf
│   │   ├── gastric/                #   nhc2022_03_gastric.pdf
│   │   ├── thyroid/                #   nhc2022_12_thyroid.pdf
│   │   ├── colorectal/             #   NHC：nhc2015_01_colorectal.doc(+.docx)、nhc2024_02_colorectal_screening.txt(+.docx)
│   │   └── all/                    #   新型抗肿瘤药物临床应用指导原则（2025 年版，覆盖全癌种）
│   └── _deprecated/                # 【弃用】已评估、不产出任何成品的原件；可整目录删除，不参与流水线
│       ├── cblue/                  #   4 个未采用子任务 zip：CMeEE-V2 / CHIP-CTC / CMedCausal / KUAKE-IR
│       ├── codetables/nhc/         #   （1）疾病分类 2.0（35,865）、（2）手术操作 3.0（13,652），未接入
│       └── guidelines/other/       #   超出 5 癌种的 17 份指南（膀胱/食管/胰腺/肾/子宫内膜/宫颈/卵巢/前列腺/脑胶质瘤/淋巴瘤/黑色素瘤/血液病等）
├── tools/                          # 【工具】编号脚本，输入读 raw/ 或 fetched/，中间写 cache/，成品写 data/clean/
│   ├── 1_extract_cancer.py         # cmedqa2 步骤1：解压 + 筛 5 癌种 → cache/cmedqa2/
│   ├── 2_convert_to_json.py        # cmedqa2 步骤2：cache/ → data/clean/eval_sets/
│   ├── 3_clean_pubmed_cancer.py    # pubmed_cancer 步骤1：清洗（去重/去短摘要）→ cache/pubmed_cancer/
│   ├── 4_pubmed_to_json.py         # pubmed_cancer 步骤2：cache/ → data/clean/corpus/
│   ├── 5_decode_kgdrug.py          # kgdrug 步骤1：解码 gStore 索引 → cache/kgdrug/triples.jsonl
│   ├── 6_filter_cancer_kg.py       # kgdrug 步骤2：筛 5 癌种子图 → data/clean/kg_triples/
│   ├── 8_fda_to_json.py            # fda_ndc：cache/fda_ndc/ → data/clean/drug_labels/
│   ├── 9_guidelines_to_json.py     # guidelines：人工指定元数据的文档 → data/clean/guidelines/（文本自检 + SHA-256）
│   ├── 10_fetch_nhc_guidelines.py  # guidelines：卫健委通知页 21 份附件下载 + 5 癌种自动录入
│   ├── 11_fetch_colorectal_guidelines.py  # guidelines：结直肠癌 2015 诊疗规范 + 2024 筛查方案下载/转录 + 录入
│   ├── 12_ingest_inbox_guidelines.py      # guidelines：inbox/ 新文件按癌种归档 → external/nccn/（非交付物）并录入
│   ├── 13_cblue_terminology.py            # cblue：ICD-10 码表 + CMeIE 尾实体 → data/clean/terminology/（A5）
│   ├── 14_cblue_kg.py                     # cblue：CMeIE 关系 → data/clean/kg_triples/（A6）
│   ├── 15_fetch_atc.py                    # WHO ATC/DDD Index 两级下钻 → fetched/atc/atc_oncology.csv（750 条，含 A04 止吐 / G03 性激素）
│   ├── 16_atc_mapping.py                  # 中文药名 ↔ INN ↔ ATC 匹配 → 回补 terminology drug atc/en_name + drug_catalog atc_code
│   ├── 17_fetch_icdo3.py                  # NHC 资料包下载 + M 码表校验（表头/编码/名称/行为码/行数/SHA-256）→ fetched/codetables/
│   ├── 18_icdo3_mapping.py                # M 码表 → 回补 terminology disease icd_o3（4 位 WHO 写法，原 5 位码存 annotation）
│   ├── 19_fetch_openfda_labels.py         # openFDA 说明书四段英文 interim → drug_catalog.label_en_interim；合并人工中文覆盖
│   ├── 20_guideline_drug_extract.py       # 指导原则 PDF → 中文适应证/用法用量/相互作用（20/49）→ drug_catalog.indications/dosage
│   ├── 21_a2_recommendation_extract.py    # guidelines → A2 结构化推荐条目（批次一肺癌 145 条，含表格分支与逐句页码）→ data/clean/recommendations/
│   ├── 22_a3_disease_profile.py           # guidelines → A3 疾病档案（1 主体 + 5 亚型）→ data/clean/disease_profiles/
│   ├── 23_fetch_caca_csco_guidelines.py   # A1 补源：CACA 英译版 PDF + 官网中文摘要转录 + CSCO 书目元数据
│   ├── 24_a2_caca_recommendation_extract.py  # CACA 英译版 → A2 英文条目（69 条，lang=en，独立文件）
│   ├── 25_align_drug_catalog.py           # A4 字段名对齐（canonical_zh→generic_name、atc→atc_code，补 brand_names 等）→ drug_catalog_v2.json
│   ├── 26_fetch_cmkb_drugs.py             # 【不随仓库分发】CMKB 目录级字段抓取（2,724 条）→ fetched/cmkb_drugs/；详情正文需登录，未采集
│   ├── 27_match_cmkb_to_catalog.py         # 【不随仓库分发】CMKB ↔ A4 药单匹配 + 缺口评估 → cache/，不写 data/clean/
│   ├── 29_cmkb_a4_interim.py               # 【不随仓库分发】CMKB 目录级字段 → A4 缺口 interim（内部参考，21 药；补适应证 18 / 禁忌 3）→ fetched/cmkb_drugs/a4_interim.json
│   ├── 30_fetch_cn_labels.py               # 企业官网中文说明书采集（13 药；robots 检查 + 低频 + sidecar 记 fetched_at）→ fetched/labels_cn/
│   ├── 31_merge_cn_labels.py               # 只填空合并中文原文字段 / cn_registration / label 元数据；英文 interim 整块替换 → drug_catalog_v2.json
│   └── word_to_docx.ps1            # 辅助：PowerShell + Word COM 把 .doc 转 .docx（供 11 号脚本调用）
├── cache/                          # 【处理缓存】脚本中间产物，可整目录删除后重跑再生；不放源数据/成品
│   ├── cmedqa2/                    # cmedqa2 中间产物（含 _unzipped/ 解压临时目录）
│   ├── pubmed_cancer/              # pubmed_cancer 中间产物（cleaned_records.json）
│   ├── kgdrug/                     # kgdrug 中间产物（triples.jsonl 528,039 条，约 162MB）
│   ├── fda_ndc/                    # fda_ndc 中间产物（oncology_products.csv 2,235 条）
│   ├── cblue/                      # cblue 中间产物（_unzipped/ 解压 + kg_candidates.json）
│   ├── codetables/                 # codetables 中间产物（icdo3_mapping.json：18 号逐条映射审计；icdo3_source_check.json：17 号抓取校验报告；_unzipped/：资料包解压临时目录）
│   ├── drug_labels/                # drug_labels 中间产物（openfda_match.json：19 号候选打分审计；zh_override_audit.json：中文覆盖校验审计；guideline_extract.json：20 号逐药抽取审计；align_v2_audit.json：25 号字段改名审计；cmkb_match_audit.json：27 号 CMKB↔A4 匹配评估）
│   ├── recommendations/            # recommendations 中间产物（a2_extract_audit.json：21 号块数/页数/各过滤环节丢弃计数；a2_caca_extract_audit.json：24 号英文抽取审计）
│   ├── disease_profiles/           # disease_profiles 中间产物（a3_extract_audit.json：22 号 section 填充数与缺口清单）
│   └── guidelines/                 # guidelines 中间产物（nhc_2022_attachments.json、nccn_2026_documents.json、caca_csco_20261028.json）
├── data/
│   └── clean/                      # 【输出】最终交付 JSON，按功能类型分目录
│       ├── eval_sets/
│       │   ├── eval_qa_cancer.json        # 成品 JSON（1,349 条，问答评测集）
│       │   └── README.md                  # 该功能目录录入说明
│       ├── corpus/
│       │   ├── cancer_literature_corpus.json  # 成品 JSON（33,802 条，文献语料）
│       │   └── README.md
│       ├── kg_triples/
│       │   ├── kg_cancer_subgraph.json    # 成品 JSON（639 条关系，A6 图谱三元组）
│       │   ├── kg_cmeie_cancer.json       # 成品 JSON（187 条关系，CBLUE CMeIE 癌症子图）
│       │   └── README.md
│       ├── terminology/
│       │   ├── terminology_cancer.json    # 成品 JSON（377 条术语，A5 术语字典）
│       │   └── README.md
│       ├── drug_labels/
│       │   ├── drug_catalog_v2.json       # 成品 JSON（49 条记录：48 种 FDA 命中 + 信迪利单抗官网建档；中文适应证/用法用量 26；中文禁忌 38 / 不良反应 32；13 条有中文说明书全文与国药准字）
│       │   ├── drug_catalog_v1_20261025.json  # v1（旧字段名 canonical_zh / atc，保留比对）
│       │   └── README.md
│       ├── recommendations/
│       │   ├── recommendations_lung_20261028_v3.json  # A2 结构化推荐条目（145 条，逐句真实页码，当前版本）
│       │   ├── recommendations_lung_20261028_v2.json  # A2 v2（145 条，page 为块起始页，保留比对）
│       │   ├── recommendations_lung_20261028.json     # A2 v1（141 条，历史版本保留比对）
│       │   ├── recommendations_lung_caca_20261028.json  # A2 英文条目（69 条，CACA 官方英译版，lang=en）
│       │   └── README.md
│       ├── disease_profiles/
│       │   ├── disease_profiles_lung_20261028_v2.json # A3 疾病档案（6 条：1 主体 + 5 亚型，icd10 取 4 位 WHO 码，当前版本）
│       │   ├── disease_profiles_lung_20261028.json    # A3 v1（icd10 为国家临床版 5 位码，保留比对）
│       │   └── README.md
│       └── guidelines/
│           ├── guidelines_lung_2022_20261025.json     # A1（原发性肺癌，官网原件）
│           ├── guidelines_gastric_2022_20261025.json  # A1（胃癌）
│           ├── guidelines_breast_2022_20261025.json   # A1（乳腺癌）
│           ├── guidelines_thyroid_2022_20261025.json  # A1（甲状腺癌）
│           ├── guidelines_colorectal_2015_20261025.json  # A1（结直肠癌诊疗规范 2015，.doc→.docx）
│           ├── guidelines_colorectal_2024_20261025.json  # A1（结直肠癌筛查与早诊早治方案 2024，正文转录）
│           ├── guidelines_all_2025_20261025.json      # A1（全癌种用药指导原则）
│           ├── guidelines_lung_nccn2026_20261025.json      # NCCN NSCLC / SCLC / 肺癌筛查（3 条，非交付物）
│           ├── guidelines_lung_caca2024_20261028.json      # CACA 英译版全文 + 官方中文摘要（2 条）
│           ├── guidelines_lung_csco2025_20261028.json      # CSCO NSCLC 2025（1 条，仅书目元数据）
│           ├── guidelines_breast_nccn2026_20261025.json    # NCCN 乳腺癌（非交付物）
│           ├── guidelines_colorectal_nccn2026_20261025.json # NCCN 结肠癌 + 直肠癌（2 条，非交付物）
│           ├── guidelines_gastric_nccn2026_20261025.json   # NCCN 胃癌（非交付物）
│           ├── guidelines_thyroid_nccn2026_20261025.json   # NCCN 甲状腺癌（非交付物）
│           └── README.md
├── external/                       # 【不可交付】版权受限资料，不进入 raw/、不随竞赛交付
│   ├── nccn/                       #   NCCN 指南 8 份原件（版权保留、禁止再分发），仅供内部评审，按官方格式引用
│   └── bios/                       #   BIOS v3 术语库 3 个压缩包（CC BY-NC-ND 4.0），仅隔离存放、不产出交付物
├── README.md                       # 本文档
└── 医疗数据需求清单.md
```

> 说明：原 `7_clean_fda_ndc.py`（fda_ndc 过滤步骤）已移除，其产物固化在 `cache/fda_ndc/oncology_products.csv`；重跑 fda_ndc 只需执行 `8_fda_to_json.py`，该目录请勿删除。

## 2. 数据集登记表

| 数据集 id | 来源 | 内容 | License | 状态 | 产出位置 |
|---|---|---|---|---|---|
| `cmedqa2` | GitHub cMedQA2 v2.0 | 中文社区医疗问答（10.8 万问 / 20.3 万答），已筛 5 癌种相关 | 仅限非商业研究（CC BY-NC 类） | 已完成初筛 + JSON 转换，待医学审核 | `data/clean/eval_sets/` |
| `pubmed_cancer` | [HuggingFace cyberpsych/PubMed-Cancer-NLP-Textual-Dataset](https://huggingface.co/datasets/cyberpsych/PubMed-Cancer-NLP-Textual-Dataset) | PubMed 癌症文献摘要（PMID/标题/摘要），收录 lung/breast/colorectal/gastric 4 类（**无 thyroid**） | apache-2.0（可商用） | 已完成清洗 + JSON 转换（33,802 条），待医学审核；定位为文献语料 | `data/clean/corpus/` |
| `kgdrug` | 原 `tdb_drug_new/`（gStore 建库目录，命名空间 kgdrug.com，2018 建库） | 医药知识图谱：疾病 7,825 / 症状 7,899 / 药品 89,556，已解码为 528,039 条三元组并筛出 5 癌种子图 | **未知（需溯源）** | 已完成解码 + 5 癌种筛选（639 条关系），待医学审核；定位为 A6 图谱关系补充 | `data/clean/kg_triples/` |
| `fda_ndc` | FDA NDC Directory 公开数据文件（`product.txt`，快照至 20271231） | 美国药品目录 116,364 行；按 A4 药单筛出 48 种药、2,235 条制剂（剂型/途径/规格/厂牌/申请号/药理分类） | 公有领域（美国政府作品，可商用） | 已完成过滤 + 聚合，待医学审核；定位为 **A4 基础字段（无说明书正文）**，`atc_code`/`atc_parent` 由 16 号脚本回补 48/48，`generic_name`/`brand_names` 等字段名由 25 号脚本对齐 §A4 | `data/clean/drug_labels/` |
| `openfda_label` | openFDA drug/label API（<https://api.fda.gov/drug/label.json>，2026-10-27 抓取；`tools/19_fetch_openfda_labels.py` 可幂等重抓） | 美国 FDA 公开标签：按 A4 药单检索，45/48 命中，取适应证/用法用量/禁忌/不良反应四段英文（未命中：阿替利珠单抗、仑伐替尼、奥希替尼） | 公有领域（美国政府作品，可商用） | 已完成抓取 + 合并，待医学审核；定位为 **A4 中文补全前的英文 interim**：写入 `label_en_interim`（`status=interim_pending_zh`，含 `fetched_at`/`source_url`）；13 种已由企业官网中文说明书整块替换（原英文摘要留在 `*_source.replaced_interim`），其余仍为英文 interim（禁忌 25 / 不良反应 19），**不得直接交付** | `fetched/openfda_labels/`、`data/clean/drug_labels/` |
| `cn_labels` | 上市许可持有人/生产企业官网公开中文说明书（罗氏 assets.roche.com、礼来医学网、辉瑞医学信息网、江苏豪森、信达生物）；`tools/30_fetch_cn_labels.py` 采集 + `31_merge_cn_labels.py` 合并 | 13 个唯一药品的说明书全文（PDF/HTML 原文 + 抽取文本）：适应证、用法用量、禁忌、不良反应、批准文号、商品名、规格、持有人、生产企业 | 企业官网公开页面，无登录/验证码/付费墙；**版权归各持有人，仅限内部知识库使用，不得再分发或商用**（逐条 `usage_note`） | 已完成：中文适应证/用法用量 6、禁忌 13、不良反应 13、国药准字 13、`cn_registration` 13、`label` 元数据 13；原文存 `fetched/labels_cn/downloads/`，文本存 `fetched/labels_cn/text/`；失败来源与原因见 `fetched/labels_cn/failures.json` | `fetched/labels_cn/`、`data/clean/drug_labels/` |
| `nmpa_labels` | 人工填写的说明书要点（按条标注 `source_name`/`source_url`）；NMPA 站点对脚本/自动化浏览器返回 HTTP 412，查询库只含注册信息 | A4 中文正式字段：国药准字、适应证、用法用量与调整、禁忌、不良反应（含频率）、相互作用、中文说明书 `label` | NMPA 公开说明书/企业官网 PDF（人工录入并留存出处） | **剩余待补（人工）**：中文适应证/用法用量 23、禁忌 11、不良反应 17、国药准字与中文说明书 36；模板 `tools/19_fetch_openfda_labels.py --template`，逐条清单见 `raw/nmpa_registry/a4_pending_fill.csv` | `data/clean/drug_labels/`（`label` 与 A4 字段） |
| `nmpa_registry` | 国家药品监督管理局数据查询页（人工查询打印，样例 `raw/nmpa_registry/nmpa_registry_alectinib_HJ20180047.pdf`） | 注册证号/批准文号、产品名称（中/英）、商品名、剂型、规格、包装规格、上市许可持有人、生产厂商、发证/有效期、境内责任人、药品本位码、产品类别 | NMPA 公开注册信息（人工查询留存） | 已归档 1 份样例（阿来替尼，国药准字HJ20180047）；**仅补 `approval_no`/商品名/剂型/规格/持有人**，查询页**无说明书正文**；已生成 48 药逐条缺项清单 `a4_pending_fill.csv` 供人工补录 | `raw/nmpa_registry/`（供人工逐药查询对照） |
| `cmkb` | 临床医学知识库 CMKB（中国医学科学院医学信息研究所/图书馆，<http://www.cmkb.cn>）；前端接口 `POST /front/date/pagelist`，`tools/26_fetch_cmkb_drugs.py` 可幂等重抓 | 药物库存量 **2,724 条**（化学药 hxyw 1,164 + 中成药 zcy 1,560）：药物名、类别、适应证、禁忌症、药物相互作用；有值覆盖：适应证 2,577 / 禁忌 994 / 相互作用 825 | **站点版权声明（© 中国医学科学院 北京协和医学院医学信息研究所/图书馆），无 robots.txt、无开放许可** | 已抓取目录级字段，**未采集详情正文**（`/view/disease/todetail` 正文由登录态渲染，脚本不绕过登录；`/tomain?tabletype=user` 同样 302 重定向循环，未登录不可用）；29 号脚本已把目录级字段对齐 A4 缺口，产出 `a4_interim.json`（21/48 命中，可补适应证 18 种、禁忌 3 种；用法用量/不良反应无目录字段），每条带 source/URL/抓取时间/license_status，仅作内部参考；写入 `fetched/` 而非 `data/clean/`，对外分发/入库前需向 sinomed@imicams.ac.cn 取得书面授权 | `fetched/cmkb_drugs/` |
| `guidelines` | 国家卫健委官网（[肿瘤和血液病相关病种诊疗指南 2022 年版通知](https://www.nhc.gov.cn/yzygj/c100068/202204/0c1f7d3aca0545abbeb02030ce255930.shtml)，国卫办医函〔2022〕104号）+ [结直肠癌筛查与早诊早治方案 2024 年版通知](https://www.nhc.gov.cn/ylyjs/gzdt/202408/42f43b5f0c4c4ebe90c78ee127959b92.shtml) + [结直肠癌诊疗规范 2015 年版](https://www.nhc.gov.cn/yzygj/c100068/201510/922e2426eb02416e8344715cab601f2e.shtml) + 新型抗肿瘤药物临床应用指导原则 2025 年版；NCCN 指南 8 份（用户提供，存 `external/nccn/`）；CACA 肺癌指南官方英译版（[Springer HIO 2024;3:10](https://link.springer.com/article/10.1007/s44178-024-00069-w)，CC BY 4.0）+ 官网中文摘要；CSCO 非小细胞肺癌诊疗指南 2025（人卫社付费电子书） | 元数据 **18 条**：NHC 7 份（2022 批 4 份 + 结直肠 2 份 + 全癌种用药原则 1 份）+ NCCN 8 份（NSCLC/SCLC/肺癌筛查、乳腺、结肠、直肠、胃、甲状腺，**仅著录、非交付物**）+ CACA 2 份（英译版全文 44 页 + 中文摘要 382 字符）+ CSCO 1 份（**仅书目，正文未采集**） | NHC 公开可引用；CACA 英译版 CC BY 4.0 可交付；**NCCN 版权保留、禁止再分发**；CSCO 付费电子书未采集 | 已完成归档 + 文本自检 + SHA-256 + 元数据录入（18 条），待医学审核；**可交付原件 9 份（NHC 7 + CACA 2），仍低于 A1 10~20 份要求**；中文完整指南仍只有 NHC 一家，CACA 中文原版需会员、CSCO 需付费，均未获取（见 `data/clean/guidelines/README.md`「获取限制」节）；其中《新型抗肿瘤药物临床应用指导原则（2025年版）》另被 `tools/20_guideline_drug_extract.py` 原文抽取（非整篇复制），为 A4 提供 20 种药的中文适应证/用法用量 | `data/clean/guidelines/` |
| `bios` | THUMedInfo BIOS v3（用户提供压缩包，2026-10-25 由 `inbox/` 归档至 `external/bios/`） | 术语 46,024,274 / 概念 22,104,559 / 关系 99,849,860；Concepts 为 UMLS 式超细概念（PT/ET、EN/CN），Semtypes 给语义类型，Relations 为三元组 | **CC BY-NC-ND 4.0（ND 禁止分发衍生作品）** | **不采用**：已评估为不可交付（粒度错位、无 ICD-10/ICD-O-3/ATC 编码、中文机器翻译错误多）；仅存 `external/bios/` 作内部比对参考，**不产出 `data/clean/` 成品**；A5 改用官方码表建设 | 无（`external/bios/README.md` 记录评估结论） |
| `cblue` | CBLUE 中文医疗 NLP 基准（用户提供 6 个子任务 zip，2026-10-27 归档；官网 tianchi.aliyun.com/cblue，GitHub CBLUEbenchmark/CBLUE） | CHIP-CDN（含 **ICD-10 北京临床版 v601 码表 40,474 条** + 6,000 条诊断归一）、CMeIE-V2（14,339 条文本 / 64,835 三元组）、CMeEE-V2（15,000 条 / 82,649 实体）、CHIP-CTC（22,962 条入排标准）、CMedCausal（800 条）、KUAKE-IR（10 万 query / 96 万段落） | Apache-2.0（官方仓库）；数据经天池发布，商用交付前建议复核原始授权 | **部分采用**：CHIP-CDN 的 ICD-10 码表 → A5 疾病条目 200 条（编码 confirmed）；CMeIE-V2 → A5 尾实体 177 条（40 条 disease 已补 `icd_o3`、15 条 drug 已补 `atc`；6 条药物类别名/短语已按非单药剔除）+ A6 三元组 187 条；CMeEE-V2 / CHIP-CTC / CMedCausal / KUAKE-IR 未采用（癌种覆盖不足或无对应需求类别），原件已移至 `raw/_deprecated/cblue/` | `data/clean/terminology/`、`data/clean/kg_triples/` |
| `codetables` | ① 国家卫健委 HQMS 2.0 官方资料包（<https://www.hqms.org.cn/usp/downFile.html>，2026-10-27 下载；`tools/17_fetch_icdo3.py` 可重下并做结构 + SHA-256 校验）② WHO ATC/DDD Index（<https://atcddd.fhi.no/atc_ddd_index/>，索引更新 2026-01-20） | ① 疾病分类与代码国家临床版2.0（2022汇总版）35,865 条 / 手术操作分类代码国家临床版3.0 13,652 条 / **肿瘤形态学编码（M码）国家临床版2.0 1,427 条**；② **ATC 5 级码 750 条（L01/L02/L03/H02/H03/M05/A11/A12/A04/G03 十个顶级组，2026-10-30 补 A04 止吐与 G03 性激素）** | 卫健委行业码表（公开可引用）；WHO ATC 版权，仅作编码对照引用、不整体再分发 | 已补码：`icd_o3` 189/240（4 位 WHO 写法，原 5 位码留 annotation）、`atc` 15/15（drug）；`loinc` 非必填字段，当前 examination 不适用。**（1）疾病分类 2.0、（2）手术操作 3.0 未接入**（与需求类别不对应），原件已移至 `raw/_deprecated/codetables/nhc/` | `fetched/codetables/nhc/`（M 码抓取结果，17 号）、`fetched/atc/`（ATC 抓取结果） |

> 新数据集到位后在此表加一行，并同步建 `raw/<id>/`（`guidelines` 例外：A1 要求原文按癌种存放，故为 `raw/guidelines/<癌种|all>/`；超出 5 癌种的放 `raw/_deprecated/guidelines/other/`）。
> 多个数据集可汇入同一功能目录；产出 JSON 中每条记录的 `source` 字段写完整来源说明，`origin` 字段写来源短码，目录名不再体现数据集。
> A1 `document` 记录按需求清单 §A1⑥ 字段表使用 G6 溯源五字段（`source_name`/`source_version`/`source_section`/`source_file`/`updated_at`），不设 `source`/`origin`。

## 3. 标准工作流程（新增一个数据集时）

1. **登记原文件**：新找到但尚未分类的文件先放 `inbox/`；确认癌种与功能类型后，**采用的**归档到 `raw/<dataset_id>/`（保留原 LICENSE），**不采用的**（超出 5 癌种、无对应需求类别、质量不达标、授权不允许）直接移入 `raw/_deprecated/<dataset_id>/`，`inbox/` 保持为空；在本 README 第 2 节登记表加一行（来源、License、内容）。
2. **编写清洗脚本**：在 `tools/` 新增该数据集的脚本（编号递增），路径遵循四个固定去向：
   - 输入只读 `raw/<dataset_id>/`；**网页抓取结果写 `fetched/<来源>/`**（未加工、供下游读取）；
   - 中间产物写 `cache/<dataset_id>/`；
   - 成品写 `data/clean/<功能目录>/`（**只按功能类型归类，不建数据集子目录**；目录名用需求清单 G3 固定名，如 `eval_sets/`、`drug_labels/`、`kg_triples/`）。
3. **跑流水线**：按编号依次执行；`cache/` 可随时删除重跑验证可复现性（fda_ndc 例外，见上文说明）。
4. **写录入说明**：每个功能目录放一份 `README.md`，必须包含：文件清单与各自来源/License、字段结构、数据量统计、待人工复核事项（新增数据集汇入已有目录时，在该 README 追加一行文件说明即可）。
5. **来源落字段**：每条记录的 `source` 写完整来源文字（数据集名 + 渠道 + 授权 + 快照日期），`origin` 写来源短码；禁止只靠目录名表达来源。
6. **对齐验收**：字段名、枚举值、ID 命名对齐需求清单 §0.5 编号体系与 §6.1 受控词表；`annotation.status` 保持 `draft`，医学审核通过后方可改 `approved` 入库。

## 4. 硬口径（采集与清洗全程遵守，详见需求清单 §0.2）

- **只做文本类**：不采影像数据、不使用训练语料、不做 OCR；源文档仅收文本可提取的原生 PDF/DOCX。
- **疾病范围仅 5 癌种**：`lung` / `breast` / `colorectal` / `gastric` / `thyroid`（外加癌前病变、良性肿瘤、肿瘤并发症）。
- **不使用真实患者数据**：演示与评测数据全部为模拟 + 脱敏虚构；公开数据集需保留原 License 标注。
- **License 红线**：CC BY 可竞赛/商用；**CC BY-NC 仅限研究用途**，竞赛交付前需确认授权。
- **版权受限资料隔离**：NCCN 等「保留所有权利」的资料一律存 `external/`，**不进 `raw/`、不随交付**；报告中只能按官方引用格式转述推荐意见，禁止复制 Algorithm 流程图、表格、图表与大段 Discussion 文本（详见 `data/clean/guidelines/README.md`）。**CC BY-NC-ND 类**（如 BIOS v3，ND 禁止分发衍生作品）同样存 `external/`，**不得清洗输出到 `data/clean/`**（详见 `external/bios/README.md`）。

## 5. Git 仓库收录范围

**仓库只收「脚本 + 交付成品 + 各目录 README/来源说明 + 抽取后的文本与元数据」**，原始数据与受限资料不入库（规则见 `.gitignore`）：

| 不入库路径 | 原因 | 获取方式 |
|---|---|---|
| `external/`（NCCN 指南 8 份、BIOS v3 术语库） | 版权保留 / CC BY-NC-ND（ND 禁止分发衍生作品） | 需自行向 NCCN、THUMedInfo 申请；仅内部评审使用 |
| `raw/` 下原始数据集（cmedqa2、pubmed_cancer、cblue、kgdrug、fda_ndc、guidelines 原件、`_deprecated/`） | 体积大且各有独立授权，不在仓库二次分发 | 按第 2 节登记表的来源链接自行下载；各目录保留上游 README/LICENSE |
| `raw/guidelines/` 指南 PDF | 大体积原件 | NHC 官网附件由 10/11 号脚本下载；CACA 英译版由 23 号脚本下载 |
| `fetched/codetables/*.rar` | 5.5 MB 资料包原件 | `python tools/17_fetch_icdo3.py` 重下 |
| `fetched/cmkb_drugs/` | CMKB 站点版权保留、无开放许可，不可对外分发；`a4_interim.json` 亦为内部参考，不得写入 `data/clean/` | `python tools/26_fetch_cmkb_drugs.py` + `python tools/29_cmkb_a4_interim.py`（需书面授权后方可对外使用） |
| `fetched/labels_cn/downloads/` | 企业官网说明书 PDF/HTML 原件与 sidecar meta，**版权归各持有人、不得再分发**；只入库 `text/` 抽取文本与 `labels_cn.json` 元数据 | `python tools/30_fetch_cn_labels.py` 重下（公开页面、低频、先读 robots.txt） |
| `cache/` | 脚本中间件，可删除重生 | 按第 3 节编号依次重跑脚本 |
| `data/clean/guidelines/*nccn*` | NCCN 元数据记录，非交付物 | 内部评审用，不公开 |

- **可复现**：`data/clean/` 下的交付 JSON 均已入库，直接可用；要重建只需按 `tools/` 编号顺序执行（各功能目录 README 的「复现」节有命令）。
- **凭据**：仓库不包含任何 token、密钥或账号信息（`.env`、`*.pem`、`*.key` 等已被忽略）。
- **注意**：`data/clean/corpus/cancer_literature_corpus.json` 约 44.6 MB，是已入库的交付成品；GitHub 单文件上限 100 MB，后续如需继续扩充语料请改用 Git LFS 或拆分文件。

**采集脚本收录规则（2026-11-04）**：**拿不到数据、或取到的数据不能用于交付的采集脚本，一律不进仓库**。以下脚本仅保留在本地，不随仓库分发（`tools/` 下同名文件已由 `.gitignore` 排除）：

| 脚本 | 不收录原因 |
|---|---|
| `tools/26_fetch_cmkb_drugs.py` | CMKB 无开放许可、详情正文需 SinoMed 登录授权；只能取到目录级字段，产出仅供内部评估 |
| `tools/27_match_cmkb_to_catalog.py` | 依赖 26 号产物，输出仅落 `cache/` 做缺口评估，不进入 `data/clean/` |
| `tools/29_cmkb_a4_interim.py` | 产出 `fetched/cmkb_drugs/a4_interim.json`，为受限 interim（`license_status=restricted_internal_only`），不可交付 |

**判定口径（2026-11-04 确认）**：按「**产出能否交付**」判定，不按「来源是否开放」判定。产出是可交付的元数据/成品，脚本即保留；只有取不到数据、或取到的数据只能内部参考、无法进入交付物的脚本才移出。据此明确保留以下两个边界脚本，**后续不得照字面按「来源有版权/付费」误删**：

| 脚本 | 保留理由 |
|---|---|
| `tools/12_ingest_inbox_guidelines.py` | 不联网抓取，只归档用户自备文件并录入元数据；产出是可交付的指南元数据（NCCN 原件仍在 `external/`，不复制正文） |
| `tools/23_fetch_caca_csco_guidelines.py` | CACA 英译版为 CC BY 4.0、可公开下载；CSCO 仅著录书目元数据（付费正文未采集）；两类产出均为可交付元数据 |
