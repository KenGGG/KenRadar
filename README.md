# KenRadar V2

KenRadar 是本地优先的个人研究情报系统。它持续监控已订阅来源，将作品处理为可追溯的转录、AI 分析、Obsidian 笔记、静态页面和飞书简报。

当前生产链路以抖音视频为主；小宇宙节目、单集和 RSS 为已验证 MVP。系统不包含公司研究、财报分析或 SQLite 数据库功能。

## 处理流程

```text
来源订阅 → 扫描发现 → 持久任务 → 下载与转录 → AI 整理 → Markdown 笔记
        → PostgreSQL current result → GitHub Pages → 飞书通知
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

## 数据与发布

- 配置：`config/config.yaml`
- 本地笔记：`data/notes/`
- 简报：`data/briefs/`
- 临时下载：`data/Downloaded/`
- 静态页面：`docs/`
- PostgreSQL：由 `DATABASE_URL` 或 `app.database_url` 配置

发布服务优先返回 GitHub Pages 的公开 URL；未配置公开地址时，Web 回退到 V2 内容页或归档页。飞书仅推送精简摘要，不包含 YAML 或完整转录。

## 本地服务

- FunASR：默认 `http://127.0.0.1:18002/v1`
- Agnes：OpenAI-compatible Chat Completions，凭 `AGNES_API_KEY` 使用
- Ollama：仅作为 Docker HTTP 备用整理服务，不由 KenRadar 安装或管理

所有 GPU 转录与本地整理任务通过现有 GPU 调度器协调。

## 验证

```bash
python -m compileall kenradar scripts
python -m pytest tests/test_api_contract.py tests/test_delivery_tasks.py -q
cd kenradar/web/frontend && npm run lint && npm run build
curl -sS http://127.0.0.1:8765/health/ready
```

敏感 Cookie、API Key、数据库密码和飞书 Webhook 只保存在本地环境或配置中，不应提交。
