# Deployment

The app deploys on **Streamlit Community Cloud** as its own app (own
URL, separate from any other repo's deploy).

## Setup

1. Push this repo to GitHub (e.g. `lucifer0096/IPL-Analytics`).
2. At <https://share.streamlit.io>, "Create app", pick the repo and
   branch `main`.
3. **Main file path: `app/app.py`** (this is the whole deploy config --
   everything else is read from the repo).
4. Python version: 3.12+ (the pins in `requirements.txt` declare
   `requires-python>=3.12`; CI runs 3.14, matching the Cloud runtime).
5. Deploy. The app needs no secrets, no network at runtime and no
   collector: it reads the committed `data/ipl_seasons.json` +
   `data/ipl_players.json` and stamps their generation time in the
   sidebar.

## Refreshing data on Cloud

Cloud cannot run the collector, so refreshes are pushed from a machine
that can (your laptop, or a scheduled GitHub Action later):

```bash
python src/collector/cricsheet.py
git add data/ipl_seasons.json data/ipl_players.json
git commit -m "Refresh IPL data"
git push        # Cloud redeploys from the new commit automatically
```

If both data files are missing or unreadable, the app shows an honest
error naming them and the rebuild command -- pinned by
`app/test_app_offline.py`.

## CI

`.github/workflows/ci.yml` runs on every push/PR: `ruff check`,
`compileall`, and the offline suite (collector unit tests + AppTest
render tests). No network needed anywhere in CI.
