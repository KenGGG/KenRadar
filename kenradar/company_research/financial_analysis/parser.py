"""JSON 解析器 — 从 Q11 回答中提取 <FINANCIAL_JSON> 标签包裹的结构化数据。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

FINANCIAL_JSON_PATTERN = re.compile(
    r"<FINANCIAL_JSON>\s*([\s\S]*?)\s*</FINANCIAL_JSON>", re.DOTALL
)


def extract_from_financial_json_tags(markdown_text: str) -> dict[str, Any] | None:
    """从 Q11 回答的 Markdown 中提取 <FINANCIAL_JSON> 标签包裹的 JSON。

    Args:
        markdown_text: Q11 的完整回答（Markdown 文本）。

    Returns:
        解析成功的 dict，或 None（标签未找到或 JSON 解析失败）。
    """
    if not markdown_text:
        return None

    match = FINANCIAL_JSON_PATTERN.search(markdown_text)
    if not match:
        logger.warning("未找到 <FINANCIAL_JSON> 标签")
        return None

    json_str = match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("JSON 解析失败: %s", exc)
        return None


def try_parse_with_fallback(
    markdown_text: str, raw_answer: str
) -> dict[str, Any]:
    """尝试解析 JSON，失败时返回带 fallback 标记的空结构。

    此函数始终返回一个包含 score_source 字段的字典，
    无论解析是否成功。

    Args:
        markdown_text: Q11 回答 Markdown。
        raw_answer: 原始 API 回答。

    Returns:
        字典，包含 score_source='ai_generated' 或 'fallback'。
    """
    result = extract_from_financial_json_tags(markdown_text)

    if result is not None:
        result["score_source"] = "ai_generated"
        result["_parse_error"] = False
        return result

    return {
        "symbol": "",
        "company_name": "",
        "analysis_period": "",
        "financial_risk_score": None,
        "financial_risk_tier": None,
        "first_repayment_source": "",
        "leasing_advice": "",
        "major_red_flags": [],
        "score_detail": {},
        "red_flags": [],
        "required_follow_up_materials": [],
        "score_source": "fallback",
        "_parse_error": True,
        "_raw_answer_saved": True,
    }


def extract_red_flags(report_json: dict[str, Any]) -> list[dict[str, Any]]:
    """从解析后的 JSON 中提取红旗列表。"""
    return report_json.get("red_flags", [])


def extract_score_detail(
    report_json: dict[str, Any],
) -> dict[str, Any]:
    """从解析后的 JSON 中提取 7 维度评分明细。"""
    return report_json.get("score_detail", {})


class FinancialReportParser:
    """财务报告 JSON 解析器。"""

    def parse(self, markdown_text: str, raw_answer: str) -> dict[str, Any]:
        """解析 Q11 回答，返回结构化数据。"""
        return try_parse_with_fallback(markdown_text, raw_answer)
