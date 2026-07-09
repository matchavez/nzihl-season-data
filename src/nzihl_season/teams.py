"""Team registry for both leagues -- kept in sync with the REG table in
matchavez/hockey's README.md ("Shared infrastructure" section). teamID is
the esportsdesk identity; it's how we tell which league a probed gameid
belongs to, since (see discovery.py) gameids are NOT scoped per-league by
the clientid/leagueid query params -- they're a single global sequence
shared across every esportsdesk customer, and a bare `gameid=` lookup
returns the same content regardless of what clientid/leagueid you pass.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamMeta:
    team_id: int
    code: str
    name: str
    league: str  # "NZIHL" | "NZWIHL"


TEAMS: dict[int, TeamMeta] = {
    674110: TeamMeta(674110, "ADM", "Pure NZ Admirals", "NZIHL"),
    675633: TeamMeta(675633, "CRD", "Canterbury Red Devils", "NZIHL"),
    675634: TeamMeta(675634, "DUN", "Dunedin Thunder", "NZIHL"),
    675635: TeamMeta(675635, "SCS", "SkyCity Stampede", "NZIHL"),
    674109: TeamMeta(674109, "BSW", "Botany Swarm", "NZIHL"),
    675636: TeamMeta(675636, "AST", "Auckland Steel", "NZWIHL"),
    675637: TeamMeta(675637, "CIN", "Canterbury Inferno", "NZWIHL"),
    675638: TeamMeta(675638, "DTW", "Dunedin Thunder Women", "NZWIHL"),
    675639: TeamMeta(675639, "WLD", "Wakatipu Wild", "NZWIHL"),
}

NZIHL_TEAM_IDS = {tid for tid, t in TEAMS.items() if t.league == "NZIHL"}
NZWIHL_TEAM_IDS = {tid for tid, t in TEAMS.items() if t.league == "NZWIHL"}

LEAGUE_TEAM_IDS = {"NZIHL": NZIHL_TEAM_IDS, "NZWIHL": NZWIHL_TEAM_IDS}


@dataclass(frozen=True)
class LeagueCfg:
    key: str            # "nzihl" | "nzwihl"
    name: str            # "NZIHL" | "NZWIHL"
    client_id: int
    league_id: int
    team_ids: frozenset
    # First gameid confirmed (empirically, 2026-07-09) to belong to this
    # league's current season block. Used only to bootstrap a brand-new
    # cursor file -- once nzihl.json/nzwihl.json exist, the committed
    # `cursor` field is authoritative and these are never consulted again.
    seed_gameid: int


LEAGUES: dict[str, LeagueCfg] = {
    "nzihl": LeagueCfg("nzihl", "NZIHL", 7131, 35499, frozenset(NZIHL_TEAM_IDS), 2519913),
    "nzwihl": LeagueCfg("nzwihl", "NZWIHL", 7132, 35501, frozenset(NZWIHL_TEAM_IDS), 2520001),
}


def team_league(team_id: int) -> str | None:
    t = TEAMS.get(team_id)
    return t.league if t else None
