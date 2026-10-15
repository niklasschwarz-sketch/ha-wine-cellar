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
           HA_API="http://127.0.0.1:%d/api" % MOCK_PORT, SUPERVISOR_TOKEN="test-token",
           CLIMATE_TEMP_ENTITY="sensor.cellar_temp", CLIMATE_HUMIDITY_ENTITY="sensor.cellar_humidity", HUMIDITY_MIN="60", HUMIDITY_MAX="75")

# A tiny stand-in for the Home Assistant API: two sensors, one fine and one too dry.
import http.server
import threading
SEEN_AUTH = []


class MockHA(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        SEEN_AUTH.append(self.headers.get("Authorization"))
        if self.path.startswith("/api/states/sensor.cellar_temp"):
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

    # ---- racks
    s, st = call("GET", "/api/racks")
    check("racks start empty", s == 200 and st == {"racks": [], "bottles": []}, st)
    s, st = call("POST", "/api/racks", {"name": "Cellar A", "shelves": 3, "slots": 4})
    check("create rack", s == 201 and len(st["racks"]) == 1, st)
    rk = st["racks"][0]["id"]
    s, st = call("POST", "/api/bottles/place", {"wineId": wid, "rackId": rk, "shelf": 1, "slot": 1})
    check("place a bottle", s == 200 and len(st["bottles"]) == 1, st)
    s, e = call("POST", "/api/bottles/place", {"wineId": wid, "rackId": rk, "shelf": 1, "slot": 2})
    check("cannot place more bottles than owned", s == 409, e)
    s, e = call("POST", "/api/bottles/place", {"wineId": wid, "rackId": rk, "shelf": 9, "slot": 1})
    check("outside the rack is refused", s == 400, e)

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
    check("backup json", bk["app"] == "wine-cellar" and len(bk["wines"]) == len(rows) and len(bk["racks"]["bottles"]) == 1, list(bk))

    # ---- restart: everything must still be there
    before = {w["id"]: (w["producer"], w["quantity"]) for w in wines()}
    placed = len(call("GET", "/api/racks")[1]["bottles"])
    stop()
    start()
    after = {w["id"]: (w["producer"], w["quantity"]) for w in wines()}
    check("wines survive a restart", before == after and len(after) == 2, (before, after))
    check("rack placements survive a restart", len(call("GET", "/api/racks")[1]["bottles"]) == placed == 1)
    s, c = call("GET", "/api/checkins?limit=50")
    check("history survives a restart", len(c["checkins"]) >= 4, len(c["checkins"]))

    # ---- stats views (used by Grafana when Postgres is chosen)
    con = sqlite3.connect(DB)
    names = ("wc_v_cellar", "wc_v_by_region", "wc_v_by_vintage", "wc_v_by_type", "wc_v_drunk_by_month", "wc_v_rack_contents")
    counts = {n: con.execute("SELECT COUNT(*) FROM " + n).fetchone()[0] for n in names}
    check("views exist and have rows", counts["wc_v_cellar"] == 2 and counts["wc_v_by_region"] >= 1 and counts["wc_v_drunk_by_month"] == 1 and counts["wc_v_rack_contents"] == 1, counts)
    tot = con.execute("SELECT SUM(bottles) FROM wc_v_by_region").fetchone()[0]
    check("region view adds up to the bottle count", tot == sum(w["quantity"] for w in wines()), tot)
    con.close()

    # ---- delete
    s, d = call("DELETE", "/api/wines/%d" % wid)
    check("delete wine", s == 200 and not any(w["id"] == wid for w in wines()), d)
    check("deleting a wine clears its placements", call("GET", "/api/racks")[1]["bottles"] == [])
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

    # ---- page and unknown paths
    with urllib.request.urlopen(BASE + "/", timeout=5) as r:
        html = r.read().decode()
    check("page is served", "Cellar" in html and "racksBtn" in html and r.status == 200)
    check("unknown api path is 404", call("GET", "/api/nope")[0] == 404)
finally:
    stop()
    mock.shutdown()

print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("All tests passed")
