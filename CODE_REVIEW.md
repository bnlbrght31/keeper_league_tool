# Code Review & Enhancement Ideas — keeper_league_tool (2026-06-14)

_Findings log; no code was changed. Scope: `main.py`, `providers/` (sleeper, yahoo, espn/sleeper/yahoo history), `dashboard.py`, `schedule.py`, `sheets.py`. Secrets (`.env`, `*token.json`, `google_credentials.json`) are correctly gitignored and untracked — good._

## What it does
Commissioner tooling for keeper leagues: pulls end-of-season rosters + draft prices + FAAB + keeper history from Sleeper/Yahoo/ESPN, writes a keeper-cost CSV/Google Sheet, builds a static league-history dashboard, and runs an email draft-date poll (via Apps Script + Gmail).

---

## Bugs / correctness

1. **Keeper count is capped at 2 — diverges from the spec.** `CLAUDE.md` asks for "number of times they have been a keeper… and any prior seasons," but both providers only look back **one** prior season (`providers/sleeper.py:24` `seasons_back=2`; `providers/yahoo.py:319-327` checks only the `renew` league). A player kept 3+ years in a row maxes out at `2`. Make the look-back depth configurable and accumulate a true count.

2. **`--cost-model escalate` is silently ignored for Yahoo.** `cmd_report` only threads `cost_model` into `sleeper.build_report` (`main.py:34`); the Yahoo branch (`main.py:39-41`) calls `yahoo.build_report` with no cost model, and `yahoo._keeper_cost` (`providers/yahoo.py:369`) hard-codes the "standard" formula. So a Yahoo user passing `--cost-model escalate` gets standard costs with no warning.

3. **The $20 "waiver floor" misfires in non-FAAB leagues.** Any `free_agent`/`waiver` add registers in `faab_acquisitions`, and a $0 bid (standard add/drop leagues have no FAAB) still yields `faab_cost = 0`, which `_keeper_cost_standard` treats as `has_faab=True` → `max(0, 20) = $20` (`providers/sleeper.py:220-227`, `providers/sleeper.py:87-102`; same shape in Yahoo `:369-380`). Every player ever add/dropped in a standard league gets a bogus $20 keeper cost. Gate the floor on the league actually using FAAB.

4. **ESPN keeper reports are unimplemented vs. the spec.** `CLAUDE.md` says the tool should work for "Sleeper, Yahoo **and ESPN**," but the `report` subcommand only accepts `sleeper`/`yahoo` (`main.py:172-174`). ESPN exists only as a *history dashboard* provider, not a keeper-cost report.

5. **Yahoo transactions are probably not paginated.** `_get_transactions` issues a single `/transactions;type=add` call (`providers/yahoo.py:254`). Yahoo's API pages results (commonly 25 at a time); a league with many adds will silently lose FAAB data past the first page. Add `start=`/`count=` paging.

---

## Sub-optimal setup

6. **Sleeper re-downloads the full player DB every run.** `fetch_keeper_data` calls `_fetch("/players/nfl")` (`providers/sleeper.py:230`) — a ~15 MB payload — on every `report`. The sibling `auction_draft_assistant` already caches this for 24h; reuse that pattern here.

7. **Dashboard injects manager names via `innerHTML` without escaping.** Names flow into template literals like `` `<th title="${m}">${m.split(' ')[0]}</th>` `` (`dashboard.py:890`, and many `tr.innerHTML = \`…\`` sites). Since dashboards are written to `docs/<slug>/` (publishable to GitHub Pages), a manager/team name containing markup is a stored-XSS vector. Escape values or use `textContent`/`createElement`.

8. **Duplicated/misplaced subcommand comment** in `main.py:210-215`: the *dashboard* parser sits under a "schedule subcommand" header banner (the comment block appears twice). Cosmetic, but confusing.

9. **Clunky manual Yahoo OAuth.** `get_access_token` opens the auth URL and asks the user to paste the full redirect URL (`providers/yahoo.py:91-104`). A tiny `http.server` on the redirect port would capture the `code` automatically.

---

## Enhancement ideas

- **Unify the cost-model layer** across providers (fixes #2) and **add the ESPN keeper report** (#4) so all three platforms reach feature parity with the spec.
- **True cumulative keeper history** (#1): configurable `seasons_back`, accumulate per-player keeper counts across the full league chain.
- **Player-DB cache** (#6) and a **single "all-in-one" command** that emits CSV + Sheet + dashboard in one pass.
- **Unit tests for the pure cost functions** (`_keeper_cost_standard`, `_keeper_cost_escalate`, `_auction_value`) — they're small, branchy, and exactly where the subtle bugs above live.
- **Auto-detect FAAB usage** from league settings to decide whether the $20 floor applies (fixes #3 cleanly).
- **Web UI / served dashboard** instead of static CSV, with sortable keeper-cost tables and "who's a value keeper" highlighting (draft price vs. current ADP).
