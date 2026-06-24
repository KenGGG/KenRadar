"""财务分析报告选择器。

从公告列表中自动选择近三年年度报告和最新一期定期报告。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import logging

from kenradar.company_research.akshare_provider import (
    Notice,
    fetch_individual_notices,
    fetch_stock_info,
    normalize_symbol,
)

logger = logging.getLogger(__name__)

# ── 排除关键词（包含以下任一关键词的公告不作为完整报告） ─────
EXCLUDE_KEYWORDS = [
    "摘要",
    "英文版",
    "英文版本",
    "取消",
    "提示性公告",
    "提示",
    "关于",
    "更正",
    "补充",
    "修订",
    "撤回",
    "延期",
]

# ── 报告期识别模式（按顺序匹配） ────────────────────────────
REPORT_PATTERNS: list[tuple[str, str, Any]] = [
    (r"(\d{4})\s*年\s*年度报告", "annual", lambda y: date(y, 12, 31)),
    (r"(\d{4})\s*年\s*半年度报告", "half", lambda y: date(y, 6, 30)),
    (r"(\d{4})\s*年\s*一季度报告", "q1", lambda y: date(y, 3, 31)),
    (r"(\d{4})\s*年\s*第一季度报告", "q1", lambda y: date(y, 3, 31)),
    (r"(\d{4})\s*年\s*三季度报告", "q3", lambda y: date(y, 9, 30)),
    (r"(\d{4})\s*年\s*第三季度报告", "q3", lambda y: date(y, 9, 30)),
    (r"(\d{4})\s*年度报告", "annual", lambda y: date(y, 12, 31)),
]

# ── 修订版识别关键词 ───────────────────────────────────────
REVISION_KEYWORDS = ["修订", "更正", "更新", "更正后"]

# ── 报告类型映射 ────────────────────────────────────────────
PERIOD_TO_TYPE = {
    "annual": "annual_report",
    "half": "semi_annual_report",
    "q1": "quarterly_report",
    "q3": "quarterly_report",
}

PERIOD_LABEL = {
    "annual": "年度",
    "half": "半年度",
    "q1": "Q1",
    "q3": "Q3",
}


# ═══════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════


@dataclass
class ParsedNotice:
    """从公告标题和日期中解析出的结构化信息。"""

    # 原始信息
    symbol: str
    stock_name: str
    notice_id: str
    notice_title: str
    notice_date: date
    notice_url: str

    # 解析字段
    report_year: int | None = None
    report_period: str | None = None  # 'annual' | 'q1' | 'half' | 'q3'
    report_period_end: date | None = None
    is_full_report: bool = True
    is_revised: bool = False
    original_title: str = ""


@dataclass
class FinancialReportSelection:
    """报告选择结果。"""

    symbol: str
    stock_name: str
    analysis_base_year: int
    selected_notices: list[ParsedNotice] = field(default_factory=list)
    missing_reports: list[str] = field(default_factory=list)
    annual_reports_found: dict[int, ParsedNotice] = field(default_factory=dict)
    periodic_report: ParsedNotice | None = None
    total_selected: int = 0
    over_limit: bool = False
    all_notices_count: int = 0


# ═══════════════════════════════════════════════════════════════
# 核心解析函数
# ═══════════════════════════════════════════════════════════════


def parse_notice_title(notice: Notice) -> ParsedNotice:
    """从公告标题解析报告信息。

    解析步骤：
    1. 判断是否为完整报告（排除摘要/英文版等）
    2. 提取报告年份
    3. 判断报告期类型
    4. 判断是否为修订版
    5. 计算 report_period_end
    """
    title = (notice.title or "").strip()
    try:
        notice_date = (
            date.fromisoformat(notice.notice_date)
            if notice.notice_date
            else date.today()
        )
    except (ValueError, TypeError):
        notice_date = date.today()

    parsed = ParsedNotice(
        symbol=notice.symbol,
        stock_name=notice.stock_name,
        notice_id=notice.notice_id,
        notice_title=title,
        notice_date=notice_date,
        notice_url=notice.notice_url,
        original_title=title,
    )

    # Step 1: 判断是否为完整报告
    parsed.is_full_report = _is_full_report(title)

    # Step 2-5: 匹配报告期模式
    for pattern, period, end_fn in REPORT_PATTERNS:
        match = re.search(pattern, title)
        if match:
            year = int(match.group(1))
            parsed.report_year = year
            parsed.report_period = period
            parsed.report_period_end = end_fn(year)
            break

    # 判断是否为修订版
    parsed.is_revised = any(kw in title for kw in REVISION_KEYWORDS)

    return parsed


def _is_full_report(title: str) -> bool:
    """判断公告标题是否为完整报告。

    规则：
    - 如果标题匹配 REPORT_PATTERNS（是正式年报/季报）：
      - 含"摘要"/"英文版"/"取消"/"提示" → 排除（不是完整报告）
      - 含"更正"/"修订"/"补充" → 保留（标记为修订版，is_revised=True 由调用方负责）
      - 其他 → 保留
    - 如果标题不匹配 REPORT_PATTERNS：直接排除
    """
    # 先检查是否匹配报告模式
    is_report = False
    for pattern, _, _ in REPORT_PATTERNS:
        if re.search(pattern, title):
            is_report = True
            break
    if not is_report:
        return False

    # 匹配报告模式的标题，检查是否包含绝对排除词
    ABSOLUTE_EXCLUDE = ["摘要", "英文版", "英文版本", "取消", "提示性公告", "提示"]
    for kw in ABSOLUTE_EXCLUDE:
        if kw in title:
            return False
    return True


def _derive_annual_years(analysis_base_year: int) -> list[int]:
    """根据分析基准年份推导最近三年年报年份。

    例: analysis_base_year=2026 → [2023, 2024, 2025]
    """
    return [
        analysis_base_year - 3,
        analysis_base_year - 2,
        analysis_base_year - 1,
    ]


def select_latest_periodic_report(
    parsed_notices: list[ParsedNotice],
    latest_annual_year: int,
    analysis_base_year: int,
) -> ParsedNotice | None:
    """选择最新一期定期报告（不是关键词优先级，而是按报告期截止日）。

    选择条件：
    1. report_period_end > 最近年报的 report_period_end（年报年份的 12-31）
    2. 且 report_period_end <= analysis_base_year 当年
    3. 是完整报告
    4. 按 report_period_end 降序 → 取最大
    5. 如果 report_period_end 相同，按 notice_date 最新
    """
    candidates = []
    latest_annual_end = date(latest_annual_year, 12, 31)
    base_year_end = date(analysis_base_year, 12, 31)

    for pn in parsed_notices:
        if not pn.is_full_report:
            continue
        if pn.report_period in ("annual", None):
            continue  # 只选定期报告（季报/半年报），排除年报
        if pn.report_period_end is None:
            continue
        if not (latest_annual_end < pn.report_period_end <= base_year_end):
            continue
        candidates.append(pn)

    if not candidates:
        return None

    # 按 report_period_end 降序，同日期按 notice_date 最新
    candidates.sort(
        key=lambda p: (p.report_period_end or date.min, p.notice_date),
        reverse=True,
    )
    return candidates[0]


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


class FinancialReportSelector:
    """财务分析报告选择器。"""

    def select(
        self,
        symbol: str,
        analysis_base_year: int | None = None,
        begin_date: str | None = None,
        end_date: str | None = None,
        max_pdfs: int = 10,
    ) -> FinancialReportSelection:
        """选择财务分析需要的报告文件。

        Args:
            symbol: 股票代码。
            analysis_base_year: 分析基准年份，默认当前年份。
            begin_date: 公告查询开始日期，默认往前 4 年。
            end_date: 公告查询结束日期，默认今天。
            max_pdfs: 最大允许 PDF 数量。

        Returns:
            FinancialReportSelection: 选择结果。
        """
        if analysis_base_year is None:
            analysis_base_year = date.today().year

        today = date.today()
        if end_date is None:
            end_date = today.isoformat()
        if begin_date is None:
            # 往前 4 年确保覆盖到最早的目标年报
            begin_date = date(analysis_base_year - 4, 1, 1).isoformat()

        # 标准化股票代码
        symbol = normalize_symbol(symbol)

        # 获取股票名称
        try:
            stock_info = fetch_stock_info(symbol)
            stock_name = stock_info.name
        except Exception:
            stock_name = symbol

        # 获取公告列表
        logger.info(
            "查询公告列表: symbol=%s begin=%s end=%s", symbol, begin_date, end_date
        )
        try:
            notices = fetch_individual_notices(symbol, begin_date, end_date, "全部")
        except Exception as exc:
            logger.error("查询公告列表失败: symbol=%s error=%s", symbol, exc)
            # 返回空结果
            return FinancialReportSelection(
                symbol=symbol,
                stock_name=stock_name,
                analysis_base_year=analysis_base_year,
                missing_reports=[
                    f"公告列表查询失败: {exc}",
                ],
            )

        result = FinancialReportSelection(
            symbol=symbol,
            stock_name=stock_name,
            analysis_base_year=analysis_base_year,
            all_notices_count=len(notices),
        )

        # 解析所有公告
        parsed_all = [parse_notice_title(n) for n in notices]

        # ── 匹配年报 ──
        target_years = _derive_annual_years(analysis_base_year)
        for year in target_years:
            candidates = [
                pn
                for pn in parsed_all
                if pn.report_year == year
                and pn.report_period == "annual"
                and pn.is_full_report
            ]
            if not candidates:
                result.missing_reports.append(f"{year}年年度报告")
                continue

            # 同一年份有多个匹配（修订版>原版），按 is_revised 降序 + notice_date 最新
            candidates.sort(
                key=lambda p: (p.is_revised, p.notice_date),
                reverse=True,
            )
            best = candidates[0]
            result.annual_reports_found[year] = best
            result.selected_notices.append(best)

        # ── 匹配最新一期定期报告 ──
        if result.annual_reports_found:
            latest_annual_year = max(result.annual_reports_found.keys())
            periodic = select_latest_periodic_report(
                parsed_all, latest_annual_year, analysis_base_year
            )
            if periodic:
                result.periodic_report = periodic
                result.selected_notices.append(periodic)
            else:
                result.missing_reports.append(
                    f"{latest_annual_year + 1}年最新一期定期报告"
                )

        result.total_selected = len(result.selected_notices)

        # ── 数量检查 ──
        if result.total_selected > max_pdfs:
            result.over_limit = True
            logger.warning(
                "选中报告数量 %d 超过上限 %d，请人工检查",
                result.total_selected,
                max_pdfs,
            )

        return result
