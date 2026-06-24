from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class StockInfo:
    symbol: str
    name: str


@dataclass(frozen=True)
class Notice:
    symbol: str
    stock_name: str
    notice_id: str
    title: str
    notice_date: str
    notice_url: str
    notice_type: str = "全部"
    source_provider: str = "akshare"


def normalize_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    match = re.search(r"(\d{6})(?:\.(SH|SZ|BJ))?", raw)
    if not match:
        raise ValueError(f"无效股票代码: {symbol}")
    code = match.group(1)
    suffix = match.group(2)
    if suffix:
        return f"{code}.{suffix}"
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code


def security_code(symbol: str) -> str:
    return normalize_symbol(symbol).split(".", 1)[0]


def compact_date(value: str | date) -> str:
    return str(value).replace("-", "")[:8]


def fetch_all_stocks(limit: int = 0) -> list[StockInfo]:
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 AKShare，无法获取股票列表") from exc
    frame = ak.stock_info_a_code_name()
    rows: list[StockInfo] = []
    for item in frame.to_dict("records"):
        code = str(item.get("code") or item.get("证券代码") or "").strip()
        name = str(item.get("name") or item.get("证券简称") or "").strip()
        if not code:
            continue
        rows.append(StockInfo(normalize_symbol(code), name or code))
        if limit and len(rows) >= limit:
            break
    return rows


def fetch_stock_info(symbol: str) -> StockInfo:
    normalized = normalize_symbol(symbol)
    code = security_code(normalized)
    try:
        for item in fetch_all_stocks():
            if security_code(item.symbol) == code:
                return StockInfo(normalized, item.name)
    except Exception:
        pass
    return StockInfo(normalized, normalized)


def fetch_individual_notices(symbol: str, begin_date: str, end_date: str, notice_type: str = "全部") -> list[Notice]:
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 AKShare，无法查询公告索引") from exc
    info = fetch_stock_info(symbol)
    frame = ak.stock_individual_notice_report(
        security=security_code(info.symbol),
        symbol=notice_type or "全部",
        begin_date=compact_date(begin_date),
        end_date=compact_date(end_date),
    )
    notices: list[Notice] = []
    for index, item in enumerate(frame.to_dict("records"), start=1):
        title = _first(item, "公告标题", "title", "notice_title", "标题")
        notice_date = _first(item, "公告日期", "date", "notice_date", "日期")
        notice_url = _first(item, "公告链接", "公告网址", "网址", "url", "notice_url")
        notice_kind = _first(item, "公告类型", "type", "notice_type") or notice_type
        if not title and not notice_url:
            continue
        notice_id = _first(item, "公告代码", "notice_id", "id") or f"{security_code(info.symbol)}-{compact_date(str(notice_date))}-{index}"
        notices.append(
            Notice(
                symbol=info.symbol,
                stock_name=info.name,
                notice_id=str(notice_id),
                title=str(title or "未命名公告"),
                notice_date=str(notice_date or ""),
                notice_url=str(notice_url or ""),
                notice_type=str(notice_kind or "全部"),
            )
        )
    return notices


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None
