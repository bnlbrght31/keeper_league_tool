# Keeper League Tool

A CLI tool for fantasy football keeper league commissioners. Pulls league history, generates keeper cost reports, and builds all-time stats dashboards.

## Features

- **Keeper report** — export end-of-year rosters with draft prices, FAAB costs, and keeper counts to CSV or Google Sheets
- **League history dashboard** — static HTML site with all-time standings, champions, head-to-head matrix, records, and streaks
- **Draft date scheduler** — send availability polls to league members via email and collect responses in Google Sheets
- Supports **Yahoo** and **Sleeper** fantasy platforms

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with your credentials:

```
# Yahoo (required for Yahoo leagues)
YAHOO_CLIENT_ID=your_client_id
YAHOO_CLIENT_SECRET=your_client_secret

# Google (required for Sheets export and schedule features)
# Place google_credentials.json in the project root
```

Yahoo OAuth tokens are cached in `yahoo_token.json` after first login. Google tokens are cached in `google_token.json`.

## Commands

### `report` — Keeper cost export

Pull end-of-year rosters and generate a keeper cost report.

```bash
# Sleeper
python3 main.py report sleeper <league_id> --output keeper_report.csv

# Yahoo
python3 main.py report yahoo <league_id> --season 2025 --output keeper_report.csv

# Export to Google Sheets as well
python3 main.py report sleeper <league_id> --sheets

# Use escalating keeper cost model (base + max(10%, $2)) instead of standard
python3 main.py report sleeper <league_id> --cost-model escalate
```

Output columns: Team, Player, Keeper Count, Draft Price, FAAB Cost

Optional `keeper_overrides.csv` can be placed in the project root to manually override keeper counts for specific players (columns: `Player`, `Keeper Count`).

---

### `dashboard` — League history dashboard

Generate a self-contained HTML dashboard from full league history.

```bash
# Sleeper
python3 main.py dashboard <league_id> <slug> --provider sleeper

# Yahoo
python3 main.py dashboard <league_id> <slug> --season 2025

# Force re-fetch from the platform (skip cache)
python3 main.py dashboard <league_id> <slug> --provider sleeper --refresh
```

- `slug` is a short name used in the output path (`docs/<slug>/index.html`) and URL
- History is cached to `<slug>_history.json` so subsequent runs are instant
- The HTML file is fully self-contained — no server needed, works from any browser

**Dashboard sections:**
- All-time standings (sortable, with per-season expandable rows; filter by active/all managers)
- Champions roll (most recent first, with 🏆/🥈/🥉 medals)
- Head-to-head matrix with nemesis and win streak highlights
- All-time records (highest/lowest single-season scores, longest streaks)

**Publishing to GitHub Pages:**

Put output in `docs/<slug>/` and enable GitHub Pages from the `docs/` folder in your repo settings. Each league gets its own URL: `https://<user>.github.io/<repo>/<slug>/`

---

### `schedule` — Draft date poll

Send an availability poll to league members and collect responses in a Google Sheet.

```bash
python3 main.py schedule \
  --sheet-id <google_sheet_id> \
  --league "League Name" \
  --dates 2026-08-01:2026-08-31 \
  --emails "person1@email.com,person2@email.com" \
  --names "Team 1,Team 2"
```

- `--dates` accepts comma-separated dates or `YYYY-MM-DD:YYYY-MM-DD` ranges
- `--names` is optional; used to label rows in the response tracker

## Project Structure

```
main.py                  # CLI entry point
dashboard.py             # Stats computation + HTML generation
schedule.py              # Draft date poll logic
sheets.py                # Google Sheets export
google_auth.py           # Google OAuth helpers
providers/
  sleeper.py             # Sleeper API: keeper report data
  sleeper_history.py     # Sleeper API: full league history
  yahoo.py               # Yahoo API: keeper report data
  yahoo_history.py       # Yahoo API: full league history
docs/
  <slug>/index.html      # Generated dashboards (served via GitHub Pages)
```
