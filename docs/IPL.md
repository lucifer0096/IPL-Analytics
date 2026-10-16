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

### GOAT rankings (hardware + role-gated production)

A separate config, `GOAT_ACCOLADES`, ranks players on two auditable
blocks that the tab shows as separate columns summing to the score:

```
GOAT = HARDWARE                  (what the official record says he won)
     +  6.0 x titles             (took the field for the champion)
     +  3.0 x finals lost        (took the field for the Final loser)
     +  6.0 x Orange Caps        (topped the season's run aggregate)
     +  6.0 x Purple Caps        (topped the season's wicket aggregate)
     +  2.5 x player-of-the-match awards (official, counted once)
     + PRODUCTION                (role-gated output + fielding, below)
     + 12.0 x (runs / 1000)          batters and all-rounders only
     + 16.0 x (wickets / 50)         bowlers and all-rounders only
     +  6.0 x max(0, 8.5 - economy)  bowlers, 20+ overs bowled
     +  3.0 x max(0, 28 - average)   bowlers, 50+ wickets
     +  2.0 per four-for  +  4.0 per five-for   (per innings bowled)
     +  0.15 x catches + 0.3 x stumpings + 0.3 x run outs  (everyone)
```

**Role gating.** Cricsheet carries no role column, so the career gates
ARE the published role: 1000+ career runs makes a batter, 30+ career
wickets makes a bowler, passing both makes an all-rounder, and failing
both makes a part-timer (scored on fielding only). Nobody is judged on
a discipline he never practised as a job: Kohli's four career wickets
at a 92.0 average are not a bowling record, Malinga's 88 runs are not
a batting record, and Jadeja is paid for batting, bowling and catching
alike. The economy bonus needs 20 overs bowled and the average bonus
needs 50 wickets, so one good spell (or one bad one) cannot decide a
career rate.

**The rating is a 0-100 index.** Raw points from the two blocks are
rescaled by one factor -- `GOAT_INDEX_MAX / the raw leader's score`,
the raw leader travelling in the payload as `goat_index.raw` -- so the
all-time leader sits exactly at 100 and both subtotals scale together,
keeping Hardware + Production equal to GOAT on screen.

**Calibration against published lists.** The weights were fixed
against three published all-time top tens (ipl.com Aug 2026,
CricketWinner Jul 2026, SportsboardIndia Feb 2026) by Spearman rank
correlation over their combined order: the role-gated, fielding-aware
config scores +0.65, up from +0.59 for the previous run/wicket-only
blend and +0.56 for the original hardware-led config. On this dataset
it ranks Kohli, Jadeja, Dhoni, Narine and Rohit on top, with Bhuvneshwar
Kumar, Malinga, Chahal and Bumrah all inside the top 15 (wicket-taking
careers are no longer buried under run-scorers) and hardware-heavy
candidates such as Ambati Rayudu outside the top 20.

Four honesty rules the rankings tab prints:

- The **official IPL Most Valuable Player** is a voted prize that
  Cricsheet does not carry, so it cannot count. Rather than invent it,
  the tab says it is missing.
- This app's **formula XI** is not official hardware, so it does not
  count either -- the rankings use only awards the record itself
  establishes.
- Player-of-the-match is counted **once** (in hardware), not twice.
- Fielding credit goes to the **first fielder listed** on a
  multi-fielder dismissal, "caught and bowled" is the bowler's own
  catch (the record lists no fielders for it), and a run out with no
  fielders listed (a direct hit) credits **nobody** -- the app does
  not guess.

### Player card (generated avatar)

Cricsheet carries ball-by-ball data, no photos, and real cricket
headshots are other people's copyright -- so the Journey tab draws a
trading-card style player card instead: the player's initials on a
gradient in his last team's brand colours (a stable hash-derived hue
for anything unlisted), his season span, last team and career role,
and every published number as chips: career (runs, wickets, catches,
stumpings, run outs, economy, average), hardware counts, ladder and
the GOAT blend with both subtotals spelled out on the card.

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

### Replay backtest (same model, honest cutoff)

- Same logistic model, but each season is seeded **only** from the
  PRIOR season's final NRR -- a franchise with no prior season starts at
  0.0, league average by construction. Nothing from the season being
  replayed enters its strengths (that is the difference from the
  single-season replay above).
- Each league match replayed 1,000 times from seed 2026; the predicted
  top four = highest simulated qualification rate; scored against the
  four teams that actually reached the playoffs (Q1 + Eliminator between
  them name all four in every recorded season).
- Result in the current record: 18 seasons (2009-2026), average
  overlap **2.11 of 4**, zero exact top fours, worst year 2022 at 0 --
  the GT/LSG expansion season no prior table could predict. The app
  prints the method verbatim and names that blind spot.

### Over phases (powerplay / middle / death)

- Phases by over faced, 0-based over index: powerplay = overs 1-6
  (index 0-5), middle = 7-15 (6-14), death = 16-20 (15-19).
- Per team per season: runs scored and legal balls faced in each phase
  (a wide adds runs but no ball); RPO = runs / (balls / 6). Whole
  season, playoffs included, team names as played that year; the
  all-time profile sums every season under merged franchise names.
- Nothing is modelled: these are the deliveries, bucketed.

### Milestones within reach

- Population: players who took the field in the LATEST season in the
  record. For each, the next round career number strictly above the
  total: runs to the next thousand up to 10,000, wickets to the next 50
  up to 300 (past the top rung = no row). Closest first, top ten.
- A **gap, not a projection**: no batting pace, games left or fitness is
  assumed, and the caption says so.

### Season finish (Franchise pages)

- Furthest stage reached that season: Champions (won the Final),
  Runner-up (played the Final), Lost Qualifier 2, Semi-final exit
  (2008-2010 format), Lost Eliminator (stage "Eliminator" or the old
  "Elimination Final"), Lost Qualifier 1, else League stage.
- League position comes from the league-phase-only table (as-played
  team name); the all-time record against each opponent sums the same
  rename-merged head-to-head rows the Head-to-Head tab shows. Super
  Over ties count under Tied, with the Super Over winner named on the
  Fixtures tab.

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

## Venue label merges (same ground)

Cricsheet writes every historical spelling of a ground; all-time venue
views merge them through `VENUE_ALIASES` (same policy as team renames:
explicit, auditable, same-ground only, no chains -- fixtures keep the
string each match was published under). The current record has 60
published venue strings; 25 alias entries collapse them to 35 grounds,
18 of which carried two or more spellings. Examples: "Wankhede Stadium"
= "Wankhede Stadium, Mumbai"; "Feroz Shah Kotla" was renamed **Arun
Jaitley Stadium**; "Sardar Patel Stadium, Motera" was rebuilt as
**Narendra Modi Stadium, Ahmedabad**; "Subrata Roy Sahara Stadium" =
Maharashtra Cricket Association Stadium (sponsor name); "OUTsurance
Oval" = SuperSport Park (2009 mixed both); "Zayed Cricket Stadium, Abu
Dhabi" = Sheikh Zayed Stadium; the four PCA Mohali spellings; and the
city-suffix variants of Eden Gardens, Chinnaswamy (punctuation too),
Chepauk, Rajiv Gandhi/Uppal, DY Patil, Sawai Mansingh, Brabourne,
HPCA Dharamsala, ACA-VDCA, Raipur and Mullanpur/New Chandigarh. Ties
and no-results count in a venue's match count but award nobody a win.

## What is honestly absent

- No vote-based awards: the IPL's official season MVP is not in the
  data, so the app's MVP is the formula MVP and says so. Orange/Purple
  Caps are computable aggregates, shown as such.
- Not live: Cricsheet republishes post-match; the app reads the
  committed build and stamps its generation time in the sidebar.
- 804 players keyed by Cricsheet registry ids; display names are the
  spellings Cricsheet records.
