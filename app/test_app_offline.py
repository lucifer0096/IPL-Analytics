"""Offline app render tests via Streamlit's AppTest -- the exact deploy
condition: no network, no collector, only the committed data/ipl_*.json
files a Streamlit Cloud checkout would carry.

Pins the contract that would otherwise rot silently: the page renders,
all seven tabs exist, the honest captions (Cricsheet attribution, LEAGUE
PHASE ONLY, TOY model) are on screen, the latest season's table is a
real table, Player Journey starts with no player selected, and a
missing -- or stale, pre-GOAT -- data file produces an honest error
state rather than a stack trace or a lie about the record.
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


def test_app_renders_all_seven_tabs():
    at = _render()
    assert any("IPL Analytics" in str(t.value) for t in at.title)
    assert [str(t.label) for t in at.tabs] == [
        "Points Table", "Fixtures & Results", "Head-to-Head",
        "Records & Ladder", "GOAT Rankings", "Player Journey",
        "Season Replay"]
    # Provenance + honesty captions are on screen: attribution, the
    # league-phase-only table rule, the TOY-model label, the
    # rename-merge note.
    text = _text(at)
    assert "Cricsheet" in text
    assert "ODC-By" in text
    assert "LEAGUE PHASE ONLY" in text
    assert "TOY model, not a prediction product" in text
    assert "RENAMES only" in text
    # The GOAT tab ranks HARDWARE and says what does NOT count: the
    # voted MVP (absent from the data) and the app's own formula XI.
    assert "HARDWARE only" in text
    assert "Most Valuable Player is a voted prize" in text


def test_latest_season_points_table_is_real():
    at = _render()
    table = at.dataframe[0].value
    assert list(table.columns) == [
        "#", "Team", "P", "W", "L", "T", "NR", "Pts", "NRR",
        "Season champion"]
    assert len(table) >= 8          # a full IPL league phase has 8+ teams
    assert table["NRR"].iloc[0].startswith("+")   # top team, NRR format
    # 14 league games a side in the modern format: no row exceeds it.
    assert table["P"].max() <= 19


def test_goat_rankings_lead_with_the_hardware():
    """The GOAT table is the 7th dataframe on the page and ranks by the
    accolade score -- titles, finals lost, caps, PoM -- with the
    all-time leader on top (committed-data pin: reviewed when a future
    season legitimately reshuffles the summit)."""
    at = _render()
    goat = at.dataframe[6].value
    assert list(goat.columns)[:5] == ["#", "Player", "GOAT", "Titles",
                                      "Runner-up"]
    assert goat["Player"].iloc[0] == "MS Dhoni"
    assert goat["GOAT"].iloc[0] > goat["GOAT"].iloc[1] > 0
    assert int(goat["Titles"].iloc[0]) >= 4


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
