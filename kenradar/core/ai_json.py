from __future__ import annotations

import json
import re
from typing import Any


def parse_ai_json(value: str) -> dict[str, Any] | None:
    """Parse model JSON even when it is wrapped in fences or prose."""
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = _loads_or_none(text)
    if data is None:
        data = _parse_loose_json(text)
    if isinstance(data, str):
        nested = data.strip()
        if nested.startswith("{") and nested.endswith("}"):
            data = _loads_or_none(nested)
    return data if isinstance(data, dict) else None


def fallback_analysis(value: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:\w+)?\s*", "", str(value or "").strip())
    text = re.sub(r"\s*```$", "", text)
    if not text:
        return {}
    lines = []
    for line in text.splitlines():
        clean = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip(" -•\t`")
        if clean:
            lines.append(clean)
    if not lines:
        return {}
    summary = limit_plain_text(lines[0], 180)
    body = limit_plain_text(" ".join(lines[1:]) or summary, 250)
    scores = fallback_scores_from_text(text)
    topics = infer_topics(text)
    return {
        "brief_title": "",
        "brief_summary": summary,
        "content_sections": [{"title": "系统基础整理", "content": body}],
        "corrected_transcript_sections": [],
        "content_category": topics[0] if topics else "",
        "keywords": topics[:8],
        "tags": topics[:5] or ["投资策略"],
        "importance_score": scores["importance_score"],
        "novelty_score": scores["novelty_score"],
        "information_density": scores["information_density"],
        "business_relevance": scores["business_relevance"],
        "value_score": scores["value_score"],
        "recommended_action": scores["recommended_action"],
        "recommendation_reason": "AI 返回非 JSON，系统按可读摘要保守评估",
        "deep_research_suggested": scores["value_score"] >= 4.2,
    }


def fallback_scores_from_text(text: str) -> dict[str, Any]:
    value = str(text or "")
    information_density = 3.0
    business_relevance = 3.0
    novelty_score = 3.0
    importance_score = 3.0
    if len(value) > 1200 or len(re.findall(r"\d+(?:\.\d+)?%?", value)) >= 5:
        information_density = 3.5
    if any(word in value for word in ["投资", "配置", "估值", "业绩", "需求", "供给", "ROE", "公司", "板块", "行业"]):
        business_relevance = 3.5
    if any(word in value for word in ["AI", "算力", "半导体", "芯片", "新能源", "电力", "券商", "有色", "创新药", "港股", "A股"]):
        importance_score = 3.5
    if any(word in value for word in ["拐点", "超预期", "周期", "催化", "新高", "反转", "爆发", "国产化"]):
        novelty_score = 3.5
    value_score = round((importance_score + novelty_score + information_density + business_relevance) / 4, 1)
    return {
        "importance_score": importance_score,
        "novelty_score": novelty_score,
        "information_density": information_density,
        "business_relevance": business_relevance,
        "value_score": value_score,
        "recommended_action": "research" if value_score >= 4.2 else ("review" if value_score >= 3.0 else "archive"),
    }


def infer_topics(text: str) -> list[str]:
    rules = [
        ("AI", "AI产业"),
        ("人工智能", "AI产业"),
        ("算力", "算力中心"),
        ("半导体", "半导体"),
        ("芯片", "半导体"),
        ("港股", "港股市场"),
        ("A股", "股票市场"),
        ("股票", "股票市场"),
        ("券商", "证券行业"),
        ("有色", "有色金属"),
        ("电力", "电力行业"),
        ("新能源", "新能源"),
        ("电池", "新能源"),
        ("储能", "新能源"),
        ("策略", "投资策略"),
        ("配置", "资产配置"),
    ]
    topics: list[str] = []
    for keyword, topic in rules:
        if keyword in text and topic not in topics:
            topics.append(topic)
    return topics


def limit_plain_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ，。,.；;") + "。"


def _loads_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_loose_json(text: str) -> Any:
    candidate = _first_json_object(text)
    if not candidate:
        return None
    repaired_missing_section_object = re.sub(
        r'(\n\s*},\s*\n)(\s*)("title"\s*:)',
        r'\1\2{\n\2  \3',
        candidate,
    )
    repaired_nested_section_array = re.sub(
        r'(\n\s*},\s*\n)\s*"content_sections"\s*:\s*\[\s*\n',
        r'\1',
        candidate,
        count=1,
    )
    if repaired_nested_section_array != candidate:
        repaired_nested_section_array = re.sub(r"\n\s*\]\s*\n\}\s*$", "\n}", repaired_nested_section_array)
        repaired_nested_section_array = re.sub(r"\n\s{2}\}\s*\n\}\s*$", "\n}", repaired_nested_section_array)
    repairs = [
        candidate,
        repaired_missing_section_object,
        repaired_nested_section_array,
        re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)"', r'\1"\2"', candidate),
        re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', candidate),
    ]
    seen: set[str] = set()
    for repaired in repairs:
        if repaired in seen:
            continue
        seen.add(repaired)
        data = _loads_or_none(repaired)
        if data is not None:
            return data
    return None


def _first_json_object(text: str) -> str:
    value = str(text or "")
    start = value.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(value)):
            char = value[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return value[start : index + 1]
        start = value.find("{", start + 1)
    return ""
