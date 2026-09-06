# KenRadar

KenRadar 是一个本地化 AI 信息雷达系统。它当前聚焦抖音博主视频：持续监控来源、抓取作品、下载视频、优先用 FunASR 转录，质量不达标或失败时直接回退 Whisper / faster-whisper；随后优先通过 Agnes AI 生成结构化摘要、评分、标签和推荐动作，Agnes 不可用时回退 Docker Ollama / qwen，写入 PostgreSQL，生成 Obsidian Markdown 笔记和 GitHub Pages HTML，并通过飞书发送精简通知。

KenRadar 不是纯下载脚本。它的愿景是成为一个本地优先、证据可追溯、可恢复的个人研究情报操作系统：把来源、内容、处理状态、知识资产、发布结果和长期质量信号连接起来，让信息能够被发现、判断、阅读、归档、修复和持续复盘。

抖音视频仍是当前最成熟的生产链路；小宇宙节目、单集和 RSS 已具备研究与订阅监控 MVP，但生产验证程度低于抖音。

## 当前定位

```text
抖音博主
  ↓
定时/手动检测
  ↓
抓取作品列表、去重、下载视频
  ↓
FunASR 转录，质量不达标时直接回退 Whisper / faster-whisper
  ↓
Agnes AI 结构化摘要、评分、标签、推荐动作，失败时回退 Ollama / qwen
  ↓
生成单一 Obsidian 内容笔记
  ↓
写入 PostgreSQL
  ↓
Markdown 转 HTML，输出到独立的本地 Pages 仓库并发布
  ↓
飞书发送通知，链接优先指向 GitHub Pages 发布页
  ↓
Web 后台查看、重试、研究、排障
```

## 当前事实

- 配置文件：`config/config.yaml`
- 运行数据：`data/`
- 下载中转目录：`data/Downloaded/`
- Markdown 内容笔记：`data/notes/<platform>/<blogger_name>/`
- 简报、周报、研究报告：`data/briefs/`
- GitHub Pages HTML 输出：`data/github-pages/`（独立仓库 `KenRadar-pages`）
- 数据库：PostgreSQL
- 转录优先级：FunASR `paraformer-zh` -> Whisper `large-v3-turbo`
- 当前 Whisper fallback 配置偏稳定：faster-whisper / CPU / int8
- AI 整理：主引擎 Agnes AI `agnes-2.5-flash`，OpenAI-compatible Chat Completions；备用引擎 Docker Ollama `qwen3.5:9b`
- Agnes API Key：通过环境变量 `AGNES_API_KEY` 提供，不写入仓库
- Agnes 免费额度按 `rpm_limit: 19` 控制；批量研究会在 AI 整理阶段排队，尽量保持在 20 RPM 免费限制以内
- Ollama endpoint：通常为 `http://127.0.0.1:11434/v1`
- FunASR endpoint：通常为 `http://127.0.0.1:18002/v1`
- Qwen3-ASR 当前禁用，仅保留兼容配置与代码
- Web 后台默认端口：`8765`
- 当前本地控制脚本：`ctl.sh`，默认 Web 监听 `0.0.0.0`；FunASR 在首次转录时按需启动，空闲 5 分钟后退出
- 飞书定位：通知流，只发摘要和链接，不发完整原稿或完整笔记

## 当前健康状态

截至 2026-07-16 的本地体检结果：

- Git：`KenRadar/main` 只管理源码、测试和工程文档；生成站点由 `KenRadar-pages/gh-pages` 独立管理。
- 工作区：Obsidian Markdown、转录、媒体、日志和生成 HTML 均位于被忽略的 `data/`，不会混入功能提交。
- Web：`./ctl.sh status` 显示 Web 与 worker 正在运行。
- 健康检查：`/health/live`、`/health/ready`、`/health/dependencies` 可访问；当前 PostgreSQL/GPU 正常，飞书已配置。
- 静态验证：`python -m compileall kenradar scripts` 通过。
- 测试：完整集合共 141 项，`141 passed`；测试配置已隔离仓库 `.env` 环境变量污染。
- 前端：`npm run lint` 与 `npm run build` 通过；已启用 Vite vendor 分包，主应用 chunk 约 442KB、vendor chunk 约 422KB。
- CLI：在项目运行环境中 `python -m kenradar --help` 正常列出命令。
- 决策仪表盘：`/api/dashboard/overview` 已在真实 PostgreSQL 返回数据，DailyTrend 和 PipelineStatus 已接入前端；7/30/90 天实测约 0.55s/0.55s/0.71s，90 天仍需优化。
- `/api/content-items` 已修复兼容视图问题，真实查询和 cursor 第二页返回正常。
- 来源洞察：既有 creator 已回填为 26 个来源、20 个启用；7 天聚合已写入 140 条日指标和 274 条主题指标，API 与页面已接线。
- SSE：35 秒实测收到 connected 和 heartbeat，服务重启后重新连接也已验证；前端仍保留轮询降级。

## V2 交付状态

V2 已具备订阅扫描、扫描后确认执行、当前结果、独立发布与通知重试，以及“今日雷达、订阅来源、处理链接、内容库、批次任务、系统与监控”六个 Web 入口。发布和通知任务只处理已有内容结果，不会重跑下载、转录或 AI。

真实环境迁移和双平台验收依赖 PostgreSQL 可连接。验收脚本和当前阻塞记录见 [`docs/superpowers/reports/2026-09-06-kenradar-v2-verification.md`](docs/superpowers/reports/2026-09-06-kenradar-v2-verification.md)。

## 核心能力

- 抖音博主监控、手动检测和历史研究任务。
- 研究博主后自动加入持续监控；后续更新生成笔记时自动重建 GitHub Pages 目录，并按配置同步到 GitHub。
- 本地化抖音客户端抓取和下载，代码位于 `kenradar/vendor/douyin_downloader/`。
- FunASR 优先转录，服务不可用、超时、返回空文本或质量校验失败时自动回退 Whisper。
- GPU 调度器协调 ASR、Whisper 和 Ollama，支持文件锁、显存检测、阶段切换和 OOM 降级。
- Agnes AI 优先生成结构化 JSON：标题、摘要、核心内容、主题、标签、评分、推荐动作；Agnes 缺少 Key、限流或服务异常时，自动尝试 Ollama / qwen 备用 provider。
- 每条视频只生成一份最终 Obsidian 内容笔记。
- Markdown 自动转 HTML，输出到 `data/github-pages/` 独立仓库，用于 GitHub Pages 发布。
- 飞书 Card/Text 通知，按钮优先指向 GitHub Pages HTML 页面。
- PostgreSQL 记录来源、作品、转录、AI 分析、笔记、推送、告警、研究任务。
- Web 后台提供仪表盘、内容工作台、归档研究、来源管理、系统配置、系统监控。
- Web 仪表盘已接入服务端内容检索、决策概览、每日趋势和流水线图表；内容检索的真实数据库兼容问题仍待修复。
- 处理中心采用任务优先的单页指挥台：先观察后台批次、阶段和卡点，再分级修复失败；发布记录、日志与模型状态作为辅助诊断。
- 来源洞察 MVP 已具备日指标表、确定性聚合代码、API 和页面，仍处于迁移、回填及真实数据验收阶段。
- 小宇宙节目、单集或 RSS 可通过 CLI 研究归档，也可登记为订阅来源。
- 失败重试支持下载、转录、AI/笔记、全流程和批量入口。

## 目录结构

```text
KenRadar/
├── config/
│   └── config.yaml                 # 本地运行配置，包含敏感信息，不应提交真实值
├── data/
│   ├── kenradar.log                # 运行日志
│   ├── Downloaded/                 # 下载和转录处理中转目录
│   ├── notes/                      # Obsidian 内容笔记
│   └── briefs/                     # 流媒体简报、周报、研究报告
├── scripts/
│   ├── funasr_openai_server.py     # FunASR OpenAI-compatible 服务
│   ├── start_funasr_server.sh
│   └── stop_funasr_server.sh
├── kenradar/
│   ├── core/                       # 抓取、下载、转录、AI 整理、工作流、GPU 调度
│   ├── notification/               # 飞书通知
│   ├── publishing/                 # 静态 HTML 发布
│   ├── storage/                    # PostgreSQL 存储
│   ├── web/                        # Web 后台和 React/Vite 前端源码
│   └── vendor/                     # 本地化抖音下载客户端
├── tests/                          # focused tests
├── ctl.sh                          # 本地服务控制脚本
└── pyproject.toml
```

## 内容处理流程

`run-once` 或 Web 手动检测会执行一次完整链路：

```text
读取启用博主
  ↓
抓取最新作品
  ↓
过滤已处理作品
  ↓
下载视频到 data/Downloaded/
  ↓
FunASR 转录，质量不足或失败时直接回退 Whisper
  ↓
Agnes AI 结构化整理，失败时回退 Ollama / qwen
  ↓
生成 Obsidian Markdown 内容笔记
  ↓
写入 PostgreSQL summary/content_note
  ↓
生成 HTML 到 docs/
  ↓
按评分和推荐动作筛选飞书通知
```

研究博主是重型批量任务，适合一次性归档某个博主的历史作品：

```bash
python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10
```

研究单视频适合临时归档一个未在监控列表中的视频：

```bash
python -m kenradar --config config/config.yaml research-video "抖音视频链接或 aweme_id"
```

研究任务会写入 `research_job`、`research_job_item`、`transcript`、`ai_analysis`、`content_note`，并生成 `data/briefs/research_博主名_YYYYMMDD_HHMM.md` 及对应 HTML。

## Obsidian 内容笔记规范

每条视频最终只生成一份内容笔记，结构固定为：

```markdown
---
type: video_note
platform: "抖音"
creator: "博主名"
creator_id: "sec_uid"
video_id: "7646255369669614308"
source_url: "https://www.douyin.com/video/7646255369669614308"
original_title: "原始标题"
title: "整理后标题"
published_at: "2026-06-01 21:06:00"
ai_model: "agnes-2.5-flash"
transcript_model: "large-v3-turbo"
topics:
  - "半导体"
  - "光通信"
tags:
  - "KenRadar"
  - "视频笔记"
  - "抖音"
status: processed
value_score: 4.2
---

# 整理后标题

## 一、内容简述

### （一）一句话结论

> [!summary]
> 一句话结论。

### （二）核心内容

1. **核心观点标题**
   核心观点正文。

## 二、分段原文

> 以下内容保持博主原意和论述顺序，仅修正明显错别字、ASR 识别错误、标点与断句。

### 1. 第一段主题

经过错别字和断句修正的博主原文，不做摘要、删减或扩写。

### 2. 第二段主题

下一段经过修正的博主原文。

## 三、知识关联

- [[半导体]]
- [[光通信]]

## 四、视频原始转录

> 以下内容由 Whisper 自动转录生成，可能存在错字、断句错误或语义遗漏，请以原视频为准。

转录原文。
```

规则：

- `video_id` 必须作为字符串写入 YAML。
- YAML 字符串必须正确转义。
- 一句话结论使用 Obsidian callout：`> [!summary]`。
- “知识关联”集中使用 `[[wikilinks]]`。
- 正文不要全文自动替换双链；外部 URL 不要写成 `[[URL]]`。
- `topics` 控制在 5-10 个左右。
- `tags` 默认包含 `KenRadar`、`视频笔记`、平台名。
- “分段原文”保持博主原意和论述顺序，只修正明显错别字、ASR 识别错误、标点与断句。
- GitHub Pages 中“视频原始转录”默认折叠，便于需要时核对。
- 转录原文只出现在 Web 详情页和最终内容笔记中，不进入飞书推送。

## GitHub Pages 发布

KenRadar 的重型流程在本机运行，不在 GitHub Actions 里跑抖音、ASR、Whisper 或 Ollama。GitHub Pages 只负责发布已经生成好的 HTML。

当前配置：

```yaml
publishing:
  github_pages:
    enabled: true
    output_dir: ./data/github-pages
    public_base_url: ${KENRADAR_GITHUB_PAGES_URL}
  github_sync:
    enabled: true
    repo_dir: ./data/github-pages
    branch: gh-pages
    auto_commit: true
    auto_push: true
    include_html_docs: true
    include_markdown_notes: false
    include_briefs: false
    include_transcripts: false
```

生成 HTML：

```bash
python -m kenradar --config config/config.yaml publish-pages
python -m kenradar --config config/config.yaml publish-research-job --job-id 1
```

输出示例：

```text
data/github-pages/
├── index.html
├── briefs/
│   └── 2026-06-01_2106_流媒体更新简报.html
└── notes/
    └── douyin/
        └── 博主名/
            └── 2026-06-01_标题_aweme_id.html
```

飞书链接逻辑：

1. 如果 `KENRADAR_GITHUB_PAGES_URL` 已设置，飞书按钮优先指向 GitHub Pages HTML。
2. 如果未设置，则回退到本地 Web 链接，例如 `/aweme?id=...` 或 `/file?path=...`。

`data/github-pages/` 是 `KenGGG/KenRadar-pages` 的本地 `gh-pages` checkout。KenRadar 在本机生成 HTML 后直接在该仓库提交和推送；源码仓库不保存生成 HTML，也不通过 Actions 中转。`data/notes/` 与 `data/briefs/` 中的 Markdown 始终只保留在本地。

环境变量示例：

```bash
export KENRADAR_GITHUB_PAGES_URL="https://你的用户名.github.io/KenRadar"
```

## 飞书通知

飞书推送标题：

```text
流媒体更新简报｜YYYY-MM-DD HH:MM
```

飞书机器人如启用了关键词校验，应将 `流媒体更新简报` 配置为安全关键词；普通简报和研究完成提醒都会包含该关键词。

飞书定位是通知，而不是完整阅读界面。

推送内容：

- 总览标题列表。
- 单条短标题。
- 简短摘要。
- 博主和发布时间。
- 原视频按钮。
- 阅读全文按钮，优先指向 GitHub Pages HTML。

不会推送：

- YAML frontmatter。
- 完整转录原稿。
- 完整 AI 整理正文。
- 完整 Markdown 笔记。

筛选逻辑：

- 默认优先推送 `recommended_action = push` 的内容。
- 或推送 `value_score >= 4` 的内容。
- 其他内容仍归档到数据库、Markdown 和 HTML，但飞书记录为 archived。

## Web 后台

启动：

```bash
./ctl.sh start
```

默认局域网访问：

```text
http://<局域网 IP>:8765/
```

仅本机监听：

```bash
HOST=127.0.0.1 ./ctl.sh start
```

`app.web_base_url` 控制飞书和系统内生成的本地 Web 链接。`run_web()` 启动时会初始化数据库并启动内置调度器。如果 `kenradar/web/frontend/dist/` 存在，会优先服务 React/Vite 前端；否则回退到服务端模板。

页面分组：

```text
KenRadar Web
├── 监控首页：服务端组合筛选、重点内容、决策指标和趋势图表
├── 来源管理：抖音博主、小宇宙节目 / 单集 / RSS 订阅源
├── 来源洞察：来源日指标、价值和质量趋势；当前处于真实数据验收阶段
├── 博主研究：单视频研究、博主历史作品批量研究、研究报告
├── 处理中心：后台任务、阶段进度、卡点诊断、失败修复和发布记录
├── 内容归档：已生成的内容笔记、Markdown 笔记和简报
└── 系统配置：调度、GitHub Pages、飞书、转录和 AI provider
```

重要路由：

- `/`：监控首页。
- `/sources`：来源管理。
- `/insights`：来源洞察。
- `/research` 或 `/archive/research`：博主研究和研究任务。
- `/run` 或 `/operations`：统一处理中心。
- `/run?tab=retry` 或 `/operations/retry`：失败重试。
- `/run?section=publishing`、`/run?tab=history` 或 `/logs/pushes`：处理中心内的发布与通知记录。
- `/archive`：内容归档。
- `/research/jobs?id=...`：研究任务详情。
- `/archive/notes`：Markdown 笔记。
- `/archive/briefs`：简报。
- `/config`：系统配置。
- `/logs/status`：系统状态。
- `/logs/pushes`：推送记录。
- `/logs/alerts`：系统告警。
- `/logs/runtime`：运行日志。
- `/aweme?id=...`：单条内容详情。
- `/file?path=...`：优先重定向到 `/aweme?id=...`。

Web 手动动作通过后台任务队列执行，避免阻塞 HTTP 请求。同一时间默认只运行一个重型任务。研究任务已接入 SSE 和轮询降级，但真实断线恢复、事件投递和连接清理仍待完整验收；数据库始终是最终事实来源。

## GPU 与模型调度

当前推荐批量研究模式：

```yaml
pipeline:
  mode: realtime

gpu_scheduler:
  mode: turbo
```

staged GPU 逻辑：

```text
阶段一：下载 + FunASR / Whisper 转录
  ├── 卸载或避让 Ollama 模型
  ├── 等待显存释放
  ├── 优先调用 FunASR 本地服务
  ├── FunASR 质量不足或失败时回退 Whisper
  └── 条目标记为 transcribed_waiting_summary

阶段二：Agnes AI 整理，失败时回退 Ollama / qwen
  ├── 释放转录模型压力
  ├── 按 Agnes provider 的 19 RPM 限流排队
  ├── Agnes 缺少 Key、限流或服务异常时切换 qwen3.5:9b
  ├── 读取已成功转录文本
  ├── 生成结构化摘要
  ├── 写 Obsidian 笔记
  └── 生成 HTML 发布页
```

GPU 约束：

- 所有占用 GPU 的任务应通过 `GpuResourceManager` 或现有服务协调。
- Web、CLI、临时任务之间使用文件锁协调。
- CUDA OOM 时 Whisper 可降级 CPU 重试。
- Ollama GPU 强制检查失败时，备用 AI 阶段会暂停并告警，不伪装成功。
- KenRadar 不安装、不启动、不管理 Ollama，只调用外部 Docker HTTP 服务。

## 配置

主配置文件：

```text
config/config.yaml
```

关键配置示例，敏感值请使用本地配置或环境变量：

```yaml
app:
  data_dir: ./data
  database_url: postgresql://kenradar:CHANGE_ME@localhost:5432/kenradar
  web_base_url: http://127.0.0.1:8765

output:
  obsidian_root: ./data

publishing:
  github_pages:
    enabled: true
    output_dir: ./data/github-pages
    public_base_url: ${KENRADAR_GITHUB_PAGES_URL}

pipeline:
  mode: realtime
  enable_llm_worker: true

transcribe:
  model: large-v3-turbo
  device: cpu
  compute_type: int8
  batch_size: 1

gpu_scheduler:
  enabled: true
  mode: turbo
  lock:
    enabled: true
    scope: file
  llm:
    provider: ollama
    endpoint: http://127.0.0.1:11434/v1
    model: qwen3.5:9b
    require_gpu: true
  whisper:
    default_device: cpu
    allow_gpu: false
    fallback_device: cpu

ai:
  funasr:
    enabled: true
    endpoint: http://127.0.0.1:18002/v1
    model: paraformer-zh
    fallback_to_qwen_asr: false

  qwen_asr:
    enabled: false
    endpoint: http://127.0.0.1:18001/v1
    model: Qwen/Qwen3-ASR-1.7B
    fallback_to_whisper: true

  whisper:
    enabled: true
    model: large-v3-turbo
    backend: faster-whisper
    device: cpu
    compute_type: int8
    conda_env: openclaw

  organizer:
    enabled: true
    api_type: chat_completions
    endpoint: https://apihub.agnes-ai.com/v1
    model: agnes-2.5-flash
    rpm_limit: 19
    max_tokens: 8192
    fallback_note: true
    providers:
      - name: agnes
        enabled: true
        api_type: chat_completions
        endpoint: https://apihub.agnes-ai.com/v1
        model: agnes-2.5-flash
        env_var: AGNES_API_KEY
        rpm_limit: 19
        requires_api_key: true
      - name: ollama-qwen-fallback
        enabled: true
        api_type: ollama
        endpoint: http://127.0.0.1:11434/v1
        model: qwen3.5:9b
        rpm_limit: 0
        requires_api_key: false

notification:
  enabled: true
  research_completion_enabled: true
  channels:
    feishu:
      webhook_url: ${FEISHU_WEBHOOK_URL}
      message_type: auto
      include_full_text: false
      send_empty_report: true
      card_max_items: 5
```

配置加载逻辑：

- 支持 `${ENV_VAR}` 形式的环境变量占位符。
- 加载时会展开环境变量。
- 保存配置时不会把占位符替换成真实密钥。
- 使用 Pydantic 做基础配置校验。
- 未设置的占位符会保留原样，下游会清晰报错或回退。
- `research_completion_enabled` 默认开启；博主批量研究完成后只发送一条飞书提醒，并优先链接公开批次目录。

AI 调用次数：

- 当前默认流程中，转录由 FunASR / Whisper 完成，不调用 organizer LLM；每条视频进入 AI 整理阶段时通常只调用 1 次 Agnes。
- 如果 Agnes 返回 429、5xx 或网络错误，会按 provider 的 `retry_count` 重试；仍失败后再调用 1 次 Ollama / qwen 备用 provider。
- `ai.transcript_correction.enabled` 当前为 `false`；如果未来开启转录后校正，每条视频会额外增加 1 次 LLM 调用。
- 研究博主的批量视频按条目排队，Agnes provider 使用 `rpm_limit: 19`，例如 38 条视频的 Agnes 整理阶段至少跨约 2 分钟窗口完成，重试会占用额外请求额度。

敏感信息：

- Cookie、数据库密码、飞书 Webhook、API key 都是敏感信息。
- 应放在本地配置或环境变量中。
- 不要提交真实值到仓库、日志或文档。

## PostgreSQL 数据库

主要逻辑表：

- `platform`：平台定义。
- `creator`：博主/来源。
- `content_item`：作品元数据和下载状态。
- `transcript`：转录原文、分段 JSON、模型、状态。
- `ai_analysis`：AI 结构化摘要 JSON、模型、状态、错误。
- `content_note`：最终内容笔记路径。
- `content_curation`：人工标记兼容表。
- `push_log`：飞书推送记录。
- `alert_log`：系统告警。
- `research_job`：研究任务。
- `research_job_item`：研究任务中的单条作品状态。

兼容视图/命名：

- `blogger`
- `aweme`
- `summary`

重要约定：

- `summary.summary_path` 指向最终内容笔记路径。
- `transcript.text_content` 保存转录原始文字。
- `transcript.text_path` 和 `json_path` 只用于处理中间文件，成功清理后可以为空。
- SQLite 后端已废弃，不要新增依赖 SQLite 的功能。

初始化数据库：

```bash
python -m kenradar --config config/config.yaml init-db
```

## 常用命令

以下 `python` 默认指已安装项目依赖的运行环境；当前本机验证使用的是 conda `openclaw` 环境。若系统默认 `python` 缺少 `pydantic`、`psycopg` 等依赖，应先激活项目环境，或显式使用该环境的 Python。

服务控制：

```bash
./ctl.sh start
./ctl.sh stop
./ctl.sh restart
./ctl.sh status
./ctl.sh logs
```

FunASR 服务：

```bash
./ctl.sh start-funasr  # 可选手动预热；正常转录会按需启动
./ctl.sh stop-funasr
./ctl.sh restart-funasr
./ctl.sh status-funasr
./ctl.sh logs-funasr
```

常用 CLI：

```bash
python -m kenradar --config config/config.yaml run-once
python -m kenradar --config config/config.yaml run-once --no-push
python -m kenradar --config config/config.yaml test-latest
python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10
python -m kenradar --config config/config.yaml research-video "抖音视频链接或 aweme_id"
python -m kenradar --config config/config.yaml research-xiaoyuzhou "小宇宙节目、单集或 RSS URL" --limit 1
python -m kenradar --config config/config.yaml summarize-existing --limit 10
python -m kenradar --config config/config.yaml cleanup-downloads
python -m kenradar --config config/config.yaml refresh-old-notes --dry-run
python -m kenradar --config config/config.yaml publish-pages
python -m kenradar --config config/config.yaml schedule
```

## FunASR 本地服务

KenRadar 默认优先调用 FunASR 服务进行转录。当前采用仓库内轻量 OpenAI-compatible 服务脚本，默认模型为 `paraformer-zh + fsmn-vad + ct-punc`。服务在首次真实转录请求前按需启动，批量任务期间复用，连续空闲 300 秒且没有活跃请求时自动退出并释放 GPU 显存。

健康检查：

```bash
curl -s http://127.0.0.1:18002/health
curl -s http://127.0.0.1:18002/v1/models
```

需要诊断时可手动预热并禁用空闲退出：

```bash
FUNASR_IDLE_TIMEOUT_SECONDS=0 ./ctl.sh start-funasr  # 诊断时禁用空闲退出
```

## Qwen3-ASR 兼容配置

Qwen3-ASR 当前不参与生产转录链路，`ai.qwen_asr.enabled` 和 `start_on_fallback` 均应保持 `false`。以下命令仅保留作历史兼容参考，不应由 KenRadar 自动执行：

```bash
docker run -d --name kenradar-qwen3-asr \
  --gpus all \
  -p 127.0.0.1:18001:8000 \
  -v $PWD/data/model_cache/huggingface:/root/.cache/huggingface \
  qwenllm/qwen3-asr:latest \
  qwen-asr-serve Qwen/Qwen3-ASR-1.7B --host 0.0.0.0 --port 8000 --gpu-memory-utilization 0.35
```

健康检查：

```bash
curl -s http://127.0.0.1:18001/v1/models
```

兼容代码仍支持 OpenAI-compatible `/v1/audio/transcriptions` 和 `/v1/chat/completions` + `audio_url`，但默认不会调用或启动该容器。

## 前端

React/Vite 前端源码位于 `kenradar/web/frontend/`。后端会优先服务 `dist/`：

```bash
cd kenradar/web/frontend
npm run lint
npm run build
```

开发预览：

```bash
cd kenradar/web/frontend
npm run dev
```

不要无明确需求做大面积视觉重构。当前 Web 仍保留服务端模板作为回退。

## Web 后台任务 API

当前读取与实时接口：

| 能力 | API | 当前状态 |
|---|---|---|
| 服务端内容筛选 | `/api/content-items` | 已接线；真实 PostgreSQL 兼容错误待修复 |
| 决策仪表盘 | `/api/dashboard/overview` | 已接线并能返回真实数据，待对账和性能验收 |
| 研究任务事件 | `/api/stream` | SSE 已接线，待稳定性验收 |
| 来源洞察 | `/api/insights/*` | 实现中，概览参数错误和聚合回填待修复 |
| 依赖健康 | `/health/dependencies` | 已接线 |

| 动作 | API | 说明 |
|---|---|---|
| 手动检测 | `/api/run-once` | 执行一次常规抓取和推送 |
| 测试最新 | `/api/test-latest` | 每个启用博主强制处理最新作品 |
| 研究单视频 | `/api/research-video` | 单条视频完整归档 |
| 研究博主 | `/api/research-blogger` | 批量抓取历史视频并归档 |
| 暂停任务 | `/api/research/pause` | 将研究任务标记为暂停 |
| 接续任务 | `/api/research/resume` | 新建任务继续未完成内容 |
| 取消任务 | `/api/research/cancel` | 取消任务和未完成条目 |
| 重新启动 | `/api/research/restart` | 按原参数新建完整研究任务 |
| 重试下载 | `/api/retry-download` | 从下载阶段重试 |
| 重试转录 | `/api/retry-transcribe` | 从转录阶段重试 |
| 重试 AI/笔记 | `/api/retry-summary` | 从 AI 整理和笔记阶段重试 |
| 全流程重试 | `/api/retry-full` | 自动判断起点并重试 |
| 批量重试 | `/api/retry-batch` | 批量执行失败重试 |
| 重新推送 | `/api/repush-aweme` | 单条内容重新推送飞书 |
| 生成周报 | `/api/generate-weekly` | 根据归档内容生成周报 |

## 研究任务状态

| 状态 | 含义 |
|---|---|
| `pending` | 等待处理 |
| `running` | 任务运行中 |
| `downloading` | 下载中 |
| `downloaded` | 已下载，等待转录 |
| `transcribing` | FunASR / Whisper 转录中 |
| `transcribed_waiting_summary` | 已转录，等待 AI |
| `summarizing` | AI 整理中 |
| `noting` | 写入 Markdown 笔记 |
| `success` | 单条完成 |
| `failed` | 单条失败 |
| `skipped` | 已完整归档，跳过 |
| `paused` | 任务暂停 |
| `cancelled` | 任务取消 |
| `completed` | 任务完成 |
| `partial_failed` | 部分失败 |

## 模块说明

- `kenradar/core/checker.py`：读取配置中的博主，抓取作品列表。
- `kenradar/core/source_resolver.py`：解析抖音主页 URL、短链、视频链接。
- `kenradar/core/downloader.py`：下载视频和作品 JSON 元数据。
- `kenradar/core/transcriber.py`：调用 FunASR 和 Whisper，保存转录结果并写入数据库；Qwen3-ASR 代码仅作兼容保留。
- `kenradar/core/organizer.py`：按 provider 顺序调用 Agnes AI 和 Ollama / qwen，生成结构化摘要，并执行 provider 级 RPM 限流。
- `kenradar/core/ai_json.py`：AI JSON 解析、松散修复和降级分析。
- `kenradar/core/gpu_scheduler.py`：GPU 文件锁、显存检测、ASR/Whisper/Ollama 协调、OOM 降级。
- `kenradar/core/workflow.py`：主工作流、研究任务、重试、笔记生成、HTML 发布触发。
- `kenradar/core/analytics.py`：来源日指标确定性聚合；当前尚未注册为主 CLI 子命令。
- `kenradar/core/obsidian.py`：Obsidian 路径、文件名、YAML 辅助函数。
- `kenradar/publishing/static_site.py`：Markdown 转 HTML，并维护 `docs/index.html`。
- `kenradar/notification/feishu.py`：飞书 Card/Text 通知、推送筛选、简报归档。
- `kenradar/scheduler/scheduler.py`：内置定时调度。
- `kenradar/storage/pg_database.py`：PostgreSQL schema、兼容视图和读写逻辑。
- `kenradar/web/`：本地 Web 后台，已包含拆分路由、统一响应、决策概览、来源洞察和 SSE。

## 验证

最小静态验证：

```bash
python -m compileall kenradar scripts
```

当前 Web 演进回归测试：

```bash
python -m pytest \
  tests/test_config_and_publishing.py \
  tests/test_api_contract.py \
  tests/test_dashboard_consistency.py \
  tests/test_source_insights.py -q
```

PostgreSQL 集成测试（需要一次性可重置的测试库；未设置该变量时自动跳过）：

```bash
KENRADAR_TEST_DATABASE_URL=postgresql://... python -m pytest tests/integration -q
```

Web 验证：

```bash
./ctl.sh restart
./ctl.sh status
tail -f data/kenradar.log
```

GitHub Pages 输出验证：

```bash
python -m kenradar --config config/config.yaml publish-pages --limit 2
ls docs
```

前端验证：

```bash
cd kenradar/web/frontend
npm run lint
npm run build
```

端到端验证应尽量覆盖：

- 本地 vendor 抖音客户端。
- Cookie 可用性。
- FunASR HTTP 服务。
- Whisper fallback。
- conda `openclaw` 和 Whisper fallback。
- PostgreSQL 写入。
- Ollama HTTP 和 GPU offload。
- Obsidian Markdown 输出。
- HTML 发布到 `docs/`。
- 飞书 Card/Text 通知。

## 故障排查

### Ollama 没有使用 GPU

检查：

```bash
curl -s http://127.0.0.1:11434/api/ps
```

如果 `size_vram` 为 0 或日志显示 `offloaded 0/... layers to GPU`，应修 Docker 容器 GPU 运行环境，不要在主机上另起 Ollama。

### FunASR 不可用

检查：

```bash
./ctl.sh status-funasr
curl -s http://127.0.0.1:18002/health
tail -f data/funasr_server.log
```

### Whisper 和 qwen 显存冲突

12GB 显存机器不建议长期同时运行 qwen 和 Whisper GPU。当前推荐让 Whisper fallback 走 CPU：

```yaml
pipeline:
  mode: realtime
transcribe:
  device: cpu
gpu_scheduler:
  whisper:
    allow_gpu: false
```

### 飞书没有 GitHub Pages 链接

检查：

```bash
echo $KENRADAR_GITHUB_PAGES_URL
```

如果未设置，飞书会回退本地 Web 链接。

### 没有生成 HTML

检查：

```bash
python -m kenradar --config config/config.yaml publish-pages --limit 2
find docs -maxdepth 3 -type f
```

### AI 返回非 JSON

KenRadar 会使用 `ai_json.py` 做松散解析和降级分析：

- 能解析则正常写入结构化摘要。
- 不能解析则生成保守 fallback。
- 降级结果不会伪装成高质量成功摘要。

## 当前不优先事项

- 抖音、小宇宙 MVP 之外的新平台完整采集链路。
- 复杂权限系统和多用户支持。
- 替换 PostgreSQL。
- 在 GitHub Actions 中运行抖音采集、ASR、Whisper 或 Ollama。
- 大面积前端视觉重构。
- 恢复首页/详情页中的收藏、选题池、深度研究、备注等旧入口。
- 在来源日指标稳定积累至少 30 天前实现异常检测。
