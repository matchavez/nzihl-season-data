# matchavez/nzihl-season-data — NZIHL/NZWIHL Season Data Warehouse

Nightly GitHub Action that scrapes every **completed** NZIHL/NZWIHL box score into
two committed JSON files, so broadcast overlay pages (matchavez/hockey) can make
season-level claims -- streaks, head-to-head records, last meetings, player game
logs -- from one cached file instead of live-probing esportsdesk during a broadcast.

No GitHub Pages needed; consumers fetch straight from raw.githubusercontent.com:

```
https://raw.githubusercontent.com/matchavez/nzihl-season-data/main/nzihl.json
https://raw.githubusercontent.com/matchavez/nzihl-season-data/main/nzwihl.json
```

> **This README is optimized for AI-assisted maintenance**, same convention as
> matchavez/hockey's own README. Record every parser gotcha here; update this
> file in the same commit as any parser change.

---

## Output schema

`nzihl.json` / `nzwihl.json`:

```jsonc
{
  "league": "NZIHL",
  "games": [
    {
      "gameid": 2519941,
      "league": "NZIHL",
      "date": "2026-07-04",              // null if the header date couldn't be parsed
      "away": {
        "teamID": 675635, "name": "SkyCity Stampede", "code": "SCS",
        "total": 3, "sog_periods": [9, 8, 8, 2], "pp": "0/2", "pim": 2
      },
      "home": { "...": "same shape" },
      "goals": [
        { "per": "OT", "t": "3:17", "no": 55, "who": "Max Roth",
          "assists": ["Conner Jean"], "flag": "", "teamID": 675635 }
      ],
      "pens": [
        { "per": "2", "t": "5:15", "no": 62, "who": "Rudolfs Lapsa",
          "inf": "Holding", "dur": "2 Minutes", "teamID": 674109, "teamPen": false }
      ],
      "goalies": [
        { "teamID": 675635, "name": "Aston Brookes", "sa": 24, "ga": 2, "sv": 22, "mp": "61:43" }
      ],
      "finalType": "OT"                  // "" | "OT" | "SO"
    }
  ],
  "derived": {
    "last5": { "<teamID>": [ { "gameid", "date", "result" }, ... ] },   // most-recent-first, max 5
    "streak": { "<teamID>": { "type": "W"|"L", "count": N } },
    "head_to_head": {
      "<lowTeamID>|<highTeamID>": {
        "teamA": <lowTeamID>, "teamB": <highTeamID>,
        "teamA_wins": N, "teamB_wins": N,
        "games": [gameid, ...],
        "last_meeting": { "gameid", "date", "winner_teamID", "away_total", "home_total", "finalType" }
      }
    },
    "player_game_logs": {
      "<normalized-name>": { "name": "Display Name", "teamID": <int|null>,
        "games": [ { "gameid", "date", "goals", "assists" }, ... ] }
    }
  }
}
```

`result` values in `last5`/streak math: `W` / `L` / `OTW` / `OTL` / `SOW` / `SOL`.

Cursor/bookkeeping state (`scanned_through`, `pending` gameids per league) lives in
a **separate** `cursor.json`, deliberately kept out of `nzihl.json`/`nzwihl.json` --
see "Idempotency" below for why.

---

## esportsdesk scraping contracts (read before touching `parser.py`)

Everything in matchavez/hockey's README ("esportsdesk scraping contracts") applies
here too (span fusion, `OVERTIME PERIOD 1` heading regex, goal-type pill, SOG
parens, GOALIES columns, `TIME REMAINING` clocks). Three things this repo's
parser does differently or additionally, found while building it (2026-07-09):

- **Gameids are a single sequence shared across every esportsdesk customer on
  the platform, not scoped per league/client.** Querying
  `hockey_boxscores.cfm?...&gameid=N` with NZWIHL's `clientid`/`leagueid` returns
  the exact same page as querying with NZIHL's -- the params are cosmetic. A
  whole season (played AND not-yet-played games) gets its gameids allocated as
  one contiguous block when the schedule is created:
  - **NZIHL 2026: 2519913-2519952** (40 ids)
  - **NZWIHL 2026: 2520001-2520024** (24 ids)

  Other customers' (non-hockey, non-NZ) games sit interleaved around and
  between those blocks. `discovery.py` classifies every probed id by whether
  its two `teamID`s belong to the league's own roster (`teams.py`) -- never by
  the `clientid`/`leagueid` query params, which don't gate anything.

- **The box score's own header carries the real game date, time, venue, and a
  literal `FINAL`, `FINAL /OT`, or `FINAL /SO` status string** -- no need to
  cross-reference `schedules.cfm` (which only ever shows the *current round*
  anyway, useless for historical games). `finalType` comes straight from this
  header text. A pre-game shell has no such status line at all -- that
  absence, plus an empty goals list, is what "not complete yet" means here.

- **A player whose display name itself carries a parenthetical** (a maiden
  name / nickname, e.g. `"Reagyn Shattock (Niskakoski)"`, `"Lucy-Jane(LJ)
  Hart"`) breaks a *lazy* name-then-assists regex: the lazy quantifier stops
  at the FIRST `(`, so the nickname paren gets misread as the start of the
  assist list. A first pass (2026-07-09) fixed this with a flat *greedy*
  regex, but that only covered the case where the parenthetical name was the
  **scorer** -- when the same shape occurs on an **assist** instead (e.g.
  `"Gabrielle Guerin (Reagyn Shattock (Niskakoski))"`), a flat greedy regex
  still splits at the wrong `(` (the last literal one, which lands inside the
  nested nickname paren), corrupting `who`, `assists`, and dropping `teamID`
  to `null`. Found 2026-07-12, fixed 2026-07-13 by replacing the regex split
  with `_split_trailing_balanced_parens()` (`parser.py`), which counts paren
  depth from the right to find the true OUTER balanced pair no matter what's
  nested inside it -- correct regardless of whether the parenthetical name is
  the scorer, an assist, or both. Assist-list comma-splitting was similarly
  switched to a depth-aware `_split_top_level_commas()`. **The live
  ticker/scorebug/activity-banner JS parsers in matchavez/hockey still use
  the original lazy version** and will misparse this exact case (either
  position) if a nicknamed player is involved in a goal during a live
  broadcast -- worth porting this fix over if revisited.

- **`SHOOTOUT` is a structurally different table** (per-team subheading + a
  name/check-or-cross-icon table, no jersey#/parens/clock) from the normal
  per-period scoring rows. Shootout attempts are correctly excluded from
  `goals` (they aren't "goals" for period/player-stat purposes -- only the
  aggregate SO tally in the score table's `SO` column decides `finalType`).

- **A penalty row can lack a jersey number in TWO different ways** that must
  not be confused: `"Team Penalty (Canterbury Inferno) Delay of game ..."` is
  a genuine team penalty (`teamPen: true`, `who: ""`), while
  `"Joel Gerard (SkyCity Stampede) Interference ..."` is a normal PLAYER
  penalty where esportsdesk simply didn't record a jersey number
  (`teamPen: false`, `who: "Joel Gerard"`, `no: null`). Distinguished by the
  literal `"Team Penalty"` label, not by number-presence.

---

## Gameid discovery (`discovery.py`)

- **Bootstrap** (no `cursor.json` entry for a league yet): probe downward from
  a known-live seed id (`teams.py`'s `LeagueCfg.seed_gameid`) until 10
  consecutive misses (HTTP 500 = "no game exists at this id") confirm the true
  season-start edge, then sweep forward from there.
- **Nightly**: re-check every id in `pending` (belongs to this league, wasn't
  complete last time); then probe forward from `scanned_through + 1` for
  `--probe-ahead` (default 20, per Mat's "+~15" spec) new ids. Each id
  resolves to `complete` / `pending` / `not_ours` / `missing`.
- Politeness: **1 fetch/sec** (`--sleep 1.0`), since discovery is real HTTP
  traffic against admin.esportsdesk.com, same convention as the roster
  pipelines.
- `schedules.cfm` is deliberately NOT used for discovery or `finalType` --
  it only ever shows the current round, useless once a round has passed. It
  might still be worth wiring in later purely as a same-day "is this
  currently live" signal, but nothing here depends on it.

## Idempotency

The gameid space being shared with unrelated esportsdesk customers means
`cursor.json`'s `scanned_through` legitimately advances on **every** run, even
when zero new games exist for our two leagues (it's recording "confirmed
nothing of ours between here and there"). That churn is deliberately kept out
of `nzihl.json`/`nzwihl.json`: those two files -- the actual deliverable every
overlay page fetches -- are byte-for-byte stable across reruns that don't
discover a genuinely new completed game. If you're checking "did a rerun
produce a no-op," diff `nzihl.json`/`nzwihl.json`, not `cursor.json`.

---

## Development

```
pip install -e . pytest
PYTHONPATH=src pytest tests/ -v
python -m nzihl_season --leagues nzihl,nzwihl --output . --probe-ahead 20 --sleep 1.0
```

`tests/fixtures/*.html` are real captured box scores (not hand-written
approximations -- see matchavez/nzihl-broadcast-rosters's own lesson that
simplified fixtures miss real markup quirks): `nzihl_2519941_ot.html` is the
Max Roth overtime winner (SCS 3, BSW 2) that originally caught the
`OVERTIME PERIOD 1` heading bug; `nzwihl_2520008.html` goes to a shootout and
has the nicknamed-player-as-SCORER row (Reagyn Shattock); `nzwihl_2520003.html`
and `nzwihl_2520016.html` (added 2026-07-13) have the nicknamed-player-as-
ASSIST case (Reagyn Shattock, Lucy-Jane(LJ) Hart) that the first paren fix
missed -- see the parser gotcha above.

## Consumers

- `matchavez/hockey`'s `ticker/` page uses this warehouse for its pregame
  "last meeting" line and head-to-head record instead of a live 25-fetch
  sequential-gameid probe (kept as a fallback if the warehouse fetch fails).
