#!/usr/bin/env python3
"""Makes the screenshots in docs/screenshots from a sample cellar with made-up wines.

    python3 scripts/make_screenshots.py
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
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "wine_cellar", "app", "server.py")
OUT = os.path.join(ROOT, "docs", "screenshots")
PORT = 18861
BASE = "http://127.0.0.1:%d" % PORT

WINES = [
    ("Domaine Example", "Les Vignes Hautes", 2016, "Red", "Syrah", "Rhone", "France", 6, 2020, 2032, 34),
    ("Casa di Prova", "Riserva", 2015, "Red", "Sangiovese", "Tuscany", "Italy", 4, 2019, 2030, 42),
    ("Weingut Muster", "Trocken", 2021, "White", "Riesling", "Mosel", "Germany", 12, 2023, 2034, 18),
    ("Bodega Ejemplo", "Crianza", 2018, "Red", "Tempranillo", "Rioja", "Spain", 8, 2021, 2028, 15),
    ("Maison Exemple", "Blanc de Blancs", 2012, "White", "Chardonnay", "Champagne", "France", 3, 2018, 2026, 65),
    ("Quinta de Teste", "Reserva", 2014, "Red", "Touriga Nacional", "Douro", "Portugal", 5, 2018, 2024, 28),
    ("Cantina Esempio", "Barolo", 2017, "Red", "Nebbiolo", "Piedmont", "Italy", 3, 2025, 2040, 55),
    ("Domaine d'Essai", "Rosé de Provence", 2023, "Rosé", "Grenache", "Provence", "France", 6, 2024, 2026, 14),
    ("Sample Hill", "Pinot Noir", 2019, "Red", "Pinot Noir", "Otago", "New Zealand", 4, 2022, 2030, 32),
    ("Weingut Probe", "Grüner Veltliner", 2022, "White", "Grüner Veltliner", "Wachau", "Austria", 6, 2023, 2028, 20),
]


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode() or "null")


def main():
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="wc-shots-")
    env = dict(os.environ, DB_TYPE="sqlite", SQLITE_PATH=os.path.join(tmp, "w.db"), PORT=str(PORT), AUTO_IMAGES="0", AUTO_PRICES="0")
    srv = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/health").read()
                break
            except Exception:
                time.sleep(0.25)
        call("PUT", "/api/settings", {"country": "SE", "currency": "EUR"})
        for p, w, v, c, g, r, co, q, b, e, val in WINES:
            call("POST", "/api/wines", {"producer": p, "wine": w, "vintage": v, "color": c, "varietal": g, "region": r, "country": co,
                                        "quantity": q, "begin": b, "end": e, "value": val, "price": val})
        with sync_playwright() as pw:
            br = pw.chromium.launch()

            def page(w, h, theme="", lang="", touch=False):
                pg = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=2 if touch else 1, has_touch=touch)
                pg.add_init_script("try{localStorage.setItem('wc_theme','%s');localStorage.setItem('wc_lang','%s');}catch(e){}" % (theme, lang))
                pg.goto(BASE + "/")
                pg.wait_for_selector(".wine")
                pg.wait_for_timeout(400)
                return pg

            pg = page(390, 844, touch=True)
            pg.screenshot(path=os.path.join(OUT, "cellar-phone.png"))
            pg.click("#dkDrink"); pg.wait_for_timeout(500)
            pg.screenshot(path=os.path.join(OUT, "drink-now-phone.png"))
            pg.close()
            pg = page(390, 844, theme="dark", touch=True)
            pg.click(".wname >> nth=0"); pg.wait_for_timeout(600)
            pg.screenshot(path=os.path.join(OUT, "wine-dark-phone.png"))
            pg.close()
            pg = page(390, 844, lang="sv", touch=True)
            pg.screenshot(path=os.path.join(OUT, "cellar-swedish-phone.png"))
            pg.close()
            pg = page(1280, 800, theme="dark")
            pg.screenshot(path=os.path.join(OUT, "wall-tablet-dark.png"))
            pg.click("#dkStats"); pg.wait_for_timeout(700)
            pg.screenshot(path=os.path.join(OUT, "stats.png"))
            pg.close()
            br.close()
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
