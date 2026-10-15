"""Food and wine pairing, offline.

Everything here is plain data and a few rules, no network and no AI service. It works in two steps:

1. profile(wine) turns what we know about a bottle (grape, appellation, region, colour, style, age)
   into a few traits: body, acidity, tannin, sweetness, bubbles, earthiness, herbal.
2. score(profile, dish) compares those traits with a dish using the usual pairing principles:
   match the weight of wine and food, fat softens tannin, acidity and bubbles cut richness,
   sweet food needs an equally sweet wine, spice clashes with tannin and strong alcohol,
   earthy wines echo earthy food, and older wines suit simple dishes.

The tables are rules of thumb, not a verdict. The wine of a producer can be lighter or bigger than
its grape suggests, so the result is a suggestion with the reason spelled out.
"""
import re
import unicodedata
from datetime import datetime

BODY = ["very light", "light", "medium", "full", "very full"]


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# --------------------------------------------------------------------------- wine traits
# name: (body, acid, tannin, sweet, earthy, herbal)   body 1-5, acid 1-5, tannin 0-5, sweet 0-4
GRAPES = {
    # whites
    "sauvignon blanc": (2, 5, 0, 0, 0, 1), "chardonnay": (3, 3, 0, 0, 0, 0), "riesling": (2, 5, 0, 0, 0, 0),
    "pinot gris": (3, 3, 0, 0, 0, 0), "pinot grigio": (2, 4, 0, 0, 0, 0), "gewurztraminer": (3, 2, 0, 1, 0, 0),
    "chenin blanc": (3, 4, 0, 0, 0, 0), "viognier": (4, 2, 0, 0, 0, 0), "albarino": (2, 4, 0, 0, 0, 0),
    "gruner veltliner": (2, 4, 0, 0, 0, 1), "melon de bourgogne": (1, 4, 0, 0, 0, 0), "muscadet": (1, 4, 0, 0, 0, 0),
    "vermentino": (2, 4, 0, 0, 0, 1), "verdejo": (2, 4, 0, 0, 0, 1), "trebbiano": (2, 3, 0, 0, 0, 0),
    "garganega": (2, 3, 0, 0, 0, 0), "cortese": (2, 4, 0, 0, 0, 0), "fiano": (3, 3, 0, 0, 0, 0),
    "assyrtiko": (3, 5, 0, 0, 0, 0), "picpoul": (2, 5, 0, 0, 0, 0), "marsanne": (4, 2, 0, 0, 0, 0),
    "roussanne": (4, 3, 0, 0, 0, 0), "semillon": (3, 3, 0, 0, 0, 0), "muscat": (2, 3, 0, 1, 0, 0),
    "silvaner": (2, 4, 0, 0, 0, 0), "aligote": (2, 5, 0, 0, 0, 0), "greco": (3, 4, 0, 0, 0, 0),
    "furmint": (3, 5, 0, 0, 0, 0), "torrontes": (2, 3, 0, 0, 0, 0), "godello": (3, 4, 0, 0, 0, 0),
    "arneis": (2, 3, 0, 0, 0, 0), "pinot blanc": (2, 3, 0, 0, 0, 0), "weissburgunder": (2, 3, 0, 0, 0, 0),
    "grenache blanc": (3, 3, 0, 0, 0, 0), "rolle": (2, 4, 0, 0, 0, 1),
    # reds
    "pinot noir": (2, 4, 2, 0, 2, 0), "gamay": (2, 4, 1, 0, 0, 0), "grenache": (3, 3, 2, 0, 1, 0), "garnacha": (3, 3, 2, 0, 1, 0),
    "syrah": (4, 3, 4, 0, 1, 0), "shiraz": (4, 3, 4, 0, 0, 0), "cabernet sauvignon": (5, 3, 5, 0, 1, 0),
    "merlot": (4, 3, 3, 0, 1, 0), "cabernet franc": (3, 4, 3, 0, 1, 1), "malbec": (4, 3, 4, 0, 0, 0),
    "tempranillo": (3, 3, 3, 0, 2, 0), "sangiovese": (3, 5, 4, 0, 2, 0), "nebbiolo": (4, 5, 5, 0, 3, 0),
    "barbera": (3, 5, 2, 0, 0, 0), "zinfandel": (4, 3, 3, 0, 0, 0), "primitivo": (4, 3, 3, 0, 0, 0),
    "carignan": (3, 4, 3, 0, 1, 0), "mourvedre": (4, 3, 4, 0, 2, 0), "monastrell": (4, 3, 4, 0, 1, 0),
    "tannat": (5, 3, 5, 0, 0, 0), "pinotage": (4, 3, 3, 0, 0, 0), "nero d avola": (4, 3, 3, 0, 0, 0),
    "aglianico": (4, 4, 5, 0, 2, 0), "montepulciano": (3, 3, 3, 0, 0, 0), "dolcetto": (3, 3, 3, 0, 0, 0),
    "zweigelt": (2, 4, 2, 0, 0, 0), "blaufrankisch": (3, 4, 3, 0, 1, 0), "touriga nacional": (4, 3, 4, 0, 0, 0),
    "carmenere": (4, 3, 3, 0, 1, 1), "petite sirah": (5, 3, 5, 0, 0, 0), "petit verdot": (5, 3, 5, 0, 0, 0),
    "corvina": (3, 4, 3, 0, 0, 0), "nerello mascalese": (3, 4, 3, 0, 2, 0), "mencia": (3, 4, 3, 0, 1, 0),
    "trousseau": (2, 4, 2, 0, 1, 0), "poulsard": (2, 4, 1, 0, 1, 0), "saperavi": (4, 4, 4, 0, 0, 0),
    "xinomavro": (4, 5, 4, 0, 2, 0), "lagrein": (3, 4, 3, 0, 0, 0), "refosco": (3, 4, 3, 0, 0, 0),
}

# appellations, regions and styles that tell more than a missing grape name
# keyword: (colour or None, body, acid, tannin, sweet, bubbles, earthy, herbal)
PLACES = {
    "chablis": ("White", 2, 5, 0, 0, False, 0, 0), "sancerre": ("White", 2, 5, 0, 0, False, 0, 1),
    "pouilly fume": ("White", 2, 5, 0, 0, False, 0, 1), "muscadet": ("White", 1, 4, 0, 0, False, 0, 0),
    "mosel": ("White", 1, 5, 0, 1, False, 0, 0), "vouvray": ("White", 3, 4, 0, 1, False, 0, 0),
    "savennieres": ("White", 3, 5, 0, 0, False, 0, 0), "meursault": ("White", 4, 3, 0, 0, False, 0, 0),
    "puligny": ("White", 3, 4, 0, 0, False, 0, 0), "chassagne": ("White", 3, 4, 0, 0, False, 0, 0),
    "pouilly fuisse": ("White", 3, 4, 0, 0, False, 0, 0), "rias baixas": ("White", 2, 4, 0, 0, False, 0, 0),
    "soave": ("White", 2, 3, 0, 0, False, 0, 0), "gavi": ("White", 2, 4, 0, 0, False, 0, 0),
    "chianti": ("Red", 3, 5, 4, 0, False, 2, 0), "brunello": ("Red", 4, 5, 5, 0, False, 2, 0),
    "vino nobile": ("Red", 3, 5, 4, 0, False, 2, 0), "barolo": ("Red", 4, 5, 5, 0, False, 3, 0),
    "barbaresco": ("Red", 4, 5, 5, 0, False, 3, 0), "amarone": ("Red", 5, 3, 4, 0, False, 1, 0),
    "valpolicella": ("Red", 3, 4, 2, 0, False, 0, 0), "rioja": ("Red", 3, 3, 3, 0, False, 2, 0),
    "ribera del duero": ("Red", 4, 3, 4, 0, False, 1, 0), "priorat": ("Red", 5, 3, 4, 0, False, 1, 0),
    "bordeaux": ("Red", 4, 3, 4, 0, False, 1, 0), "medoc": ("Red", 4, 3, 4, 0, False, 1, 0),
    "pauillac": ("Red", 5, 3, 5, 0, False, 1, 0), "margaux": ("Red", 4, 3, 4, 0, False, 1, 0),
    "saint estephe": ("Red", 5, 3, 5, 0, False, 1, 0), "saint julien": ("Red", 4, 3, 4, 0, False, 1, 0),
    "pomerol": ("Red", 4, 3, 3, 0, False, 1, 0), "saint emilion": ("Red", 4, 3, 3, 0, False, 1, 0),
    "graves": ("Red", 4, 3, 4, 0, False, 1, 0), "pessac": ("Red", 4, 3, 4, 0, False, 1, 0),
    "chateauneuf": ("Red", 4, 3, 3, 0, False, 1, 0), "cotes du rhone": ("Red", 3, 3, 3, 0, False, 1, 0),
    "hermitage": ("Red", 5, 3, 5, 0, False, 1, 0), "cote rotie": ("Red", 4, 3, 4, 0, False, 1, 0),
    "crozes": ("Red", 3, 3, 3, 0, False, 1, 0), "cornas": ("Red", 5, 3, 5, 0, False, 1, 0),
    "gigondas": ("Red", 4, 3, 4, 0, False, 1, 0), "beaujolais": ("Red", 2, 4, 1, 0, False, 0, 0),
    "morgon": ("Red", 3, 4, 2, 0, False, 0, 0), "fleurie": ("Red", 2, 4, 1, 0, False, 0, 0),
    "moulin a vent": ("Red", 3, 4, 3, 0, False, 0, 0), "chinon": ("Red", 3, 4, 3, 0, False, 1, 1),
    "bourgueil": ("Red", 3, 4, 3, 0, False, 1, 1), "saumur champigny": ("Red", 3, 4, 3, 0, False, 1, 1),
    "gevrey": ("Red", 3, 4, 3, 0, False, 2, 0), "chambolle": ("Red", 2, 4, 2, 0, False, 2, 0),
    "nuits": ("Red", 3, 4, 3, 0, False, 2, 0), "vosne": ("Red", 3, 4, 3, 0, False, 2, 0),
    "pommard": ("Red", 4, 4, 4, 0, False, 2, 0), "volnay": ("Red", 2, 4, 2, 0, False, 2, 0),
    "champagne": (None, 2, 5, 0, 0, True, 0, 0), "cremant": (None, 2, 4, 0, 0, True, 0, 0),
    "cava": (None, 2, 4, 0, 0, True, 0, 0), "prosecco": (None, 1, 4, 0, 1, True, 0, 0),
    "franciacorta": (None, 2, 4, 0, 0, True, 0, 0), "sekt": (None, 2, 4, 0, 0, True, 0, 0),
    "sauternes": ("White", 4, 3, 0, 4, False, 0, 0), "barsac": ("White", 4, 3, 0, 4, False, 0, 0),
    "tokaj": ("White", 4, 5, 0, 4, False, 0, 0), "eiswein": ("White", 3, 5, 0, 4, False, 0, 0),
    "beerenauslese": ("White", 3, 5, 0, 4, False, 0, 0), "trockenbeerenauslese": ("White", 4, 5, 0, 4, False, 0, 0),
    "vendange tardive": ("White", 4, 3, 0, 3, False, 0, 0), "passito": (None, 4, 3, 0, 4, False, 0, 0),
    "moscato d asti": ("White", 1, 3, 0, 3, True, 0, 0), "vin santo": ("White", 4, 3, 0, 4, False, 0, 0),
    "port": ("Red", 5, 3, 4, 4, False, 1, 0), "porto": ("Red", 5, 3, 4, 4, False, 1, 0),
    "madeira": (None, 4, 5, 0, 3, False, 2, 0), "sherry": (None, 3, 4, 0, 0, False, 2, 0),
    "banyuls": ("Red", 4, 3, 3, 4, False, 1, 0), "maury": ("Red", 4, 3, 3, 4, False, 1, 0),
}

SPARKLING_WORDS = ("sparkling", "champagne", "brut", "spumante", "mousseux", "cremant", "cava", "prosecco")
SWEET_WORDS = ("sweet", "dessert", "late harvest", "botrytis", "noble rot", "ice wine", "icewine", "liquoreux")
FORTIFIED_WORDS = ("fortified", "port", "porto", "madeira", "sherry", "banyuls", "maury", "vin doux")


def profile(w, year=None):
    """Traits of one bottle. `w` is a wine row (dict) with the usual wc_wines columns."""
    year = year or datetime.now().year
    color = (w.get("color") or "").strip()
    kind = fold(w.get("type"))
    hay = fold(" ".join(str(w.get(k) or "") for k in ("varietal", "wine", "appellation", "subregion", "region", "designation")))
    padded = " " + hay + " "
    # fallback by colour
    base = {"Red": (3, 3, 3, 0, 1, 0), "White": (2, 4, 0, 0, 0, 0), "Rosé": (2, 4, 1, 0, 0, 0)}.get(color, (3, 3, 2, 0, 0, 0))
    body, acid, tannin, sweet, earthy, herbal = base
    sparkling = any(x in kind or x in hay for x in SPARKLING_WORDS)
    used = []
    # grapes: average the ones we recognise
    found = [g for g in GRAPES if (" " + g + " ") in padded]
    classics = set()
    for g in found:
        classics.update(CLASSICS.get(g, []))
    # drop a grape that only appears as part of a longer matched grape (pinot gris inside pinot grigio is fine, keep both)
    if found:
        used = [GRAPES[g] for g in found]
        n = float(len(used))
        body, acid, tannin, sweet, earthy, herbal = [sum(u[i] for u in used) / n for i in range(6)]
    notes = []
    for key, (c, b, a, t, s, bub, e, hb) in PLACES.items():
        if (" " + key + " ") in padded or (key in ("port", "porto", "sherry", "madeira", "cava") and (" " + key + " ") in " " + kind + " "):
            if c is None or c == color or not color:
                body, acid, tannin, sweet, earthy, herbal = float(b), float(a), float(t), float(s), float(e), float(hb)
                sparkling = sparkling or bub
                notes.append(key)
                classics.update(CLASSICS.get(key, []))
                break
    if any(x in kind or x in hay for x in SWEET_WORDS):
        sweet = max(sweet, 3)
    fortified = any(x in kind for x in FORTIFIED_WORDS)
    if fortified:
        sweet = max(sweet, 3)
        body = max(body, 4)
    try:
        age = year - int(w.get("vintage") or 0) if int(w.get("vintage") or 0) > 1000 else 0
    except (TypeError, ValueError):
        age = 0
    aged = (color == "Red" and age >= 15 and not fortified) or (color != "Red" and age >= 10 and sweet < 3 and not sparkling)
    if aged:
        tannin = max(0, tannin - 1)
        earthy = min(3, earthy + 1)
        body = max(1, body - 0.5)
    if sparkling:
        tannin = 0
    return {
        "color": color or "Unknown", "body": round(body * 2) / 2, "acid": round(acid * 2) / 2, "tannin": round(tannin * 2) / 2,
        "sweet": round(sweet), "bubbles": bool(sparkling), "earthy": round(earthy), "herbal": round(herbal), "aged": bool(aged),
        "known": bool(found or notes), "classics": classics,
    }


def describe(p):
    """One plain sentence about the style, for the bottle's page."""
    if p["bubbles"]:
        parts = ["Sparkling", "off-dry" if p["sweet"] == 1 else ("sweet" if p["sweet"] >= 2 else "dry")]
        return (" ".join(parts) + (", crisp" if p["acid"] >= 4 else "")).capitalize() + "."
    body = BODY[min(4, max(0, int(p["body"] + 0.5) - 1))]
    bits = [body + "-bodied"]
    if p["sweet"] >= 3:
        bits.append("sweet")
    elif p["sweet"] >= 1:
        bits.append("off-dry")
    if p["tannin"] >= 4:
        bits.append("tannic")
    elif p["tannin"] >= 3 and p["color"] == "Red":
        bits.append("firm")
    if p["acid"] >= 4.5:
        bits.append("high-acid")
    elif p["acid"] >= 4:
        bits.append("fresh")
    kind = {"Red": "red", "White": "white", "Rosé": "rosé"}.get(p["color"], "wine")
    s = ", ".join(bits) + " " + kind
    if p["aged"]:
        s += ", mature"
    return s[0].upper() + s[1:] + "."


# --------------------------------------------------------------------------- dishes
# key: (label, group, examples, weight, fat, acid, spice, sweet, salt, earthy, fish, fried, herbal, synonyms)
# fish: 0 none, 1 oily or fried (tannin is a poor match), 2 delicate (tannin is a bad match)
D = {}


def dish(key, label, group, examples, weight, fat=0, acid=0, spice=0, sweet=0, salt=0, earthy=0, fish=0, fried=False, herbal=0, words=""):
    D[key] = {"key": key, "label": label, "group": group, "examples": examples, "weight": weight, "fat": fat, "acid": acid, "spice": spice,
              "sweet": sweet, "salt": salt, "earthy": earthy, "fish": fish, "fried": fried, "herbal": herbal,
              "words": fold(label + " " + examples + " " + words)}


dish("steak", "Grilled steak", "Meat", "ribeye, entrecôte, T-bone", 5, fat=3, salt=1, earthy=1, words="beef biff oxfile entrecote grillat kott")
dish("lamb", "Roast lamb", "Meat", "leg, rack, lamb chops", 4, fat=3, earthy=2, salt=1, words="lamm karre")
dish("braise", "Braised beef and ragù", "Meat", "stew, short rib, bolognese", 4, fat=2, acid=1, earthy=2, words="gryta bourguignon osso buco pot roast")
dish("bbq", "BBQ ribs and burgers", "Meat", "pulled pork, smoked meat, burgers", 4, fat=3, spice=1, sweet=1, salt=2, words="grill hamburgare barbecue smoked")
dish("chicken", "Roast chicken", "Meat", "chicken, turkey, poultry", 3, fat=2, earthy=1, words="kyckling kalkon hona")
dish("duck", "Duck and goose", "Meat", "duck breast, confit, goose", 4, fat=3, acid=1, earthy=2, words="anka gas")
dish("pork", "Roast pork", "Meat", "pork chops, tenderloin, pork belly", 3, fat=2, acid=1, words="flask fil karre revbensspjall")
dish("veal", "Veal and mild meat", "Meat", "veal, schnitzel, rabbit", 3, fat=1, words="kalv kanin")
dish("sausage", "Sausages and meatballs", "Meat", "sausage, meatballs, hot dog", 3, fat=2, acid=1, salt=1, words="korv kottbullar")
dish("charcuterie", "Charcuterie and cured ham", "Meat", "salami, prosciutto, pâté", 3, fat=3, salt=3, words="skinka salami chark paté pate")
dish("game", "Game", "Meat", "venison, elk, wild boar, grouse", 5, fat=1, earthy=3, words="vilt alg hjort rådjur radjur vildsvin")
dish("whitefish", "Delicate white fish", "Fish and seafood", "cod, sole, halibut, pike-perch", 2, fat=1, acid=1, fish=2, words="fisk torsk sandare piggvar rodspatta lutfisk")
dish("salmon", "Salmon, trout and tuna", "Fish and seafood", "grilled or baked, gravlax", 3, fat=2, acid=1, fish=1, words="lax gravad laxfile roding tonfisk")
dish("shellfish", "Oysters, shrimp and crab", "Fish and seafood", "oysters, prawns, langoustine, mussels", 1, acid=2, salt=2, fish=2, words="ostron rakor krabba hummer kraftor musslor skaldjur")
dish("lobster", "Lobster and scallops in butter", "Fish and seafood", "lobster, scallops, creamy seafood", 3, fat=3, fish=2, words="hummer pilgrimsmusslor")
dish("fried_fish", "Fried fish and tempura", "Fish and seafood", "fish and chips, tempura, calamari", 2, fat=3, acid=1, fish=1, fried=True, words="friterad stekt panerad")
dish("sushi", "Sushi and sashimi", "Fish and seafood", "nigiri, maki, poke", 1, acid=1, salt=2, fish=2, words="japanese japansk")
dish("ceviche", "Ceviche and citrus seafood", "Fish and seafood", "ceviche, seafood salad", 1, acid=3, fish=2)
dish("seafood_pasta", "Seafood pasta and paella", "Fish and seafood", "linguine vongole, paella, bouillabaisse", 2, acid=1, fish=1, words="fish soup fiskesoppa")
dish("tomato", "Tomato pasta and pizza", "Pasta and rice", "margherita, spaghetti, bruschetta", 3, fat=1, acid=3, salt=1, words="pizza pasta italian italiensk")
dish("creamy", "Creamy pasta and carbonara", "Pasta and rice", "carbonara, alfredo, gratin", 3, fat=3, salt=2, words="gradde graddsas")
dish("risotto", "Mushroom risotto", "Pasta and rice", "risotto, porcini, chanterelles", 3, fat=2, earthy=3, words="svamp kantarell champinjon steklinglar")
dish("truffle", "Truffle dishes", "Pasta and rice", "truffle pasta, truffle egg, tartufo", 3, fat=2, earthy=3, words="tryffel")
dish("lasagna", "Lasagna and baked pasta", "Pasta and rice", "lasagna, cannelloni, baked ziti", 4, fat=2, acid=2, salt=1, words="ugnsbakad")
dish("salad", "Green salad with vinaigrette", "Vegetables", "salad, raw vegetables, light starters", 1, acid=3, words="sallad")
dish("grilled_veg", "Grilled and roasted vegetables", "Vegetables", "aubergine, peppers, squash, root vegetables", 2, acid=1, earthy=1, words="gronsaker vegetarian vegetarisk")
dish("asparagus", "Asparagus, peas and fresh herbs", "Vegetables", "asparagus, green vegetables, pesto", 1, acid=2, herbal=1, words="sparris artor pesto ort")
dish("goat_cheese", "Goat cheese and herb dishes", "Vegetables", "fresh goat cheese, herb salads, tarts", 2, fat=1, acid=2, herbal=1, words="getost chevre")
dish("curry", "Thai and Indian curry", "Spicy and Asian", "green curry, tikka masala, korma", 3, fat=2, spice=3, sweet=1, words="indian indisk thai thailandsk kokosmjolk")
dish("chilli", "Sichuan and hot chilli dishes", "Spicy and Asian", "mapo tofu, hot wok, spicy noodles", 3, spice=3, words="stark het chili sichuan")
dish("stirfry", "Chinese stir-fry and soy dishes", "Spicy and Asian", "stir-fry, dumplings, teriyaki", 3, spice=1, salt=3, earthy=1, words="kinesisk wok soja dumplings dim sum")
dish("tacos", "Tacos and Mexican", "Spicy and Asian", "tacos, enchiladas, fajitas", 3, fat=2, acid=2, spice=2, words="mexikansk burrito quesadilla")
dish("hard_cheese", "Aged hard cheese", "Cheese", "parmesan, comté, aged cheddar, gouda", 4, fat=2, salt=2, earthy=1, words="ost vasterbotten prastost cheddar manchego")
dish("soft_cheese", "Brie and soft cheese", "Cheese", "brie, camembert, taleggio", 3, fat=3, earthy=1, words="ost mjukost")
dish("blue_cheese", "Blue cheese", "Cheese", "roquefort, gorgonzola, stilton", 4, fat=2, sweet=2, salt=3, words="ost blåmögelost blamogelost")
dish("fruit_dessert", "Fruit tart and apple pie", "Dessert", "tarts, pies, crumble, fruit salad", 3, acid=1, sweet=3, words="efterratt paj karamell glass")
dish("chocolate", "Chocolate dessert", "Dessert", "chocolate cake, brownies, truffles", 4, sweet=4, words="choklad kladdkaka")
dish("cream_dessert", "Cake and creamy dessert", "Dessert", "cheesecake, crème brûlée, panna cotta", 3, fat=2, sweet=3, words="tarta gradd")
dish("foie_gras", "Foie gras and rich pâté", "Dessert", "foie gras, liver pâté", 4, fat=3, sweet=2, salt=1, words="gasleverpastej")
dish("snacks", "Aperitif snacks", "Snacks", "nuts, olives, crisps, canapés", 2, fat=1, salt=3, words="tilltugg chips nötter notter oliver apero")


# Dishes pair across a range of wine weights (a sauce or a cut changes the picture), not at one point
RANGES = {
    "steak": (4, 5), "lamb": (3.5, 5), "braise": (3.5, 5), "bbq": (3.5, 5), "chicken": (2, 4), "duck": (3, 5), "pork": (2.5, 4),
    "veal": (2.5, 4), "sausage": (2.5, 4), "charcuterie": (2, 4), "game": (3.5, 5), "whitefish": (1, 3), "salmon": (2, 3.5),
    "shellfish": (1, 2.5), "lobster": (3, 4.5), "fried_fish": (1, 3), "sushi": (1, 2.5), "ceviche": (1, 2.5), "seafood_pasta": (1.5, 3),
    "tomato": (2.5, 4), "creamy": (2.5, 4), "risotto": (2, 4), "truffle": (2.5, 4.5), "lasagna": (3, 5), "salad": (1, 2.5),
    "grilled_veg": (1.5, 3.5), "asparagus": (1, 2.5), "goat_cheese": (1.5, 3), "curry": (2, 4), "chilli": (1.5, 3.5), "stirfry": (2, 4),
    "tacos": (2.5, 4), "hard_cheese": (3, 5), "soft_cheese": (2, 4), "blue_cheese": (3, 5), "fruit_dessert": (2, 4), "chocolate": (3.5, 5),
    "cream_dessert": (3, 4.5), "foie_gras": (3, 5), "snacks": (1, 3.5),
}
for _k, (_lo, _hi) in RANGES.items():
    D[_k]["lo"], D[_k]["hi"] = _lo, _hi
for _d in D.values():
    _d.setdefault("lo", _d["weight"])
    _d.setdefault("hi", _d["weight"])

# Well-known pairings, keyed by grape or place. They add a bonus on top of the rules above.
CLASSICS = {
    "chablis": ["shellfish", "whitefish", "lobster"], "muscadet": ["shellfish", "whitefish"], "albarino": ["shellfish", "seafood_pasta", "whitefish"],
    "champagne": ["shellfish", "fried_fish", "snacks", "soft_cheese"], "cremant": ["snacks", "fried_fish", "shellfish"],
    "cava": ["snacks", "charcuterie", "seafood_pasta"], "prosecco": ["snacks", "charcuterie"], "franciacorta": ["snacks", "shellfish"],
    "sauvignon blanc": ["goat_cheese", "asparagus", "salad", "shellfish"], "sancerre": ["goat_cheese", "asparagus", "shellfish"],
    "pouilly fume": ["goat_cheese", "asparagus"], "riesling": ["curry", "chilli", "pork", "shellfish"], "mosel": ["curry", "chilli", "pork"],
    "gewurztraminer": ["curry", "chilli", "hard_cheese"], "chardonnay": ["lobster", "creamy", "chicken"], "meursault": ["lobster", "creamy", "chicken"],
    "chenin blanc": ["pork", "curry", "goat_cheese"], "vouvray": ["pork", "curry", "goat_cheese"], "viognier": ["curry", "lobster", "chicken"],
    "gruner veltliner": ["asparagus", "veal", "stirfry"], "verdejo": ["salad", "seafood_pasta"], "vermentino": ["seafood_pasta", "grilled_veg"],
    "pinot grigio": ["whitefish", "seafood_pasta", "snacks"], "pinot gris": ["chicken", "pork", "creamy"], "assyrtiko": ["whitefish", "grilled_veg", "shellfish"],
    "picpoul": ["shellfish", "fried_fish"], "soave": ["seafood_pasta", "risotto"], "gavi": ["seafood_pasta", "whitefish"],
    "pinot noir": ["duck", "risotto", "salmon", "chicken", "truffle"], "gewurz": [], "gamay": ["charcuterie", "sausage", "chicken"],
    "beaujolais": ["charcuterie", "sausage", "chicken"], "fleurie": ["charcuterie", "chicken"], "burgundy": ["duck", "risotto", "chicken", "soft_cheese"],
    "gevrey": ["duck", "game", "soft_cheese"], "chambolle": ["duck", "risotto"], "vosne": ["duck", "game"], "volnay": ["duck", "chicken"],
    "grenache": ["bbq", "lamb", "sausage"], "garnacha": ["bbq", "lamb", "charcuterie"], "syrah": ["bbq", "lamb", "game", "steak"],
    "shiraz": ["bbq", "steak", "lamb"], "hermitage": ["lamb", "game", "steak"], "cote rotie": ["lamb", "game", "duck"],
    "cabernet sauvignon": ["steak", "lamb", "hard_cheese"], "pauillac": ["lamb", "steak"], "medoc": ["lamb", "steak"], "margaux": ["lamb", "duck"],
    "saint estephe": ["steak", "lamb"], "saint julien": ["lamb", "steak"], "bordeaux": ["lamb", "steak", "duck"], "graves": ["lamb", "duck"],
    "merlot": ["chicken", "pork", "tomato", "hard_cheese"], "pomerol": ["duck", "lamb", "truffle"], "saint emilion": ["duck", "lamb", "chicken"],
    "cabernet franc": ["lamb", "pork", "grilled_veg", "charcuterie"], "chinon": ["pork", "charcuterie", "grilled_veg"],
    "malbec": ["steak", "bbq", "sausage"], "tempranillo": ["lamb", "charcuterie", "hard_cheese", "pork"], "rioja": ["lamb", "charcuterie", "hard_cheese"],
    "ribera del duero": ["lamb", "steak"], "sangiovese": ["tomato", "lasagna", "sausage", "hard_cheese"], "chianti": ["tomato", "lasagna", "sausage", "hard_cheese"],
    "brunello": ["game", "steak", "hard_cheese"], "nebbiolo": ["truffle", "risotto", "braise", "game", "hard_cheese"], "barolo": ["truffle", "risotto", "braise", "game"],
    "barbaresco": ["truffle", "risotto", "braise", "veal"], "barbera": ["tomato", "lasagna", "sausage", "tacos"], "dolcetto": ["tomato", "sausage", "charcuterie"],
    "montepulciano": ["tomato", "lasagna", "sausage"], "zinfandel": ["bbq", "sausage", "tacos"], "primitivo": ["bbq", "tomato", "sausage"],
    "mourvedre": ["bbq", "lamb", "braise"], "carmenere": ["steak", "grilled_veg", "bbq"], "tannat": ["steak", "bbq"], "pinotage": ["bbq", "sausage"],
    "nero d avola": ["tomato", "lasagna", "sausage"], "aglianico": ["lamb", "braise", "hard_cheese"], "amarone": ["braise", "hard_cheese", "game"],
    "valpolicella": ["tomato", "sausage", "risotto"], "zweigelt": ["duck", "sausage", "pork"], "blaufrankisch": ["duck", "sausage", "pork"],
    "sauternes": ["foie_gras", "blue_cheese", "fruit_dessert"], "barsac": ["foie_gras", "blue_cheese", "fruit_dessert"], "tokaj": ["foie_gras", "blue_cheese", "fruit_dessert"],
    "eiswein": ["fruit_dessert", "blue_cheese"], "beerenauslese": ["fruit_dessert", "blue_cheese", "foie_gras"], "vendange tardive": ["foie_gras", "fruit_dessert", "blue_cheese"],
    "moscato d asti": ["fruit_dessert", "cream_dessert"], "vin santo": ["fruit_dessert", "hard_cheese"], "port": ["blue_cheese", "chocolate", "hard_cheese"],
    "porto": ["blue_cheese", "chocolate", "hard_cheese"], "banyuls": ["chocolate", "blue_cheese"], "maury": ["chocolate", "blue_cheese"],
    "madeira": ["hard_cheese", "snacks"], "sherry": ["snacks", "charcuterie", "hard_cheese"],
}


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def level(sc):
    return "Excellent" if sc >= 80 else "Good" if sc >= 68 else "Possible" if sc >= 55 else "Not ideal"


def score(p, d):
    """0 to 100, and the reasons that moved the number most."""
    s = 60.0
    why = []

    def add(delta, text):
        nonlocal s
        s += delta
        why.append((delta, text))

    gap = max(d["lo"] - p["body"], p["body"] - d["hi"], 0)
    if gap == 0:
        add(10, "the wine has the right weight for the dish")
    elif gap <= 0.5:
        add(3, "close in weight")
    elif gap <= 1:
        add(-8 * gap, "a little " + ("light" if p["body"] < d["lo"] else "heavy") + " for the dish")
    else:
        add(-14 * gap, "the wine is lighter than the dish" if p["body"] < d["lo"] else "the wine is heavier than the dish")
    if d["key"] in p.get("classics", ()):
        add(14, "a classic match for this grape or region")

    # sweetness
    if d["sweet"] >= 3:
        if p["sweet"] >= d["sweet"]:
            add(14, "the wine is at least as sweet as the dessert")
        elif p["sweet"] == d["sweet"] - 1:
            add(-8, "the wine is a little less sweet than the dessert")
        else:
            add(-38, "a dry wine tastes sour next to a sweet dish")
    elif d["sweet"] == 2:
        if p["sweet"] >= 2:
            add(14, "sweetness balances the salt and richness")
        else:
            add(-12, "a dry wine misses the sweet-salty contrast")
    elif p["sweet"] >= 3:
        add(-32, "a sweet wine is too much for a savoury dish")
    elif p["sweet"] == 2:
        add(-10, "the wine is sweeter than the dish")

    # tannin
    if p["tannin"] >= 2:
        if d["fish"] == 2:
            add(-12 * (p["tannin"] - 1), "tannin turns metallic with delicate seafood")
        elif d["fish"] == 1:
            add(-6 * (p["tannin"] - 1), "tannin is a poor match for fish")
        elif d["spice"] >= 2:
            add(-6 * p["tannin"], "tannin and chilli heat clash")
        elif d["fat"] >= 2:
            add(min(p["tannin"], 4) * 3, "fat softens the tannin")
        elif d["fat"] == 0 and p["tannin"] >= 4:
            add(-10, "this much tannin wants a richer dish")
        if d["salt"] >= 3 and p["tannin"] >= 3 and d["fish"] == 0:
            add(-6, "very salty food makes tannin harsher")

    # acidity
    if d["acid"] >= 2:
        if p["acid"] >= d["acid"] + 1:
            add(8, "fresh acidity matches the tangy food")
        elif p["acid"] < d["acid"]:
            add(-9 * (d["acid"] - p["acid"]), "tart food makes a low-acid wine taste flat")
    if (d["fat"] >= 3 or d["fried"]) and (p["acid"] >= 4 or p["bubbles"]):
        add(8, "acidity cuts through the richness")

    # bubbles
    if p["bubbles"]:
        if d["fat"] >= 2 or d["salt"] >= 2 or d["fried"] or d["weight"] <= 2:
            add(10, "bubbles refresh the palate")
        elif d["weight"] >= 4:
            add(-12, "bubbles are too delicate for a dish this big")

    # spice
    if d["spice"] >= 2:
        if p["sweet"] in (1, 2):
            add(12, "a touch of sweetness calms the heat")
        elif p["sweet"] == 0 and p["body"] >= 4:
            add(-10, "a big dry wine makes the heat feel hotter")
        elif p["acid"] >= 4 and p["body"] <= 2.5:
            add(5, "a light, fresh wine keeps the heat in check")

    # dark chocolate wants a sweet red or fortified wine, not a white dessert wine
    if d["key"] == "chocolate":
        if p["color"] == "Red" and p["sweet"] >= 3:
            add(12, "sweet red and fortified wines stand up to dark chocolate")
        elif p["color"] != "Red":
            add(-15, "white dessert wines get lost next to chocolate")

    # earthy, herbal
    if d["earthy"] >= 2 and p["earthy"] >= 2:
        add(10, "earthy flavours echo each other")
    if d["herbal"] and p["herbal"]:
        add(8, "herbal notes in both")

    # age
    if p["aged"]:
        if d["weight"] >= 4 or d["spice"] >= 2:
            add(-10, "an older wine is best with a simpler dish")
        elif d["earthy"] >= 2:
            add(6, "mature wines love earthy, simple food")

    # rosé, a flexible wine
    if p["color"] == "Rosé" and 2 <= d["weight"] <= 3:
        add(5, "rosé is flexible with this kind of dish")

    return int(round(clamp(s))), why


def reasons(why, n=2, positive=True):
    pick = sorted([x for x in why if (x[0] > 0) == positive and x[0] != 0], key=lambda x: -abs(x[0]))[:n]
    return [t for _, t in pick]


def best_dishes(p, n=6):
    out = []
    for d in D.values():
        sc, why = score(p, d)
        out.append({"key": d["key"], "label": d["label"], "group": d["group"], "examples": d["examples"], "score": sc,
                    "level": level(sc), "why": reasons(why) or reasons(why, 1, False)})
    out.sort(key=lambda x: (-x["score"], x["label"]))
    return out[:n]


def dish_list():
    return [{"key": d["key"], "label": d["label"], "group": d["group"], "examples": d["examples"]} for d in D.values()]


def search_dishes(q):
    q = fold(q)
    if not q:
        return dish_list()
    words = q.split()
    res = []
    for d in D.values():
        hit = sum(1 for w in words if w in d["words"].split() or (len(w) >= 4 and w in d["words"]))
        if hit:
            res.append((hit, d))
    res.sort(key=lambda x: -x[0])
    return [{"key": d["key"], "label": d["label"], "group": d["group"], "examples": d["examples"]} for _, d in res]


def drink_status(w, year=None):
    year = year or datetime.now().year
    b, e = w.get("begin_consume"), w.get("end_consume")
    if not b and not e:
        return "nowin"
    if e and e < year:
        return "past"
    if b and b > year:
        return "hold"
    if e and e == year:
        return "soon"
    return "ready"


WINDOW_BONUS = {"past": 6, "soon": 8, "ready": 4, "nowin": 0, "hold": -12}


def find_wines(dish_key, wines, year=None, limit=12):
    """Rank the bottles in stock for one dish. Bottles that should be drunk soon get a small lift,
    bottles that are not ready yet a small drop; the score itself is only about the match."""
    d = D.get(dish_key)
    if not d:
        return None
    out = []
    for w in wines:
        if (w.get("quantity") or 0) <= 0:
            continue
        p = profile(w, year)
        sc, why = score(p, d)
        st = drink_status(w, year)
        out.append({"id": w["id"], "score": sc, "level": level(sc), "status": st, "rank": sc + WINDOW_BONUS[st],
                    "why": reasons(why) or reasons(why, 1, False), "style": describe(p)})
    out.sort(key=lambda x: (-x["rank"], -x["score"], x["id"]))
    return out[:limit]
