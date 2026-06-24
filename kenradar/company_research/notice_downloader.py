from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from kenradar.company_research.a_stock_data_provider import find_matching_notice
from kenradar.company_research.akshare_provider import Notice, normalize_symbol
from kenradar.company_research.cninfo_provider import CNINFO_HEADERS, find_matching_cninfo_notice, resolve_cninfo_detail
from kenradar.company_research.pdf_validator import PdfValidationResult, validate_pdf

EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.eastmoney.com/notices/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass(frozen=True)
class NoticeDownloadResult:
    notice: Notice
    status: str
    provider: str
    file_path: str = ""
    file_name: str = ""
    download_url: str = ""
    validation: PdfValidationResult | None = None
    error: str = ""
    http_status: int | None = None
    provider_attempts: dict[str, Any] = field(default_factory=dict)


class NoticeDownloader:
    def __init__(self, root_dir: str | Path, *, timeout: int = 60):
        self.root_dir = Path(root_dir)
        self.timeout = timeout
        self.session = requests.Session()

    def download_notice_pdf(self, notice: Notice) -> NoticeDownloadResult:
        attempts: dict[str, Any] = {}

        cninfo_result, cninfo_attempt = self._attempt_cninfo(notice)
        attempts["cninfo"] = cninfo_attempt
        if cninfo_result:
            return _with_attempts(cninfo_result, attempts)

        eastmoney_result, eastmoney_attempt = self._attempt_eastmoney(notice)
        attempts["eastmoney"] = eastmoney_attempt
        if eastmoney_result:
            return _with_attempts(eastmoney_result, attempts)

        a_stock_result, a_stock_attempt = self._attempt_a_stock_data(notice)
        attempts["a_stock_data"] = a_stock_attempt
        if a_stock_result:
            return _with_attempts(a_stock_result, attempts)

        final_status = "all_providers_failed"
        if any(item.get("status") == "invalid_pdf" for item in attempts.values()):
            final_status = "invalid_pdf"
        elif attempts.get("a_stock_data", {}).get("status") == "not_installed":
            final_status = "a_stock_data_not_installed"
        return NoticeDownloadResult(
            notice=notice,
            status=final_status,
            provider="",
            error=_summarize_attempts(attempts),
            provider_attempts=attempts,
        )

    def _attempt_cninfo(self, notice: Notice) -> tuple[NoticeDownloadResult | None, dict[str, Any]]:
        attempt: dict[str, Any] = {"status": "failed", "stage": "match_cninfo_notice"}
        try:
            cninfo_notice = notice if notice.source_provider == "cninfo" or "cninfo.com.cn" in str(notice.notice_url) else find_matching_cninfo_notice(
                notice.symbol,
                notice.title,
                notice.notice_date,
            )
            if not cninfo_notice:
                attempt["reason"] = "cninfo_notice_not_found"
                return None, attempt

            detail = resolve_cninfo_detail(cninfo_notice, session=self.session, timeout=self.timeout)
            attempt.update(
                {
                    "stage": "download_pdf",
                    "detail_url": detail.detail_url,
                    "download_url": detail.pdf_url,
                    "announcement_id": detail.announcement_id,
                    "org_id": detail.org_id,
                }
            )
            result = self._download_pdf(notice, detail.pdf_url, "cninfo")
            attempt.update(_validation_attempt_fields(result))
            return (_with_attempts(result, {"cninfo": attempt}) if result.status == "downloaded" else None), attempt
        except Exception as exc:
            attempt["reason"] = str(exc)
            return None, attempt

    def _attempt_eastmoney(self, notice: Notice) -> tuple[NoticeDownloadResult | None, dict[str, Any]]:
        attempt: dict[str, Any] = {
            "status": "failed",
            "stage": "open_detail_html",
            "detail_url": notice.notice_url,
        }
        try:
            notice_url = str(notice.notice_url or "").strip()
            if not notice_url:
                attempt["reason"] = "eastmoney_notice_url_missing"
                return None, attempt
            if notice_url.lower().endswith(".pdf"):
                result = self._download_pdf(notice, notice_url, "eastmoney")
                attempt.update(_validation_attempt_fields(result))
                return (_with_attempts(result, {"eastmoney": attempt}) if result.status == "downloaded" else None), attempt

            response = self.session.get(notice_url, timeout=self.timeout, headers=EASTMONEY_HEADERS)
            attempt.update(
                {
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type", ""),
                    "html_length": len(response.text or ""),
                }
            )
            html = response.text or ""
            attempt["has_view_pdf_text"] = "查看PDF原文" in html
            attempt["has_pdf_text"] = ".pdf" in html.lower()
            attempt["has_pdf_dfcfw"] = "pdf.dfcfw.com" in html.lower()

            if response.status_code >= 400:
                attempt["reason"] = f"eastmoney_detail_http_{response.status_code}"
                return None, attempt

            direct_url = self._extract_eastmoney_pdf_from_html(html, notice_url)
            if direct_url:
                attempt["stage"] = "download_pdf"
                attempt["download_url"] = direct_url
                result = self._download_pdf(notice, direct_url, "eastmoney")
                attempt.update(_validation_attempt_fields(result))
                return (_with_attempts(result, {"eastmoney": attempt}) if result.status == "downloaded" else None), attempt

            ann_code = self._extract_eastmoney_ann_code(notice_url, html)
            if ann_code:
                attempt["announcement_code"] = ann_code
                api_url = self._resolve_eastmoney_pdf_via_api(ann_code)
                if api_url:
                    attempt["stage"] = "download_pdf"
                    attempt["download_url"] = api_url
                    result = self._download_pdf(notice, api_url, "eastmoney")
                    attempt.update(_validation_attempt_fields(result))
                    return (_with_attempts(result, {"eastmoney": attempt}) if result.status == "downloaded" else None), attempt

            attempt["stage"] = "resolve_pdf_link"
            attempt["reason"] = "eastmoney_pdf_link_not_found" if attempt["has_view_pdf_text"] else "eastmoney_pdf_text_missing"
            return None, attempt
        except Exception as exc:
            attempt["reason"] = str(exc)
            return None, attempt

    def _attempt_a_stock_data(self, notice: Notice) -> tuple[NoticeDownloadResult | None, dict[str, Any]]:
        attempt: dict[str, Any] = {"status": "failed", "stage": "match_a_stock_data"}
        try:
            matched = find_matching_notice(notice.symbol, notice.title, notice.notice_date)
        except RuntimeError as exc:
            message = str(exc)
            if "未安装 a-stock-data" in message or "not installed" in message:
                attempt["status"] = "not_installed"
                attempt["reason"] = "a-stock-data is not installed or not importable"
                return None, attempt
            attempt["reason"] = message
            return None, attempt

        if not matched or not matched.download_url:
            attempt["reason"] = "a_stock_data_notice_not_found"
            return None, attempt

        attempt["download_url"] = matched.download_url
        result = self._download_pdf(notice, matched.download_url, "a_stock_data")
        attempt.update(_validation_attempt_fields(result))
        return (_with_attempts(result, {"a_stock_data": attempt}) if result.status == "downloaded" else None), attempt

    def _extract_eastmoney_pdf_from_html(self, html: str, base_url: str) -> str:
        patterns = [
            r"""href=["']([^"']+\.pdf(?:\?[^"']*)?)["']""",
            r"""(https://pdf\.dfcfw\.com/pdf/H[23]_[^"' ]+\.PDF(?:\?[^"' ]*)?)""",
            r"""["'](https?://[^"']+\.pdf(?:\?[^"']*)?)["']""",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.I)
            if match:
                return urljoin(base_url, match.group(1))
        return ""

    def _extract_eastmoney_ann_code(self, notice_url: str, html: str) -> str:
        for value in (notice_url, html):
            match = re.search(r"(AN\d{18})", value)
            if match:
                return match.group(1)
        return ""

    def _resolve_eastmoney_pdf_via_api(self, ann_code: str) -> str:
        api_url = "https://np-cnotice-stock.eastmoney.com/api/content/ann"
        response = self.session.get(
            api_url,
            params={"cb": "jQuery", "art_code": ann_code, "client_source": "web", "page_index": 1},
            headers=EASTMONEY_HEADERS,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"eastmoney_content_api_http_{response.status_code}")
        payload_text = response.text.strip()
        match = re.match(r"^[^(]+\((.*)\)\s*$", payload_text)
        if not match:
            raise RuntimeError("eastmoney_content_api_jsonp_invalid")
        payload = json.loads(match.group(1))
        data = payload.get("data") or {}
        attach_url = str(data.get("attach_url") or "").strip()
        if attach_url:
            return attach_url
        attach_list = data.get("attach_list") or []
        for item in attach_list:
            url = str((item or {}).get("attach_url") or "").strip()
            if url:
                return url
        return ""

    def _download_pdf(self, notice: Notice, pdf_url: str, provider: str) -> NoticeDownloadResult:
        headers = CNINFO_HEADERS if provider == "cninfo" else EASTMONEY_HEADERS
        response = self.session.get(pdf_url, timeout=self.timeout, headers=headers)
        content_type = str(response.headers.get("content-type") or "")
        if response.status_code >= 400:
            return NoticeDownloadResult(notice=notice, status=f"{provider}_failed", provider=provider, download_url=pdf_url, error=f"HTTP {response.status_code}", http_status=response.status_code)

        rel_dir = self._notice_dir(notice)
        rel_dir.mkdir(parents=True, exist_ok=True)
        file_name = _safe_name(f"{notice.notice_date}_{notice.title}.pdf")
        file_path = rel_dir / file_name
        file_path.write_bytes(response.content)
        validation = validate_pdf(file_path, content_type=content_type)
        status = "downloaded" if validation.ok else "invalid_pdf"
        return NoticeDownloadResult(
            notice=notice,
            status=status,
            provider=provider,
            file_path=str(file_path),
            file_name=file_name,
            download_url=pdf_url,
            validation=validation,
            error=validation.error,
            http_status=response.status_code,
        )

    def _notice_dir(self, notice: Notice) -> Path:
        symbol = normalize_symbol(notice.symbol)
        year = str(notice.notice_date or "unknown")[:4] if notice.notice_date else "unknown"
        stock = _safe_name(f"{symbol}_{notice.stock_name or symbol}")
        return self.root_dir / "company_research" / "downloads" / "announcements" / stock / year


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:180] or "notice.pdf"


def _validation_attempt_fields(result: NoticeDownloadResult) -> dict[str, Any]:
    validation = result.validation
    return {
        "status": "success" if result.status == "downloaded" else result.status,
        "reason": result.error,
        "http_status": result.http_status,
        "file_size": validation.file_size if validation else 0,
        "is_valid_pdf": bool(validation and validation.ok),
        "file_path": result.file_path,
    }


def _with_attempts(result: NoticeDownloadResult, attempts: dict[str, Any]) -> NoticeDownloadResult:
    return NoticeDownloadResult(
        notice=result.notice,
        status=result.status,
        provider=result.provider,
        file_path=result.file_path,
        file_name=result.file_name,
        download_url=result.download_url,
        validation=result.validation,
        error=result.error,
        http_status=result.http_status,
        provider_attempts=attempts,
    )


def _summarize_attempts(attempts: dict[str, Any]) -> str:
    parts = []
    for provider, detail in attempts.items():
        reason = str(detail.get("reason") or detail.get("status") or "failed")
        parts.append(f"{provider}:{reason}")
    return "; ".join(parts)
