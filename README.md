# HA Wine Cellar
Home Assistant add-on: a filterable wine cellar app (add / drink / remove bottles, check-ins, drink-soon, charts) backed by Postgres.

Features: barcode scanning, label photo reading, pictures, printable wine list, edit table, stats, CSV export/import, Grafana views. Racks with drag and drop are built but switched off (see `docs/`).

## Install (short version)
1. Install the **Postgres 17** add-on from `https://github.com/alexbelgium/hassio-addons` and set its `POSTGRES_PASSWORD`.
2. Create a database and login for the cellar with two SQL lines (see the full guide).
3. Add this repository (`https://github.com/niklasschwarz-sketch/ha-wine-cellar`) in Settings → Add-ons → Add-on store → ⋮ → Repositories, install **Wine Cellar**, set `db_password`, start it and turn on "Show in sidebar".

The full step by step guide, including the SQL and troubleshooting, is in [`wine_cellar/DOCS.md`](wine_cellar/DOCS.md) and in the add-on's Documentation tab.

Home Assistant can only add public repositories. While this repo is private, copy the `wine_cellar` folder into `/local_apps` on your Home Assistant instead.

## Updating
Bump `version` in `wine_cellar/config.yaml`, add a line to `wine_cellar/CHANGELOG.md` and push. Home Assistant shows the update after its next repository refresh.
