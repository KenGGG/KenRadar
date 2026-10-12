# 量化 Quantgirl 重试与发布配置（2026-10-11）

## 真实抓取及结果

任务 7、研究批次 3 的实际浏览器日志：`count=130 pages=8 complete=True`。作者标识校验、作品 ID 去重和分页末尾检查均执行。130 条公开作品中，1 条图文被现有视频流程排除，129 条进入视频研究。不能把图文称为已经转录或归档的视频，也不能承诺包含未来新增、私密或平台隐藏作品。

批次已经结束：83 条此前成功后跳过，1 条新增完整成功，45 条失败。失败分布为 42 条 Agnes TLS/SSL EOF、1 条 AI 输出无法解析为 JSON、2 条转录失败。当前成功正文共 84 条；下载、转录和 AI 整理是不同阶段，完整研究仍未达成。

之前的根因包括抖音直接接口空列表、错误的演示媒体匹配、AI JSON 被重复包装、失败整理被误记成功；前几项已在此前修复。本次新发现的短视频时长误判：`7282422173682224421` 的 `video.duration=9148` 毫秒被阈值判断为 9148 秒，使 58 字转录误触发 400 字要求。质量判断已按真实抖音 `video.duration` 单位修复，103 项相关测试通过，任务结束后重启加载。该短视频尚未通过修复后的真实重新处理，不能记为研究成功。另一条 8.498 秒视频仅识别出 2 字，仍受最小文本阈值约束，未降低阈值伪造成功。

## 续用现有 GitHub Pages

已只读核实 `KenGGG/KenRadar-pages`：默认和现存分支为 `gh-pages`，HTML 在仓库根目录；根目录有 `.nojekyll`、`index.html`、`notes/` 和 `briefs/`。现有公开地址 `https://kenggg.github.io/KenRadar-pages/` 返回 HTTP 200。

准备发布时，应独立克隆该仓库到 `data/github-pages/`，不要将 KenRadar 应用仓库本身作为同步目录。保留历史 HTML；重建新首页前需保留旧首页入口，并核对新旧索引，防止原来的内容失去首页入口。本轮未克隆覆盖旧输出、生成公开内容、提交或推送。

目标配置（合并到现有 publishing，准备阶段保持各开关关闭）：

```yaml
publishing:
  github_pages:
    enabled: false
    output_dir: ./data/github-pages
    public_base_url: https://kenggg.github.io/KenRadar-pages
  github_sync:
    enabled: false
    repo_dir: ./data/github-pages
    auto_commit: false
    auto_push: false
    include_html_docs: true
    include_markdown_notes: false
    include_briefs: false
    include_transcripts: false
```

GitHub Settings → Pages 核对发布来源 `gh-pages`、`/(root)`（若已使用其他 Actions 发布流程则先核对现有流程，不直接替换）。Windows 还需为此仓库配置 Git 写入凭据；本次读取公开仓库成功不等于推送权限通过。设置中的“GitHub 本地检查”仅检查本地 Git，不能代表发布成功。确认生成结果和历史链接后才开启生成、同步、自动提交及推送，并做一次实际发布验收。

## 飞书提醒设置

1. 在目标飞书群中打开群设置 → 群机器人 → 添加机器人 → 自定义机器人，名称可填 KenRadar。
2. 复制机器人 Webhook，在 KenRadar 设置 → 发布与通知 → 飞书 Webhook 中选择替换并粘贴；或者填到本地 `.env` 的 `FEISHU_WEBHOOK_URL`。只选一种来源，环境变量优先于页面的本地值。不要把 Webhook 提交到 GitHub。
3. 使用关键词安全设置时，要允许正式消息的“流媒体”和连接测试消息的“KenRadar”。当前实现未接入签名密钥，不要仅开启签名校验后期待现有代码直接通过。
4. 打开通知总开关、飞书通知，保持“通知包含全文”关闭，保存。手动点击“发送飞书测试消息”会实际发到群里。
5. 发布地址配置正确且 Pages 可访问后，研究完成提醒才能链接到公开页面；`127.0.0.1` 链接不能供手机或他人访问。

本轮通知仍关闭，Webhook 尚未配置，未发送测试或正式提醒。等待用户在本地填写 Webhook 和确认群后才能进行真实验收。

## 回滚与限制

本轮新增代码变动只涉及转录质量判断和回归用例，可逐项恢复；没有覆盖原始媒体或数据库内容，没有修改当前发布/通知开关。实际全量重试由用户在界面发起，保留原任务审计。若要退回旧代码，先停止本应用进程，逐项恢复改动后重启；不要 reset/clean 丢弃其他未提交迁移。
