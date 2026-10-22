# Adding a language to Wine Cellar

Each language is one JSON file in this folder, named with its language code (`sv.json`, `de.json`, `fr.json`, `pt-BR.json`).
There is no build step: drop the file in, restart the add-on, and the language shows up in **Settings → On this device → Language**.
The page also picks it automatically when your browser's language matches.

## How to add one
1. Copy `en.json` to your code, for example `de.json`.
2. Set `"_name"` to the language's own name ("Deutsch").
3. Translate the **values** in `"strings"`. Leave the keys (the English text) exactly as they are.
4. Reload the page. Anything you leave out, or leave empty, stays English, so a partial translation works.

## Rules
- Keep placeholders such as `{0}` and `{1}`. They stand for numbers the app fills in, and may move in your sentence:
  `"Showing {0} of {1} wines": "Visar {0} av {1} viner"`.
- Do not translate the keys, and do not add keys that are not in `en.json`; they are never used.
- A word on its own (for example `"bottles"`) is translated on its own, so pick the form that fits where it is used.
- Keep it short: buttons and tabs have little room, especially on a phone.
- Wine names, producers, places and notes you type are never translated.
- Save the file as UTF-8.

## Checking your work
`python3 test_api.py` checks every language file: valid JSON, only known keys, placeholders kept.
`python3 scripts/i18n_scan.py` lists any text the app shows that is missing from `en.json`; run it after changing the page.

## What is not translated yet
The CSV export keeps CellarTracker's English column names, and the weekly reminder message sent to Home Assistant is English.
