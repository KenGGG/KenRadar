from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class OutboxConsumer:
    """消费 outbox_event 表的事务后事件"""

    def __init__(self, database: Any, workflow: Any, config: dict[str, Any]):
        self._database = database
        self._workflow = workflow
        self._config = config
        self._running = False

    def run_once(self, batch_size: int = 5) -> int:
        """单次消费：领取并处理一批事件，返回处理数量"""
        events = self._database.claim_outbox_events(batch_size=batch_size)
        processed = 0
        for event in events:
            try:
                self._process(event)
                self._database.complete_outbox_event(event["id"])
                processed += 1
            except Exception as exc:
                logger.error("Outbox event failed: event_id=%s type=%s error=%s",
                           event["id"], event["event_type"], exc)
                self._database.fail_outbox_event(event["id"], str(exc))
        return processed

    def _process(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload_json") or {}

        if event_type == "publish:research":
            job_id = int(payload.get("job_id") or 0)
            if job_id:
                self._workflow.publish_research_job(job_id)
        elif event_type == "notify:push":
            pass  # 预留：通知推送去重消费
        elif event_type == "notify:alert":
            pass  # 预留：告警聚合消费
        else:
            logger.debug("未知 outbox event 类型: %s", event_type)
