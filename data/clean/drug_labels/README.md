# drug_labels 药品目录

本目录存放**药品信息**成品数据（对齐需求清单 A4 药品说明书）。

## 文件

| 文件 | 记录数 | 内容 | 来源（记录内 `source` 字段） |
|---|---|---|---|
| `drug_catalog_v2.json` | 51 种药（48 条 FDA 记录 + 3 条国产原研新增：信迪利单抗、埃克替尼、安罗替尼） | **当前版本**：字段名对齐需求清单 §A4 ⑥ + 药品基础信息 + 美国上市制剂清单 + ATC 编码 + 中文适应证/用法用量（指导原则 20 条 / 官网说明书 8 条，其中 OCR 2 条）+ 中文禁忌 39 / 不良反应 33 + 15 条的 `cn_registration` 与 `label` 元数据 | FDA NDC Directory（公有领域）+ WHO ATC/DDD Index（16 号映射）+ 《新型抗肿瘤药物临床应用指导原则（2025年版）》（20 号抽取）+ openFDA drug/label（公有领域，19 号派生）+ **上市许可持有人/生产企业官网中文说明书（30 号采集文本层、32 号采集扫描件/图片，31 号合并）** |
| `drug_catalog_v1_20261025.json` | 48 种药 / 2,235 条制剂 | v1（旧字段名 `canonical_zh` / `atc`，按 G4 保留以便比对，下游已不再读取）；该快照保留原始错字「昂达司琼」，未回改 | 同上 |

## 字段名对齐（v1 → v2，2026-10-28）

由 `tools/25_align_drug_catalog.py` 纯改名迁移，**未新增任何采集内容**：

| v1 | v2（需求清单 §A4 ⑥） | 说明 |
|---|---|---|
| `canonical_zh` | `generic_name` | 中文通用名 canonical；`generic_name_en` 作为附加字段保留 |
| `atc` | `atc_code` | ATC 5 级码；`atc_parent` 保留 |
| — | `brand_names` | 由 `products[].proprietary_name` 去重生成（英文商品名，中文商品名待补），48/51 有值 |
| — | `approval_no` | 国药准字，15/51（摘自已采集的中文说明书；其余待授权渠道/人工补录） |
| — | `indications` | 原字段已存在，统一为数组（28/51） |
| — | `dosage` | 原字段已存在，统一为 `{"standard","adjustment"}` 对象（28/51） |
| — | `contraindications` | 禁忌，39/51（中文说明书原文 15 + openFDA 英文 interim 24，附 `contraindications_source`） |
| — | `adverse_reactions` | 不良反应（`[{term,frequency,ctcae_hint}]`），33/51（中文说明书原文 15 条 + openFDA 英文 interim 18 条，各带 `*_source`） |
| — | `interactions` | 原字段已存在（14/51） |
| — | `label` | 中文说明书元数据（`lang/status/source_*/fetched_at/text_path/text_sha256/char_count/sections`），15/51；全文不入目录，按 `text_path` 读取 |
| — | `cn_registration` | 注册类字段（`approval_no/brand_name/specification/dosage_form/mah/manufacturer` + 来源），15/51；**仅取自说明书原文**，不混用注册库 |

空值一律写 `null`（G8），缺口同步登记在 `missing_fields`。

## 定位说明（重要）

1. **基础字段已齐**：通用名/剂型/途径/规格/厂牌/申请号/药理分类取自 FDA NDC；`atc_code` + `atc_parent` 48/51 由 16 号脚本映射（埃克替尼、安罗替尼、信迪利单抗无映射，保持 null）。
2. **NMPA 查询页只有注册信息**：`www.nmpa.gov.cn` / `datasearch.nmpa.gov.cn` 对脚本与自动化浏览器均返回 HTTP 412（WAF），人工查询页（样例见 `raw/nmpa_registry/`）只提供批准文号/产品名称/商品名/剂型/规格/持有人/生产厂商/药品本位码，**不含说明书正文**。
3. **中文适应证/用法用量三来源**：20 号脚本从《新型抗肿瘤药物临床应用指导原则（2025年版）》PDF 抽取（呼吸/消化/乳腺/甲状腺/头颈/骨与软组织 6 章），30 号脚本从企业官网说明书采文本层原文，32 号脚本对扫描件/图片说明书做 OCR；三者互补，先到先得，20 号已填的中文不被覆盖。
4. **企业官网说明书采集（2026-11-04 / OCR 补录 2026-11-05）**：`tools/30_fetch_cn_labels.py` 采得 13 个唯一药品的文本层说明书原文（罗氏 6、礼来 1、辉瑞 2、豪森 3 + 交叉核对 1、信达 1）；`tools/32_ocr_cn_labels.py` 用 rapidocr-onnxruntime（PP-OCRv4，CPU）对 3 个图片型来源做 OCR 补录，其中 2 份质量达标（阿瑞匹坦、埃克替尼）、1 份不可用（安罗替尼，扫描件分辨率约 100–130 dpi）。全部走公开页面、无登录/验证码/付费墙，先读 robots.txt；每份都记录 `source_url`、`fetched_at`、`usage_note`，OCR 另记 `ocr_engine`/`engine_version`/`model`/`dpi`/`page_map`。原文存 `fetched/labels_cn/downloads/`，抽取文本存 `fetched/labels_cn/text/`。
5. **未覆盖的 23 种适应证/用法用量**：经典化疗药（铂类、蒽环、紫杉类、吉西他滨以外的大多）、内分泌药与支持治疗药，指导原则无独立章节（仅作联合方案提及），企业官网未挂全文或仅扫描件/图片（安罗替尼扫描件 OCR 质量不达标，字段保持 null）。不用相近药或翻译填充。
6. **禁忌与不良反应**：中文说明书覆盖 15 种（企业官网原文 13 + OCR 2，`lang=zh`），其余仍为 openFDA 英文 interim（`lang=en`、`status=interim_pending_zh`）。15 种中有 7 种禁忌、10 种不良反应原本是英文 interim，31 号合并时整块替换为中文原文，被替换的英文层摘要保留在 `*_source.replaced_interim`。
7. **注册类字段只来自说明书**：`approval_no` / `brand_name` / `specification` / `mah` 等取自说明书原文的 `【药品名称】【规格】【上市许可持有人】` 段，不使用注册库字段；说明书中未出现的项为 null（如氟维司群商品名未在正文列出，保持 null）。OCR 来源的注册字段非人工校对，`cn_registration.source_type=official_label_ocr`。
8. `missing_fields` 由 19 号脚本按实际缺口动态生成。

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
| `brand_names` | array\|null | 商品名（FDA `products[].proprietary_name` 去重 + 中文说明书【药品名称】补充），48/51 有值 |
| `atc_code` / `atc_parent` | string\|null | ATC 5 级码 / 顶级组（WHO ATC/DDD Index，16 号脚本；48/51 有值，信迪利单抗、埃克替尼、安罗替尼无 ATC 保持 null） |
| `approval_no` | string\|null | 国药准字编号，15/51（均摘自已采集的中文说明书【药品批准文号】；其余 null） |
| `indications` | array\|null | 中文适应证（20 号指导原则抽取 + 中文说明书补充），28/51 有值（指导原则 20、说明书文本层 6、OCR 2） |
| `dosage` | object\|null | `{"standard":"…","adjustment":"…"}`，标准用法用量与调整（20 号 + 说明书文本层 / OCR），28/51 有值 |
| `contraindications` | array\|null | 禁忌，39/51 有值：中文说明书原文 15（`lang=zh`，含 OCR 2）+ openFDA 英文 interim 24（`lang=en`），按 `contraindications_source.lang` 区分 |
| `contraindications_source` | object\|null | `{lang,status,source,set_id,effective_time,fetched_at,note}`；`lang=zh` 为中文说明书原文，`lang=en` 为英文 interim；OCR 来源另有 `source_type=official_label_ocr`、`proofread=false` |
| `adverse_reactions` | array\|null | `[{"term","frequency","ctcae_hint","lang","status"}]`，33/51 有值（中文 15 + 英文 18）；`frequency` 仅取标签明示值（如 `≥20%`、`2.5%`），无明示频率的不推测 |
| `adverse_reactions_source` | object\|null | 同上，字段级来源与取数时间；`lang` 区分中/英文层 |
| `interactions` | array\|null | 药物相互作用要点（20 号，可选） |
| `label_zh_source` | object\|null | 中文正文来源（G6 五字段）：`source_name` / `source_version` / `source_section` / `source_file` / `updated_at`；与英文 interim 区分 |
| `label_en_interim` | object\|null | openFDA 英文 interim，**非 A4 正式字段**：`{lang:"en", status:"interim_pending_zh", source, set_id, effective_time, fetched_at, source_url, generic_name, brand_name, sections{indications, dosage_and_administration, contraindications, adverse_reactions}}`；45/51 有值 |
| `label` | object\|null | 中文说明书元数据（A4 正式字段），15/51：`{lang:"zh", status, source_type, source_name, source_holder, source_url, fetched_at, usage_note, content_type, pages, char_count, raw_path, text_path, text_sha256, sections, text_stored_in_catalog:false, note}`；OCR 来源（`source_type=official_label_ocr`）`status=zh_from_official_label_ocr`、`proofread=false`，并附 `ocr{engine,engine_version,model,dpi,reliable,core_sections_hit,core_sections_missing,page_map,header_normalizations}`；**全文不写入目录**，按 `text_path` 读取；`raw_path` 指向的原件不入 Git（版权归持有人） |
| `cn_registration` | object\|null | 中文注册块，15/51：`{brand_name, specification, mah, approval_no}`，全部摘自已采集的说明书原文；OCR 来源 `source_type=official_label_ocr` |
| `label_ocr_failed` | object\|null | OCR 质量不达标时建档留痕（当前仅安罗替尼）：`{ocr_unreliable:true, reason, source_*/fetched_at, raw_path, text_path, text_sha256, engine/model/dpi, core_sections_hit}`；中文字段保持 null |
| `missing_fields` | array | 当前仍缺的 A4 必填项，19 号脚本按实际缺口动态生成（`atc_code` 仅在无值时出现） |
| `source` / `origin` | string / enum | 来源说明 / 固定 `fda_ndc` |
| `annotation` | object | `{"annotator","date","status"}`，当前 `status=draft` |

## 数据量

| 指标 | 数量 |
|---|---|
| A4 药单品种 | 51 种 |
| **目录记录** | **51 条**（FDA NDC 命中 48 + 官网说明书建档 3：信迪利单抗、埃克替尼、安罗替尼） |
| 未命中 FDA NDC | 3 种：埃克替尼、信迪利单抗、安罗替尼（中国本土药，未在美国上市）；均已在目录中建档，安罗替尼因 OCR 质量不达标字段全空 |
| 制剂记录 | 2,235 条（在售 2,200 / 已停售 35） |
| ATC 覆盖 | **48 / 51**（信迪利单抗、埃克替尼、安罗替尼说明书中无 ATC，保持 null 并登记缺失） |
| 中文适应证 + 用法用量 | **28 / 51**（指导原则 20 + 官网说明书文本层 6 + OCR 2，互不覆盖） |
| 禁忌 | **39 / 51**（中文说明书原文 15（含 OCR 2）+ openFDA 英文 interim 24） |
| 不良反应 | **33 / 51**（中文说明书原文 15（含 OCR 2）+ openFDA 英文 interim 18） |
| 中文说明书全文 | **15 / 51**（`fetched/labels_cn/text/*.txt`，目录内 `label` 仅存元数据；含 OCR 2） |
| 国药准字 `approval_no` | **15 / 51**（均摘自已采集说明书原文） |
| 中文注册块 `cn_registration` | **15 / 51**（品牌/规格/持有人同样只来自说明书） |

按癌种（可重叠）：肺 20、乳腺 15、结直肠 10、胃 9、甲状腺 4、支持治疗 7；信迪利单抗按说明书适应证字面标注为肺/胃/结直肠，埃克替尼标注为肺，安罗替尼因无可用适应证文本暂为空。

## 录入注意事项

1. **中文适应证/用法用量为自动抽取的草稿**：20 号脚本按「指导原则章节 + 癌种关键词」过滤，跨癌种药品（如帕博利珠单抗、曲妥珠单抗）会合并多个章节条目，须医学顾问逐条核对是否落在 5 癌种范围内。
2. **15 种已换中文原文，其余仍是英文 interim**：`contraindications_source.lang` / `adverse_reactions_source.lang` 为 `zh` 的表示已由企业官网说明书覆盖（其中 2 种为 OCR 抽取、`proofread=false`），`en` 表示 openFDA 英文 interim，正式交付前须替换；人工补录时把 `lang` 置为 `zh` 后脚本不会再被英文覆盖。
3. **注册字段来源**：`approval_no`、中文商品名、规格、持有人优先取自说明书原文（`cn_registration`，15/51）；说明书中没有的，再按 `raw/nmpa_registry/` 版式人工查询 NMPA 补充；同一药品多规格可能有多个批准文号。
4. **美国市场口径**：商品名（如 TAGRISSO）、规格单位、生产企业与国内可能不同，不能直接展示给国内患者。
5. **3 个中国原研药**：信迪利单抗已由信达官网说明书建档（DRUG-EXTRA-003）；埃克替尼（贝达官网 4 张 JPG）经 OCR 建档（DRUG-EXTRA-002，字段可用但未校对）；安罗替尼（正大天晴扫描件）已建档（DRUG-EXTRA-001）但 OCR 质量不达标，中文字段全部留空、`label_ocr_failed` 记录失败原因，仍待人工录入或找到更高分辨率原件。
6. **3 个 openFDA 缺项**：阿替利珠单抗、仑伐替尼、奥希替尼在 openFDA label 数据集中查无记录；其中阿替利珠单抗的中文适应证/用法已由指导原则补上。
7. **ATC 覆盖 48/51（2026-10-30 补 A04/G03）**：阿瑞匹坦（A04AD12）、昂丹司琼（A04AA01）已补；信迪利单抗、埃克替尼、安罗替尼说明书中无 ATC，保持 null。
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
3. 重跑 19 号脚本做格式校验并合并：`missing_fields` 自动收缩，审计写入 `cache/drug_labels/zh_override_audit.json`；格式不合规的条目会被拒绝并逐条报告原因。合并中文禁忌/不良反应时脚本会把 `contraindications_source` / `adverse_reactions_source` 置为 `lang=zh`，后续重跑不会再被英文 interim 覆盖。

逐条缺口清单（48 药 × 缺哪些字段 × 需查什么）见 `raw/nmpa_registry/a4_pending_fill.csv`。

## 复现

```bash
# 过滤步骤（原 tools/7_clean_fda_ndc.py 已移除），产物已固化在 cache/fda_ndc/oncology_products.csv
python tools/8_fda_to_json.py              # cache/fda_ndc/ → 本目录 drug_catalog_v2.json（atc_code 先置 null）
python tools/15_fetch_atc.py               # WHO ATC/DDD Index → fetched/atc/atc_oncology.csv（750 条，十组）
python tools/16_atc_mapping.py             # 中文药名 ↔ INN ↔ ATC → 回补 atc_code / atc_parent
python tools/19_fetch_openfda_labels.py    # openFDA 四段英文 → label_en_interim；并派生禁忌/不良反应（英文 interim + 来源/取数时间）
python tools/20_guideline_drug_extract.py  # 指导原则 PDF → 中文 indications / dosage / interactions（依赖 PyMuPDF）
python tools/25_align_drug_catalog.py      # 字段名对齐 §A4 ⑥（canonical_zh→generic_name、atc→atc_code，补 brand_names 等）
python tools/30_fetch_cn_labels.py         # 企业官网中文说明书 → fetched/labels_cn/（PDF/HTML，robots 检查，sidecar 记 fetched_at）
python tools/32_ocr_cn_labels.py           # 扫描件/图片说明书 OCR（rapidocr-onnxruntime，纯 pip）→ labels_cn_ocr.json + text/ + failures_ocr.json
python tools/31_merge_cn_labels.py         # 只填空合并：中文原文字段（文本层 + OCR）+ cn_registration + label 元数据；英文 interim 整块替换
python tools/19_fetch_openfda_labels.py --offline   # 刷新 missing_fields（20/31 号之后必须再跑一次）
```

- 25 号脚本纯改名迁移，审计写入 `cache/drug_labels/align_v2_audit.json`；v1 原件保留为 `drug_catalog_v1_20261025.json` 供比对（G4）。
- 19 号脚本幂等：已抓且文件存在时不联网（`--force` 强制重抓，`--offline` 只用已抓结果合并）。
- 20 号脚本审计：`cache/drug_labels/guideline_extract.json`（逐药命中章节、页码、抽取条数、跳过原因）；支持 `--dry-run` 只出审计不回写。
- 30 号脚本产出 `fetched/labels_cn/labels_cn.json`（逐药章节与字段）、`failures.json`（不可用来源与原因）、`downloads/`（原件与 `*.meta.json`，**原件不入 Git**）、`text/`（抽取文本，入库）；31 号合并审计写 `cache/drug_labels/cn_label_merge.json`。
- 32 号脚本产出 `fetched/labels_cn/labels_cn_ocr.json`（与 30 号记录同构 + `ocr{engine,engine_version,model,dpi,reliable,core_sections_hit,page_map,header_normalizations}`）、`failures_ocr.json`（OCR 不可用原因）、`text/<key>.txt`（与 30 号同一目录结构）。质量门槛：适应症/用法用量/禁忌/不良反应命中 ≥2 才入库，否则整条字段留空并记 `ocr_unreliable`。
- 30/32/31/19 四段串联幂等：连续跑两遍，`drug_catalog_v2.json`、`labels_cn.json`、`labels_cn_ocr.json`、`failures.json`、`failures_ocr.json` 与 `text/` 的 sha256 均一致（已实测）。
- 抓取结果存 `fetched/openfda_labels/labels.json`，匹配审计存 `cache/drug_labels/openfda_match.json`。

## 企业官网说明书：采集范围与不可用来源（2026-11-04，OCR 补录 2026-11-05）

已采集文本层（13 个唯一药品，全部为公开页面、无登录/验证码/付费墙）：

| 来源 | 药品 | 使用限制 |
|---|---|---|
| 上海罗氏官网（assets.roche.com） | 阿来替尼、阿替利珠单抗、贝伐珠单抗、帕妥珠单抗、曲妥珠单抗、T-DM1 | 版权归持有人，仅限内部知识库使用，不得再分发或商用 |
| 礼来医学网 | 培美曲塞（力比泰） | 同上 |
| 辉瑞医学信息网 | 依西美坦（阿诺新）、克唑替尼（赛可瑞） | 同上 |
| 江苏豪森药业官网 | 氟维司群（普来和）、吉西他滨（泽菲）、顺铂（诺欣） | 国产同通用名说明书，非原研；仅限内部知识库使用 |
| 信达生物官网 | 信迪利单抗（达伯舒） | 同上 |

OCR 补录（32 号脚本，rapidocr-onnxruntime 1.4.4 / PP-OCRv4，CPU，纯 pip 安装）：

| 来源 | 药品 | 处理方式 | 结论 |
|---|---|---|---|
| 默沙东官网（assets.msdchina.com.cn） | 阿瑞匹坦（意美） | PDF 文字层字体编码损坏，300 dpi 渲染后 OCR，4 栏列优先重排 | 质量达标：4/4 核心章节命中，26 个章节、18,113 字；已入库 |
| 贝达药业官网 | 埃克替尼（凯美纳） | 4 张 JPG（1205 px 宽单栏长图）2 倍 Lanczos 放大后逐图 OCR | 质量达标：4/4 核心章节命中（`蒙忌`→`禁忌`、`国药准宇`→`国药准字` 归一化），23 个章节、14,200 字；已入库 |
| 正大天晴官网 | 安罗替尼（福可维） | 2 页 PDF 内嵌低分辨率扫描图（约 100–130 dpi），260 dpi 重渲染 + OCR | 不达标：核心章节 0 命中、全文 3,641 字严重乱码；字段全部留空，记 `label_ocr_failed` / `failures_ocr.json` |

OCR 结果的页码/图片序号映射保存在各药 `label.ocr.page_map`（`{section,page,y,image}`），可按 `downloads/` 中的原件回查；章节标题与固定格式前缀的确定性纠错记录在 `label.ocr.header_normalizations` / `label.ocr.text_normalizations`。

已尝试但不可用（原因见 `fetched/labels_cn/failures.json`）：辉瑞表柔比星/伊立替康/紫杉醇（页面需医疗卫生专业人士登录）、礼来雷莫西尤单抗（BookLink 跳转 SPA 无直链）、安进帕尼单抗/地舒单抗、卫材仑伐替尼、拜耳索拉非尼（官网未挂中文说明书全文）、齐鲁与恒瑞（无全文或说明书为图片）、默克优甲乐（中国官网未挂 PDF）。默沙东阿瑞匹坦、正大天晴安罗替尼、贝达埃克替尼原为"仅扫描件/图片"的失败来源，已由 32 号 OCR 重新尝试（结论见上表）。

格式说明：信达 PDF 为 2 页折叠 5 栏版式，pdfplumber 直接抽取会串栏；30 号脚本对章节标题偏少的 PDF 自动改用 PyMuPDF 行级列聚类重排。礼来 PDF 有逐字水印（「仅供参考，请以实际说明书为准」），独立成行的水印字已剔除，行内插入的单字无法安全去除。
