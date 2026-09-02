"""PostgreSQL integration fixtures for KenRadar repositories.

These tests talk to a real disposable PostgreSQL database. Set
``KENRADAR_TEST_DATABASE_URL`` to enable them; without it the whole directory
skips so the default suite stays hermetic.

The database is migrated once per session and volatile tables are truncated
before each test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from kenradar.storage.pg_database import Database

CONFIG_PATH = "config/config.yaml"

# Tables that hold generated operational data and are safe to truncate per test.
# Ordered so referencing rows are removed before the rows they point at.
VOLATILE_TABLES = (
    "task_attempt",
    "task_step",
    "artifact",
    "task_run",
)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the disposable PostgreSQL URL used by integration tests."""
    url = str(os.environ.get("KENRADAR_TEST_DATABASE_URL") or "").strip()
    if not url:
        pytest.skip("KENRADAR_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return url


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(test_database_url: str) -> Iterator[str]:
    """Migrate the test database to head once per session."""
    from kenradar.storage.migrate import upgrade_database

    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_database_url
    try:
        upgrade_database(CONFIG_PATH)
        yield test_database_url
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


@pytest.fixture
def task_db(test_database_url: str, migrated_test_database: str) -> Iterator[Database]:
    """A migrated database with a clean task queue."""
    database = Database(test_database_url)
    database.initialize()
    _truncate(database, VOLATILE_TABLES)
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def content_db(test_database_url: str, migrated_test_database: str) -> Iterator[Database]:
    """A migrated database with volatile task and publication tables cleaned."""
    database = Database(test_database_url)
    database.initialize()
    _truncate(database, VOLATILE_TABLES + ("publication_log",))
    try:
        yield database
    finally:
        database.close()


def _truncate(database: Database, tables: tuple[str, ...]) -> None:
    with database.connect() as conn:
        for table in tables:
            exists = conn.execute(
                "SELECT to_regclass('public.%s')" % table
            ).fetchone()
            if exists and exists[0]:
                conn.execute("DELETE FROM {}".format(table))  # noqa: S608 - fixed table names
