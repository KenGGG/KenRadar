from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kenradar.core.config import AppConfig


def _score(value: Any) -> float:
    try:
        return max(0.0, min(5.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class CurationPolicy:
    high_value_threshold: float = 3.5
    push_threshold: float = 4.0
    research_threshold: float = 4.2

    @classmethod
    def from_config(cls, config: AppConfig | Any) -> "CurationPolicy":
        high_value = _score(config.get("curation.high_value_threshold", 3.5)) or 3.5
        configured_push = config.get("curation.push_threshold", None)
        if configured_push is None:
            legacy_rating = config.get("notification.channels.feishu.push_threshold_rating", None)
            configured_push = _number(legacy_rating) / 2 if legacy_rating is not None else 4.0
        push = _score(configured_push) or 4.0
        research = _score(config.get("curation.research_threshold", 4.2)) or 4.2
        return cls(
            high_value_threshold=high_value,
            push_threshold=push,
            research_threshold=research,
        )

    def is_high_value(self, value: Any) -> bool:
        return _score(value) >= self.high_value_threshold

    def should_push(self, action: Any, value: Any, *, analysis_status: Any = "success") -> bool:
        if str(analysis_status or "").strip().lower() in {"failed", "degraded", "skipped"}:
            return False
        return str(action or "").strip().lower() == "push" or _score(value) >= self.push_threshold

    def should_recommend(self, action: Any, value: Any) -> bool:
        return str(action or "").strip().lower() in {"push", "review", "research"} or _score(value) >= self.push_threshold

    def should_research(self, action: Any, value: Any) -> bool:
        return str(action or "").strip().lower() == "research" or _score(value) >= self.research_threshold

    def frontend_thresholds(self) -> dict[str, float]:
        return {
            "high_value_threshold": round(self.high_value_threshold * 2, 1),
            "push_threshold": round(self.push_threshold * 2, 1),
            "research_threshold": round(self.research_threshold * 2, 1),
        }
