import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nzihl_season.upcoming import parse_upcoming

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def test_parse_upcoming_skips_final_games():
    html = _load("schedule_min.html")
    games = parse_upcoming(html)
    # Fixture has one Final (15 May, Red Devils @ Stampede) and three
    # upcoming games (22 May, 23 May x2) -- the Final must not appear.
    assert len(games) == 3
    assert all(g["date"] != "2026-05-15" for g in games)


def test_parse_upcoming_extracts_teams_date_time():
    html = _load("schedule_min.html")
    games = parse_upcoming(html)
    first = games[0]
    assert first["date"] == "2026-05-22"
    assert first["time"] == "19:00"
    assert first["away"] == {"teamID": 674110, "name": "Pure NZ Admirals"}
    assert first["home"] == {"teamID": 675634, "name": "Dunedin Thunder"}


def test_parse_upcoming_sorted_chronologically():
    html = _load("schedule_min.html")
    games = parse_upcoming(html)
    keys = [(g["date"], g["time"]) for g in games]
    assert keys == sorted(keys)


def test_parse_upcoming_prefers_full_name_over_short_code():
    # Each team is linked twice (full name, then short code) -- we must
    # keep the first (full-name) occurrence, not "WAA"/"DUN"/etc.
    html = _load("schedule_min.html")
    games = parse_upcoming(html)
    names = {games[0]["away"]["name"], games[0]["home"]["name"]}
    assert "Pure NZ Admirals" in names
    assert "Dunedin Thunder" in names
    assert "WAA" not in names


def test_parse_upcoming_empty_html():
    assert parse_upcoming("<html><body>nothing here</body></html>") == []
