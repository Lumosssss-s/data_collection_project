# 肿瘤循证知识中枢

面向肿瘤临床与患者服务场景的循证知识检索、问答与分析系统。以指南推荐条目（REC）为最小检索单元，检索结果带来源与证据等级，证据不足时拒答。参赛赛事为兴智杯（依据：`docker-compose.yml` 首行注释）；具体赛道名称与赛题编号未在仓库内找到文档，未核实。

## 目录

- [项目简介](#项目简介)
- [核心能力与边界](#核心能力与边界)
- [系统架构与技术栈](#系统架构与技术栈)
- [技术实现详解](#技术实现详解)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [端口与访问](#端口与访问)
- [配置项](#配置项)
- [数据说明](#数据说明)
- [评测与指标](#评测与指标)
- [已知限制](#已知限制)
- [常见问题](#常见问题)
- [许可与第三方合规](#许可与第三方合规)
- [更新记录](#更新记录)
- [团队](#团队)

## 项目简介

系统把指南与推荐条目、药品说明书、术语、文献摘要统一入库，向前端提供检索、对照、问答、疾病档案、患者服务与知识库管理能力。指南与疾病档案覆盖肺癌、结直肠癌、乳腺癌、胃癌四类癌种；甲状腺癌无疾病档案与指南（仅有 2 条甲状腺药品说明书），肝癌无任何条目（依据：ES 全索引 `data_type` 与 `cancer_types` 聚合）。

当前数据规模为 4,370 条主索引文档（依据：`curl http://localhost:9201/medical_knowledge/_count` 与 `data_type` 聚合），属小规模演示库，不是完整指南库。

## 核心能力与边界

| 能力 | 实现说明 | 主要入口 |
|---|---|---|
| 循证检索 | BM25（IK 分词）+ 向量（bge-m3）+ RRF 融合 + cross-encoder 精排，返回带来源与证据等级的条目 | `#/search` |
| 癌种对照 | 按癌种维度并列展示推荐条目，支持慢路径深度分析 | `#/compare` |
| 循证问答 | SSE 流式输出，携带引用；实体槽位缺失或证据不足时走拒答模板 | `#/qa` |
| 疾病知识库 | 10 份疾病档案（通俗版 / 专业版两套文本）、指南浏览、药品库、知识图谱 | `#/diseases`、`#/guides`、`#/drugs`、`#/kg` |
| 患者服务 | 随访任务与预警、报告文本结构化、患者端药品与疾病页 | `#/patient`、`#/followup`、`#/report`、`#/archive` |
| 病历质控、知识库管理 | 文本质控提示；条目增删改查（管理接口需 Token） | `#/qc`、`#/admin` |

**明确不做的事**

- 不做诊断结论、不给处方、不做影像判读；报告解析只做文本结构化整理。
- 不做真实患者数据托管；仓库内不含任何真实个人信息（PHI）。
- 甲状腺癌无指南与疾病档案（仅有 2 条药品说明书），不覆盖肝癌；不提供 NCCN、CSCO 原文全文检索（仓库内未收录其原文）。
- 不提供多跳推理（2026-10-30 弃用，依据：`medical_rag/core/config.py` 多跳段落注释）。
- 不承诺临床可直接使用的准确性；当前指标与数据审核状态见下文。

## 系统架构与技术栈

### 分层与链路

```
浏览器 / 移动端
   │
   ├─ 3001  nginx:alpine ── 静态 SPA，/api/ 反代 backend:8001
   └─ 3100  nginx:alpine ── 移动端 H5（Basic Auth），独立 server block 8080
                 │
          FastAPI（容器 8001，宿主 8002）
                 │
   ┌─────────────┼──────────────┬──────────────┐
   服务层        检索链路         生成链路        数据访问层
   qa / kg /    改写→分解→       DeepSeek API   ES 8.11.0 ×5 索引
   reranker /   双路召回→RRF→                   Redis 7（语义缓存）
   followup …   两阶段精排→上下文扩展
                 │
          本地模型（只读挂载 /models）：bge-m3、bge-reranker-v2-m3
```

检索链路共 8 步：繁简改写 → 查询分解（默认关闭） → BM25 + KNN 双路召回 → RRF（k=60） → 两阶段精排（只对 RRF 前 20 条跑 cross-encoder） → 同指南相邻条目扩展 → 时效过滤 → 结果缓存（依据：`medical_rag/services/retriever_service.py`、`medical_rag/core/config.py`）。

### 技术栈与版本

| 层次 | 选型与版本 | 依据 |
|---|---|---|
| 运行时 | Python 3.10（`python:3.10-slim`） | `docker/Dockerfile` |
| Web 框架 | FastAPI（`>=0.104.0`）+ uvicorn，单进程 | `medical_rag/requirements.txt`、`docker/Dockerfile` CMD |
| 推理 | torch 2.0.0+cpu、transformers 4.36.2、sentence-transformers ≥2.2.0 | `docker/Dockerfile` L13、L29–L30 |
| 检索存储 | Elasticsearch 8.11.0（自建镜像 `medical-rag-es:8.11.0`，内置 IK 8.11.0） | `docker-compose.yml` L9、`docker/Dockerfile.es` |
| 缓存 | Redis 7-alpine，maxmemory 128MB，AOF everysec | `docker-compose.yml` L32、L43–L54 |
| 嵌入模型 | bge-m3（CPU，约 2.14GB） | `medical_rag/core/config.py`、`models/bge-m3` 实测体积（已剔除未使用的 `onnx/`） |
| 精排模型 | bge-reranker-v2-m3（cross-encoder，CPU，约 2.14GB） | 同上，合计 4.28GB |
| 编排 | langchain-core 0.3.x、langchain-openai 0.2.x，可用 `MEDICAL_RAG_CHAIN_ENABLED=false` 回退手写链路 | `medical_rag/requirements.txt` |
| 生成模型 | DeepSeek `deepseek-flash`（在线 API，可配 `base_url`） | `medical_rag/core/config.py`、`docker-compose.yml` L88 |
| Web 前端 | 原生 JavaScript SPA（hash 路由）、Chart.js 4.4.0、DOMPurify 3.0.6、nginx:alpine | `frontend/index.html` |
| 移动端 | Taro 4.1.9 + React 18 + TypeScript，`build:h5` 产物由 nginx 容器托管 | `miniapp/package.json` |
| Node | 未锁定版本（仓库内无 `.nvmrc`、`package.json` 无 `engines`） | 实测仓库根目录 |

部署形态为 Docker Compose 四服务：`elasticsearch`、`redis`、`backend`、`frontend`（依据：`docker-compose.yml` 的 `services` 段）。

## 技术实现详解

本章按功能拆解实现路径，文件名与行号对应当前仓库代码。界面一律用表格描述，不引用图片；图表见申报书。

### 1. 问答主链路

**解决什么问题**：把自然语言问题落到"可引用的推荐条目"上，再让模型只依据这些条目作答，避免自由生成。

**实现路径**：入口 `POST /api/v1/qa/stream`（`medical_rag/api/v1/qa.py` L63）或 `GET`（L26），`qa_service.ask_stream`（`services/qa_service.py` L519）先尝试语义缓存，未命中原样透传底层帧。

1. 检索：`RetrieverService.search()`（`services/retriever_service.py` L342）调用 `ElasticsearchRepository.hybrid_search()`（`repositories/elasticsearch.py` L905）。
2. 双路召回：`_hybrid_search_with_vector`（L958）并行发起 BM25（`_bm25_search` L1051）与 KNN（`_knn_search` L1005）。
3. 融合：ES 原生 RRF，`rank_constant=60`；服务层另有 `_rrf_merge_results(rrf_k=60)`（`retriever_service.py` L188）用于子查询等多组结果合并。
4. 时效过滤：两路检索都追加 `_excluded_doc_filter()`（L1029、L1084），按 `doc_catalog.json` 的 status 排除 `repealed/deleted/missing` 文档（状态集合 L1162）；目录以 mtime 为版本缓存。
5. 精排：`_rerank_two_stage` 只对 RRF 前 20 条跑 cross-encoder（`reranker_window=20`），batch=8，并发信号量 2（`core/config.py` L107）；窗口外候选按 RRF 顺序拼回。
6. 上下文扩展：`_expand_context()`（`retriever_service.py` L209）按同 `doc_id`、同节优先补入相邻条目，最多 5 条，单条截断 1000 字符（`core/config.py`）。
7. 生成：拼 prompt 后流式调用 DeepSeek `deepseek-flash`；`rag_chain_enabled=true` 时走 LangChain LCEL，`rag/chain.py` L23 `build_retrieval_stage`、L36 `build_generation_stage`，用 `RunnablePassthrough.assign` 把检索结果挂到 payload；关掉开关回退手写链路 `_ask_stream_legacy`（L719）。

**技术栈**：ES 8.11.0 + IK、bge-m3、bge-reranker-v2-m3、langchain-core 0.3.x、DeepSeek API。

**关键设计取舍**：

- 用 RRF 而不是加权求和：BM25 分数无上界、余弦在 −1~1，加权前要先归一化并调参；RRF 只看名次，只需 `k` 一个参数，跨查询更稳。
- 两阶段精排而非全量精排：cross-encoder 是 CPU 推理，约占检索延迟 93%；只排前 20 条可把该阶段压到约 40%，窗口外候选不丢弃、按 RRF 顺序兜底。
- 文献证据层追加而非混排：英文摘要相似度普遍偏低，混排会挤掉指南条目位次，因此只在主库结果之后追加（`literature_top_k=2`，相似度下限 0.75）。

**失败与降级**：

- 检索异常 → `{"type":"error"}` 帧（`qa_service.py` L741），前端显示错误条。
- 检索结果为空 → 固定话术"未找到相关的循证推荐条目…"（L745），不做无依据生成。
- reranker 加载失败 → 就绪探针仍为 ready，仅降级为不精排（`main.py` 的就绪判定）。
- LLM 异常 → 错误帧；思考模式默认关闭，防止 `max_tokens` 被 reasoning 占满导致空回答。

### 2. 语义缓存三层与降级

**解决什么问题**：同一问题或轻度改写反复出现时，跳过"检索 + 精排 + 生成"整条链路；同时不能把语义不同的问题判成同一个（癌种、分期、线数、否定词不同即为不同问题）。

**实现路径**（`utils/semantic_cache.py`）：

1. **L0 精确键**（L598）：问题做繁简归一 + 空白压缩后取哈希，拼接 `scope`（`cancer_type`/`scenario`/`stage`/`top_k`）作为 Redis key；命中直接返回，相似度记为 1.0。
2. **L1 余弦**（L613）：对问题编码 bge-m3 向量，与该 scope 下的条目矩阵做点积，取最大者；低于 `semantic_cache_threshold=0.95` 直接判未命中。
3. **L2 实体槽位守卫**（L646）：`extract_slots()` 抽取癌种、分期、线数、拉丁术语、数字、否定词；`slot_conflict()` 发现任一槽位冲突即否决，即使余弦过阈值也不算命中。
4. 阈值来源：2026-11-04 用 26 正 / 43 负 / 16 探针标定，负样本余弦上界 0.9187，取 0.95 留 0.031 余量（`data/cache/calib_report.json`、`core/config.py` L176–L179）。用户于 2026-11-05 决定维持 0.95。
5. 写入：`store()` 按 `semantic_cache_max_entries=300` 截断，普通条目 TTL 7 天、人工预热条目（`seeded`）30 天，索引版本随 `doc_catalog.json` mtime 失效。

**技术栈**：Redis 7（AOF everysec、maxmemory 128MB、allkeys-lru）+ numpy 点积；不使用 Redis 向量模块。

**关键设计取舍**：

- 纯阈值不可行：标定中发现"良性改写 0.9397"与"危险近似 0.9257"区间重叠，单靠余弦必然误合并，因此加 L2 结构化守卫，阈值只做廉价初筛。
- 不做向量索引（RediSearch/HNSW）：条目上限 300，矩阵一次加载后点积耗时在毫秒级，引入向量索引只会增加部署依赖。

**失败与降级**：

- Redis 连接失败或超时（`redis_timeout=0.8s`）→ `_get_client()` 返回 None，`lookup` 返回未命中（L583），问答与检索不受阻塞。
- 语义层失效后仍有进程内精确缓存：`utils/search_cache.py` 的 `SearchResultCache`（OrderedDict，上限 500 条，按 `doc_catalog.json` mtime 版本整体失效）。
- 写入失败只记录日志，不影响本次回答返回。

### 3. 流式问答（SSE）

**解决什么问题**：检索与生成耗时在秒级，若一次性返回，前端十几秒白屏；同时要让用户尽早看到"正在检索"和来源。

**实现路径**：

1. `qa.py` L26/L63 接受问题与过滤条件，L52 用 `StreamingResponse` 返回 `text/event-stream`。
2. `_ask_stream_legacy` 第一件事就是 `yield {"type":"status","stage":"retrieve"}`（`qa_service.py` L723），在检索之前推送，这就是首帧。
3. 帧序列：`status(retrieve)` → `sources`（L769，含来源与证据等级）→ `status(generate)`（L771）→ 多个 `content` 增量（L780）→ `end`（L797，含各阶段耗时）。
4. 缓存命中路径不重新生成，按原答案重放并附带 `similarity`（L604）。
5. nginx 侧关闭缓冲：`proxy_buffering off`、`proxy_read_timeout 120s`（`frontend/nginx.conf`）。

**技术栈**：FastAPI `StreamingResponse` + SSE 文本协议；未使用 WebSocket。

**关键设计取舍**：

- 选 SSE 而非 WebSocket：问答是单向服务端推送，SSE 走普通 HTTP、可复用现有 nginx 与鉴权，WebSocket 需要额外的升级配置与心跳管理。
- 首帧必须是状态帧：评测口径的"首帧"即此帧，实测中位 256.1 ms、最大 1,047.9 ms（含首题冷启动），与总时长 9,347.1 ms 分开统计（`eval_sets/results/qa_med_40_20261102_214803.json`）。
- 来源帧先于生成帧：引用先到，前端可以先渲染证据卡片，模型输出逐字追加。

**失败与降级**：

- 客户端断开 → 生成器停止迭代，不写缓存。
- 生成中途异常 → 已推送的 `content` 保留，末尾补错误帧，前端保留半成品并标红。
- 思考模式会产生 `reasoning_content` 并占用 `max_tokens`，默认 `MEDICAL_LLM_ENABLE_THINKING=false`。

### 4. 疾病档案（专业版 / 患者版）

**解决什么问题**：同一份疾病知识要同时服务医生（分期、分子分型、治疗线数）与患者（白话解释），且两者不能维护成两份会漂移的文档。

**实现路径**：

1. 详情入口 `GET /api/v1/diseases/{disease_id}`（`api/v1/diseases.py`），`DiseaseService.get()`（`services/disease_service.py` L178）按 `version=professional|patient` 选择输出。
2. 同一份 JSON 内并存两套文本：专业版取 `sections`，患者版取 `patient_version.sections`（L184）；章节顺序由 `SECTION_ORDER` 固定（L188）。
3. 结构化节转写：`structured_section_to_text()`（L193，定义 L56–L86）把 `list[dict]`、`{"items": [...]}`、纯字符串统一转成可读文本，支持 `name`、`description`、`icdo3` 等键。
4. 来源对照：每节返回 `sources` 与 `section_gaps`（L215–L216），缺失章节显式列出，不静默省略；患者版附免责声明（L217）。
5. 列表与检索：10 份档案另建 `medical_disease_profiles` 索引（可检索抽平层，存储层 `enabled:false`），供检索与问答引用。

**技术栈**：ES 8.11.0（档案独立索引）、Python dict 转写、无额外模板引擎。

**关键设计取舍**：

- 一套文档双口径，而不是两套文档：避免专业版更新后患者版过期；代价是 JSON 体积翻倍。
- 结构化节保留 JSON、读取时再转文本：前端可直接渲染表格/条目，改文案规则不需要重灌索引。
- 档案单独索引而不是塞进主索引：档案是"整篇文档"语义，混入主索引会与推荐条目争抢位次。

**失败与降级**：

- 章节为未知结构 → 返回"该章节为结构化内容，暂不支持文本展示"（`_STRUCTURED_UNSUPPORTED`），不做 `repr()` 硬转。
- `version` 非法 → 按专业版返回。
- 档案不存在 → 404；档案索引缺失时列表页为空，不影响主检索。

### 5. 药品详情（结构化 + 白话两段式）

**解决什么问题**：说明书原文是给专业人员看的，患者端需要"能读懂"的版本；但白话文本生成要花钱，不能每次请求都调用 LLM。

**实现路径**：

1. 结构化详情 `GET /api/v1/patient/drug/{drug_id}` → `PatientService.get_drug_patient()`（`services/patient_service.py` L96），零 LLM 调用，返回适应证、用法用量、不良反应、相互作用原文、`aliases_zh` 别名与 `boxed_warning`（黑框警示，从说明书字段派生，缺失时不伪造）。
2. 白话两段式 `GET /api/v1/patient/drug/{drug_id}/plain` → `get_drug_plain()`（L130），三级回填：
   - 一级：ES 文档已存 `patient_plain` 字段，直接返回（`cached=true`）；
   - 二级：`data/clean/drug_labels/DRUG-*.json` 有本地白话，回填 ES 后返回（零 LLM）；
   - 三级：调用 LLM 生成（温度 0.3、要求不新增原文没有的信息），成功后先备份原文件、再 partial update ES 与写回 clean JSON（L176–L206）。
3. 别名透传：`list_drugs()` 的检索同时匹配 `drug_name` 与 `aliases_zh`（L65–L69），详情原样返回别名，前端可显示"通用名/商品名"。

**技术栈**：ES `medical_knowledge`（`data_type=drug`）、DeepSeek `deepseek-flash`、JSON 文件回写 + 备份。

**关键设计取舍**：

- 白话不放在检索链路里：问答需要的是原文证据，白话只服务患者浏览，避免改写文本污染引用。
- 三级回填而不是只靠缓存：重灌 ES 后缓存会丢，本地 JSON 是持久层，保证不重复付费生成。
- 黑框警示不翻译成白话：这是最高风险信息，保留原文并单独高亮，避免改写损失。

**失败与降级**：

- LLM 失败或返回非 JSON → `{"plain": null, "cached": false}`，前端回落到结构化详情。
- 写回 ES 或本地失败 → 仅告警，本次仍返回生成结果。
- 药品不存在 → 404；`aliases_zh` 为空时列表按通用名匹配。

### 6. 报告解析

**解决什么问题**：患者拿到的是自由文本报告，系统需要抽出部位、大小、密度、边界、淋巴结五个字段，供随访与档案引用。

**实现路径**：

1. 入口 `api/v1/report.py`，服务 `services/report_parse_service.py` 的 `parse()`（L50）：先做空白归一与长度控制，再走 LLM 结构化抽取。
2. LLM 抽取 `_llm_extract()`（L84）：按 `FINDING_FIELDS`（L24–L30，5 个字段）要求返回严格 JSON，提示词明确"原文没有的字段返回 null，不得编造"。
3. 规则兜底 `_rule_extract()`（L116）：按关键词与正则匹配，尺寸用 `_SIZE_RE`（L35，支持 `12mm`、`1.2cm`、`8*6mm`）。
4. 输出包含 `findings`、`impression`、`followup_suggestions`、`diff_prev`（同一患者上一次解析结果对比，进程内字典）与 `disclaimer`（L32）。

**技术栈**：DeepSeek `deepseek-flash` + 正则；无 OCR、无影像模型。

**关键设计取舍**：

- 双通道（LLM + 规则）：LLM 对自由文本更稳，但会宕机或超时；规则通道保证最低可用。
- 只抽 5 个字段：字段越多，LLM 编造概率越高；宁少不滥。
- `diff_prev` 放进程内：报告解析是低频操作，为它建库不划算；代价是重启丢历史。

**失败与降级**：

- LLM 失败 → 自动切规则抽取，返回体带 `degraded=true`，前端提示"已降级为规则解析"。
- 文本过短或无关键字段 → 字段为 null，不猜。
- 仅支持文本粘贴/文本文件；PDF 扫描件与影像不在支持范围（未做 OCR，未核实任何影像能力）。
- 不输出诊断结论，不替代医生；免责声明随每次响应返回。

### 7. 移动端

**解决什么问题**：让患者在手机上看疾病、药品、随访，而不另建一套后端。

**实现路径**：

1. Taro 4.1.9 + React 18 + TypeScript 工程 `miniapp/`，`npm run build:h5` 产出静态站点 `miniapp/dist`（实测约 3.44MB）。
2. `docker-compose.yml` 把 `./miniapp/dist` 只读挂载到 `medical-frontend` 容器的 `/usr/share/nginx/h5`，由 `docker/h5.conf` 的独立 `server` 块监听容器 8080、宿主 3100。
3. 鉴权：容器启动时执行 `/docker-entrypoint.d/40-h5-htpasswd.sh`（`docker/h5-htpasswd.sh`），用 `MEDICAL_H5_AUTH_USER/PASS` 生成 `.htpasswd`（SHA 格式）；`h5.conf` 对该站点启用 `auth_basic`。缺 `MEDICAL_H5_AUTH_PASS` 时脚本主动退出 → 容器不启动（fail-closed，L8–L11）。
4. `/api/` 反代到同一 `medical-backend:8001`（`h5.conf` L22–L23），移动端与 PC 共用全部接口，无独立业务后端。
5. PC 端 3001 由 `frontend/nginx.conf` 提供，同样反代同一后端。

**技术栈**：Taro 4.1.9（H5 目标）、React 18、nginx:alpine、htpasswd（SHA）。

**关键设计取舍**：

- 用 nginx 托管静态产物，而不是再起一个 Node 服务：构建产物是纯静态，多一个容器只增加内存与运维面。
- Basic Auth 放在预览层：比赛演示需要低门槛访问控制，不引入账号体系；它不替代业务鉴权，管理接口仍用 Bearer Token。
- 与 PC 共用后端：接口契约一致，避免两套逻辑分叉。

**失败与降级**：

- 未设置 H5 密码 → 容器启动失败并在日志中明确报错（不会以无鉴权状态裸奔）。
- `dist` 缺失 → 站点目录为空，访问返回 404；需先构建再启动。
- 401 → 浏览器 Basic Auth 弹窗；改密码后需重启 `medical-frontend` 才重新生成 `.htpasswd`。

### 8. 数据入库

**解决什么问题**：把异构的 XML/JSON 清洗成统一文档，按类型路由到 5 个 `data_type`，并在脏数据存在时保证可重复执行、不中断整批。

**实现路径**（`medical_rag/ingest.py`）：

1. 目录路由：`_ES_ROUTED_DIRS`（L31–L37）定义 5 个入库目录（guidelines / recommendations / drug_labels / terminology / literature）；`_DEFERRED_DIRS`（L50）为档案与图谱，由 `medical_rag/scripts/data_pipeline/` 下独立脚本写入；其余为文件态（L56）。
2. 单文件处理 `process_json_file()`（L160）：非 dict 跳过（L179）；无 `id` 跳过（L184）；`duplicate_of` 标记的重复项跳过（L188）；`doc_id` 与目录前缀不一致只告警仍入库（L191）；已存在且未 `--force` 则跳过（L194）。
3. 向量化与写入：`repo.add_documents()`（`repositories/elasticsearch.py` L775）先 `_embed_texts()` 用 bge-m3 编码（批量 32，`entity_align_batch_size` 同类参数），再用 bulk 写入；单文件失败收集到 `failed_docs`，不中断批次。
4. 批次控制：`--batch-size` 默认 32（L436），`--rebuild` 先删索引再建，`--force` 覆盖已有文档；每批输出统计与失败清单。

**技术栈**：Python 3.10、Elasticsearch 8.11 bulk API、bge-m3（CPU）、JSON/XML 解析。

**关键设计取舍**：

- 以 `id` 为幂等键：重复执行不产生重复文档，避免"重灌一次多一倍"。
- 脏数据隔离到文档级：一条坏数据只进失败清单，不拖垮整批；但前缀不一致只告警，属有意放宽（清洗阶段已做前缀纠正）。
- 5 类路由而非单一索引：不同类型字段与检索权重不同（推荐条目要按癌种/分期过滤，文献只要全文）。

**失败与降级**：

- ES 不可达 → 入库中止并报错，已有文档不受影响（bulk 分批提交）。
- 单条向量化失败 → 进入失败清单，其余继续。
- 未识别目录 → 跳过并打印提示（`recommendations_breast_staging`、`recommendations_new4_staging` 两个 staging 目录即属此类）。

## 目录结构

```
.
├── medical_rag/      后端源码与数据（容器内挂载为 /app）
│   ├── api/          路由层，16 个 v1 模块
│   ├── core/         配置、领域枚举、模型单例
│   ├── services/     检索、问答、精排、图谱、随访等业务服务
│   ├── repositories/ ES 访问层
│   ├── eval_data/    评测脚本与 results/ 批次产物
│   └── data/         clean/ 清洗数据、raw/ 原始 XML、索引资产
├── frontend/         原生 JS SPA，nginx 托管（3001）
├── miniapp/          Taro 移动端工程，dist/ 为 H5 构建产物
├── docker/           镜像定义（Dockerfile、Dockerfile.es）、h5.conf、h5-htpasswd.sh、IK 插件包
├── scripts/          启动脚本 dev_up.ps1 / dev_down.ps1、模型下载 fetch_models.ps1
├── models/           本地模型目录（不入库，4.28GB；下载方式见 models/README.md）
└── docker-compose.yml 四服务编排
```

## 快速开始

### 前置条件

| 项目 | 要求 | 依据 |
|---|---|---|
| Docker | Docker Desktop，支持 `docker compose` v2 | `docker-compose.yml` |
| 内存 | 建议 ≥10GB 可用；backend 容器 `mem_limit: 10g`、`mem_reservation: 3g` | `docker-compose.yml` L71–L72 |
| 磁盘 | 模型 4.28GB + 两个镜像 + ES 数据卷 | `models/` 实测 2.14GB + 2.14GB（不含 `onnx/`） |
| 模型文件 | `models/bge-m3`、`models/bge-reranker-v2-m3`，只读挂载到容器 `/models` | `docker-compose.yml` L117–L118 |
| 密钥 | DeepSeek API Key（问答与生成需要；仅检索不需要） | `.env.example` L7–L10 |

缺少模型目录时 backend 无法就绪（`/health/ready` 持续 503）；缺少 `MEDICAL_H5_AUTH_PASS` 时 frontend 容器直接启动失败（fail-closed，依据：`docker/h5-htpasswd.sh`）。

### 配置并启动

```powershell
# 1. 首次使用先下载模型（约 4.28GB；国内网络加 -Mirror 走镜像）
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_models.ps1

# 2. 复制模板并填写（至少填 4 个密钥项 + 1 个 H5 密码）
copy .env.example .env

# 3. 中文路径下首次构建镜像需关闭 BuildKit，否则报非 ASCII 路径错误
$env:DOCKER_BUILDKIT=0

# 4. 启动（首次会构建 medical-rag-es 与 medical-rag-backend 镜像）
docker compose up -d

# 5. 查看状态，四个服务都应进入 Up
docker compose ps
```

首次冷启动实测约 57.6s 完成模型加载与推理预热（依据：`medical_rag/main.py` 启动流程注释）；`elasticsearch` 健康检查 `start_period` 为 30s，`backend` 为 180s（依据：`docker-compose.yml` L29、L149）。

### 判定就绪

```powershell
curl.exe http://localhost:8002/health
# {"status":"healthy","service":"medical-rag"}

curl.exe http://localhost:8002/health/ready
# 就绪：{"status":"ready","service":"medical-rag","models":{"reranker":"loaded","embedding":"loaded"},"warmup":"done"}
# 预热中：HTTP 503，body 为 {"status":"warming_up", ...}
```

`/health` 只表示进程存活；能否高效服务以 `/health/ready` 为准（判定逻辑见 `medical_rag/main.py`：`warmup_done` 且 embedding 为 `loaded`）。reranker 为 `failed` 时仍算就绪，只是降级为不精排。

### 停止与清空

```powershell
docker compose stop     # 停止容器，保留容器与数据卷
docker compose down     # 删除容器，保留命名卷 medical_es_data / medical_redis_data
docker compose down -v  # 连数据卷一起删除（ES 索引与 Redis 语义缓存会被清空）
```

### 入库与移动端构建

```powershell
# 重新入库（读 /app/data/clean，写入 ES）
docker compose exec backend python ingest.py

# 移动端 H5：构建后由 frontend 容器的 3100 端口提供
cd miniapp
npm install
npm run build:h5
```

`miniapp/dist` 实测约 3.44MB；compose 把它只读挂载到前端容器 `/usr/share/nginx/h5`（依据：`docker-compose.yml` L175）。

## 端口与访问

| 服务 | 宿主端口 | 容器端口 | 访问地址 | 鉴权方式 |
|---|---:|---:|---|---|
| Web 前端（SPA + `/api/` 反代） | 3001 | 80 | http://localhost:3001 | 无 |
| 移动端 H5 | 3100 | 8080 | http://localhost:3100 | HTTP Basic Auth（`MEDICAL_H5_AUTH_USER` / `MEDICAL_H5_AUTH_PASS`） |
| 后端 API | 8002 | 8001 | http://localhost:8002/api/v1 | 除 `/api/v1/admin/*` 外无鉴权；管理接口用 `Authorization: Bearer <MEDICAL_ADMIN_TOKEN>` |
| 接口文档 | 8002 | 8001 | http://localhost:8002/docs | 无 |
| Elasticsearch | 9201 | 9200 | http://localhost:9201 | 无（`xpack.security.enabled=false`） |
| Redis | 6380 | 6379 | 127.0.0.1:6380 | 无 |

依据：`docker-compose.yml` L21、L59、L75、L163、L165；`frontend/nginx.conf`；`docker/h5.conf`；`medical_rag/api/v1/admin.py`。

## 配置项

变量统一由 `MEDICAL_` 前缀读取，来源为 `.env` 或进程环境（`medical_rag/core/config.py` L232–L236）。下表仅列实际生效项。

| 变量 | 必填 | 默认值 | 作用 | 依据 |
|---|---|---|---|---|
| `MEDICAL_LLM_API_KEY` | 是 | 空 | 问答与生成调用 DeepSeek | `.env.example` L7 |
| `MEDICAL_DEEPSEEK_API_KEY` | 是 | 空 | 摘要、抽取等独立客户端 | `.env.example` L8 |
| `MEDICAL_ES_PASSWORD` | 是（compose 占位） | 无 | 注入 backend；当前 ES 关闭鉴权，值不被校验 | `.env.example` L9、`docker-compose.yml` L17 |
| `MEDICAL_ADMIN_TOKEN` | 是 | `dev_admin_token_change_me` | `/api/v1/admin/*` 的 Bearer Token | `config.py`、`docker-compose.yml` L92 |
| `MEDICAL_MODELS_DIR` | 否 | `./models` | 模型父目录，挂载到容器 `/models` | `.env.example` L14 |
| `MEDICAL_REDIS_URL` | 否 | `redis://redis:6379/0` | 语义缓存连接串 | `.env.example` L17 |
| `MEDICAL_SEMANTIC_CACHE_ENABLED` | 否 | `true` | 语义缓存总开关 | `.env.example` L20 |
| `MEDICAL_RAG_CHAIN_ENABLED` | 否 | `true` | `false` 时回退手写检索链路 | `.env.example` L21 |
| `MEDICAL_TORCH_NUM_THREADS` | 否 | `8` | CPU 推理线程数 | `.env.example` L27 |
| `MEDICAL_RERANKER_BATCH_SIZE` | 否 | `8` | 精排批大小 | `.env.example` L28 |
| `MEDICAL_RERANKER_WINDOW` | 否 | `20` | 两阶段精排窗口 | `.env.example` L29 |
| `MEDICAL_ENTITY_ALIGN_THRESHOLD` | 否 | `0.95` | 实体消歧向量对齐阈值 | `.env.example` L26 |
| `MEDICAL_ENTITY_ALIGN_ENABLED` / `..._INTRA_BATCH` | 否 | `true` / `true` | 向量对齐开关、批内两两比对 | `.env.example` L22–L23 |
| `MEDICAL_H5_AUTH_USER` | 否 | `h5` | 移动端 Basic Auth 用户名 | `docker-compose.yml` L169 |
| `MEDICAL_H5_AUTH_PASS` | 是 | 无 | 移动端 Basic Auth 密码，缺失则容器启动失败 | `docker-compose.yml` L170 |
| `MEDICAL_SEMANTIC_CACHE_THRESHOLD` | 否 | `0.95`（仅代码默认） | 缓存余弦阈值；compose 刻意不注入，改值需改 `core/config.py` | `config.py` L179、`docker-compose.yml` L83–L85 |

其余阈值（`reranker_top_k=20`、`literature_min_similarity=0.75`、`search_cache_max_entries=500`、`semantic_cache_ttl=7 天` 等）只存在于 `medical_rag/core/config.py`，不通过环境变量覆盖。

## 数据说明

### 主索引 `medical_knowledge`（5 类 `data_type`）

| `data_type` | 条数 | 内容 | 来源 |
|---|---:|---|---|
| `literature` | 2,076 | 英文文献摘要与要点 | PubMed / IMMUNOTARGET（`data/clean/literature/lit_pubmed_subset.json`） |
| `rec` | 1,863 | 推荐条目，检索主单元 | 9 份 Europe PMC 开放获取文献（CC BY 4.0）+ 1 份国家卫健委公开文件（`DOC-LUNG-NHC-001`） |
| `term` | 377 | 术语与分期映射 | 项目整理（数据内未标注来源字段） |
| `drug` | 44 | 药品说明书条目 | FDA DailyMed 标签库 |
| `doc` | 10 | 指南文档 | 同 `rec` 来源，12 份文件中入 ES 10 份 |
| **合计** | **4,370** | | `curl http://localhost:9201/medical_knowledge/_count` |

`rec` 分癌种：colorectal 1,112 / lung 546 / breast 173 / gastric 32（依据：`cancer_type` 聚合，合计 1,863）。

上表是**本地完整库**的统计。公开仓库为规避二次分发风险，不包含 `data/clean/literature/`（PubMed 摘要版权可能归各出版商），克隆后 `literature` 层为 0 条、主索引为 2,294 条，问答主链路自动跳过文献补充（`MEDICAL_LITERATURE_FALLBACK_ENABLED`，默认开启但无数据即跳过），指南与推荐条目不受影响。

### 其他索引

| 索引 | 条数 | 说明 |
|---|---:|---|
| `medical_disease_profiles` | 10 | 疾病档案，通俗版与专业版两套文本 |
| `medical_kg_triples` | 283 | 知识图谱三元组 |
| `medical_kg_entities` | 86 | 图谱实体词典 |
| `medical_analysis_cache` | 11 | 专题 / 对照分析结果缓存 |

10 份档案按癌种：结直肠 6、肺 2、乳腺 1、胃 1（依据：`data/clean/disease_profiles/*.json`）。

### 审核状态（须与「已知限制」一并阅读）

| 类别 | 磁盘文件 | ES 收录 | 已审核（approved） | 未审核（draft） |
|---|---:|---:|---:|---:|
| 指南 | 12 | 10 | 6 | 6（其中 `DOC-BREAST-EPMC-004`、`-005` 未入 ES） |
| 药品说明书 | 47 | 44 | 5 | 42 |
| 文献 | 2,076（单文件） | 2,076 | 0 | 2,076 |
| 疾病档案 | 10 | 10 | 10 | 0（已人工逐节审校，质量标杆） |

`draft` 的含义是：自动抽取、机器校验通过、未逐条人工复核；`approved` 表示完成内部字段核对，不等同临床专家复核。10 份疾病档案是当前唯一完成人工逐节审校的数据，因此作为质量标杆单列。

依据：`data/clean/guidelines/*.json` 的 `review_status`、`drug_labels/DRUG-*.json`、ES `review_status` 聚合。`drug_labels` 目录共 48 个 JSON，其中 1 个为 `drug_catalog.json`，说明书为 47 份。

药品说明书的**原文（整篇 label 文本）不随交付包分发，仅存于本地检索库**；入库与对外交付的都是可独立成立的派生字段（适应证、禁忌、用法用量、黑框警示、批准文号、通用名与中文别名）。依据：`drug_labels/DRUG-*.json` 不含整篇原文，仅含上述结构化字段（实测键集合无 `label_text`）。

`data/clean` 下共 14 个业务目录，全部参与入库或业务读取；历史备份/快照目录已清理。

### 不入 ES 的数据及原因

`ingest.py` 只把 5 个目录写入 ES（`guidelines`/`recommendations`/`drug_labels`/`terminology`/`literature`，依据 `medical_rag/ingest.py` L31–L37）。其余目录分两类：

| 目录 | 处理 |
|---|---|
| `disease_profiles/`、`kg_triples/` | 由独立写入链路同步到 ES（本路径不在 `ingest.py` 的 5 类路由中） |
| `triage_rules/`、`preconsult_slots/`、`followup_templates/`、`patient_messages/`、`eval_sets/`、`recommendations_breast_staging/`、`recommendations_new4_staging/` | 文件态直读，不建索引 |

文件态目录均为规则、模板、会话与评测数据，只被对应模块按需读取，不参与全文检索，因此不入 ES。

## 评测与指标

### 问答（SSE 流式，40 题）

批次 `qa_med_40_20261102_214803`，产物 `medical_rag/data/clean/eval_sets/results/qa_med_40_20261102_214803.json`；`failed_items=0`，`judge_tokens_total=126,829`。

| 指标 | n | 口径 | 结果 |
|---|---:|---|---|
| 首帧延迟 | 40 | 请求到首个 SSE 分片，含首题冷启动 | 中位 256.1 ms，最大 1,047.9 ms |
| 总响应时长 | 40 | 请求到流结束 | 中位 9,347.1 ms，最大 11,439.7 ms |
| 答案正确率 | 20 | 可答题，人工提示词判定 | 80.0%（16/20） |
| 引用正确率 | 20 | 引用能支撑结论 | 55.0%（11/20） |
| 无幻觉率 | 40 | 全部题目 | 62.5%（25/40） |
| 应拒答正确率 | 20 | 证据不足题应拒答 | 85.0%（17/20） |
| 不应拒答正确率 | 20 | 可答题不应拒答 | 100%（20/20） |

### 检索（115 题）

同一评测集 `data/clean/eval_sets/eval_retrieval.json`，top_k=20，两个时点各自独立成批，不可合并。

| 指标 | n | 2026-10-25（四策略） | 2026-10-27（管道重跑） |
|---|---:|---|---|
| BM25 Recall@5 | 115 | 0.2551 | — |
| 仅向量 Recall@5 | 115 | 0.9493 | — |
| 混合（BM25+向量+RRF）Recall@5 | 115 | 0.9913 | — |
| 混合+重排 Recall@5 / Recall@10 | 115 | 0.9913 / 0.9913 | 0.9913 / 0.9913 |
| MRR | 115 | 0.2399 / 0.8717 / 0.8732 / 0.9341 | 0.9341 |
| NDCG@10 | 115 | 0.2332 / 0.8663 / 0.8942 / 0.9307 | 0.9306 |
| Top-1 准确率 | 115 | 0.2870 / 0.9739 / 1.0 / 1.0 | 1.0 |

产物：`medical_rag/eval_data/results/20261025_144553/four_strategies_summary.json`、`.../20261027_103221/eval_pipeline_summary.json`。

### 语义缓存阈值标定（0 token）

`medical_rag/data/cache/calib_report.json`，生成时间 2026-11-04 07:29:56，样本 26 正 / 43 负 / 16 探针。

| 阈值 τ | 召回率 | 误合并例数 | 采纳 |
|---:|---:|---:|---|
| 0.80 | 0.9231 | 6 | 否 |
| 0.88 | 0.6923 | 2 | 否（旧值，已废弃） |
| 0.92 | 0.5769 | 0 | 未采纳（仅记录） |
| 0.95 | 0.3462 | 0 | 采用 |

负样本余弦上界 0.9187（`intent_negative` 类），阈值 0.95 留余量 0.031（依据：`calib_report.json` 的 `distribution.intent_negative.max`、`core/config.py` L176–L179）。取舍是牺牲缓存命中率换零误合并。

评测脚本共 7 个：`run_eval_pipeline.py`、`run_enhanced_eval.py`、`run_four_strategies.py`、`run_reranker_eval.py`、`run_qa_eval.py`、`run_refusal_eval.py`、`generate_4charts.py`。

## 已知限制

1. **数据未经终审**：文献 2,076 条全部 draft；指南 12 份中 6 份 approved；药品 47 份中 5 份 approved。approved 仅表示完成内部字段核对，不等同临床专家复核。
2. **癌种覆盖不全**：仅 4 个癌种有指南与疾病档案数据；甲状腺癌仅有 2 条药品说明书、无档案与指南，肝癌无任何条目。
3. **数据量小**：1,863 条推荐条目来自 9 份 Europe PMC 文献与 1 份卫健委文件，不是完整指南库；未收录 NCCN、CSCO 原文。
4. **引用正确率偏低**：55.0%（11/20），说明引用与结论的对应关系尚不稳定。
5. **缓存召回低**：τ=0.95 时标定集召回 0.3462，改写幅度较大的问法基本不吃缓存。
6. **算力约束**：CPU 推理，精排约占检索延迟 93%，backend 单进程、并发信号量上限 2、`mem_limit: 10g`。
7. **未做横向竞品对照**：没有与其他开源或商业 RAG 系统在同一数据集、同一口径下的对比。
8. **未做临床验证**：无医生双盲标注、无外部测试集、无多中心数据。
9. **鉴权不完整**：ES、Redis、后端业务接口均无鉴权，仅移动端入口有 Basic Auth；只适合本地或内网演示。
10. **遗留接口**：`/mapping/*`、`/structured/*` 已挂载但前端无消费者，属历史遗留。
11. **评估规模有限**：检索 n=115、问答 n=40、缓存标定 n=69，样本量不足以支撑强结论。

## 常见问题

| 现象 | 排查与处理 |
|---|---|
| 端口被占用（3001 / 3100 / 8002 / 9201 / 6380） | `netstat -ano \| findstr :3001` 查 PID；或改 `docker-compose.yml` 的宿主端口后 `docker compose up -d` |
| `docker compose up` 构建失败，报非 ASCII 路径 | 中文目录下先执行 `$env:DOCKER_BUILDKIT=0` 再构建 |
| frontend 容器反复重启 | 检查 `.env` 是否设置 `MEDICAL_H5_AUTH_PASS`；缺失时 `docker/h5-htpasswd.sh` 主动失败 |
| 移动端访问 3100 返回 401 | 3100 启用 Basic Auth，用 `MEDICAL_H5_AUTH_USER` / `MEDICAL_H5_AUTH_PASS` 登录；密码改动后需重启 frontend 容器 |
| `/health/ready` 持续 503 | 看 body 中 `models` 字段：`embedding` 非 `loaded` 多为 `models/` 缺失或路径错误；冷启动需约 60s |
| Elasticsearch 内存不足或频繁重启 | `ES_JAVA_OPTS=-Xms1g -Xmx1g` 固定为 1GB；宿主机可用内存不足 10GB 时先降低 backend 负载再启动全套服务 |
| 改了前端 JS 但页面无变化 | nginx 对静态资源发 `Cache-Control: no-cache`，浏览器需硬刷新（Ctrl+F5） |
| 问答返回空内容 | 思考模式默认关闭；如手动开启 `MEDICAL_LLM_ENABLE_THINKING=true`，思考会挤占 `max_tokens` |
| Redis 连不上 | 后端自动降级到进程内精确缓存，检索与问答不受影响；检查容器 6380 与 `MEDICAL_REDIS_URL` |

依据：`docker-compose.yml`、`frontend/nginx.conf`、`docker/h5-htpasswd.sh`、`medical_rag/main.py`、`medical_rag/core/config.py`。

## 许可与第三方合规

外部事实查阅日期：2026-11-05。

| 对象 | 许可 / 版权状态 | 出处 |
|---|---|---|
| bge-m3 | MIT | Hugging Face 模型卡 `BAAI/bge-m3`（License: mit） |
| bge-reranker-v2-m3 | Apache-2.0 | Hugging Face 模型卡 `BAAI/bge-reranker-v2-m3` |
| Elasticsearch 8.11.0 镜像 | Elastic License 2.0 / SSPL 双许可 | 未逐条核实再分发条款 |
| Europe PMC 指南文献 | CC BY 4.0，需署名并标注改动 | 各文档 `license_note` 字段；`https://creativecommons.org/licenses/by/4.0/` |
| 国家卫健委公开文件 | 本地标注“公开可引用、仅限非商业竞赛使用” | 文档 `license_note`；官方再分发条款未核实 |
| FDA 药品说明书（DailyMed） | NLM 公开服务；美国政府作品在美国不受版权保护，需致谢 NLM | `https://www.nlm.nih.gov/web_policies.html` |
| PubMed 摘要 | NLM 不主张摘要版权，但期刊或作者可能仍持有版权 | `https://www.ncbi.nlm.nih.gov/home/about/policies.shtml`（逐条授权未核实） |
| NCCN 指南 | 版权归 NCCN；复制、转让、再现、修改或创作衍生作品需书面许可 | `https://www.nccn.org/guidelines/permission-to-cite-or-use-nccn-content` |
| CSCO 指南 | CSCO 声明从未授权任何个人及机构发布电子版 | `https://www.csco.org.cn/cn/ncontent.aspx?oid=8744` |

本仓库未收录 NCCN、CSCO、ESMO、ASCO 指南原文，因此不涉及随代码分发其正文；若后续加入，须先取得书面许可。

医疗免责：所有面向用户的生成内容仅基于检索到的条目，强制携带来源与证据等级，不构成诊疗建议；患者端页面固定展示免责声明，不给诊断结论与处方；报告解析只做文本结构化，不做影像判读；严禁写入真实患者个人信息。

## 更新记录

| 日期 | 变更 | 依据 |
|---|---|---|
| 2026-11-05 | 交付版 README 重写，新增「技术实现详解」一章（8 项功能），数字按 ES 与配置文件现场核实 | 本文件 |
| 2026-11-04 | 语义缓存阈值 0.88 → 0.95（26 正 / 43 负标定）；`data/clean` 挂载改为可写，患者白话文本回写药品文件 | `core/config.py`、`docker-compose.yml` |
| 2026-11-03 | 移动端 H5 并入 frontend 容器（宿主 3100 → 容器 8080），停用 `scripts/h5_preview.py` | `docker/h5-htpasswd.sh`、`scripts/dev_up.ps1` 注释 |
| 2026-11-02 | 完成 40 题流式问答评测批次 | `eval_sets/results/qa_med_40_20261102_214803.json` |
| 2026-10-30 | 多跳推理整体弃用，相关配置保留为 `False` | `medical_rag/core/config.py` 多跳段落 |
| 2026-10-25 | 引入文献证据层（2,076 条）；四策略检索评测 n=115 | `data/clean/literature/lit_pubmed_subset.json`、`eval_data/results/20261025_144553` |

## 团队

队名：谁占用了我们的队名。成员名单与分工未在仓库内留存，未核实。
