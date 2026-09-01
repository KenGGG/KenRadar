# KenRadar V2 Delivery Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement the linked plans in order. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前仓库和当前 PostgreSQL 上，渐进交付双平台媒体雷达 V2，并保持现有生产链路可用。

**Architecture:** 四份子计划按依赖顺序执行。每份计划都产生可独立验收的软件增量；不得并行修改同一迁移链、任务状态或 `Workflow` 热路径。

**Tech Stack:** Python 3.10+、PostgreSQL、Alembic、React 19、TypeScript、Vite、pytest

**Spec:** `docs/superpowers/specs/2026-09-01-kenradar-v2-design.md`

## Global Constraints

- 本地优先、单用户、单体应用。
- 当前 PostgreSQL 是唯一事实源，通过 Alembic 渐进迁移。
- 生产任务只使用现有 `task_run + task_attempt`；不新增平行 `job` 系统。
- `task_step` 和 `outbox_event` 暂停扩展，不作为 V2 主链路依赖。
- 首发只支持抖音和小宇宙；本轮不实现 B站或 YouTube。
- 每条内容只保留一套当前媒体、转录、分析和主笔记。
- 重新分析和重新转录必须成功后替换；失败保留旧成功结果。
- 保留现有 Obsidian Markdown 结构和稳定文件路径。
- GitHub、飞书失败不得触发下载、ASR 或 AI。
- 公司研究、财务研究功能保持不动。

---

## 执行顺序

1. `2026-09-01-kenradar-v2-task-foundation.md`：M0-M1，先补齐任务控制与崩溃恢复。
2. `2026-09-01-kenradar-v2-content-core.md`：M2-M4，统一连接器并实现当前结果安全替换和双平台单链接。
3. `2026-09-01-kenradar-v2-subscriptions-backfill.md`：M5-M6，交付数据库来源调度及扫描—确认—执行。
4. `2026-09-01-kenradar-v2-publishing-cutover.md`：M7-M8，拆分发布通知，收敛 WebUI 并完成真实双跑。

## 总体验收

- 每份子计划的 focused tests 必须先通过，再运行完整 Python 测试。
- 涉及前端的子计划必须通过 `npm run lint` 和 `npm run build`。
- 每次 Alembic 迁移必须在测试数据库和生产备份副本演练。
- M4、M5、M6、M7、M8 必须留下真实链路验收记录，mock 通过不能标记为生产可用。
- 任一阶段回归抖音生产链路时停止后续计划，先恢复当前稳定行为。
