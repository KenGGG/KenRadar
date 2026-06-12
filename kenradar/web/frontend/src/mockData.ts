/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { VideoContent, ResearchTask, MonitorSource, PushRecord, SystemLog, SystemConfig } from './types';

export const INITIAL_VIDEOS: VideoContent[] = [
  {
    id: "7324564890123001",
    title: "AGI时代个人开发者如何利用AI Agent一个人做出百万营收的产品？",
    blogger: "AI 创投派 - 峰哥",
    rating: 8.8,
    recommend_action: "push",
    status: "completed",
    created_at: "2026-05-20 10:30",
    duration: "4:15",
    original_url: "https://v.douyin.com/iR7Mh3Y1/",
    tags: ["AI Agent", "独立开发", "商业化", "生产力"],
    whisper_text: "大家伙，我是峰哥。今天跟大伙聊聊在当下这个大模型满街跑的时代，独立开发者到底怎么利用 AI Agent 一个人把百万营收的产品给做出来。以前你要雇前端、后端、设计师，还要搞运营。现在呢？我手头就有三个项目实例，完全是用 Ollama 跑本地模型，配合 Cursor 和 v0 生成，一个月就实现了几万美刀的流水。第一个窍门是把工具垂直化，比如做跨境电商图文生成的、做特定格式 PDF 解析智能表单的。不要指望做一个万能的助理，万能的助理往往最难卖。我们要解决特定岗位痛点。配合 Whisper 轻量模型在本地把竞品短视频里的核心解法提炼成流程，然后再通过大模型直接生成代码...",
    summary_markdown: `---
title: AGI时代个人开发者如何利用AI Agent一个人做出百万营收的产品？
blogger: AI 创投派 - 峰哥
rating: 8.8
recommend_action: push
aweme_id: "7324564890123001"
duration: "4:15"
date_fetched: "2026-05-20"
---

# 📖 AGI时代个人开发者如何利用AI Agent做出百万营收产品

## 🎯 核心结论与卖点
在这个AI高度繁荣的时代，**独立开发者（Solo-Developer）的能力被放大了100倍**。通过垂直工具化AI Agent，无需组建昂贵团队即可验证极高商业价值的产品。

## 💡 核心要点
1. **超级个体崛起**：借助Cursor、v0以及本地Ollama微调模型，一人包揽“设计、前后端、本地测试与落地页推广”。
2. **拒绝大而全，主攻小而美**：万能助理无法突围。极度专注跨境电商特定图文生成、针对性PDF解析等垂直B端痛点最易变现。
3. **流程逆向工程**：通过Whisper转录竞争对手在抖音、海外TikTok等视频，快速拆解商业模式与痛点，转化为程序代码指令。

## 🛠️ 行动建议与执行路径
- **第一步**：使用本地 **Docker Ollama (GLM-4.7 Flash)** 跑产品定位和Prompt原型。
- **第二步**：选定具体变现领域（如：小红书文案配图助手、Shopify极速建站智能组件）。
- **第三步**：将飞书推送和通知接通，确保一旦用户付费或流失能实时拿到推送通知，并在KenRadar等雷达中随时复盘。`
  },
  {
    id: "7324564890123002",
    title: "深度拆解：为什么硅谷硬件初创公司的AI硬件都在翻车？",
    blogger: "Ken 哥科技",
    rating: 9.3,
    recommend_action: "push",
    status: "completed",
    created_at: "2026-05-20 09:15",
    duration: "8:50",
    original_url: "https://v.douyin.com/iR7Mh3Y2/",
    tags: ["硅谷科技", "AI硬件", "可穿戴设备", "项目复盘"],
    whisper_text: "硬件太难搞了，兄弟们。不管是 Rabbit R1 还是 Humane AI Pin，最近几个月硅谷最火的硬件简直成了退货重灾区。为什么在 ChatGPT 里体验无敌的 AI，一塞进硬件盒子里就各种完蛋？今天 Ken 哥就给你们深度拆解。首先是致命的延迟问题。说一个成语，在本地手机或者电脑里只要一两百毫秒，但你按住 AI PIN 吼一嗓子，数据要通过 4G 传回云端，云端调用大模型，大模型再调第三方 API，再转写成语音，好家伙，五秒钟过去了，这谁能忍得住？第二点是电池性能和过热。微型机身里塞高频处理器和 LTE 基带，电池大不了。使用不到半小时，设备烫得像暖手宝，还要强制降频。最后也是最核心的——它没有解决用户的硬需求。你问它温度、天气、翻译，手表和手机已经做得很完美了，为了所谓的无屏幕体验付出几百刀，纯粹是消费级电子伪命题...",
    summary_markdown: `---
title: 深度拆解：为什么硅谷硬件初创公司的AI硬件都在翻车？
blogger: Ken 哥科技
rating: 9.3
recommend_action: push
aweme_id: "7324564890123002"
duration: "8:50"
date_fetched: "2026-05-20"
---

# 🚨 深度拆解：为什么硅谷硬件初创公司的AI硬件都在翻车？

## 💎 内容评分与分发动作
*   **雷达评级**：**9.3/10 (高优推荐)**
*   **推荐动作**：**直接推送飞书 (Push)**
*   **核心关键词**：AI 硬件、产品定义、Humane AI Pin、延迟困境、热设计

## 🧩 为什么AI硬件沦为翻车灾区？
硬件开发的复杂度、制造周期与AI软件光速迭代发生了致命冲突：

1.  **网络与时延诅咒 (Latency Curse)**
    *   交互流程：\`麦克风输入 -> 4G网络 -> 云端转写 -> 大模型响应 -> 第三方API -> TTS合成 -> 播音\`。
    *   实测耗时：**4.5s - 7.0s**。在日常生活中，3秒以上的延迟意味着交互死亡。
2.  **热设计能耗限制 (Thermal & Battery Bottleneck)**
    *   精致的小型可穿戴外壳内无法布置大容量电池；
    *   持续使用4G/Wi-Fi联网与多模态流接收，导致芯片极易触及发热阈值，主频瞬间下降，速度雪上加霜。
3.  **价值主张伪命题 (Pseudo Value Proposition)**
    *   没有屏幕的“轻量化”理念成了牢笼。
    *   用户为了做手机、手表已经能高效完成的事（诸如问天气、做翻译、设闹钟），额外掏出了巨额硬件费用与月租。

## 💡 核心启示：如何重构硬件设计？
- **边缘侧计算才是解法**：转录（如本地 Whisper.cpp 构建）和核心基础逻辑控制务必完全本地闭环运行，避免网络握手开销。
- **屏幕不可妥协**：不应为无屏而无屏。智能辅助硬件应该以“视场增亮/HUD”等方式辅助认知，而非强行退回纯语音交互。`
  },
  {
    id: "7324564890123003",
    title: "10分钟带你零基础本地部署 Whisper 全功能高精度转录方案",
    blogger: "开源极客指南",
    rating: 7.2,
    recommend_action: "review",
    status: "completed",
    created_at: "2026-05-19 18:20",
    duration: "10:12",
    original_url: "https://v.douyin.com/iR7Mh3Y3/",
    tags: ["开源工具", "Whisper", "本地部署", "视频教程"],
    whisper_text: "很多小伙伴都在问我的视频字幕是怎么批量做的，其实我完全没在剪映或者云端花过一分钱，全靠本地开源的 OpenAI Whisper 方案。今天我手把手教你们部署，哪怕你电脑没 GPU 显卡也能飞速运行。我们要用的是 Whisper.cpp 项目，这把 C++ 重写的框架优化到了极致，能在 Mac M系列芯片上跑满硬件加速，Windows 的 CPU 甚至也能跑出很理想的成绩。第一步，下载编译好的二进制，把 base 模型或者 small 模型下下来。如果你有 4G 以上显存，可以考虑直接用 medium 模型。然后，如果你写 Python 代码呢，可以直接调 Faster-Whisper，它加入了 CTranslate2 的量化加速技术，速度比官方原版快 4 到 5 倍。第三步，怎么跟你的剪辑工作流结合...",
    summary_markdown: `---
title: 10分钟带你零基础本地部署 Whisper 全功能高精度转录方案
blogger: 开源极客指南
rating: 7.2
recommend_action: review
aweme_id: "7324564890123003"
duration: "10:12"
date_fetched: "2026-05-19"
---

# 🔧 10分钟带你配置 Whisper 本地高精度转录工作流

## 💡 提要
对于做内容抓取、分析或者笔记生成的团队，高额的语音转录API账单是不可承受之重。**本地部署Whisper** 能够做到完全免费、无数据外泄风险并且通过软硬件联动跑出恐怖的速度。

## ⚙️ 核心解法
- **M系列 Mac 平台**：优先使用 \`whisper.cpp\` 用 CoreML 硬件引擎加速。
- **Windows/Linux (带英伟达显卡)**：强烈建议使用 \`faster-whisper\`。它基于 CTranslate2 构建，加入了 FP16 等混精度量化，较原版 OpenAI 运行速度提升了 **400%**。
- **资源占用情况**：
  - **Medium 模型 (常用)**：需要约 5GB 显存，对中英文混合及多博主方言口癖拥有极佳包容度。
  - **Large-v3 模型 (精细转录)**：需 8-10GB 显存，词错率 (WER) 逼近人类极限。

## 💡 实践指引
1. 项目如果集成于 Linux Docker 中，使用 staging-GPU 逻辑排队，转播结束后自动离线 GPU 释放 VRAM，防止与 Ollama (LLM推理) 撞显存，造成崩盘。
2. 捕获到的高品质长文保存为 Markdown 用于 Obsidian 本地聚合，作为未来 AI 辅助简报和洞察周报的底座原料。`
  },
  {
    id: "7324564890123004",
    title: "高德地图VS百度地图，自动驾驶红利期到底谁才是城市领航一哥？",
    blogger: "科技圈观察",
    rating: 6.4,
    recommend_action: "skip",
    status: "completed",
    created_at: "2026-05-19 14:05",
    duration: "6:30",
    original_url: "https://v.douyin.com/iR7Mh3Y4/",
    tags: ["行业观察", "自动驾驶", "地图", "车联网"],
    whisper_text: "这一期我们聊聊高德和百度在城市智能领航NOA上的竞争。现在的无图方案越来越成熟，那么地图商是不是要失业了呢？其实根本不会。虽然大家现在都不讲高精地图了，但超视距的车路协同、路网先验信息还是必须靠地图商提供。高德依托阿里庞大的车主生态和实时路况，而百度则深度绑定阿波罗自动驾驶平台，从硬核算法端突围。其实车企在选择两者的时候也很有讲究...",
    summary_markdown: `---
title: 高德地图VS百度地图，自动驾驶红利期到底谁才是城市领航一哥？
blogger: 科技圈观察
rating: 6.4
recommend_action: skip
aweme_id: "7324564890123004"
duration: "6:30"
date_fetched: "2026-05-19"
---

# 🗺️ 高德VS百度：NOA时代图商的真正生态位

## 🗒️ 评级结论
*   **评分**：6.4
*   **推荐动作**：忽略 (Skip) — 偏向一般行业公关科普，不具备深层方法论与硬核商业情报。`
  },
  {
    id: "7324564890123005",
    title: "AI 生成视频的新一轮革命：Sora 对影视工业的实质性冲击究竟多大？",
    blogger: "数字导演俱乐部",
    rating: 4.5,
    recommend_action: "review",
    status: "failed",
    failed_at_step: "transcribe",
    error_message: "CUDA out of memory in Whisper base process while running batch audio slice. Target VRAM exceeded 102%.",
    created_at: "2026-05-18 20:01",
    duration: "12:45",
    original_url: "https://v.douyin.com/iR7Mh3Y5/",
    tags: ["AI影视", "Sora", "技术痛点", "算力极限"],
    whisper_text: "",
    summary_markdown: ""
  },
  {
    id: "7324564890123006",
    title: "为什么在 2026 年，我们需要抛弃 80% 的 SaaS 产品切换到自托管？",
    blogger: "极客自留地",
    rating: 8.5,
    recommend_action: "push",
    status: "failed",
    failed_at_step: "ai",
    error_message: "Ollama host 'http://127.0.0.1:11434' refused connection. Timeout (60s) reached while querying glm-4.7-flash:q4_K_M.",
    created_at: "2026-05-18 10:14",
    duration: "5:20",
    original_url: "https://v.douyin.com/iR7Mh3Y6/",
    tags: ["自托管", "Self-Hosted", "SaaS退潮", "开源替代"],
    whisper_text: "今天给大家总结一下为什么2026年很多中小企业和开发者正在毅然离场SaaS产品，全方位迁入自托管（Self-Hosted）开源替代。第一个理由是：月租噩梦。几乎所有开发协同、数据流、监控、密码管理器，都在以按头订阅的方式贪婪收费。第二个理由是隐私：你的数据在别人的云上并不是你的。利用Docker部署Appwrite、Supabase、Uptime-Kuma、KenRadar这类开源控制台，配合闲置服务器或者旧电脑，几乎可以实现0成本的高维运作...",
    summary_markdown: ""
  }
];

export const INITIAL_TASKS: ResearchTask[] = [
  {
    id: "task_1001",
    type: "single",
    target: "https://v.douyin.com/iRExplD/",
    status: "completed",
    total_items: 1,
    completed_items: 1,
    failed_items: 0,
    skipped_items: 0,
    created_at: "2026-05-20 09:00",
    pipeline_stage: "completed",
    pipeline_progress: 100
  },
  {
    id: "task_1002",
    type: "blogger",
    target: "AI创投派 - 历史列表前50",
    status: "processing",
    total_items: 20,
    completed_items: 12,
    failed_items: 1,
    skipped_items: 2,
    created_at: "2026-05-20 11:15",
    pipeline_stage: "summarizing",
    pipeline_progress: 68
  },
  {
    id: "task_1003",
    type: "blogger",
    target: "科技圈观察 - 补全过去一周记录",
    status: "failed",
    total_items: 10,
    completed_items: 4,
    failed_items: 3,
    skipped_items: 3,
    created_at: "2026-05-18 15:40",
    pipeline_stage: "failed",
    pipeline_progress: 40
  }
];

export const INITIAL_SOURCES: MonitorSource[] = [
  {
    id: "src_001",
    name: "AI 创投派 - 峰哥",
    url: "https://www.douyin.com/user/MS4wLjABAAAAAI_創投派_example",
    category: "AI",
    status: "enabled",
    quality_score: 95,
    last_checked: "2026-05-20 11:00",
    total_captured: 42,
    parse_success_rate: 100
  },
  {
    id: "src_002",
    name: "Ken 哥科技(智能硬件观察)",
    url: "https://www.douyin.com/user/MS4wLjABAAAAKen_Tech_Gizmo_example",
    category: "科技",
    status: "enabled",
    quality_score: 98,
    last_checked: "2026-05-20 10:45",
    total_captured: 128,
    parse_success_rate: 99.2
  },
  {
    id: "src_003",
    name: "开源极客指南",
    url: "https://www.douyin.com/user/Awesome_OpenSource_Geek_example",
    category: "科技",
    status: "enabled",
    quality_score: 85,
    last_checked: "2026-05-20 08:30",
    total_captured: 88,
    parse_success_rate: 96.5
  },
  {
    id: "src_004",
    name: "科技圈观察 (NOA与汽车情报)",
    url: "https://www.douyin.com/user/MS4wLjABAAAA_Tech_Cars_review",
    category: "汽车",
    status: "disabled",
    quality_score: 60,
    last_checked: "2026-05-19 12:00",
    total_captured: 14,
    parse_success_rate: 82.1
  }
];

export const INITIAL_PUSH_RECORDS: PushRecord[] = [
  {
    id: "push_901",
    aweme_id: "7324564890123002",
    title: "深度拆解：为什么硅谷硬件初创公司的AI硬件都在翻车？",
    blogger: "Ken 哥科技",
    push_type: "card",
    sent_at: "2026-05-20 09:16",
    status: "success",
    payload: JSON.stringify({
      config: {
        type: "card",
        card_id: "kenradar_recommend_v1",
        theme: "turquoise",
      },
      header: {
        title: "🚨 硅谷AI硬件翻车深度拆解 - KenRadar 雷达重点推荐",
        subtitle: "博主：Ken 哥科技 | 评级得分：9.3分 (极高价值)"
      },
      body: {
        paragraphs: [
          "1. 4G及API云端调用导致的 4.5s - 7.0s 时延诅咒，秒杀一切无屏轻量化交互体验。",
          "2. 微型机身发热与续航瓶颈，高频LTE+模态流交互致使主控频繁退避限频。",
          "3. 伪需求包围，未在手机与手表外创造革命性的边缘独立计算场景。"
        ],
        action_button: {
          label: "查看 Obsidian 全量笔记",
          url: "https://radar.ken.internal/aweme?id=7324564890123002"
        }
      }
    }, null, 2)
  },
  {
    id: "push_902",
    aweme_id: "7324564890123001",
    title: "AGI时代个人开发者如何利用AI Agent一个人做出百万营收的产品？",
    blogger: "AI 创投派 - 峰哥",
    push_type: "card",
    sent_at: "2026-05-20 10:31",
    status: "success",
    payload: JSON.stringify({
      config: {
        type: "card",
        card_id: "kenradar_recommend_v1",
        theme: "violet"
      },
      header: {
        title: "📚 AGI超级个体做独立百万营收产品方法论",
        subtitle: "博主：AI 创投派 - 峰哥 | 评级得分：8.8分 (高价值推动)"
      },
      body: {
        paragraphs: [
          "1. 个人开发者借助本地Ollama驱动 + Cursor + v0可放大常规产研效率百倍。",
          "2. 别做万能助手。应针对跨境电商图文或PDF结构提取等极窄B端刚需实现单兵击破。",
          "3. 采用逆向工程。转录竞品推广内容挖掘细分刚需以编写核心业务指令。"
        ]
      }
    }, null, 2)
  }
];

export const INITIAL_LOGS: SystemLog[] = [
  {
    id: "log_1",
    timestamp: "2026-05-20 11:30:15",
    level: "info",
    module: "Scheduler",
    message: "定时轮询加载启动。检测到 3 个启用中的监控来源：[src_001, src_002, src_003]."
  },
  {
    id: "log_2",
    timestamp: "2026-05-20 11:30:17",
    level: "info",
    module: "Downloader",
    message: "开始解析来源 ID [src_001] (AI 创投派 - 峰哥)。检测到新作品: 暂无新更新。"
  },
  {
    id: "log_3",
    timestamp: "2026-05-20 11:28:40",
    level: "info",
    module: "Ollama",
    message: "Ollama 成功解析 aweme [7324564890123001] 的 Whisper 转写片段。使用模型 glm-4.7-flash:q4_K_M，输入 1,280 tokens，用时 12.4s。已完成本地 Obsidian Obsidian 格式笔记生成。"
  },
  {
    id: "log_4",
    timestamp: "2026-05-20 11:28:41",
    level: "info",
    module: "Feishu",
    message: "开始尝试发送飞书推送。卡片参数：评分 8.8, 动作为 push。"
  },
  {
    id: "log_5",
    timestamp: "2026-05-20 11:28:42",
    level: "info",
    module: "Feishu",
    message: "飞书通知发送成功。响应：{'code': 0, 'msg': 'success'}, 耗时 120ms."
  },
  {
    id: "log_6",
    timestamp: "2026-05-20 11:20:02",
    level: "info",
    module: "Whisper",
    message: "本地英伟达 CUDA 显卡已被挂载。挂载并加速 [model: base]，成功转录 4.25分钟 音频。用时 18.5s。"
  },
  {
    id: "log_7",
    timestamp: "2026-05-20 10:14:00",
    level: "error",
    module: "Ollama",
    message: "连接 Ollama 实例受阻。Host 'http://127.0.0.1:11434' 拒绝连接错误。将在一分钟后重试。详情：Socket timed out."
  },
  {
    id: "log_8",
    timestamp: "2026-05-20 09:05:44",
    level: "warn",
    module: "Scheduler",
    message: "检测到 1 个转录任务由于显存争抢挂起，已延迟并加入等待池，等待批量 Staged GPU 排班释放。"
  }
];

export const DEFAULT_CONFIG: SystemConfig = {
  scheduler: {
    enabled: true,
    cronExpression: "10:00, 21:00",
    grace_period_mins: 5,
    max_concurrent_tasks: 0,
    retry_times: 2,
    max_items_per_blogger: 0,
    manual_trigger_enabled: true
  },
  whisper: {
    model: "large-v3-turbo",
    device: "cpu",
    threads: 6,
    use_gpu: true,
    vram_offload_gb: 4,
    staged_gpu_scheduling: true
  },
  ai: {
    api_type: "ollama",
    endpoint: "http://127.0.0.1:11434/v1",
    model: "glm-4.7-flash:q4_K_M",
    temperature: 0.2,
    top_p: 0.9,
    top_k: 40,
    timeout_sec: 120,
    max_tokens: 8192,
    max_input_chars: 12000,
    keep_alive: "10m",
    no_think: true,
    compact_prompt: true,
    fallback_model: "",
    prompt_template: `你是一个短视频内容深度剖析专家。
请仔细分析提供的 Whisper 转写原稿，提炼内容核心并编写一份优雅的 Obsidian 规范笔记。
要求：
- 输出规范的 YAML Markdown frontmatter（包括 title, blogger, rating(1-10), recommend_action, aweme_id, duration, date_fetched）。
- 用 # Markdown 标题做主标题
- 提炼核心结论与卖点。
- 梳理多条核心概念机制。
- 给出给力的商业或者研究实操建议路径。`
  },
  download: {
    path: "data/Downloaded",
    max_workers: 1,
    batch_size: 5,
    batch_cooldown_seconds: 5,
    max_duration_seconds: 900,
    retry_failed: true,
    circuit_breaker_failures: 5,
    circuit_breaker_cooldown_seconds: 300,
    save_json: true
  },
  feishu: {
    webhook_url: "",
    message_type: "auto",
    push_threshold_rating: 7.5,
    retry_attempts: 3,
    card_max_items: 5,
    card_theme: "turquoise"
  },
  security: {
    port: 8765,
    bind_ip: "0.0.0.0",
    password_auth: true,
    web_password: "",
    access_token_ttl_hours: 24
  },
  publishing: {
    github_pages_enabled: true,
    github_pages_output_dir: "./docs",
    github_pages_public_base_url: "${KENRADAR_GITHUB_PAGES_URL}",
    github_pages_public_base_url_configured: false,
    github_sync_enabled: false,
    github_sync_repo_dir: ".",
    github_sync_branch: "main",
    github_sync_auto_commit: false,
    github_sync_auto_push: false,
    github_sync_include_html_docs: true,
    github_sync_include_markdown_notes: true,
    github_sync_include_briefs: true,
    github_sync_include_transcripts: true
  }
};
