"""财务分析服务 — 任务编排（幂等重跑）。"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from kenradar.company_research.financial_analysis.parser import (
    FinancialReportParser,
)
from kenradar.company_research.financial_analysis.prompt_templates import (
    FINANCIAL_ANALYSIS_QUESTIONS,
)
from kenradar.company_research.financial_analysis.report_selector import (
    FinancialReportSelector,
)
from kenradar.company_research.financial_analysis.score_engine import (
    FinancialScoreEngine,
    SCORE_DIMENSIONS,
)
from kenradar.company_research.notebooklm_client import (
    NotebookLMClient,
)
from kenradar.company_research.notice_downloader import (
    NoticeDownloader,
)
from kenradar.company_research.pdf_validator import (
    validate_pdf,
    compute_file_hash,
)
from kenradar.core.config import AppConfig
from kenradar.storage import create_database

logger = logging.getLogger(__name__)


# ── 任务 stage 顺序（用于幂等跳过） ──────────────────────────
STAGES: list[str] = [
    "select_report_files",
    "download_pdfs",
    "create_notebook",
    "upload_sources",
    "wait_sources_ready",
    "delete_local_pdfs",
    "ask_q1",
    "ask_q2",
    "ask_q3",
    "ask_q4",
    "ask_q5",
    "ask_q6",
    "ask_q7",
    "ask_q8",
    "ask_q9",
    "ask_q10",
    "ask_q11_final_report",
    "parse_json",
    "save_red_flags",
    "save_score",
    "delete_notebook",
    "completed",
]


class FinancialAnalysisService:
    """财务分析 MVP 服务。"""

    def __init__(
        self,
        config: AppConfig,
        database: Any | None = None,
        notebook_client: NotebookLMClient | None = None,
        downloader: NoticeDownloader | None = None,
    ):
        self.config = config
        self.database = database or create_database(config)
        self.notebook_client = notebook_client or NotebookLMClient()
        self.downloader = downloader or NoticeDownloader(config.data_dir)
        self.selector = FinancialReportSelector()
        self.parser = FinancialReportParser()
        self.score_engine = FinancialScoreEngine()

    # ──────────────────────────────────────────────────────────
    # 创建任务
    # ──────────────────────────────────────────────────────────

    def create_job(
        self,
        symbol: str,
        analysis_base_year: int | None = None,
        auto_delete_notebook: bool = True,
        delete_local_pdfs_after_ready: bool = False,
    ) -> dict[str, Any]:
        """创建财务分析任务。

        Args:
            symbol: 股票代码。
            analysis_base_year: 分析基准年份，默认当前年份。
            auto_delete_notebook: 完成后是否删除 NotebookLM。
            delete_local_pdfs_after_ready: 是否在 source ready 后就删除本地 PDF。

        Returns:
            创建的 job dict。
        """
        if analysis_base_year is None:
            analysis_base_year = date.today().year

        from kenradar.company_research.akshare_provider import normalize_symbol
        normalized_symbol = normalize_symbol(symbol)

        try:
            from kenradar.company_research.akshare_provider import fetch_stock_info
            info = fetch_stock_info(normalized_symbol)
            stock_name = info.name
        except Exception:
            stock_name = normalized_symbol

        job = self.database.create_financial_analysis_job(
            symbol=normalized_symbol,
            stock_name=stock_name,
            analysis_base_year=analysis_base_year,
            auto_delete_notebook=auto_delete_notebook,
            delete_local_pdfs_after_ready=delete_local_pdfs_after_ready,
        )
        logger.info("创建财务分析任务: job_id=%s symbol=%s", job["id"], normalized_symbol)
        return job

    # ──────────────────────────────────────────────────────────
    # 预览
    # ──────────────────────────────────────────────────────────

    def preview(
        self,
        symbol: str,
        analysis_base_year: int | None = None,
    ) -> dict[str, Any]:
        """预览报告选择结果。"""
        result = self.selector.select(
            symbol=symbol,
            analysis_base_year=analysis_base_year,
        )
        return {
            "ok": True,
            "symbol": result.symbol,
            "stock_name": result.stock_name,
            "analysis_base_year": result.analysis_base_year,
            "selected_reports": [
                {
                    "report_year": pn.report_year,
                    "report_period": pn.report_period,
                    "report_period_end": str(pn.report_period_end) if pn.report_period_end else None,
                    "report_type": _period_to_type(pn.report_period),
                    "notice_title": pn.notice_title,
                    "notice_date": str(pn.notice_date),
                    "found": True,
                    "is_revised": pn.is_revised,
                }
                for pn in result.selected_notices
            ],
            "missing_reports": result.missing_reports,
            "total_selected": result.total_selected,
            "over_limit": result.over_limit,
            "all_notices_count": result.all_notices_count,
        }

    # ──────────────────────────────────────────────────────────
    # 任务编排（幂等重跑）
    # ──────────────────────────────────────────────────────────

    async def run_job(
        self,
        job_id: int,
        *,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """执行财务分析任务（幂等，支持从中断处继续）。

        每一步执行前检查数据库是否已完成。
        """
        job = self.database.get_financial_analysis_job(job_id)
        if not job:
            raise ValueError(f"未找到财务分析任务: {job_id}")

        if job["status"] == "completed":
            logger.info("任务已结束: job_id=%s status=%s", job_id, job["status"])
            return {"ok": True, "job_id": job_id, "status": job["status"]}
        if job["status"] in ("failed", "partial_failed"):
            logger.info("任务已失败，需重新创建或重置后再执行: job_id=%s status=%s", job_id, job["status"])
            return {
                "ok": False,
                "job_id": job_id,
                "status": job["status"],
                "stage": job.get("current_stage") or "",
                "error": job.get("last_error") or "任务此前已失败",
            }

        current = job.get("current_stage") or "created"
        try:
            start_idx = STAGES.index(current)
        except ValueError:
            start_idx = 0

        symbol = str(job["symbol"])
        stock_name = str(job.get("stock_name") or symbol)
        analysis_base_year = int(job.get("analysis_base_year") or date.today().year)
        auto_delete = bool(job.get("auto_delete_notebook", True))
        delete_local_pdfs_after_ready = bool(job.get("delete_local_pdfs_after_ready", False))

        self.database.update_financial_analysis_job(
            job_id,
            status="running",
            started_at=datetime.now().isoformat(),
            last_error="",
        )

        for stage in STAGES[start_idx:]:
            if stage == "completed":
                break

            try:
                await self._execute_stage(
                    stage=stage,
                    job_id=job_id,
                    job=job,
                    symbol=symbol,
                    stock_name=stock_name,
                    analysis_base_year=analysis_base_year,
                    auto_delete=auto_delete,
                    delete_local_pdfs_after_ready=delete_local_pdfs_after_ready,
                )
                self.database.update_financial_analysis_job(
                    job_id,
                    current_stage=stage,
                )
                self._report_progress(progress_callback, stage, 0, 1, symbol)

            except Exception as exc:
                error_message = _format_exception(exc)
                logger.exception(
                    "财务分析任务失败: job_id=%s stage=%s", job_id, stage
                )
                self.database.update_financial_analysis_job(
                    job_id,
                    status="failed",
                    current_stage=stage,
                    last_error=error_message,
                    finished_at=datetime.now().isoformat(),
                )
                return {
                    "ok": False,
                    "job_id": job_id,
                    "status": "failed",
                    "stage": stage,
                    "error": error_message,
                }

        self.database.update_financial_analysis_job(
            job_id,
            status="completed",
            current_stage="completed",
            finished_at=datetime.now().isoformat(),
        )
        await self.notebook_client.close()
        logger.info("财务分析任务完成: job_id=%s", job_id)
        return {"ok": True, "job_id": job_id, "status": "completed"}

    # ──────────────────────────────────────────────────────────
    # 各阶段执行
    # ──────────────────────────────────────────────────────────

    async def _execute_stage(
        self,
        *,
        stage: str,
        job_id: int,
        job: dict[str, Any],
        symbol: str,
        stock_name: str,
        analysis_base_year: int,
        auto_delete: bool,
        delete_local_pdfs_after_ready: bool,
    ) -> None:
        logger.info("执行阶段: job_id=%s stage=%s", job_id, stage)

        if stage == "select_report_files":
            await self._stage_select_report_files(
                job_id, job, symbol, stock_name, analysis_base_year
            )
        elif stage == "download_pdfs":
            await self._stage_download_pdfs(job_id, symbol)
        elif stage == "create_notebook":
            await self._stage_create_notebook(job_id, symbol, stock_name, analysis_base_year)
        elif stage == "upload_sources":
            await self._stage_upload_sources(job_id, symbol)
        elif stage == "wait_sources_ready":
            await self._stage_wait_sources_ready(job_id)
        elif stage == "delete_local_pdfs":
            if delete_local_pdfs_after_ready:
                await self._stage_delete_local_pdfs(job_id)
            else:
                logger.info("未启用 source ready 后删除本地 PDF，跳过: job_id=%s", job_id)
        elif stage == "ask_q11_final_report":
            await self._stage_ask_q11(job_id, symbol)
        elif stage.startswith("ask_q"):
            await self._stage_ask_question(job_id, symbol, stage)
        elif stage == "parse_json":
            await self._stage_parse_json(job_id, symbol)
        elif stage == "save_red_flags":
            await self._stage_save_red_flags(job_id, symbol)
        elif stage == "save_score":
            await self._stage_save_score(job_id, symbol)
        elif stage == "delete_notebook":
            await self._stage_delete_notebook(job_id, auto_delete)
        else:
            logger.warning("未知阶段: %s", stage)

    async def _stage_select_report_files(
        self,
        job_id: int,
        job: dict[str, Any],
        symbol: str,
        stock_name: str,
        analysis_base_year: int,
    ) -> None:
        # 幂等检查
        existing = self.database.list_financial_report_files(job_id)
        if existing:
            logger.info("报告选择已存在，跳过: job_id=%s", job_id)
            return

        result = self.selector.select(
            symbol=symbol,
            analysis_base_year=analysis_base_year,
        )

        for pn in result.selected_notices:
            self.database.upsert_financial_report_file(
                job_id=job_id,
                symbol=symbol,
                report_year=pn.report_year,
                report_period=pn.report_period,
                report_period_end=str(pn.report_period_end) if pn.report_period_end else None,
                report_type=_period_to_type(pn.report_period),
                notice_title=pn.notice_title,
                notice_date=str(pn.notice_date),
                pdf_status="selected",
            )

        missing_json = json.dumps(result.missing_reports, ensure_ascii=False)
        self.database.update_financial_analysis_job(
            job_id,
            selected_pdf_count=result.total_selected,
            missing_report_files=missing_json,
        )

    async def _stage_download_pdfs(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        report_files = self.database.list_financial_report_files(job_id)
        downloaded = 0
        for rf in report_files:
            if rf.get("pdf_status") in ("downloaded", "valid"):
                downloaded += 1
                continue

            notice_title = str(rf.get("notice_title") or "")
            notice_date = str(rf.get("notice_date") or "")

            # 构造 Notice 对象
            from kenradar.company_research.akshare_provider import Notice
            notice = Notice(
                symbol=symbol,
                stock_name=str(rf.get("symbol") or symbol),
                notice_id=f"fin-{job_id}-{rf['id']}",
                title=notice_title,
                notice_date=notice_date[:10] if notice_date else "",
                notice_url="",
                source_provider="akshare",
            )

            result = self.downloader.download_notice_pdf(notice)
            validation = result.validation

            self.database.upsert_financial_report_file(
                job_id=job_id,
                symbol=symbol,
                report_year=rf.get("report_year"),
                report_period=rf.get("report_period"),
                notice_title=notice_title,
                pdf_status=result.status if result.status == "downloaded" else "failed",
                file_path=result.file_path or "",
                file_size=validation.file_size if validation else 0,
                file_hash=validation.file_hash if validation else "",
                final_provider=result.provider or "",
                download_error=result.error,
            )

            if result.status == "downloaded" and result.file_path:
                downloaded += 1

        self.database.update_financial_analysis_job(
            job_id,
            selected_pdf_count=downloaded,
        )

    async def _stage_create_notebook(
        self,
        job_id: int,
        symbol: str,
        stock_name: str,
        analysis_base_year: int,
    ) -> None:
        job = self.database.get_financial_analysis_job(job_id)
        if job and job.get("notebook_id"):
            logger.info("Notebook 已存在，跳过: %s", job["notebook_id"])
            return

        title = f"财务分析_{symbol}_{stock_name}_{analysis_base_year}_{datetime.now().strftime('%Y%m%d')}"
        notebook: dict[str, str] = {}
        last_error = ""
        for attempt in range(1, 4):
            try:
                notebook = await self.notebook_client.create_notebook(title)
                break
            except Exception as exc:
                last_error = _format_exception(exc)
                logger.warning(
                    "NotebookLM 创建失败，将重试: job_id=%s attempt=%s/3 error=%s",
                    job_id,
                    attempt,
                    last_error,
                )
                await self.notebook_client.close()
                if attempt >= 3:
                    raise RuntimeError(f"NotebookLM 创建失败，已重试 3 次: {last_error}") from exc
                await asyncio.sleep(5 * attempt)
        notebook_id = str(notebook.get("id") or "")
        if not notebook_id:
            raise RuntimeError("NotebookLM 创建失败")
        self.database.update_financial_analysis_job(
            job_id,
            notebook_id=notebook_id,
        )

    async def _stage_upload_sources(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        job = self.database.get_financial_analysis_job(job_id)
        notebook_id = str(job.get("notebook_id") or "")
        if not notebook_id:
            raise RuntimeError("Notebook ID 为空")

        report_files = self.database.list_financial_report_files(job_id)
        uploaded = 0
        for rf in report_files:
            if rf.get("upload_status") == "uploaded":
                uploaded += 1
                continue
            if rf.get("pdf_status") not in ("downloaded", "valid"):
                continue
            file_path = str(rf.get("file_path") or "")
            if not file_path or not Path(file_path).exists():
                continue

            notice_title = str(rf.get("notice_title") or rf.get("notice_title") or "")
            try:
                source = await self.notebook_client.upload_pdf(
                    notebook_id, file_path, notice_title
                )
                self.database.update_financial_report_file_upload(
                    job_id=job_id,
                    notice_title=notice_title,
                    upload_status="uploaded",
                    source_id=source.source_id,
                    source_title=source.title,
                )
                uploaded += 1
            except Exception as exc:
                error_message = _format_exception(exc)
                logger.warning("上传 PDF 失败: %s error=%s", file_path, error_message)
                self.database.update_financial_report_file_upload(
                    job_id=job_id,
                    notice_title=notice_title,
                    upload_status="failed",
                    upload_error=error_message,
                )

        self.database.update_financial_analysis_job(
            job_id,
            uploaded_source_count=uploaded,
        )

    async def _stage_wait_sources_ready(
        self,
        job_id: int,
    ) -> None:
        job = self.database.get_financial_analysis_job(job_id)
        notebook_id = str(job.get("notebook_id") or "")
        report_files = self.database.list_financial_report_files(job_id)

        source_ids = [
            str(rf["source_id"])
            for rf in report_files
            if rf.get("upload_status") == "uploaded" and rf.get("source_id")
        ]
        if not source_ids:
            return

        try:
            ready = await self.notebook_client.wait_sources_ready(
                notebook_id, source_ids, timeout_seconds=900
            )
            ready_count = sum(1 for s in ready if s.status == "ready")
            for rf in report_files:
                sid = str(rf.get("source_id") or "")
                match = next((s for s in ready if s.source_id == sid), None)
                if match:
                    self.database.update_financial_report_file_upload(
                        job_id=job_id,
                        notice_title=str(rf.get("notice_title") or ""),
                        upload_status=match.status,
                        source_id=sid,
                    )
            self.database.update_financial_analysis_job(
                job_id,
                ready_source_count=ready_count,
            )
        except Exception as exc:
            logger.warning("等待 sources ready 超时: %s", exc)
            raise

    async def _stage_delete_local_pdfs(self, job_id: int) -> None:
        report_files = self.database.list_financial_report_files(job_id)
        for rf in report_files:
            if rf.get("local_file_deleted"):
                continue
            file_path = str(rf.get("file_path") or "")
            if not file_path:
                continue
            path = Path(file_path)
            if path.exists():
                path.unlink()
            self.database.upsert_financial_report_file(
                job_id=job_id,
                symbol=str(rf.get("symbol") or ""),
                notice_title=str(rf.get("notice_title") or ""),
                pdf_status=str(rf.get("pdf_status") or ""),
                local_file_deleted=True,
            )

    async def _stage_ask_question(
        self,
        job_id: int,
        symbol: str,
        stage: str,
    ) -> None:
        job = self.database.get_financial_analysis_job(job_id)
        notebook_id = str(job.get("notebook_id") or "")

        # 解析 stage: "ask_q1" → index=1
        idx_str = stage.replace("ask_q", "")
        try:
            q_index = int(idx_str)
        except ValueError:
            return

        question = next(
            (q for q in FINANCIAL_ANALYSIS_QUESTIONS if q.index == q_index),
            None,
        )
        if not question:
            logger.warning("未知问题索引: %s", q_index)
            return

        # 幂等检查
        existing = self.database.get_financial_question_answer(
            job_id, question.key
        )
        if existing and existing.get("status") == "saved":
            logger.info("问题已回答，跳过: %s", question.key)
            return

        prompt = question.prompt
        # Q2 需要替换年份占位符
        if question.key == "core_financial_data":
            base = int(job.get("analysis_base_year") or date.today().year)
            prompt = prompt.format(
                last_year_3=base - 3,
                last_year_2=base - 2,
                last_year_1=base - 1,
            )

        self.database.upsert_financial_question_answer(
            job_id=job_id,
            symbol=symbol,
            question_index=question.index,
            question_key=question.key,
            question_title=question.title,
            prompt_text=prompt,
            status="asking",
        )

        try:
            answer = await self._ask_notebook_question_with_retry(
                job_id=job_id,
                question_label=f"Q{question.index} {question.title}",
                notebook_id=notebook_id,
                prompt=prompt,
            )
            self.database.upsert_financial_question_answer(
                job_id=job_id,
                symbol=symbol,
                question_index=question.index,
                question_key=question.key,
                question_title=question.title,
                prompt_text=prompt,
                answer_markdown=answer.text,
                raw_answer=answer.raw,
                status="saved",
                conversation_id=answer.conversation_id,
            )
            answered = self.database.list_financial_question_answers(job_id)
            saved = sum(1 for a in answered if a.get("status") == "saved")
            self.database.update_financial_analysis_job(
                job_id,
                question_answered=len(answered),
                question_saved=saved,
            )
        except Exception as exc:
            self.database.upsert_financial_question_answer(
                job_id=job_id,
                symbol=symbol,
                question_index=question.index,
                question_key=question.key,
                question_title=question.title,
                prompt_text=prompt,
                status="failed",
                error_message=_format_exception(exc),
            )
            raise

    async def _stage_ask_q11(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        # 幂等检查
        existing_report = self.database.get_financial_analysis_report_by_job(job_id)
        if existing_report and existing_report.get("status") == "saved":
            logger.info("最终报告已存在，跳过: job_id=%s", job_id)
            return

        # 读取前 10 题回答，直接拼接为最终报告，不再调用 NotebookLM
        answers = self.database.list_financial_question_answers(job_id, limit=10)
        answers.sort(key=lambda a: a.get("question_index", 0))

        sections = []
        for ans in answers:
            title = ans.get("question_title", "")
            content = ans.get("answer_markdown") or ans.get("raw_answer") or ""
            sections.append(f"# {title}\n\n{content}")

        report_markdown = "\n\n---\n\n".join(sections)
        report_markdown = f"# 财务分析报告（由 Q1-Q10 合并生成）\n\n{report_markdown}"

        # 保存 Q11 问题记录（标记为 saved）
        self.database.upsert_financial_question_answer(
            job_id=job_id,
            symbol=symbol,
            question_index=11,
            question_key="final_report",
            question_title="合并生成完整财务分析报告（后台拼接）",
            prompt_text="由 Q1-Q10 各题回答直接拼接生成",
            answer_markdown=report_markdown,
            raw_answer=report_markdown,
            status="saved",
        )
        # 保存到报告表
        self.database.upsert_financial_analysis_report(
            job_id=job_id,
            symbol=symbol,
            report_markdown=report_markdown,
            raw_answer=report_markdown,
            status="saved",
        )

        self.database.update_financial_analysis_job(
            job_id,
            question_saved=11,
        )
        logger.info("Q11 最终报告已拼接生成: job_id=%s", job_id)

    async def _ask_notebook_question_with_retry(
        self,
        *,
        job_id: int,
        question_label: str,
        notebook_id: str,
        prompt: str,
        attempts: int = 3,
        timeout_seconds: int = 600,
    ):
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                answer = await asyncio.wait_for(
                    self.notebook_client.ask_question(notebook_id, prompt),
                    timeout=timeout_seconds,
                )
                if not str(answer.text or "").strip():
                    raise RuntimeError("NotebookLM 返回空答案")
                return answer
            except Exception as exc:
                last_error = _format_exception(exc)
                logger.warning(
                    "NotebookLM 问答失败，将重试: job_id=%s question=%s attempt=%s/%s error=%s",
                    job_id,
                    question_label,
                    attempt,
                    attempts,
                    last_error,
                )
                await self.notebook_client.close()
                if attempt >= attempts:
                    raise RuntimeError(
                        f"{question_label} 失败，已重试 {attempts} 次: {last_error}"
                    ) from exc
                await asyncio.sleep(5 * attempt)

        raise RuntimeError(f"{question_label} 失败: {last_error}")

    async def _stage_parse_json(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        report = self.database.get_financial_analysis_report_by_job(job_id)
        if not report:
            logger.warning("报告不存在，跳过 JSON 解析: job_id=%s", job_id)
            return
        if _has_meaningful_parsed_json(report.get("parsed_json")):
            logger.info("JSON 已解析，跳过: job_id=%s", job_id)
            return

        markdown = report.get("report_markdown") or ""
        raw_answer = report.get("raw_answer") or ""
        parsed = self.parser.parse(markdown, raw_answer)

        parse_success = not parsed.get("_parse_error", False)
        score_source = parsed.get("score_source", "fallback")

        # 优先用 JSON 中的分数，否则计算
        score_detail = parsed.get("score_detail", {})
        if parse_success:
            total_score = self.score_engine.compute_from_json(score_detail)
        else:
            # 从 Q10 回答尝试提取红旗
            q10 = self.database.get_financial_question_answer(job_id, "risk_scoring")
            red_flags: list[dict] = []
            if q10 and q10.get("answer_markdown"):
                # 简单解析尝试
                red_flags = self._extract_flags_from_q10(
                    q10.get("answer_markdown", "")
                )
            total_score = self.score_engine.fallback_score(red_flags)

        tier, tier_desc = self.score_engine.tier_from_score(total_score)

        self.database.upsert_financial_analysis_report(
            job_id=job_id,
            symbol=symbol,
            parsed_json=json.dumps(parsed, ensure_ascii=False),
            parse_success=parse_success,
            financial_risk_score=total_score,
            financial_risk_tier=tier,
            score_source=score_source,
            first_repayment_source=parsed.get("first_repayment_source", ""),
            leasing_advice=parsed.get("leasing_advice", ""),
            status="saved",
        )

    async def _stage_save_red_flags(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        report = self.database.get_financial_analysis_report_by_job(job_id)
        if not report or not report.get("parsed_json"):
            return

        flags = self.database.list_financial_red_flags(job_id)
        if flags:
            logger.info("红旗已保存，跳过: job_id=%s", job_id)
            return

        try:
            parsed = (
                json.loads(report["parsed_json"])
                if isinstance(report["parsed_json"], str)
                else report["parsed_json"]
            )
        except (json.JSONDecodeError, TypeError):
            return

        red_flags = parsed.get("red_flags", [])
        if red_flags:
            self.database.insert_financial_red_flags(job_id, symbol, red_flags)

    async def _stage_save_score(
        self,
        job_id: int,
        symbol: str,
    ) -> None:
        job = self.database.get_financial_analysis_job(job_id)
        if job and job.get("financial_risk_score") is not None:
            logger.info("评分已保存，跳过: job_id=%s", job_id)
            return

        report = self.database.get_financial_analysis_report_by_job(job_id)
        if not report:
            return

        self.database.update_financial_analysis_job(
            job_id,
            financial_risk_score=report.get("financial_risk_score"),
            financial_risk_tier=report.get("financial_risk_tier"),
            score_source=report.get("score_source"),
        )

    async def _stage_delete_notebook(
        self,
        job_id: int,
        auto_delete: bool,
    ) -> None:
        if not auto_delete:
            return

        job = self.database.get_financial_analysis_job(job_id)
        if not job or job.get("notebook_deleted"):
            return

        notebook_id = str(job.get("notebook_id") or "")
        if not notebook_id:
            return

        try:
            await self.notebook_client.delete_notebook(notebook_id)
            self.database.update_financial_analysis_job(
                job_id,
                notebook_deleted=True,
            )
        except Exception as exc:
            logger.warning("删除 Notebook 失败: %s", exc)
            raise

    def _extract_flags_from_q10(self, markdown: str) -> list[dict]:
        """从 Q10 回答中简单提取红旗用于兜底评分。"""
        import re

        flags: list[dict] = []
        lines = markdown.split("\n")
        in_table = False
        for line in lines:
            if "| 红旗事项 |" in line or "| 风险事项 |" in line:
                in_table = True
                continue
            if in_table and line.strip().startswith("|") and "---" not in line:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 5:
                    level = "低"
                    if "高" in cells[3]:
                        level = "高"
                    elif "中" in cells[3]:
                        level = "中"
                    flags.append({
                        "flag_name": cells[0][:100],
                        "risk_level": level,
                    })
        return flags

    def _report_progress(
        self,
        callback: Any,
        stage: str,
        current: int,
        total: int,
        content_id: str,
    ) -> None:
        if not callback:
            return
        try:
            callback(current, total, content_id, stage, f"财务分析: {stage}")
        except Exception:
            pass

    async def close(self) -> None:
        await self.notebook_client.close()


def _period_to_type(period: str | None) -> str:
    mapping = {
        "annual": "annual_report",
        "half": "semi_annual_report",
        "q1": "quarterly_report",
        "q3": "quarterly_report",
    }
    return mapping.get(period or "", "")


def _has_meaningful_parsed_json(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, dict):
        return bool(value) and value != {}
    if isinstance(value, str):
        text = value.strip()
        return bool(text) and text not in {"{}", "null"}
    return True


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    name = exc.__class__.__name__
    if message:
        return f"{name}: {message}"
    if name in {"ConnectTimeout", "ReadTimeout", "TimeoutException", "TimeoutError"}:
        return f"{name}: 连接 NotebookLM 超时，请检查本机网络、代理或 Google/NotebookLM 登录状态后重试"
    if name in {"ConnectError", "NetworkError", "TransportServerError"}:
        return f"{name}: NotebookLM 网络连接失败，请检查本机网络、代理或 Google/NotebookLM 登录状态后重试"
    return name
