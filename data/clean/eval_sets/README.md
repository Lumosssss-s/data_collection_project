# eval_sets 评测集目录

本目录存放**评测用**成品数据（对齐需求清单 C2 问答评测集 / C3 公开对标集），按功能类型集中，不按数据集分目录。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `eval_qa_cancer.json` | 1,349 | 5 癌种中文问答（患者提问 + 标准回答），字段对齐 `task_type=qa` | cMedQA2 v2.0（GitHub zhangsheng93/cMedQA2，中文社区医疗问答，仅限非商业研究） |

## 字段结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `qid` | string | `EVAL-QA-CMEDQA-<4位序号>` |
| `task_type` | enum | 固定 `qa` |
| `input` | string | 患者问题原文 |
| `gold` | object | `{"answer": "标准回答文本"}` |
| `gold_labeled` | bool | `true`=回答来自候选正答标签；`false`=取首个可用回答，需人工复核 |
| `cancer_type` | enum | `lung` / `breast` / `colorectal` / `gastric` / `thyroid` |
| `source` | string | 数据来源说明（数据集名 + 获取渠道 + 授权） |
| `origin` | enum | 来源短码，本批 `cMedQA2` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

## 数据量

| 指标 | 数量 |
|---|---|
| 总记录 | 1,349 |
| 肺癌 / 乳腺癌 / 结直肠癌 / 胃癌 / 甲状腺癌 | 866 / 158 / 139 / 98 / 88 |
| `gold_labeled=true`（可直接用） | 1,193 |
| `gold_labeled=false`（需重点复核） | 156 |

## 录入注意事项

1. **`gold_labeled=false` 的 156 条不可直接当标准答案**：其 `gold.answer` 只是「首个可用回答」，非正答标签。建议优先采用 `gold_labeled=true` 的 1,193 条。
2. **`annotation.status=draft`**：未经医学审核，录入前需医学顾问逐条 review 后改 `approved`。
3. **`origin` 枚举待扩展**：需求清单 C3 目前只列 `CMB`/`CMExam`，本批为 `cMedQA2`，入库前需确认扩展口径。
4. **未做 C2 的附加标注**：未标「应拒答」型（约 10%）、未标 `difficulty`、未拆 `key_points`/`refs`，需人工补。
5. **口语原文未规范化**：问题与回答保留社区原文（含错别字、口语），未做术语归一。
6. **License 为仅限非商业研究**：竞赛/商用交付前须确认授权。
7. **9 条多癌种命中**：`cancer_type` 只保留首个命中值，完整命中见 `cache/cmedqa2/questions_cancer.csv`。

## 复现

```bash
python tools/1_extract_cancer.py   # raw/cmedqa2/ → cache/cmedqa2/
python tools/2_convert_to_json.py  # cache/cmedqa2/ → 本目录
```
