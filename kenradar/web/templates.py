from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from kenradar.core.config import AppConfig
from kenradar.storage import create_database
from kenradar.web.queries import (
    find_aweme_markdown,
    is_recommended_for_reading,
    load_bloggers,
    load_brief_files,
    load_failures,
    load_intelligence_overview,
    load_log_lines,
    load_note_files,
    load_push_logs,
    load_aweme_progress,
    load_research_job,
    load_research_job_items,
    load_research_pipeline_stats,
    load_research_jobs,
    list_markdown_files,
    load_aweme_detail,
    load_aweme_rows,
    load_health,
    load_recent_alerts,
    normalize_project_path,
    load_source_quality,
    load_stats,
    parse_summary_json,
    read_text,
    safe_data_path,
)
from kenradar.web.static import WEB_CSS, WEB_SCRIPT


# ── Full page shell ──

def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="KenRadar 本地流媒体内容监控、转录、AI 笔记与飞书推送管理后台">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <title>{html.escape(title)}</title>
  <style>{WEB_CSS}</style>
</head>
<body>
        {body}
        <script>{WEB_SCRIPT}</script></body>
</html>"""


def page_shell(title: str, active: str, body: str) -> str:
    return page(
        title,
        f"""
        <div class="app-shell">
          {sidebar(active)}
          <div class="main-content">
            {body}
          </div>
        </div>
        """,
    )


def sidebar(active: str) -> str:
    groups = [
        ("核心工作区", [
            ("仪表盘", "/", "dashboard"),
            ("内容工作台", "/operations", "operations"),
            ("归档研究", "/archive", "archive"),
        ]),
        ("系统管理", [
            ("来源管理", "/sources", "sources"),
            ("系统配置", "/config", "config"),
            ("系统监控", "/logs", "logs"),
        ]),
    ]
    nav_parts = []
    for group_label, items in groups:
        nav_parts.append(f'<div class="nav-label">{group_label}</div>')
        for _label, url, key in items:
            cls = "active" if key == active else ""
            icon = nav_icon(key)
            nav_parts.append(f'<a href="{url}" class="{cls}">{icon}<span>{_label}</span></a>')
    return f"""
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo-dot">K</div>
        <div>
          <div class="title">KenRadar</div>
          <div class="subtitle">信息雷达控制台</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        {''.join(nav_parts)}
      </nav>
      <div class="sidebar-footer">
        <button type="button" class="theme-toggle">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>
          <span>切换主题</span>
        </button>
      </div>
    </aside>"""


def nav_icon(key: str) -> str:
    icons = {
        "dashboard": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M3 13h8V3H3v10Z"/><path d="M13 21h8V11h-8v10Z"/><path d="M13 3h8v6h-8V3Z"/><path d="M3 21h8v-6H3v6Z"/></svg>',
        "operations": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 7h16"/><path d="M4 12h10"/><path d="M4 17h7"/><path d="m15 16 2 2 4-5"/></svg>',
        "archive": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 8v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8"/><path d="M3 4h18v4H3z"/><path d="M10 12h4"/></svg>',
        "config": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.36a1.7 1.7 0 0 0-1 .57V20a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-.57 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-.57-1H4a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 .57-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.64a1.7 1.7 0 0 0 1-.57V4a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 .57 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.36 9c.2.35.39.69.57 1H20a2 2 0 1 1 0 4h-.09c-.18.31-.37.65-.51 1Z"/></svg>',
        "sources": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20"/><path d="M12 2a15 15 0 0 0 0 20"/></svg>',
        "items": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg>',
        "notes": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7l-5-5Z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h6"/></svg>',
        "briefs": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 4h16v16H4z"/><path d="M8 8h8"/><path d="M8 12h8"/><path d="M8 16h5"/></svg>',
        "pushes": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/></svg>',
        "research": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6"/><path d="M8 11h6"/></svg>',
        "failures": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
        "logs": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M4 5h16"/><path d="M4 12h16"/><path d="M4 19h16"/></svg>',
    }
    return icons.get(key, icons["dashboard"])


# ── Intelligence list (used by dashboard) ──

def render_intelligence_item_list(config: AppConfig, items: list[dict[str, Any]], empty: str = "暂无内容。") -> str:
    if not items:
        return f'<p class="empty">{empty}</p>'
    out = []
    for item in items:
        aweme_id = str(item.get("aweme_id") or "")
        title = str(item.get("title") or item.get("nickname") or "无标题")
        blogger = str(item.get("nickname") or "")
        score = item.get("value_score")
        score_str = f" · 评分 {format_score(score)}" if score is not None else ""
        href = "/aweme?id=" + html.escape(aweme_id)
        if item.get("summary_path"):
            title_link = file_link(config, Path(str(item.get("summary_path"))), html.escape(title))
        elif aweme_id:
            title_link = '<a href="' + href + '">' + html.escape(title) + '</a>'
        else:
            title_link = html.escape(title)
        out.append(
            '<li>'
            + title_link
            + "<span>" + html.escape(blogger) + score_str + "</span>"
            + "<p>" + html.escape(str(item.get("short_summary") or "") or "") + "</p>"
            + '</li>'
        )
    return '<ul class="intel-list">' + "".join(out) + "</ul>"


def _rank_item_name_count(item: Any) -> tuple[str, int | float]:
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("nickname") or item.get("label") or "")
        count = item.get("count", 0) or 0
    elif isinstance(item, (tuple, list)) and len(item) >= 2:
        name = str(item[0] or "")
        count = item[1] or 0
    else:
        name = str(item or "")
        count = 0
    try:
        return name, float(count)
    except (TypeError, ValueError):
        return name, 0


def render_rank_list(items: list[Any], empty: str = "暂无数据。") -> str:
    if not items:
        return f'<p class="empty">{empty}</p>'
    normalized = [_rank_item_name_count(item) for item in items]
    max_count = max((count for _, count in normalized), default=1)
    out = []
    for name, count in normalized:
        pct = round(count / max_count * 100) if max_count else 0
        count_text = str(int(count)) if float(count).is_integer() else f"{count:.1f}"
        out.append(
            '<li>'
            f'<div><strong>{html.escape(name)}</strong><span>{html.escape(count_text)}</span></div>'
            f'<div class="progress compact"><span style="width:{pct}%"></span></div>'
            '</li>'
        )
    return '<ul class="rank-list">' + "".join(out) + "</ul>"


# ── Dashboard ──

def render_dashboard(config: AppConfig, task_state: dict[str, Any]) -> str:
    create_database(config).initialize()
    intelligence = load_intelligence_overview(config)
    awemes = load_aweme_rows(config, limit=12)
    queued_tasks = task_state.get("queue") if isinstance(task_state.get("queue"), list) else []
    queue_suffix = f" ｜ 排队 {len(queued_tasks)}" if queued_tasks else ""
    return page_shell(
        "仪表盘",
        "dashboard",
        f"""
        <header class="topbar">
          <h1 class="page-title">今日情报总览</h1>
          <div class="quick-actions">
            <span id="task-status">{html.escape(str(task_state.get("message") or "空闲") + queue_suffix)}</span>
            <button type="button" class="secondary" data-post="/api/test-latest">测试最新</button>
            <button type="button" data-post="/api/run-once">手动检测</button>
          </div>
        </header>

        <main class="layout wide">
          <section class="panel intelligence-hero">
            <div class="section-head">
              <div>
                <h2>情报概览</h2>
                <p>今日新增 {html.escape(str(intelligence["today_new"]))} 条 ｜ 建议阅读 {html.escape(str(intelligence["recommended_count"]))} 条 ｜ 建议深挖 {html.escape(str(intelligence["deep_count"]))} 条</p>
              </div>
            </div>
            <div class="intel-grid">
              <div>
                <h3>今日最值得看</h3>
                {render_intelligence_item_list(config, intelligence["top_items"], empty="暂无高分内容。")}
              </div>
              <div>
                <h3>值得深挖</h3>
                {render_intelligence_item_list(config, intelligence["deep_items"], empty="暂无深挖建议。")}
              </div>
            </div>
          </section>

          <section class="intel-two-col">
            <div class="panel">
              <div class="section-head"><h2>近 7 日主题热度</h2><p>按 AI 标签聚合。</p></div>
              {render_rank_list(intelligence["topics"], "暂无主题标签。")}
            </div>
            <div class="panel">
              <div class="section-head"><h2>高热博主更新</h2><p>近 7 日更新数量。</p></div>
              {render_rank_list(intelligence["bloggers"], "暂无博主更新。")}
            </div>
          </section>

          <section class="panel">
            <div class="section-head">
              <h2>最近内容流</h2>
              <p>卡片视图用于阅读，表格入口保留在内容工作台。</p>
            </div>
            {render_aweme_cards(config, awemes)}
          </section>
        </main>
        """
    )


# ── Operations / Content Workbench ──

def render_operations_page(config: AppConfig) -> str:
    awemes = load_aweme_rows(config, limit=1000)
    active_retries = sum(1 for row in awemes if str(row.get("download_status") or "") == "failed" or str(row.get("transcript_status") or "") == "failed" or str(row.get("summary_status") or "") == "failed")

    return page_shell(
        "内容工作台",
        "operations",
        f"""
        <header class="topbar">
          <h1 class="page-title">内容工作台</h1>
          <div class="quick-actions">
            <button type="button" class="secondary" data-post="/api/run-once">手动全量检测</button>
            <button type="button" class="secondary" data-post="/api/restart-web" data-confirm="确认重启 Web 服务？当前正在运行的任务将被中断。">重启服务</button>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/operations" class="active">内容任务</a>
            <a href="/operations/retry">失败重试</a>
          </nav>

          <div class="stats">
            <div class="stat stat-monitor" data-category="monitor"><span>内容任务</span><strong data-count>{len(awemes)}</strong></div>
            <div class="stat stat-failed" data-category="failed"><span>需处理失败</span><strong data-count>{active_retries}</strong></div>
          </div>

          <section class="panel">
            <div class="section-head">
              <h2>内容任务</h2>
              <form class="inline-action">
                <p>按内容查看每个环节的状态，并可重试失败阶段。</p>
                <button type="button" class="secondary" data-table-density>紧凑视图</button>
              </form>
            </div>
            {render_filters(awemes)}
            {render_aweme_table(config, awemes)}
          </section>
        </main>
        """
    )


def render_operations_retry_page(config: AppConfig) -> str:
    failures = load_failures(config)
    awemes = load_aweme_rows(config, limit=1000)
    active_retries = sum(1 for row in awemes if str(row.get("download_status") or "") == "failed" or str(row.get("transcript_status") or "") == "failed" or str(row.get("summary_status") or "") == "failed")

    return page_shell(
        "失败重试",
        "operations",
        f"""
        <header class="topbar">
          <h1 class="page-title">失败重试</h1>
          <div class="quick-actions">
            <button type="button" class="secondary" data-post="/api/run-once">手动全量检测</button>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/operations">内容任务</a>
            <a href="/operations/retry" class="active">失败重试</a>
          </nav>

          <div class="stats">
            <div class="stat stat-failed" data-category="failed"><span>可重试失败</span><strong data-count>{active_retries}</strong></div>
            <div class="stat stat-failed" data-category="failed"><span>失败任务记录</span><strong data-count>{len(failures)}</strong></div>
          </div>

          {render_batch_retry_bar()}

          <section class="panel">
            <div class="section-head"><h2>失败任务</h2><p>下载、转录、AI 整理、笔记生成中可处理的问题统一在这里处理。</p></div>
            {render_failure_table(failures)}
          </section>
        </main>
        """
    )


def render_operations_pushes_page(config: AppConfig) -> str:
    return render_monitor_pushes_page(config)


# ── Archive / Research ──

def render_archive_page(config: AppConfig) -> str:
    awemes = load_aweme_rows(config, limit=4000)
    jobs = load_research_jobs(config)

    blogger_groups: dict[str, list[dict[str, Any]]] = {}
    for row in awemes:
        name = str(row.get("nickname") or "未分类")
        blogger_groups.setdefault(name, []).append(row)

    blogger_names = sorted(blogger_groups.keys(), key=lambda n: -len(blogger_groups[n]))
    blogger_options = "".join(
        f'<option value="{html.escape(name)}">{html.escape(name)} ({len(blogger_groups[name])})</option>'
        for name in blogger_names
    )

    total = len(awemes)
    groups_html = []
    for index, name in enumerate(blogger_names):
        rows = blogger_groups[name]
        cards = []
        for row in rows:
            aweme_id = str(row.get("aweme_id") or "")
            title = str(row.get("brief_title") or row.get("title") or "无标题")
            summary = str(row.get("brief_summary") or "")
            tags = row.get("tags") or []
            score = format_score(row.get("value_score"))
            published = str(row.get("publish_time") or str(row.get("create_time") or ""))
            status_parts = []
            for st, label in [("download_status", "下载"), ("transcript_status", "转录"), ("summary_status", "AI")]:
                val = normalize_status(row.get(st))
                if val == "success":
                    status_parts.append(f'<span style="color:var(--status-ok);font-weight:600;">✓{label}</span>')
                elif val == "failed":
                    status_parts.append(f'<span style="color:var(--status-bad);font-weight:600;">✗{label}</span>')
                elif val == "pending":
                    status_parts.append(f'<span style="color:var(--text-muted);">{label}…</span>')
            status_html = " ".join(status_parts)

            video_url = str(row.get("video_url") or "")
            source_link = f' · <a class="subtle-link" href="{html.escape(video_url)}" target="_blank" rel="noreferrer">原视频</a>' if video_url else ""
            card = f"""
            <div class="note-card" data-blogger="{html.escape(name)}">
              <div class="note-card-body">
                <a href="/aweme?id={html.escape(aweme_id)}" class="note-card-title">{html.escape(title)}</a>
                <div class="note-card-meta">{html.escape(name)} · {html.escape(published)}{source_link}</div>
                {f'<p class="note-card-summary">{html.escape(summary[:150])}</p>' if summary else ''}
                {render_tags(tags)}
                <div class="note-card-footer">
                  <span class="note-card-score" style="color:var(--accent);font-weight:700;font-size:16px;">{score}</span>
                  <span class="note-card-status">{status_html}</span>
                </div>
              </div>
              <div class="note-card-actions single-action">
                <a class="button secondary" href="/aweme?id={html.escape(aweme_id)}" style="padding:4px 10px;font-size:12px;">阅读笔记</a>
              </div>
            </div>
            """
            cards.append(card)
        open_attr = " open" if index < 3 else ""
        groups_html.append(f"""
        <details class="blogger-group"{open_attr}>
          <summary class="blogger-group-head">
            <strong>{html.escape(name)}</strong>
            <span class="muted">{len(rows)} 条内容</span>
          </summary>
          <div class="note-card-grid">{"".join(cards)}</div>
        </details>
        """)

    return page_shell(
        "归档研究",
        "archive",
        f"""
        {research_auto_refresh(jobs)}
        <header class="topbar">
          <h1 class="page-title">内容资料库</h1>
          <div class="quick-actions">
            <span class="muted">{total} 条归档</span>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/archive" class="active">内容资料库</a>
            <a href="/archive/research">研究任务</a>
            <a href="/archive/notes">Markdown 笔记</a>
            <a href="/archive/briefs">简报</a>
          </nav>

          <section class="panel">
            <div class="section-head">
              <h2>按博主浏览</h2>
              <p>点击卡片"阅读笔记"进入统一详情页。</p>
            </div>
            <div class="archive-filters">
              <input id="archive-search" placeholder="搜索标题、摘要..." oninput="filterArchive()">
              <select id="archive-blogger" onchange="filterArchive()">
                <option value="">全部博主</option>
                {blogger_options}
              </select>
            </div>
          </section>

          <div class="archive-groups">{"".join(groups_html)}</div>
        </main>
        """
    )


def render_archive_research_page(config: AppConfig) -> str:
    jobs = load_research_jobs(config)
    bloggers = load_bloggers(config)
    blogger_options = "".join(
        f'<option value="{html.escape(str(row.get("nickname") or row.get("sec_uid") or ""))}">{html.escape(str(row.get("nickname") or row.get("sec_uid") or ""))}</option>'
        for row in bloggers
    )
    blogger_datalist = "".join(
        f'<option value="{html.escape(str(row.get("nickname") or row.get("sec_uid") or row.get("douyin_url") or ""))}"></option>'
        for row in bloggers
        if row.get("monitor_enabled") or row.get("in_config")
    )

    return page_shell(
        "研究任务",
        "archive",
        f"""
        {research_auto_refresh(jobs)}
        <header class="topbar">
          <h1 class="page-title">研究任务</h1>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/archive">内容索引</a>
            <a href="/archive/research" class="active">研究任务</a>
            <a href="/archive/notes">Markdown 笔记</a>
            <a href="/archive/briefs">简报</a>
          </nav>

          <section class="panel">
            <div class="section-head">
              <h2>研究单个视频</h2>
              <p>粘贴抖音视频页或分享短链，单独完成下载、转录、AI 整理和 Obsidian 笔记归档。</p>
            </div>
            <form method="post" action="/api/research-video" class="mini-form" data-action-form>
              <label>视频链接 / 分享短链</label>
              <input name="video" placeholder="https://www.douyin.com/video/... 或 https://v.douyin.com/...">
              <label>aweme_id</label>
              <input name="aweme_id" placeholder="已知视频 ID 时可直接填写">
              <label class="check"><input type="checkbox" name="force"> 强制重跑已归档视频</label>
              <label class="check"><input type="checkbox" name="push"> 完成后推送飞书</label>
              <div class="form-actions"><button type="submit">研究视频</button></div>
            </form>
          </section>

          <section class="panel">
            <div class="section-head">
              <h2>研究博主</h2>
              <p>手动批量抓取指定抖音博主历史视频，默认不推送飞书。</p>
            </div>
            <form method="post" action="/api/research-blogger" class="mini-form" data-action-form data-research-form>
              <label>选择已配置博主</label>
              <select name="blogger_select"><option value="">手动输入</option>{blogger_options}</select>
              <label>博主名称 / sec_uid / 主页链接</label>
              <input name="blogger" list="research-blogger-list" placeholder="例如：福总说实话 或 https://www.douyin.com/user/...">
              <datalist id="research-blogger-list">{blogger_datalist}</datalist>
              <label>处理上限</label>
              <input name="limit" type="number" min="0" value="10">
              <label>开始日期</label>
              <input name="since" type="date">
              <label>结束日期</label>
              <input name="until" type="date">
              <label class="check"><input type="checkbox" name="force"> 强制重跑已归档视频</label>
              <label class="check"><input type="checkbox" name="push"> 完成后推送研究简报</label>
              <div class="form-actions"><button type="submit">开始研究</button></div>
            </form>
          </section>

          <section class="panel">
            <div class="section-head"><h2>研究任务列表</h2><p>同一时间建议只运行一个重型研究任务。</p></div>
            {render_research_job_table(jobs)}
          </section>
        </main>
        """
    )


def render_archive_notes_page(config: AppConfig) -> str:
    notes = load_note_files(config)

    return page_shell(
        "Markdown 笔记",
        "archive",
        f"""
        <header class="topbar">
          <h1 class="page-title">Markdown 笔记</h1>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/archive">内容索引</a>
            <a href="/archive/research">研究任务</a>
            <a href="/archive/notes" class="active">Markdown 笔记</a>
            <a href="/archive/briefs">简报</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>最终 Obsidian 笔记</h2><p>按平台和博主归档，点击阅读完整笔记。</p></div>
            {render_note_filters(notes)}
            {render_note_table(config, notes)}
          </section>
        </main>
        """
    )


def render_archive_briefs_page(config: AppConfig) -> str:
    briefs = load_brief_files(config)

    return page_shell(
        "流媒体简报",
        "archive",
        f"""
        <header class="topbar">
          <h1 class="page-title">流媒体简报</h1>
          <div class="quick-actions">
            <button type="button" class="secondary" data-post="/api/generate-weekly">生成周报</button>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/archive">内容索引</a>
            <a href="/archive/research">研究任务</a>
            <a href="/archive/notes">Markdown 笔记</a>
            <a href="/archive/briefs" class="active">简报</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>飞书推送简报</h2><p>每次推送时生成的精简 Markdown 简报。</p></div>
            {render_brief_table(config, briefs)}
          </section>
        </main>
        """
    )


# ── Error / File / Research Job Pages ──

def render_error(message: str) -> str:
    safe = html.escape(str(message or "未知错误"))
    return page(
        "错误",
        f"""
        <div class="app-shell">
          <div class="main-content">
            <div class="layout" style="text-align:center;padding-top:80px;">
              <h1>出错了</h1>
              <p class="muted" style="margin:16px 0;">{safe}</p>
              <a href="/" class="button">返回首页</a>
            </div>
          </div>
        </div>
        """,
    )


def _read_data_file(config: AppConfig, path_value: Any) -> str:
    value = str(path_value or "").strip()
    if not value:
        return ""
    try:
        return read_text(safe_data_path(config, value))
    except (FileNotFoundError, OSError, ValueError):
        return ""


def render_file(config: AppConfig, rel_path: str) -> str:
    path = normalize_project_path(config, Path(rel_path))
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return render_error(f"文件未找到: {html.escape(rel_path)}")
    _, ext = path.suffix.lower(), path.suffix
    if ext in {".md", ".markdown", ".txt"}:
        note_title = path.stem.replace("_", " ")
        return page_shell(
            note_title[:48],
            "",
            f"""
            <header class="topbar">
              <h1 class="page-title">{html.escape(note_title[:60])}</h1>
              <div class="quick-actions">
                <a href="/archive" class="button secondary" style="padding:4px 10px;font-size:12px;">← 返回资料库</a>
              </div>
            </header>
            <main class="layout">
              <div class="markdown">{html.escape(text)}</div>
            </main>
            """
        )
    return render_error(f"不支持的文件类型: {ext}")


def render_research_job_page(config: AppConfig, job_id: int) -> str:
    job = load_research_job(config, job_id)
    if not job:
        return render_error("研究任务未找到")
    items = load_research_job_items(config, job_id)
    pipeline = load_research_pipeline_stats(config, job_id)
    total = int(job.get("total_count") or 0)
    done = int(job.get("success_count") or 0) + int(job.get("failed_count") or 0) + int(job.get("skipped_count") or 0)
    pct = round(done / total * 100) if total > 0 else 0

    return page_shell(
        f"研究任务 #{job_id}",
        "archive",
        f"""
        {research_auto_refresh([job])}
        <header class="topbar">
          <h1 class="page-title">研究任务 #{html.escape(str(job_id))}</h1>
          <div class="quick-actions">
            <span id="task-status"></span>
            <button type="button" class="secondary" data-post="/api/research/pause?id={html.escape(str(job_id))}">暂停任务</button>
            <button type="button" class="secondary" data-post="/api/research/resume?id={html.escape(str(job_id))}" data-confirm="确认接续这个研究任务？系统会取消旧的卡住任务，并新建任务继续处理未完成内容。">接续任务</button>
            <button type="button" class="secondary" data-post="/api/research/cancel?id={html.escape(str(job_id))}" data-confirm="确认取消这个研究任务？当前正在执行的单步会尽快收尾。">取消任务</button>
            <button type="button" class="secondary" data-post="/api/research/restart?id={html.escape(str(job_id))}" data-confirm="确认重新启动这个研究任务？">重新启动</button>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/archive/research">研究任务</a>
            <a href="/research/jobs?id={html.escape(str(job_id))}" class="active">{html.escape(str(job_id))}</a>
          </nav>

          <div class="panel" data-research-job="{html.escape(str(job_id))}">
            <div class="section-head"><h2>进度</h2><p>实时更新</p></div>
            <div class="progress-row"><div class="progress"><span style="width:{pct}%"></span></div><strong>{done}/{total} · {pct}%</strong></div>
            <div id="research-progress">{render_research_progress(job)}</div>
            <div id="research-current">{render_current_research_item(job)}</div>
            <div id="research-pipeline">{render_research_pipeline(pipeline)}</div>
          </div>

          <div class="panel">
            <div class="section-head"><h2>条目列表</h2></div>
            <div id="research-items">{render_research_item_table(config, items)}</div>
          </div>
        </main>
        """
    )


# ── Sources ──

def render_sources_page(config: AppConfig) -> str:
    bloggers = load_bloggers(config)
    quality = load_source_quality(config)

    return page_shell(
        "来源管理",
        "sources",
        f"""
        <header class="topbar">
          <h1 class="page-title">来源管理</h1>
        </header>
        <main class="layout wide">
          <section class="panel">
            <div class="section-head"><h2>监控博主</h2><p>管理关注博主、来源质量评分和新博主接入。</p></div>
            {render_blogger_table(bloggers)}
          </section>

          <section class="panel">
            <div class="section-head"><h2>新增来源</h2><p>输入抖音主页链接，系统自动解析昵称和 sec_uid。</p></div>
            <form method="post" action="/sources/add" class="mini-form">
              <label>抖音主页链接</label>
              <input name="url" placeholder="https://www.douyin.com/user/..." required>
              <label>来源分类</label>
              <input name="category" placeholder="例如：科技、财经">
              <label>sec_uid（可选）</label>
              <input name="sec_uid" placeholder="自动解析">
              <label>备注</label>
              <input name="note" placeholder="例如：投资类、科技类">
              <label class="check"><input type="checkbox" name="enabled" checked> 立即启用监控</label>
              <div class="form-actions"><button type="submit">添加来源</button></div>
            </form>
          </section>
        </main>
        """
    )


# ── Config ──

def render_config_page(config: AppConfig) -> str:
    return page_shell(
        "配置",
        "config",
        f"""
        <header class="topbar">
          <h1 class="page-title">系统配置</h1>
        </header>
        <main class="layout wide">
          {render_config_form(config)}
        </main>
        """
    )


# ── Logs ──

# ── System Monitor (upgraded from logs) ──

def render_monitor_status_page(config: AppConfig) -> str:
    health = load_health(config)
    alerts = load_recent_alerts(config, limit=10)
    awemes = load_aweme_rows(config, limit=6)

    return page_shell(
        "系统状态",
        "logs",
        f"""
        <header class="topbar">
          <h1 class="page-title">系统状态</h1>
          <div class="quick-actions">
            <span id="task-status"></span>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/logs/status" class="active">系统状态</a>
            <a href="/logs/pushes">推送记录</a>
            <a href="/logs/alerts">系统告警</a>
            <a href="/logs/runtime">运行日志</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>健康状态</h2><p>调度、磁盘、推送、告警概览，优先看异常和最近检测时间。</p></div>
            <div class="ops-summary monitor-health">{render_health_cards(health)}</div>
          </section>

          <div class="intel-two-col">
            <section class="panel">
              <div class="section-head">
                <h2>最近内容</h2>
                <a href="/operations" class="button secondary" style="padding:4px 10px;font-size:12px;">去内容工作台</a>
              </div>
              {render_aweme_cards(config, awemes)}
            </section>
            <section class="panel">
              <div class="section-head">
                <h2>最近告警</h2>
                <a href="/logs/alerts" class="button secondary" style="padding:4px 10px;font-size:12px;">查看全部</a>
              </div>
              {render_alert_list(alerts)}
            </section>
          </div>
        </main>
        """
    )


def render_monitor_pushes_page(config: AppConfig) -> str:
    pushes = load_push_logs(config, limit=200)

    return page_shell(
        "推送记录",
        "logs",
        f"""
        <header class="topbar">
          <h1 class="page-title">推送记录</h1>
          <div class="quick-actions">
            <button type="button" class="secondary" data-post="/api/test-feishu-card">测试 Card</button>
            <button type="button" class="secondary" data-post="/api/test-feishu-text">测试 Text</button>
          </div>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/logs/status">系统状态</a>
            <a href="/logs/pushes" class="active">推送记录</a>
            <a href="/logs/alerts">系统告警</a>
            <a href="/logs/runtime">运行日志</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>飞书推送记录</h2><p>查看每次发送给飞书的推送详情。</p></div>
            {render_push_table(pushes)}
          </section>
        </main>
        """
    )


def render_monitor_alerts_page(config: AppConfig) -> str:
    alerts = load_recent_alerts(config, limit=200)

    return page_shell(
        "系统告警",
        "logs",
        f"""
        <header class="topbar">
          <h1 class="page-title">系统告警</h1>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/logs/status">系统状态</a>
            <a href="/logs/pushes">推送记录</a>
            <a href="/logs/alerts" class="active">系统告警</a>
            <a href="/logs/runtime">运行日志</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>告警记录</h2><p>失败来源、转录和 AI 整理异常。</p></div>
            {render_alert_list(alerts)}
          </section>
        </main>
        """
    )


def render_monitor_runtime_page(config: AppConfig) -> str:
    return page_shell(
        "运行日志",
        "logs",
        f"""
        <header class="topbar">
          <h1 class="page-title">运行日志</h1>
        </header>
        <main class="layout wide">
          <nav class="sub-nav">
            <a href="/logs/status">系统状态</a>
            <a href="/logs/pushes">推送记录</a>
            <a href="/logs/alerts">系统告警</a>
            <a href="/logs/runtime" class="active">运行日志</a>
          </nav>

          <section class="panel">
            <div class="section-head"><h2>运行日志</h2><p>读取 data/kenradar.log，支持前端关键词过滤。</p></div>
            <div class="filters"><input id="log-search" placeholder="搜索日志"><select id="log-level"><option value="">全部级别</option><option value="info">info</option><option value="warning">warning</option><option value="error">error</option></select><select id="log-component"><option value="">全部模块</option><option value="crawler">crawler</option><option value="download">download</option><option value="whisper">whisper</option><option value="ai">ai</option><option value="feishu">feishu</option><option value="web">web</option><option value="note">note</option></select></div>
            {render_log_table(load_log_lines(config))}
          </section>
        </main>
        """
    )


# ── Detail Pages ──

def render_aweme(config: AppConfig, aweme_id: str) -> str:
    if not aweme_id:
        return render_error("缺少 aweme id")
    row = load_aweme_detail(config, aweme_id)
    if not row:
        return render_error("未找到内容记录")

    title = str(row.get("title") or row.get("brief_title") or "无标题")
    nickname = str(row.get("nickname") or "未知博主")
    tags_html = render_tags(row.get("tags") or [])
    note_text = _read_data_file(config, row.get("summary_path") or row.get("note_path"))
    note_html = render_obsidian_note(note_text) if note_text else '<p class="empty">暂无笔记内容。</p>'
    summary_json = parse_summary_json(str(row.get("summary_text") or "")) or {}
    reason = str(row.get("recommendation_reason") or summary_json.get("recommendation_reason") or "")

    aweme_id_enc = html.escape(aweme_id)
    publish_time = format_ts(row.get("create_time"))
    nickname_enc = html.escape(nickname)
    title_enc = html.escape(title)

    transcript_text = str(row.get("text_content") or "") or _read_data_file(config, row.get("text_path"))
    transcript_html = ""
    if transcript_text:
        transcript_html = f'<div class="panel note-transcript-panel"><details class="transcript-fold"><summary>Whisper 转录原文</summary><pre>{html.escape(transcript_text[:8000])}</pre></details></div>'

    source_url = str(row.get("video_url") or f"https://www.douyin.com/video/{aweme_id}")
    progress = load_aweme_progress(config, aweme_id) or {}
    summary_path = str(row.get("summary_path") or "")
    raw_file_link = ""
    if summary_path:
        try:
            summary_file = safe_data_path(config, summary_path)
            raw_file_link = f'<a class="button secondary" href="/file?path={quote(str(summary_file.relative_to(config.root_dir)))}">查看原始文件</a>'
        except (FileNotFoundError, ValueError):
            raw_file_link = ""

    return page_shell(
        title[:48],
        "archive",
        f"""
        <header class="topbar">
          <h1 class="page-title">{title_enc}</h1>
          <div class="quick-actions">
            <a href="/archive" class="button secondary" style="padding:4px 10px;font-size:12px;">← 返回资料库</a>
          </div>
        </header>
        <main class="layout wide">
          <div class="note-detail-layout">
            <div class="note-reading-panel">
              <div class="panel structured note-reading-body">
                {note_html}
              </div>
              {transcript_html}
            </div>
            <div class="note-side-panel">
              <div class="panel aweme-progress-panel" data-aweme-progress="{aweme_id_enc}">
                <div class="section-head"><h2>处理进度</h2><p>实时状态</p></div>
                <div id="aweme-progress">{render_aweme_progress(progress)}</div>
              </div>
              <div class="panel">
                <div class="section-head"><h2>信息概览</h2></div>
                <div class="side-score-card">
                  <strong>{format_score(row.get("value_score"))}</strong>
                  <span>价值评分 · {html.escape(action_label(row.get("recommended_action")))}</span>
                </div>
                {f'<p class="side-reason">{html.escape(reason)}</p>' if reason else ''}
                <table class="compact-meta">
                  <tbody>
                    <tr><th>博主</th><td>{nickname_enc}</td></tr>
                    <tr><th>发布时间</th><td>{publish_time}</td></tr>
                    <tr><th>状态</th><td><span class="status-mini-row">{badge(normalize_status(row.get("download_status")))}{badge(normalize_status(row.get("transcript_status")))}{badge(normalize_status(row.get("summary_status")))}{badge(normalize_status(row.get("push_status")))}</span></td></tr>
                    <tr><th>aweme_id</th><td class="mono">{aweme_id_enc}</td></tr>
                    <tr><th>原视频</th><td><a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">打开原视频 ↗</a></td></tr>
                  </tbody>
                </table>
                {tags_html}
                {render_aweme_side_metrics(row)}
              </div>
              <div class="panel">
                <h2>操作</h2>
                <div class="side-actions">
                  <button type="button" class="secondary" data-copy-raw>复制 Markdown</button>
                  <a class="button secondary" href="{html.escape(source_url)}" target="_blank" rel="noreferrer">打开原视频</a>
                  {raw_file_link}
                  <details class="more-actions">
                    <summary>更多操作</summary>
                    <button type="button" class="secondary" data-post="/api/retry-full?id={aweme_id_enc}">重新整理</button>
                    <button type="button" class="secondary" data-post="/api/repush-aweme?id={aweme_id_enc}">重新推送飞书</button>
                    <button type="button" class="secondary" data-post="/api/retry-full?id={aweme_id_enc}">全流程重试</button>
                  </details>
                </div>
              </div>
            </div>
          </div>
          <pre class="raw-markdown" hidden>{html.escape(note_text)}</pre>
        </main>
        """
    )


def render_aweme_cards(config: AppConfig, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">暂无内容。</p>'
    cards = []
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "无标题")
        blogger = str(row.get("nickname") or "")
        summary_text = str(row.get("brief_summary") or "")
        if not summary_text:
            raw = str(row.get("summary_text") or "")
            m = re.search(r'"brief_summary"\s*:\s*"([^"]+)"', raw)
            summary_text = m.group(1) if m else raw[:280]
        score = row.get("value_score")
        action = str(row.get("recommended_action") or "")
        published = format_ts(row.get("create_time"))
        cards.append(
            '<div class="aweme-card">'
            f'<div class="aweme-card-main"><a href="/aweme?id={html.escape(aweme_id)}" class="aweme-card-title">{html.escape(title)}</a>'
            f'<p>{html.escape(summary_text[:280])}</p></div>'
            f'<div class="aweme-card-side"><strong>{format_score(score)}</strong><span>价值评分</span>'
            f'{"<em>推送</em>" if action == "push" else ""}</div>'
            f'<div class="aweme-card-meta">{html.escape(blogger)} · {html.escape(published)}</div>'
            '<div class="inline-action compact-action">'
            f'<a class="button-link" href="/aweme?id={html.escape(aweme_id)}">阅读</a>'
            '</div></div>'
        )
    return '<div class="aweme-card-grid">' + "".join(cards) + "</div>"


def render_aweme_table(config: AppConfig, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">暂无内容任务。</p>'

    body = []
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "无标题")
        nickname = str(row.get("nickname") or "")
        download_status = normalize_status(row.get("download_status"))
        transcript_status = normalize_status(row.get("transcript_status"))
        summary_status = normalize_status(row.get("summary_status"))
        push_status = normalize_status(row.get("push_status"))
        publish_time = format_ts(row.get("create_time"))
        search = escape_for_search(aweme_id, title, nickname)

        retry_actions = ""
        if download_status == "failed":
            retry_actions += f'<button type="button" data-post="/api/retry-download?id={html.escape(aweme_id)}">重试下载</button> '
        if transcript_status == "failed":
            retry_actions += f'<button type="button" data-post="/api/retry-transcribe?id={html.escape(aweme_id)}">重试转录</button> '
        if summary_status == "failed":
            retry_actions += f'<button type="button" data-post="/api/retry-summary?id={html.escape(aweme_id)}">重试 AI</button> '
        if not retry_actions and (download_status == "failed" or transcript_status == "failed" or summary_status == "failed"):
            retry_actions = f'<button type="button" data-post="/api/retry-full?id={html.escape(aweme_id)}">全流程重试</button> '
        if retry_actions:
            retry_actions = " " + retry_actions

        note_link = file_link(config, Path(str(row.get("summary_path") or "")), "笔记") if row.get("summary_path") else '<span class="muted">无笔记</span>'

        body.append(
            '<tr data-search="' + html.escape(search) + '" '
            'data-blogger="' + html.escape(nickname) + '" '
            'data-status="' + html.escape(download_status) + '">'
            f'<td><a href="/aweme?id={html.escape(aweme_id)}">{html.escape(aweme_id)}</a></td>'
            f'<td>{html.escape(title)}</td>'
            f'<td>{badge(download_status)}</td>'
            f'<td>{badge(transcript_status)}</td>'
            f'<td>{badge(summary_status)}</td>'
            f'<td>{badge(push_status)}</td>'
            f'<td>{html.escape(nickname)}</td>'
            f'<td>{html.escape(publish_time)}</td>'
            f'<td><a href="/aweme?id={html.escape(aweme_id)}">查看</a> {note_link}{retry_actions}</td>'
            '</tr>'
        )

    return f"""
    <div class="table-wrap" data-compact-table>
      <table>
        <thead>
          <tr>
            <th>aweme_id</th><th>标题</th><th>下载</th><th>转录</th><th>AI</th><th>推送</th><th>博主</th><th>发布时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    """


def render_failure_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">暂无失败任务。</p>'
    body = []
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "无标题")
        nickname = str(row.get("nickname") or "")
        error = str(row.get("last_error") or row.get("error_message") or row.get("summary_error") or "")
        stage_label = str(row.get("failed_stage") or retry_stage_label(row))
        stage = retry_stage(row)
        retry = retryButtons(aweme_id, stage, includeFull=True)
        body.append(
            '<tr>'
            f'<td><input type="checkbox" data-retry-check value="{html.escape(aweme_id)}"></td>'
            f'<td><a href="/aweme?id={html.escape(aweme_id)}">{html.escape(aweme_id)}</a></td>'
            f'<td>{html.escape(title)}</td>'
            f'<td>{html.escape(nickname)}</td>'
            f'<td>{badge(stage_label)}</td>'
            f'<td class="mono">{html.escape(error[:120])}</td>'
            f'<td>{html.escape(str(row.get("updated_at") or row.get("created_at") or ""))}</td>'
            f'<td>{retry}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th><input type="checkbox" data-retry-check-all></th>
            <th>aweme_id</th><th>标题</th><th>博主</th><th>失败阶段</th><th>错误</th><th>更新时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    """


def render_push_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">暂无推送记录。</p>'
    body = []
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "无标题")
        blogger = str(row.get("blogger_name") or "")
        ok_text = "成功" if row.get("ok") else "失败"
        ok_class = "success" if row.get("ok") else "failed"
        detail_link = f'<a href="/aweme?id={html.escape(aweme_id)}">详情</a>' if aweme_id else ""
        body.append(
            '<tr>'
            f'<td>{html.escape(aweme_id)}</td>'
            f'<td>{html.escape(title)}</td>'
            f'<td>{html.escape(blogger)}</td>'
            f'<td>{badge(ok_class)} {html.escape(ok_text)}</td>'
            f'<td>{html.escape(str(row.get("note") or ""))}</td>'
            f'<td>{html.escape(str(row.get("created_at") or ""))}</td>'
            f'<td>{detail_link}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>aweme_id</th><th>标题</th><th>博主</th><th>状态</th><th>备注</th><th>时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    """


def render_batch_retry_bar() -> str:
    return f"""
    <form method="post" action="/api/retry-batch" data-retry-batch>
      <div class="inline-action compact-action">
        <select name="retry_from">
          <option value="auto">智能重试</option>
          <option value="download">从下载开始</option>
          <option value="transcribe">从转录开始</option>
        </select>
        <input type="hidden" name="aweme_ids" value="">
        <button type="submit">批量重试选中</button>
      </div>
    </form>
    """



def render_research_job_table(jobs: list[dict[str, Any]]) -> str:
    if not jobs:
        return '<p class="empty">暂无研究任务。</p>'
    body = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        status = str(job.get("status") or "pending")
        blogger = str(job.get("blogger_name") or "")
        total = str(job.get("total_count") or 0)
        success = str(job.get("success_count") or 0)
        failed = str(job.get("failed_count") or 0)
        skipped = str(job.get("skipped_count") or 0)
        started = str(job.get("started_at") or "")
        finished = str(job.get("finished_at") or "")
        report = str(job.get("report_path") or "")
        body.append(
            '<tr>'
            f'<td><a href="/research/jobs?id={html.escape(job_id)}">{html.escape(job_id)}</a></td>'
            f'<td>{badge(status)}</td>'
            f'<td>{html.escape(blogger)}</td>'
            f'<td>{html.escape(total)}</td>'
            f'<td>{html.escape(success)}</td>'
            f'<td>{html.escape(failed)}</td>'
            f'<td>{html.escape(skipped)}</td>'
            f'<td>{html.escape(started)}</td>'
            f'<td>{html.escape(finished)}</td>'
            f'<td>{html.escape(report)}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>状态</th><th>博主</th><th>总数</th><th>成功</th><th>失败</th><th>跳过</th><th>开始</th><th>结束</th><th>报告</th>
          </tr>
        </thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    """


def render_research_item_table(config: AppConfig, items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty">暂无任务条目。</p>'
    rows_html = []
    for row in items:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "")
        status = str(row.get("status") or "pending")
        transcript_status = str(row.get("transcript_status") or "")
        summary_status = str(row.get("summary_status") or "")
        error = str(row.get("error_message") or "")
        updated = str(row.get("updated_at") or row.get("created_at") or "")
        detail = f'<a href="/aweme?id={html.escape(aweme_id)}">详情</a>' if aweme_id else ""
        note_link = file_link(config, Path(str(row.get("summary_path") or "")), "笔记") if row.get("summary_path") else ""
        retry = retryButtons(aweme_id, retry_stage(row), True) if status == "failed" else ""
        rows_html.append(
            '<tr>'
            f'<td>{html.escape(aweme_id)}</td>'
            f'<td>{html.escape(title)}</td>'
            f'<td>{badge(status)}</td>'
            f'<td>{badge(transcript_status) if transcript_status else ""}</td>'
            f'<td>{badge(summary_status) if summary_status else ""}</td>'
            f'<td>{html.escape(error)}</td>'
            f'<td>{html.escape(updated)}</td>'
            f'<td>{detail} {note_link} {retry}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>aweme_id</th><th>标题</th><th>状态</th><th>转录</th><th>AI</th><th>错误</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>
    """


def render_note_table(config: AppConfig, notes: list[dict[str, Any]]) -> str:
    if not notes:
        return '<p class="empty">暂无笔记文件。</p>'

    rows_html = []
    for note in notes:
        path = Path(str(note.get("path"))) if note.get("path") else None
        name = str(note.get("name") or (path.name if path else ""))
        platform = str(note.get("platform") or "")
        blogger_name = str(note.get("blogger") or "")
        size_kb = note.get("size_kb", 0) or 0
        updated_at = str(note.get("updated_at") or "")
        search_text = escape_for_search(name, platform, blogger_name)

        rows_html.append(
            '<tr data-note-search="' + html.escape(search_text) + '" '
            'data-note-platform="' + html.escape(platform) + '" '
            'data-note-blogger="' + html.escape(blogger_name) + '">'
            f'<td>{file_link(config, path, html.escape(name)) if path else html.escape(name)}</td>'
            f'<td>{html.escape(platform)}</td>'
            f'<td>{html.escape(blogger_name)}</td>'
            f'<td>{html.escape(str(size_kb))} KB</td>'
            f'<td>{html.escape(updated_at)}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>文件名</th><th>平台</th><th>博主</th><th>大小</th><th>修改时间</th></tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>
    """


def render_brief_table(config: AppConfig, briefs: list[dict[str, Any]]) -> str:
    if not briefs:
        return '<p class="empty">暂无简报文件。</p>'
    items = []
    for brief in briefs:
        path = Path(str(brief.get("path"))) if brief.get("path") else None
        name = str(brief.get("name") or (path.name if path else "未命名简报"))
        created_at = str(brief.get("created_at") or "")
        item_count = brief.get("item_count", 0) or 0
        status = str(brief.get("status") or "unknown")
        items.append(
            '<li><div>'
            f'<strong>{html.escape(name)}</strong>'
            f'<span>{html.escape(created_at)} · {html.escape(str(item_count))} 条 · {html.escape(status)}</span>'
            f'</div>{file_link(config, path, "阅读") if path else ""}</li>'
        )
    return f'<ul class="doc-list">{"".join(items)}</ul>'


def render_blogger_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">暂无监控来源。</p>'
    body = []
    for row in rows:
        in_config = bool(row.get("in_config"))
        monitor_enabled = bool(row.get("monitor_enabled"))
        nickname = str(row.get("nickname") or "未知")
        sec_uid = str(row.get("sec_uid") or "")
        url = str(row.get("url") or row.get("douyin_url") or "")
        platform = str(row.get("platform") or "douyin")
        category = str(row.get("category") or "未分类")
        item_count = str(row.get("aweme_count") or row.get("item_count") or 0)
        note_count = str(row.get("summary_count") or row.get("note_count") or 0)

        if in_config:
            original_key = str(row.get("sec_uid") or row.get("url") or row.get("nickname") or "")
            actions = f"""
            <details class="source-edit"><summary>管理</summary>
              <form method="post" action="/sources/update" class="mini-form compact-source-form">
                <input type="hidden" name="original_key" value="{html.escape(original_key)}">
                <label>名称</label><input name="name" value="{html.escape(nickname)}">
                <label>分类</label><input name="category" value="{html.escape(category if category != "未分类" else "")}">
                <label>主页链接</label><input name="url" value="{html.escape(url)}">
                <label>sec_uid</label><input name="sec_uid" value="{html.escape(sec_uid)}">
                <label class="check"><input type="checkbox" name="enabled" {checked(monitor_enabled)}> 启用监控</label>
                <div class="form-actions"><button type="submit">保存</button></div>
              </form>
              <form method="post" action="/sources/delete" class="compact-curation" data-curation-form>
                <input type="hidden" name="original_key" value="{html.escape(original_key)}">
                <button type="submit" class="secondary" data-confirm="移出后不再自动检测该博主，已有内容记录保留。确认移出？">移出监控</button>
              </form>
            </details>
            """
        else:
            actions = f"""
            <form method="post" action="/sources/promote" class="compact-curation" data-action-form>
              <input type="hidden" name="name" value="{html.escape(nickname)}">
              <input type="hidden" name="url" value="{html.escape(url)}">
              <input type="hidden" name="sec_uid" value="{html.escape(sec_uid)}">
              <button type="submit" class="secondary">加入监控</button>
            </form>
            """

        status = badge("success") if monitor_enabled else badge("pending") if in_config else badge("cancelled")

        body.append(
            '<tr>'
            f'<td>{html.escape(nickname)}</td>'
            f'<td>{html.escape(platform)}</td>'
            f'<td>{html.escape(category)}</td>'
            f'<td class="mono"><a href="{html.escape(url)}" target="_blank" rel="noreferrer">{html.escape(url[:50])}</a></td>'
            f'<td><code>{html.escape(sec_uid[:16])}</code></td>'
            f'<td>{html.escape(item_count)}</td>'
            f'<td>{html.escape(note_count)}</td>'
            f'<td>{status}</td>'
            f'<td>{actions}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>名称</th><th>平台</th><th>分类</th><th>主页</th><th>sec_uid</th><th>作品数</th><th>笔记数</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>{"".join(body)}</tbody>
      </table>
    </div>
    """


def render_note_filters(notes: list[dict[str, Any]]) -> str:
    platforms = sorted({str(n.get("platform") or "") for n in notes if n.get("platform")})
    bloggers = sorted({str(n.get("blogger") or "") for n in notes if n.get("blogger")})
    return f"""
    <div class="filters">
      <input id="note-search" placeholder="搜索笔记...">
      <select id="note-platform"><option value="">全部平台</option>{"".join(f'<option value="{html.escape(p)}">{html.escape(p)}</option>' for p in platforms)}</select>
      <select id="note-blogger"><option value="">全部博主</option>{"".join(f'<option value="{html.escape(b)}">{html.escape(b)}</option>' for b in bloggers)}</select>
    </div>"""


def render_log_table(lines: list[dict[str, Any]]) -> str:
    if not lines:
        return '<p class="empty">暂无日志。</p>'
    rows = []
    for entry in lines:
        timestamp = str(entry.get("timestamp") or "")
        level = str(entry.get("level") or "")
        component = str(entry.get("component") or "")
        message = str(entry.get("message") or entry.get("line") or "")
        search_text = escape_for_search(timestamp, level, component, message)
        level_badge = badge(level) if level in {"info", "warning", "error"} else ""
        rows.append(
            '<tr data-log-search="' + html.escape(search_text) + '" '
            'data-log-level="' + html.escape(level) + '" '
            'data-log-component="' + html.escape(component) + '">'
            f'<td class="mono">{html.escape(timestamp)}</td>'
            f'<td>{level_badge}</td>'
            f'<td>{html.escape(component)}</td>'
            f'<td>{html.escape(message)}</td>'
            '</tr>'
        )
    return f"""
    <div class="table-wrap log-wrap">
      <table>
        <thead>
          <tr><th>时间</th><th>级别</th><th>模块</th><th>消息</th></tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


# ── Config Form ──

def render_config_form(config: AppConfig) -> str:
    raw = config.raw
    app = config.get("app", {}) or {}
    output = config.get("output", {}) or {}
    schedule = config.get("schedule", {}) or {}
    download = config.get("download", {}) or {}
    organizer = config.get("ai.organizer", {}) or {}
    providers = organizer_providers_for_form(organizer)
    whisper = config.get("ai.whisper", {}) or {}
    notification_root = config.get("notification", {}) or {}
    notification = config.get("notification.channels.feishu", {}) or {}
    bloggers_yaml = yaml.safe_dump(raw.get("bloggers", []), allow_unicode=True, sort_keys=False)
    cookie_status = config.cookies
    return f"""
    <form method="post" action="/config" class="config-grid">
      <fieldset>
        <legend>基础配置</legend>
        <label>系统名称</label>
        <input name="app_name" value="{html.escape(str(app.get('name', 'KenRadar')))}">
        <label>详情页访问地址</label>
        <input name="web_base_url" value="{html.escape(str(app.get('web_base_url', 'http://172.30.10.150:8765')))}">
        <label>访问密码</label>
        <input name="web_password" type="password" placeholder="{secret_placeholder(app.get('web_password'))}">
        <label>运行数据目录</label>
        <input name="data_dir" value="{html.escape(str(app.get('data_dir', './data')))}">
        <label>数据库路径</label>
        <input name="database_path" value="{html.escape(str(app.get('database_path', './data/kenradar.db')))}">
        <label>Obsidian 根目录</label>
        <input name="obsidian_root" value="{html.escape(str(output.get('obsidian_root', './data')))}">
      </fieldset>

      <fieldset>
        <legend>关注来源</legend>
        <p class="muted">关注博主已统一到"来源管理"维护，避免配置页和来源页两个入口互相覆盖。</p>
        <div class="form-actions"><a class="button secondary" href="/sources">去来源管理</a></div>
        <details class="error-detail">
          <summary>查看当前关注列表 YAML</summary>
          <pre>{html.escape(bloggers_yaml)}</pre>
        </details>
      </fieldset>

      <fieldset>
        <legend>任务调度</legend>
        <label>每日运行时间，逗号分隔</label>
        <input name="schedule_times" value="{html.escape(', '.join(config.get('schedule.times', []) or []))}">
        <label>每次最多处理视频数量</label>
        <input name="max_items_per_run" type="number" min="0" value="{html.escape(str(schedule.get('max_items_per_run', 0)))}">
        <label>单个博主最多抓取数量</label>
        <input name="max_items_per_blogger" type="number" min="0" value="{html.escape(str(schedule.get('max_items_per_blogger', 0)))}">
        <label>失败重试次数</label>
        <input name="retry_times" type="number" min="0" value="{html.escape(str(schedule.get('retry_times', 2)))}">
        <label>重试间隔（秒）</label>
        <input name="retry_interval_seconds" type="number" min="0" value="{html.escape(str(schedule.get('retry_interval_seconds', 300)))}">
        <label class="check"><input type="checkbox" name="schedule_enabled" {checked(config.get('schedule.enabled', True))}> 启用调度</label>
        <label class="check"><input type="checkbox" name="manual_trigger_enabled" {checked(schedule.get('manual_trigger_enabled', True))}> 允许手动触发</label>
      </fieldset>

      <fieldset>
        <legend>平台配置</legend>
        {platform_toggle('douyin', '抖音', raw)}
        {platform_toggle('bilibili', 'B站', raw)}
        {platform_toggle('xiaohongshu', '小红书', raw)}
        {platform_toggle('youtube', 'YouTube', raw)}
      </fieldset>

      <fieldset>
        <legend>Whisper</legend>
        <label class="check"><input type="checkbox" name="whisper_enabled" {checked(whisper.get('enabled', True))}> 启用 Whisper</label>
        <label>模型</label>
        <input name="whisper_model" value="{html.escape(str(whisper.get('model', 'large-v3-turbo')))}">
        <label>设备</label>
        <select name="whisper_device">
          {option('cuda', whisper.get('device', 'cuda'))}
          {option('cpu', whisper.get('device', 'cuda'))}
        </select>
        <label>语言</label>
        <input name="whisper_language" value="{html.escape(str(whisper.get('language', 'zh')))}">
        <label class="check"><input type="checkbox" name="whisper_save_json" {checked(whisper.get('save_json', True))}> 保存 json 结果</label>
        <label class="check"><input type="checkbox" name="whisper_save_txt" {checked(whisper.get('save_txt', True))}> 保存 txt 结果</label>
        <label class="check"><input type="checkbox" name="whisper_retry_failed" {checked(whisper.get('retry_failed', True))}> 转录失败允许重试</label>
        <label class="check"><input type="checkbox" name="cleanup_video" {checked(whisper.get('cleanup_video', True))}> 处理完成后清理下载临时文件</label>
      </fieldset>

      <fieldset>
        <legend>AI 整理</legend>
        <label class="check"><input type="checkbox" name="organizer_enabled" {checked(organizer.get('enabled', True))}> 启用 AI 整理</label>
        {render_ai_provider_fields(providers)}
        <label>Temperature</label>
        <input name="organizer_temperature" type="number" step="0.1" min="0" max="2" value="{html.escape(str(organizer.get('temperature', 1.0)))}">
        <label>Top P</label>
        <input name="organizer_top_p" type="number" step="0.01" min="0" max="1" value="{html.escape(str(organizer.get('top_p', 0.95)))}">
        <label>Top K</label>
        <input name="organizer_top_k" type="number" step="1" min="0" value="{html.escape(str(organizer.get('top_k', 40)))}">
        <label>最大输出 tokens</label>
        <input name="organizer_max_tokens" type="number" min="128" max="8192" value="{html.escape(str(organizer.get('max_tokens', 2048)))}">
        <label>超时（秒）</label>
        <input name="organizer_timeout" type="number" min="5" value="{html.escape(str(organizer.get('timeout', 60)))}">
        <label>请求硬超时（秒）</label>
        <input name="organizer_request_timeout" type="number" min="5" value="{html.escape(str(organizer.get('request_timeout', organizer.get('timeout', 120))))}">
        <label>AI 最大并发</label>
        <input name="organizer_max_concurrent" type="number" min="1" max="8" value="{html.escape(str(organizer.get('max_concurrent', 1)))}">
        <label>AI RPM 限流（0 不限）</label>
        <input name="organizer_rpm_limit" type="number" min="0" value="{html.escape(str(organizer.get('rpm_limit', 40)))}">
        <label class="check"><input type="checkbox" name="organizer_fallback_note" {checked(organizer.get('fallback_note', True))}> AI 失败时生成降级笔记</label>
      </fieldset>

      <fieldset>
        <legend>下载</legend>
        <label>下载目录</label>
        <input name="download_path" value="{html.escape(str(download.get('path', './data/Downloaded/')))}">
        <label>并发下载数</label>
        <input name="download_max_workers" type="number" min="1" max="10" value="{html.escape(str(download.get('max_workers', 5)))}">
        <label>研究模式下载批次大小</label>
        <input name="download_batch_size" type="number" min="1" max="50" value="{html.escape(str(download.get('batch_size', 6)))}">
        <label>批次入队冷却（秒）</label>
        <input name="download_batch_cooldown" type="number" min="0" step="0.5" value="{html.escape(str(download.get('batch_cooldown', 3)))}">
        <label>最大视频时长（秒，0 不限制）</label>
        <input name="max_duration_seconds" type="number" min="0" value="{html.escape(str(download.get('max_duration_seconds', 0)))}">
        <label class="check"><input type="checkbox" name="download_retry_failed" {checked(download.get('retry_failed', True))}> 下载失败后降速重试一次</label>
        <label>连续失败熔断阈值</label>
        <input name="download_circuit_breaker_failures" type="number" min="1" max="20" value="{html.escape(str(download.get('circuit_breaker_failures', 3)))}">
        <label>熔断暂停（秒）</label>
        <input name="download_circuit_breaker_cooldown" type="number" min="0" step="1" value="{html.escape(str(download.get('circuit_breaker_cooldown', 30)))}">
        <label class="check"><input type="checkbox" name="save_json" {checked(config.get('download.save_json', True))}> 保存作品 JSON</label>
        <label class="check"><input type="checkbox" name="cleanup_video" {checked(whisper.get('cleanup_video', True))}> 自动清理下载临时文件</label>
      </fieldset>

      <fieldset>
        <legend>飞书</legend>
        <label class="check"><input type="checkbox" name="notification_enabled" {checked(config.get('notification.enabled', True))}> 启用飞书推送</label>
        <label>推送模式</label>
        <select name="feishu_message_type">
          {option('auto', notification.get('message_type', 'auto'))}
          {option('card', notification.get('message_type', 'auto'))}
          {option('text', notification.get('message_type', 'auto'))}
        </select>
        <label>飞书 Webhook</label>
        <input name="feishu_webhook" type="password" placeholder="{secret_placeholder(notification.get('webhook_url'))}">
        <label>Card 单次最大展示条数</label>
        <input name="feishu_card_max_items" type="number" min="1" max="10" value="{html.escape(str(notification.get('card_max_items', 5)))}">
        <label class="check"><input type="checkbox" name="feishu_fallback_enabled" {checked(notification.get('fallback_enabled', True))}> 发送失败时启用 text fallback</label>
        <label class="check"><input type="checkbox" name="alerts_enabled" {checked((notification_root.get('alerts') or {}).get('enabled', True))}> 失败告警推送</label>
      </fieldset>

      <fieldset>
        <legend>Cookie 状态</legend>
        <div class="cookie-grid">
          {"".join(f'<span>{html.escape(name)}</span><strong>{status_badge(bool(value))}</strong>' for name, value in cookie_status.items())}
        </div>
      </fieldset>

      <div class="form-actions">
        <button type="submit">保存配置</button>
      </div>
    </form>
    """


# ── Research Helpers ──

def render_research_progress(job: dict[str, Any]) -> str:
    total = int(job.get("total_count") or 0)
    success = int(job.get("success_count") or 0)
    failed = int(job.get("failed_count") or 0)
    skipped = int(job.get("skipped_count") or 0)
    done = success + failed + skipped
    percent = round(done / total * 100) if total > 0 else 0
    status = str(job.get("status") or "pending")
    last_error = str(job.get("last_error") or "").strip()
    error_html = (
        f'<div class="alert-inline"><strong>故障原因</strong><span>{html.escape(last_error)}</span><a href="/logs/alerts">查看系统告警</a></div>'
        if last_error and status in {"failed", "partial_failed", "transcribe_only_partial_failed", "transcribe_only_failed"}
        else ""
    )
    return f"""
    <div class="progress-row">
      <div class="progress"><span style="width:{percent}%"></span></div>
      <strong>{done}/{total} · {percent}% · {html.escape(_research_status_label(status))}</strong>
      <span class="muted">成功 {success} · 失败 {failed} · 跳过 {skipped} · 待处理 {max(0, total - done)}</span>
    </div>{error_html}"""


def render_current_research_item(job: dict[str, Any]) -> str:
    title = str(job.get("current_title") or job.get("current_aweme_id") or "")
    status = str(job.get("current_item_status") or "")
    if not title and not status:
        return ""
    aweme_id = str(job.get("current_aweme_id") or "")
    job_name = str(job.get("blogger_name") or job.get("creator_name") or "")
    status_label = "Ollama 整理中" if status == "summarizing" and "Ollama" in job_name else status
    link = f'<a href="/aweme?id={html.escape(aweme_id)}">查看内容</a>' if aweme_id else ""
    return f"""
    <div class="current-task">
      <span>当前处理</span>
      <strong>{html.escape(status_label or '等待中')}</strong>
      <p>{html.escape(title or '暂无当前条目')}</p>
      <div class="muted mono">{html.escape(aweme_id)} {html.escape(str(job.get('current_updated_at') or ''))} {link}</div>
    </div>"""


def render_research_pipeline(pipeline: dict[str, Any]) -> str:
    counts = pipeline.get("counts") or {}
    status_counts = pipeline.get("status_counts") or {}
    samples = pipeline.get("samples") or {}
    status_text_map = {
        "pending": "待处理", "running": "准备处理", "downloading": "下载中",
        "downloaded": "等待转录", "transcribing": "FunASR / Qwen-ASR / Whisper 转录中", "summarizing": "AI 整理中",
        "noting": "写笔记", "success": "完成", "failed": "失败",
        "transcribed_waiting_summary": "等待 AI 总结", "skipped": "已跳过", "cancelled": "已取消",
    }
    status_bits = []
    for key, label in status_text_map.items():
        value = int(status_counts.get(key) or 0)
        if value:
            status_bits.append(f"<span>{html.escape(label)} {value}</span>")
    status_distribution = (
        f'<div class="pipeline-distribution">{"".join(status_bits)}</div>'
        if status_bits
        else '<p class="muted">暂无条目状态分布。</p>'
    )
    cols = [
        ("download", "下载队列", "待下载/下载中"),
        ("transcript", "转录队列", "FunASR / Qwen-ASR / Whisper"),
        ("ai", "AI 队列", "整理/写笔记"),
    ]
    stats = f"""
    <div class="pipeline-stats">
      <div class="health"><span>下载目录占用</span><strong>{html.escape(str(pipeline.get('download_dir_size') or '0 B'))}</strong></div>
      <div class="health"><span>笔记目录占用</span><strong>{html.escape(str(pipeline.get('notes_dir_size') or '0 B'))}</strong></div>
      <div class="health"><span>已结束条目</span><strong>{int(counts.get('done') or 0) + int(counts.get('failed') or 0)}</strong></div>
      <div class="health"><span>预估剩余</span><strong>{html.escape(str(pipeline.get('eta_text') or '暂无'))}</strong></div>
    </div>{status_distribution}"""
    cards = []
    for key, title, sub in cols:
        rows = (samples.get(key) or [])[:5]
        items = [
            f'<li><span>{html.escape(status_text_map.get(item.get("status", ""), item.get("status", "")))}</span>'
            f'{html.escape(str(item.get("title") or item.get("aweme_id") or "")[:42])}</li>'
            for item in rows
        ]
        if not items:
            items.append('<li><span>空闲</span><em>暂无排队条目</em></li>')
        cards.append(
            f'<div class="pipeline-card"><h3>{html.escape(title)}</h3>'
            f'<p>{html.escape(sub)} · {int(counts.get(key) or 0)}</p>'
            f'<ul>{"".join(items)}</ul></div>'
        )
    return stats + '<div class="pipeline-grid">' + "".join(cards) + "</div>"


def _research_status_label(status: str) -> str:
    return {
        "pending": "等待调度",
        "running": "运行中",
        "completed": "已完成",
        "partial_failed": "部分失败",
        "failed": "调度故障",
        "paused": "已暂停",
        "cancelled": "已取消",
        "transcribe_only_completed": "转录完成",
        "transcribe_only_partial_failed": "转录部分失败",
        "transcribe_only_failed": "转录失败",
    }.get(status, status or "未知")


def render_aweme_progress(progress: dict[str, Any]) -> str:
    if not progress:
        return '<p class="empty">暂无处理状态。</p>'
    percent = max(0, min(100, int(progress.get("percent") or 0)))
    overall = str(progress.get("overall") or "pending")
    model = str(progress.get("model") or "")
    manual_task = progress.get("manual_task") if isinstance(progress.get("manual_task"), dict) else {}
    steps_html = "".join(render_aweme_progress_step(step) for step in progress.get("steps") or [])
    latest_job = progress.get("latest_job") if isinstance(progress.get("latest_job"), dict) else {}
    job_id = latest_job.get("id")
    job_link = f'<a href="/research/jobs?id={html.escape(str(job_id))}">研究任务 #{html.escape(str(job_id))}</a>' if job_id else '<span class="muted">暂无关联研究任务</span>'
    task_line = ""
    if manual_task:
        task_line = f'<p class="muted">后台任务：{html.escape(str(manual_task.get("message") or manual_task.get("status") or ""))}</p>'
    return f"""
    <div class="aweme-progress-summary">
      <div class="progress"><span style="width:{percent}%"></span></div>
      <div><strong>{percent}%</strong>{badge(normalize_status(overall))}</div>
    </div>
    <div class="aweme-progress-steps">{steps_html}</div>
    <div class="aweme-progress-meta">
      {f'<p class="muted">AI 模型：{html.escape(model)}</p>' if model else ''}
      {task_line}
      <p class="muted">更新时间：{html.escape(str(progress.get("updated_at") or "暂无"))}</p>
      <p>{job_link}</p>
    </div>
    """


def render_aweme_progress_step(step: dict[str, Any]) -> str:
    state = normalize_status(step.get("state"))
    label = str(step.get("label") or step.get("key") or "")
    status = str(step.get("status") or state)
    updated_at = str(step.get("updated_at") or "")
    error = str(step.get("error") or "")
    return f"""
    <div class="aweme-progress-step" data-state="{html.escape(state)}">
      <div class="aweme-progress-dot"></div>
      <div>
        <strong>{html.escape(label)}</strong>
        <span>{html.escape(_progress_status_label(state, status, step.get("progress_percent")))}</span>
        {f'<em>{html.escape(updated_at)}</em>' if updated_at else ''}
        {f'<p>{html.escape(error)}</p>' if error else ''}
      </div>
    </div>
    """


def _progress_status_label(state: str, raw_status: str = "", progress_percent: Any = None) -> str:
    if state == "running" and progress_percent is not None:
        return f"进行中 · {int(progress_percent)}%"
    labels = {
        "success": "已完成",
        "failed": "失败",
        "pending": "等待中",
        "running": "进行中",
        "skipped": "已跳过",
        "cancelled": "已取消",
    }
    return labels.get(state, raw_status or state)


def research_auto_refresh(jobs: list[dict[str, Any]]) -> str:
    if any(str(j.get("status") or "") in {"pending", "running"} for j in jobs):
        return '<meta http-equiv="refresh" content="45">'
    return ""


# ── AI Provider Fields ──

def organizer_providers_for_form(organizer: dict[str, Any]) -> list[dict[str, Any]]:
    raw = organizer.get("providers")
    if isinstance(raw, list) and raw:
        providers = [dict(item) for item in raw if isinstance(item, dict)]
    else:
        providers = []
    if not providers:
        providers = [
            {
                "name": "agnes",
                "enabled": True,
                "api_type": "chat_completions",
                "endpoint": "https://apihub.agnes-ai.com/v1",
                "model": "agnes-2.0-flash",
                "api_key": "",
                "env_var": "AGNES_API_KEY",
                "request_timeout": 300,
                "max_tokens": 4096,
                "max_input_chars": 12000,
                "temperature": 0.2,
                "top_p": 0.9,
                "top_k": 0,
                "requires_api_key": True,
                "omit_top_k": True,
                "no_think": False,
                "compact_prompt": True,
                "rpm_limit": 19,
            },
        ]
    return providers[:1]


def render_ai_provider_fields(providers: list[dict[str, Any]]) -> str:
    labels = ["主 AI Provider"]
    blocks: list[str] = []
    for index, provider in enumerate(providers):
        prefix = f"provider_{index}"
        api_type = str(provider.get("api_type") or "chat_completions")
        blocks.append(
            f"""
            <div class="subpanel">
              <h3>{labels[index]}</h3>
              <label class="check"><input type="checkbox" name="{prefix}_enabled" {checked(provider.get('enabled', True))}> 启用</label>
              <label>名称</label>
              <input name="{prefix}_name" value="{html.escape(str(provider.get('name') or 'agnes'))}">
              <label>API 类型</label>
              <select name="{prefix}_api_type">
                <option value="chat_completions" {selected(api_type, "chat_completions")}>chat_completions</option>
                <option value="ollama" {selected(api_type, "ollama")}>ollama</option>
                <option value="openai" {selected(api_type, "openai")}>openai-compatible</option>
              </select>
              <label>Endpoint</label>
              <input name="{prefix}_endpoint" value="{html.escape(str(provider.get('endpoint') or ''))}">
              <label>模型</label>
              <input name="{prefix}_model" value="{html.escape(str(provider.get('model') or ''))}">
              <label>环境变量</label>
              <input name="{prefix}_env_var" value="{html.escape(str(provider.get('env_var') or ''))}">
              <label>超时（秒）</label>
              <input name="{prefix}_request_timeout" type="number" min="5" value="{html.escape(str(provider.get('request_timeout') or 120))}">
            </div>
            """
        )
    return "".join(blocks)


# ── Utility Functions ──

def render_stat_cards(stats: dict[str, Any]) -> str:
    labels = [
        ("bloggers", "博主", "monitor"),
        ("awemes", "作品", "library"),
        ("transcripts", "转录成功", "transcript"),
        ("pending", "待处理", "queue"),
        ("summaries", "内容笔记", "docs"),
    ]
    return "".join(
        f'<div class="stat stat-{kind}"><span>{label}</span><strong data-count>{html.escape(str(stats.get(key, 0)))}</strong></div>'
        for key, label, kind in labels
    )


def render_dashboard_cards(stats: dict[str, Any]) -> str:
    items = [
        ("active_blogger_count", "监控中博主", "monitor"),
        ("today_new_items", "今日新增内容", "library"),
        ("today_downloaded", "今日成功下载", "queue"),
        ("today_transcribed", "今日成功转录", "transcript"),
        ("today_summarized", "今日 AI 笔记", "docs"),
        ("today_pushed", "今日飞书推送", "push"),
        ("today_failed", "今日失败任务", "failed"),
        ("download_failed", "下载失败", "failed"),
        ("transcript_failed", "转录失败", "failed"),
        ("summary_failed", "AI 失败", "failed"),
        ("last_check_time", "最近检测", "time"),
        ("last_push_time", "最近推送", "time"),
        ("note_count", "内容笔记", "docs"),
    ]
    return "".join(
        f"<a class=\"stat stat-{kind}\" data-category=\"{kind}\" href=\"/operations/retry\"><span>{label}</span><strong data-count>{html.escape(str(stats.get(key) or '暂无'))}</strong></a>" if key.endswith("_failed") else
        f"<div class=\"stat stat-{kind}\" data-category=\"{kind}\"><span>{label}</span><strong data-count>{html.escape(str(stats.get(key) or '暂无'))}</strong></div>"
        for key, label, kind in items
    )


def render_health_cards(health: dict[str, Any]) -> str:
    last_check = str(health["last_check"])
    relative_check = relative_time_text(last_check)
    last_check_text = f"{last_check} · {relative_check}" if relative_check else last_check
    items = [
        ("上次检测", last_check_text),
        ("调度状态", f"{health['schedule']} · {health['next_run']}"),
        ("磁盘剩余", f"{health['disk_free']} · 已用 {health['disk_used_percent']}"),
        ("推送成功", health["push_rate"]),
        ("告警记录", health["alerts"]),
    ]
    return "".join(
        f"<div class=\"health\"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in items
    )


def relative_time_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "暂无":
        return ""
    parsed = None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            pass
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        return ""
    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    seconds = max(0, int((now - parsed).total_seconds()))
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    days = hours // 24
    return f"{days} 天前"


def render_content_sections(data: Any) -> str:
    if isinstance(data, dict):
        sections = data.get("content_sections") or data.get("sections") or []
        if not sections:
            fallback = data.get("brief_summary") or data.get("one_sentence_summary") or data.get("summary")
            sections = [{"title": "内容概要", "content": fallback}] if fallback else []
    elif isinstance(data, list):
        sections = data
    else:
        sections = []

    numerals = ["一", "二", "三", "四", "五"]
    lines = []
    for index, section in enumerate(sections[:5]):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "内容概要")
        content = str(section.get("content") or "")
        lines.append(f"<h3>（{numerals[index]}）{html.escape(title)}</h3><p>{html.escape(content)}</p>")
    return "".join(lines) or '<p class="empty">暂无结构化内容。</p>'


def render_aweme_intelligence(row: dict[str, Any]) -> str:
    metrics = [
        ("重要性", row.get("importance_score")),
        ("新颖性", row.get("novelty_score")),
        ("信息密度", row.get("information_density")),
        ("业务相关", row.get("business_relevance")),
    ]
    metric_html = "".join(
        f'<div class="metric"><span>{html.escape(label)}</span><strong>{format_score(value)}</strong></div>'
        for label, value in metrics
    )
    reason = str(row.get("recommendation_reason") or "")
    return f"""
    <div class="score-panel">
      <strong>{format_score(row.get("value_score"))}</strong>
      <span>价值评分 · {html.escape(action_label(row.get("recommended_action")))}</span>
    </div>
    {render_tags(row.get("tags") or [])}
    <div class="metric-grid">{metric_html}</div>
    {f'<p class="muted">推荐理由：{html.escape(reason)}</p>' if reason else ''}
    """


def render_aweme_side_metrics(row: dict[str, Any]) -> str:
    metrics = [
        ("重要性", row.get("importance_score")),
        ("新颖性", row.get("novelty_score")),
        ("信息密度", row.get("information_density")),
        ("业务相关", row.get("business_relevance")),
    ]
    reason = str(row.get("recommendation_reason") or "")
    metric_html = "".join(
        f'<div><span>{html.escape(label)}</span><strong>{format_score(value)}</strong></div>'
        for label, value in metrics
    )
    return f"""
    <div class="side-metrics">
      {metric_html}
    </div>
    {f'<p class="side-reason">{html.escape(reason)}</p>' if reason else ''}
    """


def render_tags(tags: Any) -> str:
    if not tags:
        return ""
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        return ""
    return '<div class="tag-row">' + "".join(
        f'<span>{html.escape(str(tag))}</span>' for tag in tags[:15]
    ) + '</div>'


def render_alert_list(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return '<p class="empty">暂无告警。</p>'
    items = []
    for alert in alerts:
        aweme_id = str(alert.get("aweme_id") or "")
        detail = f'<a href="/aweme?id={html.escape(aweme_id)}">详情</a>' if aweme_id else ""
        notified = "已通知" if alert.get("notified") else "未通知"
        items.append(
            "<tr>"
            f"<td>{badge(str(alert.get('level') or 'error'))}</td>"
            f"<td>{html.escape(str(alert.get('component') or ''))}</td>"
            f"<td>{html.escape(str(alert.get('title') or ''))}<div class=\"muted mono\">{html.escape(aweme_id)}</div></td>"
            f"<td>{html.escape(str(alert.get('message') or ''))}</td>"
            f"<td>{html.escape(str(alert.get('created_at') or ''))}</td>"
            f"<td>{html.escape(notified)} {detail}</td>"
            "</tr>"
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>级别</th><th>模块</th><th>对象</th><th>错误</th><th>时间</th><th>状态</th></tr></thead>
        <tbody>{''.join(items)}</tbody>
      </table>
    </div>
    """


def render_filters(rows: list[dict[str, Any]]) -> str:
    blogger_names = sorted({str(row.get("nickname") or "") for row in rows if row.get("nickname")})
    blogger_options = "".join(
        f'<option value="{html.escape(name)}">{html.escape(name)}</option>'
        for name in blogger_names
    )
    return f"""
    <div class="filters">
      <input id="table-search" placeholder="搜索内容...">
      <select id="blogger-filter"><option value="">全部博主</option>{blogger_options}</select>
      <select id="status-filter"><option value="">全部状态</option><option value="success">成功</option><option value="failed">失败</option><option value="pending">处理中</option></select>
    </div>"""


def render_markdown_like(content: str) -> str:
    return html.escape(content or "")


def file_link(config: AppConfig, path: Path, label: str) -> str:
    path = normalize_project_path(config, path)
    try:
        rel = path.resolve().relative_to(config.root_dir)
        href = f"/file?path={quote(str(rel))}"
    except ValueError:
        href = f"/file?path={quote(str(path))}"
    return f'<a class="button-link" href="{href}">{html.escape(label)}</a>'


def format_score(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        num = float(value)
        return f"{num:.1f}"
    except (ValueError, TypeError):
        return "-"


def format_ts(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def checked(value: Any) -> str:
    return "checked" if bool(value) else ""


def selected(current: Any, value: str) -> str:
    return "selected" if str(current) == str(value) else ""


def option(value: str, current: Any) -> str:
    selected = "selected" if str(value) == str(current) else ""
    return f'<option value="{html.escape(value)}" {selected}>{html.escape(value)}</option>'


def platform_toggle(key: str, label: str, raw: dict[str, Any]) -> str:
    platforms = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else {}
    current = platforms.get(key) if isinstance(platforms.get(key), dict) else {}
    default_enabled = key == "douyin"
    return f'<label class="check"><input type="checkbox" name="platform_{html.escape(key)}_enabled" {checked(current.get("enabled", default_enabled))}> {html.escape(label)} 启用</label>'


def secret_placeholder(value: Any) -> str:
    value = str(value or "").strip()
    if not value:
        return "未配置"
    return f"已配置：{mask_secret(value)}，留空保持"


def mask_secret(value: str) -> str:
    if len(value) <= 10:
        return value[:2] + "****"
    return value[:6] + "****" + value[-4:]


def status_badge(ok: bool) -> str:
    return '<span class="badge success">已配置</span>' if ok else '<span class="badge pending">缺失</span>'


def badge(value: str) -> str:
    return f'<span class="badge {html.escape(normalize_status(value))}">{html.escape(value)}</span>'


def action_label(value: Any) -> str:
    labels = {"push": "推荐推送", "archive": "仅归档", "review": "人工审核"}
    return labels.get(str(value), str(value)) if value else "未指定"


def normalize_status(status: Any) -> str:
    s = str(status or "").strip().lower()
    if s in {"success", "done", "completed", "ok", "transcribe_only_completed"}:
        return "success"
    if s in {"failed", "error", "fail", "partial_failed", "transcribe_only_failed", "transcribe_only_partial_failed"}:
        return "failed"
    if s in {"running", "processing", "downloading", "transcribing", "transcribed_waiting_summary", "summarizing", "noting"}:
        return "running"
    if s in {"pending", "queued", "waiting"}:
        return "pending"
    if s in {"cancelled", "canceled"}:
        return "cancelled"
    if s in {"skipped", "skip"}:
        return "skipped"
    if s:
        return s
    return "pending"


def escape_for_search(*values: str) -> str:
    return " ".join(str(v).lower() for v in values if v)


def retry_stage(row: dict[str, Any]) -> str:
    error = str(row.get("last_error") or row.get("error_message") or row.get("summary_error") or "").lower()
    if row.get("download_status") == "failed" or "download" in error or "下载" in error:
        return "download"
    if row.get("transcript_status") == "failed" or "whisper" in error or "transcript" in error or "转录" in error:
        return "transcribe"
    if row.get("summary_status") == "failed" or "openai" in error or "summary" in error or "ai" in error:
        return "ai"
    return "auto"


def retry_stage_label(row: dict[str, Any]) -> str:
    labels = {"download": "download", "transcribe": "transcript", "ai": "ai", "auto": "unknown"}
    return labels.get(retry_stage(row), "unknown")


def retryButtons(aweme_id: str, stage: str, includeFull: bool = True) -> str:
    if not aweme_id:
        return ""
    encoded = html.escape(aweme_id)
    primary = {
        "download": f'<button type="button" data-post="/api/retry-download?id={encoded}">重试下载</button>',
        "transcribe": f'<button type="button" data-post="/api/retry-transcribe?id={encoded}">重试转录</button>',
        "ai": f'<button type="button" data-post="/api/retry-summary?id={encoded}">重试 AI/笔记</button>',
    }.get(stage, f'<button type="button" data-post="/api/retry-full?id={encoded}">全流程重试</button>')
    full = f' <button type="button" class="secondary" data-post="/api/retry-full?id={encoded}">全流程重试</button>' if includeFull and stage != "auto" else ""
    return primary + full


# ── Legacy helpers (kept for any remaining references) ──

def main_nav(active: str = "") -> str:
    return ""


def render_notes_page(config: AppConfig) -> str:
    return render_archive_notes_page(config)


def render_items_page(config: AppConfig) -> str:
    return render_operations_page(config)


def render_pushes_page(config: AppConfig) -> str:
    return render_monitor_pushes_page(config)


def render_research_page(config: AppConfig) -> str:
    return render_archive_research_page(config)


def render_failures_page(config: AppConfig) -> str:
    return render_operations_retry_page(config)


def render_briefs_page(config: AppConfig) -> str:
    return render_archive_briefs_page(config)


# ── Obsidian Markdown Renderer ──


def render_obsidian_note(text: str) -> str:
    if not text.strip():
        return '<p class="empty">暂无笔记内容。</p>'

    lines = text.split("\n")
    out: list[str] = []
    i = 0

    # YAML frontmatter
    frontmatter_lines: list[str] = []
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            frontmatter_lines.append(lines[i])
            i += 1
        i += 1
        if frontmatter_lines:
            fm_html = "".join(
                f"<tr><th>{html.escape(k.strip())}</th><td>{html.escape(v.strip())}</td></tr>"
                for k, v in (_parse_frontmatter_line(l) for l in frontmatter_lines)
                if k
            )
            if fm_html:
                out.append(
                    '<details class="note-frontmatter"><summary>笔记元数据</summary>'
                    f'<table class="compact-meta" style="min-width:0;"><tbody>{fm_html}</tbody></table></details>'
                )

    in_callout = False
    callout_type = ""
    callout_lines: list[str] = []
    in_list = False
    para: list[str] = []

    def flush_para():
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    def flush_callout():
        nonlocal in_callout
        if callout_lines:
            inner = "".join(
                _callout_line_html(l) for l in callout_lines
            )
            out.append(f'<div class="callout callout-{html.escape(callout_type)}">{inner}</div>')
        in_callout = False
        callout_lines.clear()

    def flush_list():
        nonlocal in_list
        in_list = False

    while i < len(lines):
        line = lines[i]
        i += 1
        trimmed = line.strip()

        # Skip empty lines
        if not trimmed:
            flush_para()
            if in_callout:
                callout_lines.append("")
            continue

        # Callout > [!type]
        if trimmed.startswith("> [!"):
            flush_para()
            callout_type = trimmed[4:].rstrip("]").strip().lower()
            in_callout = True
            continue
        if in_callout and trimmed.startswith(">"):
            content = trimmed[1:].strip() if len(trimmed) > 1 else ""
            if content:
                callout_lines.append(content)
            continue
        if in_callout:
            flush_callout()

        # Heading
        if trimmed.startswith("## "):
            flush_para()
            text_content = trimmed[3:].strip()
            is_transcript = "视频原稿" in text_content
            if is_transcript:
                out.append(
                    f'<details class="transcript-fold" style="margin-top:16px;"><summary>{html.escape(text_content)}</summary>'
                )
            else:
                out.append(f"<h2>{html.escape(text_content)}</h2>")
            continue
        if trimmed.startswith("### "):
            flush_para()
            out.append(f"<h3>{html.escape(trimmed[4:])}</h3>")
            continue

        # Wikilinks in paragraph text
        rendered = _render_wikilinks(trimmed)

        # List items
        if trimmed.startswith("- ") or trimmed.startswith("* "):
            flush_para()
            item_text = _render_inline(trimmed[2:])
            out.append(f"<li>{item_text}</li>")
            continue

        # Code block
        if trimmed.startswith("```"):
            flush_para()
            code_lines: list[str] = []
            while i < len(lines):
                cl = lines[i]
                i += 1
                if cl.strip().startswith("```"):
                    break
                code_lines.append(cl)
            out.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue

        # Horizontal rule
        if trimmed.startswith("---") or trimmed.startswith("***"):
            flush_para()
            out.append("<hr>")
            continue

        # Regular paragraph
        para.append(_render_inline(trimmed))

    flush_para()
    flush_callout()

    return "".join(out)


def _parse_frontmatter_line(line: str) -> tuple[str, str]:
    if ":" not in line:
        return ("", "")
    key, _, value = line.partition(":")
    return key.strip(), value.strip().strip("\"'")


def _render_wikilinks(text: str) -> str:
    return re.sub(r"\[\[([^\]]+)\]\]", r'<a class="wiki-link">\1</a>', html.escape(text))


def _callout_line_html(line: str) -> str:
    content = line[1:].strip() if len(line) > 1 else ""
    return "<p>" + html.escape(content) + "</p>"


def _render_inline(text: str) -> str:
    result = html.escape(text)
    result = re.sub(r"\[\[([^\]]+)\]\]", r'<a class="wiki-link">\1</a>', result)
    result = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", result)
    result = re.sub(r"`([^`]+)`", r"<code>\1</code>", result)
    return result
