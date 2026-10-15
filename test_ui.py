#!/usr/bin/env python3
"""Browser tests for the Wine Cellar page. Needs Playwright with Chromium (pip install playwright).

    python3 test_ui.py

Starts the real server on a temporary SQLite file and drives the page in a headless browser.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "wine_cellar", "app", "server.py")
PORT = int(os.environ.get("TEST_UI_PORT", "18791"))
BASE = "http://127.0.0.1:%d" % PORT
TMP = tempfile.mkdtemp(prefix="winecellar-ui-")
MOCK_PORT = PORT + 1
ENV = dict(os.environ, DB_TYPE="sqlite", SQLITE_PATH=os.path.join(TMP, "w.db"), PORT=str(PORT), AUTO_IMAGES="0", AUTO_PRICES="0",
           HA_API="http://127.0.0.1:%d/api" % MOCK_PORT, SUPERVISOR_TOKEN="t", CLIMATE_TEMP_ENTITY="sensor.t", CLIMATE_HUMIDITY_ENTITY="sensor.h")

import http.server
import threading
import datetime


class MockHA(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/states/sensor.t"):
            body = {"state": "17.2", "attributes": {"unit_of_measurement": "C", "friendly_name": "Cellar temp"}}
        elif self.path.startswith("/api/states/sensor.h"):
            body = {"state": "68", "attributes": {"unit_of_measurement": "%", "friendly_name": "Cellar humidity"}}
        else:
            body = [[{"state": "16"}, {"state": "17.2"}]]
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


mock = http.server.ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockHA)
threading.Thread(target=mock.serve_forever, daemon=True).start()

# Reads a Code 128 bit string back into text: start code, symbols, checksum and stop must all be right.
def decode128(bits, table):
    inv = {"".join(("1" if i % 2 == 0 else "0") * int(d) for i, d in enumerate(p)): v for v, p in enumerate(table)}
    syms = [bits[i:i + 11] for i in range(0, len(bits) - 13, 11)]
    assert bits[-13:] == "".join(("1" if i % 2 == 0 else "0") * int(d) for i, d in enumerate(table[106])), "stop pattern"
    vals = [inv[s] for s in syms]
    assert vals[0] == 104, "start B"
    total = vals[0] + sum(v * i for i, v in enumerate(vals[1:-1], 1))
    assert total % 103 == vals[-1], "checksum"
    return "".join(chr(v + 32) for v in vals[1:-1])

fails = []


def check(name, ok, detail=None):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   -> %r" % (detail,)))
    if not ok:
        fails.append(name)


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "null")


def image_status(wid):
    try:
        with urllib.request.urlopen(BASE + "/api/wines/%d/image" % wid, timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None, 0


# Makes an image file in the page, so no test fixtures are needed
MAKE_FILE = """() => new Promise(res => {
  const c = document.createElement('canvas'); c.width = 300; c.height = 500;
  const x = c.getContext('2d'); x.fillStyle = '#7a1f2b'; x.fillRect(0, 0, 300, 500); x.fillStyle = '#fff'; x.fillRect(60, 150, 180, 200);
  c.toBlob(b => res(new File([b], 'label.png', { type: 'image/png' })), 'image/png');
})"""

PASTE = """async (target) => {
  const f = await (%s)();
  const dt = new DataTransfer(); dt.items.add(f);
  const e = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
  document.dispatchEvent(e);
  return e.defaultPrevented;
}""" % MAKE_FILE

PASTE_TEXT = """() => {
  const dt = new DataTransfer(); dt.setData('text/plain', 'just text');
  const e = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
  document.dispatchEvent(e);
  return e.defaultPrevented;
}"""

DROP = """async (sel) => {
  const f = await (%s)();
  const dt = new DataTransfer(); dt.items.add(f);
  const el = document.querySelector(sel);
  const e = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true });
  el.dispatchEvent(e);
  return e.defaultPrevented;
}""" % MAKE_FILE

def open_info(page):
    page.fill("#q", "Pair Estate")
    page.wait_for_function("() => document.querySelectorAll('p.wn button.lnk').length === 1")
    page.locator("p.wn button.lnk").first.click()


proc = subprocess.Popen([sys.executable, "-I", SERVER], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.25)
    w1 = api("POST", "/api/wines", {"producer": "Paste Test", "wine": "One", "vintage": 2020, "color": "Red", "quantity": 2})["id"]
    w2 = api("POST", "/api/wines", {"producer": "Drop Test", "wine": "Two", "vintage": 2021, "color": "White", "quantity": 1})["id"]
    check("no pictures to start with", image_status(w1)[0] == 404 and image_status(w2)[0] == 404, (image_status(w1), image_status(w2)))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        page.wait_for_selector("button.pic")

        # ---- the picture sheet of an existing wine: paste
        card = page.locator("button.pic").filter(has=page.locator("svg")).first
        page.locator("button.pic").first.click()
        page.wait_for_selector("dialog[open] .sheet")
        check("sheet offers a Paste image button", page.locator("dialog[open] button", has_text="Paste image").count() == 1)
        check("plain text paste is left alone", page.evaluate(PASTE_TEXT) is False)
        prevented = page.evaluate(PASTE)
        check("an image paste is taken", prevented is True)
        page.wait_for_selector("dialog[open] img.photo", timeout=10000)
        titles = page.locator("dialog[open] .sh h2").inner_text()
        wid = w1 if "Paste Test" in titles else w2
        st, ctype, n = image_status(wid)
        check("pasted image is saved as a JPEG picture", st == 200 and ctype == "image/jpeg" and n > 500, (st, ctype, n))
        page.keyboard.press("Escape")

        # ---- the other wine: drop a file onto the sheet
        other = w2 if wid == w1 else w1
        page.reload()
        page.wait_for_selector("button.pic")
        for i in range(page.locator("button.pic").count()):
            btn = page.locator("button.pic").nth(i)
            btn.click()
            page.wait_for_selector("dialog[open] .sheet")
            if ("Drop Test" in page.locator("dialog[open] .sh h2").inner_text()) == (other == w2):
                break
            page.keyboard.press("Escape")
        dropped = page.evaluate(DROP, "dialog[open] .sb .f")
        check("an image drop is taken", dropped is True)
        page.wait_for_selector("dialog[open] img.photo", timeout=10000)
        st, ctype, n = image_status(other)
        check("dropped image is saved as a picture", st == 200 and ctype == "image/jpeg" and n > 500, (st, ctype, n))
        page.keyboard.press("Escape")

        # ---- the add form: paste shows a preview and is uploaded with the new wine
        page.click("#addBtn")
        page.wait_for_selector("dialog[open] .sheet")
        check("form mentions pasting", page.locator("dialog[open]").inner_text().count("paste an image") == 1)
        page.evaluate(PASTE)
        page.wait_for_function("() => { const i = document.querySelector('dialog[open] img.photo'); return i && !i.hidden && i.src.startsWith('blob:'); }", timeout=10000)
        check("form shows the pasted image as a preview", True)
        page.keyboard.press("Escape")

        # ---- nothing is hijacked when no dialog wants an image
        page.wait_for_selector("button.pic")
        check("paste outside a dialog does nothing", page.evaluate(PASTE) is False)
        # ---- pairing: info sheet and dinner finder
        api("POST", "/api/wines", {"producer": "Pair Estate", "wine": "Cab", "vintage": 2018, "color": "Red", "varietal": "Cabernet Sauvignon", "region": "Napa Valley", "country": "USA", "quantity": 3, "begin_consume": 2015, "end_consume": 2040})
        page.reload()
        page.wait_for_selector("button.pic")
        page.click("#moreBtn")
        page.click("#pairBtn")
        page.wait_for_selector("dialog[open] .dishes .chip")
        check("dinner finder lists dishes", page.locator("dialog[open] .dishes .chip").count() >= 30)
        page.fill("dialog[open] input[type=search]", "lamb")
        page.wait_for_function("() => document.querySelectorAll('dialog[open] .dishes .chip').length === 1")
        page.locator("dialog[open] .dishes .chip").first.click()
        page.wait_for_selector("dialog[open] button:has-text('Pair Estate')")
        check("finder shows the matching bottle", True)
        page.locator("dialog[open] button:has-text('Pair Estate')").first.click()
        page.wait_for_selector("dialog[open] .pair .row")
        check("bottle page has Goes well with", page.locator("dialog[open] .pair .row").count() >= 3 and "Goes well with" in page.locator("dialog[open]").inner_text())
        check("bottle page has price lookup links", page.locator("dialog[open] a:has-text('Vivino')").count() == 1 and page.locator("dialog[open] a:has-text('Wine-Searcher')").count() == 1)
        page.keyboard.press("Escape")
        # ---- cellar climate strip (Home Assistant stand-in)
        page.wait_for_selector("#climate .cl")
        txt = page.locator("#climate").inner_text()
        check("climate strip shows both readings", "17.2" in txt and "68" in txt, txt)
        check("a too warm cellar is flagged", page.locator("#climate .cl.high").count() == 1 and "too high" in txt, txt)
        page.locator("#climate .cl").first.click()
        page.wait_for_selector("dialog[open] svg polyline")
        check("climate sheet draws the last 24 hours", True)
        page.keyboard.press("Escape")

        # ---- tags and occasions
        pair_id = [w["id"] for w in api("GET", "/api/wines")["wines"] if w["producer"] == "Pair Estate"][0]
        open_info(page)
        page.wait_for_selector("dialog[open] .occ")
        sel = page.locator("dialog[open] select[aria-label=Tag]")
        sel.select_option("gift_received")
        page.locator("dialog[open] select[aria-label=Occasion]").select_option("birthday")
        page.fill("dialog[open] input[aria-label=Who]", "Anna")
        soon = datetime.date.today() + datetime.timedelta(days=5)
        page.fill("dialog[open] input[aria-label=Date]", datetime.date(2000, soon.month, soon.day).isoformat())
        page.check("dialog[open] #tagYearly")
        page.click("dialog[open] button:has-text('Add tag')")
        page.wait_for_selector("dialog[open] .occ .row:has-text('Birthday')")
        check("tag shows occasion, person and yearly flag", "from Anna" in page.locator("dialog[open] .occ").inner_text() and "every year" in page.locator("dialog[open] .occ").inner_text())
        check("tag saved on the server", len(api("GET", "/api/wines/%d/tags" % pair_id)["tags"]) == 1)
        page.keyboard.press("Escape")
        page.fill("#q", "")
        page.wait_for_selector("#occSec:not([hidden]) .tile")
        check("upcoming birthday shows under Coming up", "In 5 days" in page.locator("#occ").inner_text(), page.locator("#occ").inner_text())
        check("tag filter chip appears", page.locator("#f-tag button:has-text('Gift received')").count() == 1)
        page.click("#f-tag button:has-text('Gift received')")
        page.wait_for_function("() => document.querySelectorAll('button.pic').length === 1")
        check("tag filter narrows the list", True)
        check("filter shows only the tagged wine", "Pair Estate" in page.locator("#grid, main, .mainc").first.inner_text())
        page.click("#f-tag button:has-text('Gift received')")

        # ---- scores and reviews
        open_info(page)
        page.wait_for_selector("dialog[open] input[aria-label=Source]")
        page.fill("dialog[open] input[aria-label=Source]", "Wine Advocate")
        page.fill("dialog[open] input[aria-label=Score]", "94")
        page.fill("dialog[open] textarea", "Dense and long")
        page.click("dialog[open] button:has-text('Add review')")
        page.wait_for_selector("dialog[open] .rv:has-text('Wine Advocate')")
        check("review is listed with its score", "94/100" in page.locator("dialog[open] .rv").inner_text())
        check("critic average is summarised", "Critics 94/100" in page.locator("dialog[open]").inner_text())
        check("CellarTracker link offered", page.locator("dialog[open] a[href*=cellartracker]").count() == 1)
        page.fill("dialog[open] input[aria-label=Score]", "150")
        page.fill("dialog[open] input[aria-label=Source]", "Bad")
        page.click("dialog[open] button:has-text('Add review')")
        page.wait_for_selector("dialog[open] .err:not(:empty)")
        check("a score above the scale is refused with a message", True)
        page.keyboard.press("Escape")
        page.fill("#q", "")

        # ---- bottle labels
        code_bits = page.evaluate("() => window.__wc.code128('WC%d')" % pair_id)
        table = open(os.path.join(HERE, "wine_cellar", "app", "static", "index.html"), encoding="utf-8").read().split("var C128 = '")[1].split("'")[0].split(" ")
        check("Code 128 table is complete and consistent", len(table) == 107 and len(set(table)) == 107 and all(sum(map(int, p)) == 11 and (int(p[0]) + int(p[2]) + int(p[4])) % 2 == 0 for p in table[:106]))
        check("label code reads back as the wine id", decode128(code_bits, table) == "WC%d" % pair_id, code_bits)
        page.click("#moreBtn")
        page.click("#labelBtn")
        page.wait_for_selector("dialog[open] .lbl svg rect")
        total = sum(w["quantity"] for w in api("GET", "/api/wines")["wines"] if w["quantity"] > 0)
        check("one label per bottle", page.locator("dialog[open] .lbl").count() == total, (page.locator("dialog[open] .lbl").count(), total))
        page.click("dialog[open] button:has-text('One per wine')")
        check("one label per wine", page.locator("dialog[open] .lbl").count() == len([w for w in api("GET", "/api/wines")["wines"] if w["quantity"] > 0]))
        check("labels have a print button", page.locator("dialog[open] button:has-text('Print labels')").count() == 1)
        page.keyboard.press("Escape")

        # ---- scanning a printed label opens the wine
        page.click("#scanBtn")
        page.wait_for_selector("dialog[open] input[aria-label='Barcode number']")
        page.fill("dialog[open] input[aria-label='Barcode number']", "WC%d" % pair_id)
        page.keyboard.press("Enter")
        page.wait_for_selector("dialog[open] .sh h2:has-text('Pair Estate')")
        check("scanning a printed label opens that wine", True)
        page.keyboard.press("Escape")
        page.click("#scanBtn")
        page.fill("dialog[open] input[aria-label='Barcode number']", "WC99999")
        page.keyboard.press("Enter")
        page.wait_for_selector("dialog[open] .err:has-text('no longer')")
        check("a label for a deleted wine says so", True)
        page.keyboard.press("Escape")
        check("no script errors", errors == [], errors)
        browser.close()
finally:
    mock.shutdown()
    proc.terminate()
    proc.wait(timeout=10)

print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("All UI tests passed")
