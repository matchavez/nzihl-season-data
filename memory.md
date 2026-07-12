# memory.md — matchavez/nzihl-season-data

Self-context for Claude. README.md is thorough (schema, scraping contracts) and explicitly AI-maintenance-oriented like matchavez/hockey's. This file adds automation ordering/timing rationale and gotchas. Last refreshed: 2026-07-11.

## What this repo is
Nightly warehouse of every **completed** NZIHL/NZWIHL box score, committed as `nzihl.json`/`nzwihl.json` (games + derived streaks/H2H/last-meeting/player-game-logs). No Pages needed — consumers fetch raw.githubusercontent.com directly. Gameids are a **platform-wide shared sequence, not per-league** (NZIHL and NZWIHL gameids interleave in the same numeric space — don't assume a gameid range belongs to one league).

## Layout
`src/nzihl_season/` (scraper + derivation logic), `tests/`, `cursor.json` (bookkeeping: `scanned_through` + `pending` gameids per league — deliberately kept OUT of nzihl.json/nzwihl.json so the data files stay clean), `.github/workflows/build.yml`.

## Automation
- Cron `30 16 * * *` UTC = ~04:30 NZST — **deliberately runs before** the roster pipelines' 17:30 UTC run, so same-morning "last meeting" lookups in the ticker page always see last night's completed games already committed here. If you ever touch this cron, preserve that ordering.
- Only commits when `nzihl.json`/`nzwihl.json` actually change (fixed 2026-07-09) — don't expect a commit every single night if nothing new resolved.

## Related repos
- **matchavez/hockey** — `ticker/`'s last-meeting/H2H and `scoringleaders/`'s player game-logs are sourced from this warehouse.
- **matchavez/nzihl-broadcast-rosters** / **nzwihl-broadcast-rosters** — separate concern (upcoming games only); this repo is completed-games only.
- **matchavez/nzihl-broadcast-assets** — the in-progress Game Summary worker (`summary/worker.js`) is planned to read from this warehouse eventually (not yet wired up as of last check).

## Known bugs (open, found 2026-07-12)

**Parenthetical names inside an ASSIST list corrupt the goal-line parser** — a distinct,
unfixed sibling of the already-fixed "scorer's own name has a parenthetical" bug. When a
player with a stored parenthetical (maiden name like Canterbury Inferno #3 "Reagyn Shattock
(Niskakoski)", or a bracketed nickname like "Lucy-Jane(LJ) Hart") appears as an ASSIST on
someone else's goal, the greedy-name-capture fix (which only guards the SCORER position)
doesn't help — the goal is stored with a garbled `who`, a garbled single-entry `assists` array,
and `teamID: null`. Confirmed live examples: game 2520003 (`who: "Gabrielle Guerin (Reagyn
Shattock", assists: ["Niskakoski)"], teamID: null`) and game 2520016 (`who: "Nerhys Gordon
(Stephanie Koviessen, Lucy-Jane", assists: ["LJ) Hart"], teamID: null`). Net effect: both
players lose the goal/assist from their season totals in `derived.player_game_logs`. Found
while verifying `matchavez/hockey`'s scoringleaders totals against live `stats_1team.cfm` for
2 teams/league (see that repo's `warehouse-audit.md` + memory.md, 2026-07-12) — ADM/CRD/AST
matched exactly, CIN did not, root-caused to this. **Not fixed yet** — recommend porting the
existing greedy-capture treatment to assist names in the goal-line regex, then re-verifying
CIN's totals match live before anything downstream trusts this repo for season scoring totals.

## Sync note
Keep this file and README.md in sync with every meaningful change. If they drift, flag it to Mat and get approval before publishing the sync rather than doing it silently.
