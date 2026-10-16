# HA Wine Cellar
Home Assistant add-on: a filterable wine cellar app (add / drink / remove bottles, check-ins, drink-soon, charts) built-in database.

Features: barcode scanning, label photo reading, pictures (paste or drop images), food and wine pairing, cellar temperature and humidity from Home Assistant, gift and occasion tags, printable bottle barcode labels, scores and reviews, printable wine list, edit table, stats, CSV export/import.

## Install
[![Add this repository to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fniklasschwarz-sketch%2Fha-wine-cellar)

**Quickest way:** tap the button above (it opens your own Home Assistant and asks you to confirm adding the repository). Then go to step 2. Or add it by hand:

1. Add this repository (`https://github.com/niklasschwarz-sketch/ha-wine-cellar`) in Settings → Add-ons → Add-on store → ⋮ → Repositories.
2. Install **Wine Cellar**, start it and turn on "Show in sidebar".

No database setup is needed: the cellar is kept in a file inside the add-on and is part of Home Assistant backups. See [`wine_cellar/DOCS.md`](wine_cellar/DOCS.md) for the full guide.

Home Assistant can only add public repositories. While this repo is private, copy the `wine_cellar` folder into `/local_apps` on your Home Assistant instead.

## For testers
**What you need:** Home Assistant OS or Supervised (add-ons are not available on Container or Core installs), on a 64-bit Intel/AMD or ARM machine. About 100 MB of disk. The first install builds the add-on on your own system and downloads about 20 MB, so allow a few minutes.

**Install:** tap the "Add repository" button above (or add the repository by hand), install **Wine Cellar**, start it and turn on "Show in sidebar". Nothing needs configuring. Import a CellarTracker CSV (**More → Import / export**) or add a few wines by hand.

**What to try:** add and drink bottles, scan or type a barcode, paste a picture, open a bottle for "Goes well with", use **More → Dinner pairing**, tag a bottle as a gift with a birthday date, print a label from **More → Bottle labels** and scan it back, and (if you have cellar temperature or humidity sensors) pick them under **More → Cellar climate**.

**What leaves your home:** only two things, both explained in [`wine_cellar/DOCS.md`](wine_cellar/DOCS.md). The add-on looks up bottle pictures on Open Food Facts (switch off with `auto_images`), and, only if you turn it on, Systembolaget prices. Label photos are read inside your own browser.

**Uninstall cleanly:** Settings → Add-ons → Wine Cellar → Uninstall, and tick the option to delete the add-on's data. That removes the add-on, its image and its database file. It created nothing else in Home Assistant: no helpers, entities or automations, and it changed no settings. Things you may still want to remove by hand: the repository entry (Add-on store → ⋮ → Repositories), the `wine_cellar` folder in `/local_apps` if you installed that way, and any Home Assistant backup you made while it was installed (backups include the add-on's data). 

**Feedback:** tell the developer what you tried, what you expected and what happened, and include the add-on's Log tab text if something failed. Please export a CSV from **Import / export** before an update, to be safe.

## Licences and credits
See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the open-source components, the data sources and the non-affiliation note.

## Development
`python3 test_api.py` starts the server on a temporary SQLite file and runs the API tests. No Postgres or network needed. `python3 test_ui.py` drives the page in headless Chromium (needs `pip install playwright`).

## Updating
Bump `version` in `wine_cellar/config.yaml`, add a line to `wine_cellar/CHANGELOG.md` and push. Home Assistant shows the update after its next repository refresh.
