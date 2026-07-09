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
        "finalType": header.get("final_type", ""),
    }
