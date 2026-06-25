# 公司研究平台前端重构 第二期 — 组件拆分实施计划

> 编写日期: 2026-06-24
> 目标: 将 1104 行单文件拆分为父容器 + 4 个 section 组件 + shared 工具
> 关键约束: 保持单页 4 区块布局，不重新引入 Tab 页面切换

---

## 一、当前代码分析

### CompanyResearchWorkspace.tsx（1104 行）

```
├── 类型定义（12-46）28 行
├── 工具函数（48-71）24 行
├── 主组件（73-550）478 行
│   ├── State（74-114）
│   ├── Handlers（119-230）
│   ├── Autorefresh（232-248）
│   ├── JSX 4 区块（254-527）
│   └── StatCard 内联（268-281）
├── NotebookLMStatusCard（552-633）82 行
├── PdfPathCard（635-653）19 行
├── NotebookTable（655-718）64 行
├── StatusItem（720-727）8 行
├── Field（729-758）30 行
├── getStageLabel / getStageIndex / isTerminalStatus（760-796）37 行
├── groupJobsByBatch（798-808）11 行
├── BatchCard（810-894）85 行
├── JobStageCard（896-963）68 行
├── EventLog（965-1029）65 行
├── PdfTable（1031-1078）48 行
└── MarkdownContent（1080-1104）25 行
```

### 已拆出的外部组件

| 组件 | 来源 | 导入方式 |
|------|------|----------|
| `FinAnalysisLauncher` | `CompanyFinancialAnalysisMVP.tsx` | 命名导出，props 驱动 |
| `FinAnalysisJobList` | `CompanyFinancialAnalysisMVP.tsx` | 命名导出，props 驱动 |
| `FinScoreCard` | `CompanyFinancialAnalysisMVP.tsx` | 命名导出 |

---

## 二、目标文件结构

新增目录和 5 个文件：

```
src/components/company-research/
  shared.tsx          # 工具函数 + 通用小组件
  LauncherTab.tsx     # 区块① 发起研究
  TrackerTab.tsx      # 区块② 研究进度
  ResultsTab.tsx      # 区块③ 研究成果
  SettingsTab.tsx     # 区块④ 系统设置
```

修改 1 个文件：

```
src/components/CompanyResearchWorkspace.tsx  # 精简为父容器
```

---

## 三、核心约束：保持单页 4 区块

**不要重新引入 Tab 切换。**

父组件仍然纵向渲染 4 个区块：

```tsx
return (
  <div className="space-y-6 font-sans text-zinc-900">
    <header>...</header>
    {(message || error) && <div>...</div>}
    <LauncherTab ... />
    <TrackerTab ... />
    <ResultsTab ... />
    <SettingsTab ... />
  </div>
)
```

- 不要新增 `activeTab` state
- 不要新增 Tab 按钮导航
- 文件名带 `Tab` 只是命名惯例，组件行为是 section

---

## 四、shared.tsx

创建 `src/components/company-research/shared.tsx`

迁移以下内容：

**工具函数：**
- `requestJson`
- `statusClass`
- `getStageLabel`
- `getStageIndex`
- `isTerminalStatus`
- `groupJobsByBatch`
- `isoDate`

**通用组件：**
- `Field`
- `StatusItem`
- `MarkdownContent`（含 react-markdown / remark-gfm 导入）
- `StatCard`

**类型：**
- `PreviewStock`
- `FinJob` / `FinReportFile` / `FinAnswer` / `FinReport` / `FinRedFlag`（从 `CompanyFinancialAnalysisMVP.tsx` 的接口对齐）

所有组件从 `shared.tsx` 导入后，原文件中删除对应定义。

---

## 五、SettingsTab.tsx

创建 `src/components/company-research/SettingsTab.tsx`

迁移原工作台中的"系统设置"区块。

**Props：**
```tsx
interface SettingsTabProps {
  settingsExpanded: boolean
  onToggleSettings: () => void
  notebookStatus: NotebookLMStatus | null
  notebooks: NotebookLMNotebook[]
  onRefreshStatus: () => void
  onRefreshNotebooks: () => void
  onRelogin: (email: string) => void
  onCleanupNotebooks: () => void
  onCleanupLocalPdfs: () => void
}
```

**内部保留组件：**
- `NotebookLMStatusCard`（从主文件移入）
- `PdfPathCard`（从主文件移入）
- `NotebookTable`（从主文件移入）

**注意：** `settingsExpanded` state 保留在父组件，SettingsTab 只接收状态和回调。

---

## 六、TrackerTab.tsx

创建 `src/components/company-research/TrackerTab.tsx`

迁移原工作台中的"研究进度"区块。

**Props：**
```tsx
interface TrackerTabProps {
  batches: any[]
  jobs: CompanyResearchJob[]
  finJobs: FinJob[]
  expandedBatches: Set<string>
  expandedLogs: boolean
  onToggleBatch: (id: string) => void
  onToggleLogs: () => void
  onViewStock: (symbol: string) => void
}
```

**内部保留组件：**
- `BatchCard`（从主文件移入，保留内部 `useEffect` 调用批次 API）
- `JobStageCard`（从主文件移入）
- `EventLog`（从主文件移入）

**"查看详情"行为：** 点击后通过 `onViewStock(symbol)` 回调给父组件，由父组件调用 `loadStock(symbol)`。不要切换 Tab，不要新增导航。

---

## 七、ResultsTab.tsx

创建 `src/components/company-research/ResultsTab.tsx`

迁移原工作台中的"研究成果"区块。

**Props：**
```tsx
interface ResultsTabProps {
  query: string
  onQueryChange: (v: string) => void
  onSearch: () => void
  summary: Record<string, any> | null
  answers: CompanyResearchAnswer[]
  pdfs: CompanyNoticeFile[]
  savedCount: number
  expandedAnswers: Record<string, boolean>
  onToggleAnswer: (key: string) => void
  finScore?: { score: number; tier: string | null } | null
}
```

**内部保留组件：**
- `PdfTable`（从主文件移入，保持折叠功能）

**导入：**
- `StatCard` / `MarkdownContent` / `statusClass` → 从 `shared.tsx`
- `FinScoreCard` → 从 `CompanyFinancialAnalysisMVP.tsx`

---

## 八、LauncherTab.tsx

创建 `src/components/company-research/LauncherTab.tsx`

迁移原工作台中的"发起研究"区块。

**Props：**
```tsx
type ResearchMode = 'general' | 'financial'

interface LauncherTabProps {
  activeResearchMode: ResearchMode
  onModeChange: (mode: ResearchMode) => void
  // General research
  beginDate: string; onBeginDateChange: (v: string) => void
  endDate: string; onEndDateChange: (v: string) => void
  stockScope: string; onStockScopeChange: (v: string) => void
  maxStocks: number; onMaxStocksChange: (v: number) => void
  symbols: string; onSymbolsChange: (v: string) => void
  noticeType: string; onNoticeTypeChange: (v: string) => void
  executionMode: string; onExecutionModeChange: (v: string) => void
  autoDelete: boolean; onAutoDeleteChange: (v: boolean) => void
  previewStocks: PreviewStock[]
  onPreview: () => void; onStartTask: () => void; onRefresh: () => void
  // Financial analysis
  finSymbol: string; onFinSymbolChange: (v: string) => void
  finBaseYear: number; onFinBaseYearChange: (v: number) => void
  finAutoDelete: boolean; onFinAutoDeleteChange: (v: boolean) => void
  finPreviewResult: unknown
  onFinPreview: () => void; onFinStart: () => void; onFinRefresh: () => void
}
```

**财务分析部分复用：** `FinAnalysisLauncher`（从 `CompanyFinancialAnalysisMVP.tsx` 导入），不重新复制财务分析启动 JSX。

---

## 九、父组件 CompanyResearchWorkspace.tsx

精简后保留：

1. 所有 import（来自 `shared.tsx` + 4 个 section 组件 + `CompanyFinancialAnalysisMVP`）
2. 主组件函数 + 所有 state 定义
3. 所有 handler 函数（`loadStock`, `preview`, `startTask`, `loadJobs`, 财务 handlers, NotebookLM handlers）
4. `useEffect` 初始化和 auto-refresh polling
5. `toggleBatch` / `toggleAnswerExpanded` / `withError`
6. `handleViewStock` 回调（调用 `setQuery + loadStock`）
7. JSX：header + message + 4 个 section 组件

目标行数：**< 600 行**（从 1104 行缩减）。

---

## 十、执行顺序

### Phase 1：shared.tsx
1. 创建文件，移入工具函数和通用组件
2. 从原文件删除对应定义
3. 更新原文件 import

### Phase 2：SettingsTab.tsx
1. 创建文件，移入系统设置区 JSX 和 3 个内部组件
2. 父组件传 props

### Phase 3：TrackerTab.tsx
1. 创建文件，移入研究进度区 JSX 和 3 个内部组件
2. 接入 `FinAnalysisJobList`

### Phase 4：ResultsTab.tsx
1. 创建文件，移入研究成果区 JSX 和 `PdfTable`
2. 接入 `FinScoreCard`

### Phase 5：LauncherTab.tsx
1. 创建文件，移入发起研究区 JSX
2. 接入 `FinAnalysisLauncher`

### Phase 6：精简父组件
1. 删除所有已移动的组件和函数定义
2. 更新 import
3. 验证构建

---

## 十一、父组件最终形态（伪代码）

```tsx
import React, { ... } from 'react'
import { ... } from 'lucide-react'
import { FinAnalysisLauncher, FinAnalysisJobList, FinScoreCard } from './CompanyFinancialAnalysisMVP'
import { requestJson, statusClass, Field, MarkdownContent, ... } from './company-research/shared'
import { LauncherTab } from './company-research/LauncherTab'
import { TrackerTab } from './company-research/TrackerTab'
import { ResultsTab } from './company-research/ResultsTab'
import { SettingsTab } from './company-research/SettingsTab'

export default function CompanyResearchWorkspace() {
  // ─── 所有 state（不变）──
  // ─── 所有 handler（不变）──
  // ─── polling / useEffect（不变）──

  return (
    <div className="space-y-6 font-sans text-zinc-900">
      <header>
        <h1>公司研究平台</h1>
        <p>按标准研究流水线发起任务、跟踪进度、查看成果和管理系统设置。</p>
      </header>

      {(message || error) && <div>...</div>}

      <LauncherTab ... />
      <TrackerTab ... />
      <ResultsTab ... />
      <SettingsTab ... />
    </div>
  )
}
```

---

## 十二、验证

```bash
cd /data/Projects/KenRadar/kenradar/web/frontend
npm run build
```

| # | 检查项 |
|:-:|--------|
| 1 | 页面仍是单页 4 区块，无 Tab 导航 |
| 2 | 发起研究：通用/财务模式切换、预览、开始任务正常 |
| 3 | 研究进度：通用批次、财务任务、事件日志正常 |
| 4 | 研究成果：搜索、StatBar、问答折叠、PDF 明细正常 |
| 5 | 系统设置：折叠/展开、NotebookLM、清理工具正常 |
| 6 | `CompanyResearchWorkspace.tsx` < 600 行 |
| 7 | `company-research/` 目录 5 个新文件 |
| 8 | 未修改后端 |
| 9 | `npm run build` 通过 |
