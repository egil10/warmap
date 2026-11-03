/* War Map — MapLibre GL globe/2D map of wars through time. Data: data/wars.json (built by scripts/fetch_wars.py). */
(() => {
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const today = new Date();
  const NOW = today.getFullYear() * 12 + today.getMonth();
  const toT = ([y, m]) => y * 12 + (m - 1);
  const yearLabel = (y) => (y <= 0 ? `${1 - y} BC` : `${y}`);
  const fmt = (t) => `${MONTHS[((t % 12) + 12) % 12]} ${yearLabel(Math.floor(t / 12))}`;
  const fmtYM = (ym) => (ym ? fmt(toT(ym)) : "");
  const $ = (id) => document.getElementById(id);

  const state = { wars: [], t: NOW, from: 1900 * 12, to: NOW, query: "", onlyOngoing: false, playing: null, selected: null };

  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/dark",
    center: [30, 25],
    zoom: 1.6,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  // Keep the globe centred in the space not covered by the list panel / timeline.
  if (innerWidth > 720) map.setPadding({ left: 340, top: 50, bottom: 140, right: 0 });

  // ---------- view toggle ----------
  function setProjection(type) {
    map.setProjection({ type });
    $("btn-globe").classList.toggle("active", type === "globe");
    $("btn-flat").classList.toggle("active", type === "mercator");
  }
  $("btn-globe").onclick = () => setProjection("globe");
  $("btn-flat").onclick = () => setProjection("mercator");

  // ---------- data → GeoJSON ----------
  function isActive(w, t) {
    if (w._s > t) return false;
    if (w.ongoing) return t <= NOW;
    return w._e >= t;
  }

  function matches(w) {
    if (state.onlyOngoing && !w.ongoing) return false;
    if (!state.query) return true;
    const q = state.query;
    return w._search.includes(q);
  }

  function activeWars() {
    return state.wars.filter((w) => isActive(w, state.t) && matches(w));
  }

  function buildGeoJSON(active) {
    const conflicts = [], sites = [];
    for (const w of active) {
      conflicts.push({
        type: "Feature",
        id: w._i,
        geometry: { type: "Point", coordinates: [w.lng, w.lat] },
        properties: { i: w._i, name: w.name, ongoing: w.ongoing ? 1 : 0, precise: w.precise ? 1 : 0, weight: Math.min(w.sites.length, 40), sel: state.selected === w._i ? 1 : 0 },
      });
      for (const [lat, lng, name, d] of w.sites) {
        let recent = 0;
        if (d) {
          const dt = toT(d);
          if (dt > state.t) continue; // hasn't happened yet
          recent = state.t - dt < 12 ? 1 : 0;
        }
        sites.push({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: { i: w._i, name, war: w.name, date: fmtYM(d), recent } });
      }
    }
    return {
      conflicts: { type: "FeatureCollection", features: conflicts },
      sites: { type: "FeatureCollection", features: sites },
    };
  }

  // ---------- render ----------
  let rafPending = false;
  function render() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => {
      rafPending = false;
      const active = activeWars();
      const gj = buildGeoJSON(active);
      if (map.getSource("conflicts")) {
        map.getSource("conflicts").setData(gj.conflicts);
        map.getSource("sites").setData(gj.sites);
      }
      $("date").textContent = fmt(state.t);
      $("count").textContent = active.length.toLocaleString();
      $("count-date").textContent = fmt(state.t);
      renderList(active);
      writeHash();
    });
  }

  function renderList(active) {
    const sorted = active.slice().sort((a, b) => (b.ongoing - a.ongoing) || (b.sites.length - a.sites.length) || (b._s - a._s));
    const MAX = 300;
    const html = sorted.slice(0, MAX).map((w) => {
      const span = `${fmtYM(w.start)} – ${w.ongoing ? "present" : fmtYM(w.end) + (w.endApprox ? "?" : "")}`;
      const where = w.countries.slice(0, 3).join(", ");
      return `<li data-i="${w._i}" class="${w.ongoing ? "ongoing" : "past"}"><div class="n">${esc(w.name)}</div><div class="m">${span}${where ? " · " + esc(where) : ""}</div></li>`;
    });
    if (sorted.length > MAX) html.push(`<li class="more">+ ${sorted.length - MAX} more — refine the filter</li>`);
    $("list").innerHTML = html.join("") || `<li class="more">No conflicts match at this date.</li>`;
  }

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------- detail panel ----------
  async function select(i, fly = true) {
    const w = state.wars[i];
    if (!w) return;
    state.selected = i;
    render();
    if (fly) {
      const pts = [[w.lng, w.lat], ...w.sites.map((s) => [s[1], s[0]])];
      if (pts.length > 1) {
        const b = pts.reduce((bb, p) => bb.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
        map.fitBounds(b, { padding: { top: 40, bottom: 40, left: 40, right: innerWidth > 720 ? 380 : 40 }, maxZoom: 6, duration: 1200 });
      } else {
        map.flyTo({ center: [w.lng, w.lat], zoom: Math.max(map.getZoom(), 4), duration: 1200 });
      }
    }
    $("detail").classList.remove("hidden");
    $("d-name").textContent = w.name;
    const badges = (w.ongoing ? `<span class="badge ongoing">Ongoing</span>` : "") + (w.endApprox ? `<span class="badge approx">end date unknown</span>` : "") + (!w.precise ? `<span class="badge approx">location: country-level</span>` : "");
    $("d-meta").innerHTML = `${badges}${fmtYM(w.start)} – ${w.ongoing ? "present" : fmtYM(w.end)} · ${esc(w.type)}${w.sites.length ? ` · ${w.sites.length} mapped sites` : ""}`;
    $("d-countries").innerHTML = w.countries.map((c) => `<span>${esc(c)}</span>`).join("");
    $("d-link").href = w.wiki;
    $("d-extract").textContent = w.desc || "";
    $("d-img").removeAttribute("src");
    try {
      const title = w.wiki.split("/wiki/")[1];
      const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${title}`);
      if (r.ok && state.selected === i) {
        const j = await r.json();
        if (j.extract) $("d-extract").textContent = j.extract;
        if (j.thumbnail) $("d-img").src = j.thumbnail.source;
      }
    } catch (_) { /* offline: keep Wikidata description */ }
  }
  $("detail-close").onclick = () => { $("detail").classList.add("hidden"); state.selected = null; render(); };
  $("list").onclick = (e) => { const li = e.target.closest("li[data-i]"); if (li) select(+li.dataset.i); };

  // ---------- timeline ----------
  const slider = $("slider");
  function setRange(from, to) {
    state.from = from; state.to = to;
    slider.min = from; slider.max = to;
    if (state.t < from || state.t > to) state.t = to;
    slider.value = state.t;
  }
  function setT(t) {
    state.t = Math.max(state.from, Math.min(state.to, Math.round(t)));
    slider.value = state.t;
    render();
  }
  slider.oninput = () => setT(+slider.value);
  $("prev").onclick = () => setT(state.t - 1);
  $("next").onclick = () => setT(state.t + 1);
  $("eras").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    document.querySelectorAll("#eras button").forEach((x) => x.classList.toggle("active", x === b));
    const to = b.dataset.to === "now" ? NOW : +b.dataset.to * 12 + 11;
    setRange(+b.dataset.from * 12, to);
    setT(state.t);
  };
  $("play").onclick = () => {
    if (state.playing) { clearInterval(state.playing); state.playing = null; $("play").textContent = "▶"; return; }
    if (state.t >= state.to) state.t = state.from;
    $("play").textContent = "❚❚";
    state.playing = setInterval(() => {
      const step = +$("speed").value;
      if (state.t + step > state.to) { setT(state.to); $("play").click(); return; }
      setT(state.t + step);
    }, 450);
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.key === "ArrowLeft") setT(state.t - (e.shiftKey ? 12 : 1));
    else if (e.key === "ArrowRight") setT(state.t + (e.shiftKey ? 12 : 1));
    else if (e.key === " ") { e.preventDefault(); $("play").click(); }
  });

  $("search").oninput = (e) => { state.query = e.target.value.trim().toLowerCase(); render(); };
  $("only-ongoing").onchange = (e) => { state.onlyOngoing = e.target.checked; render(); };
  $("panel-toggle").onclick = () => $("panel").classList.toggle("collapsed");

  // ---------- URL hash (#2022-03) ----------
  function writeHash() {
    const y = Math.floor(state.t / 12), m = (state.t % 12) + 1;
    history.replaceState(null, "", `#${y}-${String(m).padStart(2, "0")}`);
  }
  function readHash() {
    const m = location.hash.match(/^#(-?\d+)-(\d\d)/);
    return m ? toT([+m[1], +m[2]]) : null;
  }

  // ---------- map layers ----------
  map.on("style.load", () => {
    setProjection("globe");
    // Recolour the base map: land a touch lighter than water so coastlines read on the globe.
    const paint = (id, prop, val) => map.getLayer(id) && map.setPaintProperty(id, prop, val);
    paint("background", "background-color", "#1d212b");
    paint("water", "fill-color", "#0b1018");
    paint("landcover_wood", "fill-color", "#20242e");
    paint("landuse_park", "fill-color", "#20242e");
    paint("landcover_ice_shelf", "fill-color", "#262a33");
    paint("landcover_glacier", "fill-color", "#262a33");
    map.setSky({
      "sky-color": "#0b0d12", "horizon-color": "#1b2233", "fog-color": "#0b0d12",
      "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 1, 7, 0],
    });
  });

  const dataReady = fetch("data/wars.json").then((r) => r.json()).then((data) => {
    state.wars = data.wars.map((w, i) => ({
      ...w, _i: i, _s: toT(w.start), _e: w.end ? toT(w.end) : Infinity,
      _search: (w.name + " " + w.countries.join(" ") + " " + w.desc).toLowerCase(),
    }));
    setRange(1900 * 12, NOW);
    const h = readHash();
    if (h !== null) {
      const y = Math.floor(h / 12);
      const era = [...document.querySelectorAll("#eras button")].find((b) => y >= +b.dataset.from && (b.dataset.to === "now" || y <= +b.dataset.to));
      if (era) era.click();
      setT(h);
    } else {
      setT(NOW);
    }
  });

  map.on("style.load", () => {
    map.addSource("conflicts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addSource("sites", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

    const r = (base) => ["interpolate", ["linear"], ["zoom"], 1, ["+", base, ["*", 0.12, ["get", "weight"]]], 6, ["+", base * 2.2, ["*", 0.3, ["get", "weight"]]]];
    const color = ["case", ["==", ["get", "ongoing"], 1], "#ff3b3b", "#ff9a3c"];

    map.addLayer({ id: "sites", type: "circle", source: "sites", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, ["case", ["==", ["get", "recent"], 1], 2.6, 1.6], 7, ["case", ["==", ["get", "recent"], 1], 6, 3.5]],
      "circle-color": ["case", ["==", ["get", "recent"], 1], "#ffffff", "#ffd36b"],
      "circle-opacity": ["case", ["==", ["get", "recent"], 1], 0.95, 0.4],
      "circle-stroke-color": "#ffd36b",
      "circle-stroke-width": ["case", ["==", ["get", "recent"], 1], 1.5, 0],
    } });
    map.addLayer({ id: "conflict-glow", type: "circle", source: "conflicts", paint: {
      "circle-radius": r(9), "circle-color": color, "circle-blur": 1, "circle-opacity": 0.45,
    } });
    map.addLayer({ id: "conflicts", type: "circle", source: "conflicts", paint: {
      "circle-radius": r(3.5), "circle-color": color, "circle-opacity": 0.9,
      "circle-stroke-color": ["case", ["==", ["get", "sel"], 1], "#ffffff", ["==", ["get", "precise"], 1], "rgba(0,0,0,0.5)", "rgba(255,255,255,0.6)"],
      "circle-stroke-width": ["case", ["==", ["get", "sel"], 1], 2.5, 1],
    } });
    map.addLayer({ id: "conflict-labels", type: "symbol", source: "conflicts", minzoom: 3.2, layout: {
      "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.1], "text-anchor": "top",
      "text-font": ["Noto Sans Regular"], "text-max-width": 10, "text-optional": true,
    }, paint: { "text-color": "#e8e9ec", "text-halo-color": "#0b0d12", "text-halo-width": 1.4 } });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    for (const layer of ["conflicts", "sites"]) {
      map.on("mouseenter", layer, (e) => {
        map.getCanvas().style.cursor = "pointer";
        const p = e.features[0].properties;
        const html = layer === "sites" ? `<b>${esc(p.name)}</b>${p.date ? " · " + esc(p.date) : ""}<br><span style="opacity:.7">${esc(p.war)}</span>` : `<b>${esc(p.name)}</b>`;
        popup.setLngLat(e.features[0].geometry.coordinates).setHTML(html).addTo(map);
      });
      map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; popup.remove(); });
      map.on("click", layer, (e) => select(+e.features[0].properties.i, layer === "conflicts"));
    }
    dataReady.then(render);
  });
})();
