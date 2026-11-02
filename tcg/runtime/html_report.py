"""Self-contained interactive HTML test report generator for HiL test benches.

Renders modern, responsive dashboard reports with zero external dependencies (no CDN, works offline).
"""
from datetime import datetime
import html
import json
from pathlib import Path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --pass: #10b981;
      --pass-bg: rgba(16, 185, 129, 0.15);
      --fail: #ef4444;
      --fail-bg: rgba(239, 68, 68, 0.15);
      --error: #f59e0b;
      --error-bg: rgba(245, 158, 11, 0.15);
      --accent: #3b82f6;
      --accent-hover: #2563eb;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 16px;
    }}
    h1 {{ font-size: 24px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }}
    .badge {{
      font-size: 11px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .badge-pass {{ background: var(--pass-bg); color: var(--pass); border: 1px solid var(--pass); }}
    .badge-fail {{ background: var(--fail-bg); color: var(--fail); border: 1px solid var(--fail); }}
    .badge-error {{ background: var(--error-bg); color: var(--error); border: 1px solid var(--error); }}
    .meta-bar {{ font-size: 13px; color: var(--text-muted); display: flex; gap: 16px; flex-wrap: wrap; }}

    /* KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      position: relative;
      overflow: hidden;
    }}
    .kpi-card .title {{ font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; }}
    .kpi-card .val {{ font-size: 32px; font-weight: 700; margin-top: 6px; }}
    .kpi-card .sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}
    .kpi-pass .val {{ color: var(--pass); }}
    .kpi-fail .val {{ color: var(--fail); }}
    .kpi-error .val {{ color: var(--error); }}

    /* Progress bar */
    .progress-bar {{
      height: 10px;
      background: #334155;
      border-radius: 9999px;
      overflow: hidden;
      display: flex;
      margin-bottom: 24px;
    }}
    .progress-fill-pass {{ background: var(--pass); height: 100%; }}
    .progress-fill-fail {{ background: var(--fail); height: 100%; }}
    .progress-fill-error {{ background: var(--error); height: 100%; }}

    /* Controls */
    .controls-bar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }}
    .filter-buttons {{ display: flex; gap: 8px; }}
    .btn {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .btn:hover {{ border-color: var(--accent); }}
    .btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    .search-input {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      min-width: 260px;
      outline: none;
    }}
    .search-input:focus {{ border-color: var(--accent); }}

    /* Test Case List */
    .test-list {{ display: flex; flex-direction: column; gap: 12px; }}
    .test-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      overflow: hidden;
      transition: border-color 0.15s ease;
    }}
    .test-card:hover {{ border-color: #475569; }}
    .test-header {{
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      gap: 16px;
      user-select: none;
    }}
    .test-title-group {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .test-id {{ font-size: 15px; font-weight: 600; font-family: monospace; }}
    .test-meta {{ font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 12px; }}
    .chevron {{ transition: transform 0.2s ease; color: var(--text-muted); }}
    .test-card.open .chevron {{ transform: rotate(180deg); }}

    /* Details Drawer */
    .test-body {{
      display: none;
      padding: 20px;
      border-top: 1px solid var(--card-border);
      background: #151f30;
      font-size: 13px;
    }}
    .test-card.open .test-body {{ display: block; }}
    .section-title {{
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--accent);
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .error-banner {{
      background: var(--fail-bg);
      border: 1px solid var(--fail);
      color: #fca5a5;
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 16px;
      font-family: monospace;
      font-size: 13px;
    }}
    pre.spec-box {{
      background: #0b1120;
      border: 1px solid #1e293b;
      padding: 14px;
      border-radius: 8px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12px;
      color: #cbd5e1;
      white-space: pre-wrap;
      max-height: 280px;
      overflow-y: auto;
      margin-bottom: 16px;
    }}

    /* Trace Table */
    table.trace-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin-top: 8px;
    }}
    table.trace-table th {{
      text-align: left;
      padding: 8px 12px;
      background: #0f172a;
      color: var(--text-muted);
      border-bottom: 1px solid var(--card-border);
      font-weight: 600;
    }}
    table.trace-table td {{
      padding: 7px 12px;
      border-bottom: 1px solid rgba(51, 65, 85, 0.4);
      font-family: monospace;
    }}
    table.trace-table tr:hover td {{ background: rgba(59, 130, 246, 0.05); }}
    .trace-time {{ color: var(--accent); width: 100px; }}
    .trace-op {{ color: #e2e8f0; font-weight: 600; width: 180px; }}
    .trace-details {{ color: #94a3b8; word-break: break-all; }}

    footer {{
      margin-top: 40px;
      padding-top: 20px;
      border-top: 1px solid var(--card-border);
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>
          <span>⚡</span>
          <span>{title}</span>
        </h1>
        <div class="meta-bar" style="margin-top: 6px;">
          <span>Prüfstands-Adapter: <strong>{bench_type}</strong></span>
          <span>•</span>
          <span>Generiert am: <strong>{timestamp}</strong></span>
          <span>•</span>
          <span>Gesamtdauer: <strong>{total_duration_s:.3f} s</strong></span>
        </div>
      </div>
      <div>
        <button class="btn" onclick="window.print()">Drucken / PDF</button>
      </div>
    </header>

    <!-- KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="title">Testfälle Gesamt</div>
        <div class="val">{total_count}</div>
        <div class="sub">100% ausgeführt</div>
      </div>
      <div class="kpi-card kpi-pass">
        <div class="title">Erfolgreich (Pass)</div>
        <div class="val">{pass_count}</div>
        <div class="sub">{pass_rate:.1f}% Erfolgsrate</div>
      </div>
      <div class="kpi-card kpi-fail">
        <div class="title">Fehlgeschlagen (Fail)</div>
        <div class="val">{fail_count}</div>
        <div class="sub">{fail_rate:.1f}% Check-Fehler</div>
      </div>
      <div class="kpi-card kpi-error">
        <div class="title">Laufzeitfehler (Error)</div>
        <div class="val">{error_count}</div>
        <div class="sub">Ausnahmen</div>
      </div>
    </div>

    <!-- Visual Progress Bar -->
    <div class="progress-bar">
      <div class="progress-fill-pass" style="width: {pass_rate}%;"></div>
      <div class="progress-fill-fail" style="width: {fail_rate}%;"></div>
      <div class="progress-fill-error" style="width: {error_rate}%;"></div>
    </div>

    <!-- Controls -->
    <div class="controls-bar">
      <div class="filter-buttons">
        <button class="btn active" onclick="filterTests('all', this)">Alle ({total_count})</button>
        <button class="btn" onclick="filterTests('PASS', this)">Pass ({pass_count})</button>
        <button class="btn" onclick="filterTests('FAIL', this)">Fail ({fail_count})</button>
        <button class="btn" onclick="filterTests('ERROR', this)">Error ({error_count})</button>
      </div>
      <input type="text" id="searchInput" class="search-input" placeholder="Nach Test-ID suchen..." onkeyup="searchTests()">
    </div>

    <!-- Test List -->
    <div class="test-list" id="testList">
      {test_cards_html}
    </div>

    <footer>
      SpecToTest v0.3.0 • Hexagonal Test Case Generator & HiL Testbench Report
    </footer>
  </div>

  <script>
    function toggleCard(card) {{
      card.classList.toggle('open');
    }}

    function filterTests(status, btn) {{
      document.querySelectorAll('.filter-buttons .btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const cards = document.querySelectorAll('.test-card');
      cards.forEach(card => {{
        if (status === 'all' || card.dataset.status === status) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}

    function searchTests() {{
      const query = document.getElementById('searchInput').value.toLowerCase();
      const cards = document.querySelectorAll('.test-card');
      cards.forEach(card => {{
        const text = card.dataset.testid.toLowerCase();
        if (text.includes(query)) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}
  </script>
</body>
</html>
"""


def _render_test_card(log) -> str:
    test_id = str(getattr(log, 'test_id', 'UNKNOWN'))
    result = str(getattr(log, 'result', 'UNKNOWN')).upper()
    duration = getattr(log, 'duration', 0.0)
    spec_text = getattr(log, 'specification', '') or ''
    error = getattr(log, 'error', None)
    records = getattr(log, 'records', []) or []

    badge_class = f"badge-{result.lower()}"

    error_html = ""
    if error:
        error_html = f'<div class="error-banner"><strong>FEHLER:</strong> {html.escape(str(error))}</div>'

    spec_html = ""
    if spec_text.strip():
        spec_html = f"""
        <div class="section-title">Original-Spezifikation (.txt)</div>
        <pre class="spec-box">{html.escape(spec_text.strip())}</pre>
        """

    trace_html = ""
    if records:
        rows = []
        for r in records:
            t = html.escape(str(r.get('time', '')))
            op = html.escape(str(r.get('operation', '')))
            details = html.escape(str(r.get('details', '')))
            rows.append(f"<tr><td class='trace-time'>{t}</td><td class='trace-op'>{op}</td><td class='trace-details'>{details}</td></tr>")
        trace_html = f"""
        <div class="section-title" style="margin-top: 14px;">Prüfstands-Ausführungs-Trace ({len(records)} Aktionen)</div>
        <table class="trace-table">
          <thead>
            <tr><th>Sim-Zeit</th><th>Operation</th><th>Parameter / Werte</th></tr>
          </thead>
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
        """

    card_html = f"""
    <div class="test-card" data-status="{result}" data-testid="{test_id}">
      <div class="test-header" onclick="toggleCard(this.parentElement)">
        <div class="test-title-group">
          <span class="badge {badge_class}">{result}</span>
          <span class="test-id">{test_id}</span>
        </div>
        <div class="test-meta">
          <span>{len(records)} Schritte</span>
          <span>•</span>
          <span>{duration:.3f} s</span>
          <span class="chevron">▼</span>
        </div>
      </div>
      <div class="test-body">
        {error_html}
        {spec_html}
        {trace_html}
      </div>
    </div>
    """
    return card_html


def generate_html_report(
    logs: list,
    output_path: Path | str,
    bench_type: str = "VectorDummyBench",
    title: str = "SpecToTest — HiL Test Bench Execution Report",
) -> Path:
    """Generates a standalone, beautiful HTML dashboard report for test executions."""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    total_count = len(logs)
    pass_count = sum(1 for log in logs if getattr(log, 'result', '') == 'PASS')
    fail_count = sum(1 for log in logs if getattr(log, 'result', '') == 'FAIL')
    error_count = sum(1 for log in logs if getattr(log, 'result', '') == 'ERROR')

    pass_rate = (pass_count / total_count * 100) if total_count else 0
    fail_rate = (fail_count / total_count * 100) if total_count else 0
    error_rate = (error_count / total_count * 100) if total_count else 0
    total_duration = sum(getattr(log, 'duration', 0.0) for log in logs)

    cards = [_render_test_card(log) for log in logs]

    html_content = HTML_TEMPLATE.format(
        title=html.escape(title),
        bench_type=html.escape(bench_type),
        timestamp=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        total_duration_s=total_duration,
        total_count=total_count,
        pass_count=pass_count,
        fail_count=fail_count,
        error_count=error_count,
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        error_rate=error_rate,
        test_cards_html="".join(cards),
    )

    out_file.write_text(html_content, encoding='utf-8')
    return out_file

