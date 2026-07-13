"""Standings scraper: `standings.cfm?clientid=&leagueid=&printPage=1` ->
`derived.standings`.

**Deliberately NOT recomputed from `games`.** NZIHL/NZWIHL's exact
points-per-result rules (regulation win/OT win/OT loss/shootout win/etc.)
aren't fully documented anywhere this repo can rely on, and getting that
math wrong on a live broadcast graphic (a producer's on-air "sits 5th in
the NZIHL" line) is a bad failure mode. Instead this module captures the
table esportsdesk ALREADY computed, verbatim -- same convention as
`upcoming.py` capturing schedules.cfm's own text rather than re-deriving a
schedule from `games`. Rank = row order on the page (esportsdesk's own
sort), never recomputed here either.

Markup contract (found 2026-07-13, real page fetched via curl with a
browser User-Agent -- admin.esportsdesk.com 403s a bare/no-UA request,
which is why an early sandbox note incorrectly logged it as "blocked"):
one `<table>`, header row of `<th>`, then one `<tr>` of `<td>` per team.
Cols: `Team | GP | W | L | OTW | OTL | PTS | P% | GF | GA | DIFF | GF/G |
GA/G | PIM | STR | L10` -- only the first seven matter here. The Team cell
holds TWO responsive `<span>`s (full name, then short code) with **no
literal space between them** in the source -- e.g.
`<span class="d-sm-inline d-none">SkyCity Stampede</span><span
class="d-sm-none d-inline" ...>SCS</span>`. Unlike parser.py's box-score
span fusion (which needs `_fix_span_fusion()` because raw `.textContent`
concatenates with zero separator), calling `td.get_text(" ", strip=True)`
here already inserts a space between the two spans' text -- so this file
does NOT need that helper, and `_TEAM_CELL_RE` (parser.py's own
`name<space>CODE` splitter) matches cleanly on the result.

Team identity is resolved against this repo's own canonical `TEAMS`
registry (name match, not the page's own trailing short code) for the same
reason `upcoming.py` prefers the schedule page's full-name link over its
short-code link: esportsdesk's own codes have drifted from ours before
(e.g. Admirals "WAA" vs our normalised "ADM"). The page's own code is kept
only as a last-resort fallback if a row's name doesn't match any known
team (should not happen for the 9 currently-active clubs; Auckland Mako is
stood down for 2026 and simply won't have a row).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .http import fetch
from .parser import normalize_name
from .teams import LEAGUES, TEAMS

_STANDINGS_URL = "https://admin.esportsdesk.com/leagues/standings.cfm"

# Same pattern as parser.py's `_TEAM_CELL_RE` (box-score team cell
# fusion) -- kept as an independent copy here rather than imported, since
# the two modules' fusion pre-processing differs (see module docstring).
_TEAM_CELL_RE = re.compile(r"^(.*?)\s+([A-Z]{2,4})$")


def _int(s: str) -> int:
    s = (s or "").strip()
    return int(s) if s.lstrip("-").isdigit() else 0


def _split_team_cell(text: str) -> tuple[str, str]:
    m = _TEAM_CELL_RE.match(text.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return text.strip(), ""


def parse_standings(html: str, league_key: str) -> list[dict]:
    """Pure parse -- no network. Returns entries in rank order (page order),
    each `{code, name, teamID, gp, w, l, otw, otl, pts}`."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    league = LEAGUES.get(league_key)
    candidates = (
        [(tid, TEAMS[tid]) for tid in league.team_ids] if league else list(TEAMS.items())
    )

    out: list[dict] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue  # header row (th-only) or a malformed/spacer row
        texts = [c.get_text(" ", strip=True) for c in cells]
        raw_name, esd_code = _split_team_cell(texts[0])
        norm_cell = normalize_name(texts[0])
        match = next(
            (t for _, t in candidates if normalize_name(t.name) and normalize_name(t.name) in norm_cell),
            None,
        )
        out.append({
            "code": match.code if match else esd_code,
            "name": match.name if match else raw_name,
            "teamID": match.team_id if match else None,
            "gp": _int(texts[1]),
            "w": _int(texts[2]),
            "l": _int(texts[3]),
            "otw": _int(texts[4]),
            "otl": _int(texts[5]),
            "pts": _int(texts[6]),
        })
    return out


def fetch_standings(league_key: str) -> list[dict]:
    """Fetch standings.cfm for one league and parse it. Raises on a fetch
    failure -- caller (cli.py) decides the fallback, same convention as
    `upcoming.fetch_upcoming()`."""
    league = LEAGUES[league_key]
    url = f"{_STANDINGS_URL}?clientid={league.client_id}&leagueid={league.league_id}&printPage=1"
    html = fetch(url)
    return parse_standings(html, league_key)
