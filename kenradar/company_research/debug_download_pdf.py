from __future__ import annotations

import argparse
from pathlib import Path

from kenradar.company_research.akshare_provider import fetch_individual_notices, normalize_symbol
from kenradar.company_research.notice_downloader import NoticeDownloader
from kenradar.core.config import load_config
from kenradar.storage import create_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug company research PDF downloads without NotebookLM.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--begin-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    database = create_database(config)
    downloader = NoticeDownloader(config.data_dir)

    symbol = normalize_symbol(args.symbol)
    notices = fetch_individual_notices(symbol, args.begin_date, args.end_date)[: max(1, args.limit)]
    if not notices:
        print("No notices found")
        return 1

    for index, notice in enumerate(notices, start=1):
        result = downloader.download_notice_pdf(notice)
        validation = result.validation
        database.upsert_company_notice_file(
            symbol=symbol,
            stock_name=notice.stock_name,
            notice_id=notice.notice_id,
            notice_title=notice.title,
            notice_date=notice.notice_date,
            notice_url=notice.notice_url,
            source_provider=result.provider or notice.source_provider,
            download_url=result.download_url,
            file_path=result.file_path,
            file_name=result.file_name,
            file_size=validation.file_size if validation else 0,
            file_hash=validation.file_hash if validation else "",
            is_valid_pdf=bool(validation and validation.ok),
            download_status=result.status,
            provider_attempts_json=result.provider_attempts,
            final_provider=result.provider or notice.source_provider,
            upload_status="pending" if result.status == "downloaded" else "",
            source_id="",
            source_title="",
            local_file_deleted=False,
            local_file_deleted_at="",
            delete_local_error="",
            error_message=result.error,
        )
        print(f"[{index}] {notice.title}")
        print("    provider_attempts:")
        for provider in ("cninfo", "eastmoney", "a_stock_data"):
            detail = result.provider_attempts.get(provider, {})
            status = detail.get("status", "skipped")
            reason = detail.get("reason", "")
            print(f"      {provider}: {status}" + (f" + {reason}" if reason else ""))
        print(f"    final_status: {result.status}")
        print(f"    file_size: {validation.file_size if validation else 0}")
        print(f"    is_valid_pdf: {bool(validation and validation.ok)}")
        print(f"    file_path: {result.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
