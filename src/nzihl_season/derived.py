"""Season-level derived stats, computed fresh at build time from the full
`games` list -- never stored incrementally, so they're always consistent
with whatever games are currently committed (idempotent rebuilds).

- last5: each team's most recent 5 results, most-recent-first.
- streak: current run length in the same direction (win vs not-a-win).
- head_to_head: per unordered team pair, career meeting record + last result.
- player_game_logs: per player (normalised name -> display name), one entry
  per game they DRESSED for (2026-07-20: includes scoreless games, sourced
  from each game's `skaters` line -- see compute_player_game_logs docstring
  for why this matters and the pre-migration fallback behavior).
"""
from __future__ import annotations

from .parser import normalize_name


def _game_sort_key(g: dict):
    # Real calendar date first (None sorts last), gameid as a same-date
    # tiebreak (double-headers share a date but not a gameid).
    return (g.get("date") or "9999-99-99", g["gameid"])


def _result_for(team_id: int, g: dict) -> str | None:
    """W / L / OTW / OTL / SOW / SOL for `team_id` in game `g`, or None if
    it didn't play in this game."""
    if g["away"]["teamID"] == team_id:
        us, them = g["away"], g["home"]
    elif g["home"]["teamID"] == team_id:
        us, them = g["home"], g["away"]
    else:
        return None
    won = us["total"] > them["total"]
    suffix = g["finalType"]  # "" | "OT" | "SO"
    if not suffix:
        return "W" if won else "L"
    tag = "OT" if suffix == "OT" else "SO"
    return f"{tag}W" if won else f"{tag}L"


def compute_last5_and_streaks(games: list[dict]) -> tuple[dict, dict]:
    ordered = sorted(games, key=_game_sort_key)
    by_team: dict[int, list[dict]] = {}
    for g in ordered:
        for side in ("away", "home"):
            tid = g[side]["teamID"]
            if tid is None:
                continue
            res = _result_for(tid, g)
            if res is None:
                continue
            by_team.setdefault(tid, []).append({"gameid": g["gameid"], "date": g.get("date"), "result": res})

    last5 = {str(tid): list(reversed(entries))[:5] for tid, entries in by_team.items()}

    streaks = {}
    for tid, entries in by_team.items():
        if not entries:
            continue
        last_won = entries[-1]["result"].startswith("W") or entries[-1]["result"].startswith("OTW") or entries[-1]["result"].startswith("SOW")
        count = 0
        for e in reversed(entries):
            won = e["result"] in ("W", "OTW", "SOW")
            if won == last_won:
                count += 1
            else:
                break
        streaks[str(tid)] = {"type": "W" if last_won else "L", "count": count}

    return last5, streaks


def compute_head_to_head(games: list[dict]) -> dict:
    h2h: dict[str, dict] = {}
    ordered = sorted(games, key=_game_sort_key)
    for g in ordered:
        a_id, h_id = g["away"]["teamID"], g["home"]["teamID"]
        if a_id is None or h_id is None:
            continue
        key = "|".join(str(x) for x in sorted((a_id, h_id)))
        rec = h2h.setdefault(key, {"teamA": min(a_id, h_id), "teamB": max(a_id, h_id),
                                    "teamA_wins": 0, "teamB_wins": 0, "games": []})
        a_won = g["away"]["total"] > g["home"]["total"]
        winner_id = a_id if a_won else h_id
        if winner_id == rec["teamA"]:
            rec["teamA_wins"] += 1
        else:
            rec["teamB_wins"] += 1
        rec["games"].append(g["gameid"])
        rec["last_meeting"] = {
            "gameid": g["gameid"],
            "date": g.get("date"),
            "winner_teamID": winner_id,
            "away_total": g["away"]["total"],
            "home_total": g["home"]["total"],
            "finalType": g["finalType"],
        }
    return h2h


def compute_player_game_logs(games: list[dict]) -> dict:
    """Keyed by normalised player name (to merge case/whitespace variants);
    each entry keeps the last-seen display spelling.

    2026-07-20 fix: this used to build entries ONLY from `goals` (the
    scoring-summary event list), which can only ever say who scored or
    assisted -- a player who dressed and recorded nothing was simply absent
    from their own log, not present with a zero. That silently broke any
    "consecutive games" logic downstream: a true streak-breaking scoreless
    game just didn't exist in the array to break on, so a gap could get
    counted as unbroken, and a "last game" fact could end up describing a
    game from days/weeks earlier because the truly-most-recent (scoreless)
    game had no entry at all. See matchavez/hockey computeFact()/
    assignDescriptors(), which both walk this array assuming it already
    means "every game, zero or not" -- that assumption is what this fixes.

    Now sourced from each game's `skaters` field (added to game.py's schema
    2026-07-20) when present: one entry per player who appears in that
    game's SKATERS table, with real G/A values including zero. Games
    committed before that change don't have `skaters` yet -- see the
    backfill in cli.py (`--backfill-skaters`) for retroactively re-fetching
    those. Until a game is backfilled, it falls back to the old goals-only
    reconstruction here, so nothing breaks mid-migration; it just keeps the
    old (documented) limitation for not-yet-backfilled games specifically.
    """
    logs: dict[str, dict] = {}

    def entry_for(name: str, team_id: int | None):
        key = normalize_name(name)
        if not key:
            return None
        e = logs.setdefault(key, {"name": name, "teamID": team_id, "games": {}})
        e["name"] = name  # keep most-recent display spelling
        if team_id is not None:
            e["teamID"] = team_id
        return e

    ordered = sorted(games, key=_game_sort_key)
    for g in ordered:
        skater_lines = g.get("skaters")
        if skater_lines:
            for line in skater_lines:
                e = entry_for(line["name"], line.get("teamID"))
                if e is None:
                    continue
                e["games"][g["gameid"]] = {
                    "gameid": g["gameid"],
                    "date": g.get("date"),
                    "goals": line.get("g", 0),
                    "assists": line.get("a", 0),
                }
            continue

        # Pre-migration fallback: no `skaters` field on this game yet, so
        # scoreless games for a player are unavoidably absent here, same as
        # the original implementation.
        for goal in g["goals"]:
            e = entry_for(goal["who"], goal.get("teamID"))
            if e is None:
                continue
            gl = e["games"].setdefault(g["gameid"], {"gameid": g["gameid"], "date": g.get("date"), "goals": 0, "assists": 0})
            gl["goals"] += 1
            for assist_name in goal["assists"]:
                ae = entry_for(assist_name, None)
                if ae is None:
                    continue
                agl = ae["games"].setdefault(g["gameid"], {"gameid": g["gameid"], "date": g.get("date"), "goals": 0, "assists": 0})
                agl["assists"] += 1

    out = {}
    for key, e in logs.items():
        game_logs = sorted(e["games"].values(), key=lambda x: (x.get("date") or "9999-99-99", x["gameid"]))
        out[key] = {"name": e["name"], "teamID": e["teamID"], "games": game_logs}
    return out


def build_derived(games: list[dict]) -> dict:
    last5, streaks = compute_last5_and_streaks(games)
    return {
        "last5": last5,
        "streak": streaks,
        "head_to_head": compute_head_to_head(games),
        "player_game_logs": compute_player_game_logs(games),
    }
