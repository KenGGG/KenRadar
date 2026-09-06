# KenRadar V2 验收记录（2026-09-06）

## 已完成的代码与自动验证

- V2 迁移链静态检查到 `0017_publication_notification_logs`，且 `alembic heads` 只有一个 head。
- 来源订阅、历史扫描、确认后逐项执行、当前结果读取、独立发布/通知任务、发布与通知审计，以及六入口导航已接线。
- 发布和通知只接收 `content_item_id` 或 `research_job_id`；失败路径不会调用下载、转录或 AI 链路。
- 只读对账脚本：`python scripts/verify_v2_media_radar.py --config config/config.yaml`。
- 已通过：
  - `python -m compileall -q kenradar scripts`
  - V2 API contract tests for health isolation, history scan registration, generic content result, operation history and delivery registration。
  - `python -m pytest tests/test_delivery_tasks.py -q`（4 passed）
  - `python -m pytest tests/test_task_worker.py tests/test_source_monitor.py tests/test_verify_v2_media_radar.py tests/test_dependency_health.py -q`（21 passed）
  - `npm run lint` 与 `npm run build`
  - `npx tsx src/components/NavigationModel.test.ts`

## 真实环境验收状态

PostgreSQL 运行于本机 Docker 网络，受限沙箱不能直连；在受控运行环境中已正常访问。已生成迁移前备份 `data/backups/kenradar-pre-0017-20260906.dump`，并成功将真实数据库从 `0016_scan_confirm_execute` 迁移到 `0017_pub_notification_logs`。`publication_log` 和 5 个 `push_log` V2 字段均已确认存在。

`python scripts/verify_v2_media_radar.py --config config/config.yaml` 已返回三类空差异。期间使用内置、幂等的来源回填补齐了 11 个抖音订阅；对账脚本也已修正为按真实平台处理历史小宇宙兼容记录，而非全部误标为抖音。

重启后的 Web 与 worker 正常运行；`/health/live`、`/health/ready`、`/health/dependencies` 均成功，数据库、schema、Agnes、Ollama、GPU、飞书和 GitHub 发布配置为可用状态。真实 Web API 已读取一条抖音和一条小宇宙内容，二者都返回当前转录、分析和笔记。

尚未执行外部 GitHub Pages 发布或飞书发送：自动审批要求对该公开发布和消息发送作出明确授权。获得授权后，只需对已验证的现有内容运行一次独立发布、一次独立通知任务，并确认审计记录与无重复发送，再完成最终切换验收。
