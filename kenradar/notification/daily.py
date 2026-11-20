"""Daily delivery audit in the existing push_log, independent of media processing.

A webhook has no idempotent message API: ambiguous acceptance is NOT replayed.
"""
from __future__ import annotations
from typing import Any, Callable
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from kenradar.storage.sqlite_database import utc_now


def source_day_coverage(database: Any, config: Any, day: str) -> dict:
    """Coverage comes from each durable source observation, never any-one scan."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(str(config.get('app.timezone', 'Asia/Shanghai') if config is not None else 'Asia/Shanghai'))
    sources = [row for row in database.list_source_subscriptions(enabled=True) if row.get('status') == 'active']
    verified, unresolved, unknown = [], [], []
    for row in sources:
        if int(row.get('consecutive_failures') or 0) > 0:
            unresolved.append(int(row['id']))
            continue
        try:
            observed_day = datetime.fromisoformat(str(row.get('last_success_at') or '').replace('Z', '+00:00')).astimezone(tz).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            observed_day = ''
        (verified if observed_day == day else unknown).append(int(row['id']))
    return {'verified': bool(sources) and len(verified) == len(sources), 'verified_source_ids': verified,
            'failed_source_ids': unresolved, 'unknown_source_ids': unknown, 'required_count': len(sources)}


class DailyDigestDelivery:
    def __init__(self, database: Any, send: Callable):
        self.database, self.send = database, send

    def deliver(self, day: str, payload: dict, *, due_time: str = '') -> dict:
        key = f'daily-summary:feishu:{day}' + (':' + due_time if due_time else '')
        table = self.database.table('push_log')
        with self.database.connect(write=True) as conn:
            created = conn.execute(insert(table).values(content_item_id=None, aweme_id=None,
                batch_id=f'daily:{day}' + (':' + due_time if due_time else ''), channel='feishu', message_type='card', status='running',
                idempotency_key=key).on_conflict_do_nothing().returning(table)).fetchone()
            row = created or conn.execute(select(table).where(table.c.idempotency_key == key)).fetchone()
            if created is None:
                if row['status'] == 'success':
                    return {'status':'success','skipped':True,'api_accepted':True,
                            'recipient_visible_verified':False,'message_id':None,'audit_id':row['id']}
                if row['status'] != 'failed':
                    raise RuntimeError('FEISHU_DELIVERY_UNKNOWN: previous send acceptance unknown; confirm recipient before retry')
                claimed = conn.execute(update(table).where(table.c.id==row['id'],table.c.status=='failed').values(
                    status='running', attempt_count=table.c.attempt_count+1, updated_at=utc_now())).rowcount
                if not claimed:
                    raise RuntimeError('FEISHU_DELIVERY_BUSY: another attempt owns this daily digest')
            audit_id = row['id']
        try:
            response = self.send(payload)
        except Exception:
            self._record(audit_id,'unknown','Transport result ambiguous; no automatic replay')
            raise RuntimeError('FEISHU_DELIVERY_UNKNOWN: transport acceptance unknown; not automatically resent') from None
        try:
            receipt = response.json()
        except Exception:
            receipt = None
        if not isinstance(receipt,dict) or not any(k in receipt for k in ('code','StatusCode')):
            self._record(audit_id,'unknown','Missing explicit business receipt; no automatic replay')
            raise RuntimeError('FEISHU_DELIVERY_UNKNOWN: explicit business receipt missing')
        accepted = response.status_code == 200 and all(receipt[k] == 0 for k in ('code','StatusCode') if k in receipt)
        if not accepted:
            self._record(audit_id,'failed','Explicit business rejection')
            raise RuntimeError('FEISHU_REJECTED: explicit business rejection; delivery-only retry permitted')
        safe_receipt = {k:receipt[k] for k in ('code','StatusCode','msg','StatusMessage') if k in receipt}
        data = receipt.get('data') if isinstance(receipt.get('data'),dict) else {}
        message_id = data.get('message_id') or receipt.get('message_id')
        self._record(audit_id,'success',None)
        return {'status':'success','skipped':False,'api_accepted':True,'receipt':safe_receipt,
                'message_id':message_id,'recipient_visible_verified':False,'audit_id':audit_id}

    def _record(self, audit_id: int, status: str, error: str | None):
        table = self.database.table('push_log')
        with self.database.connect(write=True) as conn:
            conn.execute(update(table).where(table.c.id == audit_id).values(status=status,
                error_message=error, updated_at=utc_now(), pushed_at=utc_now() if status=='success' else None))


class DailySummaryService:
    """Read durable results, include only remote/public-verified nondegraded notes."""
    def __init__(self, database: Any, config: Any):
        self.database, self.config = database, config

    def build(self, day: str, *, task_ids: list[int] | None = None, acceptance: bool = False) -> dict:
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from pathlib import Path
        from kenradar.notification.feishu import build_kenradar_feishu_card
        from kenradar.publishing.static_site import StaticSitePublisher
        from kenradar.integrations.privacy import require_deliverable
        tz = ZoneInfo(str(self.config.get('app.timezone', 'Asia/Shanghai')))
        start = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=tz)
        stamp = lambda date: date.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
        table = self.database.table('task_run')
        with self.database.connect() as conn:
            from sqlalchemy import func, or_, and_
            business_day = func.coalesce(func.json_extract(table.c.payload_json, '$.day'), '')
            day_query = select(table).where(or_(business_day == day, and_(business_day == '',
                table.c.created_at >= stamp(start), table.c.created_at < stamp(start + timedelta(days=1)))))
            query = day_query if task_ids is None else select(table).where(table.c.id.in_(task_ids))
            rows = [dict(row) for row in conn.execute(query.order_by(table.c.updated_at.desc(), table.c.id.desc())).fetchall()]
            scan_rows = rows if task_ids is None else [dict(row) for row in conn.execute(day_query.where(table.c.task_type == 'scan_sources')).fetchall()]
        sources = {int(row['id']):row for row in self.database.list_source_subscriptions(enabled=True)
                   if row.get('status') == 'active'}
        scans = [row for row in scan_rows if row['task_type']=='scan_sources' and (row.get('payload_json') or {}).get('day') == day]
        coverage = source_day_coverage(self.database, self.config, day)
        source_verified = coverage['verified']
        # Report currently unresolved sources, not a sum of transient attempts
        # that may have been successfully recovered later in the same day.
        failed = len(coverage['failed_source_ids'])
        pending, items, seen = 0, [], set()
        considered = set()
        processing_pending = publication_pending = paused_count = retrying_count = 0
        failure_details = []
        publisher = StaticSitePublisher(self.config)
        for row in rows:
            if row['task_type'] not in ('process_url','retry_summary','retry_transcribe','retry_download','publish_content',
                                        'podcast_transcribe','podcast_organize','podcast_codex'):
                continue
            payload, stats = row.get('payload_json') or {}, row.get('stats_json') or {}
            if task_ids is None and int(payload.get('subscription_id') or 0) not in sources:
                continue
            external_id = str(payload.get('external_content_id') or payload.get('aweme_id') or stats.get('aweme_id') or stats.get('content_id') or '')
            if not external_id:
                from kenradar.core.source_resolver import extract_aweme_id
                external_id = extract_aweme_id(str(payload.get('url') or ''))
            identity = (str(payload.get('platform') or 'douyin'), external_id)
            if not external_id or identity in considered:
                continue
            considered.add(identity)
            # Privacy applies to every status, including failure diagnostics and
            # pending counters, before any content identity reaches the digest.
            snapshot = payload.get('item') or {}
            if payload.get('hermes_private') or (snapshot.get('raw_metadata') or {}).get('hermes_private'):
                continue
            content = self.database.find_content_item(*identity)
            bundle = self.database.get_current_bundle(content['id']) if content else None
            try:
                require_deliverable({'content': content or {}, 'note': (bundle or {}).get('note') or {}})
                require_deliverable(bundle)
            except ValueError:
                continue
            seen.add(identity)
            if row['status'] in ('queued','running','retry_wait','paused'):
                pending += 1
                if row['status'] == 'paused':
                    paused_count += 1
                elif row['task_type'] == 'publish_content':
                    publication_pending += 1
                else:
                    processing_pending += 1
                retrying_count += row['status'] == 'retry_wait'
                continue
            recovered = False
            if row['task_type'] == 'publish_content':
                current = self.database.find_content_item(*identity)
                bundle_now = self.database.get_current_bundle(current['id']) if current else None
                note_now = (bundle_now or {}).get('note') or {}
                recovered = bool(current and note_now.get('content_sha256') and self.database.publications.find_success(current['id'], note_now['content_sha256']))
            if not recovered and (row['status'] != 'success' or stats.get('status') in ('failed','partial_failed')):
                failed += 1
                failure_details.append({'task_id': row['id'], 'platform': identity[0], 'external_id': external_id, 'stage': row['task_type']})
                continue
            bundle = bundle or {}
            analysis, note = bundle.get('analysis') or {}, bundle.get('note') or {}
            if analysis.get('analysis_status') != 'success' or not note.get('note_path'):
                failed += 1
                continue
            note_path = Path(note['note_path'])
            import hashlib
            current_hash = str(note.get('content_sha256') or '')
            receipt = self.database.publications.find_success(content['id'], current_hash) if current_hash else None
            if not receipt or not note_path.is_file() or hashlib.sha256(note_path.read_bytes()).hexdigest() != current_hash:
                pending += 1
                publication_pending += 1
                continue
            url = publisher.public_url_for(note_path)
            if receipt.get('target_url') != url:
                pending += 1
                publication_pending += 1
                continue
            import re
            binding = re.search(r':html:([0-9a-f]{64})$', str(receipt.get('idempotency_key') or ''))
            if not binding:
                pending += 1
                publication_pending += 1
                continue
            verification = self.verify_publication(note_path, url, expected_sha256=binding.group(1))
            if not verification.get('verified'):
                pending += 1
                publication_pending += 1
                continue
            result = analysis.get('result_json') or {}
            if not isinstance(result,dict) or not result.get('brief_summary'):
                failed += 1
                continue
            source = sources.get(int(payload.get('subscription_id') or 0)) or {}
            items.append({'aweme_id':external_id, 'short_title':str(result.get('brief_title') or note.get('title') or external_id),
                'short_summary':str(result['brief_summary'])[:200], 'summary_status':'success',
                'blogger_name':str(source.get('display_name') or '量化Quantgirl'), 'publish_time':str((bundle.get('content') or {}).get('publish_time') or ''),
                'detail_url':url, 'video_url':str(payload.get('url') or ''), 'verification':verification})
        payload = build_kenradar_feishu_card(day,'每日收尾',items,max_items=5)
        if acceptance:
            payload['card']['header']['title']['content'] = f'KenRadar 每日流程验收｜{day}'
        source_line = '来源扫描已验证' if source_verified else '未取得成功的来源扫描，不把未知视为无更新'
        payload['card']['elements'][0]['text']['content'] = (
            f'**每日追踪汇总** · {source_line}\n'
            f'已公开 **{len(items)}** 条 · 内容处理中 **{processing_pending}** 条 · 待公开 **{publication_pending}** 条\n'
            f'其中自动重试中 **{retrying_count}** 条 · 已暂停 **{paused_count}** 条 · 来源扫描异常 **{len(coverage["failed_source_ids"])}** 个 · 内容异常 **{failed-len(coverage["failed_source_ids"])}** 条\n'
            + ('今日没有新增视频。' if source_verified and not seen else '仅展示已通过 AI 质量门且公网内容与远端文件匹配的笔记。'))
        payload['card']['elements'][0]['text']['content'] += '\n处理中和待公开会自动推进；自动重试无需重复提交。已暂停需手动继续；内容异常请在任务中心查看原因并重试对应阶段。来源扫描异常会在后续检查中自动再试。'
        if failure_details:
            payload['card']['elements'][0]['text']['content'] += '\n失败定位：' + '；'.join(f"任务 #{entry['task_id']} · {entry['stage']} · {entry['external_id']}" for entry in failure_details[:3])
        return {'source_verified':source_verified,'verified_count':len(items),'pending':pending,
                'processing_pending':processing_pending,'publication_pending':publication_pending,
                'paused_count':paused_count,'retrying_count':retrying_count,
                'failed_sources':len(coverage['failed_source_ids']),
                'failed_content':failed-len(coverage['failed_source_ids']),
                'failed':failed,'failure_details':failure_details,'items':items,'payload':payload}

    def verify_publication(self, note_path: Any, url: str, *, expected_sha256: str = '') -> dict:
        import hashlib, requests
        from kenradar.publishing.github_sync import GithubSyncManager
        from kenradar.publishing.static_site import StaticSitePublisher
        try:
            manager = GithubSyncManager(self.config)
            rel = StaticSitePublisher(self.config).html_path_for(note_path).resolve().relative_to(manager.repo_dir).as_posix()
            branch = str(self.config.get('publishing.github_sync.branch', 'gh-pages'))
            remote = manager._run_git(['ls-remote','origin',f'refs/heads/{branch}']).stdout.strip().split()
            if not remote:
                return {'verified':False,'reason':'remote_ref_missing'}
            sha = remote[0]
            if manager._run_git(['cat-file', '-e', f'{sha}^{{commit}}'], check=False).returncode:
                manager._run_git(['fetch', '--no-tags', 'origin', sha])
            # Read the exact remotely named object, not the working tree or an unpushed HEAD.
            expected = manager._run_git(['show',f'{sha}:{rel}']).stdout.encode('utf8')
            if expected_sha256 and hashlib.sha256(expected).hexdigest() != expected_sha256:
                return {'verified':False,'reason':'receipt_artifact_mismatch','remote_sha':sha}
            response = requests.get(url,timeout=20,allow_redirects=False)
            if response.status_code != 200 or not expected or response.content != expected:
                return {'verified':False,'reason':'public_pending_or_content_mismatch','remote_sha':sha,'http':response.status_code}
            return {'verified':True,'remote_sha':sha,'path':rel,'sha256':hashlib.sha256(expected).hexdigest(),'http':200}
        except Exception:
            return {'verified':False,'reason':'remote_or_public_verification_failed'}

    def send(self, day: str, **kwargs) -> dict:
        if not self.config.get('notification.enabled',False) or not self.config.get('notification.channels.feishu.enabled',False):
            return {'status':'success','skipped':True,'api_accepted':False,'reason':'notification_disabled'}
        due_time = str(kwargs.pop('due_time', '') or '')
        result = self.build(day,**kwargs)
        if due_time:
            result['payload']['card']['header']['title']['content'] = f'流媒体更新简报｜{day} {due_time}'
        if kwargs.get('acceptance') and (not result.get('source_verified') or result.get('pending') or result.get('failed')
                or (kwargs.get('task_ids') is not None and result.get('verified_count') != len(set(kwargs['task_ids'])))):
            raise RuntimeError('ACCEPTANCE_INCOMPLETE: refusing success-labeled delivery until every requested note is verified')
        # Fixed closing digest reports pending work honestly; it does not call it published.
        # A failed media item is a reported business result, not a failed notification attempt.
        reported_failed = result.pop('failed')
        from kenradar.notification.feishu import _post_feishu_json_with_retry
        delivery = DailyDigestDelivery(self.database, lambda payload: _post_feishu_json_with_retry(
            self.config.feishu_webhook_url,payload,attempts=1)).deliver(day,result['payload'], due_time=due_time)
        return {k:v for k,v in result.items() if k not in ('payload','items')} | {'reported_failed':reported_failed} | delivery
