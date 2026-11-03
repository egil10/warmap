# warmap

An interactive **globe / 2D map of the world's wars and armed conflicts through time**, with a month-by-month timeline slider.

**Live:** https://egil10.github.io/warmap/

## Features
- Globe and flat map (MapLibre GL + OpenFreeMap, no API keys)
- Month-by-month timeline from 1000 BC to today; play, arrow keys (Shift = year)
- Conflicts placed *inside* countries: countries involved are shaded, and fighting zones are drawn as a heatmap of battle and event sites, which light up in the year they happen
- Ongoing conflicts from Wikipedia's *List of ongoing armed conflicts*
- Click for the Wikipedia summary; shareable URLs like `#1944-06`

## Data
`scripts/fetch_wars.py` pulls wars, civil wars, insurgencies, rebellions, revolutions, invasions, coups, interventions, colonial and proxy wars, campaigns, operations, offensives, occupations, and standalone battles and sieges that have an English Wikipedia article from **Wikidata**, then attaches every geolocated sub-event (battles, sieges, etc. that are *part of* the war) to place it accurately inside countries. Output: `data/wars.json`.

Location precedence: the conflict's own coordinates, unless those are missing or far from its battles (Wikidata pins World War II at 0°N) — then the middle of its battle sites → its location (P276) → one involved country. Distant countries are not averaged, because that midpoint often falls in the ocean. Battle sites are spread across the map rather than truncated to whichever rows Wikidata returns first. Year chronicles ("1955 in the Vietnam War") and non-violent revolutions are left out. A death toll and belligerents are included when Wikidata has them.

A GitHub Action refreshes the data weekly.

```bash
python3 scripts/fetch_wars.py     # rebuild data/wars.json (half an hour; Wikidata is slow)
python3 -m http.server            # then open http://localhost:8000
```

## Caveats
Wikidata dates and classifications are imperfect. Conflicts with no end date that aren't on the ongoing list are shown for an assumed 1 year (wars) or 1 month (operations), marked with "?".
