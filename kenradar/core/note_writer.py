from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.obsidian import note_dir, note_filename, platform_label


class NoteWriter:
    def __init__(self, workflow: Any, atomic_write_text: Any):
        self.workflow = workflow
        self._atomic_write_text = atomic_write_text

    def write_item_summary(
        self,
        aweme_id: str,
        title: str,
        summary_text: str,
        original_text: str,
        metadata: dict[str, Any] | None = None,
        transcript_path: str = "",
        summary_status: str = "success",
        transcript_model: str = "",
    ) -> Path:
        workflow = self.workflow
        metadata = metadata or {}
        platform = str(metadata.get("platform") or "douyin")
        blogger_name = str(metadata.get("blogger_name") or "未知博主")
        blogger_id = str(metadata.get("blogger_id") or "")
        publish_time = str(metadata.get("publish_time") or "")
        raw_video_url = str(metadata.get("video_url") or metadata.get("media_url") or "")
        source_url = workflow._canonical_source_url(platform, aweme_id, raw_video_url)
        media_url = raw_video_url if raw_video_url and raw_video_url != source_url else ""
        summary_model = str(workflow.config.get("ai.organizer.model", ""))
        transcript_model = transcript_model or str(workflow.config.get("ai.whisper.model", "large-v3-turbo"))
        organized = workflow._normalize_ai_output(summary_text, title, original_text, summary_status, aweme_id)
        if platform == "xiaoyuzhou" or str(metadata.get("media_type") or "") == "audio":
            return self.write_podcast_summary(
                aweme_id,
                title,
                organized,
                original_text,
                metadata,
                summary_model,
                transcript_model,
            )
        brief_title = organized["brief_title"]
        topics = workflow._obsidian_topics(organized, title, summary_text)
        entities = workflow._obsidian_entities(organized, title, summary_text)
        note_tags = workflow._obsidian_tags(platform, topics)
        aliases = workflow._obsidian_aliases(title, brief_title, blogger_name)
        related = workflow._obsidian_related_values(blogger_name, platform, topics, entities)
        output_dir = note_dir(workflow.config, platform, blogger_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / note_filename(publish_time, brief_title, aweme_id)
        workflow._remove_stale_item_notes(aweme_id, path)
        lines = [
            "---",
            "type: video_note",
            "template_version: obsidian-video-v2",
            f"platform: {workflow._yaml_str(platform_label(platform))}",
            f"creator: {workflow._yaml_str(blogger_name)}",
            f"creator_id: {workflow._yaml_str(blogger_id)}",
            f"video_id: {workflow._yaml_str(aweme_id)}",
            f"source_url: {workflow._yaml_str(source_url)}",
            *( [f"media_url: {workflow._yaml_str(media_url)}"] if media_url else [] ),
            f"original_title: {workflow._yaml_str(title)}",
            f"title: {workflow._yaml_str(brief_title)}",
            "aliases:",
            *workflow._yaml_list(aliases),
            f"published_at: {workflow._yaml_str(publish_time or '')}",
            f"ai_model: {workflow._yaml_str(summary_model)}",
            f"transcript_model: {workflow._yaml_str(transcript_model)}",
            "topics:",
            *workflow._yaml_list(topics),
            "tags:",
            *workflow._yaml_list(note_tags),
            "entities:",
            *workflow._yaml_list(entities),
            "related:",
            *workflow._yaml_list(related),
            "status: processed",
            f"value_score: {workflow._yaml_number(organized.get('value_score'))}",
            f"regenerated_at: {workflow._yaml_str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
            "---",
            "",
            f"# {brief_title}",
            "",
            workflow._render_note_source_line(platform, blogger_name, source_url),
            "",
            "## 一、内容简述",
            "",
            workflow._render_content_summary(organized),
            "",
            "## 二、分段原文",
            "",
            workflow._render_corrected_transcript(organized),
            "",
            "## 三、知识关联",
            "",
            workflow._render_knowledge_links(topics, entities, blogger_name, platform),
            "",
            "## 四、视频原始转录",
            "",
            "> [!quote]- 展开查看原始转录",
            "> 以下内容由 Whisper 自动转录生成，可能存在错字、断句错误或语义遗漏，请以原视频为准。",
            ">",
            *workflow._blockquote_lines(original_text or "无转录文本。"),
            "",
        ]
        markdown = "\n".join(lines)
        workflow._validate_obsidian_note(markdown, path)
        self._atomic_write_text(path, markdown)
        return path

    def write_podcast_summary(
        self,
        content_id: str,
        title: str,
        organized: dict[str, Any],
        original_text: str,
        metadata: dict[str, Any],
        summary_model: str,
        transcript_model: str,
    ) -> Path:
        workflow = self.workflow
        creator_name = str(metadata.get("blogger_name") or metadata.get("creator") or "未知播客")
        creator_id = str(metadata.get("blogger_id") or metadata.get("creator_id") or "")
        publish_time = str(metadata.get("publish_time") or "")
        source_url = str(metadata.get("video_url") or metadata.get("source_url") or "")
        brief_title = organized["brief_title"]
        topics = workflow._obsidian_topics(organized, title, json.dumps(organized, ensure_ascii=False))
        entities = workflow._obsidian_entities(organized, title, json.dumps(organized, ensure_ascii=False))
        note_tags = ["KenRadar", "播客笔记", "小宇宙", *[topic for topic in topics if topic not in {"KenRadar", "播客笔记", "小宇宙"}]][:10]
        output_dir = note_dir(workflow.config, "podcast", creator_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / note_filename(publish_time, brief_title, content_id)
        workflow._remove_stale_item_notes(content_id, path)
        conclusion = workflow._clean_summary_value(organized.get("one_sentence_conclusion")) or workflow._clean_summary_value(organized.get("brief_summary")) or "暂无摘要。"
        lines = [
            "---",
            "source: podcast",
            "platform: xiaoyuzhou",
            "media_type: audio",
            f"content_id: {workflow._yaml_str(content_id)}",
            f"episode_id: {workflow._yaml_str(str(metadata.get('episode_id') or content_id))}",
            f"show_id: {workflow._yaml_str(str(metadata.get('show_id') or creator_id))}",
            f"creator: {workflow._yaml_str(creator_name)}",
            f"creator_id: {workflow._yaml_str(creator_id)}",
            f"title: {workflow._yaml_str(brief_title)}",
            f"original_title: {workflow._yaml_str(title)}",
            f"source_url: {workflow._yaml_str(source_url)}",
            f"published_at: {workflow._yaml_str(publish_time)}",
            f"duration: {workflow._yaml_number(metadata.get('duration'))}",
            f"ai_model: {workflow._yaml_str(summary_model)}",
            f"transcript_model: {workflow._yaml_str(transcript_model)}",
            "topics:",
            *workflow._yaml_list(topics),
            "tags:",
            *workflow._yaml_list(note_tags),
            "created_at: " + workflow._yaml_str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "status: processed",
            f"value_score: {workflow._yaml_number(organized.get('value_score'))}",
            "---",
            "",
            f"# {brief_title}",
            "",
            "## 一句话摘要",
            "",
            conclusion,
            "",
            "## 本期主题",
            "",
            workflow._render_knowledge_links(topics, entities),
            "",
            "## 核心观点",
            "",
            workflow._render_bullet_section(organized, ["key_points", "core_points", "important_points"], fallback=workflow._clean_summary_value(organized.get("brief_summary"))),
            "",
            "## 重要信息点",
            "",
            workflow._render_bullet_section(organized, ["insights", "facts", "information_points"]),
            "",
            "## 时间线",
            "",
            workflow._render_podcast_timeline(organized),
            "",
            "## 对产业 / 投资 / 商业研究的启发",
            "",
            workflow._render_bullet_section(organized, ["investment_implications", "research_value", "opportunities"], fallback="暂无明确启发。"),
            "",
            "## 后续可跟踪线索",
            "",
            workflow._render_bullet_section(organized, ["follow_up", "follow_up_clues", "risks"], fallback="暂无后续线索。"),
            "",
            "## 风险与不确定性",
            "",
            workflow._render_bullet_section(organized, ["risks", "uncertainties"], fallback="暂无明确风险提示。"),
            "",
            "## 原始链接",
            "",
            source_url or "无",
            "",
            "## 原始转录",
            "",
            "> 以下内容由 ASR 自动转录生成，可能存在错字、断句错误或语义遗漏，请以原音频为准。",
            "",
            original_text or "无转录文本。",
            "",
        ]
        self._atomic_write_text(path, "\n".join(lines))
        return path
