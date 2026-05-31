"""
Fetch all-time historical data for an ESPN fantasy football league.
Iterates seasons year by year using the ESPN v3 API with cookie auth.
"""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

VIEWS = ["mTeam", "mSettings", "mMatchupScore", "mStandings"]


def _cookies():
    espn_s2 = os.getenv("ESPN_S2")
    swid = os.getenv("ESPN_SWID")
    if not espn_s2 or not swid:
        raise ValueError("ESPN_S2 and ESPN_SWID must be set in .env")
    return {"espn_s2": espn_s2, "SWID": swid}


def _fetch(league_id, year, views=VIEWS):
    """
    leagueHistory works for all seasons (including pre-2018) and returns a list;
    we unwrap the first element. Falls back to the season endpoint for edge cases.
    """
    view_qs = "&".join(f"view={v}" for v in views)
    url = f"{BASE_URL}/leagueHistory/{league_id}?seasonId={year}&{view_qs}"
    resp = requests.get(url, cookies=_cookies(), headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if isinstance(data, list) else data


def _derive_espn_playoff_ranks(schedule, playoff_ids, playoff_week_start):
    """
    Trace the championship bracket to assign final ranks 1..N.
    Returns {espn_team_id: rank}. Teams not in playoff_ids are not ranked here;
    the caller assigns consolation ranks by reg-season record.

    Algorithm:
    - Championship bracket games are those where BOTH teams are in playoff_ids.
    - Starting from the final playoff week, the championship game is between the
      two teams that both won in the previous round.  Its winner = 1st, loser = 2nd.
    - Any other final-week bracket game (3rd place, 5th place, …) is identified
      by which losers played each other; winner gets the next rank.
    - Works for any number of rounds / playoff team counts.
    """
    # Group bracket games by week
    bracket_by_week = {}
    for m in schedule:
        period = m.get("matchupPeriodId", 0)
        if period < playoff_week_start:
            continue
        home_id = (m.get("home") or {}).get("teamId")
        away_id = (m.get("away") or {}).get("teamId")
        if home_id not in playoff_ids or away_id not in playoff_ids:
            continue
        winner_id = home_id if m.get("winner") == "HOME" else (
                    away_id if m.get("winner") == "AWAY" else None)
        loser_id  = away_id if m.get("winner") == "HOME" else (
                    home_id if m.get("winner") == "AWAY" else None)
        bracket_by_week.setdefault(period, []).append({
            "home": home_id, "away": away_id,
            "winner": winner_id, "loser": loser_id,
        })

    if not bracket_by_week:
        return {}

    playoff_weeks = sorted(bracket_by_week.keys())

    # Track who won / lost each round so we can classify final-week games
    round_winners: dict[int, set] = {}
    round_losers:  dict[int, set] = {}
    for week in playoff_weeks:
        round_winners[week] = {g["winner"] for g in bracket_by_week[week] if g["winner"]}
        round_losers[week]  = {g["loser"]  for g in bracket_by_week[week] if g["loser"]}

    rank_map: dict[int, int] = {}
    rank_counter = 1

    # Process from the final week backwards; assign ranks to placement games
    for i, week in enumerate(reversed(playoff_weeks)):
        games = bracket_by_week[week]
        if i == 0:
            # Final week: sort games so the championship (all prev-winners) comes first
            if len(playoff_weeks) >= 2:
                prev_week = playoff_weeks[-(i + 2)]
                prev_w = round_winners[prev_week]
            else:
                prev_w = playoff_ids  # single-week bracket

            def _sort_key(g):
                both_prev_winners = g["home"] in prev_w and g["away"] in prev_w
                return (0 if both_prev_winners else 1)

            games = sorted(games, key=_sort_key)

        for g in games:
            if g["winner"] and g["winner"] not in rank_map:
                rank_map[g["winner"]] = rank_counter
            if g["loser"] and g["loser"] not in rank_map:
                rank_map[g["loser"]] = rank_counter + 1
            rank_counter += 2

    return rank_map


def _parse_season(league_id, year, data):
    settings = data.get("settings", {})
    league_name = settings.get("name", "Unknown League")
    schedule_settings = settings.get("scheduleSettings", {})
    reg_season_weeks = int(schedule_settings.get("matchupPeriodCount", 13))
    playoff_week_start = reg_season_weeks + 1

    # member_id → display name
    members = {}
    for m in data.get("members", []):
        display = (
            m.get("displayName")
            or f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
            or m["id"]
        )
        members[m["id"]] = display

    playoff_team_count = int(schedule_settings.get("playoffTeamCount", 4))

    # Build team lookup: team_id → team dict
    team_lookup = {}
    for t in data.get("teams", []):
        owner_ids = t.get("owners", [])
        owner_id = owner_ids[0] if owner_ids else ""
        manager = members.get(owner_id, f"Team {t['id']}")

        record = (t.get("record") or {}).get("overall") or {}
        wins   = int(record.get("wins", 0))
        losses = int(record.get("losses", 0))
        ties   = int(record.get("ties", 0))
        pf     = round(float(record.get("pointsFor", 0)), 2)
        pa     = round(float(record.get("pointsAgainst", 0)), 2)

        playoff_seed = int(t.get("playoffSeed") or 0)

        team_lookup[t["id"]] = {
            "team_key": f"{year}.{t['id']}",
            "name": t.get("name") or f"Team {t['id']}",
            "manager": manager,
            "owner_id": owner_id,
            "espn_team_id": t["id"],
            "playoff_seed": playoff_seed,
            "rank": 0,  # filled in below
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "pf": pf,
            "pa": pa,
        }

    # Teams that made the championship bracket (seeds 1..playoffTeamCount)
    playoff_ids = {
        tid for tid, t in team_lookup.items()
        if 1 <= t["playoff_seed"] <= playoff_team_count
    }

    # --- Derive final ranks from the playoff bracket ---
    # ESPN's playoffTierType is always "NONE" for historical seasons, so we
    # identify bracket membership by playoff seed and trace the bracket manually.
    rank_map = _derive_espn_playoff_ranks(
        data.get("schedule", []), playoff_ids, playoff_week_start
    )

    # Apply bracket-derived ranks; fall back to reg-season sort for the rest
    reg_season_order = sorted(
        team_lookup.values(), key=lambda t: (-t["wins"], -t["pf"])
    )
    next_rank = 1
    used_ranks = set(rank_map.values())
    for t in team_lookup.values():
        t["rank"] = rank_map.get(t["espn_team_id"], 0)

    # Fill unranked teams (consolation finishers) in reg-season order
    for t in reg_season_order:
        if t["rank"] == 0:
            while next_rank in used_ranks:
                next_rank += 1
            t["rank"] = next_rank
            used_ranks.add(next_rank)
            next_rank += 1

    standings = sorted(team_lookup.values(), key=lambda t: t["rank"])

    # Build matchups from schedule
    all_matchups = []
    for m in data.get("schedule", []):
        period = m.get("matchupPeriodId", 0)
        home = m.get("home") or {}
        away = m.get("away") or {}

        home_id = home.get("teamId")
        away_id = away.get("teamId")
        if home_id is None or away_id is None:
            continue

        home_pts = float(home.get("totalPoints", 0) or 0)
        away_pts = float(away.get("totalPoints", 0) or 0)

        is_playoffs = period >= playoff_week_start
        # Consolation: at least one team is not in the championship bracket
        is_consolation = is_playoffs and not (
            home_id in playoff_ids and away_id in playoff_ids
        )

        home_team = team_lookup.get(home_id, {})
        away_team = team_lookup.get(away_id, {})

        all_matchups.append({
            "week": period,
            "is_playoffs": is_playoffs,
            "is_consolation": is_consolation,
            "team_a": home_team.get("manager", f"Team {home_id}"),
            "key_a": home_team.get("team_key", f"{year}.{home_id}"),
            "score_a": round(home_pts, 2),
            "team_b": away_team.get("manager", f"Team {away_id}"),
            "key_b": away_team.get("team_key", f"{year}.{away_id}"),
            "score_b": round(away_pts, 2),
        })

    # Exclude unplayed games (both 0)
    all_matchups = [m for m in all_matchups if m["score_a"] > 0 or m["score_b"] > 0]
    all_matchups.sort(key=lambda m: m["week"])

    regular_season = [m for m in all_matchups if not m["is_playoffs"]]

    return {
        "season": year,
        "league_key": str(league_id),
        "league_name": league_name,
        "standings": standings,
        "matchups": regular_season,
        "all_matchups": all_matchups,
        "playoff_start_week": playoff_week_start,
    }


def fetch_all_seasons(league_id, start_year, end_year, verbose=True):
    """
    Fetch every season from start_year through end_year (inclusive).
    Skips years where the league doesn't exist or data is unavailable.
    Returns list of season dicts ordered oldest → newest.
    """
    seasons = []
    for year in range(start_year, end_year + 1):
        if verbose:
            print(f"  Fetching ESPN season {year}...")
        try:
            data = _fetch(league_id, year)
            season = _parse_season(league_id, year, data)
            # Skip seasons with no teams (shouldn't happen but safety check)
            if not season["standings"]:
                if verbose:
                    print(f"    {year}: no team data, skipping")
                continue
            played = sum(t["wins"] + t["losses"] for t in season["standings"])
            if verbose:
                print(f"    {year}: {len(season['standings'])} teams, "
                      f"{len(season['matchups'])} reg season matchups, "
                      f"{len(season['all_matchups']) - len(season['matchups'])} playoff")
            seasons.append(season)
        except requests.HTTPError as e:
            if verbose:
                print(f"    {year}: HTTP {e.response.status_code}, skipping")
        except Exception as e:
            if verbose:
                print(f"    {year}: error ({e}), skipping")

    return seasons


def save_history(seasons, path):
    with open(path, "w") as f:
        json.dump(seasons, f, indent=2)
    print(f"Saved {len(seasons)} seasons to {path}")


def load_history(path):
    with open(path) as f:
        return json.load(f)
