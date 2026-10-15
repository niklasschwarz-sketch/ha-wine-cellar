# Changelog

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
