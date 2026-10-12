# Hermes → KenRadar → GitHub Pages → 返回链接

2026-10-12 已完成真实验收。肖星视频 `7694252203724262682` 的任务 17 返回 `github_synced: true`、`public_url_ready: true`，Pages 正文 HTTP 200，并保留原始转录。发布提交为 `e46eb512c`。本次复用了先前真实完成的转录和 AI 分析；未用这次复用验收冒充一次全新视频的重新下载/转录。

## Hermes 的调用方式

将工作目录设为 `D:\Projects\KenRadar`，执行以下命令，读取 UTF-8 标准输出的 JSON。这个命令属于当前仓库，不需要改动 Hermes 环境或安装另一套运行库。

```powershell
.\.venv\python.exe -m scripts.hermes_process_link "抖音视频链接"
```

命令提交已有持久任务，由 KenRadar worker 执行下载、转录、AI 整理、HTML 生成、独立 Pages 仓库同步及公开链接可访问性检查。已成功整理的视频会复用现有笔记。调用方读取 `ok`、`task_id`、`public_url`、`public_url_ready`、`github_synced`；只有同步和链接都通过才返回 `ok: true` / 退出码 0。Hermes 应将 `public_url` 返回给用户。

失败返回 `ok: false`、非零退出码、错误与任务查询路径。相同链接默认复用同一个任务；恢复网络等条件后使用 `--retry` 创建新的持久尝试，仍不强制重复 AI 整理。等待超时不会删除后台任务，可继续查询。

如果 Hermes 已使用 HTTP 接口，继续调用现有接口即可：

```http
POST http://127.0.0.1:8765/api/process-url
Content-Type: application/json

{"url":"https://www.douyin.com/video/7694252203724262682","push":false,"force":false}
```

提交得到 `task_id` 后，查询 `GET /api/task-run?id=<task_id>`，在 `item.stats_json` 中读取公开链接与发布状态。任务列表的结果也包含公开链接、是否就绪和本地备用入口。保留现有认证和 CSRF 检查，不通过关闭保护来提供接口。本地 Web 与 worker 必须运行。

## 本轮修复

- 启用现有独立发布配置：输出/同步目录 `data/github-pages`，目标 `KenGGG/KenRadar-pages` 的 `gh-pages`，允许自动 commit/push，仅 HTML 等公开产物进入发布仓库，主项目源码和配置不推送。
- 已归档笔记补生成 HTML 后再同步，AI 整理失败不进入成功发布分支。
- Windows 下数千个路径导致 Git 命令超长，改为按 UTF-16 长度分批 status/add；已真实完成自动推送。
- 保留此前线上博主目录与批次页面，量化Quantgirl 129 篇目录仍按原视频发布时间倒序。
- 同步失败不把已有旧页面 HTTP 200 当作本次发布成功。Hermes 命令默认不发送飞书。

相关最终测试 109 passed；此前任务回归和接口链接返回测试也通过。尚未直接操控 Hermes 发起一次新视频研究，验证的是其可调用命令、真实 worker 任务和 HTTP 返回合同；Hermes 侧需使用上述命令或现有接口读取结果。

## 回滚与证据

发布前配置备份 `data/test-migration/hermes-ai-repair/config-before-publication.yaml`；真实任务返回存于 `published-result.json`，持久任务 17 和 Git 提交保留发布记录。关闭 `publishing.github_sync.enabled/auto_commit/auto_push` 可停止自动外发；已发布内容需通过 Pages 仓库的新提交回滚，本轮未撤销公开页面。未修改 Hermes 或其他项目环境。
