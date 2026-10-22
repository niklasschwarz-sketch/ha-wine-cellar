# Changelog

## 0.19.1
- **Label reading.** When Gemini refuses the key, the app now says so clearly (Google AI Studio keys start with `AIza`; other formats such as `AQ.` are not accepted) instead of silently showing garbled on-device text. The on-device reading is now an opt-in button.

## 0.19.0
- **Swedish.** Settings, *On this device*, *Language*: Automatic (follows your browser), English or Svenska. The whole app is translated, including the dinner pairing suggestions, notices and error messages. Wine names, producers and your own notes are never changed. The choice is kept per browser.
- **Add your own language.** A language is one JSON file in the add-on's `lang` folder, no coding needed. Copy `en.json`, translate the values and it appears in the list. Anything missing stays English, so a partial translation works. Guide: `wine_cellar/app/lang/README.md`.
- Not translated yet: the weekly reminder message sent to Home Assistant, the CSV column names (they follow CellarTracker) and a few screen-reader labels that contain a wine name.

## 0.18.3
- **Show or hide menu options.** In Settings, *Customise the menu*, each option now has a choice: *In the bar*, *In More* or *Hidden*. Hidden options are left out of the phone menu and the wide-screen side list completely. Settings itself can't be hidden, so you can always get back. *Reset to default* shows everything again.

## 0.18.2
- **Drink is now a pick list.** The Drink button opens *Drink now*: the wines past their window first, then those at their best this year, then everything else that is ready, each with its bottle count. Tap one to open a bottle and log it. A search box appears when the list is long. It no longer filters the main list.

## 0.18.1
- **Appearance and Customise the menu now live in Settings**, under *On this device*, instead of taking a place in the menu. The menu is shorter, and the left side of a wide screen no longer lists them.

## 0.18.0
- **Your own menu.** *Customise this menu* (under More on a phone, or the Menu icon on a wide screen) lists every option. Drag the handle, or use the arrows, to put them in the order you like, and tick **Bar** for up to three that should sit in the phone's bottom bar. The rest stay under More.
- **A wall tablet or any wide screen has no More button any more.** All options are listed down the left side, in your order, with an icon and a short name each.
- The choice is kept in the browser you set it in, so your phone and the wall tablet can differ. *Reset to default* puts everything back.
- Drink, Stats, Storage places, Edit table, Wine list, Dinner pairing, Bottle labels, Import / export, Cellar climate, Alerts and sensors, Appearance and Settings can all be moved or put in the bar.

## 0.17.0
- **New look, built on one set of design rules.** One colour, size, spacing and corner scale replaces dozens of one-off values, so every screen now matches. The accent is burgundy.
- **Dark mode.** The app follows your device by default. *More, Appearance* lets you choose Light or Dark, and a larger text size (*Large*, *Wall display*) for a kitchen or wall tablet. The choice is kept in that browser only.
- **Readable colours.** The status words (Ready, Hold, Past peak) and the grey text were too faint. They now meet the WCAG AA contrast level, and every status has an icon as well as a colour, so it does not rely on colour alone. The words are now the same everywhere: Ready, Hold, Past peak, No window.
- **Visible controls.** Search boxes, chips, drop-downs and stars have a clear outline, and every tap target is at least 44 px (48 px on touch screens).
- **Calmer wine cards.** The whole card opens the wine. The name and vintage lead, the bottle count is the biggest number, and the price is quiet. Region, grape and producer are plain text on the card; tap the card and use the links on the wine page to see all wines of one kind.
- **Cleaner top of the list.** The sentence that repeated the numbers is gone, and Sort moved into Filters. On a phone, *Coming up* and *Drink soon* now show under the Drink tab instead of above the list.
- **Phone sheets.** On a phone, dialogs slide up from the bottom. Filters open as a bottom sheet with a **Show N wines** button instead of pushing the list down. The Stats sheet no longer runs off the side of the screen.
- Navigation has icons, and Stats is no longer listed twice.
- Your data, settings and backups are unchanged.

## 0.16.0
- **Weekly drink reminder:** *More, Alerts and sensors*. Pick a day and hour and Wine Cellar sends one message a week through Home Assistant (a phone notification, or a message inside Home Assistant) listing the bottles in the last year of their window and those already past it. Nothing is sent in a week when nothing needs attention. There is a **Send a test message** button.
- **Cellar sensors in Home Assistant:** switch on *Show the cellar as sensors* and a Wine Cellar device appears with bottles, wines, ready to drink, drink this year, past peak, hold and estimated value (`sensor.wine_cellar_*`), for dashboards and automations. The names of the wines to drink soon or past peak are attached to those sensors. It needs the Mosquitto broker add-on and the MQTT integration; Wine Cellar finds the broker by itself. Switching it off removes the sensors again. After updating, restart the add-on once so Home Assistant can offer it the MQTT connection.
- **Restore from a full copy:** *Import and export, Restore from a full copy*. The full copy now includes your pictures and settings, and there is a smaller copy without pictures. Restoring replaces everything and asks first.
- **One rule for "ready to drink":** the wine list, the weekly reminder, the sensors and the database views for Grafana all use the same rule now, so they can no longer disagree. Database view `wc_v_cellar` has a new column `drink_status`.
- Hardening: the time of the weekly reminder follows the Home Assistant time zone.

## 0.15.1
- **Fix: Gemini label reading failed with "HTTP 404".** Google had retired the model the add-on asked for (gemini-2.5-flash is no longer offered to new keys). The add-on now picks the model itself: it asks Google which Flash models your key can use, takes the newest, and switches again when Google retires one. Leave the *Gemini model* option empty; if it still says gemini-2.5-flash from 0.15.0, the add-on finds a working model anyway.
- Clearer messages when Gemini says no, and the on-device fallback is labelled as such.

## 0.15.0
- **Read labels with Gemini (optional):** add your own free Gemini API key in the add-on's Configuration tab (*Gemini API key*) and photographing a label fills in producer, wine name, vintage, colour, style, country, region, appellation and grape. If you already have that wine and vintage, the form offers **Add a bottle to it**. It is off until you add a key. The label photo is sent to Google when it is on. If Gemini is unavailable, the on-device reader is used as before.
- The add-on options now have names and short explanations in the Configuration tab.

## 0.14.0
- **New look:** a light, quiet design. Wine cards have a tinted bottle picture on the left, the bottle count and prices in a clean number font, and a thin drinking-window line.
- **New navigation:** a bar along the bottom on a phone (Cellar, Drink, a round **+** to add a wine, Stats, More) and a slim bar down the left side on a landscape screen such as a wall tablet in Home Assistant. *Drink* shows the wines that are ready to drink now.
- **Place tabs:** your storage places are now underlined tabs above the list, with the bottle count on each. The cellar temperature and humidity are one small line beside them, and only turn red when something is out of range.
- The filter panel starts closed. Tap **Filters** to open it.
- Your data, settings and backups are unchanged.

## 0.13.2
- **Clearer wine list:** each card now starts with the wine name, with the year small after it, then the producer. Tap the picture or the name to open the wine page.
- **Open one** and **+1** moved to the wine page (bottom buttons), together with Edit and More… (change picture, print label, remove one, delete). The list cards are calmer without buttons.
- **Move…** sits next to *Stored in* on the wine page.

## 0.13.1
- **Move many bottles:** use the filters and search to show the wines you want (a colour, a region, a producer…), then tap **Move these…** next to the place chips (or *Storage places → Move many bottles…*). Choose where the bottles are now (no place, anywhere, or a named place) and where they go.

## 0.13.0
- **Storage places:** fridges, cellars, a bar. Switch on *Use several storage places* in *More → Settings*. Each bottle sits in one place, so a wine with several bottles can be spread over several places (4 in Cellar left, 2 in Fridge 1). The switch is off by default and nothing changes for a single shelf.
- Your existing shelf texts become places the first time you switch it on, each holding that wine's bottles.
- **More → Storage places:** add, rename, reorder and delete places. Each has a type (cellar, fridge, bar, other) and an optional temperature and humidity sensor from Home Assistant, shown live. Deleting a place asks where its bottles go.
- Place chips above the wine list filter by place; every wine card shows where its bottles are. The bottle info has *Stored in* with **Move…** and optional shelf notes ("shelf 3").
- Opening or removing a bottle of a wine that is kept in several places asks which place it comes from. Adding bottles preselects the place you used last.
- Stats gain *By place*. Export writes one CSV row per place (columns *Location* and *Bin*), and importing that file puts the bottles back. A wine listed on several rows now adds up instead of the last row winning.
- The unused rack screen (drag and drop racks) is removed. Its empty tables are dropped; the database view `wc_v_rack_contents` is replaced by `wc_v_place_contents`.

## 0.12.2
- The picture import hint points to the written zip format in the GitHub documentation (`PICTURE_ZIP_FORMAT.md`).

## 0.12.1
- Wording only: the picture import hint now points to the written zip format (`PICTURE_ZIP_FORMAT.md`). The separate picture finder tool moved to its own project, "Picture Finder for HA Wine Cellar".

## 0.12.0
- **Import pictures from a zip:** *More → Import / export → Import pictures from a zip*. A zip of pictures named by wine number (12.jpg), or by CellarTracker number (i123456.jpg), is attached to those wines, with an optional source link. Your own uploaded photos are never replaced.
- The full copy (JSON) now says which wines already have a picture.
- The zip format is documented in `PICTURE_ZIP_FORMAT.md` in the repository. Pictures can also be matched by CellarTracker number (`i123456.jpg`).

## 0.11.0
- **Settings (More → Settings):** pick your country and currency. The country suggests the currency, temperature unit and paper size, and each can still be changed. Also: Celsius or Fahrenheit, number and date format (follow the browser or the country), and A4 or US Letter for printing labels and the wine list.
- Money shows in your currency everywhere (stats, wine list, forms, edit table). If you change currency you can enter a rate to convert the prices already saved, or just switch the symbol.
- Changing the temperature unit converts the cellar climate limits and readings.
- The Systembolaget price check is shown only when the country is Sweden (or not set), with its own exchange rate to SEK in the settings.
- A new install with no wines opens Settings first, with a guess from the browser language. Existing cellars keep EUR until you change it.

## 0.10.0
- **Cellar climate menu:** *More → Cellar climate* lets you pick the temperature and humidity sensors from a list of what Home Assistant has, set the wanted lowest and highest values, choose whether the readings show at the top of the page, and switch on an alarm. The alarm sends one message to Home Assistant (or a phone notification service you name) when a reading leaves its range, and again only after 6 hours. The climate options are gone from the Configuration tab, since everything is set in the app. Sensors you set up in 0.9.0 keep working until you change them.
- **Simpler Configuration tab:** the database options are gone. The add-on always uses its built-in database file, which Home Assistant backups include. The Postgres option and the Grafana views are no longer offered.
- New add-on icon and logo

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
