"""Shared HTTP session with browser-like headers, matching the convention
established in matchavez/nzihl-broadcast-rosters (admin.esportsdesk.com
returns 403 to non-browser User-Agents).

esportsdesk box-score URLs occasionally respond with a tiny JS redirect stub
instead of the real page:

    <SCRIPT LANGUAGE="javascript">
    this.location = "hockey_boxscores.cfm?leagueID=35501&clientID=7132&gameID=2520001&link=Pro&xx=5";
    //-->
    </SCRIPT>

This seems to fire intermittently (not simply "first request in a session" --
observed on the 4th request of a session after several successful direct
fetches). `fetch_boxscore()` detects this stub and follows it once,
re-appending `printPage=1` since the redirect target doesn't carry it.
"""
from __future__ import annotations

import re

import requests

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-NZ,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_BASE = "https://admin.esportsdesk.com/leagues/"

_REDIRECT_RE = re.compile(r'this\.location\s*=\s*"([^"]+)"', re.IGNORECASE)

_SESSION: requests.Session | None = None


def session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update(_HEADERS)
        _SESSION = s
    return _SESSION


class FetchError(Exception):
    """Raised for a non-2xx response (including esportsdesk's 500 for an
    unallocated gameid -- callers use this to mean 'no game exists here')."""


def fetch(url: str, *, timeout: int = 30) -> str:
    """GET `url`, following one esportsdesk JS-redirect stub if seen."""
    resp = session().get(url, timeout=timeout)
    if resp.status_code != 200:
        raise FetchError(f"{resp.status_code} for {url}")
    text = resp.text
    m = _REDIRECT_RE.search(text) if len(text) < 1000 else None
    if m:
        target = m.group(1)
        if not target.startswith("http"):
            target = _BASE + target
        if "printPage=" not in target:
            target += ("&" if "?" in target else "?") + "printPage=1"
        resp2 = session().get(target, timeout=timeout)
        if resp2.status_code != 200:
            raise FetchError(f"{resp2.status_code} for {target} (redirected from {url})")
        return resp2.text
    return text


def boxscore_url(gameid: int, client_id: int, league_id: int) -> str:
    return (
        f"{_BASE}hockey_boxscores.cfm?clientid={client_id}&leagueid={league_id}"
        f"&gameid={gameid}&printPage=1"
    )


def fetch_boxscore(gameid: int, client_id: int, league_id: int, *, timeout: int = 30) -> str:
    return fetch(boxscore_url(gameid, client_id, league_id), timeout=timeout)
