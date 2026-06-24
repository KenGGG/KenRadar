from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import requests

from kenradar.core.config import AppConfig
from kenradar.domain import AlertLevel
from kenradar.publishing import StaticSitePublisher
from kenradar.utils.text import truncate_text

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(self, config: AppConfig, database: Any):
        self.config = config
        self.database = database

    def error(
        self,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.notify(AlertLevel.ERROR, component, message, aweme_id=aweme_id, title=title, context=context)

    def warning(
        self,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.notify(AlertLevel.WARNING, component, message, aweme_id=aweme_id, title=title, context=context)

    def degraded(
        self,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """降级告警：fallback 成功但使用了备选方案"""
        self.notify(AlertLevel.DEGRADED, component, message, aweme_id=aweme_id, title=title, context=context)

    def recovered(
        self,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """恢复告警：之前失败的组件恢复正常"""
        self.notify(AlertLevel.RECOVERED, component, message, aweme_id=aweme_id, title=title, context=context)

    def notify(
        self,
        level: str | AlertLevel,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        level_str = str(level.value) if isinstance(level, AlertLevel) else level
        context_text = json.dumps(context or {}, ensure_ascii=False, default=str) if context else None
        notified = False
        if self._enabled():
            notified = self._send_feishu(level_str, component, message, aweme_id, title, context)
        self.database.insert_alert_log(
            level=level_str,
            component=component,
            aweme_id=aweme_id,
            title=title,
            message=message,
            context=context_text,
            notified=notified,
        )

    def _enabled(self) -> bool:
        alerts_enabled = bool(self.config.get("notification.alerts.enabled", True))
        notifications_enabled = bool(self.config.get("notification.enabled", True))
        return alerts_enabled and notifications_enabled and bool(self.config.feishu_webhook_url)

    def _send_feishu(
        self,
        level: str,
        component: str,
        message: str,
        aweme_id: str | None,
        title: str | None,
        context: dict[str, Any] | None,
    ) -> bool:
        webhook_url = self.config.feishu_webhook_url
        content = self._render(level, component, message, aweme_id, title, context)
        try:
            response = requests.post(
                webhook_url,
                json=self._build_payload(webhook_url, content),
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            if response.status_code != 200:
                logger.error("飞书告警发送失败: HTTP %s %s", response.status_code, response.text[:200])
                return False
            data = response.json()
            if data.get("StatusCode") not in (None, 0) and data.get("code") != 0:
                logger.error("飞书告警发送失败: %s", data)
                return False
            return True
        except Exception:
            logger.exception("飞书告警发送异常")
            return False

    @staticmethod
    def _level_icon(level: str) -> str:
        return {
            "degraded": "⚠️",
            "warning": "⚠️",
            "error": "🚨",
            "recovered": "✅",
            "critical": "🔥",
        }.get(level, "📢")

    def _render(
        self,
        level: str,
        component: str,
        message: str,
        aweme_id: str | None,
        title: str | None,
        context: dict[str, Any] | None,
    ) -> str:
        icon = self._level_icon(level)
        label = f"{icon} KenRadar {level.upper()}" if level == "degraded" else f"{icon} KenRadar 处理告警"
        lines = [
            label,
            "",
            f"级别：{level.upper()}",
            f"模块：{component}",
            f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"信息：{truncate_text(message, 900)}",
        ]
        if title:
            lines.append(f"标题：{title}")
        if aweme_id:
            detail_url = self._resolve_detail_url(aweme_id, context)
            lines.append(f"作品 ID：{aweme_id}")
            if detail_url:
                lines.append(f"详情页：{detail_url}")
        if context:
            context_text = json.dumps(context, ensure_ascii=False, default=str)
            lines.append(f"上下文：{truncate_text(context_text, 1200)}")
        return "\n".join(lines)

    def _resolve_detail_url(self, aweme_id: str, context: dict[str, Any] | None) -> str:
        summary_path = ""
        if context:
            summary_path = str(context.get("summary_path") or context.get("note_path") or "").strip()
        if not summary_path:
            try:
                summary = self.database.get_summary(aweme_id)
                summary_path = str((summary or {}).get("summary_path") or "").strip()
            except Exception:
                summary_path = ""
        if summary_path:
            publisher = StaticSitePublisher(self.config)
            public_url = publisher.public_url_for(summary_path)
            if public_url:
                return public_url
        base_url = str(self.config.get("app.web_base_url", "http://172.30.10.150:8765") or "http://172.30.10.150:8765").rstrip("/")
        return f"{base_url}/aweme?id={aweme_id}"

    @staticmethod
    def _build_payload(webhook_url: str, content: str) -> dict[str, Any]:
        if "www.feishu.cn" in webhook_url:
            return {"msg_type": "text", "content": {"text": content}}
        return {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "body": {"elements": [{"tag": "markdown", "content": content}]},
            },
        }
