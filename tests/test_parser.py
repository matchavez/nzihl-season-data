import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nzihl_season.parser import parse_boxscore
from nzihl_season.game import build_game

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXDIR, name)) as f:
        return f.read()


def test_2519941_overtime_winner_max_roth():
    """The exact game that caught the 'OVERTIME PERIOD 1' heading-regex bug
    (matchavez/hockey commit 7f400f6) -- acceptance check for this repo too:
    finalType must be OT and Max Roth's goal must land in period 'OT'."""
    parsed = parse_boxscore(_load("nzihl_2519941_ot.html"))
    game = build_game(2519941, "NZIHL", parsed)

    assert game["finalType"] == "OT"
    assert game["date"] == "2026-07-04"
    assert game["away"]["name"] == "SkyCity Stampede"
    assert game["away"]["total"] == 3
    assert game["home"]["name"] == "Botany Swarm"
    assert game["home"]["total"] == 2

    ot_goals = [g for g in game["goals"] if g["per"] == "OT"]
    assert len(ot_goals) == 1
    winner = ot_goals[0]
    assert winner["who"] == "Max Roth"
    assert winner["no"] == 55
    assert winner["assists"] == ["Conner Jean"]
    assert winner["t"] == "3:17"

    assert game["away"]["sog_periods"] == [9, 8, 8, 2]
    assert game["home"]["sog_periods"] == [7, 8, 8, 1]
    assert len(game["goalies"]) == 2


def test_2519940_regulation_final_no_ot_suffix():
    parsed = parse_boxscore(_load("nzihl_2519940.html"))
    game = build_game(2519940, "NZIHL", parsed)
    assert game["finalType"] == ""
    assert game["away"]["name"] == "Dunedin Thunder"
    assert game["away"]["total"] == 4
    assert game["home"]["name"] == "Canterbury Red Devils"
    assert game["home"]["total"] == 6


def test_shootout_game_excludes_shootout_attempts_from_goals():
    """2520008 goes to a shootout. The SHOOTOUT section of the page is a
    completely different table shape (player name + a check/cross icon, no
    jersey#/parens/clock) -- must NOT be swept into `goals` as if each
    attempt were a normal scoring-summary row."""
    parsed = parse_boxscore(_load("nzwihl_2520008.html"))
    game = build_game(2520008, "NZWIHL", parsed)
    assert game["finalType"] == "SO"
    # Regulation goals only: CIN 2+0+2=4, WLD 1+2+1=4 -> 8 total.
    assert len(game["goals"]) == 8
    assert all(g["per"] in ("1", "2", "3") for g in game["goals"])


def test_nicknamed_player_scoring_row_not_broken_by_extra_parens():
    """'Reagyn Shattock (Niskakoski)' scores twice -- once unassisted, once
    with a real assist. Her own nickname paren must not be misread as (or
    leak into) the assist list either time."""
    parsed = parse_boxscore(_load("nzwihl_2520008.html"))
    hers = [g for g in parsed["goals"] if "Shattock" in g["who"]]
    assert len(hers) == 2, "expected two goals from Reagyn Shattock (Niskakoski)"
    for g in hers:
        assert all("Niskakoski" not in a for a in g["assists"])

    unassisted = next(g for g in hers if g["t"] == "3:35")
    assisted = next(g for g in hers if g["t"] == "5:50")
    assert unassisted["assists"] == []
    assert assisted["assists"] == ["Gabrielle Guerin"]


def test_team_penalty_vs_missing_jersey_player_penalty():
    """'Joel Gerard (SkyCity Stampede) ...' has no jersey number scraped but
    IS a player penalty (teamPen must be False, who populated). 'Team
    Penalty (Canterbury Inferno) ...' has no player at all (teamPen True,
    who empty)."""
    parsed = parse_boxscore(_load("nzihl_2519942.html"))
    joel = [p for p in parsed["pens"] if p["who"] == "Joel Gerard"]
    assert len(joel) == 1
    assert joel[0]["no"] is None
    assert joel[0]["teamPen"] is False
    assert joel[0]["teamID"] == 675635  # SkyCity Stampede

    parsed2 = parse_boxscore(_load("nzwihl_2520008.html"))
    team_pens = [p for p in parsed2["pens"] if p["teamPen"]]
    assert len(team_pens) == 1
    assert team_pens[0]["who"] == ""
    assert team_pens[0]["inf"] == "Delay of game"


def test_nicknamed_player_as_assist_not_broken_by_extra_parens():
    """Sibling of test_nicknamed_player_scoring_row_not_broken_by_extra_parens
    (found 2026-07-12, fixed 2026-07-13): the greedy-capture fix only guarded
    the SCORER position. When the parenthetical name appears as an ASSIST
    instead, the goal used to come out with a garbled `who`, a garbled
    single-entry `assists` list, and `teamID: None`. Two real repro games:
    2520003 (Gabrielle Guerin's goal assisted by "Reagyn Shattock
    (Niskakoski)") and 2520016 (Nerhys Gordon's PPG assisted by both
    "Stephanie Koviessen" and "Lucy-Jane(LJ) Hart")."""
    parsed = parse_boxscore(_load("nzwihl_2520003.html"))
    goal = next(g for g in parsed["goals"] if g["t"] == "2:29" and g["per"] == "2")
    assert goal["who"] == "Gabrielle Guerin"
    assert goal["assists"] == ["Reagyn Shattock (Niskakoski)"]
    assert goal["teamID"] == 675637  # Canterbury Inferno

    parsed2 = parse_boxscore(_load("nzwihl_2520016.html"))
    goal2 = next(g for g in parsed2["goals"] if g["t"] == "19:38" and g["per"] == "2")
    assert goal2["who"] == "Nerhys Gordon"
    assert goal2["assists"] == ["Stephanie Koviessen", "Lucy-Jane(LJ) Hart"]
    assert goal2["teamID"] == 675637  # Canterbury Inferno
    assert goal2["flag"] == "PPG"

    # Global invariant this bug class violates: every goal must resolve a
    # teamID, and neither `who` nor any assist string should carry a stray
    # unmatched "(" left over from a bad split.
    for g in parsed["goals"] + parsed2["goals"]:
        assert g["teamID"] is not None, g
        assert g["who"].count("(") == g["who"].count(")"), g
        for a in g["assists"]:
            assert a.count("(") == a.count(")"), g


def test_pregame_shell_is_not_complete():
    """A future/unplayed game's box score is a shell: teams parse, but
    there's no FINAL status text and no goals -- must not be treated as a
    completed game."""
    shell_html = """
    <p>NZIHL<br />July 11th, 2026<br />4:45PM</p>
    <p>Avondale, Auckland</p>
    <table><tr><th>Team</th><th>1</th></tr>
    <tr><td><a href="stats_1team.cfm?teamID=674110">Pure NZ Admirals ADM</a></td><td>0</td></tr>
    <tr><td><a href="stats_1team.cfm?teamID=675634">Dunedin Thunder DUN</a></td><td>0</td></tr>
    </table>
    <h5>SCORING SUMMARY</h5><div>No Scoring</div>
    <h5>PENALTY SUMMARY</h5><div>No Penalties</div>
    """
    parsed = parse_boxscore(shell_html)
    assert parsed["complete"] is False
