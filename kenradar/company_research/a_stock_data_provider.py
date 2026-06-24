from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AStockNotice:
    title: str
    notice_date: str
    download_url: str


def search_announcements(symbol: str, begin_date: str, end_date: str) -> list[AStockNotice]:
    try:
        from a_stock_data import announcements  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 a-stock-data，无法执行公告备用查询") from exc
    rows = announcements.search(symbol=symbol, begin_date=begin_date, end_date=end_date)
    return [
        AStockNotice(
            title=str(item.get("title") or ""),
            notice_date=str(item.get("date") or item.get("notice_date") or ""),
            download_url=str(item.get("download_url") or item.get("url") or ""),
        )
        for item in rows
    ]


def find_matching_notice(symbol: str, title: str, notice_date: str) -> AStockNotice | None:
    for item in search_announcements(symbol, notice_date, notice_date):
        if item.title == title or (title and title in item.title):
            return item
    return None
