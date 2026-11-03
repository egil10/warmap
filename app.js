/* War Map — wars and armed conflicts on a globe / flat map, month by month.
   Data: data/wars.json and data/countries.geojson, built by scripts/. */
(() => {
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const today = new Date();
  const NOW = today.getFullYear() * 12 + today.getMonth();
  const EVENT_TYPES = new Set(["battle", "siege", "skirmish", "coup d'état", "military action"]);
  const RED = "#d1342f", INK = "#2f2e2b";

  const toT = ([y, m]) => y * 12 + (m - 1);
  const yearLabel = (y) => (y <= 0 ? `${1 - y} BC` : `${y}`);
  const fmt = (t) => `${MONTHS[((t % 12) + 12) % 12]} ${yearLabel(Math.floor(t / 12))}`;
  const fmtYM = (ym) => (ym ? fmt(toT(ym)) : "");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const $ = (id) => document.getElementById(id);

  const state = { wars: [], t: NOW, from: 1900 * 12, to: NOW, query: "", onlyOngoing: false, playing: null, selected: null };
  let shaded = new Map(); // country a3 -> feature state currently applied

  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/positron",
    center: [25, 25],
    zoom: 1.7,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  if (innerWidth > 720) map.setPadding({ left: 300, top: 0, bottom: 60, right: 0 });

  // ---------- view ----------
  function setProjection(type) {
    map.setProjection({ type });
    $("btn-globe").classList.toggle("on", type === "globe");
    $("btn-flat").classList.toggle("on", type === "mercator");
  }
  $("btn-globe").onclick = () => setProjection("globe");
  $("btn-flat").onclick = () => setProjection("mercator");

  // ---------- filtering ----------
  const isActive = (w, t) => w._s <= t && (w.ongoing ? t <= NOW : w._e >= t);
  const matches = (w) => (!state.onlyOngoing || w.ongoing) && (!state.query || w._search.includes(state.query));
  const activeWars = () => state.wars.filter((w) => isActive(w, state.t) && matches(w));

  function buildData(active) {
    const conflicts = [], sites = [], countries = new Map();
    for (const w of active) {
      conflicts.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [w.lng, w.lat] },
        properties: { i: w._i, name: w.name, on: w.ongoing ? 1 : 0, ev: w._ev ? 1 : 0, weight: Math.min(w.sites.length, 40), sel: state.selected === w._i ? 1 : 0 },
      });
      for (const [lat, lng, name, d] of w.sites) {
        let recent = 0;
        if (d) {
          const dt = toT(d);
          if (dt > state.t || dt < state.t - 120) continue; // only the last decade of a long war
          recent = state.t - dt < 12 ? 1 : 0;
        }
        sites.push({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: { i: w._i, name, war: w.name, date: fmtYM(d), recent } });
      }
      const weight = w._ev ? 0.5 : 1;
      for (const a3 of w.iso || []) {
        const c = countries.get(a3) || { n: 0, on: 0 };
        c.n += weight;
        if (w.ongoing) c.on = 1;
        countries.set(a3, c);
      }
    }
    return { conflicts, sites, countries };
  }

  // ---------- render ----------
  let queued = false;
  function render() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const active = activeWars();
      const d = buildData(active);
      if (map.getSource("conflicts")) {
        map.getSource("conflicts").setData({ type: "FeatureCollection", features: d.conflicts });
        map.getSource("sites").setData({ type: "FeatureCollection", features: d.sites });
        shadeCountries(d.countries);
      }
      $("date").textContent = fmt(state.t);
      $("count").textContent = active.length.toLocaleString();
      renderList(active);
      history.replaceState(null, "", `#${Math.floor(state.t / 12)}-${String((state.t % 12) + 1).padStart(2, "0")}`);
    });
  }

  function shadeCountries(next) {
    if (!map.getSource("countries")) return;
    for (const a3 of shaded.keys()) if (!next.has(a3)) map.setFeatureState({ source: "countries", id: a3 }, { n: 0, on: 0 });
    for (const [a3, c] of next) map.setFeatureState({ source: "countries", id: a3 }, c);
    shaded = next;
  }

  function renderList(active) {
    const sorted = active.slice().sort((a, b) => (a._ev - b._ev) || (b.ongoing - a.ongoing) || (b.sites.length - a.sites.length) || (b._s - a._s));
    const MAX = 250;
    const rows = sorted.slice(0, MAX).map((w) => {
      const span = `${fmtYM(w.start)} – ${w.ongoing ? "present" : fmtYM(w.end) + (w.endApprox ? "?" : "")}`;
      const cls = w.ongoing ? "on" : w._ev ? "ev" : "";
      return `<li data-i="${w._i}" class="${cls}"><div class="n">${esc(w.name)}</div><div class="m">${span}</div></li>`;
    });
    if (sorted.length > MAX) rows.push(`<li class="more">${sorted.length - MAX} more</li>`);
    $("list").innerHTML = rows.join("") || `<li class="more">Nothing at this date.</li>`;
  }

  // ---------- detail ----------
  async function select(i, fly = true) {
    const w = state.wars[i];
    if (!w) return;
    state.selected = i;
    render();
    if (fly) {
      const pts = [[w.lng, w.lat], ...w.sites.map((s) => [s[1], s[0]])];
      const b = pts.reduce((bb, p) => bb.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
      map.fitBounds(b, { padding: { top: 60, bottom: 60, left: 60, right: innerWidth > 720 ? 360 : 60 }, maxZoom: pts.length > 1 ? 6 : 5, duration: 1000 });
    }
    $("detail").classList.remove("hidden");
    $("d-name").textContent = w.name;
    const when = `${fmtYM(w.start)} – ${w.ongoing ? "present" : fmtYM(w.end) + (w.endApprox ? " (end uncertain)" : "")}`;
    const deaths = w.deaths ? `${Number(w.deaths).toLocaleString()} deaths` : "";
    $("d-meta").textContent = [when, w.type, deaths, w.sites.length ? `${w.sites.length} mapped sites` : ""].filter(Boolean).join(" · ");
    $("d-countries").textContent = (w.sides && w.sides.length ? w.sides : w.countries).join(", ");
    $("d-link").href = w.wiki;
    $("d-extract").textContent = w.desc || "";
    $("d-img").removeAttribute("src");
    try {
      const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${w.wiki.split("/wiki/")[1]}`);
      if (r.ok && state.selected === i) {
        const j = await r.json();
        if (j.extract) $("d-extract").textContent = j.extract;
        if (j.thumbnail) $("d-img").src = j.thumbnail.source;
      }
    } catch (_) { /* keep the Wikidata description */ }
  }
  $("detail-close").onclick = () => { $("detail").classList.add("hidden"); state.selected = null; render(); };
  $("list").onclick = (e) => { const li = e.target.closest("li[data-i]"); if (li) select(+li.dataset.i); };

  // ---------- timeline ----------
  const slider = $("slider");
  function setRange(from, to) {
    state.from = from; state.to = to;
    slider.min = from; slider.max = to;
    if (state.t < from || state.t > to) state.t = to;
  }
  function setT(t) {
    state.t = Math.max(state.from, Math.min(state.to, Math.round(t)));
    slider.value = state.t;
    render();
  }
  function setEra(value) {
    const [a, b] = value.split(",");
    $("era").value = value;
    setRange(+a * 12, b === "now" ? NOW : +b * 12 + 11);
  }
  slider.oninput = () => setT(+slider.value);
  $("prev").onclick = () => setT(state.t - 1);
  $("next").onclick = () => setT(state.t + 1);
  $("era").onchange = (e) => { setEra(e.target.value); setT(state.t); };

  const PLAY = "M4 2.5v11l9-5.5z", PAUSE = "M4 2.5h3v11H4zM9 2.5h3v11H9z";
  function stop() { clearInterval(state.playing); state.playing = null; $("play-icon").setAttribute("d", PLAY); }
  $("play").onclick = () => {
    if (state.playing) return stop();
    if (state.t >= state.to) state.t = state.from;
    $("play-icon").setAttribute("d", PAUSE);
    const step = Math.max(1, Math.round((state.to - state.from) / 240)); // ~240 frames per range
    state.playing = setInterval(() => (state.t + step > state.to ? (setT(state.to), stop()) : setT(state.t + step)), 120);
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.key === "ArrowLeft") setT(state.t - (e.shiftKey ? 12 : 1));
    else if (e.key === "ArrowRight") setT(state.t + (e.shiftKey ? 12 : 1));
    else if (e.key === " ") { e.preventDefault(); $("play").click(); }
  });

  $("search").oninput = (e) => { state.query = e.target.value.trim().toLowerCase(); render(); };
  $("only-ongoing").onchange = (e) => { state.onlyOngoing = e.target.checked; render(); };

  // ---------- data ----------
  const ready = fetch("data/wars.json").then((r) => r.json()).then((data) => {
    state.wars = data.wars.map((w, i) => ({
      ...w, _i: i, _s: toT(w.start), _e: w.end ? toT(w.end) : Infinity, _ev: EVENT_TYPES.has(w.type) ? 1 : 0,
      _search: (w.name + " " + w.countries.join(" ") + " " + (w.sides || []).join(" ") + " " + w.desc).toLowerCase(),
    }));
    const m = location.hash.match(/^#(-?\d+)-(\d\d)/);
    const t = m ? toT([+m[1], +m[2]]) : NOW;
    const y = Math.floor(t / 12);
    const era = [...$("era").options].reverse().find((o) => { const [a, b] = o.value.split(","); return y >= +a && (b === "now" || y <= +b); });
    setEra(era ? era.value : "1900,now");
    setT(t);
  });

  // ---------- map layers ----------
  map.on("style.load", () => {
    setProjection("globe");
    map.setSky({ "sky-color": "#f4f3ef", "horizon-color": "#ffffff", "fog-color": "#f4f3ef", "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 5, 0.6, 7, 0] });

    // Insert our fills beneath the basemap's labels.
    const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

    map.addSource("countries", { type: "geojson", data: "data/countries.geojson", promoteId: "a3" });
    map.addLayer({ id: "country-fill", type: "fill", source: "countries", paint: {
      "fill-color": RED,
      "fill-opacity": ["interpolate", ["linear"], ["coalesce", ["feature-state", "n"], 0], 0, 0, 0.5, 0.035, 1, 0.06, 4, 0.11, 12, 0.18],
    } }, firstSymbol);

    map.addSource("sites", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addSource("conflicts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

    // Zones of fighting inside countries: a heatmap of battle sites and conflict locations.
    map.addLayer({ id: "zones", type: "heatmap", source: "sites", maxzoom: 9, paint: {
      "heatmap-weight": ["case", ["==", ["get", "recent"], 1], 1, 0.3],
      "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 6, 1.4],
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 8, 3, 18, 6, 34],
      "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 0, 0.5, 7, 0.35, 9, 0],
      "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"],
        0, "rgba(209,52,47,0)", 0.2, "rgba(209,52,47,0.18)", 0.5, "rgba(209,52,47,0.35)", 1, "rgba(160,30,28,0.55)"],
    } }, firstSymbol);

    map.addLayer({ id: "sites", type: "circle", source: "sites", minzoom: 2.5, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2.5, 1.5, 8, ["case", ["==", ["get", "recent"], 1], 5, 3]],
      "circle-color": ["case", ["==", ["get", "recent"], 1], RED, "#ffffff"],
      "circle-stroke-color": RED,
      "circle-stroke-width": 1,
      "circle-opacity": 0.9,
      "circle-stroke-opacity": ["case", ["==", ["get", "recent"], 1], 1, 0.6],
    } });

    map.addLayer({ id: "conflicts", type: "circle", source: "conflicts", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"],
        1, ["case", ["==", ["get", "ev"], 1], 1.5, ["+", 2.5, ["*", 0.07, ["get", "weight"]]]],
        6, ["case", ["==", ["get", "ev"], 1], 3.5, ["+", 5, ["*", 0.18, ["get", "weight"]]]]],
      "circle-color": ["case", ["==", ["get", "on"], 1], RED, INK],
      "circle-opacity": ["case", ["==", ["get", "ev"], 1], 0.55, 0.9],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["case", ["==", ["get", "sel"], 1], 3, 1],
    } });

    map.addLayer({ id: "conflict-labels", type: "symbol", source: "conflicts", minzoom: 3.5, filter: ["==", ["get", "ev"], 0], layout: {
      "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 0.9], "text-anchor": "top",
      "text-font": ["Noto Sans Regular"], "text-max-width": 10, "text-optional": true,
    }, paint: { "text-color": INK, "text-halo-color": "#ffffff", "text-halo-width": 1.5 } });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    for (const layer of ["conflicts", "sites"]) {
      map.on("mouseenter", layer, (e) => {
        map.getCanvas().style.cursor = "pointer";
        const p = e.features[0].properties;
        const html = layer === "sites" ? `${esc(p.name)}${p.date ? ` · ${esc(p.date)}` : ""}<br><span style="color:#858378">${esc(p.war)}</span>` : esc(p.name);
        popup.setLngLat(e.features[0].geometry.coordinates).setHTML(html).addTo(map);
      });
      map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; popup.remove(); });
      map.on("click", layer, (e) => select(+e.features[0].properties.i, layer === "conflicts"));
    }
    ready.then(render);
  });
})();
