"""
Build an interactive HTML dashboard from the managed merchants Excel.
Uses the same data and logic as CSCC.py. Run this script, then open
the generated dashboard.html in your browser.
"""
import csv
import json
import os
from pathlib import Path

INPUT_FILE = "CA managed merchants.xlsx"
OUTPUT_HTML = "dashboard.html"


def main():
    script_dir = Path(__file__).resolve().parent
    os.chdir(script_dir)

    excel_path = INPUT_FILE
    if not os.path.isfile(excel_path):
        print(f"Warning: '{excel_path}' not found. Using merchant_success_command_center.csv if present.")
        rows = _load_from_csv_fallback()
    else:
        from CSCC import read_merchants_from_xlsx, build_rows
        merchant_names, merchant_to_owner, merchant_to_gmv, merchant_to_legal = read_merchants_from_xlsx(excel_path)
        rows = build_rows(merchant_names, merchant_to_owner, merchant_to_gmv, merchant_to_legal)

    try:
        from snowflake_kpis import attach_kpis_to_rows
        rows = attach_kpis_to_rows(rows)
    except Exception as e:
        print(f"Snowflake KPIs skipped: {e}")

    data_json = json.dumps(rows, ensure_ascii=False)
    html = build_html(data_json)
    out_path = script_dir / OUTPUT_HTML
    out_path.write_text(html, encoding="utf-8")
    print(f"Dashboard written: {out_path}")
    print(f"Rows: {len(rows)} — Open {OUTPUT_HTML} in your browser.")


def _load_from_csv_fallback():
    path = "merchant_success_command_center.csv"
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Neither '{INPUT_FILE}' nor '{path}' found. Place the managed merchants Excel in this folder."
        )
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def build_html(data_json: str) -> str:
    # Escape for embedding in HTML script
    data_escaped = data_json.replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Merchant Success Command Center</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0f1216;
      --surface: #1a1f28;
      --surface-hover: #232a36;
      --border: #2d3648;
      --text: #e6edf5;
      --text-muted: #8b9cb3;
      --accent: #5c9ce6;
      --accent-dim: #3d7bc2;
      --critical: #e85d5d;
      --high: #e8a85d;
      --medium: #7bc2a8;
      --low: #8b9cb3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'DM Sans', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }}
    .header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 1.25rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
    }}
    .header h1 {{
      margin: 0;
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .stats {{
      display: flex;
      gap: 1.5rem;
      font-size: 0.875rem;
      color: var(--text-muted);
    }}
    .stats span {{ font-weight: 500; color: var(--text); }}
    .toolbar {{
      padding: 1rem 1.5rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: center;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }}
    .search-wrap {{
      flex: 1;
      min-width: 200px;
    }}
    .search-wrap input {{
      width: 100%;
      padding: 0.5rem 0.75rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--text);
      font-family: inherit;
      font-size: 0.9rem;
    }}
    .search-wrap input::placeholder {{ color: var(--text-muted); }}
    .search-wrap input:focus {{
      outline: none;
      border-color: var(--accent);
    }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
    }}
    .filters label {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-right: 0.25rem;
    }}
    .filters select {{
      padding: 0.45rem 0.6rem;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--bg);
      color: var(--text);
      font-family: inherit;
      font-size: 0.85rem;
    }}
    .table-wrap {{
      overflow-x: auto;
      padding: 1rem 1.5rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    th {{
      text-align: left;
      padding: 0.6rem 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
      cursor: pointer;
      user-select: none;
    }}
    th:hover {{ color: var(--text); }}
    th .sort-icon {{
      opacity: 0.5;
      margin-left: 0.25rem;
    }}
    th.sorted-asc .sort-icon::after {{ content: '↑'; opacity: 1; }}
    th.sorted-desc .sort-icon::after {{ content: '↓'; opacity: 1; }}
    td {{
      padding: 0.55rem 0.75rem;
      border-bottom: 1px solid var(--border);
    }}
    tr:hover td {{ background: var(--surface-hover); }}
    .priority-Critical {{ color: var(--critical); font-weight: 500; }}
    .priority-High {{ color: var(--high); }}
    .priority-Medium {{ color: var(--medium); }}
    .priority-Low {{ color: var(--low); }}
    .leadership-yes {{ color: var(--accent); font-weight: 500; }}
    .empty-state {{
      text-align: center;
      padding: 3rem 1rem;
      color: var(--text-muted);
    }}
    .btn-row {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .btn-action {{
      padding: 0.35rem 0.6rem;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--surface);
      color: var(--accent);
      font-size: 0.75rem;
      font-family: inherit;
      cursor: pointer;
      white-space: nowrap;
    }}
    .btn-action:hover {{ background: var(--surface-hover); border-color: var(--accent); }}
    .btn-action:disabled {{ opacity: 0.6; cursor: not-allowed; }}
    .btn-action.primary {{ background: var(--accent-dim); color: var(--text); border-color: var(--accent); }}
    .modal-backdrop {{
      position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000;
      display: none; align-items: center; justify-content: center; padding: 1rem;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
      max-width: 560px; width: 100%; max-height: 85vh; overflow: hidden; display: flex; flex-direction: column;
    }}
    .modal-header {{
      padding: 1rem 1.25rem; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; justify-content: space-between;
    }}
    .modal-header h2 {{ margin: 0; font-size: 1rem; font-weight: 600; }}
    .modal-close {{ background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1.25rem; line-height: 1; padding: 0.25rem; }}
    .modal-close:hover {{ color: var(--text); }}
    .modal-body {{ padding: 1.25rem; overflow-y: auto; font-size: 0.9rem; }}
    .modal-body.loading {{ color: var(--text-muted); }}
    .email-body {{ white-space: pre-wrap; margin: 0 0 1rem; }}
    .btn-copy {{ padding: 0.4rem 0.75rem; background: var(--accent); color: var(--bg); border: none; border-radius: 6px; font-size: 0.8rem; cursor: pointer; }}
    .btn-copy:hover {{ filter: brightness(1.1); }}
    .news-list {{ list-style: none; margin: 0; padding: 0; }}
    .news-list li {{ margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border); }}
    .news-list li:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: 0; }}
    .news-list a {{ color: var(--accent); text-decoration: none; }}
    .news-list a:hover {{ text-decoration: underline; }}
    .news-list .source {{ font-size: 0.8rem; color: var(--text-muted); margin-top: 0.2rem; }}
    .news-summary {{ margin: 0 0 1rem; padding: 0.75rem; background: var(--bg); border-radius: 8px; font-size: 0.9rem; }}
    .news-summary.markdown-body h3 {{ margin: 1rem 0 0.5rem; font-size: 1rem; color: var(--text); }}
    .news-summary.markdown-body h3:first-child {{ margin-top: 0; }}
    .news-summary.markdown-body ul {{ margin: 0.35rem 0 0.75rem 1.1rem; padding: 0; }}
    .news-summary.markdown-body li {{ margin-bottom: 0.35rem; }}
    .news-summary.markdown-body p {{ margin: 0 0 0.65rem; }}
    .news-summary.markdown-body strong {{ color: var(--text); }}
    .news-source-tag {{ font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.75rem; }}
    .api-error {{ color: var(--critical); }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Merchant Success Command Center</h1>
    <div class="stats">
      <span id="stat-rows">—</span> engagements
      <span id="stat-merchants">—</span> merchants
    </div>
  </div>
  <div class="toolbar">
    <div class="search-wrap">
      <input type="text" id="search" placeholder="Search merchant, vertical, owner, playbook…" autocomplete="off">
    </div>
    <div class="filters">
      <label>Vertical</label>
      <select id="filter-vertical">
        <option value="">All</option>
      </select>
      <label>Tier</label>
      <select id="filter-tier">
        <option value="">All</option>
        <option value="Tier 0">Tier 0</option>
        <option value="Tier 1">Tier 1</option>
        <option value="Tier 2">Tier 2</option>
      </select>
      <label>Priority</label>
      <select id="filter-priority">
        <option value="">All</option>
        <option value="Critical">Critical</option>
        <option value="High">High</option>
        <option value="Medium">Medium</option>
        <option value="Low">Low</option>
      </select>
      <label>Owner</label>
      <select id="filter-owner">
        <option value="">All</option>
      </select>
      <label>Month</label>
      <select id="filter-month">
        <option value="">All</option>
      </select>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th data-key="merchant">Merchant <span class="sort-icon"></span></th>
          <th data-key="vertical">Vertical <span class="sort-icon"></span></th>
          <th data-key="tier">Tier <span class="sort-icon"></span></th>
          <th data-key="peak_months">Peak months <span class="sort-icon"></span></th>
          <th data-key="engagement_month_label">Engagement month <span class="sort-icon"></span></th>
          <th data-key="engagement_type">Engagement type <span class="sort-icon"></span></th>
          <th data-key="priority">Priority <span class="sort-icon"></span></th>
          <th data-key="owner">CSM <span class="sort-icon"></span></th>
          <th data-key="fy26_fc_gmv">FY26 FC GMV <span class="sort-icon"></span></th>
          <th data-key="status">Status <span class="sort-icon"></span></th>
          <th data-key="next_action">Next action <span class="sort-icon"></span></th>
          <th data-key="leadership_flag">Leadership <span class="sort-icon"></span></th>
          <th data-key="playbook">Playbook <span class="sort-icon"></span></th>
          <th data-key="num_applications">Apps <span class="sort-icon"></span></th>
          <th data-key="approval_rate">Approval % <span class="sort-icon"></span></th>
          <th data-key="take_rate">Take rate % <span class="sort-icon"></span></th>
          <th data-key="loans">Loans <span class="sort-icon"></span></th>
          <th data-key="aov">AOV <span class="sort-icon"></span></th>
          <th class="no-sort">Actions</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="empty-state" id="empty-state" style="display:none;">No rows match the current filters.</div>
  </div>
  <div class="modal-backdrop" id="modal-email" role="dialog" aria-label="Generated email">
    <div class="modal">
      <div class="modal-header">
        <h2 id="modal-email-title">Reach-out email</h2>
        <button type="button" class="modal-close" aria-label="Close" id="modal-email-close">&times;</button>
      </div>
      <div class="modal-body" id="modal-email-body"></div>
    </div>
  </div>
  <div class="modal-backdrop" id="modal-news" role="dialog" aria-label="Latest news">
    <div class="modal">
      <div class="modal-header">
        <h2 id="modal-news-title">Latest news</h2>
        <button type="button" class="modal-close" aria-label="Close" id="modal-news-close">&times;</button>
      </div>
      <div class="modal-body" id="modal-news-body"></div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script>
    let RAW = {data_escaped};
    const COLS = ['merchant','vertical','tier','peak_months','engagement_month_label','engagement_type','priority','owner','status','next_action','leadership_flag','playbook'];

    let data = RAW.slice();
    let sortKey = 'engagement_month_sort';
    let sortDir = 1;
    let currentRows = [];

    const tbody = document.getElementById('tbody');
    const emptyState = document.getElementById('empty-state');
    const statRows = document.getElementById('stat-rows');
    const statMerchants = document.getElementById('stat-merchants');

    async function loadData() {{
      try {{
        const r = await fetch(apiUrl('/api/data'));
        if (r.ok) {{
          const d = await r.json();
          if (Array.isArray(d) && d.length) {{ RAW = d; data = RAW.slice(); }}
        }}
      }} catch (e) {{}}
    }}

    function unique(arr) {{ return [...new Set(arr)].filter(Boolean).sort(); }}
    function fillSelect(id, values, current) {{
      const sel = document.getElementById(id);
      const first = sel.options[0];
      sel.innerHTML = '';
      sel.appendChild(first);
      values.forEach(v => {{
        const o = document.createElement('option');
        o.value = v;
        o.textContent = v;
        if (v === current) o.selected = true;
        sel.appendChild(o);
      }});
    }}

    function getFilters() {{
      return {{
        q: document.getElementById('search').value.trim().toLowerCase(),
        vertical: document.getElementById('filter-vertical').value,
        tier: document.getElementById('filter-tier').value,
        priority: document.getElementById('filter-priority').value,
        owner: document.getElementById('filter-owner').value,
        month: document.getElementById('filter-month').value
      }};
    }}

    function filterRows(rows) {{
      const f = getFilters();
      return rows.filter(r => {{
        if (f.vertical && r.vertical !== f.vertical) return false;
        if (f.tier && r.tier !== f.tier) return false;
        if (f.priority && r.priority !== f.priority) return false;
        if (f.owner && r.owner !== f.owner) return false;
        if (f.month && r.engagement_month_label !== f.month) return false;
        if (f.q) {{
          const s = [r.merchant, r.legal_entity, r.vertical, r.owner, r.fy26_fc_gmv, r.playbook, r.next_action, r.num_applications, r.approval_rate, r.take_rate, r.loans, r.aov].join(' ').toLowerCase();
          if (!s.includes(f.q)) return false;
        }}
        return true;
      }});
    }}

    function render() {{
      const filtered = filterRows(data);
      const sorted = filtered.slice().sort((a, b) => {{
        let aVal = a[sortKey] ?? a.engagement_month_sort ?? '';
        let bVal = b[sortKey] ?? b.engagement_month_sort ?? '';
        if (aVal < bVal) return -sortDir;
        if (aVal > bVal) return sortDir;
        return 0;
      }});

      tbody.innerHTML = '';
      if (sorted.length === 0) {{
        emptyState.style.display = 'block';
        return;
      }}
      emptyState.style.display = 'none';

      const merchants = unique(sorted.map(r => r.merchant));
      statRows.textContent = sorted.length;
      statMerchants.textContent = merchants.length;
      currentRows = sorted;

      sorted.forEach((r, idx) => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{ escape(r.merchant) }}</td>
          <td>${{ escape(r.vertical) }}</td>
          <td>${{ escape(r.tier) }}</td>
          <td>${{ escape(r.peak_months) }}</td>
          <td>${{ escape(r.engagement_month_label) }}</td>
          <td>${{ escape(r.engagement_type) }}</td>
          <td class="priority-${{ escape(r.priority) }}">${{ escape(r.priority) }}</td>
          <td>${{ escape(r.owner) }}</td>
          <td>${{ escape(r.fy26_fc_gmv) }}</td>
          <td>${{ escape(r.status) }}</td>
          <td>${{ escape(r.next_action) }}</td>
          <td class="${{ r.leadership_flag === 'Yes' ? 'leadership-yes' : '' }}">${{ escape(r.leadership_flag) }}</td>
          <td>${{ escape(r.playbook) }}</td>
          <td>${{ escape(r.num_applications) }}</td>
          <td>${{ escape(r.approval_rate) }}</td>
          <td>${{ escape(r.take_rate) }}</td>
          <td>${{ escape(r.loans) }}</td>
          <td>${{ escape(r.aov) }}</td>
          <td><div class="btn-row">
            <button type="button" class="btn-action primary btn-email" data-idx="${{ idx }}">Generate email</button>
            <button type="button" class="btn-action btn-news" data-idx="${{ idx }}">Latest news</button>
          </div></td>
        `;
        tbody.appendChild(tr);
      }});
      tbody.querySelectorAll('.btn-email').forEach(btn => btn.addEventListener('click', onGenerateEmail));
      tbody.querySelectorAll('.btn-news').forEach(btn => btn.addEventListener('click', onLatestNews));
    }}

    function escape(s) {{
      if (s == null) return '';
      const div = document.createElement('div');
      div.textContent = s;
      return div.innerHTML;
    }}

    const API_BASE = (typeof window !== 'undefined' && window.location && window.location.origin) ? '' : '';
    function apiUrl(path) {{ return API_BASE + path; }}

    function openEmailModal(title, bodyHtml) {{
      document.getElementById('modal-email-title').textContent = title;
      document.getElementById('modal-email-body').innerHTML = bodyHtml;
      document.getElementById('modal-email').classList.add('open');
    }}
    function openNewsModal(title, bodyHtml) {{
      document.getElementById('modal-news-title').textContent = title;
      document.getElementById('modal-news-body').innerHTML = bodyHtml;
      document.getElementById('modal-news').classList.add('open');
    }}
    function closeEmailModal() {{ document.getElementById('modal-email').classList.remove('open'); }}
    function closeNewsModal() {{ document.getElementById('modal-news').classList.remove('open'); }}
    document.getElementById('modal-email-close').addEventListener('click', closeEmailModal);
    document.getElementById('modal-news-close').addEventListener('click', closeNewsModal);
    document.getElementById('modal-email').addEventListener('click', e => {{ if (e.target.id === 'modal-email') closeEmailModal(); }});
    document.getElementById('modal-news').addEventListener('click', e => {{ if (e.target.id === 'modal-news') closeNewsModal(); }});

    async function onGenerateEmail(ev) {{
      const idx = parseInt(ev.target.getAttribute('data-idx'), 10);
      const row = currentRows[idx];
      if (!row) return;
      const btn = ev.target;
      btn.disabled = true;
      btn.textContent = 'Generating…';
      const body = document.getElementById('modal-email-body');
      openEmailModal('Reach-out email – ' + escape(row.merchant), '<div class="modal-body loading">Calling API…</div>');
      const bodyEl = document.getElementById('modal-email-body');
      try {{
        const res = await fetch(apiUrl('/api/generate-email'), {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(row)
        }});
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) {{
          bodyEl.innerHTML = '<p class="api-error">' + escape(data.error || 'Request failed') + '</p>';
          return;
        }}
        const email = data.email || '';
        bodyEl.innerHTML = '<div class="email-body">' + escape(email) + '</div><button type="button" class="btn-copy" id="btn-copy-email">Copy to clipboard</button>';
        document.getElementById('btn-copy-email').addEventListener('click', () => {{
          navigator.clipboard.writeText(email);
          const b = document.getElementById('btn-copy-email');
          b.textContent = 'Copied!';
          setTimeout(() => b.textContent = 'Copy to clipboard', 2000);
        }});
      }} catch (e) {{
        bodyEl.innerHTML = '<p class="api-error">' + escape(e.message || 'Network error. Run the Flask server for AI features.') + '</p>';
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Generate email';
      }}
    }}

    async function onLatestNews(ev) {{
      const idx = parseInt(ev.target.getAttribute('data-idx'), 10);
      const row = currentRows[idx];
      if (!row) return;
      const merchant = row.merchant;
      const btn = ev.target;
      btn.disabled = true;
      btn.textContent = 'Loading…';
      openNewsModal('Latest news – ' + merchant, '<div class="modal-body loading">Fetching news…</div>');
      const body = document.getElementById('modal-news-body');
      try {{
        const params = new URLSearchParams({{ merchant }});
        const le = (row.legal_entity && String(row.legal_entity).trim()) ? String(row.legal_entity).trim() : '';
        if (le) params.set('legal_entity', le);
        const res = await fetch(apiUrl('/api/news?' + params.toString()));
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) {{
          body.innerHTML = '<p class="api-error">' + escape(data.error || 'Request failed') + '</p>';
          btn.disabled = false;
          btn.textContent = 'Latest news';
          return;
        }}
        const articles = data.articles || [];
        const summary = data.summary || '';
        const src = data.source || '';
        if (articles.length === 0 && !summary) {{
          body.innerHTML = '<p class="text-muted">No recent news returned. Set GEMINI_API_KEY (live web), or SERPER_API_KEY / NEWS_API_KEY, in your server environment. OpenAI alone does not browse current news.</p>';
          btn.disabled = false;
          btn.textContent = 'Latest news';
          return;
        }}
        let html = '';
        if (src) {{
          const labels = {{ gemini: 'Gemini + Google Search (live web)', serper: 'Serper (Google News)', newsapi: 'News API', openai: 'OpenAI Responses API + web search (live)' }};
          html += '<p class="news-source-tag">' + escape(labels[src] || src) + '</p>';
        }}
        if (summary) {{
          const useMd = (typeof marked !== 'undefined' && (summary.indexOf('###') >= 0 || summary.indexOf('**') >= 0));
          const inner = useMd ? marked.parse(summary) : '<p>' + escape(summary).replace(/\\n/g, '<br>') + '</p>';
          html += '<div class="news-summary markdown-body">' + inner + '</div>';
        }}
        if (articles.length) html += '<ul class="news-list">' + articles.map(a => '<li><a href="' + escape(a.url) + '" target="_blank" rel="noopener">' + escape(a.title) + '</a><div class="source">' + escape(a.source) + (a.published ? ' · ' + escape(a.published.slice(0,10)) : '') + '</div></li>').join('') + '</ul>';
        body.innerHTML = html || '<p class="text-muted">No sources returned.</p>';
        btn.disabled = false;
        btn.textContent = 'Latest news';
      }} catch (e) {{
        btn.disabled = false;
        btn.textContent = 'Latest news';
        body.innerHTML = '<p class="api-error">' + escape(e.message || 'Network error. Run the Flask server for AI features.') + '</p>';
      }}
    }}

    (async function() {{
      await loadData();
      data = RAW.slice();

      document.querySelectorAll('th[data-key]').forEach(th => {{
        th.addEventListener('click', () => {{
          const key = th.getAttribute('data-key');
          const sortCol = key === 'engagement_month_label' ? 'engagement_month_sort' : key;
          if (sortKey === sortCol) sortDir = -sortDir;
          else {{ sortKey = sortCol; sortDir = 1; }}
          document.querySelectorAll('th[data-key]').forEach(h => h.classList.remove('sorted-asc','sorted-desc'));
          th.classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');
          render();
        }});
      }});
      document.querySelector('th[data-key="engagement_month_label"]').classList.add('sorted-asc');

      document.getElementById('search').addEventListener('input', render);
      document.getElementById('filter-vertical').addEventListener('change', render);
      document.getElementById('filter-tier').addEventListener('change', render);
      document.getElementById('filter-priority').addEventListener('change', render);
      document.getElementById('filter-owner').addEventListener('change', render);
      document.getElementById('filter-month').addEventListener('change', render);

      fillSelect('filter-vertical', unique(RAW.map(r => r.vertical)));
      fillSelect('filter-owner', unique(RAW.map(r => r.owner)));
      fillSelect('filter-month', unique(RAW.map(r => r.engagement_month_label)));

      render();
    }})();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
