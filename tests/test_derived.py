import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nzihl_season.derived import build_derived

TEAM_A = 675635  # SkyCity Stampede
TEAM_B = 674109  # Botany Swarm


def _game(gameid, date, away_id, away_total, home_id, home_total, final_type="",
          goals=None):
    return {
        "gameid": gameid,
        "league": "NZIHL",
        "date": date,
        "away": {"teamID": away_id, "name": "Away", "code": "AWY", "total": away_total,
                 "sog_periods": [], "pp": "", "pim": 0},
        "home": {"teamID": home_id, "name": "Home", "code": "HOM", "total": home_total,
                 "sog_periods": [], "pp": "", "pim": 0},
        "goals": goals or [],
        "pens": [],
        "goalies": [],
        "finalType": final_type,
    }


def test_last5_and_streak_order_and_content():
    games = [
        _game(1, "2026-05-01", TEAM_A, 3, TEAM_B, 2),           # A win
        _game(2, "2026-05-08", TEAM_A, 1, TEAM_B, 4),           # A loss
        _game(3, "2026-05-15", TEAM_A, 5, TEAM_B, 2),           # A win
        _game(4, "2026-05-22", TEAM_A, 2, TEAM_B, 1, "OT"),     # A OT win
    ]
    derived = build_derived(games)
    last5 = derived["last5"][str(TEAM_A)]
    # most-recent-first
    assert [e["gameid"] for e in last5] == [4, 3, 2, 1]
    assert last5[0]["result"] == "OTW"
    assert last5[1]["result"] == "W"
    assert last5[2]["result"] == "L"

    streak = derived["streak"][str(TEAM_A)]
    assert streak == {"type": "W", "count": 2}  # games 3 and 4 are both wins

    streak_b = derived["streak"][str(TEAM_B)]
    assert streak_b == {"type": "L", "count": 2}


def test_head_to_head_record_and_last_meeting():
    games = [
        _game(1, "2026-05-01", TEAM_A, 3, TEAM_B, 2),
        _game(2, "2026-05-08", TEAM_B, 4, TEAM_A, 1),  # B home win
    ]
    derived = build_derived(games)
    key = "|".join(str(x) for x in sorted((TEAM_A, TEAM_B)))
    rec = derived["head_to_head"][key]
    assert rec["games"] == [1, 2]
    assert rec["last_meeting"]["gameid"] == 2
    assert rec["last_meeting"]["winner_teamID"] == TEAM_B
    total_wins = rec["teamA_wins"] + rec["teamB_wins"]
    assert total_wins == 2


def test_player_game_logs_goals_and_assists():
    goals = [
        {"per": "1", "t": "10:00", "no": 9, "who": "Alex Gagnon", "assists": ["Conner Jean"],
         "flag": "", "teamID": TEAM_A},
        {"per": "2", "t": "5:00", "no": 9, "who": "Alex Gagnon", "assists": [],
         "flag": "", "teamID": TEAM_A},
    ]
    games = [_game(1, "2026-05-01", TEAM_A, 2, TEAM_B, 0, goals=goals)]
    derived = build_derived(games)
    logs = derived["player_game_logs"]
    gagnon = logs["alexgagnon"]
    assert gagnon["name"] == "Alex Gagnon"
    assert gagnon["games"][0]["goals"] == 2
    assert gagnon["games"][0]["assists"] == 0

    jean = logs["connerjean"]
    assert jean["games"][0]["assists"] == 1
    assert jean["games"][0]["goals"] == 0
