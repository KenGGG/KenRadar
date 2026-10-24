from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_sqlite_v2 import sqlite_db
from kenradar.sources.xiaoyuzhou.page_parser import parse_page, _parse_datetime


@pytest.mark.parametrize("epoch", [1791928800, 1791928800000])
def test_epoch_is_explicit_utc(epoch):
    assert _parse_datetime(epoch) == datetime(2026, 10, 13, 22, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["2026-10-13T22:00:00", "2026-10-13"])
def test_timezone_unspecified_date_is_not_guessed(value):
    assert _parse_datetime(value) is None


@pytest.mark.parametrize("source_date, expected", [
    ("2026-10-13T22:00:00.000Z", "2026-10-13T22:00:00.000000Z"),
    ("2026-10-14T06:00:00+08:00", "2026-10-13T22:00:00.000000Z"),
])
def test_page_date_preserves_instant_through_sqlite(sqlite_db, source_date, expected):
    db, _ = sqlite_db
    html = Path("tests/fixtures/xiaoyuzhou_episode.html").read_text(encoding="utf-8")
    html = html.replace("2026-06-26T10:00:00+08:00", source_date)
    item = parse_page(html)[0]
    creator_id = db.upsert_creator(item.platform, item.creator_id, item.creator, "")
    db.upsert_content_item(item.platform, item.content_id, creator_id,
                           title=item.original_title, publish_time=item.published_at,
                           extra=item.raw_metadata)
    stored = db.find_content_item(item.platform, item.content_id)
    assert stored["publish_time"] == expected
    assert stored["extra"]["episode"]["pubDate"] == source_date
    assert item.published_at == datetime(2026, 10, 13, 22, tzinfo=timezone.utc)
