# corpus 文献语料目录

本目录存放**文献语料类**成品数据（需求清单 G3 无此类，为新增类别，定位为 RAG 检索语料 / 证据来源补充，入库前需申报确认）。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `cancer_literature_corpus.json` | 33,802 | PubMed 癌症文献摘要（PMID / 标题 / 摘要） | PubMed-Cancer-NLP-Textual-Dataset（HuggingFace cyberpsych，apache-2.0，PubMed 摘要） |

## 字段结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `doc_id` | string | `DOC-<癌种码>-PUB-<4位序号>`（LUNG/BREAST/CRC/GAS；PUB=PubMed 来源码） |
| `pmid` | string | PubMed 原始 ID，溯源用 |
| `title` / `abstract` | string | 清洗后的标题 / 摘要 |
| `cancer_type` | enum | `lung` / `breast` / `colorectal` / `gastric` |
| `lang` | enum | 固定 `en` |
| `source` | string | 数据来源说明（数据集名 + 渠道 + 授权） |
| `origin` | enum | 固定 `pubmed_cancer` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

## 数据量

| 癌种 | 原始 | 去重 | 过短剔除 | 保留 |
|---|---|---|---|---|
| lung | 9,999 | 0 | 991 | 9,008 |
| breast | 9,993 | 920 | 1,002 | 8,071 |
| colorectal | 9,998 | 351 | 994 | 8,653 |
| gastric | 9,997 | 663 | 1,264 | 8,070 |
| **合计** | 39,987 | 1,934 | 4,251 | **33,802** |

## 录入注意事项

1. **缺甲状腺癌**：原数据集无 thyroid 文件，5 癌种缺一，需另找来源补齐。
2. **存放位置待申报**：G3 无「文献语料」类，本目录为新增类别。
3. **标签噪声**：原数据集按关键词抓取，文件内混有其它癌种/非癌文献（如 lung 文件中的骨髓瘤个案）。
4. **英文内容**：仅可作证据溯源/图谱补充/评测参考，面向患者展示前需翻译 + 医学审核。
5. **`annotation.status=draft`**；**时效性约 2024 年抓取**，作证据时需与最新指南核对。

## 复现

```bash
python tools/3_clean_pubmed_cancer.py  # raw/pubmed_cancer/ → cache/pubmed_cancer/
python tools/4_pubmed_to_json.py       # cache/pubmed_cancer/ → 本目录
```
