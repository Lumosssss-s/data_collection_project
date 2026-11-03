# 肿瘤循证知识中枢

> 面向肿瘤临床的循证知识检索、问答与分析平台 —— 以指南推荐条目为最小检索单元，融合混合检索、重排序、知识图谱与 LLM 生成，提供「可溯源、有证据等级、可拒答」的循证知识服务。

覆盖癌种：肺癌 / 乳腺癌 / 结直肠癌 / 胃癌 / 甲状腺癌（肝癌为赛程外预留码位，不交付数据）。

---

## 一、核心能力

| 模块 | 前端入口 | 接口前缀 | 说明 |
|---|---|---|---|
| 患者端（患者概览 / 随访 / 看报告 / 疾病档案） | `#/patient`、`#/followup`、`#/report`、`#/archive` | `/api/v1/followup`、`/api/v1/report`、`/api/v1/diseases` | 患者服务：随访任务与预警、报告文本解析、带癌种切换的疾病档案 |
| 疾病知识库（疾病库 / 指南 / 图谱） | `#/diseases`、`#/guides`、`#/kg` | `/api/v1/diseases`、`/api/v1/search/docs`、`/api/v1/kg` | 疾病归档、指南文档浏览（复用检索文档网格）、肿瘤图谱 |
| 循证检索（证据检索 / 癌种对照） | `#/search`、`#/compare` | `/api/v1/search`、`/api/v1/compare` | 混合检索 + 五维癌种对照；专题分析改为对照页内的慢路径入口 |
| 问答 | `#/qa` | `/api/v1/qa` | SSE 流式问答（进入时若有历史会话，先询问「继续 / 新建」） |
| 病历质控 / 知识库管理 | `#/qc`、`#/admin` | `/api/v1/qc`、`/api/v1/admin` | 底部工具区，弱化为工具入口 |

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

> **中文路径下重建镜像**：项目目录含中文时 BuildKit 会报非 ASCII 路径错误，构建前需先执行 `$env:DOCKER_BUILDKIT=0`（仅 `docker compose up` 命中缺失镜像需重建时才用得到；镜像已存在时直接 `up -d` 不触发构建）。

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

### 3.8 模型与外部依赖准备

后端依赖两个本地推理模型，均不入库（`models/` 已被 `.gitignore` 忽略，体积约 6.41GB）：

| 模型 | 用途 | 约占体积 | 目录 |
|---|---|---:|---|
| `bge-m3` | 向量检索 embedding（CPU 推理） | 约 4.27GB | `models/bge-m3/` |
| `bge-reranker-v2-m3` | cross-encoder 精排 | 约 2.14GB | `models/bge-reranker-v2-m3/` |

模型放置目录为仓库根的 `models/`，`.env` 中 `MEDICAL_MODELS_DIR` 默认即 `./models`（该目录通过只读卷挂载到容器内 `/models`）。**若 `models/` 缺失，backend 启动会失败**（容器内 embedding / reranker 路径不存在，健康检查 `/health/ready` 无法返回 200）。

其余外部依赖：

- Elasticsearch：由 `docker compose up -d` 一起构建并启动（`Dockerfile.es`，内置 IK 分词插件），无需手工安装。
- Redis：由 compose 启动（`redis:7-alpine`，用于语义缓存；连不上时后端自动降级到进程内精确缓存）。
- LLM：使用 DeepSeek 在线接口，无需本地模型。

环境变量从模板复制并填写：

```powershell
cp .env.example .env   # 然后填入 MEDICAL_LLM_API_KEY / MEDICAL_DEEPSEEK_API_KEY / MEDICAL_ES_PASSWORD / MEDICAL_ADMIN_TOKEN
```

`.env.example` 只含键名与安全默认值，不含任何真实密钥；`.env` 含真实密钥，已被 `.gitignore` 忽略，禁止提交。

### 3.9 H5 预览服务（Basic Auth）

移动端 H5 预览由仓库内脚本 `scripts/h5_preview.py` 提供，启动器为 `scripts/h5_preview.ps1`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\h5_preview.ps1
```

- 端口 **3100**：静态托管 `miniapp/dist`，`/api/*` 反代到 `127.0.0.1:8002`（后端），SSE 逐块透传。
- 凭据来自仓库根 `.env` 的 `MEDICAL_H5_AUTH_USER` / `MEDICAL_H5_AUTH_PASS`；**缺失任一项即拒绝启动**（fail-closed，不回退为无鉴权服务）。浏览器访问时按 `<user>:<pass>` 输入 Basic Auth。
- 端口 3100 已被占用时启动器直接退出并提示占用进程 PID，不会抢占端口。
- 日志：`%TEMP%\h5_preview.out.log`（访问日志：方法/路径/状态码/耗时）与 `%TEMP%\h5_preview.err.log`。
- 限制：服务以当前用户会话运行，**注销或重启后需手动重启**，未注册开机自启。

---

## 四、接口总览

统一前缀 `/api/v1`，响应统一封装 `{ success, data, message, code }`。

| 分组 | 代表接口 |
|---|---|
| 检索 | `GET /search`、`GET /search/docs`、`GET /search/doc/{doc_id}`、`GET /search/doc/{doc_id}/summary`、`GET /search/doc/{doc_id}/similar`、`GET /search/item/{item_id}/similar`、`GET /search/cancer_types`、`GET /search/topics` |
| 问答 | `GET /qa`、`POST /qa`、`GET /qa/stream`（SSE） |
| 专题 / 对比 | `GET /topic-analysis`、`POST /compare`、`POST /compare/deep-analysis`（前端：专题为对照页内慢路径入口） |
| 图谱 | `GET /kg/ontology`、`GET /kg/statistics`、`GET /kg/cancer/{cancer_type}`、`GET /kg/entity/{entity_id}`、`POST /kg/extract/{doc_id}` |
| 疾病库 | `GET /diseases`、`GET /diseases/search`、`GET /diseases/{disease_id}` |
| 患者端 | `GET /patient/drugs`、`GET /patient/drug/{drug_id}`、`GET /patient/diseases/{disease_id}`、`GET /patient/disclaimer` |
| P5 新增 | `/preconsult/*`、`/followup/*`、`/qc/*`、`/report/parse`（预问诊独立页入口已撤，保留患者端内嵌） |
| 统计 / 管理 | `/stats/*`、`/admin/*`（Token 鉴权） |
| 历史遗留（当前无消费者） | `/mapping/*`、`/structured/*`（`main.py` 已挂载，前端与小程序均未调用，待清理） |

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
