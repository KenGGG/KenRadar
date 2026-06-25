# 公司研究 — 新增"财务分析 MVP"模块 实现方案（修正版）

> 编写日期: 2026-06-22
> 对应需求: Codex 任务 — 公司研究新增"财务分析 MVP"模块
> 修正内容: 报告选择逻辑、数据库设计、幂等重跑、评分体系、JSON 输出格式、Prompt 完整保留

---

## 一、背景与目标

现有"公司研究"模块（`CompanyResearchService`）上传**全量公告**（300+ PDF）到 NotebookLM，逐题回答 10 个通用问题，生成公司基本面研究。

本模块在现有系统基础上，**新增一个独立子模块**，专门做**财务分析 MVP**：

> 基于 3 份年报 + 1 份最新季报/半年报 → 生成财务分析报告 + 红旗清单 + 风险评分

### 核心差异

| 维度 | 现有公司研究 | 财务分析 MVP |
|------|-------------|-------------|
| 输入材料 | 近 3 年全部公告（最多 100 份 PDF） | 精选 3 年年报 + 1 份最新定期报告（≤10 份） |
| 问题数 | 10 个通用问题 | 11 个专用财务问题（Q11 为合并报告） |
| 输出 | 10 个问答 | 财务分析报告 + 红旗清单 + 风险评分 + JSON |
| 存储 | `company_research_answers` | `company_financial_question_answers` |
| 报告 | — | `company_financial_analysis_reports` |
| 红旗 | — | `company_financial_red_flags` |

---

## 二、现有系统分析

### 2.1 可复用的基础设施

| 组件 | 文件 | 可复用程度 |
|------|------|-----------|
| `NotebookLMClient` | `notebooklm_client.py` | **完全复用** — create/upload/wait/ask/delete |
| `NoticeDownloader` | `notice_downloader.py` | **完全复用** — PDF 下载、校验、a-stock-data 回退 |
| `fetch_individual_notices` | `akshare_provider.py` | **完全复用** — 查询公告索引 |
| `normalize_symbol` | `akshare_provider.py` | **完全复用** — 股票代码标准化 |
| `AppConfig` / `create_database` | `config.py` / `storage` | **完全复用** |
| PDF 校验逻辑 | `pdf_validator.py` | **完全复用** |
| 任务队列机制 | `handlers.py` / `outbox_consumer.py` | **完全复用** — `_enqueue_persistent_task` |

### 2.2 需要新增的能力

| 能力 | 说明 |
|------|------|
| 报告选择器 | `financial_report_selector.py` — 按标题匹配并解析报告期 |
| 财务专用 Prompt | `prompt_templates.py` — Q1-Q11 共 11 个完整 Prompt |
| NotebookLM 连续多问 | 11 题逐题执行 + 合并报告 |
| JSON 解析器 | `parser.py` — 从 Q11 回答中提取 `<FINANCIAL_JSON>` 标签包裹的结构化 JSON |
| 兜底评分引擎 | `score_engine.py` — 当 JSON 缺失或解析失败时根据红旗计算分数 |
| 数据库表 | 5 张新表 + 迁移脚本 |
| API 路由 | 6 个新端点 |
| 前端 Tab | "财务分析 MVP" 新 Tab |

---

## 三、新增文件清单

```
kenradar/company_research/financial_analysis/
  __init__.py
  report_selector.py          # 报告选择器
  prompt_templates.py         # Q1-Q11 完整 Prompt
  service.py                  # 任务编排（幂等重跑）
  parser.py                   # JSON 解析（<FINANCIAL_JSON> 标签提取）
  score_engine.py             # 兜底评分 + 7 维度评分校验

kenradar/storage/migrations/
  0005_company_financial_analysis_mvp.py   # 数据库迁移

kenradar/web/frontend/
  src/components/CompanyFinancialAnalysisMVP.tsx  # 前端新 Tab
```

### 按现有模式新增

此外，以下现有文件需要修改：

```
kenradar/web/app.py                      # 新增 API 路由
kenradar/jobs/handlers.py                # 新增任务类型分支
kenradar/web/frontend/src/components/
  CompanyResearchWorkspace.tsx           # 新增 Tab 入口
```

---

## 四、报告选择器设计

### 4.1 文件: `financial_report_selector.py`

#### 4.1.1 年报年份推导（不硬编码）

```python
def _derive_annual_years(analysis_base_year: int) -> list[int]:
    """根据分析基准年份推导最近三年年报年份。

    例: analysis_base_year=2026 → [2023, 2024, 2025]
    """
    return [analysis_base_year - 3, analysis_base_year - 2, analysis_base_year - 1]
```

用户可通过任务参数传入 `analysis_base_year`，默认取当前年份。

#### 4.1.2 公告标题解析

每条公告需解析出以下字段：

```python
@dataclass
class ParsedNotice:
    """从公告标题和日期中解析出的结构化信息。"""
    # 原始信息
    symbol: str
    stock_name: str
    notice_id: str
    notice_title: str
    notice_date: date          # 公告发布日期（从 API 获得）
    notice_url: str

    # 解析字段
    report_year: int | None        # 报告所属年份，如 2025 年年度报告 → 2025
    report_period: str | None      # 报告期类型: 'annual' | 'q1' | 'half' | 'q3'
    report_period_end: date | None # 报告期截止日: 年报→12-31, 半年报→06-30, 一季报→03-31, 三季报→09-30
    is_full_report: bool           # 是否为完整报告（而不是摘要、英文版、更正等）
    is_revised: bool               # 是否为修订版/更正后版本
    original_title: str            # 原始公告标题
```

#### 4.1.3 解析规则

```python
import re

def parse_notice_title(title: str, notice_date: date, stock_name: str) -> ParsedNotice:
    """从公告标题解析报告信息。

    解析优先级：
    1. 判断是否为完整报告（排除"摘要"、"英文版"、"取消"、"提示性公告"、"更正公告"等）
    2. 提取报告年份
    3. 判断报告期类型
    4. 判断是否为修订版
    5. 计算 report_period_end
    """

# 排除关键词（包含以下任一关键词的公告不作为完整报告）
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

# 报告期识别模式（按顺序匹配）
REPORT_PATTERNS = [
    (r"(\d{4})\s*年\s*年度报告", "annual", lambda y: date(y, 12, 31)),
    (r"(\d{4})\s*年\s*半年度报告", "half", lambda y: date(y, 6, 30)),
    (r"(\d{4})\s*年\s*一季度报告", "q1", lambda y: date(y, 3, 31)),
    (r"(\d{4})\s*年\s*第一季度报告", "q1", lambda y: date(y, 3, 31)),
    (r"(\d{4})\s*年\s*三季度报告", "q3", lambda y: date(y, 9, 30)),
    (r"(\d{4})\s*年\s*第三季度报告", "q3", lambda y: date(y, 9, 30)),
    (r"(\d{4})\s*年度报告", "annual", lambda y: date(y, 12, 31)),
]

# 修订版识别关键词
REVISION_KEYWORDS = ["修订", "更正", "更新"]
```

#### 4.1.4 最新一期定期报告选择逻辑（不是关键词优先级）

```python
def select_latest_periodic_report(
    parsed_notices: list[ParsedNotice],
    latest_annual_year: int,
    analysis_base_year: int,
) -> ParsedNotice | None:
    """选择最新一期定期报告。

    选择条件：
    1. report_period_end > 最近年报的 report_period_end（即年报年份的 12-31）
    2. 且 report_period_end <= analysis_base_year 当年（不跨年选择未来的报告）
    3. 是完整报告（is_full_report = True）
    4. 按 report_period_end 降序 → 取最大
    5. 如果 report_period_end 相同，按 notice_date 最新
    6. 只选一份
    """
```

#### 4.1.5 完整选择流程

```python
@dataclass
class FinancialReportSelection:
    symbol: str
    stock_name: str
    analysis_base_year: int
    selected_notices: list[ParsedNotice]        # 最终选中的公告列表
    missing_reports: list[str]                  # 缺失报告描述
    annual_reports_found: dict[int, ParsedNotice]  # {年份: ParsedNotice}
    periodic_report: ParsedNotice | None        # 最新一期定期报告
    total_selected: int
    over_limit: bool                             # 是否超过 max_pdfs


def select_financial_reports(
    symbol: str,
    stock_name: str,
    analysis_base_year: int,
    begin_date: str,
    end_date: str,
    max_pdfs: int = 10,
) -> FinancialReportSelection:
    """财务分析报告选择主入口。

    流程：
    1. 计算目标年报年份: [analysis_base_year-3, analysis_base_year-2, analysis_base_year-1]
    2. 调用 fetch_individual_notices() 获取全部公告
    3. 遍历公告列表，用 parse_notice_title() 解析每条公告
    4. 匹配年报：
       - 对每个目标年份，在解析后的公告中查找
       - 按 is_full_report=True、report_period='annual' 筛选
       - 同一年份如有多个匹配（修订版 > 原版），按 is_revised 降序 + notice_date 最新
       - 匹配到则选中，否则记入 missing_report_files
    5. 匹配最新一期定期报告：
       - 在最近年报年份之后查找
       - 按 report_period_end 最大 + notice_date 最新
       - 选中一份
    6. 如果 total_selected > max_pdfs，设置 over_limit=True 并提示人工检查
    7. 返回 FinancialReportSelection
    """
```

### 4.2 不考虑的排除场景（MVP 不做）

- ~~全公告关键词筛选~~（不做）
- ~~300 份 PDF 上传~~（不做）
- ~~公告优先级排序~~（不做）

---

## 五、Prompt 设计

### 5.1 文件: `prompt_templates.py`

使用与现有 `prompts.py` 相同的 `CompanyResearchQuestion` dataclass 结构：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FinancialAnalysisQuestion:
    key: str
    index: int
    title: str
    prompt: str
```

所有 11 个 Prompt **必须完整写入** `prompt_templates.py`，不得只保留标题。包括需求文档中的中文 Prompt 原文、表格格式、输出字段、缺失数据回答规则、证据要求。每个 Prompt 均已包含以下基线规则：

```python
_BASE_RULES = """你是一个上市公司财务分析助手。

请严格基于当前 NotebookLM 中已经上传的年报和定期报告回答问题，不得使用外部知识。

如果报告没有披露某个数据或事项，请明确回答"未披露"，不得猜测。

所有数据必须标注来源文件名称（年报年份 + 章节）。
"""
```

### 5.2 Prompt 列表

| Index | Key | 标题 | 输出特点 |
|---|---:|---|------|
| Q1 | `report_basis_audit` | 报告基础与审计意见 | 审计意见表格 + 定性分析 |
| Q2 | `core_financial_data` | 三张表核心数据提取 | 资产负债表 + 利润表 + 现金流量表，三大表格 |
| Q3 | `profitability` | 盈利能力与利润质量 | 盈利能力指标表 + 利润质量分析 + 风险结论表 |
| Q4 | `revenue_receivables` | 收入、回款与应收账款质量 | 收现匹配表 + 红旗表 |
| Q5 | `inventory_assets` | 存货与资产质量 | 资产质量表 + 分析判断 + 红旗表 |
| Q6 | `debt_liquidity` | 债务结构与流动性风险 | 债务结构表 + 分析判断 + 红旗表 |
| Q7 | `cashflow_repayment` | 现金流与第一还款来源 | 现金流表 + 还款来源判断 + 结论 |
| Q8 | `related_party_funds` | 关联交易、担保与资金占用 | 关联交易表 + 分析判断 + 红旗表 |
| Q9 | `data_contradiction` | 年报解释与数据矛盾校验 | 矛盾校验表 + 重点检查项 |
| Q10 | `risk_scoring` | 财务风险评分 | 7 维度评分表 + 风险层级 + 人工复核建议 |
| Q11 | `final_report` | 合并生成完整财务分析报告 | Markdown 报告 + `<FINANCIAL_JSON>` JSON |

### 5.3 Q11 输出格式（关键设计）

Q11 必须输出两部分：

**第一部分：Markdown 完整报告**（可读）
- 十三节完整结构（从 Q1-Q10 整合）
- 表格、红旗清单、评分表

**第二部分：JSON 代码块**（机器可解析）
- 使用 `<FINANCIAL_JSON>` 和 `</FINANCIAL_JSON>` 标签包裹 JSON
- 不允许使用其他 JSON 包裹方式
- JSON 遵循固定 Schema（见下文 parser.py）

Prompt 示例结构：

```python
Q11_FINAL_REPORT_PROMPT = _BASE_RULES + """

请综合前面 {previous_answers_context} 生成完整报告。

...（十三节内容要求，含表格和红旗）...

最后，必须在报告末尾输出一个 JSON 代码块，用 <FINANCIAL_JSON> 和 </FINANCIAL_JSON> 包裹：

<FINANCIAL_JSON>
{
  "symbol": "300750.SZ",
  "company_name": "宁德时代",
  "analysis_period": "2023-2026Q1",
  "financial_risk_score": 18,
  "financial_risk_tier": "B",
  "first_repayment_source": "中",
  "leasing_advice": "谨慎推进",
  "major_red_flags": ["应收账款增长快于收入","经营现金流波动"],
  "score_detail": {
    "revenue_quality": {"score": 3, "max": 15, "evidence": "...", "explanation": "...", "review_required": false},
    "profit_quality": {"score": 2, "max": 15, ...},
    "cashflow_quality": {"score": 5, "max": 20, ...},
    "asset_quality": {"score": 3, "max": 15, ...},
    "debt_liquidity": {"score": 2, "max": 15, ...},
    "related_party_funds": {"score": 1, "max": 10, ...},
    "audit_internal_control": {"score": 2, "max": 10, ...}
  },
  "red_flags": [
    {
      "flag_type": "收入与回款",
      "flag_name": "应收账款增速高于收入增速",
      "risk_level": "中",
      "evidence": "2025年应收增长25%，收入增长仅12%",
      "annual_report_explanation": "年报解释为销售规模扩大",
      "explanation_sufficient": false,
      "leasing_due_diligence_impact": "需核查回款周期",
      "required_follow_up_materials": ["应收账款账龄表","主要客户回款记录"]
    }
  ],
  "required_follow_up_materials": ["应收账款账龄表"]
}
</FINANCIAL_JSON>
"""
```

---

## 六、数据库设计

### 6.1 迁移文件: `0005_company_financial_analysis_mvp.py`

#### 表 1: `company_financial_analysis_jobs`

```sql
CREATE TABLE company_financial_analysis_jobs (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    stock_name          TEXT,
    analysis_base_year  INTEGER NOT NULL DEFAULT 2026,  -- 分析基准年份
    status              TEXT DEFAULT 'created',
    current_stage       TEXT DEFAULT 'created',
    selected_pdf_count     INTEGER DEFAULT 0,
    uploaded_source_count  INTEGER DEFAULT 0,
    ready_source_count     INTEGER DEFAULT 0,
    question_answered      INTEGER DEFAULT 0,
    question_saved         INTEGER DEFAULT 0,
    financial_risk_score   INTEGER,                -- 最终风险总分
    financial_risk_tier    TEXT,                    -- A/B/C/D/E
    score_source           TEXT,                    -- 'ai_generated' | 'fallback'
    missing_report_files   TEXT,                    -- JSON array
    notebook_id     TEXT,
    notebook_deleted BOOLEAN DEFAULT FALSE,
    auto_delete_notebook BOOLEAN DEFAULT TRUE,
    delete_local_pdfs_after_ready BOOLEAN DEFAULT FALSE,  -- 是否等待所有问答完成后再删除本地 PDF
    retry_count     INTEGER DEFAULT 0,
    last_error      TEXT,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_fin_jobs_symbol ON company_financial_analysis_jobs(symbol);
CREATE INDEX idx_fin_jobs_status ON company_financial_analysis_jobs(status);
CREATE INDEX idx_fin_jobs_created ON company_financial_analysis_jobs(created_at DESC);
```

#### 表 2: `company_financial_report_files`

```sql
CREATE TABLE company_financial_report_files (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER REFERENCES company_financial_analysis_jobs(id),
    symbol          TEXT NOT NULL,
    report_year     INTEGER,
    report_period   TEXT,           -- 'annual' | 'q1' | 'half' | 'q3'
    report_period_end DATE,        -- 报告期截止日
    report_type     TEXT,           -- 'annual_report' | 'quarterly_report' | 'semi_annual_report'
    notice_title    TEXT,
    notice_date     DATE,
    pdf_status      TEXT,           -- 'selected' | 'downloaded' | 'valid' | 'invalid' | 'missing'
    file_path       TEXT,
    file_size       INTEGER,
    file_hash       TEXT,
    final_provider  TEXT,
    download_error  TEXT,
    upload_status   TEXT,           -- 'pending' | 'uploaded' | 'ready' | 'failed'
    upload_error    TEXT,
    source_id       TEXT,
    source_title    TEXT,
    local_file_deleted BOOLEAN DEFAULT FALSE,
    local_file_deleted_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_fin_files_job ON company_financial_report_files(job_id);
CREATE INDEX idx_fin_files_symbol ON company_financial_report_files(symbol);
CREATE UNIQUE INDEX idx_fin_files_job_notice ON company_financial_report_files(job_id, notice_title);
```

#### 表 3: `company_financial_question_answers`

```sql
CREATE TABLE company_financial_question_answers (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER REFERENCES company_financial_analysis_jobs(id),
    symbol          TEXT NOT NULL,
    question_index  INTEGER NOT NULL,
    question_key    TEXT NOT NULL,
    question_title  TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    answer_markdown TEXT,
    raw_answer      TEXT,           -- 原始 API 返回（含 JSON 标签）
    status          TEXT DEFAULT 'pending',   -- 'pending' | 'asking' | 'saved' | 'failed'
    error_message   TEXT,
    conversation_id TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    saved_at        TIMESTAMP
);

CREATE INDEX idx_fin_qa_job ON company_financial_question_answers(job_id);
CREATE INDEX idx_fin_qa_symbol ON company_financial_question_answers(symbol);
CREATE UNIQUE INDEX idx_fin_qa_job_question ON company_financial_question_answers(job_id, question_key);
```

#### 表 4: `company_financial_analysis_reports`

```sql
CREATE TABLE company_financial_analysis_reports (
    id                      SERIAL PRIMARY KEY,
    job_id                  INTEGER REFERENCES company_financial_analysis_jobs(id),
    symbol                  TEXT NOT NULL,
    report_markdown         TEXT,           -- Q11 完整 Markdown 报告
    parsed_json             JSONB,          -- 从 <FINANCIAL_JSON> 标签中解析的 JSON
    raw_answer              TEXT,           -- Q11 原始回答（含标签）
    parse_success           BOOLEAN,        -- JSON 是否解析成功
    financial_risk_score    INTEGER,
    financial_risk_tier     TEXT,
    score_source            TEXT,           -- 'ai_generated' | 'fallback'
    first_repayment_source  TEXT,
    leasing_advice          TEXT,
    status                  TEXT DEFAULT 'pending',
    created_at              TIMESTAMP DEFAULT NOW(),
    saved_at                TIMESTAMP
);

CREATE INDEX idx_fin_report_job ON company_financial_analysis_reports(job_id);
CREATE UNIQUE INDEX idx_fin_report_symbol ON company_financial_analysis_reports(symbol);
```

#### 表 5: `company_financial_red_flags`

```sql
CREATE TABLE company_financial_red_flags (
    id                      SERIAL PRIMARY KEY,
    job_id                  INTEGER REFERENCES company_financial_analysis_jobs(id),
    symbol                  TEXT NOT NULL,
    flag_type               TEXT,           -- 红旗类别（如"收入与回款"等 7 维度之一）
    flag_name               TEXT,
    risk_level              TEXT,           -- '高' | '中' | '低'
    evidence                TEXT,
    annual_report_explanation TEXT,
    explanation_sufficient  BOOLEAN,
    leasing_due_diligence_impact TEXT,
    required_follow_up_materials TEXT,      -- JSON array
    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_fin_flags_job ON company_financial_red_flags(job_id);
CREATE INDEX idx_fin_flags_symbol ON company_financial_red_flags(symbol);
CREATE INDEX idx_fin_flags_level ON company_financial_red_flags(risk_level);
```

---

## 七、任务编排（service.py）

### 7.1 独立服务类

```python
class FinancialAnalysisService:
    def __init__(self, config, database=None, notebook_client=None, downloader=None):
        self.config = config
        self.database = database or create_database(config)
        self.notebook_client = notebook_client or NotebookLMClient()
        self.downloader = downloader or NoticeDownloader(config.data_dir)
        self.selector = FinancialReportSelector()
        self.parser = FinancialReportParser()
        self.score_engine = FinancialScoreEngine()
```

### 7.2 幂等重跑设计

**核心原则：每一步执行前先检查是否已完成。**

```python
async def run_job(self, job_id: int, *, progress_callback=None) -> dict:
    job = self.database.get_financial_analysis_job(job_id)
    if not job:
        raise ValueError(f"未找到财务分析任务: {job_id}")

    # 幂等检查：如果任务已经是终态，不再执行
    if job["status"] in ("completed", "failed", "partial_failed"):
        return {"ok": True, "job_id": job_id, "status": job["status"]}

    # 按 stage 判断从哪一步继续
    current = job.get("current_stage") or "created"

    stages = [
        "select_report_files",     # 1
        "download_pdfs",           # 2
        "create_notebook",         # 3
        "upload_sources",          # 4
        "wait_sources_ready",      # 5
        "delete_local_pdfs",       # 6  (可选: 由 delete_local_pdfs_after_ready 控制)
        "ask_q1",                  # 7
        "ask_q2",
        "ask_q3",
        "ask_q4",
        "ask_q5",
        "ask_q6",
        "ask_q7",
        "ask_q8",
        "ask_q9",
        "ask_q10",                 # 16
        "ask_q11_final_report",    # 17
        "parse_json",              # 18
        "save_red_flags",          # 19
        "save_score",              # 20
        "delete_notebook",         # 21
        "completed",               # 22
    ]

    # 找到当前 stage 在 stages 中的索引，跳过已完成的步骤
    try:
        start_idx = stages.index(current)
    except ValueError:
        start_idx = 0  # 未知 stage，从头开始

    # 从 start_idx 开始顺序执行
    for stage in stages[start_idx:]:
        if stage == "completed":
            break
        # 执行 stage 对应的处理函数
        await self._execute_stage(job_id, stage, job)
        # 更新 current_stage
        self.database.update_financial_analysis_job(job_id, current_stage=stage)
```

#### 7.2.1 各阶段的幂等检查逻辑

| Stage | 幂等检查条件 |
|-------|-------------|
| `select_report_files` | 如果 `company_financial_report_files` 已有该 job_id 的记录，跳过 |
| `download_pdfs` | 如果所有选中报告均有 `pdf_status='downloaded'` 或 `pdf_status='valid'`，跳过 |
| `create_notebook` | 如果 `job.notebook_id` 非空，复用已有 notebook |
| `upload_sources` | 如果所有报告文件的 `upload_status='uploaded'`，跳过 |
| `wait_sources_ready` | 如果所有上传文件的 `upload_status='ready'`，跳过 |
| `delete_local_pdfs` | 如果所有报告文件 `local_file_deleted=True`，跳过 |
| `ask_qN` | 如果 `company_financial_question_answers` 中该 `(job_id, question_key)` 已有 `status='saved'` 的记录，跳过 |
| `ask_q11_final_report` | 如果 `company_financial_analysis_reports` 已有该 job_id 且 `status='saved'`，跳过 |
| `parse_json` | 如果 `parsed_json` 非空，跳过 |
| `save_red_flags` | 如果 `company_financial_red_flags` 已有该 job_id 的记录，跳过 |
| `save_score` | 如果 `financial_risk_score` 已设置，跳过 |
| `delete_notebook` | 如果 `notebook_deleted=True`，跳过 |

### 7.3 整体流程

```
run_job(job_id):
  stage select_report_files     → report_selector.select()
  stage download_pdfs           → NoticeDownloader.download_notice_pdf()
  stage create_notebook         → NotebookLMClient.create_notebook()
  stage upload_sources          → NotebookLMClient.upload_pdf() × N
  stage wait_sources_ready      → NotebookLMClient.wait_sources_ready()

  # 本地 PDF 删除时间点可配置
  if job.delete_local_pdfs_after_ready:
      stage delete_local_pdfs   → 删除已上传的本地 PDF

  stage ask_q1..q10             → NotebookLMClient.ask_question() × 10
                                 每题保存到 company_financial_question_answers
  stage ask_q11_final_report    → 合并前 10 题回答 + 生成完整报告
                                 保存到 company_financial_analysis_reports

  # 始终在上传和问答完成后删除本地 PDF
  if not job.delete_local_pdfs_after_ready:
      stage delete_local_pdfs   → 此时删除

  stage parse_json              → parser.extract_from_financial_json_tags()
  stage save_red_flags          → 解析后保存到 company_financial_red_flags
  stage save_score              → 保存评分到 jobs + reports

  stage delete_notebook         → NotebookLMClient.delete_notebook()
```

### 7.4 Q11 合并报告 Prompt

```python
async def _ask_q11(self, job_id: int, notebook_id: str) -> NotebookAnswer:
    """Q11 合并前 10 题回答生成最终报告。"""
    # 从数据库读取前 10 题回答
    answers = self.database.list_financial_question_answers(
        job_id=job_id, limit=10
    )
    answers.sort(key=lambda a: a["question_index"])

    # 拼接上下文
    context_parts = []
    for ans in answers:
        title = ans["question_title"]
        content = ans.get("answer_markdown") or ans.get("raw_answer") or ""
        context_parts.append(f"### {title}\n\n{content}")

    context = "\n\n---\n\n".join(context_parts)

    prompt = Q11_FINAL_REPORT_PROMPT.format(
        previous_answers_context=context,
    )

    return await self.notebook_client.ask_question(notebook_id, prompt)
```

---

## 八、JSON 解析器（parser.py）

### 8.1 核心函数

```python
import re
import json

def extract_from_financial_json_tags(markdown_text: str) -> dict | None:
    """从 Q11 回答中提取 <FINANCIAL_JSON>...</FINANCIAL_JSON> 标签包裹的 JSON。

    Args:
        markdown_text: Q11 的完整回答（Markdown）

    Returns:
        解析成功的 dict，或 None（解析失败）
    """
    pattern = r'<FINANCIAL_JSON>\s*([\s\S]*?)\s*</FINANCIAL_JSON>'
    match = re.search(pattern, markdown_text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def extract_red_flags(report_json: dict) -> list[dict]:
    """从解析后的 JSON 中提取红旗列表。"""
    return report_json.get("red_flags", [])


def extract_score_detail(report_json: dict) -> dict:
    """从解析后的 JSON 中提取 7 维度评分明细。"""
    return report_json.get("score_detail", {})
```

### 8.2 JSON 失败处理

```python
def try_parse_with_fallback(markdown_text: str, raw_answer: str) -> dict:
    """尝试解析 JSON，失败时返回 fallback 结构。

    此函数始终返回一个包含 score_source 字段的字典。
    """
    result = extract_from_financial_json_tags(markdown_text)

    if result is not None:
        result["score_source"] = "ai_generated"
        return result

    # 解析失败：返回空结构，由 score_engine 兜底
    return {
        "symbol": "",
        "company_name": "",
        "financial_risk_score": None,
        "financial_risk_tier": None,
        "score_detail": {},
        "red_flags": [],
        "required_follow_up_materials": [],
        "score_source": "fallback",
        "_parse_error": True,
        "_raw_answer_saved": True,
    }
```

### 8.3 JSON Schema（固定合约）

Q11 输出的 JSON 必须严格遵循以下 Schema（作为 Prompt 的一部分写入）：

```json
{
  "symbol": "股票代码",
  "company_name": "公司名称",
  "analysis_period": "分析期间",
  "financial_risk_score": 0,         // 整数 0-100
  "financial_risk_tier": "A/B/C/D/E",
  "first_repayment_source": "高/中/低",
  "leasing_advice": "可推进/谨慎推进/暂缓推进/不建议推进",
  "major_red_flags": ["主要红旗摘要"],
  "score_detail": {
    "revenue_quality": {
      "score": 0,           // 整数 0-15
      "max": 15,
      "evidence": "数据证据",
      "explanation": "评分解释",
      "review_required": false   // 是否建议人工复核
    },
    "profit_quality": {
      "score": 0,           // 0-15
      "max": 15,
      "evidence": "",
      "explanation": "",
      "review_required": false
    },
    "cashflow_quality": {
      "score": 0,           // 0-20
      "max": 20,
      "evidence": "",
      "explanation": "",
      "review_required": false
    },
    "asset_quality": {
      "score": 0,           // 0-15
      "max": 15,
      "evidence": "",
      "explanation": "",
      "review_required": false
    },
    "debt_liquidity": {
      "score": 0,           // 0-15
      "max": 15,
      "evidence": "",
      "explanation": "",
      "review_required": false
    },
    "related_party_funds": {
      "score": 0,           // 0-10
      "max": 10,
      "evidence": "",
      "explanation": "",
      "review_required": false
    },
    "audit_internal_control": {
      "score": 0,           // 0-10
      "max": 10,
      "evidence": "",
      "explanation": "",
      "review_required": false
    }
  },
  "red_flags": [
    {
      "flag_type": "红旗类别（7 维度之一）",
      "flag_name": "红旗事项名称",
      "risk_level": "高/中/低",
      "evidence": "数据依据",
      "annual_report_explanation": "年报解释",
      "explanation_sufficient": false,
      "leasing_due_diligence_impact": "融资租赁影响",
      "required_follow_up_materials": ["需补充的核查材料"]
    }
  ],
  "required_follow_up_materials": ["整体补充核查材料清单"]
}
```

---

## 九、评分引擎（score_engine.py）

### 9.1 双轨策略

```
1. 优先使用 NotebookLM 输出的 JSON 评分：
   - 从 <FINANCIAL_JSON> 标签解析得到 score_detail
   - 各维度得分直接入库
   - score_source = 'ai_generated'

2. 若 JSON 缺失或解析失败，fallback 兜底：
   - 从 Q10 回答中提取红旗数量和等级
   - 按公式计算：高危红旗 × 15 + 中危红旗 × 8 + 低危红旗 × 3
   - 上限 100 分
   - score_source = 'fallback'

3. 无论哪种方式，都记录 score_source：
   - 数据库字段 company_financial_analysis_jobs.score_source
   - 数据库字段 company_financial_analysis_reports.score_source
```

### 9.2 7 维度评分规则

| 评分维度 | 满分 | 0分基准 | 满分条件 |
|---------|:---:|---------|---------|
| 收入与回款质量 | 15 | 收入、应收、销售收现基本匹配 | 收入增长纯赊销，经营现金流弱，坏账风险明显 |
| 利润质量 | 15 | 利润主要来自主营业务 | 利润严重依赖非经常性损益，主营盈利能力不足 |
| 现金流质量 | 20 | 经营现金流稳定，支持净利润和偿债 | 经营现金流持续为负 |
| 资产质量 | 15 | 应收、存货、固定资产等稳定 | 资产虚高、减值不足、长期不转固等重大隐患 |
| 债务与流动性 | 15 | 有息债务合理，货币资金覆盖能力较强 | 短期偿债压力显著，期限错配，依赖再融资 |
| 关联交易、担保和资金占用 | 10 | 规模较小，无明显异常 | 非经营性资金占用、违规担保 |
| 审计、内控和信息披露质量 | 10 | 标准无保留意见，内控无重大缺陷 | 非标意见、重大内控缺陷、重大差错、频繁换审计机构 |

### 9.3 评分层级映射

| 分数范围 | 层级 | 含义 |
|---------|------|------|
| 0–15 | A | 财务质量较好，暂无明显红旗 |
| 16–35 | B | 存在一般性波动，解释基本充分 |
| 36–55 | C | 存在若干风险信号，需要补充核查 |
| 56–75 | D | 存在重大财务隐患 |
| 76–100 | E | 存在严重财务真实性疑点或偿债压力 |

### 9.4 核心函数

```python
class FinancialScoreEngine:

    def compute_from_json(self, score_detail: dict) -> int:
        """从 JSON 的 score_detail 计算总分。"""
        total = 0
        for dim in ["revenue_quality", "profit_quality", "cashflow_quality",
                     "asset_quality", "debt_liquidity", "related_party_funds",
                     "audit_internal_control"]:
            total += score_detail.get(dim, {}).get("score", 0)
        return min(total, 100)

    def fallback_score(self, red_flags: list[dict]) -> int:
        """当 JSON 解析失败时，根据红旗计算兜底分数。

        高危 = 15分，中危 = 8分，低危 = 3分，上限100分。
        """
        weights = {"高": 15, "中": 8, "低": 3}
        total = sum(weights.get(flag.get("risk_level", "低"), 3)
                    for flag in red_flags)
        return min(total, 100)

    def tier_from_score(self, score: int) -> str:
        if score <= 15: return "A"
        if score <= 35: return "B"
        if score <= 55: return "C"
        if score <= 75: return "D"
        return "E"

    def needs_human_review(self, score_detail: dict) -> list[str]:
        """检查各维度是否需要人工复核。"""
        needs = []
        for dim_name, dim_key in [
            ("收入与回款质量", "revenue_quality"),
            ("利润质量", "profit_quality"),
            ("现金流质量", "cashflow_quality"),
            ("资产质量", "asset_quality"),
            ("债务与流动性", "debt_liquidity"),
            ("关联交易和资金占用", "related_party_funds"),
            ("审计内控", "audit_internal_control"),
        ]:
            detail = score_detail.get(dim_key, {})
            if detail.get("review_required"):
                needs.append(dim_name)
        return needs
```

---

## 十、API 设计

在 `app.py` 中新增 6 个端点：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/company-research/financial-analysis/preview` | 预览：解析股票→选择报告→返回选中报告列表 |
| POST | `/api/company-research/financial-analysis/tasks` | 创建任务并加入队列 |
| GET | `/api/company-research/financial-analysis/jobs` | 查询任务列表（支持 `symbol` 过滤） |
| GET | `/api/company-research/financial-analysis/jobs/{job_id}` | 查询单任务详情（含报告文件、逐题回答、最终报告） |
| GET | `/api/company-research/financial-analysis/stocks/{symbol}` | 查询某只股票的最新财务分析结果（含报告、红旗、评分） |
| GET | `/api/company-research/financial-analysis/ranking` | 评分排名（按风险分升序） |

### 预览接口: POST `/financial-analysis/preview`

请求：
```json
{
  "symbol": "300750.SZ",
  "analysis_base_year": 2026
}
```

响应：
```json
{
  "ok": true,
  "symbol": "300750.SZ",
  "stock_name": "宁德时代",
  "analysis_base_year": 2026,
  "selected_reports": [
    {
      "report_year": 2023,
      "report_period": "annual",
      "report_period_end": "2023-12-31",
      "report_type": "annual_report",
      "notice_title": "2023年年度报告",
      "notice_date": "2024-04-20",
      "found": true,
      "is_revised": false
    },
    {
      "report_year": 2024,
      "report_period": "annual",
      "report_period_end": "2024-12-31",
      "report_type": "annual_report",
      "notice_title": "2024年年度报告",
      "notice_date": "2025-04-15",
      "found": true,
      "is_revised": false
    },
    {
      "report_year": 2025,
      "report_period": "annual",
      "report_period_end": "2025-12-31",
      "report_type": "annual_report",
      "notice_title": "2025年年度报告",
      "notice_date": "2026-03-10",
      "found": true,
      "is_revised": false
    },
    {
      "report_year": 2026,
      "report_period": "q1",
      "report_period_end": "2026-03-31",
      "report_type": "quarterly_report",
      "notice_title": "2026年一季度报告",
      "notice_date": "2026-04-29",
      "found": true,
      "is_revised": false
    }
  ],
  "missing_reports": [],
  "total_selected": 4,
  "over_limit": false,
  "all_notices_count": 106
}
```

### 队列处理: `handlers.py`

```python
if task_type == "company_financial_analysis":
    from kenradar.company_research.financial_analysis.service import FinancialAnalysisService
    service = FinancialAnalysisService(workflow.config, workflow.database)
    return await service.run_job(int(payload["job_id"]), progress_callback=progress_callback)
```

---

## 十一、前端设计

### 11.1 Tab 入口

在 `CompanyResearchWorkspace.tsx` 中，已有 `'query' | 'download' | 'notebooklm'` 三个 Tab，新增第 4 个：

```tsx
const [activeTab, setActiveTab] = useState<'query' | 'download' | 'notebooklm' | 'financial'>('query');
```

Tab 按钮（保持与现有一致的 UI 风格）：

```tsx
<button
  onClick={() => setActiveTab('financial')}
  className={`rounded-md px-3 py-1.5 ${activeTab === 'financial' ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-50'}`}
>
  财务分析 MVP
</button>
```

### 11.2 组件文件

建议新开文件 `src/components/CompanyFinancialAnalysisMVP.tsx`，避免 `CompanyResearchWorkspace.tsx` 过于臃肿。

页面分为 6 个区域：

```
┌─ 任务配置 ───────────────────────────────────────────┐
│  股票代码 [300750.SZ]  分析基准年份 [2026]            │
│  ☑ 自动选择近三年年报  ☑ 自动选择最新一期季报/半年报   │
│  ☑ 完成后删除 NotebookLM                              │
│  [预览报告文件] [开始执行]                             │
└──────────────────────────────────────────────────────┘

┌─ 报告文件预览 ──────────────────────────────────────┐
│  报告类型  年份  报告期  截止日  公告标题        状态  │
│  年报      2023  年度    12-31  2023年年度报告   ✅   │
│  年报      2024  年度    12-31  2024年年度报告   ✅   │
│  年报      2025  年度    12-31  2025年年度报告   ✅   │
│  季报      2026  Q1      03-31  2026年一季度报告  ✅  │
└──────────────────────────────────────────────────────┘

┌─ 逐题回答 ──────────────────────────────────────────┐
│  Q1  报告基础与审计意见                   ✅ saved   │
│  Q2  三张表核心数据提取                   ✅ saved   │
│  ...                                          ...   │
│  Q10 财务风险评分                         ✅ saved   │
└──────────────────────────────────────────────────────┘

┌─ 财务分析报告 ───────────────────────────────────────┐
│  (Markdown 渲染，复用 MarkdownContent 组件)            │
└──────────────────────────────────────────────────────┘

┌─ 财务红旗清单 ───────────────────────────────────────┐
│  序号 维度  红旗事项  风险等级  证据  年报解释  融资影响 │
└──────────────────────────────────────────────────────┘

┌─ 财务风险评分 ───────────────────────────────────────┐
│  评分维度              满分  得分  证据        需复核   │
│  收入与回款质量          15   3    ...        □       │
│  利润质量               15   2    ...        □       │
│  现金流质量             20   5    ...        □       │
│  资产质量               15   3    ...        □       │
│  债务与流动性           15   2    ...        □       │
│  关联交易和资金占用      10   1    ...        □       │
│  审计、内控和信息披露    10   2    ...        □       │
│  合计                 100   xx                         │
│                                                       │
│  评分来源: AI 生成 / 兜底计算                           │
│  风险层级: B (16-35分) 存在一般性波动                   │
│  第一还款来源稳定性: 中                                │
│  融资租赁准入建议: 谨慎推进                            │
│  建议人工复核维度: [收入与回款质量]                     │
└──────────────────────────────────────────────────────┘
```

### 11.3 与现有组件的 UI 复用

| 现有组件 | 复用方式 |
|----------|----------|
| `MarkdownContent` | 直接复用，渲染报告和问题回答 |
| `statusClass` 函数 | 直接复用 |
| `Field` 组件 | 直接复用 |
| `StatusItem` 组件 | 直接复用 |

---

## 十二、实施顺序

### 第一阶段：报告选择器验收（优先完成）

| 序号 | 任务 | 文件 |
|:---:|------|------|
| 1 | 创建 `financial_analysis/__init__.py` | 空包初始化 |
| 2 | 实现 `report_selector.py` | 完整解析逻辑 |
| 3 | 编写验收脚本: 对 300750.SZ 调用 select_financial_reports() | 手动验证 |

**第一阶段验收标准（300750.SZ）：**
- 正确选出 2023、2024、2025 年年度报告
- 正确选出 2026 年一季度报告（或半年报告）
- 不会误选"年度报告摘要"
- 不会误选"英文版"
- `missing_reports` 为空
- `total_selected` = 4

### 第二阶段：后端核心

| 序号 | 任务 | 文件 |
|:---:|------|------|
| 4 | 实现 `prompt_templates.py` | 11 个完整 Prompt |
| 5 | 创建数据库迁移 `0005` | 5 张新表 + 索引 + 约束 |
| 6 | 实现 `service.py`（含幂等逻辑） | Q1-Q10 + Q11 编排 |
| 7 | 实现 `parser.py` | `<FINANCIAL_JSON>` 提取 + fallback |
| 8 | 实现 `score_engine.py` | 7 维度评分 + 兜底计算 |
| 9 | 新增 `app.py` 路由 | 6 个端点 |
| 10 | 新增 `handlers.py` 分支 | 任务队列 |

### 第三阶段：前端

| 序号 | 任务 | 文件 |
|:---:|------|------|
| 11 | 创建 `CompanyFinancialAnalysisMVP.tsx` | 新组件 |
| 12 | 修改 `CompanyResearchWorkspace.tsx` | 新增 Tab |

### 第四阶段：全流程验证

| 序号 | 任务 | 预期 |
|:---:|------|------|
| 13 | 运行 `300750.SZ` 全流程 | Q1-Q11 通过，报告+红旗+评分完整 |
| 14 | 检查数据库 5 张表 | 数据完整，索引生效 |
| 15 | 检查前端展示 | 6 个区域全部正常 |
| 16 | 确认 NotebookLM 已删除 | `notebook_deleted=True` |
| 17 | 重新执行相同任务 | 幂等，不重复处理 |

---

## 十三、现有文件修改清单

| 文件 | 修改内容 | 影响范围 |
|------|----------|----------|
| `kenradar/web/app.py` | 新增 6 个 `/api/.../financial-analysis/...` 路由 | 后端 API |
| `kenradar/jobs/handlers.py` | 新增 `company_financial_analysis` 任务类型分支 | 任务队列 |
| `kenradar/storage/pg_database.py` | 新增 5 组 CRUD 方法 + 表创建 | 数据库层 |
| `kenradar/storage/database.py` | 新增抽象方法签名（可选） | 抽象层 |
| `kenradar/web/frontend/src/components/CompanyResearchWorkspace.tsx` | 新增第 4 个 Tab 按钮 | 前端导航 |
| `kenradar/web/app.py`（`_enqueue_persistent_task` 附近） | 新增路由处理方法 | 后端路由 |

---

## 十四、不需要修改的文件

| 文件 | 理由 |
|------|------|
| `notebooklm_client.py` | 完全复用，无需修改 |
| `notice_downloader.py` | 完全复用 |
| `pdf_validator.py` | 完全复用 |
| `akshare_provider.py` | 仅使用现有函数 `fetch_individual_notices` 和 `normalize_symbol` |
| `prompts.py` | 本模块使用独立的 `prompt_templates.py` |
| `service.py` (原有) | 本模块使用独立的 `financial_analysis/service.py` |
| 任何前端依赖 | 无需新增 npm 包，`react-markdown` + `remark-gfm` 已安装 |

---

## 十五、验证标准

### 15.1 报告选择器验收（第一阶段）

对 `300750.SZ`，`analysis_base_year=2026`：

| 检查项 | 预期 |
|--------|------|
| 2023 年年度报告 | ✅ 正确选中 |
| 2024 年年度报告 | ✅ 正确选中 |
| 2025 年年度报告 | ✅ 正确选中 |
| 2026 年一季度报告 | ✅ 正确选中 |
| 2023 年年度报告摘要 | ⛔ 不会误选 |
| 2025 年年度报告英文版 | ⛔ 不会误选 |
| 年度报告更正式 | ✅ 优先选中修订版 |
| missing_reports | 为空 |
| total_selected | 4 |

### 15.2 全流程验证（第三阶段）

```
1. POST preview 返回 4 份正确报告
2. 创建任务后 job 状态进入 select_report_files
3. PDF 下载成功，pdf_status='valid'
4. NotebookLM 上传成功，source ready
5. Q1-Q10 连续提问，每题 status='saved'
6. Q11 生成完整报告 + <FINANCIAL_JSON> JSON
7. JSON 解析成功，parse_success=True
8. 红旗清单入库
9. 7 维度风险评分 + 层级入库
10. score_source 正确记录
11. NotebookLM 已删除
12. 前端展示全部 6 个区域
```

### 15.3 幂等重跑验证

```
1. 重新调用同一 job_id 的 run_job
2. 检查 report_selector：跳过（已有 report_files 记录）
3. 检查 download_pdfs：跳过（所有文件已下载）
4. 检查 create_notebook：跳过（notebook_id 已存在）
5. 检查 upload_sources：跳过（已上传）
6. 检查 ask_q1-q10：跳过（所有 question_key 已 saved）
7. 检查 ask_q11：跳过（final report 已保存）
8. 检查 parse_json：跳过（parsed_json 已存在）
9. 检查 save_red_flags：跳过（已有红旗记录）
10. 检查 save_score：跳过（score 已设置）
11. 检查 delete_notebook：跳过（已删除）
```

### 15.4 边界情况

```
1. 某份年报缺失 → missing_report_files 记录该年份，继续执行
2. 无最新定期报告 → missing_report_files 记录，继续执行
3. 选中超过 10 份 → over_limit=True，终止并提示人工检查
4. JSON 解析失败 → 保存 raw_answer，fallback_score 兜底，score_source='fallback'
5. 重新执行 → 幂等跳过已完成步骤
6. NotebookLM 超时 → 复用现有 wait 超时机制 + 重试
```
