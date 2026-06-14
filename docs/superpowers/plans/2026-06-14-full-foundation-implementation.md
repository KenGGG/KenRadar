# KenRadar 全架构方案完整实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整落实 design/KenRadar-system-foundation-review.md 中所有设计要求的可执行部分

**Architecture:** 按设计方案的 Phase 0→1→3→4→5 顺序递进实现，每个 Phase 先建基础设施再拆业务代码，保持向后兼容

**Tech Stack:** Python 3.12, PostgreSQL 16, psycopg, asyncio, Alembic

**依赖关系：** Phase 0.6（独立）→ Phase 1（Enum/Repository）→ Phase 3（Handler 拆分）→ Phase 4（Outbox）→ Phase 5（Adapter）

---

## 文件结构总览

### 新建文件
| 文件 | 职责 |
|------|------|
| `kenradar/domain/transitions.py` | state_transition 写入 API |
| `kenradar/domain/resources.py` | ResourceRequirement 定义 |
| `kenradar/jobs/outbox_consumer.py` | outbox_event 消费工作器 |
| `kenradar/processing/__init__.py` | 新 stage handler 包 |
| `kenradar/processing/base.py` | StageHandler 基类 + ResourceRequirement |
| `kenradar/processing/fetch.py` | 博主内容抓取 handler |
| `kenradar/processing/download.py` | 下载 handler |
| `kenradar/processing/transcribe.py` | 转录 handler |
| `kenradar/processing/organize.py` | AI 整理 handler |
| `kenradar/processing/note.py` | 笔记渲染 handler |
| `kenradar/processing/publish.py` | 静态发布 handler |
| `kenradar/processing/notify.py` | 通知推送 handler |
| `kenradar/adapters/__init__.py` | adapter 包 |
| `kenradar/adapters/protocols.py` | SourceAdapter/Transcriber/Organizer 等 Protocol |
| `kenradar/adapters/sources/__init__.py` | 来源 adapter 包 |
| `kenradar/adapters/sources/douyin.py` | 抖音 SourceAdapter 实现 |
| `scripts/backup_pg.sh` | PostgreSQL 备份脚本 |

### 修改文件
| 文件 | 变更 |
|------|------|
| `kenradar/domain/states.py` | 扩展所有状态 Enum |
| `kenradar/storage/pg_database.py` | 新增 ~20 个 repository 方法 |
| `kenradar/core/workflow.py` | 修复 GPU 耦合 + 提取 SQL 为 repository 调用 |
| `kenradar/core/config.py` | 增加 outbox/artifact 配置节 |
| `kenradar/web/app.py` | 使用状态 Enum + 新增 versioned API |
| `kenradar/web/queries.py` | 使用状态 Enum |
| `kenradar/scheduler/scheduler.py` | 设置 priority 字段 |
| `kenradar/notification/alert.py` | 增加 alert level Enum + 降级检测 |
| `kenradar/publishing/github_sync.py` | 增加 debounce 机制 |
| `kenradar/utils/logging.py` | 增加结构化日志 + correlation_id |
| `kenradar/jobs/handlers.py` | 精简为转发到 processing/ 的调度层 |
| `kenradar/jobs/worker.py` | 支持结构化日志 |
| `kenradar/__main__.py` | 可选：新增 backup 命令 |
| `tests/` | 新增对应测试 |

---

## Phase 0.6：解耦 Agnes/Ollama GPU 开关

### Task 0.6.1：修复 staged GPU 模式的 AI 禁用逻辑

**Files:**
- Modify: `kenradar/core/workflow.py:1023-1067`

**现状：** `_enable_llm_worker_for_pipeline()` 在 staged GPU 模式的 transcribe 阶段返回 `False`，导致 `pipeline.enable_llm_worker=False`，这会禁用所有 AI provider（包括远程 Agnes），而设计意图只是禁用本地 GPU Ollama。

**修改策略：** 分离"AI worker 是否启动"和"Ollama 是否可用"两个概念。staged GPU 的 transcribe 阶段应保持 AI worker 启用（允许远程 Agnes 工作），只禁止 GPU Ollama 的占用校验。

- [ ] **Step 1: 修改 `_enable_llm_worker_for_pipeline` 方法**

```python
def _enable_llm_worker_for_pipeline(self, transcribe_only_gpu: bool) -> bool:
    # staged GPU 的 transcribe 阶段：不禁用 AI worker，只跳过 GPU 独占校验
    # AI worker 是否启用由 pipeline.enable_llm_worker 独立控制
    if transcribe_only_gpu:
        return bool(self.config.get("pipeline.enable_llm_worker", True))
    return bool(self.config.get("pipeline.enable_llm_worker", True))
```

并在 staged GPU 的 transcribe 阶段过载中，只跳过 GPU 独占检查而不是禁用 AI worker：

```python
phase_overrides: dict[str, Any] = {
    "pipeline.mode": "transcribe_only_gpu",
    "pipeline.enable_llm_worker": True,   # 改为 True，允许远程 AI
    "gpu_scheduler.skip_gpu_exclusive_check": True,  # 新增：跳过 GPU 独占
}
```

同时在 `gpu_scheduler.py` 中增加 `skip_gpu_exclusive_check` 支持。

- [ ] **Step 2: 修改 `gpu_scheduler.py` 增加跳过 GPU 独占检查逻辑**

在 GPU 锁获取前检查 `gpu_scheduler.skip_gpu_exclusive_check` 配置，为 True 时跳过 GPU 独占锁而只保留 GPU 可用性检查。

- [ ] **Step 3: 添加 fallback 行为测试**

确保当 `ollama.enabled=false` 时，Agnes 仍然可以工作。检查 workflow.py 中 AI worker 启动条件不再耦合 Ollama 开关。

- [ ] **Step 4: 运行相关测试确认无回归**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "fix: decouple Agnes AI worker from Ollama GPU switch in staged mode"
```

---

## Phase 1：统一状态和 Repository

### Task 1.1：扩展 domain/states.py 包含所有状态 Enum

**Files:**
- Modify: `kenradar/domain/states.py`

**现状：** 只有 `TaskRunStatus` 一个 Enum，业务代码全部使用原始字符串

**修改：** 增加所有状态域的 Enum 定义

- [ ] **Step 1: 重写 `kenradar/domain/states.py`**

```python
from __future__ import annotations
from enum import StrEnum


class TaskRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

TASK_RUN_TERMINAL_STATUSES = frozenset({
    TaskRunStatus.SUCCESS,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
})


class ResearchJobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TRANSCRIBE_ONLY_COMPLETED = "transcribe_only_completed"
    TRANSCRIBE_ONLY_PARTIAL_FAILED = "transcribe_only_partial_failed"


class ResearchJobItemStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED_WAITING_SUMMARY = "transcribed_waiting_summary"
    SUMMARIZING = "summarizing"
    NOTING = "noting"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

RESEARCH_JOB_ITEM_ACTIVE_STATUSES = frozenset({
    ResearchJobItemStatus.RUNNING,
    ResearchJobItemStatus.DOWNLOADING,
    ResearchJobItemStatus.DOWNLOADED,
    ResearchJobItemStatus.TRANSCRIBING,
    ResearchJobItemStatus.TRANSCRIBED_WAITING_SUMMARY,
    ResearchJobItemStatus.SUMMARIZING,
    ResearchJobItemStatus.NOTING,
})

RESEARCH_JOB_ITEM_TERMINAL_STATUSES = frozenset({
    ResearchJobItemStatus.SUCCESS,
    ResearchJobItemStatus.FAILED,
    ResearchJobItemStatus.CANCELLED,
    ResearchJobItemStatus.SKIPPED,
})


class DownloadStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TranscriptStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class AlertLevel(StrEnum):
    DEGRADED = "degraded"
    WARNING = "warning"
    ERROR = "error"
    RECOVERED = "recovered"
    CRITICAL = "critical"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ArtifactStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    ARCHIVED = "archived"
```

- [ ] **Step 2: 更新 `kenradar/domain/__init__.py` 导出所有 Enum**

```python
from kenradar.domain.states import (
    TaskRunStatus,
    TASK_RUN_TERMINAL_STATUSES,
    ResearchJobStatus,
    ResearchJobItemStatus,
    RESEARCH_JOB_ITEM_ACTIVE_STATUSES,
    RESEARCH_JOB_ITEM_TERMINAL_STATUSES,
    DownloadStatus,
    TranscriptStatus,
    AnalysisStatus,
    AlertLevel,
    OutboxEventStatus,
    ArtifactStatus,
)

__all__ = [
    "TaskRunStatus",
    "ResearchJobStatus",
    "ResearchJobItemStatus",
    "DownloadStatus",
    "TranscriptStatus",
    "AnalysisStatus",
    "AlertLevel",
    "OutboxEventStatus",
    "ArtifactStatus",
]
```

- [ ] **Step 3: 验证导入正常**

```bash
python -c "from kenradar.domain import TaskRunStatus, ResearchJobStatus, ResearchJobItemStatus, DownloadStatus, TranscriptStatus, AnalysisStatus, AlertLevel; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(domain): add all status enums for state unification"
```

---

### Task 1.2：替换状态字符串（核心重构）

**Files:**
- Modify: `kenradar/core/workflow.py`（~50 处）
- Modify: `kenradar/storage/pg_database.py`（~20 处）
- Modify: `kenradar/web/app.py`（~5 处）
- Modify: `kenradar/web/queries.py`（~15 处）
- Modify: `kenradar/scheduler/scheduler.py`（~3 处）
- Modify: `kenradar/jobs/worker.py`（~5 处）
- Test: `tests/test_states.py`

**策略：** 逐文件替换。每个文件做一次 grep 替换，保持行为一致。字符串比较用 `status == TaskRunStatus.SUCCESS`，SQL 中字符串参数用 `TaskRunStatus.SUCCESS.value`（StrEnum 的 `.value` 返回原始字符串）。

由于 workflow.py 涉及最多（~50 处），且 SQL 中和 Python 判断都要改，建议分步：

**子任务 1.2a：workflow.py 中 Python 层状态比较**

将 `== "success"` 改为 `== TaskRunStatus.SUCCESS`，`!= "paused"` 改为 `!= ResearchJobStatus.PAUSED` 等。注意区分不同表的状态域。

- [ ] **Step 1: 替换 research_job 状态**（workflow.py）
  搜索 `status == "cancelled"`、`status != "paused"`、`status="running"` 等 research_job 域，替换为 `ResearchJobStatus.CANCELLED` 等。

- [ ] **Step 2: 替换 research_job_item 状态**（workflow.py）
  搜索 `status='pending'`、`"failed"`、`"success"`、`"skipped"` 等 research_job_item 域。

- [ ] **Step 3: 替换 transcript/analysis 状态**（workflow.py）
  搜索 `t.status = 'success'`、`status='failed'` 等。

**子任务 1.2b：pg_database.py 中状态替换**

- [ ] **Step 4: 替换 task_run 状态字符串**（pg_database.py）
  搜索 lines 655-803 中的 `'queued'`、`'running'`、`'success'` 等。

- [ ] **Step 5: 替换 transcript/analysis 状态字符串**（pg_database.py）
  搜索 lines 155-599 中的状态字符串。

**子任务 1.2c：Web 层状态替换**

- [ ] **Step 6: 替换 queries.py 状态**（web/queries.py）
  搜索 lines 645-648 的映射字典和 lines 32-900 中的状态过滤。

- [ ] **Step 7: 替换 app.py 状态**（web/app.py）
  搜索 lines 1943-1953 的 inline SQL。

**子任务 1.2d：Scheduler 和 Worker 替换**

- [ ] **Step 8: 替换 scheduler.py** 中 `"deferred"`、`"queued"` 等返回字符串。

- [ ] **Step 9: 替换 worker.py** 中状态字符串（lines 78-97）。

**子任务 1.2e：测试**

- [ ] **Step 10: 创建 `tests/test_states.py`**

```python
"""Test state enum consistency with database CHECK constraints."""
from kenradar.domain import (
    TaskRunStatus, ResearchJobStatus, ResearchJobItemStatus,
    DownloadStatus, TranscriptStatus, AnalysisStatus, AlertLevel,
)

def test_task_run_status_values():
    """Enum values must match DB CHECK constraints."""
    assert [s.value for s in TaskRunStatus] == [
        "queued", "running", "retry_wait", "success", "failed", "cancelled"
    ]

def test_research_job_status_values():
    assert [s.value for s in ResearchJobStatus] == [
        "pending", "queued", "running", "paused", "completed",
        "partial_failed", "failed", "cancelled",
        "transcribe_only_completed", "transcribe_only_partial_failed",
    ]

def test_terminal_statuses_disjoint():
    """Terminal status sets should be subsets of their enums."""
    for s in TaskRunStatus:
        assert s in TaskRunStatus
    for s in TASK_RUN_TERMINAL_STATUSES:
        assert s in TaskRunStatus
```

- [ ] **Step 11: 运行测试验证**

```bash
python -m pytest tests/test_states.py -v
```

- [ ] **Step 12: 运行完整测试套件**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 13: Commit**

```bash
git add -A && git commit -m "refactor(states): replace raw status strings with type-safe enums"
```

---

### Task 1.3：增加 state_transition API

**Files:**
- Create: `kenradar/domain/transitions.py`
- Modify: `kenradar/storage/pg_database.py`（新增 `insert_state_transition` 方法）

- [ ] **Step 1: 创建 `kenradar/domain/transitions.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class StateTransition:
    object_type: str
    object_id: str
    old_status: str | None
    new_status: str
    reason: str | None = None
    actor: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if result["created_at"] is None:
            result["created_at"] = datetime.now(timezone.utc)
        return result
```

- [ ] **Step 2: 在 pg_database.py 中增加 `insert_state_transition` 方法**

在 Database 类中增加：

```python
def insert_state_transition(
    self,
    object_type: str,
    object_id: str,
    old_status: str | None,
    new_status: str,
    reason: str | None = None,
    actor: str | None = None,
) -> None:
    with self.connect() as conn:
        conn.execute(
            """INSERT INTO state_transition
               (object_type, object_id, old_status, new_status, reason, actor, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
            (object_type, object_id, old_status, new_status, reason, actor),
        )
```

- [ ] **Step 3: 在现有状态变更处插入 transition 调用**

在 workflow.py、worker.py、scheduler.py 中所有修改状态的地方，在 UPDATE 后调用 `database.insert_state_transition(...)`。

重点位置：
- task_run 状态变更（worker.py:78-97 的 attempt/fail/success）
- research_job 状态变更（workflow.py:443, 503-507, 522, 536, 940 等）
- research_job_item 状态变更（workflow.py:1244-1248, 1442-1453 等）
- transcript/analysis 状态变更

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(domain): add state_transition tracking API"
```

---

### Task 1.4：提取 workflow.py 内联 SQL 到 Repository

**Files:**
- Modify: `kenradar/storage/pg_database.py`（新增 repository 方法）
- Modify: `kenradar/core/workflow.py`（调用 repository 方法替代 inline SQL）

**策略：** 将 workflow.py 中的 ~20 处 `conn.execute("""...""")` 调用逐一提取为 pg_database.py 中的命名方法。不改变 SQL 逻辑，只迁移位置。

- [ ] **Step 1: 在 pg_database.py 中新增以下 repository 方法**

```python
# === 研究任务相关 ===

def get_research_job_status(self, job_id: int) -> str | None:
    """获取 research_job 当前状态"""
    with self.connect() as conn:
        row = conn.execute(
            "SELECT status FROM research_job WHERE id = %s", (job_id,)
        ).fetchone()
        return row["status"] if row else None

def reset_stale_research_items(self, job_id: int, minutes: int) -> None:
    """将超时的研究条目重置为 pending"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE research_job_item
               SET status = 'pending', error_message = 'stale_reset', updated_at = NOW()
               WHERE job_id = %s
                 AND status IN ('running', 'downloading', 'downloaded', 'transcribing',
                                'summarizing', 'noting')
                 AND updated_at < NOW() - (%s * INTERVAL '1 minute')""",
            (job_id, minutes),
        )

def reset_stale_transcripts(self, minutes: int) -> None:
    """将超时的转录标记为失败"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE transcript SET status = 'failed', error_message = 'stale_reset',
               updated_at = NOW()
               WHERE status = 'running'
                 AND updated_at < NOW() - (%s * INTERVAL '1 minute')""",
            (minutes,),
        )

def get_research_report_data(self, job_id: int) -> list[dict]:
    """获取研究任务报告数据"""
    with self.connect() as conn:
        rows = conn.execute(
            """SELECT i.aweme_id, i.status, i.error_message,
                      COALESCE(a.title, i.aweme_id) AS title,
                      a.create_time, s.summary_path
               FROM research_job_item i
               LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
               LEFT JOIN summary s ON s.aweme_id = i.aweme_id
               WHERE i.job_id = %s
               ORDER BY a.create_time DESC, i.id DESC""",
            (job_id,),
        ).fetchall()
        return [dict(row) for row in rows]

def sync_research_item_status(
    self, aweme_id: str, status: str, error_message: str | None = None
) -> None:
    """同步研究条目状态"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE research_job_item SET status = %s, error_message = %s, updated_at = NOW()
               WHERE aweme_id = %s""",
            (status, error_message, aweme_id),
        )

def get_job_item_counts(self, aweme_id: str) -> list[dict]:
    """获取包含该 aweme 的所有 job 的统计"""
    with self.connect() as conn:
        rows = conn.execute(
            """SELECT job_id, COUNT(*) AS total_count,
                      COUNT(*) FILTER (WHERE status IN ('pending', 'running', 'downloading',
                        'downloaded', 'transcribing', 'transcribed_waiting_summary',
                        'summarizing', 'noting')) AS pending_count,
                      COUNT(*) FILTER (WHERE status = 'success') AS success_count,
                      COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                      COUNT(*) FILTER (WHERE status = 'skipped') AS skipped_count
               FROM research_job_item
               WHERE job_id IN (SELECT job_id FROM research_job_item WHERE aweme_id = %s)
               GROUP BY job_id""",
            (aweme_id,),
        ).fetchall()
        return [dict(row) for row in rows]

def update_research_job_counts(
    self, job_id: int, total: int, pending: int, success: int, failed: int,
    skipped: int, status: str, updated_at: str | None = None
) -> None:
    """更新研究任务计数和状态"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE research_job
               SET total_count = %s, pending_count = %s, success_count = %s,
                   failed_count = %s, skipped_count = %s, status = %s,
                   updated_at = COALESCE(%s::timestamptz, NOW())
               WHERE id = %s""",
            (total, pending, success, failed, skipped, status, updated_at, job_id),
        )

# === legacy 兼容查询 ===

def list_legacy_note_rows(self) -> list[dict]:
    """列出旧表结构中的笔记行"""
    with self.connect() as conn:
        rows = conn.execute(
            """SELECT a.aweme_id, a.title, a.create_time, a.desc, a.url,
                      a.download_path, b.name AS blogger_name,
                      t.status AS transcript_status, s.status AS summary_status,
                      s.summary_path, s.model AS ai_model, s.topics,
                      s.tags, s.value_score
               FROM aweme a
               LEFT JOIN blogger b ON b.id = a.blogger_id
               LEFT JOIN transcript t ON t.aweme_id = a.aweme_id AND t.status = 'success'
               LEFT JOIN summary s ON s.aweme_id = a.aweme_id
               ORDER BY a.create_time DESC, a.id DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

# === 研究任务管理 ===

def get_research_job(self, job_id: int) -> dict | None:
    """获取研究任务"""
    with self.connect() as conn:
        row = conn.execute(
            "SELECT * FROM research_job WHERE id = %s", (job_id,)
        ).fetchone()
        return dict(row) if row else None

def get_research_job_failed_items(self, job_id: int) -> list[str]:
    """获取研究任务中的失败条目 aweme_id 列表"""
    with self.connect() as conn:
        rows = conn.execute(
            "SELECT aweme_id FROM research_job_item WHERE job_id = %s AND status = 'failed'",
            (job_id,),
        ).fetchall()
        return [row["aweme_id"] for row in rows]

def get_research_job_publish_data(self, job_id: int) -> list[dict]:
    """获取发布所需的研究任务数据"""
    with self.connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT n.note_path
               FROM research_job_item rji
               JOIN content_item ci ON ci.content_id = rji.aweme_id
               JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
               WHERE rji.job_id = %s
                 AND rji.status IN ('success', 'skipped')
                 AND n.note_path IS NOT NULL""",
            (job_id,),
        ).fetchall()
        job = conn.execute(
            "SELECT id, blogger_name, status FROM research_job WHERE id = %s",
            (job_id,),
        ).fetchone()
        return {"job": dict(job) if job else None, "note_paths": [r["note_path"] for r in rows]}

def cancel_research_job_items(self, job_id: int) -> None:
    """取消研究任务的所有活动条目"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE research_job_item SET status = 'cancelled',
               error_message = 'cancelled_by_restart', updated_at = NOW()
               WHERE job_id = %s AND status IN ('pending', 'running', 'downloading',
                 'downloaded', 'transcribing', 'transcribed_waiting_summary',
                 'summarizing', 'noting')""",
            (job_id,),
        )

def get_creator(self, creator_id: int) -> dict | None:
    """获取创作者信息"""
    with self.connect() as conn:
        row = conn.execute(
            "SELECT id, platform_uid, nickname, profile_url FROM creator WHERE id = %s",
            (creator_id,),
        ).fetchone()
        return dict(row) if row else None

def load_aweme_for_retry(self, aweme_id: str) -> dict | None:
    """加载 aweme 用于重试操作"""
    with self.connect() as conn:
        row = conn.execute(
            """SELECT a.aweme_id, a.title, a.download_path, a.create_time, a.url,
                      a.desc, a.blogger_name,
                      t.status AS transcript_status, t.transcript_path,
                      s.status AS summary_status, s.summary_path
               FROM aweme a
               LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
               LEFT JOIN summary s ON s.aweme_id = a.aweme_id
               WHERE a.aweme_id = %s""",
            (aweme_id,),
        ).fetchone()
        return dict(row) if row else None

def set_research_job_error(self, job_id: int, error_message: str) -> None:
    """设置研究任务错误"""
    with self.connect() as conn:
        conn.execute(
            "UPDATE research_job SET status = 'failed', error_message = %s, updated_at = NOW() WHERE id = %s",
            (error_message, job_id),
        )
```

- [ ] **Step 2: 替换 workflow.py 中的 inline SQL**

逐一将 workflow.py 中的 `conn.execute("""...""")` 替换为 `self.database.get_research_job_status(...)` 等调用。

关键替换点：
| 行号 | 原 SQL | 替换方法 |
|------|--------|---------|
| 305 | SELECT status FROM research_job | `get_research_job_status(job_id)` |
| 1241-1249 | UPDATE research_job_item SET status='pending' WHERE ... | `reset_stale_research_items(job_id, minutes)` |
| 1259-1266 | UPDATE transcript SET status='failed' WHERE ... | `reset_stale_transcripts(minutes)` |
| 1307-1318 | SELECT i.aweme_id, i.status ... FROM research_job_item | `get_research_report_data(job_id)` |
| 1442-1453 | UPDATE research_job_item SET status = %s | `sync_research_item_status(aweme_id, status, error)` |
| 1456-1467 | SELECT job_id, COUNT(*) ... | `get_job_item_counts(aweme_id)` |
| 1486-1501 | UPDATE research_job SET total_count = %s | `update_research_job_counts(...)` |
| 1594-1607 | SELECT a.aweme_id, a.title ... | `list_legacy_note_rows()` |
| 1671-1679 | SELECT * FROM research_job WHERE id = %s | `get_research_job(job_id)` + `get_research_job_failed_items(job_id)` |
| 1732-1748 | SELECT ... FROM research_job_item ... | `get_research_job_publish_data(job_id)` |
| 1782-1804 | SELECT * FROM research_job + UPDATE ... SET status='cancelled' | `get_research_job(job_id)` + `cancel_research_job_items(job_id)` |
| 1821-1827 | SELECT id, platform_uid ... FROM creator | `get_creator(creator_id)` |
| 1841-1855 | SELECT a.aweme_id ... FROM aweme a LEFT JOIN | `load_aweme_for_retry(aweme_id)` |

- [ ] **Step 3: 运行测试验证**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor(workflow): extract inline SQL to pg_database repository methods"
```

---

### Task 1.5：告警级别区分 degraded/failed/recovered

**Files:**
- Modify: `kenradar/notification/alert.py`

- [ ] **Step 1: 修改 `AlertManager.notify()` 级别检查**

原来只接受 `"error"` 和 `"warning"`，现在扩展为可接受 `AlertLevel` 枚举：

```python
from kenradar.domain import AlertLevel

def notify(
    self,
    level: str | AlertLevel,
    component: str,
    message: str,
    aweme_id: str | None = None,
    title: str | None = None,
    context: dict | None = None,
) -> None:
    level_str = str(level.value) if isinstance(level, AlertLevel) else level
    ...
```

- [ ] **Step 2: 修改 `error()` 和 `warning()` 方法签名**

```python
def degraded(self, component, message, aweme_id=None, title=None, context=None):
    """降级告警：fallback 成功但使用备选方案"""
    self.notify(AlertLevel.DEGRADED, component, message, aweme_id, title, context)

def recovered(self, component, message, aweme_id=None, title=None, context=None):
    """恢复告警：之前失败的组件恢复正常"""
    self.notify(AlertLevel.RECOVERED, component, message, aweme_id, title, context)
```

- [ ] **Step 3: 在 workflow.py 中的 fallback 位置使用 `degraded()` 替代 `error()`**

例如 FunASR 失败后 Whisper 成功 → `alert.degraded()` 而非 `alert.error()`

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(alerts): distinguish degraded, failed, recovered alert levels"
```

---

## Phase 3：拆分 Stage 与资源调度

### Task 3.1：创建 ResourceRequirement 和 StageHandler 基类

**Files:**
- Create: `kenradar/processing/__init__.py`
- Create: `kenradar/processing/base.py`

- [ ] **Step 1: 创建 `kenradar/processing/__init__.py`**

空文件或包元数据

- [ ] **Step 2: 创建 `kenradar/processing/base.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ResourceRequirement:
    """资源需求定义"""
    pool: str           # 资源池名称：io:download, gpu:0, cpu:transcribe, api:agnes, fs:notes, git:repo
    capacity: int = 1   # 所需容量
    exclusive: bool = False  # 是否需要独占
    priority: int = 50  # 优先级


@dataclass
class StageContext:
    """Stage 执行上下文"""
    task_run_id: int
    content_item_id: int | None = None
    creator_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


class StageHandler(Protocol):
    """Stage handler 协议"""
    name: str
    requirements: list[ResourceRequirement]

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        """执行 stage 任务"""
        ...
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(processing): add StageHandler protocol and ResourceRequirement"
```

---

### Task 3.2：创建独立 Stage Handler 模块

**Files:**
- Create: `kenradar/processing/fetch.py`
- Create: `kenradar/processing/download.py`
- Create: `kenradar/processing/transcribe.py`
- Create: `kenradar/processing/organize.py`
- Create: `kenradar/processing/note.py`
- Create: `kenradar/processing/publish.py`
- Create: `kenradar/processing/notify.py`
- Modify: `kenradar/jobs/handlers.py`（精简为转发层）

**策略：** 每个 handler 从 `Workflow` 类中提取对应方法，包装为独立的 `StageHandler`。初期直接调用 Workflow 的同名方法，后续逐步拆出独立实现。

**子任务 3.2a：创建 fetch handler（博主内容抓取）**

- [ ] **Step 1: 创建 `kenradar/processing/fetch.py`**

```python
from __future__ import annotations
from kenradar.processing.base import StageHandler, StageContext, ResourceRequirement
from typing import Any

class FetchHandler:
    """博主最新内容抓取 handler"""
    name = "fetch"
    requirements = [
        ResourceRequirement(pool="io:douyin_fetch", capacity=1, exclusive=False),
    ]

    def __init__(self, workflow: Any, database: Any, config: dict):
        self._workflow = workflow
        self._database = database
        self._config = config

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        """执行抓取任务"""
        # 当前委托给 Workflow，后续拆出独立实现
        result = await self._workflow._fetch_latest_videos(
            ctx.payload.get("sec_uid"),
            ctx.payload.get("max_count", 30),
        )
        return {"fetched": len(result.get("items", [])), "items": result.get("items", [])}
```

**子任务 3.2b：创建 download handler**

- [ ] **Step 2: 创建 `kenradar/processing/download.py`**

从 Workflow 的下载逻辑中提取。

```python
class DownloadHandler:
    name = "download"
    requirements = [
        ResourceRequirement(pool="io:download", capacity=5, exclusive=False),
    ]
    ...
```

**子任务 3.2c：创建 transcribe handler**

- [ ] **Step 3: 创建 `kenradar/processing/transcribe.py`**

```python
class TranscribeHandler:
    name = "transcribe"
    requirements = [
        ResourceRequirement(pool="cpu:transcribe", capacity=2, exclusive=False),
        ResourceRequirement(pool="gpu:0", capacity=1, exclusive=True, priority=30),
    ]
```

**子任务 3.2d-e：创建 organize / note handler**

- [ ] **Step 4-5: 创建 `organize.py` 和 `note.py`**

**子任务 3.2f-g：创建 publish / notify handler**

- [ ] **Step 6-7: 创建 `publish.py` 和 `notify.py`**

**子任务 3.2h：精简 `handlers.py`**

- [ ] **Step 8: 修改 `kenradar/jobs/handlers.py`**

原来直接包含所有任务类型的分发逻辑，改为转发到 `processing/` 下的 handler：

```python
from kenradar.processing.fetch import FetchHandler
from kenradar.processing.download import DownloadHandler
...

HANDLER_MAP = {
    "run_once": None,  # 仍由 Workflow.run_once 处理
    "fetch_blogger": FetchHandler,
    "download_video": DownloadHandler,
    "transcribe": TranscribeHandler,
    "organize": OrganizeHandler,
    "render_note": NoteHandler,
    "publish_site": PublishHandler,
    "notify": NotifyHandler,
}
```

- [ ] **Step 9: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 10: Commit**

```bash
git add -A && git commit -m "feat(processing): create independent stage handler modules"
```

---

### Task 3.3：GPU 资源使用数据库 resource lease

**Files:**
- Modify: `kenradar/storage/pg_database.py`
- Modify: `kenradar/core/gpu_scheduler.py`

- [ ] **Step 1: 在 pg_database.py 中增加 GPU resource lease 辅助方法**

```python
def acquire_gpu_lease(self, owner: str, lease_seconds: int = 300) -> bool:
    """获取 GPU 资源租约"""
    return self.acquire_resource_lease("gpu:0", owner, lease_seconds=lease_seconds)

def release_gpu_lease(self, owner: str) -> None:
    """释放 GPU 资源租约"""
    self.release_resource_lease("gpu:0", owner)
```

- [ ] **Step 2: 修改 `gpu_scheduler.py`**

在现有的文件锁基础上增加数据库 resource lease 作为第二道保护。只在数据库可用时获取。

```python
def _acquire_db_gpu_lease(self) -> bool:
    if self.database and hasattr(self.database, 'acquire_gpu_lease'):
        return self.database.acquire_gpu_lease(self._lease_owner)
    return True
```

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(gpu): add database resource lease for GPU exclusive access"
```

---

### Task 3.4：Agnes 共享限流器

**Files:**
- Modify: `kenradar/core/organizer.py`
- `kenradar/resources/shared_limiter.py`（如果新建）

**策略：** 当前 Agnes 在 `organizer.py` 中使用进程内 RPM 限流（19 RPM）。在单机单进程场景下这已经足够。增加一个可选的数据库级共享限流器，为多 worker 场景准备。

- [ ] **Step 1: 分析当前限流实现**

确认 `organizer.py` 中的 RPM 限流机制（基于 `time.sleep` 的令牌桶或滑动窗口）。

- [ ] **Step 2: 增加数据库共享限流表**

在 `SCHEMA_SQL` 中增加：

```sql
CREATE TABLE IF NOT EXISTS rate_limiter (
    limiter_key     VARCHAR(128) PRIMARY KEY,
    count           INT DEFAULT 0,
    window_start    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

- [ ] **Step 3: 实现 `acquire_rate_limit()` 方法**

```python
def acquire_rate_limit(self, limiter_key: str, max_count: int, window_seconds: int = 60) -> bool:
    """尝试获取限流许可"""
    with self.connect() as conn:
        # 重置过期窗口
        conn.execute(
            """UPDATE rate_limiter SET count = 0, window_start = NOW(), updated_at = NOW()
               WHERE limiter_key = %s AND window_start < NOW() - (%s * INTERVAL '1 second')""",
            (limiter_key, window_seconds),
        )
        # 插入或忽略
        conn.execute(
            """INSERT INTO rate_limiter (limiter_key, count, window_start, updated_at)
               VALUES (%s, 0, NOW(), NOW())
               ON CONFLICT (limiter_key) DO NOTHING""",
            (limiter_key,),
        )
        # 增加计数
        conn.execute(
            """UPDATE rate_limiter SET count = count + 1, updated_at = NOW()
               WHERE limiter_key = %s""",
            (limiter_key,),
        )
        # 检查是否超限
        row = conn.execute(
            "SELECT count FROM rate_limiter WHERE limiter_key = %s", (limiter_key,)
        ).fetchone()
        return bool(row and row["count"] <= max_count)
```

- [ ] **Step 4: 在 organizer.py 中可选使用数据库限流**

当 `database` 可用且配置启用时，优先使用数据库级限流。

- [ ] **Step 5: 运行测试 + Commit**

---

### Task 3.5：Scheduler 优先级

**Files:**
- Modify: `kenradar/scheduler/scheduler.py`

- [ ] **Step 1: 设置 scheduler 任务优先级为 100（高于默认 50）**

```python
# scheduler 中 enqueue_task_run 时
priority=100,  # 实时监控具有更高优先级
```

区别于历史研究任务（默认 50），确保监控任务优先于回填/研究任务。

- [ ] **Step 2: 确保 `claim_next_task_run` 的 ORDER BY 正确工作**

检查 pg_database.py 的 ORDER BY 已经是 `priority DESC, available_at, created_at`，正确。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(scheduler): set monitor tasks with higher priority (100)"
```

---

### Task 3.6：发布和 GitHub sync debounce

**Files:**
- Modify: `kenradar/publishing/github_sync.py`
- Modify: `kenradar/core/workflow.py`（发布调用点）

- [ ] **Step 1: 在 `GithubSyncManager` 中增加 debounce 机制**

```python
import time

class GithubSyncManager:
    def __init__(self, ...):
        ...
        self._last_sync_time: float = 0
        self._debounce_seconds: int = 300  # 5 分钟

    def sync(self, dry_run: bool = False, force: bool = False) -> dict:
        now = time.time()
        if not force and (now - self._last_sync_time) < self._debounce_seconds:
            elapsed = now - self._last_sync_time
            logger.info("GitHub sync debounced (%.0fs since last sync, threshold %ds)",
                       elapsed, self._debounce_seconds)
            return {"status": "debounced", "elapsed_seconds": elapsed}
        self._last_sync_time = now
        # ... 原有 sync 逻辑
```

- [ ] **Step 2: 在 workflow.py 的发布调用点使用 `force=False`**

仅在研究任务完成这种重要事件时使用 `force=True`，定时监控的发布使用 `force=False`：

```python
# 定时监控完成后的发布（可 debounce）
stats.update(self._sync_github_publication("monitor_updates", force=False))

# 研究任务完成后的发布（强制立即推送）
stats.update(self._sync_github_publication("research_complete", force=True))
```

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(publishing): add github sync debounce mechanism"
```

---

## Phase 4：事务化发布和通知

### Task 4.1：Artifact 写入和消费

**Files:**
- Modify: `kenradar/storage/pg_database.py`
- Modify: `kenradar/core/workflow.py`（笔记写入后登记 artifact）

- [ ] **Step 1: 在 pg_database.py 中增加 artifact 方法**

```python
def register_artifact(
    self,
    content_item_id: int | None,
    task_run_id: int | None,
    kind: str,
    path: str,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> int:
    """注册一个产物（笔记/HTML/转录文件等）"""
    with self.connect() as conn:
        row = conn.execute(
            """INSERT INTO artifact (content_item_id, task_run_id, kind, path,
                   size_bytes, sha256, status, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, 'active', NOW(), NOW())
               ON CONFLICT (kind, path) DO UPDATE SET
                   content_item_id = COALESCE(EXCLUDED.content_item_id, artifact.content_item_id),
                   size_bytes = EXCLUDED.size_bytes,
                   sha256 = EXCLUDED.sha256,
                   updated_at = NOW()
               RETURNING id""",
            (content_item_id, task_run_id, kind, path, size_bytes, sha256),
        ).fetchone()
        return row["id"] if row else 0

def list_artifacts(self, content_item_id: int | None = None, kind: str | None = None) -> list[dict]:
    """列出产物"""
    with self.connect() as conn:
        where = []
        params = []
        if content_item_id is not None:
            where.append("content_item_id = %s")
            params.append(content_item_id)
        if kind:
            where.append("kind = %s")
            params.append(kind)
        where.append("status = 'active'")
        sql = f"SELECT * FROM artifact WHERE {' AND '.join(where)} ORDER BY created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

def deactivate_artifact(self, artifact_id: int) -> None:
    """标记产物为已删除"""
    with self.connect() as conn:
        conn.execute(
            "UPDATE artifact SET status = 'deleted', updated_at = NOW() WHERE id = %s",
            (artifact_id,),
        )
```

- [ ] **Step 2: 在 workflow.py 的笔记/HTML/转录写入成功后调用 `register_artifact`**

在 `_write_item_summary`（line 2111）写入成功后：

```python
note_path = path  # 笔记文件路径
if self.database:
    try:
        size = note_path.stat().st_size if note_path.exists() else 0
        self.database.register_artifact(
            content_item_id=content_item_id,
            task_run_id=None,
            kind="note:md",
            path=str(note_path),
            size_bytes=size,
        )
    except Exception:
        logger.warning("Failed to register artifact", exc_info=True)
```

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

---

### Task 4.2：笔记原子写

**Files:**
- Modify: `kenradar/core/workflow.py`（`_write_item_summary` 等方法）

- [ ] **Step 1: 修改 `_write_item_summary` 的写入方式**

原来（line 2111）：
```python
path.write_text("\n".join(lines), encoding="utf-8")
```

改为原子写入：
```python
import os, tempfile

# 原子写入
tmp = tempfile.NamedTemporaryFile(
    mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
)
try:
    tmp.write("\n".join(lines))
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp.close()
    os.replace(tmp.name, str(path))
except BaseException:
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    raise
```

- [ ] **Step 2: 对 `_write_research_report` 和 `_write_backfill_summary` 做同样修改**

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

---

### Task 4.3：Outbox Event 写入和消费

**Files:**
- Create: `kenradar/jobs/outbox_consumer.py`
- Modify: `kenradar/storage/pg_database.py`

- [ ] **Step 1: 在 pg_database.py 中增加 outbox 方法**

```python
def write_outbox_event(
    self,
    event_type: str,
    payload: dict,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    idempotency_key: str | None = None,
) -> int:
    """写入 outbox event"""
    with self.connect() as conn:
        row = conn.execute(
            """INSERT INTO outbox_event
               (event_type, aggregate_type, aggregate_id, idempotency_key,
                payload_json, status, available_at, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s::jsonb, 'pending', NOW(), NOW(), NOW())
               RETURNING id""",
            (event_type, aggregate_type, aggregate_id, idempotency_key,
             json.dumps(payload) if isinstance(payload, dict) else payload),
        ).fetchone()
        return row["id"] if row else 0

def claim_outbox_events(self, batch_size: int = 10, owner: str = "outbox_consumer") -> list[dict]:
    """领取待处理的 outbox events"""
    with self.connect() as conn:
        rows = conn.execute(
            """UPDATE outbox_event SET status = 'running', locked_by = %s,
               locked_at = NOW(), lease_expires_at = NOW() + INTERVAL '5 minutes',
               attempt = attempt + 1, updated_at = NOW()
               WHERE id IN (
                   SELECT id FROM outbox_event
                   WHERE status = 'pending'
                      OR (status = 'running' AND lease_expires_at < NOW())
                   ORDER BY available_at, id
                   FOR UPDATE SKIP LOCKED
                   LIMIT %s
               )
               RETURNING *""",
            (owner, batch_size),
        ).fetchall()
        return [dict(row) for row in rows]

def complete_outbox_event(self, event_id: int) -> None:
    """完成 outbox event"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE outbox_event SET status = 'success', processed_at = NOW(),
               updated_at = NOW() WHERE id = %s""",
            (event_id,),
        )

def fail_outbox_event(self, event_id: int, error: str) -> None:
    """标记 outbox event 为失败"""
    with self.connect() as conn:
        conn.execute(
            """UPDATE outbox_event SET status = 'failed', last_error = %s,
               updated_at = NOW() WHERE id = %s""",
            (error, event_id),
        )
```

- [ ] **Step 2: 创建 `kenradar/jobs/outbox_consumer.py`**

```python
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)


class OutboxConsumer:
    """消费 outbox_event 表的事件"""

    def __init__(self, database, workflow, config):
        self._database = database
        self._workflow = workflow
        self._config = config
        self._running = False

    async def run_forever(self, interval: float = 5.0):
        self._running = True
        while self._running:
            try:
                events = self._database.claim_outbox_events(batch_size=5)
                for event in events:
                    await self._process_event(event)
            except Exception:
                logger.exception("Outbox consumer error")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False

    async def _process_event(self, event: dict) -> None:
        event_type = event["event_type"]
        try:
            if event_type.startswith("publish:"):
                # 调用 publish handler
                pass
            elif event_type.startswith("notify:"):
                # 调用 notify handler
                pass
            self._database.complete_outbox_event(event["id"])
        except Exception as exc:
            logger.error("Outbox event failed: %s", exc)
            self._database.fail_outbox_event(event["id"], str(exc))
```

- [ ] **Step 3: 在关键任务完成后写入 outbox**

在 workflow.py、worker.py 中的 task_run/publish/notify 完成位置，调用 `write_outbox_event`。

- [ ] **Step 4: 运行测试 + Commit**

---

### Task 4.4：Push 去重和重放

**Files:**
- Modify: `kenradar/notification/feishu.py`
- Modify: `kenradar/storage/pg_database.py`

- [ ] **Step 1: 增加 `push_log` 去重检查**

在推送前检查 idempotency_key 是否已存在，避免重复推送。

```python
def check_push_idempotency(self, idempotency_key: str) -> bool:
    """检查推送是否已发送过"""
    with self.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM push_log WHERE idempotency_key = %s AND status = 'success'",
            (idempotency_key,),
        ).fetchone()
        return row is not None
```

- [ ] **Step 2: 在 Feishu 推送时生成 idempotency_key**

基于 `(batch_id, event_type)` 生成唯一键，推送前检查。

- [ ] **Step 3: 运行测试 + Commit**

---

### Task 4.5：清理任务依据 Artifact 生命周期执行

**Files:**
- Modify: `kenradar/core/workflow.py` 或 `kenradar/processing/cleanup.py`

- [ ] **Step 1: 分析当前清理逻辑**

现有的 `cleanup-downloads` 命令和 `_remove_stale_item_notes` 是基于文件名猜测清理。改为查询 artifact 表。

- [ ] **Step 2: 实现 artifact 感知的清理**

```python
def cleanup_by_artifact_lifecycle(self, database, config) -> dict:
    """根据 artifact 生命周期清理，不依赖文件名猜测"""
    stats = {"cleaned": 0, "errors": 0}
    artifacts = database.list_artifacts(status="deleted")
    for art in artifacts:
        path = Path(art["path"])
        if path.exists():
            try:
                path.unlink()
                stats["cleaned"] += 1
            except OSError as e:
                logger.warning("Failed to cleanup artifact %s: %s", art["path"], e)
                stats["errors"] += 1
    return stats
```

- [ ] **Step 3: 运行测试 + Commit**

---

## Phase 5：平台化接口与运维

### Task 5.1：定义 Adapter Protocol

**Files:**
- Create: `kenradar/adapters/__init__.py`
- Create: `kenradar/adapters/protocols.py`

- [ ] **Step 1: 创建 `kenradar/adapters/protocols.py`**

```python
from __future__ import annotations
from typing import AsyncIterator, Protocol, Any
from dataclasses import dataclass


@dataclass
class SourceItem:
    id: str
    title: str | None = None
    description: str | None = None
    url: str | None = None
    author_name: str | None = None
    published_at: str | None = None
    extra: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    """内容源适配器协议"""
    platform: str

    async def fetch_items(self, sec_uid: str, max_count: int = 30, **kwargs) -> list[SourceItem]:
        """获取博主最新内容列表"""
        ...

    async def resolve_user(self, url: str | None, name: str | None, sec_uid: str | None) -> dict:
        """解析用户信息"""
        ...


class MediaDownloader(Protocol):
    """媒体下载器协议"""
    async def download(self, url: str, output_dir: str, filename: str, **kwargs) -> str | None:
        """下载媒体文件，返回本地路径"""
        ...


class Transcriber(Protocol):
    """转录器协议"""
    async def transcribe(self, audio_path: str, **kwargs) -> dict:
        """转录音频，返回文本和元数据"""
        ...


class Organizer(Protocol):
    """AI 整理器协议"""
    async def organize(self, transcript: str, title: str | None = None, **kwargs) -> dict:
        """整理转录文本，返回结构化摘要"""
        ...
```

- [ ] **Step 2: Commit**

---

### Task 5.2：抖音 SourceAdapter 实现

**Files:**
- Create: `kenradar/adapters/sources/__init__.py`
- Create: `kenradar/adapters/sources/douyin.py`

- [ ] **Step 1: 创建 `kenradar/adapters/sources/douyin.py`**

包装现有的 `vendor/douyin_downloader` 模块，实现 `SourceAdapter` 接口。

```python
from kenradar.adapters.protocols import SourceAdapter, SourceItem
from kenradar.vendor.douyin_downloader import DouyinDownloader


class DouyinSourceAdapter(SourceAdapter):
    platform = "douyin"

    def __init__(self, config: dict):
        self._downloader = DouyinDownloader(config)

    async def fetch_items(self, sec_uid: str, max_count: int = 30, **kwargs) -> list[SourceItem]:
        items = await self._downloader.fetch_user_posts(sec_uid, max_count=max_count)
        return [
            SourceItem(
                id=item["aweme_id"],
                title=item.get("desc", ""),
                url=f"https://www.douyin.com/video/{item['aweme_id']}",
                published_at=item.get("create_time"),
                extra=item,
            )
            for item in items
        ]

    async def resolve_user(self, url=None, name=None, sec_uid=None) -> dict:
        return await self._downloader.resolve_user(url=url, name=name, sec_uid=sec_uid)
```

- [ ] **Step 2: Commit**

---

### Task 5.3：结构化日志 + Correlation ID

**Files:**
- Modify: `kenradar/utils/logging.py`

- [ ] **Step 1: 增加 structured logging 支持**

```python
import logging
import json
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)

def get_correlation_id() -> str | None:
    return _correlation_id.get()


class StructuredFormatter(logging.Formatter):
    """可选的结构化 JSON 日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        cid = get_correlation_id()
        if cid:
            record.msg = f"[correlation={cid}] {record.msg}"
        return super().format(record)
```

- [ ] **Step 2: 在 web 请求入口设置 correlation_id**

```python
# web/app.py 中每个请求处理前
import uuid
kenradar.utils.logging.set_correlation_id(str(uuid.uuid4())[:8])
```

- [ ] **Step 3: 在 worker.py 的任务执行中设置 correlation_id**

```python
# worker.py 处理 task_run 时
kenradar.utils.logging.set_correlation_id(f"task_{task_run['id']}")
```

- [ ] **Step 4: Commit**

---

### Task 5.4：备份策略和版本化 API

**Files:**
- Create: `scripts/backup_pg.sh`
- Modify: `kenradar/web/app.py`

- [ ] **Step 1: 创建 `scripts/backup_pg.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-./data/backups}"
DB_URL="${DATABASE_URL}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
pg_dump "$DB_URL" | gzip > "$BACKUP_DIR/kenradar_$TIMESTAMP.sql.gz"
echo "Backup saved: $BACKUP_DIR/kenradar_$TIMESTAMP.sql.gz"
# 保留最近 7 天
find "$BACKUP_DIR" -name "kenradar_*.sql.gz" -mtime +7 -delete
```

- [ ] **Step 2: 在 web/app.py 中增加版本化 API 端点**

```python
# /api/v1/health/live
# /api/v1/health/ready
# /api/v1/tasks
# /api/v1/contents
```

现有路由保留兼容，新增 `/api/v1/` 前缀的版本化路由。

- [ ] **Step 3: Commit**

---

## 执行顺序总结

```
Phase 0.6 (独立, 1 task)
    ↓
Phase 1 (5 tasks, 有依赖关系)
    ├── Task 1.1: 扩展 Enum
    ├── Task 1.2: 替换状态字符串 (可以分文件并行)
    ├── Task 1.3: Transition API
    ├── Task 1.4: Repository 提取
    └── Task 1.5: 告警级别
    ↓
Phase 3 (5 tasks, 部分可并行)
    ├── Task 3.1: 基类和协议
    ├── Task 3.2: Handler 拆分 (7 个 handler, 可并行)
    ├── Task 3.3: GPU resource lease
    ├── Task 3.4: 共享限流 (可选)
    ├── Task 3.5: Scheduler 优先级
    └── Task 3.6: Publish debounce
    ↓
Phase 4 (5 tasks, 部分可并行)
    ├── Task 4.1: Artifact 写入
    ├── Task 4.2: 笔记原子写
    ├── Task 4.3: Outbox 写入消费
    ├── Task 4.4: Push 去重
    └── Task 4.5: Artifact 清理
    ↓
Phase 5 (4 tasks, 相对独立)
    ├── Task 5.1: Protocol 定义
    ├── Task 5.2: 抖音 adapter
    ├── Task 5.3: 结构化日志
    └── Task 5.4: 备份 + 版本化 API
```
