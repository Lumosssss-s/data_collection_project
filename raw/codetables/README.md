# 编码码表（A5 补码用）

本目录只保留码表来源说明，**不再存原件**：码表由 `tools/17_fetch_icdo3.py` 抓取并校验后落在
`fetched/codetables/nhc/`（原 `nhc/` 存档副本已清理，与抓取结果字节一致、SHA-256 相同）。

> **目录边界**：脚本抓取的码表放 `fetched/codetables/`（17 号，NHC 资料包）与 `fetched/atc/`（15 号，WHO ATC）；
> `cache/` 只放脚本中间件（`cache/codetables/icdo3_source_check.json` 抓取校验报告、`icdo3_mapping.json` 映射审计、`_unzipped/` 解压临时目录）。
> 码表本身**不产出独立成品 JSON**，它只在 16/18 号脚本里被读入、回补到已有成品：
> `data/clean/terminology/terminology_cancer.json`（`atc` / `icd_o3` 字段）、
> `data/clean/drug_labels/drug_catalog_v2.json`（`atc_code` / `atc_parent` 字段）。

## 1. NHC 国家临床版码表

来源：国家卫生健康委 **医院质量监测系统（HQMS）2.0 页面下载资料包**
<https://doc.hqms.org.cn/医院质量监测系统（HQMS）2.0页面下载资料包.rar>（入口页 <https://www.hqms.org.cn/usp/downFile.html>），下载日期 2026-10-27，整包 5.5 MB。
获取方式：`python tools/17_fetch_icdo3.py`（下载 → bsdtar 解压 → 结构校验 → 落地 `fetched/codetables/nhc/`）；码表原件只保留这一份，不再在 `raw/` 另存副本。

| 文件 | 规模 | 结构 | 用途 |
|---|---|---|---|
| `（3）肿瘤形态学编码（M码）-国家临床版2.0.xlsx` | 1,427 条 | `肿瘤形态学编码`（`M######/行为码`） / `肿瘤形态学名称` | **A5 `icd_o3` 字段**；行为码 `/0` 良性、`/1` 动态未定、`/2` 原位、`/3` 恶性、`/6` 转移，其中 `/3` 724 条 |

> **已弃用（原件在 `raw/_deprecated/codetables/nhc/`）**：`（1）疾病分类与代码国家临床版2.0（2022汇总版）`35,865 条、`（2）手术操作分类代码国家临床版3.0（2022汇总版）`13,652 条 —— 两者均**不产出任何成品**（A5 的 `icd10` 已由 CHIP-CDN 北京临床版 v601 码表覆盖；手术操作类不在 A5 六类实体范围内），按目录约定移入 `_deprecated`，需要时可原样取回复用。

授权：国家卫健委公开发布的行业管理码表，可引用；分发时保留来源与版本号。
格式差异（重要）：M 码采用 `M` + **5 位**数字 + `/` + 行为码（如 `M81400/3`），第 5 位是本地亚型细分序号（`0` = WHO 基础码 1,252 条；`1~5` = 本地亚型 175 条，如 `M80411/3` 小细胞神经内分泌癌 / `M80410/3` 小细胞癌）；WHO 原版为 4 位 `M-8140/3`。需求清单 §A3⑦ 硬性要求 `Mxxxx/x` 4 位，因此 `tools/18_icdo3_mapping.py` 输出时**去掉第 5 位**，原码写入 `annotation.icd_o3_source` 保留溯源。

## 2. WHO ATC（`fetched/atc/atc_oncology.csv`）

| 项 | 内容 |
|---|---|
| 来源 | WHO Collaborating Centre for Drug Statistics Methodology，ATC/DDD Index <https://atcddd.fhi.no/atc_ddd_index/>，索引页标注 Last updated **2026-01-20** |
| 抓取方式 | `tools/15_fetch_atc.py`：从 10 个顶级组（`L01` `L02` `L03` `H02` `H03` `M05` `A11` `A12` `A04` `G03`）向下钻取 3 级 → 4 级 → 5 级码表页解析（A04 止吐、G03 性激素为 2026-10-30 补充） |
| 存放位置 | `fetched/atc/`（抓取结果、未经加工，故不进 `raw/`；`cache/` 只放脚本中间件） |
| 规模 | **750 条** 5 级码 |
| 结构 | `code` / `name_en` / `group`（4 级父组）/ `parent`（顶级组） |
| 用途 | A5 drug 的 `atc` 字段；`name_en` 可回填 `en_name` |
| 授权 | WHO ATC 索引为 WHO 版权，此处仅作编码对照引用，不整体再分发；对外交付只出现单条编码与药名 |

已知缺口：`L01XU`、`L02AX` 无 5 级码（WHO 将 L01XU 视作 L01XX 的延续组），不影响实际映射；`雷洛昔芬`（raloxifene）在 2026 版索引中已不在 L02BA 5 级表，暂无法映射。

## 3. 补码进度

| 字段 | 状态 | 说明 |
|---|---|---|
| `icd10`（confirmed） | 已有 | CBLUE 北京临床版 v601 已入库 200 条；如需切到国家临床版 2.0，需按 `疾病名称` 重新匹配 |
| `icd_o3` | **已映射 189/240** | `tools/18_icdo3_mapping.py` 三级匹配：精确名 11 + 形态学关键词 35 + 部位性兜底 143；剩下 51 条为甲状腺肿/息肉/囊肿/积液等非形态学诊断，不适用 |
| `atc` | **已映射 15/15** | `tools/16_atc_mapping.py` 中文名 → INN → ATC 三层匹配；`雷洛昔芬` → `G03XC01`（G03 组，2026-10-30 补抓）。6 条药物类别名/短语已由 13 号脚本 `DRUG_CLASS_DROP` 剔除，不再进入 A5 |
| `loinc` | 不阻塞 | 需求清单 A5⑥ 字段表只要求 `icd10 / icd_o3 / atc`，**无 loinc 字段**；LOINC 仅在 ③ 作为可选官方码表来源提及。现有 51 条 examination 以影像/内镜/操作类为主，本身不适用 LOINC（LOINC 覆盖实验室检验/观察项，如 CEA、CA125、甲胎蛋白）；若要补化验类检查项，再从 Regenstrief 注册下载 |

## 复现

```bash
python tools/15_fetch_atc.py        # → fetched/atc/atc_oncology.csv（750 条）
python tools/16_atc_mapping.py      # → 回补 terminology drug 的 atc/en_name + drug_catalog_v2 的 atc_code
python tools/17_fetch_icdo3.py      # 下载 + 校验 NHC 资料包 → fetched/codetables/nhc/（1,427 条；本地有效则跳过下载，--force 重下）
python tools/18_icdo3_mapping.py    # → 回补 terminology disease 的 icd_o3；审计明细写 cache/codetables/icdo3_mapping.json
```
