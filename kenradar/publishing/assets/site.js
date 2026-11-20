/* No local API calls. The only data source is the public, generated catalog. */
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const root = new URL(document.body.dataset.root || './', location.href);
  const urlFor = (path) => new URL(path.split('/').map(encodeURIComponent).join('/'), root).href;
  try { const theme = localStorage.getItem('kr-theme'); if (['light','dark'].includes(theme)) document.documentElement.dataset.theme = theme; } catch { /* storage may be disabled */ }
  $('[data-theme]').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme:dark)').matches;
    const theme = dark ? 'light' : 'dark'; document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('kr-theme', theme); } catch { /* optional preference */ }
  });
  $('[data-focus]')?.addEventListener('click', (e) => { const on = document.body.classList.toggle('focus'); e.target.textContent = on ? '退出专注阅读' : '专注阅读'; e.target.setAttribute('aria-pressed', String(on)); });
  let topic = '';
  const cards = $$('[data-card]');
  let limit = 40;
  const more = document.createElement('button');
  more.textContent = '加载更多'; more.hidden = true;
  if ($('.feed')) $('.feed').after(more);
  const apply = () => {
    const query = ($('#feed-query')?.value || '').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const platform = $('#platform')?.value || '';
    let count = 0;
    for (const card of cards) {
      const matches = query.every(q => card.textContent.toLocaleLowerCase().includes(q)) && (!topic || JSON.parse(card.dataset.topics).includes(topic)) && (!platform || platform === card.dataset.platform);
      if (matches) count++;
      card.hidden = !matches || count > limit;
    }
    more.hidden = count <= limit;
    if ($('#feed-status')) $('#feed-status').textContent = count ? `找到 ${count} 篇公开内容` : '没有匹配的内容，请更换关键词或筛选条件。';
  };
  const reset = () => { limit = 40; apply(); };
  more.addEventListener('click', () => { limit += 40; apply(); });
  $('#feed-query')?.addEventListener('input', reset);
  $('#platform')?.addEventListener('change', reset);
  $$('[data-topic]').forEach(button => button.addEventListener('click', () => {
    topic = button.dataset.topic;
    $$('[data-topic]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); reset();
  }));
  $('#sort')?.addEventListener('change', (event) => {
    const sorted = [...cards].sort((a,b) => event.target.value === 'title' ? a.dataset.title.localeCompare(b.dataset.title, 'zh-CN') : b.dataset.date.localeCompare(a.dataset.date));
    sorted.forEach(card => card.parentElement.append(card));
    cards.splice(0, cards.length, ...sorted); reset();
  });
  $('[data-view]')?.addEventListener('click', (event) => { const on = $('.feed').classList.toggle('list'); event.target.setAttribute('aria-pressed', String(on)); event.target.textContent = on ? '切换卡片视图' : '切换列表视图'; });
  if (cards.length) apply();
  let catalog;
  const getCatalog = () => catalog ||= fetch(new URL('content-index.json', root)).then(r => { if (!r.ok) throw Error('catalog'); return r.json(); }).then(data => data.items).catch(error => { catalog = null; throw error; });
  const dialog = $('#search-dialog');
  const results = $('#search-results');
  let previousFocus;
  const showSearch = () => { previousFocus = document.activeElement; if (!dialog.open) dialog.showModal(); $('#global-query').focus(); search(); };
  $$('[data-search]').forEach(button => button.addEventListener('click', showSearch));
  $('[data-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => previousFocus?.focus());
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && dialog.open) { e.preventDefault(); dialog.close(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); showSearch(); }
  });
  let searchRun = 0;
  const hit = (item) => {
    const a = document.createElement('a'); a.className = 'search-hit'; a.href = urlFor(item.relative_url); a.textContent = item.title;
    const small = document.createElement('small'); small.textContent = `${item.creator} · ${item.platform} · ${item.published_at || '发布时间未知'} · ${item.topics.join(' / ')}`; a.append(small); return a;
  };
  async function search() {
    const run = ++searchRun;
    const terms = $('#global-query').value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    results.textContent = '正在读取公开索引…';
    try {
      const items = await getCatalog(); if (run !== searchRun) return;
      const found = items.filter(i => terms.every(t => `${i.title} ${i.creator} ${i.platform} ${i.topics.join(' ')} ${i.summary}`.toLocaleLowerCase().includes(t)));
      results.replaceChildren();
      const status = document.createElement('p'); status.className = 'muted'; status.textContent = `找到 ${found.length} 篇${found.length > 50 ? '，先显示前 50 篇，请缩小关键词范围' : ''}`; results.append(status);
      if (!found.length) { status.textContent = '没有找到匹配的内容，请尝试其他标题、作者或主题。'; return; }
      found.slice(0,50).forEach(i => results.append(hit(i)));
    } catch { if (run === searchRun) results.textContent = '搜索索引暂时无法读取。你仍可通过来源目录浏览全部公开笔记。'; }
  }
  $('#global-query').addEventListener('input', search);
  if ($('#related')) getCatalog().then(items => {
    const section = $('#related'); const topics = JSON.parse(section.dataset.topics);
    const related = items.filter(i => i.relative_url !== section.dataset.current && i.topics.some(t => topics.includes(t))).slice(0,4);
    if (related.length) { const h = document.createElement('h2'); h.textContent = '同主题阅读'; section.append(h); related.forEach(i => section.append(hit(i))); }
  }).catch(() => {});
})();
