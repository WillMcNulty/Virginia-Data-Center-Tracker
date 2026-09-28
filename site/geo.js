// Search logic shared by the page (app.js) and the tests (tests/geo.test.mjs). No network, no dependencies:
// every search runs in the browser, so a ZIP code, school or pin never leaves the viewer's device.

const EARTH_MILES = 3958.8;
const rad = (d) => (d * Math.PI) / 180;

// Great-circle (haversine) distance in statute miles; the same formula as pipeline/geo.py.
export function miles(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dp = p2 - p1, dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_MILES * Math.asin(Math.sqrt(a));
}

// Facilities within `radius` miles of a point, nearest first, each with its distance.
export function within(facilities, lat, lon, radius) {
  return facilities
    .map((f) => ({ ...f, distance: miles(lat, lon, f.lat, f.lon) }))
    .filter((f) => f.distance <= radius)
    .sort((a, b) => a.distance - b.distance);
}

// A circle of `radius` miles as a GeoJSON polygon (for drawing the search area).
export function circle(lat, lon, radius, steps = 96) {
  const coords = [];
  const d = radius / EARTH_MILES;
  const la = rad(lat), lo = rad(lon);
  for (let i = 0; i <= steps; i++) {
    const b = (2 * Math.PI * i) / steps;
    const lat2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(b));
    const lon2 = lo + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(lat2));
    coords.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [coords] }, properties: {} };
}

const STOP = new Set(["school", "elementary", "middle", "high", "the", "of", "and", "es", "ms", "hs"]);
const norm = (s) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

// School search tolerant of how people say names: official names are often short ("Carson Middle") while people
// say "Rachel Carson Middle School". Scores each school by how many of the query's distinctive words it contains
// (in its name, known aliases or city), so a partial match still finds it. Returns the best `limit` matches.
export function searchSchools(schools, query, limit = 8) {
  const q = norm(query);
  if (q.length < 2) return [];
  const words = q.split(" ").filter((w) => w.length >= 2);
  const key = words.filter((w) => !STOP.has(w));
  const want = key.length ? key : words;
  const scored = [];
  for (const s of schools) {
    const hay = norm([s.name, ...(s.aka || [])].join(" "));
    const hayWords = hay.split(" ");
    const city = norm(s.city || "");
    let score = 0;
    for (const w of want) {
      if (hayWords.some((h) => h === w)) score += 2;
      else if (hayWords.some((h) => h.startsWith(w))) score += 1.5;
      else if (city.split(" ").some((h) => h.startsWith(w))) score += 0.5;
    }
    if (score === 0) continue;
    if (hay.startsWith(q) || (s.aka || []).some((a) => norm(a).startsWith(q))) score += 3;
    // prefer schools whose type word matches ("middle" in the query and the name)
    for (const w of words) if (STOP.has(w) && w.length > 3 && hayWords.includes(w)) score += 0.25;
    scored.push({ s, score });
  }
  scored.sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name));
  return scored.slice(0, limit).map((x) => x.s);
}

// Parse the shareable state kept in the URL fragment (never sent to a server): #zip=20171&r=3, #school=ID&r=1,
// #pin=38.93,-77.42&r=1.
export function parseHash(hash) {
  const p = new URLSearchParams((hash || "").replace(/^#/, ""));
  const r = Number(p.get("r"));
  const radius = [1, 3, 5, 10, 30].includes(r) ? r : null;
  if (p.get("zip") && /^\d{5}$/.test(p.get("zip"))) return { mode: "zip", zip: p.get("zip"), radius };
  if (p.get("school")) return { mode: "school", school: p.get("school"), radius };
  if (p.get("pin")) {
    const [lat, lon] = p.get("pin").split(",").map(Number);
    if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) return { mode: "pin", lat, lon, radius };
  }
  return { mode: null, radius };
}
