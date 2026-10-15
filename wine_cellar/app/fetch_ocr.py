#!/usr/bin/env python3
"""Download the on-device text reader (Tesseract.js) while the add-on image is built.

Everything is stored inside the add-on and served from it, so reading a label photo
happens in your own browser and nothing is sent anywhere when you use it. If any
download fails the feature is simply left out: the add-on works without it.
"""
import json
import os
import shutil
import sys
import urllib.request

CDN = "https://cdn.jsdelivr.net/npm/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "vendor")
CORE = [
    ("tesseract.js@5.1.1/dist/tesseract.min.js", "tesseract.min.js"),
    ("tesseract.js@5.1.1/dist/worker.min.js", "worker.min.js"),
    ("tesseract.js-core@5.1.0/tesseract-core-simd-lstm.wasm.js", "core/tesseract-core-simd-lstm.wasm.js"),
    ("tesseract.js-core@5.1.0/tesseract-core-lstm.wasm.js", "core/tesseract-core-lstm.wasm.js"),
]
LANGS = ["eng", "fra", "ita", "spa"]


def get(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "WineCellarBuild/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    if os.path.getsize(dest) < 1000:
        raise RuntimeError("file too small: " + url)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    try:
        for src, name in CORE:
            get(CDN + src, os.path.join(OUT, name))
        got = []
        for lang in LANGS:
            try:
                get(CDN + "@tesseract.js-data/%s@1.0.0/4.0.0_best_int/%s.traineddata.gz" % (lang, lang), os.path.join(OUT, "lang", lang + ".traineddata.gz"))
                got.append(lang)
            except Exception as e:  # a missing extra language is fine, English is required
                print("language %s skipped: %s" % (lang, e))
                if lang == "eng":
                    raise
        with open(os.path.join(OUT, "ready.json"), "w") as f:
            json.dump({"langs": got}, f)
        print("Label reader installed: " + ", ".join(got))
    except Exception as e:
        shutil.rmtree(OUT, ignore_errors=True)
        print("Label reader not installed (%s). The add-on works without it." % e)


if __name__ == "__main__":
    main()
    sys.exit(0)
