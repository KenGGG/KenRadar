# KenRadar V2 渐进演进设计

日期：2026-09-01
状态：待用户最终审阅
适用仓库：当前 KenRadar 仓库

## 0. 目标、边界与固定原则

KenRadar V2 是当前 KenRadar 的渐进演进，不是新仓库、第二套数据库或从零重写。目标是在保留成熟抖音生产链路的前提下，把产品中心从“抖音任务”调整为“来源、内容和当前处理结果”，并把小宇宙提升到经过真实验收的正式支持水平。

首发正式支持：

- 抖音：订阅监控、单链接处理、历史内容处理。
- 小宇宙：订阅监控、单链接处理、公开可访问历史内容处理。

B站和 YouTube 只要求未来能实现相同连接器契约。本轮不开发连接器、平台 UI、平台配置、抓取逻辑和生产验收。

固定架构原则：

- 本地优先、单用户、单体应用。
- 当前 PostgreSQL 是唯一事实源，通过 Alembic 渐进迁移。
- 生产任务只使用现有 `task_run + task_attempt`；不新增平行 `job` 系统。
- `task_step` 和 `outbox_event` 暂停扩展，不作为 V2 主链路依赖。
- 不引入微服务、Redis、消息队列、通用插件系统、多租户或复杂权限。
- 成熟的下载、ASR、AI provider、GPU 调度、Markdown、GitHub Pages 和飞书能力优先复用。
- 公司研究、财务研究及其数据表、API、页面和工作流保持不动。
- 不建设 KenRadar 自己的内容版本系统。Git 可以保留 Markdown 修改历史。

每条内容始终只有一套当前有效结果：

```text
content_item
├── 当前媒体：content_item.media_url/local_path/download_status
├── 当前转录：transcript（UNIQUE content_item_id）
├── 当前分析：ai_analysis（固定 analysis_type=summary）
└── 当前主笔记：content_note（固定 note_type=content）
```

`publication_log`、`push_log` 和 `task_attempt` 可以保留多条操作历史；它们是审计记录，不是内容版本。

## 1. 当前代码与 V2 需求映射

### 1.1 可以直接复用

| 能力 | 当前实现 | V2 处理 |
|---|---|---|
| 抖音解析与抓取 | `core/source_resolver.py`、`core/checker.py`、`vendor/douyin_downloader/` | 包装进 `DouyinConnector`，不重写底层客户端 |
| 抖音下载 | `core/downloader.py` | 通过连接器调用，保留已验证重试和本地缓存 |
| 小宇宙单集/RSS解析 | `sources/xiaoyuzhou/` | 补能力边界、稳定 ID、历史完整性和真实验收 |
| ASR | `core/transcriber.py`、FunASR、Whisper fallback | 提取为平台无关的处理服务，保留单一当前转录 |
| AI 整理 | `core/organizer.py`、`core/ai_json.py` | 增加处理要求输入和候选结果校验，保留 Agnes/Ollama 降级 |
| GPU 协调 | `core/gpu_scheduler.py` | 原样复用并继续作为所有本地 GPU 工作入口 |
| 笔记生成 | `core/note_writer.py`、`core/obsidian.py`、`Workflow` 内现有渲染逻辑 | 保留现有 Obsidian 结构，抽出当前主笔记渲染服务 |
| 持久任务 | `jobs/worker.py`、`jobs/handlers.py`、`storage/repositories/task_run.py` | 原表补强暂停、恢复、取消、attempt 收尾和统一任务类型 |
| GitHub Pages | `publishing/static_site.py`、`publishing/github_sync.py` | 改为独立可重试任务，不反向触发内容处理 |
| 飞书 | `notification/feishu.py` | 改为独立可重试任务，补幂等键和批次汇总 |
| WebUI | React/Vite 前端与现有 API | 小幅重组入口，不做大面积视觉重构 |

### 1.2 需要改造而非重写

1. `core/workflow.py` 已达约 3800 行。V2 只拆出与本轮直接相关的连接器路由、当前结果安全替换、发布和通知编排；不做全文件重构。
2. `storage/pg_database.py` 继续工作，但新增 V2 查询和写入进入聚焦的 repository；不再把新业务 SQL继续堆进大类。
3. `source_subscription` 已存在，但抖音仍有 YAML 导入兼容。V2 完成迁移后，数据库成为来源运行状态和策略的唯一事实源；YAML 只保留系统默认值和一次性导入兼容。
4. 通用业务 API、进度字段和前端类型从 `aweme_id`、`sec_uid` 迁移到 `content_id`、`external_source_id`。兼容路由在过渡期保留，内部新代码不再引入抖音命名。
5. `research_job` 和 `research_job_item` 继续承载历史批次，不新建 `backfill_run`；扩展为平台通用的“扫描—确认—执行”模型。

### 1.3 明确不动

- 公司研究、公司公告、财务研究相关表和业务代码。
- 当前可靠的 Agnes 19 RPM 限流、Ollama fallback、FunASR/Whisper fallback。
- 现有 Obsidian 主笔记章节约束和 `> [!summary]` 格式。
- PostgreSQL、React/Vite、本地文件存储和 `ctl.sh` 运行方式。
- 兼容视图在 V2 切换完成前继续保留，避免旧查询和旧页面立即失效。

## 2. 最小数据模型改造

原则是优先加列和约束，只在现有表无法表达独立审计记录时加表。

### 2.1 `source_subscription`：来源与默认策略

保留现表，新增：

```text
status                    active/paused/auth_required/degraded/error/disabled
is_priority               是否重点来源
next_check_at             下次应检查时间
last_success_at           最近成功检查时间
consecutive_failures      连续失败次数
default_analysis_profile  standard/deep/plain/transcript_cleanup/custom
default_instruction       来源级默认附加要求
auto_publish              是否处理后自动发布
review_required           是否要求人工审核，默认 false
notify_mode               new_content/batch_only/off
media_retention_policy    delete_after_transcript/retain_forever/retain_days/retain_favorite_only
media_retention_days      retain_days 使用的天数
history_capability        full/limited/unknown
```

平台原始信息、RSS URL、解析细节和能力诊断继续放在 `extra JSONB`，不为每个平台增加列。

### 2.2 `content_item`：统一内容身份和当前媒体

现有 `(platform_id, content_id)` 唯一约束继续使用。`content_id` 是平台稳定外部内容 ID；新增业务代码称其为 `external_content_id`，数据库本轮不做破坏性改名。

新增：

```text
discovery_source       subscription/manual_url/history
discovered_at          首次发现时间
review_status          not_required/pending/approved/rejected
current_error_code     当前需要用户关注的标准错误码
current_error_message  当前错误摘要
media_sha256           当前媒体完整性校验，可为空
media_size_bytes       当前媒体大小
media_deleted_at       按策略清理时间
```

继续使用现有 `media_url`、`local_path`、`download_status` 表示唯一当前媒体，不新增 `media_asset` 表。

### 2.3 `transcript`：唯一当前转录

继续保持 `UNIQUE(content_item_id)`。新增：

```text
source_type       official_subtitle/embedded_subtitle/external_subtitle/asr
quality_score     0-100，可为空
quality_details   JSONB，保存确定性质量检查结果
input_sha256      当前媒体或字幕输入摘要
completed_at      当前成功转录完成时间
```

重新转录使用候选结果，完整链路成功前不覆盖当前行。

### 2.4 `ai_analysis`：唯一当前分析

继续使用现有 `UNIQUE(content_item_id, analysis_type)`，V2 主链固定 `analysis_type='summary'`。不新增 `analysis_run` 或 `processing_profile` 表。

新增：

```text
profile_name       standard/deep/plain/transcript_cleanup/custom
user_instruction   本次当前有效的用户要求
prompt_version     稳定的提示模板版本
transcript_hash    分析所基于的当前转录摘要
result_hash        结构化结果摘要
completed_at       当前成功分析完成时间
```

系统内置 profile 放在代码/配置中；来源默认 profile 放在 `source_subscription`；单次自定义要求放在任务 payload，并在成功替换后写入当前 `ai_analysis`。

### 2.5 `content_note`：唯一当前主笔记

继续保持 `UNIQUE(content_item_id, note_type)` 和固定 `note_type='content'`。新增：

```text
content_sha256        当前文件摘要
analysis_result_hash  渲染所基于的分析摘要
rendered_at           最近完整生成时间
```

每条内容路径由 `platform + creator slug + year + content_id` 稳定决定；标题变化和重新分析不改变路径。

### 2.6 `publication_log`：唯一新增业务表

GitHub 发布需要独立重试和审计，现有表无法可靠表达，新增：

```text
id
content_item_id       单内容发布可用；批次发布可为空
research_job_id       批次发布可用；单内容发布可为空
channel               github_pages
idempotency_key       唯一
status                pending/running/success/failed
source_hash            发布输入摘要
target_url
commit_sha
attempt_count
last_error
created_at/updated_at/published_at
```

同一内容、同一 `source_hash` 只产生一个成功发布语义；内容变化后允许新的发布记录。

### 2.7 `push_log`：通知审计补强

保留多条历史，新增 `idempotency_key`、`research_job_id`、`target_url` 和 `attempt_count`。对幂等键建立部分唯一索引。飞书失败只重试通知任务。

### 2.8 `research_job` / `research_job_item`：历史扫描计划

不新增回溯表。扩展 `research_job`：

```text
source_subscription_id
scope_type             all/since/recent_n/selected
scope_json             范围参数
status                 新增 scanning/awaiting_confirmation/queued
discovered_count
existing_count
selected_count
confirmed_at
confirmed_by           固定为 local_user
```

扩展 `research_job_item`：

```text
external_content_id    通用外部内容 ID
selected               用户是否选择处理
existing_before_scan   扫描时是否已完整处理
raw_metadata           扫描快照
```

保留 `aweme_id` 兼容列，但 V2 新代码只写 `external_content_id`，兼容层按平台需要同步旧列。

## 3. 抖音 / 小宇宙连接器

### 3.1 小而显式的契约

不建设自动插件发现。使用显式映射：

```python
CONNECTORS = {
    "douyin": DouyinConnector,
    "xiaoyuzhou": XiaoyuzhouConnector,
}
```

连接器协议只包含首发需要的能力：

```python
class SourceConnector(Protocol):
    platform: str

    def match_url(self, url: str) -> bool: ...
    def resolve_source(self, url: str) -> SourceDescriptor: ...
    def resolve_content(self, url: str) -> ContentDescriptor: ...
    def list_recent(self, source: SourceDescriptor, cursor: str | None = None) -> ContentPage: ...
    def list_history(self, source: SourceDescriptor, cursor: str | None = None) -> ContentPage: ...
    def download(self, content: ContentDescriptor, target_dir: Path) -> DownloadResult: ...
```

`ContentPage` 明确返回 `items`、`next_cursor`、`has_more` 和 `history_capability`。通用服务只认识平台、外部 ID、标题、时间、媒体类型、URL 和 `raw_metadata`。

### 3.2 抖音连接器

`DouyinConnector` 包装现有解析器、checker、downloader 和本地 vendor 客户端：

```text
sec_uid   -> SourceDescriptor.external_source_id
aweme_id  -> ContentDescriptor.external_content_id
desc      -> title/description
作品 JSON -> raw_metadata
```

抖音 Cookie、短链、置顶作品和分页细节只停留在连接器内部。原有功能先通过适配器保持等价，再逐个把 `Workflow` 的通用路径切到新接口。

### 3.3 小宇宙能力现状

| 能力 | 当前判断 | 证据与缺口 |
|---|---|---|
| 单集 URL 解析 | 已实现 MVP | `page_parser.py` 可读公开 `__NEXT_DATA__`，有 fixture 测试；需要真实 URL 和页面变化验收 |
| 节目主页解析 | 部分实现 | 可从页面内嵌数据找到节目与若干单集；没有完整分页和完整性保证 |
| 音频下载 | 已实现 MVP | 支持 mp3/m4a/aac/wav、临时文件和本地复用；需真实长音频、重定向、超时和完整性验收 |
| 定时订阅 | 部分实现 | 已有 `source_subscription`、手动检查 API 和任务 handler；主 scheduler 未自动按 `next_check_at` 调度小宇宙 |
| 新单集发现 | 部分实现 | 依赖取回列表和数据库转录去重；缺明确 checkpoint、乱序/置顶处理和真实重复检查验收 |
| 历史节目枚举 | 待开发 | 页面只处理当前内嵌数据；RSS 可枚举 feed 已提供内容，但无完整性标记、分页或扫描确认流程 |
| RSS 支持 | 已实现 MVP | 可解析 RSS 2.0 enclosure、GUID、时间和时长；缺 feed discovery、Atom 兼容边界和真实 feed 验收 |
| 全链路处理 | 部分实现 | 单集可下载、转录、分析、写笔记、可选发布/推送；生产验证、独立发布重试和批次流程不足 |

### 3.4 小宇宙首发完成定义

1. 单集 URL 能解析稳定 episode ID、节目 ID、标题、时间、时长、音频和 canonical URL。
2. 节目主页能解析节目身份并优先发现公开 RSS；找不到 RSS 时明确 `history_capability=limited`。
3. RSS 使用 GUID，必要时回退 canonical URL 或音频 URL 摘要作为稳定 ID。
4. 定时器按数据库 `next_check_at` 入队 `check_source`，连续检查不生成重复内容。
5. 历史扫描只承诺“当前公开可枚举内容”；受限时在 UI 和批次结果显示 `limited`，不得显示“完整历史已处理”。
6. 不使用高风险登录 Token 或未公开私有接口强求完整历史。

## 4. `task_run + task_attempt` 补强

### 4.1 当前能力审计

| 能力 | 当前状态 | 结论 |
|---|---|---|
| 持久化 | 已具备 | 任务、payload、状态、进度、统计和 attempt 均在 PostgreSQL |
| 幂等 | 部分具备 | 有唯一 `idempotency_key`，但调用覆盖不完整，永久 key 语义不适合所有人工重跑 |
| 优先级 | 已具备 | claim 按 `priority DESC, available_at, created_at, id` |
| 崩溃恢复 | 部分具备 | lease 过期可重新排队或失败；遗留 attempt 没有完整标记，业务步骤仍需自身幂等 |
| 重试 | 已具备基础 | 有 `attempt/max_attempts/retry_wait/available_at`；退避和错误分类较粗 |
| 暂停 | 通用能力缺失 | 只有 `research_job` 暂停，`task_run` 无 paused 状态和 pause request |
| 继续 | 部分具备 | 研究任务通过新建 restart task 接续，不是统一的原任务恢复 |
| 取消 | 部分具备 | 有 cancel request；worker 主要在执行前后检查，长任务依赖内部检查点 |

结论：现有底座可用，不新建系统；先补缺口再承载 V2。

### 4.2 最小字段和状态补充

给 `task_run` 增加：

```text
pause_requested_at
paused_at
resumed_at
error_code
checkpoint_json
parent_task_run_id   仅用于明确的重试/派生审计，可为空
```

状态增加 `paused`。不增加 DAG 和 stage 表依赖。

### 4.3 行为补强

- `enqueue_task_run` 的幂等键按操作语义生成：定时检查使用“来源+计划窗口”，发布使用“内容+source_hash”，通知使用“事件+目标”，用户明确重新分析使用新的 request UUID。
- claim 回收过期 lease 时，同一事务把未结束的 `task_attempt` 标记为 `abandoned`，记录 `WORKER_LEASE_EXPIRED`，再决定重新排队或最终失败。
- 重试采用有限指数退避，并区分可重试错误与永久错误。`AUTH_REQUIRED`、`CONTENT_PRIVATE`、`CONTENT_DELETED` 不自动重试。
- 暂停和取消采用合作式检查：历史任务至少在“扫描页结束、单条内容开始、下载完成、转录完成、AI 完成、发布前”检查控制信号。
- 暂停时保存 `checkpoint_json`，清除 lease 并进入 `paused`；继续操作把同一 `task_run` 设回 `queued`，保留 attempt 历史。
- 取消排队任务立即终止；运行任务在最近安全边界退出。UI 明确显示“已请求”和“已停止”是两个状态。
- worker 不把业务返回的 `paused` 或 `cancelled` 误记为成功。
- 历史执行按有界小批次运行，默认每个 `task_run` 处理一条内容。每个小批次完成后更新 `research_job` checkpoint，并以新的幂等键入队下一小批次。这样高优先级任务无需强杀正在运行的 ASR，也能在内容边界自然插队；暂停批次时不再创建后续小批次。

### 4.4 固定优先级

| 优先级 | 类型 |
|---:|---|
| 100 | 用户手动单链接 |
| 90 | 定时发现的新内容 |
| 80 | 用户手动重试、重新分析、重新转录 |
| 60 | GitHub 和飞书重试 |
| 20 | 历史扫描与历史批量执行 |
| 10 | 清理、索引和低优先级维护 |

单 worker 不能中断正在执行的重型模型调用；所谓优先是安全边界后的队列顺序。历史任务必须在单条内容边界让出 worker，不能一次 claim 后无期限占用整个批次。

## 5. 三种用户入口

### 5.1 订阅来源

1. 用户提交抖音主页或小宇宙节目/RSS URL。
2. 显式 connector 解析来源并展示预览。
3. 用户确认后写入 `creator + source_subscription`。
4. scheduler 查询 `enabled=true AND next_check_at<=NOW()` 的来源，逐来源入队 `check_source`。
5. connector 拉取近期内容，按 `(platform_id, content_id)` 去重。
6. 新内容写入数据库并入队 `process_content`；无更新只更新检查时间，不生成空内容任务。

抖音 YAML 来源在迁移期导入数据库；V2 页面不再反向修改 `config.yaml`。

### 5.2 单链接处理

统一入口 `POST /api/content/process-url`：

```text
URL
+ profile_name
+ user_instruction
+ publish_policy
+ notify_policy
```

系统自动选择连接器。已存在内容时：

- 当前转录成功且用户未要求重新转录：复用转录。
- 当前分析和要求一致：返回现有结果，除非用户明确重新分析。
- 用户要求不同或明确重新分析：入队 `reanalyze_content`。
- 不因重新分析重新下载或 ASR。

### 5.3 历史内容处理

历史处理严格拆成两次用户动作：

```text
创建扫描任务
→ connector 分页枚举并写 research_job_item
→ 状态 awaiting_confirmation
→ UI 显示发现总数、已处理数、待处理数、能力限制
→ 用户选择范围并确认
→ 入队 execute_backfill
```

取消未确认扫描不下载任何媒体。执行阶段逐条复用现有内容和结果，支持暂停、继续、取消与服务重启恢复。默认只在批次结束后创建一次飞书汇总任务。

## 6. 内容处理流水线

### 6.1 统一生命周期

```text
resolve/identify
→ upsert metadata
→ ensure current media
→ ensure current transcript
→ generate candidate analysis
→ render and validate candidate Markdown
→ safely replace current analysis and note
→ enqueue optional publication
→ enqueue optional notification
→ apply media retention policy
```

每个阶段先检查当前成功状态和输入摘要。可复用就跳过；只有用户明确“重新转录”时才绕过转录复用。

### 6.2 重新分析：成功后替换

```text
读取当前成功 transcript
→ 使用新 profile/instruction 调用 AI
→ 校验结构化结果和降级状态
→ 在目标文件同目录写 Markdown 临时文件
→ 校验 frontmatter、章节、内容 ID 和摘要
→ 获取 content:{id}:current-result resource lease
→ 原笔记临时备份，os.replace 写入候选笔记
→ 数据库事务 upsert 当前 ai_analysis/content_note/hash
→ 提交成功后删除临时备份
```

AI 或 Markdown 候选失败时不触碰当前成功记录。文件替换后数据库提交失败时立即恢复备份；若进程恰在两者之间崩溃，启动对账根据 `content_note.content_sha256` 和遗留临时备份恢复旧文件。临时备份只用于事务恢复，不是内容版本。

重新分析只有结构化校验通过且 `status=success` 才能替换旧成功结果。provider 全部失败后生成的降级内容仍满足现有“必须留下可诊断降级笔记”的要求：首次处理没有旧成功结果时可以成为明确标记的降级结果；重新分析已有成功结果时，降级候选只写任务错误和 attempt 审计，不覆盖旧结果。

### 6.3 明确重新转录：当前结果包原子替换

为避免“新转录配旧分析”的不一致，重新转录被定义为一次当前结果包替换：

```text
现有媒体或重新获取媒体
→ 生成并校验候选 transcript
→ 基于候选 transcript 生成候选 analysis
→ 生成并校验候选 Markdown
→ 在同一资源租约内替换 transcript + ai_analysis + content_note
```

任一步失败，当前转录、分析和笔记全部保留。只有整套候选结果成功后才替换当前结果。这是对“重新转录成功后再生成当前分析和主笔记”的一致性实现。

### 6.4 发布和通知解耦

- 当前结果完成后，根据策略直接在 `task_run` 入队 `publish_content` 和/或 `notify_content`。
- 当前分析/笔记数据库更新与后续 `task_run` 插入使用同一 PostgreSQL 事务；不借助 `outbox_event`。启动对账只负责修复外部文件替换被进程中断的极小窗口。
- 需要“发布后通知”时，发布成功后再入队通知，通知 payload 携带已发布 URL。
- 发布失败只更新 `publication_log` 并重试发布任务。
- 飞书失败只更新 `push_log` 并重试通知任务。
- 两类失败都不得调用下载、ASR 或 AI。
- 人工审核仅在 `review_required=true` 时阻止自动发布；默认 `not_required`。

### 6.5 错误码

首发统一：

```text
AUTH_REQUIRED
CONTENT_PRIVATE
CONTENT_DELETED
REGION_RESTRICTED
RATE_LIMITED
SOURCE_PARSE_CHANGED
METADATA_FAILED
DOWNLOAD_FAILED
MEDIA_INVALID
TRANSCRIPT_EMPTY
TRANSCRIPT_LOW_QUALITY
AI_PROVIDER_FAILED
AI_SCHEMA_INVALID
NOTE_VALIDATION_FAILED
GITHUB_BUILD_FAILED
GITHUB_PUSH_FAILED
FEISHU_SEND_FAILED
WORKER_LEASE_EXPIRED
```

错误码由 connector 或对应处理服务产生，通用任务层只决定状态、重试和展示。

## 7. WebUI

沿用 React/Vite 和现有设计语言，不做大面积视觉重构。导航收敛为六个工作入口：

1. **今日雷达**：今日发现、高价值、处理中、失败、待审核、已发布。
2. **订阅来源**：抖音和小宇宙统一列表；添加、预览、启停、立即检查、编辑默认策略、发起历史扫描。
3. **处理链接**：统一 URL 输入、处理模板、自定义要求、发布和通知选项。
4. **内容库**：平台、来源、日期、主题、当前处理状态、审核状态、发布状态筛选。
5. **批次任务**：扫描结果确认、进度、能力限制、暂停、继续、取消、失败条目重试。
6. **系统与监控**：现有配置、依赖健康、任务运行、发布记录、通知记录、告警和日志。

内容详情只展示当前媒体、当前转录、当前分析和当前主笔记，不提供版本列表、比较或恢复功能。允许的操作：

- 使用新要求重新分析。
- 明确重新转录。
- 重新生成当前笔记。
- 审核通过/拒绝（仅启用审核策略时）。
- 单独发布、重新发布和重发飞书。
- 查看 publication、push 和 task attempt 操作历史。

兼容 `/aweme?id=...`，新增通用 `/content?id=<database id>`；前端切换完成后旧路由重定向到通用详情。

## 8. PostgreSQL / Alembic 渐进迁移

当前最新迁移为 0013。建议按可独立回滚的顺序执行：

### 0014：任务控制补强

- 扩展 `task_run` 字段和 paused 状态约束。
- 扩展 `task_attempt` 支持 `abandoned` 与标准错误码。
- 增加 claim/recovery 所需索引。
- 不改 `task_step/outbox_event`。

### 0015：当前内容结果字段

- 扩展 `source_subscription`、`content_item`、`transcript`、`ai_analysis`、`content_note`。
- 用确定性 SQL 回填默认状态、hash 可计算部分和来源策略默认值。
- 不删除旧列，不改变现有唯一约束。

### 0016：通用历史批次

- 扩展 `research_job/research_job_item` 扫描确认字段。
- 从 `aweme_id` 回填 `external_content_id`。
- 保留旧列和旧 API 的兼容写入。

### 0017：发布和通知幂等

- 新建 `publication_log`。
- 扩展 `push_log` 并建立幂等索引。
- 回填历史 push 记录时不伪造幂等键。

### 迁移规则

- 每次迁移先在测试数据库验证 upgrade，再用生产备份副本演练。
- 迁移只做加法和确定性回填；V2 首发周期不删除表和旧列。
- 应用在迁移过渡期双读兼容、单写新字段；不长期双写两套业务模型。
- `schema_guard` 必须阻止旧 schema 启动新 worker。
- 回滚只回滚应用版本和本次新增对象，不破坏已有内容、公司研究或财务研究数据。

## 9. 实施里程碑

### M0：基线冻结与真实样本清单

交付：修复项目环境中的 `python-multipart` 缺失，完整测试恢复全绿；确定抖音主页/视频、小宇宙节目/单集/RSS 的真实验收样本；记录当前生产表行数和任务状态。
门禁：无业务改动，现有抖音链路、Web、worker、Pages 和飞书可复现。

### M1：任务底座补强

交付：0014、通用 pause/resume/cancel、过期 attempt 收尾、错误分类、优先级和 checkpoint 测试。
门禁：杀死 worker 后任务可恢复；暂停后重启服务仍保持暂停；继续处理不重复已完成条目。

### M2：通用连接器与来源事实源

交付：统一 descriptor/protocol、`DouyinConnector` 包装、`XiaoyuzhouConnector` 整理、数据库来源调度、抖音 YAML 一次性导入兼容。
门禁：抖音现有发现数量和下载结果无回归；新业务代码不暴露 `aweme_id/sec_uid`。

### M3：当前结果安全替换

交付：0015、平台无关处理服务、重新分析、明确重新转录、稳定 Markdown 路径、故障补偿和启动对账。
门禁：在 AI、笔记写入和数据库提交位置注入失败，旧成功结果均保持可读。

### M4：统一单链接垂直链路

交付：通用 URL API、Web 处理链接页、抖音和小宇宙单链接处理、重复提交复用。
门禁：两个平台各以真实公开链接完成元数据、媒体、转录、分析和笔记；重复提交不重复下载/ASR。

### M5：订阅雷达

交付：按 `next_check_at` 的逐来源调度、两平台增量检查、checkpoint、来源状态和 Web 策略编辑。
门禁：连续检查两次不重复；小宇宙新单集可由 scheduler 自动发现，不依赖手动按钮。

### M6：扫描—确认—执行的历史处理

交付：0016、通用历史扫描、确认页面、批次执行、暂停/继续/取消、优先级让行和批次汇总。
门禁：未确认前无下载；worker 重启后从数据库继续；手动链接和新内容先于历史任务执行。

### M7：发布与通知独立化

交付：0017、独立 GitHub/飞书任务、publication/push 审计、幂等重试和批次一次通知。
门禁：GitHub 或飞书故障不触发下载、ASR、AI；恢复后可从失败阶段单独重试。

### M8：WebUI 收敛与双跑切换

交付：六入口信息架构、通用内容详情、兼容路由、抖音小样本双跑、小宇宙能力标识和运维文档。
门禁：V2 指标与 V1 对账完成后，入口逐步切换；旧字段和兼容视图暂不删除。

建议一个里程碑一个独立实施计划和验收记录。M1—M4 构成可用的单链接核心，M5—M7 完成正式 V2，M8 负责安全切换。

## 10. 真实验收标准

### 10.1 任务底座

1. 相同幂等键并发提交只得到一个有效任务。
2. 优先级 100/90 的待执行任务先于历史优先级 20 claim。
3. worker 在下载、转录、AI 前后被强制终止，lease 到期后能够恢复且不产生重复当前结果。
4. 过期 attempt 标记 `abandoned`，新 attempt 编号连续且原因可查。
5. 历史任务暂停后重启 Web 和 worker仍保持暂停；继续后从 checkpoint/待处理条目恢复。
6. 取消请求在最近安全边界生效，已成功内容不回滚，未开始条目不执行。

### 10.2 抖音

1. 真实主页解析稳定 `external_source_id`，近期与历史列表去重正确。
2. 真实视频链接完整走通下载、FunASR/Whisper、Agnes/Ollama、当前笔记。
3. 定时检查、单链接和历史扫描产生相同通用内容身份。
4. 置顶旧作品和页面顺序变化不重复入队。

### 10.3 小宇宙

1. 真实公开单集 URL 能解析节目和单集稳定 ID、元数据及音频。
2. 真实节目主页能识别节目；能发现 RSS 时保存 feed，不能时标记 limited。
3. 至少一个真实 RSS 能连续检查并只发现新增 GUID。
4. 一集长音频完整完成下载、ASR、AI 和 Obsidian 笔记。
5. 历史扫描报告 feed 可枚举数量；无法证明完整时显示 `history_limited`。
6. 页面结构改变或解析为空时返回 `SOURCE_PARSE_CHANGED`，不误报“没有更新”。

### 10.4 当前结果与失败保护

1. 用新要求重新分析时不访问媒体下载器和 ASR。
2. AI 失败保留旧 `ai_analysis` 和旧 Markdown。
3. Markdown 校验或原子替换失败保留旧分析和旧文件。
4. 重新转录任一步失败保留旧 transcript、analysis 和 note；全部成功后同时切换到一致的新结果。
5. 每条内容始终只有一个成功 transcript、一个当前 summary、一个主 note 路径。

### 10.5 三种入口和批次

1. 两个平台都能添加订阅、处理单链接并创建历史扫描。
2. 历史扫描先显示总数、已处理数、待处理数；未确认时媒体下载数为零。
3. 历史任务单条失败不终止批次；失败项可以独立重试。
4. 历史任务运行期间，新内容与手动链接在下一个安全边界优先执行。
5. 历史批次默认只产生一条完成汇总，不逐条飞书推送。

### 10.6 发布、通知和安全

1. GitHub 失败只创建/重试 `publish_content`，下载、转录和 AI 调用计数不增加。
2. 飞书失败只创建/重试 `notify_content` 或 `notify_batch`，不重新发布和处理内容。
3. 相同发布输入不产生空 Git commit；相同通知幂等键不重复发送。
4. 未审核内容仅在来源启用 `review_required` 时等待审核；默认流程不被审核阻塞。
5. Cookie、API Key、Webhook、数据库密码、完整媒体和未授权完整转录不进入公开仓库或日志。

### 10.7 非回归

1. Python 完整测试、compileall、前端 lint/build 全部通过。
2. 真实 PostgreSQL 的 dashboard、content-items、来源管理和健康接口继续可用。
3. 现有 Obsidian frontmatter、summary callout、知识关联、分段原文和原始转录章节保持兼容。
4. 公司研究、财务研究相关测试、表、API 和页面无行为变化。
5. `ctl.sh start/restart/stop/status`、独立 worker、FunASR 生命周期和 GPU 锁无回归。

## 11. 最终架构结论

V2 不再复制附件中“独立数据库、完整重写、多内容版本”的方案。它在当前系统上做四项聚焦改变：

1. 用两个显式连接器把抖音和小宇宙接入同一内容生命周期。
2. 用现有唯一约束维持一套当前媒体、转录、分析和主笔记，并以候选结果和成功后替换保护旧成果。
3. 补强现有 `task_run + task_attempt`，使历史扫描、确认、暂停、恢复、优先级和崩溃恢复成为生产能力。
4. 把 GitHub 和飞书变成独立、幂等、可审计的末端任务，失败不反向重跑内容处理。

所有变化都限定在媒体雷达领域，并通过 Alembic 加法迁移逐步上线。
