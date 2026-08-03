from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = (ROOT / "kenradar", ROOT / "scripts")
FORBIDDEN_TEXT = (
    "company_research",
    "company-research",
    "CompanyResearch",
    "CompanyFinancialAnalysis",
    "NotebookLM",
    "notebooklm",
    "company_financial_analysis",
)


def test_experimental_runtime_modules_are_removed() -> None:
    assert not (ROOT / "kenradar/company_research").exists()
    assert not (ROOT / "kenradar/web/company_research_api.py").exists()
    assert not (ROOT / "kenradar/storage/repositories/company_research.py").exists()


def test_runtime_and_frontend_have_no_experimental_symbols() -> None:
    offenders: list[str] = []
    for base in RUNTIME_ROOTS:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative == "kenradar/storage/pg_database.py":
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0003_"):
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0004_"):
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0005_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in FORBIDDEN_TEXT):
                offenders.append(relative)
    assert offenders == []


def test_retired_migrations_remain_for_private_database_compatibility() -> None:
    versions = ROOT / "kenradar/storage/migrations/versions"
    assert (versions / "0003_company_research.py").exists()
    assert (versions / "0004_company_notice_attempts.py").exists()
    assert (versions / "0005_fin_analysis_mvp.py").exists()
    assert 'down_revision = "0005_fin_analysis_mvp"' in (
        versions / "0006_add_xiaoyuzhou_platform.py"
    ).read_text(encoding="utf-8")


def test_company_api_prefix_is_not_registered() -> None:
    app_text = (ROOT / "kenradar/web/app.py").read_text(encoding="utf-8")
    assert '"/api/company-research' not in app_text
    assert '"/company-research"' not in app_text


def test_company_task_types_are_not_dispatched() -> None:
    handlers = (ROOT / "kenradar/jobs/handlers.py").read_text(encoding="utf-8")
    for task_type in (
        "company_research_batch",
        "company_research_cleanup_notebooks",
        "company_research_cleanup_local_pdfs",
        "company_financial_analysis",
    ):
        assert task_type not in handlers


def test_postgres_runtime_facade_has_no_experiment_repository() -> None:
    text = (ROOT / "kenradar/storage/pg_database.py").read_text(encoding="utf-8")
    assert "CompanyResearchRepository" not in text
    assert "self.company_research" not in text
    assert "def create_company_research" not in text
    assert "def create_financial_analysis" not in text
    assert "CREATE TABLE IF NOT EXISTS company_research_batches" in text


def test_experimental_frontend_files_are_removed() -> None:
    frontend = ROOT / "kenradar/web/frontend/src"
    assert not (frontend / "components/CompanyResearchWorkspace.tsx").exists()
    assert not (frontend / "components/CompanyFinancialAnalysisMVP.tsx").exists()
    assert not (frontend / "components/company-research").exists()


def test_product_docs_do_not_advertise_retired_experiments() -> None:
    for relative in ("README.md", "AGENTS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "NotebookLM" not in text
        assert "公司研究" not in text
        assert "财务分析" not in text


def test_retired_experiment_design_artifacts_are_removed() -> None:
    for relative in (
        "design/300750.SZ_公告列表_标题特征研究.md",
        "design/A股全量_近两年公告统计.md",
        "design/financial_analysis_mvp_plan.md",
        "design/frontend_restructure_phase2_plan.md",
        "design/frontend_restructure_plan.md",
        "design/implementation_plan_stock_1.md",
        "design/run_all_stock_notice_stats.py",
        "design/stock.md",
        "design/随机5只股票_公告标题特征研究.md",
    ):
        assert not (ROOT / relative).exists(), relative
