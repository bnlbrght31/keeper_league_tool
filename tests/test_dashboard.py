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
