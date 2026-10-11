# Deployment

The app deploys on **Streamlit Community Cloud** as its own app:

| | |
| --- | --- |
| Live app | <https://ipl-analytics.streamlit.app/> |
| Repo | `lucifer0096/IPL-Analytics` (public, branch `main`) |
| Main file path | `app/app.py` |
| Python | 3.12+ (CI runs 3.14, matching the Cloud runtime; the pins in `requirements.txt` declare `requires-python>=3.12`) |

The whole deploy config is the main file path -- everything else is
read from the repo. The app needs no secrets, no network at runtime and
no collector: it reads the committed `data/ipl_seasons.json` +
`data/ipl_players.json` and stamps their generation time in the
sidebar. Pushing to `main` redeploys automatically (CI must stay green:
`ruff`, `compileall`, and the offline suite).

If the live URL redirects viewers to a Streamlit login, the app's
access setting is not public yet: in the Cloud dashboard open
"Manage app" -> settings and allow anyone with the link to view.

## (Re)deploying from scratch

1. At <https://share.streamlit.io>, "Create app", pick
   `lucifer0096/IPL-Analytics` and branch `main`.
2. Set **Main file path: `app/app.py`** and deploy.

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
