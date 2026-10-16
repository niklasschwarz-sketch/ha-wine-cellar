#!/usr/bin/env python3
"""API tests for the Wine Cellar add-on. Runs the real server on a temporary SQLite file.

    python3 test_api.py

No Postgres and no network are needed. The server is stopped and started again halfway to check
that the data survives a restart, which is what a user's SQLite file has to do.
"""
import csv
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "wine_cellar", "app", "server.py")
PORT = int(os.environ.get("TEST_PORT", "18781"))
BASE = "http://127.0.0.1:%d" % PORT
TMP = tempfile.mkdtemp(prefix="winecellar-test-")
DB = os.path.join(TMP, "sub", "winecellar.db")  # the sub folder must be created by the server
MOCK_PORT = PORT + 1
ENV = dict(os.environ, DB_TYPE="sqlite", SQLITE_PATH=DB, PORT=str(PORT), AUTO_IMAGES="0", AUTO_PRICES="0",
           HA_API="http://127.0.0.1:%d/api" % MOCK_PORT, SUPERVISOR_TOKEN="test-token", CLIMATE_CHECK_SECS="1", CLIMATE_RENOTIFY_SECS="3600",
           CLIMATE_TEMP_ENTITY="sensor.cellar_temp", CLIMATE_HUMIDITY_ENTITY="sensor.cellar_humidity", HUMIDITY_MIN="60", HUMIDITY_MAX="75")

# A tiny stand-in for the Home Assistant API: two sensors, one fine and one too dry.
import http.server
import threading
SEEN_AUTH = []
POSTED = []


class MockHA(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        POSTED.append((self.path, json.loads(self.rfile.read(n).decode() or "{}")))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"[]")

    def do_GET(self):
        SEEN_AUTH.append(self.headers.get("Authorization"))
        if self.path == "/api/states":
            body = [
                {"entity_id": "sensor.cellar_temp", "state": "13.5", "attributes": {"device_class": "temperature", "unit_of_measurement": "\u00b0C", "friendly_name": "Cellar temp"}},
                {"entity_id": "sensor.cellar_humidity", "state": "48", "attributes": {"device_class": "humidity", "unit_of_measurement": "%", "friendly_name": "Cellar humidity"}},
                {"entity_id": "sensor.garage_temp", "state": "unavailable", "attributes": {"device_class": "temperature", "friendly_name": "Garage"}},
                {"entity_id": "sensor.power", "state": "420", "attributes": {"unit_of_measurement": "W", "friendly_name": "Power"}},
                {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
            ]
        elif self.path.startswith("/api/states/sensor.cellar_temp"):
            body = {"state": "13.5", "attributes": {"unit_of_measurement": "\u00b0C", "friendly_name": "Cellar temp"}}
        elif self.path.startswith("/api/states/sensor.cellar_humidity"):
            body = {"state": "48", "attributes": {"unit_of_measurement": "%", "friendly_name": "Cellar humidity"}}
        elif self.path.startswith("/api/history/period/"):
            vals = ["12.0", "13.5", "14.2"] if "cellar_temp" in self.path else ["50", "48", "unknown"]
            body = [[{"state": v} for v in vals]]
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


mock = http.server.ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockHA)
threading.Thread(target=mock.serve_forever, daemon=True).start()

fails = []
proc = None


def check(name, ok, detail=None):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   -> %r" % (detail,)))
    if not ok:
        fails.append(name)


def start():
    global proc
    proc = subprocess.Popen([sys.executable, "-I", SERVER], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1).read()
            return
        except Exception:
            time.sleep(0.25)
    raise SystemExit("server did not start")


def stop():
    global proc
    if proc:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        proc = None


def call(method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if raw is None and body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def wines():
    return call("GET", "/api/wines")[1]["wines"]


try:
    start()
    s, d = call("GET", "/api/health")
    check("health", s == 200 and d.get("ok") is True, d)
    check("database file was created", os.path.isfile(DB), DB)
    check("starts empty", wines() == [], wines())

    # ---- wines
    s, e = call("POST", "/api/wines", {"producer": "", "wine": "x"})
    check("a wine needs a producer", s == 400, e)
    s, w = call("POST", "/api/wines", {"producer": "Test Estate", "wine": "Reserve", "vintage": 2019, "color": "Red", "quantity": 3,
                                       "price": 20, "value": 25, "country": "France", "region": "Rhône", "begin_consume": 2022, "end_consume": 2030})
    wid = w.get("id")
    check("create wine", s == 201 and w["quantity"] == 3 and w["producer"] == "Test Estate", w)
    s, w = call("PATCH", "/api/wines/%d" % wid, {"notes": "Line one", "location": "Shelf 2", "ean": "7312345678901"})
    check("update wine", s == 200 and w["notes"] == "Line one" and w["location"] == "Shelf 2" and w["ean"] == "7312345678901", w)
    s, e = call("PATCH", "/api/wines/%d" % wid, {"ean": "12"})
    check("bad barcode refused", s == 400, e)

    s, w = call("POST", "/api/wines/%d/adjust" % wid, {"delta": -1, "kind": "drink", "rating": 4, "note": "Lovely"})
    check("drink a bottle", s == 200 and w["quantity"] == 2, w)
    s, w = call("POST", "/api/wines/%d/adjust" % wid, {"delta": -1, "kind": "remove"})
    check("remove a bottle", s == 200 and w["quantity"] == 1, w)
    s, e = call("POST", "/api/wines/%d/adjust" % wid, {"delta": -5, "kind": "remove"})
    check("cannot go below zero", s in (400, 409), (s, e))
    s, c = call("GET", "/api/checkins?wine=%d" % wid)
    kinds = [x["kind"] for x in c["checkins"]]
    check("history records add, drink and remove", {"add", "drink", "remove"} <= set(kinds), kinds)
    check("tasting note and rating are kept", any(x.get("rating") == 4 and x.get("note") == "Lovely" for x in c["checkins"]), c)
    s, c = call("GET", "/api/config")
    check("config endpoint", s == 200, c)

    # ---- storage places
    s, st = call("GET", "/api/places")
    check("places start switched off and empty", s == 200 and st["enabled"] is False and st["places"] == [] and st["unplaced"] == 1, st)
    s, st = call("PUT", "/api/settings", {"places": True, "shelfNotes": True})
    check("switching places on turns each shelf text into a place", s == 200 and st["places"] is True and st["placesMade"] == 1, st)
    s, st = call("GET", "/api/places")
    shelf2 = st["places"][0]
    check("the old shelf text became a place with its bottles", len(st["places"]) == 1 and shelf2["name"] == "Shelf 2" and shelf2["bottles"] == 1 and st["unplaced"] == 0, st)
    check("the wine lists where its bottle is", wines()[0]["stock"] == [{"placeId": shelf2["id"], "qty": 1, "note": ""}], wines()[0]["stock"])
    s, st = call("POST", "/api/places", {"name": "Fridge 1"})
    fr = [p for p in st["places"] if p["name"] == "Fridge 1"][0]
    check("create a place, type guessed from the name", s == 201 and fr["kind"] == "fridge", st)
    s, e = call("POST", "/api/places", {"name": " fridge 1 "})
    check("place names are unique", s == 409, e)
    s, e = call("POST", "/api/places", {"name": "Bar", "tempEntity": "not a sensor"})
    check("a bad sensor name is refused", s == 400, e)
    s, st = call("POST", "/api/places", {"name": "Bar", "kind": "bar", "tempEntity": "sensor.test_temp"})
    bar = [p for p in st["places"] if p["name"] == "Bar"][0]
    check("a place can have its own sensor", bar["tempEntity"] == "sensor.test_temp", bar)
    s, st = call("PUT", "/api/places/order", {"ids": [bar["id"], fr["id"], shelf2["id"]]})
    check("places can be reordered", [p["name"] for p in st["places"]] == ["Bar", "Fridge 1", "Shelf 2"], st)

    s, w = call("POST", "/api/wines", {"producer": "Spread Estate", "wine": "Split", "vintage": 2020, "color": "Red", "quantity": 3, "placeId": shelf2["id"], "placeNote": "top"})
    sp = w["id"]
    check("a new wine can start in a place", s == 201 and w["stock"] == [{"placeId": shelf2["id"], "qty": 3, "note": "top"}], w)
    s, w = call("POST", "/api/wines/%d/move" % sp, {"from": shelf2["id"], "to": fr["id"], "qty": 2, "note": "door"})
    check("move bottles between places", s == 200 and {x["placeId"]: x["qty"] for x in w["stock"]} == {shelf2["id"]: 1, fr["id"]: 2} and w["quantity"] == 3, w)
    s, e = call("POST", "/api/wines/%d/move" % sp, {"from": shelf2["id"], "to": fr["id"], "qty": 5})
    check("cannot move more bottles than are there", s == 409, e)
    s, e = call("POST", "/api/wines/%d/move" % sp, {"from": fr["id"], "to": fr["id"], "qty": 1})
    check("moving to the same place is refused", s == 400, e)
    s, w = call("POST", "/api/wines/%d/move" % sp, {"from": fr["id"], "to": None, "qty": 1})
    check("bottles can be taken out of a place without a new one", s == 200 and sum(x["qty"] for x in w["stock"]) == 2 and w["quantity"] == 3, w)
    s, w = call("POST", "/api/wines/%d/move" % sp, {"from": None, "to": bar["id"], "qty": 1})
    check("bottles without a place can be put in one", s == 200 and sum(x["qty"] for x in w["stock"]) == 3, w)
    s, w = call("PUT", "/api/wines/%d/stock/%d" % (sp, bar["id"]), {"note": "left side"})
    check("shelf note can be changed", s == 200 and [x["note"] for x in w["stock"] if x["placeId"] == bar["id"]] == ["left side"], w)
    s, w = call("POST", "/api/wines/%d/adjust" % sp, {"delta": -1, "kind": "drink", "placeId": fr["id"]})
    check("drinking a bottle takes it from the chosen place", s == 200 and w["quantity"] == 2 and {x["placeId"]: x["qty"] for x in w["stock"]} == {shelf2["id"]: 1, bar["id"]: 1}, w)
    s, e = call("POST", "/api/wines/%d/adjust" % sp, {"delta": -1, "kind": "drink", "placeId": fr["id"]})
    check("cannot drink from a place that has none", s == 409, e)
    s, w = call("POST", "/api/wines/%d/adjust" % sp, {"delta": 2, "kind": "add", "placeId": fr["id"]})
    check("adding bottles puts them in the chosen place", s == 200 and w["quantity"] == 4 and {x["placeId"]: x["qty"] for x in w["stock"]}[fr["id"]] == 2, w)
    s, w = call("POST", "/api/wines/%d/adjust" % sp, {"delta": -1, "kind": "remove"})
    check("without a place the count still never passes the places", s == 200 and sum(x["qty"] for x in w["stock"]) <= w["quantity"] == 3, w)
    s, e = call("DELETE", "/api/places/%d" % fr["id"], {})
    check("a place with bottles cannot be deleted without saying where they go", s == 409, e)
    with urllib.request.urlopen(BASE + "/api/export.csv", timeout=10) as r:
        pcsv = r.read()
    prow = [x for x in csv.DictReader(io.StringIO(pcsv.decode("utf-8-sig"))) if x["Wine"] == "Split"]
    check("export has one row per place, with the shelf note as Bin", len(prow) >= 2 and sum(int(x["Quantity"]) for x in prow) == 3 and {x["Location"] for x in prow} <= {"Shelf 2", "Fridge 1", "Bar", ""}, prow)
    s, ri = call("POST", "/api/import", raw=pcsv)
    sp_w = [x for x in wines() if x["id"] == sp][0]
    check("importing that file again keeps the bottle counts and places", s == 200 and ri["inserted"] == 0 and sp_w["quantity"] == 3 and sum(x["qty"] for x in sp_w["stock"]) == 3, (ri, sp_w))
    s, st = call("DELETE", "/api/places/%d" % bar["id"], {"moveTo": shelf2["id"]})
    sp_w = [x for x in wines() if x["id"] == sp][0]
    check("deleting a place moves its bottles where you choose", s == 200 and not any(p["id"] == bar["id"] for p in st["places"]) and sp_w["quantity"] == 3 and sum(x["qty"] for x in sp_w["stock"]) == 3, (st, sp_w))
    s, st = call("DELETE", "/api/places/%d" % fr["id"], {"moveTo": "unplaced"})
    sp_w = [x for x in wines() if x["id"] == sp][0]
    check("or leaves them without a place", s == 200 and sp_w["quantity"] == 3 and sum(x["qty"] for x in sp_w["stock"]) == 2, sp_w)
    s, d = call("DELETE", "/api/wines/%d" % sp)
    check("the test wine is removed again", s == 200)

    # ---- move many bottles at once
    s, st = call("POST", "/api/places", {"name": "Bulk target"})
    bt = [x for x in st["places"] if x["name"] == "Bulk target"][0]["id"]
    s, ba = call("POST", "/api/wines", {"producer": "Bulk A", "wine": "A", "vintage": 2020, "color": "Red", "quantity": 4, "placeId": shelf2["id"]})
    s, bb = call("POST", "/api/wines", {"producer": "Bulk B", "wine": "B", "vintage": 2020, "color": "Red", "quantity": 3})
    s, e = call("POST", "/api/places/move", {"wineIds": [], "from": "unplaced", "to": bt})
    check("bulk move needs wines", s == 400, e)
    s, r = call("POST", "/api/places/move", {"wineIds": [ba["id"], bb["id"]], "from": "unplaced", "to": bt})
    wa = [x for x in wines() if x["id"] == ba["id"]][0]
    wb = [x for x in wines() if x["id"] == bb["id"]][0]
    check("bottles without a place move to the chosen place", s == 200 and r["moved"] == 3 and r["wines"] == 1 and wb["stock"][0]["placeId"] == bt and [x["qty"] for x in wa["stock"]] == [4], (r, wa["stock"], wb["stock"]))
    s, r = call("POST", "/api/places/move", {"wineIds": [ba["id"], bb["id"]], "from": "any", "to": bt})
    wa = [x for x in wines() if x["id"] == ba["id"]][0]
    check("moving from anywhere gathers every bottle in one place", s == 200 and r["moved"] == 4 and wa["stock"] == [{"placeId": bt, "qty": 4, "note": ""}], (r, wa["stock"]))
    s, r = call("POST", "/api/places/move", {"wineIds": [ba["id"]], "from": bt, "to": shelf2["id"]})
    wa = [x for x in wines() if x["id"] == ba["id"]][0]
    check("moving from one named place to another", s == 200 and wa["stock"][0]["placeId"] == shelf2["id"] and wa["quantity"] == 4, wa["stock"])
    for w_ in (ba, bb):
        call("DELETE", "/api/wines/%d" % w_["id"])
    call("DELETE", "/api/places/%d" % bt, {})

    # ---- export and import
    s, w2 = call("POST", "/api/wines", {"producer": "Export, \"Quote\" Test", "wine": "Export Test", "vintage": "NV", "color": "White", "quantity": 2,
                                        "price": 9.5, "value": 12, "location": "Shelf 9", "notes": "Hello", "ean": "7312345678902"})
    with urllib.request.urlopen(BASE + "/api/export.csv", timeout=10) as r:
        csvb = r.read()
        cd = r.headers.get("Content-Disposition")
    rows = list(csv.DictReader(io.StringIO(csvb.decode("utf-8-sig"))))
    check("export has every wine", len(rows) == len(wines()), len(rows))
    check("export filename", bool(cd) and cd.startswith('attachment; filename="wine-cellar-'), cd)
    mine = [x for x in rows if x["Wine"] == "Export Test"][0]
    check("export keeps quotes, location and barcode", mine["Producer"] == 'Export, "Quote" Test' and mine["Location"] == "Shelf 9" and mine["EAN"] == "7312345678902", mine)
    s, ri = call("POST", "/api/import", raw=csvb)
    check("re-importing our own export adds nothing", s == 200 and ri["inserted"] == 0 and len(wines()) == len(rows), ri)
    with urllib.request.urlopen(BASE + "/api/backup.json", timeout=10) as r:
        bk = json.loads(r.read().decode())
    check("backup json", bk["app"] == "wine-cellar" and len(bk["wines"]) == len(rows) and bool(bk["places"]) and bool(bk["wines"][0]["stock"]), list(bk))

    # ---- restart: everything must still be there
    before = {w["id"]: (w["producer"], w["quantity"]) for w in wines()}
    placed = len(call("GET", "/api/places")[1]["places"])
    stop()
    start()
    after = {w["id"]: (w["producer"], w["quantity"]) for w in wines()}
    check("wines survive a restart", before == after and len(after) == 2, (before, after))
    check("places survive a restart", len(call("GET", "/api/places")[1]["places"]) == placed >= 1)
    s, c = call("GET", "/api/checkins?limit=50")
    check("history survives a restart", len(c["checkins"]) >= 4, len(c["checkins"]))

    # ---- stats views (used by Grafana when Postgres is chosen)
    con = sqlite3.connect(DB)
    names = ("wc_v_cellar", "wc_v_by_region", "wc_v_by_vintage", "wc_v_by_type", "wc_v_drunk_by_month", "wc_v_place_contents")
    counts = {n: con.execute("SELECT COUNT(*) FROM " + n).fetchone()[0] for n in names}
    check("views exist and have rows", counts["wc_v_cellar"] == 2 and counts["wc_v_by_region"] >= 1 and counts["wc_v_drunk_by_month"] == 1 and counts["wc_v_place_contents"] >= 1, counts)
    tot = con.execute("SELECT SUM(bottles) FROM wc_v_by_region").fetchone()[0]
    check("region view adds up to the bottle count", tot == sum(w["quantity"] for w in wines()), tot)
    con.close()

    # ---- delete
    s, d = call("DELETE", "/api/wines/%d" % wid)
    check("delete wine", s == 200 and not any(w["id"] == wid for w in wines()), d)
    con = sqlite3.connect(DB)
    check("deleting a wine clears its places", con.execute("SELECT COUNT(*) FROM wc_stock WHERE wine_id = ?", (wid,)).fetchone()[0] == 0)
    con.close()
    s, e = call("DELETE", "/api/wines/99999")
    check("unknown wine 404", s == 404, e)

    # ---- food and wine pairing
    def mk(**k):
        d = {"vintage": 2018, "quantity": 2, "begin_consume": 2015, "end_consume": 2040}
        d.update(k)
        return call("POST", "/api/wines", d)[1]["id"]
    cab = mk(producer="P1", wine="Cab", color="Red", varietal="Cabernet Sauvignon", region="Napa Valley", country="USA")
    chab = mk(producer="P2", wine="Chablis", color="White", varietal="Chardonnay", region="Chablis", country="France")
    sau = mk(producer="P3", wine="Sauternes", color="White", region="Sauternes", country="France", style="Sweet")
    rie = mk(producer="P4", wine="Riesling", color="White", varietal="Riesling", region="Mosel", country="Germany")
    s, pr = call("GET", "/api/wines/%d/pairing" % cab)
    labels = [x["label"] for x in pr["dishes"]]
    check("cabernet pairs with red meat", s == 200 and any(k in " ".join(labels).lower() for k in ("beef", "lamb", "steak")), labels)
    s, pr = call("GET", "/api/wines/%d/pairing" % chab)
    check("chablis pairs with seafood", "shellfish" in [x["key"] for x in pr["dishes"][:3]], [x["key"] for x in pr["dishes"]])
    s, fd = call("GET", "/api/pairing/dishes?q=lamb")
    check("dish search", s == 200 and fd["dishes"] and fd["dishes"][0]["key"] == "lamb", fd)
    s, fd = call("GET", "/api/pairing/dishes")
    check("dish list has groups", len(fd["dishes"]) >= 30 and all(x["group"] for x in fd["dishes"]), len(fd["dishes"]))
    s, f = call("GET", "/api/pairing/find?dish=lamb")
    check("find ranks the cabernet above the chablis", s == 200 and f["wines"][0]["id"] == cab, [x["id"] for x in f["wines"]])
    s, f = call("GET", "/api/pairing/find?dish=shellfish")
    check("shellfish picks chablis first", f["wines"][0]["id"] == chab, [x["id"] for x in f["wines"]])
    check("find returns wine data", f["wines"][0]["wine"]["producer"] == "P2")
    s, f = call("GET", "/api/pairing/find?dish=nope")
    check("unknown dish is 404", s == 404, f)
    s, e = call("GET", "/api/wines/99999/pairing")
    check("pairing for unknown wine is 404", s == 404, e)
    for i in (cab, chab, sau, rie):
        call("DELETE", "/api/wines/%d" % i)

    # ---- tags
    tw = mk(producer="Tag Estate", wine="Gift", color="Red")
    s, t = call("POST", "/api/wines/%d/tags" % tw, {"kind": "gift_received", "occasion": "birthday", "who": "Anna", "date": "2024-05-17", "yearly": True, "note": "50th"})
    check("add a gift tag with birthday", s == 201 and t["kind"] == "gift_received" and t["occasion"] == "birthday" and t["yearly"] is True and t["who"] == "Anna", t)
    s, t2 = call("POST", "/api/wines/%d/tags" % tw, {"kind": "special", "occasion": "anniversary"})
    check("special occasion tag without a date", s == 201 and t2["date"] == "" and t2["yearly"] is False, t2)
    s, e = call("POST", "/api/wines/%d/tags" % tw, {"kind": "nonsense"})
    check("unknown tag kind refused", s == 400, e)
    s, e = call("POST", "/api/wines/%d/tags" % tw, {"kind": "special", "date": "2024-13-45"})
    check("bad date refused", s == 400, e)
    s, e = call("POST", "/api/wines/%d/tags" % tw, {"kind": "special", "occasion": "picnic"})
    check("unknown occasion refused", s == 400, e)
    s, l = call("GET", "/api/wines/%d/tags" % tw)
    check("tags listed for a wine", s == 200 and len(l["tags"]) == 2, l)
    s, l = call("GET", "/api/tags")
    check("all tags listed", len(l["tags"]) >= 2)
    s, d = call("DELETE", "/api/tags/%d" % t2["id"])
    check("delete a tag", s == 200 and len(call("GET", "/api/wines/%d/tags" % tw)[1]["tags"]) == 1)
    check("tag on unknown wine is 404", call("POST", "/api/wines/99999/tags", {"kind": "special"})[0] == 404)

    # ---- reviews and scores
    s, rv = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "Wine Advocate", "score": 94, "scale": 100, "text": "Dense and long", "date": "2023-02-01", "url": "https://example.com/x"})
    check("add a critic review", s == 201 and rv["score100"] == 94, rv)
    s, rv2 = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "Decanter", "score": 18, "scale": 20})
    check("a 20-point score is converted to 100", s == 201 and rv2["score100"] == 90, rv2)
    s, rv3 = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "community", "source": "Friends", "score": 4, "scale": 5, "text": "Loved it"})
    check("community review", s == 201 and rv3["score100"] == 80, rv3)
    s, e = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "X", "score": 120, "scale": 100})
    check("score above the scale refused", s == 400, e)
    s, e = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "", "score": 90})
    check("source is required", s == 400, e)
    s, e = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "X"})
    check("score or text required", s == 400, e)
    s, e = call("POST", "/api/wines/%d/reviews" % tw, {"kind": "critic", "source": "X", "score": 90, "url": "javascript:alert(1)"})
    check("only http links accepted", s == 400, e)
    s, l = call("GET", "/api/wines/%d/reviews" % tw)
    check("summary averages the critics", s == 200 and l["summary"]["critic"] == {"count": 2, "avg100": 92.0} and l["summary"]["community"]["count"] == 1, l["summary"])
    check("no CellarTracker link for a wine without an iWine number", l["summary"]["cellartrackerUrl"] == "")
    s, d = call("DELETE", "/api/reviews/%d" % rv3["id"])
    check("delete a review", s == 200 and len(call("GET", "/api/wines/%d/reviews" % tw)[1]["reviews"]) == 2)
    with urllib.request.urlopen(BASE + "/api/backup.json", timeout=10) as r:
        bk = json.loads(r.read().decode())
    check("backup carries tags and reviews", len(bk["tags"]) == 1 and len(bk["reviews"]) == 2, (len(bk["tags"]), len(bk["reviews"])))
    call("DELETE", "/api/wines/%d" % tw)
    s, l = call("GET", "/api/tags")
    check("deleting a wine removes its tags", all(x["wineId"] != tw for x in l["tags"]))

    # ---- cellar climate from Home Assistant
    s, c = call("GET", "/api/climate")
    check("climate configured", s == 200 and c["configured"] is True, c)
    check("temperature is read and in range", c["temp"]["value"] == 13.5 and c["temp"]["status"] == "ok" and c["temp"]["unit"] == "\u00b0C", c["temp"])
    check("humidity too dry is flagged", c["humidity"]["value"] == 48 and c["humidity"]["status"] == "low", c["humidity"])
    check("24 hour range and series come from history", c["temp"]["min24"] == 12.0 and c["temp"]["max24"] == 14.2 and len(c["temp"]["series"]) == 3 and c["humidity"]["max24"] == 50, c["temp"])
    check("add-on sends its token to Home Assistant", set(SEEN_AUTH) == {"Bearer test-token"}, set(SEEN_AUTH))

    # ---- climate menu: sensor picker, settings, alarm
    s, sn = call("GET", "/api/climate/sensors")
    check("sensor picker lists temperature and humidity sensors", s == 200 and [x["entity"] for x in sn["temperature"]] == ["sensor.cellar_temp", "sensor.garage_temp"] and [x["entity"] for x in sn["humidity"]] == ["sensor.cellar_humidity"], sn)
    check("other numeric sensors are offered, lights are not", [x["entity"] for x in sn["other"]] == ["sensor.power"], sn["other"])
    s, cs = call("GET", "/api/climate/settings")
    check("settings start from the add-on options", cs["tempEntity"] == "sensor.cellar_temp" and cs["notify"] is False and cs["show"] is True, cs)
    s, e = call("PUT", "/api/climate/settings", {"tempEntity": "not a sensor"})
    check("bad sensor name refused", s == 400, e)
    s, e = call("PUT", "/api/climate/settings", {"tempMin": 20, "tempMax": 10})
    check("lowest above highest refused", s == 400, e)
    s, e = call("PUT", "/api/climate/settings", {"humidityMin": "abc"})
    check("non-numeric limit refused", s == 400, e)
    s, e = call("PUT", "/api/climate/settings", {"notifyService": "light.kitchen"})
    check("notification service must be notify.something", s == 400, e)
    s, cs = call("PUT", "/api/climate/settings", {"tempEntity": "sensor.cellar_temp", "humidityEntity": "sensor.cellar_humidity", "tempMin": 14, "tempMax": 18, "humidityMin": 55, "humidityMax": 80, "notify": False})
    check("settings are saved", s == 200 and cs["tempMin"] == 14 and cs["humidityMax"] == 80, cs)
    s, c = call("GET", "/api/climate")
    check("new limits are used (13.5 is now too low)", c["temp"]["status"] == "low" and c["limits"]["temp"] == [14, 18], c["limits"])
    s, c2 = call("PUT", "/api/climate/settings", {"show": False})
    s, c = call("GET", "/api/climate")
    check("show flag is passed to the page", c["show"] is False and c["configured"] is True, c.get("show"))
    s, c2 = call("PUT", "/api/climate/settings", {"show": True, "tempEntity": "", "humidityEntity": ""})
    check("clearing both sensors turns the strip off", call("GET", "/api/climate")[1]["configured"] is False)
    POSTED.clear()
    call("PUT", "/api/climate/settings", {"tempEntity": "sensor.cellar_temp", "humidityEntity": "sensor.cellar_humidity", "tempMin": 10, "tempMax": 16, "humidityMin": 60, "humidityMax": 75, "notify": False})
    time.sleep(2.5)
    check("no alarm while alerts are off", POSTED == [], POSTED)
    s, d = call("POST", "/api/climate/test")
    check("test message goes to Home Assistant", s == 200 and POSTED and POSTED[-1][0] == "/api/services/persistent_notification/create", POSTED)
    POSTED.clear()
    call("PUT", "/api/climate/settings", {"notify": True})
    time.sleep(3.5)
    alarms = [p for p in POSTED if "Wine cellar" in p[1].get("title", "")]
    check("a dry cellar raises one alarm", len(alarms) == 1 and "humidity" in alarms[0][1]["title"].lower() and "48" in alarms[0][1]["message"], POSTED)
    check("the in-range temperature raises none", not any("temperature" in p[1].get("title", "").lower() for p in POSTED), POSTED)
    time.sleep(2.5)
    check("it is not repeated every check", len([p for p in POSTED if "humidity" in p[1].get("title", "").lower()]) == 1, POSTED)
    POSTED.clear()
    call("PUT", "/api/climate/settings", {"notifyService": "notify.mobile_app_phone"})
    time.sleep(3.5)
    check("a notify service is used when chosen", any(p[0] == "/api/services/notify/mobile_app_phone" for p in POSTED), POSTED)
    call("PUT", "/api/climate/settings", {"notify": False, "notifyService": ""})

    # ---- settings: country, currency, units
    s, st = call("GET", "/api/settings")
    check("settings start with defaults and a country list", s == 200 and st["currency"] == "EUR" and st["tempUnit"] == "C" and any(c["code"] == "SE" and c["currency"] == "SEK" for c in st["countries"]), st)
    check("config carries the settings", call("GET", "/api/config")[1]["settings"]["currency"] == "EUR")
    check("unknown country is refused", call("PUT", "/api/settings", {"country": "XX"})[0] == 400)
    check("unknown currency is refused", call("PUT", "/api/settings", {"currency": "ZZZ"})[0] == 400)
    check("bad paper is refused", call("PUT", "/api/settings", {"paper": "A3"})[0] == 400)
    check("bad exchange rate is refused", call("PUT", "/api/settings", {"sekRate": "-1"})[0] == 400)
    before = [w["price"] for w in call("GET", "/api/wines")[1]["wines"]]
    s, st = call("PUT", "/api/settings", {"country": "US", "currency": "USD", "paper": "Letter", "formats": "country", "convertRate": "2"})
    after = [w["price"] for w in call("GET", "/api/wines")[1]["wines"]]
    check("saving settings works and converts amounts", s == 200 and st["currency"] == "USD" and st["paper"] == "Letter" and st["converted"] >= 1 and after == [round(p * 2, 2) for p in before], (st, before, after))
    check("wines carry the new currency", {w["currency"] for w in call("GET", "/api/wines")[1]["wines"]} == {"USD"})
    check("settings now count as saved", call("GET", "/api/settings")[1]["saved"] is True)
    s, st = call("PUT", "/api/settings", {"currency": "SEK"})
    after2 = [w["price"] for w in call("GET", "/api/wines")[1]["wines"]]
    check("changing currency without a rate keeps the numbers", s == 200 and after2 == after, (after, after2))
    call("PUT", "/api/climate/settings", {"tempMin": 10, "tempMax": 16})
    s, st = call("PUT", "/api/settings", {"tempUnit": "F"})
    cs = call("GET", "/api/climate/settings")[1]
    check("temperature limits convert to Fahrenheit", cs["tempMin"] == 50 and cs["tempMax"] == 60.8, cs)
    c = call("GET", "/api/climate?force=1")[1]
    check("sensor reading shows in Fahrenheit", c["temp"]["unit"] == "\u00b0F" and abs(c["temp"]["value"] - 56.3) < 0.1 and c["temp"]["status"] == "ok", c["temp"])
    call("PUT", "/api/settings", {"tempUnit": "C"})
    cs = call("GET", "/api/climate/settings")[1]
    check("and back to Celsius", cs["tempMin"] == 10 and cs["tempMax"] == 16, cs)
    call("PUT", "/api/settings", {"country": "SE", "currency": "EUR", "paper": "A4", "formats": "auto", "sekRate": 11})

    # ---- picture zip import
    import io as _io, zipfile as _zf, base64 as _b64
    PNG = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    wa = call("POST", "/api/wines", {"producer": "Pic Estate", "wine": "A", "vintage": 2020, "color": "Red", "quantity": 1})[1]
    wb = call("POST", "/api/wines", {"producer": "Pic Estate", "wine": "B", "vintage": 2021, "color": "Red", "quantity": 1})[1]
    def mkzip(files):
        b = _io.BytesIO()
        with _zf.ZipFile(b, "w") as z:
            for n, d in files.items():
                z.writestr(n, d)
        return b.getvalue()
    z1 = mkzip({"%d.png" % wa["id"]: PNG, "999999.png": PNG, "notes.txt": b"hi", "%d.jpg" % wb["id"]: b"not a picture",
                "sources.json": json.dumps({str(wa["id"]): {"url": "https://example.com/p", "credit": "Example"}})})
    s, r = call("POST", "/api/images/import", raw=z1)
    check("zip import adds a picture and skips bad files", s == 200 and r["added"] == 1 and r["unknownWine"] == 1 and r["notPicture"] == 2, r)
    wa2 = [w for w in wines() if w["id"] == wa["id"]][0]
    check("imported picture is attached with its source", wa2["imgSource"] == "web" and wa2["imgCredit"] == "Example" and wa2["imgUrl"] == "https://example.com/p", wa2)
    call("PUT", "/api/wines/%d/image" % wb["id"], raw=PNG)
    z2 = mkzip({"%d.png" % wb["id"]: PNG})
    s, r = call("POST", "/api/images/import", raw=z2)
    check("your own uploaded photo is not replaced", r["added"] == 0 and r["keptOwn"] == 1, r)
    z3 = mkzip({"%d.png" % wb["id"]: PNG, "sources.json": json.dumps({str(wb["id"]): {"own": True}})})
    s, r = call("POST", "/api/images/import", raw=z3)
    check("a picture marked as your own can replace one", r["added"] == 1, r)
    csvdoc = ("iWine,Type,Color,Category,Size,Currency,Value,Price,Quantity,Vintage,Wine,Producer\n"
              "424242,Red,Red,Dry,750ml,EUR,10,10,1,2018,Zip Test,Zip Estate\n").encode()
    call("POST", "/api/import", raw=csvdoc)
    z4 = mkzip({"i424242.png": PNG, "wc-%d.png" % wa["id"]: PNG, "i1.png": PNG})
    s, r = call("POST", "/api/images/import", raw=z4)
    zw = [w for w in wines() if w["iwine"] == "424242"][0]
    check("pictures can be matched by CellarTracker number or wc- id", r["added"] == 2 and r["unknownWine"] == 1 and zw["imgSource"] == "web", (r, zw.get("imgSource")))
    check("a non-zip is refused", call("POST", "/api/images/import", raw=b"hello")[0] == 400)
    bk = call("GET", "/api/backup.json")[1]
    check("the full copy says which wines have pictures", {w["id"]: w["picture"] for w in bk["wines"]}.get(wa["id"]) == "web", [w.get("picture") for w in bk["wines"]][:3])

    # ---- page and unknown paths
    with urllib.request.urlopen(BASE + "/", timeout=5) as r:
        html = r.read().decode()
    check("page is served", "Cellar" in html and "Cellar" in html and r.status == 200)
    check("unknown api path is 404", call("GET", "/api/nope")[0] == 404)
finally:
    stop()
    mock.shutdown()

print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("All tests passed")
