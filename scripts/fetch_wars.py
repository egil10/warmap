#!/usr/bin/env python3
"""Fetch wars & armed conflicts from Wikidata (linked to English Wikipedia) into data/wars.json.

Usage: python3 scripts/fetch_wars.py
"""
import json, re, sys, time, urllib.parse, urllib.request
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
    "Q766875": "insurgency",
}

QUERY = """
SELECT ?item ?itemLabel ?article ?s580 ?s571 ?s585 ?end ?coord ?locCoord ?countryCoord ?countryLabel ?desc WHERE {
  ?item wdt:P31/wdt:P279* wd:%(cls)s .
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
  OPTIONAL { ?item wdt:P580 ?s580 }
  OPTIONAL { ?item wdt:P571 ?s571 }
  OPTIONAL { ?item wdt:P585 ?s585 }
  FILTER(BOUND(?s580) || BOUND(?s571) || BOUND(?s585))
  OPTIONAL { ?item wdt:P582 ?end }
  OPTIONAL { ?item wdt:P625 ?coord }
  OPTIONAL { ?item wdt:P276 ?loc . ?loc wdt:P625 ?locCoord }
  OPTIONAL { ?item wdt:P17 ?country . ?country wdt:P625 ?countryCoord }
  OPTIONAL { ?item schema:description ?desc FILTER(LANG(?desc) = "en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

def sparql(q, tries=3):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:
            print(f"  retry {i+1}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    return []

# Broad classes: direct instance-of only (subclass closure times out).
DIRECT_CLASSES = {"Q350604": "armed conflict", "Q645883": "military operation", "Q2001676": "military offensive", "Q831663": "military campaign", "Q1261499": "naval warfare"}

# Sub-events (battles, sieges, massacres, campaigns...) that are part of a war, with coordinates.
# This is what places a war *inside* a country rather than at the country centroid.
SUB_QUERY = """
SELECT ?war ?sub ?subLabel ?coord ?date WHERE {
  VALUES ?war { %(values)s }
  ?sub (wdt:P361|wdt:P361/wdt:P361) ?war ; wdt:P625 ?coord .
  OPTIONAL { ?sub wdt:P585|wdt:P580 ?date }
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
            "coord": None, "loc": None, "countries": {},
        })
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

LONG_TYPES = {"war", "civil war", "insurgency", "rebellion", "armed conflict", "war of independence", "revolution"}

def add_months(ym, n):
    t = ym[0] * 12 + (ym[1] - 1) + n
    return [t // 12, t % 12 + 1]

def main():
    items = {}
    for cls, name in CLASSES.items():
        print(f"Querying {name} ({cls})…", file=sys.stderr)
        rows = sparql(QUERY % {"cls": cls})
        print(f"  {len(rows)} rows", file=sys.stderr)
        ingest(items, name, rows)
        time.sleep(2)
    for cls, name in DIRECT_CLASSES.items():
        print(f"Querying {name} ({cls}, direct)…", file=sys.stderr)
        rows = sparql((QUERY % {"cls": cls}).replace("wdt:P31/wdt:P279*", "wdt:P31"))
        print(f"  {len(rows)} rows", file=sys.stderr)
        CLASSES_ROWS.append((name, rows))
        time.sleep(2)
    for name, rows in CLASSES_ROWS:
        ingest(items, name, rows)

    # Sub-event locations
    qids = list(items)
    subs = {}
    for i in range(0, len(qids), 250):
        chunk = qids[i:i + 250]
        print(f"Sub-events {i}/{len(qids)}…", file=sys.stderr)
        rows = sparql(SUB_QUERY % {"values": " ".join("wd:" + q for q in chunk)})
        for r in rows:
            w = r["war"]["value"].rsplit("/", 1)[-1]
            sid = r["sub"]["value"].rsplit("/", 1)[-1]
            pt = parse_point(r["coord"]["value"])
            if not pt:
                continue
            d = subs.setdefault(w, {}).setdefault(sid, {"n": r.get("subLabel", {}).get("value", sid), "p": pt, "d": None})
            if r.get("date") and not d["d"]:
                d["d"] = parse_date(r["date"]["value"])
        time.sleep(1)

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
        sl = list(subs.get(it["id"], {}).values())
        sites = [[s_["p"][0], s_["p"][1], s_["n"], s_["d"]] for s_ in sl][:60]
        pos = it["coord"] or it["loc"]
        if not pos and sites:
            pos = (round(sum(x[0] for x in sites) / len(sites), 3), round(sum(x[1] for x in sites) / len(sites), 3))
        countries = [c for c in it["countries"] if c != "?"]
        if not pos and it["countries"]:
            pts = [p for p in it["countries"].values() if p]
            if pts:
                pos = (round(sum(p[0] for p in pts) / len(pts), 3), round(sum(p[1] for p in pts) / len(pts), 3))
        if not pos:
            continue
        out.append({
            "id": it["id"], "name": it["name"], "desc": it["desc"], "type": it["type"],
            "wiki": it["wiki"], "start": start, "end": end,
            "ongoing": end is None and urllib.parse.unquote(it["wiki"].rsplit("/", 1)[-1]).replace("_", " ") in ongoing,
            "lat": pos[0], "lng": pos[1], "countries": sorted(countries)[:8],
            "endApprox": approx,
            "precise": bool(it["coord"] or it["loc"] or sites),
            "sites": sites,
        })
    out.sort(key=lambda w: (w["start"], w["name"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "source": "Wikidata / English Wikipedia", "wars": out}, ensure_ascii=False, separators=(",", ":")))
    print(f"Wrote {len(out)} conflicts to {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
