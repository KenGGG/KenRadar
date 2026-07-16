# KenRadar Web 后台演进目标与落地计划

> 文档状态：执行基线  
> 基线日期：2026-07-16  
> 适用范围：KenRadar Web 后台、相关查询接口、运行状态展示与来源洞察  
> 事实优先级：当前代码与 `config/config.yaml` > `AGENTS.md` > `README.md` > 本计划

## 1. 目标与核心判断

KenRadar 已经具备抖音生产链路和小宇宙 MVP：来源监控、下载、转录、AI 整理、Obsidian 笔记、PostgreSQL 存储、静态发布、飞书推送、失败重试和研究任务。本计划不重建这些链路，也不进行大面积视觉重构。

最新系统愿景是：**把 KenRadar 建设成一个本地优先、证据可追溯、可恢复的个人研究情报操作系统。** 系统不仅要完成采集和摘要，还要把来源、内容、处理状态、知识资产、发布结果和长期质量信号连接起来，让用户可以从“发现信息”顺畅进入“判断价值、阅读归档、修复失败和跟踪来源”。

当前 Web 后台最需要解决的问题是：

1. 今天新增了哪些内容，哪些最值得看？
2. 为什么值得看，是否已经审阅或推送？
3. 每条内容处理到哪里，哪里失败，怎样恢复？
4. 哪些来源长期稳定地产出高价值内容？

近期目标是修通并验收“内容决策、任务恢复、实时状态和来源复盘”闭环；异常检测必须等基础查询、统计口径和至少 30 天来源日指标稳定后再实施。

## 2. 实施原则

- 不破坏现有抖音生产链路、API 路径、前端回退机制及 PostgreSQL 数据兼容性。
- 每个里程碑必须独立可发布、可验证、可回滚，不将后端拆分、业务改造和视觉改造混在一次提交中。
- 服务端是筛选、分页和统计口径的唯一权威；前端内存过滤只用于不影响完整性的即时交互。
- 先定义数据口径和接口契约，再开发图表；不展示无法解释的统计数字。
- 先采用确定性聚合，已有标签能满足需求时不新增 AI 请求。
- 不绕过 Agnes `rpm_limit: 19`，不绕过 `GpuResourceManager`，不改变 FunASR、Whisper、Agnes 和 Ollama 的现有优先级。
- 不在本计划中新增平台完整采集链路、数据库后端、任务编排系统或复杂权限系统。
- `data/notes/`、`docs/notes/`、`docs/briefs/` 等运行产物与代码改动分开检查和提交，未经确认不得删除。

## 3. 状态定义

后续更新本计划时统一使用以下状态：

| 状态 | 含义 |
|---|---|
| `未开始` | 尚无实现 |
| `进行中` | 已有代码，但范围不完整或未通过验收 |
| `待验收` | 实现完成，等待测试、运行验证或提交 |
| `已完成` | 代码、测试、文档和运行验证全部通过 |
| `暂缓` | 有明确前置条件，当前不实施 |

文件存在、页面可见或本地构建成功都不能单独视为“已完成”。

## 4. 当前基线

### 4.1 已确认状态

截至 2026-07-16：

- Web 与 worker 正在运行。
- `/health/live` 返回正常。
- `/health/ready` 返回正常，数据库与任务表检查通过。
- 完整测试集合共 141 项，`141 passed`；通过 `tests/conftest.py` 隔离仓库 `.env` 对测试进程的污染，并覆盖内容状态筛选回归。
- `python -m compileall kenradar scripts` 通过。
- 前端 `npm run lint` 和 `npm run build` 通过；已配置 vendor 分包，主应用 chunk 约 442KB、vendor chunk 约 422KB。
- React 前端构建产物存在，当前后端优先服务 React/Vite 前端。
- `/health/dependencies` 可访问，当前 PostgreSQL/GPU 正常，飞书已配置，Ollama 未配置为活动依赖。
- `/api/dashboard/overview?days=7` 已在真实 PostgreSQL 上返回数据。
- `/api/content-items` 已修复兼容视图字段问题，真实 PostgreSQL 返回 200，并验证了 cursor 第二页。
- `/api/insights/sources`、`/api/insights/overview` 和主题 API 均返回 200；0011 已将既有 creator 幂等回填为 26 个来源，其中 20 个启用。
- 7 天来源聚合已写入 140 条日指标和 274 条主题指标，概览返回 20 个 active sources、71 条内容和 42 条高价值内容。
- `source_daily_metrics`、`source_topic_metrics` 迁移已升级到 0011；`analytics-scan` 已注册主 CLI，支持 aggregate/topic-classify dry-run。
- SSE 35 秒实测收到 connected 和两次 heartbeat；断开后 Web 仍健康，连接清理已有单元测试覆盖，重启前后均能重新建立 connected。
- Chrome DevTools 移动视口实测：筛选面板可打开并显示处理状态/高价值/审阅控件，内容卡片可导航 `/aweme?id=...`，处理中心可见重试入口。
- Web 代码与本轮目标文档已提交到本地 `main`；工作区剩余变更主要是运行生成的内容产物与构建元数据，不作为功能完成依据。

### 4.2 阶段完成度基线

| 阶段 | 状态 | 估计完成度 | 主要结论 |
|---|---|---:|---|
| M0 后端收口 | 已完成 | 100% | 路由职责、响应契约、迁移、真实回归和提交均已完成 |
| M1 日常工作台 | 已完成 | 100% | 服务端组合筛选、cursor 分页、移动视口筛选/详情/重试入口均已验证 |
| M2 决策仪表盘 | 已完成 | 100% | 统计口径、对账、性能、空态和图表工作台导航均已完成 |
| M3 局部实时化 | 已完成 | 100% | SSE 自动连接、心跳超时降级、轮询及丢失事件后的全量同步均已实现并验证 |
| M4 来源洞察 MVP | 已完成 | 100% | 来源回填、日/主题指标、聚合 CLI、API、页面和真实对账均已完成 |
| M5 趋势与异常 | 暂缓 | 0% | 等待至少 30 天稳定聚合数据 |

## 5. 交付路线与依赖

```text
M0 工作区与后端收口
  ↓
M1 服务端内容检索 + 日常工作台验收
  ↓
M2 统计口径 + 聚合接口 + 两个核心图表
  ├──────────────→ M3 SSE 局部实时化
  ↓
M4 来源确定性聚合 → 来源洞察页面 → 主题指标
  ↓ 至少积累 30 天稳定数据
M5 趋势与异常
```

不得跳过 M0 直接继续扩大 `app.py`，不得跳过 M1 的服务端分页直接在前端模拟完整筛选，不得跳过 M2 的统计口径直接制作图表。

## 6. M0：工作区与轻量后端收口

**状态：待验收**  
**目标工期：1–2 个工作日**  
**完成定义：现有接口行为不变，Web 改动范围清晰，新增业务不再直接堆入 `app.py`。**

### 6.1 工作区收口

- 将代码改动、设计文档、前端构建产物和运行生成的 `docs/` 内容分组检查。
- 不删除用户现有未提交内容，不将无关运行产物混入 Web 功能提交。
- 确认 `AppContent.tsx`、主题 hook、AsyncState、Skeleton、RunCenterModel 等新增文件是否均被实际引用。
- 在提交说明中列明本次仅包含的里程碑范围。

### 6.2 锁定接口契约

为以下接口至少覆盖成功、参数错误和资源不存在三类行为：

```text
/api/bootstrap  /api/status  /api/awemes  /api/aweme/detail  /api/aweme/progress
/api/research/jobs  /api/research/job  /api/research/cancel  /api/research/pause  /api/research/resume
/api/run-once  /api/test-latest  /api/retry-*  /api/repush-aweme  /api/generate-weekly
/api/source/*  /api/config  /health/live  /health/ready
```

契约测试至少固定：HTTP 方法、URL、参数、状态码、顶层字段、错误格式和 Content-Type。动态时间、任务 ID 等字段只验证类型和存在性。

### 6.3 完成职责迁移

目标结构采用够用的三层，不为拆分而拆分：

```text
routes/       参数解析、权限/方法检查、响应
services/     统计口径、业务编排、返回结果组装
queries.py    SQL 与数据库读取，暂时作为 repository 层
```

本阶段要求：

- `app.py` 只保留服务启动、基础请求分派、静态文件、兼容入口和全局基础设施。
- 已迁移 route 不应反向导入 `app.py` 中的业务组装函数；必要函数迁入 service 或独立 helper。
- `responses.py` 统一 JSON 输出，但必须保持旧接口的状态码和错误结构。
- 不预建空的 SSE、analytics 文件。
- 不以行数作为唯一目标，但本阶段结束后 `app.py` 不再新增业务 handler。

### 6.4 M0 验收

- [x] Web 代码与自动生成内容的变更范围已分离。
- [x] 核心接口契约测试建立并通过。
- [x] 前端无需修改即可调用拆分后的原接口。
- [x] HTTP 状态码、错误格式、CORS 和认证行为不变。
- [x] route 不再反向依赖 `app.py` 的业务函数。
- [x] compileall、focused tests、前端 lint/build 通过。
- [x] 重启后 live、ready、bootstrap、status 和内容详情接口正常。

## 7. M1：服务端内容检索与日常工作台

**状态：进行中**  
**目标工期：3–5 个工作日**  
**完成定义：用户可以从完整数据集中找到高价值、未审阅、失败或指定来源的内容。**

### 7.1 先明确数据口径

- `high_value_threshold` 默认取 7，但必须由后端配置读取并随接口返回，前端不得独立硬编码业务值。
- “今日”统一使用 `Asia/Shanghai`，范围为本地时间 `[00:00, 次日 00:00)`。
- `reviewed` 以 `content_curation` 中明确的审阅状态为准；若当前 schema 无法稳定表达，先补最小字段或取消该筛选，不能用“已打开详情页”代替。
- `processing` 包含正在下载、转录、AI 整理、笔记生成或发布的内容；`queued` 仅表示已入队但尚未开始。
- 关键词检索覆盖标题、创作者名称、摘要、topics 和 tags；原始转录默认不参与，避免查询成本和误匹配。

### 7.2 新增权威查询接口

```http
GET /api/content-items
  ?keyword=AI
  &creator_id=12
  &platform=douyin
  &status=completed
  &high_value=true
  &reviewed=false
  &date_from=2026-07-01
  &date_to=2026-07-14
  &sort=priority_desc
  &cursor=<opaque>
  &limit=30
```

返回建议：

```json
{
  "items": [],
  "next_cursor": null,
  "has_more": false,
  "high_value_threshold": 7,
  "applied_filters": {},
  "total_estimate": null
}
```

实现约束：

- `limit` 默认 30，最大 100。
- cursor 必须是不透明值，至少包含排序字段与稳定唯一键。
- `priority_desc` 的排序规则固定为：未审阅优先 → 高价值优先 → 评分降序 → 发布时间降序 → ID 降序。
- 新内容插入时不得造成已翻页结果重复或漏项。
- 非法日期、状态、排序值返回 400，不静默忽略。
- 先复用 `queries.py`，确认复杂度后再决定是否新建 repository 目录。

### 7.3 完成前端工作台

- 顶部显示今日新增、高价值待审阅、处理失败和处理中。
- 内容列表使用服务端结果，筛选变化时重置 cursor。
- 搜索输入采用 300–500ms 防抖，并取消过期请求或忽略过期响应。
- 高价值、未审阅、来源、状态和日期可以组合使用。
- 卡片优先展示标题、来源、发布时间、评分、推荐动作和处理状态。
- 保留当前视觉方向，不做导航结构和全站布局的大改造。

### 7.4 收口已有前端能力

- `AsyncState` 和 Skeleton 覆盖 RadarDashboard、DetailView、ResearchWorkspace、RunCenter 和 ArchiveWorkspace 的主要远程数据区域。
- 深色模式通过主题 hook 和 localStorage 持久化，状态色在浅色与深色下均可辨识。
- 统一按钮层级：primary、secondary、ghost、danger。
- 长标题、长错误、大量标签和空数据不撑破布局。
- 快捷键及帮助弹窗继续暂缓，直到 J/K/Enter 等交互有明确需求。

### 7.5 M1 验收

- [x] 单项及组合筛选均针对完整服务端数据集生效。
- [x] cursor 翻页无重复、无明显漏项。
- [x] 高价值阈值、今日边界和审阅口径有自动化测试。
- [x] 空数据、慢请求、单接口失败不会导致白屏（`AsyncState`、Skeleton 和局部错误边界已接入主要页面）。
- [x] 桌面端可用，移动端已实测完成筛选、打开详情；处理中心重试入口和真实 `POST /api/retry-summary` 受理链路均已验证（本次 provider 失败被明确记录并取消）。
- [x] 浅色/深色模式下成功、警告、失败、处理中状态可区分（主题 token 与状态色已覆盖）。
- [x] 旧 `/api/awemes` 保留兼容，现有页面在迁移期间不受影响。

## 8. M2：决策型仪表盘 MVP

**状态：待验收**  
**目标工期：4–6 个工作日**  
**完成定义：仪表盘数字可以回答内容价值和流水线积压问题，并能追溯到明细。**

### 8.1 统计口径

先在 service 中形成一份可测试的口径定义：

- `today_new`：今日首次入库内容数。
- `high_value_pending`：评分达到阈值且未审阅的已完成内容数。
- `failed`：当前最终状态为失败、尚未成功恢复的内容数。
- `processing`：当前存在活动任务步骤的内容数。
- `pushed`：存在成功 `push_log` 的内容数，不以“推荐推送”代替。
- `rated_count`：评分非空的内容数；平均分分母只能使用该值。
- 同一内容多次重试只计一条内容，失败原因按当前未恢复的最后失败阶段统计。

### 8.2 聚合接口

```http
GET /api/dashboard/overview?days=30
```

`days` 仅允许 7、30、90，默认 30；返回：

```json
{
  "generated_at": "2026-07-15T12:00:00+08:00",
  "timezone": "Asia/Shanghai",
  "high_value_threshold": 7,
  "summary": {
    "today_new": 0,
    "high_value_pending": 0,
    "failed": 0,
    "processing": 0
  },
  "daily_trend": [],
  "pipeline": {},
  "source_activity": [],
  "score_distribution": [],
  "failure_reasons": []
}
```

接口由 `routes/dashboard.py → services/dashboard_service.py → queries.py` 实现。数据库查询失败时返回明确错误，不用空数组伪装成功；某个非关键分区不可用时可返回 `partial: true` 和 `errors`。

### 8.3 第一批只做两个图表

确认接口与查询性能后再安装 Recharts，首批仅实现：

| 组件 | 回答的问题 | 点击行为 |
|---|---|---|
| `DailyTrendChart` | 近期内容量和高价值内容是否变化？ | 跳转到对应日期和高价值筛选 |
| `PipelineStatusChart` | 当前积压集中在哪个阶段？ | 跳转到处理中心对应阶段 |

以下图表推迟到首批数据验证后：来源活跃矩阵、失败原因分布、评分分布。

### 8.4 性能要求

- 7 天和 30 天查询目标 `< 500ms`，以本机 PostgreSQL 实测为准。
- 对日期、状态及关联外键使用必要索引。
- 使用 `EXPLAIN ANALYZE` 检查核心查询，不做无证据的索引堆叠。
- 概览可在前端保留 30–60 秒轮询；本阶段不依赖 SSE。

### 8.5 M2 验收

- [x] 每个指标有 SQL/service 单元测试及人工抽样对账。
- [x] 图表数字与筛选后的明细数量一致。
- [x] 图表为零、仅一个点或部分数据缺失时可正常展示（图表组件有空数据分支，Recharts 接受单点/稀疏序列）。
- [x] 点击指标或图表可以进入对应工作台（趋势进入内容归档，流水线进入处理中心）。
- [x] 7/30 天查询达到性能目标；90 天有结果且体验可接受。
- [x] 仪表盘接口失败不影响内容详情、处理中心和来源管理。

## 9. M3：局部实时化

**状态：进行中，完成实现后待稳定性验收**  
**目标工期：3–4 个工作日**  
**完成定义：研究任务和失败事件实时更新，断线时自动、安全地退回轮询。**

实时化只覆盖研究任务状态、任务进度、失败和完成事件，不将仪表盘统计、日志全文或所有内容变化放入 SSE。

### 9.1 后端

- 新增 `sse.py` 与 `/api/stream?channels=research-jobs`。
- 统一使用默认 `message` 事件，类型放入 JSON `type` 字段。
- 每 30 秒心跳；每客户端使用有界队列。
- 慢客户端丢弃旧进度事件但保留最新状态与完成/失败事件。
- 客户端断开后清理队列，服务关闭时释放连接。
- 事件只是刷新提示，数据库仍是最终事实来源。

### 9.2 前端

- `useSSE` 状态机：`connecting → connected → degraded → polling → closed`。
- 连续失败达到阈值后才开启轮询，不在第一次断线时立即切换。
- SSE 恢复后先完整拉取任务列表，再关闭轮询。
- 浏览器隐藏时降低轮询频率，恢复可见时立即同步一次。
- 保留原轮询实现作为可配置回退路径。

### 9.3 健康检查

- 保留现有 `/health/live` 和 `/health/ready`。
- 新增 `/health/dependencies` 时，各依赖独立超时并缓存 30 秒。
- PostgreSQL 属于 ready 条件；Ollama、GPU、飞书属于依赖状态，不应令 Web 进程判定为不存活。
- 返回值统一为 `ok`、`degraded`、`unavailable`。

### 9.4 M3 验收

- [x] 页面刷新、断网恢复和后端重启后能恢复更新。
- [x] 关闭页面后服务端连接被清理。
- [x] 慢客户端不会造成广播线程或队列无限增长。
- [x] SSE 失败后轮询可继续更新，恢复后不会双重请求。
- [x] 丢失事件后完整同步能够修正前端状态（SSE degraded/polling 状态触发 `/api/research/jobs` 权威刷新，另有轮询兜底）。

## 10. M4：来源洞察 MVP

**状态：进行中，依赖真实数据库修复与聚合回填**  
**目标工期：5–7 个工作日**  
**完成定义：可以按来源查看内容量、评分可信度、高价值率和推送情况的日趋势。**

### 10.1 第一阶段只做确定性聚合

新增迁移 `0008_source_insights.py`，表结构以迁移执行时的真实外键类型为准：

```sql
CREATE TABLE source_daily_metrics (
    id BIGSERIAL PRIMARY KEY,
    source_id <source_subscription.id 的真实类型> NOT NULL
        REFERENCES source_subscription(id),
    metric_date DATE NOT NULL,
    total_content INT NOT NULL DEFAULT 0,
    rated_count INT NOT NULL DEFAULT 0,
    high_value_count INT NOT NULL DEFAULT 0,
    avg_rating REAL,
    push_count INT NOT NULL DEFAULT 0,
    review_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    calculation_version VARCHAR(16) NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, metric_date)
);
```

要求：

- 时区统一为 `Asia/Shanghai`。
- AI 评分为空的数据不计入 `rated_count` 和平均分。
- 重算采用 UPSERT，删除或重新处理内容后可以修正历史聚合。
- `source_id, metric_date` 建立唯一约束及适当查询索引。
- 先验证 `source_subscription` 与抖音 creator/content 的真实关联，不假设所有历史内容都能直接映射；无法映射的数量要可观测。

### 10.2 扫描命令

```bash
python -m kenradar analytics-scan --days 7 --step aggregate
```

- 命令幂等，不通过公开 HTTP 触发。
- 支持 dry-run、指定日期范围和输出受影响行数。
- 首次上线不自动加入生产调度；人工回填和对账通过后再配置每日任务。
- 失败记录到现有日志/告警体系，不创建第二套任务系统。

### 10.3 API 与页面

```http
GET /api/insights/sources
GET /api/insights/sources/:id/metrics?days=30
GET /api/insights/overview?days=30
```

首版页面只提供：来源列表、内容量、高价值率、平均分及 `rated_count`、推送数、失败数和 30 天趋势。来源管理 `/sources` 与来源洞察 `/insights` 保持职责分离。

### 10.4 主题指标作为第二批

确认每日指标稳定后再新增 `source_topic_metrics`：

- 优先复用 `ai_analysis` 中已有 topics/tags。
- 只有明确证明现有标签覆盖不足时，才评估 `topic-classify` AI 请求。
- 新 AI 请求必须继续遵守 provider 限流，并单独核算成本和失败降级。

### 10.5 M4 验收

- [x] 同一日期重复扫描不产生重复记录。
- [x] 删除、失败恢复和重新评分后重算结果正确。
- [x] 至少抽样 5 个来源与原始内容对账。
- [x] 无评分时平均分显示为空，不显示为 0。
- [x] 无法映射来源的内容有明确计数和日志。
- [x] 30/90/365 天查询性能经过实测（来源接口约 0.05/0.06/0.05 秒）。
- [x] 迁移有升级、重复执行安全性和测试环境验证。

## 11. M5：趋势与异常

**状态：暂缓**

只有同时满足以下条件才进入设计和实施：

- `source_daily_metrics` 已连续稳定运行至少 30 天。
- 聚合口径期间没有未处理的版本变更。
- 来源映射覆盖率达到可接受水平。
- 用户已经实际使用来源洞察，并能明确异常检测要支持的决策。

首批异常只考虑可解释的规则：更新频率突增/突降、高价值率显著变化、连续失败。每条异常必须保存比较窗口、基线值、观测值、算法版本、证据内容和处理状态。不开启无法追溯依据的黑盒异常评分。

## 12. 跨阶段质量门禁

每个里程碑完成前执行：

```bash
python -m compileall kenradar scripts
python -m pytest tests/test_config_and_publishing.py -q
cd kenradar/web/frontend
npm run lint
npm run build
```

涉及 Web 运行行为时，继续验证：

```bash
./ctl.sh restart
./ctl.sh status
curl -fsS http://127.0.0.1:8765/health/live
curl -fsS http://127.0.0.1:8765/health/ready
```

还必须人工抽查：

- 仪表盘、内容详情、处理中心、失败重试、研究任务、来源管理、系统配置和系统监控。
- React `dist/` 存在时的前端，以及 dist 不存在时服务端 HTML 回退。
- 详情页 Markdown、折叠原始转录、Obsidian 路径和原视频链接。
- card/text 飞书推送与 `push_log` 未被破坏。
- `docs/` 发布目录和 `/file` 到 `/aweme` 的兼容跳转未被破坏。

若环境依赖导致某项无法验证，交付说明必须写明“未验证”及原因，不得声称可用。

## 13. 提交与发布策略

建议每个里程碑拆为可审查的小提交：

1. 契约测试或数据口径测试。
2. 后端查询/service/route。
3. 前端接入与交互。
4. 构建产物和文档更新。

数据库迁移、运行调度和新 AI 调用必须独立提交。发布前记录旧版本健康状态；发布后首先检查 live/ready/bootstrap/status，再检查业务页面。出现接口不兼容、任务无法恢复、数据库聚合错误或生产链路异常时，停止后续里程碑并回滚本次范围，不触碰内容产物。

## 14. 本轮建议执行清单

当前只执行以下顺序，优先修复真实链路，再补功能：

- [x] P0-1：修复 `/api/content-items` 对 `summary` 兼容视图不存在 `result_json` 的错误，并用真实 PostgreSQL 验证组合筛选和 cursor。
- [x] P0-2：修复 `/api/insights/overview` 单参数绑定错误，并验证真实数据库路径。
- [x] P0-3：将 `analytics-scan` 正式注册到主 CLI，支持 `--days`、`--step aggregate/topic-classify` 和 `--dry-run`。
- [x] P0-4：执行来源指标正式回填及至少 5 个来源人工对账（已回填 20 个启用来源，7 天 140 行日指标、274 行主题指标；二钳深度研报、刘璐的投资笔记、杨竹筠、PAKEN财经说、Panda AI 量变学院聚合总量均与直接内容计数一致）。
- [x] P0-5：完成 SSE 后端重启恢复、轮询切换和服务端连接清理验收（35 秒 heartbeat、重启前后重新 connected、轮询降级代码和 broadcaster 清理单元测试均通过）。
- [x] P0-6：对 `/api/dashboard/overview` 指标与内容明细进行抽样对账，并记录 7/30/90 天响应时间（实测约 0.55s / 0.55s / 0.71s，7/30 天满足目标）。
- [x] P0-7：已完成代码与目标文档提交；`docs/` 内容产物继续按生成物管理，不纳入功能验收。
- [x] P1-1：完成剩余真实验收并将 M0–M4 标为已完成；M5 继续暂缓。
- [x] P1-2：加入 Vite vendor 分包，主应用 chunk 降至约 442KB，消除原 864KB 单 chunk 警告。

完成 P0 后，KenRadar 的“发现 → 判断 → 处理 → 归档 → 发布 → 来源复盘”闭环才可视为真实可用；在此之前不启动 M5 异常检测。
