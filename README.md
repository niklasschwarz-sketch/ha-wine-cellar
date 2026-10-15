# HA Wine Cellar
Home Assistant add-on: a filterable wine cellar app (add / drink / remove bottles, check-ins, drink-soon, charts) built-in database (Postgres optional).

Features: barcode scanning, label photo reading, pictures (paste or drop images), food and wine pairing, cellar temperature and humidity from Home Assistant, gift and occasion tags, printable bottle barcode labels, scores and reviews, printable wine list, printable wine list, edit table, stats, CSV export/import, Grafana views. Racks with drag and drop are built but switched off (see `docs/`).

## Install
1. Add this repository (`https://github.com/niklasschwarz-sketch/ha-wine-cellar`) in Settings → Add-ons → Add-on store → ⋮ → Repositories.
2. Install **Wine Cellar**, start it and turn on "Show in sidebar".

No database setup is needed: the cellar is kept in a file inside the add-on and is part of Home Assistant backups. Postgres is optional (for Grafana); see [`wine_cellar/DOCS.md`](wine_cellar/DOCS.md).

Home Assistant can only add public repositories. While this repo is private, copy the `wine_cellar` folder into `/local_apps` on your Home Assistant instead.

Coming from 0.6.x on Postgres? See [`docs/migrate-from-postgres.md`](docs/migrate-from-postgres.md) for a step by step move to the built-in database, including cleaning up Postgres and Grafana.

## Development
`python3 test_api.py` starts the server on a temporary SQLite file and runs the API tests. No Postgres or network needed. `python3 test_ui.py` drives the page in headless Chromium (needs `pip install playwright`).

## Updating
Bump `version` in `wine_cellar/config.yaml`, add a line to `wine_cellar/CHANGELOG.md` and push. Home Assistant shows the update after its next repository refresh.
