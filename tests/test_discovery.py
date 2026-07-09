import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nzihl_season.discovery import Classification, nightly_update, find_season_start
from nzihl_season.teams import LEAGUES

LEAGUE = LEAGUES["nzihl"]


def _fake_world(complete_ids, pending_ids, foreign_ids):
    """Build a classify_fn stub over a fixed in-memory world, so discovery
    logic can be tested without touching the network."""
    def classify_fn(gid, league):
        if gid in complete_ids:
            return Classification(gid, "complete", parsed={"fake": True, "gameid": gid})
        if gid in pending_ids:
            return Classification(gid, "pending")
        if gid in foreign_ids:
            return Classification(gid, "not_ours")
        return Classification(gid, "missing")
    return classify_fn


def test_nightly_update_finds_new_complete_games_and_advances_cursor():
    # Cursor already at 100; ids 101-103 are ours-complete, 104 foreign, 105 missing.
    cursor = {"scanned_through": 100, "pending": []}
    classify_fn = _fake_world(complete_ids={101, 102, 103}, pending_ids=set(), foreign_ids={104})
    new_games, updated = nightly_update(LEAGUE, cursor, probe_ahead=5, sleep=0,
                                         max_consecutive_misses=3, classify_fn=classify_fn)
    assert {g["gameid"] for g in new_games} == {101, 102, 103}
    # 105 is a miss but only 1 in a row (< max_consecutive_misses) so probing
    # continues to the probe_ahead limit; scanned_through only advances past
    # ids that resolved definitively (101-104), not the trailing miss at 105.
    assert updated["scanned_through"] == 104


def test_nightly_update_rechecks_pending_until_complete():
    cursor = {"scanned_through": 200, "pending": [150]}
    # 150 was pending before; this run it's now complete.
    classify_fn = _fake_world(complete_ids={150}, pending_ids=set(), foreign_ids=set())
    new_games, updated = nightly_update(LEAGUE, cursor, probe_ahead=0, sleep=0,
                                         classify_fn=classify_fn)
    assert {g["gameid"] for g in new_games} == {150}
    assert updated["pending"] == []


def test_nightly_update_keeps_still_incomplete_games_pending():
    cursor = {"scanned_through": 200, "pending": [150]}
    classify_fn = _fake_world(complete_ids=set(), pending_ids={150}, foreign_ids=set())
    new_games, updated = nightly_update(LEAGUE, cursor, probe_ahead=0, sleep=0,
                                         classify_fn=classify_fn)
    assert new_games == []
    assert updated["pending"] == [150]


def test_nightly_update_stops_forward_probe_after_consecutive_misses():
    cursor = {"scanned_through": 300, "pending": []}
    # Nothing exists from 301 onward -- probe should stop after
    # max_consecutive_misses, not consume the whole probe_ahead budget.
    classify_fn = _fake_world(complete_ids=set(), pending_ids=set(), foreign_ids=set())
    new_games, updated = nightly_update(LEAGUE, cursor, probe_ahead=50, sleep=0,
                                         max_consecutive_misses=5, classify_fn=classify_fn)
    assert new_games == []
    assert updated["scanned_through"] == 300  # never advanced past a miss


def test_find_season_start_stops_at_edge():
    # Games exist at 90-99 (inclusive), nothing below 90.
    existing = set(range(90, 100))

    def classify_fn(gid):
        return gid in existing

    start = find_season_start(99, max_consecutive_misses=5, sleep=0, classify_fn=classify_fn)
    assert start == 90
