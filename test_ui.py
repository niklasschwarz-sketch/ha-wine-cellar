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
ENV = dict(os.environ, DB_TYPE="sqlite", SQLITE_PATH=os.path.join(TMP, "w.db"), PORT=str(PORT), AUTO_IMAGES="0", AUTO_PRICES="0")
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
        check("no script errors", errors == [], errors)
        browser.close()
finally:
    proc.terminate()
    proc.wait(timeout=10)

print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("All UI tests passed")
