"""Gameid discovery: esportsdesk assigns gameids from a single sequence
SHARED across every client/league on the platform (confirmed empirically
2026-07-09 -- querying a known NZIHL gameid with NZWIHL's clientid/leagueid
params returns the exact same NZIHL page; the params are cosmetic, not a
filter). A whole season's games (played AND not-yet-played) get IDs in one
contiguous block when the schedule is created:

  NZIHL 2026:  2519913-2519952 (40 ids)   -- confirmed by probing
  NZWIHL 2026: 2520001-2520024 (24 ids)   -- confirmed by probing

Between/around those blocks sit OTHER esportsdesk customers' games (a
completely different sport/league), which a naive forward probe would
happily "find" if we didn't check team-id membership. So every probed id is
classified by whether its two teamIDs belong to OUR league's roster
(teams.py), not by clientid/leagueid.

State kept per league (see cli.py's cursor.json):
  scanned_through -- every id <= this has been fetched at least once and
                     definitively classified (ours-complete / ours-pending /
                     not-ours / doesn't-exist-yet). Advances every run.
  pending         -- ids that belong to OUR league but aren't complete yet
                     (future fixture / in-progress game). Re-checked every
                     run regardless of scanned_through, since a game miles
                     behind the current scan front can still be the next
                     one to finish.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .http import FetchError, fetch_boxscore
from .parser import parse_boxscore
from .teams import LeagueCfg


@dataclass
class Classification:
    gameid: int
    status: str  # "complete" | "pending" | "not_ours" | "missing"
    parsed: dict | None = None


def classify(gameid: int, league: LeagueCfg) -> Classification:
    try:
        html = fetch_boxscore(gameid, league.client_id, league.league_id)
    except FetchError:
        return Classification(gameid, "missing")
    parsed = parse_boxscore(html)
    tids = {parsed["away"].teamID, parsed["home"].teamID}
    if not (tids & league.team_ids):
        return Classification(gameid, "not_ours")
    if parsed["complete"]:
        return Classification(gameid, "complete", parsed)
    return Classification(gameid, "pending", parsed)


def find_season_start(seed_gameid: int, *, max_consecutive_misses: int = 10,
                       sleep: float = 1.0, classify_fn=None) -> int:
    """Probe downward from a known-live gameid until `max_consecutive_misses`
    straight non-existent ids confirm we're past the true edge of the
    allocated block. Returns the lowest confirmed-existing gameid found."""
    classify_fn = classify_fn or (lambda gid: _exists(gid))
    lowest_seen = seed_gameid
    misses = 0
    gid = seed_gameid - 1
    while misses < max_consecutive_misses:
        if classify_fn(gid):
            lowest_seen = gid
            misses = 0
        else:
            misses += 1
        gid -= 1
        if sleep:
            time.sleep(sleep)
    return lowest_seen


def _exists(gameid: int, *, client_id: int = 7131, league_id: int = 35499) -> bool:
    try:
        fetch_boxscore(gameid, client_id, league_id)
        return True
    except FetchError:
        return False


def nightly_update(league: LeagueCfg, cursor: dict, *, probe_ahead: int = 20,
                    max_consecutive_misses: int = 10, sleep: float = 1.0,
                    classify_fn=None) -> tuple[list[dict], dict]:
    """Re-check pending shells, then probe forward for new ids.

    Returns (new_complete_games, updated_cursor). `new_complete_games` are
    raw parsed dicts {"gameid", "parsed"} for games that just resolved to
    complete -- caller (cli.py) turns those into the final schema and merges
    them into the committed games list (idempotent: existing gameids are
    never re-fetched once complete and recorded).
    """
    classify_fn = classify_fn or classify
    scanned_through = cursor.get("scanned_through", league.seed_gameid - 1)
    pending = list(cursor.get("pending", []))

    new_games: list[dict] = []
    still_pending: list[int] = []

    for gid in pending:
        c = classify_fn(gid, league)
        if sleep:
            time.sleep(sleep)
        if c.status == "complete":
            new_games.append({"gameid": gid, "parsed": c.parsed})
        elif c.status == "pending":
            still_pending.append(gid)
        # "not_ours" / "missing" for a previously-pending id shouldn't
        # normally happen (a gameid doesn't change league), but if it does,
        # just drop it rather than loop on it forever.

    misses = 0
    gid = scanned_through + 1
    probed = 0
    while probed < probe_ahead and misses < max_consecutive_misses:
        c = classify_fn(gid, league)
        if sleep:
            time.sleep(sleep)
        if c.status == "missing":
            misses += 1
        else:
            misses = 0
            scanned_through = gid
            if c.status == "complete":
                new_games.append({"gameid": gid, "parsed": c.parsed})
            elif c.status == "pending":
                still_pending.append(gid)
            # "not_ours" -- just advances scanned_through, nothing to record.
        gid += 1
        probed += 1

    updated_cursor = {
        "scanned_through": scanned_through,
        "pending": sorted(set(still_pending)),
    }
    return new_games, updated_cursor


def bootstrap_cursor(league: LeagueCfg, *, probe_ahead: int = 60, sleep: float = 1.0,
                      classify_fn=None) -> tuple[list[dict], dict]:
    """First-ever run for a league with no committed cursor yet: confirm the
    season-start boundary by probing downward from the seed id, then sweep
    forward from there to pick up the whole currently-allocated block."""
    start = find_season_start(
        league.seed_gameid,
        sleep=sleep,
        classify_fn=lambda gid: _exists(gid, client_id=league.client_id, league_id=league.league_id),
    )
    return nightly_update(
        league,
        {"scanned_through": start - 1, "pending": []},
        probe_ahead=probe_ahead,
        sleep=sleep,
        classify_fn=classify_fn,
    )
