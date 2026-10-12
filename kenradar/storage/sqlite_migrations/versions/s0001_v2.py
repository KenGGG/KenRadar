"""Frozen V2 SQLite baseline and fencing fields."""
from pathlib import Path
import sqlite3
from alembic import op

revision = "s0001_v2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    statement = ""
    for line in Path(__file__).with_name("baseline.sql").read_text(encoding="utf-8").splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.exec_driver_sql(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("SQLite baseline 有未闭合 SQL")
    for code, name in (("douyin", "抖音"), ("xiaoyuzhou", "小宇宙"), ("bilibili", "B站"),
                       ("xiaohongshu", "小红书"), ("youtube", "YouTube"), ("local", "本地文件")):
        connection.exec_driver_sql("INSERT INTO platform(code,display_name) VALUES (?,?)", (code, name))


def downgrade() -> None:
    raise RuntimeError("请恢复校验过的备份快照；不自动删除业务表")
