import concurrent.futures
import csv
import json
import os
import time
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
TOKEN_FILE = "yahoo_token.json"
REDIRECT_URI = "https://localhost:8080"


def _client_id():
    val = os.getenv("YAHOO_CLIENT_ID")
    if not val:
        raise RuntimeError("YAHOO_CLIENT_ID not set in .env")
    return val


def _client_secret():
    val = os.getenv("YAHOO_CLIENT_SECRET")
    if not val:
        raise RuntimeError("YAHOO_CLIENT_SECRET not set in .env")
    return val


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _load_token():
    try:
        with open(TOKEN_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)


def _exchange_code(code):
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        auth=(_client_id(), _client_secret()),
    )
    resp.raise_for_status()
    token = resp.json()
    token["obtained_at"] = time.time()
    return token


def _refresh_token(token):
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": token["refresh_token"], "redirect_uri": REDIRECT_URI},
        auth=(_client_id(), _client_secret()),
    )
    resp.raise_for_status()
    new_token = resp.json()
    new_token["obtained_at"] = time.time()
    return new_token


def _is_expired(token):
    return time.time() > token.get("obtained_at", 0) + token.get("expires_in", 3600) - 60


def get_access_token():
    token = _load_token()
    if token:
        if _is_expired(token):
            print("Refreshing Yahoo token...")
            token = _refresh_token(token)
            _save_token(token)
        return token["access_token"]

    params = {"client_id": _client_id(), "redirect_uri": REDIRECT_URI, "response_type": "code"}
    url = f"{AUTH_URL}?{urlencode(params)}"
    print("\nOpening Yahoo authorization page in your browser...")
    print("After approving, your browser will redirect to a page that won't load.")
    print("Copy the full URL from the address bar and paste it here.\n")
    webbrowser.open(url)

    pasted = input("Paste the full redirect URL here: ").strip()
    parsed = urlparse(pasted)
    code = parse_qs(parsed.query).get("code", [None])[0]
    if not code:
        raise RuntimeError("Could not extract authorization code from URL.")

    print("Exchanging code for token...")
    token = _exchange_code(code)
    _save_token(token)
    print("Token saved to yahoo_token.json\n")
    return token["access_token"]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _fetch(path, access_token):
    resp = requests.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _numeric_items(d):
    """Yield values for all numeric string keys in a dict, in order."""
    i = 0
    while str(i) in d:
        yield d[str(i)]
        i += 1


def _player_id_from_key(player_key):
    return player_key.split(".")[-1]


def _extract_player_meta(p_list):
    """Extract player_id and name from the player meta list."""
    player_id, name, is_keeper_info = None, None, {}
    for v in p_list:
        if not isinstance(v, dict):
            continue
        if "player_id" in v:
            player_id = str(v["player_id"])
        if "name" in v:
            name = v["name"].get("full", "")
        if "is_keeper" in v:
            is_keeper_info = v["is_keeper"]
    return player_id, name, is_keeper_info


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _find_game_key(access_token, season):
    data = _fetch("/games;game_codes=nfl", access_token)
    games = data["fantasy_content"]["games"]
    for game_item in _numeric_items(games):
        game = game_item["game"][0]
        if str(game.get("season")) == str(season):
            return game["game_key"]
    raise RuntimeError(f"Could not find Yahoo NFL game key for season {season}")


def _resolve_league_id(league_id, game_key, access_token):
    if str(league_id).isdigit():
        return str(league_id)

    print(f"  '{league_id}' is a custom slug — looking up numeric league ID...")
    data = _fetch(f"/users;use_login=1/games;game_keys={game_key}/leagues", access_token)
    user = data["fantasy_content"]["users"]["0"]["user"]
    leagues = user[1]["games"]["0"]["game"][1]["leagues"]
    all_leagues = list(_numeric_items(leagues))

    if len(all_leagues) == 1:
        numeric_id = str(all_leagues[0]["league"][0]["league_id"])
        print(f"  Resolved to league_id={numeric_id} ({all_leagues[0]['league'][0].get('name')})")
        return numeric_id

    matches = [lg for lg in all_leagues if league_id in lg["league"][0].get("url", "")]
    if len(matches) == 1:
        numeric_id = str(matches[0]["league"][0]["league_id"])
        print(f"  Resolved to league_id={numeric_id} ({matches[0]['league'][0].get('name')})")
        return numeric_id

    print("  Your leagues for this season:")
    for lg in all_leagues:
        print(f"    {lg['league'][0]['league_id']}  {lg['league'][0].get('name')}")
    raise RuntimeError(f"Pass the numeric league_id from the list above instead of '{league_id}'")


def _get_league_meta(league_key, access_token):
    data = _fetch(f"/league/{league_key}/settings", access_token)
    league = data["fantasy_content"]["league"]
    meta = league[0]
    # is_auction_draft lives in the settings list, not the top-level meta
    settings_list = league[1].get("settings", [])
    if isinstance(settings_list, list):
        for item in settings_list:
            if isinstance(item, dict) and "is_auction_draft" in item:
                meta["is_auction_draft"] = item["is_auction_draft"]
                break
    return meta


def _get_all_rosters(league_key, access_token):
    """Return list of (team_name, players) where players is list of dicts."""
    data = _fetch(f"/league/{league_key}/teams", access_token)
    teams_raw = data["fantasy_content"]["league"][1]["teams"]

    def fetch_roster(team_item):
        t_list = team_item["team"][0]
        team_key = next(v["team_key"] for v in t_list if isinstance(v, dict) and "team_key" in v)
        team_name = next(v["name"] for v in t_list if isinstance(v, dict) and "name" in v)
        roster_data = _fetch(f"/team/{team_key}/roster/players", access_token)
        players_raw = roster_data["fantasy_content"]["team"][1]["roster"]["0"]["players"]
        players = []
        for p_item in _numeric_items(players_raw):
            p_list = p_item["player"][0]
            p_action = p_item["player"][1] if len(p_item["player"]) > 1 else {}
            player_id, name, is_keeper_info = _extract_player_meta(p_list)
            if player_id:
                players.append({
                    "player_id": player_id,
                    "name": name or f"Unknown ({player_id})",
                    "is_keeper": is_keeper_info,
                })
        return team_name, team_key, players

    all_teams = list(_numeric_items(teams_raw))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_roster, t) for t in all_teams]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    return sorted(results, key=lambda x: x[0])


def _get_draft_results(league_key, access_token):
    """Return dict of player_id -> pick data."""
    data = _fetch(f"/league/{league_key}/draftresults", access_token)
    draft_results = data["fantasy_content"]["league"][1]["draft_results"]
    picks = {}
    for item in _numeric_items(draft_results):
        pick = item["draft_result"]
        pid = _player_id_from_key(pick["player_key"])
        picks[pid] = pick
    return picks


def _get_transactions(league_key, access_token):
    """Return dict of player_id -> max FAAB bid across all add transactions."""
    data = _fetch(f"/league/{league_key}/transactions;type=add", access_token)
    txns_raw = data["fantasy_content"]["league"][1].get("transactions", {})
    acquisitions = {}

    for txn_item in _numeric_items(txns_raw):
        txn = txn_item["transaction"]
        meta = txn[0]
        if meta.get("status") != "successful":
            continue
        faab = int(meta.get("faab_bid", 0) or 0)
        players_raw = txn[1].get("players", {})
        for p_item in _numeric_items(players_raw):
            p = p_item["player"]
            p_meta = p[0]
            p_action = p[1] if len(p) > 1 else {}
            txn_data = p_action.get("transaction_data", {})
            if isinstance(txn_data, list):
                txn_data = txn_data[0]
            if txn_data.get("type") != "add":
                continue
            pid = next((str(v["player_id"]) for v in p_meta if isinstance(v, dict) and "player_id" in v), None)
            if pid:
                acquisitions[pid] = max(acquisitions.get(pid, 0), faab)

    return acquisitions


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------

def fetch_keeper_data(league_id, season=2025):
    access_token = get_access_token()

    print(f"Finding Yahoo game key for {season} season...")
    game_key = _find_game_key(access_token, season)
    print(f"  Game key: {game_key}")
    league_id = _resolve_league_id(league_id, game_key, access_token)

    league_key = f"{game_key}.l.{league_id}"
    print("Fetching league info...")
    meta = _get_league_meta(league_key, access_token)
    is_auction = bool(meta.get("is_auction_draft", 0))
    print(f"  Draft type: {'auction' if is_auction else 'snake'}")

    # Previous league key from "renew" field (format: "game_key_league_id")
    renew = meta.get("renew", "")
    prev_league_key = renew.replace("_", ".l.") if renew else None

    print("Fetching teams and rosters...")
    teams = _get_all_rosters(league_key, access_token)

    print("Fetching draft results...")
    current_picks = _get_draft_results(league_key, access_token)

    # Keeper counts: is_keeper.kept on roster = player was kept for this season's draft
    keeper_counts = {}
    for _, _, players in teams:
        for p in players:
            if p["is_keeper"].get("kept"):
                keeper_counts[p["player_id"]] = keeper_counts.get(p["player_id"], 0) + 1

    # Check previous season keepers if available
    if prev_league_key:
        print(f"  Checking previous season ({prev_league_key}) for keeper history...")
        try:
            prev_teams = _get_all_rosters(prev_league_key, access_token)
            for _, _, players in prev_teams:
                for p in players:
                    if p["is_keeper"].get("kept"):
                        keeper_counts[p["player_id"]] = keeper_counts.get(p["player_id"], 0) + 1
        except Exception as e:
            print(f"  Could not fetch previous season rosters: {e}")

    print("Fetching transactions (FAAB/waiver)...")
    faab_acquisitions = _get_transactions(league_key, access_token)

    return {
        "teams": teams,
        "current_picks": current_picks,
        "keeper_counts": keeper_counts,
        "faab_acquisitions": faab_acquisitions,
        "is_auction": is_auction,
    }


# ---------------------------------------------------------------------------
# Report + CSV
# ---------------------------------------------------------------------------

def _draft_price_label(pick, is_auction):
    if is_auction:
        cost = pick.get("cost")
        if cost is not None:
            return f"${cost}"
    rnd = pick.get("round")
    if rnd:
        return f"Round {rnd}"
    return "Unknown"


def _auction_value(label):
    if isinstance(label, str) and label.startswith("$"):
        try:
            return int(label[1:])
        except ValueError:
            pass
    return None


def _keeper_cost(draft_price, faab_cost):
    draft_val = _auction_value(draft_price)
    has_faab = faab_cost != ""
    if has_faab:
        faab_val = int(faab_cost) if faab_cost else 0
        components = [faab_val, 20]
        if draft_val is not None:
            components.append(draft_val)
        return f"${max(components)}"
    if draft_val is not None:
        return f"${draft_val}"
    return ""


def build_report(data, manual_overrides=None):
    manual_overrides = manual_overrides or {}
    rows = []

    for team_name, team_key, players in data["teams"]:
        for player in players:
            pid = player["player_id"]
            player_name = player["name"]

            name_key = player_name.lower()
            keeper_count = manual_overrides.get(name_key, data["keeper_counts"].get(pid, 0))

            pick = data["current_picks"].get(pid)
            draft_price = _draft_price_label(pick, data["is_auction"]) if pick else "Undrafted"

            max_faab = data["faab_acquisitions"].get(pid)
            faab_cost = max_faab if max_faab is not None else ""

            rows.append({
                "Team": team_name,
                "Player": player_name,
                "Keeper Count": keeper_count,
                "Draft Price": draft_price,
                "FAAB Cost": faab_cost,
                "Keeper Cost": _keeper_cost(draft_price, faab_cost),
            })

    rows.sort(key=lambda r: (r["Team"], r["Player"]))
    return rows


def write_csv(rows, output_path):
    if not rows:
        print("No data to write.")
        return
    fieldnames = ["Team", "Player", "Keeper Count", "Draft Price", "FAAB Cost", "Keeper Cost"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {output_path}")


def load_manual_keeper_overrides(path):
    overrides = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Player", "").strip().lower()
                try:
                    count = int(row.get("Keeper Count", 0))
                except ValueError:
                    count = 0
                if name:
                    overrides[name] = count
        print(f"Loaded {len(overrides)} manual keeper overrides from {path}")
    except FileNotFoundError:
        pass
    return overrides
