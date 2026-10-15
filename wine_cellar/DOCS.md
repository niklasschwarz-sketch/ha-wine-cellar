# Wine Cellar

1. In the Postgres add-on configuration create a database and login (you choose the password):
   `databases: [winecellar]`, `logins: [{username: winecellar, password: <yours>}]`, `rights: [{username: winecellar, database: winecellar}]`. Restart Postgres.
2. Enter the same values in this add-on's Configuration tab.
3. Start the add-on, enable "Show in sidebar", open **Cellar**.
4. Tap **Import / export** and choose your CellarTracker CSV export (safe to repeat; matches on iWine).

Tables are prefixed `wc_`. Drinking a bottle logs a check-in with optional rating.

## Adding wines
When you type a producer that is already in your cellar, the form fills in country, region, grape, colour and style, and suggests a drinking window from your earlier vintages (it is only a suggestion; change it freely).

## Label photo
Scan, then "Photograph the label", or use "Read the label" in the picture box. The text is read on your phone or computer; the photo never leaves your home. It finds the producer (if you already have it), vintage, appellation, grape and colour, and lists other lines you can tap into a field. Reading curved labels is not perfect, so always check the fields. The reader is downloaded when the add-on is built; if it is missing, the photo is only saved as the picture. On iPhone and Mac you can also tap a field and choose Scan Text.

## Pictures
The add-on looks up a picture for each wine in stock on Open Food Facts (free, open database), about one wine every 7 seconds. Only close matches are used, so many wines will have none: tap the bottle on a card to add your own photo. Turn the automatic lookup off with the option `auto_images`.

## Scanning
Use **Scan bottle**. A USB/Bluetooth scanner types the number into the box. The camera needs Home Assistant over HTTPS and a browser that supports barcode reading.

## Wine list
**Wine list** shows a menu-style list of your current selection (filters apply). Print it from there.

## Systembolaget prices
Once a week the add-on downloads the public mirror of Systembolaget's assortment (github.com/AlexGustafsson/systembolaget-api-data, about 30 MB) and keeps only the wines in a small table. Each of your wines is matched strictly on producer, wine name, vintage and bottle size. Many wines (especially small French producers) are not sold there and will show no price. Prices are in kr; `eur_sek_rate` converts them for "Use as current value". Turn it off with `systembolaget_prices`.

## Edit table
**Edit table** opens the whole cellar as a spreadsheet. Type in any cell, or use the + and − next to the bottle count. Enter and the up/down arrows move between rows, Tab moves right and adds a row after the last cell. You can paste rows straight from Excel or Google Sheets (column order: vintage, producer, wine, colour, style, country, region, appellation, grape, bottles, paid, value, drink from, drink to, shelf). Ctrl/Cmd+D copies the cell above.
Tick rows to add or remove a bottle on all of them, duplicate them, or delete them. Changed cells are highlighted. Nothing is saved until you press Save (or Ctrl/Cmd+S); Discard throws the changes away. Bottle changes show up in the activity list as added or removed.

## Stats
**Stats** shows bottles, value or money paid by region, country, vintage, style, grape and producer, when to drink, price bands, biggest gains and losses, and bottles opened per month. It can cover the whole cellar or only your current filters.

## Export and import
**Import / export** downloads a CSV (opens in Excel, Numbers, Google Sheets) or a full JSON copy with history and rack positions. The CSV uses CellarTracker's column names, so it can be imported again, here or in CellarTracker. Importing again updates wines and adds new ones; it deletes nothing and does not restore rack positions. For a complete backup, include the Postgres app in your Home Assistant backups.

## Grafana
The add-on creates read-only views in the database for charts: `wc_v_cellar`, `wc_v_by_region`, `wc_v_by_vintage`, `wc_v_by_type`, `wc_v_drunk_by_month` and `wc_v_rack_contents`.
1. In Grafana add a PostgreSQL data source pointing at the Postgres app (host `db21ed7f-postgres-latest`, port 5432), database `winecellar` and the `winecellar` login.
2. Import `grafana/wine-cellar-dashboard.json` from this folder and pick that data source.
