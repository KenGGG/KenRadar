from __future__ import annotations

WEB_CSS = """
/* ── Light Theme (default) ── */
:root {
  --bg-primary: #F8FAFC;
  --bg-card: #FFFFFF;
  --bg-subtle: #F1F5F9;
  --bg-muted: #F9FAFB;
  --border: rgba(0,0,0,0.07);
  --border-strong: rgba(0,0,0,0.13);
  --border-focus: rgba(37,99,235,0.35);
  --text-primary: #1E293B;
  --text-secondary: #64748B;
  --text-muted: #94A3B8;
  --accent: #2563EB;
  --accent-hover: #1D4ED8;
  --accent-light: #EFF6FF;
  --accent-glow: rgba(37,99,235,0.12);
  --status-ok: #059669;
  --status-warn: #D97706;
  --status-bad: #DC2626;
  --status-info: #6366F1;
  --duration-fast: 150ms;
  --duration: 220ms;
  --ease: ease-out;
  --radius: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 6px 16px rgba(0,0,0,0.04);
  --shadow-soft: 0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03);
  --sidebar-width: 232px;
  --sidebar-collapsed: 60px;
  color-scheme: light;
}

/* ── Dark Theme ── */
[data-theme="dark"], @media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg-primary: #0B1120;
    --bg-card: #111827;
    --bg-subtle: #172033;
    --bg-muted: #0F172A;
    --border: rgba(148,163,184,0.10);
    --border-strong: rgba(148,163,184,0.18);
    --border-focus: rgba(56,189,248,0.45);
    --text-primary: #F1F5F9;
    --text-secondary: #94A3B8;
    --text-muted: #64748B;
    --accent: #38BDF8;
    --accent-hover: #7DD3FC;
    --accent-light: rgba(56,189,248,0.10);
    --accent-glow: rgba(56,189,248,0.14);
    --status-ok: #34D399;
    --status-warn: #FBBF24;
    --status-bad: #FB7185;
    --status-info: #A78BFA;
    --shadow: 0 18px 50px rgba(0,0,0,.34);
    --shadow-soft: 0 10px 30px rgba(0,0,0,.22);
    color-scheme: dark;
  }
}

[data-theme="dark"] * { color-scheme: dark; }
[data-theme="light"] * { color-scheme: light; }

/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; overflow-x: hidden; }
body {
  margin: 0; min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: Inter, "Noto Sans SC", system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.55;
  overflow-x: hidden;
}

/* ── Shell Layout ── */
.app-shell { display: flex; min-height: 100vh; width: 100%; max-width: 100vw; overflow-x: hidden; }

/* ── Sidebar ── */
.sidebar {
  position: sticky; top: 0; left: 0; z-index: 10;
  width: var(--sidebar-width); min-width: var(--sidebar-width);
  height: 100vh; display: flex; flex-direction: column;
  background: var(--bg-card);
  border-right: 1px solid var(--border);
  box-shadow: var(--shadow-soft);
  transition: width var(--duration) var(--ease);
  overflow: hidden;
}
.sidebar-header {
  display: flex; align-items: center; gap: 10px;
  padding: 18px 16px; border-bottom: 1px solid var(--border);
}
.sidebar-header .logo-dot {
  width: 28px; height: 28px; border-radius: 7px;
  background: linear-gradient(135deg, var(--accent), var(--status-info));
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 14px;
  letter-spacing: -0.5px;
}
.sidebar-header .title {
  font-size: 18px; font-weight: 700; color: var(--text-primary);
  white-space: nowrap; overflow: hidden;
}
.sidebar-header .subtitle {
  font-size: 11px; color: var(--text-secondary); white-space: nowrap;
}
.sidebar-nav {
  flex: 1; overflow-y: auto; padding: 8px;
  display: flex; flex-direction: column; gap: 2px;
}
.sidebar-nav a, .sidebar-nav .nav-section {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 6px;
  color: var(--text-secondary); font-size: 13.5px; font-weight: 500;
  text-decoration: none; white-space: nowrap;
  transition: background var(--duration-fast) var(--ease), color var(--duration-fast) var(--ease);
}
.sidebar-nav a:hover {
  background: var(--bg-subtle); color: var(--text-primary);
}
.sidebar-nav a.active {
  background: var(--accent-light); color: var(--accent); font-weight: 600;
}
.sidebar-nav a svg { width: 18px; height: 18px; stroke-width: 2; flex-shrink: 0; }
.sidebar-nav .nav-spacer { height: 8px; }
.sidebar-nav .nav-label {
  padding: 8px 12px 4px; font-size: 10px; font-weight: 700;
  color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;
}
.sidebar-footer {
  padding: 8px; border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 2px;
}
.sidebar-footer button, .sidebar-footer a {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 8px 12px; border-radius: 6px;
  border: 0; background: transparent;
  color: var(--text-secondary); font: inherit; font-size: 13px; font-weight: 500;
  cursor: pointer; text-decoration: none;
}
.sidebar-footer button:hover, .sidebar-footer a:hover { background: var(--bg-subtle); color: var(--text-primary); }
.sidebar-footer button svg, .sidebar-footer a svg { width: 18px; height: 18px; stroke-width: 2; flex-shrink: 0; }
.sidebar-footer .theme-toggle { display: flex; align-items: center; gap: 10px; }

/* ── Sub-navigation (in-page tabs) ── */
.sub-nav {
  display: flex; gap: 4px; margin-bottom: 16px; padding-bottom: 12px;
  border-bottom: 1px solid var(--border); flex-wrap: wrap;
}
.sub-nav a {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: 6px;
  color: var(--text-secondary); font-size: 13px; font-weight: 500;
  text-decoration: none; transition: all var(--duration-fast) var(--ease);
}
.sub-nav a:hover { background: var(--bg-subtle); color: var(--text-primary); }
.sub-nav a.active { background: var(--accent); color: #fff; font-weight: 600; }
.sub-nav a svg { width: 16px; height: 16px; stroke-width: 2; }

/* ── Main Content ── */
.main-content { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow-x: hidden; }

/* ── Topbar (simplified) ── */
.topbar {
  display: flex; justify-content: space-between; align-items: center;
  gap: 16px; padding: 14px 24px; position: sticky; top: 0; z-index: 5;
  background: rgba(248,250,252,0.82);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
[data-theme="dark"] .topbar, 
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .topbar { background: rgba(11,17,32,0.82); } }
.topbar .page-title { font-size: 18px; font-weight: 700; margin: 0; }
.topbar .quick-actions { display: flex; gap: 8px; align-items: center; }
.topbar .quick-actions button { font-size: 12px; padding: 6px 12px; }
.mobile-menu-btn { display: none; background: none; border: 0; padding: 4px; cursor: pointer; color: var(--text-primary); }

/* ── Layout ── */
.layout { max-width: 1400px; margin: 0 auto; padding: 20px 28px; display: grid; gap: 18px; width: 100%; min-width: 0; overflow-x: hidden; }
.layout.wide { max-width: 1600px; }

/* ── Panels ── */
.panel {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px;
  box-shadow: var(--shadow);
  min-width: 0;
}
.panel:hover { border-color: var(--border-strong); }

/* ── Section Head ── */
.section-head {
  display: flex; justify-content: space-between; gap: 16px;
  align-items: baseline; margin-bottom: 16px;
}
.section-head h2 { margin: 0; font-size: 18px; font-weight: 700; }
.section-head p, .muted { color: var(--text-secondary); font-size: 13px; }

/* ── Stats Grid ── */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.stat {
  position: relative; overflow: hidden;
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 14px; background: var(--bg-subtle);
  border-left: 3px solid var(--accent);
  transition: transform var(--duration) var(--ease), border-color var(--duration) var(--ease), box-shadow var(--duration) var(--ease);
}
.stat[data-category="failed"] { border-left-color: var(--status-bad); }
.stat[data-category="monitor"], .stat[data-category="library"], .stat[data-category="queue"], .stat[data-category="transcript"] { border-left-color: var(--accent); }
.stat[data-category="docs"], .stat[data-category="push"] { border-left-color: var(--status-ok); }
.stat[data-category="time"] { border-left-color: var(--status-info); }
.stat, .stat:hover { color: var(--text-primary); text-decoration: none; }
.stat:hover { transform: translateY(-2px); border-color: var(--border-focus); box-shadow: var(--shadow); }
.stat span { display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 12px; font-weight: 600; }
.stat span::before { content: ""; width: 7px; height: 7px; border-radius: 999px; background: currentColor; opacity: .85; }
.stat strong { display: block; margin-top: 6px; font-size: 24px; font-variant-numeric: tabular-nums; letter-spacing: 0; }

/* ── Health Cards ── */
.health {
  display: inline-grid; min-width: 180px; gap: 4px;
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px; background: var(--bg-subtle);
}
.health span { color: var(--text-secondary); font-size: 12px; }
.health strong { font-size: 15px; }

/* ── Progress ── */
.progress-row { display: grid; gap: 8px; margin: 0 0 16px; }
.progress { height: 8px; min-width: 120px; border-radius: 999px; overflow: hidden; background: var(--bg-subtle); border: 1px solid var(--border); }
.progress.compact { height: 6px; margin-bottom: 5px; }
.progress span { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), var(--status-ok)); transition: width .3s ease; }
.aweme-progress-summary { display: grid; gap: 8px; margin: 0 0 12px; }
.aweme-progress-summary > div:last-child { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.aweme-progress-steps { display: grid; gap: 10px; margin: 10px 0 12px; }
.aweme-progress-step { display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 9px; align-items: start; }
.aweme-progress-dot { width: 10px; height: 10px; border-radius: 999px; margin-top: 5px; background: var(--border-strong); box-shadow: 0 0 0 3px var(--bg-subtle); }
.aweme-progress-step[data-state="success"] .aweme-progress-dot { background: var(--status-ok); }
.aweme-progress-step[data-state="running"] .aweme-progress-dot { background: var(--accent); }
.aweme-progress-step[data-state="failed"] .aweme-progress-dot { background: var(--status-bad); }
.aweme-progress-step strong { display: block; font-size: 13px; }
.aweme-progress-step span, .aweme-progress-step em { display: block; color: var(--text-secondary); font-size: 12px; font-style: normal; line-height: 1.45; }
.aweme-progress-step p { margin: 4px 0 0; color: var(--status-bad); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
.aweme-progress-meta p { margin: 5px 0 0; font-size: 12px; }

/* ── Live / Current Task ── */
.live-hint { margin: 0; color: var(--accent); font-size: 13px; }
.current-task { border: 1px solid var(--accent-glow); border-radius: var(--radius); padding: 14px; margin: 0 0 16px; background: var(--accent-light); }
.current-task span { display: block; color: var(--text-secondary); font-size: 13px; }
.current-task strong { display: block; margin-top: 4px; }
.current-task p { margin: 8px 0; }
.alert-inline { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 10px 0 16px; padding: 10px 12px; border: 1px solid rgba(220,38,38,0.25); border-radius: var(--radius); background: rgba(220,38,38,0.07); color: var(--status-bad); }
.alert-inline span { color: var(--text-primary); overflow-wrap: anywhere; }

/* ── Pipeline ── */
.pipeline-stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0 14px; }
.pipeline-distribution { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }
.pipeline-distribution span { padding: 4px 8px; border: 1px solid var(--border); border-radius: 999px; background: var(--bg-subtle); color: var(--text-secondary); font-size: 12px; }
.pipeline-grid { display: grid; grid-template-columns: repeat(3, minmax(200px, 1fr)); gap: 12px; margin: 0 0 16px; }
.pipeline-card { border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; background: var(--bg-subtle); min-height: 150px; }
.pipeline-card h3 { margin: 0; font-size: 15px; }
.pipeline-card p { margin: 6px 0 10px; color: var(--text-secondary); font-size: 13px; }
.pipeline-card ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.pipeline-card li { border-top: 1px solid var(--border); padding-top: 8px; color: var(--text-primary); }
.pipeline-card li span { display: block; color: var(--text-secondary); font-size: 12px; margin-bottom: 2px; }
.pipeline-card li em { color: var(--text-secondary); font-style: normal; }

/* ── Hero panels ── */
.workspace-hero { border-color: var(--accent-glow); }
.intelligence-hero { border-color: var(--accent-glow); }

/* ── Intel Grid ── */
.intel-grid, .intel-two-col { display: grid; grid-template-columns: 1.2fr .8fr; gap: 14px; }
.intel-grid h3, .intel-two-col h3 { margin: 0 0 10px; font-size: 15px; }
.intel-list, .rank-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.intel-list li, .rank-list li { border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; background: var(--bg-subtle); }
.intel-list a { display: block; font-weight: 700; color: var(--text-primary); }
.intel-list span, .rank-list span { display: block; color: var(--text-secondary); font-size: 13px; margin-top: 4px; }
.intel-list p { margin: 8px 0; }
.rank-list li div:first-child { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 8px; }
.rank-list strong { color: var(--text-primary); }

/* ── Summary ── */
.ops-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 8px 0 14px; }
.ops-summary.monitor-health { grid-template-columns: repeat(5, minmax(150px, 1fr)); align-items: stretch; }
.ops-summary .health { margin: 0; min-width: 0; }

/* ── Section Tabs ── */
.section-tabs { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 14px; }
.section-tabs a {
  display: inline-flex; align-items: center; min-height: 36px;
  border: 1px solid var(--border); border-radius: 6px; padding: 7px 12px;
  background: var(--bg-subtle); color: var(--text-secondary);
  font-weight: 600; font-size: 13px; text-decoration: none;
  transition: all var(--duration-fast) var(--ease);
}
.section-tabs a:hover { border-color: var(--border-focus); color: var(--text-primary); background: var(--accent-light); }
.section-subhead { margin: 18px 0 10px; padding-top: 14px; border-top: 1px solid var(--border); }
.section-subhead h3 { margin: 0; font-size: 15px; }

/* ── Config Grid ── */
.config-grid { display: grid; grid-template-columns: repeat(3, minmax(240px, 1fr)); gap: 16px; }
fieldset {
  position: relative; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 14px 14px; min-width: 0; background: var(--bg-subtle);
}
fieldset::before {
  content: ""; position: absolute; inset: 0 auto auto 0; width: 100%;
  height: 2px; border-radius: 8px 8px 0 0;
  background: linear-gradient(90deg, var(--accent), transparent); opacity: .6;
}
legend { font-weight: 700; padding: 0 6px; color: var(--text-primary); }
label { display: block; margin: 10px 0 6px; font-size: 13px; font-weight: 500; color: var(--text-primary); }
input, select, textarea {
  width: 100%; min-height: 40px; border: 1px solid var(--border-strong);
  border-radius: 6px; padding: 8px 10px; font: inherit;
  color: var(--text-primary); background: var(--bg-card);
  transition: border-color var(--duration-fast) var(--ease), box-shadow var(--duration-fast) var(--ease);
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
textarea { resize: vertical; font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; }

/* ── Form ── */
.check { display: flex; align-items: center; gap: 8px; }
.check input { width: auto; }
.form-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; }
button, .button {
  display: inline-flex; align-items: center; justify-content: center;
  border: 0; border-radius: 6px; padding: 9px 15px;
  background: var(--accent); color: #fff;
  font-weight: 700; font-size: 13px; cursor: pointer;
  transition: transform var(--duration-fast) var(--ease), filter var(--duration-fast) var(--ease), background var(--duration-fast) var(--ease);
  touch-action: manipulation;
}
button:hover, .button:hover { filter: brightness(1.05); }
button:active, .button:active { transform: scale(.98); }
button.secondary, .button.secondary {
  background: var(--bg-subtle); color: var(--text-primary);
  border: 1px solid var(--border-strong);
}
button.secondary:hover, .button.secondary:hover { border-color: var(--border-focus); background: var(--accent-light); }
button.copy-btn { padding: 6px 10px; font-size: 12px; background: var(--bg-subtle); color: var(--text-primary); border: 1px solid var(--border); }
button:disabled { opacity: .55; cursor: wait; }

/* ── Inline Actions ── */
.inline-action { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.compact-action { margin-top: 8px; gap: 8px; }
.compact-action button { padding: 7px 10px; font-size: 12px; }
.compact-curation { display: inline-flex; margin: 0; }
.compact-curation input { display: none; }
#task-status { color: var(--text-muted); font-size: 13px; }

/* ── Toasts ── */
.toast-stack { position: fixed; top: 18px; right: 18px; z-index: 20; display: grid; gap: 10px; width: min(360px, calc(100vw - 32px)); }
.toast { border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 12px 14px; background: var(--bg-card); box-shadow: var(--shadow); color: var(--text-primary); animation: toast-in .18s ease-out; }
.toast.success { border-color: var(--status-ok); }
.toast.error { border-color: var(--status-bad); }
.toast.fade { opacity: 0; transform: translateY(-6px); transition: opacity .2s ease, transform .2s ease; }
@keyframes toast-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }

/* ── Cookie Grid ── */
.cookie-grid { display: grid; grid-template-columns: 1fr auto; gap: 8px; }

/* ── Filters ── */
.filters { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 12px; margin-bottom: 14px; }

/* ── Tables ── */
.table-wrap { max-height: 70vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; min-width: 900px; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
tbody tr:nth-child(even) { background: var(--bg-muted); }
tbody tr:hover { background: var(--accent-light); }
th { position: sticky; top: 0; z-index: 2; background: var(--bg-subtle); font-size: 12px; font-weight: 700; color: var(--text-secondary); box-shadow: 0 1px 0 var(--border); }
.badge { display: inline-flex; align-items: center; gap: 5px; border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 600; background: var(--bg-subtle); }
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
.badge.success, .badge.done { color: var(--status-ok); background: rgba(5,150,105,0.1); }
.badge.failed { color: var(--status-bad); background: rgba(220,38,38,0.1); }
.badge.cancelled { color: var(--text-muted); background: var(--bg-subtle); }
.badge.pending { color: var(--status-warn); background: rgba(217,119,6,0.1); animation: pulse 1.6s infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(217,119,6,.2); } 50% { box-shadow: 0 0 0 6px rgba(217,119,6,0); } }

/* ── Tags ── */
.tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tag-row span { display: inline-flex; align-items: center; min-height: 24px; border: 1px solid var(--accent); border-radius: 999px; padding: 3px 8px; color: var(--accent); background: var(--accent-light); font-size: 11px; font-weight: 700; }

/* ── Aweme Cards ── */
.aweme-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
.aweme-card { display: grid; grid-template-columns: minmax(0, 1fr) 82px; gap: 12px; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; background: var(--bg-subtle); }
.aweme-card:hover { border-color: var(--border-strong); }
.aweme-card-title { display: block; color: var(--text-primary); font-size: 16px; font-weight: 750; line-height: 1.4; }
.aweme-card-main p { margin: 8px 0 0; color: var(--text-secondary); }
.aweme-card-side { display: grid; align-content: start; justify-items: end; gap: 2px; text-align: right; }
.aweme-card-side strong { font-size: 24px; color: var(--accent); line-height: 1; }
.aweme-card-side span { color: var(--text-secondary); font-size: 12px; }
.aweme-card-side em { margin-top: 6px; color: var(--status-ok); font-size: 12px; font-style: normal; font-weight: 800; }
.aweme-card-meta { grid-column: 1 / -1; color: var(--text-secondary); font-size: 13px; }
.aweme-card .inline-action { grid-column: 1 / -1; }

/* ── Doc List ── */
.doc-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.doc-list li { display: flex; justify-content: space-between; gap: 12px; border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; background: var(--bg-subtle); }
.doc-list span { display: block; margin-top: 4px; color: var(--text-secondary); font-size: 13px; }

/* ── Forms ── */
.mini-form { display: grid; grid-template-columns: repeat(2, minmax(200px, 1fr)); gap: 12px; }
.mini-form .form-actions { grid-column: 1 / -1; }
.subpanel { grid-column: 1 / -1; border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; background: var(--bg-subtle); }
.subpanel h3 { margin: 0 0 6px; font-size: 15px; }
.source-edit { margin-top: 8px; }
.source-edit summary { color: var(--accent); font-weight: 700; }
.compact-source-form { grid-template-columns: 1fr; margin-top: 10px; min-width: min(420px, 70vw); }

/* ── Timeline ── */
.timeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 20px; margin-bottom: 16px; }
.compact-timeline { grid-template-columns: 1fr; gap: 8px; }
.compact-timeline .step::after { display: none; }
.step { position: relative; border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; background: var(--bg-subtle); }
.step::after { content: "→"; position: absolute; right: -16px; top: 50%; transform: translateY(-50%); color: var(--text-muted); font-weight: 700; }
.step:last-child::after { content: ""; }
.step span { display: block; margin-bottom: 8px; color: var(--text-secondary); font-size: 13px; }
.step.step-action { width: 100%; text-align: left; color: var(--text-primary); background: rgba(220,38,38,0.06); border: 1px solid rgba(220,38,38,0.25); }
.step.step-action:hover { background: rgba(220,38,38,0.1); }
.step.step-action em { display: block; margin-top: 8px; color: var(--status-bad); font-size: 12px; font-style: normal; }
.step.failed { animation: status-pulse 1.8s ease-out infinite; }
@keyframes status-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,.14); } 50% { box-shadow: 0 0 0 7px rgba(220,38,38,0); } }
.error-detail summary { cursor: pointer; color: var(--status-bad); }
.error-detail pre { white-space: pre-wrap; max-width: 520px; margin: 10px 0 0; color: var(--text-primary); font: inherit; font-size: 12px; line-height: 1.55; }

/* ── Compact Table ── */
.compact-table th:nth-child(2), .compact-table td:nth-child(2),
.compact-table th:nth-child(8), .compact-table td:nth-child(8) { display: none; }

/* ── Structured Content ── */
.structured { max-width: 980px; line-height: 1.75; }

/* ── Detail Grid ── */
.detail-grid { display: grid; grid-template-columns: minmax(220px, .85fr) minmax(0, 1.5fr) minmax(240px, .9fr); gap: 16px; align-items: start; }
.detail-grid > .panel { height: fit-content; }
.note-detail-layout { display: flex; align-items: flex-start; gap: 14px; width: 100%; min-width: 0; max-width: 100%; overflow-x: hidden; }
.note-reading-panel { flex: 1 1 auto; min-width: 0; max-width: 100%; overflow-x: hidden; }
.note-reading-body { max-width: none; width: 100%; min-width: 0; margin: 0; overflow-wrap: anywhere; word-break: break-word; }
.note-side-panel { flex: 0 0 260px; width: 260px; min-width: 0; display: grid; gap: 12px; position: sticky; top: 92px; align-self: flex-start; }
.note-side-panel .panel { font-size: 13px; }
.note-side-panel .compact-meta { max-height: none; }
.note-side-panel .compact-meta th { width: 64px; white-space: nowrap; }
.note-side-panel .compact-meta td { word-break: break-word; overflow-wrap: anywhere; }
.note-side-panel .tag-row { margin: 12px 0 0; }
.accent-score { font-size: 18px; color: var(--accent); }
.status-mini-row { display: flex; gap: 4px; flex-wrap: wrap; }
.side-score-card { display: grid; gap: 3px; margin: 0 0 12px; padding: 12px; border: 1px solid var(--accent); border-radius: var(--radius); background: var(--accent-light); }
.side-score-card strong { color: var(--accent); font-size: 28px; line-height: 1; font-variant-numeric: tabular-nums; }
.side-score-card span { color: var(--text-secondary); font-size: 12px; line-height: 1.4; }
.side-metrics { display: grid; gap: 8px; margin-top: 12px; }
.side-metrics div { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-subtle); }
.side-metrics span { color: var(--text-secondary); font-size: 12px; }
.side-metrics strong { color: var(--text-primary); font-size: 14px; font-variant-numeric: tabular-nums; }
.side-reason { margin: 12px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.side-actions { display: grid; gap: 8px; }
.side-actions .button, .side-actions button { width: 100%; justify-content: center; text-align: center; }
.more-actions { display: grid; gap: 8px; }
.more-actions summary { cursor: pointer; color: var(--text-secondary); font-size: 12px; font-weight: 700; padding: 2px 0; }
.more-actions summary:hover { color: var(--text-primary); }
.more-actions button { margin-top: 8px; }
.note-transcript-panel { margin-top: 0; }
.note-transcript-panel pre { white-space: pre-wrap; max-height: 50vh; overflow: auto; margin-top: 12px; font-size: 13px; line-height: 1.65; }
.note-reading-body table { max-width: 100%; display: block; overflow-x: auto; }
.note-reading-body img, .note-reading-body video, .note-reading-body iframe { max-width: 100%; height: auto; }
.note-reading-body pre { max-width: 100%; overflow-x: auto; white-space: pre-wrap; }
.note-reading-body code { white-space: pre-wrap; word-break: break-word; }
.compact-meta { max-height: 48vh; }
.compact-meta table { min-width: 0; }
.score-panel { display: grid; gap: 2px; margin-bottom: 12px; border: 1px solid var(--accent); border-radius: var(--radius); padding: 14px; background: var(--accent-light); }
.score-panel strong { font-size: 32px; line-height: 1; }
.score-panel span { color: var(--text-secondary); font-size: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 14px 0; }
.metric { border: 1px solid var(--border); border-radius: 6px; padding: 9px; background: var(--bg-subtle); }
.metric span { display: block; color: var(--text-secondary); font-size: 12px; }
.metric strong { display: block; margin-top: 3px; color: var(--text-primary); }

/* ── Curation ── */
.curation-form { display: grid; gap: 8px; margin-bottom: 16px; }
.transcript-fold summary { font-size: 18px; font-weight: 800; }

/* ── Markdown / Reader ── */
.raw-markdown { max-width: 980px; margin: 0 auto 40px; white-space: pre-wrap; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; overflow: auto; }
.log-wrap { max-height: 78vh; }
.reader-head { max-width: 980px; margin: 0 auto; padding: 24px 24px 8px; }
.reader-head h1 { font-size: 24px; line-height: 1.35; }
.reader-shell { max-width: 1240px; margin: 0 auto; display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 18px; padding: 0 24px 40px; }
.toc { position: sticky; top: 112px; align-self: start; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; background: var(--bg-card); }
.toc a { display: block; padding: 6px 0; color: var(--text-secondary); font-size: 13px; text-decoration: none; }
.toc a:hover { color: var(--text-primary); }
.markdown { max-width: 980px; margin: 0 auto 40px; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; line-height: 1.75; word-break: break-word; }
.markdown h1, .markdown h2, .markdown h3 { line-height: 1.35; margin: 1.25em 0 .5em; }
.markdown pre { overflow: auto; background: var(--bg-subtle); padding: 14px; border-radius: var(--radius); }
.markdown code { background: var(--bg-subtle); border-radius: 4px; padding: 2px 5px; }
.markdown blockquote { margin: 1em 0; padding-left: 14px; border-left: 3px solid var(--accent); color: var(--text-secondary); }

/* ── Mono ── */
.mono { font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; font-variant-numeric: tabular-nums; }
.empty { color: var(--text-muted); }

/* ── Archive Cards ── */
.archive-filters { display:flex; gap:12px; margin-bottom:16px; }
.archive-filters input { flex:2; min-height:38px; }
.archive-filters select { flex:1; min-height:38px; }
.archive-groups { display:grid; gap:12px; }
.blogger-group { border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; background:var(--bg-card); }
.blogger-group-head { display:flex; align-items:center; gap:12px; padding:12px 16px; cursor:pointer; font-size:15px; border-bottom:1px solid var(--border); background:var(--bg-subtle); user-select:none; }
.blogger-group-head::-webkit-details-marker { color:var(--text-muted); }
.blogger-group-head strong { font-size:16px; }
.blogger-group[open] .blogger-group-head { border-bottom-color:var(--border); }
.note-card-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; padding:16px; }
.note-card { border:1px solid var(--border); border-radius:var(--radius); background:var(--bg-card); display:flex; flex-direction:column; transition:box-shadow var(--duration-fast) var(--ease); }
.note-card:hover { box-shadow:var(--shadow); }
.note-card-body { padding:14px 14px 10px; flex:1; }
.note-card-title { display:block; font-weight:700; font-size:15px; line-height:1.4; margin-bottom:4px; color:var(--text-primary); text-decoration:none; }
.note-card-title:hover { color:var(--accent); }
.note-card-meta { color:var(--text-secondary); font-size:12px; margin-bottom:8px; }
.note-card-summary { color:var(--text-secondary); font-size:13px; line-height:1.5; margin:6px 0; }
.note-card-footer { display:flex; justify-content:space-between; align-items:center; margin-top:8px; gap:8px; }
.note-card-status { font-size:11px; display:flex; gap:6px; align-items:center; }
.note-card-actions { display:flex; gap:6px; padding:8px 14px 12px; border-top:1px solid var(--border); }
.note-card-actions .button { flex:1; justify-content:center; }
.note-card-actions.single-action .button { width:100%; }
.note-card-score { font-variant-numeric:tabular-nums; }
.subtle-link { color:var(--text-secondary); text-decoration:none; }
.subtle-link:hover { color:var(--accent); }

/* ── Note Frontmatter ── */
.note-frontmatter { margin-bottom:16px; border:1px solid var(--border); border-radius:var(--radius); }
.note-frontmatter summary { padding:8px 12px; cursor:pointer; color:var(--accent); font-weight:600; font-size:13px; }
.note-frontmatter table { margin:0; border-top:1px solid var(--border); }

/* ── Callout ── */
.callout { margin:16px 0; border:1px solid var(--border); border-radius:var(--radius); padding:14px; background:var(--bg-subtle); }
.callout.callout-summary { border-left:4px solid var(--accent); background:var(--accent-light); }
.callout p { margin:4px 0; color:var(--text-primary); }

/* ── Wiki Links ── */
.wiki-link { color:var(--accent); font-weight:500; border-bottom:1px dashed var(--accent); cursor:default; }

/* ── Structured content ── */
.structured { line-height:1.75; }
.structured h2 { margin:1.2em 0 0.4em; font-size:18px; }
.structured h3 { margin:1em 0 0.3em; font-size:16px; }
.structured p { margin:0.5em 0; color:var(--text-primary); }
.structured li { margin:4px 0; }
.structured pre { overflow:auto; background:var(--bg-subtle); padding:12px; border-radius:var(--radius); font-size:13px; }
.structured code { background:var(--bg-subtle); border-radius:3px; padding:1px 4px; font-size:13px; }
.structured table { max-width: 100%; }
.structured img, .structured video, .structured iframe { max-width: 100%; height: auto; }
.structured hr { border:0; border-top:1px solid var(--border); margin:20px 0; }

/* ── Responsive ── */
@media (max-width: 1200px) { .config-grid { grid-template-columns: repeat(2, minmax(240px, 1fr)); } .layout { padding: 16px 20px; } }
@media (max-width: 980px) {
  .sidebar { width: var(--sidebar-collapsed); min-width: var(--sidebar-collapsed); }
  .sidebar .title, .sidebar .subtitle, .sidebar-nav a span:not(:first-child), .sidebar-nav .nav-label, .sidebar-footer span { display: none; }
  .sidebar-header { justify-content: center; padding: 12px 8px; }
  .sidebar-nav a, .sidebar-footer a, .sidebar-footer button { justify-content: center; padding: 10px; }
  .reader-shell, .pipeline-grid, .ops-summary, .intel-grid, .intel-two-col, .detail-grid { grid-template-columns: 1fr; }
  .note-detail-layout { flex-direction: column; }
  .note-side-panel { position: static; width: 100%; flex-basis: auto; }
  .section-head { display: block; }
  .toc { position: static; }
  .topbar { padding: 12px 16px; }
  .mobile-menu-btn { display: block; }
}
@media (max-width: 768px) {
  body { font-size: 14px; }
  .sidebar { display: none; }
  .sidebar.open { display: flex; position: fixed; width: var(--sidebar-width); min-width: var(--sidebar-width); z-index: 20; }
  .sidebar.open + .main-content::before { content: ""; position: fixed; inset: 0; z-index: 9; background: rgba(0,0,0,0.3); }
  .topbar { padding: 12px 14px; }
  .layout { padding: 14px; }
  .stats, .config-grid, .filters, .mini-form { grid-template-columns: 1fr; }
  table { min-width: 760px; }
  .timeline { grid-template-columns: 1fr; gap: 10px; }
  .step::after { display: none; }
  .mobile-menu-btn { display: block; }
}
@media (max-width: 480px) {
  .layout { padding: 10px; }
  .panel { padding: 14px; }
  .stats { grid-template-columns: 1fr; }
  .topbar .page-title { font-size: 16px; }
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
"""

WEB_SCRIPT = """
const escapeHtml = (value) => value.replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const inlineMd = (value) => escapeHtml(value)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
  .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
function renderMarkdown(raw) {
  const lines = raw.replace(/\\r\\n/g, '\\n').split('\\n');
  const out = [];
  let listOpen = false;
  let para = [];
  const flushPara = () => { if (para.length) { out.push('<p>' + inlineMd(para.join(' ')) + '</p>'); para = []; } };
  const closeList = () => { if (listOpen) { out.push('</ul>'); listOpen = false; } };
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { flushPara(); closeList(); continue; }
    const heading = /^(#{1,4})\\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushPara(); closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${inlineMd(heading[2])}</h${level}>`);
      continue;
    }
    const item = /^[-*]\\s+(.+)$/.exec(trimmed);
    if (item) {
      flushPara();
      if (!listOpen) { out.push('<ul>'); listOpen = true; }
      out.push('<li>' + inlineMd(item[1]) + '</li>');
      continue;
    }
    para.push(trimmed);
  }
  flushPara(); closeList();
  return out.join('\\n');
}
document.querySelectorAll('.markdown').forEach((el) => {
  el.innerHTML = renderMarkdown(el.textContent || '');
});

/* ── Theme Toggle ── */
(function() {
  const stored = localStorage.getItem('kenradar.theme');
  if (stored === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  else if (stored === 'light') document.documentElement.setAttribute('data-theme', 'light');
})();
document.querySelector('.theme-toggle')?.addEventListener('click', () => {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  let next;
  if (current === 'dark') next = 'light';
  else if (current === 'light') next = null;
  else next = prefersDark ? 'light' : 'dark';
  if (next) root.setAttribute('data-theme', next);
  else root.removeAttribute('data-theme');
  localStorage.setItem('kenradar.theme', next || '');
});

/* ── Mobile Sidebar ── */
document.querySelector('.mobile-menu-btn')?.addEventListener('click', () => {
  document.querySelector('.sidebar')?.classList.toggle('open');
});
document.querySelector('.sidebar.open + .main-content')?.addEventListener('click', () => {
  document.querySelector('.sidebar')?.classList.remove('open');
});

/* ── Table Search ── */
const search = document.getElementById('table-search');
const blogger = document.getElementById('blogger-filter');
const status = document.getElementById('status-filter');
function filterRows() {
  const q = (search?.value || '').trim().toLowerCase();
  const b = blogger?.value || '';
  const s = status?.value || '';
  document.querySelectorAll('tbody tr[data-search]').forEach((row) => {
    const ok = (!q || row.dataset.search.includes(q)) && (!b || row.dataset.blogger === b) && (!s || row.dataset.status === s);
    row.style.display = ok ? '' : 'none';
  });
}
[search, blogger, status].forEach((el) => el && el.addEventListener('input', filterRows));

/* ── Animated Counters ── */
document.querySelectorAll('[data-count]').forEach((el) => {
  const target = Number(el.textContent || 0);
  if (!Number.isFinite(target)) return;
  let current = 0;
  const step = Math.max(1, Math.ceil(target / 18));
  const tick = () => {
    current = Math.min(target, current + step);
    el.textContent = current;
    if (current < target) requestAnimationFrame(tick);
  };
  tick();
});

/* ── Toast ── */
function showToast(message, type = 'info') {
  const text = String(message || '').trim();
  if (!text) return;
  let stack = document.querySelector('.toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = text;
  stack.appendChild(toast);
  setTimeout(() => toast.classList.add('fade'), 3600);
  setTimeout(() => toast.remove(), 3900);
}

/* ── API Actions ── */
async function postAction(url, label, form) {
  const statusLabel = document.getElementById('task-status');
  if (statusLabel) statusLabel.textContent = label || '正在提交...';
  showToast(label || '正在提交...', 'info');
  const options = {method:'POST'};
  if (form) {
    options.body = new URLSearchParams(new FormData(form));
    options.headers = {'Content-Type': 'application/x-www-form-urlencoded'};
  }
  const res = await fetch(url, options);
  const data = await res.json();
  if (statusLabel) statusLabel.textContent = data.message || (data.ok ? '已提交' : '失败');
  showToast(data.message || (data.ok ? '已提交' : '失败'), data.ok ? 'success' : 'error');
  return data;
}
document.querySelectorAll('[data-action-form]').forEach((actionForm) => actionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = actionForm.querySelector('button');
  const confirmMsg = button?.dataset?.confirm;
  if (confirmMsg && !confirm(confirmMsg)) return;
  if (button) button.disabled = true;
  try {
    await postAction(actionForm.action || '/api/run-once', '正在启动任务...', actionForm);
  } catch (error) {
    const label = document.getElementById('task-status');
    if (label) label.textContent = String(error);
    showToast(String(error), 'error');
  } finally {
    setTimeout(() => { if (button) button.disabled = false; }, 3000);
  }
}));
document.querySelectorAll('[data-post]').forEach((button) => {
  button.dataset.boundPost = '1';
  button.addEventListener('click', async () => {
    const confirmMsg = button.dataset.confirm;
    if (confirmMsg && !confirm(confirmMsg)) return;
    button.disabled = true;
    try { await postAction(button.dataset.post, '正在执行...'); }
    catch (error) { const label = document.getElementById('task-status'); if (label) label.textContent = String(error); showToast(String(error), 'error'); }
    finally { setTimeout(() => { button.disabled = false; }, 2500); }
  });
});

/* ── Table Density ── */
const tableDensityButton = document.querySelector('[data-table-density]');
const compactTable = document.querySelector('[data-compact-table]');
if (tableDensityButton && compactTable) {
  const key = 'kenradar.items.compact';
  const applyCompact = (enabled) => {
    compactTable.classList.toggle('compact-table', enabled);
    tableDensityButton.textContent = enabled ? '宽松视图' : '紧凑视图';
    localStorage.setItem(key, enabled ? '1' : '0');
  };
  applyCompact(localStorage.getItem(key) === '1');
  tableDensityButton.addEventListener('click', () => applyCompact(!compactTable.classList.contains('compact-table')));
}

/* ── Copy Actions ── */
document.querySelectorAll('[data-copy-path]').forEach((button) => {
  button.addEventListener('click', () => navigator.clipboard?.writeText(button.dataset.copyPath || ''));
});
document.querySelectorAll('[data-copy-text]').forEach((button) => {
  button.addEventListener('click', () => navigator.clipboard?.writeText(button.dataset.copyText || ''));
});
document.querySelector('[data-copy-raw]')?.addEventListener('click', () => {
  const raw = document.querySelector('.raw-markdown')?.textContent || '';
  navigator.clipboard?.writeText(raw);
});
document.querySelector('[data-toggle-raw]')?.addEventListener('click', () => {
  const raw = document.querySelector('.raw-markdown');
  if (raw) raw.hidden = !raw.hidden;
});

/* ── Curation Form ── */
document.querySelectorAll('[data-curation-form]').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const confirmMsg = button?.dataset?.confirm;
    if (confirmMsg && !confirm(confirmMsg)) return;
    if (button) button.disabled = true;
    try { await postAction(form.action || '/api/curation', '正在保存标记...', form); }
    catch (error) { showToast(String(error), 'error'); }
    finally { setTimeout(() => { if (button) button.disabled = false; }, 1200); }
  });
});

/* ── Note Filters ── */
const noteSearch = document.getElementById('note-search');
const notePlatform = document.getElementById('note-platform');
const noteBlogger = document.getElementById('note-blogger');
function filterNotes() {
  const q = (noteSearch?.value || '').trim().toLowerCase();
  const p = notePlatform?.value || '';
  const b = noteBlogger?.value || '';
  document.querySelectorAll('tbody tr[data-note-search]').forEach((row) => {
    const ok = (!q || row.dataset.noteSearch.includes(q)) && (!p || row.dataset.notePlatform === p) && (!b || row.dataset.noteBlogger === b);
    row.style.display = ok ? '' : 'none';
  });
}
[noteSearch, notePlatform, noteBlogger].forEach((el) => el && el.addEventListener('input', filterNotes));

/* ── Log Filters ── */
const logSearch = document.getElementById('log-search');
const logLevel = document.getElementById('log-level');
const logComponent = document.getElementById('log-component');
function filterLogs() {
  const q = (logSearch?.value || '').trim().toLowerCase();
  const level = logLevel?.value || '';
  const component = logComponent?.value || '';
  document.querySelectorAll('tbody tr[data-log-search]').forEach((row) => {
    const ok = (!q || row.dataset.logSearch.includes(q)) && (!level || row.dataset.logLevel === level) && (!component || row.dataset.logComponent === component);
    row.style.display = ok ? '' : 'none';
  });
}
[logSearch, logLevel, logComponent].forEach((el) => el && el.addEventListener('input', filterLogs));

/* ── Archive Filters ── */
function filterArchive() {
  const q = (document.getElementById('archive-search')?.value || '').trim().toLowerCase();
  const blogger = document.getElementById('archive-blogger')?.value || '';
  let visibleCount = 0;
  document.querySelectorAll('.note-card').forEach((card) => {
    const matchesBlogger = !blogger || card.dataset.blogger === blogger;
    const matchesSearch = !q || card.textContent.toLowerCase().includes(q);
    card.style.display = (matchesBlogger && matchesSearch) ? '' : 'none';
    if (matchesBlogger && matchesSearch) visibleCount++;
  });
  document.querySelectorAll('.blogger-group').forEach((group) => {
    const visible = Array.from(group.querySelectorAll('.note-card')).some((card) => card.style.display !== 'none');
    group.style.display = visible ? '' : 'none';
  });
}

/* ── Retry Logic ── */
const retryStage = (row = {}) => {
  const error = String(row.error_message || row.summary_error || '').toLowerCase();
  if (row.download_status === 'failed' || error.includes('download') || error.includes('下载')) return 'download';
  if (row.transcript_status === 'failed' || error.includes('whisper') || error.includes('transcript') || error.includes('转录')) return 'transcribe';
  if (row.summary_status === 'failed' || error.includes('openai') || error.includes('summary') || error.includes('ai')) return 'ai';
  return 'auto';
};
const retryButtons = (id, stage, includeFull = true) => {
  if (!id) return '';
  const encoded = encodeURIComponent(id);
  const primary = stage === 'download'
    ? `<button type="button" data-post="/api/retry-download?id=${encoded}">重试下载</button>`
    : stage === 'transcribe'
      ? `<button type="button" data-post="/api/retry-transcribe?id=${encoded}">重试转录</button>`
      : stage === 'ai'
        ? `<button type="button" data-post="/api/retry-summary?id=${encoded}">重试 AI/笔记</button>`
        : `<button type="button" data-post="/api/retry-full?id=${encoded}">全流程重试</button>`;
  const full = includeFull && stage !== 'auto' ? ` <button type="button" class="secondary" data-post="/api/retry-full?id=${encoded}">全流程重试</button>` : '';
  return primary + full;
};
function bindPostButtons(root = document) {
  root.querySelectorAll('[data-post]:not([data-bound-post])').forEach((button) => {
    button.dataset.boundPost = '1';
    button.addEventListener('click', async () => {
      const confirmMsg = button.dataset.confirm;
      if (confirmMsg && !confirm(confirmMsg)) return;
      button.disabled = true;
      try { await postAction(button.dataset.post, '正在执行...'); }
      catch (error) { const label = document.getElementById('task-status'); if (label) label.textContent = String(error); showToast(String(error), 'error'); }
      finally { setTimeout(() => { button.disabled = false; }, 2500); }
    });
  });
}

/* ── Aweme Progress Polling ── */
const awemeProgressRoot = document.querySelector('[data-aweme-progress]');
if (awemeProgressRoot) {
  const awemeId = awemeProgressRoot.dataset.awemeProgress;
  const statusText = (status) => ({
    pending:'等待中', running:'进行中', downloading:'下载中', downloaded:'下载完成',
    transcribing:'FunASR / Whisper 转录中', transcribed_waiting_summary:'等待 AI 总结', summarizing:'AI 整理中', noting:'写入 Markdown',
    success:'已完成', failed:'失败', skipped:'已跳过', cancelled:'已取消'
  })[status] || status || '';
  const normalizeState = (state) => {
    const value = String(state || '').toLowerCase();
    if (['success', 'done', 'completed', 'ok'].includes(value)) return 'success';
    if (['failed', 'error', 'fail'].includes(value)) return 'failed';
    if (['running', 'processing', 'downloading', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting'].includes(value)) return 'running';
    if (['skipped', 'skip'].includes(value)) return 'skipped';
    if (['cancelled', 'canceled'].includes(value)) return 'cancelled';
    return 'pending';
  };
  const progressBadge = (state) => `<span class="badge ${escapeHtml(normalizeState(state))}">${escapeHtml(normalizeState(state))}</span>`;
  const renderAwemeProgress = (progress) => {
    const percent = Math.max(0, Math.min(100, Number(progress?.percent || 0)));
    const steps = (progress?.steps || []).map((step) => {
      const state = normalizeState(step.state);
      const label = step.label || step.key || '';
      const stateLabel = state === 'running' && step.progress_percent !== null && step.progress_percent !== undefined
        ? `进行中 · ${Number(step.progress_percent)}%`
        : statusText(state);
      const updated = step.updated_at ? `<em>${escapeHtml(step.updated_at)}</em>` : '';
      const error = step.error ? `<p>${escapeHtml(step.error)}</p>` : '';
      return `<div class="aweme-progress-step" data-state="${escapeHtml(state)}"><div class="aweme-progress-dot"></div><div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(stateLabel)}</span>${updated}${error}</div></div>`;
    }).join('');
    const latestJob = progress?.latest_job || {};
    const jobLink = latestJob.id ? `<a href="/research/jobs?id=${encodeURIComponent(latestJob.id)}">研究任务 #${escapeHtml(latestJob.id)}</a>` : '<span class="muted">暂无关联研究任务</span>';
    const manual = progress?.manual_task ? `<p class="muted">后台任务：${escapeHtml(progress.manual_task.message || progress.manual_task.status || '')}</p>` : '';
    const model = progress?.model ? `<p class="muted">AI 模型：${escapeHtml(progress.model)}</p>` : '';
    return `<div class="aweme-progress-summary"><div class="progress"><span style="width:${percent}%"></span></div><div><strong>${percent}%</strong>${progressBadge(progress?.overall || 'pending')}</div></div><div class="aweme-progress-steps">${steps}</div><div class="aweme-progress-meta">${model}${manual}<p class="muted">更新时间：${escapeHtml(progress?.updated_at || '暂无')}</p><p>${jobLink}</p></div>`;
  };
  const tickAwemeProgress = async () => {
    try {
      const res = await fetch(`/api/aweme/progress?id=${encodeURIComponent(awemeId)}`);
      const data = await res.json();
      if (data.ok && data.progress) {
        const target = document.getElementById('aweme-progress');
        if (target) target.innerHTML = renderAwemeProgress(data.progress);
        const shouldPoll = ['running', 'pending'].includes(normalizeState(data.progress.overall)) || data.progress.manual_task;
        if (shouldPoll) setTimeout(tickAwemeProgress, data.progress.manual_task ? 2000 : 5000);
      }
    } catch (error) {
      console.warn('aweme progress polling failed', error);
      setTimeout(tickAwemeProgress, 5000);
    }
  };
  setTimeout(tickAwemeProgress, 1500);
}

/* ── Research Job Polling ── */
const researchRoot = document.querySelector('[data-research-job]');
if (researchRoot) {
  const jobId = researchRoot.dataset.researchJob;
  const statusText = (status) => ({
    pending:'待处理', running:'准备处理', downloading:'下载中', downloaded:'下载完成，等待转录',
    transcribing:'FunASR / Whisper 转录中', transcribed_waiting_summary:'等待 AI 总结', summarizing:'AI 整理中', noting:'写入 Markdown 笔记',
    success:'完成', completed:'已完成', partial_failed:'部分失败', failed:'调度故障', skipped:'已跳过', paused:'已暂停', cancelled:'已取消',
    transcribe_only_completed:'转录完成', transcribe_only_partial_failed:'转录部分失败', transcribe_only_failed:'转录失败'
  })[status] || status || '';
  const badgeClass = (status) => {
    const value = String(status || '').toLowerCase();
    if (['success', 'done', 'completed', 'ok', 'transcribe_only_completed'].includes(value)) return 'success';
    if (['failed', 'error', 'fail', 'partial_failed', 'transcribe_only_failed', 'transcribe_only_partial_failed'].includes(value)) return 'failed';
    if (['running', 'processing', 'downloading', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting'].includes(value)) return 'running';
    if (['cancelled', 'canceled'].includes(value)) return 'cancelled';
    if (['skipped', 'skip'].includes(value)) return 'skipped';
    return 'pending';
  };
  const badgeHtml = (status) => `<span class="badge ${escapeHtml(badgeClass(status))}">${escapeHtml(status || 'pending')}</span>`;
  const renderProgress = (job) => {
    const total = Number(job?.total_count || 0);
    const success = Number(job?.success_count || 0);
    const failed = Number(job?.failed_count || 0);
    const skipped = Number(job?.skipped_count || 0);
    const done = success + failed + skipped;
    const percent = total > 0 ? Math.round(done / total * 100) : 0;
    const status = job?.status || 'pending';
    const lastError = String(job?.last_error || '').trim();
    const error = lastError && ['failed', 'partial_failed', 'transcribe_only_partial_failed', 'transcribe_only_failed'].includes(status)
      ? `<div class="alert-inline"><strong>故障原因</strong><span>${escapeHtml(lastError)}</span><a href="/logs/alerts">查看系统告警</a></div>`
      : '';
    return `<div class="progress-row"><div class="progress"><span style="width:${percent}%"></span></div><strong>${done}/${total} · ${percent}% · ${escapeHtml(statusText(status))}</strong><span class="muted">成功 ${success} · 失败 ${failed} · 跳过 ${skipped} · 待处理 ${Math.max(0, total - done)}</span></div>${error}`;
  };
  const renderCurrent = (job) => {
    const title = job?.current_title || job?.current_aweme_id || '';
    const rawStatus = job?.current_item_status || '';
    const status = rawStatus === 'summarizing' ? 'AI 整理中' : statusText(rawStatus);
    if (!title && !status) return '';
    const id = job?.current_aweme_id || '';
    const link = id ? `<a href="/aweme?id=${encodeURIComponent(id)}">查看内容</a>` : '';
    return `<div class="current-task"><span>当前处理</span><strong>${escapeHtml(status || '等待中')}</strong><p>${escapeHtml(title || '暂无当前条目')}</p><div class="muted mono">${escapeHtml(id)} ${escapeHtml(job?.current_updated_at || '')} ${link}</div></div>`;
  };
  const renderPipeline = (pipeline) => {
    const counts = pipeline?.counts || {};
    const statusCounts = pipeline?.status_counts || {};
    const samples = pipeline?.samples || {};
    const cols = [['download','下载队列','待下载/下载中'], ['transcript','转录队列','FunASR / Whisper'], ['ai','AI 队列','Agnes 主引擎 / Ollama 后备']];
    const statusOrder = ['pending','downloading','downloaded','transcribing','transcribed_waiting_summary','summarizing','noting','success','failed','skipped','cancelled'];
    const distribution = statusOrder
      .filter((key) => Number(statusCounts[key] || 0) > 0)
      .map((key) => `<span>${escapeHtml(statusText(key))} ${Number(statusCounts[key] || 0)}</span>`)
      .join('');
    const stats = `<div class="pipeline-stats"><div class="health"><span>下载目录占用</span><strong>${escapeHtml(pipeline?.download_dir_size || '0 B')}</strong></div><div class="health"><span>笔记目录占用</span><strong>${escapeHtml(pipeline?.notes_dir_size || '0 B')}</strong></div><div class="health"><span>已结束条目</span><strong>${Number(counts.done || 0) + Number(counts.failed || 0)}</strong></div><div class="health"><span>预估剩余</span><strong>${escapeHtml(pipeline?.eta_text || '暂无')}</strong></div></div>${distribution ? `<div class="pipeline-distribution">${distribution}</div>` : '<p class="muted">暂无条目状态分布。</p>'}`;
    const cards = cols.map(([key, title, sub]) => {
      const rows = (samples[key] || []).slice(0, 5).map((item) => `<li><span>${escapeHtml(statusText(item.status))}</span>${escapeHtml((item.title || item.aweme_id || '').slice(0, 42))}</li>`);
      if (!rows.length) rows.push('<li><span>空闲</span><em>暂无排队条目</em></li>');
      return `<div class="pipeline-card"><h3>${title}</h3><p>${sub} · ${Number(counts[key] || 0)}</p><ul>${rows.join('')}</ul></div>`;
    }).join('');
    return stats + `<div class="pipeline-grid">${cards}</div>`;
  };
  const renderItems = (items) => {
    if (!items?.length) return '<p class="empty">暂无任务条目。</p>';
    const rows = items.map((row) => {
      const id = row.aweme_id || '';
      const detail = id ? `<a href="/aweme?id=${encodeURIComponent(id)}">详情</a>` : '';
      const note = row.summary_path ? `<a href="/file?path=${encodeURIComponent(row.summary_path)}">笔记</a>` : '<span class="muted">无笔记</span>';
      const retry = row.status === 'failed' ? retryButtons(id, retryStage(row), true) : '';
      return `<tr><td>${escapeHtml(id)}</td><td>${escapeHtml(row.title || '')}</td><td>${badgeHtml(row.status)} ${escapeHtml(statusText(row.status))}</td><td>${badgeHtml(row.transcript_status || 'pending')}</td><td>${badgeHtml(row.summary_status || 'pending')}</td><td>${escapeHtml(row.error_message || '')}</td><td>${escapeHtml(row.updated_at || row.created_at || '')}</td><td>${detail} ${note} ${retry}</td></tr>`;
    }).join('');
    return `<div class="table-wrap"><table><thead><tr><th>aweme_id</th><th>标题</th><th>任务状态</th><th>转录</th><th>AI</th><th>错误</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  };
  const tickResearch = async () => {
    try {
      const res = await fetch(`/api/research/job?id=${encodeURIComponent(jobId)}`);
      const data = await res.json();
      if (data.job) {
        document.getElementById('research-progress').innerHTML = renderProgress(data.job);
        document.getElementById('research-current').innerHTML = renderCurrent(data.job);
        document.getElementById('research-pipeline').innerHTML = renderPipeline(data.pipeline || {});
        document.getElementById('research-items').innerHTML = renderItems(data.items || []);
        bindPostButtons(document.getElementById('research-items'));
        if (['pending', 'running'].includes(data.job.status || '')) {
          const counts = data.pipeline?.counts || {};
          const delay = (Number(counts.transcript || 0) + Number(counts.ai || 0)) > 0 ? 2000 : 5000;
          setTimeout(tickResearch, delay);
        }
      }
    } catch (error) {
      console.warn('research polling failed', error);
      setTimeout(tickResearch, 5000);
    }
  };
  setTimeout(tickResearch, 3000);
}

/* ── Batch Retry ── */
document.querySelector('[data-retry-check-all]')?.addEventListener('change', (event) => {
  document.querySelectorAll('[data-retry-check]').forEach((box) => box.checked = event.target.checked);
});
document.querySelector('[data-retry-batch]')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const ids = [...document.querySelectorAll('[data-retry-check]:checked')].map((box) => box.value).filter(Boolean);
  form.elements.aweme_ids.value = ids.join(',');
  if (!ids.length) {
    const label = document.getElementById('task-status');
    if (label) label.textContent = '请先选择要重试的内容';
    return;
  }
  const button = form.querySelector('button');
  if (button) button.disabled = true;
  try { await postAction(form.action, '正在提交批量重试...', form); }
  catch (error) { const label = document.getElementById('task-status'); if (label) label.textContent = String(error); showToast(String(error), 'error'); }
  finally { setTimeout(() => { if (button) button.disabled = false; }, 3000); }
});

/* ── Research Form Persistence ── */
const researchForm = document.querySelector('[data-research-form]');
if (researchForm) {
  const key = 'kenradar.research.form';
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    for (const [name, value] of Object.entries(saved)) {
      const field = researchForm.elements[name];
      if (!field || field.type === 'checkbox') continue;
      field.value = value;
    }
    ['force', 'push'].forEach((name) => {
      if (saved[name] !== undefined && researchForm.elements[name]) researchForm.elements[name].checked = Boolean(saved[name]);
    });
  } catch {}
  researchForm.addEventListener('submit', () => {
    const data = {};
    ['blogger_select', 'blogger', 'limit', 'since', 'until'].forEach((name) => data[name] = researchForm.elements[name]?.value || '');
    ['force', 'push'].forEach((name) => data[name] = Boolean(researchForm.elements[name]?.checked));
    localStorage.setItem(key, JSON.stringify(data));
  });
}
"""
