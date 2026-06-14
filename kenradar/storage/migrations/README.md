# KenRadar PostgreSQL Migrations

PostgreSQL schema 由 Alembic 版本管理。`kenradar.storage.pg_database.SCHEMA_SQL` 只作为
baseline 的幂等建表定义，不再由 Web、Workflow 或页面渲染在运行时执行。

升级数据库：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar --config config/config.yaml migrate
```

`./kenradarctl.sh start/restart` 会先执行迁移，再分别启动 Web 和独立任务 worker。
应用启动后只检查 schema 是否已迁移，不会自动执行 DDL。

一次性历史数据迁移入口：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar.storage.migrate_sqlite_to_pg --config config/config.yaml
```
