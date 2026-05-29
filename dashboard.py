"""
Build a static HTML league history dashboard from serialized season data.
"""
import json
import os


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def _build_key_to_manager(seasons):
    """Build {team_key: manager_name} across all seasons."""
    k2m = {}
    for s in seasons:
        for t in s["standings"]:
            k2m[t["team_key"]] = t["manager"]
    return k2m


def _canonical_managers(seasons):
    """Return ordered list of all unique manager names (most recent season order)."""
    seen = {}
    for s in reversed(seasons):
        for t in s["standings"]:
            m = t["manager"]
            if m not in seen:
                seen[m] = t["name"]
    return list(seen.keys())


def _compute_alltime_standings(seasons):
    k2m = _build_key_to_manager(seasons)
    totals = {}  # manager → {wins, losses, ties, pf, pa, seasons, titles}

    for s in seasons:
        champ = next((t["manager"] for t in s["standings"] if t["rank"] == 1), None)
        for t in s["standings"]:
            m = t["manager"]
            if m not in totals:
                totals[m] = {"manager": m, "wins": 0, "losses": 0, "ties": 0,
                              "pf": 0.0, "pa": 0.0, "seasons": 0, "titles": 0}
            totals[m]["wins"] += t["wins"]
            totals[m]["losses"] += t["losses"]
            totals[m]["ties"] += t["ties"]
            totals[m]["pf"] += t["pf"]
            totals[m]["pa"] += t["pa"]
            totals[m]["seasons"] += 1
            if m == champ:
                totals[m]["titles"] += 1

    rows = []
    for m, d in totals.items():
        played = d["wins"] + d["losses"] + d["ties"]
        d["win_pct"] = round(d["wins"] / played, 3) if played else 0.0
        d["pf"] = round(d["pf"], 1)
        d["pa"] = round(d["pa"], 1)
        rows.append(d)

    rows.sort(key=lambda r: (-r["win_pct"], -r["wins"], -r["pf"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def _compute_champions(seasons):
    champs = []
    for s in seasons:
        champ_team = next((t for t in s["standings"] if t["rank"] == 1), None)
        if champ_team:
            champs.append({
                "season": s["season"],
                "manager": champ_team["manager"],
                "team_name": champ_team["name"],
                "wins": champ_team["wins"],
                "losses": champ_team["losses"],
                "pf": champ_team["pf"],
            })
    return list(reversed(champs))  # most recent first


def _compute_head_to_head(seasons):
    k2m = _build_key_to_manager(seasons)
    managers = _canonical_managers(seasons)
    # matrix[a][b] = {wins, losses} where wins = a beat b
    matrix = {m: {n: {"wins": 0, "losses": 0} for n in managers if n != m} for m in managers}

    for s in seasons:
        for match in s["matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            if not ma or not mb or ma == mb:
                continue
            if ma not in matrix:
                continue
            if mb not in matrix:
                continue
            if match["score_a"] > match["score_b"]:
                matrix[ma][mb]["wins"] += 1
                matrix[mb][ma]["losses"] += 1
            elif match["score_b"] > match["score_a"]:
                matrix[mb][ma]["wins"] += 1
                matrix[ma][mb]["losses"] += 1

    # Nemesis: opponent each manager has the worst record against (min win%)
    nemeses = {}
    for m in managers:
        best_nemesis = None
        worst_pct = 1.1
        for opp, rec in matrix[m].items():
            total = rec["wins"] + rec["losses"]
            if total < 3:
                continue
            pct = rec["wins"] / total
            if pct < worst_pct:
                worst_pct = pct
                best_nemesis = opp
        nemeses[m] = {"nemesis": best_nemesis, "win_pct": round(worst_pct, 3) if best_nemesis else None}

    return {"managers": managers, "matrix": matrix, "nemeses": nemeses}


def _compute_records(seasons):
    k2m = _build_key_to_manager(seasons)

    high_week = None   # {score, manager, team, season, week}
    low_week = None
    blowout = None     # {margin, winner, loser, score_w, score_l, season, week}
    closest = None

    best_season = None   # {manager, wins, losses, pf, season}
    worst_season = None

    all_scores = []  # (season, week, manager, score)

    for s in seasons:
        yr = s["season"]
        for match in s["matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            sa, sb = match["score_a"], match["score_b"]
            wk = match["week"]

            for mgr, score, name in [(ma, sa, match["team_a"]), (mb, sb, match["team_b"])]:
                if not mgr:
                    continue
                all_scores.append((yr, wk, mgr, score, name))
                if score > 0:
                    entry = {"score": score, "manager": mgr, "team": name, "season": yr, "week": wk}
                    if high_week is None or score > high_week["score"]:
                        high_week = entry
                    if low_week is None or score < low_week["score"]:
                        low_week = entry

            if ma and mb and sa > 0 and sb > 0:
                margin = abs(sa - sb)
                winner_mgr = ma if sa > sb else mb
                loser_mgr  = mb if sa > sb else ma
                score_w    = max(sa, sb)
                score_l    = min(sa, sb)
                w_name     = match["team_a"] if sa > sb else match["team_b"]
                l_name     = match["team_b"] if sa > sb else match["team_a"]

                blow_entry = {
                    "margin": round(margin, 2),
                    "winner": winner_mgr, "winner_team": w_name,
                    "loser": loser_mgr, "loser_team": l_name,
                    "score_w": score_w, "score_l": score_l,
                    "season": yr, "week": wk,
                }
                close_entry = blow_entry.copy()

                if blowout is None or margin > blowout["margin"]:
                    blowout = blow_entry
                if closest is None or margin < closest["margin"]:
                    closest = close_entry

        # Best/worst single season record by win %
        for t in s["standings"]:
            played = t["wins"] + t["losses"] + t["ties"]
            if played == 0:
                continue
            wpct = t["wins"] / played
            entry = {
                "manager": t["manager"], "team": t["name"],
                "wins": t["wins"], "losses": t["losses"],
                "pf": t["pf"], "win_pct": round(wpct, 3), "season": yr,
            }
            if best_season is None or wpct > best_season["win_pct"] or \
               (wpct == best_season["win_pct"] and t["pf"] > best_season["pf"]):
                best_season = entry
            if worst_season is None or wpct < worst_season["win_pct"] or \
               (wpct == worst_season["win_pct"] and t["pf"] < worst_season["pf"]):
                worst_season = entry

    # Streaks: sort all scores by (season, week), track per manager
    streaks = _compute_streaks(seasons, k2m)

    return {
        "high_week": high_week,
        "low_week": low_week,
        "blowout": blowout,
        "closest": closest,
        "best_season": best_season,
        "worst_season": worst_season,
        "streaks": streaks,
    }


def _compute_streaks(seasons, k2m):
    """Find longest win and loss streaks for each manager across all regular season games."""
    # Collect all (season, week, manager, result) ordered chronologically
    results = []  # (season, week, manager, won: bool)

    for s in seasons:
        yr = s["season"]
        for match in s["matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            if not ma or not mb:
                continue
            sa, sb = match["score_a"], match["score_b"]
            if sa == sb:
                continue
            winner = ma if sa > sb else mb
            loser  = mb if sa > sb else ma
            results.append((yr, match["week"], winner, True))
            results.append((yr, match["week"], loser,  False))

    results.sort(key=lambda r: (r[0], r[1]))

    # Per-manager running streaks
    mgr_games = {}
    for _, _, mgr, won in results:
        if mgr not in mgr_games:
            mgr_games[mgr] = []
        mgr_games[mgr].append(won)

    best_win_streak  = {"manager": None, "length": 0}
    best_loss_streak = {"manager": None, "length": 0}

    for mgr, games in mgr_games.items():
        cur_w = cur_l = max_w = max_l = 0
        for won in games:
            if won:
                cur_w += 1; cur_l = 0
            else:
                cur_l += 1; cur_w = 0
            max_w = max(max_w, cur_w)
            max_l = max(max_l, cur_l)
        if max_w > best_win_streak["length"]:
            best_win_streak  = {"manager": mgr, "length": max_w}
        if max_l > best_loss_streak["length"]:
            best_loss_streak = {"manager": mgr, "length": max_l}

    return {"win": best_win_streak, "loss": best_loss_streak}


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{league_name} — League History</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh}}
header{{background:linear-gradient(135deg,#1c3d5a 0%,#0d1117 100%);padding:32px 24px 24px;text-align:center;border-bottom:1px solid #21262d}}
header h1{{font-size:28px;font-weight:800;letter-spacing:-.5px}}
header p{{color:#8b949e;font-size:14px;margin-top:6px}}
nav{{display:flex;justify-content:center;gap:4px;padding:16px 24px;border-bottom:1px solid #21262d;background:#161b22;position:sticky;top:0;z-index:10}}
.tab{{padding:8px 20px;border-radius:6px;border:1px solid transparent;font-size:14px;font-weight:600;cursor:pointer;background:transparent;color:#8b949e;transition:all .15s}}
.tab:hover{{background:#21262d;color:#e6edf3}}
.tab.active{{background:#1c3d5a;border-color:#1f6feb;color:#58a6ff}}
.section{{display:none;max-width:1100px;margin:0 auto;padding:32px 24px}}
.section.active{{display:block}}
h2{{font-size:20px;font-weight:700;margin-bottom:20px;color:#f0f6fc}}
.card{{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:20px;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;padding:10px 12px;border-bottom:2px solid #21262d;color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
th.sortable{{cursor:pointer;user-select:none}}
th.sortable:hover{{color:#e6edf3}}
th.sort-asc::after{{content:' ▲';font-size:10px}}
th.sort-desc::after{{content:' ▼';font-size:10px}}
td{{padding:10px 12px;border-bottom:1px solid #21262d}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1c2128}}
.rank{{color:#8b949e;font-size:13px;width:32px}}
.champion-badge{{display:inline-block;background:#b8860b;color:#fff9c4;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700;margin-left:6px}}
.win{{color:#3fb950}}
.loss{{color:#f85149}}
.neutral{{color:#8b949e}}
.pct{{font-variant-numeric:tabular-nums}}
.champ-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
.champ-card{{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:18px;transition:transform .15s}}
.champ-card:hover{{transform:translateY(-2px)}}
.champ-year{{font-size:13px;color:#8b949e;margin-bottom:4px}}
.champ-manager{{font-size:18px;font-weight:800;color:#f0f6fc;margin-bottom:2px}}
.champ-team{{font-size:13px;color:#58a6ff;margin-bottom:8px}}
.champ-record{{font-size:13px;color:#8b949e}}
/* H2H matrix */
.matrix-wrap{{overflow-x:auto}}
.matrix{{border-collapse:collapse;font-size:12px;white-space:nowrap}}
.matrix th,.matrix td{{padding:6px 8px;border:1px solid #21262d;text-align:center}}
.matrix th{{background:#161b22;color:#8b949e;font-weight:600}}
.matrix .row-label{{text-align:right;font-weight:600;color:#e6edf3;background:#161b22;max-width:120px;overflow:hidden;text-overflow:ellipsis}}
.matrix td.self{{background:#0d1117}}
.matrix td.dominant{{background:#1a3a1e;color:#3fb950}}
.matrix td.winning{{background:#1a2a1e;color:#3fb950}}
.matrix td.even{{background:#1c2128;color:#8b949e}}
.matrix td.losing{{background:#2a1a1a;color:#f85149}}
.matrix td.dominated{{background:#3a1a1a;color:#f85149}}
/* Records grid */
.records-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}
.rec-card{{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:18px}}
.rec-label{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#8b949e;margin-bottom:8px;font-weight:600}}
.rec-value{{font-size:26px;font-weight:800;color:#f0f6fc;margin-bottom:4px}}
.rec-sub{{font-size:13px;color:#58a6ff}}
.rec-detail{{font-size:12px;color:#8b949e;margin-top:4px}}
.nemesis-row td:first-child{{font-weight:600;color:#e6edf3}}
</style>
</head>
<body>
<header>
  <h1>🏈 {league_name}</h1>
  <p>League History · {year_range}</p>
</header>
<nav>
  <button class="tab active" onclick="show('standings')">All-Time Standings</button>
  <button class="tab" onclick="show('champions')">Champions</button>
  <button class="tab" onclick="show('h2h')">Head-to-Head</button>
  <button class="tab" onclick="show('records')">Records</button>
</nav>

<div id="standings" class="section active">
  <h2>All-Time Standings</h2>
  <div class="card">
    <table id="standings-tbl">
      <thead><tr>
        <th></th>
        <th class="sortable" data-key="manager" data-type="str">Manager</th>
        <th class="sortable" data-key="seasons" data-type="num">Seasons</th>
        <th class="sortable" data-key="wins" data-type="num">W</th>
        <th class="sortable" data-key="losses" data-type="num">L</th>
        <th class="sortable sort-desc" data-key="win_pct" data-type="num">Win%</th>
        <th class="sortable" data-key="pf" data-type="num">PF</th>
        <th class="sortable" data-key="pa" data-type="num">PA</th>
        <th class="sortable" data-key="titles" data-type="num">Titles</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div id="champions" class="section">
  <h2>Hall of Champions</h2>
  <div class="champ-grid" id="champ-grid"></div>
</div>

<div id="h2h" class="section">
  <h2>Head-to-Head Records</h2>
  <div class="card matrix-wrap">
    <table class="matrix" id="h2h-tbl"></table>
  </div>
  <h2 style="margin-top:32px">Nemesis Report</h2>
  <div class="card">
    <table id="nemesis-tbl">
      <thead><tr><th>Manager</th><th>Nemesis</th><th>Record vs Nemesis</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div id="records" class="section">
  <h2>Records &amp; Milestones</h2>
  <div class="records-grid" id="records-grid"></div>
</div>

<script>
const DATA = {data_json};

function show(id) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
}}

// ── Standings ──────────────────────────────────────────────────────────────
(function buildStandings() {{
  let sortKey = 'win_pct', sortDir = -1;

  function renderRow(r, i) {{
    const tr = document.createElement('tr');
    const trophy = r.titles > 0 ? ` <span style="color:#ffd700">${{'🏆'.repeat(r.titles)}}</span>` : '';
    tr.innerHTML = `
      <td class="rank">${{i + 1}}</td>
      <td><strong>${{r.manager}}</strong>${{trophy}}</td>
      <td class="neutral">${{r.seasons}}</td>
      <td class="win">${{r.wins}}</td>
      <td class="loss">${{r.losses}}</td>
      <td class="pct">${{(r.win_pct*100).toFixed(1)}}%</td>
      <td>${{r.pf.toLocaleString('en-US',{{minimumFractionDigits:1,maximumFractionDigits:1}})}}</td>
      <td class="neutral">${{r.pa.toLocaleString('en-US',{{minimumFractionDigits:1,maximumFractionDigits:1}})}}</td>
      <td>${{r.titles > 0 ? r.titles : '—'}}</td>
    `;
    return tr;
  }}

  function renderTable() {{
    const sorted = [...DATA.alltime].sort((a, b) => {{
      const av = a[sortKey], bv = b[sortKey];
      return typeof av === 'string' ? av.localeCompare(bv) * sortDir : (av - bv) * sortDir;
    }});
    const tbody = document.querySelector('#standings-tbl tbody');
    tbody.innerHTML = '';
    sorted.forEach((r, i) => tbody.appendChild(renderRow(r, i)));
  }}

  document.querySelectorAll('#standings-tbl th.sortable').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.key;
      if (sortKey === key) {{ sortDir *= -1; }}
      else {{ sortKey = key; sortDir = key === 'manager' ? 1 : -1; }}
      document.querySelectorAll('#standings-tbl th').forEach(t => t.classList.remove('sort-asc','sort-desc'));
      th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
      renderTable();
    }});
  }});

  renderTable();
}})();

// ── Champions ──────────────────────────────────────────────────────────────
(function buildChampions() {{
  const grid = document.getElementById('champ-grid');
  DATA.champions.forEach(c => {{
    const div = document.createElement('div');
    div.className = 'champ-card';
    div.innerHTML = `
      <div class="champ-year">🏆 ${{c.season}} Champion</div>
      <div class="champ-manager">${{c.manager}}</div>
      <div class="champ-team">${{c.team_name}}</div>
      <div class="champ-record">${{c.wins}}–${{c.losses}} &nbsp;·&nbsp; ${{c.pf.toFixed(1)}} pts</div>
    `;
    grid.appendChild(div);
  }});
}})();

// ── Head-to-Head ───────────────────────────────────────────────────────────
(function buildH2H() {{
  const {{managers, matrix, nemeses}} = DATA.h2h;
  const tbl = document.getElementById('h2h-tbl');

  // Header row
  const hdr = document.createElement('tr');
  hdr.innerHTML = '<th></th>' + managers.map(m => `<th title="${{m}}">${{m.split(' ')[0]}}</th>`).join('');
  tbl.appendChild(hdr);

  managers.forEach(row => {{
    const tr = document.createElement('tr');
    let cells = `<td class="row-label" title="${{row}}">${{row}}</td>`;
    managers.forEach(col => {{
      if (row === col) {{ cells += '<td class="self">·</td>'; return; }}
      const rec = matrix[row][col];
      const w = rec.wins, l = rec.losses, tot = w + l;
      if (tot === 0) {{ cells += '<td class="even">—</td>'; return; }}
      const pct = w / tot;
      let cls = 'even';
      if (pct >= .7) cls = 'dominant';
      else if (pct > .5) cls = 'winning';
      else if (pct <= .3) cls = 'dominated';
      else if (pct < .5) cls = 'losing';
      cells += `<td class="${{cls}}" title="${{row}} vs ${{col}}: ${{w}}-${{l}}">${{w}}-${{l}}</td>`;
    }});
    tr.innerHTML = cells;
    tbl.appendChild(tr);
  }});

  // Nemesis table
  const ntbody = document.querySelector('#nemesis-tbl tbody');
  managers.forEach(m => {{
    const n = nemeses[m];
    if (!n.nemesis) return;
    const rec = matrix[m][n.nemesis];
    const tr = document.createElement('tr');
    tr.className = 'nemesis-row';
    tr.innerHTML = `
      <td>${{m}}</td>
      <td style="color:#f85149">${{n.nemesis}}</td>
      <td class="loss">${{rec.wins}}–${{rec.losses}} (${{(n.win_pct*100).toFixed(0)}}% win rate)</td>
    `;
    ntbody.appendChild(tr);
  }});
}})();

// ── Records ────────────────────────────────────────────────────────────────
(function buildRecords() {{
  const rec = DATA.records;
  const grid = document.getElementById('records-grid');

  function card(label, value, sub, detail) {{
    const d = document.createElement('div');
    d.className = 'rec-card';
    d.innerHTML = `
      <div class="rec-label">${{label}}</div>
      <div class="rec-value">${{value}}</div>
      ${{sub ? `<div class="rec-sub">${{sub}}</div>` : ''}}
      ${{detail ? `<div class="rec-detail">${{detail}}</div>` : ''}}
    `;
    grid.appendChild(d);
  }}

  if (rec.high_week) {{
    const h = rec.high_week;
    card('Highest Single-Week Score', h.score.toFixed(2) + ' pts',
      h.manager, `${{h.team}} · Week ${{h.week}}, ${{h.season}}`);
  }}
  if (rec.low_week) {{
    const l = rec.low_week;
    card('Lowest Single-Week Score', l.score.toFixed(2) + ' pts',
      l.manager, `${{l.team}} · Week ${{l.week}}, ${{l.season}}`);
  }}
  if (rec.blowout) {{
    const b = rec.blowout;
    card('Biggest Blowout', '+' + b.margin.toFixed(2) + ' margin',
      b.winner + ' def. ' + b.loser,
      `${{b.score_w.toFixed(2)}}–${{b.score_l.toFixed(2)}} · Week ${{b.week}}, ${{b.season}}`);
  }}
  if (rec.closest) {{
    const c = rec.closest;
    card('Closest Game', c.margin.toFixed(2) + ' margin',
      c.winner + ' def. ' + c.loser,
      `${{c.score_w.toFixed(2)}}–${{c.score_l.toFixed(2)}} · Week ${{c.week}}, ${{c.season}}`);
  }}
  if (rec.best_season) {{
    const b = rec.best_season;
    card('Best Single Season', b.wins + '–' + b.losses,
      b.manager, `${{b.team}} · ${{b.season}} · ${{b.pf.toFixed(1)}} pts`);
  }}
  if (rec.worst_season) {{
    const w = rec.worst_season;
    card('Worst Single Season', w.wins + '–' + w.losses,
      w.manager, `${{w.team}} · ${{w.season}} · ${{w.pf.toFixed(1)}} pts`);
  }}
  if (rec.streaks.win.manager) {{
    const s = rec.streaks.win;
    card('Longest Win Streak', s.length + ' wins', s.manager);
  }}
  if (rec.streaks.loss.manager) {{
    const s = rec.streaks.loss;
    card('Longest Losing Streak', s.length + ' losses', s.manager);
  }}
}})();
</script>
</body>
</html>"""


def build_dashboard(seasons, output_path="dashboard/index.html"):
    if not seasons:
        raise ValueError("No season data provided.")

    league_name = seasons[-1]["league_name"]
    years = [s["season"] for s in seasons]
    year_range = f"{min(years)}–{max(years)}"

    stats = {
        "alltime":   _compute_alltime_standings(seasons),
        "champions": _compute_champions(seasons),
        "h2h":       _compute_head_to_head(seasons),
        "records":   _compute_records(seasons),
    }

    data_json = json.dumps(stats, separators=(",", ":"))
    html = _HTML_TEMPLATE.format(
        league_name=league_name,
        year_range=year_range,
        data_json=data_json,
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
