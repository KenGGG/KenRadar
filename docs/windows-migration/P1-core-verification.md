# P1 本地核心验收 — 2026-10-10

## 实际修改

- 正常数据库工厂仅使用 SQLite；PG 历史迁移冻结。SQLite 独立 Alembic baseline 保留 V2 关系，新增原稿版本与租约 token。
- SQLAlchemy Core 短事务，读 DEFERRED、写 IMMEDIATE；WAL/FK/FULL/busy_timeout 验证，不自动建立不存在的运行库。
- 持久任务原子领取、attempt/状态转换/outbox 原子提交、失效回收、暂停/继续/取消，任务与步骤结果拒绝旧租约写入。
- 当前转录/分析/笔记、来源订阅、研究扫描确认执行、交付审计使用 V2 表；同名外部标识可属于不同平台。失败候选保留成功结果，原稿替换保留历史。
- `ctl.ps1`/Python 生命周期管理，一个 Web 和 worker；调度归 worker，Web 默认无内置 worker。文件锁使用 portalocker，锁失败不会无锁运行。
- 提供拒绝覆盖现有环境的 `install.ps1`；只允许仓库内新环境。pyproject 为依赖源，uv.lock 与 requirements 导出保持对应。
- 内容列表/详情、仪表盘、readiness 与依赖诊断接入 SQLite。开发前端绑定 loopback，clean 改为固定路径的 Node 脚本。

## 实测证据

解释器：仓库 `.venv/python.exe`，Python 3.11.17、sqlite3 3.54.0、SQLAlchemy 2.1.4。portalocker 4.4.0、psutil 7.2.2 仅安装到此独立环境。

- `pytest-all-p1c`：**285 passed / 35 skipped**，69.04 秒。跳过不是通过，包含 PG 外部条件缺口。
- 两个 Windows spawn 进程消费 1,000 个任务：任务、attempt、2,000 条状态转换及 1,000 条 outbox 一致，无重复领取。
- 子进程领取后强制退出；过期后重新领取，旧心跳、完成提交与内容写入被拒绝。
- 完成事务故障注入回滚，DDL/savepoint 回滚、FK 拒绝、JSON NULL/对象/数组、短 busy 超时通过。
- 真正文件库 + HTTP server + 独立 worker；屏蔽 psycopg 导入，列表、详情、readiness、仪表盘与任务执行通过。
- 10,000 条内容 fixture，中文短词/英文词检索与连续分页通过。
- Windows 两进程启停、重复启动不重复建进程、跨进程文件锁竞争与释放通过。
- 订阅扫描状态、研究审批与执行、内容成功保留、跨平台同 external ID、发布通知审计本地契约通过；这些测试没有真实采集或外发。

部分回归首次卡在 Windows asyncio socketpair，被沙箱回环权限限制；放行后执行成功。固定路径 `/tmp` 的旧测试改为各自临时配置，避免测试顺序污染。

## 未完成与验收范围

- **真实 PG 迁移待源验证**，无源库或导出包，数量/内容/文件/前后 API 等价未取得证据。
- 抖音登录、FunASR/Whisper/GPU、Agnes/Ollama、真实笔记及真实外部交付链路待验。GPU 组合在 lock 中解析不等于实测通过。
- 后续已完成仓库内全新核心环境安装演练；详见 `P3-P6-verification.md`。完整 GPU/模型安装仍待验。
- worker 强制停止后按租约到期恢复；重型 ASR/FFmpeg 子进程运行中的停止场景待真实链路验证。
- 旧 Web 研究控制/洞察和部分维护查询仍有 PG SQL，需要在后续接口与 UI 联调中逐项迁移；不得把其降级/空结果称为验收通过。
- SQLite 当前不强制抢占运行中的研究任务，定时任务等待安全边界；避免旧 handler 返回时改写已中断的研究记录。

因此此处通过的是 **P1 本地核心门槛**（原生启动、不依赖 PG、原子领取和失效恢复），不是完整生产可用声明。

## 回滚边界

生产配置和原始数据未修改，未 push/公开发布/飞书发送，测试进程已停止。全部新库和测试产物在 `data/test-migration/`，未提交。回滚只撤销本轮代码块及新增文件，先对照 P0 原始 diff；不要 `git reset --hard`、清空 data/docs 或还原用户原有删除。正式 SQLite 写入后不能承诺直接切回 PG 而无新增数据损失。
