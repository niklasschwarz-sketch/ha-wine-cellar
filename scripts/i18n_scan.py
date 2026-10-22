#!/usr/bin/env python3
"""Collects every piece of text the page shows, so the language template stays complete.

    python3 scripts/i18n_scan.py            # prints the strings that are not in wine_cellar/app/lang/en.json
    python3 scripts/i18n_scan.py --raw      # prints everything it found

Starts the real server on a temporary database with a few sample wines, opens the page with ?i18n=collect
and clicks through the screens, then reads back the text the page collected. Needs Playwright with Chromium.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "wine_cellar", "app", "server.py")
TEMPLATE = os.path.join(ROOT, "wine_cellar", "app", "lang", "en.json")
PORT = int(os.environ.get("SCAN_PORT", "18851"))
BASE = "http://127.0.0.1:%d" % PORT
SKIP = ("delete", "remove", "restore", "reset", "discard", "erase", "clear all")


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit("%s %s -> %s %s" % (method, path, e.code, e.read().decode()[:200]))


def seed():
    call("PUT", "/api/settings", {"country": "SE", "places": True, "shelfNotes": True})
    for p in ("Fridge 1", "Cellar left"):
        call("POST", "/api/places", {"name": p, "type": "fridge" if "Fridge" in p else "cellar"})
    wines = [
        {"producer": "Sample Estate", "wine": "Reserve", "vintage": 2018, "color": "Red", "quantity": 3, "begin": 2022, "end": 2035, "varietal": "Syrah", "region": "Rhone", "country": "France", "ean": "7312345678901", "value": 30},
        {"producer": "Old Vines", "wine": "Classic", "vintage": 2005, "color": "Red", "quantity": 1, "begin": 2008, "end": 2015, "country": "Italy"},
        {"producer": "Young Cellars", "wine": "Fresh", "vintage": 2023, "color": "White", "quantity": 2, "begin": 2027, "end": 2032, "country": "Germany"},
        {"producer": "Bubbly House", "wine": "Brut", "vintage": 2020, "color": "White", "type": "White - Sparkling", "quantity": 6, "country": "France"},
    ]
    ids = [call("POST", "/api/wines", w)["id"] for w in wines]
    call("POST", "/api/wines/%d/adjust" % ids[0], {"delta": -1, "kind": "drink", "rating": 4, "note": "Lovely"})
    return ids


def snap(page, found):
    page.wait_for_timeout(250)
    found.update(page.evaluate("Object.keys(window.__untranslated || {})"))


def close_all(page):
    for _ in range(3):
        page.keyboard.press("Escape")
        page.wait_for_timeout(80)


def run():
    tmp = tempfile.mkdtemp(prefix="wc-scan-")
    env = dict(os.environ, DB_TYPE="sqlite", SQLITE_PATH=os.path.join(tmp, "w.db"), PORT=str(PORT), AUTO_IMAGES="0", AUTO_PRICES="0")
    srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    found = set()
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health").read()
                break
            except Exception:
                time.sleep(0.25)
        seed()
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            for vp in ({"width": 1400, "height": 900}, {"width": 390, "height": 844}):
                pg = b.new_page(viewport=vp)
                url = BASE + "/?i18n=collect&lang=en"
                pg.goto(url)
                pg.wait_for_selector(".card", timeout=10000)
                snap(pg, found)
                # every dock / menu button, then every harmless button inside whatever opened
                ids = pg.evaluate("Array.from(document.querySelectorAll('.dk[id], #moreMenu button[id], #navSrc button[id], #addBtn, #scanBtn, #filtBtn')).map(function(e){return e.id})")
                for bid in ids:
                    pg.goto(url); pg.wait_for_selector(".card", timeout=10000)
                    try:
                        if vp["width"] < 700 and bid in ("tableBtn", "menuBtn", "pairBtn", "settingsBtn", "climateBtn", "alertsBtn", "labelBtn", "importBtn", "placesBtn"):
                            pg.click("#moreBtn")
                        pg.click("#" + bid, timeout=1500)
                    except Exception:
                        continue
                    snap(pg, found)
                    names = pg.evaluate("Array.from(document.querySelectorAll('dialog[open] button, dialog[open] summary')).map(function(e,i){return (e.textContent||'').trim()+'|'+i})")
                    for entry in names[:40]:
                        label, idx = entry.rsplit("|", 1)
                        if not label or label.lower() in ("close", "done", "cancel") or any(x in label.lower() for x in SKIP):
                            continue
                        try:
                            pg.evaluate("(i)=>{var e=document.querySelectorAll('dialog[open] button, dialog[open] summary')[i]; if(e) e.click();}", int(idx))
                        except Exception:
                            continue
                        snap(pg, found)
                        # a sub-dialog may have opened; look at it, then close it
                        close_all(pg)
                        if not pg.query_selector("dialog[open]"):
                            try:
                                pg.click("#" + bid, timeout=1000)
                            except Exception:
                                break
                if vp["width"] < 700:
                    pg.close()
                    continue
                # a wine's page and every button on it, one by one (reopened each time)
                def open_info():
                    pg.goto(url); pg.wait_for_selector(".wname", timeout=10000)
                    pg.click(".wname >> nth=0")
                    pg.wait_for_selector("dialog[open]", timeout=3000)
                open_info()
                snap(pg, found)
                n = pg.evaluate("document.querySelectorAll('dialog[open] button, dialog[open] summary').length")
                for i in range(min(n, 60)):
                    open_info()
                    label = pg.evaluate("(i)=>{var e=document.querySelectorAll('dialog[open] button, dialog[open] summary')[i]; return e ? (e.textContent||'').trim() : ''}", i)
                    if not label or label.lower() in ("close", "done", "cancel") or any(x in label.lower() for x in SKIP):
                        continue
                    pg.evaluate("(i)=>{var e=document.querySelectorAll('dialog[open] button, dialog[open] summary')[i]; if(e) e.click();}", i)
                    snap(pg, found)
                    # one level further: buttons of whatever opened on top
                    top = pg.evaluate("document.querySelectorAll('dialog[open]').length")
                    for entry in pg.evaluate("Array.from(document.querySelectorAll('dialog[open]:last-of-type button')).map(function(e,i){return (e.textContent||'').trim()+'|'+i})")[:12]:
                        lab2, idx2 = entry.rsplit("|", 1)
                        if not lab2 or lab2.lower() in ("close", "done", "cancel") or any(x in lab2.lower() for x in SKIP):
                            continue
                        pg.evaluate("(i)=>{var e=document.querySelectorAll('dialog[open]:last-of-type button')[i]; if(e) e.click();}", int(idx2))
                        snap(pg, found)
                    close_all(pg)
                pg.close()
            b.close()
    finally:
        srv.terminate()
    return found


if __name__ == "__main__":
    found = run()
    have = set()
    if os.path.exists(TEMPLATE) and "--raw" not in sys.argv:
        have = set(json.load(open(TEMPLATE, encoding="utf-8")).get("strings", {}))
    for s in sorted(found - have):
        print(s)
