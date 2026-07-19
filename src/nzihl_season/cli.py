"""Nightly build entrypoint.

For each league (nzihl, nzwihl):
  1. Load `cursor.json` (internal bookkeeping: how far we've probed, which
     ids are still pending) and the committed `<league>.json` (the actual
     data-warehouse deliverable: games + derived).
  2. If this league has no cursor yet, bootstrap: confirm the season-start
     boundary by probing downward from a known-live seed id, then sweep
     forward to collect every currently-allocated game.
     Otherwise: recheck pending (not-yet-complete) games, then probe
     forward from the cursor for brand-new ids.
  3. Merge any newly-completed games into the committed list (idempotent --
     keyed by gameid; existing entries are never re-fetched or overwritten).
  4. Recompute `derived` fresh from the full merged games list.
  5. Fetch the season's remaining fixtures (schedules.cfm, no lookahead
     cap -- see upcoming.py) and attach as `upcoming`.
  6. Write `<league>.json` = {"league", "games", "derived", "upcoming"}
     and update `cursor.json`.

Cursor bookkeeping is deliberately kept OUT of nzihl.json/nzwihl.json: the
gameid space is shared with every other esportsdesk customer on the
platform (see discovery.py), so `scanned_through` legitimately creeps
forward on every run even when zero new games for OUR leagues appear (it's
just recording "nothing of ours between here and there"). Keeping that
churn in a separate file means the actual deliverable -- the file every
overlay page fetches -- is byte-for-byte stable across reruns that find no
new games, which is what "idempotent" means to a consumer of this warehouse.

Politeness: one fetch per second (`--sleep`, default 1.0) since every probe
is a real HTTP request to admin.esportsdesk.com.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .discovery import bootstrap_cursor, nightly_update
from .game import build_game
from .derived import build_derived
from .http import FetchError, fetch_boxscore
from .parser import parse_boxscore
from .standings import fetch_standings
from .teams import LEAGUES
from .upcoming import fetch_upcoming

CURSOR_FILE = "cursor.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 -- corrupt/missing file: start fresh
        return default


def build_league(key: str, out_dir: Path, cursor_state: dict, *, probe_ahead: int = 20,
                  bootstrap_probe_ahead: int = 60, sleep: float = 1.0) -> dict:
    league = LEAGUES[key]
    path = out_dir / f"{key}.json"
    existing = _load_json(path, {"league": league.name, "games": [], "derived": {}, "upcoming": []})
    existing_games = {g["gameid"]: g for g in existing.get("games", [])}
    cursor = cursor_state.get(key) or {}

    if not cursor:
        new_raw, updated_cursor = bootstrap_cursor(league, probe_ahead=bootstrap_probe_ahead, sleep=sleep)
    else:
        new_raw, updated_cursor = nightly_update(league, cursor, probe_ahead=probe_ahead, sleep=sleep)

    for item in new_raw:
        gid = item["gameid"]
        if gid in existing_games:
            continue  # already recorded -- completed games never change
        existing_games[gid] = build_game(gid, league.name, item["parsed"])

    games = sorted(existing_games.values(), key=lambda g: (g.get("date") or "9999-99-99", g["gameid"]))
    derived = build_derived(games)

    # Current standings table, captured VERBATIM from standings.cfm (esportsdesk's
    # own computed W/L/OTW/OTL/PTS + rank order) -- deliberately not recomputed
    # from `games`, since NZIHL/NZWIHL's exact points-per-result rules aren't
    # reliably known here and getting that math wrong on a live broadcast graphic
    # is a bad failure mode (see standings.py module docstring). Best-effort, same
    # pattern as `upcoming` below: a transient scrape failure keeps whatever was
    # committed last time rather than wiping the field or aborting the build.
    try:
        derived["standings"] = fetch_standings(key)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {league.name} standings fetch failed ({exc!r}); "
              f"keeping previously-committed standings", file=sys.stderr)
        derived["standings"] = existing.get("derived", {}).get("standings", [])

    # Whole-season remaining fixtures (no lookahead cap -- see upcoming.py's
    # module docstring for why this is deliberately separate from
    # nzihl-broadcast-rosters' windowed boxscores.json). Best-effort: a
    # transient scrape failure just keeps whatever was committed last time
    # rather than wiping the field or aborting the whole league's build.
    try:
        upcoming = fetch_upcoming(league.client_id, league.league_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {league.name} upcoming-schedule fetch failed ({exc!r}); "
              f"keeping previously-committed upcoming list", file=sys.stderr)
        upcoming = existing.get("upcoming", [])

    manifest = {"league": league.name, "games": games, "derived": derived, "upcoming": upcoming}
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")

    cursor_state[key] = updated_cursor
    return manifest


def backfill_skaters(key: str, out_dir: Path, *, sleep: float = 1.0) -> dict:
    """One-time (re-run-safe) migration: re-fetch every currently-committed
    game's box score and re-parse it with the current parser, so games
    committed before the `skaters` field existed (2026-07-20, see
    derived.py's compute_player_game_logs docstring for why it matters)
    retroactively gain it. Games that already have a non-empty `skaters`
    list are skipped -- safe to re-run or resume after an interruption.

    Deliberately narrow: only re-fetches box scores and rebuilds `games` +
    `derived`. Does not touch `standings`/`upcoming` (kept as committed) and
    does not discover new games -- run a normal build afterward (or let the
    next scheduled run) to pick up anything new since this started.
    """
    league = LEAGUES[key]
    path = out_dir / f"{key}.json"
    existing = _load_json(path, {"league": league.name, "games": [], "derived": {}, "upcoming": []})
    games_by_id = {g["gameid"]: g for g in existing.get("games", [])}

    todo = sorted(gid for gid, g in games_by_id.items() if not g.get("skaters"))
    print(f"{key}: {len(todo)} of {len(games_by_id)} committed games need a skaters backfill")

    refetched = 0
    for gid in todo:
        try:
            html = fetch_boxscore(gid, league.client_id, league.league_id)
        except FetchError as exc:
            print(f"[warn] {key} gameid {gid}: refetch failed ({exc!r}), leaving as-is", file=sys.stderr)
            if sleep:
                time.sleep(sleep)
            continue
        parsed = parse_boxscore(html)
        if not parsed.get("complete"):
            print(f"[warn] {key} gameid {gid}: refetched page no longer parses as complete, leaving as-is",
                  file=sys.stderr)
            if sleep:
                time.sleep(sleep)
            continue
        games_by_id[gid] = build_game(gid, league.name, parsed)
        refetched += 1
        if sleep:
            time.sleep(sleep)

    games = sorted(games_by_id.values(), key=lambda g: (g.get("date") or "9999-99-99", g["gameid"]))
    derived = build_derived(games)
    # Untouched by this migration -- not a full rebuild, just the skaters backfill.
    derived["standings"] = existing.get("derived", {}).get("standings", [])
    manifest = {"league": league.name, "games": games, "derived": derived,
                "upcoming": existing.get("upcoming", [])}
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    print(f"{key}: backfilled {refetched}/{len(todo)} games "
          f"({len(todo) - refetched} skipped/failed, see warnings above)")
    return manifest


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build the NZIHL/NZWIHL season data warehouse.")
    ap.add_argument("--output", default=".", help="directory to read/write nzihl.json/nzwihl.json/cursor.json in-place (repo root in CI)")
    ap.add_argument("--probe-ahead", type=int, default=20, help="nightly forward-probe batch size per league")
    ap.add_argument("--bootstrap-probe-ahead", type=int, default=60,
                     help="forward-probe batch size used only on a brand-new cursor (first-ever run)")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between fetches (politeness)")
    ap.add_argument("--leagues", default="nzihl,nzwihl", help="comma-separated league keys to build")
    ap.add_argument("--backfill-skaters", action="store_true",
                     help="one-time migration: re-fetch every already-committed game to add the "
                          "`skaters` field (2026-07-20), then exit WITHOUT discovering new games "
                          "or touching cursor.json. Safe to re-run -- already-migrated games are skipped.")
    args = ap.parse_args(argv)

    out_dir = Path(args.output)

    if args.backfill_skaters:
        for key in args.leagues.split(","):
            key = key.strip()
            if not key:
                continue
            backfill_skaters(key, out_dir, sleep=args.sleep)
        return

    cursor_path = out_dir / CURSOR_FILE
    cursor_state = _load_json(cursor_path, {})

    for key in args.leagues.split(","):
        key = key.strip()
        if not key:
            continue
        manifest = build_league(
            key, out_dir, cursor_state,
            probe_ahead=args.probe_ahead,
            bootstrap_probe_ahead=args.bootstrap_probe_ahead,
            sleep=args.sleep,
        )
        print(f"{key}: {len(manifest['games'])} games, cursor={cursor_state[key]}")

    out_dir.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(json.dumps(cursor_state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
