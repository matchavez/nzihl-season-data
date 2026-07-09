"""Box-score parser: `hockey_boxscores.cfm?...&printPage=1` -> structured dict.

Ports the battle-tested parser from matchavez/hockey (ticker/index.html's
`parse()`, itself shared with scorebug/ and activity-banner/) to Python, using
BeautifulSoup instead of DOMParser. Every gotcha below is recorded in
matchavez/hockey's README ("esportsdesk scraping contracts") -- read that
before touching this file.

Contracts carried over:
  - Span fusion: `#no FirstName` sits in a responsive span with the surname
    trailing OUTSIDE it, sometimes with NO space. Fix: force a space after
    every `</span>` before parsing.
  - Name case: source names arrive ALL-CAPS or all-lowercase at random --
    `proper_case()` normalises, hyphen/apostrophe-aware.
  - OT period heading: "OVERTIME PERIOD 1", not just "OVERTIME" -- the
    heading regex must allow a trailing `(\\s*\\d+)?` or OT goals silently
    fold into the 3rd period (bug that lived in 3 pages until 2026-07-07).
  - Goal-type pill: scoring rows carry a middle "PPG"/"SHG"/"ENG"/"PS" cell
    only when the row has 3+ cells.
  - SOG cell: "38 (13-11-14)" -- total shots, per-period counts in parens.
  - GOALIES table cols: # | Name | SA | GA | SV | SV% | MP | PIM; skip a
    row whose MP is blank/"0:00" (didn't play).
  - Assist lists carry no jersey numbers -- resolved from the SKATERS table.
  - Pre-game box scores are shells: teams parse, SCORING/PENALTY tables are
    "No Scoring"/"No Penalties" placeholders. A completed game always has
    goals (a real final can't be 0-0 -- OT/SO decides).

New contract found while building this warehouse (2026-07-09, not previously
documented): a scoring-summary cell for a player whose display name itself
carries a parenthetical (nickname/maiden name, e.g. "Reagyn Shattock
(Niskakoski)") breaks a *lazy* name-then-assists regex -- the lazy quantifier
stops at the FIRST "(", so the nickname paren gets misread as the assist
list. Fixed here by capturing the name GREEDILY so the trailing group always
resolves to the LAST parenthetical (real assists / "Unassisted"), matching
how the penalty-row team-suffix regex already behaved. The live ticker/
scorebug/activity-banner JS parsers still have the lazy version and should
be patched to match if this is ever revisited.

Also new: the completed box score's own header block carries the game's
real calendar date, time, venue, and a literal "FINAL", "FINAL /OT" or
"FINAL /SO" status string -- no need to cross-reference schedules.cfm (which
only ever shows the current round anyway, useless for historical games).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

_SECTION_RE = re.compile(
    r"^(1ST|2ND|3RD|\dTH|OVERTIME|OT\d*|SHOOTOUT)(\s+PERIOD)?(\s*\d+)?$", re.IGNORECASE
)
_TEAMID_RE = re.compile(r"teamID=(\d+)", re.IGNORECASE)
_TEAM_CELL_RE = re.compile(r"^(.*?)\s+([A-Z]{2,4})$")
# Greedy name capture -- see "New contract" note above.
_GOAL_ROW_RE = re.compile(r"^#?(\d+)\s+(.+)\s*\((.*)\)\s*$")
_PEN_TEAM_RE = re.compile(r"\(([^()]*)\)\s*$")
_PEN_ROW_RE = re.compile(r"^#?(\d+)\s+(.+?)\s*\([^()]*\)\s*$")
_SOG_PARENS_RE = re.compile(r"\(([^)]*)\)")
_MONTHS = {
    m.lower(): i + 1
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
    )
}
_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"FINAL\s*(?:/\s*(OT|SO))?", re.IGNORECASE)


def _fix_span_fusion(html: str) -> str:
    return re.sub(r"</span>", "</span> ", html, flags=re.IGNORECASE)


def _txt(el) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text()).strip()


def _team_id_of(el) -> int | None:
    if el is None:
        return None
    a = el.find("a", href=_TEAMID_RE)
    if not a:
        return None
    m = _TEAMID_RE.search(a.get("href", ""))
    return int(m.group(1)) if m else None


def proper_case(s: str) -> str:
    """Normalise ALL-CAPS or all-lowercase names; leave mixed-case alone."""
    s = s or ""
    letters = re.sub(r"[^a-zA-Z]", "", s)
    if not letters:
        return s
    all_upper = letters == letters.upper() and letters != letters.lower()
    all_lower = letters == letters.lower() and letters != letters.upper()
    if not all_upper and not all_lower:
        return s

    def cap(m: re.Match) -> str:
        return m.group(1) + m.group(2).upper()

    return re.sub(r"(^|[\s\-'.(])([a-z])", cap, s.lower())


def normalize_name(s: str) -> str:
    """Lowercase, alpha-only -- used for name/team matching (mirrors normName/normT)."""
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _norm_period(p: str) -> str:
    p = p.upper()
    if p.startswith("1"):
        return "1"
    if p.startswith("2"):
        return "2"
    if p.startswith("3"):
        return "3"
    if re.search(r"OT|OVER", p):
        return "OT"
    if re.search(r"SO|SHOOT", p):
        return "SO"
    return p


@dataclass
class TeamLine:
    teamID: int | None
    name: str
    code: str
    total: int
    sog_periods: list = field(default_factory=list)
    pp: str = ""
    pim: int = 0


def _parse_team_cell(tr) -> TeamLine:
    cells = [_txt(td) for td in tr.find_all(["td", "th"])]
    m = _TEAM_CELL_RE.match(cells[0])
    name = (m.group(1) if m else cells[0]).strip()
    code = (m.group(2) if m else "").strip()
    total_txt = cells[-1] if cells else "0"
    total = int(total_txt) if total_txt.lstrip("-").isdigit() else 0
    return TeamLine(teamID=_team_id_of(tr), name=name, code=code, total=total)


def parse_header(html: str) -> dict:
    """Pull {date, status_text, final_type, venue} from the box-score header.
    All fields are None/"" if this is a pre-game shell (no FINAL text yet)."""
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text())
    date = None
    dm = _DATE_RE.search(text)
    if dm:
        y, mo, d = int(dm.group(3)), _MONTHS[dm.group(1).lower()], int(dm.group(2))
        date = f"{y:04d}-{mo:02d}-{d:02d}"
    status_text = ""
    final_type = ""
    sm = _STATUS_RE.search(text)
    if sm:
        status_text = sm.group(0).strip()
        final_type = (sm.group(1) or "").upper()
    return {"date": date, "status_text": status_text, "final_type": final_type}


def is_complete(header: dict, goals: list) -> bool:
    """A completed game always has goals (a real final can't be 0-0) AND the
    header's own FINAL status text -- require both, belt-and-suspenders."""
    return bool(header.get("status_text")) and len(goals) > 0


def parse_boxscore(html: str) -> dict:
    html = _fix_span_fusion(html)
    soup = BeautifulSoup(html, "html.parser")

    h5s = soup.find_all("h5")

    def find_h(pattern: str):
        for h in h5s:
            if re.search(pattern, h.get_text(), re.IGNORECASE):
                return h
        return None

    tables = soup.find_all("table")
    score_tbl = tables[0]
    srows = score_tbl.find_all("tr")
    # srows[0] = header row; [1] = away; [2] = home
    away = _parse_team_cell(srows[1])
    home = _parse_team_cell(srows[2])

    # SKATERS rows (per team) -- used to resolve assist jersey numbers and,
    # as a fallback, a scorer/penalized player's team when the trailing-paren
    # team name doesn't cleanly match (shouldn't normally happen).
    skaters: list[tuple[int | None, str]] = []
    for h in h5s:
        if not re.search(r"SKATERS", h.get_text(), re.IGNORECASE):
            continue
        tbl = None
        for sib in h.find_next_siblings():
            if sib.name == "table":
                tbl = sib
                break
            found = sib.find("table") if hasattr(sib, "find") else None
            if found:
                tbl = found
                break
        if tbl is None:
            continue
        for row in tbl.find_all("tr")[1:]:
            tid = _team_id_of(row)
            if tid:
                skaters.append((tid, _txt(row)))

    def team_of_name(who: str) -> int | None:
        for tid, text in skaters:
            if who in text:
                return tid
        return None

    def match_team(team_name: str) -> int | None:
        t = normalize_name(team_name)
        if not t:
            return None
        for cand in (away, home):
            n = normalize_name(cand.name)
            if n and (t == n or t in n or n in t):
                return cand.teamID
        return None

    def section(h5_tag) -> list[dict]:
        items = []
        per = ""
        for el in h5_tag.find_next_siblings():
            t = _txt(el)
            has_table = el.name == "table" or (hasattr(el, "find") and el.find("table"))
            if _SECTION_RE.match(t) and not has_table:
                per = _norm_period(t)
                continue
            tbl = el if el.name == "table" else (el.find("table") if hasattr(el, "find") else None)
            if tbl:
                for r in tbl.find_all("tr"):
                    cells = [_txt(td) for td in r.find_all(["td", "th"])]
                    if cells and cells[0] and not re.search(r"No Penalties|No Scoring", cells[0], re.IGNORECASE):
                        items.append({"per": per, "c": cells})
        return items

    ss_h = find_h(r"SCORING SUMMARY")
    ps_h = find_h(r"PENALTY SUMMARY")

    goals = []
    if ss_h:
        for o in section(ss_h):
            c = o["c"]
            m = _GOAL_ROW_RE.match(c[0])
            if not m:
                # Not a real scoring row -- e.g. a SHOOTOUT attempt list row
                # ("Nerhys Gordon" + a check/cross icon with no jersey#/parens/
                # time). Shootout attempts aren't goals for period/player
                # stat purposes; skip rather than misrecord. See module note.
                continue
            who = proper_case(m.group(2).strip())
            assists_raw = m.group(3).strip()
            assists = (
                []
                if not assists_raw or re.match(r"^unassisted$", assists_raw, re.IGNORECASE)
                else [proper_case(a.strip()) for a in assists_raw.split(",") if a.strip()]
            )
            flag = str(c[1]).strip() if len(c) > 2 else ""
            tid = team_of_name(m.group(2).strip())
            goals.append(
                {
                    "per": o["per"],
                    "t": c[-1] if c else "",
                    "no": int(m.group(1)),
                    "who": who,
                    "assists": assists,
                    "flag": flag,
                    "teamID": tid,
                }
            )

    pens = []
    if ps_h:
        for o in section(ps_h):
            c = o["c"]
            cell = c[0]
            tm = _PEN_TEAM_RE.search(cell)
            # Strip the trailing "(Team)" to inspect the leading player/label
            # text. Two shapes without a "#NN " prefix exist in the wild:
            #   "Team Penalty (Canterbury Inferno) ..."   -> genuine team
            #     penalty, no individual player at all.
            #   "Joel Gerard (SkyCity Stampede) ..."       -> a normal PLAYER
            #     penalty where esportsdesk simply didn't record a jersey
            #     number -- still a player penalty, just no `no`.
            # Distinguish by the literal "Team Penalty" label, not by
            # whether a jersey number happened to be present.
            leading = re.sub(r"\s*\([^()]*\)\s*$", "", cell).strip()
            is_team_pen = bool(re.match(r"^team\s+penalt(y|ies)\b", leading, re.IGNORECASE))
            pm = _PEN_ROW_RE.match(cell)
            if is_team_pen:
                who, no = "", None
            elif pm:
                who, no = proper_case(pm.group(2).strip()), int(pm.group(1))
            else:
                who, no = proper_case(leading), None
            tid = match_team(tm.group(1).strip()) if tm else None
            if tid is None and not is_team_pen:
                tid = team_of_name(who)
            pens.append(
                {
                    "per": o["per"],
                    "t": c[-1] if c else "",
                    "no": no,
                    "who": who,
                    "inf": c[1] if len(c) > 1 else "",
                    "dur": c[2] if len(c) > 2 else "",
                    "teamID": tid,
                    "teamPen": is_team_pen,
                }
            )

    # SOG details table (header text contains "SOG"); cell e.g. "27 (9-8-8-2)"
    d_tbl = None
    for t in tables:
        head_row = t.find("tr")
        if head_row and re.search(r"SOG", _txt(head_row)):
            d_tbl = t
            break
    if d_tbl is not None:
        drows = d_tbl.find_all("tr")

        def sog_row(tr):
            if tr is None:
                return [], "", 0
            cells = [_txt(td) for td in tr.find_all(["td", "th"])]
            pm = _SOG_PARENS_RE.search(cells[1]) if len(cells) > 1 else None
            periods = [int(x.strip() or 0) for x in pm.group(1).split("-")] if pm else []
            pp = cells[2] if len(cells) > 2 else ""
            pim_txt = cells[3] if len(cells) > 3 else "0"
            pim = int(pim_txt) if pim_txt.strip().isdigit() else 0
            return periods, pp, pim

        if len(drows) > 2:
            away.sog_periods, away.pp, away.pim = sog_row(drows[1])
            home.sog_periods, home.pp, home.pim = sog_row(drows[2])

    # GOALIES tables: one per team, heading "<TEAM> GOALIES"
    goalies = []
    for h in h5s:
        if not re.search(r"GOALIES", h.get_text(), re.IGNORECASE):
            continue
        team_label = re.sub(r"GOALIES", " ", h.get_text(), flags=re.IGNORECASE).strip()
        tid = match_team(team_label)
        tbl = None
        for sib in h.find_next_siblings():
            if sib.name == "table":
                tbl = sib
                break
            found = sib.find("table") if hasattr(sib, "find") else None
            if found:
                tbl = found
                break
        if tbl is None:
            continue
        for row in tbl.find_all("tr")[1:]:
            cells = [_txt(td) for td in row.find_all(["td", "th"])]
            if len(cells) < 7:
                continue
            sa_txt, ga_txt, sv_txt, mp_txt = cells[2], cells[3], cells[4], cells[6]
            if not mp_txt or mp_txt == "0:00" or not sa_txt.isdigit():
                continue
            wide = row.find_all("td")[1] if len(row.find_all("td")) > 1 else None
            wide_span = wide.select_one("span.d-none") if wide else None
            raw_name = wide_span.get_text() if wide_span else cells[1]
            name = proper_case(
                re.sub(r"\s+", " ", re.sub(r"\b(ST|OTL|OTW|SOL|SOW|W|L|SO|OT)\b", " ", raw_name)).strip()
            )
            if not name:
                continue
            goalies.append(
                {
                    "teamID": tid,
                    "name": name,
                    "sa": int(sa_txt),
                    "ga": int(ga_txt) if ga_txt.isdigit() else None,
                    "sv": int(sv_txt) if sv_txt.isdigit() else None,
                    "mp": mp_txt,
                }
            )

    header = parse_header(html)

    return {
        "header": header,
        "away": away,
        "home": home,
        "goals": goals,
        "pens": pens,
        "goalies": goalies,
        "complete": is_complete(header, goals),
    }
