#!/usr/bin/env python3
"""Fetch wars & armed conflicts from Wikidata (linked to English Wikipedia) into data/wars.json.

Usage: python3 scripts/fetch_wars.py
"""
import json, math, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "warmap/0.1 (https://github.com/egil10/warmap)"
OUT = Path(__file__).resolve().parent.parent / "data" / "wars.json"

# Classes to pull. Each queried separately to keep queries under the timeout.
CLASSES = {
    "Q198": "war",
    "Q8465": "civil war",
    "Q467011": "invasion",
    "Q124734": "rebellion",
    "Q10931": "revolution",
    "Q1006311": "war of independence",
    "Q766875": "ethnic conflict",
    "Q1323212": "insurgency",
    "Q45382": "coup d'état",
    "Q864113": "proxy war",
    "Q2659056": "colonial war",
    "Q582956": "punitive expedition",
    "Q5919191": "military intervention",
    "Q1361229": "conquest",
    "Q1827102": "religious war",
    "Q107637520": "border conflict",
}

QUERY = """
SELECT ?item ?itemLabel ?article ?parent ?s580 ?s571 ?s585 ?end ?coord ?locCoord ?countryCoord ?countryLabel ?desc WHERE {
  ?item wdt:P31/wdt:P279* wd:%(cls)s .
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
  OPTIONAL { ?item wdt:P580 ?s580 }
  OPTIONAL { ?item wdt:P571 ?s571 }
  OPTIONAL { ?item wdt:P585 ?s585 }
  FILTER(BOUND(?s580) || BOUND(?s571) || BOUND(?s585))
  OPTIONAL { ?item wdt:P582 ?end }
  OPTIONAL { ?item wdt:P361 ?parent }
  OPTIONAL { ?item wdt:P625 ?coord }
  OPTIONAL { ?item wdt:P276 ?loc . ?loc wdt:P625 ?locCoord }
  OPTIONAL { ?item wdt:P17 ?country . ?country wdt:P625 ?countryCoord }
  OPTIONAL { ?item schema:description ?desc FILTER(LANG(?desc) = "en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

def sparql(q, tries=3):
    """Run a query. Returns rows, or None if every attempt failed."""
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    last = "unknown"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:
            last = e
            print(f"  retry {i+1}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    print(f"  giving up: {last}", file=sys.stderr)
    return None

# Broad classes: direct instance-of only (subclass closure times out).
DIRECT_CLASSES = {
    "Q350604": "armed conflict", "Q645883": "military operation", "Q2001676": "military offensive",
    "Q831663": "military campaign", "Q1261499": "naval warfare", "Q15835236": "military action",
    "Q188686": "military occupation",
    "Q178561": "battle", "Q188055": "siege", "Q997267": "skirmish",
}

# For these, only keep items that are NOT already a sub-event of a conflict we have
# (those show up as sites on their parent instead).
STANDALONE_ONLY = {"battle", "siege", "skirmish"}
SPLIT_BY_YEAR = {"battle", "siege"}
YEAR_SLICES = [(-5000, 1000), (1000, 1500), (1500, 1700), (1700, 1800), (1800, 1860), (1860, 1914),
               (1914, 1919), (1919, 1939), (1939, 1942), (1942, 1946), (1946, 1990), (1990, 3000)]

# Sub-events (battles, sieges, campaigns...) that are part of a war, with coordinates.
# This is what places a war *inside* a country rather than at the country centroid.
SUB_QUERY = """
SELECT ?war ?sub ?subLabel ?coord ?date WHERE {
  VALUES ?war { %(values)s }
  ?sub (wdt:P361|wdt:P361/wdt:P361|wdt:P361/wdt:P361/wdt:P361) ?war .
  { ?sub wdt:P625 ?coord } UNION { ?sub wdt:P276/wdt:P625 ?coord }
  OPTIONAL { ?sub wdt:P585|wdt:P580 ?date }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Death toll (P1120) and belligerents (P710). Separate from the class queries so those stay under the timeout.
META_QUERY = """
SELECT ?item ?deaths ?sideLabel WHERE {
  VALUES ?item { %(values)s }
  OPTIONAL { ?item wdt:P1120 ?deaths }
  OPTIONAL { ?item wdt:P710 ?side }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

PT = re.compile(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)")

def parse_point(s):
    m = PT.search(s or "")
    return (round(float(m.group(2)), 3), round(float(m.group(1)), 3)) if m else None

def parse_date(s):
    # Wikidata xsd:dateTime e.g. "1914-07-28T00:00:00Z" or "-0490-01-01T00:00:00Z"
    if not s:
        return None
    m = re.match(r"(-?\d+)-(\d\d)-(\d\d)", s)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2)) or 1
    return [y, max(1, min(12, mo))]

CLASSES_ROWS = []

def ingest(items, name, rows):
    for r in rows:
        qid = r["item"]["value"].rsplit("/", 1)[-1]
        label = r.get("itemLabel", {}).get("value", qid)
        if re.fullmatch(r"Q\d+", label):
            continue
        it = items.setdefault(qid, {
            "id": qid, "name": label,
            "wiki": r["article"]["value"],
            "desc": r.get("desc", {}).get("value", ""),
            "type": name,
            "starts": {"s580": set(), "s571": set(), "s585": set()}, "ends": set(),
            "coord": None, "loc": None, "countries": {}, "parents": set(),
        })
        if r.get("parent"): it["parents"].add(r["parent"]["value"].rsplit("/", 1)[-1])
        for k in ("s580", "s571", "s585"):
            if r.get(k): it["starts"][k].add(r[k]["value"])
        if r.get("end"): it["ends"].add(r["end"]["value"])
        if r.get("coord") and not it["coord"]: it["coord"] = parse_point(r["coord"]["value"])
        if r.get("locCoord") and not it["loc"]: it["loc"] = parse_point(r["locCoord"]["value"])
        if r.get("countryCoord"):
            it["countries"].setdefault(r.get("countryLabel", {}).get("value", "?"), parse_point(r["countryCoord"]["value"]))


def ongoing_titles():
    """Article titles linked from Wikipedia's 'List of ongoing armed conflicts'."""
    titles, cont = set(), {}
    while True:
        params = {"action": "query", "titles": "List of ongoing armed conflicts", "prop": "links",
                  "plnamespace": 0, "pllimit": "max", "format": "json", "redirects": 1, **cont}
        req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        for page in data["query"]["pages"].values():
            for l in page.get("links", []):
                titles.add(l["title"])
        if "continue" not in data:
            return titles
        cont = data["continue"]

LONG_TYPES = {"war", "civil war", "insurgency", "rebellion", "armed conflict", "war of independence", "revolution",
              "proxy war", "colonial war", "religious war", "ethnic conflict", "border conflict", "military occupation"}

def add_months(ym, n):
    t = ym[0] * 12 + (ym[1] - 1) + n
    return [t // 12, t % 12 + 1]

# Pages that are not themselves conflicts: year chronicles, lists, and revolutions that were not wars.
CHRONICLE = re.compile(r"^(?:timeline of|list of|\d{3,4} in )\b", re.I)
NOISE_NAME = re.compile(
    r"\b(?:neolithic|industrial|scientific|cultural|sexual|digital|green|white|velvet|"
    r"orange|rose|tulip|cedar|bolivarian|people power|price|agricultural|quantum|colou?r) revolution\b",
    re.I,
)
PEACEFUL_DESC = (
    "hunter-gatherer", "hunter gatherer", "sociopolitical movement", "series of protests",
    "democratization", "peaceful", "political process", "reforms by", "popular demonstrations",
    "protest movement", "transition from communism", "nonviolent", "non-violent",
)
SITE_LIMIT = 220

def valid_pt(p):
    """Reject null-island and the exact-equator defaults Wikidata sometimes stores (World War II is 0°N, 15°E)."""
    if not p:
        return False
    lat, lng = p
    if not (-85 <= lat <= 85 and -180 <= lng <= 180):
        return False
    if abs(lat) < 0.05 and abs(lng) < 0.05:
        return False
    if abs(lat) < 0.001:
        return False
    return True

def km(a, b):
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))

def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2

def is_noise(it):
    if CHRONICLE.match(it["name"]) or NOISE_NAME.search(it["name"]):
        return True
    if it["type"] == "revolution":
        desc = it["desc"].lower()
        if any(s in desc for s in PEACEFUL_DESC):
            return True
    return False

def _mentioned(name, country):
    n, c = name.lower(), country.lower()
    if len(c) >= 4 and c in n:
        return True
    last = c.split()[-1]
    stem = last[:4]
    return len(stem) >= 4 and stem in n

def country_point(countries, name):
    """One on-land fallback. Never the midpoint of countries on different continents (that lands in the ocean)."""
    pts = [(n, p) for n, p in countries.items() if n != "?" and valid_pt(p)]
    if not pts:
        return None
    ment = [(n, p) for n, p in pts if _mentioned(name, n)]
    pool = ment or pts
    if len(pool) == 1:
        return pool[0][1]
    far = max(km(a[1], b[1]) for i, a in enumerate(pool) for b in pool[i + 1:])
    if far <= 1800:
        return (round(sum(p[0] for _, p in pool) / len(pool), 3), round(sum(p[1] for _, p in pool) / len(pool), 3))
    if ment:
        return ment[0][1]
    med = (median([p[0] for _, p in pts]), median([p[1] for _, p in pts]))
    return min(pts, key=lambda np: km(np[1], med))[1]

def thin_sites(sites, limit=SITE_LIMIT):
    """Deduplicate, drop bad coordinates, and spread the kept sites across the map instead of taking an arbitrary prefix."""
    seen, uniq = set(), []
    for lat, lng, name, date in sites:
        if not valid_pt((lat, lng)) or not name or re.fullmatch(r"Q\d+", name):
            continue
        key = (round(lat, 2), round(lng, 2), name)
        if key in seen:
            continue
        seen.add(key)
        uniq.append([lat, lng, name, date])
    if len(uniq) <= limit:
        return uniq
    buckets = defaultdict(list)
    for s in uniq:
        buckets[(round(s[0] / 12), round(s[1] / 12))].append(s)

    def rank(s):
        n = s[2].lower()
        pri = 0 if re.match(r"(?:battle|siege|raid|capture|fall|sack|bombardment|naval battle)\b", n) else 1
        return (pri, 0 if s[3] else 1, n)

    for bucket in buckets.values():
        bucket.sort(key=rank)
    out, keys, i = [], list(buckets), 0
    while len(out) < limit and any(buckets.values()):
        bucket = buckets[keys[i % len(keys)]]
        if bucket:
            out.append(bucket.pop(0))
        i += 1
        if i > limit * len(keys) + 5:
            break
    return out

def place(it, sites):
    """Own coordinate, unless it is missing or far from the fighting — then the middle of the battle sites."""
    pts = [(s[0], s[1]) for s in sites]
    own = it["coord"] if valid_pt(it["coord"]) else None
    loc = it["loc"] if valid_pt(it["loc"]) else None
    if len(pts) >= 4:
        med = (median([p[0] for p in pts]), median([p[1] for p in pts]))
        nearest = min(pts, key=lambda p: km(p, med))
        center = nearest if km(nearest, med) > 400 else med
        center = (round(center[0], 3), round(center[1], 3))
        anchor = own or loc
        if anchor is None or km(anchor, center) > 500:
            return center, True
        return anchor, True
    if own:
        return own, True
    if loc:
        return loc, True
    if pts:
        if len(pts) == 1:
            return pts[0], True
        return (round(sum(p[0] for p in pts) / len(pts), 3), round(sum(p[1] for p in pts) / len(pts), 3)), True
    c = country_point(it["countries"], it["name"])
    if c:
        return (round(c[0], 3), round(c[1], 3)), False
    return None, False

def fetch_chunked(qids, query, size, label):
    rows_out = []
    i = 0
    step = size
    while i < len(qids):
        chunk = qids[i:i + step]
        print(f"{label} {i}/{len(qids)}…", file=sys.stderr)
        rows = sparql(query % {"values": " ".join("wd:" + q for q in chunk)})
        if rows is None and len(chunk) >= 40:
            step = max(20, step // 2)
            print(f"  shrinking chunks to {step}", file=sys.stderr)
            time.sleep(2)
            continue
        if rows is None:
            print(f"  skipped a {len(chunk)}-id chunk", file=sys.stderr)
            rows = []
        rows_out.extend(rows)
        i += len(chunk)
        step = size
        time.sleep(1)
    return rows_out

COUNTRIES = OUT.parent / "countries.geojson"

def _in_ring(x, y, r):
    inside = False
    j = len(r) - 1
    for i in range(len(r)):
        xi, yi = r[i]; xj, yj = r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside

def assign_countries(wars):
    """Tag each conflict with the modern countries (ADM0_A3) its location and battle sites fall in."""
    if not COUNTRIES.exists():
        print("countries.geojson missing — run scripts/build_countries.py", file=sys.stderr)
        return
    polys = []
    for f in json.loads(COUNTRIES.read_text())["features"]:
        for poly in f["geometry"]["coordinates"]:
            xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
            polys.append((f["id"], (min(xs), min(ys), max(xs), max(ys)), poly))
    cache = {}
    def lookup(lat, lng):
        key = (round(lat, 1), round(lng, 1))
        if key not in cache:
            cache[key] = None
            for a3, (x0, y0, x1, y1), poly in polys:
                if x0 <= lng <= x1 and y0 <= lat <= y1 and _in_ring(lng, lat, poly[0]) \
                        and not any(_in_ring(lng, lat, h) for h in poly[1:]):
                    cache[key] = a3
                    break
        return cache[key]
    for w in wars:
        pts = [(w["lat"], w["lng"])] + [(s_[0], s_[1]) for s_ in w["sites"]]
        if not w["precise"]:
            pts = [(s_[0], s_[1]) for s_ in w["sites"]]  # country-centroid fallback is too coarse to trust
        found = []
        for lat, lng in pts:
            a3 = lookup(lat, lng)
            if a3 and a3 not in found:
                found.append(a3)
        w["iso"] = found

def self_check():
    assert is_noise({"name": "1955 in the Vietnam War", "type": "war", "desc": ""})
    assert is_noise({"name": "Cultural Revolution", "type": "revolution", "desc": "movement"})
    assert is_noise({"name": "Neolithic Revolution", "type": "revolution", "desc": "transition from hunter gatherer"})
    assert not is_noise({"name": "French Revolution", "type": "revolution", "desc": "A period of political and societal change in France"})
    assert not is_noise({"name": "Wars of the Roses", "type": "war", "desc": "civil war"})
    assert not valid_pt((0.0, 15.0))
    assert valid_pt((48.8, 2.3))
    ww2 = {"coord": (0.0, 15.0), "loc": None, "countries": {}, "name": "World War II"}
    european = [[49.0, 2.3, "A", [1914, 9]], [48.8, 2.3, "B", None], [50.0, 3.0, "C", None], [51.5, -0.1, "D", None]]
    pos, precise = place(ww2, thin_sites(european))
    assert precise and pos[0] > 40, pos
    acw = {"coord": (39.828, -98.579), "loc": None, "countries": {}, "name": "American Civil War"}
    virginia = [[37.6, -77.5, "Bull Run", None], [37.2, -76.5, "X", None], [39.8, -77.2, "Gettysburg", None], [35.0, -80.0, "Y", None]]
    pos, precise = place(acw, virginia)
    assert precise and pos[1] > -85, pos
    spain = country_point({"Spain": (40.0, -4.0), "Mexico": (23.0, -102.0)}, "Spanish conquest of the Aztec Empire")
    assert spain == (40.0, -4.0), spain
    far = country_point({"France": (47.0, 2.0), "Japan": (36.0, 138.0)}, "Some Distant War")
    assert far in ((47.0, 2.0), (36.0, 138.0)), far
    spread = [[10, 10, f"Battle of A{i}", None] for i in range(30)] + [[40, 140, f"Battle of B{i}", None] for i in range(30)]
    kept = thin_sites(spread, limit=10)
    assert any(s[1] > 100 for s in kept) and any(s[1] < 50 for s in kept)
    print("self-check ok")

def _require(rows, name):
    if rows is None:
        print(f"query failed for {name}; not overwriting {OUT.name}", file=sys.stderr)
        sys.exit(1)
    return rows

def _better(a, b):
    return (len(a["sites"]), a["precise"], 0 if a["endApprox"] else 1, a.get("deaths") or 0) > \
           (len(b["sites"]), b["precise"], 0 if b["endApprox"] else 1, b.get("deaths") or 0)

def dedup(out):
    best, order = {}, []
    for w in out:
        key = (w["name"].casefold(), w["start"][0], round(w["lat"]), round(w["lng"]))
        prev = best.get(key)
        if prev is None:
            best[key] = w
            order.append(key)
        elif _better(w, prev):
            best[key] = w
    return [best[k] for k in order]

def sane(out):
    if len(out) < 4000:
        return f"only {len(out)} conflicts"
    ww2 = next((w for w in out if w["name"] == "World War II"), None)
    if ww2 is None:
        return "World War II missing"
    if not (36 <= ww2["lat"] <= 60 and -12 <= ww2["lng"] <= 45):
        return f"World War II is outside Europe ({ww2['lat']},{ww2['lng']})"
    if not any(w["name"] == "American Civil War" for w in out):
        return "American Civil War missing"
    if sum(bool(w["sites"]) for w in out) < 800:
        return "too few battles mapped"
    if any(w["name"].lower().startswith("neolithic") for w in out):
        return "neolithic revolution still present"
    return None

POINT_EVENTS = {"battle", "siege", "skirmish", "naval warfare"}

def main():
    if "--check" in sys.argv:
        self_check()
        return
    if "--countries-only" in sys.argv:
        data = json.loads(OUT.read_text())
        assign_countries(data["wars"])
        OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"Tagged countries for {len(data['wars'])} conflicts", file=sys.stderr)
        return
    items = {}
    for cls, name in CLASSES.items():
        print(f"Querying {name} ({cls})…", file=sys.stderr)
        rows = _require(sparql(QUERY % {"cls": cls}), name)
        print(f"  {len(rows)} rows", file=sys.stderr)
        ingest(items, name, rows)
        time.sleep(2)
    for cls, name in DIRECT_CLASSES.items():
        print(f"Querying {name} ({cls}, direct)…", file=sys.stderr)
        q = (QUERY % {"cls": cls}).replace("wdt:P31/wdt:P279*", "wdt:P31")
        if name in SPLIT_BY_YEAR:
            # Too many results for one response: page through by start year.
            rows = []
            for lo, hi in YEAR_SLICES:
                f = f"  FILTER(YEAR(COALESCE(?s580, ?s571, ?s585)) >= {lo} && YEAR(COALESCE(?s580, ?s571, ?s585)) < {hi})\n  SERVICE"
                rows += _require(sparql(q.replace("  SERVICE", f, 1)), f"{name} {lo}-{hi}")
                time.sleep(1)
        else:
            rows = _require(sparql(q), name)
        print(f"  {len(rows)} rows", file=sys.stderr)
        CLASSES_ROWS.append((name, rows))
        time.sleep(2)
    for name, rows in CLASSES_ROWS:
        if name not in STANDALONE_ONLY:
            ingest(items, name, rows)
    # Battles etc.: keep only those not part of a conflict already in the set.
    events = {}
    for name, rows in CLASSES_ROWS:
        if name in STANDALONE_ONLY:
            ingest(events, name, rows)
    kept = 0
    for q, ev in events.items():
        if q not in items and not (ev["parents"] & items.keys()):
            items[q] = ev
            kept += 1
    print(f"Standalone battles/sieges kept: {kept}", file=sys.stderr)
    noise = [q for q, it in items.items() if is_noise(it)]
    for q in noise:
        del items[q]
    print(f"Dropped {len(noise)} non-conflicts", file=sys.stderr)

    subs = {}
    for r in fetch_chunked(list(items), SUB_QUERY, 120, "Sub-events"):
        w = r["war"]["value"].rsplit("/", 1)[-1]
        sid = r["sub"]["value"].rsplit("/", 1)[-1]
        pt = parse_point(r["coord"]["value"])
        if not pt:
            continue
        d = subs.setdefault(w, {}).setdefault(sid, {"n": r.get("subLabel", {}).get("value", sid), "p": pt, "d": None})
        if r.get("date") and not d["d"]:
            d["d"] = parse_date(r["date"]["value"])

    for r in fetch_chunked(list(items), META_QUERY, 150, "Belligerents"):
        it = items.get(r["item"]["value"].rsplit("/", 1)[-1])
        if not it:
            continue
        if r.get("deaths"):
            try:
                n = int(float(r["deaths"]["value"]))
            except ValueError:
                n = 0
            if 0 < n < 200_000_000:
                it["deaths"] = max(it.get("deaths") or 0, n)
        side = r.get("sideLabel", {}).get("value")
        if side and not re.fullmatch(r"Q\d+", side):
            sides = it.setdefault("sides", [])
            if side not in sides and len(sides) < 8:
                sides.append(side)

    try:
        ongoing = ongoing_titles()
        print(f"{len(ongoing)} links on ongoing-conflicts list", file=sys.stderr)
    except Exception as e:
        print(f"ongoing list failed: {e}", file=sys.stderr)
        ongoing = set()

    out = []
    for it in items.values():
        # Prefer "start time" (P580); fall back to inception (P571), then point in time (P585).
        src = next((v for k, v in it["starts"].items() if v), set())
        starts = sorted(filter(None, (parse_date(s) for s in src)))
        ends = sorted(filter(None, (parse_date(s) for s in it["ends"])))
        if not starts:
            continue
        start = starts[0]
        end = ends[-1] if ends else None
        if end and end < start:
            end = start
        approx = False
        title = urllib.parse.unquote(it["wiki"].rsplit("/", 1)[-1]).replace("_", " ")
        if end is None and title not in ongoing:
            # Unknown end date: assume a short duration so it doesn't linger forever.
            end, approx = add_months(start, 12 if it["type"] in LONG_TYPES else 1), True
        raw = [[s_["p"][0], s_["p"][1], s_["n"], s_["d"]] for s_ in subs.get(it["id"], {}).values()]
        # Place from every battle. Thinning first pulls a world war's pin into the empty middle of the map.
        located = thin_sites(raw, limit=10**6)
        sites = thin_sites(located)
        if approx and it["type"] in LONG_TYPES:
            dated = sorted(s[3] for s in sites if s[3] and s[3] >= start and s[3][0] - start[0] <= 120)
            if dated and (end is None or dated[-1] > end):
                end = dated[-1]
        pos, precise = place(it, located)
        if not pos or (not precise and it["type"] in POINT_EVENTS):
            continue
        countries = [c for c in it["countries"] if c != "?"]
        rec = {
            "id": it["id"], "name": it["name"], "desc": it["desc"], "type": it["type"],
            "wiki": it["wiki"], "start": start, "end": end,
            "ongoing": end is None and title in ongoing,
            "lat": pos[0], "lng": pos[1], "countries": sorted(countries)[:8],
            "endApprox": approx,
            "precise": precise,
            "sites": sites,
        }
        if it.get("deaths"):
            rec["deaths"] = it["deaths"]
        if it.get("sides"):
            rec["sides"] = it["sides"]
        out.append(rec)
    before = len(out)
    out = dedup(out)
    out.sort(key=lambda w: (w["start"], w["name"]))
    print(f"Deduped {before - len(out)} overlaps", file=sys.stderr)
    problem = sane(out)
    if problem:
        print(f"Refusing to overwrite {OUT.name}: {problem}", file=sys.stderr)
        sys.exit(1)
    assign_countries(out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "source": "Wikidata / English Wikipedia", "wars": out}, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(OUT)
    print(f"Wrote {len(out)} conflicts to {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
