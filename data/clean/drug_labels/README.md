# drug_labels 药品目录

本目录存放**药品信息**成品数据（对齐需求清单 A4 药品说明书）。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `drug_catalog_v2.json` | 48 种药 / 2,235 条制剂 | **当前版本**：字段名对齐需求清单 §A4 ⑥ + 药品基础信息 + 美国上市制剂清单 + ATC 编码 + 中文适应证/用法用量 + openFDA 说明书四段英文 interim | FDA NDC Directory（公有领域）+ WHO ATC/DDD Index（16 号映射）+ 《新型抗肿瘤药物临床应用指导原则（2025年版）》（20 号抽取）+ openFDA drug/label（公有领域） |
| `drug_catalog_v1_20261025.json` | 48 种药 / 2,235 条制剂 | v1（旧字段名 `canonical_zh` / `atc`，按 G4 保留以便比对，下游已不再读取）；该快照保留原始错字「昂达司琼」，未回改 | 同上 |

## 字段名对齐（v1 → v2，2026-10-28）

由 `tools/25_align_drug_catalog.py` 纯改名迁移，**未新增任何采集内容**：

| v1 | v2（需求清单 §A4 ⑥） | 说明 |
|---|---|---|
| `canonical_zh` | `generic_name` | 中文通用名 canonical；`generic_name_en` 作为附加字段保留 |
| `atc` | `atc_code` | ATC 5 级码；`atc_parent` 保留 |
| — | `brand_names` | 由 `products[].proprietary_name` 去重生成（英文商品名，中文商品名待补），48/48 有值 |
| — | `approval_no` | 国药准字，当前 0/48（NMPA 无公开接口，待授权渠道） |
| — | `indications` | 原字段已存在，统一为数组（17/48） |
| — | `dosage` | 原字段已存在，统一为 `{"standard","adjustment"}` 对象（17/48） |
| — | `contraindications` | 禁忌，当前 0/48 |
| — | `adverse_reactions` | 不良反应（`[{term,frequency,ctcae_hint}]`），当前 0/48 |
| — | `interactions` | 原字段已存在（11/48） |

空值一律写 `null`（G8），缺口同步登记在 `missing_fields`。

## 定位说明（重要）

1. **基础字段已齐**：通用名/剂型/途径/规格/厂牌/申请号/药理分类取自 FDA NDC；`atc_code` + `atc_parent` 48/48 由 16 号脚本映射。
2. **NMPA 查询页只有注册信息**：`www.nmpa.gov.cn` / `datasearch.nmpa.gov.cn` 对脚本与自动化浏览器均返回 HTTP 412（WAF），人工查询页（样例见 `raw/nmpa_registry/`）只提供批准文号/产品名称/商品名/剂型/规格/持有人/生产厂商/药品本位码，**不含说明书正文**。
3. **中文适应证/用法用量改由官方指导原则抽取**：20 号脚本从《新型抗肿瘤药物临床应用指导原则（2025年版）》PDF 抽取，覆盖 **17/48**（呼吸/消化/乳腺三个章节，适应证按癌种关键词过滤，剔除「※」境外获批、国内未获批条目），写入 `indications` / `dosage` / `interactions`，来源记入 `label_zh_source`。
4. **未覆盖的 31 种**：化疗药（铂类、蒽环、紫杉类、吉西他滨、伊立替康、培美曲塞、卡培他滨、氟尿嘧啶）、内分泌药（他莫昔芬、来曲唑、阿那曲唑、依西美坦、氟维司群）、支持治疗（G-CSF、止吐、骨转移、地塞米松、左甲状腺素）不在该指导原则内；甲状腺癌无独立章节（仑伐替尼、索拉非尼、凡德他尼未覆盖）。
5. **禁忌与不良反应仍未完成**：暂用 openFDA 英文 interim（45/48，`label_en_interim`），并与人工补充的说明书要点合并；不得直接当作中文说明书交付。
6. `missing_fields` 由 19 号脚本按实际缺口动态生成：17 条剩 4 项（禁忌/不良反应/批准文号/中文说明书）、29 条剩 6 项、2 条无 ATC 的剩 7 项。

## 字段结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `drug_id` | string | `DRUG-<癌种码>-<3位序号>`（LUNG/BREAST/CRC/GAS/THY/SUP） |
| `generic_name` | string | 中文通用名（canonical，需求清单 A4 字段） |
| `generic_name_en` | string | 英文通用名（附加字段，按 A4 药单人工映射） |
| `drug_class` | enum | 化疗 / 靶向 / 免疫 / 抗血管生成 / 内分泌 / 内分泌抑制 / 支持治疗 |
| `cancer_type` | array | `lung`/`breast`/`colorectal`/`gastric`/`thyroid`/`general`，可多值 |
| `pharm_classes` | array | FDA 药理分类原文（EPC/MoA 标签） |
| `routes` / `dosage_forms` | array | 给药途径 / 剂型去重集合 |
| `product_count` / `labeler_count` | int | 在美制剂数 / 生产企业数 |
| `application_numbers` | array | FDA 申请号（NDA/ANDA/BLA） |
| `products` | array | 制剂明细（NDC、商品名、规格、厂牌、上市状态等） |
| `brand_names` | array\|null | 商品名（取自 `products[].proprietary_name`，48/48 有值） |
| `atc_code` / `atc_parent` | string\|null | ATC 5 级码 / 顶级组（WHO ATC/DDD Index，16 号脚本；48 条中 46 条有值） |
| `approval_no` | string\|null | 国药准字编号，当前全 null（NMPA 无公开接口） |
| `indications` | array\|null | 中文适应证（20 号从指导原则抽取，仅 5 癌种子集），17/48 有值 |
| `dosage` | object\|null | `{"standard":"…","adjustment":"…"}`，标准用法用量与调整（20 号），17/48 有值 |
| `contraindications` | array\|null | 禁忌，当前全 null |
| `adverse_reactions` | array\|null | `[{"term","frequency","ctcae_hint"}]`，当前全 null |
| `interactions` | array\|null | 药物相互作用要点（20 号，可选） |
| `label_zh_source` | object\|null | 中文正文来源（G6 五字段）：`source_name` / `source_version` / `source_section` / `source_file` / `updated_at`；与英文 interim 区分 |
| `label_en_interim` | object\|null | openFDA 英文 interim，**非 A4 正式字段**：`{lang:"en", status:"interim_pending_zh", source, set_id, effective_time, generic_name, brand_name, sections{indications, dosage_and_administration, contraindications, adverse_reactions}}`；45/48 有值 |
| `label` | object\|null | 中文说明书（A4 正式字段），当前全为 null；由 `raw/nmpa_labels/labels_zh.json` 经 19 号脚本合并后写入：`{lang:"zh", status:"zh_from_nmpa", source_name, source_url, updated_at}` |
| `missing_fields` | array | 当前仍缺的 A4 必填项，19 号脚本按实际缺口动态生成（`atc_code` 仅在无值时出现） |
| `source` / `origin` | string / enum | 来源说明 / 固定 `fda_ndc` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

## 数据量

| 指标 | 数量 |
|---|---|
| A4 药单品种 | 51 种 |
| **命中（FDA NDC）** | **48 种** |
| 未命中 | 3 种：埃克替尼、信迪利单抗、安罗替尼（中国本土药，未在美国上市） |
| 制剂记录 | 2,235 条（在售 2,200 / 已停售 35） |
| ATC 覆盖 | **48 / 48**（阿瑞匹坦 A04AD12、昂丹司琼 A04AA01；2026-10-30 由 15 号脚本扩展 A04 组 + 16 号回补） |
| 中文适应证 + 用法用量 | 17 / 48（指导原则抽取） |
| openFDA 英文 interim | 45 / 48 |
| 未命中 openFDA | 3 种：阿替利珠单抗（TECENTRIQ）、仑伐替尼（LENVIMA）、奥希替尼（TAGRISSO） |
| 中文正式 `label` | 0 / 48（待人工按说明书要点覆盖） |

按癌种（可重叠）：肺 18、乳腺 15、结直肠 9、胃 8、甲状腺 4、支持治疗 7。

## 录入注意事项

1. **中文适应证/用法用量为自动抽取的草稿**：20 号脚本按「指导原则章节 + 癌种关键词」过滤，跨癌种药品（如帕博利珠单抗、曲妥珠单抗）会合并多个章节条目，须医学顾问逐条核对是否落在 5 癌种范围内。
2. **禁忌与不良反应仍需人工**：NMPA 查询页不含这两段；当前英文 interim 只作翻译/比对参考，正式交付前必须按说明书补齐（含发生频率与 CTCAE 提示）。
3. **NMPA 只能补注册字段**：`approval_no`、商品名、剂型、规格、持有人按 `raw/nmpa_registry/` 样例版式人工查询后录入；同一药品多规格可能有多个批准文号。
4. **美国市场口径**：商品名（如 TAGRISSO）、规格单位、生产企业与国内可能不同，不能直接展示给国内患者。
5. **3 个中国原研药缺口**：埃克替尼、信迪利单抗、安罗替尼既无 FDA NDC 也无 openFDA 标签，需从 NMPA 单独补。
6. **3 个 openFDA 缺项**：阿替利珠单抗、仑伐替尼、奥希替尼在 openFDA label 数据集中查无记录；其中阿替利珠单抗的中文适应证/用法已由指导原则补上。
7. **ATC 缺口已闭环（2026-10-30）**：阿瑞匹坦（A04AD12）、昂丹司琼（A04AA01）属 A04 止吐类，15 号脚本已扩展 A04 + G03 组（750 条码表）并重跑 16 号，`atc_code` 现为 48/48。
8. **药理分类不全**：原表 36.2% 记录为空；本批「环磷酰胺」「曲妥珠单抗-emtansine」为空，需人工补。
9. **支持治疗类**（G-CSF、止吐、骨转移、激素）标为 `general`，无特定癌种归属。
10. **`annotation.status=draft`**：全自动映射/抽取，需医学顾问复核。
11. **建议定期重拉**：FDA 目录、openFDA 标签与指导原则版本持续更新。

## 中文覆盖流程（人工补禁忌/不良反应/批准文号）

1. 生成模板：

   ```bash
   python tools/19_fetch_openfda_labels.py --template   # → raw/nmpa_labels/labels_zh.template.json
   ```

2. 人工按模板填写后另存为 `raw/nmpa_labels/labels_zh.json`，每药字段：
   `approval_no`（国药准字…，来源为 NMPA 注册查询页）、`indications`（数组）、`dosage`（`{standard, adjustment}`）、`contraindications`（数组）、`adverse_reactions`（`[{term, frequency, ctcae_hint}]`）、`interactions`（可选）、`source_name`（说明书名称，必填）、`source_url`（出处链接）、`approved_date`（说明书日期）；可选 `brand_names`。
   已由 20 号脚本填好的 `indications` / `dosage` 可留空，脚本只覆盖非空项。
3. 重跑 19 号脚本做格式校验并合并：`missing_fields` 自动收缩，审计写入 `cache/drug_labels/zh_override_audit.json`；格式不合规的条目会被拒绝并逐条报告原因。

## 复现

```bash
# 过滤步骤（原 tools/7_clean_fda_ndc.py 已移除），产物已固化在 cache/fda_ndc/oncology_products.csv
python tools/8_fda_to_json.py              # cache/fda_ndc/ → 本目录 drug_catalog_v2.json（atc_code 先置 null）
python tools/15_fetch_atc.py               # WHO ATC/DDD Index → fetched/atc/atc_oncology.csv（750 条，十组）
python tools/16_atc_mapping.py             # 中文药名 ↔ INN ↔ ATC → 回补 atc_code / atc_parent
python tools/19_fetch_openfda_labels.py    # openFDA 四段英文 → label_en_interim
python tools/20_guideline_drug_extract.py  # 指导原则 PDF → 中文 indications / dosage / interactions（依赖 PyMuPDF）
python tools/25_align_drug_catalog.py      # 字段名对齐 §A4 ⑥（canonical_zh→generic_name、atc→atc_code，补 brand_names 等）
python tools/19_fetch_openfda_labels.py --offline   # 刷新 missing_fields（20 号之后必须再跑一次）
```

- 25 号脚本纯改名迁移，审计写入 `cache/drug_labels/align_v2_audit.json`；v1 原件保留为 `drug_catalog_v1_20261025.json` 供比对（G4）。

- 19 号脚本幂等：已抓且文件存在时不联网（`--force` 强制重抓，`--offline` 只用已抓结果合并）。
- 20 号脚本审计：`cache/drug_labels/guideline_extract.json`（逐药命中章节、页码、抽取条数、跳过原因）；支持 `--dry-run` 只出审计不回写。
- 抓取结果存 `fetched/openfda_labels/labels.json`，匹配审计存 `cache/drug_labels/openfda_match.json`。
