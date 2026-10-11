# IPL Analytics

[![CI](https://github.com/lucifer0096/IPL-Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/lucifer0096/IPL-Analytics/actions/workflows/ci.yml)
[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://ipl-analytics.streamlit.app/)

**Live app: <https://ipl-analytics.streamlit.app/>**

Every IPL season from the inaugural 2008 campaign through the latest,
built on [Cricsheet](https://cricsheet.org)'s official ball-by-ball
record (1,243 matches, 19 seasons, 804 players -- and refreshed by
rerunning one script).

Six tabs, one rule: **every number is either a plain sum over the
official record or a clearly-labelled toy model.** Nothing is invented,
nothing is inferred beyond what the data carries, and when the record is
silent the UI says so.

| Tab | What it answers |
| --- | --- |
| Points Table | The official league-phase table: points, NRR with the all-out quota, league topper and season champion |
| Fixtures & Results | Every match of the season with the recorded scoreline, stage, venue and player of the match |
| Head-to-Head | All-history rivalries (franchise renames merged), most-played pairings |
| Records & Ladder | The season's formula XI + MVP, Orange/Purple Caps, the published-weights all-time ladder |
| GOAT Rankings | All-time rankings on **accolades only**: titles, finals lost, Orange/Purple Caps, official player-of-the-match awards |
| Player Journey | One player, every season: teams across eras, runs, wickets, the whole career line |
| Season Replay | A transparent toy model: replay every league match 5,000 times from seed, playoff and title odds |

## Why it looks like this

- **Official math, printed.** Points (win 2 / tie 1 each / no result 1
  each), NRR with a bowled-out side credited the full 20-over quota,
  bowler charges including wides and no-balls but not byes or leg-byes,
  wicket credit excluding run outs and retirements. Every formula shown
  in the UI is the formula the collector computes.
- **One published weights config.** The all-time ladder, the season XI
  and the MVP all run off `GOAT_WEIGHTS` in
  `src/collector/cricsheet.py`; the GOAT Rankings tab runs off
  `GOAT_ACCOLADES` (hardware only). Change a config, everything
  recomputes, the tests pin the schema.
- **The replay owns its label.** The Season Replay tab is a toy: team
  strength is the actual NRR gap through a logistic curve, no form,
  injuries or home advantage. It prints its method, its seed and its
  verdict -- "finished NOT as champion" when it was wrong.
- **Attribution everywhere.** Data: Cricsheet (cricsheet.org),
  Open Data Commons Attribution License. Every tab carries the credit,
  as the license requires.

## Quickstart

```bash
pip install -r requirements.txt -r requirements-dev.txt

# (re)build the committed data from Cricsheet's official zip
python src/collector/cricsheet.py            # downloads + builds
python src/collector/cricsheet.py --zip PATH # or point at a saved zip

# run the app
streamlit run app/app.py

# tests (offline: synthetic Cricsheet fixtures + AppTest renders)
pytest -q
ruff check app src
```

The collector is stdlib-only; the app needs the pins in
`requirements.txt`. Both data files are committed, so a fresh clone runs
the app without the collector.

## Refreshing the data

Cricsheet republishes the zip after matches are finalized. To refresh:

```bash
python src/collector/cricsheet.py   # conditional GET: only refetches when republished
git add data/ipl_seasons.json data/ipl_players.json
git commit -m "Refresh IPL data"
```

See `docs/IPL.md` for the full formula reference and `docs/DEPLOYMENT.md`
for Streamlit Cloud setup.

## Layout

```
app/app.py                    the Streamlit app (six tabs)
src/collector/cricsheet.py    collector + every computed aggregate
src/collector/test_cricsheet.py  synthetic-fixture tests for every rule
data/ipl_seasons.json         per-season tables, fixtures, caps, XI, replay
data/ipl_players.json         registry-keyed careers + ladder scores
docs/                         formula reference, collector, deployment
```
