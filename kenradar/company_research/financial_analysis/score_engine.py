"""评分引擎 — 7 维度财务风险评分 + 兜底计算。"""
from __future__ import annotations

from typing import Any

# 7 维度评分配置
SCORE_DIMENSIONS: list[dict[str, Any]] = [
    {"key": "revenue_quality", "label": "收入与回款质量", "max": 15},
    {"key": "profit_quality", "label": "利润质量", "max": 15},
    {"key": "cashflow_quality", "label": "现金流质量", "max": 20},
    {"key": "asset_quality", "label": "资产质量", "max": 15},
    {"key": "debt_liquidity", "label": "债务与流动性", "max": 15},
    {"key": "related_party_funds", "label": "关联交易、担保和资金占用", "max": 10},
    {"key": "audit_internal_control", "label": "审计、内控和信息披露质量", "max": 10},
]

# 兜底评分权重
FALLBACK_WEIGHTS = {"高": 15, "中": 8, "低": 3}

# 评分层级
TIERS: list[tuple[int, str, str]] = [
    (15, "A", "财务质量较好，暂无明显红旗"),
    (35, "B", "存在一般性波动，解释基本充分"),
    (55, "C", "存在若干风险信号，需要补充核查"),
    (75, "D", "存在重大财务隐患"),
    (100, "E", "存在严重财务真实性疑点或偿债压力"),
]


class FinancialScoreEngine:
    """财务风险评分引擎。"""

    def compute_from_json(self, score_detail: dict[str, Any]) -> int:
        """从 JSON 的 score_detail 计算总分。

        Args:
            score_detail: {'revenue_quality': {'score': 3, 'max': 15, ...}, ...}

        Returns:
            总分（0-100）。
        """
        total = 0
        for dim in SCORE_DIMENSIONS:
            key = dim["key"]
            detail = score_detail.get(key, {})
            score = detail.get("score", 0)
            if isinstance(score, (int, float)):
                total += int(score)
        return min(total, 100)

    def fallback_score(self, red_flags: list[dict[str, Any]]) -> int:
        """当 JSON 解析失败时，根据红旗计算兜底分数。

        高危红旗 × 15 + 中危红旗 × 8 + 低危红旗 × 3，上限 100。

        Args:
            red_flags: [{'risk_level': '高', ...}, ...]

        Returns:
            兜底总分（0-100）。
        """
        total = 0
        for flag in red_flags:
            level = flag.get("risk_level", "低")
            total += FALLBACK_WEIGHTS.get(level, 3)
        return min(total, 100)

    def tier_from_score(self, score: int) -> tuple[str, str]:
        """根据分数返回风险层级和描述。

        Returns:
            (层级字母, 层级描述)
        """
        for threshold, tier, desc in TIERS:
            if score <= threshold:
                return (tier, desc)
        return ("E", TIERS[-1][2])

    def needs_human_review(self, score_detail: dict[str, Any]) -> list[str]:
        """检查各维度是否需要人工复核。

        Returns:
            需要复核的维度名称列表。
        """
        needs = []
        for dim in SCORE_DIMENSIONS:
            key = dim["key"]
            detail = score_detail.get(key, {})
            if detail.get("review_required"):
                needs.append(dim["label"])
        return needs

    def compute_and_tier(
        self, score_detail: dict[str, Any]
    ) -> dict[str, Any]:
        """从 score_detail 计算总分并确定层级。

        Returns:
            {'score': int, 'tier': str, 'tier_description': str,
             'dimensions': list[dict], 'needs_review': list[str]}
        """
        total = self.compute_from_json(score_detail)
        tier, tier_desc = self.tier_from_score(total)
        needs_review = self.needs_human_review(score_detail)

        dims = []
        for dim in SCORE_DIMENSIONS:
            key = dim["key"]
            detail = score_detail.get(key, {})
            dims.append({
                "key": key,
                "label": dim["label"],
                "max": dim["max"],
                "score": detail.get("score", 0),
                "evidence": detail.get("evidence", ""),
                "explanation": detail.get("explanation", ""),
                "review_required": detail.get("review_required", False),
            })

        return {
            "score": total,
            "tier": tier,
            "tier_description": tier_desc,
            "dimensions": dims,
            "needs_review": needs_review,
        }
