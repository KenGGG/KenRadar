# AGENTS.md

## 当前状态

- KenRadar 是本地化 AI 信息雷达系统，不是纯下载脚本。
- 最新愿景是建设“本地优先、证据可追溯、可恢复的个人研究情报操作系统”，连接来源、内容、处理状态、知识资产、发布结果和长期质量信号。
- 当前成熟生产链路聚焦抖音视频作品；小宇宙节目 / 单集 / RSS 已有研究与订阅监控 MVP，但成熟度、数据覆盖和生产验证仍低于抖音。
- 系统能力包括来源监控、作品抓取、媒体下载、FunASR / Whisper 转录、Agnes AI 主引擎整理、Docker Ollama / qwen 备用整理、Obsidian Markdown 笔记、PostgreSQL 状态存储、GitHub Pages 静态 HTML 发布、飞书 Card/Text 推送、Web 后台、研究任务、失败重试和内置定时调度。
- 产品和运行时事实以当前代码、`config/config.yaml`、`README.md` 和本文件为准。
- 创建模块、配置、命令或数据库 schema 时，应延续现有架构，不要另起一套系统。
- 所有运行时代码必须位于当前仓库内；不要通过 `sys.path`、绝对路径或导入访问当前文件夹外的项目文件。

## 当前体检结果

截至 2026-07-16：

- Web 演进代码与目标文档已提交到本地 `main`；工作区剩余主要是运行生成的 `docs/` 内容产物和构建元数据，不应混入功能提交。
- 工作区存在运行后生成的 `docs/notes/`、`docs/briefs/` 和索引变化；它们是内容产物，未确认前不要删除或与 Web 代码混合提交。
- 当前控制脚本为 `./ctl.sh`；旧 `kenradarctl.sh` 在工作区已删除。脚本内部帮助文本仍可能显示旧名称，以真实文件名为准。
- `./ctl.sh status` 显示 Web 与 worker 正在运行。
- `/api/status` 可访问，当前可能有研究任务和队列任务运行中。
- `python -m compileall kenradar scripts` 通过。
- 完整测试集合共 `140 passed`；`tests/conftest.py` 已隔离仓库 `.env` 对测试进程的污染。
- 前端 `npm run lint` 与 `npm run build` 通过；Vite 已启用 vendor 分包，主应用 chunk 约 442KB、vendor chunk 约 422KB。
- `python -m kenradar --help` 在项目运行环境中正常。
- `/health/live`、`/health/ready` 和 `/health/dependencies` 可访问；当前 PostgreSQL/GPU 正常，飞书已配置，Ollama 可显示为未配置。
- `/api/dashboard/overview` 和 `/api/content-items` 已在真实 PostgreSQL 返回数据，内容接口 cursor 第二页已验证。
- 来源洞察迁移已到 0011，既有 creator 已回填为 26 个来源、20 个启用；7 天聚合已写入 140 条日指标和 274 条主题指标。
- SSE 后端和前端降级逻辑已接线，35 秒 heartbeat、重启前后重新 connected 和 broadcaster 清理测试均通过。

## 产品流程

当前主流程：

```text
抖音博主 -> 定时/手动检测 -> 抓取作品列表 -> 去重 -> 下载视频 -> FunASR 转录 -> Whisper 兜底 -> AI 生成结构化摘要/评分/标签 -> 生成单一 Obsidian 内容笔记 -> 写入 PostgreSQL -> 生成 docs/ HTML -> 按推荐动作筛选飞书简报 -> Web 后台查看详情
```

每条视频最终只生成一份 Obsidian 内容笔记，结构固定为：

- YAML frontmatter
- `一、内容简述`
- `二、分段原文`
- `三、知识关联`
- `四、视频原始转录`

内容笔记 frontmatter 必须包含：`type`、`platform`、`creator`、`creator_id`、`video_id`、`source_url`、`original_title`、`title`、`published_at`、`ai_model`、`transcript_model`、`topics`、`tags`、`status`、`value_score`。

规则：

- `video_id` 必须作为字符串写入 YAML。
- YAML 字符串必须正确转义。
- 一句话结论使用 Obsidian callout：`> [!summary]`。
- “知识关联”小节集中使用 `[[wikilinks]]`。
- 正文不要全文自动替换双链；外部 URL 不要写成 `[[URL]]`。
- `topics` 控制在 5-10 个左右，只保留可长期复用的主题、行业、概念、资产类别、机构类型。
- `tags` 默认包含 `KenRadar`、`视频笔记`、平台名，并可补充少量主题。
- `二、分段原文` 保持博主原意和论述顺序，由 organizer 在同一次请求中完成错别字/ASR 错误修正、自然分段和段落标题生成；不得摘要、删减、扩写或补充事实。
- `四、视频原始转录` 保留未经整理的 ASR 原文，在 GitHub Pages HTML 中默认折叠。
- 转录原文只出现在 Web 详情页和最终内容笔记中，不进入飞书推送。
- 飞书推送定位为精简资讯流，不推送 YAML、frontmatter、完整转录原文或完整 AI 整理文章。

## 当前 Web 后台

Web 后端位于 `kenradar/web/`。如果 `kenradar/web/frontend/dist/` 存在，后端优先服务 React/Vite 前端；否则回退到 `kenradar/web/templates.py` 中的服务端 HTML。

页面分组：

- 仪表盘 / 情报概览：服务端组合筛选、决策指标和趋势/流水线图表
- 内容工作台：内容任务、失败重试
- 归档研究：内容资料库、研究任务、Markdown 笔记、简报
- 来源管理：博主管理、来源解析、来源质量
- 来源洞察：来源日指标、质量与价值趋势；当前仍处于真实数据验收阶段
- 系统配置
- 系统监控：系统状态、推送记录、系统告警、运行日志

当前 UX 约束：

- 首页和内容详情页不再暴露收藏、选题池、深度研究、备注等旧入口。
- 内容详情页采用 Markdown 正文 + 信息概览/操作区；转录原稿可折叠查看。
- `/file?path=...` 应尽量重定向到统一 `/aweme?id=...` 详情页。
- 归档卡片以阅读为主，维护动作集中到详情页、失败重试页或研究任务详情页。
- 不要做大面积前端视觉重构，除非用户明确再次要求。

## 核心模块

- `kenradar/core/checker.py`：读取配置中的博主，使用本地化抖音客户端抓取作品。
- `kenradar/core/source_resolver.py`：根据抖音主页 URL、短链、视频链接解析来源信息并补齐配置。
- `kenradar/core/downloader.py`：下载视频和作品 JSON 元数据。
- `kenradar/core/transcriber.py`：优先调用 FunASR OpenAI-compatible 服务；质量不足或失败时直接回退 faster-whisper / Whisper，并保存 `.transcript.txt` 和 `.transcript.json` 中间文件。Qwen3-ASR 当前禁用。
- `kenradar/core/organizer.py`：优先调用 Agnes AI `agnes-2.0-flash`，按 provider 的 `rpm_limit: 19` 控制免费额度请求速率；Agnes 缺少 Key、限流或服务异常时回退 Docker Ollama 上的 `qwen3.5:9b`；要求输出 JSON 摘要、评分、标签和推荐动作；全部失败时生成降级结果。
- `kenradar/core/ai_json.py`：AI JSON 解析、松散修复和本地 fallback 分析。
- `kenradar/core/gpu_scheduler.py`：协调 FunASR、Whisper 与 Docker Ollama 的 GPU 使用，并保留 Qwen3-ASR 兼容分支；提供跨进程文件锁、显存检测、阶段切换和 OOM 降级策略。
- `kenradar/core/workflow.py`：编排抓取、下载、转录、AI 整理、Obsidian 笔记生成、GitHub Pages 发布、研究任务、旧笔记升级、失败重试和推送。
- `kenradar/core/analytics.py`：来源日指标确定性聚合；当前尚未注册到主 CLI。
- `kenradar/publishing/static_site.py`：将 `data/notes/` 和 `data/briefs/` 下的 Markdown 转为 `docs/` HTML，并维护 `docs/index.html`。
- `kenradar/notification/feishu.py`：生成流媒体更新简报 Markdown，并推送飞书 Card/Text；负责按推荐动作/价值评分筛选推送项，链接优先指向 GitHub Pages。
- `kenradar/scheduler/scheduler.py`：定时调度；Web 启动时也会拉起内置调度器。
- `kenradar/web/`：本地 Web 信息雷达后台；`routes/`、`router.py`、`responses.py`、`helpers.py` 已承担部分从 `app.py` 拆出的职责。
- `kenradar/web/sse.py` 与 `routes/stream.py`：研究任务 SSE 广播和端点，当前待真实稳定性验收。
- `kenradar/storage/pg_database.py`：PostgreSQL schema、兼容视图和读写逻辑。

## 外部依赖

- 抖音 API 和下载逻辑已本地化到 `kenradar/vendor/douyin_downloader/`；继续复用这些本地文件，不要再引用仓库外的 `douyin-downloader`。
- FunASR 服务由仓库内 `scripts/funasr_openai_server.py` 封装，默认监听 `http://127.0.0.1:18002/v1`，模型组合为 `paraformer-zh`、`fsmn-vad`、`ct-punc`。
- `./ctl.sh start` 默认会先启动 FunASR；可用 `KENRADAR_FUNASR_MANAGED=0` 禁用托管。
- Qwen3-ASR 当前已禁用，不属于生产转录链路；保留相关兼容代码与配置结构，但不要自动启动容器。
- Whisper 是最终兜底，默认在 conda 环境 `openclaw` 中运行 `large-v3-turbo`，当前配置使用 faster-whisper CPU / int8，以稳定为先。
- AI 整理主 provider 使用 Agnes AI OpenAI-compatible Chat Completions，endpoint 为 `https://apihub.agnes-ai.com/v1`，API Key 通过 `AGNES_API_KEY` 环境变量提供。
- Agnes 免费额度按 `rpm_limit: 19` 控制；批量研究博主时，AI 整理阶段应排队处理，不要绕过 provider 限流或提高并发冲击 20 RPM 限制。
- Docker Ollama 的 `qwen3.5:9b` 是备用 organizer provider；不要删除本地 qwen fallback。
- Ollama 是外部 Docker HTTP 服务，KenRadar 只调用 `http://127.0.0.1:11434/v1` 或配置中的 endpoint。
- 不要在 KenRadar 中安装、启动或管理 Ollama，不要新增系统级 Ollama 依赖。
- 如果 Ollama 没有使用 GPU，应检查 Docker 容器 GPU 运行环境和 Ollama 日志，而不是在主机上另起 Ollama。
- 所有会占用本地 GPU 的任务应通过 `GpuResourceManager` 或现有服务协调；不要绕过 GPU 文件锁直接并发调用 CUDA Whisper 或本地 Ollama。
- API 失败时必须生成降级笔记并记录错误；不得把转录原文当摘要推送；降级结果不得伪装成成功摘要。

## 数据与配置

- 配置路径：`config/config.yaml`。
- 运行时数据根目录：`data/`。
- PostgreSQL 由 `DATABASE_URL` 或 `app.database_url` 配置。
- 下载目录：`data/Downloaded/`，仅作为处理中转目录；内容笔记和数据库写入成功后应清理原始视频、转录 txt/json 等临时文件。
- Obsidian 输出根目录：`data/`。
- GitHub Pages 静态输出目录：`docs/`。
- 当前 Markdown 输出结构：
  - 内容笔记：`data/notes/<platform>/<blogger_name>/`
  - 流媒体简报、周报、研究报告：`data/briefs/`
  - 维护任务日志：`data/logs/`
- 主要 PostgreSQL 逻辑表包括：`platform`、`creator`、`content_item`、`transcript`、`ai_analysis`、`content_note`、`content_curation`、`push_log`、`alert_log`、`research_job`、`research_job_item`。
- 持久任务相关表包括：`task_run`、`task_attempt`、`task_step`、`state_transition`、`artifact`、`outbox_event`、`resource_lease`。
- 来源订阅与洞察表包括：`source_subscription`、`source_daily_metrics`；后者须在迁移和回填验证完成后才能作为生产统计依据。
- 兼容视图/命名包括：`blogger`、`aweme`、`summary`。
- `summary.summary_path` 指向最终内容笔记路径。
- `transcript.text_content` 保存转录原始文字；`transcript.text_path` / `json_path` 只用于处理中间文件，成功清理后可以为空，不应指向单独转录 Markdown。
- SQLite 后端已废弃；不要新增依赖 SQLite 的功能。

## 调度、发布与推送

- 当前配置中的默认检测时间为 `09:00`、`12:00`、`15:00`、`18:00` 和 `21:00`。
- Web 后台启动时会自动启动内置调度器；配置 `schedule.enabled: true` 时，会按 `schedule.times` 执行。
- 成功识别并研究一个博主后，应自动将其写入 `bloggers` 配置并启用持续监控；后续发现新作品并生成笔记时，应重建 `docs/index.html` 并在该批次结束后执行 GitHub 同步。
- `pipeline.mode: realtime` 是当前推荐批量研究模式：下载、转录和 Agnes 整理使用队列流水线；每条视频转录成功后立即进入 Agnes 队列，不等待整批转录完成。Agnes 仍按 `rpm_limit: 19` 串行限流，Ollama 只在 Agnes 失败时作为 GPU 协调后的备用方案。
- 飞书推送标题统一为：`流媒体更新简报｜YYYY-MM-DD HH:MM`。
- 博主批量研究完成后默认发送一条批次完成提醒，链接优先指向公开 `batch-notes/job-<任务号>-<博主>/index.html`；不逐条推送 143 篇内容。
- 飞书卡片链接优先使用 `publishing.github_pages.public_base_url` 生成的 HTML URL；未配置时回退 `app.web_base_url` 下的 `/aweme?id=...` 或 `/file?path=...`。
- `include_full_text` 当前应保持 `false`。
- GitHub Actions 只发布 `docs/` 到 `gh-pages`，不要在 Actions 中运行抖音采集、转录或 Ollama。
- 批量研究任务完成后，在 `docs/batch-notes/job-<任务号>-<博主>/` 生成该批次 HTML 副本和索引，并只执行一次 GitHub commit/push；不要按单条视频频繁触发 Actions。
- Cookie、API key、飞书 Webhook、数据库密码都是敏感信息；只放在本地配置或环境变量中，不要提交真实值，不要在日志和文档中暴露完整值。

## 常用命令

以下 `python` 默认指已安装 KenRadar 依赖的项目运行环境；当前本机验证使用 conda `openclaw` 环境。若系统默认 `python` 缺少依赖，应先激活项目环境或显式使用项目环境 Python。

- 启动 Web 后台、初始化数据库并默认托管 FunASR：`./ctl.sh start`
- 重启：`./ctl.sh restart`
- 停止：`./ctl.sh stop`
- 状态：`./ctl.sh status`
- 日志：`./ctl.sh logs`
- FunASR：`./ctl.sh start-funasr`、`stop-funasr`、`restart-funasr`、`status-funasr`、`logs-funasr`
- 初始化数据库：`python -m kenradar --config config/config.yaml init-db`
- 手动端到端运行：`python -m kenradar --config config/config.yaml run-once`
- 调试时跳过飞书：`python -m kenradar --config config/config.yaml run-once --no-push`
- 清理已归档内容的 Downloaded 临时文件：`python -m kenradar --config config/config.yaml cleanup-downloads`
- 强制处理每个启用博主最新作品：`python -m kenradar --config config/config.yaml test-latest`
- 研究并归档指定博主历史视频：`python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10`
- 研究并归档单个视频：`python -m kenradar --config config/config.yaml research-video "抖音视频链接或 aweme_id"`
- 研究并归档小宇宙节目、单集或 RSS：`python -m kenradar --config config/config.yaml research-xiaoyuzhou "URL" --limit 1`
- 补齐已有成功转录的 AI 摘要：`python -m kenradar --config config/config.yaml summarize-existing --limit 10`
- 旧 Markdown 笔记升级为新版 Obsidian 模板：`python -m kenradar --config config/config.yaml refresh-old-notes --dry-run`
- 生成 GitHub Pages HTML：`python -m kenradar --config config/config.yaml publish-pages`
- 独立调度模式：`python -m kenradar --config config/config.yaml schedule`

## 实现约束

- 当前成熟生产关注抖音视频作品；小宇宙 / RSS 是已实现 MVP；B站、小红书、YouTube 只预留字段和目录结构。
- 通用网页源、OPML 导入、复杂权限系统、更多推送渠道仍属于后续扩展。
- 新增 Web 功能必须先通过真实 PostgreSQL 路径验证；仅 mock 测试通过不能标记为生产可用。
- 当前实测 `/api/dashboard/overview` 7/30/90 天约 0.55s/0.55s/0.71s；90 天尚未达到 500ms 目标。
- 高价值阈值当前以 5 分制 `value_score >= 3.5` 对应前端 10 分制 `rating >= 7`；查询、仪表盘和来源聚合必须保持同一口径。
- 研究博主、旧笔记升级和大批量发布都是重型批量任务，同一时间建议只运行一个。
- 默认每条视频通常只产生 1 次 organizer LLM 请求，也就是 Agnes 整理请求；Agnes 重试和 Ollama fallback 会增加额外请求。`ai.transcript_correction.enabled` 当前为 `false`，开启后会额外增加 1 次转录校正 LLM 请求。
- 新增功能时优先保持：
  - Obsidian 内容笔记 frontmatter 结构不破坏；
  - `> [!summary]`、`知识关联`、`分段原文` 和 `视频原始转录` 小节不破坏；
  - text fallback 不破坏；
  - HTML 发布不破坏；
  - card/text 推送不破坏；
  - `push_log` 不破坏；
  - 定时和手动触发不破坏；
  - 旧数据通过 `summary_path`、`text_path` 兼容读取。

## 验证

最小静态验证：

```bash
python -m compileall kenradar scripts
```

Focused tests：

```bash
python -m pytest tests/test_config_and_publishing.py -q
```

Web 验证：

```bash
./ctl.sh restart
./ctl.sh status
tail -f data/kenradar.log
```

前端验证：

```bash
cd kenradar/web/frontend
npm run lint
npm run build
```

声称功能可用前，应尽量验证真实执行链路，包括：本地 vendor 抖音客户端、Cookie、FunASR、conda `openclaw`、Whisper fallback、PostgreSQL、Obsidian 文件输出、`docs/` HTML 输出、Docker Ollama HTTP/GPU 兜底和飞书 Webhook 行为。

## 当前不优先事项

- 抖音、小宇宙 MVP 之外的新平台完整采集链路。
- 复杂权限系统和多用户支持。
- 大屏展示或移动端优先适配。
- 替换 PostgreSQL 或新增其他数据库。
- 重构 workflow 架构或引入新的任务编排系统。
- 在 GitHub Actions 中运行采集、转录或 AI 链路。
- 大面积前端视觉重构。
- 在来源日指标稳定积累至少 30 天之前实现异常检测。
