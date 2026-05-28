import csv
import requests

BASE_URL = "https://api.sleeper.app/v1"


def _fetch(path):
    resp = requests.get(f"{BASE_URL}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get_team_name(user):
    return (
        (user.get("metadata") or {}).get("team_name")
        or user.get("display_name")
        or user.get("username")
        or f"Team {user['user_id']}"
    )


def get_league_chain(league_id, seasons_back=2):
    chain = []
    current_id = str(league_id)
    for _ in range(seasons_back):
        league = _fetch(f"/league/{current_id}")
        chain.append(league)
        prev_id = league.get("previous_league_id")
        if not prev_id:
            break
        current_id = str(prev_id)
    return chain


def _fetch_draft_picks(league_id):
    drafts = _fetch(f"/league/{league_id}/drafts")
    picks = []
    for draft in drafts:
        draft_picks = _fetch(f"/draft/{draft['draft_id']}/picks")
        for pick in draft_picks:
            pick["_draft_type"] = draft.get("type", "snake")
        picks.extend(draft_picks)
    return picks


def _fetch_transactions(league_id):
    transactions = []
    for week in range(1, 19):
        try:
            week_txns = _fetch(f"/league/{league_id}/transactions/{week}")
            if week_txns:
                transactions.extend(week_txns)
        except requests.HTTPError:
            break
    return transactions


def _is_keeper_pick(pick):
    val = (pick.get("metadata") or {}).get("is_keeper")
    return val in ("1", 1, True, "true")


def _draft_price_label(pick):
    metadata = pick.get("metadata") or {}
    amount = metadata.get("amount")
    if amount is not None:
        return f"${amount}"
    return f"Round {pick.get('round', '?')}"


def load_manual_keeper_overrides(path):
    """
    Load a CSV with columns: Player,Keeper Count
    Returns dict of player_name (lowercase) -> keeper_count int.
    Used when Sleeper's is_keeper flag is not set in historical drafts.
    """
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


def fetch_keeper_data(league_id):
    print(f"Fetching league chain for {league_id}...")
    chain = get_league_chain(league_id, seasons_back=2)
    season_labels = [lg["season"] for lg in chain]
    print(f"  Seasons found: {', '.join(season_labels)}")

    current_league = chain[0]
    current_league_id = current_league["league_id"]

    print("Fetching users and rosters...")
    users = _fetch(f"/league/{current_league_id}/users")
    rosters = _fetch(f"/league/{current_league_id}/rosters")

    user_by_id = {u["user_id"]: u for u in users}

    roster_team = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        if owner_id and owner_id in user_by_id:
            roster_team[roster["roster_id"]] = _get_team_name(user_by_id[owner_id])
        else:
            roster_team[roster["roster_id"]] = f"Roster {roster['roster_id']}"

    # Build keeper sets from Sleeper's roster.keepers field (set by commissioner pre-draft)
    # roster_id -> set of player_ids designated as keepers
    sleeper_keepers = {}
    for roster in rosters:
        keeper_list = roster.get("keepers") or []
        if keeper_list:
            sleeper_keepers[roster["roster_id"]] = set(str(p) for p in keeper_list)

    print("Fetching draft picks...")
    current_picks = {}
    # Keeper counts from is_keeper flag in historical drafts
    keeper_counts_from_drafts = {}

    for i, league in enumerate(chain):
        picks = _fetch_draft_picks(league["league_id"])
        for pick in picks:
            pid = pick.get("player_id")
            if not pid:
                continue
            if i == 0:
                current_picks[pid] = pick
            if _is_keeper_pick(pick):
                keeper_counts_from_drafts[pid] = keeper_counts_from_drafts.get(pid, 0) + 1

    sleeper_keepers_found = sum(len(v) for v in sleeper_keepers.values())
    draft_keepers_found = len(keeper_counts_from_drafts)
    print(f"  Keeper designations — Sleeper roster field: {sleeper_keepers_found}, draft is_keeper flag: {draft_keepers_found}")

    print("Fetching transactions (FAAB/waiver)...")
    transactions = _fetch_transactions(current_league_id)

    faab_acquisitions = {}
    for txn in transactions:
        if txn.get("type") not in ("waiver", "free_agent"):
            continue
        if txn.get("status") != "complete":
            continue
        adds = txn.get("adds") or {}
        bid = (txn.get("settings") or {}).get("waiver_bid", 0)
        for pid, roster_id in adds.items():
            faab_acquisitions[pid] = {"bid": bid, "roster_id": roster_id}

    print("Fetching player database...")
    players_db = _fetch("/players/nfl")

    return {
        "rosters": rosters,
        "roster_team": roster_team,
        "sleeper_keepers": sleeper_keepers,
        "current_picks": current_picks,
        "keeper_counts_from_drafts": keeper_counts_from_drafts,
        "faab_acquisitions": faab_acquisitions,
        "players_db": players_db,
    }


def build_report(data, manual_overrides=None):
    manual_overrides = manual_overrides or {}
    rows = []

    for roster in data["rosters"]:
        roster_id = roster["roster_id"]
        team_name = data["roster_team"].get(roster_id, f"Roster {roster_id}")

        # players already includes starters, reserve, and taxi — deduplicate
        all_players = list(dict.fromkeys(roster.get("players") or []))

        for pid in all_players:
            if not pid:
                continue

            player_info = data["players_db"].get(str(pid)) or {}
            first = player_info.get("first_name", "")
            last = player_info.get("last_name", "")
            player_name = f"{first} {last}".strip() or f"Unknown ({pid})"

            # Keeper count: prefer manual override, then draft is_keeper history
            name_key = player_name.lower()
            if name_key in manual_overrides:
                keeper_count = manual_overrides[name_key]
            else:
                keeper_count = data["keeper_counts_from_drafts"].get(str(pid), 0)

            # Note if Sleeper has this player marked as a keeper for upcoming draft
            is_sleeper_keeper = str(pid) in data["sleeper_keepers"].get(roster_id, set())
            if is_sleeper_keeper and keeper_count == 0:
                # Count this season's keeper designation if not already in draft history
                keeper_count = 1

            pick = data["current_picks"].get(str(pid))
            draft_price = _draft_price_label(pick) if pick else "Undrafted"

            faab_info = data["faab_acquisitions"].get(str(pid))
            if faab_info and faab_info["roster_id"] == roster_id:
                faab_cost = faab_info["bid"]
            else:
                faab_cost = ""

            rows.append({
                "Team": team_name,
                "Player": player_name,
                "Keeper Count": keeper_count,
                "Draft Price": draft_price,
                "FAAB Cost": faab_cost,
            })

    rows.sort(key=lambda r: (r["Team"], r["Player"]))
    return rows


def write_csv(rows, output_path):
    if not rows:
        print("No data to write.")
        return

    fieldnames = ["Team", "Player", "Keeper Count", "Draft Price", "FAAB Cost"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_path}")
