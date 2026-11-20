# Pages E 版阅读界面

本次只改公开静态站点。`static_site.py` 保持路径与 Markdown 转换契约，`public_site.py` 负责首页、来源目录、博主页、文章外壳和公开内容索引。共享资源在 `publishing/assets/`，打包安装时随包携带。

- 首页展示公开内容流、来源和主题统计；来源页使用真实公开条目计数。
- 文章保留章节、来源链接和默认折叠的 ASR；目录、移动导航、深浅色与专注阅读均不依赖本地后台。
- 搜索使用 `content-index.json` 的标题、来源、主题和短摘要，不是 Pagefind 正文搜索。搜索界面支持 Ctrl/Cmd+K 和 Esc。列表支持主题/平台过滤、排序及分批展示。
- ID 保持字符串，按平台与内容 ID 去重；历史缺少 Markdown 的页面保留标题与入口，不推测发布日期和主题。
- 原 Markdown 不存在时，只替换已有公开 HTML 的阅读外壳。不会下载、转录、调用 AI 或新增未公开文章。
- 历史索引链接继续保留。私有路径、Markdown 标记及数据库策略继续生效；静态构建只读复用本次数据库策略快照，外发同步照常检查当前策略。

已有站点升级命令（会写 HTML，须使用选定配置）：

```powershell
.\.venv\python.exe -m kenradar --config <隔离配置> publish-pages --refresh-layout --no-sync
```

新版共享文件是 `assets/site.css`、`assets/site.js`、`sources.html`、`content-index.json`。有限发布白名单需明确允许这些路径。单次全站外观升级使用本次实际变化 HTML 的精确白名单，不扩大长期文章发布范围。保留既有 Git 同步、敏感检查和历史链接检查。

Pagefind 正文索引、独立专题页面及真实部署环境的 Lighthouse 指标尚未交付；不能以元数据检索代替正文检索验收。
