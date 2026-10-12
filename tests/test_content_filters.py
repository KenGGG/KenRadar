"""Regression tests for server-side content filter SQL composition."""

from kenradar.core.curation import CurationPolicy
from kenradar.web.queries import _build_content_items_where, _recommended_sql


def test_status_filter_is_a_where_predicate_not_join_condition() -> None:
    where, params = _build_content_items_where({"status": "failed"})

    assert where == " AND (s.status = 'failed' OR t.status = 'failed' OR ci.download_status = 'failed')"
    assert params == []


def test_high_value_filter_uses_curation_policy_threshold() -> None:
    policy = CurationPolicy(high_value_threshold=4.25)

    where, params = _build_content_items_where({"high_value": True}, policy=policy)

    assert ">= 4.25" in where
    assert params == []


def test_recommended_sql_uses_curation_policy_threshold() -> None:
    policy = CurationPolicy(push_threshold=3.75)

    sql = _recommended_sql("aa", policy=policy)

    assert ">= 3.75" in sql
