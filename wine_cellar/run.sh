#!/usr/bin/with-contenv bashio
# Which database? An explicit db_type wins. If it is not set, an install that already has a
# Postgres password keeps using Postgres (so updating never switches a running cellar to an empty
# one), and a new install uses the built-in SQLite file, which needs no setup.
DB_TYPE_OPT=""
if bashio::config.has_value 'db_type'; then DB_TYPE_OPT="$(bashio::config 'db_type')"; fi
DB_PASSWORD=""
if bashio::config.has_value 'db_password'; then DB_PASSWORD="$(bashio::config 'db_password')"; fi
if [ -z "$DB_TYPE_OPT" ]; then
  if [ -n "$DB_PASSWORD" ]; then DB_TYPE_OPT=postgres; else DB_TYPE_OPT=sqlite; fi
fi
export PORT=8099
if [ "$DB_TYPE_OPT" = "postgres" ]; then
  export DB_TYPE=postgres
  export DB_HOST="$(bashio::config 'db_host')"
  export DB_PORT="$(bashio::config 'db_port')"
  export DB_NAME="$(bashio::config 'db_name')"
  export DB_USER="$(bashio::config 'db_user')"
  export DB_PASSWORD
  if [ -z "$DB_PASSWORD" ]; then
    bashio::log.fatal "db_type is postgres but db_password is empty. Enter the password of the winecellar database login in the Configuration tab (see Documentation), or clear db_type to use the built-in database."
    exit 1
  fi
  bashio::log.info "Starting Wine Cellar with Postgres, database ${DB_NAME}@${DB_HOST}"
else
  export DB_TYPE=sqlite
  export SQLITE_PATH=/data/winecellar.db
  bashio::log.info "Starting Wine Cellar with its built-in database (${SQLITE_PATH})"
fi
if bashio::config.false 'auto_images'; then export AUTO_IMAGES=0; else export AUTO_IMAGES=1; fi
if bashio::config.false 'systembolaget_prices'; then export AUTO_PRICES=0; else export AUTO_PRICES=1; fi
if bashio::config.has_value 'eur_sek_rate'; then export EUR_SEK="$(bashio::config 'eur_sek_rate')"; fi
exec python3 /app/server.py
