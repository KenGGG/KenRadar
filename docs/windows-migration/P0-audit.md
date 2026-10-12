# P0 核查记录 — 2026-10-10

HEAD：`73630013372db1286d958ebe5bf1f680d087bcca`，与规格一致。

当前工作区已有 Windows/FunASR、文件锁、配置、前端查询、依赖和 README 改动，以及旧方案文档删除。本轮不还原、不合并提交这些用户改动。首次审计保存到 `data/test-migration/p0/preexisting.patch` 和 untracked-hashes.json（本地，不发布）。

## 范围与契约

`scripts/audit_portability.py` 扫描 runtime/scripts/tests 的 SQL、Repository 方法、平台特定调用和 API 路由调用位置；首轮发现 405 SQL 常量、821 兼容性调用位置，详见本地 inventory.json。该清单包含迁移与测试中的历史 SQL，不能视为已修复数量。

| 范围 | 当前 | 目标/核对边界 |
| --- | --- | --- |
| storage/pg_database.py | psycopg、PG schema、业务方法 | SQLAlchemy Core + SQLite；业务身份、关系、返回键保留 |
| repositories/task_run.py/runtime.py | SKIP LOCKED、修改 CTE、分离 attempt | IMMEDIATE 短事务、attempt/审计同提交、租约 token fencing |
| current_content.py | 同连接替换当前结果 | 成功结果保留、原稿版本审计、提交时校验租约 |
| source_monitor/research_job/publication | 订阅、扫描确认、发布通知 | 自然键、幂等键、失败独立恢复 |
| migrations/versions | PG 0001–0018 | 冻结；SQLite 独立 Alembic 链 |
| web/queries + API routes | 原始 PG SQL、部分 PG import | 逐个请求验证；保持旧内容和批次 URL |
| core/config + settings | YAML/.env/进程变量、整表保存 | 明确覆盖来源、按组 revision、秘密三态 |
| frontend | ConfigEditor/Nav/App | 六入口、草稿与服务端分离、真实 API 联调 |
| scripts/ctl.sh | Bash 进程管理 | Windows 原生入口、受控停止与租约恢复 |

Schema 映射：SERIAL/BIGSERIAL → INTEGER PK；JSONB → 校验的 JSON 文本，读取恢复类型；TIMESTAMPTZ → UTC 固定精度；布尔 → 0/1；自然键/外键/唯一键和状态枚举保留。退休表/兼容视图不恢复。索引、约束与所有新增列需逐项对照 0018 head，不能执行 PG 历史迁移后 stamp。

API 路由入口清单由 inventory.json 的 route_callsites 保存，接口包括内容/归档/订阅/研究批次/任务控制/设置/健康/发布通知；原 `/content?platform=...&external_id=...` 保留。

## 实际基线

- 仓库内独立 Conda prefix `.venv/python.exe` 可运行，Python 3.11.17、SQLite 3.54.0、SQLAlchemy 2.1.4；未使用其他项目环境。
- 首次 pytest：5 passed / 5 failed / 31 skipped（maxfail=5）；失败来自 API contract 测试硬编码 `/tmp`。PG 集成跳过不是通过。
- Focused 原测试首次执行：2 passed / 3 errors；默认沙箱临时目录无法创建。后续明确使用仓库独立测试目录，不更改系统临时目录。
- 没有读取真实数据库记录或秘密；本轮没有旧 PG 导出源，真实迁移待验。

## 风险与回滚

运行文件库可能因租约过期发生旧 worker 返回，必须拒绝所有旧结果；长推理不得占有写事务。设置 revision 不能覆盖未保存草稿。公开发布与通知必须独立，失败不触发重转录。

本阶段仅新增审计和修订冲突约束，没有更改生产配置或数据。回滚按本轮 diff 撤销新增文件/段落，保留 preexisting.patch 对照；不要整体还原整个工作区。
