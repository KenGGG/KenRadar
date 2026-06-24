"""财务分析 MVP 模块。

基于 3 份年报 + 1 份最新季报/半年报，通过 NotebookLM 生成
财务分析报告、红旗清单和风险评分。
"""

from kenradar.company_research.financial_analysis.report_selector import (
    FinancialReportSelector,
    FinancialReportSelection,
    ParsedNotice,
)

from kenradar.company_research.financial_analysis.prompt_templates import (
    FINANCIAL_ANALYSIS_QUESTIONS,
    FinancialAnalysisQuestion,
)

from kenradar.company_research.financial_analysis.parser import (
    FinancialReportParser,
)

from kenradar.company_research.financial_analysis.score_engine import (
    FinancialScoreEngine,
    SCORE_DIMENSIONS,
)

from kenradar.company_research.financial_analysis.service import (
    FinancialAnalysisService,
)

__all__ = [
    "FinancialReportSelector",
    "FinancialReportSelection",
    "ParsedNotice",
    "FINANCIAL_ANALYSIS_QUESTIONS",
    "FinancialAnalysisQuestion",
    "FinancialReportParser",
    "FinancialScoreEngine",
    "SCORE_DIMENSIONS",
    "FinancialAnalysisService",
]
