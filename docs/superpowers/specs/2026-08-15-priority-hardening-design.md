# KenRadar 优先级加固设计

日期：2026-08-15

## 目标

在不改变现有抖音、小宇宙、PostgreSQL、Obsidian、GitHub Pages、飞书和持久任务主链路的前提下，完成当前最高优先级加固：关闭默认局域网裸奔入口，消除数据库版本漂移，统一来源与价值判断口径，收敛未接通的任务基础设施，降低首屏负载，修正健康状态，并控制重复告警。

## 设计原则

1. PostgreSQL 是运行状态和来源订阅的唯一事实源；YAML 中的 `bloggers` 只承担启动导入和兼容导出。
2. 继续以 `task_run + research_job + research_job_item` 为生产任务模型。`task_step`、`outbox_event`、`artifact` 表保留迁移兼容，但未完成前不暴露可误用的 CLI/worker。
3. 批次任务与内容结果分离：批次允许部分失败，内容阶段失败可单独重试；只有任务本身不可执行时才触发整批重试。
4. 所有高价值、推荐、推送和深度研究判断从同一个策略模块读取。
5. 安全和数据库版本问题采用 fail-closed；可选外部依赖采用 degraded，而不是让整个服务不可用。

## 1. Web 安全与启动门禁

- `ctl.sh` 默认绑定 `127.0.0.1`。
- 非回环地址必须配置 `KENRADAR_WEB_PASSWORD` 或 `app.web_password`，否则 Web 启动失败。
- 保留 Basic Auth 以兼容现有前端，但明确其只适用于可信网络；非回环部署应位于 TLS 反向代理或 VPN 后。
- POST 继续执行 Origin/Sec-Fetch-Site 校验；安全测试覆盖回环、非回环、环境变量密码三种情况。
- Web、worker 启动前检查 Alembic current 等于 head。`ctl.sh start` 仍先执行迁移；绕过控制脚本直接启动时，如果版本落后则明确失败。
- 版本接口动态报告应用版本、当前 Python 和 Alembic current/head，不再硬编码。

## 2. 来源事实源

- 新增幂等同步函数，将 YAML 中的抖音来源导入 `source_subscription` 和 `creator`。
- 启动和迁移后执行一次导入，不反向覆盖数据库中的启用状态。
- `Checker.load_targets()` 优先读取数据库订阅；数据库为空时才回退 YAML，并立即同步。
- Web 来源增删改写数据库；为兼容现有部署，可同步更新 YAML，但监控和统计统一读数据库。
- 增加一致性诊断，报告 YAML/数据库数量差异，不输出来源敏感字段。

## 3. 统一策展策略

- 新增 `CurationPolicy`，集中管理 5 分制阈值和推荐动作：
  - high value：默认 3.5；
  - push：默认 4.0 或动作 `push`；
  - deep research：默认 4.2 或动作 `research`；
  - 10 分制只在 API/UI 边界转换。
- 兼容现有 `push_threshold_rating`，将其转换为 5 分制；未配置时使用默认值。
- Web 查询、来源聚合、飞书筛选和前端 smart view 均消费后端返回的策略值，不再各自硬编码。
- 当一批内容没有达到推送阈值时全部归档；不得因为筛选结果为空而退回推送低价值或失败摘要。

## 4. 任务模型收敛与失败语义

- 从 CLI 隐藏 `step-worker`，并标记 processing handlers 为实验兼容代码；不删除历史表和迁移。
- `TaskWorker` 只在结果明确 `status=failed/error/cancelled` 或出现任务级异常时重试整批。
- `failed > 0` 且存在成功/跳过项时，任务保存为成功完成的批次结果，并在统计中报告 `partial_failed`；失败内容通过已有 retry API 单独处理。
- `run_once`、研究任务和批量重试统一返回 `total/success/failed/skipped/status`，同时保持旧字段兼容。
- 发布、推送和 Git 同步继续使用已有幂等/资源锁；不在整批重试中重复已成功副作用。

## 5. Bootstrap 与 API

- `/api/bootstrap` 只返回导航与首屏必需数据：系统、配置、来源概要、最近任务/告警/推送和有限条最近内容。
- 内容库通过现有 `/api/content-items` cursor 接口分页；详情继续使用 `/api/aweme/detail`。
- 笔记、简报和日志改为独立懒加载接口，避免把 Markdown 正文和历史日志放进首屏。
- 保留旧字段一个兼容周期，但默认 bootstrap 目标小于 500KB、1 秒内返回（本机 PostgreSQL）。

## 6. 依赖健康检查

- `/health/live` 只证明进程存活。
- `/health/ready` 检查 PostgreSQL、迁移版本和任务表；任一失败返回 not-ready。
- `/health/dependencies` 分别检查：PostgreSQL、Agnes 配置/可达性、FunASR 配置/按需状态、Ollama fallback、GPU、飞书配置、GitHub 发布配置。
- 不主动启动按需服务，不发送真实飞书消息；状态统一为 `ok/configured/idle/degraded/unavailable/disabled`。
- Ollama 从所有 provider 中按 `api_type=ollama` 查找，不再假设第一个 provider。

## 7. 告警聚合与恢复

- 为 `alert_log` 增加 `fingerprint`、`occurrence_count`、`first_seen_at`、`last_seen_at`、`resolved_at` 和聚合窗口字段。
- 指纹由 level、component 和规范化消息生成，不包含作品 ID、URL 或瞬时数字。
- 同一指纹在聚合窗口内更新计数而不重复推送；首次出现和窗口后持续失败才通知。
- `recovered()` 解析对应未恢复指纹并只发送一次恢复通知。
- Web 健康页展示活跃告警数量和累计次数；历史数据保持可读。

## 8. 兼容性与迁移

- 新增 Alembic 迁移承载告警字段和必要索引。
- 保留旧视图、旧 Markdown 路径、旧 API 响应字段和已有 GitHub/飞书链接。
- 不改变 Obsidian frontmatter、四个固定章节或转录保存规则。
- 不删除用户生成的 `docs/`、`data/notes/`、`data/briefs/` 和运行数据。

## 9. 验证

- 单元测试：安全绑定、迁移门禁、来源导入/优先级、统一阈值、部分失败、健康状态、告警聚合与恢复。
- API 测试：bootstrap 结构、分页内容、health 状态和版本信息。
- 前端测试：不依赖 bootstrap 全量内容，smart view 使用服务端策略。
- 静态验证：compileall、完整 pytest、TypeScript lint、Vite build。
- 真实验证：当前 PostgreSQL 升级至 head，查询来源/内容/告警，重启 Web/worker，验证 loopback 访问、非回环安全门禁和接口性能。

## 非目标

- 不新增平台完整采集链路。
- 不重写 Workflow 或切换 Web 框架。
- 不把 `task_step/outbox/artifact` 扩展为新的生产编排系统。
- 不改变 GitHub Pages 或飞书的内容产品形态。
