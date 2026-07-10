"""Fetch the full-season schedule page and extract games that haven't
been played yet ("upcoming"). Complements `games` (built from completed
box scores via discovery.py's gameid probing) with the rest of the
season's known fixtures, so consumers -- e.g. the hockey/team/ page's
schedule widget -- can show the *whole* season, not just what's already
been played.

Unlike nzihl-broadcast-rosters' boxscores.json, this has NO lookahead
cap: it's whatever schedules.cfm's season-wide widget currently shows.
That repo's ~11-day window is a deliberate choice for ITS purpose
(roster PDF prep, hockeyrosters "coming soon" cards); this module
serves a different consumer with a different need and is intentionally
independent of it.

Team identity comes straight from the schedule page's own
`stats_1team.cfm?teamID=...` links (teamID + the link's display-name
text) -- we deliberately do NOT reuse the page's own short-code link
(e.g. "WAA" for the Admirals), since that drifts from the code our own
`games` archive already normalises to ("ADM"). Consumers should resolve
codes via teamID against the `games` array's own team objects, not
anything carried on these upcoming entries.
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .http import fetch

NZ_TZ = ZoneInfo("Pacific/Auckland")
_SCHEDULE_URL = "https://admin.esportsdesk.com/leagues/schedules.cfm"

# Same shape as nzihl-broadcast-rosters/src/nzihl_rosters/schedule.py --
# kept independently here rather than imported cross-repo.
_DAY_HEADER_RE = re.compile(
    r"<h5[^>]*>\s*(?:<strong>\s*)?"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(\d{1,2})\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+"
    r"(\d{4})",
    re.IGNORECASE,
)
_TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_TEAM_LINK_RE = re.compile(
    r'<a[^>]+stats_1team\.cfm\?[^"\'<>]*teamID=(\d+)[^"\'<>]*"[^>]*>([\s\S]*?)</a>',
    re.IGNORECASE,
)
_BOXSCORE_RE = re.compile(r"hockey_boxscores\.cfm", re.IGNORECASE)
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b", re.IGNORECASE)
_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}


def _strip_tags(s: str) -> str:
    return unescape(_TAG_RE.sub(" ", s)).strip()


def _row_teams(row_html: str) -> list[tuple[int, str]]:
    """First-seen (teamID, display name) pairs from a row, deduplicated.
    Each team is linked twice (full name, then short code); dedup-by-id
    keeps the first (full-name) occurrence."""
    seen_ids: set[int] = set()
    out: list[tuple[int, str]] = []
    for m in _TEAM_LINK_RE.finditer(row_html):
        tid = int(m.group(1))
        name = _strip_tags(m.group(2))
        if tid not in seen_ids and name:
            seen_ids.add(tid)
            out.append((tid, name))
    return out


def _row_time(row_html: str) -> tuple[int, int] | None:
    m = _TIME_RE.search(_strip_tags(row_html))
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour, minute


def parse_upcoming(html: str) -> list[dict]:
    """Pure parse -- no network. Returns every game on the page that has
    a time (upcoming) and no boxscore link (not yet final), sorted
    chronologically."""
    out: list[dict] = []
    headers = list(_DAY_HEADER_RE.finditer(html))
    for i, h in enumerate(headers):
        day = int(h.group(1))
        month = _MONTHS[h.group(2).lower()]
        year = int(h.group(3))
        day_date = datetime(year, month, day, tzinfo=NZ_TZ)
        block_start = h.end()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(html)
        block = html[block_start:block_end]

        for tr in _TR_RE.finditer(block):
            row = tr.group(1)
            if _BOXSCORE_RE.search(row):
                continue  # already final -- that's `games`' job, not ours
            teams = _row_teams(row)
            if len(teams) < 2:
                continue
            t = _row_time(row)
            if not t:
                continue
            hour, minute = t
            start = day_date.replace(hour=hour, minute=minute)
            (away_id, away_name), (home_id, home_name) = teams[0], teams[1]
            out.append({
                "date": start.strftime("%Y-%m-%d"),
                "time": start.strftime("%H:%M"),
                "away": {"teamID": away_id, "name": away_name},
                "home": {"teamID": home_id, "name": home_name},
            })

    out.sort(key=lambda g: (g["date"], g["time"]))
    return out


def fetch_upcoming(client_id: int, league_id: int) -> list[dict]:
    """Fetch schedules.cfm for one league and parse it. Raises on a
    fetch failure (caller decides the fallback -- see cli.py)."""
    params = {"clientid": client_id, "leagueid": league_id}
    url = f"{_SCHEDULE_URL}?{urlencode(params)}"
    html = fetch(url)
    return parse_upcoming(html)
