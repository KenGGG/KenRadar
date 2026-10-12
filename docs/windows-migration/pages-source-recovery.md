# Pages 来源恢复结果（2026-10-10）

来源仓库：https://github.com/KenGGG/KenRadar-pages ，分支 gh-pages，提交 83b576dcdffa8e5dc1e103c41978c69b6a4ac52c。

实际扫描 3738 篇内容 HTML，55 个来源目录（抖音 52、播客 3），提取 3711 个不同抖音作品 ID。没有找到可靠抖音 sec_uid 或播客主页，因此当前可直接恢复的订阅身份为 0；未把名称当作稳定标识，也未伪造订阅。目录中的待定、单视频来源需要按作品作者拆分；深圳温姑娘等改名目录需要在身份相同后合并。

导入步骤：先按每个目录选取一至数个源视频，用现有 resolve_douyin_video 在具备登录条件时获取作者 sec_uid 和昵称；多视频返回不同作者时拆分，多个名称返回相同 sec_uid 时合并。播客须人工补主页或 RSS。保留证据链接、文件 SHA 和作者验证结果，复核后以关闭状态写入 V2 source_subscription，再单独授权启用监控。来源配置若需要兼容旧 bloggers，也必须按稳定身份同步，不能只新增目录名。

恢复的是历史发布来源候选，不能还原当时的启用、轮询频率、失败状态、任务、秘密或完整数据库。JSON 清单：data/test-migration/pages-recovery/inventory/sources.json。脚本 scripts/recover_pages_sources.py，导入契约测试 1 passed，覆盖身份歧义、关闭状态、重复导入和已有设置保留；真实页面清单无可验证身份，因此没有实际写入订阅。

回滚仅撤销本轮新增脚本、测试、报告及独立恢复目录，不清空原数据，不改生产配置。

# GitHub Pages 来源恢复清单

这是历史发布证据；启用状态未知。未导入生产或开启监控。

| 平台 | 名称 | HTML 篇数 | 来源身份 |
| --- | --- | ---: | --- |
| douyin | [B_A](https://kenggg.github.io/KenRadar-pages/notes/douyin/B_A/index.html) | 12 | identity_required |
| douyin | [Jaybee黄](https://kenggg.github.io/KenRadar-pages/notes/douyin/Jaybee黄/index.html) | 40 | identity_required |
| douyin | [PAKEN财经说](https://kenggg.github.io/KenRadar-pages/notes/douyin/PAKEN财经说/index.html) | 53 | identity_required |
| douyin | [Panda_AI_量变学院](https://kenggg.github.io/KenRadar-pages/notes/douyin/Panda_AI_量变学院/index.html) | 74 | identity_required |
| douyin | [Simon林](https://kenggg.github.io/KenRadar-pages/notes/douyin/Simon林/index.html) | 127 | identity_required |
| douyin | [YY中文頻道](https://kenggg.github.io/KenRadar-pages/notes/douyin/YY中文頻道/index.html) | 1 | identity_required |
| douyin | [一切皆法](https://kenggg.github.io/KenRadar-pages/notes/douyin/一切皆法/index.html) | 52 | identity_required |
| douyin | [中产财富说](https://kenggg.github.io/KenRadar-pages/notes/douyin/中产财富说/index.html) | 265 | identity_required |
| douyin | [书九爷](https://kenggg.github.io/KenRadar-pages/notes/douyin/书九爷/index.html) | 1 | identity_required |
| douyin | [二钳深度研报](https://kenggg.github.io/KenRadar-pages/notes/douyin/二钳深度研报/index.html) | 91 | identity_required |
| douyin | [优优yoyo](https://kenggg.github.io/KenRadar-pages/notes/douyin/优优yoyo/index.html) | 24 | identity_required |
| douyin | [做量化的西蒙](https://kenggg.github.io/KenRadar-pages/notes/douyin/做量化的西蒙/index.html) | 30 | identity_required |
| douyin | [元姐的亲子财商日常](https://kenggg.github.io/KenRadar-pages/notes/douyin/元姐的亲子财商日常/index.html) | 57 | identity_required |
| douyin | [兜妈家的娃](https://kenggg.github.io/KenRadar-pages/notes/douyin/兜妈家的娃/index.html) | 52 | identity_required |
| douyin | [刘璐的投资笔记](https://kenggg.github.io/KenRadar-pages/notes/douyin/刘璐的投资笔记/index.html) | 98 | identity_required |
| douyin | [努力进化的派](https://kenggg.github.io/KenRadar-pages/notes/douyin/努力进化的派/index.html) | 54 | identity_required |
| douyin | [北大泽爸深耕自驱力](https://kenggg.github.io/KenRadar-pages/notes/douyin/北大泽爸深耕自驱力/index.html) | 1 | identity_required |
| douyin | [卓叔增重](https://kenggg.github.io/KenRadar-pages/notes/douyin/卓叔增重/index.html) | 301 | identity_required |
| douyin | [单视频来源](https://kenggg.github.io/KenRadar-pages/notes/douyin/单视频来源/index.html) | 47 | identity_required |
| douyin | [复利变量.47🤖](https://kenggg.github.io/KenRadar-pages/notes/douyin/复利变量.47🤖/index.html) | 1 | identity_required |
| douyin | [大物是也](https://kenggg.github.io/KenRadar-pages/notes/douyin/大物是也/index.html) | 50 | identity_required |
| douyin | [小mo今天不面试](https://kenggg.github.io/KenRadar-pages/notes/douyin/小mo今天不面试/index.html) | 1 | identity_required |
| douyin | [小木之之](https://kenggg.github.io/KenRadar-pages/notes/douyin/小木之之/index.html) | 2 | identity_required |
| douyin | [峨眉峰还独照](https://kenggg.github.io/KenRadar-pages/notes/douyin/峨眉峰还独照/index.html) | 72 | identity_required |
| douyin | [当个事儿](https://kenggg.github.io/KenRadar-pages/notes/douyin/当个事儿/index.html) | 5 | identity_required |
| douyin | [待定](https://kenggg.github.io/KenRadar-pages/notes/douyin/待定/index.html) | 53 | identity_required |
| douyin | [扶摇乘风](https://kenggg.github.io/KenRadar-pages/notes/douyin/扶摇乘风/index.html) | 1 | identity_required |
| douyin | [抖音法律](https://kenggg.github.io/KenRadar-pages/notes/douyin/抖音法律/index.html) | 1 | identity_required |
| douyin | [易老师谈育儿（牛娃版）](https://kenggg.github.io/KenRadar-pages/notes/douyin/易老师谈育儿（牛娃版）/index.html) | 36 | identity_required |
| douyin | [易老师（8.18晚9点外教专场）](https://kenggg.github.io/KenRadar-pages/notes/douyin/易老师（8.18晚9点外教专场）/index.html) | 1 | identity_required |
| douyin | [晓玉说](https://kenggg.github.io/KenRadar-pages/notes/douyin/晓玉说/index.html) | 272 | identity_required |
| douyin | [晖哥说投资](https://kenggg.github.io/KenRadar-pages/notes/douyin/晖哥说投资/index.html) | 99 | identity_required |
| douyin | [机构一手调研（福总）](https://kenggg.github.io/KenRadar-pages/notes/douyin/机构一手调研（福总）/index.html) | 146 | identity_required |
| douyin | [机油手](https://kenggg.github.io/KenRadar-pages/notes/douyin/机油手/index.html) | 45 | identity_required |
| douyin | [李奇奇读书号](https://kenggg.github.io/KenRadar-pages/notes/douyin/李奇奇读书号/index.html) | 116 | identity_required |
| douyin | [杜雨商业洞察](https://kenggg.github.io/KenRadar-pages/notes/douyin/杜雨商业洞察/index.html) | 1 | identity_required |
| douyin | [杨竹筠](https://kenggg.github.io/KenRadar-pages/notes/douyin/杨竹筠/index.html) | 348 | identity_required |
| douyin | [沪上故事123](https://kenggg.github.io/KenRadar-pages/notes/douyin/沪上故事123/index.html) | 1 | identity_required |
| douyin | [深圳温姑娘](https://kenggg.github.io/KenRadar-pages/notes/douyin/深圳温姑娘/index.html) | 27 | identity_required |
| douyin | [深圳温姑娘（博士在读版）](https://kenggg.github.io/KenRadar-pages/notes/douyin/深圳温姑娘（博士在读版）/index.html) | 26 | identity_required |
| douyin | [温温的数学](https://kenggg.github.io/KenRadar-pages/notes/douyin/温温的数学/index.html) | 1 | identity_required |
| douyin | [牵牛哥_牵牛读书会](https://kenggg.github.io/KenRadar-pages/notes/douyin/牵牛哥_牵牛读书会/index.html) | 1 | identity_required |
| douyin | [琰总研究圈](https://kenggg.github.io/KenRadar-pages/notes/douyin/琰总研究圈/index.html) | 218 | identity_required |
| douyin | [百通讲解](https://kenggg.github.io/KenRadar-pages/notes/douyin/百通讲解/index.html) | 528 | identity_required |
| douyin | [茄语金融常识Commonsense](https://kenggg.github.io/KenRadar-pages/notes/douyin/茄语金融常识Commonsense/index.html) | 104 | identity_required |
| douyin | [这个月](https://kenggg.github.io/KenRadar-pages/notes/douyin/这个月/index.html) | 1 | identity_required |
| douyin | [这很容易](https://kenggg.github.io/KenRadar-pages/notes/douyin/这很容易/index.html) | 18 | identity_required |
| douyin | [追野](https://kenggg.github.io/KenRadar-pages/notes/douyin/追野/index.html) | 11 | identity_required |
| douyin | [郑茜茜（xi）](https://kenggg.github.io/KenRadar-pages/notes/douyin/郑茜茜（xi）/index.html) | 39 | identity_required |
| douyin | [量化Quantgirl](https://kenggg.github.io/KenRadar-pages/notes/douyin/量化Quantgirl/index.html) | 115 | identity_required |
| douyin | [量化李不白](https://kenggg.github.io/KenRadar-pages/notes/douyin/量化李不白/index.html) | 10 | identity_required |
| douyin | [顾学长](https://kenggg.github.io/KenRadar-pages/notes/douyin/顾学长/index.html) | 1 | identity_required |
| podcast | [YY中文頻道](https://kenggg.github.io/KenRadar-pages/notes/podcast/YY中文頻道/index.html) | 1 | identity_required |
| podcast | [当个事儿](https://kenggg.github.io/KenRadar-pages/notes/podcast/当个事儿/index.html) | 4 | identity_required |
| podcast | [跨国串门儿计划](https://kenggg.github.io/KenRadar-pages/notes/podcast/跨国串门儿计划/index.html) | 2 | identity_required |
