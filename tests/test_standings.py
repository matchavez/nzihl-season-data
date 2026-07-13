import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nzihl_season.standings import parse_standings

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def test_parse_standings_nzihl_rank_order_and_fields():
    html = _load("standings_nzihl.html")
    rows = parse_standings(html, "nzihl")
    # Real 2026-07-13 snapshot, 5 NZIHL clubs, esportsdesk's own PTS-sorted order.
    assert [r["code"] for r in rows] == ["SCS", "ADM", "DUN", "CRD", "BSW"]
    top = rows[0]
    assert top["name"] == "SkyCity Stampede"
    assert top["teamID"] == 675635
    assert top["gp"] == 12 and top["w"] == 7 and top["l"] == 2
    assert top["otw"] == 3 and top["otl"] == 0 and top["pts"] == 27


def test_parse_standings_nzwihl_rank_order_and_fields():
    html = _load("standings_nzwihl.html")
    rows = parse_standings(html, "nzwihl")
    assert [r["code"] for r in rows] == ["AST", "DTW", "WLD", "CIN"]
    last = rows[-1]
    assert last["name"] == "Canterbury Inferno"
    assert last["teamID"] == 675637
    assert last["gp"] == 10 and last["w"] == 1 and last["l"] == 7
    assert last["otw"] == 2 and last["otl"] == 0 and last["pts"] == 7


def test_parse_standings_team_cell_fusion_no_literal_space():
    # standings.cfm's Team cell fuses "Full Name" + short-code spans with NO
    # literal space between them in the source HTML (unlike the box score's
    # span fusion, which parser.py fixes with _fix_span_fusion()) -- this
    # asserts the fused cell still splits into a clean name, not "...eSCS".
    html = _load("standings_nzihl.html")
    rows = parse_standings(html, "nzihl")
    assert all("SCS" not in r["name"] and "ADM" not in r["name"] for r in rows)


def test_parse_standings_uses_canonical_code_not_page_code():
    # code must be OUR canonical TLA (matches teams.py / matchavez/hockey's
    # REG map), not whatever short code esportsdesk happens to render --
    # these have drifted before (e.g. Admirals "WAA" vs our "ADM").
    html = _load("standings_nzihl.html")
    rows = parse_standings(html, "nzihl")
    admirals = next(r for r in rows if r["teamID"] == 674110)
    assert admirals["code"] == "ADM"


def test_parse_standings_empty_html():
    assert parse_standings("<html><body>nothing here</body></html>", "nzihl") == []


def test_parse_standings_unknown_league_key_falls_back_to_all_teams():
    # Defensive: an unrecognised league_key shouldn't crash -- just widens
    # the match candidate pool instead of restricting to one league's teams.
    html = _load("standings_nzihl.html")
    rows = parse_standings(html, "not-a-real-league")
    assert len(rows) == 5
    assert rows[0]["code"] == "SCS"
