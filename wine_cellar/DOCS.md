# Wine Cellar

## Install
1. Add this repository with one tap: [Add to my Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fniklasschwarz-sketch%2Fha-wine-cellar) (it opens your own Home Assistant and asks you to confirm). Or by hand: Settings → Add-ons → Add-on store → ⋮ → Repositories → `https://github.com/niklasschwarz-sketch/ha-wine-cellar`. Home Assistant can only read public repositories. For a private one, copy the `wine_cellar` folder into the `/local_apps` folder of your Home Assistant instead.
2. Install **Wine Cellar**. The first install builds the add-on on your own Home Assistant and downloads about 20 MB (the label reader), so it takes a few minutes.
3. Start it and turn on **Show in sidebar**. Open **Cellar**.
4. Tap **Add wine**, or **Import / export** and choose your CellarTracker CSV export (safe to repeat; matches on iWine).

That is all. There is nothing to configure: the add-on keeps your cellar in its own database file, so it needs no database server and touches nothing else on your system.

## No warranty
Wine Cellar is free software under the Apache License 2.0 and is provided "as is", without warranty of any kind. The author is not liable for any loss or damage, including lost data. Keep a Home Assistant backup and export a CSV from **Import / export** now and then. Prices, scores, pairings and drinking windows are suggestions, not advice. The barcode labels and scanner are a convenience and may misread.

## Privacy: what goes over the internet
- **Pictures:** for each wine in stock the add-on asks Open Food Facts (a free, open database) for a picture, using the producer, wine name and barcode. Switch it off with the option `auto_images`.
- **Systembolaget prices:** off by default. If you turn on `systembolaget_prices` it downloads a public price list once a week. Your own wines are never sent anywhere.
- **Label reading** happens in your browser. The photo stays in your home.
- Pairing, tags, reviews, labels and the climate strip run entirely inside Home Assistant.
- The first install downloads the label reader (about 20 MB) from a public software CDN while the add-on is built.

## Uninstalling
Uninstall the add-on in Settings → Add-ons and tick the option to delete its data. That removes the database file. Nothing is left in Home Assistant itself. Remove the repository entry and any `/local_apps/wine_cellar` folder by hand, and delete old backups if you do not want a copy of the cellar to remain.

## Where your data is, and backups
Your cellar is one file inside the add-on (`/data/winecellar.db`). Home Assistant backups include it automatically. During a backup the add-on is stopped for a moment so the file is copied cleanly. You can also download a CSV (opens in Excel and Sheets) or a full JSON copy from **Import / export** at any time.

## Adding wines
When you type a producer that is already in your cellar, the form fills in country, region, grape, colour and style, and suggests a drinking window from your earlier vintages (it is only a suggestion; change it freely).

## Label photo
Scan, then "Photograph the label", or use "Read the label" in the picture box. The text is read on your phone or computer; the photo never leaves your home. It finds the producer (if you already have it), vintage, appellation, grape and colour, and lists other lines you can tap into a field. Reading curved labels is not perfect, so always check the fields. The reader is downloaded when the add-on is built; if it is missing, the photo is only saved as the picture. On iPhone and Mac you can also tap a field and choose Scan Text.

## Pictures
For many wines at once, use **More → Import / export → Import pictures from a zip** (files named by wine number, for example `12.jpg`). The zip format is described in `PICTURE_ZIP_FORMAT.md` in the ha-wine-cellar documentation on GitHub. Only add pictures you have the right to use.

The add-on looks up a picture for each wine in stock on Open Food Facts (free, open database), about one wine every 7 seconds. Only close matches are used, so many wines will have none: tap the bottle on a card to add your own photo. Turn the automatic lookup off with the option `auto_images`.

## Scanning
Use **Scan bottle**. A USB/Bluetooth scanner types the number into the box. The camera needs Home Assistant over HTTPS and a browser that supports barcode reading.

## Wine list
**Wine list** shows a menu-style list of your current selection (filters apply). Print it from there.

## Settings: country, currency and units
*More → Settings* sets your country, currency, temperature unit (°C or °F), number and date format, and paper size (A4 or US Letter) for printing. Picking a country suggests the rest. If you switch currency you may enter a rate to convert the prices already saved (for example 1 EUR = 1.08 USD), or leave it empty to keep the numbers and change only the symbol. The Systembolaget price check appears only for Sweden.

## Systembolaget prices
Once a week the add-on downloads the public mirror of Systembolaget's assortment (github.com/AlexGustafsson/systembolaget-api-data, about 30 MB) and keeps only the wines in a small table. Each of your wines is matched strictly on producer, wine name, vintage and bottle size. Many wines (especially small French producers) are not sold there and will show no price. Prices are in kr; `eur_sek_rate` converts them for "Use as current value". Turn it off with `systembolaget_prices`.

## Food and wine pairing
Open a bottle: **Goes well with** lists the dishes that suit it best (score 80 and up is excellent, 68 and up good). **More → Dinner pairing** works the other way round: search or pick a dish and see your best bottles for it, with drink-soon bottles lifted a little. The suggestions come from rules built into the add-on (grape, region, weight, acidity, tannin, sweetness, age and classic matches), so they work offline and are a guide, not a promise. Sauces and spices change a dish, and a wine with no grape or region filled in is judged on colour and style only.

## Cellar climate (temperature and humidity)
Open **More → Cellar climate**. Pick a temperature sensor and a humidity sensor from the list of sensors Home Assistant knows (or choose "Other sensor" and type its name, such as `sensor.cellar_temperature`). Set the lowest and highest temperature and humidity you want. The page then shows both readings at the top, marked orange when outside their range, and tapping one shows the last 24 hours. Untick **Show the readings at the top of the page** to hide them while keeping the alarm.

**Alarm:** tick *Send me an alarm in Home Assistant* and the add-on checks every 5 minutes. When a reading leaves its range it sends one message, and again only after 6 hours if it is still out of range. By default the message appears as a notification inside Home Assistant (the bell in the sidebar). To get it on your phone, enter a notification service such as `notify.mobile_app_my_phone` (find the name under Developer tools → Actions). **Send a test message** checks it works. The add-on only reads the two sensors you pick, through Home Assistant's own connection, and needs no password.

## Tags and occasions
On a bottle's page, **Tags and occasions** lets you mark it as a gift you received, a gift you gave, or one kept for a special occasion. Add an occasion (birthday, anniversary, wedding and so on), a person, a date and a note. Tick **Remind me every year** for birthdays and anniversaries: they show under **Coming up** for 45 days before. The Filters list has a **Tags** group once you have used a tag.

## Bottle labels
**More → Bottle labels** shows a sheet of barcode labels (Code 128, text such as `WC12`) for your current selection or the whole cellar, one per bottle or one per wine, and **Print labels** opens the print dialog (3 labels across; use sticker paper). A single wine's page has **Print label**. Choose **Scan** and read a label with a USB or Bluetooth scanner (click the box first), or type the code, or use the camera if your browser can read barcodes: the wine's page opens, with **Open one** ready. Labels keep working after backups and restores because they carry the wine's number in this cellar. If you import the same cellar into a fresh install the numbers can change, so reprint then.

## Scores and reviews
Each wine page has **Scores and reviews**: add a critic or community score (out of 100, 20, 10 or 5) with the source, date, a few words and a link. The average of your critic scores is shown at the top, with the CellarTracker "members like it" share from your import. CellarTracker, Vivino and the critics do not let other apps read their scores, so you enter the ones you care about; the **CellarTracker** button opens the wine's page there for the community and critic notes.

## Edit table
**Storage places.** *More → Settings → Use several storage places* turns on fridges, cellars and a bar. Add them under *More → Storage places* (for example Fridge 1, Fridge 2, Cellar left, Cellar right, Bar, Bar fridge), each with a type and, if you like, its own Home Assistant temperature and humidity sensor. Each bottle is in exactly one place, so a wine with several bottles can be split over places. The first time you switch it on, every shelf text you already have becomes a place holding that wine's bottles. The chips above the list filter by place, a wine's bottle info shows where it is and has **Move…**, and opening a bottle asks which place it comes from when the wine is in more than one. *Shelf notes* adds a short note per place such as "shelf 3". The CSV export has one row per place (columns Location and Bin) and importing it restores them. Turning the switch off keeps your places and goes back to the single shelf text.

**Edit table** opens the whole cellar as a spreadsheet. Type in any cell, or use the + and − next to the bottle count. Enter and the up/down arrows move between rows, Tab moves right and adds a row after the last cell. You can paste rows straight from Excel or Google Sheets (column order: vintage, producer, wine, colour, style, country, region, appellation, grape, bottles, paid, value, drink from, drink to, shelf). Ctrl/Cmd+D copies the cell above.
Tick rows to add or remove a bottle on all of them, duplicate them, or delete them. Changed cells are highlighted. Nothing is saved until you press Save (or Ctrl/Cmd+S); Discard throws the changes away. Bottle changes show up in the activity list as added or removed.

## Stats
**Stats** shows bottles, value or money paid by region, country, vintage, style, grape and producer, when to drink, price bands, biggest gains and losses, and bottles opened per month. It can cover the whole cellar or only your current filters.

## Export and import
**Import / export** downloads a CSV (opens in Excel, Numbers, Google Sheets) or a full JSON copy with history and storage places. The CSV uses CellarTracker's column names, so it can be imported again, here or in CellarTracker. Importing again updates wines and adds new ones; it deletes nothing and restores the places from the Location and Bin columns when storage places are on. For a complete backup, include this add-on in your Home Assistant backups.
