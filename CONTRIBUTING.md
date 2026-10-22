# Contributing

Thanks for helping. Bug reports, ideas and translations are all welcome.

## Report a bug or suggest something
Open an issue and pick the template. For bugs, the add-on version, your device and the add-on log (Settings → Add-ons → Wine Cellar → Log) make it much faster to fix.

## Add or improve a language
A language is one JSON file. Copy `wine_cellar/app/lang/en.json`, translate the values and open a pull request. The guide is in [`wine_cellar/app/lang/README.md`](wine_cellar/app/lang/README.md). A partial translation is fine.

## Change the code
There is no build step.

- `wine_cellar/app/server.py`: the server (Python standard library only) and API
- `wine_cellar/app/static/index.html`: the whole page (HTML, CSS and JavaScript in one file, no framework)
- `wine_cellar/app/pairing.py`, `drink.py`, `mqtt.py`: food pairing, drink status, Home Assistant sensors

Run the tests before you open a pull request:

```
python3 test_api.py                     # starts the server on a temporary SQLite file, no network needed
pip install playwright && playwright install chromium
python3 test_ui.py                      # drives the page in headless Chromium
```

Guidelines:
- Keep it simple: no new runtime dependencies unless there is a strong reason.
- Anything that sends data off the device must be optional, off by default where it involves a third party, and described in `DOCS.md`.
- New text on screen goes into `lang/en.json`. `python3 scripts/i18n_scan.py` lists text missing from it.
- Add a line to `wine_cellar/CHANGELOG.md` and bump `version` in `wine_cellar/config.yaml` and `VERSION` in `server.py` for a release.
- `python3 scripts/make_screenshots.py` regenerates the screenshots in the README from a sample cellar.

By contributing you agree that your work is licensed under the Apache License 2.0, like the rest of the project.
