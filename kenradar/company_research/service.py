from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from kenradar.company_research.akshare_provider import (
    StockInfo,
    fetch_all_stocks,
    fetch_individual_notices,
    fetch_stock_info,
    normalize_symbol,
)
from kenradar.company_research.notebooklm_client import NotebookLMClient
from kenradar.company_research.notice_downloader import NoticeDownloader
from kenradar.company_research.prompts import COMPANY_RESEARCH_QUESTIONS
from kenradar.core.config import AppConfig
from kenradar.storage import create_database

logger = logging.getLogger(__name__)


class CompanyResearchService:
    def __init__(self, config: AppConfig, database: Any | None = None, notebook_client: NotebookLMClient | None = None):
        self.config = config
        self.database = database or create_database(config)
        self.notebook_client = notebook_client or NotebookLMClient()
        self.downloader = NoticeDownloader(config.data_dir)

    def default_request(self) -> dict[str, Any]:
        today = date.today()
        return {
            "begin_date": (today - timedelta(days=365 * 3)).isoformat(),
            "end_date": today.isoformat(),
            "stock_scope": "manual",
            "max_stocks": 1,
            "symbols": ["300750.SZ"],
            "notice_type": "全部",
            "execution_mode": "full",
            "auto_delete_notebook": True,
        }

    def preview_tasks(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_request(request)
        stocks = self._resolve_stocks(normalized)
        return {
            "ok": True,
            "estimated_stocks": len(stocks),
            "estimated_questions": len(stocks) * len(COMPANY_RESEARCH_QUESTIONS),
            "estimated_pdf_count": None,
            "begin_date": normalized["begin_date"],
            "end_date": normalized["end_date"],
            "notice_type": normalized["notice_type"],
            "execution_mode": normalized["execution_mode"],
            "stocks": [asdict(stock) for stock in stocks],
        }

    def create_tasks(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_request(request)
        stocks = self._resolve_stocks(normalized)
        batch_id = f"company-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.database.create_company_research_batch(
            batch_id=batch_id,
            begin_date=normalized["begin_date"],
            end_date=normalized["end_date"],
            max_stocks=normalized["max_stocks"],
            stock_scope=normalized["stock_scope"],
            notice_type=normalized["notice_type"],
            execution_mode=normalized["execution_mode"],
            total_stocks=len(stocks),
            status="queued",
        )
        jobs = []
        for stock in stocks:
            job = self.database.create_company_research_job(
                batch_id=batch_id,
                symbol=stock.symbol,
                stock_name=stock.name,
                begin_date=normalized["begin_date"],
                end_date=normalized["end_date"],
                notice_type=normalized["notice_type"],
                execution_mode=normalized["execution_mode"],
                max_stocks=normalized["max_stocks"],
                auto_delete_notebook=normalized["auto_delete_notebook"],
            )
            jobs.append(job)
        return {"ok": True, "batch_id": batch_id, "jobs": jobs, "total_stocks": len(jobs)}

    async def run_batch(self, batch_id: str, *, progress_callback: Any = None) -> dict[str, Any]:
        batch = self.database.get_company_research_batch(batch_id)
        if not batch:
            raise ValueError(f"未找到公司研究批次: {batch_id}")
        self.database.update_company_research_batch(batch_id, status="running")
        jobs = self.database.list_company_research_jobs(batch_id=batch_id, limit=500)
        completed = 0
        failed = 0
        results: list[dict[str, Any]] = []
        for job in jobs:
            try:
                result = await self.run_job(int(job["id"]), progress_callback=progress_callback)
                results.append(result)
                if str(result.get("status") or "").startswith("completed"):
                    completed += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                self.database.update_company_research_job(
                    int(job["id"]),
                    status="failed",
                    current_stage="failed",
                    last_error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                logger.exception("公司研究任务失败: job_id=%s", job.get("id"))
                results.append({"job_id": job.get("id"), "status": "failed", "error": str(exc)})
        status = "completed" if failed == 0 else ("partial_failed" if completed else "failed")
        self.database.update_company_research_batch(
            batch_id,
            status=status,
            completed_stocks=completed,
            failed_stocks=failed,
        )
        await self.notebook_client.close()
        return {"ok": failed == 0, "batch_id": batch_id, "status": status, "completed": completed, "failed": failed, "results": results}

    async def run_job(self, job_id: int, *, progress_callback: Any = None) -> dict[str, Any]:
        job = self.database.get_company_research_job(job_id)
        if not job:
            raise ValueError(f"未找到公司研究任务: {job_id}")
        symbol = normalize_symbol(str(job["symbol"]))
        stock_name = str(job.get("stock_name") or symbol)
        begin_date = str(job["begin_date"])
        end_date = str(job["end_date"])
        notice_type = str(job.get("notice_type") or "全部")
        execution_mode = str(job.get("execution_mode") or "full")
        auto_delete = bool(job.get("auto_delete_notebook", True))
        total_questions = len(COMPANY_RESEARCH_QUESTIONS)

        await self._stage(job_id, "fetch_notice_index", "downloading", 5, progress_callback)
        notices = fetch_individual_notices(symbol, begin_date, end_date, notice_type)
        self.database.update_company_research_job(job_id, notice_total=len(notices), stock_name=stock_name)
        if not notices:
            raise RuntimeError("未查询到公告索引")

        await self._stage(job_id, "download_pdfs_by_akshare", "downloading", 10, progress_callback)
        downloaded: list[dict[str, Any]] = []
        pdf_failed = 0
        for notice in notices:
            result = self.downloader.download_notice_pdf(notice)
            validation = result.validation
            self.database.upsert_company_notice_file(
                symbol=symbol,
                stock_name=stock_name,
                notice_id=result.notice.notice_id,
                notice_title=result.notice.title,
                notice_date=result.notice.notice_date,
                notice_url=result.notice.notice_url,
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
            if result.status == "downloaded" and result.file_path:
                downloaded.append({"path": result.file_path, "notice": result.notice})
            else:
                pdf_failed += 1
            self.database.update_company_research_job(job_id, pdf_downloaded=len(downloaded), pdf_failed=pdf_failed)
        if not downloaded:
            raise RuntimeError("公告 PDF 全部下载失败")

        # Sort notices by date descending, respect source limit
        downloaded.sort(key=lambda x: x["notice"].notice_date, reverse=True)
        max_sources = 100
        if len(downloaded) > max_sources:
            logger.info("PDF 数量超过 NotebookLM 来源限制: %d → %d", len(downloaded), max_sources)
            downloaded = downloaded[:max_sources]

        if execution_mode == "download_only":
            self.database.update_company_research_job(
                job_id,
                status="completed",
                current_stage="downloaded",
                progress_percent=100,
                finished_at=datetime.now().isoformat(),
            )
            return {"ok": True, "job_id": job_id, "status": "completed", "pdf_downloaded": len(downloaded)}

        await self._stage(job_id, "create_notebook", "uploading", 35, progress_callback)
        notebook_title = f"公司研究_临时_{symbol}_{stock_name}_{begin_date.replace('-', '')}_{end_date.replace('-', '')}"
        notebook = await self.notebook_client.create_notebook(notebook_title)
        notebook_id = str(notebook.get("id") or "")
        if not notebook_id:
            raise RuntimeError("NotebookLM 创建成功但未返回 notebook_id")
        self.database.upsert_company_notebook(symbol, stock_name, notebook_id, notebook_title, "created")
        self.database.update_company_research_job(job_id, notebook_id=notebook_id)

        # Upload PDFs in batches of 10, waiting for each batch to be ready
        await self._stage(job_id, "upload_pdfs", "uploading", 45, progress_callback)
        upload_records: list[dict[str, Any]] = []
        all_source_ids: list[str] = []
        all_ready_count = 0
        BATCH_SIZE = 10

        for batch_start in range(0, len(downloaded), BATCH_SIZE):
            batch = downloaded[batch_start:batch_start + BATCH_SIZE]
            batch_source_ids: list[str] = []

            for item in batch:
                path = str(item["path"])
                notice = item["notice"]
                try:
                    source = await self.notebook_client.upload_pdf(notebook_id, path, Path(path).name)
                    batch_source_ids.append(source.source_id)
                    upload_records.append({"path": path, "notice": notice, "source": source})
                    self.database.update_company_notice_file_upload(
                        symbol=symbol,
                        notice_id=str(notice.notice_id),
                        upload_status="uploaded",
                        source_id=source.source_id,
                        source_title=source.title,
                    )
                except Exception as exc:
                    logger.warning("上传 PDF 失败: symbol=%s notice_id=%s error=%s", symbol, notice.notice_id, exc)
                    self.database.update_company_notice_file_upload(
                        symbol=symbol,
                        notice_id=str(notice.notice_id),
                        upload_status="failed",
                        source_id="",
                        source_title="",
                        error_message=str(exc),
                    )

            all_source_ids.extend(batch_source_ids)
            self.database.update_company_research_job(job_id, source_uploaded=len(all_source_ids))
            self.database.update_company_notebook_counts(
                notebook_id, source_count=len(all_source_ids), ready_source_count=all_ready_count,
            )

            if batch_source_ids:
                batch_ready = await self.notebook_client.wait_sources_ready(notebook_id, batch_source_ids)
                batch_ready_count = sum(1 for s in batch_ready if s.status == "ready")
                all_ready_count += batch_ready_count
                batch_ready_by_id = {s.source_id: s for s in batch_ready}

                for item in batch:
                    notice = item["notice"]
                    record = next(
                        (r for r in upload_records if r["notice"].notice_id == notice.notice_id),
                        None,
                    )
                    if not record:
                        continue
                    s = batch_ready_by_id.get(record["source"].source_id, record["source"])
                    self.database.update_company_notice_file_upload(
                        symbol=symbol,
                        notice_id=str(notice.notice_id),
                        upload_status="ready" if s.status == "ready" else s.status,
                        source_id=s.source_id,
                        source_title=s.title,
                    )
                    self._delete_local_pdf(symbol, str(notice.notice_id), str(item["path"]))

                self.database.update_company_research_job(job_id, source_ready=all_ready_count)
                self.database.update_company_notebook_counts(
                    notebook_id, source_count=len(all_source_ids), ready_source_count=all_ready_count,
                )

        self.database.update_company_research_job(job_id, source_ready=all_ready_count)
        self.database.update_company_notebook_counts(
            notebook_id, source_count=len(all_source_ids), ready_source_count=all_ready_count,
        )
        if execution_mode == "download_upload":
            self.database.update_company_research_job(job_id, status="completed", current_stage="uploaded", progress_percent=100, finished_at=datetime.now().isoformat())
            return {"ok": True, "job_id": job_id, "status": "completed", "source_uploaded": len(all_source_ids), "source_ready": all_ready_count}

        await self._stage(job_id, "ask_questions", "asking", 60, progress_callback)
        answered = 0
        saved = 0
        for question in COMPANY_RESEARCH_QUESTIONS:
            self.database.upsert_company_research_answer(
                symbol=symbol,
                stock_name=stock_name,
                question_index=question.index,
                question_key=question.key,
                question_title=question.title,
                prompt_text=question.prompt,
                notebook_id=notebook_id,
                status="asking",
            )
            self.database.update_company_research_job(job_id, current_stage=f"ask_question_{question.index:02d}")
            answer = await self.notebook_client.ask_question(notebook_id, question.prompt)
            answered += 1
            self.database.upsert_company_research_answer(
                symbol=symbol,
                stock_name=stock_name,
                question_index=question.index,
                question_key=question.key,
                question_title=question.title,
                prompt_text=question.prompt,
                answer_markdown=answer.text,
                raw_answer=answer.raw,
                references_json=json.dumps(answer.references, ensure_ascii=False),
                conversation_id=answer.conversation_id,
                source_ids=answer.source_ids,
                notebook_id=notebook_id,
                status="saved",
                generated_at=datetime.now().isoformat(),
                saved_at=datetime.now().isoformat(),
            )
            saved += 1
            progress = 60 + int(saved / len(COMPANY_RESEARCH_QUESTIONS) * 30)
            self.database.update_company_research_job(job_id, question_answered=answered, question_saved=saved, progress_percent=progress)
            self._report_progress(
                progress_callback,
                current=saved,
                total=total_questions,
                content_id=symbol,
                stage=f"ask_question_{question.index:02d}",
                message=f"{symbol} 已保存第 {saved}/{total_questions} 个问题",
            )

        if not self.database.can_delete_company_notebook(symbol):
            self.database.update_company_research_job(job_id, status="partial_failed", current_stage="verify_answers", last_error="answers_not_fully_saved")
            return {"ok": False, "job_id": job_id, "status": "partial_failed", "error": "answers_not_fully_saved"}

        status = "completed"
        await self._stage(job_id, "delete_notebook", "notebook_deleted", 95, progress_callback)
        if auto_delete:
            try:
                await self.notebook_client.delete_notebook(notebook_id)
                self.database.mark_company_notebook_deleted(notebook_id, "deleted")
                notebook_deleted = True
            except Exception as exc:
                status = "completed_with_delete_pending"
                notebook_deleted = False
                self.database.mark_company_notebook_delete_failed(notebook_id, str(exc))
        else:
            status = "completed_with_delete_pending"
            notebook_deleted = False

        self.database.update_company_research_job(
            job_id,
            status=status,
            current_stage="completed",
            progress_percent=100,
            notebook_deleted=notebook_deleted,
            notebook_deleted_at=datetime.now().isoformat() if notebook_deleted else None,
            finished_at=datetime.now().isoformat(),
        )
        await self.notebook_client.close()
        return {"ok": True, "job_id": job_id, "status": status, "pdf_downloaded": len(downloaded), "question_saved": saved, "notebook_deleted": notebook_deleted}

    async def cleanup_completed_notebooks(self) -> dict[str, Any]:
        rows = self.database.list_company_notebooks_pending_cleanup(limit=100)
        cleaned = 0
        failed = 0
        for row in rows:
            notebook_id = str(row.get("notebook_id") or "")
            if not notebook_id:
                continue
            try:
                await self.notebook_client.delete_notebook(notebook_id)
                self.database.mark_company_notebook_deleted(notebook_id, "deleted")
                self.database.mark_company_jobs_notebook_deleted(notebook_id)
                cleaned += 1
            except Exception as exc:
                failed += 1
                self.database.mark_company_notebook_delete_failed(notebook_id, str(exc))
        await self.notebook_client.close()
        return {"ok": failed == 0, "cleaned": cleaned, "failed": failed}

    def cleanup_local_pdfs(self) -> dict[str, Any]:
        rows = self.database.list_company_notice_files_pending_cleanup(limit=500)
        cleaned = 0
        failed = 0
        for row in rows:
            if self._delete_local_pdf(str(row.get("symbol") or ""), str(row.get("notice_id") or ""), str(row.get("file_path") or "")):
                cleaned += 1
            else:
                failed += 1
        return {"ok": failed == 0, "cleaned": cleaned, "failed": failed}

    async def retry_question(self, symbol: str, question_key: str) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        answer_row = self.database.get_company_research_answer(normalized, question_key)
        if not answer_row:
            raise ValueError("未找到要重试的问题")
        question = next((item for item in COMPANY_RESEARCH_QUESTIONS if item.key == question_key), None)
        if not question:
            raise ValueError(f"未知问题 key: {question_key}")
        jobs = self.database.list_company_research_jobs(symbol=normalized, limit=1)
        stock_name = str(answer_row.get("stock_name") or (jobs[0].get("stock_name") if jobs else normalized) or normalized)
        notebook_id = str(answer_row.get("notebook_id") or "")
        rebuilt_notebook = False
        if not notebook_id or (jobs and bool(jobs[0].get("notebook_deleted"))):
            notebook_id = await self._rebuild_notebook_for_retry(
                normalized,
                stock_name,
                question_key=question_key,
                begin_date=str(jobs[0].get("begin_date") or "") if jobs else "",
                end_date=str(jobs[0].get("end_date") or "") if jobs else "",
            )
            rebuilt_notebook = True
        self.database.upsert_company_research_answer(
            symbol=normalized,
            stock_name=stock_name,
            question_index=question.index,
            question_key=question.key,
            question_title=question.title,
            prompt_text=question.prompt,
            notebook_id=notebook_id,
            status="asking",
        )
        answer = await self.notebook_client.ask_question(notebook_id, question.prompt)
        self.database.upsert_company_research_answer(
            symbol=normalized,
            stock_name=stock_name,
            question_index=question.index,
            question_key=question.key,
            question_title=question.title,
            prompt_text=question.prompt,
            answer_markdown=answer.text,
            raw_answer=answer.raw,
            references_json=json.dumps(answer.references, ensure_ascii=False),
            conversation_id=answer.conversation_id,
            source_ids=answer.source_ids,
            notebook_id=notebook_id,
            status="saved",
            generated_at=datetime.now().isoformat(),
            saved_at=datetime.now().isoformat(),
        )
        if notebook_id and rebuilt_notebook:
            try:
                await self.notebook_client.delete_notebook(notebook_id)
                self.database.mark_company_notebook_deleted(notebook_id, "deleted")
            except Exception as exc:
                self.database.mark_company_notebook_delete_failed(notebook_id, str(exc))
        await self.notebook_client.close()
        return {"ok": True, "symbol": normalized, "question_key": question_key}

    async def _stage(self, job_id: int, stage: str, status: str, progress: int, progress_callback: Any = None) -> None:
        self.database.update_company_research_job(job_id, status=status, current_stage=stage, progress_percent=progress, started_at=datetime.now().isoformat())
        self._report_progress(
            progress_callback,
            current=int(progress),
            total=100,
            content_id=str(job_id),
            stage=stage,
            message=f"公司研究阶段: {stage}",
        )
        await asyncio.sleep(0)

    def _normalize_request(self, request: dict[str, Any]) -> dict[str, Any]:
        defaults = self.default_request()
        data = {**defaults, **(request or {})}
        max_stocks = max(1, min(50, int(data.get("max_stocks") or 1)))
        execution_mode = str(data.get("execution_mode") or "full")
        if execution_mode in {"download", "download_only"}:
            execution_mode = "download_only"
        elif execution_mode in {"download_upload", "upload"}:
            execution_mode = "download_upload"
        elif execution_mode in {"ask", "download_upload_ask"}:
            execution_mode = "download_upload_ask"
        else:
            execution_mode = "full"
        return {
            "begin_date": str(data["begin_date"])[:10],
            "end_date": str(data["end_date"])[:10],
            "stock_scope": str(data.get("stock_scope") or "manual"),
            "max_stocks": max_stocks,
            "symbols": data.get("symbols") or [],
            "notice_type": str(data.get("notice_type") or "全部"),
            "execution_mode": execution_mode,
            "auto_delete_notebook": bool(data.get("auto_delete_notebook", True)),
        }

    def _resolve_stocks(self, request: dict[str, Any]) -> list[StockInfo]:
        scope = str(request.get("stock_scope") or "manual")
        max_stocks = int(request.get("max_stocks") or 1)
        if scope == "first_n":
            try:
                return fetch_all_stocks(limit=max_stocks)
            except Exception:
                return [StockInfo("300750.SZ", "宁德时代")][:max_stocks]
        symbols = _parse_symbols(request.get("symbols") or [])
        if not symbols:
            symbols = ["300750.SZ"]
        stocks: list[StockInfo] = []
        for symbol in symbols[:max_stocks]:
            try:
                stocks.append(fetch_stock_info(symbol))
            except Exception:
                normalized = normalize_symbol(symbol)
                stocks.append(StockInfo(normalized, normalized))
        return stocks

    async def _rebuild_notebook_for_retry(self, symbol: str, stock_name: str, *, question_key: str, begin_date: str, end_date: str) -> str:
        notices = self.database.list_company_notice_files(symbol, limit=500)
        downloadable = [row for row in notices if str(row.get("download_url") or row.get("notice_url") or "").strip()]
        if not downloadable:
            raise RuntimeError("retry_failed_pdf_redownload_failed")
        notebook_title = f"公司研究_重试_{symbol}_{question_key}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        notebook = await self.notebook_client.create_notebook(notebook_title)
        notebook_id = str(notebook.get("id") or "")
        if not notebook_id:
            raise RuntimeError("retry_failed_pdf_redownload_failed")
        self.database.upsert_company_notebook(symbol, stock_name, notebook_id, notebook_title, "created")
        source_ids: list[str] = []
        redownloaded_rows: list[dict[str, Any]] = []
        for row in downloadable:
            notice = _notice_from_row(row)
            result = self.downloader.download_notice_pdf(notice)
            if result.status != "downloaded" or not result.file_path:
                raise RuntimeError("retry_failed_pdf_redownload_failed")
            self.database.upsert_company_notice_file(
                symbol=symbol,
                stock_name=stock_name,
                notice_id=notice.notice_id,
                notice_title=notice.title,
                notice_date=notice.notice_date,
                notice_url=notice.notice_url,
                source_provider=result.provider or notice.source_provider,
                download_url=result.download_url,
                file_path=result.file_path,
                file_name=result.file_name,
                file_size=result.validation.file_size if result.validation else 0,
                file_hash=result.validation.file_hash if result.validation else "",
                is_valid_pdf=bool(result.validation and result.validation.ok),
                download_status=result.status,
                provider_attempts_json=result.provider_attempts,
                final_provider=result.provider or notice.source_provider,
                upload_status="pending",
                source_id="",
                source_title="",
                local_file_deleted=False,
                local_file_deleted_at="",
                delete_local_error="",
                error_message=result.error,
            )
            source = await self.notebook_client.upload_pdf(notebook_id, result.file_path, Path(result.file_path).name)
            source_ids.append(source.source_id)
            redownloaded_rows.append(
                {
                    "notice": notice,
                    "file_path": result.file_path,
                    "source_id": source.source_id,
                    "source_title": source.title,
                }
            )
            self.database.update_company_notice_file_upload(
                symbol=symbol,
                notice_id=notice.notice_id,
                upload_status="uploaded",
                source_id=source.source_id,
                source_title=source.title,
            )
        ready = await self.notebook_client.wait_sources_ready(notebook_id, source_ids)
        ready_by_id = {item.source_id: item for item in ready}
        for row in redownloaded_rows:
            source = ready_by_id.get(str(row["source_id"]))
            self.database.update_company_notice_file_upload(
                symbol=symbol,
                notice_id=str(row["notice"].notice_id),
                upload_status="ready" if source else "uploaded",
                source_id=str(row["source_id"]),
                source_title=str((source.title if source else row["source_title"]) or ""),
            )
            self._delete_local_pdf(symbol, str(row["notice"].notice_id), str(row["file_path"]))
        return notebook_id

    def _delete_local_pdf(self, symbol: str, notice_id: str, file_path: str) -> bool:
        path = Path(file_path)
        if not file_path:
            self.database.mark_company_notice_file_local_deleted(symbol, notice_id, deleted=False, delete_error="missing_file_path")
            return False
        try:
            if path.exists():
                path.unlink()
            self.database.mark_company_notice_file_local_deleted(symbol, notice_id, deleted=True, delete_error=None)
            return True
        except Exception as exc:
            self.database.mark_company_notice_file_local_deleted(symbol, notice_id, deleted=False, delete_error=str(exc))
            logger.warning("删除本地公司研究 PDF 失败: symbol=%s notice_id=%s path=%s error=%s", symbol, notice_id, file_path, exc)
            return False

    def _report_progress(
        self,
        callback: Any,
        *,
        current: int,
        total: int,
        content_id: str,
        stage: str,
        message: str,
    ) -> None:
        if not callback:
            return
        try:
            callback(int(current), int(total), str(content_id), str(stage), str(message))
        except Exception:
            logger.debug("公司研究进度回调写入失败", exc_info=True)


def _parse_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).replace("\n", ",").split(","))
    else:
        raw_items = []
    return [normalize_symbol(item) for item in raw_items if str(item).strip()]


def _notice_from_row(row: dict[str, Any]) -> Any:
    from kenradar.company_research.akshare_provider import Notice

    return Notice(
        symbol=str(row.get("symbol") or ""),
        stock_name=str(row.get("stock_name") or row.get("symbol") or ""),
        notice_id=str(row.get("notice_id") or ""),
        title=str(row.get("notice_title") or "未命名公告"),
        notice_date=str(row.get("notice_date") or ""),
        notice_url=str(row.get("download_url") or row.get("notice_url") or ""),
        source_provider=str(row.get("source_provider") or "akshare"),
    )
