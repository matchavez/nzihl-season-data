"""Assemble a single game record (the warehouse's per-game schema) from a
parsed box score."""
from __future__ import annotations

from dataclasses import asdict

from .parser import TeamLine


def _team_dict(t: TeamLine) -> dict:
    d = asdict(t)
    return d


def build_game(gameid: int, league: str, parsed: dict) -> dict:
    header = parsed["header"]
    return {
        "gameid": gameid,
        "league": league,
        "date": header.get("date"),
        "away": _team_dict(parsed["away"]),
        "home": _team_dict(parsed["home"]),
        "goals": parsed["goals"],
        "pens": parsed["pens"],
        "goalies": parsed["goalies"],
        # 2026-07-20: full per-skater per-game line (see parser.py's
        # skater_lines) -- the authoritative source for player_game_logs
        # (derived.py), since `goals` alone can't say who dressed but didn't
        # score. Absent on games committed before this date; derived.py
        # falls back to the old goals-only reconstruction for those.
        "skaters": parsed.get("skater_lines", []),
        "finalType": header.get("final_type", ""),
    }
