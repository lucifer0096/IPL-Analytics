# The collector: `src/collector/cricsheet.py`

Stdlib-only (no pandas, no auth): downloads Cricsheet's official IPL zip
and computes every aggregate the app renders. Run it to (re)build the
committed fallbacks the deployed app reads.

```bash
python src/collector/cricsheet.py              # download + build
python src/collector/cricsheet.py --zip PATH   # build from a saved zip
python src/collector/cricsheet.py --runs 2000  # fewer replay sims (dev)
python src/collector/cricsheet.py --out DIR    # write elsewhere
```

## Inputs

| What | Where |
| --- | --- |
| Official zip | `https://cricsheet.org/downloads/ipl_json.zip` (ODC-By license, attribution required) |
| Local cache | `.cricsheet/ipl_json.zip` (gitignored; conditional GET via If-Modified-Since, so most refreshes are a 304) |
| Saved copy | `--zip PATH` skips the network entirely (CI, offline, the Kaggle mirror) |

## Outputs (committed)

| File | Contents |
| --- | --- |
| `data/ipl_seasons.json` | source, generated-utc stamp, meta counts, `team_aliases`, per season: champion, points table (league phase), fixtures, Orange/Purple Cap tables, formula XI + MVP, replay odds; all-time `h2h` |
| `data/ipl_players.json` | source, stamp, `ladder_weights` + `goat_weights`, registry-keyed players: per-season lines (team, batting, bowling), career totals, PoM, titles, runner-ups, Orange/Purple Caps, ladder score, GOAT score with `goat_hardware` + `goat_production` subtotals |

Both are committed because Streamlit Cloud cannot run the collector; the
app reads only these files and stamps their `_generated_utc` in the
sidebar.

## The pipeline inside `build()`

1. `load_matches` -- every zip member parsed to a normalized match:
   season year from the match DATE (labels are ambiguous: `2020/21` is
   the 2020 season), players keyed by `registry.people` ids, per-innings
   batting/bowling splits with the extras and dismissal-kind rules (see
   `docs/IPL.md`). A corrupt member is skipped, never fatal.
2. `_line_accum` -- grows one batting/bowling line per (player, season),
   shared by caps, journeys and careers.
3. `season_table` -- official points + NRR (league phase only, all-out
   side credited the full quota).
4. `season_fixtures` -- scoreline + result sentence per match
   (margin, super-over winner, or honest no-result).
5. `season_caps` / `season_xi` -- most runs / most wickets; the
   published formula XI and MVP (weights in `GOAT_WEIGHTS`).
6. `head_to_head` -- all-history pair records under rename-merged names.
7. `replay_odds` -- the labelled toy model: logistic on the NRR gap,
   5,000 league-match replays from seed 2026, real IPL knockout format.
8. `_career_of` -- per-player totals + the published ladder score.

## Determinism

The replay is the only stochastic piece and it is seeded (2026): the
same zip always produces byte-identical JSON, so a refresh diff shows
only new matches. Unit tests pin every rule on synthetic
Cricsheet-shaped matches (`src/collector/test_cricsheet.py`) -- no
network, no zip needed.
