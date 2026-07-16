"""Regression tests for server-side content filter SQL composition."""

from kenradar.web.queries import _build_content_items_where


def test_status_filter_is_a_where_predicate_not_join_condition() -> None:
    where, params = _build_content_items_where({"status": "failed"})

    assert where == " AND (s.status = 'failed' OR t.status = 'failed' OR a.download_status = 'failed')"
    assert params == []

