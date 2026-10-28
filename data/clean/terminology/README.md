# terminology 术语字典目录

本目录存放 **A5 术语字典**成品（5 癌种实体消歧与标准化用）。当前只有一批：CBLUE 冷启动版。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `terminology_cancer.json` | 377 | 6 类实体（disease / symptom / examination / drug / staging / gene） | CBLUE CHIP-CDN 附带的 ICD-10 北京临床版 v601 码表 + CMeIE-V2 关系语料 |

## 字段结构（对齐需求清单 §A5⑥）

| 字段 | 类型 | 说明 |
|---|---|---|
| `term_id` | string | `TERM-<类别>-<4位序号>` |
| `canonical` | string | 标准名，全局唯一 |
| `category` | enum | disease / drug / examination / symptom / gene / staging |
| `synonyms` | array\|null | 别名；当前仅疾病条目有值（通用简称 + CMeIE「同义词」关系） |
| `icd10` | string\|null | ICD-10 北京临床版 v601 编码 |
| `icd_o3` | string\|null | ICD-O-3 形态学编码，**`Mxxxx/x` 4 位 WHO 标准写法**（如 `M8010/3`）；disease 240 条中 189 条已映射，51 条非形态学诊断保持 null 并在 `annotation.icd_o3_note` 记录原因 |
| `atc` | string\|null | ATC 5 级码（WHO ATC/DDD Index），drug 15 条中 14 条已映射；唯一 null 为 `雷洛昔芬`（WHO 2026 索引已无此单药） |
| `loinc` | 不设 | 需求清单 A5⑥ 字段表**无 `loinc` 字段**（仅 `icd10 / icd_o3 / atc`，按类别填）；examination 现有 51 条为影像/内镜/操作类，不适用 LOINC 检验编码 |
| `pinyin` / `en_name` | string\|null | `pinyin` 当前全为 null；drug 条目的 `en_name` 已由 16 号脚本补入 INN 英文名 |
| `mapping_status` | enum | `confirmed`（编码直接来自官方码表）/ `pending`（无编码，待核） |
| `cancer_type` | enum\|null | `lung`/`breast`/`colorectal`/`gastric`/`thyroid`；并发症与待核条目为 null |
| `source` / `origin` | string / enum | 来源说明 / 固定 `cblue` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft`；映射成功的 disease 额外带 `icd_o3_source`（NHC 原 5 位码）与 `icd_o3_basis`（匹配依据），未映射的带 `icd_o3_note`（原因） |

## 数据量与构成

| category | 条数 | confirmed | pending | 说明 |
|---|---|---|---|---|
| disease | 240 | 200 | 40 | confirmed 全部带 ICD-10 编码：原发 147、癌前 24、转移 21、并发症 8；189/240 已补 `icd_o3` |
| symptom | 66 | 0 | 66 | 来自 CMeIE「临床表现」尾实体 |
| examination | 51 | 0 | 51 | 来自 CMeIE 各类检查谓词尾实体 |
| drug | 15 | 14 | 1 | 来自 CMeIE「药物治疗」尾实体；14 条已补 `atc` + `en_name`，`雷洛昔芬` 因索引缺项保持 pending。**已剔除 6 条药物类别名/短语**（双膦酸盐、双磷酸盐、糖皮质激素、维生素D、钙片、"联合或不联合长期选择性雌激素受体调节剂"，见 13 号脚本 `DRUG_CLASS_DROP`） |
| staging | 4 | 0 | 4 | 仅 T分期 / N分期 / 早期 / 晚期 |
| gene | 1 | 0 | 1 | BRAF（原被标为「检查」，已改归 gene） |
| **合计** | **377** | **214** | **163** | |

疾病条目癌种分布：结直肠 56 / 肺 36 / 乳腺 34 / 胃 32 / 甲状腺 28 / 未定 14（并发症与转移类）。

## 待人工复核（重要）

1. **数量远低于 A5 目标**：需求 2,000~5,000 条，本批 377 条。缺口集中在 symptom（需 300~600）、examination（200~400）、drug（150~300）、gene（100~200）；staging 目前只有 4 个粗粒度词，未对齐 AJCC 8th 的 Ⅰ~Ⅳ 期与 T/N/M 组合。
2. **`pending` 163 条无编码**：需按需求清单 A5⑤ 的「后续确认计划」补 ICD-10 / ATC，未确认前不得作为 `confirmed` 使用。
3. **`icd_o3` 为规则自动映射，须医学复核**：189 条中 143 条为部位性诊断兜底（`恶性肿瘤`→`M8010/3`、`原位`→`M8010/2`、`继发/转移`→`M8010/6`、`良性肿瘤`→`M8000/0`），35 条形态学关键词规则、11 条名称精确命中。部位性诊断的真实形态学亚型需由 A2 疾病档案的「病理分型」逐条给出，**`M8010/3` 只代表「癌 NOS」，不应据此推断组织学类型**。剩余 51 条经确认不适用（甲状腺肿 17、息肉 14、囊肿 7、积液 3、增生/结节/骨折/恶病质等 10），已在 `annotation.icd_o3_note` 逐条记录原因。
4. **ICD-O-3 格式口径**：NHC 原码为 5 位（`M81400/3`，第 5 位是本地亚型细分序号，如 `M80411/3` 小细胞神经内分泌癌 vs `M80410/3` 小细胞癌）。需求清单 §A3⑦ 硬性要求 `Mxxxx/x` 4 位，且把「缺 M 前缀或行为码」列入错误清单，故本目录统一输出 4 位标准码，原 5 位码保留在 `annotation.icd_o3_source`；若后续校验允许 5 位，可从该字段无损还原。
5. **待核疾病名质量**：40 条 pending 疾病由关系尾自动生成，含 `嗜铬细胞瘤`、`平滑肌肉瘤`、`神经纤维瘤` 等超出 5 癌种范围的肿瘤，以及 `乳头状癌`、`未分化癌`、`腺癌` 这类无部位限定名，须人工判入或剔除。
6. **检查/症状粒度过粗**：如 `超声`、`乳腺X线`、`活检`、`出血`、`肿块`，需补部位限定（对齐需求清单示例「胸部低剂量CT」）。
7. **同义词不完整**：仅补入 6 个通用简称（肺癌/乳腺癌/胃癌/结肠癌/直肠癌/甲状腺癌）与 CMeIE「同义词」关系；口语别名（肺CA、NSCLC 等）尚未编集。
8. **上下位关系须另置 A6**：NSCLC、SCLC 等已作为独立 disease 条目（pending），**未**写入 `synonyms`，符合需求清单的判别法则。
9. **License**：CBLUE 官方仓库为 Apache-2.0；数据经天池发布，商用交付前建议再与主办方确认原始数据授权。

## 复现

```bash
python tools/13_cblue_terminology.py   # raw/cblue/ → 本目录 terminology_cancer.json（icd_o3/atc 先置 null）
python tools/14_cblue_kg.py            # → data/clean/kg_triples/kg_cmeie_cancer.json
python tools/15_fetch_atc.py           # WHO ATC/DDD Index → fetched/atc/atc_oncology.csv
python tools/16_atc_mapping.py         # → 回补 drug 的 atc / en_name
python tools/17_fetch_icdo3.py         # 下载 + 校验 NHC 资料包 → fetched/codetables/nhc/（M 码表）
python tools/18_icdo3_mapping.py       # M 码表 → 回补 disease 的 icd_o3（必须在 13、17 之后运行）
```
