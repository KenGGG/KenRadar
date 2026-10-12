# P2 离线迁移与备份 — 2026-10-10

本阶段工具演练通过，**真实 PG 迁移仍待源验证**。未改生产配置、未覆盖原库、未恢复生产写入。

## 实际修改与测试

- `offline_migration.py`：PG 可选只读导出器，在同一个 REPEATABLE READ/READ ONLY 快照中导出 22 个 V2 表。未知/缺失表拒绝静默遗漏。JSONB 以文本导出，时间/Decimal/二进制明确编码；不能无损表达的 Decimal 拒绝转换。
- 全新 `*.importing.sqlite3` 临时目标，独立 Alembic 初始化，逐表内容/数量/主键投影哈希、平台/状态分类、FK/integrity 检查；manifest 与路径映射绑定恢复检查点。
- 历史非终态任务/步骤默认暂停；running attempt 标记 abandoned，过期交付标记 unknown；原成功记录、公开 URL、幂等键保持，规范化另写 migration 审计。
- 只改已声明的路径字段，不改正文/JSON/URL。笔记与简报包逐文件哈希、复制核对，存在不同目标文件时拒绝覆盖；缺少持久笔记与已清理媒体/转录中间文件分开列报。
- `sqlite_backup.py`：运行中库使用 sqlite3 backup API；关闭后的快照完整性、逐表内容哈希、行数与 schema 核对。恢复仅到 `*.restoring.sqlite3`。
- 完整应用包需要明确停写窗口，受管理 Web/worker 仍运行时拒绝；包含 DB、notes/briefs、脱敏配置和文件 manifest，排除 `.env`/Cookie 资料。恢复文件只到全新 `*.restoring` 数据目录。
- `scripts/migrate_v2.py`：独立导出/导入/备份/恢复 CLI，不启动服务或切换配置。PG 凭据通过环境变量读取，错误不打印 DSN/原始记录。

`tests/test_offline_migration.py`：**6 passed，4.88 秒**（pytest-p2e）。使用非空 V2 fixture：内容/原稿/分析/笔记、任务/attempt/outbox 和真实文件。测试覆盖原稿与 URL 不误替换、长字符串 ID、交付暂停、重复恢复不增记录、篡改拒绝、Decimal 精度、WAL 在线快照、完整应用临时恢复与拒绝覆盖。独立子进程在表提交后、检查点写入前强制退出，再恢复导入成功。

这些是工具与 fixture 证据，不能证明 Ubuntu/真实 PG 的数据、文件和前后 API 输出已经一致。

## 手工运行入口

在旧源端安装 PG 可选依赖后，通过 `KENRADAR_MIGRATION_PG_URL` 指定只读连接；先停止旧系统所有 DB/文件写入，再执行：

```powershell
python -m scripts.migrate_v2 export-pg --package <新目录> --data-root <旧data根> --writers-stopped
```

新 Windows 端不需 PG 服务或 psycopg。路径映射 JSON 只包含明确旧根 → 新根：

```powershell
.\.venv\python.exe -m scripts.migrate_v2 import --package <导出包> --target data/migration/kenradar.importing.sqlite3 --path-map <映射JSON>
```

中断后使用同一 manifest、目标与映射加 `--resume`。只持有 `.dump` 时需在隔离 PG 正规恢复，再执行源端导出；此工具不直接读取 PG 自定义 dump。

## 未完成与回滚边界

- 真实源版本、所有实际表覆盖、真实笔记文件、交付历史与迁移前后同组 API 等价，尚无真实源可验证。
- 导出器数据库快照保证不代表文件一致性；文件一致性依赖操作者声明且实际完成停写窗口。
- 目前导入按表建立检查点，超大单表仍会整体读取/写入；按明确批次细化的导入扩展与大规模真实演练待做。
- 图形化备份/恢复入口、保留策略与定时维护在后续设置/UI 阶段接线。
- 没有正式切换命令。原库、原配置、原代码和文件快照必须保留；回滚本阶段只涉及新建测试库/恢复目录与新增工具，不能删除原数据。
