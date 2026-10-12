# Hermes 调用 AI 整理故障修复

2026-10-12，受影响视频 `7694252203724262682`（肖星：上市公司如何估值？）。原始转录成功，任务 12 在 Agnes TLS 握手阶段失败。

实测系统 DNS 返回 `198.18.0.37`，Python 和 Windows curl 均无法完成该路径的 TLS 握手；公共 DNS 返回 `104.18.19.62` / `104.18.18.62`。使用真实地址、原 Host、原 SNI 和标准 CA/主机名校验后，未认证请求正常返回 401。

新增 KenRadar 内部 HTTPS 地址路由适配器。仅本地配置 `ai.organizer.connect_hostname: apihub.agnes-ai.com` 与 `connect_address: 104.18.19.62` 生效，不修改系统 DNS、代理、hosts 或 Hermes 环境。这个 IP 是本次诊断的地址；网络恢复正常时可删除两个配置项恢复系统解析，地址变化时须重新查询和核验，不能将其当永久 DNS。

恢复任务 13、14 连接成功，但模型输出 JSON 校验失败；任务 15 完成真实 AI 整理。笔记存在、原始转录保留、一句话结论存在。旧任务 12、13、14 标记已解决，保留失败状态、错误和审计，不伪造旧尝试成功。

针对模型无效 JSON，新增一次受限 provider 重试，复用原限流与完整性校验；再失败仍生成明确降级结果。相关回归 112 项通过，新增 JSON 重试测试单独通过。Web 与 worker 已恢复。修复中未公开发布或发送飞书。

备份位于 `data/test-migration/hermes-ai-repair/`，数据库 `before.sqlite3` 和笔记 `note-before.md`。恢复备份前必须停止 Web 与 worker，恢复会撤销备份之后的本地结果。
