# memory.md — matchavez/nzihl-season-data

Self-context for Claude. README.md is thorough (schema, scraping contracts) and explicitly AI-maintenance-oriented like matchavez/hockey's. This file adds automation ordering/timing rationale and gotchas. Last refreshed: 2026-07-13.

## What this repo is
Nightly warehouse of every **completed** NZIHL/NZWIHL box score, committed as `nzihl.json`/`nzwihl.json` (games + derived streaks/H2H/last-meeting/player-game-logs). No Pages needed — consumers fetch raw.githubusercontent.com directly. Gameids are a **platform-wide shared sequence, not per-league** (NZIHL and NZWIHL gameids interleave in the same numeric space — don't assume a gameid range belongs to one league).

## Layout
`src/nzihl_season/` (scraper + derivation logic), `tests/`, `cursor.json` (bookkeeping: `scanned_through` + `pending` gameids per league — deliberately kept OUT of nzihl.json/nzwihl.json so the data files stay clean), `.github/workflows/build.yml`.

## Automation
- **Runs every 3 hours** (8 cron slots, tightened 2026-07-13 from once-nightly -- see README "Schedule" for the full writeup and the concrete same-day-multi-game case that motivated it). Original anchor `30 16 * * *` UTC = ~04:30 NZST is preserved exactly — **deliberately runs before** the roster pipelines' 17:30 UTC run, so same-morning "last meeting" lookups in the ticker page always see last night's completed games already committed here. The other 7 slots are that same anchor at +3h increments. If you ever touch this schedule, preserve the 04:30 NZST slot's ordering relative to the roster pipelines.
- Only commits when `nzihl.json`/`nzwihl.json` actually change (fixed 2026-07-09) — don't expect a commit every single night if nothing new resolved.

## Related repos
- **matchavez/hockey** — `ticker/`'s last-meeting/H2H and `scoringleaders/`'s player game-logs are sourced from this warehouse.
- **matchavez/nzihl-broadcast-rosters** / **nzwihl-broadcast-rosters** — separate concern (upcoming games only); this repo is completed-games only.
- **matchavez/nzihl-broadcast-assets** — the in-progress Game Summary worker (`summary/worker.js`) is planned to read from this warehouse eventually (not yet wired up as of last check).

## Known bugs (found 2026-07-12, FIXED 2026-07-13)

**Parenthetical names inside an ASSIST list corrupted the goal-line parser** — a distinct
sibling of the already-fixed "scorer's own name has a parenthetical" bug. When a player with
a stored parenthetical (maiden name like Canterbury Inferno #3 "Reagyn Shattock
(Niskakoski)", or a bracketed nickname like "Lucy-Jane(LJ) Hart") appeared as an ASSIST on
someone else's goal, the greedy-name-capture fix (which only guarded the SCORER position)
didn't help — the goal was stored with a garbled `who`, a garbled single-entry `assists`
array, and `teamID: null`. Confirmed live examples: game 2520003 (`who: "Gabrielle Guerin
(Reagyn Shattock", assists: ["Niskakoski)"], teamID: null`) and game 2520016 (`who: "Nerhys
Gordon (Stephanie Koviessen, Lucy-Jane", assists: ["LJ) Hart"], teamID: null`). Net effect:
both players lost the goal/assist from their season totals in `derived.player_game_logs`.
Found while verifying `matchavez/hockey`'s scoringleaders totals against live
`stats_1team.cfm` for 2 teams/league (see that repo's `warehouse-audit.md` + memory.md,
2026-07-12) — ADM/CRD/AST matched exactly, CIN did not, root-caused to this.

**Fix (2026-07-13):** replaced the flat greedy regex split in `parser.py`'s goal-row parsing
with `_split_trailing_balanced_parens()` — counts paren depth from the right to find the true
OUTER, balanced parenthesis pair regardless of what's nested inside it, so it handles the
parenthetical landing on the scorer, on an assist, or on more than one name in the list.
Assist-list comma-splitting also switched to a depth-aware `_split_top_level_commas()`. Two
new fixtures (`nzwihl_2520003.html`, `nzwihl_2520016.html`, fetched live) back a new
regression test, `test_nicknamed_player_as_assist_not_broken_by_extra_parens` in
`tests/test_parser.py`. The two already-committed corrupted game entries in `nzwihl.json`
were hand-rebuilt (re-parsed + `derived` recomputed) rather than waiting for a nightly
run — `build_league()`'s "completed games never change" merge logic means a normal
`workflow_dispatch`/cron run does NOT retroactively fix already-committed games, only newly
discovered ones, so any future bug of this shape needs the same manual one-off rebuild.

**Live-verification result (2026-07-13):** scanned the full rebuilt `nzihl.json` (32 games)
and `nzwihl.json` (20 games) — zero goals with `teamID: null` and zero `who`/assist strings
with unmatched parens anywhere in either file (NZIHL had none of this bug to begin with).
Canterbury Inferno (teamID 675637) — Gabrielle Guerin, Nerhys Gordon, Reagyn Shattock
(Niskakoski), Lucy-Jane(LJ) Hart, and Stephanie Koviessen — all now match live
`stats_1team.cfm` exactly (previously each short by 1 G or A). Spot-checked Pure NZ Admirals
(ADM, NZIHL) and Auckland Steel (AST, NZWIHL) full rosters against live stats_1team.cfm too —
byte-for-byte G/A/PTS match, confirming no regression from the two previously-clean teams.

## New: standings scraping (2026-07-13)

Added `src/nzihl_season/standings.py` -> `derived.standings`. Scrapes
`standings.cfm` once per league per build and stores esportsdesk's own
computed table VERBATIM (rank = page order, W/L/OTW/OTL/PTS as scraped) --
deliberately NOT recomputed from `games`, since the exact NZIHL/NZWIHL
points-per-result rules aren't reliably known here and getting that math
wrong on a live broadcast graphic is a bad failure mode. Wired into
`cli.py`'s `build_league()` with the same best-effort try/except pattern as
`fetch_upcoming` (keeps last-committed standings on a transient scrape
failure, never wipes the field). Team identity resolved against `TEAMS`
(name match), not the page's own trailing short code (which drifts --
same reasoning as `upcoming.py`). Team-cell fusion note: standings.cfm's
"Full Name" + short-code spans have literally NO space between them in the
source (unlike the box score, which needs `_fix_span_fusion()`) --
`td.get_text(" ", strip=True)` already separates them, so no fusion fix
was needed here. 6 tests in `tests/test_standings.py` against two real
fixtures fetched 2026-07-13 (`standings_nzihl.html`, `standings_nzwihl.html`).

Live-verified 2026-07-13: `derived.standings` for all 5 NZIHL + all 4
NZWIHL clubs matched a fresh live `standings.cfm` fetch exactly (rank
order + every column) immediately after the first `workflow_dispatch`
that populated the field.

**Consumer:** `matchavez/hockey`'s `activity-banner/`, `scorebug-l3/`
(coach Player L3 record+rank line) and `ticker/` (pregame "sits Nth" line)
migrated off a live `standings.cfm` fetch onto this field the same day --
see that repo's `memory.md`.

**2026-07-13, later same day: cron tightened from once-nightly to every 3
hours.** Mat flagged a concrete risk after seeing the migration: NZIHL's
upcoming schedule has two DIFFERENT matchups on the same calendar day
(2026-07-18: SkyCity Stampede @ Canterbury Red Devils 17:10, Botany Swarm
@ Dunedin Thunder 18:00) -- with a once-nightly refresh, the second
broadcast's pregame standings line could still reflect the previous
morning's data, missing the first game's result entirely for up to ~24h.
Presented Mat 4 options (manual pre-broadcast refresh / preflight
freshness indicator+button / tighten cron / restore a live fallback); he
chose tightening the cron. `.github/workflows/build.yml` now has 8 cron
slots at 3h intervals instead of 1 -- the original `30 16 * * *` anchor is
untouched (still precedes the roster pipelines' 17:30 UTC run), the other
7 are that same anchor +3h/+6h/etc. Max staleness for "game finished
hours ago, not yet reflected" dropped from ~24h to ~3h. This does NOT
solve the case of two games genuinely overlapping in time (the second
game's broadcast can start before the first has finished, which no
refresh cadence fixes) -- only the "stale by up to a day" case. No-op
runs (no new games) still don't commit, so this doesn't spam history.

## Sync note
Keep this file and README.md in sync with every meaningful change. If they drift, flag it to Mat and get approval before publishing the sync rather than doing it silently.
