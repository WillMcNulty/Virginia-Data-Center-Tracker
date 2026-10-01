// Tests for the in-browser search (site/geo.js) against the built data. Run: node tests/geo.test.mjs
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { miles, within, circle, searchSchools, parseHash } from "../site/geo.js";

const load = (n) => JSON.parse(readFileSync(new URL(`../site/virginia/data/${n}.json`, import.meta.url), "utf8"));
const facilities = load("facilities"), schools = load("schools"), zips = load("zips");
let failed = 0;
const check = (name, ok, detail = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? "  " + detail : ""}`); if (!ok) failed++; };

// 1. Distances agree with the Python pipeline (pipeline/geo.py), to a millionth of a mile.
const pairs = [[38.927278, -77.419005, 39.0195, -77.4504], [36.6, -83.6, 39.4, -75.3], [37.54, -77.43, 37.54, -77.43]];
const py = JSON.parse(execFileSync("python", ["-c",
  `import sys,json; sys.path.insert(0,'pipeline'); import geo; print(json.dumps([geo.miles(*p) for p in ${JSON.stringify(pairs)}]))`],
  { cwd: new URL("..", import.meta.url) }).toString());
check("JS and Python distances agree", pairs.every((p, i) => Math.abs(miles(...p) - py[i]) < 1e-6), JSON.stringify(py.map((x) => +x.toFixed(4))));

// 2. The case that started the project: within 1 mile of Carson Middle (Herndon).
const carson = schools.find((s) => s.id === "510126001756");
check("Carson Middle is in the school list", !!carson && carson.name === "Carson Middle");
const near = within(facilities, carson.lat, carson.lon, 1);
check("4 data centers within 1 mile of Carson Middle", near.length === 4, near.map((f) => `${f.id} ${f.stage} ${f.distance.toFixed(2)}`).join("; "));
check("...2 planned and 2 operating", near.filter((f) => f.stage === "planned").length === 2 && near.filter((f) => f.stage === "operating").length === 2);
check("results come nearest first", near.every((f, i) => i === 0 || near[i - 1].distance <= f.distance));

// 3. School search copes with how people actually say names.
for (const q of ["Rachel Carson", "rachel carson middle school", "Carson Middle", "carson"]) {
  const top = searchSchools(schools, q)[0];
  check(`"${q}" finds Carson Middle first`, top?.id === "510126001756", top ? top.name : "no result");
}
check("nonsense finds nothing", searchSchools(schools, "zzqx").length === 0);

// 4. ZIP codes: Virginia only.
check("ZIP 20171 (Herndon) is present", Array.isArray(zips["20171"]));
check("DC and Maryland ZIPs are excluded", !zips["20001"] && !zips["20850"]);

// 5. Shareable links parse safely.
const h1 = parseHash("#school=510126001756&r=1"), h2 = parseHash("#zip=2017&r=7"), h3 = parseHash("#pin=38.9,-77.4&r=30");
check("school link parses", h1.mode === "school" && h1.radius === 1);
check("bad ZIP and radius are rejected", h2.mode === null && h2.radius === null);
check("pin link parses", h3.mode === "pin" && h3.lat === 38.9 && h3.radius === 30);

// 6. The drawn search circle really has the requested radius.
const ring = circle(38.9, -77.4, 3).geometry.coordinates[0];
check("circle points are 3 miles out", ring.every(([lon, lat]) => Math.abs(miles(38.9, -77.4, lat, lon) - 3) < 1e-6));

// 7. County filings (the map's diamonds) work with the same search: all in Loudoun, found near a Loudoun ZIP.
const filings = load("filings");
check("county filings are present", filings.length > 50, String(filings.length));
check("every filing is in Loudoun's extent with a county record link", filings.every((f) =>
  f.lat >= 38.8 && f.lat <= 39.35 && f.lon >= -77.97 && f.lon <= -77.32 && f.source.startsWith("https://logis.loudoun.gov/")));
const ashburn = within(filings, ...zips["20147"], 3);
check("filings within 3 miles of ZIP 20147 (Ashburn), nearest first", ashburn.length > 0 && ashburn.every((f, i) => i === 0 || ashburn[i - 1].distance <= f.distance), String(ashburn.length));
check("no filings near Carson Middle (Fairfax County)", within(filings, carson.lat, carson.lon, 1).length === 0);

console.log(failed ? `${failed} FAILED` : "all passed");
process.exit(failed ? 1 : 0);
