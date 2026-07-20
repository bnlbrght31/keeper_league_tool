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
    totals = {}  # manager → {wins, losses, ties, pf, pa, seasons, titles, season_records}

    for s in seasons:
        champ = next((t["manager"] for t in s["standings"] if t["rank"] == 1), None)

        # Championship bracket playoff W/L keyed by team_key
        po_record = {}  # team_key → [wins, losses]
        playoff_team_keys = set()  # teams in the championship bracket (non-consolation)
        for match in s["all_matchups"]:
            if not match["is_playoffs"]:
                continue
            if match.get("is_consolation"):
                continue
            ka, kb = match["key_a"], match["key_b"]
            playoff_team_keys.add(ka)
            playoff_team_keys.add(kb)
            for k in (ka, kb):
                if k not in po_record:
                    po_record[k] = [0, 0]
            if match["score_a"] > match["score_b"]:
                po_record[ka][0] += 1
                po_record[kb][1] += 1
            elif match["score_b"] > match["score_a"]:
                po_record[kb][0] += 1
                po_record[ka][1] += 1

        for t in s["standings"]:
            m = t["manager"]
            if m not in totals:
                totals[m] = {"manager": m, "wins": 0, "losses": 0, "ties": 0,
                              "pf": 0.0, "pa": 0.0, "seasons": 0, "titles": 0,
                              "playoff_apps": 0, "season_records": []}
            totals[m]["wins"] += t["wins"]
            totals[m]["losses"] += t["losses"]
            totals[m]["ties"] += t["ties"]
            totals[m]["pf"] += t["pf"]
            totals[m]["pa"] += t["pa"]
            totals[m]["seasons"] += 1
            champion = (m == champ)
            if champion:
                totals[m]["titles"] += 1
            made_playoffs = t["team_key"] in playoff_team_keys
            if made_playoffs:
                totals[m]["playoff_apps"] += 1
            po = po_record.get(t["team_key"], None)
            totals[m]["season_records"].append({
                "season": s["season"],
                "team_name": t["name"],
                "wins": t["wins"],
                "losses": t["losses"],
                "ties": t.get("ties", 0),
                "pf": round(t["pf"], 1),
                "pa": round(t["pa"], 1),
                "rank": t["rank"],
                "champion": champion,
                "playoff_app": made_playoffs,
                "po_wins": po[0] if po else None,
                "po_losses": po[1] if po else None,
            })

    rows = []
    for m, d in totals.items():
        played = d["wins"] + d["losses"] + d["ties"]
        d["win_pct"] = round(d["wins"] / played, 3) if played else 0.0
        d["pf"] = round(d["pf"], 1)
        d["pa"] = round(d["pa"], 1)
        d["season_records"].sort(key=lambda r: r["season"])
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
    # matrix[a][b] = {wins, losses, ties} where wins = a beat b
    matrix = {m: {n: {"wins": 0, "losses": 0, "ties": 0} for n in managers if n != m} for m in managers}

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
            else:
                matrix[ma][mb]["ties"] += 1
                matrix[mb][ma]["ties"] += 1

    # Full matchup log for player-vs-player lookup (all matchups including playoffs)
    matchup_log = []
    for s in seasons:
        champ = next((t["manager"] for t in s["standings"] if t["rank"] == 1), None)
        final_week = max(
            (m["week"] for m in s["all_matchups"] if m["is_playoffs"] and not m.get("is_consolation")),
            default=None,
        )
        for match in s["all_matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            if not ma or not mb or ma == mb:
                continue
            is_champ_game = (
                match["is_playoffs"]
                and not match.get("is_consolation")
                and match["week"] == final_week
                and champ in (ma, mb)
            )
            matchup_log.append({
                "season": s["season"],
                "week": match["week"],
                "ma": ma,
                "mb": mb,
                "sa": match["score_a"],
                "sb": match["score_b"],
                "playoffs": match["is_playoffs"],
                "consolation": match.get("is_consolation", False),
                "championship": is_champ_game,
            })
    matchup_log.sort(key=lambda m: (m["season"], m["week"]))

    # Nemesis: opponent each manager has the worst record against (min win%)
    nemeses = {}
    for m in managers:
        best_nemesis = None
        worst_pct = 1.1
        for opp, rec in matrix[m].items():
            total = rec["wins"] + rec["losses"] + rec["ties"]
            if total < 3:
                continue
            pct = rec["wins"] / total
            if pct < worst_pct:
                worst_pct = pct
                best_nemesis = opp
        nemeses[m] = {"nemesis": best_nemesis, "win_pct": round(worst_pct, 3) if best_nemesis else None}

    streaks = _compute_h2h_streaks(seasons, k2m)
    return {"managers": managers, "matrix": matrix, "nemeses": nemeses, "streaks": streaks, "matchup_log": matchup_log}


def _compute_h2h_streaks(seasons, k2m):
    # Collect all regular-season matchups ordered by (season, week)
    ordered = []
    for s in seasons:
        for match in s["matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            if not ma or not mb or ma == mb:
                continue
            if match["score_a"] > match["score_b"]:
                ordered.append((s["season"], match["week"], ma, mb))
            elif match["score_b"] > match["score_a"]:
                ordered.append((s["season"], match["week"], mb, ma))
    ordered.sort(key=lambda x: (x[0], x[1]))

    # Group by pair, preserving chronological order
    pair_games = {}  # (a,b) canonical sorted → [(winner, loser), ...]
    for _, _, winner, loser in ordered:
        key = tuple(sorted([winner, loser]))
        pair_games.setdefault(key, []).append((winner, loser))

    # Store per-pair data so the JS can recompute top-5 and per-manager
    # summaries dynamically after filtering to active players.
    pair_streaks = []  # {manager, vs, alltime, active_wins}

    for (a, b), games in pair_games.items():
        # All-time max streak per direction
        max_streak = {a: 0, b: 0}
        cur_winner, cur_len = None, 0
        for winner, _ in games:
            if winner == cur_winner:
                cur_len += 1
            else:
                cur_winner, cur_len = winner, 1
            if cur_len > max_streak[winner]:
                max_streak[winner] = cur_len

        # Current (active) streak
        active_wins = {a: 0, b: 0}
        cur_winner, cur_len = None, 0
        for winner, _ in reversed(games):
            if cur_winner is None:
                cur_winner, cur_len = winner, 1
            elif winner == cur_winner:
                cur_len += 1
            else:
                break
        active_wins[cur_winner] = cur_len

        for mgr in (a, b):
            opp = b if mgr == a else a
            pair_streaks.append({
                "manager": mgr,
                "vs": opp,
                "alltime": max_streak[mgr],
                "active_wins": active_wins[mgr],
            })

    return {"pair_streaks": pair_streaks}


def _compute_records(seasons):
    k2m = _build_key_to_manager(seasons)

    score_entries = []   # all individual weekly scores
    margin_entries = []  # all matchup margins
    season_entries = []  # all manager-seasons

    for s in seasons:
        yr = s["season"]
        for match in s["matchups"]:
            ma = k2m.get(match["key_a"])
            mb = k2m.get(match["key_b"])
            sa, sb = match["score_a"], match["score_b"]
            wk = match["week"]

            for mgr, score, name in [(ma, sa, match["team_a"]), (mb, sb, match["team_b"])]:
                if mgr and score > 0:
                    score_entries.append({"score": score, "manager": mgr, "team": name, "season": yr, "week": wk})

            if ma and mb and sa > 0 and sb > 0:
                margin = abs(sa - sb)
                winner_mgr = ma if sa > sb else mb
                loser_mgr  = mb if sa > sb else ma
                margin_entries.append({
                    "margin": round(margin, 2),
                    "winner": winner_mgr,
                    "loser":  loser_mgr,
                    "score_w": round(max(sa, sb), 2),
                    "score_l": round(min(sa, sb), 2),
                    "season": yr, "week": wk,
                })

        for t in s["standings"]:
            played = t["wins"] + t["losses"] + t["ties"]
            if played == 0:
                continue
            season_entries.append({
                "manager": t["manager"], "team": t["name"],
                "wins": t["wins"], "losses": t["losses"],
                "pf": t["pf"], "win_pct": round(t["wins"] / played, 3), "season": yr,
            })

    streaks = _compute_streaks(seasons, k2m)

    return {
        "high_week":     sorted(score_entries,  key=lambda x: -x["score"])[:10],
        "low_week":      sorted(score_entries,  key=lambda x:  x["score"])[:10],
        "blowouts":      sorted(margin_entries, key=lambda x: -x["margin"])[:10],
        "closest":       sorted([x for x in margin_entries if x["margin"] > 0], key=lambda x: x["margin"])[:10],
        "best_seasons":  sorted(season_entries, key=lambda x: (-x["win_pct"], -x["pf"]))[:10],
        "worst_seasons": sorted(season_entries, key=lambda x:  (x["win_pct"],  x["pf"]))[:10],
        "streaks": streaks,
    }


def _compute_playoff_report(seasons):
    """
    Only count games on the path to the championship.
    3rd-place, 5th-place, etc. games are skipped because those teams already
    have a loss and are no longer in contenders when those games are played.
    Invariant: titles + po_losses == apps for every manager.
    """
    k2m = _build_key_to_manager(seasons)
    mgr_stats = {}

    def get(mgr):
        if mgr not in mgr_stats:
            mgr_stats[mgr] = {"manager": mgr, "apps": 0, "po_wins": 0,
                               "po_losses": 0, "finals": 0, "titles": 0}
        return mgr_stats[mgr]

    for s in seasons:
        champ = next((t["manager"] for t in s["standings"] if t["rank"] == 1), None)
        non_consol = [m for m in s["all_matchups"]
                      if m["is_playoffs"] and not m.get("is_consolation")]
        if not non_consol:
            continue

        playoff_weeks = sorted({m["week"] for m in non_consol})
        final_week = playoff_weeks[-1]

        # Everyone who appears in any non-consolation game starts as a contender
        contenders = set()
        for match in non_consol:
            for key in (match["key_a"], match["key_b"]):
                mgr = k2m.get(key)
                if mgr:
                    contenders.add(mgr)

        for mgr in contenders:
            get(mgr)["apps"] += 1

        # Walk weeks in order; skip games where either team already has a loss
        for week in playoff_weeks:
            eliminated = set()
            for match in [m for m in non_consol if m["week"] == week]:
                ma = k2m.get(match["key_a"])
                mb = k2m.get(match["key_b"])
                if not ma or not mb:
                    continue
                if ma not in contenders or mb not in contenders:
                    continue  # placement game — both teams already lost once

                sa, sb = match["score_a"], match["score_b"]
                winner = ma if sa > sb else (mb if sb > sa else None)
                loser  = mb if sa > sb else (ma if sb > sa else None)
                if winner:
                    get(winner)["po_wins"] += 1
                if loser:
                    get(loser)["po_losses"] += 1
                    eliminated.add(loser)

                # Both remaining contenders meeting in the final week = championship game
                if week == final_week:
                    get(ma)["finals"] += 1
                    get(mb)["finals"] += 1

            contenders -= eliminated

        # If multiple contenders remain after all weeks (tied championship score),
        # use standings to settle: champion wins, others take the loss
        if len(contenders) > 1 and champ:
            for mgr in contenders:
                if mgr == champ:
                    get(mgr)["po_wins"] += 1
                else:
                    get(mgr)["po_losses"] += 1

        if champ:
            get(champ)["titles"] += 1

    rows = list(mgr_stats.values())
    for r in rows:
        total = r["po_wins"] + r["po_losses"]
        r["po_pct"] = round(r["po_wins"] / total, 3) if total else 0.0
    rows.sort(key=lambda r: (-r["apps"], -r["po_pct"], -r["titles"]))
    return rows


def _compute_streaks(seasons, k2m):
    """
    Find top-10 win and loss streaks across all managers.
    Each distinct non-overlapping streak is its own entry, so one manager
    can appear multiple times. Each entry includes the season range.
    """
    results = []  # (season, week, manager, won)
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

    # Per-manager games in chronological order, keeping season info
    mgr_games = {}
    for yr, _wk, mgr, won in results:
        mgr_games.setdefault(mgr, []).append((yr, won))

    win_streaks  = []
    loss_streaks = []

    for mgr, games in mgr_games.items():
        cur_type = None
        cur_seasons = []

        def flush():
            if not cur_seasons:
                return
            start, end = cur_seasons[0], cur_seasons[-1]
            years = str(start) if start == end else f"{start}–{end}"
            entry = {"manager": mgr, "length": len(cur_seasons), "years": years}
            (win_streaks if cur_type else loss_streaks).append(entry)

        for yr, won in games:
            if cur_type is None or won == cur_type:
                cur_seasons.append(yr)
                cur_type = won
            else:
                flush()
                cur_seasons = [yr]
                cur_type = won
        flush()

    win_streaks.sort(key=lambda x: -x["length"])
    loss_streaks.sort(key=lambda x: -x["length"])
    return {"win": win_streaks[:10], "loss": loss_streaks[:10]}


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_CSS = r"""
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
.filter-bar select{font-family:var(--fb);font-weight:700;font-size:.9rem;color:var(--text);
  background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:.5rem .9rem;cursor:pointer}
.filter-bar select:hover{border-color:var(--surface-3)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
/* standings leaderboard */
.player-cell{display:flex;align-items:center;gap:.6rem}
.player-name{font-weight:700;white-space:nowrap}
.rank{font-family:var(--fd);font-weight:800;color:var(--text-dim);text-align:center;width:2.6rem}
.rank-1{color:var(--gold)}
.crown{color:var(--gold);vertical-align:-2px}
tr.leader td{background:linear-gradient(90deg,var(--gold-glow),transparent 55%)}
.expand-inner{padding:.75rem 1rem;background:var(--bg)}

/* champions: reigning-champ hero + year timeline */
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

/* Head-to-Head: desktop matrix / mobile focal list responsive split */
.h2h-mobile{display:block}
.h2h-desktop{display:none}
@media(min-width:720px){.h2h-mobile{display:none}.h2h-desktop{display:block}}
.matrix-wrap{overflow-x:auto}
.h2h-matrix{width:auto;font-size:.72rem;white-space:nowrap}
.h2h-matrix th,.h2h-matrix td{padding:.4rem .55rem;text-align:center;border:1px solid var(--border-soft);font-family:var(--fd);font-weight:700;color:var(--text)}
.h2h-matrix th{color:var(--text-dim);background:var(--surface-2)}
.h2h-matrix .row-label{position:sticky;left:0;z-index:1;background:var(--surface-2);color:var(--text);text-align:right}
.h2h-matrix td.self{background:var(--bg);color:var(--text-dim)}
.h2h-matrix td.even{color:var(--text-dim)}
.h2h-matrix td.winning{background:var(--success-dim);color:var(--success)}
.h2h-matrix td.dominant{background:rgba(53,208,127,.28);color:#7dffb8}
.h2h-matrix td.losing{background:var(--danger-dim);color:var(--danger)}
.h2h-matrix td.dominated{background:rgba(255,92,108,.28);color:#ffb3bb}
/* Mobile focal-manager list */
.h2h-row{display:grid;grid-template-columns:28px 1fr auto auto;align-items:center;gap:.7rem;padding:.6rem .9rem;border-bottom:1px solid var(--border-soft)}
.h2h-row:last-child{border-bottom:none}
.h2h-name{font-weight:700;color:var(--text)}
.h2h-rec{font-family:var(--fd);font-weight:800;font-variant-numeric:tabular-nums}
.h2h-verb{font-family:var(--fd);font-weight:800;font-size:.6rem;text-transform:uppercase;letter-spacing:.04em;padding:.2rem .55rem;border-radius:var(--pill)}
.v-owns,.v-leads{background:var(--success-dim);color:var(--success)}
.v-even{background:var(--surface-2);color:var(--text-dim)}
.v-trails{background:var(--danger-dim);color:var(--danger)}
/* Player vs Player versus header */
.pvp-versus{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:1rem;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1rem 1.2rem;margin-bottom:1rem}
.pvp-side{display:flex;align-items:center;gap:.6rem;font-weight:700}
.pvp-right{justify-content:flex-end}
.pvp-score{font-family:var(--fd);font-weight:900;font-size:1.6rem;color:var(--gold)}
.pvp-dash{color:var(--text-dim);margin:0 .25rem}
/* Records — stat cards */
.stat-grid{display:grid;grid-template-columns:1fr;gap:.85rem}
@media(min-width:640px){.stat-grid{grid-template-columns:1fr 1fr}}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1rem 1.1rem;box-shadow:var(--shadow)}
.stat-label{font-family:var(--fd);font-size:.72rem;font-weight:800;color:var(--text-dim);text-transform:uppercase;letter-spacing:.09em;margin-bottom:.5rem}
.stat-value{font-family:var(--fd);font-weight:900;font-size:1.6rem;color:var(--text);line-height:1.1}
.stat-sub{color:var(--gold);font-size:.85rem;margin-top:.2rem}
.rec-detail{color:var(--text-dim);font-size:.8rem;margin-top:.2rem}
.rec-expand{margin-top:.75rem;border-top:1px solid var(--border-soft);padding-top:.6rem;font-size:.85rem;color:var(--text-muted)}
.rec-expand-btn{cursor:pointer;font-weight:700;color:var(--gold);user-select:none}
.rec-expand-btn:hover{color:var(--gold-deep)}
.rec-expand-list{margin-top:.5rem;display:flex;flex-direction:column;gap:.4rem}
.rec-expand-row{padding:.3rem 0;border-bottom:1px solid var(--border-soft);color:var(--text-muted)}
.rec-expand-row:last-child{border-bottom:none}
.rec-expand-rank{font-family:var(--fd);font-weight:800;color:var(--text-dim);margin-right:.5rem}
"""

_JS = r"""
const DATA = __DATA_JSON__;
const ACTIVE = new Set(DATA.active_managers);

// Deterministic name → color for avatar chips. Shared by all render functions
// across sections (standings, champions, h2h, pvp, records).
function avatarColor(name) {
  const pal = ['#FFC24B','#35D07F','#7B9BFF','#FF8DA1','#B79BFF','#F5A05A','#2CC5C5','#E0483F'];
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return pal[h % pal.length];
}

function activeFilter(selectId) {
  const sel = document.getElementById(selectId);
  return sel && sel.value === 'active' ? ACTIVE : null;
}

function show(id){
  document.querySelectorAll('.section').forEach(s=>s.classList.toggle('active', s.id===id));
  document.querySelectorAll('[data-tab]').forEach(t=>t.classList.toggle('active', t.dataset.tab===id));
  window.scrollTo(0,0);
}

// ── Standings ──────────────────────────────────────────────────────────────
(function buildStandings() {
  // Build season lookup: year → manager → season_record
  const seasonLookup = {};
  DATA.alltime.forEach(r => {
    r.season_records.forEach(sr => {
      if (!seasonLookup[sr.season]) seasonLookup[sr.season] = {};
      seasonLookup[sr.season][r.manager] = {...sr, manager: r.manager};
    });
  });

  // Populate season dropdown (most recent first, exclude seasons with no games)
  const seasons = Object.keys(seasonLookup)
    .map(Number)
    .filter(y => Object.values(seasonLookup[y]).some(sr => sr.wins + sr.losses > 0))
    .sort((a, b) => b - a);
  const seasonSel = document.getElementById('season-filter');
  seasons.forEach(y => {
    const opt = document.createElement('option');
    opt.value = y; opt.textContent = y;
    seasonSel.appendChild(opt);
  });

  let sortKey = 'win_pct', sortDir = -1;

  function renderExpandRow(r, ncols) {
    const tr = document.createElement('tr');
    tr.className = 'expand-row';
    function finishBadge(s) {
      if (s.champion) return '🏆';
      if (s.rank === 2) return '🥈';
      if (s.rank === 3) return '🥉';
      return s.rank > 0 ? '#' + s.rank : '—';
    }
    function poCell(s) {
      if (s.po_wins === null) return '<td class="neutral">—</td>';
      return `<td>${s.po_wins}–${s.po_losses}</td>`;
    }
    const seasonRows = [...r.season_records].reverse().filter(s => s.wins + s.losses > 0).map(s => `
      <tr>
        <td>${s.season}</td>
        <td class="win">${s.wins}</td>
        <td class="loss">${s.losses}</td>
        ${s.ties > 0 ? `<td class="neutral">${s.ties}</td>` : '<td class="neutral">—</td>'}
        <td>${s.pf.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
        <td class="neutral">${s.pa.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
        ${poCell(s)}
        <td>${finishBadge(s)}</td>
      </tr>`).join('');
    tr.innerHTML = `<td colspan="${ncols}"><div class="expand-inner">
      <table>
        <thead><tr><th>Season</th><th>RS W</th><th>RS L</th><th>T</th><th>PF</th><th>PA</th><th>Playoffs</th><th>Finish</th></tr></thead>
        <tbody>${seasonRows}</tbody>
      </table></div></td>`;
    return tr;
  }

  function renderRow(r, i, ncols) {
    const tr = document.createElement('tr');
    tr.style.cursor = 'pointer';
    if (r.rank === 1) tr.classList.add('leader');
    const initials = r.manager.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
    const crown = r.titles > 0 ? ` <svg class="crown" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M5 8l4 4 3-6 3 6 4-4-2 10H7z"/></svg>` : '';
    tr.innerHTML = `
      <td class="rank${r.rank === 1 ? ' rank-1' : ''}">${i + 1}</td>
      <td><span class="player-cell"><span class="avatar" style="--av:${avatarColor(r.manager)}">${initials}</span><span class="player-name">${r.manager}${crown}</span></span></td>
      <td class="neutral">${r.seasons}</td>
      <td class="win">${r.wins}</td>
      <td class="loss">${r.losses}</td>
      <td class="neutral">${r.ties > 0 ? r.ties : '—'}</td>
      <td class="pct">${(r.win_pct*100).toFixed(1)}%</td>
      <td>${r.pf.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
      <td class="neutral">${r.pa.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
      <td class="neutral">${r.playoff_apps > 0 ? r.playoff_apps : '—'}</td>
      <td>${r.titles > 0 ? r.titles : '—'}</td>
    `;
    tr.addEventListener('click', () => {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('expand-row')) {
        next.remove();
      } else {
        tr.insertAdjacentElement('afterend', renderExpandRow(r, ncols));
      }
    });
    return tr;
  }

  window.renderTable = function() {
    const flt = activeFilter('standings-filter');
    const seasonVal = document.getElementById('season-filter').value;
    const isSeason = seasonVal !== 'all';
    const thead = document.querySelector('#standings-tbl thead tr');

    if (isSeason) {
      // Single-season mode: swap column headers
      thead.cells[2].textContent = 'Team';
      thead.cells[9].textContent = 'Made PO';
      thead.cells[10].textContent = 'Finish';
      // Disable sort on those two cols
      thead.cells[2].classList.remove('sortable');
      thead.cells[9].classList.remove('sortable');
      thead.cells[10].classList.remove('sortable');

      const srMap = seasonLookup[parseInt(seasonVal)] || {};
      const rows = Object.values(srMap)
        .filter(sr => sr.wins + sr.losses > 0)
        .filter(sr => !flt || flt.has(sr.manager))
        .sort((a, b) => (a.rank || 99) - (b.rank || 99) || b.pf - a.pf);

      const tbody = document.querySelector('#standings-tbl tbody');
      tbody.innerHTML = '';
      rows.forEach((sr, i) => {
        const tr = document.createElement('tr');
        if (sr.rank === 1) tr.classList.add('leader');
        function finishBadge(sr) {
          if (sr.champion) return '🏆';
          if (sr.rank === 2) return '🥈';
          if (sr.rank === 3) return '🥉';
          return sr.rank > 0 ? '#' + sr.rank : '—';
        }
        const initials = sr.manager.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
        const crown = sr.champion ? ` <svg class="crown" viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M5 8l4 4 3-6 3 6 4-4-2 10H7z"/></svg>` : '';
        tr.innerHTML = `
          <td class="rank${sr.rank === 1 ? ' rank-1' : ''}">${i + 1}</td>
          <td><span class="player-cell"><span class="avatar" style="--av:${avatarColor(sr.manager)}">${initials}</span><span class="player-name">${sr.manager}${crown}</span></span></td>
          <td class="neutral" style="font-size:12px">${sr.team_name}</td>
          <td class="win">${sr.wins}</td>
          <td class="loss">${sr.losses}</td>
          <td class="neutral">${sr.ties > 0 ? sr.ties : '—'}</td>
          <td class="pct">${(sr.wins/(sr.wins+sr.losses+(sr.ties||0))*100).toFixed(1)}%</td>
          <td>${sr.pf.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
          <td class="neutral">${sr.pa.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})}</td>
          <td class="neutral">${sr.playoff_app ? '✓' : '—'}</td>
          <td>${finishBadge(sr)}</td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      // All-time mode: restore column headers
      thead.cells[2].textContent = 'Seasons';
      thead.cells[9].textContent = 'Playoffs';
      thead.cells[10].textContent = 'Titles';
      thead.cells[2].classList.add('sortable');
      thead.cells[9].classList.add('sortable');
      thead.cells[10].classList.add('sortable');

      const sorted = [...DATA.alltime]
        .filter(r => !flt || flt.has(r.manager))
        .sort((a, b) => {
          const av = a[sortKey], bv = b[sortKey];
          return typeof av === 'string' ? av.localeCompare(bv) * sortDir : (av - bv) * sortDir;
        });
      const tbody = document.querySelector('#standings-tbl tbody');
      const ncols = document.querySelectorAll('#standings-tbl thead th').length;
      tbody.innerHTML = '';
      sorted.forEach((r, i) => tbody.appendChild(renderRow(r, i, ncols)));
    }
  };

  document.querySelectorAll('#standings-tbl th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (sortKey === key) { sortDir *= -1; }
      else { sortKey = key; sortDir = key === 'manager' ? 1 : -1; }
      document.querySelectorAll('#standings-tbl th').forEach(t => t.classList.remove('sort-asc','sort-desc'));
      th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
      renderTable();
    });
  });

  renderTable();
})();

// ── Champions ──────────────────────────────────────────────────────────────
function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
function buildChampions() {
  const champs = DATA.champions;
  if (!champs.length) return;
  const titles = {};
  DATA.alltime.forEach(r => titles[r.manager] = r.titles);
  const c0 = champs[0];
  const heroTitle = titles[c0.manager] || 1;
  const hero = `<div class="eyebrow">★ ${c0.season} Champion</div>
    <div class="champ-hero">
      <div class="champ-trophy"><svg viewBox="0 0 24 24" fill="none" stroke="#1a1200" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3M9 18h6M8 21h8M12 16v2"/></svg></div>
      <div class="champ-body">
        <div class="champ-name">${c0.manager}</div>
        <div class="champ-team">${c0.team_name}</div>
        <div class="champ-meta"><b>${c0.wins}–${c0.losses}</b> · ${ordinal(heroTitle)} title</div>
      </div>
    </div>`;
  const rows = champs.map(c => `<div class="champ-yr">
      <span class="champ-yr-year">${c.season}</span>
      <span class="avatar" style="--av:${avatarColor(c.manager)}">${c.manager.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()}</span>
      <span class="champ-yr-name">${c.manager} · <span class="champ-yr-team">${c.team_name}</span></span>
      <span class="champ-yr-badge">${c.wins}–${c.losses}</span>
    </div>`).join('');
  document.getElementById('champions-body').innerHTML =
    hero + `<div class="eyebrow" style="margin-top:1.5rem">Champions by year</div><div class="champ-timeline">${rows}</div>`;
}
buildChampions();

// ── Head-to-Head ───────────────────────────────────────────────────────────
// Record → short verb + matching pill class. Shared by the mobile focal list.
function recordVerb(w, l) { return w >= l + 5 ? 'Owns' : w > l ? 'Leads' : w === l ? 'Even' : 'Trails'; }
function verbClass(w, l) { return w >= l + 5 ? 'v-owns' : w > l ? 'v-leads' : w === l ? 'v-even' : 'v-trails'; }

function renderH2H() {
  const flt = activeFilter('h2h-filter');
  const {managers: allMgrs, matrix, nemeses, streaks} = DATA.h2h;
  const managers = flt ? allMgrs.filter(m => flt.has(m)) : allMgrs;

  // Matrix
  const tbl = document.getElementById('h2h-tbl');
  tbl.innerHTML = '';
  const hdr = document.createElement('tr');
  hdr.innerHTML = '<th></th>' + managers.map(m => `<th title="${m}">${m.split(' ')[0]}</th>`).join('');
  tbl.appendChild(hdr);
  managers.forEach(row => {
    const tr = document.createElement('tr');
    let cells = `<td class="row-label" title="${row}">${row}</td>`;
    managers.forEach(col => {
      if (row === col) { cells += '<td class="self">·</td>'; return; }
      const rec = matrix[row][col];
      const w = rec.wins, l = rec.losses, t = rec.ties || 0, tot = w + l + t;
      if (tot === 0) { cells += '<td class="even">—</td>'; return; }
      const pct = w / tot;
      let cls = 'even';
      if (pct >= .7) cls = 'dominant';
      else if (pct > .5) cls = 'winning';
      else if (pct <= .3) cls = 'dominated';
      else if (pct < .5) cls = 'losing';
      const lbl = t > 0 ? `${w}-${l}-${t}` : `${w}-${l}`;
      cells += `<td class="${cls}" title="${row} vs ${col}: ${lbl}">${lbl}</td>`;
    });
    tr.innerHTML = cells;
    tbl.appendChild(tr);
  });

  // Mobile focal list — one row per other visible manager, derived from the
  // same matrix. Options rebuilt each render so the All/Active filter applies;
  // current selection is preserved when the focal manager is still visible.
  const focus = document.getElementById('h2h-focus');
  const prev = focus.value;
  focus.innerHTML = managers.map(m => `<option>${m}</option>`).join('');
  focus.value = managers.includes(prev) ? prev : (managers[0] || '');
  function renderFocusList() {
    const a = focus.value || managers[0];
    const list = document.getElementById('h2h-list');
    if (!a) { list.innerHTML = ''; return; }
    list.innerHTML = managers.filter(b => b !== a).map(b => {
      const rec = matrix[a][b];
      if (!rec) return '';
      const w = rec.wins, l = rec.losses, t = rec.ties || 0;
      const initials = b.split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase();
      const lbl = t > 0 ? `${w}–${l}–${t}` : `${w}–${l}`;
      return `<div class="h2h-row">
        <span class="avatar" style="--av:${avatarColor(b)}">${initials}</span>
        <span class="h2h-name">${b}</span>
        <span class="h2h-rec">${lbl}</span>
        <span class="h2h-verb ${verbClass(w, l)}">${recordVerb(w, l)}</span></div>`;
    }).join('');
  }
  focus.onchange = renderFocusList;
  renderFocusList();

  // Nemesis — recompute from matrix against visible opponents only
  const ntbody = document.querySelector('#nemesis-tbl tbody');
  ntbody.innerHTML = '';
  managers.forEach(m => {
    let worstOpp = null, worstPct = 1.1;
    managers.forEach(opp => {
      if (opp === m) return;
      const rec = matrix[m][opp];
      if (!rec) return;
      const tot = rec.wins + rec.losses + (rec.ties || 0);
      if (tot < 3) return;
      const pct = rec.wins / tot;
      if (pct < worstPct) { worstPct = pct; worstOpp = opp; }
    });
    if (!worstOpp) return;
    const rec = matrix[m][worstOpp];
    const tr = document.createElement('tr');
    tr.className = 'nemesis-row';
    tr.innerHTML = `
      <td>${m}</td>
      <td style="color:var(--danger);font-weight:700">${worstOpp}</td>
      <td style="color:var(--danger)">${rec.wins}–${rec.losses}${rec.ties ? `–${rec.ties}` : ''} (${(worstPct*100).toFixed(0)}% win rate)</td>
    `;
    ntbody.appendChild(tr);
  });

  // Streaks — recompute from pair_streaks after applying active filter
  const pairs = DATA.h2h.streaks.pair_streaks.filter(
    p => !flt || (flt.has(p.manager) && flt.has(p.vs))
  );

  // Per-manager: best alltime and active streak among filtered opponents
  const pmBest = {}, pmActive = {};
  pairs.forEach(p => {
    if (!pmBest[p.manager] || p.alltime > pmBest[p.manager].length) {
      pmBest[p.manager] = {length: p.alltime, opps: [p.vs]};
    } else if (p.alltime === pmBest[p.manager].length && !pmBest[p.manager].opps.includes(p.vs)) {
      pmBest[p.manager].opps.push(p.vs);
    }
    if (p.active_wins >= 2) {
      if (!pmActive[p.manager] || p.active_wins > pmActive[p.manager].length) {
        pmActive[p.manager] = {length: p.active_wins, opps: [p.vs]};
      } else if (p.active_wins === pmActive[p.manager].length && !pmActive[p.manager].opps.includes(p.vs)) {
        pmActive[p.manager].opps.push(p.vs);
      }
    }
  });

  function oppLabel(rec) {
    if (!rec) return '—';
    if (rec.opps.length === 1) return rec.opps[0];
    return `${rec.opps.length} opponents (${rec.opps.join(', ')})`;
  }

  const pmBody = document.querySelector('#streak-mgr-tbl tbody');
  pmBody.innerHTML = '';
  managers.forEach(m => {
    const best = pmBest[m], act = pmActive[m];
    if (!best) return;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${m}</strong></td>
      <td>${best.length}</td>
      <td style="color:var(--text-dim)">${oppLabel(best)}</td>
      <td>${act ? act.length : '—'}</td>
      <td style="color:var(--text-dim)">${act ? oppLabel(act) : '—'}</td>
    `;
    pmBody.appendChild(tr);
  });

  // Top 5 all-time from filtered pairs
  const top_alltime = [...pairs].sort((a,b) => b.alltime - a.alltime).slice(0,5);
  const atBody = document.querySelector('#streak-alltime-tbl tbody');
  atBody.innerHTML = '';
  top_alltime.forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><strong>${s.manager}</strong></td><td style="color:var(--text-dim)">${s.vs}</td><td style="font-weight:700">${s.alltime}</td>`;
    atBody.appendChild(tr);
  });
  if (!top_alltime.length) atBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-dim)">No data</td></tr>';

  // Top 5 active from filtered pairs
  const top_active = [...pairs].filter(p => p.active_wins >= 2).sort((a,b) => b.active_wins - a.active_wins).slice(0,5);
  const acBody = document.querySelector('#streak-active-tbl tbody');
  acBody.innerHTML = '';
  top_active.forEach(s => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><strong>${s.manager}</strong></td><td style="color:var(--text-dim)">${s.vs}</td><td style="font-weight:700;color:var(--success)">${s.active_wins}</td>`;
    acBody.appendChild(tr);
  });
  if (!top_active.length) acBody.innerHTML = '<tr><td colspan="3" style="color:var(--text-dim)">No active streaks ≥ 2</td></tr>';
}
renderH2H();

// ── Player vs Player ───────────────────────────────────────────────────────
(function initPvP() {
  const mgrs = DATA.h2h.managers;
  const p1sel = document.getElementById('pvp-p1');
  const p2sel = document.getElementById('pvp-p2');
  mgrs.forEach(m => {
    p1sel.insertAdjacentHTML('beforeend', `<option value="${m}">${m}</option>`);
    p2sel.insertAdjacentHTML('beforeend', `<option value="${m}">${m}</option>`);
  });
})();

window.renderPvP = function() {
  const p1 = document.getElementById('pvp-p1').value;
  const p2 = document.getElementById('pvp-p2').value;
  const results = document.getElementById('pvp-results');
  const summary = document.getElementById('pvp-summary');

  if (!p1 || !p2 || p1 === p2) {
    results.innerHTML = '';
    summary.textContent = '';
    return;
  }

  const av = (n)=>`<span class="avatar" style="--av:${avatarColor(n)}">${n.split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase()}</span>`;

  const log = DATA.h2h.matchup_log.filter(
    m => (m.ma === p1 && m.mb === p2) || (m.ma === p2 && m.mb === p1)
  );

  let p1w = 0, p2w = 0, ties = 0;
  log.forEach(m => {
    const p1score = m.ma === p1 ? m.sa : m.sb;
    const p2score = m.ma === p1 ? m.sb : m.sa;
    if (p1score > p2score) p1w++;
    else if (p2score > p1score) p2w++;
    else ties++;
  });

  const versus = `<div class="pvp-versus">
    <div class="pvp-side">${av(p1)}<span class="pvp-mgr">${p1}</span></div>
    <div class="pvp-score">${p1w}<span class="pvp-dash">–</span>${p2w}</div>
    <div class="pvp-side pvp-right"><span class="pvp-mgr">${p2}</span>${av(p2)}</div>
  </div>`;

  if (!log.length) {
    results.innerHTML = versus + '<p style="color:#8b949e">No matchups found between these players.</p>';
    summary.textContent = '';
    return;
  }

  summary.textContent = ties > 0
    ? `${p1}: ${p1w}–${p2w}–${ties} vs ${p2}`
    : `${p1}: ${p1w}–${p2w} vs ${p2}`;

  const rows = log.map(m => {
    const p1score = m.ma === p1 ? m.sa : m.sb;
    const p2score = m.ma === p1 ? m.sb : m.sa;
    const p1wins  = p1score > p2score;
    const isTie   = p1score === p2score;

    let rowStyle = '';
    if (m.championship) rowStyle = 'background:rgba(210,153,34,0.15);outline:1px solid rgba(210,153,34,0.4)';
    else if (p1wins)    rowStyle = 'background:rgba(63,185,80,0.12)';
    else if (!isTie)    rowStyle = 'background:rgba(248,81,73,0.12)';

    let typeLabel = '';
    if (m.championship)      typeLabel = '<span style="color:#d29922;font-weight:700">🏆 Championship</span>';
    else if (m.consolation)  typeLabel = '<span style="color:#8b949e">Consolation</span>';
    else if (m.playoffs)     typeLabel = '<span style="color:#58a6ff">Playoffs</span>';

    const resultIcon = p1wins ? '<span style="color:#3fb950">▲</span>'
                     : isTie  ? '<span style="color:#8b949e">—</span>'
                     :          '<span style="color:#f85149">▼</span>';

    return `<tr style="${rowStyle}">
      <td style="color:#8b949e">${m.season}</td>
      <td style="color:#8b949e">Wk ${m.week}</td>
      <td><strong>${p1}</strong></td>
      <td style="text-align:right;font-weight:700">${p1score.toFixed(2)}</td>
      <td style="text-align:center">${resultIcon}</td>
      <td style="font-weight:700">${p2score.toFixed(2)}</td>
      <td><strong>${p2}</strong></td>
      <td style="text-align:right;font-size:12px">${typeLabel}</td>
    </tr>`;
  }).join('');

  results.innerHTML = versus + `
    <table style="width:100%;border-collapse:collapse">
      <thead><tr>
        <th style="text-align:left">Season</th>
        <th style="text-align:left">Week</th>
        <th style="text-align:left">${p1}</th>
        <th style="text-align:right">Score</th>
        <th></th>
        <th style="text-align:left">Score</th>
        <th style="text-align:left">${p2}</th>
        <th style="text-align:right">Type</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
};

// ── Records ────────────────────────────────────────────────────────────────
(function buildRecords() {
  const rec = DATA.records;
  const grid = document.getElementById('records-grid');

  // Expandable card: items is an array; top entry shown by default, rest revealed on click
  function card(label, items, fmtVal, fmtSub, fmtDetail) {
    if (!items || !items.length) return;
    const d = document.createElement('div');
    d.className = 'stat-card';
    const top = items[0];
    d.innerHTML = `
      <h3 class="stat-label">${label}</h3>
      <div class="stat-value">${fmtVal(top)}</div>
      <div class="stat-sub">${fmtSub(top)}</div>
      ${fmtDetail ? `<div class="rec-detail">${fmtDetail(top)}</div>` : ''}
    `;
    if (items.length > 1) {
      const wrap = document.createElement('div');
      wrap.className = 'rec-expand';
      const btn = document.createElement('div');
      btn.className = 'rec-expand-btn';
      btn.textContent = `▾ see top ${items.length}`;
      const list = document.createElement('div');
      list.className = 'rec-expand-list';
      list.style.display = 'none';
      items.slice(1).forEach((item, i) => {
        const row = document.createElement('div');
        row.className = 'rec-expand-row';
        const detail = fmtDetail ? ' · ' + fmtDetail(item) : '';
        row.innerHTML = `<span class="rec-expand-rank">#${i + 2}</span>${fmtVal(item)} — ${fmtSub(item)}${detail}`;
        list.appendChild(row);
      });
      btn.addEventListener('click', () => {
        const open = list.style.display !== 'none';
        list.style.display = open ? 'none' : '';
        btn.textContent = open ? `▾ see top ${items.length}` : '▴ collapse';
      });
      wrap.appendChild(btn);
      wrap.appendChild(list);
      d.appendChild(wrap);
    }
    grid.appendChild(d);
  }

  card('Highest Single-Week Score', rec.high_week,
    h => h.score.toFixed(2) + ' pts',
    h => h.manager,
    h => `${h.team} · Week ${h.week}, ${h.season}`);

  card('Lowest Single-Week Score', rec.low_week,
    l => l.score.toFixed(2) + ' pts',
    l => l.manager,
    l => `${l.team} · Week ${l.week}, ${l.season}`);

  card('Biggest Blowout', rec.blowouts,
    b => '+' + b.margin.toFixed(2) + ' margin',
    b => b.winner + ' def. ' + b.loser,
    b => `${b.score_w.toFixed(2)}–${b.score_l.toFixed(2)} · Week ${b.week}, ${b.season}`);

  card('Closest Game', rec.closest,
    c => c.margin.toFixed(2) + ' margin',
    c => c.winner + ' def. ' + c.loser,
    c => `${c.score_w.toFixed(2)}–${c.score_l.toFixed(2)} · Week ${c.week}, ${c.season}`);

  card('Best Single Season', rec.best_seasons,
    b => b.wins + '–' + b.losses,
    b => b.manager,
    b => `${b.team} · ${b.season} · ${b.pf.toFixed(1)} pts`);

  card('Worst Single Season', rec.worst_seasons,
    w => w.wins + '–' + w.losses,
    w => w.manager,
    w => `${w.team} · ${w.season} · ${w.pf.toFixed(1)} pts`);

  card('Longest Win Streak',    rec.streaks.win,  s => s.length + ' wins',   s => s.manager + ' (' + s.years + ')');
  card('Longest Losing Streak', rec.streaks.loss, s => s.length + ' losses', s => s.manager + ' (' + s.years + ')');
})();

// ── Playoff Report ─────────────────────────────────────────────────────────
(function buildPlayoffReport() {
  const rows = DATA.playoffs;
  const tbody = document.querySelector('#playoff-report-tbl tbody');
  rows.forEach(r => {
    const tr = document.createElement('tr');
    const poRec = r.po_wins + '–' + r.po_losses;
    const poPct = r.po_wins + r.po_losses > 0
      ? (r.po_pct * 100).toFixed(1) + '%' : '—';
    const trophy = r.titles > 0 ? ' <span style="color:var(--gold)">' + '🏆'.repeat(r.titles) + '</span>' : '';
    tr.innerHTML = `
      <td><strong>${r.manager}</strong></td>
      <td style="text-align:center">${r.apps}</td>
      <td style="text-align:center">${poRec}</td>
      <td style="text-align:center;font-variant-numeric:tabular-nums">${poPct}</td>
      <td style="text-align:center">${r.finals > 0 ? r.finals : '—'}</td>
      <td style="text-align:center">${r.titles > 0 ? r.titles + trophy : '—'}</td>
    `;
    tbody.appendChild(tr);
  });
})();
"""

_SKELETON = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0A0D16">
<title>__LEAGUE_NAME__ — League History</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>__CSS__</style>
</head>
<body>
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

<div id="standings" class="section active">
  <div class="filter-bar">
    <label for="standings-filter">Players:</label>
    <select id="standings-filter" onchange="renderTable()">
      <option value="all">All Players</option>
      <option value="active" selected>Active Players</option>
    </select>
    <label for="season-filter" style="margin-left:12px">Season:</label>
    <select id="season-filter" onchange="renderTable()">
      <option value="all">All Time</option>
    </select>
  </div>
  <h2>All-Time Standings</h2>
  <div class="card">
    <table id="standings-tbl">
      <thead><tr>
        <th></th>
        <th class="sortable" data-key="manager" data-type="str">Manager</th>
        <th class="sortable" data-key="seasons" data-type="num">Seasons</th>
        <th class="sortable" data-key="wins" data-type="num">W</th>
        <th class="sortable" data-key="losses" data-type="num">L</th>
        <th class="sortable" data-key="ties" data-type="num">T</th>
        <th class="sortable sort-desc" data-key="win_pct" data-type="num">Win%</th>
        <th class="sortable" data-key="pf" data-type="num">PF</th>
        <th class="sortable" data-key="pa" data-type="num">PA</th>
        <th class="sortable" data-key="playoff_apps" data-type="num">Playoffs</th>
        <th class="sortable" data-key="titles" data-type="num">Titles</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div id="champions" class="section">
  <h2>Hall of Champions</h2>
  <div id="champions-body"></div>
</div>

<div id="h2h" class="section">
  <div class="filter-bar">
    <label for="h2h-filter">Show:</label>
    <select id="h2h-filter" onchange="renderH2H()">
      <option value="all">All Players</option>
      <option value="active" selected>Active Players</option>
    </select>
  </div>
  <h2>Head-to-Head Records</h2>
  <div class="card matrix-wrap h2h-desktop">
    <table class="matrix h2h-matrix" id="h2h-tbl"></table>
  </div>
  <div class="h2h-mobile">
    <div class="filter-bar">
      <label for="h2h-focus">Manager</label>
      <span class="pill-select"><select id="h2h-focus"></select></span>
    </div>
    <div class="card" id="h2h-list"></div>
  </div>
  <h2 style="margin-top:32px">Nemesis Report</h2>
  <div class="card">
    <table id="nemesis-tbl">
      <thead><tr><th>Manager</th><th>Nemesis</th><th>Record vs Nemesis</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <h2 style="margin-top:32px">H2H Winning Streaks — Per Manager</h2>
  <div class="card">
    <table id="streak-mgr-tbl">
      <thead><tr><th>Manager</th><th>Best All-Time Streak</th><th>vs</th><th>Current Streak</th><th>vs</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px">
    <div class="card">
      <h2 style="margin-bottom:16px">Top 5 All-Time H2H Streaks</h2>
      <table id="streak-alltime-tbl">
        <thead><tr><th>Manager</th><th>vs</th><th>Consecutive Wins</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="card">
      <h2 style="margin-bottom:16px">Top 5 Active H2H Streaks</h2>
      <table id="streak-active-tbl">
        <thead><tr><th>Manager</th><th>vs</th><th>Active Wins</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  </div>
</div>

<div id="pvp" class="section">
  <h2>Player vs Player</h2>
  <div class="card">
    <div class="filter-bar">
      <select id="pvp-p1" onchange="renderPvP()" style="min-width:160px">
        <option value="">— Player 1 —</option>
      </select>
      <span style="color:var(--text-dim);font-weight:700;font-size:18px">vs</span>
      <select id="pvp-p2" onchange="renderPvP()" style="min-width:160px">
        <option value="">— Player 2 —</option>
      </select>
      <span id="pvp-summary" style="color:var(--text-dim);font-size:14px;margin-left:8px"></span>
    </div>
    <div id="pvp-results"></div>
  </div>
</div>

<div id="records" class="section">
  <h2>Records &amp; Milestones</h2>
  <div class="stat-grid" id="records-grid"></div>
  <h2 style="margin-top:32px">Playoff Report</h2>
  <div class="card">
    <table id="playoff-report-tbl">
      <thead><tr>
        <th style="text-align:left">Manager</th>
        <th>Apps</th>
        <th>PO Record</th>
        <th>PO Win%</th>
        <th>Finals</th>
        <th>Titles</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<nav class="tabbar">
  <a data-tab="standings" class="active" onclick="show('standings')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>Standings</a>
  <a data-tab="champions" onclick="show('champions')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3M9 18h6M8 21h8M12 16v2"/></svg>Champs</a>
  <a data-tab="h2h" onclick="show('h2h')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h7v10H4zM13 7h7v10h-7z"/></svg>H2H</a>
  <a data-tab="pvp" onclick="show('pvp')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/><path d="M3 20a5 5 0 0 1 10 0M13 20a5 5 0 0 1 8-3.5"/></svg>vs</a>
  <a data-tab="records" onclick="show('records')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V11M10 20V5M16 20v-6M22 20H2"/></svg>Records</a>
</nav>
<script>__JS__</script>
</body>
</html>"""


def build_dashboard(seasons, output_path="dashboard/index.html"):
    if not seasons:
        raise ValueError("No season data provided.")

    league_name = seasons[-1]["league_name"]
    years = [s["season"] for s in seasons]
    year_range = f"{min(years)}–{max(years)}"

    completed = [s for s in seasons if any(t["wins"] + t["losses"] > 0 for t in s["standings"])]
    latest = max(completed, key=lambda s: s["season"]) if completed else None
    active_managers = [t["manager"] for t in latest["standings"]] if latest else []

    stats = {
        "alltime":         _compute_alltime_standings(completed),
        "champions":       _compute_champions(completed),
        "h2h":             _compute_head_to_head(completed),
        "records":         _compute_records(completed),
        "playoffs":        _compute_playoff_report(completed),
        "active_managers": active_managers,
    }

    data_json = json.dumps(stats, separators=(",", ":"))
    # Inject the user-derived data JSON LAST so a team/manager name that happens
    # to contain a marker literal (e.g. "__LEAGUE_NAME__") can't be corrupted by
    # a later .replace() — the data is never re-scanned after it lands.
    html = (
        _SKELETON
        .replace("__CSS__", _CSS)
        .replace("__JS__", _JS)
        .replace("__LEAGUE_NAME__", league_name)
        .replace("__YEAR_RANGE__", year_range)
        .replace("__DATA_JSON__", data_json)
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
