# Moving from Postgres (0.6.x) to the built-in database (0.7.0)

For installs that ran Wine Cellar on a Postgres add-on and want to switch to the built-in database, then remove the old database and Grafana leftovers. Take it one phase at a time. Everything up to phase E can be undone.

Names used below are the defaults: Postgres add-on host `db21ed7f-postgres-latest`, database and login `winecellar`, Wine Cellar installed from `/local_apps`. Change them if yours differ.

## What moves and what does not
The CSV export carries every wine with bottle counts, prices, values, drinking windows, location, notes and barcodes. It does not carry the check-in history (drink log and ratings), pictures you uploaded yourself, or rack positions. Pictures found automatically are looked up again after the switch. In a rehearsal with a CellarTracker-style file and a wine added in the app, all wine fields came across identical and a second import changed nothing.

## A. Safety copies (about 10 minutes)
1. Open the running app. Write down the numbers in the summary strip: wines, bottles, value. You will compare them later.
2. **Import / export**: download the **CSV** and the **full copy (JSON)**. Keep both somewhere outside Home Assistant. The CSV is the file you import in phase C.
3. Dump the database. In **Terminal & SSH** (run `apk add postgresql17-client` first if `psql` is missing):
   ```
   pg_dump -h db21ed7f-postgres-latest -U postgres winecellar | gzip > /share/winecellar-before-0.7.sql.gz
   ls -l /share/winecellar-before-0.7.sql.gz
   ```
   Enter the Postgres administrator password (`POSTGRES_PASSWORD` of the Postgres add-on). The file should be more than a few kB.
4. Optional but sensible: Settings → System → Backups → create a backup that includes Wine Cellar, Postgres and Grafana.

Check before going on: the CSV, the JSON and the dump file exist, and you have the three numbers.

## B. Update the add-on (nothing changes yet)
1. Paste `install_wine_cellar_v070.sh` into the Terminal & SSH prompt (it unpacks into `/local_apps/wine_cellar` and prints `version: "0.7.0"`). Once the repository is public you can update from GitHub instead.
2. Settings → Add-ons → Add-on store → ⋮ → **Check for updates**. Open Wine Cellar and press **Update**.
3. Your existing `db_password` is still set, so the add-on keeps using Postgres. The log says "Starting Wine Cellar with Postgres". Open the app and check it looks exactly as before.

Rollback: none needed, nothing has changed. To go back to 0.6.x, restore the backup from phase A.

## C. Switch to the built-in database
1. Wine Cellar → Configuration: set `db_type` to `sqlite`. Leave the Postgres fields as they are for now. Save, then restart the add-on.
2. The log says "Starting Wine Cellar with its built-in database (/data/winecellar.db)". The app opens empty.
3. **Import / export** → Import a CSV file → choose the CSV from phase A.
4. Compare the summary strip with your numbers from phase A: wines, bottles and value should match. Open a few wines and check location and notes. Open **Stats**.
5. The automatic picture lookup starts by itself (about one wine every 7 seconds). Add again any photos you uploaded by hand.

Rollback during the trial: set `db_type` to `postgres`, save and restart. You are back on the old data as it was when you switched. Anything you entered in the built-in database since then is not in Postgres, so export a CSV first if you made changes.

## D. Trial period
Use the app normally for a week or two. Let at least one Home Assistant backup run, then export a fresh CSV from the new install and keep it. Do not start phase E until you trust the new install.

## E. Clean up
Do these in this order, once phase D is done.

1. **Wine Cellar → Configuration**: clear `db_password` (keep `db_type` on `sqlite`). Save and restart. The log must still say "built-in database".
2. **Grafana** (only if you ever set it up): Connections → Data sources → delete the PostgreSQL data source that points at the `winecellar` database. Dashboards → "Wine cellar" → Settings → Delete dashboard. If you never imported the dashboard, there is nothing to remove.
3. **Postgres**: in Terminal & SSH run `psql -h db21ed7f-postgres-latest -U postgres`, then:
   ```
   \l
   DROP DATABASE winecellar;
   DROP USER winecellar;
   \l
   ```
   The first `\l` lists the databases. Only `winecellar` is dropped; leave every other database (for example TeslaMate's) and `postgres` alone. The read-only `wc_v_*` views live inside the `winecellar` database and are removed with it. If PostgreSQL says the database is being accessed by other users, stop the Wine Cellar add-on and run the command again.
4. Keep `/share/winecellar-before-0.7.sql.gz` for a while. When you are sure, delete it with `rm /share/winecellar-before-0.7.sql.gz`.
5. The Postgres add-on stays installed if another add-on (such as TeslaMate) uses it.

## If something goes wrong
- The app opens empty after the switch: that is expected until the CSV is imported (phase C step 3).
- The log shows "db_type is postgres but db_password is empty": you cleared the password while `db_type` was still `postgres`. Set `db_type` to `sqlite`.
- The import reports fewer wines than expected: check that you chose the CSV from the export in phase A, not a file from another source, and look at the numbers it reports ("inserted", "skipped").
- Back to the old data after phase E step 3: recreate the login and database (`CREATE USER winecellar WITH PASSWORD '...'; CREATE DATABASE winecellar OWNER winecellar;`), then restore the dump with `gunzip -c /share/winecellar-before-0.7.sql.gz | psql -h db21ed7f-postgres-latest -U postgres winecellar`. Or just import the CSV.
