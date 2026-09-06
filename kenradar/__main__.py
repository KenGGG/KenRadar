from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from urllib.parse import urlsplit, urlunsplit

from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KenRadar 抖音监控与转录推送")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="初始化数据库")
    subparsers.add_parser("migrate", help="将 PostgreSQL schema 升级到最新版本")
    worker_parser = subparsers.add_parser("worker", help="运行持久任务 worker")
    worker_parser.add_argument("--name", default="", help="worker 名称")
    worker_parser.add_argument("--once", action="store_true", help="只领取并执行一个任务")
    task_status_parser = subparsers.add_parser("task-status", help="查看持久任务状态")
    task_status_parser.add_argument("task_id", type=int)
    task_cancel_parser = subparsers.add_parser("task-cancel", help="请求取消持久任务")
    task_cancel_parser.add_argument("task_id", type=int)
    task_cancel_parser.add_argument("--reason", default="CLI 请求取消")
    task_pause_parser = subparsers.add_parser("task-pause", help="请求暂停持久任务")
    task_pause_parser.add_argument("task_id", type=int)
    task_pause_parser.add_argument("--reason", default="CLI 请求暂停")
    task_resume_parser = subparsers.add_parser("task-resume", help="继续已暂停的持久任务")
    task_resume_parser.add_argument("task_id", type=int)
    scan_sources_parser = subparsers.add_parser("scan-sources", help="扫描到期的订阅并加入处理队列")
    scan_sources_parser.add_argument("--limit", type=int, default=50)
    scan_sources_parser.add_argument(
        "--scope", choices=["recent", "full"], default="recent",
        help="扫描深度：recent 仅最新一页，full 翻页到历史尽头",
    )
    scan_history_parser = subparsers.add_parser(
        "scan-history", help="扫描单个订阅的历史内容并生成待确认作业（不直接处理）"
    )
    scan_history_parser.add_argument("subscription_id", type=int)
    scan_history_parser.add_argument(
        "--scope", choices=["recent", "full"], default="full",
        help="扫描深度，默认 full",
    )
    scan_history_parser.add_argument(
        "--confirm", action="store_true",
        help="扫描后自动确认并执行已批准项（默认仅生成待确认作业）",
    )
    backfill_subs_parser = subparsers.add_parser(
        "backfill-subscriptions", help="为已有内容但缺少订阅的来源补建订阅"
    )
    backfill_subs_parser.add_argument("--platform", default="", help="限定平台，如 douyin / xiaoyuzhou")
    subparsers.add_parser("doctor", help="检查数据库、secret、目录权限和外部服务，不输出敏感值")

    analytics_parser = subparsers.add_parser("analytics-scan", help="计算来源日指标（确定性聚合）")
    analytics_parser.add_argument("--days", type=int, default=7, help="回填最近多少天，默认 7")
    analytics_parser.add_argument("--step", choices=["aggregate", "topic-classify"], default="aggregate", help="分析步骤")
    analytics_parser.add_argument("--dry-run", action="store_true", help="只预览，不写入数据库")

    run_once_parser = subparsers.add_parser("run-once", help="执行一次检测、下载、转录和推送")
    run_once_parser.add_argument("--no-push", action="store_true", help="只处理内容，不推送飞书")

    backfill_parser = subparsers.add_parser("backfill", help="分页处理单个博主的历史视频")
    backfill_parser.add_argument("--target-index", type=int, default=0, help="启用博主列表中的下标，默认 0")
    backfill_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条视频；0 表示不限")

    summarize_parser = subparsers.add_parser("summarize-existing", help="为已有成功转录补生成 AI 摘要")
    summarize_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条；0 表示不限")

    regenerate_notes_parser = subparsers.add_parser("regenerate-notes", help="用 Agnes 基于数据库原始转录重生存量 Obsidian 内容笔记")
    regenerate_notes_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条；0 表示不限")
    regenerate_notes_parser.add_argument("--dry-run", action="store_true", help="只统计待重生数量，不调用 Agnes、不写文件")
    regenerate_notes_parser.add_argument("--force", action="store_true", help="强制重生已是新版模板的笔记")
    regenerate_notes_parser.add_argument("--publish", action="store_true", help="每条重生后立即发布对应 HTML；默认建议结束后统一 publish-pages")
    regenerate_notes_parser.add_argument("--aweme-id", default="", help="只重生指定 aweme_id")

    validate_notes_parser = subparsers.add_parser("validate-obsidian-notes", help="校验 Obsidian 内容笔记 frontmatter、章节和 wikilink")
    validate_notes_parser.add_argument("--limit", type=int, default=0, help="最多校验多少个 Markdown 文件；0 表示全部")
    validate_notes_parser.add_argument("--path", default="", help="只校验指定 Markdown 文件")

    classify_parser = subparsers.add_parser("classify-existing", help="用 Agnes 为已有摘要重分类并丰富阅读库主题")
    classify_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条；0 表示不限")
    classify_parser.add_argument("--only-missing", action="store_true", help="只处理缺少 tags/keywords 的内容")
    classify_parser.add_argument("--skip-classified", action="store_true", help="跳过已经由 Agnes 分类过的内容")
    classify_parser.add_argument("--batch-size", type=int, default=5, help="每次 Agnes 请求批量分类多少条，默认 5，最大 10")
    classify_parser.add_argument("--dry-run", action="store_true", help="只预览 Agnes 分类结果，不写回数据库和笔记")
    classify_parser.add_argument("--no-update-notes", action="store_true", help="不更新已有 Markdown 笔记 frontmatter")

    cleanup_parser = subparsers.add_parser("cleanup-downloads", help="清理已归档内容在 Downloaded 中的临时文件")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="只统计可清理文件，不实际删除")

    refresh_notes_parser = subparsers.add_parser("refresh-old-notes", help="用 Ollama 将旧 Markdown 笔记升级为新版 Obsidian 模板")
    refresh_notes_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条旧笔记；0 表示不限")
    refresh_notes_parser.add_argument("--dry-run", action="store_true", help="只统计待升级数量，不实际调用 Ollama")

    test_latest_parser = subparsers.add_parser("test-latest", help="强制处理每个启用博主最新作品，用于端到端验收")
    test_latest_parser.add_argument("--limit-per-target", type=int, default=1, help="每个博主处理多少条最新作品，默认 1")
    test_latest_parser.add_argument("--no-push", action="store_true", help="只处理内容，不推送飞书")

    research_parser = subparsers.add_parser("research-blogger", help="一次性研究并归档指定博主的历史视频")
    research_parser.add_argument("--blogger", required=True, help="博主名称、sec_uid 或抖音主页链接")
    research_parser.add_argument("--limit", type=int, default=0, help="最多处理多少条历史视频；0 表示不限")
    research_parser.add_argument("--no-push", action="store_true", default=True, help="不推送飞书；研究模式默认不推送")
    research_parser.add_argument("--push", action="store_true", help="显式开启研究结果推送")
    research_parser.add_argument("--force", action="store_true", help="强制重新处理已成功归档的视频")
    research_parser.add_argument("--since", default="", help="只处理该日期之后发布的视频，格式 YYYY-MM-DD")
    research_parser.add_argument("--until", default="", help="只处理该日期之前发布的视频，格式 YYYY-MM-DD")

    video_parser = subparsers.add_parser("research-video", help="研究并归档指定抖音单个视频")
    video_parser.add_argument("video", nargs="?", default="", help="抖音视频链接、分享短链或 aweme_id")
    video_parser.add_argument("--url", default="", help="抖音视频链接或分享短链")
    video_parser.add_argument("--aweme-id", default="", help="直接指定 aweme_id")
    video_parser.add_argument("--no-push", action="store_true", default=True, help="不推送飞书；单视频研究默认不推送")
    video_parser.add_argument("--push", action="store_true", help="显式开启单视频结果推送")
    video_parser.add_argument("--force", action="store_true", help="强制重新处理已成功归档的视频")
    video_parser.add_argument("--json", action="store_true", help="将任务结果以 JSON 输出到标准输出")

    podcast_parser = subparsers.add_parser("research-xiaoyuzhou", help="研究并归档小宇宙节目、RSS 或单集")
    podcast_parser.add_argument("source", help="小宇宙节目 URL、单集 URL 或 RSS Feed URL")
    podcast_parser.add_argument("--limit", type=int, default=1, help="最多处理多少期，默认 1")
    podcast_parser.add_argument("--force", action="store_true", help="强制重新处理已成功转录的单集")
    podcast_parser.add_argument("--push", action="store_true", help="显式开启推送；仍需 sources.xiaoyuzhou.auto_push_feishu=true")
    podcast_parser.add_argument("--no-publish", action="store_true", help="只生成本地 Markdown 和数据库记录，不发布 Pages、不执行 Git 同步、不推送飞书")
    podcast_parser.add_argument("--json", action="store_true", help="将研究结果以 JSON 输出到标准输出")

    subparsers.add_parser("schedule", help="按 schedule.times 常驻运行")

    publish_parser = subparsers.add_parser("publish-pages", help="将现有 Markdown 笔记和简报生成 GitHub Pages HTML")
    publish_parser.add_argument("--limit", type=int, default=0, help="最多发布多少个 Markdown 文件；0 表示全部")
    publish_parser.add_argument("--no-sync", action="store_true", help="只生成 HTML，不执行 GitHub 同步")

    sync_parser = subparsers.add_parser("sync-github", help="同步 docs、data/notes 和 data/briefs 到 GitHub 仓库")
    sync_parser.add_argument("--dry-run", action="store_true", help="只预览将同步的文件，不执行 git add/commit/push")
    sync_parser.add_argument("--force", action="store_true", help="跳过同步防抖，立即检查并提交发布产物")

    research_publish_parser = subparsers.add_parser("publish-research-job", help="生成批量研究笔记目录并同步 GitHub")
    research_publish_parser.add_argument("--job-id", type=int, required=True, help="研究任务 ID")
    research_publish_parser.add_argument("--wait", action="store_true", help="等待任务结束后再发布")
    research_publish_parser.add_argument("--poll-seconds", type=int, default=60, help="等待任务时的轮询间隔")

    web_parser = subparsers.add_parser("web", help="启动本地 Web 控制台")
    web_parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只监听本机")
    web_parser.add_argument("--port", type=int, default=8765, help="监听端口")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    config = load_config(args.config)

    if args.command == "init-db":
        from kenradar.storage.migrate import upgrade_database

        upgrade_database(args.config)
        logger.info("数据库已初始化: %s", _mask_database_url(config.database_url) or config.database_path)
        return

    if args.command == "migrate":
        from kenradar.storage.migrate import schema_status, upgrade_database

        upgrade_database(args.config)
        logger.info("数据库迁移完成: %s", schema_status(args.config))
        return

    if args.command == "worker":
        from kenradar.jobs.worker import TaskWorker

        worker = TaskWorker(args.config, worker_name=args.name)
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
        return

    if args.command == "task-status":
        row = create_database(config).get_task_run(args.task_id)
        if not row:
            raise ValueError(f"未找到任务: {args.task_id}")
        logger.info("任务状态: %s", row)
        return

    if args.command == "task-cancel":
        create_database(config).request_task_cancel(args.task_id, args.reason)
        logger.info("已请求取消任务: %s", args.task_id)
        return

    if args.command == "task-pause":
        database = create_database(config)
        row = database.get_task_run(args.task_id)
        if not row:
            raise ValueError(f"未找到任务: {args.task_id}")
        database.request_task_pause(args.task_id, args.reason)
        if str(row.get("status") or "") in {"queued", "retry_wait"}:
            database.pause_task_run(args.task_id, {}, args.reason)
        logger.info("已请求暂停任务: %s", args.task_id)
        return

    if args.command == "task-resume":
        create_database(config).resume_task_run(args.task_id)
        logger.info("已继续暂停任务: %s", args.task_id)
        return

    if args.command == "scan-sources":
        from kenradar.core.source_monitor import SourceMonitorService

        database = create_database(config)
        try:
            stats = asyncio.run(
                SourceMonitorService(database).scan_due_subscriptions(
                    limit=args.limit, scan_scope=args.scope
                )
            )
        finally:
            database.close()
        logger.info(
            "订阅雷达扫描完成: scanned=%s discovered=%s failed=%s skipped=%s",
            stats["scanned"], stats["discovered"], stats["failed"], stats["skipped"],
        )
        return

    if args.command == "scan-history":
        from kenradar.core.source_monitor import SourceMonitorService

        database = create_database(config)
        try:
            stats = asyncio.run(
                SourceMonitorService(database).scan_subscription_history(
                    subscription_id=args.subscription_id, scan_scope=args.scope
                )
            )
            if args.confirm:
                # 默认批准后执行：确认作业并立即对批准项入队
                database.research_jobs.confirm_job(
                    stats["job_id"], confirmed_by="cli", approve=True
                )
                database.research_jobs.mark_executed(stats["job_id"])
                logger.info("已确认并执行作业: job_id=%s", stats["job_id"])
        finally:
            database.close()
        logger.info(
            "历史扫描完成: subscription_id=%s job_id=%s scope=%s discovered=%s already_known=%s",
            stats["subscription_id"], stats["job_id"], stats["scan_scope"],
            stats["discovered"], stats["already_known"],
        )
        return

    if args.command == "backfill-subscriptions":
        from kenradar.core.source_monitor import SourceMonitorService

        database = create_database(config)
        try:
            stats = asyncio.run(
                SourceMonitorService(database).backfill_subscriptions(platform=args.platform or "")
            )
        finally:
            database.close()
        logger.info(
            "订阅回填完成: examined=%s created=%s enriched=%s skipped=%s",
            stats["examined"], stats["created"], stats["enriched"], stats["skipped"],
        )
        return

    if args.command == "doctor":
        _run_doctor(config, args.config)
        return

    if args.command == "analytics-scan":
        from kenradar.core.analytics import aggregate_source_metrics

        if args.days < 1 or args.days > 3650:
            raise ValueError("--days 必须在 1 到 3650 之间")
        stats = aggregate_source_metrics(config, days=args.days, dry_run=bool(args.dry_run))
        logger.info("来源指标聚合完成: %s", stats)
        if int(stats.get("errors") or 0) > 0:
            raise SystemExit(1)
        return

    if args.command == "run-once":
        row = _submit_and_wait(args.config, "run_once", {"push": not args.no_push}, "CLI 执行一次监控")
        logger.info("执行完成: %s", row.get("stats_json"))
        return

    if args.command == "backfill":
        row = _submit_and_wait(
            args.config,
            "backfill",
            {"target_index": args.target_index, "limit": args.limit},
            "CLI 历史回填",
        )
        logger.info("历史处理完成: %s", row.get("stats_json"))
        return

    if args.command == "summarize-existing":
        row = _submit_and_wait(
            args.config,
            "summarize_existing",
            {"limit": args.limit},
            "CLI 补齐已有转录摘要",
        )
        logger.info("已有转录摘要补齐完成: %s", row.get("stats_json"))
        return

    if args.command == "regenerate-notes":
        from kenradar.core.workflow import Workflow

        stats = asyncio.run(
            Workflow(config).regenerate_notes_with_agnes(
                limit=args.limit,
                dry_run=bool(args.dry_run),
                force=bool(args.force),
                publish=bool(args.publish),
                aweme_id=str(args.aweme_id or ""),
            )
        )
        logger.info("Agnes 存量笔记重生完成: %s", stats)
        return

    if args.command == "validate-obsidian-notes":
        from kenradar.core.workflow import Workflow

        stats = Workflow(config).validate_obsidian_notes(limit=args.limit, path=args.path)
        logger.info("Obsidian 笔记校验完成: %s", stats)
        if int(stats.get("failed") or 0) > 0:
            raise SystemExit(1)
        return

    if args.command == "classify-existing":
        from kenradar.core.classifier import ExistingContentClassifier

        stats = ExistingContentClassifier(config).classify_existing(
            limit=args.limit,
            only_missing=bool(args.only_missing),
            skip_classified=bool(args.skip_classified),
            batch_size=args.batch_size,
            dry_run=bool(args.dry_run),
            update_notes=not bool(args.no_update_notes),
        )
        logger.info("已有内容重分类完成: %s", stats)
        return

    if args.command == "cleanup-downloads":
        from kenradar.core.workflow import Workflow

        stats = Workflow(config).cleanup_processed_downloads(dry_run=args.dry_run)
        logger.info("下载临时文件清理完成: %s", stats)
        return

    if args.command == "refresh-old-notes":
        row = _submit_and_wait(
            args.config,
            "refresh_old_notes",
            {"limit": args.limit, "dry_run": args.dry_run},
            "CLI 升级旧 Markdown 笔记",
        )
        logger.info("旧 Markdown 笔记升级任务完成: %s", row.get("stats_json"))
        return

    if args.command == "test-latest":
        row = _submit_and_wait(
            args.config,
            "test_latest",
            {"limit_per_target": args.limit_per_target, "push": not args.no_push},
            "CLI 最新作品端到端测试",
        )
        logger.info("最新作品端到端测试完成: %s", row.get("stats_json"))
        return

    if args.command == "research-blogger":
        row = _submit_and_wait(
            args.config,
            "research_blogger",
            {
                "blogger": args.blogger,
                "limit": args.limit,
                "push": bool(args.push),
                "force": bool(args.force),
                "since": args.since,
                "until": args.until,
            },
            f"CLI 研究博主：{args.blogger}",
        )
        logger.info("研究博主归档完成: %s", row.get("stats_json"))
        return

    if args.command == "research-video":
        row = _submit_and_wait(
            args.config,
            "research_video",
            {
                "video": args.url or args.video,
                "aweme_id": args.aweme_id,
                "push": bool(args.push),
                "force": bool(args.force),
            },
            "CLI 研究单个视频",
        )
        if args.json:
            print(_task_result_json(row), flush=True)
        else:
            logger.info("单视频研究完成: %s", row.get("stats_json"))
        return

    if args.command == "research-xiaoyuzhou":
        from kenradar.core.workflow import Workflow

        stats = asyncio.run(
            Workflow(config).research_xiaoyuzhou(
                source=args.source,
                limit=args.limit,
                force=bool(args.force),
                push=bool(args.push),
                publish=not bool(args.no_publish),
            )
        )
        if args.json:
            print(json.dumps(stats, ensure_ascii=False), flush=True)
        else:
            logger.info("小宇宙研究完成: %s", stats)
        return

    if args.command == "schedule":
        from kenradar.scheduler.scheduler import run_forever

        asyncio.run(run_forever(config))
        return

    if args.command == "publish-pages":
        from kenradar.core.obsidian import brief_dir, summary_dir
        from kenradar.publishing import GithubSyncManager, StaticSitePublisher

        publisher = StaticSitePublisher(config)
        paths = sorted(
            [*summary_dir(config).glob("**/*.md"), *brief_dir(config).glob("**/*.md")],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if args.limit > 0:
            paths = paths[: args.limit]
        urls = publisher.publish_many(paths)
        index_path = publisher.write_index()
        logger.info("GitHub Pages HTML 发布完成: files=%s index=%s", len(urls), index_path)
        if not args.no_sync:
            manager = GithubSyncManager(config)
            result = manager.sync(force=True)
            if result.get("enabled"):
                manager.write_last_sync(result)
            logger.info("%s", result.get("message") or "GitHub 同步完成")
            for path in result.get("files") or []:
                logger.info("  %s", path)
        return

    if args.command == "sync-github":
        from kenradar.publishing import GithubSyncManager

        manager = GithubSyncManager(config)
        result = manager.sync(dry_run=bool(args.dry_run), force=bool(args.force))
        if not args.dry_run and result.get("enabled"):
            manager.write_last_sync(result)
        logger.info("%s", result.get("message") or "GitHub 同步完成")
        for path in result.get("files") or []:
            logger.info("  %s", path)
        return

    if args.command == "publish-research-job":
        from kenradar.core.workflow import Workflow

        workflow = Workflow(config)
        if args.wait:
            terminal = {
                "completed",
                "partial_failed",
                "failed",
                "cancelled",
                "transcribe_only_completed",
                "transcribe_only_partial_failed",
            }
            while True:
                with workflow.database.connect() as conn:
                    row = conn.execute("SELECT status FROM research_job WHERE id = %s", (args.job_id,)).fetchone()
                if row is None:
                    raise ValueError(f"未找到研究任务: {args.job_id}")
                status = str(row["status"] or "")
                if status in terminal:
                    break
                logger.info("等待研究任务结束后发布: job_id=%s status=%s", args.job_id, status)
                time.sleep(max(10, int(args.poll_seconds)))
        result = workflow.publish_research_job(args.job_id)
        logger.info("研究任务 GitHub 发布完成: %s", result)
        return

    if args.command == "web":
        from kenradar.web.app import run_web

        run_web(args.config, host=args.host, port=args.port)
        return


def _mask_database_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.password:
        return value
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:***@{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _task_result_json(row: dict) -> str:
    stats = row.get("stats_json") or {}
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            stats = {}
    if not isinstance(stats, dict):
        stats = {}
    return json.dumps(stats, ensure_ascii=False)


def _submit_and_wait(config_path: str, task_type: str, payload: dict, message: str) -> dict:
    from kenradar.jobs.worker import TaskWorker, wait_for_task

    config = load_config(config_path)
    database = create_database(config)
    row = database.enqueue_task_run(
        task_type,
        payload,
        message,
        requested_by="cli",
        priority=70,
        max_attempts=3,
    )
    run_id = int(row.get("id") or 0)
    worker = TaskWorker(config_path, worker_name="cli-inline-worker", poll_seconds=0.5)
    while True:
        current = database.get_task_run(run_id)
        if current and str(current.get("status") or "") in {"success", "failed", "cancelled"}:
            if current["status"] != "success":
                raise RuntimeError(str(current.get("last_error") or f"任务 {current['status']}"))
            return current
        worker.run_once()
        time.sleep(0.2)


def _doctor_web_binding_secure(config) -> bool:
    host = str(config.get("app.web_host", "127.0.0.1") or "127.0.0.1").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"} or bool(str(config.web_password or "").strip())


def _run_doctor(config, config_path: str) -> None:
    import os
    from pathlib import Path

    from kenradar.storage.migrate import schema_status
    from kenradar.core.source_registry import SourceRegistry

    checks = {
        "database_url": bool(config.database_url),
        "web_binding_security": _doctor_web_binding_secure(config),
        "douyin_cookies": bool(config.cookies),
        "feishu_webhook": bool(config.feishu_webhook_url),
        "agnes_api_key": bool(os.getenv("AGNES_API_KEY", "").strip()),
        "schema_up_to_date": bool(schema_status(config_path)["up_to_date"]),
    }
    for path in (Path(config_path), config.root_dir / ".env"):
        checks[f"permissions:{path.name}"] = not path.exists() or (path.stat().st_mode & 0o077) == 0
    for name, ok in checks.items():
        logger.info("doctor %-28s %s", name, "OK" if ok else "MISSING/UNSAFE")
    source_counts = SourceRegistry(config, create_database(config)).diagnostics()
    logger.info(
        "doctor %-28s config=%d/%d db=%d/%d config_only=%d db_only=%d",
        "source_registry",
        source_counts["config_enabled"],
        source_counts["config_total"],
        source_counts["database_enabled"],
        source_counts["database_total"],
        source_counts["config_only"],
        source_counts["database_only"],
    )
    if not all(checks.values()):
        raise RuntimeError("doctor 检查未通过")


if __name__ == "__main__":
    main()
