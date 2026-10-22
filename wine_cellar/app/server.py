#!/usr/bin/env python3
"""Wine Cellar add-on backend.

Small JSON API + static page. Stores wines and a check-in log in Postgres
(the existing Postgres add-on). Standard library only, plus pg8000 for Postgres.
Set DB_TYPE=sqlite (and SQLITE_PATH) to run against SQLite for local tests.
"""
import base64
import csv
import io
import zipfile
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drink  # noqa: E402
import mqtt  # noqa: E402
import pairing  # noqa: E402

VERSION = "0.19.5"  # keep in step with wine_cellar/config.yaml (test_api.py checks it)

DB_TYPE = os.environ.get("DB_TYPE", "postgres")
PORT = int(os.environ.get("PORT", "8099"))
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
LANG_DIR = os.path.join(HERE, "lang")
LANG_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
# Home Assistant ingress reaches add-ons from the Supervisor proxy only.
ALLOWED_IPS = {"172.30.32.2", "127.0.0.1", "::1"}
ALLOW_ANY = os.environ.get("ALLOW_ANY", "") == "1"
MAX_BODY = 8 * 1024 * 1024
IMG_MAX = 3 * 1024 * 1024
AUTO_IMAGES = os.environ.get("AUTO_IMAGES", "1") != "0"
IMG_API = os.environ.get("IMG_API_BASE", "https://world.openfoodfacts.org").rstrip("/")
IMG_GAP = float(os.environ.get("IMG_GAP", "7"))  # seconds between lookups (Open Food Facts allows 10 searches a minute)
IMG_TEST_HOST = os.environ.get("IMG_TEST_HOST", "")
AUTO_PRICES = os.environ.get("AUTO_PRICES", "1") != "0"
SB_URL = os.environ.get("SB_URL", "https://raw.githubusercontent.com/AlexGustafsson/systembolaget-api-data/main/data/assortment.json")
SB_MAX = 120 * 1024 * 1024
EUR_SEK = float(os.environ.get("EUR_SEK", "11") or 11)
USER_AGENT = "WineCellarHomeAssistant/0.2 (personal home cellar; local add-on)"
# Optional: read a label photo with Google's Gemini (free tier with your own key). Off unless a key is set.
LABEL_KEY = os.environ.get("LABEL_AI_KEY", "").strip()
LABEL_MODEL = re.sub(r"[^A-Za-z0-9._-]", "", os.environ.get("LABEL_AI_MODEL", "").strip())  # empty: pick the newest Flash model automatically
LABEL_BASE = os.environ.get("LABEL_AI_BASE", "https://generativelanguage.googleapis.com").rstrip("/")
LABEL_MAX = 4 * 1024 * 1024

HA_API = os.environ.get("HA_API", "http://supervisor/core/api").rstrip("/")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SUPERVISOR_API = os.environ.get("SUPERVISOR_API", "http://supervisor").rstrip("/")
# Home Assistant sensors over MQTT. The broker is found through the Supervisor; MQTT_HOST is only for tests and special setups.
MQTT_HOST = os.environ.get("MQTT_HOST", "").strip()
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883") or 1883)
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
SENSORS_SECS = float(os.environ.get("HA_SENSORS_SECS", "60"))
ALERT_CHECK_SECS = float(os.environ.get("DRINK_ALERT_CHECK_SECS", "600"))
CLIMATE_TEMP = os.environ.get("CLIMATE_TEMP_ENTITY", "").strip()
CLIMATE_HUM = os.environ.get("CLIMATE_HUMIDITY_ENTITY", "").strip()


def _envf(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


TEMP_MIN, TEMP_MAX = _envf("TEMP_MIN", 10), _envf("TEMP_MAX", 16)
HUM_MIN, HUM_MAX = _envf("HUMIDITY_MIN", 60), _envf("HUMIDITY_MAX", 75)
TAG_KINDS = ("gift_received", "gift_given", "special")
OCCASIONS = ("birthday", "anniversary", "wedding", "christmas", "graduation", "dinner", "other")
REVIEW_KINDS = ("critic", "community")

COUNTRIES = [
    ("AR", "Argentina", "ARS", "es-AR"), ("AU", "Australia", "AUD", "en-AU"), ("AT", "Austria", "EUR", "de-AT"), ("BE", "Belgium", "EUR", "nl-BE"),
    ("BR", "Brazil", "BRL", "pt-BR"), ("CA", "Canada", "CAD", "en-CA"), ("CL", "Chile", "CLP", "es-CL"), ("CN", "China", "CNY", "zh-CN"),
    ("HR", "Croatia", "EUR", "hr-HR"), ("CZ", "Czechia", "CZK", "cs-CZ"), ("DK", "Denmark", "DKK", "da-DK"), ("EE", "Estonia", "EUR", "et-EE"),
    ("FI", "Finland", "EUR", "fi-FI"), ("FR", "France", "EUR", "fr-FR"), ("DE", "Germany", "EUR", "de-DE"), ("GR", "Greece", "EUR", "el-GR"),
    ("HK", "Hong Kong", "HKD", "en-HK"), ("HU", "Hungary", "HUF", "hu-HU"), ("IS", "Iceland", "ISK", "is-IS"), ("IN", "India", "INR", "en-IN"),
    ("IE", "Ireland", "EUR", "en-IE"), ("IL", "Israel", "ILS", "he-IL"), ("IT", "Italy", "EUR", "it-IT"), ("JP", "Japan", "JPY", "ja-JP"),
    ("LV", "Latvia", "EUR", "lv-LV"), ("LT", "Lithuania", "EUR", "lt-LT"), ("LU", "Luxembourg", "EUR", "fr-LU"), ("MX", "Mexico", "MXN", "es-MX"),
    ("NL", "Netherlands", "EUR", "nl-NL"), ("NZ", "New Zealand", "NZD", "en-NZ"), ("NO", "Norway", "NOK", "nb-NO"), ("PL", "Poland", "PLN", "pl-PL"),
    ("PT", "Portugal", "EUR", "pt-PT"), ("RO", "Romania", "RON", "ro-RO"), ("SG", "Singapore", "SGD", "en-SG"), ("SK", "Slovakia", "EUR", "sk-SK"),
    ("SI", "Slovenia", "EUR", "sl-SI"), ("ZA", "South Africa", "ZAR", "en-ZA"), ("KR", "South Korea", "KRW", "ko-KR"), ("ES", "Spain", "EUR", "es-ES"),
    ("SE", "Sweden", "SEK", "sv-SE"), ("CH", "Switzerland", "CHF", "de-CH"), ("TW", "Taiwan", "TWD", "zh-TW"), ("TH", "Thailand", "THB", "th-TH"),
    ("TR", "Turkey", "TRY", "tr-TR"), ("AE", "United Arab Emirates", "AED", "en-AE"), ("GB", "United Kingdom", "GBP", "en-GB"),
    ("US", "United States", "USD", "en-US"), ("UY", "Uruguay", "UYU", "es-UY"),
]
CURRENCIES = sorted({c[2] for c in COUNTRIES})
COUNTRY_CODES = {c[0] for c in COUNTRIES}

COLORS = ("Red", "White", "Rosé")
STYLES = ("Dry", "Off-dry", "Sparkling", "Sweet")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- database
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS wc_wines (
        id BIGSERIAL PRIMARY KEY,
        iwine TEXT UNIQUE,
        color TEXT NOT NULL DEFAULT 'Red',
        type TEXT,
        vintage INTEGER,
        producer TEXT NOT NULL,
        wine TEXT,
        varietal TEXT,
        designation TEXT,
        vineyard TEXT,
        country TEXT,
        region TEXT,
        subregion TEXT,
        appellation TEXT,
        size TEXT,
        currency TEXT,
        value DOUBLE PRECISION NOT NULL DEFAULT 0,
        price DOUBLE PRECISION NOT NULL DEFAULT 0,
        quantity INTEGER NOT NULL DEFAULT 0,
        begin_consume INTEGER,
        end_consume INTEGER,
        like_percent DOUBLE PRECISION,
        like_votes INTEGER,
        location TEXT,
        notes TEXT,
        ean TEXT,
        created_at TS_TYPE,
        updated_at TS_TYPE
    )""",
    """CREATE TABLE IF NOT EXISTS wc_checkins (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT,
        label TEXT,
        kind TEXT NOT NULL,
        delta INTEGER NOT NULL,
        rating DOUBLE PRECISION,
        note TEXT,
        ts TS_TYPE
    )""",
    "CREATE INDEX IF NOT EXISTS wc_checkins_ts ON wc_checkins (ts)",
    """CREATE TABLE IF NOT EXISTS wc_images (
        wine_id BIGINT PRIMARY KEY,
        data BYTEA,
        mime TEXT,
        source TEXT NOT NULL,
        source_url TEXT,
        credit TEXT,
        checked_at TS_TYPE
    )""",
    """CREATE TABLE IF NOT EXISTS wc_sb (
        product_number TEXT PRIMARY KEY,
        producer TEXT,
        name TEXT,
        vintage INTEGER,
        volume INTEGER,
        price DOUBLE PRECISION,
        seen TS_TYPE
    )""",
    """CREATE TABLE IF NOT EXISTS wc_prices (
        wine_id BIGINT PRIMARY KEY,
        source TEXT NOT NULL,
        price DOUBLE PRECISION,
        product_number TEXT,
        name TEXT,
        vintage INTEGER,
        volume INTEGER,
        status TEXT NOT NULL,
        checked_at TS_TYPE
    )""",
    """CREATE TABLE IF NOT EXISTS wc_price_log (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT,
        source TEXT,
        price DOUBLE PRECISION,
        ts TS_TYPE
    )""",
    """CREATE TABLE IF NOT EXISTS wc_places (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'cellar',
        pos INTEGER NOT NULL DEFAULT 0,
        temp_entity TEXT,
        hum_entity TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS wc_stock (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT NOT NULL,
        place_id BIGINT NOT NULL,
        qty INTEGER NOT NULL,
        note TEXT
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS wc_stock_pos ON wc_stock (wine_id, place_id)",
    "CREATE INDEX IF NOT EXISTS wc_stock_place ON wc_stock (place_id)",
    """CREATE TABLE IF NOT EXISTS wc_tags (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT NOT NULL,
        kind TEXT NOT NULL,
        occasion TEXT,
        who TEXT,
        date TEXT,
        yearly INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        created_at TS_TYPE
    )""",
    "CREATE INDEX IF NOT EXISTS wc_tags_wine ON wc_tags (wine_id)",
    """CREATE TABLE IF NOT EXISTS wc_reviews (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT NOT NULL,
        kind TEXT NOT NULL,
        source TEXT,
        score DOUBLE PRECISION,
        scale INTEGER,
        text TEXT,
        url TEXT,
        date TEXT,
        created_at TS_TYPE
    )""",
    "CREATE INDEX IF NOT EXISTS wc_reviews_wine ON wc_reviews (wine_id)",
    """CREATE TABLE IF NOT EXISTS wc_meta (
        k TEXT PRIMARY KEY,
        v TEXT
    )""",
]


def ddl(sql):
    if DB_TYPE == "sqlite":
        return sql.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("TS_TYPE", "TEXT").replace("BIGINT", "INTEGER").replace("BYTEA", "BLOB")
    return sql.replace("TS_TYPE", "TIMESTAMPTZ")


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.conn = None

    def _connect(self):
        if DB_TYPE == "sqlite":
            import sqlite3
            path = os.environ.get("SQLITE_PATH", ":memory:")
            if path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            c = sqlite3.connect(path, check_same_thread=False, timeout=15)
            return c
        import pg8000.dbapi as pg
        return pg.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "5432")),
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ.get("DB_PASSWORD", ""),
            timeout=15,
        )

    def _sql(self, sql):
        return sql if DB_TYPE == "sqlite" else sql.replace("?", "%s")

    def _args(self, params):
        out = []
        for p in params:
            if isinstance(p, datetime) and DB_TYPE == "sqlite":
                p = p.isoformat()
            out.append(p)
        return out

    def run(self, sql, params=(), fetch=None):
        """fetch: None | 'one' | 'all'. Returns rows as dicts. Commits writes."""
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.conn is None:
                        self.conn = self._connect()
                    cur = self.conn.cursor()
                    cur.execute(self._sql(sql), self._args(params))
                    rows = None
                    if fetch:
                        cols = [d[0].decode() if isinstance(d[0], bytes) else d[0] for d in cur.description]
                        raw = cur.fetchone() if fetch == "one" else cur.fetchall()
                        if fetch == "one":
                            rows = dict(zip(cols, raw)) if raw else None
                        else:
                            rows = [dict(zip(cols, r)) for r in raw]
                    self.conn.commit()
                    return rows
                except Exception as e:  # reconnect once on a dropped connection
                    try:
                        if self.conn is not None:
                            self.conn.rollback()
                    except Exception:
                        self.conn = None
                    name = type(e).__name__
                    if attempt == 1 and name in ("InterfaceError", "OperationalError", "BrokenPipeError", "ConnectionResetError", "OSError"):
                        self.conn = None
                        continue
                    raise

    def init_schema(self):
        for stmt in SCHEMA:
            self.run(ddl(stmt))
        # Upgrade tables created by version 0.1.0
        try:
            if DB_TYPE == "sqlite":
                self.run("ALTER TABLE wc_wines ADD COLUMN ean TEXT")
            else:
                self.run("ALTER TABLE wc_wines ADD COLUMN IF NOT EXISTS ean TEXT")
        except Exception as e:
            if "duplicate" not in str(e).lower():
                raise
        self.run("CREATE INDEX IF NOT EXISTS wc_wines_ean ON wc_wines (ean)")
        self.drop_old_racks()
        make_views()

    def drop_old_racks(self):
        """The rack screen of earlier versions was never switched on. Remove its tables when they hold nothing."""
        try:
            self.run("DROP VIEW IF EXISTS wc_v_rack_contents")
            n = self.run("SELECT COUNT(*) AS n FROM wc_bottles", fetch="one")["n"]
            if not n:
                self.run("DROP TABLE IF EXISTS wc_bottles")
                self.run("DROP TABLE IF EXISTS wc_racks")
        except Exception:
            pass


db = DB()


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- helpers
class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def num(v, default=0.0):
    try:
        s = str(v if v is not None else "").strip().replace(",", ".")
        return float(s) if s else default
    except ValueError:
        return default


def txt(v, limit=300):
    s = "" if v is None else str(v).strip()
    if s.lower() == "unknown":
        s = ""
    return s[:limit]


def iso(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def wine_json(r, stock=None):
    if stock is None:
        stock = stock_of(r["id"])
    return {
        "id": r["id"],
        "iwine": r.get("iwine"),
        "color": r["color"],
        "type": r.get("type") or r["color"],
        "vintage": "NV" if r.get("vintage") in (None, 0) else r["vintage"],
        "producer": r["producer"],
        "wine": r.get("wine") or "",
        "varietal": r.get("varietal") or "",
        "designation": r.get("designation") or "",
        "vineyard": r.get("vineyard") or "",
        "country": r.get("country") or "",
        "region": r.get("region") or "",
        "subregion": r.get("subregion") or "",
        "appellation": r.get("appellation") or "",
        "size": r.get("size") or "",
        "currency": r.get("currency") or "EUR",
        "value": r.get("value") or 0,
        "price": r.get("price") or 0,
        "quantity": r.get("quantity") or 0,
        "begin": r.get("begin_consume"),
        "end": r.get("end_consume"),
        "status": drink.status(r.get("begin_consume"), r.get("end_consume")),
        "likePercent": r.get("like_percent"),
        "likeVotes": r.get("like_votes") or 0,
        "location": r.get("location") or "",
        "stock": stock,
        "notes": r.get("notes") or "",
        "ean": r.get("ean") or "",
        "updated": iso(r.get("updated_at")),
        "img": iso(r.get("img_ts")) if r.get("img_source") in ("upload", "web") else None,
        "imgSource": r.get("img_source") if r.get("img_source") in ("upload", "web") else None,
        "imgCredit": r.get("img_credit") or "",
        "sb": ({"status": r.get("sb_status"), "price": r.get("sb_price"), "name": r.get("sb_name") or "", "number": r.get("sb_no") or "",
                "vintage": r.get("sb_vintage"), "checked": iso(r.get("sb_ts"))} if r.get("sb_status") else None),
        "imgUrl": r.get("img_url") if str(r.get("img_url") or "").startswith(("https://", "http://")) else "",
    }


def type_for(color, style):
    if style == "Dry":
        return color
    return color + " - " + ("Sweet/Dessert" if style == "Sweet" else style)


def clean_wine(data, partial=False):
    """Validate and normalise a wine payload. Returns a dict of DB columns."""
    out = {}

    def need(key):
        if not partial and key not in data:
            raise ApiError(400, "Missing field: " + key)

    need("producer")
    if "producer" in data:
        p = txt(data["producer"], 200)
        if not p:
            raise ApiError(400, "Producer is required")
        out["producer"] = p
    if "color" in data or not partial:
        c = data.get("color", "Red")
        if c not in COLORS:
            raise ApiError(400, "Colour must be one of " + ", ".join(COLORS))
        out["color"] = c
    if "vintage" in data or not partial:
        v = data.get("vintage", "NV")
        if v in ("NV", "nv", None, "", 0, 1001):
            out["vintage"] = None
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ApiError(400, "Vintage must be a year or NV")
            if not 1800 <= v <= 2100:
                raise ApiError(400, "Vintage must be between 1800 and 2100")
            out["vintage"] = v
    if "quantity" in data or not partial:
        try:
            q = int(data.get("quantity", 1))
        except (TypeError, ValueError):
            raise ApiError(400, "Quantity must be a whole number")
        if not 0 <= q <= 9999:
            raise ApiError(400, "Quantity must be between 0 and 9999")
        out["quantity"] = q
    for key in ("wine", "varietal", "designation", "vineyard", "country", "region", "subregion", "appellation", "size", "location"):
        if key in data:
            out[key] = txt(data[key], 300)
    if "notes" in data:
        out["notes"] = txt(data["notes"], 2000)
    if "ean" in data:
        e = re.sub(r"\s+", "", str(data["ean"] or ""))
        if e and not (e.isdigit() and 8 <= len(e) <= 14):
            raise ApiError(400, "EAN must be 8 to 14 digits")
        out["ean"] = e
    for key in ("value", "price"):
        if key in data:
            f = num(data[key])
            if f < 0 or f > 1000000:
                raise ApiError(400, key.capitalize() + " must be 0 or more")
            out[key] = f
    for src, dst in (("begin", "begin_consume"), ("end", "end_consume")):
        if src in data:
            v = data[src]
            if v in (None, "", 0, 9999):
                out[dst] = None
            else:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    raise ApiError(400, "Drinking window must be years")
                if not 1900 <= v <= 2200:
                    raise ApiError(400, "Drinking window must be between 1900 and 2200")
                out[dst] = v
    if out.get("begin_consume") and out.get("end_consume") and out["begin_consume"] > out["end_consume"]:
        raise ApiError(400, "Window start must not be after window end")
    if "style" in data or not partial:
        style = data.get("style", "Dry")
        if style not in STYLES:
            raise ApiError(400, "Style must be one of " + ", ".join(STYLES))
        out["type"] = type_for(out.get("color") or data.get("color", "Red"), style)
    return out


def label_of(r):
    v = "NV" if r.get("vintage") in (None, 0) else str(r["vintage"])
    full = r.get("wine") or ""
    if r["producer"] and not full.startswith(r["producer"]):
        full = (r["producer"] + " " + full).strip()
    return (v + " " + full).strip()[:300]


# ---------------------------------------------------------------- operations
WINE_SELECT = (
    "SELECT w.*, i.source AS img_source, i.checked_at AS img_ts, i.credit AS img_credit, i.source_url AS img_url, "
    "p.status AS sb_status, p.price AS sb_price, p.name AS sb_name, p.product_number AS sb_no, p.vintage AS sb_vintage, p.checked_at AS sb_ts "
    "FROM wc_wines w LEFT JOIN wc_images i ON i.wine_id = w.id AND i.data IS NOT NULL "
    "LEFT JOIN wc_prices p ON p.wine_id = w.id"
)


def list_wines():
    rows = db.run(WINE_SELECT + " ORDER BY w.id", fetch="all")
    sm = stock_map()
    return [wine_json(r, sm.get(r["id"], [])) for r in rows]


def wine_pairing(wid):
    r = get_wine(wid)
    p = pairing.profile(r)
    return {"style": pairing.describe(p), "dishes": pairing.best_dishes(p, 6), "status": pairing.drink_status(r)}


def pairing_find(dish):
    rows = db.run(WINE_SELECT + " ORDER BY w.id", fetch="all")
    found = pairing.find_wines(dish, rows)
    if found is None:
        raise ApiError(404, "Unknown dish")
    byid = {r["id"]: r for r in rows}
    sm = stock_map()
    for f in found:
        f["wine"] = wine_json(byid[f["id"]], sm.get(f["id"], []))
    return {"dish": dish, "wines": found}


def get_wine(wid):
    r = db.run(WINE_SELECT + " WHERE w.id = ?", (wid,), fetch="one")
    if not r:
        raise ApiError(404, "Wine not found")
    return r


def insert_wine(cols):
    cols = dict(cols)
    cols["created_at"] = now()
    cols["updated_at"] = cols["created_at"]
    names = list(cols)
    r = db.run(
        "INSERT INTO wc_wines (" + ", ".join(names) + ") VALUES (" + ", ".join("?" for _ in names) + ") RETURNING id",
        [cols[n] for n in names],
        fetch="one",
    )
    return r["id"]


def create_wine(data):
    cols = clean_wine(data)
    if not cols.get("wine"):
        cols["wine"] = cols["producer"]
    cols.setdefault("currency", "EUR")
    place = _place_arg(data.get("placeId")) if cols["quantity"] > 0 else None
    wid = insert_wine(cols)
    if cols["quantity"] > 0:
        add_checkin(wid, label_of(cols), "add", cols["quantity"], None, "Added to the cellar")
        if place:
            _stock_add(wid, place, cols["quantity"], txt(data.get("placeNote"), 100))
    if data.get("fetchPicture") and cols.get("ean") and AUTO_IMAGES:
        attach_ean_picture(wid, cols["ean"])
    wake.set()
    price_wake.set()
    return wine_json(get_wine(wid))


def update_wine(wid, data):
    get_wine(wid)
    cols = clean_wine(data, partial=True)
    if "quantity" in cols:
        raise ApiError(400, "Use the adjust action to change the bottle count")
    if not cols:
        raise ApiError(400, "Nothing to update")
    cols["updated_at"] = now()
    names = list(cols)
    db.run("UPDATE wc_wines SET " + ", ".join(n + " = ?" for n in names) + " WHERE id = ?", [cols[n] for n in names] + [wid])
    return wine_json(get_wine(wid))


def add_checkin(wid, label, kind, delta, rating, note):
    db.run(
        "INSERT INTO wc_checkins (wine_id, label, kind, delta, rating, note, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (wid, label, kind, delta, rating, note, now()),
    )


def adjust_wine(wid, data):
    r = get_wine(wid)
    try:
        delta = int(data.get("delta", 0))
    except (TypeError, ValueError):
        raise ApiError(400, "delta must be a whole number")
    if delta == 0 or abs(delta) > 999:
        raise ApiError(400, "delta must be between -999 and 999, not 0")
    kind = data.get("kind") or ("drink" if delta < 0 else "add")
    if kind not in ("drink", "remove", "add", "correction"):
        raise ApiError(400, "Unknown kind")
    rating = data.get("rating")
    if rating not in (None, ""):
        rating = num(rating, -1)
        if not (0.5 <= rating <= 5) or (rating * 2) % 1:
            raise ApiError(400, "Rating must be 0.5 to 5 in half steps")
    else:
        rating = None
    if rating is not None and kind != "drink":
        raise ApiError(400, "Only opened bottles can be rated")
    note = txt(data.get("note"), 1000) or None
    place = _place_arg(data.get("placeId"))
    newq = (r["quantity"] or 0) + delta
    if newq < 0:
        raise ApiError(409, "There are not that many bottles left")
    if place is not None and delta < 0:
        row = _stock_row(wid, place)
        if not row or row["qty"] < -delta:
            raise ApiError(409, "There are not that many bottles in " + get_place(place)["name"])
    # Conditional update keeps the count correct if two taps race.
    db.run("UPDATE wc_wines SET quantity = ?, updated_at = ? WHERE id = ? AND quantity = ?", (newq, now(), wid, r["quantity"] or 0))
    cur = get_wine(wid)
    if (cur["quantity"] or 0) != newq:
        raise ApiError(409, "The cellar changed, please try again")
    add_checkin(wid, label_of(r), kind, delta, rating, note)
    stock_after_adjust(wid, delta, place, newq)
    return wine_json(get_wine(wid))


def delete_wine(wid):
    r = get_wine(wid)
    add_checkin(None, label_of(r), "delete", -(r["quantity"] or 0), None, "Wine deleted from the cellar")
    db.run("UPDATE wc_checkins SET wine_id = NULL WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_images WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_prices WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_stock WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_tags WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_reviews WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_wines WHERE id = ?", (wid,))
    return {"deleted": wid}


def list_checkins(limit, wine=None):
    limit = max(1, min(int(limit), 500))
    if wine:
        rows = db.run("SELECT * FROM wc_checkins WHERE wine_id = ? ORDER BY ts DESC, id DESC LIMIT ?", (int(wine), limit), fetch="all")
    else:
        rows = db.run("SELECT * FROM wc_checkins ORDER BY ts DESC, id DESC LIMIT ?", (limit,), fetch="all")
    return [
        {
            "id": r["id"], "wineId": r["wine_id"], "label": r["label"], "kind": r["kind"], "delta": r["delta"],
            "rating": r["rating"], "note": r["note"], "ts": iso(r["ts"]),
        }
        for r in rows
    ]


def decode_csv(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ApiError(400, "Could not read the file as text")


def import_csv(raw):
    text = decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text))
    need = {"iWine", "Color", "Producer", "Quantity", "Vintage"}
    if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
        raise ApiError(400, "This does not look like a CellarTracker export (missing columns: " + ", ".join(sorted(need - set(reader.fieldnames or []))) + ")")
    inserted = updated = skipped = 0
    # One wine can be listed on several rows (one per place, as the export writes it). Those rows add up.
    groups = {}
    for r in reader:
        iw = txt(r.get("iWine"), 40)
        color = r.get("Color") or "Red"
        if not iw or color not in COLORS or not txt(r.get("Producer"), 200):
            skipped += 1
            continue
        groups.setdefault(iw, []).append(r)
    use_places = places_on()
    pcache = {}
    for iw, rows_ in groups.items():
        r = rows_[0]
        color = r.get("Color") or "Red"
        try:
            v = int(r.get("Vintage") or 0)
        except ValueError:
            v = 0
        b, e = r.get("BeginConsume"), r.get("EndConsume")

        def yr(x):
            try:
                x = int(x)
                return x if 1900 <= x < 9999 else None
            except (TypeError, ValueError):
                return None
        lp = num(r.get("LikePercent"), None) if (r.get("LikePercent") or "").strip() else None
        try:
            lv = int(r.get("LikeVotes") or 0)
        except ValueError:
            lv = 0
        qty_total = sum(max(0, int(num(x.get("Quantity")))) for x in rows_)
        cols = {
            "color": color, "type": txt(r.get("Type"), 60) or color, "vintage": None if v in (0, 1001) else v,
            "producer": txt(r.get("Producer"), 200), "wine": txt(r.get("Wine"), 300), "varietal": txt(r.get("Varietal"), 200),
            "designation": txt(r.get("Designation")), "vineyard": txt(r.get("Vineyard")), "country": txt(r.get("Country")),
            "region": txt(r.get("Region")), "subregion": txt(r.get("SubRegion")), "appellation": txt(r.get("Appellation")),
            "size": txt(r.get("Size"), 40), "currency": txt(r.get("Currency"), 8) or "EUR",
            "value": num(r.get("Value")), "price": num(r.get("Price")), "quantity": qty_total,
            "begin_consume": yr(b), "end_consume": yr(e), "like_percent": lp, "like_votes": lv,
        }
        # Our own export carries these; a plain CellarTracker file does not, and must not wipe them.
        for col, key in (("Location", "location"), ("Notes", "notes")):
            first = next((x.get(col) for x in rows_ if (x.get(col) or "").strip()), "")
            if first.strip():
                cols[key] = txt(first, 1000)
        ean = re.sub(r"\D", "", r.get("EAN") or "")
        if 8 <= len(ean) <= 14:
            cols["ean"] = ean
        ex = db.run("SELECT id FROM wc_wines WHERE iwine = ?", (iw,), fetch="one")
        if not ex and re.fullmatch(r"wc-\d+", iw):  # a wine added in this app, exported earlier
            ex = db.run("SELECT id FROM wc_wines WHERE id = ? AND iwine IS NULL", (int(iw[3:]),), fetch="one")
        if ex:
            cols["updated_at"] = now()
            names = list(cols)
            db.run("UPDATE wc_wines SET " + ", ".join(n + " = ?" for n in names) + " WHERE id = ?", [cols[n] for n in names] + [ex["id"]])
            wid = ex["id"]
            updated += 1
        else:
            cols["iwine"] = iw
            wid = insert_wine(cols)
            inserted += 1
        if use_places:
            where = {}
            for x in rows_:
                loc = txt(x.get("Location"), 60)
                if loc:
                    k = (place_for_import(loc, pcache), txt(x.get("Bin"), 100))
                    where[k] = where.get(k, 0) + max(0, int(num(x.get("Quantity"))))
            if where:  # the file says where the bottles are: it replaces what is stored for this wine
                db.run("DELETE FROM wc_stock WHERE wine_id = ?", (wid,))
                for (pid, bin_), n in where.items():
                    if n > 0:
                        _stock_add(wid, pid, n, bin_)
            normalize_stock(wid)
    total = db.run("SELECT COALESCE(SUM(quantity), 0) AS q, COUNT(*) AS n FROM wc_wines", fetch="one")
    wake.set()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "wines": total["n"], "bottles": int(total["q"])}


# ---------------------------------------------------------------- storage places (fridges, cellars, bar ...)
PLACE_KINDS = ("cellar", "fridge", "bar", "other")


def clean_int(v, lo, hi, label):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, label + " must be a whole number")
    if not lo <= n <= hi:
        raise ApiError(400, "%s must be between %d and %d" % (label, lo, hi))
    return n


def guess_kind(name):
    n = (name or "").lower()
    if "fridge" in n or "kyl" in n or "cooler" in n:
        return "fridge"
    if n.startswith("bar") or " bar" in n:
        return "bar"
    if "cellar" in n or "källare" in n or "kallare" in n:
        return "cellar"
    return "other"


def places_on():
    return bool(app_settings()[0].get("places"))


def stock_map():
    out = {}
    for s in db.run("SELECT wine_id, place_id, qty, note FROM wc_stock WHERE qty > 0 ORDER BY id", fetch="all"):
        out.setdefault(s["wine_id"], []).append({"placeId": s["place_id"], "qty": s["qty"], "note": s.get("note") or ""})
    return out


def stock_of(wid):
    return [{"placeId": s["place_id"], "qty": s["qty"], "note": s.get("note") or ""}
            for s in db.run("SELECT place_id, qty, note FROM wc_stock WHERE wine_id = ? AND qty > 0 ORDER BY id", (wid,), fetch="all")]


_place_cache = {}


def _place_reading(entity):
    """Current value of a sensor, cached for a minute so a busy list never hammers Home Assistant."""
    if not entity or not HA_TOKEN:
        return None
    hit = _place_cache.get(entity)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    val = None
    try:
        st = _ha_get("/states/" + quote(entity, safe="._"))
        unit = (st.get("attributes") or {}).get("unit_of_measurement", "")
        v = float(st.get("state"))
        want = app_settings()[0]["tempUnit"]
        conv = _unit_converter(unit, want)
        if conv:
            v, unit = conv(v), "°" + want
        val = {"value": round(v, 1), "unit": unit}
    except Exception:
        val = None
    _place_cache[entity] = (time.time(), val)
    return val


def place_json(p, bottles=0, readings=True):
    return {"id": p["id"], "name": p["name"], "kind": p["kind"], "tempEntity": p.get("temp_entity") or "", "humEntity": p.get("hum_entity") or "",
            "bottles": bottles,
            "temp": _place_reading(p.get("temp_entity")) if readings else None,
            "humidity": _place_reading(p.get("hum_entity")) if readings else None}


def places_state(readings=True):
    rows = db.run("SELECT * FROM wc_places ORDER BY pos, id", fetch="all")
    counts = {r["place_id"]: int(r["n"]) for r in db.run("SELECT place_id, COALESCE(SUM(qty), 0) AS n FROM wc_stock GROUP BY place_id", fetch="all")}
    placed = db.run("SELECT COALESCE(SUM(s.qty), 0) AS n FROM wc_stock s JOIN wc_wines w ON w.id = s.wine_id", fetch="one")["n"]
    total = db.run("SELECT COALESCE(SUM(quantity), 0) AS n FROM wc_wines", fetch="one")["n"]
    return {"places": [place_json(p, counts.get(p["id"], 0), readings) for p in rows], "unplaced": max(0, int(total) - int(placed)),
            "enabled": places_on()}


def get_place(pid):
    p = db.run("SELECT * FROM wc_places WHERE id = ?", (pid,), fetch="one")
    if not p:
        raise ApiError(404, "That place no longer exists")
    return p


def _place_fields(data, partial=False):
    out = {}
    if "name" in data or not partial:
        name = txt(data.get("name"), 60)
        if not name:
            raise ApiError(400, "Give the place a name")
        out["name"] = name
    if "kind" in data or not partial:
        kind = data.get("kind") or guess_kind(out.get("name"))
        if kind not in PLACE_KINDS:
            raise ApiError(400, "Type must be one of " + ", ".join(PLACE_KINDS))
        out["kind"] = kind
    for key, col in (("tempEntity", "temp_entity"), ("humEntity", "hum_entity")):
        if key in data:
            v = txt(data.get(key), 80).lower()
            if v and not ENTITY_RE.match(v):
                raise ApiError(400, "That does not look like a sensor name. It should look like sensor.fridge_temperature")
            out[col] = v
    return out


def _name_free(name, skip=None):
    for p in db.run("SELECT id, name FROM wc_places", fetch="all"):
        if p["id"] != skip and p["name"].strip().lower() == name.strip().lower():
            raise ApiError(409, "There is already a place called " + p["name"])


def create_place(data):
    f = _place_fields(data)
    _name_free(f["name"])
    n = db.run("SELECT COALESCE(MAX(pos), 0) AS m FROM wc_places", fetch="one")["m"]
    f["pos"] = n + 1
    names = list(f)
    db.run("INSERT INTO wc_places (" + ", ".join(names) + ") VALUES (" + ", ".join("?" for _ in names) + ")", [f[k] for k in names])
    return places_state()


def update_place(pid, data):
    get_place(pid)
    f = _place_fields(data, partial=True)
    if not f:
        raise ApiError(400, "Nothing to update")
    if "name" in f:
        _name_free(f["name"], pid)
    names = list(f)
    db.run("UPDATE wc_places SET " + ", ".join(n + " = ?" for n in names) + " WHERE id = ?", [f[k] for k in names] + [pid])
    _place_cache.clear()
    return places_state()


def order_places(data):
    ids = data.get("ids")
    if not isinstance(ids, list):
        raise ApiError(400, "Send the place ids in the order you want")
    for i, pid in enumerate(ids):
        if str(pid).isdigit():
            db.run("UPDATE wc_places SET pos = ? WHERE id = ?", (i + 1, int(pid)))
    return places_state()


def delete_place(pid, data):
    get_place(pid)
    n = db.run("SELECT COALESCE(SUM(qty), 0) AS n FROM wc_stock WHERE place_id = ?", (pid,), fetch="one")["n"]
    if n:
        if "moveTo" not in data:
            raise ApiError(409, "%d bottles are stored here. Choose where they should go first." % n)
        dest = data.get("moveTo")
        with db.lock:
            if dest not in (None, "", "unplaced"):
                dest = clean_int(dest, 1, 10 ** 12, "Place")
                if dest == pid:
                    raise ApiError(400, "Choose another place")
                get_place(dest)
                for s in db.run("SELECT wine_id, qty, note FROM wc_stock WHERE place_id = ?", (pid,), fetch="all"):
                    _stock_add(s["wine_id"], dest, s["qty"], s.get("note"))
            db.run("DELETE FROM wc_stock WHERE place_id = ?", (pid,))
    db.run("DELETE FROM wc_places WHERE id = ?", (pid,))
    _place_cache.clear()
    return places_state()


def _stock_row(wid, pid):
    return db.run("SELECT * FROM wc_stock WHERE wine_id = ? AND place_id = ?", (wid, pid), fetch="one")


def _stock_add(wid, pid, qty, note=None):
    """Put qty bottles of a wine in a place (adds to what is there). A given note replaces the shelf note."""
    row = _stock_row(wid, pid)
    if row:
        db.run("UPDATE wc_stock SET qty = ?, note = ? WHERE id = ?", (row["qty"] + qty, (note if note is not None else row.get("note")), row["id"]))
    else:
        db.run("INSERT INTO wc_stock (wine_id, place_id, qty, note) VALUES (?, ?, ?, ?)", (wid, pid, qty, note or ""))


def _stock_take(wid, pid, qty):
    row = _stock_row(wid, pid)
    have = row["qty"] if row else 0
    if have < qty:
        raise ApiError(409, "There are not that many bottles in " + get_place(pid)["name"])
    if have == qty:
        db.run("DELETE FROM wc_stock WHERE id = ?", (row["id"],))
    else:
        db.run("UPDATE wc_stock SET qty = ? WHERE id = ?", (have - qty, row["id"]))


def normalize_stock(wid):
    """Never let the places hold more bottles than the wine has. Takes from the biggest place first."""
    q = db.run("SELECT quantity FROM wc_wines WHERE id = ?", (wid,), fetch="one")
    if not q:
        return
    rows = db.run("SELECT id, qty FROM wc_stock WHERE wine_id = ? ORDER BY qty DESC, id", (wid,), fetch="all")
    over = sum(r["qty"] for r in rows) - (q["quantity"] or 0)
    for r in rows:
        if over <= 0:
            break
        cut = min(over, r["qty"])
        if cut == r["qty"]:
            db.run("DELETE FROM wc_stock WHERE id = ?", (r["id"],))
        else:
            db.run("UPDATE wc_stock SET qty = ? WHERE id = ?", (r["qty"] - cut, r["id"]))
        over -= cut


def _place_arg(v, label="Place"):
    """A place id, or None for 'not placed'."""
    if v in (None, "", "unplaced"):
        return None
    pid = clean_int(v, 1, 10 ** 12, label)
    get_place(pid)
    return pid


def move_stock(wid, data):
    r = get_wine(wid)
    src = _place_arg(data.get("from"), "From")
    dst = _place_arg(data.get("to"), "To")
    qty = clean_int(data.get("qty", 1), 1, 9999, "Bottles")
    note = txt(data.get("note"), 100) if "note" in data else None
    if src == dst and note is None:
        raise ApiError(400, "Choose two different places")
    with db.lock:
        placed = sum(s["qty"] for s in db.run("SELECT qty FROM wc_stock WHERE wine_id = ?", (wid,), fetch="all"))
        if src is None:
            if (r["quantity"] or 0) - placed < qty:
                raise ApiError(409, "There are not that many bottles without a place")
        else:
            _stock_take(wid, src, qty)
        if dst is not None:
            _stock_add(wid, dst, qty, note)
    return wine_json(get_wine(wid))


def bulk_move(data):
    """Move bottles for many wines at once (the wines currently shown). from: 'unplaced', 'any' or a place id."""
    ids = data.get("wineIds")
    if not isinstance(ids, list) or not ids or len(ids) > 5000:
        raise ApiError(400, "Choose at least one wine")
    src = data.get("from")
    if src not in ("unplaced", "any"):
        src = _place_arg(src, "From")
        if src is None:
            raise ApiError(400, "Choose where the bottles are now")
    dst = _place_arg(data.get("to"), "To")
    if dst is None and src == "unplaced":
        raise ApiError(400, "Choose a place to move them to")
    moved = wines_n = 0
    with db.lock:
        for raw in ids:
            if not str(raw).isdigit():
                continue
            wid = int(raw)
            w = db.run("SELECT quantity FROM wc_wines WHERE id = ?", (wid,), fetch="one")
            if not w:
                continue
            stock = {x["place_id"]: x["qty"] for x in db.run("SELECT place_id, qty FROM wc_stock WHERE wine_id = ?", (wid,), fetch="all")}
            free = (w["quantity"] or 0) - sum(stock.values())
            take = {}   # place id -> bottles
            n_free = 0
            if src == "unplaced":
                n_free = max(0, free)
            elif src == "any":
                take = {k: v for k, v in stock.items() if k != dst}
                n_free = max(0, free)
            else:
                if src != dst and stock.get(src):
                    take = {src: stock[src]}
            n = sum(take.values()) + n_free
            if not n:
                continue
            for pid, q in take.items():
                _stock_take(wid, pid, q)
            if dst is not None:
                _stock_add(wid, dst, n)
            moved += n
            wines_n += 1
    return {"moved": moved, "wines": wines_n}


def set_stock_note(wid, pid, data):
    get_wine(wid)
    row = _stock_row(wid, pid)
    if not row:
        raise ApiError(404, "This wine is not stored in that place")
    db.run("UPDATE wc_stock SET note = ? WHERE id = ?", (txt(data.get("note"), 100), row["id"]))
    return wine_json(get_wine(wid))


def stock_after_adjust(wid, delta, place, newq):
    """Keep the places in step with a changed bottle count."""
    if place is not None:
        if delta < 0:
            _stock_take(wid, place, -delta)
        else:
            _stock_add(wid, place, delta)
    elif delta < 0:
        normalize_stock(wid)


def enable_places():
    """First time the switch goes on: every distinct shelf text becomes a place holding that wine's bottles."""
    if db.run("SELECT COUNT(*) AS n FROM wc_places", fetch="one")["n"]:
        return 0
    made = {}
    for w in db.run("SELECT id, quantity, location FROM wc_wines WHERE quantity > 0 ORDER BY id", fetch="all"):
        loc = txt(w.get("location"), 60)
        if not loc:
            continue
        key = loc.lower()
        if key not in made:
            n = len(made) + 1
            db.run("INSERT INTO wc_places (name, kind, pos) VALUES (?, ?, ?)", (loc, guess_kind(loc), n))
            made[key] = db.run("SELECT id FROM wc_places WHERE name = ?", (loc,), fetch="one")["id"]
        _stock_add(w["id"], made[key], w["quantity"])
    return len(made)


def place_for_import(name, cache):
    key = name.strip().lower()
    if key not in cache:
        ex = None
        for p in db.run("SELECT id, name FROM wc_places", fetch="all"):
            if p["name"].strip().lower() == key:
                ex = p["id"]
        if ex is None:
            n = db.run("SELECT COALESCE(MAX(pos), 0) AS m FROM wc_places", fetch="one")["m"]
            db.run("INSERT INTO wc_places (name, kind, pos) VALUES (?, ?, ?)", (name[:60], guess_kind(name), n + 1))
            ex = db.run("SELECT id FROM wc_places WHERE name = ?", (name[:60],), fetch="one")["id"]
        cache[key] = ex
    return cache[key]


# ---------------------------------------------------------------- export, backup, stats views
EXPORT_COLUMNS = ["iWine", "Type", "Color", "Category", "Size", "Currency", "Value", "Price", "Quantity", "Vintage", "Wine", "Producer",
                  "Varietal", "Designation", "Vineyard", "Country", "Region", "SubRegion", "Appellation", "BeginConsume", "EndConsume",
                  "LikeVotes", "LikePercent", "Location", "Bin", "Notes", "EAN"]


def export_csv():
    """Same column names as CellarTracker, so the file can be imported again (here or in CellarTracker).
    A wine kept in several places gets one row per place (Location = the place, Bin = the shelf note)."""
    sm = stock_map() if places_on() else {}
    names = {p["id"]: p["name"] for p in db.run("SELECT id, name FROM wc_places", fetch="all")}
    out = io.StringIO()
    wr = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    wr.writerow(EXPORT_COLUMNS)
    for r in db.run("SELECT * FROM wc_wines ORDER BY id", fetch="all"):
        t = r.get("type") or r["color"]
        cat = t.split(" - ", 1)[1] if " - " in t else "Dry"
        parts = [(names.get(s["placeId"], ""), s["note"], s["qty"]) for s in sm.get(r["id"], [])]
        rest = (r.get("quantity") or 0) - sum(p[2] for p in parts)
        if not parts:
            parts = [(r.get("location") or "", "", r.get("quantity") or 0)]
        elif rest > 0:
            parts.append(("", "", rest))
        for loc, bin_, n in parts:
            wr.writerow([
                r.get("iwine") or "wc-%d" % r["id"], t, r["color"], cat, r.get("size") or "750ml", r.get("currency") or "EUR",
                "%g" % (r.get("value") or 0), "%g" % (r.get("price") or 0), n,
                r["vintage"] if r.get("vintage") else 1001, r.get("wine") or "", r["producer"], r.get("varietal") or "",
                r.get("designation") or "", r.get("vineyard") or "", r.get("country") or "", r.get("region") or "",
                r.get("subregion") or "", r.get("appellation") or "", r.get("begin_consume") or "", r.get("end_consume") or "",
                r.get("like_votes") or 0, "" if r.get("like_percent") is None else "%g" % r["like_percent"],
                loc, bin_, r.get("notes") or "", r.get("ean") or "",
            ])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


# ---------------------------------------------------------------- tags
def tag_json(r):
    return {"id": r["id"], "wineId": r["wine_id"], "kind": r["kind"], "occasion": r.get("occasion") or "", "who": r.get("who") or "",
            "date": r.get("date") or "", "yearly": bool(r.get("yearly")), "note": r.get("note") or ""}


def clean_date(v):
    v = txt(v, 10)
    if not v:
        return ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        raise ApiError(400, "Date must look like 2026-12-24")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError(400, "That date does not exist")
    return v


def add_tag(wid, data):
    get_wine(wid)
    kind = txt(data.get("kind"), 20)
    if kind not in TAG_KINDS:
        raise ApiError(400, "Kind must be one of: " + ", ".join(TAG_KINDS))
    occ = txt(data.get("occasion"), 20).lower()
    if occ and occ not in OCCASIONS:
        raise ApiError(400, "Occasion must be one of: " + ", ".join(OCCASIONS))
    date = clean_date(data.get("date"))
    yearly = 1 if (data.get("yearly") and date) else 0
    r = db.run(
        "INSERT INTO wc_tags (wine_id, kind, occasion, who, date, yearly, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (wid, kind, occ, txt(data.get("who"), 80), date, yearly, txt(data.get("note"), 300), now()), fetch="one")
    return tag_json(db.run("SELECT * FROM wc_tags WHERE id = ?", (r["id"],), fetch="one"))


def list_tags(wid=None):
    if wid is None:
        rows = db.run("SELECT * FROM wc_tags ORDER BY id", fetch="all")
    else:
        rows = db.run("SELECT * FROM wc_tags WHERE wine_id = ? ORDER BY id", (wid,), fetch="all")
    return [tag_json(r) for r in rows]


def delete_tag(tid):
    if not db.run("SELECT id FROM wc_tags WHERE id = ?", (tid,), fetch="one"):
        raise ApiError(404, "Tag not found")
    db.run("DELETE FROM wc_tags WHERE id = ?", (tid,))
    return {"deleted": tid}


# ---------------------------------------------------------------- reviews
def review_json(r):
    sc, scale = r.get("score"), r.get("scale") or 100
    return {"id": r["id"], "wineId": r["wine_id"], "kind": r["kind"], "source": r.get("source") or "", "score": sc, "scale": scale,
            "score100": None if sc is None else round(sc * 100.0 / scale, 1), "text": r.get("text") or "", "url": r.get("url") or "", "date": r.get("date") or ""}


def add_review(wid, data):
    get_wine(wid)
    kind = txt(data.get("kind"), 20)
    if kind not in REVIEW_KINDS:
        raise ApiError(400, "Kind must be critic or community")
    source = txt(data.get("source"), 80)
    if not source:
        raise ApiError(400, "Say where the review is from (for example Wine Advocate)")
    scale = int(num(data.get("scale"), 100) or 100)
    if scale not in (5, 10, 20, 100):
        raise ApiError(400, "Scale must be 5, 10, 20 or 100")
    raw = data.get("score")
    score = None
    if raw not in (None, ""):
        score = num(raw, None)
        if score is None or score < 0 or score > scale:
            raise ApiError(400, "Score must be between 0 and %d" % scale)
    text = txt(data.get("text"), 2000)
    if score is None and not text:
        raise ApiError(400, "Add a score or a few words")
    url = txt(data.get("url"), 300)
    if url and not re.match(r"^https?://", url, re.I):
        raise ApiError(400, "The link must start with http:// or https://")
    r = db.run(
        "INSERT INTO wc_reviews (wine_id, kind, source, score, scale, text, url, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (wid, kind, source, score, scale, text, url, clean_date(data.get("date")), now()), fetch="one")
    return review_json(db.run("SELECT * FROM wc_reviews WHERE id = ?", (r["id"],), fetch="one"))


def list_reviews(wid):
    get_wine(wid)
    rows = db.run("SELECT * FROM wc_reviews WHERE wine_id = ? ORDER BY id DESC", (wid,), fetch="all")
    out = [review_json(r) for r in rows]
    w = get_wine(wid)
    summ = {}
    for kind in REVIEW_KINDS:
        sc = [x["score100"] for x in out if x["kind"] == kind and x["score100"] is not None]
        summ[kind] = {"count": len([x for x in out if x["kind"] == kind]), "avg100": round(sum(sc) / len(sc), 1) if sc else None}
    summ["like"] = {"percent": w.get("like_percent"), "votes": w.get("like_votes")}
    iw = str(w.get("iwine") or "")
    summ["cellartrackerUrl"] = "https://www.cellartracker.com/wine.asp?iWine=" + iw if iw.isdigit() else ""
    return {"reviews": out, "summary": summ}


def delete_review(rid):
    if not db.run("SELECT id FROM wc_reviews WHERE id = ?", (rid,), fetch="one"):
        raise ApiError(404, "Review not found")
    db.run("DELETE FROM wc_reviews WHERE id = ?", (rid,))
    return {"deleted": rid}


# ---------------------------------------------------------------- app settings (country, currency, units)
def app_settings():
    d = {"country": "", "currency": "EUR", "tempUnit": "C", "formats": "auto", "paper": "A4", "sekRate": EUR_SEK, "places": False, "shelfNotes": False}
    try:
        saved = json.loads(meta_get("app_settings") or "null")
    except ValueError:
        saved = None
    if isinstance(saved, dict):
        d.update({k: v for k, v in saved.items() if k in d})
    return d, isinstance(saved, dict)


def settings_json():
    d, saved = app_settings()
    return dict(d, saved=saved, countries=[{"code": c[0], "name": c[1], "currency": c[2], "locale": c[3]} for c in COUNTRIES], currencies=CURRENCIES)


def _c_to_f(v):
    return round(v * 9.0 / 5.0 + 32.0, 1)


def _f_to_c(v):
    return round((v - 32.0) * 5.0 / 9.0, 1)


def save_app_settings(data):
    cur, _ = app_settings()
    new = dict(cur)
    if "country" in data:
        v = txt(data.get("country"), 2).upper()
        if v and v not in COUNTRY_CODES:
            raise ApiError(400, "Unknown country")
        new["country"] = v
    if "currency" in data:
        v = txt(data.get("currency"), 3).upper()
        if v not in CURRENCIES:
            raise ApiError(400, "Unknown currency")
        new["currency"] = v
    if "tempUnit" in data:
        if data.get("tempUnit") not in ("C", "F"):
            raise ApiError(400, "Temperature unit must be C or F")
        new["tempUnit"] = data["tempUnit"]
    if "formats" in data:
        if data.get("formats") not in ("auto", "country"):
            raise ApiError(400, "Number and date format must be auto or country")
        new["formats"] = data["formats"]
    if "paper" in data:
        if data.get("paper") not in ("A4", "Letter"):
            raise ApiError(400, "Paper must be A4 or Letter")
        new["paper"] = data["paper"]
    if "sekRate" in data:
        v = num(data.get("sekRate"), None)
        if v is None or v <= 0 or v > 100000:
            raise ApiError(400, "The exchange rate to SEK must be a positive number")
        new["sekRate"] = v
    for key in ("places", "shelfNotes"):
        if key in data:
            new[key] = bool(data.get(key))
    made = 0
    if new["places"] and not cur["places"]:
        made = enable_places()
    converted = 0
    if new["currency"] != cur["currency"] and data.get("convertRate") not in (None, ""):
        rate = num(data.get("convertRate"), None)
        if rate is None or rate <= 0 or rate > 1000000:
            raise ApiError(400, "The conversion rate must be a positive number")
        rows = db.run("SELECT id, price, value FROM wc_wines", fetch="all")
        for r in rows:
            db.run("UPDATE wc_wines SET price = ?, value = ?, currency = ?, updated_at = ? WHERE id = ?",
                   (round((r["price"] or 0) * rate, 2), round((r["value"] or 0) * rate, 2), new["currency"], now(), r["id"]))
        converted = len(rows)
    elif new["currency"] != cur["currency"]:
        db.run("UPDATE wc_wines SET currency = ?", (new["currency"],))
    if new["tempUnit"] != cur["tempUnit"]:
        cs = climate_settings()
        f = _c_to_f if new["tempUnit"] == "F" else _f_to_c
        cs["tempMin"], cs["tempMax"] = f(cs["tempMin"]), f(cs["tempMax"])
        meta_set("climate_settings", json.dumps(cs))
        _climate_cache.update(t=0, v=None)
    meta_set("app_settings", json.dumps(new))
    out = settings_json()
    out["converted"] = converted
    out["placesMade"] = made
    return out


# ---------------------------------------------------------------- cellar climate (from Home Assistant)
_climate_cache = {"t": 0, "v": None}
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
NOTIFY_RE = re.compile(r"^notify\.[a-z0-9_]+$")


def climate_settings():
    """What the person chose in the Cellar climate menu. Options from older versions (environment) are the starting point."""
    d = {"tempEntity": CLIMATE_TEMP, "humidityEntity": CLIMATE_HUM, "tempMin": TEMP_MIN, "tempMax": TEMP_MAX,
         "humidityMin": HUM_MIN, "humidityMax": HUM_MAX, "show": True, "notify": False, "notifyService": ""}
    try:
        saved = json.loads(meta_get("climate_settings") or "{}")
    except ValueError:
        saved = {}
    if isinstance(saved, dict):
        d.update({k: v for k, v in saved.items() if k in d})
    return d


def save_climate_settings(data):
    cur = climate_settings()
    for key, pat in (("tempEntity", ENTITY_RE), ("humidityEntity", ENTITY_RE)):
        if key in data:
            v = txt(data.get(key), 80).lower()
            if v and not pat.match(v):
                raise ApiError(400, "That does not look like a sensor name. It should look like sensor.cellar_temperature")
            cur[key] = v
    if "notifyService" in data:
        v = txt(data.get("notifyService"), 80).lower()
        if v and not NOTIFY_RE.match(v):
            raise ApiError(400, "The notification service should look like notify.mobile_app_my_phone, or be empty for a message inside Home Assistant")
        cur["notifyService"] = v
    for key in ("show", "notify"):
        if key in data:
            cur[key] = bool(data.get(key))
    for lo, hi, what in (("tempMin", "tempMax", "temperature"), ("humidityMin", "humidityMax", "humidity")):
        for key in (lo, hi):
            if key in data:
                v = num(data.get(key), None)
                if v is None:
                    raise ApiError(400, "The %s limits must be numbers" % what)
                cur[key] = v
        if cur[lo] >= cur[hi]:
            raise ApiError(400, "The lowest %s must be below the highest" % what)
    meta_set("climate_settings", json.dumps(cur))
    _climate_cache.update(t=0, v=None)
    _alerted.clear()
    return cur


def _ha_get(path):
    req = urllib.request.Request(HA_API + path, headers={"Authorization": "Bearer " + HA_TOKEN, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _ha_post(path, body):
    req = urllib.request.Request(HA_API + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + HA_TOKEN, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as r:
        r.read()


def list_sensors():
    """Temperature and humidity sensors Home Assistant knows about, for the picker."""
    try:
        states = _ha_get("/states")
    except (urllib.error.URLError, OSError, ValueError):
        raise ApiError(502, "Could not reach Home Assistant. You can still type the sensor name yourself.")
    out = {"temperature": [], "humidity": [], "other": []}
    for st in states if isinstance(states, list) else []:
        eid = st.get("entity_id", "")
        if not eid.startswith("sensor."):
            continue
        at = st.get("attributes") or {}
        try:
            float(st.get("state"))
            numeric = True
        except (TypeError, ValueError):
            numeric = False
        item = {"entity": eid, "name": at.get("friendly_name") or eid, "state": st.get("state"), "unit": at.get("unit_of_measurement", "")}
        cls = at.get("device_class")
        if cls == "temperature":
            out["temperature"].append(item)
        elif cls == "humidity":
            out["humidity"].append(item)
        elif numeric:
            out["other"].append(item)
    for k in out:
        out[k].sort(key=lambda x: x["name"].lower())
    out["other"] = out["other"][:300]
    return out


def _unit_converter(unit, want):
    u = (unit or "").replace("\u00b0", "").strip().upper()
    if want == "F" and u == "C":
        return _c_to_f
    if want == "C" and u == "F":
        return _f_to_c
    return None


def _reading(entity, lo, hi, start_iso, want=None):
    out = {"entity": entity, "value": None, "unit": "", "status": "unavailable", "min24": None, "max24": None, "series": []}
    st = None
    try:
        st = _ha_get("/states/" + quote(entity, safe="._"))
        out["unit"] = (st.get("attributes") or {}).get("unit_of_measurement", "")
        out["name"] = (st.get("attributes") or {}).get("friendly_name", entity)
        v = float(st.get("state"))
        conv = _unit_converter(out["unit"], want)
        if conv:
            v = conv(v)
            out["unit"] = "\u00b0" + want
        out["value"] = round(v, 1) if conv else v
        out["status"] = "low" if v < lo else ("high" if v > hi else "ok")
    except (ValueError, TypeError, KeyError):
        pass
    except (urllib.error.URLError, OSError):
        out["status"] = "offline"
        return out
    try:
        hist = _ha_get("/history/period/%s?filter_entity_id=%s&minimal_response&no_attributes" % (quote(start_iso, safe=""), quote(entity, safe="._")))
        pts = []
        for p in (hist[0] if hist else []):
            try:
                pts.append(float(p.get("state")))
            except (ValueError, TypeError):
                continue
        conv2 = _unit_converter((st.get("attributes") or {}).get("unit_of_measurement", ""), want) if st else None
        if conv2:
            pts = [conv2(x) for x in pts]
        if pts:
            out["min24"], out["max24"] = min(pts), max(pts)
            step = max(1, len(pts) // 48)
            out["series"] = [round(x, 1) for x in pts[::step]]
    except Exception:
        pass
    return out


def climate(force=False):
    cs = climate_settings()
    if not (cs["tempEntity"] or cs["humidityEntity"]):
        return {"configured": False, "settings": cs}
    if not force and time.time() - _climate_cache["t"] < 60 and _climate_cache["v"]:
        return _climate_cache["v"]
    start = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    res = {"configured": True, "show": cs["show"], "settings": cs, "limits": {"temp": [cs["tempMin"], cs["tempMax"]], "humidity": [cs["humidityMin"], cs["humidityMax"]]}, "temp": None, "humidity": None}
    if cs["tempEntity"]:
        res["temp"] = _reading(cs["tempEntity"], cs["tempMin"], cs["tempMax"], start, app_settings()[0]["tempUnit"])
    if cs["humidityEntity"]:
        res["humidity"] = _reading(cs["humidityEntity"], cs["humidityMin"], cs["humidityMax"], start)
    _climate_cache.update(t=time.time(), v=res)
    return res


_alerted = {}
RENOTIFY_SECS = float(os.environ.get("CLIMATE_RENOTIFY_SECS", str(6 * 3600)))
CHECK_SECS = float(os.environ.get("CLIMATE_CHECK_SECS", "300"))


def send_notification(title, message, service="", nid="wine_cellar_climate"):
    if service:
        _ha_post("/services/notify/" + service.split(".", 1)[1], {"title": title, "message": message})
    else:
        _ha_post("/services/persistent_notification/create", {"title": title, "message": message, "notification_id": nid})


def climate_alarm_check():
    """One pass: tell the person once when a reading goes outside its range, again only after RENOTIFY_SECS, and forget it when it is back in range."""
    cs = climate_settings()
    if not cs["notify"]:
        return
    res = climate(force=True)
    if not res.get("configured"):
        return
    for key, label in (("temp", "Temperature"), ("humidity", "Humidity")):
        x = res.get(key)
        if not x:
            continue
        if x["status"] in ("low", "high"):
            last = _alerted.get(key)
            if last is None or time.time() - last >= RENOTIFY_SECS:
                lim = res["limits"][key]
                msg = "%s in the wine cellar is %s %s, %s the wanted range %s to %s." % (label, x["value"], x["unit"], "below" if x["status"] == "low" else "above", lim[0], lim[1])
                try:
                    send_notification("Wine cellar: %s %s" % (label.lower(), "too low" if x["status"] == "low" else "too high"), msg, cs["notifyService"], "wine_cellar_" + key)
                    _alerted[key] = time.time()
                except Exception as e:
                    log("Could not send the climate alert:", type(e).__name__)
        elif x["status"] == "ok":
            _alerted.pop(key, None)


def climate_worker():
    time.sleep(min(30.0, CHECK_SECS))
    while True:
        try:
            climate_alarm_check()
        except Exception as e:
            log("Climate check error:", type(e).__name__, str(e)[:160])
        time.sleep(CHECK_SECS)


# ---------------------------------------------------------------- weekly drink alert
ALERT_DEFAULT = {"enabled": False, "notifyService": "", "weekday": 4, "hour": 16}  # Friday afternoon, before the weekend (0 is Monday)
_alert_retry = [0.0]
_tz_cache = {"t": 0.0, "tz": None}


def alert_settings():
    d = dict(ALERT_DEFAULT)
    try:
        saved = json.loads(meta_get("drink_alerts") or "{}")
    except ValueError:
        saved = {}
    if isinstance(saved, dict):
        d.update({k: v for k, v in saved.items() if k in d})
    return d


def save_alert_settings(data):
    cur = alert_settings()
    if "enabled" in data:
        cur["enabled"] = bool(data.get("enabled"))
    if "notifyService" in data:
        v = txt(data.get("notifyService"), 80).lower()
        if v and not NOTIFY_RE.match(v):
            raise ApiError(400, "The notification service should look like notify.mobile_app_my_phone, or be empty for a message inside Home Assistant")
        cur["notifyService"] = v
    if "weekday" in data:
        cur["weekday"] = clean_int(data.get("weekday"), 0, 6, "Day of the week")
    if "hour" in data:
        cur["hour"] = clean_int(data.get("hour"), 0, 23, "Hour")
    meta_set("drink_alerts", json.dumps(cur))
    return drink_alert_state()


def drink_groups(year=None):
    """Wines in stock that are in the last year of their window, and wines that are past it."""
    year = year or drink.this_year()
    soon, past = [], []
    for r in db.run("SELECT * FROM wc_wines WHERE quantity > 0", fetch="all"):
        s = drink.status(r.get("begin_consume"), r.get("end_consume"), year)
        if s == "soon":
            soon.append(r)
        elif s == "past":
            past.append(r)
    soon.sort(key=lambda r: label_of(r).lower())
    past.sort(key=lambda r: (-(r.get("end_consume") or 0), label_of(r).lower()))
    return soon, past


def _bottles(rows):
    return sum(r["quantity"] or 0 for r in rows)


def _line(r):
    q = r["quantity"] or 0
    return label_of(r) + (" ×%d" % q if q > 1 else "")


def drink_digest_text(soon, past, cap=8):
    parts = []
    for title, rows in (("Best this year", soon), ("Past their window", past)):
        if not rows:
            continue
        n = _bottles(rows)
        lines = ["• " + _line(r) for r in rows[:cap]]
        if len(rows) > cap:
            lines.append("and %d more wines" % (len(rows) - cap))
        parts.append("%s (%d %s):\n%s" % (title, n, "bottle" if n == 1 else "bottles", "\n".join(lines)))
    return "\n\n".join(parts)


def drink_alert_state():
    soon, past = drink_groups()
    return dict(alert_settings(), soonBottles=_bottles(soon), pastBottles=_bottles(past), preview=drink_digest_text(soon, past))


def send_drink_alert(test=False):
    """Send the digest. Nothing is sent when there is nothing to report, unless it is a test."""
    soon, past = drink_groups()
    text = drink_digest_text(soon, past)
    title = "Wine cellar: time to drink"
    if not text:
        if not test:
            return {"sent": False, "message": ""}
        title, text = "Wine cellar: test", "No bottle is past its window or in the last year of it right now. Alerts are working."
    send_notification(title, text, alert_settings()["notifyService"], "wine_cellar_drink")
    return {"sent": True, "title": title, "message": text}


def local_now():
    """The time in the Home Assistant time zone. The add-on container itself usually runs in UTC."""
    if time.time() - _tz_cache["t"] > 3600:
        try:
            name = _ha_get("/config").get("time_zone")
            from zoneinfo import ZoneInfo
            _tz_cache.update(t=time.time(), tz=ZoneInfo(name) if name else None)
        except Exception:
            _tz_cache["t"] = time.time() - 3000  # try again in ten minutes
    tz = _tz_cache["tz"]
    return datetime.now(tz) if tz else datetime.now()


def drink_alert_check():
    """One pass of the weekly alert: on the chosen day, from the chosen hour, once."""
    st = alert_settings()
    if not st["enabled"] or time.time() < _alert_retry[0]:
        return False
    n = local_now()
    today = n.strftime("%Y-%m-%d")
    if n.weekday() != st["weekday"] or n.hour < st["hour"] or meta_get("drink_alert_last") == today:
        return False
    try:
        send_drink_alert()
    except Exception as e:
        log("Could not send the drink alert:", type(e).__name__)
        _alert_retry[0] = time.time() + 1800
        return False
    meta_set("drink_alert_last", today)
    return True


def drink_alert_worker():
    time.sleep(min(30.0, ALERT_CHECK_SECS))
    while True:
        try:
            drink_alert_check()
        except Exception as e:
            log("Drink alert error:", type(e).__name__, str(e)[:160])
        time.sleep(ALERT_CHECK_SECS)


# ---------------------------------------------------------------- Home Assistant sensors (MQTT discovery)
# key, name, icon, unit ("$" is the cellar currency)
HA_SENSORS = [
    ("bottles", "Bottles", "mdi:bottle-wine", "bottles"),
    ("wines", "Wines", "mdi:glass-wine", "wines"),
    ("ready", "Ready to drink", "mdi:check-circle-outline", "bottles"),
    ("drink_soon", "Drink this year", "mdi:clock-alert-outline", "bottles"),
    ("past_peak", "Past peak", "mdi:alert-circle-outline", "bottles"),
    ("hold", "Hold", "mdi:timer-sand", "bottles"),
    ("value", "Estimated value", "mdi:cash-multiple", "$"),
]
SENSOR_LISTS = {"drink_soon": "soonWines", "past_peak": "pastWines"}
STATE_TOPIC = "wine_cellar/state"
LIST_TOPIC = "wine_cellar/list/%s"
DISCOVERY_TOPIC = "homeassistant/sensor/wine_cellar/%s/config"
NO_BROKER = ("No MQTT broker was found. Install the Mosquitto broker add-on and add the MQTT integration in Home Assistant, then restart Wine Cellar.")
_sensors = {"hash": "", "sent": False, "unit": "", "last": None, "error": ""}
_sensors_lock = threading.Lock()


def sensors_enabled():
    try:
        return bool((json.loads(meta_get("ha_sensors") or "{}") or {}).get("enabled"))
    except ValueError:
        return False


def cellar_numbers():
    year = drink.this_year()
    out = {"bottles": 0, "wines": 0, "ready": 0, "drink_soon": 0, "past_peak": 0, "hold": 0, "value": 0.0}
    soon, past = [], []
    for r in db.run("SELECT * FROM wc_wines WHERE quantity > 0", fetch="all"):
        q = r["quantity"] or 0
        s = drink.status(r.get("begin_consume"), r.get("end_consume"), year)
        out["wines"] += 1
        out["bottles"] += q
        out["value"] += q * (r.get("value") or 0)
        if drink.is_ready(s):
            out["ready"] += q
        if s == "soon":
            out["drink_soon"] += q
            soon.append(r)
        elif s == "past":
            out["past_peak"] += q
            past.append(r)
        elif s == "hold":
            out["hold"] += q
    out["value"] = round(out["value"], 2)
    out["currency"] = app_settings()[0]["currency"]
    soon.sort(key=lambda r: label_of(r).lower())
    past.sort(key=lambda r: (-(r.get("end_consume") or 0), label_of(r).lower()))
    out["soonWines"] = [_line(r) for r in soon[:20]]
    out["pastWines"] = [_line(r) for r in past[:20]]
    return out


def mqtt_broker():
    """Where the MQTT broker is. Home Assistant tells the add-on through the Supervisor (config.yaml asks for the mqtt service)."""
    if MQTT_HOST:
        return {"host": MQTT_HOST, "port": MQTT_PORT, "user": MQTT_USER, "password": MQTT_PASSWORD, "ssl": False}
    if not HA_TOKEN:
        return None
    try:
        req = urllib.request.Request(SUPERVISOR_API + "/services/mqtt", headers={"Authorization": "Bearer " + HA_TOKEN, "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = (json.loads(r.read().decode("utf-8")) or {}).get("data") or {}
    except Exception:
        return None
    if not d.get("host"):
        return None
    return {"host": d["host"], "port": int(d.get("port") or 1883), "user": d.get("username") or "", "password": d.get("password") or "", "ssl": bool(d.get("ssl"))}


def _sensor_discovery(unit):
    dev = {"identifiers": ["wine_cellar"], "name": "Wine Cellar", "manufacturer": "Wine Cellar add-on", "model": "Cellar", "sw_version": VERSION}
    msgs = []
    for key, name, icon, u in HA_SENSORS:
        cfg = {"name": name, "unique_id": "wine_cellar_" + key, "state_topic": STATE_TOPIC, "value_template": "{{ value_json.%s }}" % key,
               "icon": icon, "state_class": "measurement", "unit_of_measurement": unit if u == "$" else u, "device": dev}
        if key in SENSOR_LISTS:
            cfg["json_attributes_topic"] = LIST_TOPIC % key
        msgs.append((DISCOVERY_TOPIC % key, json.dumps(cfg), True))
    return msgs


def _publish(msgs):
    b = mqtt_broker()
    if not b:
        raise mqtt.MqttError(NO_BROKER)
    mqtt.publish_all(b["host"], b["port"], msgs, b["user"], b["password"], b["ssl"])


def ha_sensors_publish(force=False):
    """Tell Home Assistant the numbers, when they changed. The entities are announced again after a restart or a currency change."""
    if not sensors_enabled():
        return False
    num = cellar_numbers()
    state = {k: num[k] for k, _, _, _ in HA_SENSORS}
    digest = json.dumps([state, num["soonWines"], num["pastWines"], num["currency"]], sort_keys=True)
    with _sensors_lock:
        announce = force or not _sensors["sent"] or _sensors["unit"] != num["currency"]
        if not announce and digest == _sensors["hash"]:
            return False
        msgs = _sensor_discovery(num["currency"]) if announce else []
        msgs.append((STATE_TOPIC, json.dumps(state), True))
        for key, field in SENSOR_LISTS.items():
            msgs.append((LIST_TOPIC % key, json.dumps({"wines": num[field]}), True))
        try:
            _publish(msgs)
        except mqtt.MqttError as e:
            _sensors.update(sent=False, hash="", error=str(e))
            raise
        _sensors.update(sent=True, hash=digest, unit=num["currency"], last=iso(now()), error="")
    return True


def ha_sensors_remove():
    """Empty retained messages make Home Assistant forget the entities."""
    msgs = [(DISCOVERY_TOPIC % key, b"", True) for key, _, _, _ in HA_SENSORS] + [(STATE_TOPIC, b"", True)] + [(LIST_TOPIC % k, b"", True) for k in SENSOR_LISTS]
    with _sensors_lock:
        _sensors.update(sent=False, hash="", unit="")
        _publish(msgs)


def ha_sensors_state():
    num = cellar_numbers()
    return {"enabled": sensors_enabled(), "broker": bool(mqtt_broker()), "last": _sensors["last"], "error": _sensors["error"],
            "values": {k: num[k] for k, _, _, _ in HA_SENSORS}, "currency": num["currency"], "entities": ["sensor.wine_cellar_" + k for k, _, _, _ in HA_SENSORS]}


def save_ha_sensors(data):
    want = bool(data.get("enabled"))
    warning = ""
    if want:
        if not mqtt_broker():
            raise ApiError(409, NO_BROKER)
        meta_set("ha_sensors", json.dumps({"enabled": True}))
        try:
            ha_sensors_publish(force=True)
        except mqtt.MqttError as e:
            meta_set("ha_sensors", json.dumps({"enabled": False}))
            raise ApiError(502, str(e))
    else:
        was = sensors_enabled()
        meta_set("ha_sensors", json.dumps({"enabled": False}))
        if was:
            try:
                ha_sensors_remove()
            except mqtt.MqttError as e:
                warning = "Switched off, but the sensors could not be removed from Home Assistant: %s. Delete them under Settings, Devices, MQTT if they stay." % e
    out = ha_sensors_state()
    out["warning"] = warning
    return out


def ha_sensors_worker():
    time.sleep(min(20.0, SENSORS_SECS))
    while True:
        try:
            ha_sensors_publish()
        except mqtt.MqttError as e:
            log("Could not update the Home Assistant sensors:", str(e)[:160])
        except Exception as e:
            log("Sensor update error:", type(e).__name__, str(e)[:160])
        time.sleep(SENSORS_SECS)


# ---------------------------------------------------------------- full copy and restore
def export_json(pictures=True):
    sm = stock_map()
    wines = [wine_json(r, sm.get(r["id"], [])) for r in db.run("SELECT * FROM wc_wines ORDER BY id", fetch="all")]
    pics = {r["wine_id"]: r for r in db.run("SELECT wine_id, source, mime, source_url, credit, data FROM wc_images WHERE data IS NOT NULL", fetch="all")}
    for w in wines:
        p = pics.get(w["id"])
        w["picture"] = p["source"] if p else ""
        if p and pictures:
            w.update(pictureMime=p.get("mime") or "image/jpeg", pictureUrl=p.get("source_url") or "", pictureCredit=p.get("credit") or "",
                     pictureData=base64.b64encode(bytes(p["data"])).decode("ascii"))
    checkins = db.run("SELECT * FROM wc_checkins ORDER BY id", fetch="all")
    for c in checkins:
        c["ts"] = iso(c.get("ts"))
    doc = {"app": "wine-cellar", "version": VERSION, "exported": iso(now()), "picturesIncluded": bool(pictures), "wines": wines, "checkins": checkins,
           "places": places_state(readings=False)["places"], "tags": list_tags(), "reviews": [review_json(r) for r in db.run("SELECT * FROM wc_reviews ORDER BY id", fetch="all")],
           "settings": {"app": app_settings()[0], "climate": climate_settings(), "alerts": alert_settings()}}
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def _int(v, default=None):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _rows(doc, key):
    v = doc.get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _restored_settings(saved):
    """Settings from a copy, checked one by one. Anything odd is left out, so the current value stays."""
    out = {}
    if not isinstance(saved, dict):
        return out
    a = saved.get("app")
    if isinstance(a, dict):
        d = {}
        if a.get("country") in COUNTRY_CODES or a.get("country") == "":
            d["country"] = a.get("country")
        if a.get("currency") in CURRENCIES:
            d["currency"] = a["currency"]
        if a.get("tempUnit") in ("C", "F"):
            d["tempUnit"] = a["tempUnit"]
        if a.get("formats") in ("auto", "country"):
            d["formats"] = a["formats"]
        if a.get("paper") in ("A4", "Letter"):
            d["paper"] = a["paper"]
        if num(a.get("sekRate"), None) and 0 < num(a.get("sekRate"), None) <= 100000:
            d["sekRate"] = num(a.get("sekRate"), None)
        for k in ("places", "shelfNotes"):
            if k in a:
                d[k] = bool(a[k])
        out["app_settings"] = dict(app_settings()[0], **d)
    c = saved.get("climate")
    if isinstance(c, dict):
        cur = climate_settings()
        for k in ("tempEntity", "humidityEntity"):
            v = txt(c.get(k), 80).lower()
            if k in c and (not v or ENTITY_RE.match(v)):
                cur[k] = v
        v = txt(c.get("notifyService"), 80).lower()
        if "notifyService" in c and (not v or NOTIFY_RE.match(v)):
            cur["notifyService"] = v
        for k in ("show", "notify"):
            if k in c:
                cur[k] = bool(c[k])
        for lo, hi in (("tempMin", "tempMax"), ("humidityMin", "humidityMax")):
            a1, b1 = num(c.get(lo), None), num(c.get(hi), None)
            if a1 is not None and b1 is not None and a1 < b1:
                cur[lo], cur[hi] = a1, b1
        out["climate_settings"] = cur
    al = saved.get("alerts")
    if isinstance(al, dict):
        cur = alert_settings()
        v = txt(al.get("notifyService"), 80).lower()
        if "notifyService" in al and (not v or NOTIFY_RE.match(v)):
            cur["notifyService"] = v
        if "enabled" in al:
            cur["enabled"] = bool(al["enabled"])
        for k, hi in (("weekday", 6), ("hour", 23)):
            n = _int(al.get(k))
            if n is not None and 0 <= n <= hi:
                cur[k] = n
        out["drink_alerts"] = cur
    return out


def restore_backup(raw, confirm=""):
    """Replace everything in the cellar with a full copy made by this add-on. All or nothing."""
    if confirm != "replace":
        raise ApiError(400, "Restoring replaces everything in the cellar. Confirm to go on.")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "That file is not a Wine Cellar copy. It is not valid JSON.")
    if not isinstance(doc, dict) or doc.get("app") != "wine-cellar" or not isinstance(doc.get("wines"), list):
        raise ApiError(400, "That file is not a full copy made by Wine Cellar (Import / export, Download full copy).")
    stamp = now()
    skipped = 0
    place_rows, place_ids = [], set()
    for i, p in enumerate(_rows(doc, "places")):
        pid, name = _int(p.get("id")), txt(p.get("name"), 80)
        if not pid or pid <= 0 or pid in place_ids or not name:
            skipped += 1
            continue
        place_ids.add(pid)
        kind = p.get("kind") if p.get("kind") in PLACE_KINDS else "other"
        place_rows.append((pid, name, kind, i, txt(p.get("tempEntity"), 80) or None, txt(p.get("humEntity"), 80) or None))
    wine_rows, stock_rows, image_rows, wine_ids, iwines, stocked = [], [], [], set(), set(), {}
    for w in _rows(doc, "wines"):
        wid, producer = _int(w.get("id")), txt(w.get("producer"), 200)
        if not wid or wid <= 0 or wid in wine_ids or not producer:
            skipped += 1
            continue
        wine_ids.add(wid)
        color = w.get("color") if w.get("color") in COLORS else "Red"
        vin = _int(w.get("vintage"))
        vin = vin if vin and 1000 < vin < 3000 else None
        iw = txt(w.get("iwine"), 40) or None
        if iw in iwines:
            iw = None
        if iw:
            iwines.add(iw)
        window = []
        for k in ("begin", "end"):
            y = _int(w.get(k))
            window.append(y if y and 1000 < y < 3000 else None)
        lp = num(w.get("likePercent"), None)
        qty = max(0, min(_int(w.get("quantity"), 0), 99999))
        ean = re.sub(r"\D", "", str(w.get("ean") or ""))
        wine_rows.append((wid, iw, color, txt(w.get("type"), 80) or color, vin, producer, txt(w.get("wine"), 300), txt(w.get("varietal"), 300),
                          txt(w.get("designation"), 300), txt(w.get("vineyard"), 300), txt(w.get("country"), 300), txt(w.get("region"), 300),
                          txt(w.get("subregion"), 300), txt(w.get("appellation"), 300), txt(w.get("size"), 40) or "750ml", txt(w.get("currency"), 8) or "EUR",
                          max(0.0, num(w.get("value"))), max(0.0, num(w.get("price"))), qty, window[0], window[1], lp, _int(w.get("likeVotes"), 0),
                          txt(w.get("location"), 300), txt(w.get("notes"), 2000), ean if 8 <= len(ean) <= 14 else "", stamp, stamp))
        have = {}
        for s in (w.get("stock") if isinstance(w.get("stock"), list) else []):
            pid, q = _int(s.get("placeId")) if isinstance(s, dict) else None, _int(s.get("qty"), 0) if isinstance(s, dict) else 0
            if pid in place_ids and q and q > 0:
                have[pid] = (have.get(pid, (0, ""))[0] + q, txt(s.get("note"), 300))
        for pid, (q, note) in have.items():
            stock_rows.append((wid, pid, q, note))
        stocked[wid] = sum(q for q, _ in have.values())
        if w.get("pictureData"):
            try:
                data = base64.b64decode(str(w["pictureData"]), validate=True)
            except (ValueError, TypeError):
                data = b""
            mime = str(w.get("pictureMime") or "")
            if data and len(data) <= IMG_MAX and mime in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                src = w.get("picture") if w.get("picture") in ("upload", "web") else "upload"
                image_rows.append((wid, data, mime, src, txt(w.get("pictureUrl"), 500) or None, txt(w.get("pictureCredit"), 300) or None, stamp))
    checkin_rows = []
    for c in _rows(doc, "checkins"):
        cid, delta = _int(c.get("id")), _int(c.get("delta"))
        if not cid or cid <= 0 or delta is None or not txt(c.get("kind"), 20):
            skipped += 1
            continue
        wid = _int(c.get("wine_id"))
        r = num(c.get("rating"), None)
        checkin_rows.append((cid, wid if wid in wine_ids else None, txt(c.get("label"), 300), txt(c.get("kind"), 20), delta, r, txt(c.get("note"), 2000),
                             txt(c.get("ts"), 40) or iso(stamp)))
    tag_rows = []
    for t in _rows(doc, "tags"):
        tid, wid = _int(t.get("id")), _int(t.get("wineId"))
        if not tid or tid <= 0 or wid not in wine_ids or t.get("kind") not in TAG_KINDS:
            skipped += 1
            continue
        tag_rows.append((tid, wid, t["kind"], txt(t.get("occasion"), 20), txt(t.get("who"), 80), txt(t.get("date"), 10), 1 if t.get("yearly") else 0, txt(t.get("note"), 300), stamp))
    review_rows = []
    for v in _rows(doc, "reviews"):
        rid, wid = _int(v.get("id")), _int(v.get("wineId"))
        if not rid or rid <= 0 or wid not in wine_ids or v.get("kind") not in REVIEW_KINDS:
            skipped += 1
            continue
        scale = _int(v.get("scale"), 100)
        review_rows.append((rid, wid, v["kind"], txt(v.get("source"), 80), num(v.get("score"), None), scale if scale in (5, 10, 20, 100) else 100,
                            txt(v.get("text"), 2000), txt(v.get("url"), 300), txt(v.get("date"), 10), stamp))
    settings = _restored_settings(doc.get("settings"))
    with db.lock:
        if db.conn is None:
            db.conn = db._connect()
        cur = db.conn.cursor()

        def put(sql, rows):
            for row in rows:
                cur.execute(db._sql(sql), db._args(row))
        try:
            for t in ("wc_stock", "wc_tags", "wc_reviews", "wc_checkins", "wc_images", "wc_prices", "wc_price_log", "wc_places", "wc_wines"):
                cur.execute("DELETE FROM " + t)
            put("INSERT INTO wc_places (id, name, kind, pos, temp_entity, hum_entity) VALUES (?, ?, ?, ?, ?, ?)", place_rows)
            put("INSERT INTO wc_wines (id, iwine, color, type, vintage, producer, wine, varietal, designation, vineyard, country, region, subregion, appellation, size, "
                "currency, value, price, quantity, begin_consume, end_consume, like_percent, like_votes, location, notes, ean, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", wine_rows)
            put("INSERT INTO wc_stock (wine_id, place_id, qty, note) VALUES (?, ?, ?, ?)", stock_rows)
            put("INSERT INTO wc_images (wine_id, data, mime, source, source_url, credit, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?)", image_rows)
            put("INSERT INTO wc_checkins (id, wine_id, label, kind, delta, rating, note, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", checkin_rows)
            put("INSERT INTO wc_tags (id, wine_id, kind, occasion, who, date, yearly, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tag_rows)
            put("INSERT INTO wc_reviews (id, wine_id, kind, source, score, scale, text, url, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", review_rows)
            if DB_TYPE != "sqlite":  # the next new row must not reuse an id that was restored
                for t in ("wc_wines", "wc_places", "wc_checkins", "wc_tags", "wc_reviews", "wc_stock"):
                    cur.execute("SELECT setval(pg_get_serial_sequence('%s', 'id'), COALESCE((SELECT MAX(id) FROM %s), 1))" % (t, t))
            db.conn.commit()
        except Exception:
            try:
                db.conn.rollback()
            except Exception:
                db.conn = None
            raise
    for key, val in settings.items():
        meta_set(key, json.dumps(val))
    for wid, n in stocked.items():
        if n > next((r[18] for r in wine_rows if r[0] == wid), 0):
            normalize_stock(wid)
    _climate_cache.update(t=0, v=None)
    _place_cache.clear()
    _alerted.clear()
    with _sensors_lock:
        _sensors["hash"] = ""
    return {"wines": len(wine_rows), "bottles": sum(r[18] for r in wine_rows), "places": len(place_rows), "checkins": len(checkin_rows),
            "pictures": len(image_rows), "tags": len(tag_rows), "reviews": len(review_rows), "skipped": skipped, "settings": sorted(settings)}


def make_views():
    """Read-only views for Grafana or any SQL client. Failure here must never stop the app."""
    pg = DB_TYPE != "sqlite"
    year = "EXTRACT(YEAR FROM CURRENT_DATE)" if pg else "CAST(strftime('%Y', 'now') AS INTEGER)"
    month = "to_char(ts, 'YYYY-MM')" if pg else "substr(ts, 1, 7)"
    views = {
        "wc_v_cellar": (
            "SELECT id, producer, wine, CASE WHEN vintage IS NULL OR vintage = 0 THEN NULL ELSE vintage END AS vintage, color, type, country, region, appellation, varietal, "
            "quantity, price, value, quantity * price AS paid_total, quantity * value AS value_total, begin_consume, end_consume, "
            "%s AS status, %s AS drink_status FROM wc_wines WHERE quantity > 0"
            % (drink.sql_case(year, {"nowin": "No window", "past": "Past peak", "hold": "Hold", "soon": "Ready", "ready": "Ready"}), drink.sql_case(year))),
        "wc_v_by_region": (
            "SELECT COALESCE(NULLIF(country, ''), 'Unknown') AS country, COALESCE(NULLIF(region, ''), 'Unknown') AS region, SUM(quantity) AS bottles, "
            "SUM(quantity * value) AS value_total, SUM(quantity * price) AS paid_total FROM wc_wines WHERE quantity > 0 GROUP BY 1, 2"),
        "wc_v_by_vintage": (
            "SELECT CASE WHEN vintage IS NULL OR vintage = 0 THEN 0 ELSE vintage END AS vintage, SUM(quantity) AS bottles, "
            "SUM(quantity * value) AS value_total FROM wc_wines WHERE quantity > 0 GROUP BY 1"),
        "wc_v_by_type": (
            "SELECT COALESCE(type, color) AS type, SUM(quantity) AS bottles, SUM(quantity * value) AS value_total FROM wc_wines WHERE quantity > 0 GROUP BY 1"),
        "wc_v_drunk_by_month": (
            "SELECT %s AS month, -SUM(delta) AS bottles, AVG(rating) AS avg_rating FROM wc_checkins WHERE kind = 'drink' GROUP BY 1" % month),
        "wc_v_place_contents": (
            "SELECT p.name AS place, p.kind, s.note AS bin, w.id AS wine_id, w.producer, w.wine, w.vintage, s.qty AS bottles FROM wc_stock s "
            "JOIN wc_places p ON p.id = s.place_id JOIN wc_wines w ON w.id = s.wine_id"),
    }
    for name, sql in views.items():
        try:
            db.run("DROP VIEW IF EXISTS " + name)
            db.run("CREATE VIEW " + name + " AS " + sql)
        except Exception as e:
            log("Could not create view %s: %s: %s" % (name, type(e).__name__, str(e)[:120]))


# ---------------------------------------------------------------- pictures
class NetError(Exception):
    pass


def sniff(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


_gap_lock = threading.Lock()
_last_call = [0.0]


def http_get(url, limit=2 * 1024 * 1024, trusted_host=True):
    """GET with a polite pause between calls. Only talks to the picture source."""
    host = urlparse(url).hostname or ""
    api_host = urlparse(IMG_API).hostname or ""
    ok = host == api_host or host.endswith(".openfoodfacts.org") or host == "openfoodfacts.org" or (IMG_TEST_HOST and host == IMG_TEST_HOST)
    if not ok or not url.startswith(("https://", "http://")):
        raise NetError("blocked host")
    with _gap_lock:
        wait = IMG_GAP - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, image/*"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise NetError("HTTP %d from %s" % (e.code, host))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise NetError("%s: %s" % (type(e).__name__, str(getattr(e, "reason", e))[:80]))
    if len(data) > limit:
        raise NetError("too large")
    return data


STOP = {
    "chateau", "domaine", "maison", "cave", "caves", "clos", "vins", "vin", "de", "du", "des", "la", "le", "les", "et", "the",
    "wine", "wines", "winery", "co", "estate", "famille", "bodegas", "bodega", "cantina", "weingut", "and", "of", "d", "l",
}


def tokens(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


GENERIC = {"rouge", "blanc", "rose", "red", "white", "sec", "dry", "brut", "demi", "doux", "moelleux", "vin", "cuvee", "reserve"}


def name_parts(w):
    """Producer words, 'generic' words (region, grape, colour...) and the wine's own distinctive name words."""
    ptoks_all = set(tokens(w["producer"]))
    gen = set(GENERIC)
    for k in ("appellation", "region", "subregion", "varietal", "country"):
        gen |= set(tokens(w.get(k) or ""))
    rest = [t for t in tokens(w.get("wine") or "") if t not in ptoks_all and t not in STOP and not t.isdigit() and t not in gen]
    return ptoks_all, gen, rest


def name_fits(w, ctoks):
    """True when a listing's words fit this wine: its distinctive words are there, and it adds no other distinctive words of its own."""
    ptoks_all, gen, rest = name_parts(w)
    if rest:
        return sum(1 for t in rest if t in ctoks) >= -(-len(rest) * 3 // 5)
    extra = {t for t in ctoks if t not in ptoks_all and t not in STOP and t not in gen and not t.isdigit()}
    return not extra


def pick_product(w, products):
    """Choose the Open Food Facts product that is really this wine, or None. Strict on purpose."""
    ptoks_all = tokens(w["producer"])
    ptoks = [t for t in ptoks_all if t not in STOP] or ptoks_all
    rest = name_parts(w)[2]
    vint = w.get("vintage")
    best = None
    for p in products:
        img = p.get("image_front_url") or p.get("image_front_small_url")
        if not img:
            continue
        cats = " ".join(p.get("categories_tags") or [])
        if not re.search(r"wine|champagne|cremant|alcoholic", cats):
            continue
        hay = set(tokens((p.get("brands") or "") + " " + (p.get("product_name") or "")))
        if not ptoks or not all(t in hay for t in ptoks):
            continue
        if not name_fits(w, hay):
            continue
        score = sum(1 for t in rest if t in hay)
        years = re.findall(r"\b(?:19|20)\d\d\b", p.get("product_name") or "")
        if vint and str(vint) in years:
            score += 3
        elif vint and years:
            score -= 1
        if best is None or score > best[0]:
            best = (score, p, img)
    return best


def product_query(path_qs):
    return json.loads(http_get(IMG_API + path_qs).decode("utf-8", "replace"))


FIELDS = "code,product_name,brands,categories_tags,image_front_url,image_front_small_url"


def off_search(w):
    rest = " ".join(t for t in (w.get("wine") or "").split() if t.lower() not in w["producer"].lower())
    queries = []
    for qtext in ((w["producer"] + " " + rest).strip(), w["producer"]):
        if qtext and qtext not in queries:
            queries.append(qtext)
    for qtext in queries[:2]:
        data = product_query("/cgi/search.pl?search_terms=%s&search_simple=1&action=process&json=1&page_size=12&fields=%s" % (quote(qtext[:120]), FIELDS))
        best = pick_product(w, data.get("products") or [])
        if best:
            return best[1], best[2]
    return None


def save_image(wid, data, source, url=None, credit=None):
    mime = sniff(data) if data else None
    db.run(
        "INSERT INTO wc_images (wine_id, data, mime, source, source_url, credit, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (wine_id) DO UPDATE SET data = EXCLUDED.data, mime = EXCLUDED.mime, source = EXCLUDED.source, "
        "source_url = EXCLUDED.source_url, credit = EXCLUDED.credit, checked_at = EXCLUDED.checked_at",
        (wid, data, mime, source, url, credit, now()),
    )


def find_picture(wid, force=False):
    """Look the wine up online. Returns True if a picture was saved. Raises NetError when the source is unreachable."""
    w = get_wine(wid)
    cur = db.run("SELECT source FROM wc_images WHERE wine_id = ?", (wid,), fetch="one")
    if cur and not force and cur["source"] in ("upload", "web", "removed"):
        return False
    hit = off_search(w)
    if not hit:
        if not cur or cur["source"] in ("none",):
            save_image(wid, None, "none")
        return False
    p, img_url = hit
    data = http_get(img_url)
    if not sniff(data):
        raise NetError("not an image")
    save_image(wid, data, "web", IMG_API + "/product/" + quote(str(p.get("code") or "")), "Open Food Facts (CC BY-SA)")
    return True


def lookup_ean(ean):
    ean = re.sub(r"\s+", "", str(ean or ""))
    if not (ean.isdigit() and 8 <= len(ean) <= 14):
        raise ApiError(400, "EAN must be 8 to 14 digits")
    mine = db.run(WINE_SELECT + " WHERE w.ean = ? ORDER BY w.id", (ean,), fetch="all")
    out = {"ean": ean, "mine": [wine_json(r) for r in mine], "product": None}
    if mine:
        return out
    try:
        data = product_query("/api/v2/product/%s.json?fields=%s,quantity" % (ean, FIELDS))
    except NetError:
        out["offline"] = True
        return out
    p = data.get("product") if data.get("status") == 1 else None
    if p:
        cats = " ".join(p.get("categories_tags") or [])
        name = (p.get("product_name") or "").strip()
        brand = (p.get("brands") or "").split(",")[0].strip()
        out["product"] = {"name": name[:200], "brand": brand[:200], "isWine": bool(re.search(r"wine|champagne|cremant|alcoholic", cats)),
                          "image": bool(p.get("image_front_url") or p.get("image_front_small_url")), "code": ean}
    return out


def attach_ean_picture(wid, ean):
    """Use the product picture for a freshly scanned wine, if there is one."""
    try:
        data = product_query("/api/v2/product/%s.json?fields=%s" % (ean, FIELDS))
        p = data.get("product") or {}
        url = p.get("image_front_url") or p.get("image_front_small_url")
        if url:
            img = http_get(url)
            if sniff(img):
                save_image(wid, img, "web", IMG_API + "/product/" + quote(ean), "Open Food Facts (CC BY-SA)")
    except (NetError, ValueError):
        pass


wake = threading.Event()


def image_worker():
    time.sleep(15)
    while True:
        wait = 3600
        try:
            if AUTO_IMAGES:
                todo = db.run(
                    "SELECT w.id FROM wc_wines w LEFT JOIN wc_images i ON i.wine_id = w.id "
                    "WHERE w.quantity > 0 AND (i.wine_id IS NULL OR (i.source = 'none' AND i.checked_at < ?)) ORDER BY w.id LIMIT 40",
                    (now() - timedelta(days=30),), fetch="all")
                for r in todo:
                    find_picture(r["id"])
                if todo:
                    wait = 5
        except NetError as e:
            log("Picture lookup paused, source not reachable (%s). Trying again in 10 minutes." % e)
            wait = 600
        except Exception as e:
            log("Picture lookup error:", type(e).__name__, str(e)[:160])
            wait = 300
        wake.wait(wait)
        wake.clear()


def get_image(wid):
    r = db.run("SELECT data, mime FROM wc_images WHERE wine_id = ? AND data IS NOT NULL", (wid,), fetch="one")
    if not r:
        raise ApiError(404, "No picture")
    return bytes(r["data"]), r["mime"] or "image/jpeg"


def upload_image(wid, data):
    get_wine(wid)
    if not data or len(data) > IMG_MAX:
        raise ApiError(413 if data else 400, "Picture must be under 3 MB")
    if not sniff(data):
        raise ApiError(400, "Use a JPEG, PNG or WebP picture")
    save_image(wid, data, "upload")
    return wine_json(get_wine(wid))


ZIP_MAX_FILES = 600
ZIP_MAX_TOTAL = 200 * 1024 * 1024


def import_pictures(raw):
    """Attach pictures from a zip of <wine id>.jpg/.png/.webp files (or i<CellarTracker iWine>.jpg, wc-<id>.jpg) (optional sources.json: {"12": {"url": "...", "credit": "..."}}).
    Your own uploaded photos are never replaced."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ApiError(400, "That is not a zip file")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > ZIP_MAX_FILES or sum(i.file_size for i in infos) > ZIP_MAX_TOTAL:
        raise ApiError(413, "The zip is too big (most %d pictures)" % ZIP_MAX_FILES)
    sources = {}
    for i in infos:
        if os.path.basename(i.filename) == "sources.json" and i.file_size < 1024 * 1024:
            try:
                sources = json.loads(z.read(i).decode("utf-8"))
            except ValueError:
                sources = {}
            if not isinstance(sources, dict):
                sources = {}
    out = {"added": 0, "keptOwn": 0, "unknownWine": 0, "notPicture": 0}
    for i in infos:
        base = os.path.basename(i.filename)
        m = re.fullmatch(r"(i|wc-)?(\d{1,12})\.(jpe?g|png|webp)", base, re.I)
        if not m:
            if base != "sources.json" and not i.filename.startswith("__MACOSX"):
                out["notPicture"] += 1
            continue
        stem = base.rsplit(".", 1)[0]
        if i.file_size > IMG_MAX:
            out["notPicture"] += 1
            continue
        data = z.read(i)
        if not sniff(data):
            out["notPicture"] += 1
            continue
        if (m.group(1) or "").lower() == "i":
            row = db.run("SELECT id FROM wc_wines WHERE iwine = ?", (m.group(2),), fetch="one")
        else:
            row = db.run("SELECT id FROM wc_wines WHERE id = ?", (int(m.group(2)),), fetch="one")
        if not row:
            out["unknownWine"] += 1
            continue
        wid = row["id"]
        cur = db.run("SELECT source FROM wc_images WHERE wine_id = ?", (wid,), fetch="one")
        own = isinstance(sources.get(stem), dict) and sources[stem].get("own") is True
        if cur and cur["source"] == "upload" and not own:
            out["keptOwn"] += 1
            continue
        src = sources.get(stem) if isinstance(sources.get(stem), dict) else {}
        url = txt(src.get("url"), 500)
        if url and not url.startswith(("https://", "http://")):
            url = ""
        if src.get("own") is True:
            save_image(wid, data, "upload")
        else:
            save_image(wid, data, "web", url or None, txt(src.get("credit"), 120) or "Picture found on the web")
        out["added"] += 1
    return out


def remove_image(wid):
    get_wine(wid)
    save_image(wid, None, "removed")
    return wine_json(get_wine(wid))


# ---------------------------------------------------------------- Systembolaget prices
def meta_get(k):
    r = db.run("SELECT v FROM wc_meta WHERE k = ?", (k,), fetch="one")
    return r["v"] if r else None


def meta_set(k, v):
    db.run("INSERT INTO wc_meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v", (k, v))


def to_int(v):
    try:
        f = float(str(v).replace(",", ".").strip())
        return int(f) if f == f else None
    except (TypeError, ValueError):
        return None


def sb_rows_from_json(data):
    """Wines only; skips discontinued items and anything without a price. One row per product number."""
    out = {}
    for p in data if isinstance(data, list) else []:
        if not isinstance(p, dict) or p.get("categoryLevel1") != "Vin" or p.get("isDiscontinued"):
            continue
        price = p.get("price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        num_ = str(p.get("productNumber") or "").strip()
        if not num_ or price <= 0:
            continue
        name = ((p.get("productNameBold") or "").strip() + " " + (p.get("productNameThin") or "").strip()).strip()
        v = to_int(p.get("vintage"))
        if v is not None and not 1800 <= v <= 2100:
            v = None
        out[num_] = (num_, (p.get("producerName") or "").strip()[:200], name[:300], v, to_int(p.get("volume")), price)
    return list(out.values())


_sb_lock = threading.Lock()
_sb_cache = {"rows": None}


def sb_refresh():
    """Download Systembolaget's published assortment once and keep only the wines in a small table."""
    host = urlparse(SB_URL).hostname or ""
    if not SB_URL.startswith(("https://", "http://")) or not (host == "raw.githubusercontent.com" or host == urlparse(IMG_API).hostname or host == IMG_TEST_HOST):
        raise NetError("blocked host")
    req = urllib.request.Request(SB_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read(SB_MAX + 1)
    except urllib.error.HTTPError as e:
        raise NetError("HTTP %d" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise NetError("%s: %s" % (type(e).__name__, str(getattr(e, "reason", e))[:80]))
    if len(raw) > SB_MAX:
        raise NetError("too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise NetError("not JSON")
    del raw
    rows = sb_rows_from_json(data)
    del data
    if len(rows) < 3:
        raise NetError("no wines in file")
    stamp = now()
    for i in range(0, len(rows), 60):
        chunk = rows[i:i + 60]
        db.run(
            "INSERT INTO wc_sb (product_number, producer, name, vintage, volume, price, seen) VALUES " + ", ".join(["(?, ?, ?, ?, ?, ?, ?)"] * len(chunk)) +
            " ON CONFLICT (product_number) DO UPDATE SET producer = EXCLUDED.producer, name = EXCLUDED.name, vintage = EXCLUDED.vintage, "
            "volume = EXCLUDED.volume, price = EXCLUDED.price, seen = EXCLUDED.seen",
            [x for row in chunk for x in (row + (stamp,))],
        )
    db.run("DELETE FROM wc_sb WHERE seen < ?", (stamp,))
    meta_set("sb_refreshed", stamp.isoformat())
    with _sb_lock:
        _sb_cache["rows"] = None
    return len(rows)


def sb_candidates():
    with _sb_lock:
        if _sb_cache["rows"] is None:
            rows = db.run("SELECT * FROM wc_sb", fetch="all")
            _sb_cache["rows"] = [dict(r, toks=set(tokens((r["producer"] or "") + " " + (r["name"] or "")))) for r in rows]
        return _sb_cache["rows"]


def wine_volume(w):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", (w.get("size") or "").lower())
    if not m:
        return 750
    v = float(m.group(1).replace(",", "."))
    return int(round(v * {"ml": 1, "cl": 10, "l": 1000}[m.group(2)]))


def match_sb(w, cands):
    """Strict match: producer words, a wine-name word, same vintage and bottle size. Returns the cheapest fitting listing or None."""
    ptoks_all = tokens(w["producer"])
    ptoks = [t for t in ptoks_all if t not in STOP] or ptoks_all
    rest = name_parts(w)[2]
    vint = w.get("vintage") or None
    vol = wine_volume(w)
    best = None
    for c in cands:
        if not ptoks or not all(t in c["toks"] for t in ptoks):
            continue
        if not name_fits(w, c["toks"]):
            continue
        if c.get("volume") and c["volume"] != vol:
            continue
        cv = c.get("vintage")
        if vint and cv and cv != vint:
            continue
        score = sum(1 for t in rest if t in c["toks"]) + (3 if (vint and cv == vint) else 0)
        key = (score, -(c["price"] or 0))
        if best is None or key > best[0]:
            best = (key, c)
    return best[1] if best else None


def sb_debug(wid):
    """Why a wine did or did not match: the listings that share its producer words, with the rule each one failed."""
    w = get_wine(wid)
    ptoks_all = tokens(w["producer"])
    ptoks = [t for t in ptoks_all if t not in STOP] or ptoks_all
    ppart, gen, rest = name_parts(w)
    vint = w.get("vintage") or None
    vol = wine_volume(w)
    out = []
    for c in sb_candidates():
        if not ptoks or not all(t in c["toks"] for t in ptoks):
            continue
        why = []
        if not name_fits(w, c["toks"]):
            why.append("name")
        if c.get("volume") and c["volume"] != vol:
            why.append("volume %s vs %s" % (c["volume"], vol))
        if vint and c.get("vintage") and c["vintage"] != vint:
            why.append("vintage %s vs %s" % (c["vintage"], vint))
        out.append({"number": c["product_number"], "name": c["name"], "producer": c["producer"], "vintage": c.get("vintage"), "volume": c.get("volume"), "price": c["price"], "rejected": why})
    out.sort(key=lambda x: len(x["rejected"]))
    return {"wine": label_of(w), "producerWords": ptoks, "nameWords": rest, "wineVolume": vol, "candidates": out[:15], "candidateCount": len(out), "listSize": len(sb_candidates())}


def sb_check(wid):
    w = get_wine(wid)
    cands = sb_candidates()
    if not cands:
        raise ApiError(503, "Systembolaget's list has not been downloaded yet. It is fetched in the background, try again in a few minutes.")
    c = match_sb(w, cands)
    stamp = now()
    if c:
        old = db.run("SELECT price FROM wc_prices WHERE wine_id = ? AND status = 'ok'", (wid,), fetch="one")
        db.run(
            "INSERT INTO wc_prices (wine_id, source, price, product_number, name, vintage, volume, status, checked_at) VALUES (?, 'systembolaget', ?, ?, ?, ?, ?, 'ok', ?) "
            "ON CONFLICT (wine_id) DO UPDATE SET source = EXCLUDED.source, price = EXCLUDED.price, product_number = EXCLUDED.product_number, name = EXCLUDED.name, "
            "vintage = EXCLUDED.vintage, volume = EXCLUDED.volume, status = EXCLUDED.status, checked_at = EXCLUDED.checked_at",
            (wid, c["price"], c["product_number"], c["name"], c.get("vintage"), c.get("volume"), stamp),
        )
        if not old or old["price"] != c["price"]:
            db.run("INSERT INTO wc_price_log (wine_id, source, price, ts) VALUES (?, 'systembolaget', ?, ?)", (wid, c["price"], stamp))
    else:
        db.run(
            "INSERT INTO wc_prices (wine_id, source, price, status, checked_at) VALUES (?, 'systembolaget', NULL, 'none', ?) "
            "ON CONFLICT (wine_id) DO UPDATE SET price = NULL, product_number = NULL, name = NULL, status = 'none', checked_at = EXCLUDED.checked_at",
            (wid, stamp),
        )
    return wine_json(get_wine(wid))


price_wake = threading.Event()


def price_worker():
    time.sleep(float(os.environ.get("PRICE_DELAY", "40")))
    while True:
        wait = 3600
        try:
            if AUTO_PRICES:
                last = meta_get("sb_refreshed")
                try:
                    age = (now() - datetime.fromisoformat(last)).total_seconds() if last else None
                except ValueError:
                    age = None
                if age is None or age > 7 * 86400:
                    n = sb_refresh()
                    log("Systembolaget wine list updated: %d wines" % n)
                    ids = db.run("SELECT id FROM wc_wines", fetch="all")
                else:
                    ids = db.run("SELECT w.id FROM wc_wines w LEFT JOIN wc_prices p ON p.wine_id = w.id WHERE p.wine_id IS NULL", fetch="all")
                for r in ids:
                    try:
                        sb_check(r["id"])
                    except ApiError:
                        break
        except NetError as e:
            log("Systembolaget price update paused (%s). Trying again in an hour." % e)
        except Exception as e:
            log("Systembolaget price error:", type(e).__name__, str(e)[:160])
        price_wake.wait(wait)
        price_wake.clear()


def app_config():
    n = db.run("SELECT COUNT(*) AS n FROM wc_sb", fetch="one")["n"]
    st, saved = app_settings()
    return {"eurSek": st["sekRate"], "settings": st, "settingsSaved": saved, "autoPrices": AUTO_PRICES, "sbProducts": n, "sbUpdated": meta_get("sb_refreshed"), "labelAi": bool(LABEL_KEY)}


# ---------------------------------------------------------------- label photo, read by Gemini
LABEL_PROMPT = (
    "You read the label of a wine bottle from a photo (front label, maybe the back label too). "
    "Answer with one JSON object and nothing else, with exactly these keys: "
    "producer, cuvee, vintage, color, style, country, region, appellation, grape. "
    "Use null for anything that is not printed on the label or that you cannot tell. Never guess. "
    "producer: the winery, estate or house name as printed. "
    "cuvee: the wine's own name, vineyard or cuvee if printed; do not repeat the producer or the appellation in it. "
    "vintage: the four-digit harvest year, or \"NV\" if the label says non-vintage; null if no year is shown. "
    "color: Red, White or Rose. style: Dry, Off-dry, Sparkling or Sweet. "
    "country: in English. region: the wine region, for example Burgundy or Rhone Valley. "
    "appellation: as printed, for example Gevrey-Chambertin. "
    "grape: the grape varieties printed on the label, separated by commas."
)
_label_lock = threading.Lock()


def _lv(v, limit=150):
    s = txt(v, limit)
    return "" if s.lower() in ("null", "none", "n/a", "na", "-", "not shown", "unknown") else s


def clean_label(d):
    """Take only the fields we expect from the model's answer, trimmed to what the form accepts."""
    out = {k: _lv(d.get(k)) for k in ("producer", "cuvee", "country", "region", "appellation")}
    out["varietal"] = _lv(d.get("grape") or d.get("varietal"))
    v = _lv(d.get("vintage"), 10)
    if v.upper() == "NV":
        out["vintage"] = "NV"
    elif re.fullmatch(r"(19|20)\d\d", v) and int(v) <= datetime.now().year + 1:
        out["vintage"] = int(v)
    else:
        out["vintage"] = ""
    c = _lv(d.get("color"), 20).lower()
    out["color"] = "Rosé" if c in ("rose", "rosé", "rosado", "rosato", "pink") else ("Red" if c == "red" else ("White" if c == "white" else ""))
    s = _lv(d.get("style"), 20).lower()
    out["style"] = next((x for x in STYLES if x.lower() == s), "")
    return out


_label_model = [""]  # a model found automatically, kept until the add-on restarts


def _gemini(url, body=None):
    headers = {"x-goog-api-key": LABEL_KEY, "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None, method="POST" if body is not None else "GET", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(2 * 1024 * 1024)


def flash_models():
    """Google retires models often. Ask which ones this key can use: plain Flash models newest first, then Flash-Lite."""
    try:
        data = json.loads(_gemini("%s/v1beta/models?pageSize=200" % LABEL_BASE).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    found = []
    skip = re.compile(r"image|tts|audio|live|embed|robotics|computer|thinking|learnlm|aqa|imagen|veo", re.I)
    for m in data.get("models") or []:
        name = str(m.get("name", "")).replace("models/", "")
        if not name.startswith("gemini-") or skip.search(name) or "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        ver = re.match(r"gemini-(?:(\d+(?:\.\d+)?)-)?(flash|flash-lite|pro)(?:-(latest|preview.*|\d{3}))?$", name)
        if not ver:
            continue
        v = float(ver.group(1) or 99)  # the "-latest" aliases count as newest
        kind = {"flash": 0, "flash-lite": 1, "pro": 2}[ver.group(2)]
        found.append((kind, -v, "preview" in name, name))
    names = [n for _, _, _, n in sorted(found)]
    log("Label reading: models available: %s" % ", ".join(names[:8]))
    return names


def newest_flash_model():
    m = flash_models()
    return m[0] if m else ""


def last_failed(last):
    return last[2] if last else []


def read_label(blob):
    if not LABEL_KEY:
        raise ApiError(503, "Reading labels with Gemini is not set up. Add a Gemini API key in the add-on options.")
    mime = sniff(blob or b"")
    if not mime:
        raise ApiError(400, "That is not a picture")
    body = {
        "contents": [{"parts": [{"text": LABEL_PROMPT}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(blob).decode("ascii")}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    with _label_lock:  # one photo at a time keeps us inside the free per-minute limit
        first = _label_model[0] or LABEL_MODEL
        queue = [first] if first else []
        raw = None
        last = None
        tried = 0
        while raw is None and tried < 7:
            if not queue:
                queue = [m for m in flash_models() if m not in last_failed(last)] if tried < 3 else []
                if not queue:
                    break
            model = queue.pop(0)
            tried += 1
            try:
                raw = _gemini("%s/v1beta/models/%s:generateContent" % (LABEL_BASE, model), body)
                _label_model[0] = model
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read(600).decode("utf-8", "replace").replace(LABEL_KEY, "***")
                except Exception:
                    pass
                detail = " ".join(detail.split())
                log("Label reading: Gemini answered HTTP %d for %s %s" % (e.code, model, detail[:300]))
                last = (e.code, model, (last[2] if last else []) + ([model] if e.code == 404 else []))
                if e.code == 404:
                    _label_model[0] = ""  # gone or not offered to this key: look for another
                    continue
                if e.code in (500, 503, 504):  # Google is busy: try the next model, then once more
                    time.sleep(min(2 * tried, 6))
                    if not queue and tried < 3:
                        queue = [model]  # nothing else to try: give the same model another go
                    continue
                if e.code == 429:
                    raise ApiError(429, "Gemini's free limit was reached. Try again in a minute, or tomorrow if it keeps happening.")
                if e.code in (400, 401, 403):
                    raise ApiError(502, "Gemini did not accept the request (HTTP %d). Check the API key in the add-on options." % e.code)
                raise ApiError(502, "Gemini had a problem (HTTP %d). Try again later." % e.code)
            except (urllib.error.URLError, OSError, ValueError) as e:
                log("Label reading: could not reach Gemini: %s" % type(e).__name__)
                raise ApiError(502, "Could not reach Gemini. Check the internet connection of Home Assistant.")
        if raw is None:
            if last and last[0] == 404:
                raise ApiError(502, "Gemini does not offer a usable model to this key. Check the API key in the add-on options.")
            raise ApiError(503, "Gemini is busy right now (high demand at Google). Try again in a minute.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise NetError("not JSON")
    del raw
    rows = sb_rows_from_json(data)
    del data
    if len(rows) < 3:
        raise NetError("no wines in file")
    stamp = now()
    for i in range(0, len(rows), 60):
        chunk = rows[i:i + 60]
        db.run(
            "INSERT INTO wc_sb (product_number, producer, name, vintage, volume, price, seen) VALUES " + ", ".join(["(?, ?, ?, ?, ?, ?, ?)"] * len(chunk)) +
            " ON CONFLICT (product_number) DO UPDATE SET producer = EXCLUDED.producer, name = EXCLUDED.name, vintage = EXCLUDED.vintage, "
            "volume = EXCLUDED.volume, price = EXCLUDED.price, seen = EXCLUDED.seen",
            [x for row in chunk for x in (row + (stamp,))],
        )
    db.run("DELETE FROM wc_sb WHERE seen < ?", (stamp,))
    meta_set("sb_refreshed", stamp.isoformat())
    with _sb_lock:
        _sb_cache["rows"] = None
    return len(rows)


def sb_candidates():
    with _sb_lock:
        if _sb_cache["rows"] is None:
            rows = db.run("SELECT * FROM wc_sb", fetch="all")
            _sb_cache["rows"] = [dict(r, toks=set(tokens((r["producer"] or "") + " " + (r["name"] or "")))) for r in rows]
        return _sb_cache["rows"]


def wine_volume(w):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|cl|l)\b", (w.get("size") or "").lower())
    if not m:
        return 750
    v = float(m.group(1).replace(",", "."))
    return int(round(v * {"ml": 1, "cl": 10, "l": 1000}[m.group(2)]))


def match_sb(w, cands):
    """Strict match: producer words, a wine-name word, same vintage and bottle size. Returns the cheapest fitting listing or None."""
    ptoks_all = tokens(w["producer"])
    ptoks = [t for t in ptoks_all if t not in STOP] or ptoks_all
    rest = name_parts(w)[2]
    vint = w.get("vintage") or None
    vol = wine_volume(w)
    best = None
    for c in cands:
        if not ptoks or not all(t in c["toks"] for t in ptoks):
            continue
        if not name_fits(w, c["toks"]):
            continue
        if c.get("volume") and c["volume"] != vol:
            continue
        cv = c.get("vintage")
        if vint and cv and cv != vint:
            continue
        score = sum(1 for t in rest if t in c["toks"]) + (3 if (vint and cv == vint) else 0)
        key = (score, -(c["price"] or 0))
        if best is None or key > best[0]:
            best = (key, c)
    return best[1] if best else None


def sb_debug(wid):
    """Why a wine did or did not match: the listings that share its producer words, with the rule each one failed."""
    w = get_wine(wid)
    ptoks_all = tokens(w["producer"])
    ptoks = [t for t in ptoks_all if t not in STOP] or ptoks_all
    ppart, gen, rest = name_parts(w)
    vint = w.get("vintage") or None
    vol = wine_volume(w)
    out = []
    for c in sb_candidates():
        if not ptoks or not all(t in c["toks"] for t in ptoks):
            continue
        why = []
        if not name_fits(w, c["toks"]):
            why.append("name")
        if c.get("volume") and c["volume"] != vol:
            why.append("volume %s vs %s" % (c["volume"], vol))
        if vint and c.get("vintage") and c["vintage"] != vint:
            why.append("vintage %s vs %s" % (c["vintage"], vint))
        out.append({"number": c["product_number"], "name": c["name"], "producer": c["producer"], "vintage": c.get("vintage"), "volume": c.get("volume"), "price": c["price"], "rejected": why})
    out.sort(key=lambda x: len(x["rejected"]))
    return {"wine": label_of(w), "producerWords": ptoks, "nameWords": rest, "wineVolume": vol, "candidates": out[:15], "candidateCount": len(out), "listSize": len(sb_candidates())}


def sb_check(wid):
    w = get_wine(wid)
    cands = sb_candidates()
    if not cands:
        raise ApiError(503, "Systembolaget's list has not been downloaded yet. It is fetched in the background, try again in a few minutes.")
    c = match_sb(w, cands)
    stamp = now()
    if c:
        old = db.run("SELECT price FROM wc_prices WHERE wine_id = ? AND status = 'ok'", (wid,), fetch="one")
        db.run(
            "INSERT INTO wc_prices (wine_id, source, price, product_number, name, vintage, volume, status, checked_at) VALUES (?, 'systembolaget', ?, ?, ?, ?, ?, 'ok', ?) "
            "ON CONFLICT (wine_id) DO UPDATE SET source = EXCLUDED.source, price = EXCLUDED.price, product_number = EXCLUDED.product_number, name = EXCLUDED.name, "
            "vintage = EXCLUDED.vintage, volume = EXCLUDED.volume, status = EXCLUDED.status, checked_at = EXCLUDED.checked_at",
            (wid, c["price"], c["product_number"], c["name"], c.get("vintage"), c.get("volume"), stamp),
        )
        if not old or old["price"] != c["price"]:
            db.run("INSERT INTO wc_price_log (wine_id, source, price, ts) VALUES (?, 'systembolaget', ?, ?)", (wid, c["price"], stamp))
    else:
        db.run(
            "INSERT INTO wc_prices (wine_id, source, price, status, checked_at) VALUES (?, 'systembolaget', NULL, 'none', ?) "
            "ON CONFLICT (wine_id) DO UPDATE SET price = NULL, product_number = NULL, name = NULL, status = 'none', checked_at = EXCLUDED.checked_at",
            (wid, stamp),
        )
    return wine_json(get_wine(wid))


price_wake = threading.Event()


def price_worker():
    time.sleep(float(os.environ.get("PRICE_DELAY", "40")))
    while True:
        wait = 3600
        try:
            if AUTO_PRICES:
                last = meta_get("sb_refreshed")
                try:
                    age = (now() - datetime.fromisoformat(last)).total_seconds() if last else None
                except ValueError:
                    age = None
                if age is None or age > 7 * 86400:
                    n = sb_refresh()
                    log("Systembolaget wine list updated: %d wines" % n)
                    ids = db.run("SELECT id FROM wc_wines", fetch="all")
                else:
                    ids = db.run("SELECT w.id FROM wc_wines w LEFT JOIN wc_prices p ON p.wine_id = w.id WHERE p.wine_id IS NULL", fetch="all")
                for r in ids:
                    try:
                        sb_check(r["id"])
                    except ApiError:
                        break
        except NetError as e:
            log("Systembolaget price update paused (%s). Trying again in an hour." % e)
        except Exception as e:
            log("Systembolaget price error:", type(e).__name__, str(e)[:160])
        price_wake.wait(wait)
        price_wake.clear()


def app_config():
    n = db.run("SELECT COUNT(*) AS n FROM wc_sb", fetch="one")["n"]
    st, saved = app_settings()
    return {"eurSek": st["sekRate"], "settings": st, "settingsSaved": saved, "autoPrices": AUTO_PRICES, "sbProducts": n, "sbUpdated": meta_get("sb_refreshed"), "labelAi": bool(LABEL_KEY)}


# ---------------------------------------------------------------- label photo, read by Gemini
LABEL_PROMPT = (
    "You read the label of a wine bottle from a photo (front label, maybe the back label too). "
    "Answer with one JSON object and nothing else, with exactly these keys: "
    "producer, cuvee, vintage, color, style, country, region, appellation, grape. "
    "Use null for anything that is not printed on the label or that you cannot tell. Never guess. "
    "producer: the winery, estate or house name as printed. "
    "cuvee: the wine's own name, vineyard or cuvee if printed; do not repeat the producer or the appellation in it. "
    "vintage: the four-digit harvest year, or \"NV\" if the label says non-vintage; null if no year is shown. "
    "color: Red, White or Rose. style: Dry, Off-dry, Sparkling or Sweet. "
    "country: in English. region: the wine region, for example Burgundy or Rhone Valley. "
    "appellation: as printed, for example Gevrey-Chambertin. "
    "grape: the grape varieties printed on the label, separated by commas."
)
_label_lock = threading.Lock()


def _lv(v, limit=150):
    s = txt(v, limit)
    return "" if s.lower() in ("null", "none", "n/a", "na", "-", "not shown", "unknown") else s


def clean_label(d):
    """Take only the fields we expect from the model's answer, trimmed to what the form accepts."""
    out = {k: _lv(d.get(k)) for k in ("producer", "cuvee", "country", "region", "appellation")}
    out["varietal"] = _lv(d.get("grape") or d.get("varietal"))
    v = _lv(d.get("vintage"), 10)
    if v.upper() == "NV":
        out["vintage"] = "NV"
    elif re.fullmatch(r"(19|20)\d\d", v) and int(v) <= datetime.now().year + 1:
        out["vintage"] = int(v)
    else:
        out["vintage"] = ""
    c = _lv(d.get("color"), 20).lower()
    out["color"] = "Rosé" if c in ("rose", "rosé", "rosado", "rosato", "pink") else ("Red" if c == "red" else ("White" if c == "white" else ""))
    s = _lv(d.get("style"), 20).lower()
    out["style"] = next((x for x in STYLES if x.lower() == s), "")
    return out


_label_model = [""]  # a model found automatically, kept until the add-on restarts


def _gemini(url, body=None):
    headers = {"x-goog-api-key": LABEL_KEY, "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None, method="POST" if body is not None else "GET", headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(2 * 1024 * 1024)


def flash_models():
    """Google retires models often. Ask which ones this key can use: plain Flash models newest first, then Flash-Lite."""
    try:
        data = json.loads(_gemini("%s/v1beta/models?pageSize=200" % LABEL_BASE).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    found = []
    for m in data.get("models") or []:
        name = str(m.get("name", "")).replace("models/", "")
        ver = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?", name)
        if ver and "generateContent" in (m.get("supportedGenerationMethods") or []):
            found.append((1 if ver.group(2) else 0, -float(ver.group(1)), name))
    return [n for _, _, n in sorted(found)]


def newest_flash_model():
    m = flash_models()
    return m[0] if m else ""


def read_label(blob):
    if not LABEL_KEY:
        raise ApiError(503, "Reading labels with Gemini is not set up. Add a Gemini API key in the add-on options.")
    mime = sniff(blob or b"")
    if not mime:
        raise ApiError(400, "That is not a picture")
    body = {
        "contents": [{"parts": [{"text": LABEL_PROMPT}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(blob).decode("ascii")}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    with _label_lock:  # one photo at a time keeps us inside the free per-minute limit
        model = _label_model[0] or LABEL_MODEL or newest_flash_model()
        if not model:
            raise ApiError(502, "Could not find a Gemini model for this key. Check the API key in the add-on options.")
        raw = None
        for attempt in (1, 2):
            try:
                raw = _gemini("%s/v1beta/models/%s:generateContent" % (LABEL_BASE, model), body)
                _label_model[0] = model
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read(600).decode("utf-8", "replace").replace(LABEL_KEY, "***")
                except Exception:
                    pass
                detail = " ".join(detail.split())
                log("Label reading: Gemini answered HTTP %d for %s %s" % (e.code, model, detail[:300]))
                if e.code == 404 and attempt == 1:  # the model is gone or not offered to this key: look for the current one
                    found = newest_flash_model()
                    if found and found != model:
                        log("Label reading: switching to %s" % found)
                        model = found
                        continue
                if e.code == 429:
                    raise ApiError(429, "Gemini's free limit was reached. Try again in a minute, or tomorrow if it keeps happening.")
                if e.code == 404:
                    raise ApiError(502, "Gemini does not offer the model %s to this key. Clear the Gemini model option so the add-on picks a current one." % model)
                if e.code in (400, 401, 403):
                    raise ApiError(502, "Gemini did not accept the request (HTTP %d). Check the API key in the add-on options." % e.code)
                raise ApiError(502, "Gemini had a problem (HTTP %d). Try again later." % e.code)
            except (urllib.error.URLError, OSError, ValueError) as e:
                log("Label reading: could not reach Gemini: %s" % type(e).__name__)
                raise ApiError(502, "Could not reach Gemini. Check the internet connection of Home Assistant.")
    try:
        data = json.loads(raw.decode("utf-8"))
        cands = data.get("candidates") or []
        if not cands:
            raise ApiError(422, "Gemini would not read this picture. Try another photo.")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        ans = json.loads(text)
    except ApiError:
        raise
    except (ValueError, AttributeError, TypeError):
        raise ApiError(502, "Gemini gave an answer that could not be understood. Try again.")
    if isinstance(ans, list) and ans and isinstance(ans[0], dict):
        ans = ans[0]
    if not isinstance(ans, dict):
        raise ApiError(502, "Gemini gave an answer that could not be understood. Try again.")
    return clean_label(ans)


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "WineCellar/" + VERSION

    def log_message(self, fmt, *args):  # keep logs quiet, no request bodies
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8", cache="no-store", filename=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.end_headers()
        self.wfile.write(data)

    def _body(self, limit=None):
        n = int(self.headers.get("Content-Length") or 0)
        if n > (limit or MAX_BODY):
            raise ApiError(413, "File too large")
        return self.rfile.read(n) if n else b""

    def _json(self):
        raw = self._body()
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ApiError(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object")
        return data

    def _route(self, method):
        if not ALLOW_ANY and self.client_address[0] not in ALLOWED_IPS:
            raise ApiError(403, "Forbidden")
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        if method == "GET" and (not parts or parts == ["index.html"]):
            with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if method == "GET" and len(parts) >= 2 and parts[0] == "vendor":
            return self._vendor(parts[1:])
        if not parts or parts[0] != "api":
            raise ApiError(404, "Not found")
        parts = parts[1:]
        if parts == ["languages"] and method == "GET":
            return self._send(200, self._languages())
        if len(parts) == 2 and parts[0] == "lang" and method == "GET":
            return self._language(parts[1])
        if parts == ["health"] and method == "GET":
            db.run("SELECT 1 AS ok", fetch="one")
            return self._send(200, {"ok": True})
        if parts == ["wines"]:
            if method == "GET":
                return self._send(200, {"wines": list_wines()})
            if method == "POST":
                return self._send(201, create_wine(self._json()))
        if len(parts) >= 2 and parts[0] == "wines" and parts[1].isdigit():
            wid = int(parts[1])
            if len(parts) == 2:
                if method == "PATCH":
                    return self._send(200, update_wine(wid, self._json()))
                if method == "DELETE":
                    return self._send(200, delete_wine(wid))
            if len(parts) == 3 and parts[2] == "adjust" and method == "POST":
                return self._send(200, adjust_wine(wid, self._json()))
            if len(parts) == 3 and parts[2] == "move" and method == "POST":
                return self._send(200, move_stock(wid, self._json()))
            if len(parts) == 4 and parts[2] == "stock" and parts[3].isdigit() and method == "PUT":
                return self._send(200, set_stock_note(wid, int(parts[3]), self._json()))
            if len(parts) == 3 and parts[2] == "image":
                if method == "GET":
                    data, mime = get_image(wid)
                    return self._send(200, data, mime, "private, max-age=86400")
                if method == "PUT":
                    return self._send(200, upload_image(wid, self._body()))
                if method == "DELETE":
                    return self._send(200, remove_image(wid))
            if len(parts) == 4 and parts[2] == "image" and parts[3] == "search" and method == "POST":
                get_wine(wid)
                try:
                    found = find_picture(wid, force=True)
                except NetError:
                    raise ApiError(502, "Could not reach the picture source. Check the internet connection and try again.")
                if not found:
                    raise ApiError(404, "No picture found online for this wine. You can add your own photo.")
                return self._send(200, wine_json(get_wine(wid)))
            if len(parts) == 3 and parts[2] == "tags":
                if method == "GET":
                    get_wine(wid)
                    return self._send(200, {"tags": list_tags(wid)})
                if method == "POST":
                    return self._send(201, add_tag(wid, self._json()))
            if len(parts) == 3 and parts[2] == "reviews":
                if method == "GET":
                    return self._send(200, list_reviews(wid))
                if method == "POST":
                    return self._send(201, add_review(wid, self._json()))
            if len(parts) == 3 and parts[2] == "pairing" and method == "GET":
                return self._send(200, wine_pairing(wid))
            if len(parts) == 3 and parts[2] == "sb" and method == "POST":
                return self._send(200, sb_check(wid))
        if len(parts) == 3 and parts[:2] == ["sb", "debug"] and parts[2].isdigit() and method == "GET":
            return self._send(200, sb_debug(int(parts[2])))
        if parts == ["tags"] and method == "GET":
            return self._send(200, {"tags": list_tags()})
        if len(parts) == 2 and parts[0] == "tags" and parts[1].isdigit() and method == "DELETE":
            return self._send(200, delete_tag(int(parts[1])))
        if len(parts) == 2 and parts[0] == "reviews" and parts[1].isdigit() and method == "DELETE":
            return self._send(200, delete_review(int(parts[1])))
        if parts == ["settings"]:
            if method == "GET":
                return self._send(200, settings_json())
            if method == "PUT":
                return self._send(200, save_app_settings(self._json()))
        if parts == ["climate"] and method == "GET":
            return self._send(200, climate())
        if parts == ["climate", "sensors"] and method == "GET":
            return self._send(200, list_sensors())
        if parts == ["climate", "settings"]:
            if method == "GET":
                return self._send(200, climate_settings())
            if method == "PUT":
                return self._send(200, save_climate_settings(self._json()))
        if parts == ["climate", "test"] and method == "POST":
            cs = climate_settings()
            try:
                send_notification("Wine cellar: test", "This is a test message from the Wine Cellar add-on.", cs["notifyService"], "wine_cellar_test")
            except Exception:
                raise ApiError(502, "Home Assistant did not accept the message. Check the notification service name.")
            return self._send(200, {"sent": True})
        if parts == ["pairing", "dishes"] and method == "GET":
            return self._send(200, {"dishes": pairing.search_dishes(q.get("q", [""])[0])})
        if parts == ["pairing", "find"] and method == "GET":
            return self._send(200, pairing_find(q.get("dish", [""])[0]))
        if parts == ["config"] and method == "GET":
            return self._send(200, app_config())
        if parts == ["sb", "refresh"] and method == "POST":
            price_wake.set()
            return self._send(202, {"started": True})
        if len(parts) == 2 and parts[0] == "ean" and method == "GET":
            return self._send(200, lookup_ean(parts[1]))
        if parts == ["label"] and method == "POST":
            return self._send(200, {"fields": read_label(self._body(LABEL_MAX))})
        if parts == ["checkins"] and method == "GET":
            wine = q.get("wine", [""])[0]
            if wine and not wine.isdigit():
                raise ApiError(400, "Bad wine id")
            return self._send(200, {"checkins": list_checkins(q.get("limit", ["30"])[0], wine or None)})
        if parts == ["places"]:
            if method == "GET":
                return self._send(200, places_state())
            if method == "POST":
                return self._send(201, create_place(self._json()))
        if parts == ["places", "move"] and method == "POST":
            return self._send(200, bulk_move(self._json()))
        if parts == ["places", "order"] and method == "PUT":
            return self._send(200, order_places(self._json()))
        if len(parts) == 2 and parts[0] == "places" and parts[1].isdigit():
            pid = int(parts[1])
            if method == "PATCH":
                return self._send(200, update_place(pid, self._json()))
            if method == "DELETE":
                return self._send(200, delete_place(pid, self._json()))
        if parts == ["export.csv"] and method == "GET":
            return self._send(200, export_csv(), "text/csv; charset=utf-8", filename="wine-cellar-%s.csv" % now().strftime("%Y-%m-%d"))
        if parts == ["backup.json"] and method == "GET":
            return self._send(200, export_json(q.get("pictures", ["1"])[0] != "0"), "application/json; charset=utf-8",
                              filename="wine-cellar-backup-%s.json" % now().strftime("%Y-%m-%d"))
        if parts == ["restore"] and method == "POST":
            return self._send(200, restore_backup(self._body(64 * 1024 * 1024), q.get("confirm", [""])[0]))
        if parts == ["alerts", "drink"]:
            if method == "GET":
                return self._send(200, drink_alert_state())
            if method in ("PUT", "POST"):
                return self._send(200, save_alert_settings(self._json()))
        if parts == ["alerts", "drink", "send"] and method == "POST":
            try:
                return self._send(200, send_drink_alert(test=True))
            except Exception:
                raise ApiError(502, "Home Assistant did not accept the message. Check the notification service name.")
        if parts == ["ha", "sensors"]:
            if method == "GET":
                return self._send(200, ha_sensors_state())
            if method in ("PUT", "POST"):
                return self._send(200, save_ha_sensors(self._json()))
        if parts == ["ha", "sensors", "publish"] and method == "POST":
            if not sensors_enabled():
                raise ApiError(409, "Switch the sensors on first")
            try:
                ha_sensors_publish(force=True)
            except mqtt.MqttError as e:
                raise ApiError(502, str(e))
            return self._send(200, ha_sensors_state())
        if parts == ["images", "import"] and method == "POST":
            return self._send(200, import_pictures(self._body(64 * 1024 * 1024)))
        if parts == ["import"] and method == "POST":
            return self._send(200, import_csv(self._body()))
        raise ApiError(404, "Not found")

    def _languages(self):
        """Language files in lang/: one JSON per language (see lang/README.md)."""
        out = []
        try:
            names = sorted(os.listdir(LANG_DIR))
        except OSError:
            names = []
        for fn in names:
            code = fn[:-5] if fn.endswith(".json") else ""
            if not LANG_CODE.match(code):
                continue
            try:
                with open(os.path.join(LANG_DIR, fn), encoding="utf-8") as f:
                    meta = json.load(f)
                out.append({"code": code, "name": str(meta.get("_name") or code)[:40]})
            except (OSError, ValueError):
                log("Skipping unreadable language file", fn)
        return {"languages": out}

    def _language(self, code):
        if not LANG_CODE.match(code):
            raise ApiError(404, "Not found")
        path = os.path.join(LANG_DIR, code + ".json")
        try:
            with open(path, "rb") as f:
                return self._send(200, f.read(), "application/json; charset=utf-8", "no-cache")
        except OSError:
            raise ApiError(404, "Not found")

    def _vendor(self, rel):
        """Files the add-on downloaded at build time (the label reader). Nothing else is served."""
        root = os.path.realpath(os.path.join(STATIC_DIR, "vendor"))
        path = os.path.realpath(os.path.join(root, *rel))
        if not path.startswith(root + os.sep) or not os.path.isfile(path):
            raise ApiError(404, "Not found")
        kinds = {".js": "text/javascript; charset=utf-8", ".json": "application/json", ".gz": "application/octet-stream", ".wasm": "application/wasm"}
        ctype = kinds.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            return self._send(200, f.read(), ctype, "public, max-age=604800")

    def _handle(self, method):
        try:
            self._route(method)
        except ApiError as e:
            self._send(e.status, {"error": e.message})
        except Exception as e:  # never leak details (could include connection info)
            log("Unhandled error:", type(e).__name__, str(e)[:200])
            self._send(500, {"error": "Something went wrong. Check the add-on log."})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


def main():
    for attempt in range(1, 31):
        try:
            db.init_schema()
            break
        except Exception as e:
            log("Database not ready (%d/30): %s: %s" % (attempt, type(e).__name__, str(e)[:160]))
            db.conn = None
            time.sleep(2)
    else:
        log("Could not reach the database. Check the add-on options (host, name, user, password).")
    threading.Thread(target=image_worker, daemon=True).start()
    threading.Thread(target=price_worker, daemon=True).start()
    threading.Thread(target=climate_worker, daemon=True).start()
    threading.Thread(target=drink_alert_worker, daemon=True).start()
    threading.Thread(target=ha_sensors_worker, daemon=True).start()
    srv =ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log("Wine Cellar listening on port %d (%s)" % (PORT, DB_TYPE))
    srv.serve_forever()


if __name__ == "__main__":
    main()
