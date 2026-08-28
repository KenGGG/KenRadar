from __future__ import annotations

from types import SimpleNamespace

from kenradar.core.curation import CurationPolicy
from kenradar.notification.feishu import FeishuPusher


def _config(values: dict[str, object] | None = None):
    data = values or {}
    return SimpleNamespace(get=lambda key, default=None: data.get(key, default))


def test_curation_policy_uses_one_default_scale():
    policy = CurationPolicy.from_config(_config())

    assert policy.high_value_threshold == 3.5
    assert policy.push_threshold == 4.0
    assert policy.research_threshold == 4.2
    assert policy.frontend_thresholds() == {
        "high_value_threshold": 7.0,
        "push_threshold": 8.0,
        "research_threshold": 8.4,
    }


def test_curation_policy_accepts_legacy_ten_point_push_threshold():
    policy = CurationPolicy.from_config(
        _config({"notification.channels.feishu.push_threshold_rating": 7.5})
    )

    assert policy.push_threshold == 3.75
    assert policy.should_push("review", 3.7) is False
    assert policy.should_push("review", 3.8) is True


def test_curation_policy_never_pushes_failed_analysis():
    policy = CurationPolicy.from_config(_config())

    assert policy.should_push("push", 5.0, analysis_status="failed") is False
    assert policy.should_push("push", 1.0, analysis_status="success") is True


def test_curation_policy_recommendation_and_research_actions_are_consistent():
    policy = CurationPolicy.from_config(_config())

    assert policy.is_high_value(3.5) is True
    assert policy.should_recommend("review", 2.0) is True
    assert policy.should_recommend("archive", 4.0) is True
    assert policy.should_research("research", 1.0) is True
    assert policy.should_research("review", 4.2) is True


def test_feishu_filter_archives_batch_when_no_item_qualifies():
    pusher = FeishuPusher.__new__(FeishuPusher)
    pusher.config = _config({"notification.channels.feishu.max_publish_age_hours": 0})

    selected = pusher._filter_push_videos(
        [
            {
                "aweme_id": "1",
                "recommended_action": "archive",
                "value_score": "3.9",
                "summary_status": "success",
                "publish_time": "",
            }
        ]
    )

    assert selected == []


def test_feishu_filter_never_selects_failed_analysis():
    pusher = FeishuPusher.__new__(FeishuPusher)
    pusher.config = _config({"notification.channels.feishu.max_publish_age_hours": 0})

    selected = pusher._filter_push_videos(
        [
            {
                "aweme_id": "1",
                "recommended_action": "push",
                "value_score": "5.0",
                "summary_status": "failed",
                "publish_time": "",
            }
        ]
    )

    assert selected == []
