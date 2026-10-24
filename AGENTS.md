# AGENTS.md

## 适用范围与事实优先级

- 本文件适用于当前 KenRadar 仓库；最后核对日期：2026-10-24。
- KenRadar 是本地优先、证据可追溯、可恢复的个人研究情报系统。延续现有模块和持久任务架构，不另建一套系统。
- 用户在当前会话中的明确指令和授权优先于本文件。实现事实以当前代码及有效配置为准；README 和历史方案用于补充背景，冲突时应核查并修正文档。
- Windows 原生运行，SQLite 是唯一正常运行数据库。PostgreSQL 历史迁移冻结，仅用于离线导出与旧版本恢复，不建设长期双后端。
- 迁移设计参考 `docs/KenRadar_Windows_SQLite_UI_Codex_Plan_20261010.md`；其中未完成的目标不能当作已经验收的能力。
- 保留 V2 来源、平台内容标识、原始转录、分析、笔记、持久任务、attempt、租约、失败恢复及独立发布/通知。

## 工作区、数据与授权边界

- 先检查 `git status --short` 和相关 diff；保留所有已有未提交改动、删除与内容产物。禁止用 reset/clean 清理工作区，不把无关改动混入提交。
- 开发、测试、迁移演练的写入限定在 `data/test-migration/`。隔离数据库、笔记、媒体、日志、锁和发布目录，并关闭调度、飞书与 GitHub 外发。
- 正式运行维护必须在用户授权范围内进行；不得覆盖原数据、擅自换库、切换数据根、批量重处理、注册系统服务或开机任务，不修改其他项目环境。
- 2026-10-24 用户已明确批准：恢复现有来源的自动扫描、正式下载处理和 worker；随后分别批准恢复飞书推送及 GitHub Pages 生成、自动 commit/push。维护这些已授权功能不需要反复询问，也不得因旧迁移限制擅自关闭它们。
- 上述授权限于既有正常内容处理和发布流程，不扩大为代码仓库任意 push、私有内容公开、历史全量重处理或全量重建发布。单独执行重型历史操作应有对应任务授权。
- 修改文档、开发或测试本身不授权实发测试消息、上传测试产物或触发正式任务。声称已发消息或已公开发布时必须有实际结果证据。
- Cookie、API Key、Webhook、密码只放本地配置或环境变量；不得提交真实值，也不在日志、文档或工具输出中展示完整值。配置检查只输出是否存在及脱敏状态。
- 所有运行时代码位于本仓库；不得通过 `sys.path`、绝对路径导入仓库外项目。已有明确配置的外部 HTTP 服务调用除外。

## 当前运行配置（快照，不替代现场检查）

- 配置入口：`config/config.yaml`，有效配置通过 `load_config` 读取，注意 `DATABASE_URL` 等环境变量覆盖。
- 当前数据根：`data/fresh/`；SQLite：`data/fresh/db/kenradar.sqlite3`。
- Markdown：数据根下 `notes/<platform>/<来源>/` 与 `briefs/`；处理中媒体：`Downloaded/`；运行日志：`logs/`；进程记录：`runtime/processes.json`。
- 当前静态产物和独立发布 Git 仓库均为 `data/github-pages/`，公开地址由 `publishing.github_pages.public_base_url` 配置。不要把代码仓库根或历史 `docs/` 默认当成当前发布仓库。
- 定时任务、订阅雷达、现有来源、飞书和 Pages 自动同步已恢复启用。进程存活、Cookie、GPU、推送权限及网络每次按需检查，不能引用旧快照声称当前正常。
- 数据库路径不能热切换；不得因目标路径缺失而静默创建空库替代原库。改库或迁移前保留可恢复备份并核对 schema、数量与关键关联。

## 处理与调度

```text
来源订阅 → 到期扫描 / 定时检测 → 去重与持久任务 → 下载 → 转录 → AI 整理
        → SQLite 当前结果 + Obsidian 笔记 → 独立静态发布 / 通知
```

- 成熟链路聚焦抖音；小宇宙节目、单集和 RSS 为 MVP。B站、小红书、YouTube 仅预留结构，不宣称完整支持。
- 内容身份统一使用 `platform + external_content_id`，外部 ID 保持字符串，禁止经 JavaScript Number 丢失精度。
- 标准原生部署为一个 Web + 一个常驻 worker。`TaskWorker` 启动持久调度线程；Web 负责查询、设置和入队。不要额外启动第二套 `schedule` 或采集调度器。
- 固定检测时间由 `schedule.times` 控制，当前为 09:00、12:00、15:00、18:00、21:00，时区为 `app.timezone=Asia/Shanghai`。
- 订阅雷达要求 `schedule.enabled`、`schedule.source_radar_enabled` 均开启；来源还必须 enabled、status=active 且已到 next_check_at。
- 雷达默认每 15 分钟检查到期订阅，来源自身检查间隔未配置时按 60 分钟处理；队列背压、扫描失败退避会推迟扫描。不要将雷达轮询频率与来源间隔混淆。
- 订阅数据在 `source_subscription`，旧固定检测读取 `bloggers`。排查停止监控时同时检查两处启用状态、有效配置、worker 日志、最近检查时间、错误和待处理队列。
- 当前雷达创建的 `process_url` 任务显式 `push=false`；固定定时 `run_once` 请求 push=true，但仍受通知开关及筛选规则控制。飞书总开关不等于每条内容立即推送。
- 扫描只发现并入队；下载、ASR 和 AI 在 worker 执行。未知作品不得因尚无 content_item 就阻止处理任务入队。
- 保持幂等键、租约、心跳、暂停/继续/取消、失败重试及审计。网络、下载、模型推理与外发必须放在数据库短事务之外；租约失效的旧 worker 不得提交结果。
- 同一时间尽量只运行一个重型历史研究、笔记升级或全量发布任务。

## 内容笔记契约

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

## Web 与核心代码定位

- `kenradar/web/`：后台、路由、查询、SSE；`frontend/` 为 React/Vite。存在 dist 时优先服务构建产物，否则回退服务端模板。
- 内容详情统一 `/content?platform=<platform>&external_id=<id>`；以 Markdown 阅读为主，转录原稿可折叠。首页和详情不恢复已退役的收藏、选题池、旧深度研究和备注入口。
- 归档卡片以阅读为主，维护动作集中到详情、失败重试和研究任务详情。界面优化按用户任务范围进行，不做无关的大面积视觉改版。
- `core/checker.py`、`source_resolver.py`：旧固定检测与来源解析；抖音采集继续复用 `vendor/douyin_downloader/`。
- `core/source_monitor.py`、`sources/`：订阅雷达、平台连接器和来源契约。
- `jobs/worker.py`、`jobs/handlers.py`、`scheduler/scheduler.py`：持久任务执行、分发和调度。
- `core/workflow.py`：下载、转录、AI、笔记与历史研究编排；不另引入任务编排系统。
- `storage/sqlite_database.py`、`sqlite_content.py`、`sqlite_research.py` 及 SQLite 迁移链：正常运行存储；`pg_database.py` 为历史兼容代码。
- `publishing/static_site.py`、`github_sync.py`、`service.py`：HTML 生成和独立发布；`notification/`：飞书与通知审计。
- `integrations/hermes_v1.py`、`safe_network.py`、`privacy.py`：私有任务、受控联网与外发隔离；改动相关路径需覆盖对应回归。

## 转录、AI 与 GPU

- FunASR 为优先转录服务，默认 `http://127.0.0.1:18002/v1`，模型组合 paraformer-zh / fsmn-vad / ct-punc；Windows 入口为 `scripts/funasr.ps1` 和仓库内封装服务。
- FunASR 可按需启动，空闲退出；失败或质量不足时回退 faster-whisper / Whisper。当前 Whisper 配置使用 CPU；实际模型、设备与计算类型以有效配置为准，不沿用历史 conda 环境假设。
- Qwen3-ASR 当前禁用，只保留兼容结构，不自动启动其容器。
- Agnes `agnes-2.5-flash` 是当前首选 organizer，免费额度保持 `rpm_limit: 19`，批量请求经过现有队列限流；禁止提高并发绕过限制。
- 当前备用为 Strata `qwen3.8-flash-next-iq2_xs`，经已有 KenPulse 按需启动服务，在 GPU 锁内使用；只释放本次自行启动的服务，不干扰其他项目。
- 历史 Docker Ollama / qwen fallback 保留，当前 provider 禁用。不得删除兼容能力，也不在主机另装、启动或管理 Ollama；启用时只调用配置的外部 HTTP 服务。
- 所有本地 GPU 任务必须经过现有 `GpuResourceManager`、跨进程文件锁和服务协调，禁止绕过锁并发占用 CUDA。
- 默认每条内容通常一次 organizer 请求；重试、备用 provider 或额外转录校正会增加请求。不要把这些次数写成绝对保证。
- AI 服务失败要记录错误并明确降级；不得以原始转录冒充成功摘要或推送全文。转录、HTML、笔记和 card/text fallback 契约不能被破坏。

## 发布、飞书与私有内容

- 通知总开关为 `notification.enabled`，飞书渠道为 `notification.channels.feishu.enabled`；推送还受任务 push 标志、内容筛选和平台配置约束。系统告警同样可能外发。
- 飞书定位为精简资讯流，标题为 `流媒体更新简报｜YYYY-MM-DD HH:MM`；`include_full_text` 保持 false。不发送 YAML、frontmatter、完整 ASR 或整篇 AI 文章。
- 链接优先使用配置的 Pages 地址，否则回退本地 Web 内容地址。批量研究采用批次完成提醒与批次索引，不逐条轰炸推送。
- Pages 生成开关、GitHub 同步开关、auto_commit 和 auto_push 相互独立。恢复开关不会自动重建全部历史 HTML。
- `publish-pages` 遍历已有笔记和简报 Markdown，生成 HTML、更新索引，再同步变化；不重新下载、ASR 或 AI 整理。`--limit 0` 为全部，`--no-sync` 只跳过 Git 同步，仍会写 HTML。
- 当前同步包含 HTML 产物，不包含原始 Markdown 笔记或简报。只同步发布白名单文件，不混入代码、配置、数据库、媒体和敏感信息。
- 使用独立发布仓库和现有敏感信息检查；GitHub Actions 只部署静态产物，不运行采集、转录或模型服务。
- Hermes 私有内容、hermes-private 目录、`hermes_private: true` 标记及数据库私有属性必须保留。即使复制或改名也不能绕过隐私边界，禁止由旧恢复、发布、通知或告警路径泄露。
- 不把私有内容加入公开索引，不为了通过发布检查删除隐私标记或关闭安全检查。

## Windows 常用命令

以下从仓库根执行；优先使用已验证的项目解释器 `.\.venv\python.exe`，不要修改系统或其他项目 Python。

```powershell
# 生命周期；不注册系统服务
.\ctl.ps1 status -Config config/config.yaml
.\ctl.ps1 start -Config config/config.yaml
.\ctl.ps1 stop -Config config/config.yaml
.\ctl.ps1 diagnose -Config config/config.yaml
# 重启为 stop 后 start；先确认没有不应中断的任务

# 数据库迁移仅对明确选定的目标配置执行
.\.venv\python.exe -m kenradar --config config/config.sqlite.example.yaml migrate

# 下列正式任务会写入/入队，按任务授权执行
.\.venv\python.exe -m kenradar --config config/config.yaml scan-sources
.\.venv\python.exe -m kenradar --config config/config.yaml run-once --no-push
.\.venv\python.exe -m kenradar --config config/config.yaml research-blogger --blogger "名称或 sec_uid" --limit 10
.\.venv\python.exe -m kenradar --config config/config.yaml research-video "视频链接或 ID"
.\.venv\python.exe -m kenradar --config config/config.yaml research-xiaoyuzhou "URL" --limit 1
.\.venv\python.exe -m kenradar --config config/config.yaml publish-pages
.\.venv\python.exe -m kenradar --config config/config.yaml sync-github --dry-run
```

- `run-once --no-push` 只禁飞书，不保证禁止 HTML/GitHub 发布；隔离测试必须同时隔离路径并关闭所有发布开关。
- `ctl.ps1 init` 会迁移数据库；普通启停不需要重复 init。Linux `ctl.sh` 仅用于相应环境，不作为 Windows 默认入口。
- 详细参数以 `python -m kenradar --help` 和子命令帮助、当前代码为准。

## 验证与报告

- 根据改动运行相关测试；测试数据库和产物必须在 `data/test-migration/`，不使用正式数据验证写操作。
- 存储、队列和监控改动须使用真实 SQLite 文件库验收，覆盖已知/未知内容、重复入队、禁用来源、时间间隔及失败恢复等相关分支。
- 静态通过、mock、空库或历史测试结果不能替代真实迁移、平台、网络及 GPU 链路验收。报告区分已测试范围与尚未验证的能力。
- 不将进程 PID、历史测试数、旧性能指标或临时健康结果固化成“始终正常”。实际运行状态按需读取 ctl 状态、日志和健康端点。

```powershell
.\.venv\python.exe -m compileall kenradar scripts
.\.venv\python.exe -m pytest tests/test_monitor_activation.py tests/test_source_monitor.py tests/test_sqlite_content_contract.py -q -p no:cacheprovider --basetemp=data/test-migration/pytest-monitor
.\.venv\python.exe -m pytest tests/test_api_contract.py tests/test_delivery_tasks.py -q -p no:cacheprovider --basetemp=data/test-migration/pytest-api
# 前端有改动时，在 kenradar/web/frontend 执行 npm run lint 和 npm run build
```

- 不复用含有需保留文件的 pytest basetemp；pytest 会清理该目录。
- 关键回归：笔记 frontmatter/章节、平台内容身份、原始转录、当前结果选择、降级状态、发布与通知审计、租约恢复、私有内容防泄露、手动与定时触发。
- 高价值口径统一为后端 5 分制 value_score >= 3.5，对应前端 10 分制 rating >= 7。
- 报告说明具体改动、验证证据与未验证限制；不声称未执行的完整平台或 GPU 链路已通过。

## 暂不扩展

- 抖音和小宇宙/RSS MVP 之外的新平台完整链路、复杂权限、多用户、通用网页源和更多推送渠道。
- PostgreSQL 长期运行支持、Redis/Celery 等替代编排系统、无关的 workflow 或 UI 大规模重构。
- 未有足够真实历史数据与明确任务前，不实现来源异常检测。
