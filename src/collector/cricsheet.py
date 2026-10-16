"""IPL all-history collector on Cricsheet's official ball-by-ball files.

Cricsheet (https://cricsheet.org) publishes one JSON file per IPL match --
every season from 2007/08 (the league's first,59 matches) through the
latest -- under the Open Data Commons Attribution License: free to use
with the source named, which every caption and doc here does ("Data:
Cricsheet"). Each file carries an `info` block (teams, venue, dates,
toss, player of the match, playoff stage, outcome with margin or
super-over winner) plus every delivery of every over. The registry block
maps each player name to a stable id, so a career can never split on a
spelling.

This module downloads the official zip (conditional GET: Cricsheet
publishes Last-Modified, so a re-run only refetches when they republish)
and computes the aggregates the IPL app renders, every one of them a
plain sum over the deliveries -- no ratings, no modelled form:

- season points tables  (win 2, tie/no-result 1 each, loss 0; net run
                          rate from innings totals, a side bowled out
                          credited the FULL quota of overs -- the
                          official IPL method)
- season fixtures        (scores, result sentence, stage, venue and
                          player of the match for every match; venue
                          strings kept as published, merged for
                          all-time views through VENUE_ALIASES)
- season phases          (runs and legal balls per over phase --
                          powerplay 1-6, middle 7-15, death 16-20 --
                          per team, whole season)
- the batting/bowling caps (most runs / most wickets: the Orange and
                          Purple Cap rule; a wicket counts for the
                          bowler unless it was a run out or retirement)
- season XI + season MVP (a formula XI -- top-five batting scores,
                          top-five bowling scores, best remaining
                          all-rounder -- since Cricsheet carries no
                          player roles; weights printed verbatim)
- head-to-head records   (all history; franchise RENAMES merged via
                          TEAM_ALIASES, season tables keep the names
                          each year was played under)
- player careers         (per-season lines and all-time totals plus the
                          published-weights all-time ladder score)
- GOAT rankings          (hardware + production, published as a 0-100
                          index: titles, finals lost, Orange / Purple
                          Caps, official player-of-the-match awards,
                          plus career runs/wickets at GOAT_ACCOLADES'
                          own rates, rescaled so the all-time leader
                          sits at the top of the index, reported as two
                          auditable subtotals per player)
- season replay odds     (a clearly-labelled TOY model: P(A beats B) =
                          logistic(2 * NRR gap), 5k replays, fixed seed;
                          it is a probability lesson on the official
                          record, never a prediction product)
- replay backtest        (same TOY model, honest cutoff: strengths from
                          the PRIOR season's NRR only, predicted top 4
                          vs the real playoff teams, 1k runs/season)

The weights live in GOAT_WEIGHTS (the ladder) and GOAT_ACCOLADES
(the GOAT score's hardware + production blocks) below: two published
configs, so change them there and the ladder, the XI/MVP and the GOAT
rankings recompute, with tests pinning the schema.

Run `python src/collector/cricsheet.py [--zip PATH] [--no-download]` to
(re)build the committed fallbacks data/ipl_seasons.json and
data/ipl_players.json. Kaggle mirrors the same record behind an API key
(see docs/IPL.md); Cricsheet is the primary because it needs no auth,
which keeps CI honest.
"""

import argparse
import json
import math
import os
import random
import urllib.request
import zipfile
from datetime import datetime, timezone

IPL_URL = "https://cricsheet.org/downloads/ipl_json.zip"
SOURCE = "Cricsheet (cricsheet.org), Open Data Commons Attribution License"
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..")
DATA_DIR = os.path.join(REPO_ROOT, "data")
CACHE_DIR = os.path.join(REPO_ROOT, ".cricsheet")

# Deliveries with these wicket kinds do NOT credit the bowler (official
# cricket scoring); everything else -- bowled, caught, lbw, stumped,
# caught and bowled, hit wicket -- does.
BOWLER_NO_CREDIT = frozenset({
    "run out", "retired hurt", "retired out", "obstructing the field",
    "handled the ball", "timed out", "hit the ball twice",
})
# The batter is NOT out (no dismissal, so averages skip him) for these.
BATTER_NOT_OUT = frozenset({"retired hurt"})

# Over phases by 0-based over index: powerplay = overs 1-6, middle =
# 7-15, death = 16-20. Published in docs/IPL.md and printed in the
# app's caption next to every phase number.
PHASE_KEYS = ("powerplay", "middle", "death")


def _phase(over_index: int) -> str:
    if over_index <= 5:
        return "powerplay"
    if over_index <= 14:
        return "middle"
    return "death"


# Franchise RENAMES only (same team, new name): all-time views merge via
# this map so one franchise is one row. Successor franchises that were
# replacements rather than renames (Deccan Chargers -> Sunrisers
# Hyderabad, Gujarat Lions -> Gujarat Titans) stay SEPARATE -- different
# teams wearing the city, not a new paint job.
TEAM_ALIASES = {
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Delhi Daredevils": "Delhi Capitals",
    "Kings XI Punjab": "Punjab Kings",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
}

# Venue RENAMES and label variants of the SAME ground -- Cricsheet
# carries every historical spelling ("Wankhede Stadium" vs "Wankhede
# Stadium, Mumbai", Feroz Shah Kotla vs its rename to Arun Jaitley
# Stadium). Same policy as TEAM_ALIASES: explicit, auditable,
# same-ground merges only; fixtures keep the venue string each match
# was published under, all-time venue views merge through this map.
# Every value here is itself a string Cricsheet uses, and no value is
# ever a key (no merge chains).
VENUE_ALIASES = {
    "Feroz Shah Kotla": "Arun Jaitley Stadium",
    "Arun Jaitley Stadium, Delhi": "Arun Jaitley Stadium",
    "Sardar Patel Stadium, Motera": "Narendra Modi Stadium, Ahmedabad",
    "OUTsurance Oval": "SuperSport Park",
    "Subrata Roy Sahara Stadium": "Maharashtra Cricket Association Stadium",
    "Maharashtra Cricket Association Stadium, Pune":
        "Maharashtra Cricket Association Stadium",
    "M.Chinnaswamy Stadium": "M Chinnaswamy Stadium",
    "M Chinnaswamy Stadium, Bengaluru": "M Chinnaswamy Stadium",
    "Wankhede Stadium, Mumbai": "Wankhede Stadium",
    "Eden Gardens, Kolkata": "Eden Gardens",
    "MA Chidambaram Stadium, Chepauk": "MA Chidambaram Stadium",
    "MA Chidambaram Stadium, Chepauk, Chennai": "MA Chidambaram Stadium",
    "Rajiv Gandhi International Stadium, Uppal":
        "Rajiv Gandhi International Stadium",
    "Rajiv Gandhi International Stadium, Uppal, Hyderabad":
        "Rajiv Gandhi International Stadium",
    "Dr DY Patil Sports Academy, Mumbai": "Dr DY Patil Sports Academy",
    "Sawai Mansingh Stadium, Jaipur": "Sawai Mansingh Stadium",
    "Brabourne Stadium, Mumbai": "Brabourne Stadium",
    "Himachal Pradesh Cricket Association Stadium, Dharamsala":
        "Himachal Pradesh Cricket Association Stadium",
    "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium, Visakhapatnam":
        "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium",
    "Shaheed Veer Narayan Singh International Stadium, Raipur":
        "Shaheed Veer Narayan Singh International Stadium",
    "Maharaja Yadavindra Singh International Cricket Stadium, New Chandigarh":
        "Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur",
    "Punjab Cricket Association IS Bindra Stadium":
        "Punjab Cricket Association Stadium, Mohali",
    "Punjab Cricket Association IS Bindra Stadium, Mohali":
        "Punjab Cricket Association Stadium, Mohali",
    "Punjab Cricket Association IS Bindra Stadium, Mohali, Chandigarh":
        "Punjab Cricket Association Stadium, Mohali",
    "Zayed Cricket Stadium, Abu Dhabi": "Sheikh Zayed Stadium",
}

# Published all-time ladder weights -- one config, printed verbatim
# wherever a score is shown (the ladder, the season XI, the MVP card).
GOAT_WEIGHTS = {
    "runs_per_1000": 3.0,     # career runs
    "wickets_per_50": 3.0,    # career wickets
    "player_of_match": 0.5,   # each official PoM award
    "title": 1.0,             # each IPL title won (champion team's XI)
}
# Published GOAT weights -- TWO auditable components in one config:
# a HARDWARE block (what the official record says a player won) and a
# PRODUCTION block (career output at rates a great IPL career actually
# reaches). Every weight printed verbatim on the rankings tab. The
# official IPL "Most Valuable player" is a voted prize absent from the
# data, so it can never count (say so, don't invent it).
# The rates were fixed against three published all-time lists (ipl.com
# Aug 2026, CricketWinner Jul 2026, SportsboardIndia Feb 2026): those
# rank individual output first and treat team trophies as seasoning,
# so a squad ring can never outrank a decade of runs.
# Production is ROLE-GATED: a player is only judged on the discipline
# he actually practised as a job. A batter's four career wickets are
# not a bowling record (Kohli), a bowler's nightwatchman runs are not
# a batting record (Malinga), and a part-timer's two catches are not
# a batting or bowling record at all. Everyone is judged on fielding,
# because catches, stumpings and run outs are recorded dismissals.
# Calibration check against those three lists (Spearman on the top 40):
# role gating + fielding scores +0.65, up from +0.59 without them.
GOAT_ACCOLADES = {
    "title": 6.0,             # took the field for the champion
    "runner_up": 3.0,         # took the field for the Final loser
    "orange_cap": 6.0,        # topped the season's run aggregate
    "purple_cap": 6.0,        # topped the season's wicket aggregate
    "player_of_match": 2.5,   # each official PoM award (counted once)
    # -- production, batting (batters and all-rounders only) ----------
    "runs_per_1000": 12.0,    # career runs at 1000 apiece
    # -- production, bowling (bowlers and all-rounders only) ----------
    "wickets_per_50": 16.0,   # career wickets at 50 apiece
    "economy_weight": 6.0,    # points per run/under the par economy
    "economy_par": 8.5,       # par IPL economy for the bonus
    "average_weight": 3.0,    # points per run under the par average
    "average_par": 28.0,      # par bowling average for the bonus
    "four_wkts": 2.0,         # each 4-wicket haul in an innings
    "five_wkts": 4.0,         # each 5-wicket haul in an innings
    # -- production, fielding (everyone) -------------------------------
    "catch": 0.15,            # each catch taken
    "stumping": 0.3,          # each stumping (the keeper's dismissal)
    "run_out": 0.3,           # each run out effected
}
# Role gates (published): a career of at least these numbers makes the
# discipline count in the GOAT production block, and sets the role
# label the app prints. Below both gates a player is a "part-timer"
# and is scored on fielding only -- honest for a fringe player whose
# 300 runs and 8 wickets are not a career-level discipline.
GOAT_ROLE = {"bat_runs": 1000, "bowl_wkts": 30}
# Bowling-quality qualifiers: the economy bonus needs 20 overs bowled
# (one bad over can't wreck or save a rate), the average bonus needs
# 50 wickets (an average on 5 wickets is noise).
GOAT_ECON_MIN_BALLS = 120
GOAT_AVG_MIN_WICKETS = 50
# The GOAT rating is a 0-100 INDEX: every score is rescaled so the
# all-time leader sits exactly at the top. Raw points stay published
# in the payload (goat_index.raw), so the rescale stays auditable.
GOAT_INDEX_MAX = 100.0
# Season MVP/XI impact: the same two scoring rates on ONE season.
# Qualifiers keep a part-timer from topping a tiny sample.
XI_BAT_MIN_INNS = 4
XI_BOWL_MIN_INNS = 4
SIM_SEED = 2026
SIM_RUNS = 5000
SIM_LOGISTIC_K = 2.0         # P(A beats B) = 1 / (1 + e^(-K * NRR gap))
SIM_BACKTEST_RUNS = 1000     # per season, replay_backtest (18 seasons)


def season_year(label) -> int:
    """Label fallback ONLY ('2007/08' -> 2008): a season label is
    ambiguous -- '2020/21' is the 2020 season, played Sep-Nov 2020 --
    so the season year comes from the match DATE (every IPL season sits
    in one calendar year). The end-year rule below covers a match with
    no dates at all."""
    text = str(label)
    if "/" in text:
        start, end = text.split("/")
        return int(start) // 100 * 100 + int(end)
    return int(text)


def team_name(team: str) -> str:
    """The rename-merged display name for all-time views (season tables
    keep the name as played -- see TEAM_ALIASES)."""
    return TEAM_ALIASES.get(team, team)


def download(dest: str = CACHE_DIR, url: str = IPL_URL) -> str:
    """The IPL zip at `dest`, reusing yesterday's copy when Cricsheet
    hasn't republished (If-Modified-Since against their Last-Modified;
    the zip changes a handful of times per season, so a daily bot re-run
    costs one 304 most days)."""
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, "ipl_json.zip")
    headers = {"User-Agent": "IPL-Analytics collector (cricsheet.org)"}
    if os.path.exists(path):
        stamp = datetime.fromtimestamp(os.path.getmtime(path),
                                       tz=timezone.utc)
        headers["If-Modified-Since"] = stamp.strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as resp:  # fixed URL
        if getattr(resp, "status", 200) == 304:
            return path
        payload = resp.read()
    with open(path, "wb") as f:
        f.write(payload)
    return path


def load_matches(zip_path: str) -> list:
    """One normalized dict per match file: id, season year, date, stage,
    teams (as played), venue/city, player-of-match id+name, outcome and
    per-innings batting/bowling splits the builders aggregate. A corrupt
    member is skipped, never allowed to kill a refresh."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for name in sorted(n for n in z.namelist()
                           if n.endswith(".json")):
            try:
                doc = json.loads(z.read(name))
            except (json.JSONDecodeError, OSError):
                continue
            info = doc.get("info") or {}
            people = ((info.get("registry") or {}).get("people")) or {}
            pom_name = (info.get("player_of_match") or [None])[0]
            oc = info.get("outcome") or {}
            innings = [_parse_innings(inn, people)
                       for inn in doc.get("innings") or []]
            stem = name.split(".")[0]
            dates = info.get("dates") or []
            # The season year is the year the match was PLAYED in (every
            # IPL season sits inside one calendar year); the label alone
            # is ambiguous -- Cricsheet calls the 2020 season "2020/21".
            played = str(dates[0])[:4] if dates else ""
            year = (int(played) if played.isdigit()
                    else season_year(info.get("season")))
            out.append({
                "id": int(stem) if stem.isdigit() else stem,
                "year": year,
                "date": dates[0] if dates else None,
                "stage": (info.get("event") or {}).get("stage") or "League",
                "teams": list(info.get("teams") or []),
                "venue": info.get("venue"),
                "city": info.get("city"),
                "pom": people.get(pom_name) if pom_name else None,
                "pom_name": pom_name,
                "people": dict(people),
                "winner": oc.get("winner"),
                "result": oc.get("result"),       # "tie"/"no result"/None
                "eliminator": oc.get("eliminator"),
                "margin": oc.get("by") or {},
                "innings": innings,
            })
    return out


def _field_credit(field: dict, player: str, kind: str) -> None:
    """One recorded dismissal for the fielder credited with it."""
    row = field.setdefault(player, {"catches": 0, "stumpings": 0,
                                    "run_outs": 0})
    row[kind] += 1


def _parse_innings(inn: dict, people: dict) -> dict:
    """One innings -> {team, runs, balls, all_out, bat{}, bowl{}, field{},
    phases{}}: totals plus per-batter runs/balls/out/boundaries, per-bowler
    balls, charged runs (wides + no-balls are the bowler's, byes/leg-byes
    are not) and credited wickets, per-fielder catches/stumpings/run outs,
    and run/ball counts per over phase (powerplay/middle/death).
    Batting/bowling/fielding dicts key on the registry's stable player id
    (display-name fallback), so a Cricsheet spelling fix can never split a
    career. Fielding credits the FIRST fielder listed (multi-fielder
    dismissals have no shared-credit rule in the data -- one name, the
    first, is the honest pick); "caught and bowled" has no fielders
    listed, so it is the bowler's own catch. A run out with no fielders
    listed (direct hits: ~150 in the history) credits nobody -- we do
    not guess."""
    bat: dict = {}
    bowl: dict = {}
    field: dict = {}
    runs_total = 0
    legal_balls = 0
    dismissals = 0
    phases = {k: {"runs": 0, "balls": 0} for k in PHASE_KEYS}
    for oi, over in enumerate(inn.get("overs") or []):
        raw = over.get("over")
        n = int(raw) if raw is not None else oi
        phase = _phase(n)
        for dl in over.get("deliveries") or []:
            runs = dl.get("runs") or {}
            total = int(runs.get("total") or 0)
            bat_runs = int(runs.get("batter") or 0)
            runs_total += total
            phases[phase]["runs"] += total
            extra = dl.get("extras") or {}
            legal = "wides" not in extra and "noballs" not in extra
            if legal:
                legal_balls += 1
                phases[phase]["balls"] += 1
            batter = people.get(dl.get("batter"), dl.get("batter"))
            row = bat.setdefault(batter, {"runs": 0, "balls": 0,
                                          "out": False, "fours": 0,
                                          "sixes": 0})
            row["runs"] += bat_runs
            if legal:
                row["balls"] += 1
            row["fours"] += 1 if bat_runs == 4 else 0
            row["sixes"] += 1 if bat_runs == 6 else 0
            bowler = people.get(dl.get("bowler"), dl.get("bowler"))
            charged = (bat_runs + int(extra.get("wides") or 0)
                       + int(extra.get("noballs") or 0))
            brow = bowl.setdefault(bowler, {"balls": 0, "runs": 0,
                                            "wickets": 0})
            if legal:
                brow["balls"] += 1
            brow["runs"] += charged
            for w in dl.get("wickets") or []:
                kind = str(w.get("kind") or "").lower()
                who = people.get(w.get("player_out"), w.get("player_out"))
                if kind not in BATTER_NOT_OUT:
                    dismissals += 1
                    if who in bat:
                        bat[who]["out"] = True
                if kind not in BOWLER_NO_CREDIT and bowler:
                    bowl[bowler]["wickets"] += 1
                listed = [people.get(f.get("name"), f.get("name"))
                          for f in (w.get("fielders") or [])
                          if f.get("name")]
                first = listed[0] if listed else None
                if kind == "caught" and first:
                    _field_credit(field, first, "catches")
                elif kind == "caught and bowled" and bowler:
                    _field_credit(field, bowler, "catches")
                elif kind == "stumped" and first:
                    _field_credit(field, first, "stumpings")
                elif kind == "run out" and first:
                    _field_credit(field, first, "run_outs")
    return {"team": inn.get("team"), "runs": runs_total,
            "balls": legal_balls, "fell": dismissals,
            "all_out": dismissals >= 10, "bat": bat, "bowl": bowl,
            "field": field, "phases": phases}


def _overs(balls: int) -> str:
    """12 balls -> '2.0', 92 balls -> '15.2' (cricket's 15.2 notation)."""
    return f"{balls // 6}.{balls % 6}"


def season_table(matches: list) -> list:
    """Points-table rows for one season's LEAGUE-phase matches (the
    official IPL table never counts Qualifiers/Eliminators/Finals):
    played, won, lost, tied, no-result, points (win 2, tie/no-result 1
    each, loss 0) and net run rate -- (runs for / overs faced) - (runs
    conceded / overs bowled), a side bowled out credited the full quota
    of overs, the official IPL method. Sorted by points, then NRR."""
    stats: dict = {}
    quota = 20.0  # every IPL season is 20 overs a side

    def side(team):
        return stats.setdefault(team, {
            "team": team, "played": 0, "won": 0, "lost": 0, "tied": 0,
            "nr": 0, "points": 0, "runs_for": 0, "overs_for": 0.0,
            "runs_ag": 0, "overs_ag": 0.0})

    for m in matches:
        if m["stage"] != "League":
            continue
        two = m["teams"]
        if len(two) != 2:
            continue
        a, b = side(two[0]), side(two[1])
        a["played"] += 1
        b["played"] += 1
        if m["result"] == "tie":
            a["tied"] += 1
            b["tied"] += 1
            a["points"] += 1
            b["points"] += 1
        elif m["result"] == "no result":
            a["nr"] += 1
            b["nr"] += 1
            a["points"] += 1
            b["points"] += 1
        elif m["winner"] in two:
            win, lose = (a, b) if m["winner"] == two[0] else (b, a)
            win["won"] += 1
            win["points"] += 2
            lose["lost"] += 1
        for inn in m["innings"]:
            mine = side(inn["team"])
            other = b if inn["team"] == two[0] else a
            overs = quota if inn["all_out"] else inn["balls"] / 6.0
            mine["runs_for"] += inn["runs"]
            mine["overs_for"] += overs
            other["runs_ag"] += inn["runs"]
            other["overs_ag"] += overs
    rows = []
    for s in stats.values():
        nrr = ((s["runs_for"] / s["overs_for"]) if s["overs_for"]
               else 0.0) - ((s["runs_ag"] / s["overs_ag"])
                            if s["overs_ag"] else 0.0)
        rows.append({"team": s["team"], "played": s["played"],
                     "won": s["won"], "lost": s["lost"],
                     "tied": s["tied"], "nr": s["nr"],
                     "points": s["points"], "nrr": round(nrr, 3)})
    rows.sort(key=lambda r: (-r["points"], -r["nrr"], r["team"]))
    return rows


def _result_sentence(m: dict) -> str:
    """The fixture's honest result line: margin, super-over winner, or a
    plain no-result -- never inferred beyond what outcome carries."""
    if m["result"] == "no result":
        return "No result"
    if m["result"] == "tie":
        who = m.get("eliminator")
        return (f"Tied, {who} won the Super Over" if who else "Tied")
    if m["winner"]:
        margin = m.get("margin") or {}
        if "wickets" in margin:
            return f"{m['winner']} won by {margin['wickets']} wickets"
        if "runs" in margin:
            return f"{m['winner']} won by {margin['runs']} runs"
        return f"{m['winner']} won"
    return "No result"


def season_fixtures(matches: list) -> list:
    """One row per match: date, stage, both teams with innings totals
    (overs in cricket notation), venue, the result sentence and the
    decisive-winner team (None for ties and no-results -- a Super Over
    names its winner in the result sentence, not here)."""
    rows = []
    for m in sorted(matches, key=lambda x: (x.get("date") or "",
                                            str(x["id"]))):
        scores = []
        for inn in m["innings"]:
            mark = f"{inn['team']} {inn['runs']}/{inn['fell']}"
            if m["result"] != "no result":
                mark += f" ({_overs(inn['balls'])})"
            scores.append(mark)
        rows.append({
            "id": m["id"], "date": m["date"], "stage": m["stage"],
            "teams": list(m["teams"]), "scores": scores,
            "venue": m.get("venue"), "result": _result_sentence(m),
            "winner": m.get("winner"), "pom": m.get("pom_name"),
        })
    return rows


def _line_accum(agg: dict, player: str, name: str, year: int,
                team: str, bat: dict | None, bowl: dict | None,
                field: dict | None = None) -> None:
    """Grow the per-(player, season) batting/bowling/fielding line dicts
    shared by the caps, the journeys and the careers. `player` is the
    registry id, `name` the display name (last seen wins = most recent
    spelling). A haul counts the innings it was taken in (4 wickets =
    a four-for, 5 or more = a five-for, never both)."""
    line = agg.setdefault((player, year), {
        "name": name, "team": team,
        "batting": {"inns": 0, "runs": 0, "balls": 0, "hs": 0,
                    "not_outs": 0, "fours": 0, "sixes": 0, "fifties": 0,
                    "hundreds": 0},
        "bowling": {"inns": 0, "balls": 0, "runs": 0, "wickets": 0,
                    "four_wkts": 0, "five_wkts": 0, "best": None},
        "fielding": {"catches": 0, "stumpings": 0, "run_outs": 0}})
    line["team"] = team  # last team he turned out for that season
    if bat is not None:
        row = line["batting"]
        row["inns"] += 1
        row["runs"] += bat["runs"]
        row["balls"] += bat["balls"]
        row["hs"] = max(row["hs"], bat["runs"])
        row["not_outs"] += 0 if bat["out"] else 1
        row["fours"] += bat["fours"]
        row["sixes"] += bat["sixes"]
        row["fifties"] += 1 if 50 <= bat["runs"] < 100 else 0
        row["hundreds"] += 1 if bat["runs"] >= 100 else 0
    if bowl is not None:
        row = line["bowling"]
        row["inns"] += 1
        row["balls"] += bowl["balls"]
        row["runs"] += bowl["runs"]
        row["wickets"] += bowl["wickets"]
        row["five_wkts"] += 1 if bowl["wickets"] >= 5 else 0
        row["four_wkts"] += 1 if bowl["wickets"] == 4 else 0
        if (row["best"] is None
                or bowl["wickets"] > row["best"][0]
                or (bowl["wickets"] == row["best"][0]
                    and bowl["runs"] < row["best"][1])):
            row["best"] = [bowl["wickets"], bowl["runs"]]
    if field is not None:
        row = line["fielding"]
        row["catches"] += field["catches"]
        row["stumpings"] += field["stumpings"]
        row["run_outs"] += field["run_outs"]


def season_caps(season_matches: list, lines: dict) -> dict:
    """{"batting": [...], "bowling": [...]} -- most runs and most
    wickets for the season (the Orange/Purple Cap rule): sorted by the
    cap metric, then strike rate / fewer runs conceded."""
    bat_rows, bowl_rows = [], []
    for (player, year), line in lines.items():
        b = line["batting"]
        if b["inns"]:
            bat_rows.append({
                "player": player, "name": line["name"],
                "team": line["team"], "inns": b["inns"],
                "runs": b["runs"], "hs": b["hs"],
                "not_outs": b["not_outs"],
                "sr": round(100.0 * b["runs"] / b["balls"], 1)
                      if b["balls"] else 0.0,
                "fifties": b["fifties"], "hundreds": b["hundreds"],
                "fours": b["fours"], "sixes": b["sixes"]})
        w = line["bowling"]
        if w["balls"]:
            best = w["best"] or [0, 0]
            bowl_rows.append({
                "player": player, "name": line["name"],
                "team": line["team"], "inns": w["inns"],
                "wickets": w["wickets"],
                "balls": w["balls"], "runs": w["runs"],
                "econ": round(6.0 * w["runs"] / w["balls"], 2)
                        if w["balls"] else 0.0,
                "best": f"{best[0]}/{best[1]}"})
    bat_rows.sort(key=lambda r: (-r["runs"], -r["sr"], r["name"]))
    bowl_rows.sort(key=lambda r: (-r["wickets"], r["runs"], r["name"]))
    return {"batting": bat_rows, "bowling": bowl_rows}


def season_xi(caps: dict) -> dict:
    """The season's formula XI -- Cricsheet carries no player roles, so
    the honest pick is published and blunt: the five top RUN-scorers
    (min innings), the five top WICKET-takers likewise, the best
    remaining all-rounder (batted AND bowled, most combined scaled
    impact), and the season MVP by that same impact. Weights and
    qualifiers are printed verbatim in the app."""
    bat_rows = [r for r in caps["batting"]
                if r["inns"] >= XI_BAT_MIN_INNS]
    bowl_rows = [r for r in caps["bowling"]
                 if r["inns"] >= XI_BOWL_MIN_INNS]
    batting = bat_rows[:5]
    picked = {b["player"] for b in batting}
    bowling = [r for r in bowl_rows if r["player"] not in picked][:5]
    picked |= {b["player"] for b in bowling}
    bat_by = {r["player"]: r for r in bat_rows}
    bowl_by = {r["player"]: r for r in bowl_rows}

    def impact(pid):
        bat = (GOAT_WEIGHTS["runs_per_1000"]
               * bat_by[pid]["runs"] / 1000) if pid in bat_by else 0.0
        bowl = (GOAT_WEIGHTS["wickets_per_50"]
                * bowl_by[pid]["wickets"] / 50) if pid in bowl_by else 0.0
        return bat + bowl

    both = [p for p in bat_by if p in bowl_by and p not in picked]
    allrounder = max(both, key=impact) if both else None
    mvp_pool = [p for p in set(bat_by) | set(bowl_by)]
    mvp = max(mvp_pool, key=impact) if mvp_pool else None
    return {"batting": [b["player"] for b in batting],
            "bowling": [b["player"] for b in bowling],
            "allrounder": allrounder,
            "mvp": mvp,
            "mvp_impact": round(impact(mvp), 2) if mvp else None}


def head_to_head(matches: list) -> dict:
    """All-history pair records under the rename-merged names:
    {"A|B" (alphabetical): {"a", "b", "played", "a_wins", "b_wins",
    "tied", "nr"}} -- the rivalry card and most-played table's feed."""
    out: dict = {}
    for m in matches:
        if len(m["teams"]) != 2:
            continue
        a, b = sorted(team_name(t) for t in m["teams"])
        row = out.setdefault(f"{a}|{b}", {
            "a": a, "b": b, "played": 0, "a_wins": 0, "b_wins": 0,
            "tied": 0, "nr": 0})
        row["played"] += 1
        if m["result"] == "tie":
            row["tied"] += 1
        elif m["result"] == "no result":
            row["nr"] += 1
        elif m["winner"]:
            w = team_name(m["winner"])
            row["a_wins" if w == a else "b_wins"] += 1
    return out


def replay_odds(season_matches: list, seed: int = SIM_SEED,
                runs: int = SIM_RUNS) -> dict:
    """TOY season replay: P(A beats B) = 1 / (1 + e^(-K * NRR gap)) off
    the actual points table, every match replayed `runs` times from a
    fixed seed (reproducible), top four by simulated points (actual NRR
    as tiebreak) then 1v4/2v3 knockouts. It is a transparent probability
    lesson on the official record, NOT a prediction product -- no form,
    injuries or home advantage enter."""
    table = season_table(season_matches)
    if len(table) < 4:
        return {}
    nrr = {r["team"]: r["nrr"] for r in table}
    # League-phase fixtures only: the actual playoffs are replaced by the
    # simulated knockout below, so replaying them too would double-count.
    schedule = [(m["teams"][0], m["teams"][1]) for m in season_matches
                if len(m["teams"]) == 2 and m["stage"] == "League"]
    if not schedule:
        return {}
    rng = random.Random(seed)
    playoff: dict = {r["team"]: 0 for r in table}
    title: dict = {r["team"]: 0 for r in table}

    def p_win(a, b):
        return 1.0 / (1.0 + math.exp(-SIM_LOGISTIC_K * (nrr[a] - nrr[b])))

    for _ in range(runs):
        points: dict = {r["team"]: 0 for r in table}
        for a, b in schedule:
            points[a if rng.random() < p_win(a, b) else b] += 2
        order = sorted(points, key=lambda t: (-points[t], -nrr[t]))
        first, second, third, fourth = order[:4]
        for t in order[:4]:
            playoff[t] += 1
        # The modern IPL knockout, faithfully: Qualifier 1 (1v2, winner
        # straight to the final), Eliminator (3v4), Qualifier 2 (Q1
        # loser v Eliminator winner), Final.
        q1_loser = (second if rng.random() < p_win(first, second)
                    else first)
        elim = (fourth if rng.random() < p_win(third, fourth)
                else third)
        q2 = (q1_loser if rng.random() < p_win(q1_loser, elim)
              else elim)
        champ = (first if rng.random() < p_win(first, q2)
                 else q2)
        title[champ] += 1
    return {
        "method": (f"TOY model: P(A beats B) = 1/(1+e^(-{SIM_LOGISTIC_K} "
                   f"x NRR gap)) off the actual points table; every "
                   f"LEAGUE match replayed, top 4 by points (NRR "
                   f"tiebreak), IPL playoffs (Q1 1v2, Elim 3v4, Q2, "
                   f"Final)"),
        "runs": runs, "seed": seed,
        "odds": {t: {"playoff": round(100.0 * playoff[t] / runs, 1),
                     "title": round(100.0 * title[t] / runs, 1)}
                 for t in playoff}}


def replay_backtest(by_year: dict, seed: int = SIM_SEED,
                    runs: int = SIM_BACKTEST_RUNS) -> dict:
    """TOY backtest with a legitimate information cutoff: every season
    (first excepted) is replayed with strengths taken from the PRIOR
    season's final NRR -- a franchise with no prior season starts at
    0.0, league average by construction -- then the predicted top four
    (by simulated qualification rate) is compared against the four
    teams that actually made the playoffs. Unlike the single-season
    replay (a probability lesson on a completed table), nothing from
    the season being replayed enters its strengths: this measures
    genuine prior-season predictive power. Reproducible from a fixed
    seed; no form, injuries or home advantage, same TOY label."""
    out: dict = {}
    years = sorted(by_year, key=int)
    for i, year in enumerate(years):
        if i == 0:
            continue                     # no prior season to seed from
        prior = {team_name(r["team"]): r["nrr"]
                 for r in season_table(by_year[years[i - 1]])}
        table = season_table(by_year[year])
        if not prior or len(table) < 4:
            continue
        schedule = [(team_name(m["teams"][0]), team_name(m["teams"][1]))
                    for m in by_year[year]
                    if len(m["teams"]) == 2 and m["stage"] == "League"]
        if not schedule:
            continue
        strengths = {team_name(r["team"]): prior.get(team_name(r["team"]),
                                                     0.0)
                     for r in table}
        rng = random.Random(seed)
        qualify: dict = {team_name(r["team"]): 0 for r in table}

        def p_win(a, b):
            return 1.0 / (1.0 + math.exp(
                -SIM_LOGISTIC_K * (strengths[a] - strengths[b])))

        for _ in range(runs):
            points: dict = {team_name(r["team"]): 0 for r in table}
            for a, b in schedule:
                points[a if rng.random() < p_win(a, b) else b] += 2
            order = sorted(points,
                           key=lambda t: (-points[t], -strengths[t], t))
            for t in order[:4]:
                qualify[t] += 1
        predicted = [t for t, _ in sorted(qualify.items(),
                                          key=lambda kv: (-kv[1],
                                                          kv[0]))][:4]
        actual = sorted({team_name(t) for m in by_year[year]
                         if m["stage"] != "League"
                         for t in m["teams"]})
        if not actual:
            continue
        overlap = len(set(predicted) & set(actual))
        out[str(year)] = {"predicted": predicted, "actual": actual,
                          "overlap": overlap}
    overlaps = [r["overlap"] for r in out.values()]
    exact = sum(1 for r in out.values()
                if set(r["predicted"]) == set(r["actual"]))
    return {
        "method": (f"TOY backtest: strengths = PRIOR season's final NRR "
                   f"(no prior season -> 0.0, league average by "
                   f"construction); each LEAGUE match of the season "
                   f"simulated {runs} times from seed {seed}, predicted "
                   f"top 4 by qualification rate, compared with the "
                   f"teams that actually reached the playoffs. No form, "
                   f"injuries or home advantage; no information from "
                   f"the season being replayed enters its strengths."),
        "runs": runs, "seed": seed, "seasons": out,
        "summary": {"seasons": len(out),
                    "avg_overlap": (round(sum(overlaps) / len(overlaps),
                                           2) if overlaps else 0.0),
                    "exact": exact}}


def _role_of(agg: dict) -> str:
    """The discipline a career was actually built on, from the
    published gates (GOAT_ROLE): "batter", "bowler", "all-rounder"
    (both gates passed) or "part-timer" (neither -- scored on fielding
    only). Cricsheet carries no role column, so the gates ARE the
    honest role: 1000 runs is a batting career, 30 wickets is a
    bowling career."""
    bat = agg["runs"] >= GOAT_ROLE["bat_runs"]
    bowl = agg["wickets"] >= GOAT_ROLE["bowl_wkts"]
    return ("all-rounder" if bat and bowl else "batter" if bat
            else "bowler" if bowl else "part-timer")


def _career_of(lines: dict, honours: dict, player: str,
               name: str) -> dict:
    """One player's all-time totals + both published scores from his
    season lines: the PRODUCTION ladder (weights in GOAT_WEIGHTS) and
    the GOAT score (weights in GOAT_ACCOLADES, split into a hardware
    subtotal and a production subtotal that sum to the total, so the
    blend stays auditable). `honours` maps each accolade kind to
    {player: count}. Production is ROLE-GATED: batting counts only
    past the runs gate, bowling only past the wicket gate (economy,
    average and haul bonuses live inside that gate), fielding always
    -- nobody is judged on a discipline he never practised."""
    titles = honours["titles"]
    runner_up = honours["runner_up"]
    oranges = honours["orange"]
    purples = honours["purple"]
    poms = honours["pom"]
    seasons = {year: line for (pid, year), line in lines.items()
               if pid == player}
    agg = {"inns": 0, "runs": 0, "hs": 0, "not_outs": 0, "fours": 0,
           "sixes": 0, "fifties": 0, "hundreds": 0, "balls": 0,
           "balls_bowled": 0, "runs_charged": 0, "wickets": 0,
           "four_wkts": 0, "five_wkts": 0, "catches": 0, "stumpings": 0,
           "run_outs": 0, "best": None}
    for line in seasons.values():
        b, w = line["batting"], line["bowling"]
        f = line["fielding"]
        agg["inns"] += b["inns"]
        agg["runs"] += b["runs"]
        agg["hs"] = max(agg["hs"], b["hs"])
        agg["not_outs"] += b["not_outs"]
        agg["fours"] += b["fours"]
        agg["sixes"] += b["sixes"]
        agg["fifties"] += b["fifties"]
        agg["hundreds"] += b["hundreds"]
        agg["balls"] += b["balls"]
        agg["balls_bowled"] += w["balls"]
        agg["runs_charged"] += w["runs"]
        agg["wickets"] += w["wickets"]
        agg["four_wkts"] += w["four_wkts"]
        agg["five_wkts"] += w["five_wkts"]
        agg["catches"] += f["catches"]
        agg["stumpings"] += f["stumpings"]
        agg["run_outs"] += f["run_outs"]
        if w["best"] and (agg["best"] is None
                          or w["best"][0] > agg["best"][0]
                          or (w["best"][0] == agg["best"][0]
                              and w["best"][1] < agg["best"][1])):
            agg["best"] = list(w["best"])
    ladder = round(
        GOAT_WEIGHTS["runs_per_1000"] * agg["runs"] / 1000
        + GOAT_WEIGHTS["wickets_per_50"] * agg["wickets"] / 50
        + GOAT_WEIGHTS["player_of_match"] * poms.get(player, 0)
        + GOAT_WEIGHTS["title"] * titles.get(player, 0), 2)
    counts = {"title": titles.get(player, 0),
              "runner_up": runner_up.get(player, 0),
              "orange_cap": oranges.get(player, 0),
              "purple_cap": purples.get(player, 0),
              "player_of_match": poms.get(player, 0)}
    role = _role_of(agg)
    # Hardware block (PoM counted ONCE, here; role-neutral -- a title
    # is a title whatever you did in the XI) + ROLE-GATED production.
    # Both subtotals round to 1dp and the total is their sum, so the
    # columns always add up on screen. They are RAW points here;
    # build() rescales them onto the 0-100 index once every player's
    # raw score is known.
    w = GOAT_ACCOLADES
    hardware = round(sum(w[k] * n for k, n in counts.items()), 1)
    econ = (round(6.0 * agg["runs_charged"] / agg["balls_bowled"], 2)
            if agg["balls_bowled"] else None)
    bowl_avg = (round(agg["runs_charged"] / agg["wickets"], 2)
                if agg["wickets"] else None)
    prod = 0.0
    if role in ("batter", "all-rounder"):
        prod += w["runs_per_1000"] * agg["runs"] / 1000
    if role in ("bowler", "all-rounder"):
        prod += w["wickets_per_50"] * agg["wickets"] / 50
        if (econ is not None
                and agg["balls_bowled"] >= GOAT_ECON_MIN_BALLS):
            prod += w["economy_weight"] * max(0.0, w["economy_par"] - econ)
        if (bowl_avg is not None
                and agg["wickets"] >= GOAT_AVG_MIN_WICKETS):
            prod += w["average_weight"] * max(
                0.0, w["average_par"] - bowl_avg)
        prod += (w["four_wkts"] * agg["four_wkts"]
                 + w["five_wkts"] * agg["five_wkts"])
    prod += (w["catch"] * agg["catches"] + w["stumping"] * agg["stumpings"]
             + w["run_out"] * agg["run_outs"])
    production = round(prod, 1)
    goat = round(hardware + production, 1)
    return {"name": name, "seasons": {str(y): s for y, s in
                                     sorted(seasons.items())},
            "role": role,
            "career": {**agg, "econ": econ, "bowl_avg": bowl_avg,
                       "best": agg["best"] or [0, 0]},
            "pom": counts["player_of_match"],
            "titles": counts["title"],
            "runner_up": counts["runner_up"],
            "orange": counts["orange_cap"],
            "purple": counts["purple_cap"],
            "ladder": ladder, "goat": goat,
            "goat_hardware": hardware, "goat_production": production}


def _goat_index(players: dict) -> float:
    """Rescale every GOAT subtotal onto the published 0-100 index:
    one factor = GOAT_INDEX_MAX / the raw leader's score, applied to
    BOTH subtotals (then rounded to 1dp) so Hardware + Production
    still equals GOAT on screen. Returns the raw leader score, so the
    payload can state where the index came from."""
    raw_leader = max((p["goat"] for p in players.values()), default=0.0)
    factor = GOAT_INDEX_MAX / raw_leader if raw_leader else 1.0
    for p in players.values():
        hardware = round(p["goat_hardware"] * factor, 1)
        production = round(p["goat_production"] * factor, 1)
        p["goat_hardware"], p["goat_production"] = hardware, production
        p["goat"] = round(hardware + production, 1)
    return raw_leader


def build(zip_path: str = None, out_dir: str = DATA_DIR,
          seed: int = SIM_SEED, runs: int = SIM_RUNS) -> dict:
    """(Re)build the committed fallbacks from the zip; returns both
    payloads. `zip_path=None` downloads (unless the cache is fresh)."""
    zip_path = zip_path or download()
    matches = load_matches(zip_path)
    if not matches:
        raise RuntimeError("no IPL match files in the zip")

    by_year: dict = {}
    lines: dict = {}          # (player id, year) -> line
    poms: dict = {}
    titles: dict = {}
    runner_up: dict = {}      # took the field for the Final loser
    oranges: dict = {}        # topped a season's run aggregate
    purples: dict = {}        # topped a season's wicket aggregate
    id_names: dict = {}       # registry id -> latest display name
    phase_totals: dict = {}   # year -> team (as played) -> phase -> agg
    for m in matches:
        by_year.setdefault(m["year"], []).append(m)
        if m.get("pom"):
            poms[m["pom"]] = poms.get(m["pom"], 0) + 1
        for who, key in (m.get("people") or {}).items():
            id_names[key] = who
        for inn in m["innings"]:
            bat_team = inn["team"]
            # A bowler belongs to the FIELDING side -- the innings' team
            # is the one batting, so crediting him with it would file
            # every bowler under the opposition (and wreck title
            # counting for bowlers).
            bowl_team = next((t for t in m["teams"] if t != bat_team),
                             bat_team)
            for player, bat in (inn["bat"] or {}).items():
                _line_accum(lines, player, id_names.get(player, player),
                            m["year"], bat_team, bat, None)
            for player, bowl in (inn["bowl"] or {}).items():
                _line_accum(lines, player, id_names.get(player, player),
                            m["year"], bowl_team, None, bowl)
            # Fielding credit belongs to the FIELDING side, exactly
            # like bowling -- the innings' team is the one batting.
            for player, fld in (inn.get("field") or {}).items():
                _line_accum(lines, player, id_names.get(player, player),
                            m["year"], bowl_team, None, None, fld)
            bucket = phase_totals.setdefault(m["year"], {}).setdefault(
                bat_team, {k: {"runs": 0, "balls": 0} for k in PHASE_KEYS})
            for pname, agg in (inn.get("phases") or {}).items():
                bucket[pname]["runs"] += agg["runs"]
                bucket[pname]["balls"] += agg["balls"]
    champions = {y: next((m["winner"] for m in ms
                          if m["stage"] == "Final" and m["winner"]),
                         None)
                 for y, ms in by_year.items()}
    runner_ups_by_year = {
        y: next((t for t in next(
            (m["teams"] for m in ms if m["stage"] == "Final"), [])
            if champions.get(y) and t != champions.get(y)), None)
        for y, ms in by_year.items()}
    for (player, year), line in lines.items():
        team = team_name(line["team"])
        if champions.get(year) and team == team_name(champions[year]):
            titles[player] = titles.get(player, 0) + 1
        if runner_ups_by_year.get(year) \
                and team == team_name(runner_ups_by_year[year]):
            runner_up[player] = runner_up.get(player, 0) + 1

    seasons_payload: dict = {}
    for year in sorted(by_year):
        ms = by_year[year]
        caps = season_caps(ms, {(p, y): ln for (p, y), ln in lines.items()
                                if y == year})
        # The caps ARE the official Orange/Purple Cap: whoever tops the
        # season's run / wicket aggregate wears it.
        if caps["batting"]:
            top = caps["batting"][0]["player"]
            oranges[top] = oranges.get(top, 0) + 1
        if caps["bowling"]:
            top = caps["bowling"][0]["player"]
            purples[top] = purples.get(top, 0) + 1
        seasons_payload[str(year)] = {
            "champion": champions.get(year),
            "points": season_table(ms),
            "fixtures": season_fixtures(ms),
            "caps": caps,
            "xi": season_xi(caps),
            "phases": phase_totals.get(year, {}),
            "sim": replay_odds(ms, seed, runs),
        }
    players_payload = {}
    names = {}
    for (player, _year), line in lines.items():
        names[player] = line["name"]
    honours = {"titles": titles, "runner_up": runner_up,
               "orange": oranges, "purple": purples, "pom": poms}
    for player, name in names.items():
        players_payload[player] = _career_of(lines, honours,
                                             player, name)
    # Raw points -> published 0-100 index (the leader sits at the top);
    # the raw leader score travels in the payload so the rescale is
    # auditable on the rankings tab.
    raw_leader = _goat_index(players_payload)
    index_leader = max(players_payload.values(), key=lambda p: p["goat"])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"matches": len(matches),
            "seasons": len(seasons_payload),
            "players": len(players_payload)}
    seasons_doc = {"source": SOURCE, "_generated_utc": stamp,
                   "meta": meta, "team_aliases": TEAM_ALIASES,
                   "venue_aliases": VENUE_ALIASES,
                   "seasons": seasons_payload,
                   "backtest": replay_backtest(by_year, seed),
                   "h2h": head_to_head(matches)}
    players_doc = {"source": SOURCE, "_generated_utc": stamp,
                   "meta": meta, "ladder_weights": GOAT_WEIGHTS,
                   "goat_weights": GOAT_ACCOLADES,
                   "goat_index": {"max": GOAT_INDEX_MAX,
                                  "leader": index_leader["name"],
                                  "raw": raw_leader},
                   "players": players_payload}
    os.makedirs(out_dir, exist_ok=True)
    for name, doc in (("ipl_seasons.json", seasons_doc),
                      ("ipl_players.json", players_doc)):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        print(f"  wrote {path}")
    return {"seasons": seasons_doc, "players": players_doc}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", dest="zip_path", default=None,
                    help="use a downloaded zip instead of fetching")
    ap.add_argument("--out", dest="out_dir", default=DATA_DIR)
    ap.add_argument("--runs", dest="runs", type=int, default=SIM_RUNS)
    args = ap.parse_args()
    built = build(args.zip_path, args.out_dir, runs=args.runs)
    m = built["seasons"]["meta"]
    print(f"IPL: {m['matches']} matches, {m['seasons']} seasons, "
          f"{m['players']} players (Data: Cricsheet)")
