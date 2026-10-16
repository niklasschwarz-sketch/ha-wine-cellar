"""Tests for tools/picture-finder (a fake search service and fake picture host, no internet)."""
import base64, http.server, io, json, os, subprocess, sys, tempfile, threading, time, urllib.request, zipfile

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
MOCK, PORT = 18931, 18930
fails = []
SEEN = []


def check(name, ok, info=None):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "   -> %s" % (info,)))
    if not ok:
        fails.append(name)


class Mock(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/search"):
            SEEN.append((self.path, self.headers.get("X-Subscription-Token")))
            res = [{"title": "Bottle %d" % i, "url": "https://shop.example/%d" % i, "source": "shop.example",
                    "thumbnail": {"src": "http://127.0.0.1:%d/img%d.png" % (MOCK, i)}, "properties": {"url": "http://127.0.0.1:%d/img%d.png" % (MOCK, i)}} for i in range(10)]
            body = json.dumps({"results": res}).encode()
            ctype = "application/json"
        else:
            body, ctype = PNG, "image/png"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


mock = http.server.ThreadingHTTPServer(("127.0.0.1", MOCK), Mock)
threading.Thread(target=mock.serve_forever, daemon=True).start()
env = dict(os.environ, PF_PORT=str(PORT), PF_SEARCH_URL="http://127.0.0.1:%d/search" % MOCK, BRAVE_API_KEY="testkey", PF_GAP="0")
proc = subprocess.Popen([sys.executable, "tools/picture-finder/picture_finder.py"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = "http://127.0.0.1:%d" % PORT


def post(path, body, host=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


try:
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    with urllib.request.urlopen(BASE + "/", timeout=5) as r:
        check("page is served", r.status == 200 and b"Picture finder" in r.read())
    s, b, _ = post("/search", {"wine": {"producer": "Chateau Test", "wine": "Chateau Test Reserve", "vintage": 2019}})
    res = json.loads(b)["results"]
    check("search returns ten candidates", s == 200 and len(res) == 10 and res[0]["thumb"].endswith("img0.png"), res[:1])
    check("query uses producer, name and vintage, and the key is sent", "Chateau+Test" in SEEN[-1][0] and "Reserve" in SEEN[-1][0] and "2019" in SEEN[-1][0] and SEEN[-1][1] == "testkey", SEEN[-1])
    check("other websites cannot call it", post("/search", {"wine": {}}, host="evil.example")[0] == 403)
    own = "data:image/png;base64," + base64.b64encode(PNG).decode()
    s, b, h = post("/zip", {"picks": [{"id": 5, "cand": res[0]}, {"id": 6, "cand": {"data": own, "source": "My picture"}}, {"id": 7, "cand": {"full": "http://127.0.0.1:1/x.png", "thumb": ""}}]})
    z = zipfile.ZipFile(io.BytesIO(b))
    names = sorted(z.namelist())
    src = json.loads(z.read("sources.json"))
    check("zip holds the chosen pictures named by wine id", s == 200 and names == ["5.png", "6.png", "sources.json"] and h["X-Added"] == "2" and h["X-Failed"] == "1", (names, h["X-Added"], h["X-Failed"]))
    check("zip records sources, and marks your own picture", src["5"]["url"] == "https://shop.example/0" and src["6"].get("own") is True, src)
    csvtxt = "\ufeffiWine,Type,Color,Quantity,Vintage,Wine,Producer\r\n123456,Red - Dry,Red,2,2019,Cuvee X,Domaine Test\r\nwc-7,White,White,1,1001,Plain,Some Estate\r\n999,Red,Red,0,2015,Empty,Gone\r\n,Red,Red,1,2015,NoId,Nobody\r\n"
    req = urllib.request.Request(BASE + "/csv", data=csvtxt.encode("utf-8"), method="POST")
    cw = json.loads(urllib.request.urlopen(req, timeout=5).read())["wines"]
    check("a CSV export is read, keyed so the app can match it", [(w["key"], w["quantity"], w["vintage"]) for w in cw] == [("i123456", 2, "2019"), ("wc-7", 1, "NV"), ("i999", 0, "2015")], cw)
    s, b, h = post("/zip", {"picks": [{"id": "i123456", "cand": res[0]}]})
    check("zip files for CSV wines are named by their key", "i123456.png" in zipfile.ZipFile(io.BytesIO(b)).namelist(), s)
    check("bad request is refused", post("/zip", {"picks": [{"cand": {}}]})[0] == 400)

    from playwright.sync_api import sync_playwright
    wines = [{"id": 1, "producer": "Alpha", "wine": "Alpha Rouge", "vintage": 2018, "quantity": 2, "picture": ""},
             {"id": 2, "producer": "Beta", "wine": "Beta", "vintage": "NV", "quantity": 1, "picture": "upload"},
             {"id": 3, "producer": "Gone", "wine": "Gone", "vintage": 2010, "quantity": 0, "picture": ""}]
    tmp = tempfile.mkdtemp()
    jp = os.path.join(tmp, "backup.json")
    open(jp, "w").write(json.dumps({"app": "wine-cellar", "wines": wines}))
    pp = os.path.join(tmp, "mine.png")
    open(pp, "wb").write(PNG)
    errors = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_page(accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        page.set_input_files("#f", jp)
        page.wait_for_function("() => document.querySelectorAll('.w').length === 2")
        check("wines in the cellar are listed, empty ones are not", True)
        page.click("#go")
        page.wait_for_function("() => document.querySelectorAll('.w').length === 2 && document.querySelectorAll('.w')[0].querySelectorAll('img').length === 10")
        check("only wines without a picture are searched by default", page.locator(".w").nth(1).locator("img").count() == 0)
        page.locator(".w").nth(1).locator("input[type=file]").set_input_files(pp)
        page.wait_for_function("() => document.querySelectorAll('.w')[1].querySelectorAll('img').length === 1")
        check("your own picture can be added to a wine", True)
        with page.expect_download() as dl:
            page.click("#zip")
        zz = zipfile.ZipFile(dl.value.path())
        check("the page makes a zip with both", sorted(zz.namelist()) == ["1.png", "2.jpg", "sources.json"] or sorted(zz.namelist()) == ["1.png", "2.png", "sources.json"], zz.namelist())
        check("no script errors", errors == [], errors)
        br.close()
finally:
    proc.terminate()
    mock.shutdown()

print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("All picture finder tests passed")
