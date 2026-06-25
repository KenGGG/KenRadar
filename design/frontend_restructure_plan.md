# 公司研究平台第一期前端重构 — 实施计划（修正版）

> 编写日期: 2026-06-23
> 目标: 将 4-Tab 页面重构为单页工作台，不改后端
> 修正: CompanyFinancialAnalysisMVP 拆出子组件，不整体嵌入

---

## 一、现有代码分析

### 1.1 CompanyResearchWorkspace.tsx（~964 行）

| 区域 | 行号 | 功能 |
|------|:----:|------|
| Header + Tab 导航 | 168-221 | 4 个 Tab 按钮 + 标题 |
| query Tab | 222-291 | 股票搜索 + 个股概览 + 问答卡片 + PDF 表格 |
| download Tab | 292-393 | 任务配置表单 + 预览 + BatchCard + EventLog |
| notebooklm Tab | 394-411 | NotebookLM 状态 + 笔记本管理 + 清理工具 |
| `NotebookLMStatusCard` | 412-493 | 认证状态组件 |
| `PdfPathCard` | 495-513 | PDF 路径说明 |
| `NotebookTable` | 515-578 | 笔记本表格 |
| `StatusItem` | 580-588 | 单项展示 |
| `Field` | 589-597 | 表单字段 |
| `getStageLabel` 等 | 620-668 | 阶段映射工具函数 |
| `BatchCard` | 670-754 | 通用研究批次卡片 |
| `JobStageCard` | 756-823 | 通用研究任务阶段视图 |
| `EventLog` | 825-889 | 事件日志 |
| `PdfTable` | 891-938 | PDF 明细表（可折叠） |
| `MarkdownContent` | 940-964 | Markdown 渲染 |

### 1.2 CompanyFinancialAnalysisMVP.tsx（~635 行）

| 区域 | 行号 | 功能 |
|------|:----:|------|
| ScoreCard 子组件 | 172-217 | 评分展示（可独立导出） |
| 任务配置 + 启动 | 257-326 | 股票代码、年份、预览/开始/刷新 |
| 报告文件预览 | 327-390 | 选中报告列表 |
| 任务列表 | 391-455 | 财务分析任务表 |
| 逐题回答 | 456-493 | Q1-Q11 回答 |
| 最终报告 | 494-550 | 财务分析报告 + Markdown 渲染 |
| 红旗清单 | 551-578 | 红旗表 |
| 风险评分 | 580-590 | ScoreCard |
| `MarkdownContent` | 611-635 | Markdown 渲染 |

### 1.3 现有 API 清单（不改）

| 用途 | API 路径 |
|------|---------|
| 通用研究预览 | `POST /api/company-research/tasks/preview` |
| 通用研究创建 | `POST /api/company-research/tasks` |
| 通用研究任务列表 | `GET /api/company-research/jobs` |
| 通用研究批次详情 | `GET /api/company-research/batches/{id}` |
| 个股研究结果 | `GET /api/company-research/stocks/{symbol}/answers` |
| 财务分析预览 | `POST /api/company-research/financial-analysis/preview` |
| 财务分析创建 | `POST /api/company-research/financial-analysis/tasks` |
| 财务分析任务列表 | `GET /api/company-research/financial-analysis/jobs` |
| 财务分析任务详情 | `GET /api/company-research/financial-analysis/jobs/{id}` |
| 个股财务结果 | `GET /api/company-research/financial-analysis/stocks/{symbol}` |
| 财务评分排名 | `GET /api/company-research/financial-analysis/ranking` |
| NotebookLM 状态 | `GET /api/company-research/notebooklm/status` |
| NotebookLM 笔记本 | `GET /api/company-research/notebooklm/notebooks` |
| NotebookLM 重登 | `POST /api/company-research/notebooklm/relogin` |
| 清理 Notebook | `POST /api/company-research/notebooks/cleanup` |
| 清理本地 PDF | `POST /api/company-research/pdfs/cleanup-local` |

---

## 二、修改文件范围

### 2.1 修改 2 个前端文件

```
kenradar/web/frontend/src/components/
  CompanyResearchWorkspace.tsx      ← 主要重构：4 Tab → 4 区块
  CompanyFinancialAnalysisMVP.tsx   ← 拆分子组件导出，不改默认行为
```

### 2.2 不修改的文件（后端 + 基础设施）

- `kenradar/web/app.py`
- `kenradar/company_research/financial_analysis/service.py`
- `kenradar/company_research/financial_analysis/prompt_templates.py`
- `kenradar/company_research/service.py`
- `kenradar/company_research/prompts.py`
- `kenradar/storage/pg_database.py`
- `kenradar/storage/migrations/`
- `kenradar/jobs/handlers.py`
- `kenradar/web/frontend/src/types.ts`（如编译必须做最小补充）
- `kenradar/web/frontend/src/App.tsx`

---

## 三、第一步：改造 CompanyFinancialAnalysisMVP.tsx

### 3.1 拆分子组件并导出

```tsx
// ── 导出子组件 ──────────────────────────────────────
export function FinAnalysisLauncher(props: {
  symbol: string;
  onSymbolChange: (s: string) => void;
  autoDelete: boolean;
  onAutoDeleteChange: (v: boolean) => void;
  onPreview: () => void;
  onStart: () => void;
  onRefresh: () => void;
  previewResult: FinPreviewResult | null;
}) { /* 启动面板：股票代码 + 年份 + 按钮 + 预览 */ }

export function FinAnalysisJobList(props: {
  jobs: FinJob[];
  onSelectJob?: (jobId: number) => void;
  selectedJobId?: number | null;
}) { /* 财务任务表格 */ }

export function FinAnalysisResultPanel(props: {
  report: FinReport | null;
  answers: FinAnswer[];
  redFlags: FinRedFlag[];
  reportFiles: FinReportFile[];
  expandedSection: string | null;
  onToggleSection: (key: string) => void;
  onLoadJobDetail?: (jobId: number) => void;
}) { /* 报告文件 + 逐题回答 + 最终报告 + 红旗 + 评分 */ }

export { FinScoreCard }  // 原 ScoreCard 组件改名导出
```

### 3.2 保持默认导出不变

```tsx
export default function CompanyFinancialAnalysisMVP() {
  // 调用内部子组件，保持原完整页面
  return (
    <YourOriginalJSXUsingSubComponents />
  );
}
```

### 3.3 实现原则

- 保留所有现有 API 调用逻辑、state、handler
- 子组件只做展示（props 驱动），状态由父组件或原组件管理
- 默认导出的 `CompanyFinancialAnalysisMVP` 行为完全不变
- 不改变财务分析后端协议

---

## 四、第二步：重构 CompanyResearchWorkspace.tsx

### 4.1 State 变更

**移除：**
```ts
const [activeTab, setActiveTab] = useState<'query' | 'download' | 'notebooklm' | 'financial'>('query');
```

**新增：**
```ts
const [activeResearchMode, setActiveResearchMode] = useState<'general' | 'financial'>('general');
const [expandedAnswers, setExpandedAnswers] = useState<Record<string, boolean>>({});
const [settingsExpanded, setSettingsExpanded] = useState(false);
```

**保留**所有现有 state 和 handler（`loadStock`、`loadJobs`、`preview`、`startTask`、`cleanupNotebooks` 等）。

### 4.2 移除 Tab 导航

删除：
- Tab 按钮组（`<button onClick={() => setActiveTab('query')}>` 等）
- Tab 条件渲染（`activeTab === 'query' ? ...` 三元表达式）

### 4.3 新页面架构

```
┌─────────────────────────────────────────────────────┐
│  公司研究平台                                        │
│  研究模式: ● 通用公告研究 ○ 财务风险分析 ○ 自定义     │
├─────────────────────────────────────────────────────┤
│  [① 发起研究]                                        │
│    通用模式 → 原 download Tab 表单                    │
│    财务模式 → FinAnalysisLauncher 组件                │
│    预览区 / 执行选项 / 刷新按钮                        │
├─────────────────────────────────────────────────────┤
│  [② 研究进度]                                        │
│    [通用公告研究] badge                               │
│    BatchCard / JobStageCard（原逻辑）                 │
│    [财务风险分析] badge                               │
│    FinAnalysisJobList 组件                            │
│    EventLog（可折叠）                                 │
├─────────────────────────────────────────────────────┤
│  [③ 研究成果]                                        │
│    搜索栏（全宽）                                     │
│    个股概览 StatBar（grid）                           │
│    财务评分摘要 FinScoreCard（如有）                   │
│    问答卡片（默认折叠，expandedAnswers 控制）          │
│    PDF 明细 PdfTable（可折叠）                        │
├─────────────────────────────────────────────────────┤
│  [④ 系统设置]（默认折叠）                             │
│    NotebookLMStatusCard / NotebookTable              │
│    PdfPathCard / 清理工具                             │
└─────────────────────────────────────────────────────┘
```

---

## 五、逐区块实施细节

### 区块 ①：发起研究

#### 研究模式选择器

```tsx
<div className="flex items-center gap-4 mb-4">
  <label className="flex items-center gap-2 cursor-pointer">
    <input type="radio" name="researchMode" checked={activeResearchMode === 'general'}
      onChange={() => setActiveResearchMode('general')} />
    <span className="font-medium">通用公告研究（10题）</span>
  </label>
  <label className="flex items-center gap-2 cursor-pointer">
    <input type="radio" name="researchMode" checked={activeResearchMode === 'financial'}
      onChange={() => setActiveResearchMode('financial')} />
    <span className="font-medium">财务风险分析（11题）</span>
  </label>
  <label className="flex items-center gap-2 cursor-not-allowed opacity-50">
    <input type="radio" disabled />
    <span>自定义问题集（第二期）</span>
  </label>
</div>
```

#### 通用模式（activeResearchMode === 'general'）

直接复用现有 download Tab 中的 JSX 区块：
- 开始日期 / 结束日期
- 处理模式 / 股票代码 / 公告类型 / 执行模式
- 自动删除 checkbox
- 预览任务按钮 → 调用通用 `preview()` handler
- 开始执行按钮 → 调用通用 `startTask()` handler
- 预览 stocks 列表
- 刷新进度按钮

#### 财务模式（activeResearchMode === 'financial'）

```tsx
<FinAnalysisLauncher
  symbol={financialSymbol}
  onSymbolChange={setFinancialSymbol}
  autoDelete={finAutoDelete}
  onAutoDeleteChange={setFinAutoDelete}
  onPreview={handleFinPreview}
  onStart={handleFinStart}
  onRefresh={handleFinRefresh}
  previewResult={finPreviewResult}
/>
```

`FinAnalysisLauncher` 从 `CompanyFinancialAnalysisMVP.tsx` 拆出，其内部逻辑（调用财务分析预览/创建 API）保持不变。

### 区块 ②：研究进度

```tsx
{/* 通用公告研究 */}
<div className="mb-4">
  <h3 className="flex items-center gap-2 text-sm font-semibold mb-3">
    <span className="rounded bg-blue-100 text-blue-700 px-2 py-0.5 text-xs">通用公告研究</span>
  </h3>
  {/* 原 batches.map(BatchCard) 逻辑 */}
  {batches.length > 0 ? (...)
   : jobs.length > 0 ? groupJobsByBatch(jobs).map(...)
   : <p className="text-sm text-zinc-400">暂无通用研究任务</p>
  }
</div>

{/* 财务风险分析 */}
<div className="mb-4">
  <h3 className="flex items-center gap-2 text-sm font-semibold mb-3">
    <span className="rounded bg-emerald-100 text-emerald-700 px-2 py-0.5 text-xs">财务风险分析</span>
  </h3>
  <FinAnalysisJobList
    jobs={finJobs}
    onSelectJob={handleFinJobSelect}
    selectedJobId={selectedFinJobId}
  />
</div>

{/* 事件日志 */}
<EventLog jobs={jobs} expanded={...} onToggle={...} />
```

**关键：** 不在区块 ② 使用 `<CompanyFinancialAnalysisMVP section="jobs" />` 这种 prop 控制方式，而是直接用 `FinAnalysisJobList` 子组件，避免模态渲染。

### 区块 ③：研究成果

```tsx
{/* 搜索栏 */}
<div className="flex gap-3">
  <input value={query} onChange={e => setQuery(e.target.value)}
    className="flex-1 h-10 rounded border border-zinc-200 px-3 ..." placeholder="股票代码 / 名称" />
  <button onClick={() => withError(() => loadStock())}
    className="inline-flex h-10 items-center gap-2 rounded bg-zinc-900 px-4 text-white ...">
    查询
  </button>
</div>

{/* 个股概览 StatBar */}
{summary && (
  <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
    <StatCard label="股票代码" value={summary?.symbol || '-'} />
    <StatCard label="股票名称" value={summary?.stock_name || '-'} />
    <StatCard label="本地 PDF" value={summary?.local_pdf_count ?? 0} />
    <StatCard label="已回答" value={`${savedCount}/10`} />
    <StatCard label="状态" value={summary?.status || '-'} mono />
    <StatCard label="更新" value={summary?.last_researched_at?.slice(0,10) || '-'} />
  </div>
)}

{/* StatCard 内联组件 */}
function StatCard({ label, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="rounded border border-zinc-100 bg-zinc-50 px-3 py-3">
      <div className="text-xs text-zinc-400">{label}</div>
      <div className={`mt-1 text-sm font-medium text-zinc-900 ${mono ? 'font-mono' : ''}`}>{String(value)}</div>
    </div>
  );
}

{/* 财务评分摘要（如有） */}
{finReport && (
  <FinScoreCard ... />
)}

{/* 问答卡片（默认折叠） */}
{answers.map(answer => (
  <div key={answer.question_key} className="rounded-lg border border-zinc-200 bg-white">
    <button onClick={() => toggleAnswerExpanded(answer.question_key)}
      className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50">
      <div className="flex items-center gap-3">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs text-white">
          {answer.question_index}
        </span>
        <span className="text-sm font-medium">{answer.question_title}</span>
        <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(answer.status)}`}>
          {answer.status}
        </span>
      </div>
      {expandedAnswers[answer.question_key] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
    </button>
    {expandedAnswers[answer.question_key] && (
      <div className="border-t border-zinc-100 p-5">
        <MarkdownContent text={answer.answer_markdown || answer.raw_answer || '暂无回答'} />
        <div className="mt-4 text-xs text-zinc-400">
          <span>生成: {answer.generated_at || '-'}</span>
          <span className="ml-4">保存: {answer.saved_at || '-'}</span>
        </div>
      </div>
    )}
  </div>
))}

{/* PDF 明细 */}
<PdfTable pdfs={pdfs} />
```

#### toggle 函数

```ts
function toggleAnswerExpanded(answerKey: string) {
  setExpandedAnswers(prev => ({
    ...prev,
    [answerKey]: !prev[answerKey],
  }));
}
```

### 区块 ④：系统设置

```tsx
<div className="rounded-lg border border-zinc-200 bg-white">
  <button onClick={() => setSettingsExpanded(!settingsExpanded)}
    className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50">
    <div className="flex items-center gap-2 text-sm font-semibold">
      <Settings className="h-4 w-4" />系统设置
    </div>
    {settingsExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
  </button>
  {settingsExpanded && (
    <div className="border-t border-zinc-100 p-5 space-y-4">
      <NotebookLMStatusCard ... />
      <PdfPathCard />
      <NotebookTable ... />
      <div className="flex flex-wrap gap-3">
        <button onClick={withError(cleanupNotebooks)} className="...">清理 Notebook</button>
        <button onClick={withError(cleanupLocalPdfs)} className="...">清理本地 PDF</button>
        <button onClick={() => { withError(loadNotebookStatus); withError(loadNotebooks); }} className="...">刷新状态</button>
      </div>
    </div>
  )}
</div>
```

---

## 六、组件复用对照表

| 原组件 | 新位置 | 复用方式 |
|--------|--------|----------|
| `NotebookLMStatusCard` | 区块 ④ | 完全复用 |
| `PdfPathCard` | 区块 ④ | 完全复用 |
| `NotebookTable` | 区块 ④ | 完全复用 |
| `StatusItem` | 区块 ④ | 完全复用 |
| `Field` | 区块 ① | 完全复用 |
| `BatchCard` | 区块 ② | 完全复用 |
| `JobStageCard` | 区块 ② | 完全复用 |
| `EventLog` | 区块 ② | 完全复用 |
| `PdfTable` | 区块 ③ | 完全复用 |
| `MarkdownContent` | 区块 ③ | 完全复用 |
| `ScoreCard / FinScoreCard` | 区块 ③ | 导出为子组件 |
| `FinAnalysisLauncher` | 区块 ①（财务模式） | 从财务分析组件拆出 |
| `FinAnalysisJobList` | 区块 ② | 从财务分析组件拆出 |

---

## 七、验证命令

```bash
cd /data/Projects/KenRadar/kenradar/web/frontend
npm run build
```

---

## 八、人工验收清单

| # | 检查项 | 预期 |
|:-:|--------|------|
| 1 | 页面顶部 | 显示"公司研究平台"，无 Tab 按钮 |
| 2 | 研究模式 radio | 通用 / 财务 / 自定义 disabled |
| 3 | 通用模式表单 | 原 download Tab 字段完整 |
| 4 | 通用预览 | 调用原 preview API |
| 5 | 通用开始 | 调用原 startTask API |
| 6 | 财务模式表单 | 使用 FinAnalysisLauncher |
| 7 | 财务预览 | 调用财务分析预览 API |
| 8 | 财务开始 | 调用财务分析创建 API |
| 9 | 区块 ② 通用任务 | BatchCard 正常展示 |
| 10 | 区块 ② 财务任务 | FinAnalysisJobList 展示（非完整 MVP 页面） |
| 11 | 区块 ③ 搜索 | 输入 300750.SZ 查询 |
| 12 | 区块 ③ stat bar | 全宽 6 格 |
| 13 | 区块 ③ 问答 | 默认折叠，点击展开 |
| 14 | 区块 ③ 评分 | 如有财务结果则展示 |
| 15 | 区块 ④ 设置 | 默认折叠，展开后 NotebookLM |
| 16 | handler 不变 | 按钮调用原 API |
| 17 | npm run build | 通过 |

---

## 九、交付

完成后输出：

1. 修改了哪些文件。
2. 每个文件的主要改动。
3. 是否修改后端：**未修改后端。**
4. `npm run build` 结果。
5. 未完成项（如有）及原因。
