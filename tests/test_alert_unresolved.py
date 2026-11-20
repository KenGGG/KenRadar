from sqlalchemy import update
from test_sqlite_v2 import sqlite_db
from kenradar.storage.sqlite_database import utc_now


def test_notified_unresolved_failure_does_not_repeat_after_window(sqlite_db):
    db, _ = sqlite_db
    first = db.insert_alert_log('error', 'github_sync', 'scope blocked')
    assert first['should_notify']
    db.mark_alert_notified(first['id'], True)
    t = db.table('alert_log')
    with db.connect(write=True) as conn:
        conn.execute(update(t).where(t.c.id == first['id']).values(aggregation_window_started_at=utc_now(-7200)))
    again = db.insert_alert_log('error', 'github_sync', 'scope blocked')
    assert not again['should_notify'] and again['occurrence_count'] == 2
    assert again['notified']
    db.resolve_alert_fingerprint('github_sync', 'scope blocked')
    recurrent = db.insert_alert_log('error', 'github_sync', 'scope blocked')
    assert recurrent['should_notify'] and recurrent['id'] != first['id']


def test_explicit_reminders_and_failed_delivery_can_retry(sqlite_db):
    db, _ = sqlite_db
    first = db.insert_alert_log('error', 'github_sync', 'network failure')
    db.mark_alert_notified(first['id'], False)
    t = db.table('alert_log')
    with db.connect(write=True) as conn:
        conn.execute(update(t).where(t.c.id == first['id']).values(aggregation_window_started_at=utc_now(-7200)))
    assert db.insert_alert_log('error', 'github_sync', 'network failure')['should_notify']
    db.mark_alert_notified(first['id'], True)
    with db.connect(write=True) as conn:
        conn.execute(update(t).where(t.c.id == first['id']).values(aggregation_window_started_at=utc_now(-7200)))
    assert db.insert_alert_log('error', 'github_sync', 'network failure', repeat_unresolved=True)['should_notify']


def test_disabled_feishu_channel_cannot_send_alert():
    from kenradar.notification.alert import AlertManager
    class Config:
        feishu_webhook_url = 'https://example.invalid/test'
        def get(self, key, default=None):
            return False if key == 'notification.channels.feishu.enabled' else default
    assert not AlertManager(Config(), None)._enabled()
