#!/usr/bin/env python3
"""Wine Cellar add-on backend.

Small JSON API + static page. Stores wines and a check-in log in Postgres
(the existing Postgres add-on). Standard library only, plus pg8000 for Postgres.
Set DB_TYPE=sqlite (and SQLITE_PATH) to run against SQLite for local tests.
"""
import csv
import io
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
import pairing  # noqa: E402

DB_TYPE = os.environ.get("DB_TYPE", "postgres")
PORT = int(os.environ.get("PORT", "8099"))
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
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

HA_API = os.environ.get("HA_API", "http://supervisor/core/api").rstrip("/")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
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
    """CREATE TABLE IF NOT EXISTS wc_racks (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        shelves INTEGER NOT NULL,
        slots INTEGER NOT NULL,
        pos INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS wc_bottles (
        id BIGSERIAL PRIMARY KEY,
        wine_id BIGINT NOT NULL,
        rack_id BIGINT NOT NULL,
        shelf INTEGER NOT NULL,
        slot INTEGER NOT NULL,
        placed_at TS_TYPE
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS wc_bottles_pos ON wc_bottles (rack_id, shelf, slot)",
    "CREATE INDEX IF NOT EXISTS wc_bottles_wine ON wc_bottles (wine_id)",
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
        make_views()


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


def wine_json(r):
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
        "likePercent": r.get("like_percent"),
        "likeVotes": r.get("like_votes") or 0,
        "location": r.get("location") or "",
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
    return [wine_json(r) for r in rows]


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
    for f in found:
        f["wine"] = wine_json(byid[f["id"]])
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
    wid = insert_wine(cols)
    if cols["quantity"] > 0:
        add_checkin(wid, label_of(cols), "add", cols["quantity"], None, "Added to the cellar")
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
    newq = (r["quantity"] or 0) + delta
    if newq < 0:
        raise ApiError(409, "There are not that many bottles left")
    # Conditional update keeps the count correct if two taps race.
    db.run("UPDATE wc_wines SET quantity = ?, updated_at = ? WHERE id = ? AND quantity = ?", (newq, now(), wid, r["quantity"] or 0))
    cur = get_wine(wid)
    if (cur["quantity"] or 0) != newq:
        raise ApiError(409, "The cellar changed, please try again")
    add_checkin(wid, label_of(r), kind, delta, rating, note)
    if delta < 0:
        prefer = data.get("bottleId")
        trim_bottles(wid, newq, int(prefer) if str(prefer or "").isdigit() else None)
    return wine_json(cur)


def delete_wine(wid):
    r = get_wine(wid)
    add_checkin(None, label_of(r), "delete", -(r["quantity"] or 0), None, "Wine deleted from the cellar")
    db.run("UPDATE wc_checkins SET wine_id = NULL WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_images WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_prices WHERE wine_id = ?", (wid,))
    db.run("DELETE FROM wc_bottles WHERE wine_id = ?", (wid,))
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
    for r in reader:
        iw = txt(r.get("iWine"), 40)
        color = r.get("Color") or "Red"
        if not iw or color not in COLORS or not txt(r.get("Producer"), 200):
            skipped += 1
            continue
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
        cols = {
            "color": color, "type": txt(r.get("Type"), 60) or color, "vintage": None if v in (0, 1001) else v,
            "producer": txt(r.get("Producer"), 200), "wine": txt(r.get("Wine"), 300), "varietal": txt(r.get("Varietal"), 200),
            "designation": txt(r.get("Designation")), "vineyard": txt(r.get("Vineyard")), "country": txt(r.get("Country")),
            "region": txt(r.get("Region")), "subregion": txt(r.get("SubRegion")), "appellation": txt(r.get("Appellation")),
            "size": txt(r.get("Size"), 40), "currency": txt(r.get("Currency"), 8) or "EUR",
            "value": num(r.get("Value")), "price": num(r.get("Price")), "quantity": max(0, int(num(r.get("Quantity")))),
            "begin_consume": yr(b), "end_consume": yr(e), "like_percent": lp, "like_votes": lv,
        }
        # Our own export carries these; a plain CellarTracker file does not, and must not wipe them.
        for col, key in (("Location", "location"), ("Notes", "notes")):
            if (r.get(col) or "").strip():
                cols[key] = txt(r.get(col), 1000)
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
            updated += 1
        else:
            cols["iwine"] = iw
            insert_wine(cols)
            inserted += 1
    total = db.run("SELECT COALESCE(SUM(quantity), 0) AS q, COUNT(*) AS n FROM wc_wines", fetch="one")
    wake.set()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "wines": total["n"], "bottles": int(total["q"])}


# ---------------------------------------------------------------- racks
def clean_int(v, lo, hi, label):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, label + " must be a whole number")
    if not lo <= n <= hi:
        raise ApiError(400, "%s must be between %d and %d" % (label, lo, hi))
    return n


def racks_state():
    racks = db.run("SELECT id, name, shelves, slots FROM wc_racks ORDER BY pos, id", fetch="all")
    bottles = db.run("SELECT id, wine_id, rack_id, shelf, slot FROM wc_bottles ORDER BY id", fetch="all")
    return {
        "racks": [{"id": r["id"], "name": r["name"], "shelves": r["shelves"], "slots": r["slots"]} for r in racks],
        "bottles": [{"id": b["id"], "wineId": b["wine_id"], "rackId": b["rack_id"], "shelf": b["shelf"], "slot": b["slot"]} for b in bottles],
    }


def get_rack(rid):
    r = db.run("SELECT * FROM wc_racks WHERE id = ?", (rid,), fetch="one")
    if not r:
        raise ApiError(404, "Rack not found")
    return r


def create_rack(data):
    name = txt(data.get("name"), 60)
    if not name:
        raise ApiError(400, "Give the rack a name")
    shelves = clean_int(data.get("shelves"), 1, 40, "Shelves")
    slots = clean_int(data.get("slots"), 1, 60, "Bottles per shelf")
    with db.lock:
        n = db.run("SELECT COALESCE(MAX(pos), 0) AS m FROM wc_racks", fetch="one")["m"]
        db.run("INSERT INTO wc_racks (name, shelves, slots, pos) VALUES (?, ?, ?, ?)", (name, shelves, slots, n + 1))
    return racks_state()


def update_rack(rid, data):
    r = get_rack(rid)
    name = txt(data.get("name"), 60) if "name" in data else r["name"]
    if not name:
        raise ApiError(400, "Give the rack a name")
    shelves = clean_int(data.get("shelves", r["shelves"]), 1, 40, "Shelves")
    slots = clean_int(data.get("slots", r["slots"]), 1, 60, "Bottles per shelf")
    with db.lock:
        out = db.run("SELECT COUNT(*) AS n FROM wc_bottles WHERE rack_id = ? AND (shelf > ? OR slot > ?)", (rid, shelves, slots), fetch="one")["n"]
        if out:
            raise ApiError(409, "%d bottle%s sit outside the smaller size. Move them first." % (out, "" if out == 1 else "s"))
        db.run("UPDATE wc_racks SET name = ?, shelves = ?, slots = ? WHERE id = ?", (name, shelves, slots, rid))
    return racks_state()


def delete_rack(rid):
    get_rack(rid)
    with db.lock:
        db.run("DELETE FROM wc_bottles WHERE rack_id = ?", (rid,))
        db.run("DELETE FROM wc_racks WHERE id = ?", (rid,))
    return racks_state()


def clear_rack(rid):
    get_rack(rid)
    db.run("DELETE FROM wc_bottles WHERE rack_id = ?", (rid,))
    return racks_state()


def get_bottle(bid):
    b = db.run("SELECT * FROM wc_bottles WHERE id = ?", (bid,), fetch="one")
    if not b:
        raise ApiError(404, "That bottle is no longer in a rack")
    return b


def place_bottle(data):
    rid = clean_int(data.get("rackId"), 1, 10 ** 12, "Rack")
    rack = get_rack(rid)
    shelf = clean_int(data.get("shelf"), 1, rack["shelves"], "Shelf")
    slot = clean_int(data.get("slot"), 1, rack["slots"], "Slot")
    with db.lock:
        occ = db.run("SELECT * FROM wc_bottles WHERE rack_id = ? AND shelf = ? AND slot = ?", (rid, shelf, slot), fetch="one")
        if str(data.get("bottleId") or "").isdigit():  # move (or swap) a bottle that is already in a rack
            b = get_bottle(int(data["bottleId"]))
            if occ and occ["id"] == b["id"]:
                return racks_state()
            if occ:  # swap through a parking position, the slot index is unique
                db.run("UPDATE wc_bottles SET shelf = 0, slot = ? WHERE id = ?", (-b["id"], b["id"]))
                db.run("UPDATE wc_bottles SET rack_id = ?, shelf = ?, slot = ? WHERE id = ?", (b["rack_id"], b["shelf"], b["slot"], occ["id"]))
            db.run("UPDATE wc_bottles SET rack_id = ?, shelf = ?, slot = ? WHERE id = ?", (rid, shelf, slot, b["id"]))
            return racks_state()
        wid = clean_int(data.get("wineId"), 1, 10 ** 12, "Wine")
        w = get_wine(wid)
        placed = db.run("SELECT COUNT(*) AS n FROM wc_bottles WHERE wine_id = ?", (wid,), fetch="one")["n"]
        if placed >= (w["quantity"] or 0):
            raise ApiError(409, "All bottles of this wine are already in a rack")
        if occ:
            raise ApiError(409, "That slot is taken")
        db.run("INSERT INTO wc_bottles (wine_id, rack_id, shelf, slot, placed_at) VALUES (?, ?, ?, ?, ?)", (wid, rid, shelf, slot, now()))
    return racks_state()


def unplace_bottle(bid):
    get_bottle(bid)
    db.run("DELETE FROM wc_bottles WHERE id = ?", (bid,))
    return racks_state()


def trim_bottles(wid, qty, prefer=None):
    """Keep placed bottles <= bottle count. A bottle that was just opened is removed first."""
    with db.lock:
        if prefer:
            b = db.run("SELECT id FROM wc_bottles WHERE id = ? AND wine_id = ?", (prefer, wid), fetch="one")
            if b:
                db.run("DELETE FROM wc_bottles WHERE id = ?", (b["id"],))
        rows = db.run("SELECT id FROM wc_bottles WHERE wine_id = ? ORDER BY id", (wid,), fetch="all")
        for r in rows[max(qty, 0):]:
            db.run("DELETE FROM wc_bottles WHERE id = ?", (r["id"],))


def fill_rack(rid, data):
    """Put unplaced bottles into the free slots of a rack, row by row."""
    rack = get_rack(rid)
    only = data.get("wineId")
    with db.lock:
        taken = {(b["shelf"], b["slot"]) for b in db.run("SELECT shelf, slot FROM wc_bottles WHERE rack_id = ?", (rid,), fetch="all")}
        free = [(sh, sl) for sh in range(1, rack["shelves"] + 1) for sl in range(1, rack["slots"] + 1) if (sh, sl) not in taken]
        wines = db.run(
            "SELECT w.id, w.color, w.country, w.region, w.producer, w.vintage, w.wine, w.quantity - COALESCE(p.n, 0) AS left_over "
            "FROM wc_wines w LEFT JOIN (SELECT wine_id, COUNT(*) AS n FROM wc_bottles GROUP BY wine_id) p ON p.wine_id = w.id "
            "WHERE w.quantity - COALESCE(p.n, 0) > 0", fetch="all")
        if str(only or "").isdigit():
            wines = [w for w in wines if w["id"] == int(only)]
        order = {"Red": 0, "White": 1, "Rosé": 2}
        wines.sort(key=lambda w: (order.get(w["color"], 3), w["country"] or "", w["region"] or "", w["producer"] or "", w["vintage"] or 0, w["id"]))
        limit = None
        if str(data.get("count") or "").isdigit():
            limit = int(data["count"])
        n = 0
        for w in wines:
            for _ in range(w["left_over"]):
                if not free or (limit is not None and n >= limit):
                    break
                sh, sl = free.pop(0)
                db.run("INSERT INTO wc_bottles (wine_id, rack_id, shelf, slot, placed_at) VALUES (?, ?, ?, ?, ?)", (w["id"], rid, sh, sl, now()))
                n += 1
    out = racks_state()
    out["placed"] = n
    return out


# ---------------------------------------------------------------- export, backup, stats views
def rack_labels():
    names = {r["id"]: r["name"] for r in db.run("SELECT id, name FROM wc_racks", fetch="all")}
    by = {}
    for b in db.run("SELECT wine_id, rack_id, shelf, slot FROM wc_bottles ORDER BY rack_id, shelf, slot", fetch="all"):
        by.setdefault(b["wine_id"], []).append("%s %d/%d" % (names.get(b["rack_id"], "?"), b["shelf"], b["slot"]))
    return by


EXPORT_COLUMNS = ["iWine", "Type", "Color", "Category", "Size", "Currency", "Value", "Price", "Quantity", "Vintage", "Wine", "Producer",
                  "Varietal", "Designation", "Vineyard", "Country", "Region", "SubRegion", "Appellation", "BeginConsume", "EndConsume",
                  "LikeVotes", "LikePercent", "Location", "Notes", "EAN", "Racks"]


def export_csv():
    """Same column names as CellarTracker, so the file can be imported again (here or in CellarTracker)."""
    labels = rack_labels()
    out = io.StringIO()
    wr = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    wr.writerow(EXPORT_COLUMNS)
    for r in db.run("SELECT * FROM wc_wines ORDER BY id", fetch="all"):
        t = r.get("type") or r["color"]
        cat = t.split(" - ", 1)[1] if " - " in t else "Dry"
        wr.writerow([
            r.get("iwine") or "wc-%d" % r["id"], t, r["color"], cat, r.get("size") or "750ml", r.get("currency") or "EUR",
            "%g" % (r.get("value") or 0), "%g" % (r.get("price") or 0), r.get("quantity") or 0,
            r["vintage"] if r.get("vintage") else 1001, r.get("wine") or "", r["producer"], r.get("varietal") or "",
            r.get("designation") or "", r.get("vineyard") or "", r.get("country") or "", r.get("region") or "",
            r.get("subregion") or "", r.get("appellation") or "", r.get("begin_consume") or "", r.get("end_consume") or "",
            r.get("like_votes") or 0, "" if r.get("like_percent") is None else "%g" % r["like_percent"],
            r.get("location") or "", r.get("notes") or "", r.get("ean") or "", "; ".join(labels.get(r["id"], [])),
        ])
    return ("﻿" + out.getvalue()).encode("utf-8")


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
    d = {"country": "", "currency": "EUR", "tempUnit": "C", "formats": "auto", "paper": "A4", "sekRate": EUR_SEK}
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


def export_json():
    wines = [wine_json(r) for r in db.run("SELECT * FROM wc_wines ORDER BY id", fetch="all")]
    checkins = db.run("SELECT * FROM wc_checkins ORDER BY id", fetch="all")
    for c in checkins:
        c["ts"] = iso(c.get("ts"))
    doc = {"app": "wine-cellar", "exported": iso(now()), "wines": wines, "checkins": checkins, "racks": racks_state(),
           "tags": list_tags(), "reviews": [review_json(r) for r in db.run("SELECT * FROM wc_reviews ORDER BY id", fetch="all")]}
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def make_views():
    """Read-only views for Grafana or any SQL client. Failure here must never stop the app."""
    pg = DB_TYPE != "sqlite"
    year = "EXTRACT(YEAR FROM CURRENT_DATE)" if pg else "CAST(strftime('%Y', 'now') AS INTEGER)"
    month = "to_char(ts, 'YYYY-MM')" if pg else "substr(ts, 1, 7)"
    views = {
        "wc_v_cellar": (
            "SELECT id, producer, wine, CASE WHEN vintage IS NULL OR vintage = 0 THEN NULL ELSE vintage END AS vintage, color, type, country, region, appellation, varietal, "
            "quantity, price, value, quantity * price AS paid_total, quantity * value AS value_total, begin_consume, end_consume, "
            "CASE WHEN begin_consume IS NULL AND end_consume IS NULL THEN 'No window' WHEN end_consume < %s THEN 'Past peak' "
            "WHEN begin_consume > %s THEN 'Hold' ELSE 'Ready' END AS status FROM wc_wines WHERE quantity > 0" % (year, year)),
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
        "wc_v_rack_contents": (
            "SELECT r.name AS rack, b.shelf, b.slot, w.id AS wine_id, w.producer, w.wine, w.vintage FROM wc_bottles b "
            "JOIN wc_racks r ON r.id = b.rack_id JOIN wc_wines w ON w.id = b.wine_id"),
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
    return {"eurSek": st["sekRate"], "settings": st, "settingsSaved": saved, "autoPrices": AUTO_PRICES, "sbProducts": n, "sbUpdated": meta_get("sb_refreshed")}


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "WineCellar/0.4"

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

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
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
        if parts == ["checkins"] and method == "GET":
            wine = q.get("wine", [""])[0]
            if wine and not wine.isdigit():
                raise ApiError(400, "Bad wine id")
            return self._send(200, {"checkins": list_checkins(q.get("limit", ["30"])[0], wine or None)})
        if parts == ["racks"]:
            if method == "GET":
                return self._send(200, racks_state())
            if method == "POST":
                return self._send(201, create_rack(self._json()))
        if len(parts) >= 2 and parts[0] == "racks" and parts[1].isdigit():
            rid = int(parts[1])
            if len(parts) == 2 and method == "PATCH":
                return self._send(200, update_rack(rid, self._json()))
            if len(parts) == 2 and method == "DELETE":
                return self._send(200, delete_rack(rid))
            if len(parts) == 3 and parts[2] == "bottles" and method == "DELETE":
                return self._send(200, clear_rack(rid))
            if len(parts) == 3 and parts[2] == "fill" and method == "POST":
                return self._send(200, fill_rack(rid, self._json()))
        if parts == ["bottles", "place"] and method == "POST":
            return self._send(200, place_bottle(self._json()))
        if len(parts) == 2 and parts[0] == "bottles" and parts[1].isdigit() and method == "DELETE":
            return self._send(200, unplace_bottle(int(parts[1])))
        if parts == ["export.csv"] and method == "GET":
            return self._send(200, export_csv(), "text/csv; charset=utf-8", filename="wine-cellar-%s.csv" % now().strftime("%Y-%m-%d"))
        if parts == ["backup.json"] and method == "GET":
            return self._send(200, export_json(), "application/json; charset=utf-8", filename="wine-cellar-backup-%s.json" % now().strftime("%Y-%m-%d"))
        if parts == ["import"] and method == "POST":
            return self._send(200, import_csv(self._body()))
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
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log("Wine Cellar listening on port %d (%s)" % (PORT, DB_TYPE))
    srv.serve_forever()


if __name__ == "__main__":
    main()
