# kg_triples 知识图谱三元组目录

本目录存放**知识图谱关系**成品数据（对齐需求清单 A6），按功能类型集中。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `kg_cancer_subgraph.json` | 639 | 5 癌种子图关系（疾病-症状-药物-文本属性） | gStore 医药知识图谱 kgdrug.com（2018 建库，原始 N-Triples 已缺失，由索引文件解码） |
| `kg_cmeie_cancer.json` | 187 | 5 癌种疾病 → 症状/检查/药物/亚型关系（A6 词表内） | CBLUE CMeIE-V2 关系抽取语料（train+dev 14,339 条文本），已按 A5 术语集筛子图 |

## 字段结构

**`kg_cancer_subgraph.json`（kgdrug 原库结构）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `relation_id` | string | `KG-<癌种码>-<5位序号>`（LUNG/BREAST/CRC/GAS/THY/GEN） |
| `head` | object | `{id, type, name}`，type ∈ disease/symptom/drug |
| `relation` | enum | `has_symptom` / `related_disease` / `needs_drug` / `treated_by` / `cause` / `overview` / `treatment` / `prevention` / `complication` / `disease_name` / `symptom_*` / `drug_*` |
| `raw_predicate` | string | 原图谱谓词（拼音），保留溯源 |
| `tail` | object | 实体关系为 `{id,type,name}`；文本属性为 `{text}` |
| `cancer_type` | enum | `lung`/`breast`/`colorectal`/`gastric`/`thyroid`/`general` |
| `source` | string | 数据来源说明 |
| `origin` | enum | 固定 `kgdrug` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

**`kg_cmeie_cancer.json`（对齐需求清单 §A6⑥）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `triple_id` | string | `KG-CBLUE-<5位序号>` |
| `head` / `tail` | string | A5 `term.canonical`（head 必为 disease） |
| `head_type` / `tail_type` | enum | A5 `term.category` 六类之一 |
| `relation` | enum | 仅 A6 九种词表：`has_symptom` / `examined_by` / `treated_by` / `complication_of` / `subtype_of` / `expressed_by` / `targeted_by` / `recommended_for` / `followed_by` |
| `cancer_type` | enum | 继承自 head 疾病条目 |
| `evidence` | string | CMeIE 原文句（≤200 字） |
| `confidence` | enum | `medium`（原句≥20 字）/ `low` |
| `raw_predicate` | string | CMeIE 原谓词（临床表现 / 病理分型 / 药物治疗 …） |
| `source` / `origin` | string / enum | 来源说明 / 固定 `cblue` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

> 两个文件字段体系不同，勿混用：`kg_cancer_subgraph.json` 沿用 kgdrug 原库结构（实体对象 + 拼音谓词），`kg_cmeie_cancer.json` 严格对齐需求清单字段表（字符串 head/tail + 关系词表）。

## 数据量

| 癌种 | 疾病实体 | 关系数 |
|---|---|---|
| 乳腺癌 | 9 | 207 |
| 结直肠癌 | 5 | 141 |
| 肺癌 | 3 | 113 |
| 胃癌 | 3 | 107 |
| 甲状腺癌 | 1 | 71 |
| **合计** | **21** | **639** |

关联实体：症状 56、药物 46。

**`kg_cmeie_cancer.json` 关系分布（187 条）**

| relation | 条数 |
|---|---|
| `has_symptom` | 77 |
| `examined_by` | 55 |
| `subtype_of` | 40 |
| `treated_by` | 15 |

癌种分布：甲状腺 56 / 乳腺 45 / 胃 33 / 肺 11 / 结直肠 2 / 未定 40。

## 录入注意事项

1. **规模不足 A6 目标**：需求 3,000~8,000 条，本目录合计 826 条（kgdrug 639 + CMeIE 187），缺口需 CMeKG / 指南抽取补齐。
2. **疾病 ID 为原库内部编号**：不可当作 ICD 编码，入库前需映射 A5 术语字典。
3. **药物关系偏粗**：`needs_drug` 仅表示关联，不区分线数/适应症强度（如甲状腺癌关联「甲泼尼龙片」属噪声），用药口径仍以 A4 说明书为准。
4. **文本属性为科普原文**：`cause`/`treatment` 等含口语与旧表述，需 A1 指南交叉校验。
5. **`annotation.status=draft`**；**无 License**（来源授权不明，商用前须溯源）。
6. **时效性 2018 年**：靶向/免疫口径已明显过时。
7. **甲状腺覆盖极弱**：仅 1 个实体、71 条关系。
8. **CMeIE 子图无 `complication_of`**：并发症类尾实体未进 A5 疾病集，58 条候选因端点缺失被丢弃；补齐并发症术语后可回捞。
9. **CMeIE 子图 `confidence` 全为 medium/low**：未做医学审核，`evidence` 为原句截断，需按 A6 验收人工抽检方向与语义（≥90%）。
10. **CMeIE 子图混入少量状态型 `subtype_of`**：已按「转移性/继发性/复发性」关键词过滤 3 条，仍需人工复核其余亚型判断。

## 复现

```bash
python tools/5_decode_kgdrug.py     # raw/kgdrug/ → cache/kgdrug/triples.jsonl（528,039 条）
python tools/6_filter_cancer_kg.py  # cache/kgdrug/ → 本目录
python tools/13_cblue_terminology.py # raw/cblue/ → A5 术语字典 + cache/cblue/kg_candidates.json
python tools/14_cblue_kg.py          # cache/cblue/kg_candidates.json → 本目录 kg_cmeie_cancer.json
```
