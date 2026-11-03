#!/usr/bin/env python3
"""Download Natural Earth 1:50m countries and write a slim data/countries.geojson (id = ADM0_A3)."""
import json, urllib.request
from pathlib import Path

SRC = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
OUT = Path(__file__).resolve().parent.parent / "data" / "countries.geojson"

def ring(r):
    out = []
    for x, y in r:
        p = [round(x, 2), round(y, 2)]
        if not out or out[-1] != p:
            out.append(p)
    return out if len(out) >= 4 else None

def main():
    with urllib.request.urlopen(SRC, timeout=120) as r:
        src = json.load(r)
    feats = []
    for f in src["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        polys = [[rr for rr in map(ring, p) if rr] for p in polys]
        polys = [p for p in polys if p]
        a3 = f["properties"]["ADM0_A3"]
        feats.append({"type": "Feature", "id": a3, "properties": {"a3": a3, "name": f["properties"]["NAME"]},
                      "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print(f"Wrote {len(feats)} countries, {OUT.stat().st_size // 1024} KB")

if __name__ == "__main__":
    main()
