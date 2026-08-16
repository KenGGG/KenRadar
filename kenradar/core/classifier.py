from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.ai_json import parse_ai_json
from kenradar.core.config import AppConfig
from kenradar.core.organizer import ContentOrganizer
from kenradar.core.workflow import Workflow, platform_label
from kenradar.storage import create_database

logger = logging.getLogger(__name__)


THEME_TAXONOMY = [
    "AI产业",
    "算力中心",
    "半导体",
    "港股市场",
    "股票市场",
    "宏观经济",
    "货币政策",
    "房地产",
    "新能源车",
    "新能源",
    "商业航天",
    "创新药",
    "医药行业",
    "红利资产",
    "投资策略",
    "资产配置",
    "量化交易",
    "消费行业",
    "金融机构",
    "国企改革",
    "出海业务",
    "产业链调研",
    "公司研究",
    "风险提示",
    "其他",
]


class ExistingContentClassifier:
    def __init__(self, config: AppConfig):
        self.config = config
        self.database = create_database(config)
        self.organizer = ContentOrganizer(config)

    def classify_existing(
        self,
        limit: int = 0,
        only_missing: bool = False,
        skip_classified: bool = False,
        batch_size: int = 5,
        dry_run: bool = False,
        update_notes: bool = True,
    ) -> dict[str, Any]:
        provider = self._agnes_provider()
        api_key = self.organizer._provider_api_key(provider)
        if not api_key:
            raise RuntimeError("缺少 AGNES_API_KEY，无法使用 Agnes 进行已有内容重分类。")

        rows = self._load_rows(limit=limit, only_missing=only_missing, skip_classified=skip_classified)
        batch_size = max(1, min(10, int(batch_size or 1)))
        stats: dict[str, Any] = {
            "total": len(rows),
            "classified": 0,
            "updated": 0,
            "notes_updated": 0,
            "skipped": 0,
            "failed": 0,
            "dry_run": dry_run,
            "batch_size": batch_size,
        }
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            try:
                batch_results = (
                    self._classify_rows_batch(provider, api_key, batch)
                    if len(batch) > 1
                    else {str(batch[0].get("aweme_id") or ""): self._classify_row(provider, api_key, batch[0], self._summary_json(batch[0]))}
                )
            except Exception as exc:
                logger.warning("批量分类失败，降级为逐条分类: range=%s-%s error=%s", offset + 1, offset + len(batch), exc)
                batch_results = {}
                for row in batch:
                    aweme_id = str(row.get("aweme_id") or "")
                    try:
                        batch_results[aweme_id] = self._classify_row(provider, api_key, row, self._summary_json(row))
                    except Exception as item_exc:
                        stats["failed"] += 1
                        logger.exception("已有内容重分类失败: aweme_id=%s error=%s", aweme_id, item_exc)

            for batch_index, row in enumerate(batch, start=1):
                index = offset + batch_index
                aweme_id = str(row.get("aweme_id") or "")
                if aweme_id not in batch_results:
                    stats["skipped"] += 1
                    continue
                self._apply_classification_row(
                    row=row,
                    classification=batch_results[aweme_id],
                    provider=provider,
                    index=index,
                    total=len(rows),
                    stats=stats,
                    dry_run=dry_run,
                    update_notes=update_notes,
                )
        return stats

    def _apply_classification_row(
        self,
        row: dict[str, Any],
        classification: dict[str, Any],
        provider: dict[str, Any],
        index: int,
        total: int,
        stats: dict[str, Any],
        dry_run: bool,
        update_notes: bool,
    ) -> None:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "")
        try:
            current = self._summary_json(row)
            merged = self._merge_summary_json(current, classification)
            stats["classified"] += 1
            if dry_run:
                logger.info(
                    "分类预览 %s/%s aweme_id=%s category=%s topics=%s",
                    index,
                    total,
                    aweme_id,
                    merged.get("content_category"),
                    ", ".join(merged.get("tags") or []),
                )
                return
            self._update_summary(row, merged, provider)
            stats["updated"] += 1
            if update_notes and self._update_note_frontmatter(row, merged):
                stats["notes_updated"] += 1
            logger.info(
                "已重分类 %s/%s aweme_id=%s title=%s category=%s topics=%s",
                index,
                total,
                aweme_id,
                title[:30],
                merged.get("content_category"),
                ", ".join(merged.get("tags") or []),
            )
        except Exception as exc:
            stats["failed"] += 1
            logger.exception("已有内容重分类失败: aweme_id=%s title=%s error=%s", aweme_id, title, exc)

    def _agnes_provider(self) -> dict[str, Any]:
        providers = self.config.get("ai.organizer.providers", []) or []
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            if str(provider.get("name") or "").strip().lower() == "agnes":
                return dict(provider)
        raise RuntimeError("未找到 Agnes organizer provider。")

    def _load_rows(self, limit: int, only_missing: bool, skip_classified: bool) -> list[dict[str, Any]]:
        sql = """
            SELECT
                ci.id AS content_item_id,
                ci.content_id AS aweme_id,
                ci.title,
                ci.description,
                ci.source_url,
                ci.publish_time,
                cr.nickname,
                a.result_json,
                a.result_text,
                a.model,
                a.status AS summary_status,
                n.note_path,
                t.text_content
            FROM content_item ci
            JOIN ai_analysis a ON a.content_item_id = ci.id AND a.analysis_type = 'summary'
            LEFT JOIN creator cr ON cr.id = ci.creator_id
            LEFT JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
            LEFT JOIN transcript t ON t.content_item_id = ci.id
            WHERE a.status = 'success'
            ORDER BY COALESCE(ci.publish_time, ci.created_at) DESC, ci.id DESC
        """
        with self.database.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql).fetchall()]
        if only_missing:
            rows = [row for row in rows if not self._summary_tags(row)]
        if skip_classified:
            rows = [row for row in rows if self._summary_json(row).get("classification_source") != "agnes"]
        if limit > 0:
            rows = rows[:limit]
        return rows

    @staticmethod
    def _summary_json(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get("result_json")
        if isinstance(value, dict):
            return deepcopy(value)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        parsed = parse_ai_json(str(row.get("result_text") or ""))
        return parsed if isinstance(parsed, dict) else {}

    def _summary_tags(self, row: dict[str, Any]) -> list[str]:
        data = self._summary_json(row)
        return Workflow._string_list(data.get("tags") or data.get("keywords") or [])

    def _classify_row(
        self,
        provider: dict[str, Any],
        api_key: str,
        row: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = self._classification_prompt(row, current)
        local_provider = dict(provider)
        local_provider["max_tokens"] = min(int(local_provider.get("max_tokens") or 4096), 1200)
        local_provider["request_timeout"] = min(int(local_provider.get("request_timeout") or 300), 60)
        local_provider["temperature"] = 0.1
        local_provider["top_p"] = 0.9
        local_provider["omit_top_k"] = True
        text = self.organizer._organize_with_provider(local_provider, api_key, prompt)
        parsed = parse_ai_json(text)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Agnes 分类结果不是 JSON: {text[:120]}")
        return parsed

    def _classify_rows_batch(
        self,
        provider: dict[str, Any],
        api_key: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        prompt = self._batch_classification_prompt(rows)
        local_provider = dict(provider)
        local_provider["max_tokens"] = min(int(local_provider.get("max_tokens") or 4096), 4096)
        local_provider["request_timeout"] = min(int(local_provider.get("request_timeout") or 300), 60)
        local_provider["temperature"] = 0.1
        local_provider["top_p"] = 0.9
        local_provider["omit_top_k"] = True
        text = self.organizer._organize_with_provider(local_provider, api_key, prompt)
        parsed = parse_ai_json(text) or self._parse_json_object(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
            raise RuntimeError(f"Agnes 批量分类结果不是 items JSON: {text[:160]}")
        results: dict[str, dict[str, Any]] = {}
        expected = {str(row.get("aweme_id") or "") for row in rows}
        for item in parsed["items"]:
            if not isinstance(item, dict):
                continue
            aweme_id = str(item.get("aweme_id") or "").strip()
            if aweme_id in expected:
                results[aweme_id] = item
        if not results:
            raise RuntimeError("Agnes 批量分类没有返回可匹配 aweme_id")
        return results

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _batch_classification_prompt(self, rows: list[dict[str, Any]]) -> str:
        items: list[dict[str, Any]] = []
        for row in rows:
            current = self._summary_json(row)
            items.append(
                {
                    "aweme_id": str(row.get("aweme_id") or ""),
                    "blogger": str(row.get("nickname") or ""),
                    "title": str(current.get("brief_title") or row.get("title") or "")[:80],
                    "summary": str(current.get("brief_summary") or "")[:220],
                    "sections": self._section_digest(current)[:900],
                    "current_tags": Workflow._string_list(current.get("tags") or current.get("keywords") or []),
                }
            )
        taxonomy = "、".join(THEME_TAXONOMY)
        payload = json.dumps(items, ensure_ascii=False)
        return f"""请为下面多条 KenRadar 已归档内容逐条重新分类。只输出一个 JSON 对象，不要 Markdown 或解释。

分类目标：
- 必须为每个输入 aweme_id 返回一条结果。
- content_category 选择 1 个最核心主题。
- topics 输出 5-10 个可长期复用的中文主题，优先从候选主题中选择，可补充具体行业/资产/机构类型。
- tags 输出 5-8 个用于阅读库筛选的短标签，尽量与 topics 一致。
- keywords 输出 5-10 个具体关键词，可以包含公司、机构、资产、行业链条。
- 删除来源平台话题、活动话题和泛营销词，例如 #财经、干货分享、掘金计划、青年创作者成长计划、股民、庄家。
- 不要编造原文没有依据的公司、数据或结论。

候选主题：
{taxonomy}

输入 items：
{payload}

输出格式：
{{
  "items": [
    {{
      "aweme_id": "7650000000000000000",
      "content_category": "AI产业",
      "topics": ["AI产业", "算力中心", "半导体"],
      "tags": ["AI产业", "算力中心", "半导体"],
      "keywords": ["GPU", "算力租赁", "光模块"],
      "classification_reason": "一句话说明分类依据"
    }}
  ]
}}"""

    @staticmethod
    def _section_digest(current: dict[str, Any]) -> str:
        sections = current.get("content_sections")
        if not isinstance(sections, list):
            return ""
        parts: list[str] = []
        for section in sections[:5]:
            if isinstance(section, dict):
                parts.append(f"{section.get('title') or ''}: {section.get('content') or ''}")
            elif section:
                parts.append(str(section))
        return "\n".join(parts)

    @staticmethod
    def _classification_prompt(row: dict[str, Any], current: dict[str, Any]) -> str:
        title = str(current.get("brief_title") or row.get("title") or "")
        summary = str(current.get("brief_summary") or "")
        sections = current.get("content_sections")
        section_text = ""
        if isinstance(sections, list):
            parts = []
            for section in sections[:5]:
                if isinstance(section, dict):
                    parts.append(f"{section.get('title') or ''}: {section.get('content') or ''}")
                elif section:
                    parts.append(str(section))
            section_text = "\n".join(parts)
        transcript = str(row.get("text_content") or "")[:1800]
        current_tags = ", ".join(Workflow._string_list(current.get("tags") or current.get("keywords") or []))
        taxonomy = "、".join(THEME_TAXONOMY)
        return f"""请为下面这条 KenRadar 已归档内容重新分类。只输出 JSON 对象，不要 Markdown 或解释。

分类目标：
- content_category 必须从候选主题中选择 1 个最核心主题。
- topics 输出 5-10 个可长期复用的中文主题，优先从候选主题中选择，可补充具体行业/资产/机构类型。
- tags 输出 5-8 个用于阅读库筛选的短标签，尽量与 topics 一致。
- keywords 输出 5-10 个具体关键词，可以包含公司、机构、资产、行业链条。
- 删除来源平台话题、活动话题和泛营销词，例如 #财经、干货分享、掘金计划、青年创作者成长计划、股民、庄家。
- 不要编造原文没有依据的公司、数据或结论。
- 如果内容很泛，使用“投资策略”或“其他”，不要强行贴热门主题。

候选主题：
{taxonomy}

当前标签：
{current_tags or "无"}

内容信息：
博主：{row.get("nickname") or ""}
标题：{title}
一句话摘要：{summary}
核心内容：
{section_text}

转录节选：
{transcript}

输出格式：
{{
  "content_category": "AI产业",
  "topics": ["AI产业", "算力中心", "半导体"],
  "tags": ["AI产业", "算力中心", "半导体"],
  "keywords": ["GPU", "算力租赁", "光模块"],
  "classification_reason": "一句话说明分类依据"
}}"""

    def _merge_summary_json(self, current: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        topics = self._normalize_topics(classification.get("topics") or classification.get("tags") or [])
        tags = self._normalize_topics(classification.get("tags") or topics, limit=8)
        keywords = self._normalize_keywords(classification.get("keywords") or [])
        category = Workflow._normalize_topic(str(classification.get("content_category") or "")) or (topics[0] if topics else "")
        if not topics and category:
            topics = [category]
        if category:
            merged["content_category"] = category
        merged["topics"] = topics[:10]
        merged["tags"] = tags[:8] or topics[:8]
        merged["keywords"] = keywords[:10] or topics[:8]
        merged["classification_source"] = "agnes"
        merged["classification_model"] = str(self.config.get("ai.organizer.model", "agnes-2.5-flash") or "agnes-2.5-flash")
        merged["classification_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reason = Workflow._limit_plain_text(str(classification.get("classification_reason") or ""), 120)
        if reason:
            merged["classification_reason"] = reason
        return merged

    @staticmethod
    def _normalize_topics(value: Any, limit: int = 10) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in Workflow._string_list(value, limit=20):
            topic = Workflow._normalize_topic(item)
            if not topic or topic in seen:
                continue
            if topic.startswith("#"):
                continue
            seen.add(topic)
            result.append(topic)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _normalize_keywords(value: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        banned = {"干货分享", "掘金计划", "青年创作者成长计划", "股民", "庄家", "#财经", "#金融"}
        for item in Workflow._string_list(value, limit=16):
            text = re.sub(r"\s+", " ", str(item or "")).strip(" #[]`'\"，。,.；;：:")
            if not text or text in banned or text in seen or len(text) > 24:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _update_summary(self, row: dict[str, Any], merged: dict[str, Any], provider: dict[str, Any]) -> None:
        content_item_id = int(row["content_item_id"])
        result_text = json.dumps(merged, ensure_ascii=False, indent=2)
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE ai_analysis
                SET result_json = %s::jsonb,
                    result_text = %s,
                    model = %s,
                    provider = %s,
                    updated_at = NOW()
                WHERE content_item_id = %s AND analysis_type = 'summary'
                """,
                (
                    json.dumps(merged, ensure_ascii=False),
                    result_text,
                    str(provider.get("model") or "agnes-2.5-flash"),
                    "agnes",
                    content_item_id,
                ),
            )

    def _update_note_frontmatter(self, row: dict[str, Any], merged: dict[str, Any]) -> bool:
        note_path = str(row.get("note_path") or "").strip()
        if not note_path:
            return False
        path = Path(note_path)
        if not path.is_absolute():
            path = self.config.root_dir / path
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\r?\n(?P<front>[\s\S]*?)\r?\n---\r?\n", text)
        if not match:
            return False
        topics = self._normalize_topics(merged.get("topics") or merged.get("tags") or [])
        platform = self._frontmatter_value(match.group("front"), "platform") or "抖音"
        note_tags = self._note_tags(platform, topics)
        front = self._replace_yaml_list(match.group("front"), "topics", topics)
        front = self._replace_yaml_list(front, "tags", note_tags)
        updated = f"---\n{front.rstrip()}\n---\n{text[match.end():]}"
        if updated == text:
            return False
        path.write_text(updated, encoding="utf-8")
        return True

    @staticmethod
    def _frontmatter_value(front: str, key: str) -> str:
        match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", front, flags=re.MULTILINE)
        if not match:
            return ""
        return match.group(1).strip().strip('"')

    @staticmethod
    def _replace_yaml_list(front: str, key: str, values: list[str]) -> str:
        lines = front.splitlines()
        output: list[str] = []
        index = 0
        replaced = False
        while index < len(lines):
            line = lines[index]
            if re.match(rf"^{re.escape(key)}:\s*$", line):
                output.append(f"{key}:")
                output.extend(Workflow._yaml_list(values))
                index += 1
                while index < len(lines) and (lines[index].startswith("  - ") or lines[index].strip() == "[]"):
                    index += 1
                replaced = True
                continue
            output.append(line)
            index += 1
        if not replaced:
            output.extend([f"{key}:", *Workflow._yaml_list(values)])
        return "\n".join(output)

    @staticmethod
    def _note_tags(platform: str, topics: list[str]) -> list[str]:
        normalized_platform = platform_label(platform)
        tags = ["KenRadar", "视频笔记", normalized_platform]
        for topic in topics:
            if topic not in tags:
                tags.append(topic)
            if len(tags) >= 10:
                break
        return tags
