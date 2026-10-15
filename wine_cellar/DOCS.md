# Wine Cellar

## Install
1. Add this repository: Settings → Add-ons → Add-on store → ⋮ → Repositories → `https://github.com/niklasschwarz-sketch/ha-wine-cellar`. Home Assistant can only read public repositories. For a private one, copy the `wine_cellar` folder into the `/local_apps` folder of your Home Assistant instead.
2. Install **Wine Cellar**. The first install builds the add-on on your own Home Assistant and downloads about 20 MB (the label reader), so it takes a few minutes.
3. Start it and turn on **Show in sidebar**. Open **Cellar**.
4. Tap **Add wine**, or **Import / export** and choose your CellarTracker CSV export (safe to repeat; matches on iWine).

That is all. There is nothing to configure: the add-on keeps your cellar in its own database file, so it needs no database server and touches nothing else on your system.

## Where your data is, and backups
Your cellar is one file inside the add-on (`/data/winecellar.db`). Home Assistant backups include it automatically. During a backup the add-on is stopped for a moment so the file is copied cleanly. You can also download a CSV (opens in Excel and Sheets) or a full JSON copy from **Import / export** at any time.

## Using Postgres instead (optional)
Use this only if you want your data in Postgres, for example to chart it in Grafana. You need a Postgres server that Home Assistant can reach and an empty database and login of its own on it. Set this up once, in this order.

### 1. Install a Postgres add-on
Use **Postgres 17** from Alex Belgium's add-on repository (the setup below is written for it).
1. Settings → Add-ons → Add-on store → ⋮ → Repositories, add `https://github.com/alexbelgium/hassio-addons`.
2. Install **Postgres 17**. In its Configuration tab set `POSTGRES_PASSWORD` (this is the password of the `postgres` administrator, keep it safe) and press Save.
3. Start it and check the log for errors. Its address for other add-ons is `db21ed7f-postgres-latest`, port `5432`. That name is the same on every Home Assistant that installed it from this repository.

Already running another Postgres (for example one shared with other add-ons)? You can use it. Just use its host name below, and the same two commands in step 2.

### 2. Create the database and login for Wine Cellar
You do this once, with a SQL command line. The **Terminal & SSH** add-on has one:
1. Install and start **Terminal & SSH** (official add-ons).
2. In its terminal run `apk add postgresql17-client`.
3. Run `psql -h db21ed7f-postgres-latest -U postgres` and enter the `POSTGRES_PASSWORD` from step 1.
4. At the `postgres=#` prompt run these two lines. Replace `CHOOSE_A_PASSWORD` with a new password only for Wine Cellar (not your admin password), and keep the quotes:

```
CREATE USER winecellar WITH PASSWORD 'CHOOSE_A_PASSWORD';
CREATE DATABASE winecellar OWNER winecellar;
```
5. Type `exit`.

The add-on creates its own tables (they start with `wc_`) the first time it runs. It never touches other databases.

### 3. Point Wine Cellar at it
1. In the Wine Cellar Configuration tab set `db_type` to `postgres` and `db_password` to the `CHOOSE_A_PASSWORD` from step 2. The other options (`db_host` `db21ed7f-postgres-latest`, `db_port` 5432, `db_name` `winecellar`, `db_user` `winecellar`) already match the steps above, so only change them if you chose different names or use another Postgres. Save.
2. Restart the add-on. The log says "Starting Wine Cellar with Postgres".

### If it does not start
Open the add-on's **Log** tab. Database problems show up as "Database not ready" lines followed by the reason, and after about a minute "Could not reach the database".
- "db_type is postgres but db_password is empty": fill in `db_password` in the Configuration tab and start again.
- "password authentication failed": the password does not match the one from step 2. Either correct `db_password`, or reset it with `ALTER USER winecellar WITH PASSWORD 'new';` in `psql`.
- "database ... does not exist" or "Could not reach the database": check step 2 was done, and that `db_host`, `db_name` and `db_user` match what you created and Postgres is started.

Tip: by default the Postgres add-on can also be reached from other devices on your network on port 5432. If only add-ons need it, clear the port under the Postgres add-on's Network settings and restart it.

Tables are prefixed `wc_`. Drinking a bottle logs a check-in with optional rating.

If `db_type` is not set, an add-on that already has a `db_password` keeps using Postgres, so updating from an older version never switches you to an empty cellar. A new install with no password uses the built-in database. Data is not copied between the two: to move, export a CSV and import it on the other side (wines and bottle counts move; history, pictures and rack positions do not).

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
**Import / export** downloads a CSV (opens in Excel, Numbers, Google Sheets) or a full JSON copy with history and rack positions. The CSV uses CellarTracker's column names, so it can be imported again, here or in CellarTracker. Importing again updates wines and adds new ones; it deletes nothing and does not restore rack positions. For a complete backup, include this add-on in your Home Assistant backups (or the Postgres add-on, if you use Postgres).

## Grafana (Postgres only)
Grafana needs the Postgres option above. The add-on creates read-only views in the database for charts: `wc_v_cellar`, `wc_v_by_region`, `wc_v_by_vintage`, `wc_v_by_type`, `wc_v_drunk_by_month` and `wc_v_rack_contents`.
1. In Grafana add a PostgreSQL data source pointing at the Postgres app (host `db21ed7f-postgres-latest`, port 5432), database `winecellar` and the `winecellar` login.
2. Import `grafana/wine-cellar-dashboard.json` from this folder and pick that data source.
