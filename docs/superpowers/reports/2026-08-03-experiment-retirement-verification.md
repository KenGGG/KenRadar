# 实验功能退役验证报告

验证日期：2026-08-03

## 范围

本次验证覆盖公司研究、财务分析与 NotebookLM 运行时能力退役后的私有 KenRadar 分支。历史 PostgreSQL 表定义与 Alembic 0003–0005 兼容迁移仍保留，未执行删除、降级或数据清理。

## 自动验证结果

- Python 编译：`/home/ken/miniconda3/envs/openclaw/bin/python -m compileall kenradar scripts`，通过。
- 完整测试：`159 passed in 29.07s`。
- 前端类型检查：`npm run lint`，通过。
- 前端生产构建：`npm run build`，通过。
- 前端产物：主应用约 454.43 kB，vendor 约 421.73 kB。
- 迁移当前版本：`0011_backfill_douyin_sources (head)`。
- 迁移唯一 head：`0011_backfill_douyin_sources (head)`。
- 退役契约：后端模块、API 前缀、worker 任务类型、运行时 repository、前端组件和专属设计材料均不存在；历史兼容迁移仍存在。

## 当前生产服务只读检查

为避免隔离工作树抢占生产端口，本阶段未用改造分支重启 8765 服务。对当前运行中的私有主服务仅执行只读检查：

- `/health/live`：live。
- `/health/ready`：PostgreSQL 与 task_run ready。
- `/health/dependencies`：PostgreSQL、GPU 正常；飞书已配置；Ollama 未配置；总体可用。

## GitHub Pages

隔离工作树没有绑定生产 `data/github-pages` 仓库，故未在此阶段运行真实 Pages 生成或同步，避免接触现有内容仓库。静态发布与 GitHub dry-run 的单元测试已包含在完整测试集合并通过。真实 Pages dry-run 与改造分支重启检查将在代码整合到私有主工作区后执行，且不会启用 push。

## 数据安全

- 未执行 Alembic downgrade。
- 未执行 `DROP TABLE`、`TRUNCATE` 或实验数据导出。
- 未打印 Cookie、数据库连接串、Webhook、API Key 或 Web 密码。
- 工作树只通过被忽略的符号链接读取本地配置用于测试，链接未进入 Git。

## 待最终整合验证

1. 将完成的改造分支整合到私有 `main`。
2. 使用 `./ctl.sh restart` 启动改造后的代码。
3. 再次验证 health、dashboard、content、sources、insights 与 SSE。
4. 执行 Pages 本地生成和 GitHub 同步 dry-run，确认现有发布链路未变化。
