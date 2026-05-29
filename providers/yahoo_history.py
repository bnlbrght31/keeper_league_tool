"""
Fetch all-time historical data for a Yahoo fantasy football league.
Walks the 'renew' chain from the current season back to the first season.
"""
import concurrent.futures
import json

from providers.yahoo import _fetch, _numeric_items, get_access_token, _find_game_key


def _get_standings(league_key, access_token):
    """Return list of team dicts with final standings for a season."""
    data = _fetch(f"/league/{league_key}/standings", access_token)
    league = data["fantasy_content"]["league"]
    meta = league[0]
    season = int(meta.get("season", 0))
    league_name = meta.get("name", "")

    teams_raw = league[1]["standings"][0]["teams"]
    teams = []
    for team_item in _numeric_items(teams_raw):
        t = team_item["team"]
        t_meta = t[0]
        t_standings = next(
            (item["team_standings"] for item in t[1:] if isinstance(item, dict) and "team_standings" in item),
            {}
        )

        name = next((v["name"] for v in t_meta if isinstance(v, dict) and "name" in v), "Unknown")
        team_key = next((v["team_key"] for v in t_meta if isinstance(v, dict) and "team_key" in v), "")

        managers = next((v["managers"] for v in t_meta if isinstance(v, dict) and "managers" in v), [])
        manager_name = ""
        if managers:
            mgr_list = list(_numeric_items(managers)) if isinstance(managers, dict) else managers
            if mgr_list:
                first = mgr_list[0]
                mgr = first.get("manager", first) if isinstance(first, dict) else {}
                manager_name = mgr.get("nickname", mgr.get("guid", ""))

        outcome = t_standings.get("outcome_totals", {})
        def _int(v): return int(v) if str(v).strip().lstrip('-').isdigit() else 0
        def _flt(v):
            try: return float(v or 0)
            except (ValueError, TypeError): return 0.0
        rank = _int(t_standings.get("rank", 0))
        wins = _int(outcome.get("wins", 0))
        losses = _int(outcome.get("losses", 0))
        ties = _int(outcome.get("ties", 0))
        pf = _flt(t_standings.get("points_for", 0))
        pa = _flt(t_standings.get("points_against", 0))

        teams.append({
            "team_key": team_key,
            "name": name,
            "manager": manager_name or name,
            "rank": rank,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "pf": round(pf, 2),
            "pa": round(pa, 2),
        })

    return season, league_name, sorted(teams, key=lambda t: t["rank"])


def _get_weekly_scores(league_key, access_token, start_week, end_week):
    """Return list of matchup dicts {week, team_a, score_a, team_b, score_b} for regular season."""
    matchups = []

    def fetch_week(w):
        try:
            data = _fetch(f"/league/{league_key}/scoreboard;week={w}", access_token)
            week_matchups = []
            sb = data["fantasy_content"]["league"][1].get("scoreboard", {})
            # scoreboard → "0" → matchups → "0".."N" → matchup (dict)
            raw = sb.get("0", {}).get("matchups", {})
            for m_item in _numeric_items(raw):
                m = m_item["matchup"]           # dict, not list
                is_playoffs = str(m.get("is_playoffs", "0")) != "0"
                teams_raw = m.get("0", {}).get("teams", {})

                team_data = []
                for t_item in _numeric_items(teams_raw):
                    t = t_item["team"]
                    t_meta = t[0]               # list of meta dicts
                    t_stats = t[1] if len(t) > 1 else {}
                    name = next((v["name"] for v in t_meta if isinstance(v, dict) and "name" in v), "Unknown")
                    team_key = next((v["team_key"] for v in t_meta if isinstance(v, dict) and "team_key" in v), "")
                    score = float(t_stats.get("team_points", {}).get("total", 0) or 0)
                    team_data.append({"name": name, "team_key": team_key, "score": score})

                if len(team_data) == 2:
                    week_matchups.append({
                        "week": w,
                        "is_playoffs": is_playoffs,
                        "team_a": team_data[0]["name"],
                        "key_a": team_data[0]["team_key"],
                        "score_a": team_data[0]["score"],
                        "team_b": team_data[1]["name"],
                        "key_b": team_data[1]["team_key"],
                        "score_b": team_data[1]["score"],
                    })
            return week_matchups
        except Exception as e:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_week, w): w for w in range(start_week, end_week + 1)}
        for f in concurrent.futures.as_completed(futures):
            matchups.extend(f.result())

    return sorted(matchups, key=lambda m: m["week"])


def _get_season_meta(league_key, access_token):
    """Return (renew_key, start_week, end_week, playoff_start_week)."""
    data = _fetch(f"/league/{league_key}/settings", access_token)
    league = data["fantasy_content"]["league"]
    meta = league[0]
    settings_list = league[1].get("settings", [])

    start_week = int(meta.get("start_week", 1))
    end_week = int(meta.get("end_week", 16))
    playoff_start_week = end_week  # fallback

    if isinstance(settings_list, list):
        for item in settings_list:
            if isinstance(item, dict):
                if "playoff_start_week" in item:
                    playoff_start_week = int(item["playoff_start_week"])

    renew = meta.get("renew", "")
    prev_key = renew.replace("_", ".l.") if renew else None
    return prev_key, start_week, end_week, playoff_start_week


def fetch_all_seasons(league_id, current_season, verbose=True):
    """
    Walk the renew chain from current_season back to the first season.
    Returns a list of season dicts ordered oldest → newest.
    """
    access_token = get_access_token()

    if verbose:
        print(f"Finding game key for {current_season}...")
    game_key = _find_game_key(access_token, current_season)
    start_key = f"{game_key}.l.{league_id}"

    seasons = []
    league_key = start_key

    while league_key:
        if verbose:
            print(f"  Fetching {league_key}...")

        prev_key, start_week, end_week, playoff_start_week = _get_season_meta(league_key, access_token)
        season, league_name, standings = _get_standings(league_key, access_token)

        if verbose:
            print(f"    {season}: {len(standings)} teams, weeks {start_week}-{end_week}")

        matchups = _get_weekly_scores(league_key, access_token, start_week, end_week)
        regular_season = [m for m in matchups if not m["is_playoffs"]]

        seasons.append({
            "season": season,
            "league_key": league_key,
            "league_name": league_name,
            "standings": standings,
            "matchups": regular_season,
            "all_matchups": matchups,
            "playoff_start_week": playoff_start_week,
        })

        league_key = prev_key

    seasons.reverse()  # oldest first
    return seasons


def save_history(seasons, path="lobos_history.json"):
    with open(path, "w") as f:
        json.dump(seasons, f, indent=2)
    print(f"Saved {len(seasons)} seasons to {path}")


def load_history(path="lobos_history.json"):
    with open(path) as f:
        return json.load(f)
