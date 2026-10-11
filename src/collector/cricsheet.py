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
                          player of the match for every match)
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
- GOAT rankings          (accolades only: titles, finals lost, Orange /
                          Purple Caps, official player-of-the-match
                          awards -- weights in GOAT_ACCOLADES, never a
                          run count)
- season replay odds     (a clearly-labelled TOY model: P(A beats B) =
                          logistic(2 * NRR gap), 5k replays, fixed seed;
                          it is a probability lesson on the official
                          record, never a prediction product)

The weights live in GOAT_WEIGHTS (production) and GOAT_ACCOLADES
(hardware) below: two published configs, so change them there and the
ladder, the XI/MVP and the GOAT rankings recompute, with tests pinning
the schema.

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

# Published all-time ladder weights -- one config, printed verbatim
# wherever a score is shown (the ladder, the season XI, the MVP card).
GOAT_WEIGHTS = {
    "runs_per_1000": 3.0,     # career runs
    "wickets_per_50": 3.0,    # career wickets
    "player_of_match": 0.5,   # each official PoM award
    "title": 1.0,             # each IPL title won (champion team's XI)
}
# Published GOAT (accolades) weights -- HARDWARE only: what the official
# record says a player won, never how many runs it took. Every weight
# printed verbatim on the rankings tab, same one-config rule as above.
# The official IPL "Most Valuable Player" is a voted prize absent from
# the data, so it can never count (say so, don't invent it).
GOAT_ACCOLADES = {
    "title": 30.0,            # took the field for the champion
    "runner_up": 12.0,        # took the field for the Final loser
    "orange_cap": 15.0,       # topped the season's run aggregate
    "purple_cap": 15.0,       # topped the season's wicket aggregate
    "player_of_match": 2.0,   # each official PoM award
}
# Season MVP/XI impact: the same two scoring rates on ONE season.
# Qualifiers keep a part-timer from topping a tiny sample.
XI_BAT_MIN_INNS = 4
XI_BOWL_MIN_INNS = 4
SIM_SEED = 2026
SIM_RUNS = 5000
SIM_LOGISTIC_K = 2.0         # P(A beats B) = 1 / (1 + e^(-K * NRR gap))


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


def _parse_innings(inn: dict, people: dict) -> dict:
    """One innings -> {team, runs, balls, all_out, bat{}, bowl{}}: totals
    plus per-batter runs/balls/out/boundaries and per-bowler balls,
    charged runs (wides + no-balls are the bowler's, byes/leg-byes are
    not) and credited wickets. Batting/bowling dicts key on the
    registry's stable player id (display-name fallback), so a Cricsheet
    spelling fix can never split a career."""
    bat: dict = {}
    bowl: dict = {}
    runs_total = 0
    legal_balls = 0
    dismissals = 0
    for over in inn.get("overs") or []:
        for dl in over.get("deliveries") or []:
            runs = dl.get("runs") or {}
            total = int(runs.get("total") or 0)
            bat_runs = int(runs.get("batter") or 0)
            runs_total += total
            extra = dl.get("extras") or {}
            legal = "wides" not in extra and "noballs" not in extra
            if legal:
                legal_balls += 1
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
    return {"team": inn.get("team"), "runs": runs_total,
            "balls": legal_balls, "fell": dismissals,
            "all_out": dismissals >= 10, "bat": bat, "bowl": bowl}


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
    (overs in cricket notation), venue and the result sentence."""
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
            "pom": m.get("pom_name"),
        })
    return rows


def _line_accum(agg: dict, player: str, name: str, year: int,
                team: str, bat: dict | None, bowl: dict | None) -> None:
    """Grow the per-(player, season) batting/bowling line dicts shared by
    the caps, the journeys and the careers. `player` is the registry id,
    `name` the display name (last seen wins = most recent spelling)."""
    line = agg.setdefault((player, year), {
        "name": name, "team": team,
        "batting": {"inns": 0, "runs": 0, "balls": 0, "hs": 0,
                    "not_outs": 0, "fours": 0, "sixes": 0, "fifties": 0,
                    "hundreds": 0},
        "bowling": {"inns": 0, "balls": 0, "runs": 0, "wickets": 0,
                    "best": None}})
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
        if (row["best"] is None
                or bowl["wickets"] > row["best"][0]
                or (bowl["wickets"] == row["best"][0]
                    and bowl["runs"] < row["best"][1])):
            row["best"] = [bowl["wickets"], bowl["runs"]]


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


def _career_of(lines: dict, honours: dict, player: str,
               name: str) -> dict:
    """One player's all-time totals + both published scores from his
    season lines: the PRODUCTION ladder (weights in GOAT_WEIGHTS) and
    the accolade GOAT score (hardware only, weights in GOAT_ACCOLADES).
    `honours` maps each accolade kind to {player: count}."""
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
           "best": None}
    for line in seasons.values():
        b, w = line["batting"], line["bowling"]
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
    goat = round(sum(GOAT_ACCOLADES[k] * n for k, n in counts.items()), 1)
    return {"name": name, "seasons": {str(y): s for y, s in
                                     sorted(seasons.items())},
            "career": {**agg, "best": agg["best"] or [0, 0]},
            "pom": counts["player_of_match"],
            "titles": counts["title"],
            "runner_up": counts["runner_up"],
            "orange": counts["orange_cap"],
            "purple": counts["purple_cap"],
            "ladder": ladder, "goat": goat}


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
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"matches": len(matches),
            "seasons": len(seasons_payload),
            "players": len(players_payload)}
    seasons_doc = {"source": SOURCE, "_generated_utc": stamp,
                   "meta": meta, "team_aliases": TEAM_ALIASES,
                   "seasons": seasons_payload,
                   "h2h": head_to_head(matches)}
    players_doc = {"source": SOURCE, "_generated_utc": stamp,
                   "meta": meta, "ladder_weights": GOAT_WEIGHTS,
                   "goat_weights": GOAT_ACCOLADES,
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
