# KenRadar PostgreSQL Migrations

当前 PostgreSQL 初始 schema 由 `kenradar.storage.pg_database.SCHEMA_SQL` 管理，`init-db`
会直接创建表、索引和兼容视图。项目已加入 Alembic 依赖，后续 schema 演进可在本目录下补充
Alembic `env.py` 与版本脚本。

一次性历史数据迁移入口：

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar.storage.migrate_sqlite_to_pg --config config/config.yaml
```
