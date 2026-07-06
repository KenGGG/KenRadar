from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from kenradar.core.ai_json import parse_ai_json
from kenradar.core.config import AppConfig
from kenradar.core.obsidian import brief_dir
from kenradar.publishing import StaticSitePublisher
from kenradar.utils.redaction import redact_secret

EMOJIS = ["📌", "🚀", "🧠", "🔥", "📊", "⚠️", "💡", "🧩", "📈", "🔍"]
SUMMARY_FAILED_TEXT = "该视频已完成抓取和转录，但 AI 摘要暂未生成，系统已记录待重试。"
SUMMARY_PENDING_TEXT = "该视频已完成抓取和转录，但 AI 摘要暂未生成，系统已记录待重试。"
logger = logging.getLogger(__name__)
FEISHU_RATE_LIMIT_CODES = {11232}


def build_kenradar_feishu_card(
    brief_date: str,
    brief_time: str,
    videos: list[dict[str, Any]],
    max_items: int = 5,
    brief_detail_url: str | None = None,
) -> dict[str, Any]:
    display_videos = videos[:max_items]
    overview_lines = []
    for index, video in enumerate(display_videos):
        emoji = EMOJIS[index % len(EMOJIS)]
        title = str(video.get("short_title") or video.get("title") or "未命名视频")
        overview_lines.append(f"{emoji} {title}")

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**总览**\n" + ("\n".join(overview_lines) if overview_lines else "暂无更新"),
            },
        },
        {"tag": "hr"},
    ]

    for index, video in enumerate(display_videos, start=1):
        title = str(video.get("short_title") or video.get("title") or "未命名视频")
        summary = str(video.get("short_summary") or SUMMARY_PENDING_TEXT)
        blogger = str(video.get("blogger_name") or "未知博主")
        publish_time = str(video.get("publish_time") or "未知时间")
        publish_delta = str(video.get("publish_delta") or "").strip()
        video_url = str(video.get("video_url") or "").strip()
        detail_url = str(video.get("detail_url") or "").strip()
        detail_url = _normalize_public_url(detail_url)
        publish_line = f"博主：{blogger} ｜ 发布时间：{publish_time}"
        if publish_delta:
            publish_line += f" ｜ 距推送：{publish_delta}"

        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{index}. {title}**\n\n{summary}\n\n{publish_line}",
                },
            }
        )

        actions = []
        if video_url:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "原视频"},
                    "type": "default",
                    "url": video_url,
                }
            )
        if detail_url:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看全文"},
                    "type": "primary",
                    "url": detail_url,
                }
            )
        if actions:
            elements.append({"tag": "action", "actions": actions})
        if index != len(display_videos):
            elements.append({"tag": "hr"})

    if len(videos) > max_items:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"本次共有 {len(videos)} 条更新，以上仅展示前 {max_items} 条，请点击完整简报查看全部内容。",
                },
            }
        )
        if brief_detail_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看完整简报"},
                            "type": "primary",
                            "url": brief_detail_url,
                        }
                    ],
                }
            )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": f"流媒体更新简报｜{brief_date} {brief_time}"},
            },
            "elements": elements,
        },
    }


def send_feishu_card(webhook_url: str, card_payload: dict[str, Any]) -> None:
    response = _post_feishu_json_with_retry(webhook_url, card_payload)
    logger.info("飞书 Card 返回: webhook=%s status=%s body=%s", redact_secret(webhook_url), response.status_code, response.text[:300])
    _raise_for_feishu_error(response)


def normalize_video_for_card(video: dict[str, Any]) -> dict[str, str]:
    aweme_id = str(video.get("aweme_id") or "")
    title = str(video.get("title") or "未命名视频")
    summary_status = str(video.get("summary_status") or "").lower()
    raw_summary = str(video.get("text") or video.get("summary_text") or "").strip()
    parsed = _parse_summary_json(raw_summary)
    importance_level = ""
    recommended_action = ""
    value_score = 0.0
    summary_failed = summary_status == "failed" or "AI 整理失败" in raw_summary or "AI 摘要生成失败" in raw_summary
    if summary_failed:
        short_summary_value = SUMMARY_FAILED_TEXT
        short_title_value = title
    elif parsed:
        short_title_value = str(parsed.get("brief_title") or title)
        short_summary_value = str(parsed.get("brief_summary") or SUMMARY_PENDING_TEXT)
        importance_level = str(parsed.get("importance_level") or "").strip()
        recommended_action = str(parsed.get("recommended_action") or "").strip().lower()
        value_score = _float_score(parsed.get("value_score"))
    elif raw_summary:
        short_summary_value = _limit_chars(_plain_summary(raw_summary), 100)
        short_title_value = _infer_short_title(raw_summary, title)
    else:
        short_summary_value = SUMMARY_PENDING_TEXT
        short_title_value = title
    video_url = str(video.get("video_url") or video.get("url") or "")
    if aweme_id and (not video_url or "/aweme/v1/play/" in video_url):
        video_url = f"https://www.douyin.com/video/{aweme_id}"
    summary_limit = 200 if _importance_rank(importance_level or "中") >= _importance_rank("高") else 100
    publish_time = str(video.get("publish_time") or video.get("create_time") or "未知时间")
    return {
        "short_title": _limit_chars(short_title_value, 30),
        "short_summary": _limit_chars(short_summary_value, summary_limit),
        "aweme_id": aweme_id,
        "blogger_name": str(video.get("blogger_name") or "未知博主"),
        "publish_time": publish_time,
        "publish_delta": _publish_delta_label(publish_time),
        "video_url": video_url,
        "detail_url": _normalize_public_url(str(video.get("html_url") or video.get("public_url") or video.get("detail_url") or "")),
        "note_path": str(video.get("note_path") or video.get("summary_path") or ""),
        "summary_path": str(video.get("summary_path") or ""),
        "title": title,
        "importance_level": importance_level or "中",
        "recommended_action": recommended_action,
        "value_score": f"{value_score:.1f}" if value_score else "",
    }


class FeishuPusher:
    def __init__(self, config: AppConfig, database: Any):
        self.config = config
        self.database = database
        self.publisher = StaticSitePublisher(config)

    def push(
        self,
        items: list[dict[str, Any]],
        before_send: Callable[[str, list[dict[str, str]]], str | None] | None = None,
    ) -> bool:
        if not self.config.get("notification.enabled", True):
            return True
        if not items:
            return True

        webhook_url = self.config.feishu_webhook_url
        if not webhook_url:
            raise ValueError("未配置飞书 Webhook：请设置 FEISHU_WEBHOOK_URL 或 config/config.yaml")

        now = datetime.now()
        batch_id = uuid.uuid4().hex
        brief_path = self._write_brief_archive(items, push_status="pending")
        brief_detail_url = self._file_url(brief_path)
        all_videos = [self._normalize_video_for_card(item) for item in items]
        videos = self._filter_push_videos(all_videos)
        if not videos:
            self._write_brief_archive(items, push_status="archived", existing_path=brief_path)
            for item in items:
                self.database.insert_push_log(str(item.get("aweme_id") or ""), batch_id, "archived", "过滤后无可推送内容")
            return True
        max_items = int(self.config.get("notification.channels.feishu.card_max_items", 5) or 5)
        mode = str(self.config.get("notification.channels.feishu.message_type", "auto") or "auto").lower()
        fallback_enabled = bool(self.config.get("notification.channels.feishu.fallback_enabled", True))
        card_payload = build_kenradar_feishu_card(
            brief_date=now.strftime("%Y-%m-%d"),
            brief_time=now.strftime("%H:%M"),
            videos=videos,
            max_items=max_items,
            brief_detail_url=brief_detail_url,
        )
        if before_send:
            brief_detail_url = before_send(brief_detail_url, videos) or brief_detail_url
            card_payload = build_kenradar_feishu_card(
                brief_date=now.strftime("%Y-%m-%d"),
                brief_time=now.strftime("%H:%M"),
                videos=videos,
                max_items=max_items,
                brief_detail_url=brief_detail_url,
            )

        try:
            if mode == "text":
                self._send_text_fallback(webhook_url, videos, brief_detail_url)
            elif mode == "card" or self._supports_interactive_card(webhook_url):
                send_feishu_card(webhook_url, card_payload)
            else:
                self._send_text_fallback(webhook_url, videos, brief_detail_url)
        except Exception as card_exc:
            if not fallback_enabled:
                self.database.insert_push_log(None, batch_id, "failed", str(card_exc), message_type=mode)
                return False
            try:
                self._send_text_fallback(webhook_url, videos, brief_detail_url)
            except Exception as fallback_exc:
                message = f"card failed: {card_exc}; text fallback failed: {fallback_exc}"
                self.database.insert_push_log(None, batch_id, "failed", message)
                return False

        pushed_aweme_ids = {str(video.get("aweme_id") or "") for video in videos if video.get("aweme_id")}
        for item in items:
            aweme_id = str(item.get("aweme_id") or "")
            if not pushed_aweme_ids or aweme_id in pushed_aweme_ids:
                self.database.insert_push_log(aweme_id, batch_id, "success")
            else:
                self.database.insert_push_log(aweme_id, batch_id, "archived", "未达到本次飞书推送评分/推荐动作阈值")
        self._write_brief_archive(items, push_status="success", existing_path=brief_path)
        self._file_url(brief_path)
        return True

    def _filter_push_videos(self, videos: list[dict[str, str]]) -> list[dict[str, str]]:
        max_age_hours = float(self.config.get("notification.channels.feishu.max_publish_age_hours", 36) or 0)
        if max_age_hours > 0:
            videos = [video for video in videos if _publish_age_hours(video.get("publish_time")) <= max_age_hours]
        selected_by_value = [
            video
            for video in videos
            if str(video.get("recommended_action") or "") == "push" or _float_score(video.get("value_score")) >= 4
        ]
        if selected_by_value:
            videos = selected_by_value
        if not self.config.get("notification.importance_filter.enabled", False):
            return videos
        min_level = str(self.config.get("notification.importance_filter.min_level", "低") or "低")
        quiet_low = bool(self.config.get("notification.importance_filter.quiet_low", True))
        selected = [video for video in videos if _importance_rank(video.get("importance_level", "中")) >= _importance_rank(min_level)]
        if quiet_low:
            selected = [video for video in selected if _importance_rank(video.get("importance_level", "中")) > _importance_rank("低")]
        return selected

    def push_empty_report(
        self,
        stats: dict[str, Any] | None = None,
        before_send: Callable[[str, list[dict[str, str]]], str | None] | None = None,
    ) -> bool:
        if not self.config.get("notification.enabled", True):
            return True
        if not self.config.get("notification.channels.feishu.send_empty_report", True):
            return True
        webhook_url = self.config.feishu_webhook_url
        if not webhook_url:
            raise ValueError("未配置飞书 Webhook：请设置 FEISHU_WEBHOOK_URL 或 config/config.yaml")

        now = datetime.now()
        batch_id = uuid.uuid4().hex
        brief_path = self._write_empty_brief_archive(stats or {}, push_status="pending")
        brief_detail_url = self._file_url(brief_path)
        mode = str(self.config.get("notification.channels.feishu.empty_report_message_type", "text") or "text").lower()
        fallback_enabled = bool(self.config.get("notification.channels.feishu.fallback_enabled", True))
        if before_send:
            brief_detail_url = before_send(brief_detail_url, []) or brief_detail_url
        try:
            if mode == "text" or mode == "auto":
                self._send_text_fallback(webhook_url, [], brief_detail_url)
            elif mode == "card" and self._supports_interactive_card(webhook_url):
                payload = build_kenradar_feishu_card(
                    brief_date=now.strftime("%Y-%m-%d"),
                    brief_time=now.strftime("%H:%M"),
                    videos=[],
                    max_items=0,
                    brief_detail_url=brief_detail_url,
                )
                send_feishu_card(webhook_url, payload)
            else:
                self._send_text_fallback(webhook_url, [], brief_detail_url)
        except Exception as card_exc:
            if not fallback_enabled:
                self.database.insert_push_log(None, batch_id, "failed", str(card_exc))
                return False
            try:
                self._send_text_fallback(webhook_url, [], brief_detail_url)
            except Exception as fallback_exc:
                self.database.insert_push_log(None, batch_id, "failed", f"card failed: {card_exc}; text fallback failed: {fallback_exc}", message_type=mode)
                return False
        self.database.insert_push_log(None, batch_id, "success", "本时段无新增视频", message_type=mode)
        self._write_empty_brief_archive(stats or {}, push_status="success", existing_path=brief_path)
        self._file_url(brief_path)
        return True

    def push_research_summary(self, job_id: int, blogger_name: str, stats: dict[str, Any]) -> bool:
        if not self.config.get("notification.enabled", True):
            return True
        webhook_url = self.config.feishu_webhook_url
        if not webhook_url:
            return False
        batch_id = f"research-{job_id}-{uuid.uuid4().hex[:8]}"
        notification_title = f"流媒体更新简报｜研究归档完成｜{blogger_name}"
        detail_url = (
            str(stats.get("report_url") or "").strip()
            or f"{str(self.config.get('app.web_base_url', 'http://172.30.10.150:8765')).rstrip('/')}/research/jobs?id={job_id}"
        )
        detail_url = _normalize_public_url(detail_url)
        content = (
            f"{notification_title}\n\n"
            f"本次抓取：{stats.get('fetched', 0)} 条\n"
            f"新增处理：{stats.get('processed', 0)} 条\n"
            f"已跳过：{stats.get('skipped', 0)} 条\n"
            f"失败：{stats.get('failed', 0)} 条"
        )
        try:
            if self._supports_interactive_card(webhook_url):
                payload = {
                    "msg_type": "interactive",
                    "card": {
                        "config": {"wide_screen_mode": True},
                        "header": {
                            "template": "blue",
                            "title": {"tag": "plain_text", "content": notification_title},
                        },
                        "elements": [
                            {"tag": "div", "text": {"tag": "lark_md", "content": content.replace("\n", "\n\n")}},
                            {
                                "tag": "action",
                                "actions": [
                                    {
                                        "tag": "button",
                                        "text": {"tag": "plain_text", "content": "查看全文"},
                                        "type": "primary",
                                        "url": detail_url,
                                    }
                                ],
                            },
                        ],
                    },
                }
                send_feishu_card(webhook_url, payload)
            else:
                response = _post_feishu_json_with_retry(webhook_url, {"msg_type": "text", "content": {"text": f"{content}\n\n查看全文：{detail_url}"}})
                _raise_for_feishu_error(response)
        except Exception as exc:
            self.database.insert_push_log(None, batch_id, "failed", str(exc))
            return False
        self.database.insert_push_log(None, batch_id, "success")
        return True

    def _render(self, items: list[dict[str, Any]], brief_path: Path | None = None) -> str:
        now = datetime.now()
        videos = [normalize_video_for_card(item) for item in items]
        bloggers = {video["blogger_name"] for video in videos}
        lines = [
            f"# 流媒体更新简报｜{now.strftime('%Y-%m-%d %H:%M')}",
            "",
            f"本时段共监控到 **{len(bloggers)} 位博主** 更新，合计 **{len(items)} 条视频**。",
            "",
        ]
        for index, video in enumerate(videos[:5], start=1):
            lines.append(f"## {index}. {video['blogger_name']}｜{video['short_title']}")
            lines.append("")
            lines.append(f"发布时间：{video['publish_time']}")
            lines.append("")
            lines.append(video["short_summary"])
            lines.append("")
            if video["video_url"]:
                lines.append(f"原视频：{video['video_url']}")
            if video["detail_url"]:
                lines.append(f"发布页：{video['detail_url']}")
            lines.append("")
        if len(videos) > 5:
            lines.append(f"本次共有 {len(videos)} 条更新，以上仅展示前 5 条。")
        if brief_path:
            lines.extend(["---", "", "完整简报已归档：", self._file_url(brief_path)])
        return "\n".join(lines).strip()

    def _write_brief_archive(self, items: list[dict[str, Any]], push_status: str, existing_path: Path | None = None) -> Path:
        now = datetime.now()
        output_dir = brief_dir(self.config)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = existing_path or output_dir / f"{now.strftime('%Y-%m-%d_%H%M')}_流媒体更新简报.md"
        videos = [normalize_video_for_card(item) for item in items]
        bloggers = sorted({video["blogger_name"] for video in videos})
        push_time = now.strftime("%Y-%m-%d %H:%M:%S") if push_status == "success" else ""
        overview = [f"{EMOJIS[index % len(EMOJIS)]} {video['short_title']}" for index, video in enumerate(videos[:5])]
        lines = [
            f"# 流媒体更新简报｜{now.strftime('%Y-%m-%d %H:%M')}",
            "",
            f"本次共 **{len(bloggers)} 位博主** 更新，合计 **{len(videos)} 条视频**。",
            "",
            "## 总览",
            "",
            "\n".join(overview) if overview else "暂无更新",
            "",
            "---",
            "",
            "## 视频详情",
            "",
        ]
        for index, video in enumerate(videos[:5], start=1):
            lines.extend(
                [
                    f"### {index}. {video['short_title']}",
                    "",
                    video["short_summary"],
                    "",
                    f"博主：{video['blogger_name']} ｜ 发布时间：{video['publish_time']} ｜ 距推送：{video['publish_delta'] or '未知'}",
                    "",
                    f"[原视频]({video['video_url']})  [阅读全文]({video['detail_url']})",
                    f"本地笔记：{video.get('note_path') or ''}",
                    "",
                ]
            )
            if index != min(len(videos), 5):
                lines.extend(["---", ""])
        if len(videos) > 5:
            lines.extend(["", f"本次共有 {len(videos)} 条更新，以上仅展示前 5 条。", ""])
        lines.extend(["", f"推送状态：{push_status}", f"推送时间：{push_time or '待发送'}", ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_empty_brief_archive(self, stats: dict[str, Any], push_status: str, existing_path: Path | None = None) -> Path:
        now = datetime.now()
        output_dir = brief_dir(self.config)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = existing_path or output_dir / f"{now.strftime('%Y-%m-%d_%H%M')}_流媒体更新简报.md"
        push_time = now.strftime("%Y-%m-%d %H:%M:%S") if push_status == "success" else ""
        lines = [
            f"# 流媒体更新简报｜{now.strftime('%Y-%m-%d %H:%M')}",
            "",
            "本时段已完成定时检测，未发现新的抖音视频更新。",
            "",
            "可能原因：无新作品、作品已去重、发布时间超过推送窗口、价值评分/推荐动作未达到推送条件，或上游抓取/AI 阶段已在告警中记录。",
            "",
            "## 检测结果",
            "",
            f"- 监控博主：{stats.get('bloggers', 0)} 位",
            f"- 新增视频：{stats.get('new_awemes', 0)} 条",
            f"- 失败任务：{stats.get('failed', 0)} 条",
            "",
            f"推送状态：{push_status}",
            f"推送时间：{push_time or '待发送'}",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _file_url(self, path: Path) -> str:
        public_url = self.publisher.publish_markdown(path)
        if public_url:
            return public_url
        base_url = str(self.config.get("app.web_base_url", "http://172.30.10.150:8765") or "http://172.30.10.150:8765").rstrip("/")
        return f"{base_url}/file?path={quote(str(path))}"

    def _send_text_fallback(self, webhook_url: str, videos: list[dict[str, str]], brief_detail_url: str) -> None:
        content = self._render_normalized_text(videos, brief_detail_url)
        payload = {"msg_type": "text", "content": {"text": content}}
        response = _post_feishu_json_with_retry(webhook_url, payload)
        logger.info("飞书 Text 返回: webhook=%s status=%s body=%s", redact_secret(webhook_url), response.status_code, response.text[:300])
        _raise_for_feishu_error(response)

    @staticmethod
    def _render_normalized_text(videos: list[dict[str, str]], brief_detail_url: str) -> str:
        now = datetime.now()
        if not videos:
            lines = [
                f"KenRadar 定时检测报告｜{now.strftime('%Y-%m-%d %H:%M')}",
                "",
                "本时段已完成定时检测，未发现新的抖音视频更新。",
                "",
                "可能原因：无新作品、作品已去重、发布时间超过推送窗口、价值评分/推荐动作未达到推送条件，或上游抓取/AI 阶段已在告警中记录。",
            ]
            if brief_detail_url:
                lines.extend(["", f"完整简报：{brief_detail_url}"])
            return "\n".join(lines).strip()
        lines = [
            f"流媒体更新简报｜{now.strftime('%Y-%m-%d %H:%M')}",
            "",
            f"本次共有 {len(videos)} 条更新，以下展示前 5 条。",
            "",
        ]
        for index, video in enumerate(videos[:5], start=1):
            lines.extend(
                [
                    f"{index}. {video['short_title']}",
                    video["short_summary"],
                    f"博主：{video['blogger_name']} ｜ 发布时间：{video['publish_time']} ｜ 距推送：{video['publish_delta'] or '未知'}",
                    f"原视频：{video['video_url']}",
                    f"发布页：{video['detail_url']}",
                    "",
                ]
            )
        if len(videos) > 5:
            lines.append("更多内容请查看完整简报。")
        if brief_detail_url:
            lines.extend(["", f"完整简报：{brief_detail_url}"])
        return "\n".join(lines).strip()

    @staticmethod
    def _supports_interactive_card(webhook_url: str) -> bool:
        return "open.feishu.cn" in webhook_url or "open.larksuite.com" in webhook_url

    def _normalize_video_for_card(self, video: dict[str, Any]) -> dict[str, str]:
        normalized = normalize_video_for_card(video)
        detail_url = self._public_detail_url(normalized)
        if detail_url:
            normalized["detail_url"] = detail_url
        return normalized

    def _public_detail_url(self, video: dict[str, str]) -> str:
        note_path = str(video.get("summary_path") or video.get("note_path") or "").strip()
        if note_path:
            public_url = self.publisher.public_url_for(note_path)
            if public_url:
                return public_url

        aweme_id = str(video.get("aweme_id") or "").strip()
        if aweme_id:
            summary = self.database.get_summary(aweme_id)
            summary_path = str((summary or {}).get("summary_path") or "").strip()
            if summary_path:
                public_url = self.publisher.public_url_for(summary_path)
                if public_url:
                    return public_url

        html_url = _normalize_public_url(str(video.get("detail_url") or video.get("public_url") or video.get("html_url") or ""))
        return html_url


def _normalize_public_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    normalized_path = "/".join(quote(unquote(part), safe="-_.~") for part in parsed.path.split("/"))
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))


def _raise_for_feishu_error(response: requests.Response) -> None:
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        data = response.json()
    except ValueError:
        return
    status_code = data.get("StatusCode")
    code = data.get("code")
    if (status_code is not None and status_code != 0) or (code is not None and code != 0):
        message = data.get("msg") or data.get("StatusMessage") or str(data)
        raise RuntimeError(str(message))


def _post_feishu_json_with_retry(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    attempts: int = 3,
    retry_delay: float = 5.0,
) -> requests.Response:
    last_response: requests.Response | None = None
    for attempt in range(1, max(1, attempts) + 1):
        response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        last_response = response
        if not _is_feishu_rate_limited(response):
            return response
        if attempt >= attempts:
            return response
        sleep_seconds = retry_delay * attempt
        logger.warning(
            "飞书返回频率限制，%.1f 秒后重试: webhook=%s attempt=%s/%s body=%s",
            sleep_seconds,
            redact_secret(webhook_url),
            attempt,
            attempts,
            response.text[:300],
        )
        time.sleep(sleep_seconds)
    assert last_response is not None
    return last_response


def _is_feishu_rate_limited(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    try:
        data = response.json()
    except ValueError:
        return False
    code = data.get("code")
    status_code = data.get("StatusCode")
    message = str(data.get("msg") or data.get("StatusMessage") or "")
    return code in FEISHU_RATE_LIMIT_CODES or status_code in FEISHU_RATE_LIMIT_CODES or "frequency limited" in message.lower()


def _infer_short_title(summary: str, fallback_title: str) -> str:
    plain = _plain_summary(summary)
    for line in plain.splitlines():
        line = line.strip(" -:：")
        if not line:
            continue
        if "AI 整理失败" in line or "摘要生成失败" in line:
            continue
        if len(line) <= 60:
            return line
    return fallback_title


def _parse_summary_json(value: str) -> dict[str, Any] | None:
    return parse_ai_json(value)


def _parse_publish_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text or text == "未知时间":
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text))
        except (OSError, ValueError):
            return None
    normalized = text.replace("T", " ").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _publish_age_hours(value: Any) -> float:
    publish_time = _parse_publish_time(value)
    if publish_time is None:
        return 10**9
    return max(0.0, (datetime.now() - publish_time).total_seconds() / 3600)


def _publish_delta_label(value: Any) -> str:
    publish_time = _parse_publish_time(value)
    if publish_time is None:
        return ""
    seconds = int((datetime.now() - publish_time).total_seconds())
    if seconds < 0:
        seconds = 0
    minutes = seconds // 60
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 48:
        rest_minutes = minutes % 60
        return f"{hours} 小时 {rest_minutes} 分钟" if rest_minutes else f"{hours} 小时"
    days = hours // 24
    return f"{days} 天"


def _importance_rank(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized in {"高", "high", "重要", "urgent"}:
        return 3
    if normalized in {"中", "medium", "normal", "一般"}:
        return 2
    if normalized in {"低", "low", "quiet"}:
        return 1
    return 2


def _float_score(value: Any) -> float:
    try:
        return max(0.0, min(5.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _plain_summary(value: str) -> str:
    text = value.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    cleaned_lines: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped or stripped == "---":
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("type:", "platform:", "aweme_id:", "tags:", "created:", "updated:")):
            continue
        stripped = stripped.lstrip("-*0123456789.、 ").strip()
        stripped = stripped.replace("**", "").replace("`", "")
        if stripped:
            cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines).strip()


def _limit_chars(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned or "未命名视频"
    return cleaned[:limit].rstrip() + "..."
