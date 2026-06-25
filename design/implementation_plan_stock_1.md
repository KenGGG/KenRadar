# 修复 NotebookLM 公司研究对接 — 重写 NotebookLMClient

## 问题诊断

### 1. 当前客户端架构完全错误

现有 [notebooklm_client.py](file:///data/Projects/KenRadar/kenradar/company_research/notebooklm_client.py) 是一个"动态方法探测"包装器，试图通过 `hasattr` 猜测 `notebooklm-py` 的 API（`client.notebooks.create`、`client.sources.upload_pdf`、`client.chat.ask_question` 等）。

但 **`notebooklm-py 0.7.2` 的真实 API 完全不是这样的：**

| 现有代码假设 | 真实 API |
|---|---|
| `client.notebooks.create_notebook(title=)` | `await client.notebooks.create(title)` → `Notebook` |
| `client.sources.upload_pdf(notebook_id=, file_path=, title=)` | `await client.sources.add_file(notebook_id, file_path, wait=True)` → `Source` |
| `client.sources.wait_for_sources(notebook_id=, source_ids=)` | `await client.sources.wait_for_sources(notebook_id, source_ids)` → `list[Source]` |
| `client.chat.ask_question(notebook_id=, prompt=)` | `await client.chat.ask(notebook_id, question)` → `AskResult` |
| `client.notebooks.delete_notebook(notebook_id=)` | `await client.notebooks.delete(notebook_id)` → `None` |

> [!CAUTION]
> 所有这些方法在现有代码中都被 `_call` + `_api` 辅助函数动态调用，参数名全部不匹配（如 `prompt` vs `question`、`upload_pdf` vs `add_file`），**导致 100% 调用失败**。

### 2. 客户端初始化方式错误

```python
# 现有代码
client_cls.from_storage()  # 返回 _FromStorageContext (async context manager)
# 但代码试图直接当 client 用
```

真实用法应是：
```python
async with notebooklm.NotebookLMClient.from_storage() as client:
    notebook = await client.notebooks.create("Title")
    # ...
```

### 3. 返回值类型不匹配

- `Notebook` 对象有 `.id`, `.title` 属性，不是 dict
- `Source` 对象有 `.id`, `.title`, `.status` 属性，不是 dict
- `AskResult` 有 `.answer`, `.conversation_id`, `.references` 属性，不是 dict 

### 4. 上传 106 个 PDF 全部 error

从 `notebooklm source list` 可以确认：
- 106 个 PDF 已经上传到 notebook `7afe942f` 
- **所有 source 状态都是 `error`，类型是 `Unknown`**
- 这说明上传本身执行了，但文件处理失败

可能原因：
- NotebookLM 账户有**源文件数量限制**（Standard: 50, Plus: 100 per notebook）
- 部分 PDF 可能过大或格式异常
- 一次性上传太多超过限流

### 5. 登录账号问题

`notebooklm auth check --test` 显示认证成功（`token_fetch: true`）。`notebooklm_session.json` 记录的 `garworn8848@gmail.com` 与实际认证 profile 一致。**登录本身目前正常**，但 `_company_notebooklm_relogin` 中的 `--account` 参数依赖 `notebooklm login --browser-cookies chrome --account email`，如果 Chrome 中没有该账号的 cookie 会失败。

---

## 修复方案

### 核心修改：重写 `notebooklm_client.py`

完全废弃动态探测模式，改为直接调用 `notebooklm-py 0.7.2` 的已知 API：

#### [MODIFY] [notebooklm_client.py](file:///data/Projects/KenRadar/kenradar/company_research/notebooklm_client.py)

重写核心逻辑：

```python
import notebooklm

class NotebookLMClient:
    def __init__(self):
        self._client = None
        self._ctx = None

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        self._ctx = notebooklm.NotebookLMClient.from_storage()
        self._client = await self._ctx.__aenter__()
        return self._client

    async def close(self):
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
            self._ctx = None
            self._client = None

    async def create_notebook(self, title: str) -> dict[str, str]:
        client = await self._ensure_client()
        nb = await client.notebooks.create(title)
        return {"id": nb.id, "title": nb.title}

    async def upload_pdf(self, notebook_id, file_path, title=None):
        client = await self._ensure_client()
        source = await client.sources.add_file(
            notebook_id, str(file_path),
            wait=False,  # 不等待处理完成
            title=title,
        )
        return NotebookSource(source.id, source.title or title or Path(file_path).name, "uploaded")

    async def wait_sources_ready(self, notebook_id, source_ids, timeout=900):
        client = await self._ensure_client()
        ready = await client.sources.wait_for_sources(notebook_id, source_ids, timeout=timeout)
        return [NotebookSource(s.id, s.title or s.id, "ready" if s.is_ready else "error") for s in ready]

    async def ask_question(self, notebook_id, prompt):
        client = await self._ensure_client()
        result = await client.chat.ask(notebook_id, prompt)
        refs = [{"source_id": r.source_id, "cited_text": r.cited_text or ""} for r in (result.references or [])]
        return NotebookAnswer(
            text=result.answer,
            raw=result.raw_response,
            references=refs,
            conversation_id=result.conversation_id,
            source_ids=[r.source_id for r in (result.references or [])],
        )

    async def delete_notebook(self, notebook_id):
        client = await self._ensure_client()
        await client.notebooks.delete(notebook_id)
```

### 上传策略优化

当前代码一次性上传 106 个 PDF，**但 NotebookLM 有单 notebook 源数量限制**（Standard: 50, Plus: 100）。需要：

1. **上传前检查账户限额** — 使用 `client.notebooks.get(notebook_id).sources_count` 检查
2. **分批上传 + wait** — 每上传 10 个后等待处理完成再继续
3. **超限处理** — 如果 PDF 数量超过限额，按重要性排序截取
4. **上传失败容错** — 单个 PDF 上传失败不影响其他 PDF

#### [MODIFY] [service.py](file:///data/Projects/KenRadar/kenradar/company_research/service.py)

在 `run_job` 的上传阶段添加：
- 批量上传分组（每批 10 个）
- 每批上传后等待处理完成
- 添加 source limit 检查和日志
- 在 job 结束时调用 `client.close()` 清理连接

### 后续优化

#### [MODIFY] [service.py](file:///data/Projects/KenRadar/kenradar/company_research/service.py) — 连接生命周期管理

在 `run_job` 和 `run_batch` 结束时确保 `await self.notebook_client.close()` 关闭连接。

---

## 关键风险

> [!WARNING]
> **NotebookLM 源数量限制：** 106 个 PDF 可能超出账户限额。Standard 账户限制 50 个源/notebook。需确认当前账户等级。如果是 Standard 账户，106 个 PDF 不可能全部上传，需要分策略处理。

> [!IMPORTANT]
> **现有已创建的 notebook `7afe942f`** 中 106 个 source 全部是 error 状态，需要用户决定：
> 1. 删除这个 notebook，清理后重新创建
> 2. 在新代码中增加自动清理 error sources 的逻辑

## Open Questions

1. **NotebookLM 账户等级？** Standard (50源) / Plus (100源) / Pro (300源)？这决定单次上传上限。如果是 Standard，106 个 PDF 需要拆分多个 notebook 或精选。

回答：根据页面中选择的账号决定的，有standard和pro两种。客户选择pro账号就有对应的300源功能。客户之前选的是pro账号。

2. **是否需要先删除现有错误 notebook `7afe942f`？** 建议删除后重试。

回答：删除。客户之前自己尝试上传的时候把106个pdf全传进去了，然后全显示error了。我删掉，重新来。

3. **PDF 数量策略：** 如果超出限额，优先保留哪些类型的公告？(年报/季报优先 vs 按时间)

回答：就一个公司。默认情况下，系统会按照时间倒序对所有公告进行排序，并自动选择最新的 100 个公告进行上传。

## Verification Plan

### Automated Tests
```bash
# 编译检查
/home/ken/miniconda3/envs/openclaw/bin/python -m compileall kenradar/company_research/

# 验证 notebooklm-py API 兼容性（小规模端到端测试）
/home/ken/miniconda3/envs/openclaw/bin/python -c "
import asyncio, notebooklm

async def test():
    async with notebooklm.NotebookLMClient.from_storage() as client:
        nb = await client.notebooks.create('test_api_check')
        print(f'Created: {nb.id}')
        await client.notebooks.delete(nb.id)
        print('Deleted OK')

asyncio.run(test())
"
```

### Manual Verification
- 用 1-2 个 PDF 测试完整上传 → 提问 → 删除流程
- 确认 Web 后台公司研究页面正常触发任务
