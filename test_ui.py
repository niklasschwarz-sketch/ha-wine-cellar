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
        if self.path == "/api/states":
            body = [{"entity_id": "sensor.t", "state": "17.2", "attributes": {"device_class": "temperature", "unit_of_measurement": "C", "friendly_name": "Cellar temp"}},
                    {"entity_id": "sensor.h", "state": "68", "attributes": {"device_class": "humidity", "unit_of_measurement": "%", "friendly_name": "Cellar humidity"}},
                    {"entity_id": "sensor.t2", "state": "9", "attributes": {"device_class": "temperature", "unit_of_measurement": "C", "friendly_name": "Fridge"}}]
        elif self.path.startswith("/api/states/sensor.t2"):
            body = {"state": "9", "attributes": {"unit_of_measurement": "C", "friendly_name": "Fridge"}}
        elif self.path.startswith("/api/states/sensor.t"):
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
    page.wait_for_function("() => document.querySelectorAll('.wname > button.lnk').length === 1")
    page.locator(".wname > button.lnk").first.click()


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
        page.locator("button.pic").first.click()
        page.wait_for_selector("dialog[open] .sheet")
        check("the picture opens the wine page", page.locator("dialog[open] .sf button:has-text('Open one')").count() == 1 and page.locator("dialog[open] .sf button:has-text('+1')").count() == 1)
        page.click("dialog[open] .sf button:has-text('More…')")
        page.click("dialog[open] button:has-text('picture…')")
        page.wait_for_selector("dialog[open] button:has-text('Paste image')")
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
                page.click("dialog[open] .sf button:has-text('More…')")
                page.click("dialog[open] button:has-text('picture…')")
                page.wait_for_selector("dialog[open] button:has-text('Paste image')")
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
        page.get_by_role("button", name="Settings").click()
        page.wait_for_selector("dialog[open] select[aria-label='Temperature sensor']")
        check("climate sheet leads to the settings", True)
        page.keyboard.press("Escape")

        # ---- climate settings menu
        page.click("#moreBtn")
        page.click("#climateBtn")
        page.wait_for_selector("dialog[open] select[aria-label='Temperature sensor'] option[value='sensor.t2']", state="attached")
        opts = page.locator("dialog[open] select[aria-label='Humidity sensor'] option").all_inner_texts()
        check("picker lists the humidity sensor with its reading", any("Cellar humidity (68 %)" in o for o in opts), opts)
        check("current choice is preselected", page.locator("dialog[open] select[aria-label='Temperature sensor']").input_value() == "sensor.t")
        page.fill("dialog[open] input[aria-label='Highest temperature']", "20")
        page.select_option("dialog[open] select[aria-label='Temperature sensor']", "sensor.t2")
        page.fill("dialog[open] input[aria-label='Lowest temperature']", "5")
        page.check("dialog[open] #clNotify")
        page.fill("dialog[open] input[aria-label='Notification service']", "not valid")
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_selector("dialog[open] .err:not(:empty)")
        check("a bad notification service is explained", "notify." in page.locator("dialog[open] .err").inner_text())
        page.fill("dialog[open] input[aria-label='Notification service']", "")
        page.click("dialog[open] button:has-text('Send a test message')")
        page.wait_for_selector("dialog[open] .note:has-text('Test message sent')")
        check("test message reaches Home Assistant", any(p[0] == "/api/services/persistent_notification/create" for p in POSTED), POSTED)
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_function("() => !document.querySelector('dialog[open]')")
        page.wait_for_function("() => document.querySelector('#climate').innerText.indexOf('Cellar') === -1 && document.querySelector('#climate .cl.ok')")
        txt = page.locator("#climate").inner_text()
        check("strip now shows the chosen sensor within its new range", "9" in txt and page.locator("#climate .cl.ok").count() >= 1, txt)
        saved = api("GET", "/api/climate/settings")
        check("choices are saved on the server", saved["tempEntity"] == "sensor.t2" and saved["tempMax"] == 20 and saved["notify"] is True, saved)
        page.click("#moreBtn")
        page.click("#climateBtn")
        page.wait_for_selector("dialog[open] #clShow")
        page.uncheck("dialog[open] #clShow")
        page.uncheck("dialog[open] #clNotify")
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_function("() => document.querySelector('#climate').hidden")
        check("untick Show hides the strip", True)
        page.click("#moreBtn")
        page.click("#climateBtn")
        page.wait_for_selector("dialog[open] #clShow")
        page.check("dialog[open] #clShow")
        page.select_option("dialog[open] select[aria-label='Temperature sensor']", "sensor.t")
        page.fill("dialog[open] input[aria-label='Lowest temperature']", "10")
        page.fill("dialog[open] input[aria-label='Highest temperature']", "16")
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_selector("#climate .cl.high")

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
        if not page.locator("#f-tag").is_visible(): page.click("#filtBtn")
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
        # ---- settings: country, currency, units
        page.click("#moreBtn")
        page.click("#settingsBtn")
        page.wait_for_selector("dialog[open] select[aria-label='Country']")
        page.select_option("dialog[open] select[aria-label='Country']", "US")
        check("choosing a country suggests currency, unit and paper",
              page.input_value("dialog[open] select[aria-label='Currency']") == "USD" and page.input_value("dialog[open] select[aria-label='Temperature unit']") == "F" and page.input_value("dialog[open] select[aria-label='Paper size']") == "Letter")
        check("exchange rate field is hidden outside Sweden", not page.locator("dialog[open] input[aria-label='Exchange rate to SEK']").is_visible())
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_function("() => !document.querySelector('dialog[open]')")
        page.wait_for_function("() => /\\$/.test(document.querySelector('#k-value').textContent)")
        check("money now shows in dollars", True)
        check("paper size reaches the print style", "letter" in page.evaluate("() => document.getElementById('pageSize').textContent"))
        page.click("#moreBtn")
        page.click("#climateBtn")
        page.wait_for_selector("dialog[open] #clShow")
        check("climate limits are labelled in Fahrenheit", page.locator("dialog[open] .lab:has-text('°F')").count() == 1)
        page.keyboard.press("Escape")
        saved = api("GET", "/api/settings")
        check("settings are stored on the server", saved["country"] == "US" and saved["currency"] == "USD" and saved["tempUnit"] == "F", saved)
        page.click("#moreBtn")
        page.click("#settingsBtn")
        page.wait_for_selector("dialog[open] select[aria-label='Country']")
        page.select_option("dialog[open] select[aria-label='Country']", "SE")
        page.select_option("dialog[open] select[aria-label='Temperature unit']", "C")
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_function("() => !document.querySelector('dialog[open]')")
        page.wait_for_function("() => /kr|SEK/.test(document.querySelector('#k-value').textContent)")
        check("Sweden gives kronor", True)
        page.click("#moreBtn")
        page.click("#menuBtn")
        page.wait_for_selector("dialog[open] .mbar")
        check("Systembolaget choice is offered for Sweden", page.locator("dialog[open] .mbar :text('Systembolaget')").count() >= 1)
        page.keyboard.press("Escape")
        api("PUT", "/api/settings", {"country": "US", "currency": "USD"})
        page.reload()
        page.wait_for_selector("#k-value")
        page.click("#moreBtn")
        page.click("#menuBtn")
        page.wait_for_selector("dialog[open] .mbar")
        check("Systembolaget choice is hidden outside Sweden", page.locator("dialog[open] .mbar :text('Systembolaget')").count() == 0)
        page.keyboard.press("Escape")
        api("PUT", "/api/settings", {"country": "SE", "currency": "EUR"})

        # ---- storage places
        api("PUT", "/api/settings", {"places": True, "shelfNotes": True})
        fr = [x for x in api("POST", "/api/places", {"name": "Fridge 1", "tempEntity": "sensor.t2"})["places"] if x["name"] == "Fridge 1"][0]
        cl = [x for x in api("POST", "/api/places", {"name": "Cellar left"})["places"] if x["name"] == "Cellar left"][0]
        two = [w for w in api("GET", "/api/wines")["wines"] if w["quantity"] >= 2 and not w["stock"]][0]
        api("POST", "/api/wines/%d/move" % two["id"], {"from": None, "to": fr["id"], "qty": 1})
        api("POST", "/api/wines/%d/move" % two["id"], {"from": None, "to": cl["id"], "qty": 1, "note": "shelf 3"})
        page.reload()
        page.wait_for_selector("#k-value")
        page.wait_for_selector("#placeBar .chip")
        check("a row of place chips appears above the list", page.locator("#placeBar .chip").count() >= 3, page.locator("#placeBar").inner_text())
        card = page.locator("article.wine", has_text=two["producer"]).first
        check("the wine card shows where its bottles are", "Fridge 1 ×1" in card.inner_text() and "Cellar left ×1" in card.inner_text(), card.inner_text())
        page.click("#placeBar .chip:has-text('Fridge 1')")
        total = page.locator("article.wine").count()
        check("tapping a place shows only wines kept there", 1 <= total < len(api("GET", "/api/wines")["wines"]) and page.locator("article.wine", has_text=two["producer"]).count() >= 1, total)
        page.locator("article.wine", has_text=two["producer"]).first.locator("button.pic").click()
        page.click("dialog[open] .sf button:has-text('Open one')")
        page.wait_for_selector("dialog[open] .radio")
        check("opening a bottle that is in several places asks which one", page.locator("dialog[open] .radio").count() >= 2)
        page.locator("dialog[open] .radio", has_text="Cellar left").click()
        page.click("dialog[open] button:has-text('Log it')")
        page.wait_for_function("() => !document.querySelector('dialog[open]')")
        after = [w for w in api("GET", "/api/wines")["wines"] if w["id"] == two["id"]][0]
        check("the bottle came from the chosen place", after["quantity"] == two["quantity"] - 1 and [x["qty"] for x in after["stock"] if x["placeId"] == cl["id"]] == [] and [x["qty"] for x in after["stock"] if x["placeId"] == fr["id"]] == [1], after["stock"])
        page.click("#moreBtn")
        page.click("#placesBtn")
        page.wait_for_selector("dialog[open] .pl-row")
        rowtxt = page.locator("dialog[open] .pl-row", has_text="Fridge 1").inner_text()
        check("the places list shows bottles and the place's own temperature", "1 bottle" in rowtxt and "9" in rowtxt, rowtxt)
        page.click("dialog[open] .pl-row:has-text('Cellar left') button:has-text('Edit')")
        page.wait_for_selector("dialog[open] input[aria-label='Place name']")
        page.fill("dialog[open] input[aria-label='Place name']", "Cellar right")
        page.click("dialog[open] button:has-text('Save')")
        page.wait_for_selector("dialog[open] .pl-row:has-text('Cellar right')")
        check("a place can be renamed", api("GET", "/api/places")["places"][1]["name"] == "Cellar right")
        page.keyboard.press("Escape")
        api("PUT", "/api/settings", {"places": False})

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
