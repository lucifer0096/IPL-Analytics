"""Cricsheet collector tests on synthetic v1.3-shaped match files.

The fixtures below mirror the real zip's structure exactly (info block,
registry ids, overs/deliveries with extras and wicket kinds) at a tiny
scale, so every rule the IPL app renders is pinned without network or a
5 MB download: points + NRR (all-out quota, leg-byes excluded from
bowler charges, wides included), result sentences (margin, super over,
no result), the run-out/retired-hurt no-credit rule, franchise RENAME
merging (successors stay separate), the formula XI qualifiers, the
published ladder weights and the toy replay's reproducibility.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "collector"))

import cricsheet  # noqa: E402

PEOPLE = {"A1": "aaa1", "A2": "aaa2", "A3": "aaa3", "B1": "bbb1",
          "B2": "bbb2", "bA2": "xxx2", "bA3": "xxx3", "bB1": "yyy1",
          "bB2": "yyy2", "G1": "ggg1", "DD1": "ddd1"}


def _d(batter, bowler, total, bat_runs=None, extras=None, wickets=None):
    bat = total if bat_runs is None else bat_runs
    return {"batter": batter, "bowler": bowler, "non_striker": "NS",
            "runs": {"batter": bat, "extras": total - bat,
                     "total": total},
            **({"extras": extras} if extras else {}),
            **({"wickets": wickets} if wickets else {})}


def _inn(team, overs):
    return {"team": team, "overs": [{"over": i, "deliveries": d}
                                    for i, d in enumerate(overs)]}


def _match(teams, season, stage, date, innings, outcome, pom=None):
    return {"info": {
        "teams": teams, "season": season, "dates": [date],
        "event": {"stage": stage} if stage else {},
        "venue": "Test Oval", "city": "Testville",
        "outcome": outcome,
        "player_of_match": [pom] if pom else [],
        "registry": {"people": dict(PEOPLE)},
        "gender": "male", "match_type": "T20", "overs": 20,
        "toss": {"winner": teams[0], "decision": "bat"}},
        "innings": innings}


def _fixtures() -> dict:
    """m1/m2 -> 2024 (labelled '2023/24'); m3-m5 -> 2023. Every expected
    number in the tests derives from these deliveries by hand."""
    m1 = _match(
        ["Alpha", "Beta"], "2023/24", None, "2024-04-01",
        [_inn("Alpha", [
            # 7 off the bat + 1 leg-bye = 8 (leg-byes are NOT the
            # bowler's charge but DO count for the team total)
            [_d("A1", "bB1", 4), _d("A1", "bB1", 0), _d("A1", "bB1", 1),
             _d("A1", "bB1", 0), _d("A1", "bB1", 2),
             _d("A1", "bB1", 1, bat_runs=0, extras={"legbyes": 1})],
            # a wide (1) then 8 off the bat = 9 (wides ARE charged)
            [_d("A1", "bB1", 1, bat_runs=0, extras={"wides": 1}),
             _d("A1", "bB1", 0), _d("A1", "bB1", 6),
             _d("A1", "bB1", 0), _d("A1", "bB1", 1),
             _d("A1", "bB1", 0), _d("A1", "bB1", 1)]],
         ), _inn("Beta", [
            # B1 caught off bA2 (bowler credited), 5 off the over
            [_d("B1", "bA2", 1,
                wickets=[{"kind": "caught", "player_out": "B1"}]),
             _d("B1", "bA2", 0), _d("B1", "bA2", 2),
             _d("B1", "bA2", 1), _d("B1", "bA2", 0),
             _d("B1", "bA2", 1)],
            [_d("B1", "bA2", 4), _d("B1", "bA2", 0),
             _d("B1", "bA2", 0), _d("B1", "bA2", 1),
             _d("B1", "bA2", 0), _d("B1", "bA2", 0)]],
         )],
        {"winner": "Alpha", "by": {"runs": 7}}, pom="A1")

    m2 = _match(
        ["Alpha", "Beta"], "2023/24", "Final", "2024-05-26",
        [_inn("Alpha", [
            [_d("A1", "bB2", 2), _d("A1", "bB2", 4),
             _d("A1", "bB2", 1), _d("A1", "bB2", 0),
             _d("A1", "bB2", 2), _d("A1", "bB2", 1)],
            [_d("A1", "bB2", 1,
                wickets=[{"kind": "caught", "player_out": "A1"}]),
             _d("A2", "bB2", 0), _d("A2", "bB2", 0),
             _d("A2", "bB2", 0), _d("A2", "bB2", 1),
             _d("A2", "bB2", 0)]],
         ), _inn("Beta", [
            [_d("B1", "bA3", 1), _d("B1", "bA3", 2),
             _d("B1", "bA3", 0), _d("B1", "bA3", 4),
             _d("B1", "bA3", 0), _d("B1", "bA3", 1)],
            # a run out: NO bowler credit (dismissal still counted)
            [_d("B1", "bA3", 0,
                wickets=[{"kind": "run out", "player_out": "B2"}]),
             _d("B1", "bA3", 1), _d("B1", "bA3", 0),
             _d("B1", "bA3", 0), _d("B1", "bA3", 2),
             _d("B1", "bA3", 0)],
            # retired hurt: NOT out, NO bowler credit
            [_d("B1", "bA3", 2,
                wickets=[{"kind": "retired hurt",
                          "player_out": "B1"}])],
         ]),],
        {"winner": "Beta", "by": {"wickets": 7}}, pom="B1")

    m3 = _match(
        ["Alpha", "Gamma"], "2023", None, "2023-04-10",
        [_inn("Alpha", [[_d("A1", "G1", 4), _d("A1", "G1", 0),
                         _d("A1", "G1", 0), _d("A1", "G1", 0),
                         _d("A1", "G1", 0), _d("A1", "G1", 0)]]),
         _inn("Gamma", [[_d("G1", "A2", 4), _d("G1", "A2", 0),
                         _d("G1", "A2", 0), _d("G1", "A2", 0),
                         _d("G1", "A2", 0), _d("G1", "A2", 0)]])],
        {"result": "tie", "eliminator": "Alpha"})

    m4 = _match(["Beta", "Gamma"], "2023", None, "2023-04-12", [],
                {"result": "no result"})

    m5 = _match(
        ["Delhi Daredevils", "Alpha"], "2023", None, "2023-04-15",
        [_inn("Delhi Daredevils",
              [[_d("DD1", "A3", 4), _d("DD1", "A3", 2),
                _d("DD1", "A3", 0), _d("DD1", "A3", 0),
                _d("DD1", "A3", 0), _d("DD1", "A3", 0)]]),
         _inn("Alpha", [[_d("A2", "DD1", 4), _d("A2", "DD1", 0),
                         _d("A2", "DD1", 0), _d("A2", "DD1", 0),
                         _d("A2", "DD1", 0), _d("A2", "DD1", 0)]])],
        {"winner": "Delhi Daredevils", "by": {"runs": 2}})

    return {"1001.json": m1, "1002.json": m2, "1003.json": m3,
            "1004.json": m4, "1005.json": m5}


@pytest.fixture()
def zip_path(tmp_path) -> str:
    path = tmp_path / "ipl_json.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("README.txt", "synthetic fixture")
        for name, doc in _fixtures().items():
            z.writestr(name, json.dumps(doc))
    return str(path)


def test_season_year_normalizes():
    assert cricsheet.season_year("2007/08") == 2008
    assert cricsheet.season_year("2009") == 2009
    assert cricsheet.season_year("2009/10") == 2010


def test_season_year_prefers_the_date_the_match_was_played(tmp_path):
    """Cricsheet labels the 2020 season '2020/21' (played Sep-Nov
    2020), so the label's end year would file it under 2021 and merge
    it into the wrong season -- the match DATE must win."""
    doc = _match(["Alpha", "Beta"], "2020/21", None, "2020-09-20", [],
                 {"result": "no result"})
    path = tmp_path / "one.json.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.json", json.dumps(doc))
    assert cricsheet.load_matches(str(path))[0]["year"] == 2020


def test_load_matches_parses_ids_and_survives_corrupt(tmp_path):
    path = tmp_path / "bad.zip"
    docs = _fixtures()
    docs["9999.json"] = "{not json"
    with zipfile.ZipFile(path, "w") as z:
        for name, doc in docs.items():
            z.writestr(name, doc if isinstance(doc, str)
                       else json.dumps(doc))
    matches = cricsheet.load_matches(str(path))
    assert len(matches) == 5           # the corrupt member is skipped
    m1 = next(m for m in matches if m["id"] == 1001)
    assert m1["year"] == 2024          # '2023/24' -> the END year
    assert m1["teams"] == ["Alpha", "Beta"]
    assert m1["pom"] == "aaa1"         # registry id, not the name


def _season(matches, year):
    return [m for m in matches if m["year"] == year]


def test_points_table_and_nrr(zip_path):
    matches = cricsheet.load_matches(zip_path)
    table = cricsheet.season_table(_season(matches, 2024))
    alpha, beta = table
    # Only m1 counts: it is the LEAGUE game (m2 is the Final, and the
    # official table never counts knockouts). 17-10 in two overs a side.
    assert (alpha["team"], alpha["points"]) == ("Alpha", 2)
    assert (beta["team"], beta["points"]) == ("Beta", 0)
    assert alpha["nrr"] == 3.5          # (17/2) - (10/2)
    assert beta["nrr"] == -3.5
    assert alpha["played"] == 1 and beta["played"] == 1
    # 2023: a tie (1 each), a no-result (1 each) and Delhi's win.
    table = cricsheet.season_table(_season(matches, 2023))
    by_team = {r["team"]: r for r in table}
    assert by_team["Delhi Daredevils"]["points"] == 2   # as played
    assert by_team["Gamma"]["points"] == 2              # tie + NR
    assert by_team["Alpha"]["points"] == 1
    assert by_team["Beta"]["points"] == 1 and \
        by_team["Beta"]["nr"] == 1
    assert table[0]["team"] == "Delhi Daredevils"       # +2.0 NRR


def test_fixtures_result_sentences(zip_path):
    matches = cricsheet.load_matches(zip_path)
    rows = {r["id"]: r for r in
            cricsheet.season_fixtures(matches)}
    assert rows[1001]["result"] == "Alpha won by 7 runs"
    assert rows[1002]["result"] == "Beta won by 7 wickets"
    assert rows[1002]["stage"] == "Final"
    assert rows[1003]["result"] == "Tied, Alpha won the Super Over"
    assert rows[1004]["result"] == "No result"
    assert rows[1001]["scores"][0] == "Alpha 17/0 (2.0)"
    assert rows[1002]["scores"][1].startswith("Beta 13/1")
    # the winner field is the DECISIVE winner only: a Super Over tie
    # names its winner in the result sentence, never here
    assert rows[1001]["winner"] == "Alpha"
    assert rows[1002]["winner"] == "Beta"
    assert rows[1003]["winner"] is None
    assert rows[1004]["winner"] is None


def test_caps_extras_charging_and_wicket_credit(zip_path):
    matches = cricsheet.load_matches(zip_path)
    caps = cricsheet.season_caps(
        _season(matches, 2024),
        {(p, y): ln for (p, y), ln in _lines(matches).items()
         if y == 2024})
    bat = {r["player"]: r for r in caps["batting"]}
    assert bat["aaa1"]["runs"] == 26   # 15 + 11 across both finals
    assert bat["aaa1"]["not_outs"] == 1
    assert bat["bbb1"]["runs"] == 23   # 10 (m1) + 13 (m2 chase)
    bowl = {r["player"]: r for r in caps["bowling"]}
    # caught -> credited; run out + retired hurt -> NOT credited
    assert bowl["xxx2"]["wickets"] == 1
    assert bowl["yyy2"]["wickets"] == 1
    assert bowl["xxx3"]["wickets"] == 0
    # wides charged to bB1 (15 bat + 1 wide), leg-bye NOT (16 vs 17)
    assert bowl["yyy1"]["runs"] == 16
    assert bowl["yyy1"]["balls"] == 12
    assert caps["bowling"][0]["player"] == "xxx2"   # 1/10 before 1/12
    # A bowler's line carries the FIELDING side: bA2 (xxx2) bowled in
    # Beta's innings, so he played for Alpha -- not the batting team.
    assert _lines(matches)[("xxx2", 2024)]["team"] == "Alpha"


def _lines(matches):
    lines: dict = {}
    id_names: dict = {}
    for m in matches:
        for who, key in (m.get("people") or {}).items():
            id_names[key] = who
        for inn in m["innings"]:
            bat_team = inn["team"]
            bowl_team = next((t for t in m["teams"] if t != bat_team),
                             bat_team)
            for player, bat in (inn["bat"] or {}).items():
                cricsheet._line_accum(
                    lines, player, id_names.get(player, player),
                    m["year"], bat_team, bat, None)
            for player, bowl in (inn["bowl"] or {}).items():
                cricsheet._line_accum(
                    lines, player, id_names.get(player, player),
                    m["year"], bowl_team, None, bowl)
    return lines


def test_xi_mvp_and_ladder_weights(zip_path, monkeypatch):
    monkeypatch.setattr(cricsheet, "XI_BAT_MIN_INNS", 1)
    monkeypatch.setattr(cricsheet, "XI_BOWL_MIN_INNS", 1)
    matches = cricsheet.load_matches(zip_path)
    caps = cricsheet.season_caps(
        _season(matches, 2024),
        {(p, y): ln for (p, y), ln in _lines(matches).items()
         if y == 2024})
    xi = cricsheet.season_xi(caps)
    assert xi["batting"] == ["aaa1", "bbb1", "aaa2"]  # top run-scorers
    assert xi["bowling"][:2] == ["xxx2", "yyy2"]  # then fewer runs
    assert xi["allrounder"] is None   # nobody both batted AND bowled
    assert xi["mvp"] == "aaa1"        # 3x26/1000 > 3x1/50
    # Published ladder: A' = 3*(30/1000) + 0.5*1 PoM; B1 also a title.
    honours = {"titles": {"bbb1": 1}, "runner_up": {"aaa1": 1},
               "orange": {"aaa1": 1}, "purple": {"xxx2": 1},
               "pom": {"aaa1": 1, "bbb1": 1}}
    careers = {p: cricsheet._career_of(
        _lines(matches), honours, p, n)
        for p, n in (("aaa1", "A1"), ("bbb1", "B1"))}
    assert careers["aaa1"]["ladder"] == 0.59
    assert careers["bbb1"]["ladder"] == 1.57      # 3x23/1000 + 0.5 + 1.0
    # GOAT = hardware + production: A1 lost the Final + wore an Orange
    # Cap + one PoM (3+6+2.5) over 30 runs (12x30/1000); B1 won the
    # title + one PoM (6+2.5) over 23 runs. Subtotals sum to the total.
    # These are the RAW points _career_of always reports; build() then
    # rescales them onto the 0-100 index (see the build test below).
    assert careers["aaa1"]["goat_hardware"] == 11.5
    assert careers["aaa1"]["goat_production"] == 0.4
    assert careers["aaa1"]["goat"] == 11.9
    assert careers["aaa1"]["runner_up"] == 1
    assert careers["aaa1"]["orange"] == 1
    assert careers["bbb1"]["goat_hardware"] == 8.5
    assert careers["bbb1"]["goat_production"] == 0.3
    assert careers["bbb1"]["goat"] == 8.8
    assert careers["bbb1"]["titles"] == 1
    assert (careers["aaa1"]["goat_hardware"]
            + careers["aaa1"]["goat_production"]
            == careers["aaa1"]["goat"])


def test_goat_index_rescales_onto_100():
    """The published GOAT rating is a 0-100 index: the raw leader sits
    at the top and BOTH subtotals scale by the same factor, so
    Hardware + Production still equals GOAT after the rescale."""
    players = {"aaa1": {"goat": 50.0, "goat_hardware": 40.0,
                        "goat_production": 10.0},
               "bbb1": {"goat": 100.0, "goat_hardware": 80.0,
                        "goat_production": 20.0}}
    raw = cricsheet._goat_index(players)
    assert raw == 100.0                      # the raw leader's score
    assert players["bbb1"]["goat"] == 100.0  # leader stays at the max
    assert players["aaa1"]["goat"] == 50.0   # factor 1.0: nothing moves
    # scale a 50-point leader down to the 100 cap
    weak = {"aaa1": {"goat": 25.0, "goat_hardware": 20.0,
                     "goat_production": 5.0},
            "bbb1": {"goat": 50.0, "goat_hardware": 40.0,
                     "goat_production": 10.0}}
    cricsheet._goat_index(weak)
    assert weak["bbb1"]["goat"] == 100.0
    for p in weak.values():
        assert p["goat"] == round(p["goat_hardware"] + p["goat_production"], 1)
    # no players at all: no crash, no invented leader
    assert cricsheet._goat_index({}) == 0.0


def test_replay_odds_reproducible_and_conservative(zip_path):
    matches = cricsheet.load_matches(zip_path)
    season = _season(matches, 2023)   # four teams: the sim's minimum
    a = cricsheet.replay_odds(season, seed=7, runs=200)
    b = cricsheet.replay_odds(season, seed=7, runs=200)
    assert a == b                                # fixed seed wins
    assert "TOY model" in a["method"]
    total_playoff = sum(o["playoff"] for o in a["odds"].values())
    total_title = sum(o["title"] for o in a["odds"].values())
    # as percentages-of-replays: 4 playoff slots per replay, 1 champion
    assert total_playoff == pytest.approx(400.0)
    assert total_title == pytest.approx(100.0)


def test_phase_boundaries():
    """Powerplay = overs 1-6 (0-based index 0-5), middle = 7-15
    (6-14), death = 16-20 (15-19)."""
    assert [cricsheet._phase(i) for i in (0, 5)] == ["powerplay"] * 2
    assert [cricsheet._phase(i) for i in (6, 14)] == ["middle"] * 2
    assert [cricsheet._phase(i) for i in (15, 19)] == ["death"] * 2


def test_venue_aliases_merge_same_ground_only():
    """Same-ground merges, explicit and chain-free: no alias target is
    itself aliased (a->b->c would drop b silently), and the known
    rename/suffix pairs land on one canonical spelling each."""
    va = cricsheet.VENUE_ALIASES
    assert not (set(va.values()) & set(va))
    assert va["Feroz Shah Kotla"] == "Arun Jaitley Stadium"
    assert va["Arun Jaitley Stadium, Delhi"] == "Arun Jaitley Stadium"
    assert va["Wankhede Stadium, Mumbai"] == "Wankhede Stadium"
    assert va["Sardar Patel Stadium, Motera"] == \
        "Narendra Modi Stadium, Ahmedabad"
    assert va["M.Chinnaswamy Stadium"] == "M Chinnaswamy Stadium"
    assert va["Subrata Roy Sahara Stadium"] == \
        "Maharashtra Cricket Association Stadium"
    assert va["Zayed Cricket Stadium, Abu Dhabi"] == "Sheikh Zayed Stadium"
    # no key ever maps to itself (a silent no-op row)
    assert all(k != v for k, v in va.items())


def _pm(winner, loser, year, stage="League"):
    """A parsed-shape match (what build() feeds the backtest): 20 off
    12 balls beating 10 off 12 -- enough for season_table's NRR and
    the backtest's schedule scan."""
    return {"id": 1, "year": year, "teams": [winner, loser],
            "stage": stage, "result": None, "winner": winner,
            "innings": [
                {"team": winner, "runs": 20, "balls": 12,
                 "all_out": False, "bat": {}, "bowl": {}},
                {"team": loser, "runs": 10, "balls": 12,
                 "all_out": False, "bat": {}, "bowl": {}}]}


def _backtest_by_year() -> dict:
    y22, y23 = [], []
    for loser in ("Beta", "Gamma", "Delta"):
        y22.append(_pm("Alpha", loser, 2022))
        y23.append(_pm("Alpha", loser, 2023))
    y22 += [_pm("Beta", "Gamma", 2022), _pm("Gamma", "Delta", 2022),
            _pm("Beta", "Delta", 2022)]
    y23 += [_pm("Beta", "Gamma", 2023), _pm("Gamma", "Delta", 2023),
            _pm("Beta", "Delta", 2023),
            _pm("Alpha", "Omega", 2023),   # expansion side, no prior
            _pm("Alpha", "Beta", 2023, stage="Qualifier 1"),
            _pm("Gamma", "Delta", 2023, stage="Eliminator")]
    return {2022: y22, 2023: y23}


def test_replay_backtest_uses_prior_season_only():
    """The backtest's information cutoff: strengths come from the PRIOR
    season (Omega, new in 2023, falls back to 0.0 without raising),
    the first season is skipped outright, and the predicted four is
    compared with the real playoff teams (Q1 + Eliminator between them
    name all four). Same seed, identical output."""
    by_year = _backtest_by_year()
    bt = cricsheet.replay_backtest(by_year, seed=7, runs=200)
    assert set(bt["seasons"]) == {"2023"}   # 2022 has no prior season
    row = bt["seasons"]["2023"]
    pool = {"Alpha", "Beta", "Gamma", "Delta", "Omega"}
    assert len(row["predicted"]) == len(set(row["predicted"])) == 4
    assert set(row["predicted"]) <= pool
    assert row["actual"] == ["Alpha", "Beta", "Delta", "Gamma"]
    assert row["overlap"] == len(set(row["predicted"])
                                 & set(row["actual"]))
    assert bt["summary"] == {"seasons": 1,
                             "avg_overlap": float(row["overlap"]),
                             "exact": int(set(row["predicted"])
                                          == set(row["actual"]))}
    assert "PRIOR season" in bt["method"]
    assert "No form, injuries" in bt["method"]
    assert cricsheet.replay_backtest(by_year, seed=7, runs=200) == bt


def test_all_out_side_is_credited_the_full_quota():
    """Official NRR rule: a side bowled out faces the FULL 20-over
    quota, not the overs it actually lasted -- so a collapse of 50 in
    ten overs costs the same rate as 50 in twenty."""
    match = {"teams": ["A", "B"], "stage": "League", "result": None,
             "winner": "A", "innings": [
                 {"team": "A", "runs": 50, "balls": 60, "all_out": True},
                 {"team": "B", "runs": 100, "balls": 120,
                  "all_out": False}]}
    row = {r["team"]: r for r in cricsheet.season_table([match])}
    assert row["A"]["nrr"] == -2.5     # (50/20) - (100/20)
    assert row["B"]["nrr"] == 2.5
    # NOT all out: the 50 stands on the ten overs actually faced (5.0 a
    # over), exactly cancelling B's own rate -- the quota is what bites.
    match["innings"][0]["all_out"] = False
    row = {r["team"]: r for r in cricsheet.season_table([match])}
    assert row["A"]["nrr"] == 0.0      # (50/10) - (100/20)


def test_team_aliases_merge_renames_only():
    assert cricsheet.team_name("Royal Challengers Bangalore") == \
        "Royal Challengers Bengaluru"
    assert cricsheet.team_name("Delhi Daredevils") == "Delhi Capitals"
    assert cricsheet.team_name("Kings XI Punjab") == "Punjab Kings"
    # successors (different franchises) are NOT merged
    assert cricsheet.team_name("Deccan Chargers") == "Deccan Chargers"
    assert cricsheet.team_name("Gujarat Lions") == "Gujarat Lions"


def test_build_writes_attributed_payloads(zip_path, tmp_path):
    built = cricsheet.build(zip_path, out_dir=str(tmp_path), runs=50)
    seasons = json.loads((tmp_path / "ipl_seasons.json")
                         .read_text(encoding="utf-8"))
    players = json.loads((tmp_path / "ipl_players.json")
                         .read_text(encoding="utf-8"))
    assert "Cricsheet" in seasons["source"] and \
        "Attribution" in seasons["source"]
    assert sorted(seasons["seasons"]) == ["2023", "2024"]
    assert seasons["seasons"]["2024"]["champion"] == "Beta"
    assert seasons["seasons"]["2023"]["champion"] is None  # no Final
    assert seasons["meta"] == {"matches": 5, "seasons": 2, "players": 10}
    assert seasons["h2h"]["Alpha|Delhi Capitals"]["b_wins"] == 1
    assert players["ladder_weights"] == cricsheet.GOAT_WEIGHTS
    assert players["goat_weights"] == cricsheet.GOAT_ACCOLADES
    a1 = players["players"]["aaa1"]
    assert a1["name"] == "A1"
    assert a1["career"]["runs"] == 30
    assert a1["career"]["hs"] == 15
    assert a1["pom"] == 1
    # The Final (m2) awards the hardware the GOAT tab counts: A1's Alpha
    # lost it (runner-up), topped the 2024 runs (Orange Cap), and B1's
    # Beta won it (title); 2023's caps went to DD1/A2 by the same rule.
    assert a1["runner_up"] == 1 and a1["orange"] == 1
    # The GOAT rating is a 0-100 INDEX: the raw leader (A1, 11.9 raw
    # points) is rescaled to exactly 100 and every other score follows
    # the SAME factor, so the two subtotals still sum to the total.
    index = players["goat_index"]
    assert index == {"max": 100.0, "leader": "A1", "raw": 11.9}
    factor = 100.0 / index["raw"]
    assert a1["goat_hardware"] == round(11.5 * factor, 1)   # 96.6
    assert a1["goat_production"] == round(0.4 * factor, 1)  # 3.4
    assert a1["goat"] == 100.0 == index["max"]
    assert a1["goat"] == a1["goat_hardware"] + a1["goat_production"]
    # Nobody outscores the index max, and the runner-up (B1) is lower.
    assert max(p["goat"] for p in players["players"].values()) == 100.0
    assert players["players"]["bbb1"]["goat"] < 100.0
    assert players["players"]["ddd1"]["orange"] == 1
    assert players["players"]["xxx2"]["purple"] == 1
    assert built["seasons"]["meta"]["matches"] == 5
    # Whole-season phase splits: every synthetic delivery sits in over
    # 0-1, so it all lands in the powerplay (m1's 17/2 overs + m2's
    # 12/2 for Alpha; m1's 10 + m2's 13 for Beta).
    ph = seasons["seasons"]["2024"]["phases"]
    assert ph["Alpha"]["powerplay"] == {"runs": 29, "balls": 24}
    assert ph["Beta"]["powerplay"] == {"runs": 23, "balls": 25}
    assert ph["Alpha"]["middle"] == {"runs": 0, "balls": 0}
    assert ph["Alpha"]["death"] == {"runs": 0, "balls": 0}
    assert seasons["seasons"]["2023"]["phases"]["Alpha"][
        "powerplay"] == {"runs": 8, "balls": 12}
    # Backtest payload: method printed verbatim; nothing to score on
    # the synthetic years (2023 has no prior season, 2024's table has
    # two teams -- under the sim's four-team minimum).
    bt = seasons["backtest"]
    assert "PRIOR season" in bt["method"]
    assert bt["seasons"] == {} and bt["summary"]["seasons"] == 0
    # Venue merge map rides in the payload for the app's venue views.
    assert seasons["venue_aliases"] == cricsheet.VENUE_ALIASES
