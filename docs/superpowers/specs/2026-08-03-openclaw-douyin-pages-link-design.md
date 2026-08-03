# OpenClaw 抖音处理回复 GitHub Pages 链接设计

## 目标

用户向 OpenClaw 发送抖音链接后，`douyin-process` skill 调用 KenRadar 完成单视频归档。OpenClaw 保留现有精简回复，并在 GitHub Pages 页面确认可访问后附加“阅读全文”链接。

成功标准：

- 新视频和已归档视频都能得到由 KenRadar 生成的公开页面 URL。
- OpenClaw 只回复已经确认可访问的 GitHub Pages URL。
- GitHub 同步失败或 Pages 部署超时时，不返回可能 404 的公开链接。
- 失败时仍保留本地归档结果，并提供明确的降级说明和本地 Web 详情链接。
- OpenClaw 回复不暴露本地绝对文件路径。

## 方案选择

采用“KenRadar 负责发布与确认，OpenClaw skill 负责调用与展示”的边界。

不采用由 skill 根据 Markdown 路径自行拼接 URL的方案，因为它会复制 KenRadar 的路径、编码和发布规则。暂不把调用方式整体迁移为异步 Web API；当前 CLI 持久任务已经能返回结构化任务结果，本次只扩展其结果契约。

## 组件职责

### KenRadar 单视频工作流

`Workflow.research_video` 负责：

1. 解析并处理视频，生成 Obsidian 笔记与本地 HTML。
2. 通过现有 `StaticSitePublisher` 取得规范化公开 URL。
3. 通过现有 `GithubSyncManager` 执行一次 Git commit/push。
4. 在同步成功后有限轮询公开 URL，确认页面可访问。
5. 将发布结果写入持久任务的 `stats_json`，供 CLI 和其他调用方读取。

已经完整归档的视频不重复下载、转录或 AI 整理，但仍需重新计算公开 URL；若页面尚不可访问，则补做同步与确认。

### 发布确认

复用现有公开 URL就绪检查能力，避免引入第二套 HTTP 检测逻辑。默认策略：

- 每 5 秒检查一次。
- 最多等待 90 秒。
- HTTP 成功响应才视为就绪。
- 同步关闭、同步失败或等待超时均返回明确状态，不把本地 HTML 存在等同于远端可访问。

等待参数应从配置读取，并提供上述默认值，便于测试和不同部署环境调整。

### OpenClaw `douyin-process` skill

skill 继续调用 KenRadar `research-video` 命令并等待任务结束，然后读取任务返回结果，而不是扫描文件名或自行拼接公开 URL。

skill 的回复规则：

- `public_url_ready=true`：保留精简内容，并追加 `阅读全文：<public_url>`。
- 页面未就绪：说明内容已归档但公开页面仍在部署或同步失败，不输出未确认的 Pages URL；可提供 `detail_url` 作为本地 Web 入口。
- 内容处理失败：说明真实失败阶段，不输出公开链接。
- 不向用户展示 `summary_path`、项目目录或其他本机绝对路径。

## 返回数据契约

`research-video` 的任务结果保留现有字段，并增加：

```json
{
  "public_url": "https://example.github.io/KenRadar-pages/notes/douyin/...html",
  "public_url_ready": true,
  "github_synced": true,
  "github_sync_message": "GitHub 同步完成"
}
```

字段语义：

- `public_url`：由发布器生成的规范公开 URL；无法生成时为空字符串。
- `public_url_ready`：远端 URL 已确认可访问时才为 `true`。
- `github_synced`：本次同步命令成功且同步功能已启用。
- `github_sync_message`：供日志和降级回复使用的简短结果，不包含凭据。

`detail_url` 继续表示本地 Web 详情地址，不与 `public_url` 混用。

## 回复格式

成功示例：

```text
✅ 已完成：视频标题
博主：示例博主

一句话结论：……

核心观点：
- ……
- ……

阅读全文：
https://example.github.io/KenRadar-pages/notes/douyin/...html

完整原文、结构化整理和知识关联请打开上面的页面查看。
```

发布未确认示例：

```text
✅ 内容已完成归档：视频标题

一句话结论：……

公开页面仍在部署，暂未返回未确认的链接。
本地详情：http://127.0.0.1:8765/aweme?id=...
```

## 错误处理

- Git 同步失败不回滚已经生成的笔记和本地 HTML。
- Pages 确认超时不触发视频重新处理，只记录发布未就绪。
- URL 检查不得记录认证信息、Cookie 或 API Key。
- 发布结果必须进入任务统计，避免 skill 依赖日志文本解析。
- AI 降级结果继续遵循现有规则，不得伪装为成功摘要或可发布完成状态。

## 测试

KenRadar 自动化测试覆盖：

- 新视频成功处理、同步并确认公开 URL。
- 已归档视频复用结果并返回公开 URL。
- 中文标题和路径生成正确编码的 URL。
- GitHub 同步失败时保留归档结果，但 `public_url_ready=false`。
- Pages 等待超时时不返回可用链接标记。
- CLI 持久任务结果包含新增字段。

skill 验证覆盖：

- 成功结果保留现有精简回复并附加已确认的公开链接。
- 发布超时或失败时不输出未确认链接。
- 回复不包含本机绝对路径。

## 非目标

- 不改变 GitHub Pages 的仓库、分支或 Actions 架构。
- 不在 GitHub Actions 中运行采集、转录或 AI 整理。
- 不将 OpenClaw 调用整体迁移到新的异步 API。
- 不改变飞书推送格式和现有定时监控流程。
