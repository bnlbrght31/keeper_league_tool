"""
Fetch all-time historical data for a Sleeper fantasy football league.
Walks the 'previous_league_id' chain from the current season back to the first season.
"""
import concurrent.futures
import json

from providers.sleeper import _fetch, _get_team_name


def _get_league_info(league_id):
    """Return raw league dict from Sleeper API."""
    return _fetch(f"/league/{league_id}")


def _get_users(league_id):
    """Return {user_id: user_dict} mapping."""
    users = _fetch(f"/league/{league_id}/users") or []
    return {u["user_id"]: u for u in users}


def _get_rosters(league_id):
    """Return list of roster dicts."""
    return _fetch(f"/league/{league_id}/rosters") or []


def _get_standings(league_id, users, rosters):
    """
    Build standings list from rosters + users.
    Returns list of team dicts; rank is initially set by regular-season record
    and will be overwritten by _apply_bracket_ranks.

    team_key is prefixed with league_id so roster slot numbers (1-14) don't
    collide across seasons when dashboard.py builds the global k2m lookup.
    """
    user_map = {r["roster_id"]: users.get(r.get("owner_id"), {}) for r in rosters}

    teams = []
    for roster in rosters:
        roster_id = roster["roster_id"]
        settings = roster.get("settings") or {}

        wins = int(settings.get("wins", 0) or 0)
        losses = int(settings.get("losses", 0) or 0)
        ties = int(settings.get("ties", 0) or 0)
        pf = float(settings.get("fpts", 0) or 0) + float(settings.get("fpts_decimal", 0) or 0) / 100
        pa = float(settings.get("fpts_against", 0) or 0) + float(settings.get("fpts_against_decimal", 0) or 0) / 100

        user = user_map.get(roster_id, {})
        owner_id = roster.get("owner_id") or ""
        # Stable person identifier: Sleeper account display name
        manager_name = user.get("display_name") or user.get("username") or f"User {owner_id}"
        # Per-season team name set within the league (falls back to manager name)
        metadata = (user.get("metadata") or {})
        team_name = metadata.get("team_name") or manager_name

        teams.append({
            "team_key": f"{league_id}.{roster_id}",  # globally unique across seasons
            "name": team_name,       # per-season team name (expandable row history)
            "manager": manager_name, # stable person identifier (grouping key)
            "owner_id": owner_id,
            "roster_id": roster_id,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "pf": round(pf, 2),
            "pa": round(pa, 2),
            "rank": 0,
        })

    # Initial rank by regular-season record (overwritten for completed seasons)
    teams.sort(key=lambda t: (-t["wins"], -t["pf"]))
    for i, t in enumerate(teams):
        t["rank"] = i + 1

    return teams


def _apply_bracket_ranks(standings, winners_bracket, losers_bracket):
    """
    Overwrite team ranks using the playoff bracket p-games.

    Sleeper bracket entries that have a 'p' field are placement games:
      - winners bracket p=N → winner gets rank N, loser gets rank N+1
      - losers bracket p=N → winner gets rank (champ_size + N), loser gets (champ_size + N + 1)

    champ_size is the number of unique roster IDs that appear in the winners bracket.
    Teams not covered by any p-game keep their regular-season rank (shouldn't happen
    in a completed season with a full bracket).
    """
    def _roster_ids(bracket):
        ids = set()
        for e in bracket:
            for key in ("t1", "t2", "w", "l"):
                if e.get(key) is not None:
                    ids.add(int(e[key]))
        return ids

    champ_size = len(_roster_ids(winners_bracket))

    rank_map = {}  # roster_id → final rank

    for entry in winners_bracket:
        p = entry.get("p")
        if p is not None:
            if entry.get("w") is not None:
                rank_map[int(entry["w"])] = p
            if entry.get("l") is not None:
                rank_map[int(entry["l"])] = p + 1

    for entry in losers_bracket:
        p = entry.get("p")
        if p is not None:
            if entry.get("w") is not None:
                rank_map[int(entry["w"])] = champ_size + p
            if entry.get("l") is not None:
                rank_map[int(entry["l"])] = champ_size + p + 1

    if not rank_map:
        return  # no completed bracket; keep regular-season ranks

    for t in standings:
        rid = t["roster_id"]
        if rid in rank_map:
            t["rank"] = rank_map[rid]

    standings.sort(key=lambda t: t["rank"])


def _get_weekly_matchups(league_id, start_week, end_week):
    """Fetch all weekly matchups. Returns raw list of per-week matchup dicts."""
    matchups = []

    def fetch_week(w):
        try:
            raw = _fetch(f"/league/{league_id}/matchups/{w}") or []
            by_matchup = {}
            for entry in raw:
                mid = entry.get("matchup_id")
                if mid is None:
                    continue
                by_matchup.setdefault(mid, []).append(entry)

            week_matchups = []
            for mid, entries in by_matchup.items():
                if len(entries) != 2:
                    continue
                a, b = entries
                week_matchups.append({
                    "week": w,
                    "matchup_id": mid,
                    "roster_id_a": a["roster_id"],
                    "roster_id_b": b["roster_id"],
                    "score_a": float(a.get("points", 0) or 0),
                    "score_b": float(b.get("points", 0) or 0),
                })
            return week_matchups
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_week, w): w for w in range(start_week, end_week + 1)}
        for f in concurrent.futures.as_completed(futures):
            matchups.extend(f.result())

    return sorted(matchups, key=lambda m: m["week"])


def _get_winners_bracket(league_id):
    try:
        return _fetch(f"/league/{league_id}/winners_bracket") or []
    except Exception:
        return []


def _get_losers_bracket(league_id):
    try:
        return _fetch(f"/league/{league_id}/losers_bracket") or []
    except Exception:
        return []


def _annotate_matchups(raw_matchups, winners_bracket, losers_bracket,
                       playoff_start_week, roster_to_manager, league_id):
    """
    Convert raw matchup dicts (with roster_ids) to the format dashboard.py expects:
    - team names resolved from roster_to_manager
    - is_playoffs / is_consolation flags
    Excludes unplayed games (both scores == 0).
    """
    # All roster IDs that appear anywhere in the losers or winners bracket
    loser_rosters = set()
    for e in losers_bracket:
        for k in ("t1", "t2", "w", "l"):
            if e.get(k) is not None:
                loser_rosters.add(int(e[k]))

    winner_rosters = set()
    for e in winners_bracket:
        for k in ("t1", "t2", "w", "l"):
            if e.get(k) is not None:
                winner_rosters.add(int(e[k]))

    finalized = []
    for m in raw_matchups:
        # Skip unplayed games
        if m["score_a"] == 0 and m["score_b"] == 0:
            continue

        w = m["week"]
        is_playoffs = w >= playoff_start_week

        ra = m["roster_id_a"]
        rb = m["roster_id_b"]

        # Consolation: both rosters appear in losers bracket, neither in winners bracket
        is_consolation = (
            is_playoffs
            and ra in loser_rosters and rb in loser_rosters
            and ra not in winner_rosters and rb not in winner_rosters
        )

        finalized.append({
            "week": w,
            "is_playoffs": is_playoffs,
            "is_consolation": is_consolation,
            "team_a": roster_to_manager.get(ra, f"Roster {ra}"),
            "key_a": f"{league_id}.{ra}",  # globally unique key matching team_key in standings
            "score_a": m["score_a"],
            "team_b": roster_to_manager.get(rb, f"Roster {rb}"),
            "key_b": f"{league_id}.{rb}",
            "score_b": m["score_b"],
        })

    return finalized


def fetch_all_seasons(league_id, verbose=True):
    """
    Walk the previous_league_id chain from the given league back to the first season.
    Returns a list of season dicts ordered oldest → newest.
    """
    seasons = []
    current_id = str(league_id)

    while current_id:
        if verbose:
            print(f"  Fetching Sleeper league {current_id}...")

        league = _get_league_info(current_id)
        season = int(league.get("season", 0))
        league_name = league.get("name", "Unknown League")
        prev_id = league.get("previous_league_id")

        settings = league.get("settings") or {}
        start_week = int(settings.get("start_week", 1) or 1)
        playoff_week_start = int(settings.get("playoff_week_start", 15) or 15)
        end_week = playoff_week_start + 3  # covers 2-3 playoff rounds safely

        if verbose:
            print(f"    {season}: weeks {start_week}-{end_week}, playoffs from week {playoff_week_start}")

        users = _get_users(current_id)
        rosters = _get_rosters(current_id)
        standings = _get_standings(current_id, users, rosters)

        winners_bracket = _get_winners_bracket(current_id)
        losers_bracket = _get_losers_bracket(current_id)

        # Override regular-season ranks with final playoff bracket positions
        _apply_bracket_ranks(standings, winners_bracket, losers_bracket)

        roster_to_manager = {t["roster_id"]: t["manager"] for t in standings}

        raw_matchups = _get_weekly_matchups(current_id, start_week, end_week)
        all_matchups = _annotate_matchups(
            raw_matchups, winners_bracket, losers_bracket,
            playoff_week_start, roster_to_manager, current_id,
        )
        regular_season = [m for m in all_matchups if not m["is_playoffs"]]

        if verbose:
            print(f"    {len(standings)} teams, {len(regular_season)} reg season, "
                  f"{len(all_matchups) - len(regular_season)} playoff matchups")

        seasons.append({
            "season": season,
            "league_key": current_id,
            "league_name": league_name,
            "standings": standings,
            "matchups": regular_season,
            "all_matchups": all_matchups,
            "playoff_start_week": playoff_week_start,
        })

        current_id = str(prev_id) if prev_id else None

    seasons.reverse()  # oldest first
    return seasons


def save_history(seasons, path="sleeper_history.json"):
    with open(path, "w") as f:
        json.dump(seasons, f, indent=2)
    print(f"Saved {len(seasons)} seasons to {path}")


def load_history(path="sleeper_history.json"):
    with open(path) as f:
        return json.load(f)
