#!/usr/bin/env python3
"""Picture finder: a small tool that runs on your own computer (Mac, Windows or Linux).

1. In Wine Cellar choose More > Import / export > "Download full copy (JSON)".
2. Run:  BRAVE_API_KEY=your-key python3 picture_finder.py   (or put the key in ~/.picture_finder_key)
3. Open http://127.0.0.1:8765, load the JSON file, press "Search all", look over the choices
   (the best match is pre-selected), then "Make zip".
4. In Wine Cellar choose More > Import / export > "Import pictures from a zip".

Only python3 is needed (no installs). The page is served on this computer only. Your API key stays
in this program and is never sent to the page. Pictures are for your own private cellar.
"""
import base64
import csv
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PF_PORT", "8765"))
SEARCH_URL = os.environ.get("PF_SEARCH_URL", "https://api.search.brave.com/res/v1/images/search")
GAP = float(os.environ.get("PF_GAP", "1.1"))  # seconds between searches (Brave's free plan allows about one a second)
MAX_PIC = 3 * 1024 * 1024
UA = "WineCellarPictureFinder/1.0 (personal use)"

_gap = threading.Lock()
_last = [0.0]
STATE = {"wines": []}


def api_key():
    k = os.environ.get("BRAVE_API_KEY", "").strip()
    if not k:
        try:
            with open(os.path.expanduser("~/.picture_finder_key")) as f:
                k = f.read().strip()
        except OSError:
            k = ""
    return k


def sniff(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def query_for(w):
    prod = (w.get("producer") or "").strip()
    name = (w.get("wine") or "").strip()
    rest = " ".join(t for t in name.split() if t.lower() not in prod.lower())
    vint = w.get("vintage")
    parts = [prod, rest, str(vint) if vint not in (None, "", "NV", 0) else "", "wine bottle"]
    return " ".join(p for p in parts if p)[:200]


def search(q):
    key = api_key()
    if not key:
        raise RuntimeError("No API key. Set BRAVE_API_KEY or put it in ~/.picture_finder_key")
    with _gap:
        wait = GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    url = SEARCH_URL + "?" + urllib.parse.urlencode({"q": q, "count": 10, "safesearch": "strict"})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("The search service refused the API key (HTTP %d)" % e.code)
        if e.code == 429:
            raise RuntimeError("Too many searches. Wait a minute and press Search again")
        raise RuntimeError("Search failed (HTTP %d)" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError("Could not reach the search service: %s" % e)
    out = []
    for it in data.get("results") or []:
        props = it.get("properties") or {}
        full = props.get("url") or ""
        thumb = (it.get("thumbnail") or {}).get("src") or ""
        if not (full or thumb):
            continue
        out.append({"thumb": thumb or full, "full": full, "title": (it.get("title") or "")[:120],
                    "page": it.get("url") or "", "source": (it.get("source") or "")[:80]})
    return out[:10]


def fetch(url, limit=MAX_PIC):
    if not url.startswith(("https://", "http://")):
        raise ValueError("bad url")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(limit + 1)
    if len(data) > limit or not sniff(data):
        raise ValueError("not a usable picture")
    return data


def parse_csv(raw):
    """A CellarTracker export or the app's own CSV. Returns wines keyed so the app can match them again."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        iw = (r.get("iWine") or "").strip()
        if not iw:
            continue
        if iw.lower().startswith("wc-") and iw[3:].isdigit():
            key = iw.lower()
        elif iw.isdigit():
            key = "i" + iw
        else:
            continue
        try:
            qty = int(float(r.get("Quantity") or 0))
        except ValueError:
            qty = 0
        vint = (r.get("Vintage") or "").strip()
        out.append({"key": key, "producer": (r.get("Producer") or "").strip(), "wine": (r.get("Wine") or "").strip(),
                    "vintage": "NV" if vint in ("", "1001", "0") else vint, "quantity": qty, "picture": ""})
    return out


def build_zip(picks):
    buf = io.BytesIO()
    sources, added, failed = {}, 0, []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for wid, cand in picks:
            data = None
            if cand.get("data"):
                try:
                    data = base64.b64decode(cand["data"].split(",", 1)[-1], validate=True)
                    if len(data) > MAX_PIC or not sniff(data):
                        data = None
                except ValueError:
                    data = None
            for u in ([] if data else (cand.get("full"), cand.get("thumb"))):
                if not u:
                    continue
                try:
                    data = fetch(u)
                    break
                except Exception:
                    continue
            if not data:
                failed.append(wid)
                continue
            z.writestr("%s.%s" % (wid, sniff(data)), data)
            if cand.get("data"):
                sources[str(wid)] = {"own": True, "credit": "My own picture"}
            else:
                sources[str(wid)] = {"url": cand.get("page") or cand.get("full") or "", "credit": (cand.get("source") or "the web")[:80]}
            added += 1
        z.writestr("sources.json", json.dumps(sources))
    return buf.getvalue(), added, failed


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Picture finder</title><style>
:root{--bg:#fbf8f1;--fg:#1d1a16;--mut:#6b6258;--line:#e2d9c8;--acc:#9b2d3f}
@media(prefers-color-scheme:dark){:root{--bg:#171513;--fg:#f2ece0;--mut:#a39a8b;--line:#3a352e;--acc:#e0788a}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 -apple-system,system-ui,sans-serif;padding:16px;max-width:70rem;margin:0 auto}
h1{font:600 1.6rem Georgia,serif;margin:.2rem 0}.mut{color:var(--mut)}button,input[type=file]{font:inherit}
button{border:1px solid var(--line);background:none;color:var(--fg);border-radius:10px;padding:8px 14px;cursor:pointer}button.p{background:var(--acc);color:#fff;border-color:var(--acc)}
button:disabled{opacity:.5}.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:14px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}
.w{border-top:1px solid var(--line);padding:12px 0}.w b{font-weight:600}.c{display:flex;gap:8px;overflow-x:auto;padding:8px 0}
.c label{flex:0 0 auto;width:110px;cursor:pointer;text-align:center;font-size:.72rem;color:var(--mut)}
.c img{width:110px;height:130px;object-fit:contain;background:#fff;border:2px solid var(--line);border-radius:8px;display:block}
.c input{display:none}.c input:checked+img{border-color:var(--acc);box-shadow:0 0 0 2px var(--acc)}.err{color:#c0392b}
</style></head><body><h1>Picture finder</h1>
<p class="mut">For Wine Cellar. Load your full copy (JSON) or a CSV export, search, check the pre-selected pictures, then make a zip and import it in the app. You can also drag your own picture onto any wine, or use "add my own picture".</p>
<div class="bar"><input type="file" id="f" accept=".json,.csv,application/json,text/csv"><label><input type="checkbox" id="all"> include wines that already have a picture</label>
<button id="go" class="p" disabled>Search all</button><button id="zip" disabled>Make zip</button><span id="st" class="mut"></span></div>
<div id="list"></div>
<script>
var W=[],busy=false;function $(i){return document.getElementById(i)}
function el(t,p,c){var e=document.createElement(t);for(var k in p||{})e[k]=p[k];(c||[]).forEach(function(x){e.appendChild(typeof x==='string'?document.createTextNode(x):x)});return e}
function api(m,p,b){return fetch(p,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined}).then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||r.status);return j})})}
function own(w,file){if(!file||!/^image\//.test(file.type))return;var u=URL.createObjectURL(file),im=new Image();im.onload=function(){var s=Math.min(1,1000/Math.max(im.width,im.height)),c=document.createElement('canvas');c.width=Math.round(im.width*s);c.height=Math.round(im.height*s);c.getContext('2d').drawImage(im,0,0,c.width,c.height);var d=c.toDataURL('image/jpeg',0.88);URL.revokeObjectURL(u);w.cands=w.cands||[];w.cands.unshift({thumb:d,data:d,source:'My picture',title:file.name});w.pick=0;w.msg='';draw()};im.onerror=function(){w.msg='could not read that picture';draw()};im.src=u}
function draw(){var L=$('list');L.textContent='';W.forEach(function(w,i){var row=el('div',{className:'w'},[el('b',{},[w.label]),el('span',{className:'mut',textContent:'  '+(w.picture?'has a picture':'no picture')+(w.msg?' · ':'')}),el('span',{className:'err',textContent:w.msg||''}),el('label',{className:'mut',style:'margin-left:12px;cursor:pointer;text-decoration:underline'},['add my own picture',el('input',{type:'file',accept:'image/*',style:'display:none',onchange:function(){own(w,this.files[0])}})])]);
 row.ondragover=function(e){e.preventDefault();row.style.background='rgba(155,45,63,.08)'};row.ondragleave=function(){row.style.background=''};row.ondrop=function(e){e.preventDefault();row.style.background='';own(w,e.dataTransfer.files[0])};
 if(w.cands){var c=el('div',{className:'c'});var none=el('label',{},[el('input',{type:'radio',name:'r'+i,checked:w.pick===-1,onchange:function(){w.pick=-1}}),el('div',{style:'width:110px;height:130px;border:2px dashed var(--line);border-radius:8px;display:flex;align-items:center;justify-content:center'},['none']),'skip']);c.appendChild(none);
 w.cands.forEach(function(cd,j){c.appendChild(el('label',{title:cd.title},[el('input',{type:'radio',name:'r'+i,checked:w.pick===j,onchange:function(){w.pick=j}}),el('img',{src:cd.thumb,loading:'lazy',referrerPolicy:'no-referrer'}),cd.source||''])) });row.appendChild(c)}
 L.appendChild(row)});$('zip').disabled=!W.some(function(w){return w.cands&&w.pick>=0})}
function setWines(list){W=list.filter(function(w){return w.quantity>0}).map(function(w){return{id:w.key||String(w.id),picture:w.picture||'',label:(w.producer+' '+(w.wine||'')+' '+(w.vintage&&w.vintage!=='NV'?w.vintage:'')).replace(/\s+/g,' ').trim(),raw:w}});
 $('go').disabled=!W.length;$('st').textContent=W.length+' wines in the cellar';draw()}
$('f').onchange=function(){var f=this.files[0];if(!f)return;var bad=function(){$('st').textContent='That is not a Wine Cellar file (use the full copy JSON, or a CSV export)'};
 if(/\.csv$/i.test(f.name)){fetch('/csv',{method:'POST',body:f}).then(function(r){return r.json()}).then(function(d){if(!d.wines||!d.wines.length)return bad();setWines(d.wines)}).catch(bad)}
 else f.text().then(function(t){var d=JSON.parse(t);setWines(d.wines||[])}).catch(bad)};
$('all').onchange=draw;
$('go').onclick=async function(){if(busy)return;busy=true;$('go').disabled=true;var todo=W.filter(function(w){return !(w.cands&&w.cands.length)&&($('all').checked||!w.picture)});
 for(var n=0;n<todo.length;n++){var w=todo[n];$('st').textContent='Searching '+(n+1)+' of '+todo.length+'…';try{var r=await api('POST','/search',{wine:w.raw});w.cands=r.results;w.pick=r.results.length?0:-1;w.msg=r.results.length?'':'nothing found'}catch(e){w.msg=e.message;if(/key|Too many/.test(e.message)){draw();break}}draw()}
 busy=false;$('go').disabled=false;$('st').textContent='Done. Look through the choices, then make the zip.'};
$('zip').onclick=function(){var picks=W.filter(function(w){return w.cands&&w.pick>=0}).map(function(w){return{id:w.id,cand:w.cands[w.pick]}});$('st').textContent='Downloading '+picks.length+' pictures…';$('zip').disabled=true;
 fetch('/zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({picks:picks})}).then(function(r){if(!r.ok)return r.json().then(function(j){throw new Error(j.error)});var a=+r.headers.get('X-Added'),f=r.headers.get('X-Failed');return r.blob().then(function(b){var u=URL.createObjectURL(b),l=el('a',{href:u,download:'wine-pictures.zip'});document.body.appendChild(l);l.click();$('st').textContent=a+' pictures in the zip'+(f?', '+f+' could not be downloaded':'')+'. Now import it in Wine Cellar.'})}).catch(function(e){$('st').textContent=e.message}).then(function(){$('zip').disabled=false})};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PictureFinder"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 60 * 1024 * 1024:
            raise ValueError("too big")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def _local(self):
        # only answer requests for this computer (blocks other sites from calling the tool)
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "local only"})
        if self.path.split("?")[0] == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._local():
            return self._send(403, {"error": "local only"})
        try:
            if self.path == "/csv":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 20 * 1024 * 1024:
                    raise ValueError("too big")
                return self._send(200, {"wines": parse_csv(self.rfile.read(n))})
            body = self._json()
            if self.path == "/search":
                return self._send(200, {"results": search(query_for(body.get("wine") or {}))})
            if self.path == "/zip":
                picks = []
                for p in (body.get("picks") or [])[:600]:
                    c = p.get("cand") or {}
                    key = str(p["id"])
                    if not re.fullmatch(r"(i|wc-)?\d{1,12}", key):
                        raise ValueError("bad id")
                    picks.append((key, {k: str(c.get(k) or "") for k in ("full", "thumb", "page", "source", "data")}))
                data, added, failed = build_zip(picks)
                return self._send(200, data, "application/zip", {"X-Added": str(added), "X-Failed": str(len(failed))})
            self._send(404, {"error": "not found"})
        except RuntimeError as e:
            self._send(502, {"error": str(e)})
        except (ValueError, KeyError, TypeError):
            self._send(400, {"error": "bad request"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Picture finder is running. Open http://127.0.0.1:%d  (Ctrl+C to stop)" % PORT)
    if not api_key():
        print("No API key found yet: set BRAVE_API_KEY or put it in ~/.picture_finder_key before searching.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
