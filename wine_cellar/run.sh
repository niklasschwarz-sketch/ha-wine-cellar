#!/usr/bin/with-contenv bashio
export DB_TYPE=postgres
export DB_HOST="$(bashio::config 'db_host')"
export DB_PORT="$(bashio::config 'db_port')"
export DB_NAME="$(bashio::config 'db_name')"
export DB_USER="$(bashio::config 'db_user')"
export DB_PASSWORD="$(bashio::config 'db_password')"
export PORT=8099
if [ -z "$DB_PASSWORD" ]; then
  bashio::log.fatal "db_password is empty. Open this add-on's Configuration tab, enter the password you chose for the winecellar database login (see Documentation, step 2), save and start again."
  exit 1
fi
if bashio::config.false 'auto_images'; then export AUTO_IMAGES=0; else export AUTO_IMAGES=1; fi
if bashio::config.false 'systembolaget_prices'; then export AUTO_PRICES=0; else export AUTO_PRICES=1; fi
if bashio::config.has_value 'eur_sek_rate'; then export EUR_SEK="$(bashio::config 'eur_sek_rate')"; fi
bashio::log.info "Starting Wine Cellar, database ${DB_NAME}@${DB_HOST}"
exec python3 /app/server.py
