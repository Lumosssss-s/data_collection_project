# virtual_cases 虚拟病例目录（C4 预问诊病例集 / C6 模拟病例）

本目录存放 **C 组评测与演示用的虚拟病例**，当前共 **150 条**，全部为**模板化合成数据**，不含任何真实患者信息。

> ⚠️ **状态：待医学审核（draft）。未经专业医生复核前，不得作为临床依据、不得用于任何诊疗决策。**
> 每条病例均由脚本按固定模板生成，医学合理性尚未经执业医师确认；引用方须自行承担复核责任。

> 路径说明：需求清单中 C4 建议放 `data/clean/eval_sets/`、C6 建议放 `data/clean/mock_cases/`；本项目按要求合并为 `data/virtual_cases/` 一个独立目录，字段仍分别对齐两节规范。提交评审时需在清单/方案中注明这一目录映射。

## 依据（需求清单）

| 来源 | 清单小节 | 关键要求 |
|---|---|---|
| C4 预问诊病例集 | §C4（第 1604–1662 行） | 50~100 例；普通 / 高危 / 急诊约 60% / 30% / 10%；每条叙述 80~200 字、患者自然口吻；标注期望红旗征 + 科室 + 风险等级；`qid` = `EVAL-TRIAGE-<序号>`；`task_type=triage`；`origin=self_built` |
| C6 模拟病例 | §C6（第 1726–1783 行） | 20~50 例；场景覆盖 initial / revisit / followup / emergency；`case_id` = `CASE-<序号>`；`structured` 固定六项：**主诉 / 现病史 / 既往史 / 检查 / 诊断 / 医嘱**；`labels` 含 `expected_triage` 与 `qc_issues`；全部虚构，禁止真实姓名/身份证号/手机号/住院号（G13） |
| 受控词表 | §6.1 | `risk_level`：`emergency` / `urgent` / `routine`；`stage`：`0` / `I` / `II` / `III` / `IV` / `unknown` |

两种情况共用本目录，用 `case_type` 区分：`triage_case`（C4）、`mock_case`（C6）。

## 文件与规模

| 文件 | 记录数 | 内容 |
|---|---|---|
| `virtual_cases_20261105.json` | **150** | 合成病例。C4 100 条（`EVAL-TRIAGE-0001`~`0100`）+ C6 50 条（`CASE-0001`~`0050`） |

数量分布（本轮扩量后的实际值）：

| 分组 | 分类 | 条数 |
|---|---|---|
| C4 `triage_case` | `routine` / `urgent` / `emergency` | 60 / 30 / 10（60% / 30% / 10%） |
| C6 `mock_case` | `initial` / `revisit` / `followup` / `emergency` | 13 / 13 / 12 / 12 |

## 扩量方式与去重自检

- **C4**：15 类普通病例图景 × 4 个变体 = 60；15 类高危图景 × 2 个变体 = 30；10 类急诊图景 = 10。变体覆盖年龄段、性别、吸烟史、就诊背景，主诉分 A/B 两种自然口吻，避免"同一句只改数字"。
- **C6**：50 条独立模板，按肺癌亚型（腺癌 / 鳞癌 / 小细胞 / 微浸润）、分期与治疗阶段（初诊、术后辅助、靶向、免疫、放化疗、复发、急症）分布，无重复叙述。
- 自检结果：C4 100 条输入全部唯一，长度 94~131 字；任意两条文本相似度中位数 0.435、p95 0.703、最高 0.815（最高值出现在同一图景的两个不同人群变体，属预期）。C6 50 条 `narrative` 全部唯一。

## 真实脱敏病例来源核查结论

判定口径：**只有许可证明确允许再分发、且确为病例级文本的，才能放入本交付目录**；需申请授权或协议禁止再分发的，一律不用，只做记录引用。

| 数据集 | 类型 | 许可证 / 协议（官方） | 结论 | 理由 |
|---|---|---|---|---|
| MIMIC-IV / MIMIC-CXR | EHR / 影像报告 | PhysioNet Credentialed Access + DUA 1.5.0（physionet.org/content/mimiciv） | 不可用 | 需认证培训并签 DUA，协议禁止再分发 |
| n2c2 / i2b2 | 临床笔记 | n2c2 Data Use Agreement（n2c2.dbmi.hms.harvard.edu/data-sets） | 不可用 | DUA 明令不得转交他人或上传公开网站 |
| CMB | 考试题 + 74 条案例问答 | Apache-2.0（huggingface.co/datasets/FreedomIntelligence/CMB） | 不可用 | 主体是医学考试题，非病例级文本 |
| CMedQA2 | 问答对 | 仅限非商业研究（代码 GPL-3.0；github.com/zhangsheng93/CMedQA2） | 不可用 | 类型不符，且无明确再分发条款 |
| MedDG | 医患对话 | GPL-3.0（仅代码），数据经 Drive 分发（github.com/lwgkzl/MedDG） | 不可用 | 纯对话语料，数据无独立许可证 |
| CMExam | 考试题 | Apache-2.0，限学术、禁商用（github.com/williamliujl/CMExam） | 不可用 | 考试题，非病例文本 |
| PMC-Patients | 英文病例摘要 | CC BY-NC-SA 4.0（huggingface.co/datasets/zhengyun21/PMC-Patients） | 条件性可用，未采用 | 病例级文本，但 NC + SA 会传染整个交付集，且为英文 |
| TCM-SD | 中文中医病历 | CC BY-NC-SA 4.0（tianchi.aliyun.com/dataset/139034） | 条件性可用，未采用 | 主题为中医诊疗、非肺癌；NC + SA 限制交付 |
| MedTxt-CR | 病例报告 | J-Stage 版权，仅可申请（sociocom.naist.jp/medtxt-en/cr） | 不可用 | 不公开分发，禁止再分发 |
| MTS-Dialog | 对话 | 无明确许可（源自 MTSamples；github.com/sdiazlor/MTS-Dialog） | 不可用 | 上游许可不明 |
| DDXPlus | 合成结构化病例 | CC-BY（github.com/mila-iqia/ddxplus） | 不可用 | 合成症状表，非病例叙述 |
| LCMDC / 预问诊相关集 | 分诊问诊对话 | 论文 CC BY 4.0，数据许可未明（arxiv.org/abs/2410.03521） | 不可用 | 非病例级文本；部分原始数据需申请 |

**结论：在"无附加限制、可直接再分发"的严格口径下，没有可放入本交付目录的真实脱敏病例。** 因此本目录全部使用合成病例；上述数据集仅作为未来可选参考，若确需引入须先取得书面授权并单独评审。

## 口径对齐

| 项目 | 落点 | 状态 |
|---|---|---|
| `risk_level` | 统一为 **`routine` / `urgent` / `emergency`** | **已对齐** §6.1 受控词表；原 `normal` 已全部替换为 `routine` |
| `qc_issues` | 数组，元素固定为 `{"field","type","severity"}`；`type` ∈ `completeness` / `consistency` / `standardization` / `timeliness`（B6 四类），`severity` ∈ `high` / `medium` / `low` | **结构已定义并纳入校验**；本批无质量问题，全部为 `[]` |
| 红旗征 `red_flags` | `gold.red_flags` / `labels.expected_triage.red_flags` 有 A5 canonical 的已改用 canonical；每条原始表述保留在 `annotation.red_flag_terms`（`raw`/`canonical`/`term_id`/`mapping_status`） | **已映射 9 个词条**（咯血、胸痛、呼吸困难、声音嘶哑、体重下降、淋巴结肿大、盗汗、水肿、背痛）；上腔静脉综合征、窒息风险、夜间胸闷、持续发热、大汗、意识改变、颈静脉怒张、喘鸣、抽搐、下肢无力、大小便障碍、口渴多尿、嗜睡、心包填塞等 **A5 无对应词条，保留原表述并标 `canonical=null`**，待 A5 补词后批量映射 |
| 审核角色代号 | 项目统一代号见根 `README.md`「审核角色代号约定」 | **已建立**：`病例编写-A`、`医学审核-A` 等，禁止真实人名 |
| 目录映射 | 合并存放于 `data/virtual_cases/`，与 C4 `eval_sets/`、C6 `mock_cases/` 的差异已在根 README 与本文件登记 | 已登记，待评审确认 |

> A5 术语字典中 symptom 词条的 `mapping_status` 目前均为 `pending`（待与上游码表核验），故 `annotation.red_flag_terms.mapping_status` 如实记录为 `pending`；canonical 与 `term_id` 本身可解析、可校验。

## 字段结构

### 公共字段（两种 `case_type` 都必填）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `case_id` | string | 是 | 全局唯一。`triage_case` 用 `EVAL-TRIAGE-<4 位序号>`（与 `qid` 同值）；`mock_case` 用 `CASE-<4 位序号>` |
| `case_type` | enum | 是 | `triage_case` / `mock_case` |
| `cancer_type` | enum | 是 | 本批全部 `lung` |
| `stage` | string / null | 是 | `0` / `I` / `II` / `III` / `IV` / `unknown`；C4 不适用写 `null`（G8） |
| `origin` | enum | 是 | 固定 `self_built` |
| `synthetic` | bool | 是 | 固定 `true` |
| `disclaimer` | string | 是 | 固定文案：`本病例为合成数据，非真实患者，不构成医疗建议` |
| `disease_id` | string | 是 | 关联 A3 疾病档案，必须存在于 `data/clean/disease_profiles/`，不允许悬空 |
| `related_recommendations` | array | 是 | 关联 A2 推荐条目的 `rec_id`，必须全部存在，不允许悬空 |
| `annotation` | object | 是 | `{"author","date","status","red_flag_terms"}`；本批 `status=draft`，`author=病例编写-A` |
| `version` | string | 是 | 记录级版本，本批 `v1` |
| `last_updated` | date | 是 | `YYYY-MM-DD` |

### `triage_case` 专属字段（C4）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `qid` | string | 是 | 与 `case_id` 同值，`EVAL-TRIAGE-<4 位序号>` |
| `task_type` | enum | 是 | 固定 `triage` |
| `input` | string | 是 | 病例叙述，**80~200 字**，患者/家属自然口吻（本批实测 94~131 字） |
| `gold` | object | 是 | `{"red_flags":[…],"department":"…","risk_level":"routine|urgent|emergency"}` |
| `difficulty` | enum / null | 是 | `easy` / `medium` / `hard`；未标注写 `null`（G8） |

### `mock_case` 专属字段（C6）

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `scenario` | enum | 是 | `initial` / `revisit` / `followup` / `emergency` |
| `narrative` | string | 是 | 脱敏虚构叙述（G13） |
| `structured` | object | 是 | **固定六项**：`主诉` / `现病史` / `既往史` / `检查` / `诊断` / `医嘱`；六项均须有值 |
| `labels` | object | 是 | `{"expected_triage":{"red_flags":[…],"department":"…","risk_level":"…"},"qc_issues":[…]}`；无缺陷写 `[]` |

> 已按约定**去掉可选 `medications` 字段**：用药与方案信息统一并入 `structured.医嘱`，便于校验脚本按六键严格比对。

## 生成规则与可追溯性

1. **一律标合成**：每条 `synthetic=true` 且带固定 `disclaimer`。
2. **禁止真实标识**：不得出现真实姓名、身份证号、手机号、住院号、门诊号、具体医院名、具体住址（G13）；医院统一写科室名。
3. **不引入真实病历文本**：叙述全部自写，不摘抄医院病历或受限来源。
4. **ID 不悬空**：`disease_id` 只取 A3 中真实存在的 `DIS-LUNG-0001`~`0006`；`related_recommendations` 运行时从 A2 按场景分组取真实 `rec_id`。
5. **用药可追溯**：`structured.医嘱` 中出现的药名必须能在 `data/clean/drug_labels/drug_catalog_v2.json` 命中；本批只用到目录内药品（培美曲塞、卡铂、吉西他滨、顺铂、依托泊苷、紫杉醇、奥希替尼、阿来替尼、安罗替尼、帕博利珠单抗、非格司亭、唑来膦酸、地塞米松、左甲状腺素等），不编造药名、剂量或检查项目。
6. **确定性生成**：模板顺序固定、日期固定、无随机数与时间戳，重复运行字节级一致。

## 与 A2 / A3 的关联方式

| 关联 | 字段 | 目标文件 | 校验规则 |
|---|---|---|---|
| 疾病 | `disease_id` | `data/clean/disease_profiles/disease_profiles_lung_20261028_v2.json` | 必须命中 A3，未命中即失败 |
| 诊疗依据 | `related_recommendations[]` | `data/clean/recommendations/recommendations_lung_20261028_v3.json` | 每个 `rec_id` 必须存在；C4 用 `screening` / `diagnosis` / `staging` / `supportive_care`，C6 用 `diagnosis`（initial）/ `treatment_adjuvant`（revisit）/ `treatment_later`（followup）/ `supportive_care`（emergency） |
| 术语（红旗征） | `gold.red_flags` / `labels.expected_triage` | `data/clean/terminology/terminology_cancer.json` | 有 canonical 的已映射并校验 `term_id`；无词条的登记为待映射 |

关联为**单向引用**：病例引用 A2/A3，A2/A3 不回写病例。

## JSON 记录示例（C4 首条实际产物）

```json
{
  "case_id": "EVAL-TRIAGE-0001",
  "qid": "EVAL-TRIAGE-0001",
  "case_type": "triage_case",
  "task_type": "triage",
  "cancer_type": "lung",
  "stage": null,
  "input": "患者58岁男，吸烟三十年，每天一包。体检发现右肺上叶一枚八毫米磨玻璃结节，无明显不适。无咳嗽、咯血、发热，体重近期无明显变化。平时身体尚可，没有规律体检的习惯。病来精神尚可，饮食睡眠正常，大小便无异常，近期体重稳定，生活自理。",
  "gold": {"red_flags": [], "department": "呼吸内科", "risk_level": "routine"},
  "difficulty": null,
  "disease_id": "DIS-LUNG-0001",
  "related_recommendations": ["REC-LUNG-NHC-0001", "REC-LUNG-NHC-0002"],
  "origin": "self_built",
  "synthetic": true,
  "disclaimer": "本病例为合成数据，非真实患者，不构成医疗建议",
  "annotation": {"author": "病例编写-A", "date": "2026-11-05", "status": "draft", "red_flag_terms": []},
  "version": "v1",
  "last_updated": "2026-11-05"
}
```

带红旗征的记录，`annotation.red_flag_terms` 形如：

```json
[{"raw": "持续胸痛", "canonical": "胸痛", "term_id": "TERM-SYMPTOM-XXXX", "mapping_status": "pending"}]
```

`qc_issues` 元素结构（本批为空数组，供后续标注使用）：

```json
[{"field": "现病史", "type": "completeness", "severity": "high"}]
```

## 生成与校验

```powershell
# 生成（幂等，重复运行字节级一致）
python tools\33_generate_virtual_cases.py

# 结构校验（只读；退出码 0 为通过）
python tools\34_validate_virtual_cases.py
```

校验覆盖：字段完整性、受控值合法性（`case_type` / `task_type` / `origin` / `risk_level` / `scenario` / `stage` / `status` / `qc_issues`）、`disease_id` 与 `rec_id` 可解析、`red_flag_terms` 与 A5 一致、目录外药名扫描、禁忌标识（身份证/手机号/住院号/医院名/长数字串）、C4 叙述长度 80~200、C6 六项齐全、`synthetic` 与 `disclaimer` 一致。

## 质量与验收

- C4：风险构成 60 / 30 / 10；`red_flags`、`department`、`risk_level` 需医师复核；红旗征召回率 ≥95% 为后续评测指标。
- C6：六项齐全、四类场景齐备、脱敏检查全过、临床合理性需医师复核。
- 通用：`case_id` / `qid` 唯一；ID 无悬空；无真实身份信息。

## 待复核事项（需项目确认）

1. **医学审核**：150 条全部为 `draft`，须由执业医师逐条复核后改 `reviewed`/`approved`；**复核前不得作为临床依据**。
2. **审核角色代号**：现用 `病例编写-A`、`医学审核-A`（尚未指定实际审核人）；真实姓名名单只保留在仓库外的内部台账。
3. **红旗征待映射词条**：上腔静脉综合征、窒息风险、夜间胸闷、持续发热、大汗、意识改变、颈静脉怒张、喘鸣、抽搐、下肢无力、大小便障碍、口渴多尿、嗜睡、心包填塞共 14 类，A5 补词后需批量映射。
4. **A5 `mapping_status`**：symptom 词条当前均为 `pending`，待上游码表核验后统一改为 `confirmed`，届时同步刷新 `annotation.red_flag_terms.mapping_status`。
5. **`qc_issues` 填充**：本批无缺陷，全部 `[]`；后续若引入缺陷样本，按 `{field,type,severity}` 填写。
6. **目录映射**：与清单 C4（`eval_sets/`）、C6（`mock_cases/`）的路径差异需在清单或方案中登记。
