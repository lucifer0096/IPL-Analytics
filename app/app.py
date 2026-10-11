"""IPL Analytics -- every IPL season from the inaugural 2008 campaign
through the latest, built on Cricsheet's official ball-by-ball files.

Six in-page tabs, one honest rule: every number is a plain sum over the
official record (points tables, NRR with the all-out quota, Orange/Purple
Cap totals, head-to-head, player careers) or a clearly-labelled TOY model
(the season replay). Nothing is inferred beyond what the data carries,
and empty states say so.

Data: Cricsheet (cricsheet.org), Open Data Commons Attribution License.
The committed data/ipl_seasons.json + data/ipl_players.json are the
deploy's only source (Streamlit Cloud cannot run the collector); rebuild
them locally with `python src/collector/cricsheet.py`.
"""

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
div[data-testid="stMetric"] {
  background: var(--ipl-card); border: 1px solid var(--ipl-border);
  border-radius: 14px; padding: 12px 16px;
}
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
.ipl-chip--mvp {
  border-color: var(--ipl-gold);
  background: color-mix(in srgb, var(--ipl-gold) 16%, transparent);
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_data
def load_docs() -> dict:
    """The two committed payloads, parsed once per session. A missing or
    unreadable file is an honest empty state in the UI, never a crash."""
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


st.title("IPL Analytics")
docs = load_docs()
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

tab_table, tab_fix, tab_h2h, tab_records, tab_goat, tab_journey, \
    tab_replay = st.tabs(["Points Table", "Fixtures & Results",
                          "Head-to-Head", "Records & Ladder",
                          "GOAT Rankings", "Player Journey",
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
                "GOAT Rankings tab ranks official accolades only.")

# --------------------------------------------------------------------------
# GOAT Rankings (accolades)
# --------------------------------------------------------------------------
with tab_goat:
    st.subheader("GOAT rankings: hardware only")
    goat_weights = players_doc.get("goat_weights") or {}
    ranked = sorted((p for p in players.values()
                     if p.get("goat", 0) > 0),
                    key=lambda p: -p["goat"])[:25]
    if not ranked:
        st.info("No player in the record has ever won anything.")
    else:
        rows = []
        for i, p in enumerate(ranked, start=1):
            span = (f"{min(p['seasons'])}-{max(p['seasons'])}"
                    if p.get("seasons") else "")
            rows.append({
                "#": i, "Player": p["name"], "GOAT": p["goat"],
                "Titles": p["titles"], "Runner-up": p["runner_up"],
                "Orange": p["orange"], "Purple": p["purple"],
                "PoM": p["pom"], "Seasons": span})
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     width="stretch")
        top10 = rows[:10]
        fig = go.Figure(go.Bar(
            y=[r["Player"] for r in top10],
            x=[r["GOAT"] for r in top10], orientation="h",
            marker_color="#F5C542"))
        fig.update_layout(height=max(240, 30 * len(top10)),
                          margin=dict(l=10, r=10, t=10, b=10),
                          showlegend=False)
        st.plotly_chart(fig, width="stretch", key="goat_bar_ipl")
        st.caption(
            "HARDWARE only -- what the official record says a player "
            "won, never how many runs it took: "
            f"{goat_weights.get('title', 30.0)} per title (took the "
            f"field for the champion), "
            f"{goat_weights.get('runner_up', 12.0)} per Final lost, "
            f"{goat_weights.get('orange_cap', 15.0)} per Orange Cap "
            "(topped the season's runs), "
            f"{goat_weights.get('purple_cap', 15.0)} per Purple Cap "
            "(topped the season's wickets), "
            f"{goat_weights.get('player_of_match', 2.0)} per official "
            "player-of-the-match award. The official IPL Most Valuable "
            "Player is a voted prize Cricsheet does not carry, so it "
            "cannot count -- and this app's formula XI is not official "
            "hardware either, so it does not count here. " + SOURCE_LINE)

# --------------------------------------------------------------------------
# Player Journey
# --------------------------------------------------------------------------
with tab_journey:
    st.subheader("Player journey")
    roster = sorted(players.values(), key=lambda p: p["name"])
    if not roster:
        st.info("No players in the record.")
    else:
        options = [p["name"] for p in roster]
        name = st.selectbox("Player", options, key="player_ipl")
        match = [p for p in roster if p["name"] == name]
        if not match:
            st.info("That player vanished from the record.")
        else:
            career = match[0]["career"]
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Runs", career["runs"])
            k2.metric("Wickets", career["wickets"])
            k3.metric("Player of the match", match[0]["pom"])
            k4.metric("Titles", match[0]["titles"])
            k5.metric("Ladder", match[0]["ladder"])
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
                    })
                frame = pd.DataFrame(rows)
                st.dataframe(frame, hide_index=True, width="stretch")
                st.line_chart(frame.set_index("Season")["Runs"])
                played = list(lines.items())
                teams_played = sorted({ln["team"] for _, ln in played})
                sentence = (
                    f"{name}: {len(played)} seasons in the record "
                    f"({played[0][0]} to {played[-1][0]}), turning out "
                    f"for {' / '.join(teams_played)}.")
                if career["balls"]:
                    sentence += (
                        f" Career {career['runs']} runs at a "
                        f"{100.0 * career['runs'] / career['balls']:.1f}"
                        " strike rate.")
                st.markdown(sentence)
                st.caption(
                    "Every season he took the field, per Cricsheet's "
                    "ball-by-ball record; a dash means he did not bat or "
                    "bowl that season. " + WEIGHTS_CAPTION
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
