# Changelog

## 0.9.0
- **Cellar climate:** the add-on reads your temperature and humidity sensors from Home Assistant and shows them at the top of the page, marked orange when outside the range you want. Tap one for the last 24 hours. Set `climate_temp_entity` and `climate_humidity_entity` (for example `sensor.cellar_temperature`) and the wanted ranges in the Configuration tab. Nothing is shown until you set a sensor.
- **Tags and occasions:** mark a bottle as a gift you received, a gift you gave, or kept for a special occasion, with an optional occasion (birthday, anniversary, wedding, Christmas, graduation, dinner), person, date and note. Dates can repeat every year; birthdays and anniversaries in the next 45 days appear under **Coming up**. You can also filter the cellar by tag.
- **Bottle labels:** **More → Bottle labels** prints Code 128 barcode labels, one per bottle or one per wine. **Scan** reads them (USB scanner, typing, or the phone camera where the browser supports it) and opens the wine. Each wine page also has **Print label**.
- **Scores and reviews:** each wine keeps your own list of critic and community scores and reviews (any scale: 100, 20, 10 or 5 points), with a summary average, plus a link to the wine's CellarTracker page. The CellarTracker "members like it" share from your import is shown there too. CellarTracker and the critics do not offer their scores to other apps, so these are entered by hand.
- Tags and reviews are part of the JSON backup

## 0.8.0
- Food and wine pairing: every bottle's page has a **Goes well with** list (best dishes, with a score and the reason), worked out on your own system from grape, region, colour, sweetness, age and style. Nothing is sent over the internet.
- **More → Dinner pairing**: pick or search a dish (about 40, with Swedish words such as lamm, torsk, ost) and see which bottles in your cellar suit it best. Bottles that should be drunk soon rank a little higher, bottles not ready yet a little lower.
- Bottle pages link to Vivino and Wine-Searcher to look up the wine and its price

## 0.7.1
- Pictures can be pasted: copy an image anywhere (a web page, a screenshot, a photo app) and press Ctrl+V (⌘+V on a Mac) in the picture dialog or the add/edit form, or use the new **Paste image** button
- Image files can also be dragged onto the picture dialog or the form
- Browser tests added (`test_ui.py`)

## 0.7.0
- No database to set up: a new install keeps your cellar in its own file inside the add-on, which Home Assistant backups include. Install, start, open.
- Postgres is now optional (`db_type: postgres`), for example for Grafana. An existing install that has a database password keeps using Postgres when it updates.
- The add-on is stopped briefly during Home Assistant backups so the data file is copied cleanly
- The setup guide is rewritten around the simple install, with Postgres as an optional section
- Test script `test_api.py` added to the repository
## 0.6.1
- Setup guide rewritten for a fresh Home Assistant: installing Postgres 17, creating the database and login with two SQL lines, installing and configuring this add-on, and what to do if it does not start
- The add-on now stops with a clear message in the log when `db_password` is empty

## 0.6.0
- New wine-cellar look: dark cellar colours, serif headings, a brass accent, and a "drinking window" bar on every card
- Wines come first: a slim summary strip, then drink-soon, then the list; the header has Add wine, Scan and a More menu
- Filters moved to a sidebar with short, collapsible lists and counts (a Filters button on phones)
- Cards show more: window bar, region, grapes, price and value, location
- Smarter add: pick a producer you already have and the country, region, grape, colour, style and drinking window are filled in from your cellar
- Label photo: photograph a label (Scan, or the picture box) and the producer, vintage, appellation and grape are read on the device and filled in. The reader (Tesseract) is downloaded when the add-on is built (about 20 MB); if that fails the photo is still saved and the add-on works as before

## 0.5.0
- Edit table: a spreadsheet view of the whole cellar to add, change and remove many wines and bottles at once
- Type in cells, use the + / − steppers, paste rows from Excel or Sheets, copy a cell down with Ctrl/Cmd+D, select rows to add or remove bottles, duplicate or delete them
- Changed cells are highlighted and nothing is saved until you press Save (or Ctrl/Cmd+S); problems are shown per row

## 0.4.0
- Racks: the backend and screen are built but hidden for now (button switched off)
- Stats page: region, country, vintage, style, grape, producer, drink-by years, price bands, gains and losses, bottles opened per month
- Import / export: CSV download (re-importable, includes rack positions as text) and a full JSON copy
- Import now also reads Location, Notes and EAN from our own export
- Read-only database views and a Grafana dashboard file
- New installs have Systembolaget prices off by default

## 0.3.2
- Diagnostic: /api/sb/debug/<wine id> shows why a wine did or did not match Systembolaget

## 0.3.1
- Fix: Systembolaget list with repeated product numbers no longer stops the update
- Clearer errors in the log when a download fails

## 0.3.0
- Systembolaget prices: the add-on downloads Systembolaget's published wine list weekly and matches your wines strictly (producer, wine name, vintage, bottle size)
- See price paid against Systembolaget's price per wine, use it as the current value, and a "Paid vs worth now" card
- Wine list can show Systembolaget prices in kr
- Options: systembolaget_prices, eur_sek_rate

## 0.2.1
- Click a wine name for the bottle info (details and history)
- Click producer, region, appellation, grape or year to show all matching bottles

## 0.2.0
- Pictures: found online automatically (Open Food Facts), or add your own photo
- Scan bottle: scanner, typed EAN or camera; opens a form for year, bottles, price paid, drinking window and picture
- Wine list: restaurant-style, printable, follows your filters
- Fix: pop-ups with footer buttons now open

## 0.1.0
- First release
