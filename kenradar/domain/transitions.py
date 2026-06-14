from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class StateTransition:
    """状态变更记录"""

    object_type: str
    object_id: str
    old_status: str | None
    new_status: str
    reason: str | None = None
    actor: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if result["created_at"] is None:
            result["created_at"] = datetime.now(timezone.utc)
        return result
