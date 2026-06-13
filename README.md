# KenRadar

KenRadar 是一个本地化 AI 信息雷达系统。它当前聚焦抖音博主视频：持续监控来源、抓取作品、下载视频、优先用 FunASR 转录，质量不达标或失败时直接回退 Whisper / faster-whisper；随后优先通过 Agnes AI 生成结构化摘要、评分、标签和推荐动作，Agnes 不可用时回退 Docker Ollama / qwen，写入 PostgreSQL，生成 Obsidian Markdown 笔记和 GitHub Pages HTML，并通过飞书发送精简通知。

KenRadar 不是纯下载脚本。它的目标是把视频流内容沉淀成可检索、可复盘、可发布、可重试的个人研究资料库。

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
Markdown 转 HTML，输出到 docs/ 供 GitHub Pages 发布
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
- GitHub Pages HTML 输出：`docs/`
- 数据库：PostgreSQL
- 转录优先级：FunASR `paraformer-zh` -> Whisper `large-v3-turbo`
- 当前 Whisper fallback 配置偏稳定：faster-whisper / CPU / int8
- AI 整理：主引擎 Agnes AI `agnes-2.0-flash`，OpenAI-compatible Chat Completions；备用引擎 Docker Ollama `qwen3.5:9b`
- Agnes API Key：通过环境变量 `AGNES_API_KEY` 提供，不写入仓库
- Agnes 免费额度按 `rpm_limit: 19` 控制；批量研究会在 AI 整理阶段排队，尽量保持在 20 RPM 免费限制以内
- Ollama endpoint：通常为 `http://127.0.0.1:11434/v1`
- FunASR endpoint：通常为 `http://127.0.0.1:18002/v1`
- Qwen3-ASR 当前禁用，仅保留兼容配置与代码
- Web 后台默认端口：`8765`
- `kenradarctl.sh` 默认 Web 监听 `0.0.0.0`，并默认托管启动 FunASR
- 飞书定位：通知流，只发摘要和链接，不发完整原稿或完整笔记

## 核心能力

- 抖音博主监控、手动检测和历史研究任务。
- 研究博主后自动加入持续监控；后续更新生成笔记时自动重建 GitHub Pages 目录，并按配置同步到 GitHub。
- 本地化抖音客户端抓取和下载，代码位于 `kenradar/vendor/douyin_downloader/`。
- FunASR 优先转录，服务不可用、超时、返回空文本或质量校验失败时自动回退 Whisper。
- GPU 调度器协调 ASR、Whisper 和 Ollama，支持文件锁、显存检测、阶段切换和 OOM 降级。
- Agnes AI 优先生成结构化 JSON：标题、摘要、核心内容、主题、标签、评分、推荐动作；Agnes 缺少 Key、限流或服务异常时，自动尝试 Ollama / qwen 备用 provider。
- 每条视频只生成一份最终 Obsidian 内容笔记。
- Markdown 自动转 HTML，输出到 `docs/`，用于 GitHub Pages 发布。
- 飞书 Card/Text 通知，按钮优先指向 GitHub Pages HTML 页面。
- PostgreSQL 记录来源、作品、转录、AI 分析、笔记、推送、告警、研究任务。
- Web 后台提供仪表盘、内容工作台、归档研究、来源管理、系统配置、系统监控。
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
├── docs/                           # Markdown 转 HTML 后的 GitHub Pages 输出目录
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
├── kenradarctl.sh                  # 本地服务控制脚本
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
qwen 结构化整理
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
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10
```

研究单视频适合临时归档一个未在监控列表中的视频：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml research-video "抖音视频链接或 aweme_id"
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
ai_model: "agnes-2.0-flash"
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

## 二、知识关联

- [[半导体]]
- [[光通信]]

## 三、分段原文

> 以下内容保持博主原意和论述顺序，仅修正明显错别字、ASR 识别错误、标点与断句。

### 1. 第一段主题

经过错别字和断句修正的博主原文，不做摘要、删减或扩写。

### 2. 第二段主题

下一段经过修正的博主原文。

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
    output_dir: ./docs
    public_base_url: ${KENRADAR_GITHUB_PAGES_URL}
```

生成 HTML：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml publish-pages
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml publish-research-job --job-id 1
```

输出示例：

```text
docs/
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

GitHub Actions：

- `.github/workflows/deploy-pages.yml` 会把 `docs/` 发布到 `gh-pages` 分支。
- 它只发布静态 HTML，不执行 KenRadar 采集和 AI 链路。

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
./kenradarctl.sh start
```

默认局域网访问：

```text
http://<局域网 IP>:8765/
```

仅本机监听：

```bash
HOST=127.0.0.1 ./kenradarctl.sh start
```

`app.web_base_url` 控制飞书和系统内生成的本地 Web 链接。`run_web()` 启动时会初始化数据库并启动内置调度器。如果 `kenradar/web/frontend/dist/` 存在，会优先服务 React/Vite 前端；否则回退到服务端模板。

页面分组：

```text
KenRadar Web
├── 仪表盘 / 情报概览
├── 内容工作台
│   ├── 内容任务
│   └── 失败重试
├── 归档研究
│   ├── 内容资料库
│   ├── 研究任务
│   ├── Markdown 笔记
│   └── 简报
├── 来源管理
│   ├── 博主管理
│   ├── 来源解析
│   └── 来源质量
├── 系统配置
└── 系统监控
    ├── 系统状态
    ├── 推送记录
    ├── 系统告警
    └── 运行日志
```

重要路由：

- `/`：仪表盘。
- `/operations`：内容任务。
- `/operations/retry`：失败重试。
- `/archive`：内容资料库。
- `/archive/research`：研究任务。
- `/research/jobs?id=...`：研究任务详情。
- `/archive/notes`：Markdown 笔记。
- `/archive/briefs`：简报。
- `/sources`：来源管理。
- `/config`：系统配置。
- `/logs/status`：系统状态。
- `/logs/pushes`：推送记录。
- `/logs/alerts`：系统告警。
- `/logs/runtime`：运行日志。
- `/aweme?id=...`：单条内容详情。
- `/file?path=...`：优先重定向到 `/aweme?id=...`。

Web 手动动作通过后台任务队列执行，避免阻塞 HTTP 请求。同一时间默认只运行一个重型任务，页面通过 `/api/status`、`/api/aweme/progress` 和研究任务接口轮询。

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
  database_url: postgresql://user:pass@localhost:5432/KenRadar
  web_base_url: http://172.30.10.150:8765

output:
  obsidian_root: ./data

publishing:
  github_pages:
    enabled: true
    output_dir: ./docs
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
    model: agnes-2.0-flash
    rpm_limit: 19
    max_tokens: 8192
    fallback_note: true
    providers:
      - name: agnes
        enabled: true
        api_type: chat_completions
        endpoint: https://apihub.agnes-ai.com/v1
        model: agnes-2.0-flash
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
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml init-db
```

## 常用命令

服务控制：

```bash
./kenradarctl.sh start
./kenradarctl.sh stop
./kenradarctl.sh restart
./kenradarctl.sh status
./kenradarctl.sh logs
```

FunASR 服务：

```bash
./kenradarctl.sh start-funasr
./kenradarctl.sh stop-funasr
./kenradarctl.sh restart-funasr
./kenradarctl.sh status-funasr
./kenradarctl.sh logs-funasr
```

常用 CLI：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml run-once
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml run-once --no-push
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml test-latest
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml research-video "抖音视频链接或 aweme_id"
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml summarize-existing --limit 10
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml cleanup-downloads
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml refresh-old-notes --dry-run
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml publish-pages
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml schedule
```

## FunASR 本地服务

KenRadar 默认优先调用 FunASR 服务进行转录。当前采用仓库内轻量 OpenAI-compatible 服务脚本，默认模型为 `paraformer-zh + fsmn-vad + ct-punc`，默认使用 `cuda:0` 启动并预加载模型。

健康检查：

```bash
curl -s http://127.0.0.1:18002/health
curl -s http://127.0.0.1:18002/v1/models
```

`./kenradarctl.sh start` 默认会先启动 FunASR。禁用自动托管：

```bash
KENRADAR_FUNASR_MANAGED=0 ./kenradarctl.sh start
```

## Qwen3-ASR 兼容配置

Qwen3-ASR 当前不参与生产转录链路，`ai.qwen_asr.enabled` 和 `start_on_fallback` 均应保持 `false`。以下命令仅保留作历史兼容参考，不应由 KenRadar 自动执行：

```bash
docker run -d --name kenradar-qwen3-asr \
  --gpus all \
  -p 127.0.0.1:18001:8000 \
  -v /data/Projects/KenRadar/data/model_cache/huggingface:/root/.cache/huggingface \
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
- `kenradar/core/obsidian.py`：Obsidian 路径、文件名、YAML 辅助函数。
- `kenradar/publishing/static_site.py`：Markdown 转 HTML，并维护 `docs/index.html`。
- `kenradar/notification/feishu.py`：飞书 Card/Text 通知、推送筛选、简报归档。
- `kenradar/scheduler/scheduler.py`：内置定时调度。
- `kenradar/storage/pg_database.py`：PostgreSQL schema、兼容视图和读写逻辑。
- `kenradar/web/`：本地 Web 后台。

## 验证

最小静态验证：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m compileall kenradar
```

Focused tests：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m pytest tests/test_config_and_publishing.py -q
```

Web 验证：

```bash
./kenradarctl.sh restart
./kenradarctl.sh status
tail -f data/kenradar.log
```

GitHub Pages 输出验证：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml publish-pages --limit 2
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
./kenradarctl.sh status-funasr
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
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml publish-pages --limit 2
find docs -maxdepth 3 -type f
```

### AI 返回非 JSON

KenRadar 会使用 `ai_json.py` 做松散解析和降级分析：

- 能解析则正常写入结构化摘要。
- 不能解析则生成保守 fallback。
- 降级结果不会伪装成高质量成功摘要。

## 当前不优先事项

- 新平台完整采集链路。
- 复杂权限系统和多用户支持。
- 替换 PostgreSQL。
- 在 GitHub Actions 中运行抖音采集、ASR、Whisper 或 Ollama。
- 大面积前端视觉重构。
- 恢复首页/详情页中的收藏、选题池、深度研究、备注等旧入口。
