# warmap

An interactive **globe / 2D map of the world's wars and armed conflicts through time**, with a month-by-month timeline slider.

**Live:** https://egil10.github.io/warmap/

## Features
- 🌍 Globe ↔ 2D map toggle (MapLibre GL, OpenFreeMap tiles — no API keys)
- 🕰 Timeline slider by year-month, era presets (antiquity → today), play button, arrow-key stepping (Shift = 1 year)
- 📍 Locations *within* countries: each conflict is placed at its own coordinates, its location, or the centroid of its battles/sub-events; individual battle & event sites are drawn as dots and light up in the year they happen
- 🔴 Ongoing conflicts flagged from Wikipedia's *List of ongoing armed conflicts*
- 📖 Click a conflict for its Wikipedia summary & image
- 🔗 Shareable URLs: `#1943-06`

## Data
`scripts/fetch_wars.py` pulls wars, civil wars, insurgencies, rebellions, revolutions, invasions, campaigns, operations and offensives that have an English Wikipedia article from **Wikidata**, then attaches every geolocated sub-event (battles, sieges, etc. that are *part of* the war) to place it accurately inside countries. Output: `data/wars.json`.

Location precedence: the conflict's own coordinates → its location (P276) → centroid of its battle sites → centroid of involved countries (marked "country-level").

A GitHub Action refreshes the data weekly.

```bash
python3 scripts/fetch_wars.py     # rebuild data/wars.json (~5 min)
python3 -m http.server            # then open http://localhost:8000
```

## Caveats
Wikidata dates and classifications are imperfect. Conflicts with no end date that aren't on the ongoing list are shown for an assumed 1 year (wars) or 1 month (operations), marked with "?".
