#!/usr/bin/env python3
"""Builds the list of translatable strings: what the page shows (from a crawl file), plus messages and
wording that only appear in some situations (server errors, notices, pairing text).

    python3 scripts/i18n_keys.py crawl.txt > keys.txt     (crawl.txt is the output of i18n_scan.py --raw)
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "wine_cellar", "app")
sys.path.insert(0, APP)

DATA_WORDS = ["Sample Estate", "Old Vines", "Young Cellars", "Bubbly House", "Reserve", "Classic", "Fresh", "Brut", "Syrah", "Rhone",
              "Fridge", "Cellar left", "Lovely", "Germany ×", "Young", "France ×"]
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def clean(s):
    n = [0]

    def sub(m):
        n[0] += 1
        return "{%d}" % (n[0] - 1)
    return re.sub(r"\{#\}", sub, s)


def noise(s):
    if re.fullmatch(r"[A-Z]{3}", s) or re.fullmatch(r"WC\{\d\}", s):
        return True
    if any(w in s for w in DATA_WORDS):
        return True
    if re.match(r"^(%s)\b" % "|".join(MONTHS), s) and (":" in s or re.search(r"\{\d\}", s)):
        return True
    if re.fullmatch(r"(sensor|notify)\.[a-z_]+( \(.*\))?", s) and "empty" not in s:
        return True
    if not re.search(r"[A-Za-z]{3}", s.replace("{0}", "")):
        return True
    if re.match(r"^(Open|Remove filter|Show all wines (from|of)|Move|Edit) ", s) and re.search(r"\{\d\}|Germany|Cellar|Fridge", s):
        return True
    return False


def static_server():
    out = set()
    src = open(os.path.join(APP, "server.py"), encoding="utf-8").read()
    for m in re.finditer(r'ApiError\(\d+,\s*"((?:[^"\\]|\\.)*)"\)', src):
        out.add(ast.literal_eval('"%s"' % m.group(1)))
    return out


def static_js():
    out = set()
    html = open(os.path.join(APP, "static", "index.html"), encoding="utf-8").read()
    for pat in (r"toast\('((?:[^'\\]|\\.)*)'", r"new Error\('((?:[^'\\]|\\.)*)'"):
        for m in re.finditer(pat, html):
            out.add(ast.literal_eval("'%s'" % m.group(1)))
    return out


def pairing_text():
    import pairing
    out = set()
    src = open(os.path.join(APP, "pairing.py"), encoding="utf-8").read()
    for m in re.finditer(r'add\([^"\n]*?"((?:[^"\\]|\\.)*)"\)', src):
        out.add(m.group(1))
    for d in pairing.D.values():
        out.add(d["label"]); out.add(d["group"]); out.add(d["examples"])
    out |= {"a little light for the dish", "a little heavy for the dish"}
    out |= {"Excellent match", "Good match", "Possible match", "Not ideal"}
    for w in ("very light-bodied medium-bodied full-bodied tannic firm high-acid fresh sweet off-dry dry "
              "red white rosé wine mature sparkling crisp").split():
        out.add(w)
    return out


# Notices the page builds from pieces (numbers inside), written out as the page shows them
EXTRA = [
    "Moved {0} bottle", "Moved {0} bottles", "Settings saved", "Saved changes", "Added {0} bottle", "Added {0} bottles",
    "Settings saved. {0} place was made from your shelf texts.", "Settings saved. {0} places were made from your shelf texts.",
    "The bottom bar holds {0}. Move one to More first.", "Imported: {0} new, {1} updated · {2} bottles",
    "Restored {0} wines", "{0} pictures", "{0} entries skipped", "{0} pictures added", "{0} of your own photos kept", "{0} for wines not found",
    "Pasted {0} row", "Pasted {0} rows", "Saved {0} change", "Saved {0} changes",
    "Saved {0}. {1} row needs attention, see the Status column", "Saved {0}. {1} rows need attention, see the Status column",
    "Pasted {0} row. {1} colour or style values were not recognised and skipped", "Pasted {0} rows. {1} colour or style values were not recognised and skipped",
    "Value set to ", "Deleted ", "Reading ", "Restoring ", "Undo", "Error {0}",
]
PREFIXES_OK = {"Value set to ", "Deleted ", "Reading ", "Restoring "}
MONTH_ONLY = set(MONTHS)


def main():
    keys = set()
    if len(sys.argv) > 1:
        for line in open(sys.argv[1], encoding="utf-8"):
            line = line.rstrip("\n")
            if line:
                keys.add(clean(line))
    keys = {k for k in keys if not noise(k)}
    keys |= set(EXTRA)
    for k in static_server() | static_js() | pairing_text():
        if k and not noise(k):
            keys.add(k)
    keys = {k for k in keys if k not in MONTH_ONLY and (k == k.rstrip() or k in PREFIXES_OK)}
    # a line made of keys joined by ", " or " · " is translated piece by piece, so it needs no entry of its own
    def pieces(k):
        return [x for x in re.split(r", | · ", k)]
    keys = {k for k in keys if not (len(pieces(k)) > 1 and all(x in keys or x.rstrip(".") in keys for x in pieces(k)))}
    for k in sorted(keys, key=lambda x: x.lower()):
        print(k)


if __name__ == "__main__":
    main()
