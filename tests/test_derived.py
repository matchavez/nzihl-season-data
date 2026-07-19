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


def _skater_game(gameid, date, away_id, away_total, home_id, home_total, skaters):
    g = _game(gameid, date, away_id, away_total, home_id, home_total)
    g["skaters"] = skaters
    return g


def test_player_game_logs_uses_skaters_field_when_present_including_zero_games():
    """2026-07-20 fix: when a game carries the new `skaters` field, every
    player in it gets a log entry -- including a real zero-point game --
    instead of only the games they recorded a point in."""
    games = [
        _skater_game(1, "2026-05-01", TEAM_A, 3, TEAM_B, 1, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 1, "a": 0, "pts": 1,
             "plusMinus": 1, "shots": 3, "pim": 0},
        ]),
        _skater_game(2, "2026-05-08", TEAM_A, 0, TEAM_B, 2, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 0, "a": 0, "pts": 0,
             "plusMinus": -1, "shots": 1, "pim": 0},
        ]),
    ]
    derived = build_derived(games)
    gagnon = derived["player_game_logs"]["alexgagnon"]
    assert len(gagnon["games"]) == 2, "scoreless game 2 must still produce a log entry"
    by_gid = {g["gameid"]: g for g in gagnon["games"]}
    assert by_gid[1] == {"gameid": 1, "date": "2026-05-01", "goals": 1, "assists": 0}
    assert by_gid[2] == {"gameid": 2, "date": "2026-05-08", "goals": 0, "assists": 0}


def test_player_game_logs_streak_breaks_on_real_scoreless_game():
    """The whole point of the fix: consumers (matchavez/hockey's
    computeFact/assignDescriptors) walk games most-recent-first and stop
    counting a streak at the first zero. Before this fix a scoreless game
    was never in the array at all, so a streak could silently jump over a
    real gap. Games 1 and 2 have points, game 3 (most recent) is scoreless
    -- any correct streak/last-game consumer must see game 3 and stop."""
    games = [
        _skater_game(1, "2026-05-01", TEAM_A, 3, TEAM_B, 1, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 1, "a": 0, "pts": 1,
             "plusMinus": 1, "shots": 3, "pim": 0},
        ]),
        _skater_game(2, "2026-05-08", TEAM_A, 3, TEAM_B, 1, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 1, "a": 0, "pts": 1,
             "plusMinus": 1, "shots": 3, "pim": 0},
        ]),
        _skater_game(3, "2026-05-15", TEAM_A, 0, TEAM_B, 2, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 0, "a": 0, "pts": 0,
             "plusMinus": -1, "shots": 1, "pim": 0},
        ]),
    ]
    derived = build_derived(games)
    gagnon_games = derived["player_game_logs"]["alexgagnon"]["games"]
    # Most-recent-first walk, same logic matchavez/hockey uses downstream.
    sorted_desc = sorted(gagnon_games, key=lambda x: x["date"], reverse=True)
    assert sorted_desc[0]["goals"] == 0 and sorted_desc[0]["assists"] == 0
    streak = 0
    for gm in sorted_desc:
        if gm["goals"] > 0 or gm["assists"] > 0:
            streak += 1
        else:
            break
    assert streak == 0, "the most recent game is scoreless -- streak must be 0, not skip over it"


def test_player_game_logs_mixed_pre_and_post_migration_games():
    """A pre-migration game (no `skaters` field) and a post-migration game
    for the same player must both land in one combined log without error --
    this is the real-world state during the backfill rollout window."""
    old_goals = [
        {"per": "1", "t": "10:00", "no": 88, "who": "Alex Gagnon", "assists": [],
         "flag": "", "teamID": TEAM_A},
    ]
    games = [
        _game(1, "2026-05-01", TEAM_A, 1, TEAM_B, 0, goals=old_goals),  # pre-migration
        _skater_game(2, "2026-05-08", TEAM_A, 0, TEAM_B, 2, skaters=[
            {"teamID": TEAM_A, "no": 88, "name": "Alex Gagnon", "g": 0, "a": 0, "pts": 0,
             "plusMinus": -1, "shots": 1, "pim": 0},
        ]),  # post-migration, scoreless
    ]
    derived = build_derived(games)
    gagnon_games = derived["player_game_logs"]["alexgagnon"]["games"]
    assert len(gagnon_games) == 2
    by_gid = {g["gameid"]: g for g in gagnon_games}
    assert by_gid[1]["goals"] == 1
    assert by_gid[2]["goals"] == 0 and by_gid[2]["assists"] == 0
