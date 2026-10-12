# Data, formulas and honesty rules

## Source: Cricsheet

[Cricsheet](https://cricsheet.org) publishes the official IPL
ball-by-ball record as one JSON file per match (v1.2/1.3 format, docs at
<https://cricsheet.org/format/json/>), free to download:

- Zip: `https://cricsheet.org/downloads/ipl_json.zip` (~5 MB)
- License: **Open Data Commons Attribution (ODC-By)** -- free to use and
  redistribute with attribution. Every app caption and this repo credit
  "Cricsheet (cricsheet.org)" per that license.
- Refresh: Cricsheet republishes after matches finalize. The collector
  uses conditional GET (If-Modified-Since), so a daily run costs one
  304 most days.

Each match file carries:

- `info`: teams, season label, dates, venue/city, toss, player of the
  match, playoff stage, outcome (winner, margin in runs/wickets,
  `result: "tie"|"no result"`, super-over `eliminator`), and
  `registry.people` -- a name-to-stable-id map so a career can never
  split on a spelling.
- `innings[].overs[].deliveries[]`: batter, bowler, non-striker,
  itemized `extras` (wides / no-balls / byes / leg-byes), `runs`, and
  `wickets` with the dismissal kind.

### The season-label quirk (why the DATE wins)

Cricsheet's season labels are ambiguous: `2007/08` is the 2008 season
(played Apr-Jun 2008) but `2020/21` is the 2020 season (played Sep-Nov
2020, moved for COVID). An end-year rule would file 2020 under 2021 and
merge two seasons. The collector therefore takes **the calendar year the
match was played in** -- every IPL season sits inside one calendar year.
The label rule survives only as a fallback for a match with no dates.

### Not used: ESPN, Kaggle

- ESPN's free APIs carry no cricket (every endpoint probed: league
  lookups return not-found; ESPNcricinfo's API is Akamai-blocked from
  server IPs).
- The Kaggle mirror
  (<https://www.kaggle.com/datasets/vedantbhavsar43/ipl-2007-to-2026-complete-ball-by-ball-dataset>)
  is the same Cricsheet lineage behind an API key. Cricsheet is the
  primary because it needs **no auth**, which is what lets CI and
  Streamlit Cloud stay honest. Use the Kaggle copy as an offline mirror
  if you like; the collector also accepts a saved zip via `--zip`.

## Formulas (as computed and as printed)

### Points table (league phase only)

- Win 2, tie 1 each, no result 1 each, loss 0.
- **NRR** = (runs for / overs faced) − (runs conceded / overs
  bowled). A side bowled out is credited the **full 20-over quota** --
  the official IPL method, so a collapse costs the full rate.
- Legal balls exclude wides and no-balls; byes and leg-byes do not add
  to a ball faced.
- Qualifiers, Eliminators and Finals never touch the table. Season
  tables keep the team names as played that year; all-time views merge
  renames only (see below).

### Wicket credit and bowling charges

- A bowler is charged the batter's runs **plus wides and no-balls**
  (byes and leg-byes are not his).
- A bowler is credited a wicket unless the dismissal was a run out,
  retired hurt, retired out, obstructing the field, handled the ball,
  timed out or hit the ball twice.
- A batter is not out only for retired hurt.

### Caps, XI and MVP

- Orange/Purple Cap = most runs / most wickets over the whole season
  (playoffs included).
- Cricsheet carries **no player roles**, so the season XI is a published
  formula, not a claim about anyone's real role: the five highest
  run-scorers (min 4 innings), the five highest wicket-takers among
  players not already picked, the best remaining all-rounder (batted AND
  bowled that season, most combined impact), and the season MVP by that
  same impact.

### All-time ladder (published weights)

One config, `GOAT_WEIGHTS` in `src/collector/cricsheet.py`:

```
ladder = 3.0 x (runs / 1000)
       + 3.0 x (wickets / 50)
       + 0.5 x player-of-the-match awards
       + 1.0 x titles (seasons taking the field for the champion)
```

### GOAT rankings (hardware + production)

A separate config, `GOAT_ACCOLADES`, ranks players on two auditable
blocks that the tab shows as separate columns summing to the score:

```
GOAT = HARDWARE
     + 30.0 x titles        (took the field for the champion)
     + 12.0 x finals lost   (took the field for the Final loser)
     + 15.0 x Orange Caps   (topped the season's run aggregate)
     + 15.0 x Purple Caps   (topped the season's wicket aggregate)
     +  2.0 x player-of-the-match awards (official, counted once)
     + PRODUCTION           (the ladder's own rates)
     +  3.0 x (runs / 1000)
     +  3.0 x (wickets / 50)
```

Hardware leads (the production block reuses the ladder's small rates,
so a title still outruns a season of runs), but career output is never
worth zero: 9,346 runs should move a player, and the columns let a
reader check every point of the blend.

Three honesty rules the rankings tab prints:

- The **official IPL Most Valuable Player** is a voted prize that
  Cricsheet does not carry, so it cannot count. Rather than invent it,
  the tab says it is missing.
- This app's **formula XI** is not official hardware, so it does not
  count either -- the rankings use only awards the record itself
  establishes.
- Player-of-the-match is counted **once** (in hardware), not twice.

### Player card (generated avatar)

Cricsheet carries ball-by-ball data, no photos, and real cricket
headshots are other people's copyright -- so the Journey tab draws a
trading-card style player card instead: the player's initials on a
gradient in his last team's brand colours (a stable hash-derived hue
for anything unlisted), his season span and last team, and every
published number as chips: career, hardware counts, ladder and the
GOAT blend with both subtotals spelled out on the card.

### Season Replay (TOY model, labelled as such)

- Team strength = actual points-table NRR gap through a logistic curve:
  `P(A beats B) = 1 / (1 + e^(-2 x NRR_gap))`.
- Every **league** match replayed 5,000 times from seed 2026; top four
  by simulated points (actual NRR tiebreak); then the real IPL knockout
  (Qualifier 1 1v2, Eliminator 3v4, Qualifier 2, Final).
- It is a probability lesson on the official record, **not a
  prediction product**: no form, injuries or home advantage enter. The
  app prints the method, seed, and the verdict against what actually
  happened.

## Team renames (merged) vs successors (not merged)

Same franchise, new name -- merged in all-time views only:

| As played | Counts as |
| --- | --- |
| Royal Challengers Bangalore | Royal Challengers Bengaluru |
| Delhi Daredevils | Delhi Capitals |
| Kings XI Punjab | Punjab Kings |
| Rising Pune Supergiants | Rising Pune Supergiant |

Different franchises that merely wore the city -- **not** merged:
Deccan Chargers vs Sunrisers Hyderabad, Gujarat Lions vs Gujarat
Titans.

## What is honestly absent

- No vote-based awards: the IPL's official season MVP is not in the
  data, so the app's MVP is the formula MVP and says so. Orange/Purple
  Caps are computable aggregates, shown as such.
- Not live: Cricsheet republishes post-match; the app reads the
  committed build and stamps its generation time in the sidebar.
- 804 players keyed by Cricsheet registry ids; display names are the
  spellings Cricsheet records.
