# Keeper Dashboard Pick'em Reskin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reskin the generated league-history dashboard (`docs/<slug>/index.html`) to match the `nfl_pickem_app` "Sleeper-style" look, plus light mobile UX polish, without changing any stats or data.

**Architecture:** All markup/CSS/JS lives inside one big `_HTML_TEMPLATE` string in `dashboard.py`, rendered client-side from a `const DATA = {…}` JSON blob. We first add a regression test, then split the template into `_CSS` / `_JS` / `_SKELETON` constants assembled by concatenation (killing the `.format()` `{{ }}` brace-escaping), then rewrite the CSS + header/nav + each section's JS render function. The Python stat functions (`_compute_*`) and the `main.py` CLI are untouched.

**Tech Stack:** Python 3 (stdlib only), vanilla HTML/CSS/JS, pytest for tests, Playwright MCP (optional) for final render verification. Fonts via Google Fonts CDN. No framework, no build step; output stays a single static HTML file.

## Global Constraints

- Palette tokens (copy verbatim into `:root`): `--bg:#0A0D16`, `--bg-glow:#121a2e`, `--surface:#141a26`, `--surface-2:#1B2331`, `--surface-3:#232d3d`, `--border:#262f40`, `--border-soft:#1d2534`, `--text:#F4F7FB`, `--text-muted:#AEB8C9`, `--text-dim:#8B96A9`, `--gold:#FFC24B`, `--gold-deep:#E2A02E`, `--gold-glow:rgba(255,194,75,0.16)`, `--success:#35D07F`, `--danger:#FF5C6C`.
- Fonts: `Archivo` (600–900, display) + `Manrope` (400–800, body), Google Fonts CDN, fallback `system-ui, sans-serif`. Numbers use `font-feature-settings:'tnum' 1`.
- Nav is **hybrid**: desktop (≥720px) = gold pill row; mobile (<720px) = fixed bottom tab bar. Breakpoint is **720px** everywhere.
- Sections (fixed order + tab labels): `standings` (Standings) · `champions` (Champs) · `h2h` (H2H) · `pvp` (vs) · `records` (Records).
- **No new data/stats.** `build_dashboard(seasons, output_path)` keeps its signature and the injected `stats` dict shape: `{alltime, champions, h2h, records, playoffs, active_managers}`.
- **Accessibility:** AA color contrast (free from the palette) + `:focus-visible` outlines + honor `prefers-reduced-motion`. No screen-reader/ARIA/tablist hardening (fully-sighted audience — deliberate).
- Output stays one self-contained file per league. Only external references allowed: the two Google Fonts `<link>`s.
- Source of truth for component CSS: `../../../nfl_pickem_app/app/static/css/style.css` (relative to this repo: `/Users/balbright/Desktop/claude/nfl_pickem_app/app/static/css/style.css`).

---

## File Structure

- `dashboard.py` — MODIFY. Split `_HTML_TEMPLATE` into `_CSS`, `_JS`, `_SKELETON` module constants; rewrite them for the new look. `build_dashboard` assembles the final HTML.
- `tests/test_dashboard.py` — CREATE. Verified fixture + pipeline value-preservation tests + per-section reskin marker tests.
- `docs/{wheaton,hey,lobos,espn-test}/index.html` — REGENERATED outputs (Task 9).

---

## Task 1: Test harness + value-preservation regression guard

Establishes the safety net **before** touching the template. These tests exercise the untouched stat pipeline and must stay green through every later task.

**Files:**
- Create: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `dashboard.build_dashboard(seasons, output_path)`, `dashboard._compute_champions(seasons)`, `dashboard._compute_alltime_standings(seasons)`.
- Produces: `_fixture_seasons()` and `_build_html(tmp_path)` helpers reused by all later tasks in this file.

- [ ] **Step 1: Ensure pytest is available**

Run: `cd /Users/balbright/Desktop/claude/keeper_league_tool && source .venv/bin/activate && python -m pytest --version || pip install pytest`
Expected: a pytest version prints (installs it if missing).

- [ ] **Step 2: Write the test file with the verified fixture and pipeline tests**

This fixture was validated against the real `dashboard.py`: reigning champ = Bob (2025), Alice all-time wins = 17.

```python
# tests/test_dashboard.py
import dashboard


def _fixture_seasons():
    """Two-season, 4-manager league with a playoff final each year.
    2024 champ: Alice.  2025 champ (reigning): Bob.  Verified against dashboard.py."""
    def team(key, name, mgr, w, l, rank, pf, pa):
        return {"team_key": key, "name": name, "manager": mgr, "wins": w,
                "losses": l, "ties": 0, "pf": pf, "pa": pa, "rank": rank}

    def reg(wk, ka, kb, sa, sb, ta, tb):
        return {"week": wk, "is_playoffs": False, "is_consolation": False,
                "key_a": ka, "key_b": kb, "score_a": sa, "score_b": sb,
                "team_a": ta, "team_b": tb}

    def po(wk, ka, kb, sa, sb, ta, tb):
        d = reg(wk, ka, kb, sa, sb, ta, tb)
        d["is_playoffs"] = True
        return d

    s2024_reg = [
        reg(1, "t1", "t2", 100, 90, "Alice's Team", "Bob's Team"),
        reg(1, "t3", "t4", 80, 70, "Carol's Team", "Dave's Team"),
        reg(2, "t1", "t3", 110, 60, "Alice's Team", "Carol's Team"),
        reg(2, "t2", "t4", 95, 85, "Bob's Team", "Dave's Team"),
    ]
    s2024 = {
        "season": 2024, "league_name": "Test League", "league_key": "L",
        "playoff_start_week": 15,
        "standings": [
            team("t1", "Alice's Team", "Alice", 9, 4, 1, 1500.0, 1400.0),
            team("t2", "Bob's Team",   "Bob",   8, 5, 2, 1450.0, 1420.0),
            team("t3", "Carol's Team", "Carol", 6, 7, 3, 1300.0, 1350.0),
            team("t4", "Dave's Team",  "Dave",  3, 10, 4, 1200.0, 1500.0),
        ],
        "matchups": s2024_reg,
        "all_matchups": s2024_reg + [po(15, "t1", "t2", 120, 100, "Alice's Team", "Bob's Team")],
    }
    s2025_reg = [
        reg(1, "t2", "t1", 105, 95, "Bob's Team", "Alice's Team"),
        reg(1, "t3", "t4", 88, 72, "Carol's Team", "Dave's Team"),
        reg(2, "t2", "t3", 100, 70, "Bob's Team", "Carol's Team"),
        reg(2, "t1", "t4", 99, 80, "Alice's Team", "Dave's Team"),
    ]
    s2025 = {
        "season": 2025, "league_name": "Test League", "league_key": "L",
        "playoff_start_week": 15,
        "standings": [
            team("t2", "Bob's Team",   "Bob",   9, 4, 1, 1520.0, 1410.0),
            team("t1", "Alice's Team", "Alice", 8, 5, 2, 1480.0, 1440.0),
            team("t3", "Carol's Team", "Carol", 7, 6, 3, 1350.0, 1360.0),
            team("t4", "Dave's Team",  "Dave",  2, 11, 4, 1180.0, 1520.0),
        ],
        "matchups": s2025_reg,
        "all_matchups": s2025_reg + [po(15, "t2", "t1", 118, 100, "Bob's Team", "Alice's Team")],
    }
    return [s2024, s2025]


def _build_html(tmp_path):
    out = tmp_path / "out.html"
    dashboard.build_dashboard(_fixture_seasons(), str(out))
    return out.read_text(encoding="utf-8")


def test_reigning_champion_is_most_recent():
    champs = dashboard._compute_champions(_fixture_seasons())
    assert champs[0]["manager"] == "Bob"
    assert champs[0]["season"] == 2025
    assert [(c["season"], c["manager"]) for c in champs] == [(2025, "Bob"), (2024, "Alice")]


def test_alltime_wins_aggregate_across_seasons():
    rows = dashboard._compute_alltime_standings(_fixture_seasons())
    alice = next(r for r in rows if r["manager"] == "Alice")
    assert alice["wins"] == 17          # 9 + 8
    assert alice["titles"] == 1


def test_build_writes_selfcontained_dashboard(tmp_path):
    html = _build_html(tmp_path)
    assert html.startswith("<!DOCTYPE html>")
    assert "Test League" in html
    assert "const DATA =" in html
    # value survives into the page: Bob is the reigning champion in the JSON blob
    assert '"manager":"Bob"' in html
```

- [ ] **Step 3: Run the tests to verify they pass on the current (un-reskinned) code**

Run: `cd /Users/balbright/Desktop/claude/keeper_league_tool && source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v`
Expected: 3 passed. (These guard the pipeline; they stay green for the whole plan.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_dashboard.py
git commit -m "test: add dashboard pipeline regression guard + verified fixture"
```

---

## Task 2: Behavior-preserving refactor — split template, drop `.format()` brace-escaping

Extract the CSS and JS out of the single `.format()` template so the reskin edits don't need `{{ }}` doubling. Output stays functionally identical.

**Files:**
- Modify: `dashboard.py` (the `_HTML_TEMPLATE` block ~line 465 and `build_dashboard` ~line 1224)

**Interfaces:**
- Consumes: `_fixture_seasons`, `_build_html` from Task 1.
- Produces: module constants `_CSS` (str), `_JS` (str, contains the literal token `__DATA_JSON__`), `_SKELETON` (str, contains `__LEAGUE_NAME__`, `__YEAR_RANGE__`, and a `__JS__` insertion point). `build_dashboard` assembles: `_SKELETON` with `__CSS__`→`_CSS`, `__JS__`→(`_JS` with `__DATA_JSON__`→`data_json`), and the two placeholders filled.

- [ ] **Step 1: Add the marker test (fails until refactor keeps output intact)**

Add to `tests/test_dashboard.py`:

```python
def test_output_has_all_sections_and_data(tmp_path):
    html = _build_html(tmp_path)
    for section_id in ("standings", "champions", "h2h", "pvp", "records"):
        assert f'id="{section_id}"' in html
    assert "const DATA =" in html
    assert "renderTable" in html   # standings JS still shipped
```

- [ ] **Step 2: Run it — passes now (baseline), must still pass after refactor**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py::test_output_has_all_sections_and_data -v`
Expected: PASS (this is the invariant the refactor must preserve).

- [ ] **Step 3: Refactor `dashboard.py`**

Replace the single `_HTML_TEMPLATE = """…"""` with three constants. Mechanically:
1. Cut the CSS between `<style>` and `</style>` into `_CSS = r"""…"""` (a raw triple-quoted string). **Un-double every `{{`→`{` and `}}`→`}`** in that CSS (they were doubled only to survive `.format()`).
2. Cut the JS between `<script>` and `</script>` into `_JS = r"""…"""`, un-doubling braces the same way. Replace the `const DATA = {data_json};` line with `const DATA = __DATA_JSON__;`.
3. What remains (doctype/head/body skeleton with header, nav, empty section containers) becomes `_SKELETON = """…"""` with `<style>__CSS__</style>`, `<script>__JS__</script>`, and `{league_name}`/`{year_range}` swapped to `__LEAGUE_NAME__`/`__YEAR_RANGE__`. Un-double any remaining braces here too.

Then rewrite `build_dashboard`'s assembly (replace the `_HTML_TEMPLATE.format(...)` call):

```python
    data_json = json.dumps(stats, separators=(",", ":"))
    js = _JS.replace("__DATA_JSON__", data_json)
    html = (
        _SKELETON
        .replace("__CSS__", _CSS)
        .replace("__JS__", js)
        .replace("__LEAGUE_NAME__", league_name)
        .replace("__YEAR_RANGE__", year_range)
    )
```

(Use `.replace` not `.format`, so `{`/`}` in CSS/JS need no escaping ever again. `data_json` is injected last-ish but before `__CSS__`/others — order of these independent replaces doesn't matter since the markers are unique.)

- [ ] **Step 4: Run the full test file — all green, output still intact**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v`
Expected: 4 passed.

- [ ] **Step 5: Sanity-regenerate one real dashboard from cache and eyeball it is unchanged**

Run: `source .venv/bin/activate && python main.py dashboard 0 hey --provider sleeper --output /tmp/hey_refactor.html && python -c "print('OK', len(open('/tmp/hey_refactor.html').read()))"`
Expected: prints `OK <bytes>`. Open `/tmp/hey_refactor.html` — it should look identical to the current `docs/hey/index.html` (refactor is cosmetic-neutral).

- [ ] **Step 6: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "refactor: split dashboard template into _CSS/_JS/_SKELETON, drop format() escaping"
```

---

## Task 3: Design system + shell (fonts, tokens, topbar, hybrid nav, base cards/tables)

Rewrite `_CSS` with the pick'em design system and `_SKELETON`'s head + header + nav; wire the mobile tab bar to the existing `show()` switcher.

**Files:**
- Modify: `dashboard.py` (`_CSS`, `_SKELETON`, and the `show()` function inside `_JS`)

**Interfaces:**
- Consumes: refactored constants from Task 2.
- Produces: `.topbar`, `.pill-nav`/`.pill-nav a`, `.tabbar`/`.tabbar a` markup + `show(id)` updating `aria-current`/`.active` on **both** the desktop pills and the bottom-bar items.

- [ ] **Step 1: Add reskin marker tests**

Add to `tests/test_dashboard.py`:

```python
def test_shell_uses_pickem_design_system(tmp_path):
    html = _build_html(tmp_path)
    assert "Archivo" in html and "Manrope" in html
    assert "#FFC24B" in html            # gold token
    assert "#0A0D16" in html            # charcoal bg token
    assert 'class="topbar"' in html
    assert 'class="tabbar"' in html     # mobile bottom bar
    assert "prefers-reduced-motion" in html
```

- [ ] **Step 2: Run — fails on current look**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py::test_shell_uses_pickem_design_system -v`
Expected: FAIL (no `#FFC24B`/`tabbar` yet).

- [ ] **Step 3: Replace `_CSS` with the design system**

Set `_CSS` to the following (base system; per-section rules are appended in Tasks 4–8). Port additional component rules (`.btn-primary`, `.pill-select`, `input/select`, `.empty`, `.flash`) from `nfl_pickem_app/app/static/css/style.css` verbatim where the dashboard uses them.

```css
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0A0D16;--bg-glow:#121a2e;--surface:#141a26;--surface-2:#1B2331;--surface-3:#232d3d;
  --border:#262f40;--border-soft:#1d2534;
  --text:#F4F7FB;--text-muted:#AEB8C9;--text-dim:#8B96A9;
  --gold:#FFC24B;--gold-deep:#E2A02E;--gold-glow:rgba(255,194,75,.16);
  --success:#35D07F;--success-dim:rgba(53,208,127,.14);--danger:#FF5C6C;--danger-dim:rgba(255,92,108,.14);
  --fd:'Archivo',system-ui,sans-serif;--fb:'Manrope',system-ui,-apple-system,sans-serif;
  --radius:14px;--radius-sm:10px;--pill:999px;
  --shadow:0 6px 24px -8px rgba(0,0,0,.6);--tabbar-h:64px;--maxw:1100px;
}
html{font-size:100%;-webkit-text-size-adjust:100%}
body{font-family:var(--fb);line-height:1.55;color:var(--text);min-height:100vh;
  background:radial-gradient(1100px 460px at 50% -180px,var(--bg-glow),transparent 70%),var(--bg);
  background-attachment:fixed;-webkit-font-smoothing:antialiased;font-feature-settings:'tnum' 1;
  padding-bottom:calc(var(--tabbar-h) + 1rem)}
@media(min-width:720px){body{padding-bottom:0}}
:focus-visible{outline:2px solid var(--gold);outline-offset:3px;border-radius:4px}
a{color:var(--gold)}
/* topbar */
.topbar{position:sticky;top:0;z-index:40;background:rgba(10,13,22,.82);
  backdrop-filter:saturate(140%) blur(14px);-webkit-backdrop-filter:saturate(140%) blur(14px);
  border-bottom:1px solid var(--border-soft)}
.topbar-inner{max-width:var(--maxw);margin:0 auto;display:flex;align-items:center;justify-content:space-between;
  gap:1rem;min-height:58px;padding:0 1.15rem}
.brand{display:flex;align-items:center;gap:.6rem;text-decoration:none;color:var(--text)}
.brand-mark{width:30px;height:30px;display:grid;place-items:center;border-radius:9px;
  background:linear-gradient(150deg,var(--gold),var(--gold-deep));color:#1a1200;box-shadow:0 4px 14px -3px var(--gold-glow)}
.brand-mark svg{width:18px;height:18px}
.brand-word{font-family:var(--fd);font-weight:900;font-size:1.1rem;letter-spacing:-.02em}
.topbar-meta{font-family:var(--fd);font-weight:700;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text-dim);border:1px solid var(--border);border-radius:var(--pill);padding:.28rem .7rem}
/* desktop pill nav */
.pill-nav{display:none}
@media(min-width:720px){
  .pill-nav{display:flex;gap:.2rem;list-style:none}
  .pill-nav a{display:block;text-decoration:none;color:var(--text-muted);font-weight:700;font-size:.9rem;
    padding:.5rem .85rem;border-radius:var(--pill);transition:color .15s,background .15s;cursor:pointer}
  .pill-nav a:hover{color:var(--text);background:var(--surface-2)}
  .pill-nav a.active{color:#1a1200;background:var(--gold)}
}
/* mobile bottom tab bar */
.tabbar{position:fixed;bottom:0;left:0;right:0;z-index:50;height:calc(var(--tabbar-h) + env(safe-area-inset-bottom));
  padding-bottom:env(safe-area-inset-bottom);display:grid;grid-template-columns:repeat(5,1fr);
  background:rgba(13,17,27,.92);backdrop-filter:saturate(150%) blur(18px);
  -webkit-backdrop-filter:saturate(150%) blur(18px);border-top:1px solid var(--border)}
.tabbar a{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
  text-decoration:none;color:var(--text-dim);font-size:.6rem;font-weight:700;letter-spacing:.02em;
  text-transform:uppercase;position:relative;cursor:pointer}
.tabbar a svg{width:22px;height:22px}
.tabbar a.active{color:var(--gold)}
.tabbar a.active::before{content:"";position:absolute;top:0;width:24px;height:3px;border-radius:0 0 3px 3px;
  background:var(--gold);box-shadow:0 0 12px 1px var(--gold-glow)}
@media(min-width:720px){.tabbar{display:none}}
/* layout + type */
.section{display:none;max-width:var(--maxw);margin:0 auto;padding:1.6rem 1.15rem}
.section.active{display:block;animation:rise .35s ease both}
h2{font-family:var(--fd);font-weight:800;font-size:1.35rem;letter-spacing:-.01em;margin-bottom:1rem}
.eyebrow{font-family:var(--fd);font-weight:800;font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);margin-bottom:.5rem}
/* card + table base */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius);-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.9rem}
thead th{font-family:var(--fd);font-weight:700;font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--text-dim);background:var(--surface-2);border-bottom:1px solid var(--border);white-space:nowrap;
  text-align:left;padding:.72rem .9rem}
tbody td{padding:.72rem .9rem;border-bottom:1px solid var(--border-soft)}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:rgba(255,255,255,.02)}
th.sortable{cursor:pointer;user-select:none}
th.sortable:hover{color:var(--text)}
th.sort-asc::after{content:' ▲';font-size:10px;color:var(--gold)}
th.sort-desc::after{content:' ▼';font-size:10px;color:var(--gold)}
/* shared avatar / pill-select / filter bar */
.avatar{width:28px;height:28px;flex-shrink:0;border-radius:8px;display:grid;place-items:center;
  font-family:var(--fd);font-weight:800;font-size:.72rem;color:#0a0d16;background:var(--av,var(--surface-3))}
.filter-bar{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin-bottom:1.1rem}
.filter-bar label{color:var(--text-dim);font-weight:700;font-size:.8rem;text-transform:uppercase;letter-spacing:.06em}
.pill-select select{appearance:none;-webkit-appearance:none;font-family:var(--fb);font-weight:700;font-size:.9rem;
  color:var(--text);background:var(--surface-2);border:1px solid var(--border);border-radius:var(--pill);
  padding:.5rem 2rem .5rem 1rem;cursor:pointer}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
```

- [ ] **Step 4: Update the `_SKELETON` head + header + nav markup**

In `_SKELETON`, set `<head>` to include the fonts and the swapped `__CSS__`:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0A0D16">
<title>__LEAGUE_NAME__ — League History</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>__CSS__</style>
```

Replace the old `<header>` + `<nav>` with the topbar + desktop pill nav, and add the mobile tab bar just before `</body>` (5 items, icons inline; labels `Standings/Champs/H2H/vs/Records`):

```html
<header class="topbar"><div class="topbar-inner">
  <a class="brand" onclick="show('standings')">
    <span class="brand-mark"><svg viewBox="0 0 24 24" fill="none" stroke="#1a1200" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3M9 18h6M8 21h8M12 16v2"/></svg></span>
    <span class="brand-word">__LEAGUE_NAME__</span>
  </a>
  <ul class="pill-nav">
    <li><a data-tab="standings" class="active" onclick="show('standings')">Standings</a></li>
    <li><a data-tab="champions" onclick="show('champions')">Champions</a></li>
    <li><a data-tab="h2h" onclick="show('h2h')">Head-to-Head</a></li>
    <li><a data-tab="pvp" onclick="show('pvp')">Player vs Player</a></li>
    <li><a data-tab="records" onclick="show('records')">Records</a></li>
  </ul>
  <span class="topbar-meta">__YEAR_RANGE__</span>
</div></header>
```

Bottom bar before `</body>` — each item has a matching `data-tab` and an inline `<svg>` (all `viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`):

```html
<nav class="tabbar">
  <a data-tab="standings" class="active" onclick="show('standings')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>Standings</a>
  <a data-tab="champions" onclick="show('champions')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3M9 18h6M8 21h8M12 16v2"/></svg>Champs</a>
  <a data-tab="h2h" onclick="show('h2h')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h7v10H4zM13 7h7v10h-7z"/></svg>H2H</a>
  <a data-tab="pvp" onclick="show('pvp')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/><path d="M3 20a5 5 0 0 1 10 0M13 20a5 5 0 0 1 8-3.5"/></svg>vs</a>
  <a data-tab="records" onclick="show('records')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V11M10 20V5M16 20v-6M22 20H2"/></svg>Records</a>
</nav>
```

- [ ] **Step 5: Update `show(id)` in `_JS` to sync both navs**

Replace the body of `show(id)` so it toggles `.active` on every `[data-tab]` (pills **and** tab-bar) plus the sections:

```javascript
function show(id){
  document.querySelectorAll('.section').forEach(s=>s.classList.toggle('active', s.id===id));
  document.querySelectorAll('[data-tab]').forEach(t=>t.classList.toggle('active', t.dataset.tab===id));
  window.scrollTo(0,0);
}
```

- [ ] **Step 6: Run marker + regression tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v`
Expected: all passed (pipeline guards + new shell markers).

- [ ] **Step 7: Regenerate `hey` from cache and eyeball the shell**

Run: `source .venv/bin/activate && python main.py dashboard 0 hey --provider sleeper`
Open `docs/hey/index.html`: topbar with brand + year chip, gold pills on desktop, bottom tab bar under 720px, sections still switch, tables carry the new dark card look.

- [ ] **Step 8: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: pick'em design system + hybrid topbar/tab-bar nav for dashboard"
```

---

## Task 4: Standings leaderboard restyle

**Files:**
- Modify: `dashboard.py` (`renderRow`/`renderTable`/`renderExpandRow` in `_JS`; append standings CSS to `_CSS`)

**Interfaces:**
- Consumes: `DATA.alltime` rows `{manager,wins,losses,ties,pf,pa,win_pct,titles,playoff_apps,rank,season_records}`; `ACTIVE` set.
- Produces: rows with `.player-cell`/`.avatar`/`.rank-1`/`.crown`/`tr.leader`.

- [ ] **Step 1: Add marker test**

```python
def test_standings_has_leaderboard_styling(tmp_path):
    html = _build_html(tmp_path)
    assert "player-cell" in html and "class=\"avatar\"" in html.replace("'", '"')
    assert "rank-1" in html
```

- [ ] **Step 2: Run — FAIL**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py::test_standings_has_leaderboard_styling -v` → FAIL.

- [ ] **Step 3: Rewrite the standings row template literals**

In `renderRow` (and the sorted-render branch), emit for each row: a rank cell (`class="rank rank-1"` when `r.rank===1`), a name cell:

```javascript
const initials = r.manager.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
const crown = r.titles>0 ? ` <svg class="crown" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M5 8l4 4 3-6 3 6 4-4-2 10H7z"/></svg>` : '';
// name cell:
`<td><span class="player-cell"><span class="avatar" style="--av:${'{avatarColor(r.manager)}'}">${'{initials}'}</span><span class="player-name">${'{r.manager}'}${'{crown}'}</span></span></td>`
```

Add a small deterministic color helper near the top of `_JS`:

```javascript
function avatarColor(name){
  const pal=['#FFC24B','#35D07F','#7B9BFF','#FF8DA1','#B79BFF','#F5A05A','#2CC5C5','#E0483F'];
  let h=0; for(const c of name) h=(h*31+c.charCodeAt(0))>>>0;
  return pal[h%pal.length];
}
```

Give the `#1` row `class="leader"` on its `<tr>`. Keep the existing sortable-column and expand-row wiring; only the emitted cell markup/classes change.

- [ ] **Step 4: Append standings CSS to `_CSS`**

```css
.player-cell{display:flex;align-items:center;gap:.6rem}
.player-name{font-weight:700;white-space:nowrap}
.rank{font-family:var(--fd);font-weight:800;color:var(--text-dim);text-align:center;width:2.6rem}
.rank-1{color:var(--gold)}
.crown{color:var(--gold);vertical-align:-2px}
tr.leader td{background:linear-gradient(90deg,var(--gold-glow),transparent 55%)}
.expand-inner{padding:.75rem 1rem;background:var(--bg)}
```

- [ ] **Step 5: Run tests + regenerate + eyeball**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v && python main.py dashboard 0 hey --provider sleeper`
Expected: all pass; `docs/hey/index.html` standings shows avatars, gold #1 row, crown on champions, sort + expand still work.

- [ ] **Step 6: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: restyle standings as leaderboard (avatars, gold leader, crowns)"
```

---

## Task 5: Champions — reigning-champ hero + timeline (Option A)

**Files:**
- Modify: `dashboard.py` (`buildChampions()` in `_JS`; the `#champions` container in `_SKELETON`; append champions CSS)

**Interfaces:**
- Consumes: `DATA.champions` = list (most-recent-first) of `{season,manager,team_name,wins,losses,pf}`; `DATA.alltime` for title counts.
- Produces: `.champ-hero` (index 0) + `.champ-timeline` list.

- [ ] **Step 1: Add marker test**

```python
def test_champions_hero_and_timeline(tmp_path):
    html = _build_html(tmp_path)
    assert "champ-hero" in html
    assert "champ-timeline" in html
```

- [ ] **Step 2: Run — FAIL.** `python -m pytest tests/test_dashboard.py::test_champions_hero_and_timeline -v`

- [ ] **Step 3: Rewrite `buildChampions()`**

Compute a `titlesByManager` map from `DATA.alltime` (`{r.manager: r.titles}`) and an ordinal helper. Render the reigning champ (`DATA.champions[0]`) as a hero card, then the rest (all of `DATA.champions`) as a timeline. Target markup:

```javascript
function ordinal(n){const s=['th','st','nd','rd'],v=n%100;return n+(s[(v-20)%10]||s[v]||s[0]);}
function buildChampions(){
  const champs = DATA.champions; if(!champs.length) return;
  const titles = {}; DATA.alltime.forEach(r=>titles[r.manager]=r.titles);
  const c0 = champs[0];
  const heroTitle = titles[c0.manager] || 1;
  const hero = `<div class="eyebrow">★ ${'{c0.season}'} Champion</div>
    <div class="champ-hero">
      <div class="champ-trophy"><svg viewBox="0 0 24 24" fill="none" stroke="#1a1200" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3M9 18h6M8 21h8M12 16v2"/></svg></div>
      <div class="champ-body">
        <div class="champ-name">${'{c0.manager}'}</div>
        <div class="champ-team">${'{c0.team_name}'}</div>
        <div class="champ-meta"><b>${'{c0.wins}'}–${'{c0.losses}'}</b> · ${'{ordinal(heroTitle)}'} title</div>
      </div>
    </div>`;
  const rows = champs.map(c=>`<div class="champ-yr">
      <span class="champ-yr-year">${'{c.season}'}</span>
      <span class="avatar" style="--av:${'{avatarColor(c.manager)}'}">${'{c.manager.split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase()}'}</span>
      <span class="champ-yr-name">${'{c.manager}'} · <span class="champ-yr-team">${'{c.team_name}'}</span></span>
      <span class="champ-yr-badge">${'{c.wins}'}–${'{c.losses}'}</span>
    </div>`).join('');
  document.getElementById('champions-body').innerHTML =
    hero + `<div class="eyebrow" style="margin-top:1.5rem">Champions by year</div><div class="champ-timeline">${'{rows}'}</div>`;
}
```

Ensure the `#champions` section container in `_SKELETON` has `<div id="champions-body"></div>` (replace whatever grid container it renders into) and that `buildChampions()` still runs at load.

- [ ] **Step 4: Append champions CSS**

```css
.champ-hero{position:relative;overflow:hidden;border:1px solid var(--gold);border-radius:var(--radius);
  background:linear-gradient(135deg,rgba(255,194,75,.14),transparent 55%),var(--surface);
  padding:1.25rem 1.4rem;display:flex;gap:1.1rem;align-items:center}
.champ-trophy{width:64px;height:64px;flex-shrink:0;border-radius:16px;display:grid;place-items:center;
  background:linear-gradient(150deg,var(--gold),var(--gold-deep));box-shadow:0 8px 24px -6px var(--gold-glow)}
.champ-trophy svg{width:34px;height:34px}
.champ-name{font-family:var(--fd);font-weight:900;font-size:1.7rem;letter-spacing:-.02em;line-height:1}
.champ-team{color:var(--gold);font-weight:700;margin:.25rem 0 .35rem}
.champ-meta{color:var(--text-muted);font-size:.9rem}
.champ-meta b{color:var(--text);font-family:var(--fd)}
.champ-timeline{border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;background:var(--surface)}
.champ-yr{display:grid;grid-template-columns:52px 28px 1fr auto;align-items:center;gap:.7rem;
  padding:.6rem .9rem;border-bottom:1px solid var(--border-soft)}
.champ-yr:last-child{border-bottom:none}
.champ-yr-year{font-family:var(--fd);font-weight:800;color:var(--text-dim);font-size:.85rem}
.champ-yr-name{font-weight:700}
.champ-yr-team{color:var(--text-dim);font-weight:500}
.champ-yr-badge{font-family:var(--fd);font-weight:800;font-size:.75rem;color:var(--gold);background:var(--gold-glow);border-radius:var(--pill);padding:.15rem .6rem}
```

- [ ] **Step 5: Run tests + regenerate + eyeball**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v && python main.py dashboard 0 hey --provider sleeper`
Expected: pass; champions tab shows a glowing hero for the latest champ + a year timeline.

- [ ] **Step 6: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: champions hall-of-fame hero card + timeline"
```

---

## Task 6: Head-to-Head — desktop matrix restyle + mobile pick-a-manager list (Option B)

**Files:**
- Modify: `dashboard.py` (`renderH2H()` in `_JS`; `#h2h` container in `_SKELETON`; append H2H CSS)

**Interfaces:**
- Consumes: `DATA.h2h.managers` (list) + `DATA.h2h.matrix` (`{a:{b:{wins,losses,ties}}}`).
- Produces: `.h2h-matrix` (desktop, in a `.table-wrap`) + `.h2h-mobile` (a focal-manager `<select id="h2h-focus">` + `.h2h-list`). A `matchMedia('(max-width:719px)')` branch picks which to build; changing `#h2h-focus` re-renders the list.

- [ ] **Step 1: Add marker test**

```python
def test_h2h_has_matrix_and_mobile_list(tmp_path):
    html = _build_html(tmp_path)
    assert "h2h-matrix" in html
    assert "h2h-focus" in html      # mobile focal-manager selector
    assert "h2h-list" in html
```

- [ ] **Step 2: Run — FAIL.** `python -m pytest tests/test_dashboard.py::test_h2h_has_matrix_and_mobile_list -v`

- [ ] **Step 3: Rewrite `renderH2H()`**

Keep computing from `DATA.h2h.matrix`. Build BOTH views into the DOM (CSS hides one per breakpoint — simplest and keeps the mobile list derived from the same matrix). Add a `recordVerb(w,l)` helper → `Owns` (w≥l+5), `Leads` (w>l), `Even` (w===l), `Trails` (w<l). Matrix cell class from record: `big-win`(w-l≥5), `win`(w>l), `even`(w===l), `lose`(w<l), `self`(diagonal).

```javascript
function recordVerb(w,l){return w>=l+5?'Owns':w>l?'Leads':w===l?'Even':'Trails';}
function verbClass(w,l){return w>=l+5?'v-owns':w>l?'v-leads':w===l?'v-even':'v-trails';}
function renderH2H(){
  const {managers, matrix} = DATA.h2h;
  // ---- desktop matrix ----
  let m = '<table class="h2h-matrix"><thead><tr><th></th>' +
    managers.map(n=>`<th title="${'{n}'}">${'{n.split(" ")[0]}'}</th>`).join('') + '</tr></thead><tbody>';
  managers.forEach(a=>{
    m += `<tr><th class="rowlab">${'{a}'}</th>` + managers.map(b=>{
      if(a===b) return '<td class="self">—</td>';
      const r=matrix[a][b]; const cls = r.wins>=r.losses+5?'big-win':r.wins>r.losses?'win':r.wins===r.losses?'even':'lose';
      return `<td class="${'{cls}'}">${'{r.wins}'}-${'{r.losses}'}</td>`;
    }).join('') + '</tr>';
  });
  m += '</tbody></table>';
  document.getElementById('h2h-matrix-wrap').innerHTML = m;
  // ---- mobile focal list ----
  const sel = document.getElementById('h2h-focus');
  if(!sel.options.length) sel.innerHTML = managers.map(n=>`<option>${'{n}'}</option>`).join('');
  function renderList(){
    const a = sel.value || managers[0];
    document.getElementById('h2h-list').innerHTML = managers.filter(n=>n!==a).map(b=>{
      const r=matrix[a][b];
      return `<div class="h2h-row"><span class="avatar" style="--av:${'{avatarColor(b)}'}">${'{b.split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase()}'}</span>
        <span class="h2h-name">${'{b}'}</span><span class="h2h-rec">${'{r.wins}'}–${'{r.losses}'}</span>
        <span class="h2h-verb ${'{verbClass(r.wins,r.losses)}'}">${'{recordVerb(r.wins,r.losses)}'}</span></div>`;
    }).join('');
  }
  sel.onchange = renderList; renderList();
}
```

Set the `#h2h` container in `_SKELETON` to:

```html
<div id="h2h" class="section"><h2>Head-to-Head</h2>
  <div class="h2h-desktop table-wrap" id="h2h-matrix-wrap"></div>
  <div class="h2h-mobile"><div class="filter-bar"><label for="h2h-focus">Showing</label>
    <span class="pill-select"><select id="h2h-focus"></select></span></div>
    <div class="card" id="h2h-list"></div></div>
</div>
```

- [ ] **Step 4: Append H2H CSS (matrix palette + mobile list + breakpoint show/hide)**

```css
.h2h-mobile{display:block}
.h2h-desktop{display:none}
@media(min-width:720px){.h2h-mobile{display:none}.h2h-desktop{display:block}}
.h2h-matrix{font-size:.72rem;white-space:nowrap}
.h2h-matrix th,.h2h-matrix td{padding:.4rem .55rem;text-align:center;border:1px solid var(--border-soft);font-family:var(--fd);font-weight:700}
.h2h-matrix thead th{color:var(--text-dim);background:var(--surface-2)}
.h2h-matrix .rowlab{position:sticky;left:0;background:var(--surface-2);color:var(--text);text-align:right;z-index:1}
.h2h-matrix td.self{background:var(--bg);color:var(--text-dim)}
.h2h-matrix td.win{background:var(--success-dim);color:var(--success)}
.h2h-matrix td.big-win{background:rgba(53,208,127,.28);color:#7dffb8}
.h2h-matrix td.lose{background:var(--danger-dim);color:var(--danger)}
.h2h-matrix td.even{color:var(--text-dim)}
.h2h-row{display:grid;grid-template-columns:28px 1fr auto auto;align-items:center;gap:.7rem;padding:.6rem .9rem;border-bottom:1px solid var(--border-soft)}
.h2h-row:last-child{border-bottom:none}
.h2h-name{font-weight:700}
.h2h-rec{font-family:var(--fd);font-weight:800}
.h2h-verb{font-family:var(--fd);font-weight:800;font-size:.6rem;text-transform:uppercase;letter-spacing:.04em;padding:.15rem .55rem;border-radius:var(--pill)}
.v-owns,.v-leads{background:var(--success-dim);color:var(--success)}
.v-even{background:var(--surface-2);color:var(--text-dim)}
.v-trails{background:var(--danger-dim);color:var(--danger)}
```

- [ ] **Step 5: Run tests + regenerate + eyeball at both widths**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v && python main.py dashboard 0 hey --provider sleeper`
Expected: pass; wide window shows the colored matrix, a ~375px window shows the focal selector + list; changing the selector re-renders.

- [ ] **Step 6: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: restyle H2H matrix + add mobile pick-a-manager list"
```

---

## Task 7: Player vs Player — versus header restyle

**Files:**
- Modify: `dashboard.py` (the PvP render in `_JS` ~`DATA.h2h.managers`/`matchup_log`; `#pvp` container; append PvP CSS)

**Interfaces:**
- Consumes: existing PvP data (`DATA.h2h.managers`, `DATA.h2h.matrix`, `DATA.h2h.matchup_log`).
- Produces: `.pvp-versus` header (two `.avatar`s + each record) above the existing matchup history list. Behavior/selectors unchanged.

- [ ] **Step 1: Add marker test**

```python
def test_pvp_has_versus_header(tmp_path):
    html = _build_html(tmp_path)
    assert "pvp-versus" in html
```

- [ ] **Step 2: Run — FAIL.** `python -m pytest tests/test_dashboard.py::test_pvp_has_versus_header -v`

- [ ] **Step 3: Add the versus header to the PvP render**

Where the two managers are chosen, before the matchup-history list, render (using `DATA.h2h.matrix[a][b]` for the head-to-head record):

```javascript
const rAB = DATA.h2h.matrix[a][b] || {wins:0,losses:0};
const av = (n)=>`<span class="avatar" style="--av:${'{avatarColor(n)}'}">${'{n.split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase()}'}</span>`;
const versus = `<div class="pvp-versus">
  <div class="pvp-side">${'{av(a)}'}<span class="pvp-mgr">${'{a}'}</span></div>
  <div class="pvp-score">${'{rAB.wins}'}<span class="pvp-dash">–</span>${'{rAB.losses}'}</div>
  <div class="pvp-side pvp-right"><span class="pvp-mgr">${'{b}'}</span>${'{av(b)}'}</div>
</div>`;
```

Prepend `versus` to the existing `#pvp-results` innerHTML (keep the matchup list rendering intact below it).

- [ ] **Step 4: Append PvP CSS**

```css
.pvp-versus{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:1rem;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1rem 1.2rem;margin-bottom:1rem}
.pvp-side{display:flex;align-items:center;gap:.6rem;font-weight:700}
.pvp-right{justify-content:flex-end}
.pvp-score{font-family:var(--fd);font-weight:900;font-size:1.6rem;color:var(--gold)}
.pvp-dash{color:var(--text-dim);margin:0 .25rem}
```

- [ ] **Step 5: Run tests + regenerate + eyeball**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v && python main.py dashboard 0 hey --provider sleeper`
Expected: pass; picking two managers shows a versus header over the history.

- [ ] **Step 6: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: PvP versus header"
```

---

## Task 8: Records — stat cards restyle

**Files:**
- Modify: `dashboard.py` (records render in `_JS` ~`DATA.records`; `#records` container; append records CSS)

**Interfaces:**
- Consumes: `DATA.records` (existing record entries).
- Produces: `.stat-grid` of `.stat-card`s; existing expandable top-N lists kept, restyled with `.rec-expand`.

- [ ] **Step 1: Inspect the exact record keys** so no record type is dropped.

Run: `source .venv/bin/activate && python -c "import json,dashboard as d; s=__import__('tests.test_dashboard',fromlist=['_fixture_seasons'])._fixture_seasons(); print(list(d._compute_records(s).keys()))"`
Expected: prints the record keys (e.g. blowouts, high/low scores, streaks, nemeses…). Map each to a stat card. (If the import path errors, read `_compute_records` in `dashboard.py` directly for its returned dict keys.)

- [ ] **Step 2: Add marker test**

```python
def test_records_uses_stat_cards(tmp_path):
    html = _build_html(tmp_path)
    assert "stat-grid" in html and "stat-card" in html
```

- [ ] **Step 3: Run — FAIL.** `python -m pytest tests/test_dashboard.py::test_records_uses_stat_cards -v`

- [ ] **Step 4: Wrap each record block in a stat card**

Change the records render so the container is `<div class="stat-grid">` and each record renders as:

```javascript
`<div class="stat-card"><h3 class="stat-label">${'{label}'}</h3>
   <div class="stat-value">${'{value}'}</div>
   <div class="stat-sub">${'{subtext}'}</div>
   ${'{expandableListHtmlIfAny}'}</div>`
```

Preserve every record type found in Step 1 and the existing expand-list toggle behavior (keep its JS handler; just update its wrapper class to `.rec-expand`).

- [ ] **Step 5: Append records CSS**

```css
.stat-grid{display:grid;grid-template-columns:1fr;gap:.85rem}
@media(min-width:640px){.stat-grid{grid-template-columns:1fr 1fr}}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1rem 1.1rem;box-shadow:var(--shadow)}
.stat-label{font-family:var(--fd);font-size:.72rem;font-weight:800;color:var(--text-dim);text-transform:uppercase;letter-spacing:.09em;margin-bottom:.5rem}
.stat-value{font-family:var(--fd);font-weight:900;font-size:1.6rem;color:var(--text);line-height:1.1}
.stat-sub{color:var(--gold);font-size:.85rem;margin-top:.2rem}
.rec-expand{margin-top:.75rem;border-top:1px solid var(--border-soft);padding-top:.6rem;font-size:.85rem;color:var(--text-muted)}
```

- [ ] **Step 6: Run tests + regenerate + eyeball**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v && python main.py dashboard 0 hey --provider sleeper`
Expected: pass; Records tab is a grid of stat cards, expand lists still work.

- [ ] **Step 7: Commit**

```bash
git add dashboard.py tests/test_dashboard.py
git commit -m "feat: restyle records as stat cards"
```

---

## Task 9: Regenerate all leagues + full render verification

**Files:**
- Regenerate: `docs/{wheaton,hey,lobos,espn-test}/index.html`

- [ ] **Step 1: Regenerate every league from cache (no network)**

Run each (all use the cached `<slug>_history.json`, so no `--refresh`):

```bash
source .venv/bin/activate
python main.py dashboard 0 hey       --provider sleeper
python main.py dashboard 0 wheaton   --provider sleeper
python main.py dashboard 0 lobos     --provider sleeper
python main.py dashboard 0 espn-test --provider sleeper
```

Expected: each prints "Loading cached history…" and writes its `docs/<slug>/index.html`. (If a slug's cached provider differs, match the `--provider` used previously for that slug; the cache load path ignores provider when the cache exists.)

- [ ] **Step 2: Full test suite green**

Run: `source .venv/bin/activate && python -m pytest tests/test_dashboard.py -v`
Expected: all passed.

- [ ] **Step 3: Render-verify with Playwright MCP (recommended) — for `docs/wheaton/index.html`**

Using the Playwright MCP tools: `browser_navigate` to `file:///Users/balbright/Desktop/claude/keeper_league_tool/docs/wheaton/index.html`, then:
- `browser_snapshot` → confirm topbar, gold pill nav, and a rendered standings table with avatars.
- Click each pill (Champions/H2H/Player vs Player/Records) → confirm the champ hero, the H2H **matrix** (wide), PvP versus header, and records stat cards render.
- `browser_resize` to 375×760 → confirm the bottom **tab bar** shows, and H2H switches to the **focal selector + list**; change the selector and confirm the list updates.

If Playwright MCP is unavailable, open each `docs/<slug>/index.html` manually in a browser and a 375px devtools viewport and verify the same checklist.

- [ ] **Step 4: Spot-check value preservation against the old look**

Pick one league; confirm the reigning champion, the #1 all-time manager, and one H2H record match the pre-reskin dashboard (compare to `git show HEAD~9:docs/<slug>/index.html` rendered, or a value you know). Presentation changed; numbers did not.

- [ ] **Step 5: Commit the regenerated dashboards**

```bash
git add docs/hey/index.html docs/wheaton/index.html docs/lobos/index.html docs/espn-test/index.html
git commit -m "chore: regenerate all league dashboards with pick'em reskin"
```

---

## Notes for the implementer

- **Brace escaping is gone after Task 2** — inside `_CSS`/`_JS` write normal `{ }`. The `${'{...}'}` you see in *this plan's* JS snippets is only to keep template-literal `${…}` from being misread here; in the actual `_JS` source write plain `${expr}` template literals.
- Keep everything inside the single generated file — no external CSS/JS files, only the two Google Fonts `<link>`s.
- Run `python -m pytest tests/test_dashboard.py -v` after every task; the three Task 1 tests are your "didn't break the stats" guard and must never go red.
