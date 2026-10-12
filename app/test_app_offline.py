"""Offline app render tests via Streamlit's AppTest -- the exact deploy
condition: no network, no collector, only the committed data/ipl_*.json
files a Streamlit Cloud checkout would carry.

Pins the contract that would otherwise rot silently: the page renders,
all ten tabs exist, the honest captions (Cricsheet attribution, LEAGUE
PHASE ONLY, TOY model) are on screen, the latest season's table is a
real table, Player Journey starts with no player selected (and the two
players sharing one display name are BOTH selectable), the phase /
venue / franchise / compare / milestone / backtest views are populated
with their same-ground merges visible, and a missing -- or stale,
pre-GOAT -- data file produces an honest error state rather than a
stack trace or a lie about the record.
"""

import json
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "collector"))


def _render() -> AppTest:
    at = AppTest.from_file(str(REPO_ROOT / "app" / "app.py"),
                           default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    return at


def _text(at: AppTest) -> str:
    """Every human-readable string the page emits: markdown, captions
    and error boxes (the honest-empty-state paths live in the last
    two)."""
    parts = []
    for name in ("markdown", "caption", "error", "info", "title"):
        elements = getattr(at, name, None) or []
        parts += [str(getattr(e, "value", "")) for e in elements]
    return " ".join(parts)


def _table(at: AppTest, first_cols: list, nth: int = 0) -> "object":
    """The nth dataframe whose leading columns match, found by content:
    inserting a tab can never silently repoint a test at the wrong
    table the way a raw index would."""
    hits = []
    for df in at.dataframe:
        cols = list(df.value.columns)
        if cols[:len(first_cols)] == first_cols:
            hits.append(df.value)
    if len(hits) <= nth:
        raise AssertionError(f"no dataframe #{nth} starting "
                             f"with {first_cols} ({len(hits)} found)")
    return hits[nth]


def test_committed_data_json_is_parseable():
    """Both committed payloads must parse: conflict markers or a
    truncated merge commit them silently and every tab would empty out.
    One clear red naming the files beats page-level cascades."""
    broken = []
    for name in ("ipl_seasons.json", "ipl_players.json"):
        path = REPO_ROOT / "data" / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            broken.append(f"{name}: {exc}")
    assert not broken, ("unreadable committed data files "
                        "(conflict markers or truncation?):\n"
                        + "\n".join(broken))


def test_app_renders_all_ten_tabs():
    at = _render()
    assert any("IPL Analytics" in str(t.value) for t in at.title)
    assert [str(t.label) for t in at.tabs] == [
        "Points Table", "Fixtures & Results", "Season Insights",
        "Head-to-Head", "Franchises", "Records & Ladder",
        "GOAT Rankings", "Player Journey", "Compare",
        "Season Replay"]
    # Provenance + honesty captions are on screen: attribution, the
    # league-phase-only table rule, the TOY-model label, the
    # rename-merge note, the phase definition and the venue merge.
    text = _text(at)
    assert "Cricsheet" in text
    assert "ODC-By" in text
    assert "LEAGUE PHASE ONLY" in text
    assert "TOY model, not a prediction product" in text
    assert "RENAMES only" in text
    assert "powerplay = overs 1-6" in text
    assert "same-ground label variants merged" in text
    # The GOAT tab blends two auditable components and says what does
    # NOT count: the voted MVP (absent from the data) and the app's
    # own formula XI.
    assert "Two auditable components" in text
    assert "Most Valuable Player is a voted prize" in text


def test_latest_season_points_table_is_real():
    at = _render()
    table = _table(at, ["#", "Team"])
    assert list(table.columns) == [
        "#", "Team", "P", "W", "L", "T", "NR", "Pts", "NRR",
        "Season champion"]
    assert len(table) >= 8          # a full IPL league phase has 8+ teams
    assert table["NRR"].iloc[0].startswith("+")   # top team, NRR format
    # 14 league games a side in the modern format: no row exceeds it.
    assert table["P"].max() <= 19


def test_goat_rankings_blend_hardware_and_production():
    """The GOAT table shows the blend with separate Hardware /
    Production columns that sum to the total, ranked by the published
    0-100 INDEX (committed-data pin: the all-time leader sits at the
    top of the index; reviewed when a future season legitimately
    reshuffles the summit)."""
    at = _render()
    goat = _table(at, ["#", "Player", "GOAT"])
    assert list(goat.columns)[:7] == ["#", "Player", "GOAT", "Hardware",
                                      "Production", "Titles",
                                      "Runner-up"]
    assert goat["Player"].iloc[0] == "V Kohli"
    # The columns must add up -- that is the audit trail for the blend.
    assert abs(goat["GOAT"].iloc[0]
               - (goat["Hardware"].iloc[0]
                  + goat["Production"].iloc[0])) < 0.05
    assert goat["Production"].iloc[0] > 0        # career output counts
    assert goat["GOAT"].iloc[0] > goat["GOAT"].iloc[1] > 0
    # The rating is an INDEX: the leader tops it out and nothing
    # exceeds the published maximum.
    assert goat["GOAT"].iloc[0] == 100.0
    assert goat["GOAT"].max() <= 100.0
    assert int(goat["Titles"].iloc[0]) >= 1      # Kohli: 2 titles
    text = _text(at)
    assert "0-100 INDEX" in text                 # the rescale is stated
    assert "V Kohli" in text


def test_season_insights_phases_and_venues():
    """The Season Insights tab earns its place: the selected season's
    per-team phase table, an all-time franchise rollup, and a venue
    table whose same-ground merges are VISIBLE -- one Wankhede row,
    not 'Wankhede Stadium' and 'Wankhede Stadium, Mumbai' split
    apart."""
    at = _render()
    phases = _table(at, ["Team", "PP runs", "PP RPO"])
    assert list(phases.columns) == [
        "Team", "PP runs", "PP RPO", "Mid runs", "Mid RPO",
        "Death runs", "Death RPO"]
    assert len(phases) >= 8              # a full league phase
    assert all(isinstance(v, (int, float)) and v > 0
               for v in phases["PP RPO"])   # real balls, real runs
    all_time = _table(at, ["Franchise", "PP runs"])
    assert len(all_time) >= 14           # 15 franchises in the record
    venues = _table(at, ["Venue", "Matches"])
    assert list(venues.columns) == ["Venue", "Matches", "Most wins",
                                    "Wins there"]
    assert len(venues) == 15             # the top-15 cut
    names = list(venues["Venue"])
    assert "Wankhede Stadium" in names
    assert not any(", Mumbai" in v for v in names)   # merged, not split
    wankhede = venues[venues["Venue"] == "Wankhede Stadium"].iloc[0]
    assert wankhede["Matches"] > 100     # both spellings counted
    assert venues["Matches"].is_monotonic_decreasing


def test_franchise_page_starts_empty_then_shows_the_arc():
    """The franchise picker opens on the honest empty state (no team
    auto-picked), and choosing one renders its season-by-season finish
    timeline, title count, and the rename-merged all-time rivalry
    rows."""
    at = _render()
    assert at.selectbox(key="team_ipl").value is None
    assert "Pick a franchise to see its arc" in _text(at)
    at.selectbox(key="team_ipl").select("Mumbai Indians").run()
    assert not at.exception, f"page raised: {at.exception}"
    arc = _table(at, ["Season", "Name that year"])
    assert list(arc.columns) == ["Season", "Name that year", "League pos",
                                 "P", "Pts", "NRR", "Finish"]
    assert len(arc) >= 14               # MI has played every season
    # MI's five titles can only ever grow, never be revoked
    assert sum("Champions" in f for f in arc["Finish"]) >= 5
    rivals = _table(at, ["Opponent", "Played"])
    assert "Chennai Super Kings" in set(rivals["Opponent"])
    assert len(rivals) >= 8
    assert rivals["Played"].is_monotonic_decreasing


def test_franchise_page_merges_era_names():
    """Picking RCB (canonical name) must show BOTH names it wore: the
    era caption, and the as-played column across seasons."""
    at = _render()
    at.selectbox(key="team_ipl").select("Royal Challengers Bengaluru")
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert "Royal Challengers Bangalore" in _text(at)
    arc = _table(at, ["Season", "Name that year"])
    assert "Royal Challengers Bangalore" in set(arc["Name that year"])
    assert "Royal Challengers Bengaluru" in set(arc["Name that year"])


def test_compare_tab_puts_careers_side_by_side():
    """Compare opens empty (both pickers unselected), and picking two
    players renders the metric frame with an auditable GOAT sum on
    each side plus both season overlays."""
    at = _render()
    assert at.selectbox(key="compare_a_ipl").value is None
    assert at.selectbox(key="compare_b_ipl").value is None
    assert ("Pick two players to put their careers side by side"
            in _text(at))
    at.selectbox(key="compare_a_ipl").select("V Kohli").run()
    at.selectbox(key="compare_b_ipl").select("MS Dhoni").run()
    assert not at.exception, f"page raised: {at.exception}"
    pair = _table(at, ["Metric", "V Kohli", "MS Dhoni"])
    by = {m: (pair["V Kohli"].iloc[i], pair["MS Dhoni"].iloc[i])
          for i, m in enumerate(pair["Metric"])}
    # 9,346 against 5,439 in the current record (reviewed when a
    # future season legitimately reshuffles career runs)
    assert int(by["Runs"][0]) > int(by["Runs"][1])
    assert int(by["Titles"][1]) >= 4
    for col in ("V Kohli", "MS Dhoni"):
        total = float(pair[col][pair["Metric"] == "GOAT total"].iloc[0])
        hw = float(pair[col][pair["Metric"] == "GOAT hardware"].iloc[0])
        prod = float(pair[col][
            pair["Metric"] == "GOAT production"].iloc[0])
        assert abs(total - (hw + prod)) < 0.05
    # both season overlays joined the standing three charts (H2H bar,
    # GOAT stack, replay bar)
    charts = {c.key for c in at.get("plotly_chart")}
    assert {"compare_runs_ipl", "compare_wkts_ipl"} <= charts


def test_milestones_show_the_gap_not_a_projection():
    """The Records tab's milestone tables: the next round number above
    each active player's total, closest first (top 10), framed as a
    gap rather than a forecast."""
    at = _render()
    runs = _table(at, ["Player", "Has", "Milestone", "Needs"])
    assert list(runs.columns) == ["Player", "Has", "Milestone", "Needs"]
    assert len(runs) == 10                     # closest chasers only
    assert runs["Needs"].is_monotonic_increasing   # closest first
    assert all(1 <= int(n) <= 1000 for n in runs["Needs"])  # rounds only
    assert min(int(n) for n in runs["Needs"]) <= 25
    wkts = _table(at, ["Player", "Has", "Milestone", "Needs"], nth=1)
    assert len(wkts) == 10
    assert min(int(n) for n in wkts["Needs"]) <= 25
    assert all(1 <= int(n) <= 50 for n in wkts["Needs"])
    text = _text(at)
    assert "A GAP, not a projection" in text
    assert "latest season in the record" in text


def test_replay_backtest_shows_its_information_cutoff():
    """The Replay tab's backtest table: every replayed season with its
    predicted vs actual playoff four, the printed PRIOR-season method,
    and the summary metrics."""
    at = _render()
    bt = _table(at, ["Season", "Predicted top 4"])
    assert list(bt.columns) == ["Season", "Predicted top 4",
                                "Actually reached playoffs", "Overlap"]
    assert len(bt) >= 15            # one row per replayed season
    assert all(str(v).endswith("/4") for v in bt["Overlap"])
    text = _text(at)
    assert "PRIOR season" in text           # the method, verbatim
    assert "blind spot" in text             # the honest weakness


def test_duplicate_display_names_are_selectable():
    """Two real players share the display name Harmeet Singh: the
    picker offers both with their spans, and the journey shows the one
    actually chosen -- not whichever sorted first."""
    at = _render()
    labels = at.selectbox(key="player_ipl").options
    dup = [x for x in labels if x.startswith("Harmeet Singh (")]
    assert len(dup) == 2
    single = next(x for x in dup if "2013-2013" in x)
    at.selectbox(key="player_ipl").select(single).run()
    assert not at.exception, f"page raised: {at.exception}"
    text = _text(at)
    assert "Harmeet Singh" in text
    assert "2013 to 2013" in text
    assert "2009 to 2013" not in text   # not the OTHER Harmeet Singh


def test_player_journey_starts_with_no_selection():
    """The journey box must open EMPTY -- placeholder, no default
    player, and the prompt visible before anything is chosen. An
    auto-picked first player would make the tab look broken."""
    at = _render()
    assert not at.exception, f"page raised: {at.exception}"
    picker = at.selectbox(key="player_ipl")
    assert picker.value is None
    assert "Pick a player to see his journey" in _text(at)


def test_player_journey_renders_after_selection():
    at = _render()
    at.selectbox(key="player_ipl").select("MS Dhoni").run()
    assert not at.exception, f"page raised: {at.exception}"
    text = _text(at)
    assert "MS Dhoni" in text
    assert "Pick a player" not in text      # the prompt is gone
    assert at.dataframe                    # the career table is up
    # The player card: generated initials avatar ("MS Dhoni" -> "MD",
    # only in the card, not in the CSS) and the auditable GOAT
    # breakdown line (only the card spells the two subtotals out).
    assert ">MD</div>" in text
    assert " hardware + " in text


def test_stale_data_without_goat_field_is_an_honest_error(monkeypatch):
    """A data build from before the GOAT tab (no `goat` field anywhere)
    must say the data is stale, NOT 'nobody ever won anything' -- the
    second reading is false, and would hide a bad deploy behind a
    plausible-looking empty state."""
    real_read = Path.read_text

    def _stale(self, *args, **kwargs):
        text = real_read(self, *args, **kwargs)
        if self.name == "ipl_players.json":
            doc = json.loads(text)
            doc.pop("goat_weights", None)
            for player in doc.get("players", {}).values():
                player.pop("goat", None)
            return json.dumps(doc)
        return text

    monkeypatch.setattr(Path, "read_text", _stale)
    import streamlit as st  # noqa: PLC0415 - test-local cache reset

    st.cache_data.clear()
    at = AppTest.from_file(str(REPO_ROOT / "app" / "app.py"),
                           default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    text = _text(at)
    assert "predates the GOAT rankings" in text
    assert "cricsheet.py" in text         # how to rebuild
    assert "No player in the record has ever won anything" not in text


def test_stale_data_without_the_split_is_named_not_blank(monkeypatch):
    """An intermediate build (has `goat` but no `goat_hardware` /
    `goat_production`) would silently render the two columns as blank
    cells -- the exact bug seen against a stale session. It must
    surface as a named stale-data error carrying the build stamp, and
    the Hardware/Production table must not render at all."""
    real_read = Path.read_text

    def _stale(self, *args, **kwargs):
        text = real_read(self, *args, **kwargs)
        if self.name == "ipl_players.json":
            doc = json.loads(text)
            for player in doc.get("players", {}).values():
                player.pop("goat_hardware", None)
                player.pop("goat_production", None)
            return json.dumps(doc)
        return text

    monkeypatch.setattr(Path, "read_text", _stale)
    import streamlit as st  # noqa: PLC0415 - test-local cache reset

    st.cache_data.clear()
    at = AppTest.from_file(str(REPO_ROOT / "app" / "app.py"),
                           default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    text = _text(at)
    assert "predates the hardware/production split" in text
    assert "Data build stamp:" in text        # which build is live
    assert "No player in the record has ever won anything" not in text
    assert not any("Hardware" in list(df.value.columns)
                   for df in at.dataframe)


def test_missing_data_files_are_an_honest_error(monkeypatch):
    """With both payloads gone (fresh checkout before the collector ran,
    or a bad deploy) the page must SAY SO -- an error naming the files
    and the rebuild command, not a stack trace and not another season's
    leftovers."""
    real_read = Path.read_text

    def _deny(self, *args, **kwargs):
        if self.name.startswith("ipl_"):
            raise OSError("denied for test")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _deny)
    # load_docs is @st.cache_data: an earlier test in this file already
    # filled the process-wide cache with the real payloads, and a fresh
    # AppTest run would happily reuse them instead of touching the
    # denied paths. Clearing it is what makes this test exercise the
    # missing-file path at all.
    import streamlit as st  # noqa: PLC0415 - test-local cache reset

    st.cache_data.clear()
    at = AppTest.from_file(str(REPO_ROOT / "app" / "app.py"),
                           default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    text = _text(at)
    assert "missing or unreadable" in text
    assert "cricsheet.py" in text     # tells the operator how to rebuild
