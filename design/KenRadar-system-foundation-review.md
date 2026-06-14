# KenRadar 全面架构审计与系统底座化实施方案

> 审计日期：2026-06-14  
> 审计范围：CLI、配置、抖音采集、下载、转录、AI 整理、GPU 调度、Obsidian、PostgreSQL、静态发布、GitHub 同步、飞书、Web、调度、测试与当前运行状态。

## 1. 结论摘要

KenRadar 已经不是单一下载脚本，而是一套可实际运行的本地 AI 内容处理产品。它已经具备完整业务闭环、较强的单任务容错、研究任务流水线、GPU 协调、状态存储、内容发布和运维后台。

当前最准确的工程定位是：

> 一个以 `Workflow` 为中心、PostgreSQL 保存业务结果、进程内队列驱动执行的单机内容处理系统。

它适合当前“单机、单用户、抖音优先、有限并发”的生产场景，但还不适合作为可扩展系统底座。主要差距不在业务功能，而在任务持久化、原子领取、状态机约束、进程恢复、资源调度、模块边界、安全配置、数据库迁移和系统级测试。

底座化不建议重写。推荐保留现有采集器、下载器、转录器、organizer、笔记模板、发布器和推送器，把执行控制逐步从 `Workflow` 大类迁移到 PostgreSQL 驱动的持久任务模型。

## 2. 当前功能地图

### 2.1 控制入口

- CLI：初始化、监控运行、历史回填、单视频研究、博主研究、摘要补齐、重分类、旧笔记升级、清理、发布、GitHub 同步、Web 和独立调度。
- Web：仪表盘、内容资料库、失败重试、研究任务、来源管理、配置、推送记录、告警和日志。
- 内置调度：Web 启动时拉起调度线程，按配置时间执行 `run_once`。

### 2.2 内容主链路

1. 从配置加载启用博主。
2. 通过本地 Douyin vendor 获取作品列表。
3. 按数据库记录和检查点过滤。
4. 并发下载视频和 JSON 元数据。
5. 优先 FunASR，失败或质量不足时回退 Whisper。
6. 优先 Agnes AI，失败时回退 Docker Ollama。
7. AI 全部失败时生成明确标记的本地降级结果。
8. 生成唯一 Obsidian 内容笔记。
9. 写入 PostgreSQL。
10. 生成静态 HTML 和索引。
11. 批次结束后 GitHub commit/push。
12. 按推荐动作和价值评分生成飞书精简简报。
13. 成功持久化后清理下载和转录中间文件。

### 2.3 研究链路

研究博主支持：

- URL、名称或 `sec_uid` 解析。
- 时间范围、数量限制和强制重跑。
- 下载、转录、AI 三段队列流水线。
- 有界队列和背压。
- 下载重试与连续失败熔断。
- 转录超时、重试和 stale 状态重置。
- 暂停、取消、恢复和失败条目重试。
- 已有视频或转录复用。
- 批次报告、批次笔记索引、一次 GitHub 同步和完成提醒。
- 研究成功后自动加入持续监控配置。

### 2.4 存储模型

PostgreSQL 已包含以下核心实体：

- `platform`
- `creator`
- `content_item`
- `transcript`
- `ai_analysis`
- `content_note`
- `content_curation`
- `push_log`
- `alert_log`
- `research_job`
- `research_job_item`

同时通过 `blogger`、`aweme`、`summary` 兼容视图维持旧查询接口。

### 2.5 当前运行事实

审计时实际状态：

- Web、FunASR、Ollama 本地端点均可达。
- PostgreSQL 中有 308 条内容。
- 308 条内容均已下载完成。
- 308 条转录均为成功。
- 308 条 AI summary 均为成功。
- 308 条内容笔记均已登记。
- 8 个研究任务完成，1 个历史任务取消。
- 当前无活跃研究任务。
- 历史研究任务中保留 2 条失败明细，但后续独立重试任务已成功。

这证明当前业务闭环真实可用，而不是只存在于代码中。

## 3. 健壮性评估

### 3.1 已做得较好的部分

#### 内容幂等

- `content_item` 使用 `(platform_id, content_id)` 唯一约束。
- transcript、summary 和 note 使用内容级唯一约束及 upsert。
- 成功转录不会被后续失败结果覆盖。
- 已成功内容、已有转录和已有视频可以复用。
- 同一视频旧标题笔记和旧 HTML 会被清理。

#### 外部服务容错

- 下载有单条重试、批次节流和连续失败熔断。
- FunASR 有质量检查，并直接回退 Whisper。
- Whisper 有 VAD 重试、OOM 识别和 CPU fallback。
- organizer 有 provider 顺序、超时、重试、RPM 限流和本地降级。
- 飞书 Card 失败可回退 Text。
- API 失败会写告警和失败状态，不会把原始转录伪装成摘要。

#### 资源控制

- 下载使用 semaphore。
- 研究流水线使用有界 `asyncio.Queue` 和背压。
- Agnes 使用跨进程文件级 RPM 限流。
- GPU 使用进程内锁和文件锁。
- staged/turbo 模式可在 Whisper 和 Ollama 之间切换显存占用。

#### 输出契约

- Obsidian frontmatter 和固定四段正文结构集中生成。
- YAML 字符串有专门转义。
- 原始转录只进入详情页和笔记，不进入飞书。
- 静态发布和 GitHub 同步包含敏感文件与敏感文本拦截。

### 3.2 关键风险

#### P0：敏感配置仍保存在明文运行配置

当前本地 `config/config.yaml` 包含数据库凭据和完整登录 Cookie。文件被 `.gitignore` 排除，GitHub 同步也有阻断规则，因此当前未发现被 Git 跟踪，但这仍有以下风险：

- 本机备份、日志采集、误打包或人工复制泄露。
- Web 配置写回时继续保存明文。
- 配置备份文件扩大敏感数据副本数量。
- 密码轮换没有统一入口和审计。

改进：

- `config/config.yaml` 只保留 `${DATABASE_URL}`、`${DOUYIN_COOKIE_FILE}` 等引用。
- Cookie 放入权限为 `0600` 的独立 secret 文件，或从环境变量注入。
- 启动时检查敏感文件权限。
- 提供 `kenradar doctor secrets`，只报告是否配置，不输出值。
- 对已经暴露在本地历史备份中的数据库密码和 Cookie 做轮换。

#### P0：任务队列和锁只存在于 Web 进程内

`_TASK_QUEUE`、`_TASK_STATE`、`_TASK_LOCK` 都是内存对象。后果：

- Web 重启后排队任务丢失。
- 运行中任务可能仍在外部服务执行，但系统只会把数据库任务标为取消。
- CLI、第二个 Web 进程或独立 scheduler 不共享任务锁。
- 无法可靠部署多个 worker。
- `force` 路径会主动释放一个可能仍被旧线程使用的锁，存在两个重任务同时运行的风险。

改进：

- 所有长任务写入持久 `task_run` 和 `task_step`。
- worker 使用 `FOR UPDATE SKIP LOCKED` 原子领取。
- 使用 lease、heartbeat、attempt 和 `locked_by`。
- 取消采用 `cancel_requested_at`，由 worker 协作退出。
- Web 只提交任务和查询状态，不直接持有执行线程。

#### P0：内容处理没有统一的数据库 claim

当前数据库唯一约束可以避免重复插入，但不能避免两个进程同时下载、转录或整理同一内容。`should_process_aweme` 是读后判断，不是原子领取。

改进：

- 为每个 stage 建立可领取任务，或在 `content_processing_state` 上保存 lease。
- claim SQL 必须同时完成状态判断、attempt 增加、owner 和 lease 写入。
- stage 输出写入与 task 完成尽量在同一事务提交。
- 增加 idempotency key：`platform:content_id:stage:input_version`。

#### P1：状态字符串分散，缺少合法迁移约束

`pending`、`running`、`downloading`、`downloaded`、`transcribing`、`transcribed_waiting_summary`、`summarizing`、`noting`、`success`、`failed` 等字符串散落在 Workflow、Web、SQL 和前端映射中。

风险：

- 拼写错误不会被数据库拒绝。
- Web 展示状态与执行状态可能漂移。
- 无法证明某次迁移是否合法。
- 历史任务失败和内容最终成功容易混淆。

改进：

- Python `Enum` 作为唯一状态定义。
- PostgreSQL 使用 CHECK 约束，或单独状态字典表。
- 明确区分 `task outcome`、`content current state` 和 `attempt history`。
- 所有迁移通过一个 repository/service 方法执行，并记录 `state_transition`。

#### P1：数据库 schema 仍靠启动时执行整段 SQL

虽然依赖中已有 Alembic，但尚未建立 `env.py` 和版本脚本。当前 `initialize()` 每次执行 `SCHEMA_SQL`，并 DROP/CREATE 兼容视图。

风险：

- 无版本号，无法判断实例处于哪个 schema。
- 复杂变更无法安全回滚或灰度。
- 多进程同时初始化可能增加锁竞争。
- 生产升级缺少备份、迁移和验收步骤。

改进：

- 建立 Alembic baseline，标记当前 schema 为 `0001_baseline`。
- 启动只做 schema version 检查，不自动做破坏性迁移。
- `kenradar migrate` 显式执行升级。
- 每个版本提供向前迁移、数据修复和兼容窗口。

#### P1：PostgreSQL 与 SQLite 的运行时策略冲突

产品约束声明 SQLite 已废弃，但配置和 `create_database()` 在数据库 URL 缺失或 scheme 异常时仍静默回退 SQLite，Web 仍暴露 `database_path`。

改进：

- 正常运行要求 `postgresql://`，缺失时 fail-fast。
- `storage/database.py` 只供迁移工具导入。
- 删除 Web 的 SQLite 配置入口。
- `migrate_sqlite_to_pg` 保留为显式离线命令。

#### P1：`Workflow` 过大，事务边界不清晰

`workflow.py` 超过 3000 行，同时承担编排、状态更新、Markdown 渲染、清理、发布、重试、研究报告和配置写回。

风险：

- 局部改动容易影响多条主线。
- 文件写入、数据库写入和发布不是原子操作。
- 单元测试难以替换依赖。
- 新平台容易复制分支而不是复用能力。

改进：

- 不重写业务实现，先抽出 stage service。
- `Workflow` 最终只负责创建 job graph。
- Markdown 渲染迁入 `note_renderer`。
- 清理迁入 `artifact_service`。
- 发布和推送改为独立、可重试的后置任务。

#### P1：配置写入不是原子的，也没有并发控制

`save_config()` 直接覆盖 YAML。Web 多请求或研究任务自动加入监控时，可能出现后写覆盖先写；进程中途退出可能留下不完整文件。

改进：

- 写临时文件、`fsync`、`os.replace`。
- 使用配置文件锁。
- 引入 `config_revision` 或基于 mtime 的乐观锁。
- 运行配置与 secret 配置分离。
- 长期将来源管理迁入 PostgreSQL，YAML 只保留系统级默认值。

#### P1：来源配置没有唯一性校验

`Checker.load_targets()` 会逐项加载配置，但不按 `(platform, sec_uid)` 去重。当前配置中已存在重复来源，同一次定时任务可能重复请求同一博主；虽然内容唯一约束能避免重复入库，仍会浪费抓取配额，并可能重复推进同一个 creator checkpoint。

改进：

- 配置加载时按 `(platform, sec_uid)` 去重并报告冲突。
- 保存配置前拒绝重复来源。
- 以 PostgreSQL `creator` 作为来源事实源，YAML 只用于初始化导入。
- 为来源增加独立抓取 lease，避免多个 scheduler 同时抓取。

#### P1：远程 AI 与 Ollama 开关存在错误耦合

研究流水线会在 `gpu_scheduler.ollama.enabled=false` 时直接关闭 AI worker，即使 Agnes 远程 provider 已启用。这会把“是否启动 AI 阶段”和“本地 GPU fallback 是否启用”混为一体。

改进：

- AI worker 是否启用只由 organizer 和可用 provider 决定。
- Ollama 开关只控制 fallback provider，不控制 Agnes。
- provider readiness 在任务开始前计算并记录。
- `ContentOrganizer.last_error` 改为单次调用返回值的一部分，避免未来并发调用共享可变状态。

#### P1：Web 安全只适合可信内网

- 未配置密码时完全开放。
- Basic Auth 密码为明文配置。
- 没有 CSRF 防护。
- 没有登录会话、权限和操作审计。
- `ThreadingHTTPServer`、内嵌后台线程和重启子进程适合本地工具，不适合底座服务。

改进：

- 当前阶段至少要求非 loopback 监听时必须设置密码。
- 管理写接口校验 CSRF token。
- 密码只保存 hash。
- 记录配置修改、重试、取消、发布等审计事件。
- 底座阶段迁移到成熟 ASGI 框架和独立 worker，但保留现有 API 兼容层。

#### P1：发布和 Git 操作缺少跨进程互斥

多个任务同时生成 `docs/index.html` 或执行 git add/commit/push 会产生覆盖和索引不一致。

改进：

- `publish_site` 和 `github_sync` 定义为全局互斥资源。
- 使用数据库 advisory lock 或独立 `resource_lock`。
- 只允许一个 publisher 合并一段时间内的变更。
- Git 提交前重新扫描候选文件，并保存发布 manifest。

#### P2：测试集中在纯函数和输出，缺少系统级覆盖

现有 19 个测试全部通过，但主要覆盖配置、AI JSON、文本分段、静态发布、GitHub dry-run、飞书返回和少量转录 fallback。

缺少：

- PostgreSQL repository 集成测试。
- 状态迁移和并发 claim 测试。
- worker crash/restart 恢复。
- scheduler 重复触发和错过窗口。
- Web 鉴权、CSRF 和配置并发写。
- publish/git 并发。
- 完整 pipeline 的 fake-provider 端到端测试。
- migration upgrade 测试。

#### P2：告警可能形成噪声

24 小时内存在较多服务 fallback 告警。单条 FunASR 失败后 Whisper 成功，最终业务并未失败，但告警仍可能以 error 级别记录或推送。

改进：

- 区分 `degraded`、`retrying`、`failed`、`recovered`。
- 同一 component/error fingerprint 做时间窗聚合。
- fallback 成功只记录 warning 和指标。
- 最终失败才触发高优先级通知。

## 4. 可并行操作分析

### 4.1 当前代码已经支持的并行

| 范围 | 当前能力 | 约束 |
|---|---|---|
| 同一博主批次下载 | 可并行 | `download.max_workers` |
| 下载与转录 | 可流水并行 | 有界 transcript queue |
| 转录与 Agnes AI | 可流水并行 | 有界 AI queue，AI worker 单线程 |
| 多个 CPU 转录 | 可并行 | `transcribe.workers` 和 CPU 线程数 |
| 多个 HTTP 查询 | 可并行 | Web 使用 ThreadingHTTPServer |
| 多个轻量数据库读 | 可并行 | PostgreSQL pool 最大 5 |
| Agnes 与 CPU Whisper | 原理上可并行 | Agnes 为远程服务 |
| 静态文件阅读与后台任务 | 可并行 | 只读路径 |

### 4.2 当前被全局任务锁串行化的主线

Web 发起的以下长任务会进入同一个 `_TASK_LOCK`：

- `run_once`
- `test_latest`
- 博主研究
- 单视频研究
- 各类失败重试
- 旧任务重启或恢复

内置 scheduler 也使用同一锁，因此长研究任务会推迟定时监控。日志已真实出现定时任务因研究任务持锁而连续暂缓。

### 4.3 底座化后建议的并行矩阵

| 主线组合 | 建议 | 原因 |
|---|---|---|
| 来源抓取 A + 来源抓取 B | 并行 | 网络 IO，按平台限流 |
| 下载 A + 下载 B | 并行 | 网络 IO，按域名 semaphore |
| 下载 + CPU Whisper | 并行 | 资源不同 |
| 下载 + FunASR HTTP | 并行 | 资源不同，但限制 backlog |
| Agnes AI + CPU Whisper | 并行 | 远程 LLM 与本地 CPU |
| Agnes AI + FunASR | 并行 | 两个独立服务 |
| Agnes AI 多任务 | 受控并行/串行 | 必须共享 19 RPM |
| CUDA Whisper + Ollama GPU | 互斥 | 单 GPU 显存竞争 |
| 两个 CUDA Whisper | 默认互斥 | 除非显存配额证明可并行 |
| 两个同内容同 stage | 禁止 | 使用 idempotency/claim |
| 两个不同博主研究 | 可并行到下载和远程 AI | GPU stage 由资源调度器串行 |
| 定时监控 + 历史研究 | 应并行 | 监控赋予更高优先级 |
| 笔记渲染不同内容 | 可并行 | 每内容唯一文件路径 |
| 全局 index 重建 | 串行并合并 | 单一共享输出 |
| GitHub sync + GitHub sync | 串行 | 共享 worktree/index |
| 飞书不同批次推送 | 可并行但限流 | 使用 outbox 和去重键 |
| 配置写 + 配置写 | 串行 | 文件锁/乐观锁 |

### 4.4 推荐资源池

- `io:douyin_fetch`：按 Cookie/account 限流。
- `io:download`：默认 5。
- `cpu:transcribe`：根据 CPU 核心数和模型内存配置。
- `service:funasr`：根据服务吞吐配置。
- `api:agnes`：共享 19 RPM，可设置并发 1。
- `gpu:0`：容量 1，CUDA Whisper 和 Ollama 都申请。
- `fs:notes`：按 `content_id` 细粒度锁。
- `fs:site-index`：容量 1。
- `git:repo`：容量 1。
- `notify:feishu`：按 webhook 限流。

优先级建议：

1. 实时监控新内容。
2. 用户手动单视频研究。
3. 失败重试。
4. 历史博主研究。
5. 旧笔记升级和批量重分类。

## 5. 目标底座架构

### 5.1 设计原则

- PostgreSQL 是任务和业务状态的唯一事实源。
- 文件系统保存大对象和最终内容，但文件引用必须登记在数据库。
- 所有 stage 至少一次执行，业务写入保持幂等。
- Web、scheduler 和 CLI 都只提交命令，不直接拥有长任务生命周期。
- worker 可以重启，任务可以恢复。
- GPU、外部 API、Git 和共享索引都是显式资源。
- 平台差异放在 adapter，通用处理链路不感知抖音字段细节。
- 保留当前笔记、HTML、飞书和兼容视图契约。

### 5.2 逻辑组件

```text
CLI / Web / Scheduler
        |
        v
Command Service -----> PostgreSQL task_run/task_step/outbox
                              |
                 +------------+-------------+
                 |            |             |
              IO Worker   AI Worker    Publisher Worker
                 |            |             |
          adapters/services/resources/artifact store
                 |
                 v
     content_item/transcript/analysis/note/push_log
```

### 5.3 建议模块边界

```text
kenradar/
  domain/
    models.py
    states.py
    commands.py
    events.py
  application/
    command_service.py
    pipeline_planner.py
    content_service.py
    research_service.py
  adapters/
    sources/douyin.py
    transcription/funasr.py
    transcription/whisper.py
    organizer/agnes.py
    organizer/ollama.py
    notification/feishu.py
    publishing/static_site.py
  infrastructure/
    db/repositories.py
    db/migrations/
    jobs/worker.py
    jobs/leases.py
    resources/locks.py
    artifacts/store.py
    observability/
  web/
  cli/
```

这是目标边界，不要求一次性搬目录。第一阶段可以只增加 repository、task engine 和 adapter protocol，现有实现通过包装接入。

## 6. 数据库与任务模型

### 6.1 新增 `task_run`

建议字段：

- `id UUID`
- `task_type`
- `priority`
- `status`
- `payload JSONB`
- `idempotency_key UNIQUE`
- `requested_by`
- `scheduled_at`
- `started_at`
- `finished_at`
- `cancel_requested_at`
- `attempt`
- `max_attempts`
- `last_error_code`
- `last_error_message`
- `created_at`
- `updated_at`

### 6.2 新增 `task_step`

- `id UUID`
- `task_run_id`
- `content_item_id`
- `stage`
- `status`
- `input_version`
- `output_ref JSONB`
- `priority`
- `available_at`
- `locked_by`
- `locked_at`
- `lease_expires_at`
- `heartbeat_at`
- `attempt`
- `max_attempts`
- `error_code`
- `error_message`
- `started_at`
- `finished_at`
- 唯一键 `(content_item_id, stage, input_version)`

领取示意：

```sql
WITH candidate AS (
  SELECT id
  FROM task_step
  WHERE status IN ('queued', 'retry_wait')
    AND available_at <= NOW()
    AND stage = ANY(%s)
  ORDER BY priority DESC, available_at, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE task_step
SET status = 'running',
    locked_by = %s,
    locked_at = NOW(),
    lease_expires_at = NOW() + INTERVAL '5 minutes',
    heartbeat_at = NOW(),
    attempt = attempt + 1
WHERE id = (SELECT id FROM candidate)
RETURNING *;
```

### 6.3 新增历史与事件表

- `task_attempt`：每次执行的 provider、耗时、结果和错误。
- `state_transition`：对象、旧状态、新状态、原因和 actor。
- `artifact`：视频、音频、transcript sidecar、Markdown、HTML 的路径、大小、hash、生命周期。
- `outbox_event`：发布、推送、告警等事务后事件。
- `resource_lease`：GPU、Git、site index 等跨进程互斥资源。
- `config_audit`：配置修改前后差异，不记录 secret 明文。

### 6.4 内容最终状态与任务历史分离

建议：

- `content_item` 只表达内容身份和当前处理概览。
- `transcript`、`ai_analysis`、`content_note` 表达当前有效产物。
- `task_step/task_attempt` 表达每次处理历史。
- 历史 job item 失败不因后续成功而消失，但 UI 应显示“本次任务失败，内容当前已恢复成功”。

## 7. 分阶段实施方案

### Phase 0：安全与一致性止血

目标：不改变业务流程，先消除高风险不一致。

工作项：

1. 配置 secret 全部改为环境变量或独立 secret 文件。
2. 轮换当前数据库密码和抖音 Cookie。
3. PostgreSQL 缺失时 fail-fast，移除运行时 SQLite fallback。
4. `save_config()` 改为文件锁加原子替换。
5. 增加来源唯一性校验和启动时重复来源报告。
6. 解耦 Agnes AI worker 与 Ollama enable 开关。
7. 非 loopback Web 监听要求认证。
8. 删除强制释放运行中 `_TASK_LOCK` 的路径。
9. GitHub sync 增加跨进程 repo lock。
10. 建立 Alembic baseline。

验收：

- 仓库和运行配置中无 secret 明文。
- 数据库配置错误时启动明确失败。
- 并发保存配置不会损坏 YAML。
- 两个发布进程不能同时操作 git index。

### Phase 1：统一状态和 repository

目标：保持现有 Workflow 行为，先收拢状态和数据访问。

工作项：

1. 建立 stage/status Enum。
2. 为状态字段增加数据库 CHECK。
3. 把 Workflow 内直接 SQL 移入 PostgreSQL repository。
4. 增加 transition API 和错误码分类。
5. 区分 degraded、failed 和 recovered。
6. 为内容状态增加 `updated_at` 和必要索引。

验收：

- 业务代码不再直接拼研究任务状态 SQL。
- 非法状态写入被测试和数据库拒绝。
- Web 状态映射只依赖统一 Enum。

### Phase 2：持久任务引擎

目标：替换 Web 内存队列，但暂时仍可单 worker 运行。

工作项：

1. 增加 `task_run/task_step/task_attempt` migration。
2. 实现 submit、claim、heartbeat、complete、fail、retry 和 cancel。
3. Web、CLI、scheduler 改为提交任务。
4. 增加独立 `kenradar worker` 命令。
5. worker 启动时回收过期 lease。
6. 保留旧 Workflow 作为一个 task handler，降低迁移风险。

验收：

- Web 重启不丢排队任务。
- worker 被 kill 后任务在 lease 到期后恢复。
- 重复提交同一 idempotency key 不产生重复处理。

### Phase 3：拆分 stage 与资源调度

目标：让不同主线真正可控并行。

工作项：

1. 拆出 fetch、download、transcribe、organize、note、publish、notify handler。
2. 每个 handler 定义 resource requirement。
3. GPU 使用数据库资源 lease，保留现有文件锁作为第二道保护。
4. Agnes 限流迁移到共享 limiter，保留 19 RPM。
5. scheduler 对实时监控使用更高优先级。
6. 发布索引和 GitHub sync 使用 debounce/coalesce。

验收：

- 历史研究运行时，定时监控仍能抓取和处理新内容。
- 两个博主研究可以并行下载。
- CUDA Whisper 与 Ollama 不会同时占用 GPU。
- 同一内容不会被两个 worker 同 stage 执行。

### Phase 4：发布、通知与 artifact 事务化

目标：消除“数据库成功但文件/推送失败”的模糊状态。

工作项：

1. 引入 artifact manifest 和 hash。
2. 笔记先写临时文件，再原子替换。
3. 数据库事务提交时写 outbox event。
4. publisher/notification worker 消费 outbox。
5. push 增加去重键和重放能力。
6. 清理任务依据 artifact 生命周期执行，不再依赖文件名猜测。

验收：

- 数据库重试不会重复推送同一批次。
- 发布失败可独立重试，不重新转录和整理。
- 清理不会删除尚未登记成功的产物。

### Phase 5：平台化接口与运维

目标：成为可承载后续平台和处理器的稳定底座。

工作项：

1. 定义 `SourceAdapter`、`MediaDownloader`、`Transcriber`、`Organizer`、`Publisher`、`Notifier` Protocol。
2. 抖音实现迁入 adapter，不改变当前业务能力。
3. 增加 `/health/live`、`/health/ready` 和指标端点。
4. 增加结构化日志、correlation id、task id、content id。
5. 增加备份恢复、数据保留和容量策略。
6. 建立版本化 API 和配置 schema。

验收：

- 新来源只需实现 adapter 和映射，不复制 Workflow。
- 可按 task/stage/provider 查看吞吐、延迟、失败率和 backlog。
- PostgreSQL 备份可以在空环境恢复并继续任务。

## 8. 测试方案

### 8.1 单元测试

- 状态迁移表。
- error code 分类。
- idempotency key。
- provider fallback。
- note renderer 契约。
- artifact 生命周期。
- 配置 secret 引用和原子写。

### 8.2 PostgreSQL 集成测试

- 使用临时 PostgreSQL schema 或 Testcontainers。
- 两个 worker 并发 claim，只允许一个成功。
- lease 过期后可回收。
- 成功 transcript 不被失败覆盖。
- task complete 与 outbox 同事务。
- Alembic 从 baseline 升级到最新。

### 8.3 故障注入

- 下载到一半断网。
- FunASR 500/timeout/空文本。
- Whisper OOM。
- Agnes 429/500/无效 JSON。
- Ollama 不在 GPU。
- 写笔记时进程退出。
- Git push 失败。
- worker 在每个 stage 完成前后被 kill。

### 8.4 端到端测试

使用本地 fake Douyin、fake ASR、fake Agnes、fake Feishu：

1. 提交内容。
2. 完成下载、转录、整理和笔记。
3. 验证 PostgreSQL 状态。
4. 验证唯一 Markdown 和 HTML。
5. 验证 outbox 和 push 去重。
6. 重复提交，验证无重复副作用。

### 8.5 生产验收指标

- 实时新内容成功率 >= 99%。
- task claim 重复执行率接近 0；即使重复也无重复副作用。
- worker 重启后任务恢复时间 <= lease + 1 个 polling interval。
- 定时任务错过率为 0。
- Agnes 请求不超过配置 RPM。
- GPU 冲突次数为 0。
- 失败任务均有 error code、attempt 和可重试判断。
- 发布和推送可单独重放。

## 9. 可观测性方案

核心指标：

- `task_queue_depth{stage,priority}`
- `task_duration_seconds{stage,provider}`
- `task_attempts_total{stage,result,error_code}`
- `content_pipeline_lag_seconds`
- `provider_requests_total{provider,status}`
- `provider_fallback_total{from,to}`
- `agnes_rate_limit_wait_seconds`
- `gpu_lease_seconds{consumer}`
- `artifact_bytes{kind}`
- `publish_pending_events`
- `notification_outbox_depth`

结构化日志必须至少包含：

- `task_run_id`
- `task_step_id`
- `content_id`
- `creator_id`
- `stage`
- `attempt`
- `provider`
- `error_code`
- `elapsed_ms`

告警分级：

- warning：发生 fallback 但最终成功。
- error：单条内容最终失败。
- critical：数据库不可用、任务队列停止、GPU lease 泄漏、发布连续失败或 backlog 超阈值。

## 10. 性能与容量建议

### 当前单机

- 下载并发保持 5 左右，防止抖音侧 403/限流扩大。
- CPU Whisper worker 数不要只看核心数，还要考虑每 worker 模型内存。
- Agnes 保持单并发、共享 19 RPM。
- PostgreSQL pool 从固定 5 改为按 Web/worker 数量配置。
- Web bootstrap 不应一次读取 5000 条完整内容和全部关联文本，改为服务端分页。

### 扩展顺序

1. 先拆 worker，不拆机器。
2. 再允许多个 IO worker。
3. 再把远程 AI worker 独立。
4. 最后才考虑多机 GPU worker。

不要优先引入 Kafka、Kubernetes 或全新编排框架。PostgreSQL queue、lease 和 outbox 足以覆盖当前规模，并且与现有架构最兼容。

## 11. 建议的首批工作包

### 工作包 A：安全和数据库单后端

- Secret 外置和轮换。
- PostgreSQL fail-fast。
- SQLite 运行时入口删除。
- Web 非本机监听强制认证。

### 工作包 B：Alembic 与状态统一

- Alembic baseline。
- 状态 Enum/CHECK。
- repository 收拢。
- 状态迁移测试。

### 工作包 C：持久任务 MVP

- `task_run/task_step/task_attempt`。
- 单 worker claim/lease。
- Web/CLI/scheduler 统一 submit。
- crash recovery 测试。

### 工作包 D：并行与资源租约

- stage handler。
- priority queue。
- GPU/Git/index resource lease。
- 实时监控与历史研究并行。

### 工作包 E：outbox 与发布可靠性

- artifact manifest。
- publish/notify outbox。
- 原子文件写。
- 去重、重放和独立重试。

## 12. 最终判断

KenRadar 当前的业务能力是完整且经过真实数据验证的，尤其是转录回退、AI provider fallback、研究流水线、内容笔记契约、静态发布和失败重试，已经构成很好的产品核心。

当前不应做大规模 UI 重构，也不应推倒重写 Workflow。正确路线是：

1. 先解决 secret、SQLite 回退、配置原子性和强制解锁风险。
2. 用 Alembic 和统一状态模型固定数据契约。
3. 用 PostgreSQL 持久任务、lease 和 outbox 替换进程内队列。
4. 把现有 Workflow 逐段包装成可独立重试的 handler。
5. 最后再开放多主线并行和平台 adapter。

完成 Phase 0-2 后，KenRadar 就能从“可靠的单机应用”进入“可恢复的系统底座”；完成 Phase 3-5 后，才具备稳定承载多来源、多 worker 和长期演进的能力。
