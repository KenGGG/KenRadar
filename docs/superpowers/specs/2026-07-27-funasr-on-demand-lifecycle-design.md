# FunASR 按需启动与空闲释放设计

## 目标

KenRadar 启动时不再自动加载 FunASR 模型或占用 GPU 显存。只有实际进入 FunASR 转录阶段时才启动本地服务；批量任务期间复用该服务；连续空闲 300 秒且没有活跃转录请求时，服务自动退出并释放约 2 GB 显存。

## 范围

本次仅调整仓库内本地 FunASR 服务的生命周期管理，不改变转录质量校验、Whisper fallback、GPU 锁、笔记生成、数据库状态或发布推送流程。远程或人工管理的 FunASR endpoint 仍受支持。

## 配置

在 `ai.funasr` 下增加：

- `managed: true`：是否由 KenRadar 按需管理本地 FunASR。设为 `false` 时只调用配置的 endpoint，不运行本地启停脚本。
- `idle_timeout_seconds: 300`：没有活跃请求后的自动退出时间。正数启用空闲退出；诊断时可通过环境变量覆盖或禁用。
- `startup_timeout_seconds: 180`：按需启动后的健康检查等待上限。

环境变量继续覆盖脚本默认值。现有 `start-funasr`、`stop-funasr`、`restart-funasr`、`status-funasr` 和日志命令保留。

## 生命周期

1. `./ctl.sh start` 只启动 KenRadar Web、worker 或 schedule，不再调用 `start_funasr`。
2. 转录器准备向 FunASR endpoint 提交音频前检查服务健康状态。
3. `managed: true` 且服务不可用时，转录器在跨进程文件锁内再次检查健康状态，然后调用仓库内 `scripts/start_funasr_server.sh`。
4. 启动脚本等待 `/health` 就绪。其他并发转录调用在同一锁外或锁后复用已经启动的服务，避免重复进程和端口竞争。
5. FunASR 服务跟踪活跃转录请求数及最后一次请求完成时间。只在活跃请求数为零且空闲达到 300 秒后请求 Uvicorn 正常退出。
6. 新转录请求会刷新活动时间；长时间运行的转录不会被空闲监视器中断。
7. 服务退出后遗留的 PID 文件由现有启动、停止和状态逻辑安全识别及清理；下一个任务可重新拉起服务。

## 组件边界

### KenRadar 转录器

负责判断当前 endpoint 是否需要本地托管、确保本地服务在请求前可用，并维持现有失败分类和 fallback 行为。它不直接加载 FunASR 模型。

### FunASR 启动脚本

继续负责选择项目 Python 环境、设置服务环境变量、写入 PID/日志并等待健康检查。脚本保持幂等。

### FunASR HTTP 服务

继续延迟或预加载模型并处理 OpenAI-compatible 请求，同时新增线程安全的请求活动跟踪和空闲退出监视器。HTTP 健康检查和模型列表查询不算转录活动，不延长 GPU 模型生命周期。

## 并发与故障处理

- 跨进程文件锁覆盖“健康检查—启动—等待就绪”临界区，兼容 Web worker、调度进程和手动任务同时触发。
- 锁内进行二次健康检查，避免等待锁期间服务已经由另一进程启动后再次启动。
- 服务启动失败、超时、端口冲突或请求失败时，沿用现有 `funasr_unavailable` 等失败分类并进入 Whisper fallback。
- 空闲监视器异常不得中断正在执行的请求；退出条件必须同时满足“活跃请求为零”和“超过空闲阈值”。
- `managed: false` 时不触碰本地进程，适用于外部 FunASR 服务。

## 运维行为

- `./ctl.sh status` 不以 FunASR 未运行为错误，因为空闲状态下停止是预期行为。
- `./ctl.sh status-funasr` 仍明确显示当前是否运行。
- `./ctl.sh start-funasr` 可手动预热服务；默认仍在空闲超时后退出。
- 提供环境变量覆盖空闲时间，并允许在故障诊断期间关闭空闲退出。
- 帮助文本和 README 更新为“按需启动”，移除“KenRadar 启动前自动启动”的默认描述。

## 测试与验收

采用测试驱动实现，至少覆盖：

1. `./ctl.sh start` 路径不再自动启动 FunASR。
2. 托管模式下，endpoint 不健康时首次转录会启动服务。
3. endpoint 已健康时不会重复启动。
4. 并发调用通过锁只触发一次启动。
5. 活跃转录期间空闲监视器不退出。
6. 最后一个请求完成并空闲 300 秒后请求服务退出。
7. 新请求会重置空闲计时。
8. `managed: false` 不执行本地启动。
9. 启动失败或超时仍进入现有 Whisper fallback。

完成 focused tests 后运行 `python -m compileall kenradar scripts`，并在可用环境中验证：KenRadar 重启后 GPU 无 FunASR 常驻占用；触发一次真实转录时模型加载；完成后等待 5 分钟，FunASR 进程退出且显存释放。

## 非目标

- 不改为 CPU FunASR。
- 不管理或重构 Docker Ollama。
- 不改变 Whisper 的设备和计算类型。
- 不引入新的守护进程、任务编排系统或数据库 schema。
- 不中断当前正在执行的转录任务来强制释放显存。
