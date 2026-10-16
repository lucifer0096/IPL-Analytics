"""IPL Analytics -- every IPL season from the inaugural 2008 campaign
through the latest, built on Cricsheet's official ball-by-ball files.

Seven in-page tabs, one honest rule: every number is a plain sum over the
official record (points tables, NRR with the all-out quota, Orange/Purple
Cap totals, head-to-head, player careers) or a clearly-labelled TOY model
(the season replay). Nothing is inferred beyond what the data carries,
and empty states say so.

Data: Cricsheet (cricsheet.org), Open Data Commons Attribution License.
The committed data/ipl_seasons.json + data/ipl_players.json are the
deploy's only source (Streamlit Cloud cannot run the collector); rebuild
them locally with `python src/collector/cricsheet.py`.
"""

import colorsys
import hashlib
import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="IPL Analytics", page_icon="\U0001F3CF",
                   layout="wide")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SOURCE_LINE = "Data: Cricsheet (cricsheet.org), ODC-By license"

CSS = """
<style>
:root {
  --ipl-accent: var(--primary-color, #2CA6A4);
  --ipl-gold: #F5C542;
  --ipl-card: color-mix(in srgb, var(--secondary-background-color) 70%,
    transparent);
  --ipl-border: color-mix(in srgb, var(--text-color) 14%, transparent);
}
[data-testid="stTitle"] h1 {
  background: linear-gradient(90deg, var(--ipl-accent), var(--ipl-gold));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.ipl-hero {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
  padding: 12px 16px; margin: 4px 0 14px;
  border: 1px solid var(--ipl-border); border-radius: 14px;
  background: var(--ipl-card);
}
.ipl-pill {
  display: inline-block; padding: 3px 12px; border-radius: 999px;
  font-size: 0.78rem; font-weight: 700;
  background: color-mix(in srgb, var(--ipl-accent) 20%, transparent);
  border: 1px solid color-mix(in srgb, var(--ipl-accent) 45%, transparent);
}
.ipl-pill--gold {
  background: color-mix(in srgb, var(--ipl-gold) 18%, transparent);
  border-color: color-mix(in srgb, var(--ipl-gold) 55%, transparent);
}
.ipl-sub { opacity: 0.75; font-size: 0.9rem; }
[data-baseweb="tab"] { padding-left: 12px; padding-right: 12px; }
[data-baseweb="tab"][aria-selected="true"] {
  border-bottom: 2px solid var(--ipl-accent);
}
.ipl-chip {
  display: inline-block; margin: 2px 4px 2px 0; padding: 3px 11px;
  border-radius: 999px; font-size: 0.78rem; font-weight: 600;
  border: 1px solid var(--ipl-border); background: var(--ipl-card);
}
.ipl-chip--bat { border-color: color-mix(in srgb, var(--ipl-accent) 50%,
  transparent); }
.ipl-chip--bowl { border-color: color-mix(in srgb, var(--ipl-gold) 55%,
  transparent); }
.ipl-chip--gold, .ipl-chip--mvp {
  border-color: var(--ipl-gold);
  background: color-mix(in srgb, var(--ipl-gold) 16%, transparent);
}
.ipl-player-card {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 18px; margin: 2px 0 12px;
  border: 1px solid var(--ipl-border); border-radius: 16px;
  background: var(--ipl-card);
}
.ipl-avatar {
  width: 66px; height: 66px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 800; color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
}
.ipl-card-body { flex: 1; min-width: 0; }
.ipl-card-name { font-size: 1.15rem; font-weight: 700; }
.ipl-card-sub { font-size: 0.85rem; opacity: 0.75; margin-bottom: 4px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def _data_stamp() -> str:
    """mtime signature of the two payloads. Streamlit's file watcher
    only tracks .py files, so a data rebuild on disk never triggers a
    rerun by itself -- but this string is part of the load_docs cache
    key, so the next rerun (any widget interaction) reloads the fresh
    JSON instead of serving what was cached at server start. This is
    exactly the 'new code, old rows' trap: watcher picks up app.py,
    cache keeps last session's data."""
    parts = []
    for name in ("ipl_seasons.json", "ipl_players.json"):
        path = DATA_DIR / name
        try:
            parts.append(f"{name}:{path.stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{name}:missing")
    return "|".join(parts)


@st.cache_data
def load_docs(stamp: str) -> dict:
    """The two committed payloads, parsed once per session (keyed by
    `_data_stamp`, so a rebuild on disk invalidates the cache). A
    missing or unreadable file is an honest empty state in the UI,
    never a crash."""
    out = {}
    for name in ("ipl_seasons.json", "ipl_players.json"):
        path = DATA_DIR / name
        try:
            out[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out[name] = None
    return out


def _df(rows: list, cols: list) -> pd.DataFrame:
    """A frame with every column present (empty frames keep their
    headers so the table still renders its honest skeleton)."""
    frame = pd.DataFrame(rows)
    for col in cols:
        if col not in frame:
            frame[col] = []
    return frame[cols]


def _player_options(roster: list) -> dict:
    """Unique picker label -> player, shared by both player tabs. The
    record holds two real players called Harmeet Singh, and a
    name-only selectbox resolves a duplicate to whichever sorted first
    (silently showing the wrong career). Duplicates get the season
    span appended so both stay selectable."""
    counts: dict = {}
    for p in roster:
        counts[p["name"]] = counts.get(p["name"], 0) + 1
    out: dict = {}
    for p in sorted(roster, key=lambda p: p["name"]):
        label = p["name"]
        if counts[label] > 1 and p.get("seasons"):
            label = (f"{p['name']} ({min(p['seasons'])}"
                     f"-{max(p['seasons'])})")
        out[label] = p
    return out


# Presentational only -- franchise brand colours for the player card's
# generated avatar. No photos exist in the record (Cricsheet carries
# ball-by-ball data, not images) and headshots are other people's
# copyright, so the card draws initials on the team's colours instead
# of fetching a face. Anything not listed gets a stable hue derived
# from its own name.
TEAM_COLORS = {
    "Chennai Super Kings": ("#F4C500", "#005DB7"),
    "Mumbai Indians": ("#004BA0", "#D1AB3E"),
    "Royal Challengers Bangalore": ("#D5152D", "#111111"),
    "Royal Challengers Bengaluru": ("#D5152D", "#111111"),
    "Kolkata Knight Riders": ("#3B2269", "#F2C14E"),
    "Delhi Capitals": ("#004C93", "#EF1B23"),
    "Delhi Daredevils": ("#004C93", "#EF1B23"),
    "Punjab Kings": ("#D71920", "#7E0A10"),
    "Kings XI Punjab": ("#D71920", "#7E0A10"),
    "Rajasthan Royals": ("#EA1A85", "#254AA5"),
    "Sunrisers Hyderabad": ("#F26522", "#0B0B0B"),
    "Gujarat Titans": ("#1B2133", "#B4975A"),
    "Lucknow Super Giants": ("#0057E2", "#00306B"),
    "Deccan Chargers": ("#002B5C", "#C0A062"),
    "Pune Warriors": ("#E52327", "#4A0A0C"),
    "Rising Pune Supergiant": ("#D6244E", "#4C0A1C"),
    "Rising Pune Supergiants": ("#D6244E", "#4C0A1C"),
    "Gujarat Lions": ("#E8462B", "#1B4F8C"),
    "Kochi Tuskers Kerala": ("#F5A623", "#0E5C33"),
}


def _team_colors(team: str) -> tuple:
    if team in TEAM_COLORS:
        return TEAM_COLORS[team]
    hue = int(hashlib.md5(team.encode("utf-8")).hexdigest(), 16) % 360
    top = colorsys.hsv_to_rgb(hue / 360, 0.72, 0.90)
    base = colorsys.hsv_to_rgb(hue / 360, 0.80, 0.62)
    return ("#{:02X}{:02X}{:02X}".format(*(round(255 * v) for v in top)),
            "#{:02X}{:02X}{:02X}".format(*(round(255 * v) for v in base)))


def _initials(name: str) -> str:
    parts = [w for w in name.split() if w]
    return "".join(w[0].upper() for w in parts[:2]) or "?"


def player_card(p: dict) -> str:
    """The Journey tab's trading card: a generated initials avatar on
    the player's last team's colours, his career span, and every
    published number as chips -- career, hardware, ladder and the GOAT
    score with both subtotals spelled out, so the blend is auditable
    right on the card. Theme-aware CSS only, so it stays legible on
    light and dark; every player-supplied string is escaped."""
    name = html.escape(p.get("name", "?"))
    lines = p.get("seasons") or {}
    ordered = sorted(lines, key=int)
    last = lines[ordered[-1]] if ordered else {}
    team = last.get("team", "")
    car = p.get("career") or {}
    c1, c2 = _team_colors(team)
    chips = [
        ("Runs", f"{car.get('runs', 0):,}"),
        ("HS", str(car.get("hs", 0))),
        ("Wkts", str(car.get("wickets", 0))),
    ]
    best = car.get("best") or [0, 0]
    if car.get("balls_bowled"):
        chips.append(("Best", f"{best[0]}/{best[1]}"))
        if car.get("econ") is not None:
            chips.append(("Econ", str(car["econ"])))
        if car.get("bowl_avg") is not None:
            chips.append(("Avg", str(car["bowl_avg"])))
    if (car.get("catches") or car.get("stumpings")
            or car.get("run_outs")):
        chips.append(("Catches", str(car.get("catches", 0))))
        chips.append(("Stumpings", str(car.get("stumpings", 0))))
        chips.append(("Run-outs", str(car.get("run_outs", 0))))
    chips += [
        ("PoM", str(p.get("pom", 0))),
        ("Titles", str(p.get("titles", 0))),
        ("Runner-up", str(p.get("runner_up", 0))),
        ("Orange", str(p.get("orange", 0))),
        ("Purple", str(p.get("purple", 0))),
        ("Ladder", str(p.get("ladder", 0))),
    ]
    gold = {"Titles", "Runner-up", "Orange", "Purple"}
    chip_html = "".join(
        f'<span class="{"ipl-chip ipl-chip--gold" if k in gold else "ipl-chip"}">'
        f"{k} {html.escape(v)}</span>" for k, v in chips)
    if "goat" in p:                    # a stale build simply omits it
        chip_html += (f'<span class="ipl-chip ipl-chip--gold">GOAT '
                      f'{p["goat"]}</span>')
    sub = f"{ordered[0]}-{ordered[-1]}" if ordered else "no seasons"
    sub += f" · {team}" if team else ""
    if p.get("role"):
        sub += f" · {p['role']}"
    if "goat_hardware" in p:
        sub += (f" · GOAT {p['goat']} = {p['goat_hardware']} hardware "
                f"+ {p['goat_production']} production")
    return (
        '<div class="ipl-player-card">'
        f'<div class="ipl-avatar" style="background-image: '
        f"linear-gradient(rgba(0,0,0,0.30), rgba(0,0,0,0.30)), "
        f'linear-gradient(135deg, {c1}, {c2});">'
        f"{_initials(p.get('name', ''))}</div>"
        '<div class="ipl-card-body">'
        f'<div class="ipl-card-name">{name}</div>'
        f'<div class="ipl-card-sub">{html.escape(sub)}</div>'
        f'<div>{chip_html}</div>'
        "</div></div>"
    )


st.title("IPL Analytics")
docs = load_docs(_data_stamp())
seasons_doc = docs.get("ipl_seasons.json")
players_doc = docs.get("ipl_players.json")

if seasons_doc is None or players_doc is None:
    st.error(
        "The committed data files (data/ipl_seasons.json, "
        "data/ipl_players.json) are missing or unreadable. Rebuild them "
        "locally with `python src/collector/cricsheet.py` and commit the "
        "result. There is no live fallback: this app only shows what the "
        "committed record actually contains."
    )
    st.stop()

seasons = seasons_doc["seasons"]
players = players_doc["players"]
aliases = seasons_doc.get("team_aliases") or {}
venue_aliases = seasons_doc.get("venue_aliases") or {}


def canonical(team: str) -> str:
    """Merge-alias view of a team name: franchise RENAMES only. Season
    tables keep the names each year was played under; all-time views
    go through this so one franchise is one row."""
    return aliases.get(team, team)


def canonical_venue(venue: str) -> str:
    """Same-ground merge for venue labels: Cricsheet writes every
    historical spelling ("Wankhede Stadium" / "Wankhede Stadium,
    Mumbai"), fixtures keep the published string."""
    return venue_aliases.get(venue, venue)

weights = players_doc.get("ladder_weights") or {}
WEIGHTS_CAPTION = (
    "Published weights (one config, src/collector/cricsheet.py "
    "GOAT_WEIGHTS): ladder = "
    f"{weights.get('runs_per_1000', 3.0)} per 1000 runs + "
    f"{weights.get('wickets_per_50', 3.0)} per 50 wickets + "
    f"{weights.get('player_of_match', 0.5)} per player-of-the-match + "
    f"{weights.get('title', 1.0)} per title. Titles = seasons taking the "
    "field for the champion. {source}".format(source=SOURCE_LINE)
)

# Sidebar: season selector + provenance, keys suffixed _ipl so another
# app's widgets never collide on a shared Streamlit instance.
st.sidebar.markdown("### Season")
years = sorted(seasons, key=int, reverse=True)
year = st.sidebar.selectbox("Season", years, key="season_ipl")
meta = seasons_doc.get("meta") or {}
st.sidebar.caption(
    f"{meta.get('matches', 0)} matches, {meta.get('seasons', 0)} seasons, "
    f"{meta.get('players', 0)} players. Generated "
    f"{seasons_doc.get('_generated_utc', 'unknown')}."
)
if aliases:
    st.sidebar.caption(
        "All-time views merge franchise RENAMES only ("
        + "; ".join(f"{k} -> {v}" for k, v in aliases.items())
        + "). Season tables keep the names each year was played under."
    )
st.sidebar.caption(SOURCE_LINE)

season = seasons.get(str(year)) or {}
champion = season.get("champion")
champion_cap = (
    f"\U0001F3C6 {champion}" if champion
    else "No completed Final in the record for this season"
)
st.markdown(
    f'<div class="ipl-hero"><span class="ipl-pill">{year} season</span>'
    f'<span class="ipl-pill ipl-pill--gold">{champion_cap}</span>'
    f'<span class="ipl-sub">{SOURCE_LINE}</span></div>',
    unsafe_allow_html=True,
)

tab_table, tab_fix, tab_insights, tab_h2h, tab_franchise, tab_records, \
    tab_goat, tab_journey, tab_compare, tab_replay = st.tabs([
        "Points Table", "Fixtures & Results", "Season Insights",
        "Head-to-Head", "Franchises", "Records & Ladder",
        "GOAT Rankings", "Player Journey", "Compare",
        "Season Replay"])
by_id = {pid: p["name"] for pid, p in players.items()}

# --------------------------------------------------------------------------
# Points Table
# --------------------------------------------------------------------------
with tab_table:
    st.subheader(f"IPL {year} points table")
    table = season.get("points") or []
    if not table:
        st.info("No league-phase matches in the record for this season.")
    else:
        rows = []
        for pos, r in enumerate(table, start=1):
            rows.append({
                "#": pos, "Team": r["team"], "P": r["played"],
                "W": r["won"], "L": r["lost"], "T": r["tied"],
                "NR": r["nr"], "Pts": r["points"],
                "NRR": f"{r['nrr']:+.3f}",
                "Season champion": "\U0001F3C6" if r["team"] == champion
                                    else "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "Points: win 2, tie or no result 1 each, loss 0. NRR = "
            "(runs for / overs faced) - (runs conceded / overs bowled); "
            "a side bowled out is credited the FULL 20-over quota; "
            "wides and no-balls count, byes and leg-byes do not face an "
            "over. LEAGUE PHASE ONLY: Qualifiers, Eliminators and Finals "
            "never count toward the table. " + SOURCE_LINE
        )
        top = table[0]
        st.markdown(
            f"League phase topped by **{top['team']}** with "
            f"{top['points']} points (NRR {top['nrr']:+.3f})"
            + (f"; champions: **{champion}**." if champion else ".")
        )

# --------------------------------------------------------------------------
# Fixtures & Results
# --------------------------------------------------------------------------
with tab_fix:
    st.subheader(f"IPL {year} fixtures & results")
    fixtures = season.get("fixtures") or []
    if not fixtures:
        st.info("No matches in the record for this season.")
    else:
        stages = sorted({f["stage"] for f in fixtures})
        picked = st.multiselect(
            "Stages", stages, default=stages, key=f"stages_{year}_ipl")
        rows = [{
            "Date": f.get("date") or "", "Stage": f["stage"],
            "Match": " vs ".join(f["teams"]),
            "Scores": "; ".join(f["scores"]) if f["scores"]
                       else "no innings in the record",
            "Result": f["result"],
            "Venue": f.get("venue") or "",
            "Player of the match": f.get("pom") or "",
        } for f in fixtures if f["stage"] in picked]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     width="stretch")
        st.caption(
            "Every match of the season, playoff rounds included, with "
            "the scoreline as recorded (overs in cricket notation, e.g. "
            "15.2 = 15 overs and 2 balls). Ties show the Super Over "
            "winner as text only. " + SOURCE_LINE
        )

# --------------------------------------------------------------------------
# Season Insights (over phases + venues)
# --------------------------------------------------------------------------
with tab_insights:
    st.subheader(f"IPL {year}: phases & venues")

    st.markdown("#### Over phases")
    phases = season.get("phases") or {}
    if not phases:
        st.info("No phase splits in this build of the data (the payload "
                "predates them -- rebuild with "
                "`python src/collector/cricsheet.py`). Showing nothing "
                "rather than zeros that would look like real cricket.")
    else:
        def phase_rows(by_team) -> list:
            out = []
            for team, ph in sorted(by_team.items()):
                row = {"Team": team}
                for label, key in (("PP", "powerplay"),
                                   ("Mid", "middle"), ("Death", "death")):
                    agg = ph.get(key) or {}
                    runs, balls = agg.get("runs", 0), agg.get("balls", 0)
                    row[f"{label} runs"] = runs
                    row[f"{label} RPO"] = (round(runs / (balls / 6), 2)
                                           if balls else "")
                out.append(row)
            return out

        phase_cols = ["Team", "PP runs", "PP RPO", "Mid runs", "Mid RPO",
                      "Death runs", "Death RPO"]
        st.dataframe(_df(phase_rows(phases), phase_cols),
                     hide_index=True, width="stretch")
        st.caption(
            "Phases by over faced: powerplay = overs 1-6, middle = "
            "7-15, death = 16-20. RPO = runs per 6-ball over (legal "
            "balls only; a wide adds runs but no ball). Whole season, "
            "playoffs included, team names as played that year. "
            + SOURCE_LINE
        )

        all_time: dict = {}
        for s in seasons.values():
            for team, ph in (s.get("phases") or {}).items():
                bucket = all_time.setdefault(canonical(team), {})
                for key in ("powerplay", "middle", "death"):
                    agg = ph.get(key) or {}
                    slot = bucket.setdefault(key,
                                             {"runs": 0, "balls": 0})
                    slot["runs"] += agg.get("runs", 0)
                    slot["balls"] += agg.get("balls", 0)
        if all_time:
            st.markdown("#### All-time phase profile")
            rows = []
            for r in phase_rows(all_time):
                row = {"Franchise": r.pop("Team")}
                row.update(r)
                rows.append(row)
            st.dataframe(_df(rows, ["Franchise"] + phase_cols[1:]),
                         hide_index=True, width="stretch")
            st.caption(
                "Every delivery in the record summed per franchise, "
                "franchise renames merged (" + (
                    "; ".join(f"{k} -> {v}" for k, v in aliases.items())
                    if aliases else "none") + "). " + SOURCE_LINE
            )

    st.markdown("#### Venues, all history")
    venue_stats: dict = {}
    for s in seasons.values():
        for f in s.get("fixtures") or []:
            v = canonical_venue(f.get("venue") or "Unknown")
            slot = venue_stats.setdefault(v, {"matches": 0, "wins": {}})
            slot["matches"] += 1
            w = f.get("winner")
            if w:
                w = canonical(w)
                slot["wins"][w] = slot["wins"].get(w, 0) + 1
    if not venue_stats:
        st.info("No venues in the record.")
    else:
        top = sorted(venue_stats.items(),
                     key=lambda kv: (-kv[1]["matches"], kv[0]))[:15]
        rows = []
        for v, slot in top:
            best = (max(slot["wins"].items(),
                        key=lambda kv: (kv[1], kv[0]))
                    if slot["wins"] else ("-", 0))
            rows.append({"Venue": v, "Matches": slot["matches"],
                         "Most wins": best[0], "Wins there": best[1]})
        st.dataframe(_df(rows, ["Venue", "Matches", "Most wins",
                                "Wins there"]),
                     hide_index=True, width="stretch")
        st.caption(
            f"Top 15 of {len(venue_stats)} grounds in the record; "
            f"{len(venue_aliases)} same-ground label variants merged "
            "(e.g. Feroz Shah Kotla = Arun Jaitley Stadium, "
            "Subrata Roy Sahara Stadium = Maharashtra Cricket "
            "Association Stadium) -- fixtures keep the string each "
            "match was published under. Whole history, playoffs "
            "included; ties and no-results count in Matches but award "
            "nobody a win. " + SOURCE_LINE
        )

# --------------------------------------------------------------------------
# Head-to-Head
# --------------------------------------------------------------------------
with tab_h2h:
    st.subheader("Head-to-head, all history")
    h2h = seasons_doc.get("h2h") or {}
    teams = sorted({row["a"] for row in h2h.values()}
                   | {row["b"] for row in h2h.values()})
    if len(teams) < 2:
        st.info("Not enough teams in the record for a rivalry view.")
    else:
        default_a = ("Chennai Super Kings" if "Chennai Super Kings"
                     in teams else teams[0])
        default_b = ("Mumbai Indians" if "Mumbai Indians" in teams
                     else teams[-1])
        col_a, col_b = st.columns(2)
        with col_a:
            a = st.selectbox("Team A", teams, index=teams.index(default_a),
                             key="h2h_a_ipl")
        with col_b:
            b = st.selectbox("Team B", teams, index=teams.index(default_b),
                             key="h2h_b_ipl")
        if a == b:
            st.info("Pick two different teams to see the rivalry.")
        else:
            key = "|".join(sorted([a, b]))
            row = h2h.get(key)
            if not row:
                st.info("These two teams have no matches against each "
                        "other in the record.")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Matches", row["played"])
                c2.metric(row["a"], row["a_wins"])
                c3.metric(row["b"], row["b_wins"])
                other = row["tied"] + row["nr"]
                c4.metric("Ties / no result", other)
                fig = go.Figure(go.Bar(
                    x=[row["a_wins"], row["b_wins"], row["tied"],
                       row["nr"]],
                    y=[row["a"], row["b"], "Tied", "No result"],
                    orientation="h",
                    marker_color=["#2CA6A4", "#F5C542",
                                  "#8A93A6", "#4A5060"]))
                fig.update_layout(
                    height=260, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(tickmode="linear", dtick=1),
                    showlegend=False)
                st.plotly_chart(fig, width="stretch",
                                key=f"h2h_bar_{key.replace(' ', '_')}_ipl")
                st.caption(
                    "All history (league + playoffs), franchise renames "
                    "merged: "
                    + ("; ".join(f"{k} counts as {v}"
                                 for k, v in aliases.items())
                       if aliases else "no renames to merge")
                    + ". " + SOURCE_LINE
                )
        st.markdown("#### Most-played rivalries")
        most = sorted(h2h.values(), key=lambda r: -r["played"])[:15]
        st.dataframe(_df(
            [{"Pair": f"{r['a']} vs {r['b']}", "Played": r["played"],
              r["a"]: r["a_wins"], r["b"]: r["b_wins"],
              "Tied": r["tied"], "No result": r["nr"]} for r in most],
            ["Pair", "Played", "Tied", "No result"]),
            hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Franchises
# --------------------------------------------------------------------------
with tab_franchise:
    st.subheader("Franchise pages")
    # every franchise under one merged name + the names it wore
    eras: dict = {}
    for s in seasons.values():
        for f in s.get("fixtures") or []:
            for t in f.get("teams") or []:
                eras.setdefault(canonical(t), set()).add(t)
    franchises = sorted(eras)
    if not franchises:
        st.info("No teams in the record.")
    else:
        pick = st.selectbox("Franchise", franchises, index=None,
                            placeholder="Choose a franchise...",
                            key="team_ipl")
        if not pick:
            st.info("Pick a franchise to see its arc: every season's "
                    "finish, the title timeline, and the all-time "
                    "record against each opponent.")
        else:
            if len(eras[pick]) > 1:
                st.caption(
                    "One franchise, names it wore in the record: "
                    + " / ".join(sorted(eras[pick])) + "."
                )
            rows, title_years, playoff_years = [], [], []
            for y in sorted(seasons, key=int):
                s = seasons[y]
                fx = s.get("fixtures") or []
                mine = [f for f in fx
                        if pick in [canonical(t)
                                    for t in (f.get("teams") or [])]]
                if not mine:
                    continue
                as_played = next(t for t in mine[0]["teams"]
                                 if canonical(t) == pick)
                prow = next((r for r in (s.get("points") or [])
                             if r["team"] == as_played), None)
                stages = {f["stage"] for f in mine}
                champ = s.get("champion")
                if champ and canonical(champ) == pick:
                    finish = "\U0001F3C6 Champions"
                    title_years.append(y)
                elif "Final" in stages:
                    finish = "Runner-up"
                elif "Qualifier 2" in stages:
                    finish = "Lost Qualifier 2"
                elif "Semi Final" in stages:
                    finish = "Semi-final exit"
                elif stages & {"Eliminator", "Elimination Final"}:
                    finish = "Lost Eliminator"
                elif "Qualifier 1" in stages:
                    finish = "Lost Qualifier 1"
                else:
                    finish = "League stage"
                if stages - {"League"}:
                    playoff_years.append(y)
                rows.append({
                    "Season": y, "Name that year": as_played,
                    "League pos": next(
                        (i for i, r in enumerate(s.get("points") or [], 1)
                         if r["team"] == as_played), "-"),
                    "P": prow["played"] if prow else "-",
                    "Pts": prow["points"] if prow else "-",
                    "NRR": (f"{prow['nrr']:+.3f}" if prow else "-"),
                    "Finish": finish,
                })
            c1, c2, c3 = st.columns(3)
            c1.metric("Seasons", len(rows))
            c2.metric("Playoff seasons", len(playoff_years))
            c3.metric("Titles", len(title_years))
            if title_years:
                st.markdown(
                    "**Title timeline:** "
                    + " ".join(
                        f'<span class="ipl-pill ipl-pill--gold">'
                        f'{y}</span>' for y in title_years),
                    unsafe_allow_html=True)
            else:
                st.markdown("**Title timeline:** no titles in the record")
            st.dataframe(_df(
                rows, ["Season", "Name that year", "League pos",
                       "P", "Pts", "NRR", "Finish"]),
                hide_index=True, width="stretch")
            st.caption(
                "Every season the franchise took the field (calendar "
                "year = year played), league position from the "
                "league-phase-only table, finish = furthest stage "
                "reached: Champion, Runner-up, Qualifier 2, "
                "Qualifier 1, Eliminator (2008-2010: Semi Final), or "
                "League stage. " + SOURCE_LINE
            )
            # all-time record vs each opponent: sums of the same
            # rename-merged head-to-head rows the other tab shows
            overall = {"p": 0, "w": 0, "l": 0, "t": 0, "nr": 0}
            opp_rows = []
            for r in h2h.values():
                if r["a"] == pick:
                    opp, win, lose = r["b"], r["a_wins"], r["b_wins"]
                elif r["b"] == pick:
                    opp, win, lose = r["a"], r["b_wins"], r["a_wins"]
                else:
                    continue
                overall["p"] += r["played"]
                overall["w"] += win
                overall["l"] += lose
                overall["t"] += r["tied"]
                overall["nr"] += r["nr"]
                opp_rows.append({"Opponent": opp, "Played": r["played"],
                                 "W": win, "L": lose, "T": r["tied"],
                                 "NR": r["nr"]})
            opp_rows.sort(key=lambda x: (-x["Played"], x["Opponent"]))
            st.markdown("#### All-time record")
            o1, o2 = st.columns(2)
            o1.metric("Matches", overall["p"])
            o2.metric("W-L-T-NR",
                      f"{overall['w']}-{overall['l']}-"
                      f"{overall['t']}-{overall['nr']}")
            st.dataframe(_df(opp_rows, ["Opponent", "Played", "W",
                                        "L", "T", "NR"]),
                         hide_index=True, width="stretch")
            st.caption(
                "All history (league + playoffs), franchise renames "
                "merged; Super Over ties are counted under T here, "
                "with the Super Over winner named on the Fixtures & "
                "Results tab. " + SOURCE_LINE
            )

# --------------------------------------------------------------------------
# Records & Ladder
# --------------------------------------------------------------------------
with tab_records:
    st.subheader(f"IPL {year}: formula XI & season MVP")
    xi = season.get("xi") or {}
    caps = season.get("caps") or {}

    def chips(ids, css):
        return " ".join(
            f'<span class="ipl-chip {css}">'
            f'{html.escape(by_id.get(pid, pid))}</span>'
            for pid in ids)

    st.markdown(chips(xi.get("batting") or [], "ipl-chip--bat"),
                unsafe_allow_html=True)
    allrounder = xi.get("allrounder")
    st.markdown(
        (chips([allrounder], "ipl-chip--bat") + " "
         if allrounder else "")
        + chips(xi.get("bowling") or [], "ipl-chip--bowl"),
        unsafe_allow_html=True)
    mvp = xi.get("mvp")
    if mvp:
        st.markdown(
            f'<span class="ipl-chip ipl-chip--mvp">Season MVP: '
            f'{by_id.get(mvp, mvp)} (impact {xi.get("mvp_impact")})'
            f'</span>', unsafe_allow_html=True)
    else:
        st.info("No player met the XI/MVP qualifiers this season "
                "(at least 4 batting or bowling innings).")
    st.caption(
        "Formula XI, because Cricsheet carries no player roles: the five "
        "highest run-scorers, the five highest wicket-takers among "
        "players not already picked, the best remaining all-rounder "
        "(batted AND bowled that season, most combined impact), and the "
        "season MVP by that same impact. Qualifier: at least 4 innings. "
        "Orange/Purple Cap = most runs / most wickets. " + SOURCE_LINE
    )

    cap_bat, cap_bowl = st.columns(2)
    with cap_bat:
        st.markdown("#### Orange Cap (most runs)")
        st.dataframe(_df(
            [{"#": i, "Player": r["name"], "Team": r["team"],
              "Runs": r["runs"], "Inns": r["inns"], "HS": r["hs"],
              "50s": r["fifties"], "100s": r["hundreds"],
              "SR": r["sr"]}
             for i, r in enumerate((caps.get("batting") or [])[:10], 1)],
            ["#", "Player", "Runs"]), hide_index=True,
            width="stretch")
    with cap_bowl:
        st.markdown("#### Purple Cap (most wickets)")
        st.dataframe(_df(
            [{"#": i, "Player": r["name"], "Team": r["team"],
              "Wkts": r["wickets"], "Inns": r["inns"],
              "Econ": r["econ"], "Best": r["best"]}
             for i, r in enumerate((caps.get("bowling") or [])[:10], 1)],
            ["#", "Player", "Wkts"]), hide_index=True,
            width="stretch")
    st.caption(
        "Cap tables count the whole season, playoffs included. "
        + SOURCE_LINE
    )

    st.markdown("#### All-time ladder (production)")
    ladder = sorted(players.values(),
                    key=lambda p: -p.get("ladder", 0))[:25]
    st.dataframe(_df(
        [{"Player": p["name"],
          "Seasons": f"{min(p['seasons'])}-{max(p['seasons'])}"
                     if p.get("seasons") else "",
          "Runs": p["career"]["runs"],
          "Wkts": p["career"]["wickets"],
          "PoM": p["pom"], "Titles": p["titles"],
          "Ladder": p["ladder"]} for p in ladder],
        ["Player", "Runs", "Wkts", "PoM", "Titles", "Ladder"]),
        hide_index=True, width="stretch")
    st.caption(WEIGHTS_CAPTION + " This is the PRODUCTION ladder; the "
                "GOAT Rankings tab blends hardware + role-gated "
                "production.")

    st.markdown("#### Milestones within reach")
    latest = max(int(y) for y in seasons)
    active = [p for p in players.values()
              if p.get("seasons")
              and max(int(y) for y in p["seasons"]) == latest]
    run_rows, wkt_rows = [], []
    for p in active:
        c = p["career"]
        nxt = next((m for m in range(1000, 10001, 1000)
                    if m > c["runs"]), None)
        if nxt:
            run_rows.append({"Player": p["name"], "Has": c["runs"],
                             "Milestone": f"{nxt:,}",
                             "Needs": nxt - c["runs"]})
        nxt = next((m for m in range(50, 301, 50)
                    if m > c["wickets"]), None)
        if nxt:
            wkt_rows.append({"Player": p["name"], "Has": c["wickets"],
                             "Milestone": f"{nxt}",
                             "Needs": nxt - c["wickets"]})
    if not run_rows and not wkt_rows:
        st.info("No player active in the latest season is within reach "
                "of a round career number in this build.")
    else:
        col_r, col_w = st.columns(2)
        cols = ["Player", "Has", "Milestone", "Needs"]
        with col_r:
            st.markdown("**Runs**")
            st.dataframe(_df(
                sorted(run_rows, key=lambda r: r["Needs"])[:10], cols),
                hide_index=True, width="stretch")
        with col_w:
            st.markdown("**Wickets**")
            st.dataframe(_df(
                sorted(wkt_rows, key=lambda r: r["Needs"])[:10], cols),
                hide_index=True, width="stretch")
        st.caption(
            f"Players who took the field in {latest}, the latest "
            "season in the record, ordered by how close they sit to "
            "the next round career number: runs to the next thousand "
            "up to 10,000, wickets to the next 50 up to 300 (a player "
            "past the top rung has no row). A GAP, not a projection: "
            "no batting pace, games left or fitness is assumed. "
            + SOURCE_LINE
        )

# --------------------------------------------------------------------------
# GOAT Rankings (hardware + production)
# --------------------------------------------------------------------------
with tab_goat:
    st.subheader("GOAT index (0-100): hardware + role-gated production")
    goat_weights = players_doc.get("goat_weights") or {}
    goat_index = players_doc.get("goat_index") or {}
    build_stamp = players_doc.get("_generated_utc", "unknown")
    # A data build older than this tab must read as STALE DATA with its
    # stamp, never as "nobody won anything" and never as blank cells:
    # a missing field below would silently render an empty column.
    built_with_goat = any("goat" in p for p in players.values())
    split_ok = all("goat_hardware" in p and "goat_production" in p
                   for p in players.values())
    ranked = (sorted((p for p in players.values()
                      if p.get("goat", 0) > 0),
                     key=lambda p: -p["goat"])[:25]
              if built_with_goat and split_ok else [])
    if not built_with_goat:
        st.error(
            "This build of data/ipl_players.json predates the GOAT "
            "rankings (no `goat` field on any player). Rebuild with "
            "`python src/collector/cricsheet.py` and redeploy -- an "
            "empty table here would misrepresent the record. "
            f"Data build stamp: {build_stamp}."
        )
    elif not split_ok:
        st.error(
            "This build of data/ipl_players.json predates the "
            "hardware/production split (no `goat_hardware` / "
            "`goat_production` fields), so those columns would render "
            "blank. Rebuild with `python src/collector/cricsheet.py` "
            f"and redeploy. Data build stamp: {build_stamp}."
        )
    elif not ranked:
        st.info("No player in the record has ever won anything.")
    else:
        rows = []
        for i, p in enumerate(ranked, start=1):
            span = (f"{min(p['seasons'])}-{max(p['seasons'])}"
                    if p.get("seasons") else "")
            rows.append({
                "#": i, "Player": p["name"], "Role": p.get("role", "-"),
                "GOAT": p["goat"],
                "Hardware": p.get("goat_hardware"),
                "Production": p.get("goat_production"),
                "Titles": p["titles"], "Runner-up": p["runner_up"],
                "Orange": p["orange"], "Purple": p["purple"],
                "PoM": p["pom"], "Seasons": span})
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     width="stretch")
        # Stacked so the blend is visible: rank 1 on top, hardware and
        # production as separate segments that add to the bar's length.
        top10 = list(reversed(rows[:10]))
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=[r["Player"] for r in top10],
            x=[r["Hardware"] for r in top10], orientation="h",
            name="Hardware", marker_color="#F5C542"))
        fig.add_trace(go.Bar(
            y=[r["Player"] for r in top10],
            x=[r["Production"] for r in top10], orientation="h",
            name="Production", marker_color="#2CA6A4"))
        fig.update_layout(barmode="stack",
                          height=max(240, 30 * len(top10)),
                          margin=dict(l=10, r=10, t=10, b=10),
                          legend_orientation="h")
        st.plotly_chart(fig, width="stretch", key="goat_bar_ipl")
        # The index rescale is stated up front (raw points -> 0-100),
        # and a build from before the rescale says so instead of
        # pretending its raw points are already an index.
        leader_name = goat_index.get("leader") or "the top scorer"
        index_line = (
            f"GOAT is a 0-100 INDEX: raw points are rescaled so the "
            f"all-time leader ({leader_name}) sits at "
            f"{goat_index.get('max', 100.0)} "
            f"(raw {goat_index.get('raw', 0)} points). "
            if goat_index else
            "These are raw GOAT points; this build predates the "
            "0-100 index rescale. ")
        st.caption(
            index_line +
            "Two auditable components, one published config "
            "(GOAT_ACCOLADES); GOAT = Hardware + Production columns. "
            "HARDWARE is what the official record says a player won: "
            f"{goat_weights.get('title', 6.0)} per title (took the "
            f"field for the champion), "
            f"{goat_weights.get('runner_up', 3.0)} per Final lost, "
            f"{goat_weights.get('orange_cap', 6.0)} per Orange Cap "
            "(topped the season's runs), "
            f"{goat_weights.get('purple_cap', 6.0)} per Purple Cap "
            "(topped the season's wickets), "
            f"{goat_weights.get('player_of_match', 2.5)} per official "
            "player-of-the-match award (counted once, in hardware). "
            "PRODUCTION is ROLE-GATED -- nobody is judged on a "
            "discipline he never played. Batters and all-rounders "
            "(1000+ career runs) score "
            f"{goat_weights.get('runs_per_1000', 12.0)} per 1000 runs; "
            "bowlers and all-rounders (30+ career wickets) score "
            f"{goat_weights.get('wickets_per_50', 16.0)} per 50 wickets "
            "plus a quality bonus: "
            f"{goat_weights.get('economy_weight', 6.0)} per run/over "
            f"under the {goat_weights.get('economy_par', 8.5)} par "
            "economy (20+ overs bowled) and "
            f"{goat_weights.get('average_weight', 3.0)} per run under "
            f"the {goat_weights.get('average_par', 28.0)} par average "
            "(50+ wickets), plus "
            f"{goat_weights.get('four_wkts', 2.0)} per four-for and "
            f"{goat_weights.get('five_wkts', 4.0)} per five-for. "
            "Fielding counts for EVERYONE: "
            f"{goat_weights.get('catch', 0.15)} per catch, "
            f"{goat_weights.get('stumping', 0.3)} per stumping, "
            f"{goat_weights.get('run_out', 0.3)} per run out. A player "
            "below both career gates is a part-timer, scored on "
            "fielding only -- so Kohli's four career wickets are not a "
            "bowling record and Malinga's 88 runs are not a batting "
            "record, while Jadeja is paid for batting, bowling and "
            "catching alike. A squad ring can never outrank a decade "
            "of output. The "
            "official IPL Most Valuable Player is a voted prize "
            "Cricsheet does not carry, so it cannot count -- and this "
            "app's formula XI is not official hardware either. "
            + SOURCE_LINE)

# --------------------------------------------------------------------------
# Player Journey
# --------------------------------------------------------------------------
with tab_journey:
    st.subheader("Player journey")
    roster = sorted(players.values(), key=lambda p: p["name"])
    if not roster:
        st.info("No players in the record.")
    else:
        opts = _player_options(roster)
        # No default selection: an empty box with a placeholder, and an
        # honest prompt until a player is actually chosen.
        label = st.selectbox("Player", list(opts), key="player_ipl",
                             index=None, placeholder="Choose a player...")
        if not label:
            st.info("Pick a player to see his journey: every season he "
                    "took the field, the teams across eras, runs, "
                    "wickets and the whole career line.")
        elif label not in opts:
            st.info("That player vanished from the record.")
        else:
            match = [opts[label]]
            name = match[0]["name"]
            career = match[0]["career"]
            # The card replaces the old metric row: avatar, span, team,
            # and every published number (career, hardware, ladder, the
            # GOAT blend) as chips, so the tab opens with one object
            # instead of five disconnected numbers.
            st.markdown(player_card(match[0]), unsafe_allow_html=True)
            lines = match[0].get("seasons") or {}
            if not lines:
                st.info("No season lines for this player.")
            else:
                rows = []
                for y, ln in sorted(lines.items(), key=lambda kv: kv[0]):
                    bat, bowl = ln["batting"], ln["bowling"]
                    best = bowl.get("best") or [0, 0]
                    rows.append({
                        "Season": int(y), "Team": ln["team"],
                        "Inns": bat["inns"], "Runs": bat["runs"],
                        "HS": bat["hs"],
                        "NO": bat["not_outs"],
                        "50s": bat["fifties"], "100s": bat["hundreds"],
                        "SR": round(100.0 * bat["runs"] / bat["balls"], 1)
                              if bat["balls"] else "",
                        "Wkts": bowl["wickets"],
                        "Balls": bowl["balls"],
                        "Econ": round(6.0 * bowl["runs"] / bowl["balls"],
                                      2) if bowl["balls"] else "",
                        "Best": f"{best[0]}/{best[1]}"
                                if bowl["balls"] else "",
                        "Catches": ln.get("fielding", {}).get(
                            "catches", 0),
                    })
                frame = pd.DataFrame(rows)
                st.dataframe(frame, hide_index=True, width="stretch")
                st.line_chart(frame.set_index("Season")["Runs"])
                played = list(lines.items())
                teams_played = sorted({ln["team"] for _, ln in played})
                sentence = (
                    f"{name}: {len(played)} season"
                    f"{'s' if len(played) != 1 else ''} in the record "
                    f"({played[0][0]} to {played[-1][0]}), turning out "
                    f"for {' / '.join(teams_played)}.")
                if career["balls"]:
                    sentence += (
                        f" Career {career['runs']} runs at a "
                        f"{100.0 * career['runs'] / career['balls']:.1f}"
                        " strike rate.")
                if match[0].get("role"):
                    sentence += (f" Role by the published career gates: "
                                 f"{match[0]['role']}.")
                st.markdown(sentence)
                st.caption(
                    "Every season he took the field, per Cricsheet's "
                    "ball-by-ball record; a dash means he did not bat or "
                    "bowl that season. " + WEIGHTS_CAPTION
                )

# --------------------------------------------------------------------------
# Compare (two players, side by side)
# --------------------------------------------------------------------------
with tab_compare:
    st.subheader("Compare two players")
    roster_c = sorted(players.values(), key=lambda p: p["name"])
    if not roster_c:
        st.info("No players in the record.")
    else:
        opts = _player_options(roster_c)
        labels = list(opts)
        col_a, col_b = st.columns(2)
        with col_a:
            a_label = st.selectbox("Player A", labels, index=None,
                                   placeholder="Choose a player...",
                                   key="compare_a_ipl")
        with col_b:
            b_label = st.selectbox("Player B", labels, index=None,
                                   placeholder="Choose a player...",
                                   key="compare_b_ipl")
        if not a_label or not b_label:
            st.info("Pick two players to put their careers side by "
                    "side: season-by-season output, honours, ladder "
                    "and GOAT score.")
        elif a_label == b_label:
            st.info("Pick two DIFFERENT players to compare.")
        else:
            a, b = opts[a_label], opts[b_label]

            def metrics(p: dict) -> list:
                c = p["career"]
                seasons = p.get("seasons") or {}
                span = (f"{min(seasons)}-{max(seasons)}"
                        if seasons else "-")
                return [
                    ("Seasons played", len(seasons)),
                    ("Span", span),
                    ("Role", p.get("role", "-")),
                    ("Runs", c["runs"]),
                    ("Highest score", c["hs"]),
                    ("Batting strike rate",
                     (round(100.0 * c["runs"] / c["balls"], 1)
                      if c["balls"] else "-")),
                    ("Fifties / hundreds",
                     f"{c['fifties']} / {c['hundreds']}"),
                    ("Wickets", c["wickets"]),
                    ("Best bowling",
                     (f"{c['best'][0]}/{c['best'][1]}"
                      if c.get("best") else "-")),
                    ("Economy (career)",
                     c.get("econ") if c.get("econ") is not None else "-"),
                    ("Bowling average",
                     (c.get("bowl_avg")
                      if c.get("bowl_avg") is not None else "-")),
                    ("Four-fors / five-fors",
                     f"{c.get('four_wkts', 0)} / {c.get('five_wkts', 0)}"),
                    ("Catches / stumpings / run outs",
                     (f"{c.get('catches', 0)} / {c.get('stumpings', 0)}"
                      f" / {c.get('run_outs', 0)}")),
                    ("Player of the match awards", p["pom"]),
                    ("Titles", p["titles"]),
                    ("Runner-up finishes", p["runner_up"]),
                    ("Orange Caps", p["orange"]),
                    ("Purple Caps", p["purple"]),
                    ("Ladder (production)", p["ladder"]),
                    ("GOAT hardware", p.get("goat_hardware", "-")),
                    ("GOAT production", p.get("goat_production", "-")),
                    ("GOAT total", p.get("goat", "-")),
                ]

            ma, mb = dict(metrics(a)), dict(metrics(b))
            # Every cell a string: a column mixing ints with the span
            # ("2008-2026") would make pyarrow choke on st.dataframe.
            st.dataframe(_df(
                [{"Metric": k, a_label: str(ma[k]), b_label: str(mb[k])}
                 for k, _ in metrics(a)],
                ["Metric", a_label, b_label]),
                hide_index=True, width="stretch")

            def series(p: dict, part: str, field: str) -> tuple:
                lines = p.get("seasons") or {}
                ys = sorted(lines, key=int)
                return ([int(y) for y in ys],
                        [lines[y][part][field] for y in ys])

            for heading, part, field, ckey in (
                    ("Runs by season", "batting", "runs",
                     "compare_runs_ipl"),
                    ("Wickets by season", "bowling", "wickets",
                     "compare_wkts_ipl")):
                fig = go.Figure()
                for p, nm, color in ((a, a_label, "#2CA6A4"),
                                     (b, b_label, "#F5C542")):
                    xs, ys = series(p, part, field)
                    fig.add_trace(go.Scatter(
                        x=xs, y=ys, mode="lines+markers", name=nm,
                        line=dict(color=color, width=2)))
                fig.update_layout(
                    height=280, margin=dict(l=10, r=10, t=24, b=10),
                    xaxis=dict(dtick=1, title="Season"),
                    yaxis_title=heading.split()[0],
                    legend=dict(orientation="h", y=1.14))
                st.markdown(f"**{heading}**")
                st.plotly_chart(fig, width="stretch", key=ckey)
            shared = sorted(set(a.get("seasons") or {})
                            & set(b.get("seasons") or {}), key=int)
            st.caption(
                (("Both took the field in " + ", ".join(shared) + ". ")
                 if shared else
                 "No season in common in the record. ")
                + "One line per player, per-season totals as recorded "
                "(a season he missed is not a point -- the line spans "
                "it). "
                "GOAT total = hardware + production, the two auditable "
                "subtotals the GOAT tab ranks on. " + SOURCE_LINE
            )

# --------------------------------------------------------------------------
# Season Replay (TOY model)
# --------------------------------------------------------------------------
with tab_replay:
    st.subheader(f"IPL {year} season replay")
    sim = season.get("sim") or {}
    odds = sim.get("odds") or {}
    if not odds:
        st.info("No replay for this season (fewer than four teams in "
                "the league phase of the record).")
    else:
        st.markdown(f"**{sim.get('method')}**")
        ranked = sorted(odds.items(),
                        key=lambda kv: -kv[1]["title"])
        rows = [{"Team": t, "Title %": o["title"],
                 "Playoff %": o["playoff"]} for t, o in ranked]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     width="stretch")
        fig = go.Figure(go.Bar(
            y=[r["Team"] for r in rows],
            x=[r["Title %"] for r in rows], orientation="h",
            marker_color="#2CA6A4"))
        fig.update_layout(height=max(220, 28 * len(rows)),
                          margin=dict(l=10, r=10, t=10, b=10),
                          showlegend=False)
        st.plotly_chart(fig, width="stretch",
                        key=f"replay_bar_{year}_ipl")
        actual_top4 = [r["team"] for r in (season.get("points") or [])[:4]]
        fav = ranked[0][0]
        if champion == fav:
            verdict = "as champion"
        elif champion:
            verdict = "NOT as champion"
        else:
            verdict = "with the Final unrecorded"
        st.markdown(
            f"Actual league-phase top four: {', '.join(actual_top4)}. "
            + (f"Champions: **{champion}**."
               if champion else "No completed Final recorded."))
        st.caption(
            "TOY model, not a prediction product: team strength is the "
            "actual points-table NRR gap through a logistic curve, "
            f"every league match replayed "
            f"{sim.get('runs', 0)} times from seed {sim.get('seed')}, "
            "top four by simulated points (actual NRR tiebreak), then "
            "the real IPL knockout format (Qualifier 1, Eliminator, "
            "Qualifier 2, Final). No form, injuries or home advantage "
            f"enter. The replay's favorite finished {verdict}. "
            + SOURCE_LINE
        )

    st.markdown("#### Backtest: prior-season strengths vs reality")
    bt = seasons_doc.get("backtest")
    if not bt or not bt.get("seasons"):
        st.info(
            "This build of the data predates the replay backtest (or "
            "no season in it has a prior season to seed from). "
            "Data build stamp: "
            f"{seasons_doc.get('_generated_utc', 'unknown')}."
        )
    else:
        st.markdown(f"**{bt.get('method')}**")
        rows = [{"Season": y,
                 "Predicted top 4": ", ".join(r["predicted"]),
                 "Actually reached playoffs": ", ".join(r["actual"]),
                 "Overlap": f"{r['overlap']}/4"}
                for y, r in sorted(bt["seasons"].items(),
                                   key=lambda kv: int(kv[0]))]
        st.dataframe(_df(rows, ["Season", "Predicted top 4",
                                "Actually reached playoffs", "Overlap"]),
                     hide_index=True, width="stretch")
        summary = bt.get("summary") or {}
        b1, b2, b3 = st.columns(3)
        b1.metric("Seasons replayed", summary.get("seasons", 0))
        b2.metric("Average overlap",
                  f"{summary.get('avg_overlap', 0):.2f} / 4")
        b3.metric("Exact top fours", summary.get("exact", 0))
        st.caption(
            "The single-season replay above is seeded from the very "
            "table it replays; this backtest is not -- each season "
            "sees only the PRIOR season's final NRR. Read the average "
            "overlap: 4 would mean prior form always picks the "
            "playoffs, 0 never. Expansion seasons are the known blind "
            "spot -- no prior table contains the new franchises. "
            + SOURCE_LINE
        )
