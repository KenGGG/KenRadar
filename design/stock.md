# “公司研究”功能修正版设计方案

## 1. 功能定位

在系统左侧功能栏新增一级栏目：

```text id="l9r8i6"
公司研究
```

该模块用于自动完成上市公司公告研究流程：

```text id="afh1al"
选择股票范围
→ 设置公告 PDF 查询时间区间
→ 下载公告 PDF 源文件
→ 创建临时 NotebookLM 笔记
→ 上传 PDF 到 NotebookLM
→ 向 NotebookLM 逐题提问 10 次
→ 每题回答单独保存到数据库
→ 10 题全部保存成功后删除 NotebookLM 笔记
→ 前端按股票查询研究结果
```

该模块的核心原则：

```text id="jbfsrq"
PDF 必须本地保存
NotebookLM 只作为临时阅读和问答工具
最终答案必须保存在当前系统数据库
NotebookLM 笔记不能长期保留
```

---

## 2. 左侧菜单与页面结构

左侧功能栏新增：

```text id="q45wip"
公司研究
```

页面包含两个 Tab：

```text id="kk3b75"
Tab 1：信息查询
Tab 2：信息下载
```

---

# 第一部分：信息查询 Tab

## 3. 信息查询 Tab 设计

### 3.1 功能目标

信息查询区域用于查看某一只股票的研究结果。

用户可以根据股票代码或股票名称查询：

```text id="wzw81g"
1. 该股票的公告下载情况
2. 该股票的 NotebookLM 问答完成情况
3. 10 个问题的逐题回答
4. 每个回答的生成时间
5. 每个回答对应的原始 PDF 公告来源
6. NotebookLM 笔记是否已删除
```

### 3.2 页面布局

```text id="k87fyv"
公司研究 / 信息查询

顶部：
[股票搜索框：代码 / 名称] [查询按钮] [重新生成研究按钮]

左侧信息卡：
- 股票代码
- 股票名称
- 公告查询区间
- 本地 PDF 数量
- 已上传 PDF 数量
- 已回答问题数
- NotebookLM notebook 状态
- NotebookLM notebook 是否已删除
- 最近研究时间
- 当前研究状态

右侧主区域：
- 问题 1：公司主营业务
- 问题 2：产业链位置
- 问题 3：产品与技术
- 问题 4：客户与订单
- 问题 5：产能与扩张
- 问题 6：财务变化
- 问题 7：风险事项
- 问题 8：投资假设
- 问题 9：重要股东股权质押情况
- 问题 10：一句话结论

底部：
- 已下载 PDF 公告列表
- NotebookLM 问答日志
- 错误日志
```

### 3.3 每个问题卡片展示字段

```text id="o36g3d"
问题编号
问题标题
回答状态
回答正文 Markdown
证据来源
原始回答 raw_answer
回答生成时间
重新提问按钮
```

### 3.4 状态展示

每个问题单独显示状态：

```text id="ry0szy"
pending：未提问
asking：正在提问
answered：已回答
saved：已保存
failed：失败
```

整只股票研究状态：

```text id="1kt5up"
not_started：未开始
downloading：正在下载 PDF
uploading：正在上传 NotebookLM
asking：正在逐题提问
completed：全部完成
partial_failed：部分失败
failed：失败
notebook_deleted：NotebookLM 笔记已删除
```

---

# 第二部分：信息下载 Tab

## 4. 信息下载 Tab 设计

### 4.1 功能目标

信息下载区域用于控制和查看公告 PDF 下载、NotebookLM 上传、逐题问答和删除 NotebookLM 笔记的全过程。

该 Tab 必须提供用户自定义参数：

```text id="coprkx"
1. PDF 查询开始日期
2. PDF 查询结束日期
3. 本次处理多少只股票
4. 处理哪些股票
5. 是否只下载 PDF
6. 是否下载后立即上传 NotebookLM
7. 是否上传后立即提问
8. 是否完成后自动删除 NotebookLM 笔记
```

### 4.2 下载任务配置区

页面顶部提供任务配置表单：

```text id="fbjbdd"
公告 PDF 查询区间：
[开始日期 begin_date] [结束日期 end_date]

股票处理范围：
[处理模式下拉框]
- 单只股票
- 手动输入多只股票
- 从股票列表前 N 只
- 从失败任务中选择
- 从未完成任务中继续

股票数量：
[本次最多处理股票数 max_stocks]

股票代码输入：
[300750.SZ, 000001.SZ, 600519.SH]

公告类型：
[全部]
[财务报告]
[重大事项]
[融资公告]
[风险提示]
[资产重组]
[信息变更]
[持股变动]

执行模式：
[仅下载 PDF]
[下载 PDF + 上传 NotebookLM]
[下载 PDF + 上传 NotebookLM + 逐题提问]
[完整流程：下载 + 上传 + 逐题提问 + 保存 + 删除 Notebook]

NotebookLM 删除策略：
[10 题全部保存成功后自动删除 Notebook]
```

默认参数建议：

```text id="dnbdf8"
begin_date = 当前日期往前 3 年
end_date = 当前日期
max_stocks = 1
notice_type = 全部
execution_mode = 完整流程
auto_delete_notebook = true
```

### 4.3 执行按钮

```text id="su950b"
[预览任务]
[开始执行]
[暂停]
[继续]
[重试失败]
[清理已完成 NotebookLM 笔记]
```

### 4.4 预览任务

点击“预览任务”后，先不执行，只显示：

```text id="mfav85"
预计处理股票数量
预计查询日期区间
每只股票预估公告数量
预计下载 PDF 数量
预计上传 NotebookLM 文件数量
预计提问次数 = 股票数 × 10
```

用户确认后再执行。

### 4.5 任务进度表

任务表格字段：

```text id="cmkec9"
股票代码
股票名称
公告区间
当前阶段
总进度
公告索引数量
PDF 已下载数量
PDF 下载失败数量
NotebookLM 上传数量
NotebookLM source ready 数量
已回答问题数
已保存问题数
Notebook 是否已删除
最近错误
更新时间
操作
```

操作按钮：

```text id="h1x33l"
查看
暂停
继续
重试
跳过
重新下载 PDF
重新上传 NotebookLM
重新提问
删除 NotebookLM 笔记
```

---

# 第三部分：阶段化实施策略

## 5. 系统第一阶段必须按 1 只 → 2 只 → 小批量推进

不能一开始就跑全 A 股。

### 5.1 第一阶段：只跑通 1 只股票

目标：

```text id="jcwjg2"
完整跑通一只股票的全部流程
```

推荐测试股票：

```text id="2nsn65"
300750.SZ 宁德时代
```

也可以由用户在前端输入任意一只股票。

必须跑通以下流程：

```text id="hvvv7m"
1. 获取股票基础信息
2. 获取公告索引
3. 下载该股票指定时间区间内的 PDF 源文件
4. 本地保存 PDF
5. 创建 NotebookLM 临时笔记
6. 上传 PDF
7. 等待 source ready
8. 问第 1 个问题
9. 保存第 1 个回答
10. 问第 2 个问题
11. 保存第 2 个回答
12. 直到第 10 个问题
13. 确认 10 个回答全部保存成功
14. 删除 NotebookLM 笔记
15. 前端可以查询 10 个回答
```

通过标准：

```text id="dlzazj"
PDF 文件真实存在
数据库有 PDF 文件路径
NotebookLM 能成功回答 10 个问题
10 个回答都已保存到数据库
NotebookLM notebook 已删除
前端能查询结果
```

### 5.2 第二阶段：跑 2 只股票

第一只股票通过后，再跑 2 只股票。

目标：

```text id="arps78"
验证任务队列、逐只处理、失败隔离和 NotebookLM 清理逻辑
```

要求：

```text id="otzwr6"
一只股票失败不能影响另一只
每只股票都有独立任务状态
每只股票对应独立临时 Notebook
每只股票完成后自动删除自己的 Notebook
```

### 5.3 第三阶段：小批量

第二阶段通过后，再支持小批量。

建议顺序：

```text id="e0k9ap"
第 3 阶段：5 只股票
第 4 阶段：10 只股票
第 5 阶段：50 只股票
第 6 阶段：更大批量
```

每一阶段都要观察：

```text id="s5npcf"
PDF 下载成功率
NotebookLM 上传成功率
NotebookLM 问答成功率
数据库保存成功率
Notebook 删除成功率
失败重试是否正常
```

---

# 第四部分：PDF 下载策略

## 6. PDF 源文件必须下载到本地

这是硬性要求。

系统不能只保存公告 URL，也不能只把 URL 上传给 NotebookLM。

必须保存：

```text id="s8j6bq"
PDF 源文件
PDF 本地路径
PDF 文件大小
PDF hash
PDF 原始下载链接
PDF 对应公告标题
PDF 对应公告日期
```

### 6.1 首选数据源：AKShare

第一数据源：

```python id="hxcsx3"
ak.stock_individual_notice_report(
    security="300750",
    symbol="全部",
    begin_date="20230620",
    end_date="20260620"
)
```

AKShare 返回公告网址后，系统需要进一步解析真实 PDF 地址。

流程：

```text id="apwrrr"
调用 AKShare 获取公告列表
→ 获取公告详情页 URL
→ 请求详情页
→ 解析 PDF 下载地址
→ 下载 PDF
→ 校验 PDF 文件
→ 保存到本地
```

### 6.2 备用数据源：a-stock-data

如果 AKShare 无法下载 PDF，必须尝试 a-stock-data 项目。

备用策略：

```text id="cp25gw"
第一步：AKShare 获取公告列表和网址
第二步：AKShare 解析 PDF 失败
第三步：调用 a-stock-data 的公告 Provider
第四步：用 a-stock-data 查找同一股票、同一公告标题、同一公告日期
第五步：下载 PDF 源文件
第六步：保存本地并回写数据库
```

### 6.3 数据源优先级

本功能的数据源优先级：

```text id="gw5y9t"
1. AKShare stock_individual_notice_report
2. a-stock-data announcements provider
3. 手工标记 failed，等待重试或人工处理
```

不使用 Tushare。

### 6.4 PDF 下载失败处理

如果某个公告 PDF 下载失败，不能静默跳过。

必须记录：

```text id="cl8lmc"
notice_id
股票代码
公告标题
公告日期
公告 URL
尝试的数据源
失败原因
HTTP 状态码
重试次数
最后失败时间
```

失败状态：

```text id="w58q82"
pending
downloading
downloaded
akshare_failed
a_stock_data_failed
pdf_missing
invalid_pdf
failed
```

### 6.5 PDF 校验规则

下载后必须检查：

```text id="e6sav6"
文件是否存在
文件大小是否大于最小阈值
文件头是否为 PDF
是否能被 PDF 解析器打开
是否已经重复下载
```

建议最小阈值：

```text id="iwy2p1"
file_size > 20KB
```

重复文件判断：

```text id="uq4k29"
file_hash = sha256(pdf_bytes)
```

### 6.6 本地目录结构

```text id="m8uleh"
~/.vibe-trading/company_research/
  downloads/
    announcements/
      300750.SZ_宁德时代/
        2023/
          2023-08-25_2023年半年度报告.pdf
        2024/
          2024-04-20_2023年年度报告.pdf
        2025/
        2026/
  logs/
  tmp/
```

---

# 第五部分：NotebookLM 临时笔记策略

## 7. NotebookLM 只作为临时处理工具

每只股票创建一个临时 NotebookLM notebook。

命名规则：

```text id="rnbxqf"
公司研究_临时_300750.SZ_宁德时代_20230620_20260620
```

数据库中保存：

```text id="snat68"
stock_symbol
stock_name
notebook_id
notebook_title
created_at
deleted_at
delete_status
```

## 8. NotebookLM 生命周期

每只股票的 NotebookLM 生命周期：

```text id="mnzyrv"
create_notebook
→ upload_pdf_sources
→ wait_sources_ready
→ ask_question_01
→ save_answer_01
→ ask_question_02
→ save_answer_02
→ ...
→ ask_question_10
→ save_answer_10
→ verify_all_answers_saved
→ delete_notebook
→ mark_notebook_deleted
```

### 8.1 删除规则

只有满足以下条件后，才能删除 NotebookLM notebook：

```text id="ff5hcd"
10 个问题全部回答成功
10 个问题全部保存到当前数据库
每个问题都有 answer_markdown 或 raw_answer
每个问题状态为 saved
数据库事务提交成功
```

满足后执行：

```text id="m39pnc"
delete_notebook(notebook_id)
```

删除后，数据库中仍保留：

```text id="ujtygi"
notebook_id
notebook_title
notebook_created_at
notebook_deleted_at
notebook_delete_status
```

但不再依赖 NotebookLM 查询历史内容。

### 8.2 删除失败处理

如果 NotebookLM 删除失败：

```text id="kc9xgv"
1. 研究结果仍然标记为 completed
2. notebook_delete_status 标记为 delete_failed
3. 进入待清理队列
4. 信息下载 Tab 显示“待清理 Notebook”
5. 用户可以点击“清理已完成 NotebookLM 笔记”
```

### 8.3 任务失败时的 Notebook 处理

如果 10 个问题没有全部完成：

默认策略：

```text id="tsxi90"
暂不立即删除 Notebook
保留用于重试
标记为 partial_failed
```

但是为了避免 NotebookLM 装不下太多笔记，需要增加自动清理策略：

```text id="m2s4td"
失败任务 Notebook 保留时间：默认 24 小时
超过保留时间仍未重试：自动删除 Notebook
再次重试时：重新创建 Notebook，重新上传 PDF
```

---

# 第六部分：10 个问题逐题提问设计

## 9. 逐题问答原则

NotebookLM 提问必须按顺序执行。

不能一次性问 10 个问题。

正确流程：

```text id="afmzpb"
问问题 1
等待 NotebookLM 回答
保存问题 1 回答到数据库
确认保存成功

问问题 2
等待 NotebookLM 回答
保存问题 2 回答到数据库
确认保存成功

...

问问题 10
等待 NotebookLM 回答
保存问题 10 回答到数据库
确认保存成功

确认 10 个问题全部 saved
删除 NotebookLM notebook
```

每个问题都是完整 prompt，不依赖前一个问题的回答。

每次提问都要保存：

```text id="dtrqjz"
question_key
question_index
question_title
prompt_text
answer_markdown
raw_answer
references_json
conversation_id
source_ids
status
error_message
generated_at
saved_at
```

---

## 10. 10 个完整问题 Prompt

### 问题 1：公司主营业务

```text id="ie9gy2"
你是一个上市公司公告研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：公司主营业务是什么？

请按以下结构输出：

# 公司主营业务

## 1. 主要产品
请列出公司公告中披露的主要产品。如果有多个业务板块，请分板块列示。

## 2. 主要服务
请列出公司公告中披露的主要服务或解决方案。

## 3. 收入占比
请说明近三年各主要业务、产品或服务的收入占比变化。如果公告未披露具体占比，请说明“公告未披露”。

## 4. 近三年变化
请总结近三年公司主营业务是否发生变化，包括新增业务、剥离业务、业务重心变化、产品结构变化。

## 5. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 2：产业链位置

```text id="qy3l5p"
你是一个上市公司产业链研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司处在什么产业链位置？

请按以下结构输出：

# 产业链位置

## 1. 所属产业链
请根据公告披露的产品、客户、供应商、应用场景，判断公司主要属于哪些产业链。

## 2. 上游 / 中游 / 下游位置
请判断公司在产业链中属于上游材料、中游制造、核心零部件、设备、系统集成、下游应用、渠道服务或其他位置。

## 3. 关键供应链环节
请说明公司是否处于某个关键供应链环节，例如材料、设备、零部件、制造、封装、测试、认证、渠道等。

## 4. 是否可能是瓶颈环节
请基于公告证据判断公司是否可能是供应链瓶颈环节。请区分“公告明确支持”和“仅能弱推断”。

## 5. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 3：产品与技术

```text id="lzboyw"
你是一个上市公司产品与技术研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司的核心产品和技术壁垒是什么？

请按以下结构输出：

# 产品与技术

## 1. 核心产品
请列出公告中披露的核心产品、主要型号、产品系列或解决方案。

## 2. 技术壁垒
请总结公告中披露的技术门槛、研发能力、核心工艺、专有技术、技术难点。

## 3. 认证资质
请列出公司公告中披露的客户认证、行业认证、产品认证、生产资质、准入资质。

## 4. 专利 / 工艺 / 产线能力
请总结公告中披露的专利、工艺路线、生产线能力、研发平台、实验室或技术中心。

## 5. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 4：客户与订单

```text id="c19ry4"
你是一个上市公司客户与订单研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司的客户、订单和客户认证情况如何？

请按以下结构输出：

# 客户与订单

## 1. 主要客户
请列出公告中披露的主要客户、客户类型、下游行业或终端应用领域。

## 2. 客户集中度
请说明公司是否披露前五大客户、第一大客户、客户集中度或大客户依赖情况。

## 3. 重大合同
请列出近三年公告中披露的重大合同、日常经营合同、框架协议、中标项目。

## 4. 在手订单
请说明公告是否披露在手订单、订单金额、订单周期、订单增长情况。

## 5. 新客户认证
请说明公告是否披露新客户开拓、客户认证、进入客户供应链、供应商资格认证等情况。

## 6. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 5：产能与扩张

```text id="g01ywx"
你是一个上市公司产能与扩张研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司的产能、扩产和资本开支情况如何？

请按以下结构输出：

# 产能与扩张

## 1. 当前产能
请列出公告中披露的现有产能、生产基地、产线数量、产能利用率等信息。

## 2. 在建项目
请列出近三年公告中披露的在建项目、扩产项目、新基地、新产线。

## 3. 募投项目
请说明公司是否有 IPO、定增、可转债等募投项目，并列出项目名称、投资金额、建设内容。

## 4. 投产时间
请说明公告中披露的项目建设周期、预计投产时间、达产时间、实际进度。

## 5. 资本开支
请总结近三年资本开支、在建工程、固定资产投入、长期资产投入的变化。

## 6. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 6：财务变化

```text id="vwvtmq"
你是一个上市公司财务分析助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司近三年的财务变化情况如何？

请按以下结构输出：

# 财务变化

## 1. 收入趋势
请总结近三年营业收入的变化方向、增速、主要原因。

## 2. 毛利率趋势
请总结近三年毛利率变化方向，并说明公告披露的原因。

## 3. 净利润趋势
请总结近三年归母净利润、扣非净利润变化方向及主要原因。

## 4. 经营现金流
请总结近三年经营活动现金流净额变化，并说明与净利润是否匹配。

## 5. 存货变化
请说明近三年存货规模、存货结构、存货跌价准备、存货周转变化。

## 6. 应收账款变化
请说明近三年应收账款、应收票据、合同资产变化及坏账风险。

## 7. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 7：风险事项

```text id="p4e3jm"
你是一个上市公司风险审查助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司近三年有哪些重要风险事项？

请按以下结构输出：

# 风险事项

## 1. 诉讼仲裁
请列出公告中披露的重大诉讼、仲裁、执行案件及可能影响。

## 2. 担保
请说明公司对外担保、对子公司担保、违规担保或担保余额情况。

## 3. 关联交易
请说明近三年重大关联交易、日常关联交易、关联采购、关联销售、资金往来情况。

## 4. 减值
请说明商誉减值、资产减值、信用减值、存货跌价准备等情况。

## 5. 债务压力
请说明短期借款、长期借款、债券、流动性风险、偿债压力等情况。

## 6. 股权质押
请说明控股股东、实际控制人、重要股东是否存在股权质押风险。

## 7. 监管处罚
请说明是否有监管函、问询函、处罚、立案调查、审计意见异常等情况。

## 8. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 8：投资假设

```text id="f25wu2"
你是一个上市公司投资研究助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：如果继续研究这家公司，可能的投资假设和证伪条件是什么？

请按以下结构输出：

# 投资假设

## 1. 看多逻辑
请基于公告证据，总结该公司可能被继续研究的核心看多逻辑。

## 2. 核心证据
请列出支持看多逻辑的公告证据，例如收入增长、订单增长、产能扩张、客户突破、技术认证、产业链瓶颈等。

## 3. 最大不确定性
请说明该公司投资逻辑中最大的风险和不确定性。

## 4. 证伪条件
请列出哪些情况出现时，说明该公司的投资逻辑可能不成立。

## 5. 研究优先级
请根据公告证据，将该公司后续研究优先级分为：高 / 中 / 低，并说明理由。
```

---

### 问题 9：重要股东股权质押情况

```text id="j3iftx"
你是一个上市公司股权质押风险分析助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请回答：该公司重要股东股权质押情况如何？

请按以下结构输出：

# 重要股东股权质押情况

## 1. 是否存在重要股东质押
请说明控股股东、实际控制人、5%以上股东或其他重要股东是否存在股权质押。

## 2. 质押主体
请列出公告中披露的质押股东名称、身份、持股比例。

## 3. 质押比例
请说明质押数量、占其所持股份比例、占公司总股本比例。

## 4. 质押变化趋势
请总结近三年质押比例是上升、下降、解除还是新增。

## 5. 平仓或流动性风险
请说明公告是否披露平仓风险、补充质押、解除质押、展期、违约风险。

## 6. 风险判断
请判断股权质押对公司控制权稳定性和投资风险的影响。

## 7. 证据来源
请列出支持上述判断的公告名称、公告年份和关键依据。
```

---

### 问题 10：一句话结论

```text id="u96oxt"
你是一个上市公司研究结论助手。

请严格基于当前 NotebookLM 中已经上传的该上市公司公告回答问题，不允许使用外部知识。

如果公告没有披露，请明确回答“公告未披露”，不要猜测。

请基于公告内容，对这家公司是否值得继续深入研究给出一句话结论。

请按以下结构输出：

# 一句话结论

## 1. 150 字以内结论
请用不超过 150 字总结这家公司是否值得继续深入研究。

## 2. 最核心理由
请列出 1-3 条最核心理由。

## 3. 最大风险
请列出 1-3 条最大风险。

## 4. 继续研究建议
请判断后续应该重点研究哪些方向，例如产品、客户、产能、财务、股权质押、诉讼风险、产业链位置等。

## 5. 证据来源
请列出支持上述结论的公告名称、公告年份和关键依据。
```

---

# 第七部分：后端流程设计

## 11. 后端主流程

每只股票独立执行：

```text id="ltt3k0"
start_company_research_job(symbol, begin_date, end_date)
```

完整流程：

```text id="njvrkr"
1. 校验股票代码
2. 获取公告索引
3. 下载 PDF 源文件
4. 校验 PDF
5. 创建 NotebookLM 临时笔记
6. 上传 PDF
7. 等待 source ready
8. 逐题向 NotebookLM 提问
9. 每题回答保存数据库
10. 校验 10 个问题是否全部保存
11. 删除 NotebookLM 笔记
12. 标记任务完成
```

伪代码：

```python id="p02rob"
async def run_company_research_job(job_id: int):
    job = load_job(job_id)

    update_stage(job, "fetch_notice_index")
    notices = fetch_notices(job.symbol, job.begin_date, job.end_date)

    update_stage(job, "download_pdfs")
    pdf_files = download_all_notice_pdfs(notices)

    if not pdf_files:
        fail_job(job, "no_pdf_downloaded")
        return

    update_stage(job, "create_notebook")
    notebook = await notebooklm.create_notebook(job)

    update_stage(job, "upload_sources")
    sources = await notebooklm.upload_files(notebook.id, pdf_files)

    update_stage(job, "wait_sources_ready")
    await notebooklm.wait_sources_ready(notebook.id, sources)

    update_stage(job, "ask_questions")

    for question in COMPANY_RESEARCH_QUESTIONS:
        answer = await notebooklm.ask(notebook.id, question.prompt)
        save_answer(
            symbol=job.symbol,
            question_key=question.key,
            prompt_text=question.prompt,
            raw_answer=answer.raw,
            answer_markdown=answer.text,
            references=answer.references,
            conversation_id=answer.conversation_id,
        )
        mark_question_saved(job.symbol, question.key)

    if verify_all_10_answers_saved(job.symbol):
        update_stage(job, "delete_notebook")
        await notebooklm.delete_notebook(notebook.id)
        mark_notebook_deleted(job.symbol, notebook.id)
        complete_job(job)
    else:
        mark_partial_failed(job, "answers_not_fully_saved")
```

---

## 12. 后端模块目录

建议新增：

```text id="rr8ho6"
agent/src/company_research/
  __init__.py
  routes.py
  service.py
  models.py
  schemas.py
  job_runner.py
  akshare_provider.py
  a_stock_data_provider.py
  notice_downloader.py
  pdf_validator.py
  notebooklm_client.py
  prompts.py
  parser.py
  storage.py
```

### 12.1 akshare_provider.py

职责：

```text id="tilazw"
调用 AKShare 获取股票列表和公告索引
```

函数：

```python id="n9bh5t"
fetch_all_stocks()
fetch_individual_notices(security, begin_date, end_date, notice_type)
```

### 12.2 a_stock_data_provider.py

职责：

```text id="ye35js"
当 AKShare 无法下载 PDF 时，调用 a-stock-data 公告能力进行补充
```

函数：

```python id="kdjz2f"
search_announcements(symbol, begin_date, end_date)
find_matching_notice(symbol, title, notice_date)
download_notice_pdf(symbol, notice)
```

### 12.3 notice_downloader.py

职责：

```text id="tqz6a9"
统一处理 PDF 下载
先 AKShare，再 a-stock-data
```

函数：

```python id="k6y09a"
download_notice_pdf(notice)
download_pdf_from_akshare_notice_url(notice_url)
download_pdf_from_a_stock_data(symbol, notice_title, notice_date)
```

### 12.4 pdf_validator.py

职责：

```text id="gq5xma"
校验 PDF 文件是否真实有效
```

函数：

```python id="n96gxu"
validate_pdf(file_path)
compute_file_hash(file_path)
```

### 12.5 notebooklm_client.py

职责：

```text id="hoal30"
封装 notebooklm-py
```

函数：

```python id="i53dhf"
create_notebook(title)
upload_pdf(notebook_id, file_path, title)
wait_sources_ready(notebook_id, source_ids)
ask_question(notebook_id, prompt)
delete_notebook(notebook_id)
```

---

# 第八部分：数据库设计修正

## 13. company_research_jobs

任务表增加用户自定义时间区间和股票数量。

```sql id="ddo00z"
CREATE TABLE company_research_jobs (
    id INTEGER PRIMARY KEY,
    batch_id TEXT,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    begin_date DATE NOT NULL,
    end_date DATE NOT NULL,
    notice_type TEXT DEFAULT '全部',
    execution_mode TEXT,
    max_stocks INTEGER,
    status TEXT,
    current_stage TEXT,
    progress_percent REAL DEFAULT 0,
    notice_total INTEGER DEFAULT 0,
    pdf_downloaded INTEGER DEFAULT 0,
    pdf_failed INTEGER DEFAULT 0,
    source_uploaded INTEGER DEFAULT 0,
    source_ready INTEGER DEFAULT 0,
    question_answered INTEGER DEFAULT 0,
    question_saved INTEGER DEFAULT 0,
    notebook_id TEXT,
    notebook_deleted BOOLEAN DEFAULT FALSE,
    notebook_deleted_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

## 14. company_notice_files

PDF 文件表必须保存源文件信息。

```sql id="r8p2il"
CREATE TABLE company_notice_files (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    notice_id INTEGER,
    notice_title TEXT,
    notice_date DATE,
    notice_url TEXT,
    source_provider TEXT,
    download_url TEXT,
    file_path TEXT NOT NULL,
    file_name TEXT,
    file_size INTEGER,
    file_hash TEXT,
    is_valid_pdf BOOLEAN DEFAULT FALSE,
    download_status TEXT,
    error_message TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

## 15. company_notebooks

Notebook 表必须支持删除状态。

```sql id="o2422c"
CREATE TABLE company_notebooks (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    notebook_id TEXT,
    notebook_title TEXT,
    notebook_status TEXT,
    created_at TIMESTAMP,
    deleted_at TIMESTAMP,
    delete_status TEXT,
    delete_error TEXT,
    source_count INTEGER DEFAULT 0,
    ready_source_count INTEGER DEFAULT 0
);
```

## 16. company_research_answers

逐题保存答案。

```sql id="u4bxdn"
CREATE TABLE company_research_answers (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    question_index INTEGER NOT NULL,
    question_key TEXT NOT NULL,
    question_title TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    answer_markdown TEXT,
    raw_answer TEXT,
    references_json TEXT,
    conversation_id TEXT,
    notebook_id TEXT,
    status TEXT,
    error_message TEXT,
    generated_at TIMESTAMP,
    saved_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(symbol, question_key)
);
```

## 17. company_research_batches

批次表用于记录用户一次提交的批量任务。

```sql id="nxg48n"
CREATE TABLE company_research_batches (
    id INTEGER PRIMARY KEY,
    batch_id TEXT UNIQUE NOT NULL,
    begin_date DATE NOT NULL,
    end_date DATE NOT NULL,
    max_stocks INTEGER,
    stock_scope TEXT,
    notice_type TEXT,
    execution_mode TEXT,
    total_stocks INTEGER,
    completed_stocks INTEGER DEFAULT 0,
    failed_stocks INTEGER DEFAULT 0,
    status TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

# 第九部分：API 设计修正

## 18. 预览任务

```http id="b2ez21"
POST /api/company-research/tasks/preview
```

请求：

```json id="x0d7ar"
{
  "begin_date": "2023-06-20",
  "end_date": "2026-06-20",
  "stock_scope": "first_n",
  "max_stocks": 1,
  "symbols": [],
  "notice_type": "全部",
  "execution_mode": "full"
}
```

返回：

```json id="qbt0t4"
{
  "estimated_stocks": 1,
  "estimated_questions": 10,
  "stocks": [
    {
      "symbol": "300750.SZ",
      "name": "宁德时代"
    }
  ]
}
```

## 19. 创建任务

```http id="fuzm9u"
POST /api/company-research/tasks
```

请求：

```json id="byp84p"
{
  "begin_date": "2023-06-20",
  "end_date": "2026-06-20",
  "stock_scope": "manual",
  "max_stocks": 1,
  "symbols": ["300750.SZ"],
  "notice_type": "全部",
  "execution_mode": "full",
  "auto_delete_notebook": true
}
```

## 20. 查询批次进度

```http id="ueu9hy"
GET /api/company-research/batches/{batch_id}
```

## 21. 查询单只股票任务

```http id="qtnntt"
GET /api/company-research/jobs/{job_id}
```

## 22. 查询某只股票 10 个回答

```http id="u2dya5"
GET /api/company-research/stocks/{symbol}/answers
```

## 23. 查询某只股票 PDF 列表

```http id="xetlyv"
GET /api/company-research/stocks/{symbol}/pdfs
```

## 24. 重新提问某一个问题

```http id="k79pq5"
POST /api/company-research/stocks/{symbol}/questions/{question_key}/retry
```

## 25. 清理已完成 Notebook

```http id="f9guo4"
POST /api/company-research/notebooks/cleanup
```

---

# 第十部分：前端修正

## 26. 信息下载 Tab 新增配置项

必须增加：

```text id="zm6ytk"
开始日期
结束日期
本次处理股票数量
处理模式
股票代码输入框
公告类型
执行模式
自动删除 Notebook 开关
```

页面结构：

```text id="ae7h1c"
信息下载

一、任务配置
- 开始日期
- 结束日期
- 股票范围
- 股票数量
- 股票代码
- 公告类型
- 执行模式
- 自动删除 NotebookLM 笔记

二、任务预览
- 预计股票数
- 预计提问次数
- 预计 PDF 数量

三、任务进度
- 批次进度
- 单股进度
- 逐题问答进度

四、错误与重试
- PDF 下载失败
- NotebookLM 上传失败
- NotebookLM 回答失败
- Notebook 删除失败
```

## 27. 逐题问答进度展示

每只股票详情页显示：

```text id="jr5dij"
问题 1：公司主营业务       saved
问题 2：产业链位置         saved
问题 3：产品与技术         asking
问题 4：客户与订单         pending
...
问题 10：一句话结论        pending
```

每题状态：

```text id="xwoxwx"
pending
asking
answered
saving
saved
failed
```

---

# 第十一部分：任务执行顺序

## 28. 单只股票完整状态机

```text id="ed085v"
created
→ fetch_stock_info
→ fetch_notice_index
→ download_pdfs_by_akshare
→ fallback_download_by_a_stock_data
→ validate_pdfs
→ create_notebook
→ upload_pdfs
→ wait_sources_ready
→ ask_question_01
→ save_answer_01
→ ask_question_02
→ save_answer_02
→ ask_question_03
→ save_answer_03
→ ask_question_04
→ save_answer_04
→ ask_question_05
→ save_answer_05
→ ask_question_06
→ save_answer_06
→ ask_question_07
→ save_answer_07
→ ask_question_08
→ save_answer_08
→ ask_question_09
→ save_answer_09
→ ask_question_10
→ save_answer_10
→ verify_answers
→ delete_notebook
→ completed
```

## 29. 批量股票执行顺序

批量任务不能并发过高。

MVP 阶段：

```text id="e5pnyj"
一次只处理 1 只股票
```

小批量阶段：

```text id="iy54aw"
最多并发 1-2 只股票
NotebookLM 提问必须限速
```

批量流程：

```text id="t1jk4b"
从批次中取第 1 只股票
完成全部流程
删除 Notebook
再取第 2 只股票
完成全部流程
删除 Notebook
继续下一只
```

不要同时创建大量 NotebookLM 笔记。

---

# 第十二部分：关键校验规则

## 30. 删除 Notebook 前校验

删除 NotebookLM notebook 前，必须执行：

```python id="p9jldu"
def can_delete_notebook(symbol: str) -> bool:
    answers = load_answers(symbol)
    if len(answers) != 10:
        return False

    for answer in answers:
        if answer.status != "saved":
            return False
        if not answer.answer_markdown and not answer.raw_answer:
            return False

    return True
```

只有返回 true 才能删除。

## 31. 完成任务前校验

任务标记 completed 前，必须满足：

```text id="q1a3za"
PDF 至少成功下载 1 个
NotebookLM 成功创建
PDF 至少成功上传 1 个
10 个问题全部 saved
NotebookLM notebook 删除成功或进入 delete_failed 待清理状态
```

如果回答已保存，但 Notebook 删除失败：

```text id="f5gs6f"
任务状态：completed_with_delete_pending
```

---

# 第十三部分：实施顺序

## 32. 第一阶段：单只股票闭环

只实现：

```text id="pxi6vf"
手动输入 1 只股票
自定义 begin_date / end_date
下载 PDF
创建 Notebook
上传 PDF
逐题问答 10 次
保存 10 个回答
删除 Notebook
前端查询答案
```

验收标准：

```text id="ykxab6"
1 只股票完整跑通
数据库中有 PDF 文件记录
数据库中有 10 条回答
NotebookLM 笔记已删除
前端能看到 10 个问题答案
```

## 33. 第二阶段：2 只股票

实现：

```text id="bgf9qo"
一次提交 2 只股票
按顺序逐只执行
每只股票独立创建 Notebook
每只股票完成后删除 Notebook
```

验收标准：

```text id="h8wri4"
2 只股票都有 10 条回答
2 个 Notebook 都已删除
一只失败不影响另一只
```

## 34. 第三阶段：小批量

逐步支持：

```text id="bzbuxg"
5 只
10 只
50 只
```

每个阶段通过后再扩大。

---

# 第十四部分：最终结论

修正后的“公司研究”模块应按以下原则实现：

```text id="jg4060"
1. 信息下载 Tab 必须支持自定义 PDF 查询时间区间。
2. 信息下载 Tab 必须支持设置本次处理股票数量。
3. 第一阶段只跑通 1 只股票。
4. 第二阶段再跑 2 只股票。
5. 后续再扩大到小批量。
6. PDF 源文件必须下载到本地。
7. AKShare 下载失败时，必须尝试 a-stock-data。
8. NotebookLM 必须逐题提问 10 次。
9. 每一题回答后，必须立即保存到数据库。
10. 10 题全部保存成功后，必须删除该股票对应的 NotebookLM 笔记。
```

最终系统形态：

```text id="wbtp8o"
本地系统保存 PDF 源文件
本地数据库保存 10 个问题答案
NotebookLM 只作为临时阅读器
NotebookLM 不保存长期笔记
```
