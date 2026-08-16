from __future__ import annotations

from types import SimpleNamespace

from kenradar.notification.alert import AlertManager, alert_fingerprint


def test_alert_fingerprint_normalizes_urls_ids_and_transient_numbers():
    first = alert_fingerprint(
        "error",
        "downloader",
        "下载 https://example.com/video/123456 失败，作品 987654321，重试 12 次",
    )
    second = alert_fingerprint(
        "error",
        "downloader",
        "下载 https://other.example/video/888888 失败，作品 111111111，重试 99 次",
    )

    assert first == second
    assert first != alert_fingerprint("warning", "downloader", "下载失败")


class _Config:
    feishu_webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

    @staticmethod
    def get(key, default=None):
        return True if key in {"notification.enabled", "notification.alerts.enabled"} else default


def test_alert_manager_notifies_only_when_database_opens_a_window(monkeypatch):
    sent = []

    class Database:
        calls = 0

        def insert_alert_log(self, **kwargs):
            self.calls += 1
            return {"id": 7, "should_notify": self.calls == 1, "occurrence_count": self.calls}

        def mark_alert_notified(self, alert_id, notified):
            pass

    monkeypatch.setattr(AlertManager, "_send_feishu", lambda self, *args, **kwargs: sent.append(args) or True)
    manager = AlertManager(_Config(), Database())

    manager.error("worker", "same failure 123456")
    manager.error("worker", "same failure 987654")

    assert len(sent) == 1


def test_recovery_is_sent_once_for_the_active_fingerprint(monkeypatch):
    sent = []

    class Database:
        active = True

        def resolve_alert_fingerprint(self, component, message):
            if not self.active:
                return None
            self.active = False
            return {"id": 9, "level": "error", "occurrence_count": 3, "should_notify": True}

        def mark_alert_notified(self, alert_id, notified):
            pass

    monkeypatch.setattr(AlertManager, "_send_feishu", lambda self, *args, **kwargs: sent.append(args) or True)
    manager = AlertManager(_Config(), Database())

    manager.recovered("worker", "same failure")
    manager.recovered("worker", "same failure")

    assert len(sent) == 1
