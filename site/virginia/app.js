// Virginia Data Center Tracker: map and search. Plain DOM, MapLibre served from this site (vendor/), data from
// data/*.json built by build.py. Searches never leave the browser; the URL fragment (#zip=..., #school=...,
// #pin=...) keeps a search shareable without sending it to any server.
import { Map as MLMap, NavigationControl, Popup } from "../vendor/maplibre-gl.mjs";
import { miles, within, circle, searchSchools, parseHash } from "../geo.js";

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, text) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (v != null) e.setAttribute(k, v);
  }
  if (text != null) e.textContent = text;
  return e;
};
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const STAGE_LABEL = { planned: "Planned", construction: "Under construction", operating: "Operating", shutdown: "Temporarily shut down", other: "Other" };
const STAGE_ORDER = { planned: 0, construction: 1, operating: 2, shutdown: 3, other: 4 };
const DEQ_RECORD = (id) => `https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294/query?where=PLA_REG_NUM%3D${id}&outFields=*&f=html`;
const fmtDate = (iso) => iso ? new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : null;
const fmtMi = (d) => (d < 10 ? d.toFixed(2) : d.toFixed(1)) + " mi";
// A few DEQ records have no street address or ZIP; say so instead of leaving a gap.
const addr = (f) => `${f.address || "Street address not listed by DEQ"}, ${f.city}${f.zip ? " " + f.zip : ""}`;

const [facilities, schools, zips, meta] = await Promise.all(
  ["facilities", "schools", "zips", "meta"].map((n) => fetch(`data/${n}.json`).then((r) => r.json())));
// County filings are optional: the map works without them (e.g. before the first build that writes the file).
const filings = await fetch("data/filings.json").then((r) => (r.ok ? r.json() : [])).catch(() => []);
const byId = new Map(facilities.map((f) => [String(f.id), f]));
const filingById = new Map(filings.map((f) => [f.id, f]));
const filingCounties = [...new Set(filings.map((f) => f.county))].sort().join(" and ");
const schoolById = new Map(schools.map((s) => [s.id, s]));

// ---- headline numbers -------------------------------------------------------------------------------------------
{
  const snapYear = (meta.permit_snapshot || "").slice(0, 4);
  const stats = [
    [String(meta.facilities), "Data centers on DEQ's records", "Across " + meta.localities.length + " counties and cities"],
    [String(meta.stages.planned + meta.stages.construction), "Planned or under construction", "DEQ status; not yet operating"],
    [String(meta.permits_by_year[snapYear] || 0), `Air permits issued in ${snapYear}`, `Through ${fmtDate(meta.permit_snapshot)}; ${meta.permits_by_year[String(snapYear - 1)] || 0} in all of ${snapYear - 1}`],
    [String(meta.stages.operating), "Operating", `${meta.localities[0][0]} has ${meta.localities[0][1]}`],
  ];
  if (filings.length) stats.push([String(filings.filter((f) => f.status === "in-review").length), "County filings in review",
    `${filingCounties} so far; ${filings.length} filings in all`]);
  $("#stats").replaceChildren(...stats.map(([v, l, n]) => { const d = el("div", { class: "stat" }); d.append(el("span", {}, l), el("b", {}, v), el("em", {}, n)); return d; }));
  $("#snap-date").textContent = fmtDate(meta.permit_snapshot);
  $("#built").textContent = new Date(meta.built_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
  $("#disclaimer").textContent = meta.deq_disclaimer ? "DEQ's data notice: " + meta.deq_disclaimer : "";
  // The donate link stays hidden until data/site_config.json has a support_url.
  if (meta.support_url) { const a = $("#support-link"); a.href = meta.support_url; a.textContent = meta.support_label || "Support this project"; a.hidden = false; }
}

// ---- state --------------------------------------------------------------------------------------------------------
const state = { mode: "zip", center: null, label: null, radius: 3, stages: new Set(["planned", "construction", "operating", "shutdown", "other"]), recent: false, filings: true };
const SIX_MONTHS_AGO = new Date(Date.now() - 183 * 864e5).toISOString().slice(0, 10);
function visible() {
  return facilities.filter((f) => state.stages.has(f.stage) && (!state.recent || (f.latest_permit && f.latest_permit >= SIX_MONTHS_AGO)));
}
const visibleFilings = () => (state.filings ? filings : []);

// ---- map ----------------------------------------------------------------------------------------------------------
// theme.js (loaded in <head>) says whether the page is light or dark: Auto follows the device, or the viewer's pick.
const isDark = () => (window.siteTheme ? window.siteTheme.effective() : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
const styleUrl = () => `https://tiles.openfreemap.org/styles/${isDark() ? "dark" : "positron"}`;
const map = new MLMap({ container: "map", style: styleUrl(), center: [-78.6, 37.9], zoom: 5.9, attributionControl: { compact: true }, cooperativeGestures: false });
map.addControl(new NavigationControl({ showCompass: false }), "top-right");
map.fitBounds([[-83.7, 36.5], [-75.2, 39.5]], { padding: 20, animate: false });

function geojson(list) {
  return { type: "FeatureCollection", features: list.map((f) => ({ type: "Feature", geometry: { type: "Point", coordinates: [f.lon, f.lat] }, properties: { id: String(f.id), stage: f.stage, order: 4 - STAGE_ORDER[f.stage] } })) };
}
function filingsGeojson(list) {
  return { type: "FeatureCollection", features: list.map((f) => ({ type: "Feature", geometry: { type: "Point", coordinates: [f.lon, f.lat] }, properties: { id: f.id, status: f.status, order: f.status === "in-review" ? 1 : 0 } })) };
}
// Diamond marker images, drawn for the current theme: solid (decided), hollow (in county review), gray (denied).
function diamond(fill, ring, hollow) {
  const px = 2, size = 18 * px, c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d"), h = size / 2;
  const dia = (r, color) => { g.beginPath(); g.moveTo(h, h - r); g.lineTo(h + r, h); g.lineTo(h, h + r); g.lineTo(h - r, h); g.closePath(); g.fillStyle = color; g.fill(); };
  dia(h, ring); dia(h - 2.5 * px, fill);
  if (hollow) dia(h - 6 * px, ring);
  return { image: g.getImageData(0, 0, size, size), options: { pixelRatio: px } };
}
function addLayers() {
  const c = { op: css("--st-operating"), pl: css("--st-planned"), sd: css("--st-shutdown"), ring: isDark() ? "#0c0c0c" : "#ffffff", navy: isDark() ? "#aebdf0" : "#232d4b" };
  map.addSource("area", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": c.navy, "fill-opacity": 0.07 } });
  map.addLayer({ id: "area-line", type: "line", source: "area", paint: { "line-color": c.navy, "line-width": 2, "line-dasharray": [2, 1.5] } });
  const fil = css("--filing");
  // Images can outlive a style swap (and replacing one in use blanks the layer), so each theme gets its own names.
  const t = isDark() ? "dark" : "light";
  for (const [name, img] of [["decided", diamond(fil, c.ring)], ["review", diamond(fil, c.ring, true)], ["denied", diamond(c.sd, c.ring)]])
    if (!map.hasImage(`dia-${name}-${t}`)) map.addImage(`dia-${name}-${t}`, img.image, img.options);
  // Under the data center dots (DEQ's records come first); the diamonds are drawn larger so their points show.
  map.addSource("filings", { type: "geojson", data: filingsGeojson(visibleFilings()) });
  map.addLayer({ id: "filings", type: "symbol", source: "filings", layout: {
    "icon-image": ["match", ["get", "status"], "in-review", `dia-review-${t}`, "denied", `dia-denied-${t}`, `dia-decided-${t}`],
    "icon-size": ["interpolate", ["linear"], ["zoom"], 6, 0.6, 10, 0.95, 14, 1.25],
    "icon-allow-overlap": true, "icon-ignore-placement": true, "symbol-sort-key": ["get", "order"] } });
  map.addSource("dc", { type: "geojson", data: geojson(visible()) });
  map.addLayer({ id: "dc", type: "circle", source: "dc", layout: { "circle-sort-key": ["get", "order"] }, paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 4, 10, 6.5, 14, 9],
    "circle-color": ["match", ["get", "stage"], "planned", c.pl, "construction", c.pl, "operating", c.op, c.sd],
    "circle-stroke-color": c.ring, "circle-stroke-width": 1.5 } });
  map.addLayer({ id: "dc-construction", type: "circle", source: "dc", filter: ["==", ["get", "stage"], "construction"], paint: {
    "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 1.5, 10, 2.5, 14, 3.5], "circle-color": c.ring } });
  map.addSource("center", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "center", type: "circle", source: "center", paint: { "circle-radius": 7, "circle-color": c.navy, "circle-stroke-color": c.ring, "circle-stroke-width": 3 } });
  drawSearch(false);
}
map.on("style.load", addLayers);
// Swap the basemap (and re-add the layers in the new theme's colors) when the theme changes.
window.addEventListener("themechange", () => map.setStyle(styleUrl()));

for (const layer of ["dc", "filings"]) {
  map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = state.mode === "pin" ? "crosshair" : ""; });
}
map.on("click", (e) => {
  const hit = map.queryRenderedFeatures(e.point, { layers: ["dc", "filings"] });  // topmost first
  if (hit.length) {
    const p = hit[0].properties;
    if (hit[0].layer.id === "filings") openFilingPopup(filingById.get(p.id)); else openPopup(byId.get(p.id));
    return;
  }
  if (state.mode === "pin") setCenter(e.lngLat.lat, e.lngLat.lng, `your pin (${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)})`, { pin: `${e.lngLat.lat.toFixed(5)},${e.lngLat.lng.toFixed(5)}` });
});

let popup = null;
function openPopup(f, fly) {
  if (!f) return;
  if (fly) map.flyTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 13), offset: map.getContainer().clientWidth < 560 ? [0, 90] : [0, 0] });
  const box = el("div", { class: "pop" });
  box.append(el("h3", {}, f.name));
  const st = el("p"); st.append(el("span", { class: "tag " + f.stage }, STAGE_LABEL[f.stage]), document.createTextNode(" DEQ status"));
  box.append(st);
  box.append(el("p", {}, addr(f)));
  let loc = f.locality || "";
  if (f.listed_locality && f.listed_locality !== f.locality) loc += ` (DEQ's permit list says ${f.listed_locality})`;
  box.append(el("p", {}, loc));
  if (state.center) box.append(el("p", {}, `${fmtMi(miles(state.center.lat, state.center.lon, f.lat, f.lon))} from ${state.label}`));
  box.append(el("p", {}, f.permits.length
    ? `Air permit${f.permits.length > 1 ? "s" : ""}: ` + f.permits.map((p) => `${p.no} (${fmtDate(p.issued) || "date not given"})`).join(", ")
    : "No issued air permit on DEQ's list yet"));
  const src = el("p", { class: "src" });
  src.append(document.createTextNode("Source: "), el("a", { href: DEQ_RECORD(f.id), target: "_blank", rel: "noopener" }, `DEQ record ${f.id}`),
    document.createTextNode(" · "), el("a", { href: meta.sources.deq_permit_page, target: "_blank", rel: "noopener" }, "DEQ permit list"));
  box.append(src);
  showPopup(f, box, fly);
}
function showPopup(f, box, fly) {
  popup?.remove();
  // On narrow screens, size the popup to the map and center the point so the popup can't run off the edge.
  const w = map.getContainer().clientWidth;
  if (w < 560 && !fly) map.easeTo({ center: [f.lon, f.lat], offset: [0, 90], duration: 300 });
  popup = new Popup({ offset: 10, maxWidth: Math.min(310, w - 40) + "px", anchor: w < 560 ? "bottom" : undefined })
    .setLngLat([f.lon, f.lat]).setDOMContent(box).addTo(map);
}
// A county filing: what was filed, its status in the county's words, and a link to the county record.
function openFilingPopup(f, fly) {
  if (!f) return;
  if (fly) map.flyTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 13), offset: map.getContainer().clientWidth < 560 ? [0, 90] : [0, 0] });
  const box = el("div", { class: "pop" });
  box.append(el("h3", {}, f.name));
  const st = el("p"); st.append(el("span", { class: "tag filing" }, f.label), document.createTextNode(" County status"));
  box.append(st);
  box.append(el("p", {}, `${f.type} ${f.id}, filed ${fmtDate(f.date)} · ${f.county}`));
  if (state.center) box.append(el("p", {}, `${fmtMi(miles(state.center.lat, state.center.lon, f.lat, f.lon))} from ${state.label}`));
  if (f.description) box.append(el("p", {}, f.description.length > 280 ? f.description.slice(0, 280).replace(/\s+\S*$/, "") + "…" : f.description));
  if (f.related?.length) box.append(el("p", {}, "Filed with it: " + f.related.join(", ")));
  box.append(el("p", { class: "src" }, f.kind === "land-use"
    ? "A land-use application: the county board decides, usually after a public hearing."
    : "A site plan: construction plans reviewed by county staff."));
  const src = el("p", { class: "src" });
  src.append(document.createTextNode("Source: "), el("a", { href: f.source, target: "_blank", rel: "noopener" }, `${f.county} record ${f.id}`));
  box.append(src);
  showPopup(f, box, fly);
}

// ---- search -------------------------------------------------------------------------------------------------------
const MODES = {
  zip: { label: "ZIP code", placeholder: "e.g. 20171", hint: "Any Virginia ZIP code. Distances are measured from the ZIP code's center.", input: true, inputmode: "numeric" },
  school: { label: "School name", placeholder: "e.g. Rachel Carson Middle", hint: "Virginia public schools. Type part of the name, then pick from the list.", input: true, inputmode: "text" },
  pin: { label: "", placeholder: "", hint: "Tap or click anywhere on the map to drop a pin. Tapping a dot shows its details instead.", input: false },
};
function setMode(mode, keep) {
  state.mode = mode;
  document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
  const m = MODES[mode];
  $("#q-wrap").style.visibility = m.input ? "visible" : "hidden";
  $("#q-label").textContent = m.label;
  $("#q").placeholder = m.placeholder;
  $("#q").setAttribute("inputmode", m.inputmode || "text");
  $("#q-hint").textContent = m.hint;
  $("#suggest").replaceChildren();
  map.getCanvas().style.cursor = mode === "pin" ? "crosshair" : "";
  if (!keep) $("#q").value = "";
}
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

$("#q").addEventListener("input", () => {
  const v = $("#q").value.trim();
  if (state.mode === "zip") {
    if (/^\d{5}$/.test(v)) selectZip(v);
    else if (v.length >= 5) $("#summary").textContent = "Enter a 5-digit ZIP code.";
  } else if (state.mode === "school") {
    const hits = searchSchools(schools, v, 8);
    $("#suggest").replaceChildren(...hits.map((s) => {
      const li = el("li"); const b = el("button", { type: "button" });
      b.append(document.createTextNode(s.name + " "), el("small", {}, `${s.city}${s.aka?.length ? " · also " + s.aka.join(", ") : ""}`));
      b.addEventListener("click", () => selectSchool(s)); li.append(b); return li;
    }));
    if (v.length >= 3 && !hits.length) $("#summary").textContent = "No Virginia public school matches that name.";
  }
});
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#suggest button")?.click(); } });
$("#radius").addEventListener("change", () => { state.radius = Number($("#radius").value); drawSearch(true); syncHash(); });
$("#stage-filter").addEventListener("change", () => {
  state.stages = new Set([...document.querySelectorAll("#stage-filter input:checked")].map((i) => i.value).concat(["other"]));
  refresh();
});
$("#recent").addEventListener("change", () => { state.recent = $("#recent").checked; refresh(); });
$("#show-filings").addEventListener("change", () => { state.filings = $("#show-filings").checked; refresh(); });
if (!filings.length) $("#show-filings").closest("div").hidden = true;

function selectZip(z) {
  const ll = zips[z];
  if (!ll) { $("#summary").textContent = `${z} isn't a Virginia ZIP code in the Census list.`; $("#results").replaceChildren(); return; }
  setCenter(ll[0], ll[1], `ZIP ${z}`, { zip: z });
}
function selectSchool(s) {
  $("#q").value = s.name; $("#suggest").replaceChildren();
  setCenter(s.lat, s.lon, `${s.name} (${s.city})`, { school: s.id });
}
let hashParams = {};
function setCenter(lat, lon, label, params) {
  state.center = { lat, lon }; state.label = label; hashParams = params;
  drawSearch(true); syncHash();
}
function syncHash() {
  if (!state.center) return;
  const p = new URLSearchParams({ ...hashParams, r: String(state.radius) });
  history.replaceState(null, "", "#" + p.toString());
}

function refresh() {
  if (map.getSource("dc")) map.getSource("dc").setData(geojson(visible()));
  if (map.getSource("filings")) map.getSource("filings").setData(filingsGeojson(visibleFilings()));
  drawSearch(false);
}

function drawSearch(fit) {
  if (!map.getSource("area")) return;
  if (!state.center) {
    map.getSource("area").setData({ type: "FeatureCollection", features: [] });
    map.getSource("center").setData({ type: "FeatureCollection", features: [] });
    const n = visible().length, nf = visibleFilings().length;
    $("#summary").textContent = `Showing all ${n} data centers${nf ? ` and ${nf} county filings` : ""} on the map. Pick a ZIP code, school or pin to list what's nearby.`;
    $("#results").replaceChildren();
    return;
  }
  const { lat, lon } = state.center;
  const area = circle(lat, lon, state.radius);
  map.getSource("area").setData(area);
  map.getSource("center").setData({ type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] }, properties: {} });
  if (fit) {
    const lons = area.geometry.coordinates[0].map((c) => c[0]), lats = area.geometry.coordinates[0].map((c) => c[1]);
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 30, duration: 600 });
  }
  const near = within(visible(), lat, lon, state.radius).sort((a, b) => a.distance - b.distance);
  const counts = {};
  for (const f of near) counts[f.stage] = (counts[f.stage] || 0) + 1;
  const parts = Object.keys(STAGE_ORDER).filter((k) => counts[k]).map((k) => `${counts[k]} ${STAGE_LABEL[k].toLowerCase()}`);
  const nearFilings = within(visibleFilings(), lat, lon, state.radius);
  const inReview = nearFilings.filter((f) => f.status === "in-review").length;
  const filingText = nearFilings.length ? ` Plus ${nearFilings.length} county filing${nearFilings.length > 1 ? "s" : ""} (${inReview} in county review).` : "";
  const s = $("#summary");
  s.replaceChildren(el("b", {}, String(near.length)), document.createTextNode(
    ` data center${near.length === 1 ? "" : "s"} within ${state.radius} mile${state.radius > 1 ? "s" : ""} of ${state.label}` + (parts.length ? `: ${parts.join(", ")}.` : ".") + filingText));
  // Data centers and county filings in one list, nearest first; the marker shape and the text say which is which.
  const rows = [...near.map((f) => ({ f, filing: false })), ...nearFilings.map((f) => ({ f, filing: true }))]
    .sort((a, b) => a.f.distance - b.f.distance);
  $("#results").replaceChildren(...rows.map(({ f, filing }) => {
    const li = el("li"); const b = el("button", { type: "button" });
    b.append(el("i", { class: (filing ? "dia " + f.status : "dot " + f.stage), "aria-hidden": "true" }), el("span", { class: "nm" }, f.name), el("span", { class: "dist" }, fmtMi(f.distance)));
    if (filing) {
      b.append(el("span", { class: "meta" }, `County filing · ${f.label} · ${f.type} ${f.id}, filed ${fmtDate(f.date)}`));
      b.addEventListener("click", () => openFilingPopup(f, true));
    } else {
      const date = f.latest_permit ? ` · permit ${fmtDate(f.latest_permit)}` : "";
      b.append(el("span", { class: "meta" }, `${STAGE_LABEL[f.stage]} · ${addr(f)}${date}`));
      b.addEventListener("click", () => openPopup(f, true));
    }
    li.append(b); return li;
  }));
}

// ---- start from a shared link -----------------------------------------------------------------------------------
{
  const h = parseHash(location.hash);
  if (h.radius) { state.radius = h.radius; $("#radius").value = String(h.radius); }
  const go = () => {
    if (h.mode === "zip") { setMode("zip"); $("#q").value = h.zip; selectZip(h.zip); }
    else if (h.mode === "school" && schoolById.get(h.school)) { setMode("school"); selectSchool(schoolById.get(h.school)); }
    else if (h.mode === "pin") { setMode("pin"); setCenter(h.lat, h.lon, `your pin (${h.lat.toFixed(4)}, ${h.lon.toFixed(4)})`, { pin: `${h.lat},${h.lon}` }); }
    else setMode("zip");
  };
  if (map.isStyleLoaded()) go(); else map.once("style.load", () => setTimeout(go, 0));
}
