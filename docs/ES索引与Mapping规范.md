# ES 索引与 Mapping 规范（C2 · 施工图）

> **文档定位**：医疗版 Elasticsearch 索引的**权威定义**——索引命名、settings、字段 mapping、现状→医疗字段映射对照。C1 中 BE-31（`repositories/elasticsearch.py`）、BE-02（`config.py` 索引名）、BE-32（`schemas.py`）均以本文档为准。
>
> **字段业务约束权威**：字段语义、必填性、枚举值以主方案 §5.7.2 / §5.7.3 为准；本文档定义其 **ES 物理形态**（类型 / 分析器 / 是否索引）。二者冲突时：业务口径以主方案为准、物理形态以本文档为准。
>
> **边界声明**：只定义索引，不含建索引代码；建索引逻辑改造见 C1 BE-31，入库脚本见 C3。
>
> 版本：v1.0（2026-10-12 初稿 · 待检查点②确认）

---

## §0 已定案架构决策（2026-10-12 用户确认）

| 编号 | 决策 | 结论 |
|---|---|---|
| D2-01 | 主检索索引架构 | **方案 C**：检索型知识（DOC / REC / DRUG / TERM）合并单主索引 `medical_knowledge`，`data_type` 字段分域；疾病档案独立 `medical_disease_profiles`；图谱沿用双索引；缓存沿用单索引 |
| D2-02 | B 组功能支撑数据归宿 | **文件态，不入 ES**：红旗征 / 槽位 / 分诊 / 随访模板 / 患者消息 / 质控规则 / 运营指标以 JSON 落 `data/` 固定目录（G3），服务启动加载，管理端走文件读写 |
| 沿用 | 图谱索引命名 | `medical_kg_triples` / `medical_kg_entities`（C1 BE-12/BE-31 已引用） |

**方案 C 取舍记录**：与主方案 §5.2「REC 为检索主单元」+ §5.5「disease_profile 索引」表述吻合；混合检索（一次 query 同时召回推荐条目 + 说明书 + 术语）单索引内完成，RRF / 两阶段精排管线（BE-15）改动最小。代价：单索引字段并集存在稀疏（如 REC 无 `atc_code`），靠 §3 字段表「适用域」列约束。

---

## §1 设计总则

| 项 | 约定 | 说明 |
|---|---|---|
| 集群 | 沿用 `medical-rag-platform` / `medical-es:9201` | 已隔离，不与法规栈共卷 |
| 分片 / 副本 | `number_of_shards: 1`，`number_of_replicas: 0` | 单节点现状，数据量 MB~GB 级 |
| 中文分析器 | `chinese_analyzer`：`ik_max_word` + `lowercase` | IK 插件已固化进镜像（Dockerfile.es） |
| 英文分析器 | `text_analyzer`：`standard` + `lowercase` + `stop` | 沿用现状 |
| 向量 | `dense_vector`，`dims: 1024`，`index: true`，`similarity: cosine` | bge-m3 输出维度，dense_vector 建后 dims 不可改 |
| 数据迁移 | **无迁移**：`medical_es_data` 全新卷，法规数据不带入 | 医疗数据全新灌入（ingest 清空重建模式沿用） |
| 索引别名 | 暂不引入（直接索引名） | 单人项目，重建走停机窗口；引入别名收益不足 |
| 索引创建 | 首次启动自动建（`_create_index_if_not_exists` 模式沿用） | 5 个索引全部纳入该机制 |
| 枚举字段 | 一律 `keyword` 类型，取值以主方案 §5.7.3 为准 | 入库前由校验脚本卡枚举（V4，见 C3） |

---

## §2 索引架构总览

| 索引名 | 承载数据 | data_type 值 | 向量 | 主要消费方 |
|---|---|---|---|---|
| `medical_knowledge` | 指南文档元数据、推荐条目、药品说明书、术语字典 | `doc` / `rec` / `drug` / `term` | ✅ | 检索（BE-15）、问答（BE-17）、对比 / 专题、管理端（BE-13） |
| `medical_disease_profiles` | 疾病档案（14 section 双版本） | —（整索引单一类型） | ✅（概述向量） | 疾病知识库（NM-01）、相似疾病（BE-28） |
| `medical_kg_triples` | 图谱三元组 | — | ❌ | 图谱（BE-12）、症状反查、实体消歧 |
| `medical_kg_entities` | 图谱实体（消歧后） | — | ✅ | 实体消歧（BE-21）向量对齐 |
| `medical_analysis_cache` | 专题 / 对比分析缓存 | — | ❌ | 结构化分析缓存（BE-24） |

**不入 ES 的数据（文件态，D2-02）**：B 组全部（红旗征 RF / 预问诊槽位 / 分诊映射 / 随访模板 TPL / 患者消息 / 质控规则 QC / 运营指标 METRIC）+ C 组评测集与模拟病例（EVAL / CASE，评测脚本直读 JSON）+ DOC 原文 PDF（仅存 `file_path` 引用）。目录布局见数据清单 G3，脚本交付见 C3。

---

## §3 主索引 `medical_knowledge`

### 3.1 文档组织与检索单元

| data_type | 一条 ES 文档 = | content 字段内容 | 向量来源 | 分块 |
|---|---|---|---|---|
| `doc` | 一份指南 / 规范的**元数据记录** | 文档摘要（标题 + 发布机构 + 目录概述，供标题级检索） | 摘要文本 | 不分块 |
| `rec` | **一个推荐条目（检索主单元）** | `recommendation_text` 原文 | 推荐文本 | 不分块（条目即单元） |
| `drug` | 一份药品说明书（长文按块拆） | 适应证 / 用法 / 禁忌 / 不良反应拼接文本 | 各块文本 | **分块**（`chunk_index` 生效） |
| `term` | 一条术语 | `canonical + synonyms + en_name` 拼接 | 同左 | 不分块 |

### 3.2 settings（沿用现状，无改动）

```json
{
  "number_of_shards": 1,
  "number_of_replicas": 0,
  "analysis": {
    "analyzer": {
      "text_analyzer":   { "type": "custom", "tokenizer": "standard",    "filter": ["lowercase", "stop"] },
      "chinese_analyzer":{ "type": "custom", "tokenizer": "ik_max_word", "filter": ["lowercase"] }
    }
  }
}
```

### 3.3 字段 mapping

**通用层（全部 data_type 共有）**

| 字段 | ES 类型 | 说明 |
|---|---|---|
| data_type | keyword | `doc` / `rec` / `drug` / `term`（检索必带过滤或默认 `rec,drug,term`） |
| title | text(chinese_analyzer) + keyword 子字段 | 各类标题（文档名 / 条目主题 / 药品通用名 / canonical） |
| content | text(chinese_analyzer) + keyword 子字段 | 检索正文（§3.1 定义） |
| embedding | dense_vector(1024, cosine, index) | bge-m3 归一化向量 |
| chunk_index | integer | 仅 drug 分块生效，其余 = 0 |
| review_status | keyword | `draft` / `reviewed` / `approved`（仅 approved 入库，§5.7.3） |
| taxonomy_version | keyword | 分类体系版本（沿用） |
| topics_details | nested {id, label_zh, score, matched_keywords} | 医疗 taxonomy 自动标注（沿用现状结构） |
| updated_at | date | 入库 / 更新时间 |

**DOC 专属层**

| 字段 | ES 类型 | 约束（§5.7.2-1） |
|---|---|---|
| doc_id | keyword | `DOC-<范围>-<来源>-<序号>`（亦作 ES `_id`） |
| doc_type | keyword | `guideline` / `standard` / `consensus` |
| issuer | keyword | 发布机构（过滤用；长名不需分词） |
| publish_date | **date**（`yyyy-MM-dd`） | **类型升级**：现状三日期字段为 keyword，医疗版统一为 date 支持范围过滤 / 聚合 |
| cancer_types | keyword（数组） | §5.7.3 |
| license_note | text(chinese_analyzer)，`index: false` 可选 | 版权说明，仅展示 |
| file_path | keyword | 相对路径 |
| doc_hash | keyword | SHA-256 |

**REC 专属层（检索主单元，字段最多）**

| 字段 | ES 类型 | 约束（§5.7.2-2） |
|---|---|---|
| rec_id | keyword | `REC-<癌种>-<来源>-<序号>`（亦作 ES `_id`） |
| doc_id | keyword | 引用 DOC（V5 引用完整性校验） |
| cancer_type | keyword | §5.7.3 |
| breadcrumb | keyword | `第三部分/3.2 早期治疗`（溯源展示 + 精确过滤） |
| scenario | keyword | 15 类场景枚举 |
| stage | keyword（数组） | `0/I/II/III/IV/unknown`；细分入 stage_detail（keyword） |
| stage_detail | keyword | 如 `IIIA` |
| biomarker | keyword（数组） | 20 项枚举 |
| population | text(chinese_analyzer) | 适用人群 / 前提条件 |
| verbatim | boolean | 原文摘录标记 |
| evidence_level | keyword | `high/moderate/low/very_low` |
| evidence_level_original | keyword | 原文表述 |
| rec_strength | keyword | `strong/weak/not_graded` |
| refs | keyword（数组） | 支撑文献 |
| page | integer | 原文页码 |

**DRUG 专属层**

| 字段 | ES 类型 | 约束（§5.7.2-4） |
|---|---|---|
| drug_id | keyword | `DRUG-<来源>-<序号>`（亦作 ES `_id`） |
| generic_name | keyword | 中文通用名（canonical；检索走 title/content） |
| brand_names | keyword（数组） | 商品名 |
| atc_code | keyword | ATC 码 |
| approval_no | keyword | 国药准字 |
| indications | text(chinese_analyzer) + keyword 子字段 | 适应证（过滤 + 全文双用） |
| dosage | object（动态） | `{standard, adjustment}`，仅展示 |
| contraindications | text(chinese_analyzer) | 禁忌 |
| adverse_reactions | object（动态，`enabled: false`） | 原始结构 `[{term, frequency, ctcae_hint}]` 仅存储 |
| adverse_reaction_terms | keyword（数组） | **抽平字段**：不良反应术语，供过滤 / 聚合 |
| interactions | text(chinese_analyzer) | 药物相互作用 |

**TERM 专属层**

| 字段 | ES 类型 | 约束（§5.7.2-5） |
|---|---|---|
| term_id | keyword | `TERM-<类别>-<序号>`（亦作 ES `_id`） |
| canonical | keyword | 标准名（全局唯一；分词检索走 content） |
| category | keyword | 六类：disease/drug/examination/symptom/gene/staging |
| synonyms | keyword（数组） | 别名 / 缩写 / 繁简变体 |
| icd10 / icd_o3 / atc | keyword | 按类别填 |
| pinyin | keyword | 首字母拼音（前缀检索） |
| en_name | keyword | 英文名 |
| mapping_status | keyword | `confirmed` / `pending` |

> **设计原则**：需要过滤 / 聚合 / 排序的字段一律 keyword；纯展示的大 JSON 用 object `enabled: false`（不索引、省空间，整存整取）；既要全文又要精确的（indications 等）用 text + keyword 子字段双形态。

---

## §4 疾病档案索引 `medical_disease_profiles`

### 4.1 设计要点

一条 ES 文档 = 一个疾病 profile。**检索抽平层 + 存储层**分离：

- **抽平层**（可检索 / 可过滤）：名称族（canonical / synonyms / pinyin / en）、症状全集、病理亚型、分期、治疗手段、类别 / 部位 / 科室——支撑疾病名检索、症状反查、分类浏览三个入口（主方案 §6.7）；
- **存储层**（`enabled: false`）：`sections`（14 section 专业版 JSON）、`patient_version`（患者版 JSON）——详情页整存整取，不走 ES 全文（渲染直接读文档原文，且省去巨型 mapping）。

### 4.2 字段 mapping

| 字段 | ES 类型 | 说明 |
|---|---|---|
| disease_id | keyword | `DIS-<序号>`（亦作 ES `_id`） |
| name_canonical | text(chinese_analyzer) + keyword 子字段 | 标准名（全文 + 精确双用） |
| synonyms | text(chinese_analyzer) | 别名 / 缩写（肺CA / NSCLC……），名称检索主字段之一 |
| pinyin | keyword | 首字母拼音（前缀检索） |
| name_en | text(text_analyzer) | 英文名 |
| icd10 / icd_o3 | keyword | 编码 |
| category | keyword | 四类枚举（§5.7.3 disease_profile.category） |
| body_system | keyword | 部位系统 |
| departments | keyword（数组） | 就诊科室 |
| cancer_type | keyword | 归属癌种（五癌种枚举；并发症类填宿主癌种） |
| **symptoms** | keyword（数组） | **抽平字段**：early + late + signs 全部症状名（术语字典 canonical 名）——症状反查主字段 |
| symptom_early / symptom_late / signs | keyword（数组） | 分型症状（细粒度过滤） |
| pathology_subtypes | keyword（数组） | 病理亚型名 |
| stages | keyword（数组） | 分期 |
| treatment_methods | keyword（数组） | 治疗手段（手术/化疗/靶向/免疫/放疗/内分泌…） |
| overview_text | text(chinese_analyzer) | 概述 section 纯文本（详情页摘要 + 全文检索） |
| embedding | dense_vector(1024, cosine, index) | 概述文本向量（相似疾病 KNN，BE-28） |
| sections | object，**enabled: false** | 14 section 专业版 JSON（§5.5 Schema） |
| patient_version | object，**enabled: false** | 患者版 JSON（同构） |
| section_gaps | keyword（数组） | 缺失 section 及原因 |
| links | object，**enabled: false** | 图谱关联（symptoms/drugs/checks/diseases/guidelines/genes/biomarkers）；图谱查询走 KG 索引 |
| sources | keyword（数组） | 来源引用 |
| profile_version | keyword | 版本 |
| last_updated | date | 更新时间 |

---

## §5 图谱双索引

### 5.1 `medical_kg_triples`（三元组）

沿用现状结构（L2236-2262），仅做字段替换：

| 现状字段 | 医疗字段 | ES 类型 | 说明 |
|---|---|---|---|
| law_id | **source_id** | keyword | 来源 DOC / REC ID |
| jurisdiction | **cancer_type** | keyword | 归属癌种 |
| fingerprint | fingerprint | keyword | 源文档指纹（缓存失效判断，沿用） |
| head_id / head_type / head_name | 同名保留 | keyword | 头实体 |
| head_canonical_id | 同名保留 | keyword | 消歧回填（BE-21） |
| tail_id / tail_type / tail_name / tail_canonical_id | 同名保留 | keyword | 尾实体 |
| relation | relation | keyword | 九类枚举（§5.7.3：has_symptom / examined_by / treated_by / complication_of / subtype_of / expressed_by / targeted_by / recommended_for / followed_by） |
| source_article | **source_ref** | keyword | 支撑句 / 来源章节（breadcrumb 或 refs） |
| confidence | confidence | float | 沿用 |
| extracted_at | extracted_at | date | 沿用 |

**实体类型**（head_type / tail_type）：六类对齐 term.category——`disease / drug / examination / symptom / gene / staging`（BE-20 本体重构口径）。
**文档 ID 策略沿用**：`hash(source_id + head + relation + tail + source_ref)` 幂等 upsert；按 source_id 增量抽取、指纹未变跳过。

### 5.2 `medical_kg_entities`（实体）

| 现状字段 | 医疗字段 | ES 类型 | 说明 |
|---|---|---|---|
| entity_id | entity_id | keyword | 沿用 |
| name | name | keyword | canonical 名 |
| type | type | keyword | 六类（同上） |
| aliases | aliases | keyword（数组） | 同义词 |
| jurisdictions | **cancer_types** | keyword（数组） | 出现癌种 |
| embedding | embedding | dense_vector(1024, cosine, index) | **保留**——实体消歧 L3 向量对齐依赖（BE-21，dims 建后不可改，一次性建好） |
| updated_at | updated_at | date | 沿用 |

---

## §6 分析缓存索引 `medical_analysis_cache`

现状 `analysis_reports_cache` 更名，字段微调：

| 现状字段 | 医疗字段 | ES 类型 | 说明 |
|---|---|---|---|
| cache_type | 同名 | keyword | `analysis` / `compare`（沿用） |
| topic_id | 同名 | keyword | 专题 ID |
| jurisdiction_a / jurisdiction_b | **target_a / target_b** | keyword | 对比对象（方案 / 疾病，BE-08 双模式） |
| fingerprint | 同名 | keyword | 缓存指纹（沿用） |
| report_data | 同名 | object，enabled: false | 报告 JSON（沿用） |
| created_at / updated_at | 同名 | date | 沿用 |
| cache_version | 同名 | integer | 沿用 |

文档 ID 策略沿用：`{cache_type}::{topic_id}::{target_a}::{target_b}`。

---

## §7 现状 → 医疗字段映射对照（BE-31/BE-32 改造索引）

| 现状（legal_documents） | 医疗（medical_knowledge） | 备注 |
|---|---|---|
| law_id | data_type + 各专用 ID（doc_id / rec_id / drug_id / term_id） | 单 ID 拆为分域 ID |
| jurisdiction | cancer_type（REC）/ cancer_types（DOC 数组） | |
| article_number | breadcrumb | 条款号 → 章节层级 |
| passing_date / effective_date / publication_date | publish_date（date 类型） | 三合一 + 类型升级 |
| topic / topics / topic_labels | scenario（REC 专属） | 主题 → 场景；topic 体系由 taxonomy（topics_details）承接 |
| topics_details / taxonomy_version | 同名保留 | 分类管线沿用（BE-35） |
| title / content / embedding / chunk_index / metadata | title / content / embedding / chunk_index / **结构化字段直平** | metadata 塞杂物模式废止，字段显式声明 |

---

## §8 入库与重建约定

| 项 | 约定 |
|---|---|
| 建索引 | 首次启动自动建（5 索引纳入 `_create_index_if_not_exists` 族）；mapping 即本文档 §3.3/§4.2/§5/§6，**代码中与本文档不一致时以本文档为准并回改代码** |
| 灌入 | `ingest.py` 清空 + 重建模式沿用；按 data_type 分路由（C3 详述）；ES `_id` = 各专用 ID（doc_id / rec_id / drug_id / term_id / disease_id） |
| 校验 | 入库前置校验 V1~V9（主方案 §5.7.4）：JSON Schema / 枚举 / 引用完整性 / 脱敏 / 去重——脚本口径见 C3 |
| 重建 | 停机窗口执行（`DELETE index` → 重启自动重建 → 重灌）；不引入别名零停机方案 |
| 验收 | ① 5 索引 mapping 与本文档逐字段一致 ② 空库启动无报错 ③ 肺癌首批数据灌入后 `_count` 与 manifest 一致 ④ 抽检 3 条 REC 全字段回读正确 |

---

## §9 决策与开放项汇总

| 编号 | 事项 | 状态 |
|---|---|---|
| D2-01 | 主索引架构 = 方案 C（主索引 + 疾病档案独立） | ✅ 已定案（2026-10-12） |
| D2-02 | B 组数据文件态不入 ES | ✅ 已定案（2026-10-12） |
| D2-03 | 索引别名 / 零停机重建 | ✅ 已定案：暂不引入（数据量小，停机重建可接受） |
| D2-04 | license_note 是否入索引（`index: false` 省空间 vs 可检索） | 开放项，实施 P1 时随 BE-31 一并定（倾向 index:false，展示型字段） |
| — | stage_detail / symptom 分型字段等抽平细节 | 实施中如遇检索需求变化，回写本文档保持同步 |
