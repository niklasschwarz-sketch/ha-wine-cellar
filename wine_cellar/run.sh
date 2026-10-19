#!/usr/bin/with-contenv bashio
# The cellar lives in one file inside the add-on (/data), which Home Assistant backups include.
export PORT=8099
export DB_TYPE=sqlite
export SQLITE_PATH=/data/winecellar.db
bashio::log.info "Starting Wine Cellar with its built-in database (${SQLITE_PATH})"
if bashio::config.false 'auto_images'; then export AUTO_IMAGES=0; else export AUTO_IMAGES=1; fi
if bashio::config.false 'systembolaget_prices'; then export AUTO_PRICES=0; else export AUTO_PRICES=1; fi
if bashio::config.has_value 'eur_sek_rate'; then export EUR_SEK="$(bashio::config 'eur_sek_rate')"; fi
if bashio::config.has_value 'label_ai_key'; then export LABEL_AI_KEY="$(bashio::config 'label_ai_key')"; fi
if bashio::config.has_value 'label_ai_model'; then export LABEL_AI_MODEL="$(bashio::config 'label_ai_model')"; fi
exec python3 /app/server.py
