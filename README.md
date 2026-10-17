# 肿瘤循证知识中枢

> 面向肿瘤临床的循证知识检索、问答与分析平台 —— 以指南推荐条目为最小检索单元，融合混合检索、重排序、知识图谱与 LLM 生成，提供「可溯源、有证据等级、可拒答」的循证知识服务。

覆盖癌种：肺癌 / 乳腺癌 / 结直肠癌 / 胃癌 / 甲状腺癌（肝癌为赛程外预留码位，不交付数据）。

---

## 一、核心能力

| 模块 | 前端入口 | 接口前缀 | 说明 |
|---|---|---|---|
| 循证检索 | `#/search` | `/api/v1/search` | 混合检索（BM25 + 向量）+ RRF + 精排，按癌种 / 文档类型 / 来源 / 场景 / 分期 / 生物标志物筛选 |
| 循证问答 | `#/qa` | `/api/v1/qa` | SSE 流式生成，答案逐句携带 `[来源: 指南 版本 章节]` 与证据等级；无依据时明确拒答 |
| 跨癌种专题分析 | `#/topic` | `/api/v1/topic-analysis` | 同一主题（如「PD-1 抑制剂」）在各癌种的适应证与证据差异 |
| 方案 / 疾病对比 | `#/compare` | `/api/v1/compare` | 双癌种五维对照（症状 / 病理分子 / 诊断 / 治疗 / 预后）+ LLM 深度分析 |
| 知识图谱 | `#/kg` | `/api/v1/kg` | 8 类医学实体 + 9 类关系；癌种全景子图、实体搜索与邻域子图 |
| 指南速览 | `#/guideline/{id}` | `/api/v1/search/doc/*` | 概要 / 核心推荐 / 证据特点 / 关键词 + 相关指南推荐 |
| 疾病知识库 | `#/diseases` | `/api/v1/diseases` | 疾病名归一（肺CA / NSCLC → 肺癌）、症状反查、双版本（专业版 / 患者版） |
| 智能预问诊 | `#/preconsult` | `/api/v1/preconsult` | 症状结构化采集 + 风险分层（高风险 / 中风险 / 常规）+ 就医方向建议 |
| 智能随访 | `#/followup` | `/api/v1/followup` | 随访计划、任务提醒、依从性统计、异常预警 |
| 病历质控 | `#/qc` | `/api/v1/qc` | 规则化质控要点核查（完整性 / 规范性） |
| 报告智能解析 | `#/report` | `/api/v1/report` | 检验检查报告结构化提取（仅整理文本，不做判读） |
| 患者端 H5 | `#/patient` | `/api/v1/patient` | 用药了解、患者版疾病科普（通俗改写 + 专业词括注） |
| 知识库管理 | `#/admin` | `/api/v1/admin` | 条目 CRUD、文档目录、目录重建（Token 鉴权） |
| 运营看板 | `#/dashboard` | `/api/v1/stats` | 指南数 / 条目数 / 疾病档案数 / 术语数 / 覆盖癌种 / 主题与年份分布 |

另有独立跨端小程序工程 `miniapp/`（Taro + React + TS，4 tabBar + 4 二级页，直连同一后端）。

---

## 二、技术架构

### 2.1 技术栈

| 层次 | 选型 |
|---|---|
| 后端框架 | FastAPI + uvicorn（Python 3.10，单进程） |
| 检索存储 | Elasticsearch 8.11 + IK 分词插件（`ik_max_word`） |
| 稠密向量 | bge-m3（`dense_vector` + cosine） |
| 精排 | bge-reranker-v2-m3（cross-encoder，CPU 推理） |
| 生成模型 | DeepSeek（API 可配置 `base_url` / `model`） |
| 前端 | 原生 JavaScript SPA（hash 路由）+ Chart.js + Nginx |
| 小程序 | Taro 4.1.9 + React 18 + TypeScript + Sass（CSS Modules） |
| 部署 | Docker Compose（ES / 后端 / 前端 三容器） |

### 2.2 索引设计

| 索引 | 用途 |
|---|---|
| `medical_knowledge` | 主索引，4 类 `data_type`：`doc`（指南文档）/ `rec`（推荐条目，检索主单元）/ `drug`（药品说明书）/ `term`（术语） |
| `medical_disease_profiles` | 疾病档案（A3） |
| `medical_kg_triples` | 知识图谱三元组 |
| `medical_kg_entities` | 图谱实体词典（别名归一） |
| `medical_analysis_cache` | 分析结果缓存（对比 / 专题 / 摘要 / 图谱指纹） |

### 2.3 检索链路

```
用户查询
  ├─ 1. 查询改写        繁简双向变体（同一查询的繁/简写法一并送入 multi_match）
  ├─ 2. 查询分解        复合查询按规则切分（LLM 兜底），各子查询并行检索，最多 3 路
  ├─ 3. 双路召回        BM25（IK，content^3 + title^5） 与 KNN（bge-m3 余弦）
  ├─ 4. RRF 融合        Reciprocal Rank Fusion（k=60）
  ├─ 5. 两阶段精排      仅对 RRF 前 N 条（`MEDICAL_RERANKER_WINDOW`，默认 20）跑 cross-encoder，
  │                     其余按 RRF 顺序拼接在尾部 —— 兼顾精度与 CPU 延迟
  ├─ 6. 上下文扩展      命中条目的同指南相邻条目补入尾部（retrieval_hop=2，标注来源）
  ├─ 7. 时效过滤        剔除已废止 / 已删除文档
  └─ 8. 结果缓存        精确命中即跳过整条链路（失效版本取 doc_catalog.json 的 mtime）
```

**并发模型**：检索 / 对比等重活走同步 `def` 路由，交由 FastAPI 线程池执行，避免阻塞单进程事件循环；流式接口（`/qa/stream`、`/structured-analysis/stream`）保持 `async`，阻塞迭代经 `run_in_executor` 卸载。

### 2.4 主要服务组件

| 组件 | 职责 |
|---|---|
| `retriever_service` | 检索主链路（改写 / 分解 / 混合召回 / RRF / 精排 / 上下文扩展） |
| `qa_service` | 循证问答（癌种识别 / prompt 组装 / 拒答 / 多轮会话） |
| `reranker_service` | cross-encoder 精排（并发信号量控制） |
| `entity_disambiguation_service` | 实体消歧四层：繁简统一 → 别名表 → 向量对齐 → 类型约束（含数字 / 编辑距离 / 长度三重守卫） |
| `kg_extraction_service` | 从推荐条目抽取医学三元组（LLM + 本体约束） |
| `query_decomposer` | 临床问题拆分（癌种 / 分期 / 分子 / 治疗线数四维，PICO 式） |
| `summary_service` / `abstract_service` | 指南速览卡 / 文档摘要 |
| `doc_management_service` | 知识库条目管理（增删改查 + 目录同步） |

### 2.5 目录结构

```
.
├── medical_rag/                 后端（容器内平铺为 /app）
│   ├── api/v1/                  路由层（15 个模块）
│   ├── core/                    配置、领域枚举、模型单例加载
│   ├── models/                  Pydantic DTO
│   ├── repositories/            ES 访问层（主索引 / 缓存 / 图谱 / 疾病档案）
│   ├── services/                业务服务层
│   ├── utils/                   工具（分块 / 数据加载 / 文档目录 / 检索缓存 / 主题分类）
│   ├── data/                    索引资产（doc_catalog.json / taxonomy_merged.json / zh_convert.json）
│   ├── eval_data/               评测脚本与产物
│   ├── ingest.py                数据入库（data/clean → ES）
│   ├── run_abstracts.py         批量生成文档摘要
│   └── main.py                  应用入口（含 /health 与 /health/ready）
├── frontend/                    原生 JS SPA（由 Nginx 托管）
├── miniapp/                     Taro 跨端小程序（患者端）
├── docs/                        本地施工图（不入库，见 §7）
├── Dockerfile / Dockerfile.es  后端镜像 / ES+IK 镜像
├── docker-compose.yml           三容器编排
└── .env                         环境变量（不入库）
```

---

## 三、快速开始

### 3.1 前置条件

- Docker Desktop（建议 ≥ 10GB 可用内存）
- 本地模型目录：`bge-m3` 与 `bge-reranker-v2-m3`（约 6.4GB）
- DeepSeek API Key（仅问答 / 生成类接口需要；缺失时检索不受影响）

### 3.2 配置环境变量

在项目根目录创建 `.env`：

```dotenv
# LLM（问答 / 生成 / 抽取）
MEDICAL_LLM_API_KEY=<your-deepseek-api-key>
MEDICAL_DEEPSEEK_API_KEY=<your-deepseek-api-key>

# Elasticsearch
MEDICAL_ES_PASSWORD=123456

# 管理端 Token
MEDICAL_ADMIN_TOKEN=<change-me>

# 本地模型目录（指向含 bge-m3 / bge-reranker-v2-m3 的父目录）
MEDICAL_MODELS_DIR=./models
```

可选调优（均有默认值，见 `docker-compose.yml`）：`MEDICAL_TORCH_NUM_THREADS`、`MEDICAL_RERANKER_WINDOW`、`MEDICAL_RERANKER_BATCH_SIZE`。

### 3.3 启动

```powershell
docker compose up -d
# 首次启动会自动构建 medical-rag-es（内置 IK）与 medical-rag-backend 镜像
```

### 3.4 就绪判定

模型冷加载约 60s，期间 `/health/ready` 返回 503：

```powershell
(Invoke-WebRequest http://localhost:8002/health/ready -UseBasicParsing).Content
# 期望：{"status":"ready", ...}
```

> `/health` 只表示进程存活；**能否高效服务请以 `/health/ready` 为准。**

### 3.5 访问

| 入口 | 地址 |
|---|---|
| Web 前端 | http://localhost:3001 |
| 后端 API | http://localhost:8002/api/v1 |
| 接口文档（Swagger） | http://localhost:8002/docs |
| Elasticsearch | http://localhost:9201 |

### 3.6 数据入库

清洗后的数据按 14 个固定目录置于 `medical_rag/data/clean/`，由 `ingest.py` 消费（目录不存在时相关模块优雅降级，接口返回 `degraded=true` + 提示，不抛 500）：

| 目录 | 去向 |
|---|---|
| `guidelines/` `recommendations/` `drug_labels/` `terminology/` | ES 主索引（`doc` / `rec` / `drug` / `term`） |
| `disease_profiles/` `kg_triples/` | ES（疾病档案 / 图谱，写入链路按需启用） |
| `triage_rules/` `preconsult_slots/` `followup_templates/` `patient_messages/` `qc_rules/` `eval_sets/` `mock_cases/` `ops_metrics/` | 文件态，由对应模块直读，不入 ES |

```powershell
# 入库（容器内 /app 下运行）
docker compose exec backend python ingest.py
# 批量生成文档摘要（写入 doc.content 并刷新向量）
docker compose exec backend python run_abstracts.py
```

### 3.7 小程序

```powershell
cd miniapp
npm install
npm run dev:weapp     # 微信开发者工具导入 miniapp/ 目录
npm run build:h5      # H5 预览
```

后端地址配置在 `miniapp/src/services/api.ts` 的 `API_BASE`：本机调试用 `localhost:8002`，真机调试改为局域网 IP，并在小程序后台配置 request 合法域名。未启用微信云开发，直连自建后端（真实后端优先，数据未就绪时以示例数据兜底并显式提示）。

---

## 四、接口总览

统一前缀 `/api/v1`，响应统一封装 `{ success, data, message, code }`。

| 分组 | 代表接口 |
|---|---|
| 检索 | `GET /search`、`GET /search/docs`、`GET /search/doc/{doc_id}`、`GET /search/doc/{doc_id}/summary`、`GET /search/doc/{doc_id}/similar`、`GET /search/item/{item_id}/similar`、`GET /search/cancer_types`、`GET /search/topics` |
| 问答 | `GET /qa`、`POST /qa`、`GET /qa/stream`（SSE） |
| 专题 / 对比 | `GET /topic-analysis`、`POST /compare`、`POST /compare/deep-analysis` |
| 图谱 | `GET /kg/ontology`、`GET /kg/statistics`、`GET /kg/cancer/{cancer_type}`、`GET /kg/entity/{entity_id}`、`POST /kg/extract/{doc_id}` |
| 疾病库 | `GET /diseases`、`GET /diseases/search`、`GET /diseases/{disease_id}` |
| 患者端 | `GET /patient/drugs`、`GET /patient/drug/{drug_id}`、`GET /patient/diseases/{disease_id}`、`GET /patient/disclaimer` |
| P5 新增 | `/preconsult/*`、`/followup/*`、`/qc/*`、`/report/parse` |
| 统计 / 管理 | `/stats/*`、`/admin/*`（Token 鉴权） |

其余路由以 `http://localhost:8002/docs` 为准。

---

## 五、评测

`medical_rag/eval_data/` 提供 7 个评测脚本，统一输出到 `results/<时间戳>/`。建议先停后端释放内存：

```powershell
docker compose stop backend
docker compose run --rm -T -e PYTHONPATH=/app backend python -u /app/eval_data/run_enhanced_eval.py   # 四策略对比（BM25 / 向量 / 混合 / 混合+重排）
docker compose run --rm -T -e PYTHONPATH=/app backend python -u /app/eval_data/run_qa_eval.py          # 问答（检索命中@K / 引用正确率 / 无幻觉率 / 拒答正确率）
docker compose start backend
```

| 脚本 | 口径 |
|---|---|
| `run_eval_pipeline.py` | 主检索管道：Recall@5/10、MRR、NDCG@10 |
| `run_enhanced_eval.py` | 增强评测（按癌种细分），E-01 / E-06 的共享实现 |
| `run_four_strategies.py` | 四策略横向对比 |
| `run_reranker_eval.py` | 精排增益 |
| `run_multihop_ab.py` | 多跳检索 A/B |
| `run_qa_eval.py` | 问答四指标 |
| `generate_4charts.py` | 图表生成（依赖 `matplotlib`，需在已装该包的宿主环境运行） |

> 评测基线待首批数据入库后重建；LLM 主观指标（相关性 / 忠实性）跨批次不可直接比较，引用时需标注评判口径与日期。

---

## 六、已知限制

- 数据依赖：`medical_rag/data/clean/` 数据未就绪时，相关接口返回 `degraded=true` 与说明性 `note`，前端显示提示而非报错。
- 单次检索延迟以 CPU 精排为主导（单进程 + CPU 推理），属算力约束而非排队。
- 结构化专题分析（`/structured-analysis`）与条款映射模块（`/mapping`）在赛程内保留接口、不重点建设。
- 跨文档引用解析仅覆盖同指南内引用；法规版本管理（as-of 检索）未实现。

---

## 七、医疗合规与免责

- 所有面向用户的生成内容**仅基于检索到的指南推荐条目**，强制携带来源标注与证据等级，不构成诊疗建议，定位辅助参考。
- 患者端每个页面固定展示免责声明与就医指引（见 `miniapp/src/utils/constants.ts`），不给诊断结论、不给处方。
- 报告解析仅做文本结构化整理，不做影像判读与诊断结论。
- 严禁将真实患者个人信息（PHI）写入代码、示例数据或日志。

---

## 八、仓库文档约定

- **本仓库仅跟踪 `README.md` 一个 Markdown 文档**。其余 `.md`（含 `docs/` 下的施工图、需求清单、改造方案等）已在 `.gitignore` 中排除，仅本地留存、不入库、不推送。
- 新建 `.md` 默认被忽略；确需入库时使用 `git add -f <path>`，并同步调整 `.gitignore` 规则。
- 环境文件（`.env`、`docker.env`）与大型数据 / 模型目录同样不入库。
