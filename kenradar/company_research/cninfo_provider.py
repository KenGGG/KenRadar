from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from kenradar.company_research.akshare_provider import Notice, compact_date, normalize_symbol, security_code

CNINFO_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "http://www.cninfo.com.cn/",
    "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass(frozen=True)
class CninfoDetail:
    pdf_url: str
    detail_url: str
    announcement_id: str
    org_id: str
    title: str
    notice_time: str
    raw: dict[str, Any]


@lru_cache(maxsize=128)
def fetch_cninfo_notices(symbol: str, begin_date: str, end_date: str) -> list[Notice]:
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 AKShare，无法查询巨潮公告") from exc

    normalized = normalize_symbol(symbol)
    code = security_code(normalized)
    frame = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code,
        market="沪深京",
        start_date=compact_date(begin_date),
        end_date=compact_date(end_date),
    )

    notices: list[Notice] = []
    for index, item in enumerate(frame.to_dict("records"), start=1):
        title = str(item.get("公告标题") or item.get("title") or "未命名公告")
        notice_time = str(item.get("公告时间") or item.get("date") or "")
        notice_url = str(item.get("公告链接") or item.get("url") or "")
        notice_id = _announcement_id_from_url(notice_url) or f"{code}-{compact_date(notice_time)}-{index}"
        notices.append(
            Notice(
                symbol=normalized,
                stock_name=str(item.get("简称") or normalized),
                notice_id=notice_id,
                title=title,
                notice_date=notice_time[:10],
                notice_url=notice_url,
                source_provider="cninfo",
            )
        )
    return notices


def find_matching_cninfo_notice(symbol: str, title: str, notice_date: str) -> Notice | None:
    notices = fetch_cninfo_notices(symbol, notice_date[:10], notice_date[:10])
    target = _normalize_notice_title(title)
    if not target:
        return notices[0] if notices else None

    best: Notice | None = None
    best_score = -1
    for item in notices:
        score = _title_match_score(target, _normalize_notice_title(item.title))
        if score > best_score:
            best = item
            best_score = score
    return best if best_score >= 3 else None


def resolve_cninfo_detail(notice: Notice, *, session: requests.Session | None = None, timeout: int = 60) -> CninfoDetail:
    detail_url = str(notice.notice_url or "").strip()
    if detail_url.lower().endswith(".pdf"):
        return CninfoDetail(
            pdf_url=detail_url,
            detail_url=detail_url,
            announcement_id=str(notice.notice_id or ""),
            org_id="",
            title=notice.title,
            notice_time=str(notice.notice_date or ""),
            raw={},
        )

    announcement_id = _announcement_id_from_url(detail_url) or str(notice.notice_id or "")
    announcement_time = _announcement_time_from_url(detail_url) or str(notice.notice_date or "")
    if not announcement_id:
        raise RuntimeError("cninfo_announcement_id_missing")

    request_session = session or requests.Session()
    response = request_session.post(
        "http://www.cninfo.com.cn/new/announcement/bulletin_detail",
        params={
            "announceId": announcement_id,
            "flag": "true",
            "announceTime": _format_cninfo_announce_time(announcement_time),
        },
        headers=CNINFO_HEADERS,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"cninfo_detail_http_{response.status_code}")

    payload = response.json()
    announcement = payload.get("announcement") or {}
    file_url = str(payload.get("fileUrl") or "").strip()
    adjunct_url = str(announcement.get("adjunctUrl") or "").strip()
    if not file_url and adjunct_url:
        if adjunct_url.lower().startswith("http"):
            file_url = adjunct_url
        else:
            file_url = f"http://static.cninfo.com.cn/{adjunct_url.lstrip('/')}"
    if not file_url:
        raise RuntimeError("cninfo_pdf_link_not_found")

    return CninfoDetail(
        pdf_url=file_url,
        detail_url=detail_url,
        announcement_id=str(announcement.get("announcementId") or announcement_id),
        org_id=str(announcement.get("orgId") or ""),
        title=str(announcement.get("announcementTitle") or notice.title),
        notice_time=_notice_time_from_payload(announcement.get("announcementTime"), announcement_time),
        raw=payload,
    )


def _announcement_id_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    announcement_id = query.get("announcementId") or query.get("announceId")
    if announcement_id:
        return str(announcement_id[0])
    match = re.search(r"(AN\d{18})", url)
    return match.group(1) if match else ""


def _announcement_time_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    values = query.get("announcementTime") or query.get("announceTime")
    return str(values[0]) if values else ""


def _format_cninfo_announce_time(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) == 10:
        return f"{raw} 00:00:00"
    return raw.replace("T", " ")[:19]


def _notice_time_from_payload(value: Any, fallback: str) -> str:
    if isinstance(value, (int, float)) and int(value) > 0:
        return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return _format_cninfo_announce_time(str(fallback or ""))


def _normalize_notice_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[^:：]{1,40}[:：]", "", text)
    text = re.sub(r"^\d{4}-\d{2,4}[：:]", "", text)
    text = re.sub(r"[（）()《》“”\"'·•,\-—_:：\s]+", "", text)
    return text.lower()


def _title_match_score(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if left == right:
        return 100
    if left in right or right in left:
        return min(len(left), len(right))
    overlap = set(_ngrams(left, 3)) & set(_ngrams(right, 3))
    return len(overlap)


def _ngrams(value: str, size: int) -> list[str]:
    if len(value) <= size:
        return [value] if value else []
    return [value[index : index + size] for index in range(0, len(value) - size + 1)]
