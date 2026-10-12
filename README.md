# KenRadar V2

KenRadar 是本地优先的个人研究情报系统。它持续监控已订阅来源，将作品处理为可追溯的转录、AI 分析、Obsidian 笔记、静态页面和飞书简报。

当前成熟链路以抖音视频为主；小宇宙节目、单集和 RSS 为 MVP。2026-10-10 的迁移实现采用 Windows 原生运行和 SQLite V2 存储，旧 PostgreSQL 仅用于离线源导出。原始生产数据尚未切换；真实平台和 GPU 链路待单独验收。

Windows 隔离运行示例：`./ctl.ps1 init -Config config/config.sqlite.example.yaml`，然后 `./ctl.ps1 start -Config config/config.sqlite.example.yaml`。该配置禁用外发与调度。详细变更、测试与回滚边界见 [迁移验收记录](docs/windows-migration/P1-core-verification.md) 和 [离线迁移与备份](docs/windows-migration/P2-migration-and-backup.md)。下文保留原 Ubuntu 运行说明供迁移核对，不应作为当前 Windows 启动步骤。

## 处理流程

```text
来源订阅 → 扫描发现 → 持久任务 → 下载与转录 → AI 整理 → Markdown 笔记
        → SQLite V2 current result → 独立静态发布 → 独立通知
```

每条内容以 `platform + external_content_id` 定位，当前结果保存在 `content_item`、`transcript`、`ai_analysis` 和 `content_note` 中。Web 内容地址为：

```text
/content?platform=<平台>&external_id=<外部内容 ID>
```

## 运行

使用已安装项目依赖的 Python 环境：

```bash
./ctl.sh start
./ctl.sh status
./ctl.sh restart
python -m kenradar --config config/config.yaml migrate
```

常用任务：

```bash
python -m kenradar --config config/config.yaml run-once
python -m kenradar --config config/config.yaml research-blogger --blogger "博主名称或 sec_uid" --limit 10
python -m kenradar --config config/config.yaml research-video "抖音视频链接或外部 ID"
python -m kenradar --config config/config.yaml research-xiaoyuzhou "URL" --limit 1
python -m kenradar --config config/config.yaml publish-pages
```

## 处理中心

`/run` 以 V2 持久任务为统计单位，通过 SQLite 分类、计数和分页，每 10 秒刷新：

- **执行队列**：有效租约的执行任务、排队任务、等待自动重试的任务。
- **待处理**：失败、部分失败、暂停和等待租约回收的任务，可按状态筛选。
- **历史记录**：成功、取消和已退役功能的执行记录，保留原始状态供追溯。

任务默认显示精简行，展开后查看错误原因、处理建议、时间和步骤进度，并按状态暂停或继续。研究批次进入独立批次页；内容降级、发布失败和系统告警分别查看，不与执行任务重复累计。内容质量区只统计当前已载入的内容。

## 数据与发布

- 配置：`config/config.yaml`
- 本地笔记：`data/notes/`
- 简报：`data/briefs/`
- 临时下载：`data/Downloaded/`
- 静态页面：`docs/`
- SQLite 文件库：由 `DATABASE_URL` 或 `app.database_url` 配置；环境变量优先，PG URL 不可用于正常运行

发布服务优先返回 GitHub Pages 的公开 URL；未配置公开地址时，Web 回退到 V2 内容页或归档页。飞书仅推送精简摘要，不包含 YAML 或完整转录。

## 本地服务

- FunASR：默认 `http://127.0.0.1:18002/v1`
- Agnes：OpenAI-compatible Chat Completions，凭 `AGNES_API_KEY` 使用
- Ollama：仅作为 Docker HTTP 备用整理服务，不由 KenRadar 安装或管理

所有 GPU 转录与本地整理任务通过现有 GPU 调度器协调。

### Windows FunASR

使用 Python 3.11 环境安装官方 [FunASR](https://github.com/modelscope/FunASR)：

```powershell
.\.venv\python.exe -m pip install -e ".[funasr]" faster-whisper
.\scripts\funasr.ps1 start
.\scripts\funasr.ps1 status
```

将 `config/funasr.example.yaml` 的配置合并到本地 `config/config.yaml`。
首次启动会下载 Paraformer、FSMN-VAD 和标点模型，可能需要数分钟。
默认设备自动选择；只有 PyTorch 检测到 CUDA 时使用 GPU，否则使用 CPU。
服务监听 `127.0.0.1:18002`，空闲 300 秒后退出，下一次转录按需启动；日志位于
`data/funasr_server.log`。Windows 无需 Bash；Linux 继续使用原来的 shell 启动脚本。
FunASR 失败时仍回退 Whisper。未在 PATH 中安装 FFmpeg 时，音频提取可使用
可选依赖 `imageio-ffmpeg` 的随包可执行文件。

## 验证

```bash
python -m compileall kenradar scripts
python -m pytest tests/test_api_contract.py tests/test_delivery_tasks.py -q
cd kenradar/web/frontend && npm run lint && npm run build
curl -sS http://127.0.0.1:8765/health/ready
```

敏感 Cookie、API Key、数据库密码和飞书 Webhook 只保存在本地环境或配置中，不应提交。
