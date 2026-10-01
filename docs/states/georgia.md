# Georgia: Phase 0 source research

Research only (backlog T12). Checked 2026-09-30. Every count below comes from a request actually made that day,
unless marked **unverified**. Nothing here changes the site.

## Summary

- **Air permits (the Virginia DEQ equivalent):** Georgia EPD has no ArcGIS layer with a data center flag. The best
  scriptable source is **EPA ECHO's Air Facilities layer** (federal, ArcGIS REST). It carries Georgia EPD's own
  facility records (AIRS number, address, coordinates, operating status, SIC/NAICS) and returns **42 Georgia data
  center facilities** (22 operating, 15 planned, 5 permanently closed). All 36 facilities that EPD's permit search
  lists under SIC 7374/7375/7376 are in it. EPD's **permit search** (permitsearch.gaepd.org) adds the permit
  history and links to permit PDFs, but it is an ASP.NET form, not an API.
- **Applications under review:** EPD's **weekly Public Advisory PDFs** list new air-permit applications before
  anything reaches ECHO or the permit search (8 data center entries in the 8 advisories from Aug-Sep 2026). They are
  PDFs, so parsing them needs a PDF library (or a hand-kept snapshot).
- **Regional review (DRI):** the state's DRI system (apps.dca.ga.gov) **disallows all crawling in robots.txt**, so
  the build can't fetch it. Two of Georgia's 12 regional commissions publish their DRIs as public ArcGIS layers:
  Northeast Georgia (Newton, Walton, Morgan, Jackson and others) and Coastal (Effingham and others).
- **County filings:** no county was found with a Loudoun-LOLA-style ArcGIS case layer. Coweta and Henry publish
  meeting agendas through CivicClerk's public JSON API, which is keyword-searchable. The other counties checked use
  CivicPlus or Revize websites with PDF agendas. The City of Atlanta's website returns 403 to scripts.
- **State records:** PSC docket filings are listable as JSON. Georgia Power's quarterly "Large Load Economic
  Development Reports" give statewide MW totals, not sites.
- **Schools/ZIPs/counties:** the national sources work: NCES (2,349 GA schools), Census Gazetteer (751 GA ZCTAs),
  Census TIGERweb counties (159).
- **Recommendation:** feasible with the same pipeline. The minimal viable source set is ECHO + NCES + Gazetteer +
  TIGERweb, which is about 2-3 days of work. Details are at the end.

## (a) Air permits

### A1. EPA ECHO: Air Facilities layer (recommended primary source)

- **Owner:** U.S. EPA, Enforcement and Compliance History Online (ECHO). The Georgia records come from EPD through
  EPA's ICIS-Air system.
- **Endpoint:** `https://echogeo.epa.gov/arcgis/rest/services/ECHO/Facilities/MapServer/1` ("Air Facilities"),
  ArcGIS REST, maxRecordCount 1000. Georgia has 7,478 rows (`AIR_STATE='GA'`).
- **How to identify data centers:** there is no flag. This filter worked:
  `AIR_STATE='GA' AND (AIR_NAICS LIKE '%518210%' OR FAC_SIC_CODES LIKE '%7374%' OR FAC_SIC_CODES LIKE '%7375%'
  OR FAC_SIC_CODES LIKE '%7376%' OR UPPER(AIR_NAME) LIKE '%DATA CENTER%')`.
- **Sample query (2026-09-30):** that filter returned **42 facilities**:
  - by status (`AIR_STATUS`): Operating 22, Planned Facility 15, Permanently Closed 5;
  - by county (`AIR_COUNTY`): Fulton 17, Douglas 10, Gwinnett 4, Newton 3, and one each in Fayette, Rockdale,
    Whitfield, Henry, Bartow, Jackson, Troup and Forsyth;
  - every row had a street address and ZIP.
- **Fields to use:** `SOURCE_ID` (`GA00000013` + 3-digit county code + 5-digit facility number; the last 8 digits
  are EPD's AIRS number, e.g. `GA0000001309700102` = AIRS `097-00102`), `AIR_NAME`, `AIR_STREET`, `AIR_CITY`,
  `AIR_ZIP`, `AIR_COUNTY`, `AIR_STATUS`, `AIR_NAICS`, `FAC_SIC_CODES`, `AIR_UNIVERSE` (e.g. "Synthetic Minor
  Emissions", "Major Emissions"), `FAC_LAT`, `FAC_LONG`, `DFR_URL` (link to EPA's facility report).
- **Join to EPD:** all 36 facilities that EPD's permit search lists under SIC 7374/7375/7376 matched an ECHO row by
  AIRS number (36/36). ECHO adds 4 more: Travelers Data Center (SIC 4911), Serverfarm LLC, Cingular Network
  Technology Center, and an older closed Google record.
- **Gaps and quirks:**
  - The filter misses data centers filed under telecom SIC 4813. EPD's own 2022 layer describes Bellsouth Telecomm
    Midtown Two as a "data center and peak shaving generator", and the 4813 list also includes Savvis AT1 and
    375 Riverside Pkwy LLC. A **reviewed allow-list of AIRS numbers** is needed for these, as Maryland needs.
  - It may also include a few non-data-center telecom or IT sites (for example the Cingular technology center).
    Review each one before publishing.
  - The statuses are Operating / Planned Facility / Permanently Closed. Unlike Virginia's layer, there is no
    "Under Construction".
  - Projects whose applications are still under review are not in ECHO yet (see A3).
  - Two Google records share one coordinate.
- **Update frequency:** EPA documents a weekly ECHO refresh (**unverified** from the service metadata).
- **Terms / bot blocking:** federal public data. Requests from both the Python standard library and curl worked
  with no blocking.
- **Personal data:** none in the fields listed above. The layer also carries demographic and EJScreen percentile
  fields (`FAC_PERCENT_MINORITY`, `PCTILE_*`). Don't request them: they aren't needed and they aren't facility
  records.

### A2. Georgia EPD: Air Permit Search Engine

- **Owner:** Georgia EPD, Air Protection Branch.
- **URL:** `https://permitsearch.gaepd.org/`. This is an ASP.NET WebForms page with Telerik controls. There's no API:
  a search is a form POST carrying `__VIEWSTATE`/`__EVENTVALIDATION` and Telerik "ClientState" JSON, and paging is a
  further postback.
  - SIC searches need the `txtSIC` ClientState JSON (`validationText`/`valueAsString`) set to the code.
  - Facility-name searches go through a Telerik autocomplete box. Its ClientState must be
    `{"enabled":true,"logEntries":[{"Type":1,"Index":0,"Data":{"text":"<name>","value":""}}]}`.
  - Without these fields the filter is silently ignored and all **10,422** permits come back (522 pages).
- **How to identify data centers:** permit numbers begin with the facility's SIC code
  (`7374-097-0102-S-01-0`), and the SIC box matches on that. Results on 2026-09-30:

  | SIC | Permits | Facilities | Notes |
  |---|---|---|---|
  | 7374 (data processing) | 47 | 26 | the main code (QTS, Amazon, Aligned, Vantage, Edged, EdgeConneX, DC Blox, Equinix, T5 …) |
  | 7375 | 5 | 2 | The Keep Campus (Douglas), The Keep 2 Campus (Bartow) |
  | 7376 | 42 | 8 | Microsoft (3 sites), Quality Investment Properties (QTS) Metro and Suwanee, Equinix, others |
  | 7389 | 28 | 3 | includes Google (Douglas, `097-00061`); the other two are not data centers |
  | 4813 | 17 | 9 | mix of telecom sites and some data centers (see the allow-list note above) |
  | 7379, 6798, 7371, 7372, 4899 | 0-1 | | nothing relevant |

  SIC 7374 + 7375 + 7376 give **36 unique facilities**. Name searches ("data", "Microsoft", "Amazon", "Google",
  "QTS", "Vantage", "Equinix" …) added only Travelers Data Center (permits under SIC 4911).
- **Fields:** AIRS number, facility name, permit number, issuance date, permit type (SIP / Title V), and links to the
  permit and narrative PDFs (`/Permit/OP-<application no>`, `/Permit/ON-<application no>`). The results table has
  **no address and no coordinates**.
  - Page 1 of a permit PDF gives the facility address, the AIRS number and a plain description. For example,
    `OP-29723` (DCB Atlanta West, Douglas County) describes "two (2) buildings equipped with a total of
    seventy-six (76) emergency generators".
  - Text extraction needs a PDF library (pypdf worked); the standard library can't do it.
- **TLS quirk:** the server sends an incomplete certificate chain. Python's `urllib` fails with
  `CERTIFICATE_VERIFY_FAILED`. curl on Windows (schannel, which fetches the missing intermediate) works. A build
  would have to ship the intermediate certificate or use a CA bundle that includes it.
- **robots.txt:** none (404). No CAPTCHA or bot blocking seen.
- **Recommendation:** use it only lightly, if at all: about 10 requests per run (three SIC searches with paging), for
  permit history and PDF links. It is HTML form scraping rather than an API, so the owner should decide. ECHO alone
  is enough for the map.
- **Update frequency:** permits appear when issued (**unverified** cadence).
- **Personal data:** the permit and narrative PDFs name EPD reviewing staff and signers. Don't extract them. The
  mailing address on page 1 is a company office; use only the facility address.

### A3. Georgia EPD: weekly Public Advisories (applications under review)

- **Owner:** Georgia EPD (all branches; the air section is "Georgia Air Protection Branch").
- **URL:** index page `https://epd.georgia.gov/permitting-public-advisories-and-public-notices`, with PDFs at
  `https://epd.georgia.gov/document/document/pa<MMYY>-<n>/download`. The September 2026 files were `pa0926-1` …
  `pa0926-3` and `pa0926-4-1`. The suffix varies, so read the index page; don't guess URLs.
- **Format:** text PDF, published weekly, with a fixed block per application: county heading, `Facility Name:`,
  `Application No:`, `Facility Address:`, `EPD Notice Type:` (Permit Application / Proposed Permit),
  `Description of Operation:`, `Reason for Application:`, and a comment deadline. **No AIRS number**: match to ECHO
  later by name and address.
- **How to identify data centers:** "Description of Operation" contains "Data Processing, Hosting" (EPD's SIC
  7374/NAICS 518210 wording, sometimes misspelled: "Hostin", "Relative Services"), or "Reason for Application"
  mentions "data center".
- **Sample (2026-09-30):** all 8 advisories from Aug-Sep 2026 downloaded and parsed with pypdf. They contained **8
  data center entries**:
  - The Keep 2 Campus (Bartow)
  - Amazon Data Services ATL088 (Douglas)
  - Equinix Atlanta Data Center (Henry)
  - "Appling Facility", 700 Innovation Parkway, Appling (Columbia)
  - QTS ATL3 Campus (Augusta)
  - QTS Fayetteville I (Fayette)
  - Apex Site Solutions (Henry)
  - TADG ATL02 / Ellenwood (Clayton)

  At least Apex Site Solutions was not in ECHO that day.
- **robots.txt** (epd.georgia.gov): allows `/document/` paths. No blocking seen.
- **Personal data:** none seen. Comments go to a generic EPD mailbox.
- **Gap:** PDF parsing. Either add pypdf to CI (the pipeline is standard library only today), or keep a hand-checked
  dated snapshot in `data/`, as Virginia does for DEQ's issued-permits page.

### A4. Georgia EPD: "Permitted Air Facilities" ArcGIS layer (not recommended)

- `https://services1.arcgis.com/p0dLjwtOaJHU8zq2/arcgis/rest/services/air_source_coordinates1/FeatureServer/0`. It
  is owned by an EPD ArcGIS Online account and used in EPD's "Georgia Community Mapping Tool".
- 1,084 rows covering Title V and synthetic-minor sources only (`Classification` A / B / SM). It has a
  `Plant_Description` free-text field; 12 rows match data / computer / information.
- **Stale:** `dataLastEditDate` is 2022-07-25. Use it only as a cross-check.

## (b) Local land-use filings

### B1. Developments of Regional Impact (DRI): state system

- **Owner:** Georgia Department of Community Affairs (DCA). Each filing has a page at
  `https://apps.dca.ga.gov/DRI/AppSummary.aspx?driid=<n>`, giving project, local government, developer, status,
  regional commission, tier, and dated steps through the RDC finding.
- **robots.txt at `apps.dca.ga.gov` is `User-agent: * Disallow: /`.** By the project's rule, the build must not fetch
  it. One summary page was opened by hand to confirm its contents; no other requests were made.
- **Data centers:** DCA's board added a "Technological Facility" DRI category covering data centers in late 2025,
  with thresholds of 300,000 sq ft in the 11-county metro Atlanta area and 500,000 sq ft elsewhere (from press
  coverage; the rule text is **unverified**). Since then, data center DRIs can be found by development type. Older
  ones are filed as "Industrial" under project code names.
- **Options:** ask DCA for a feed or bulk export, keep a hand-saved snapshot, or use the regional commission layers
  below. The regional layers carry `DCALink` back to each DCA page, so the site can link to DCA without fetching it.

### B2. Northeast Georgia Regional Commission: DRI layer

- **Endpoint:** `https://services1.arcgis.com/Ug5xGQbHsD8zuZzM/arcgis/rest/services/NEGRC_Developments_of_Regional_Impact_Locations_(Public)/FeatureServer/1`
  (polygons). It covers Barrow, Clarke, Elbert, Greene, Jackson, Jasper, Madison, Morgan, Newton, Oconee,
  Oglethorpe and Walton.
- **Fields:** `Number` (DCA DRI id), `Name`, `DRIStatusText`, `DevelopmentTypeName`, `CountyName`,
  `JurisdictionName`, `RDCFindingText`, `DateFormSubmittedInitial1`, `Year`, `DCALink`, `NEGRCLink`, `DRI_Acres`.
- **Sample (2026-09-30):** 430 DRIs. `dataLastEditDate` was 2026-09-30, so the layer is actively maintained.
  - No "Technological Facility" type appears yet. Data centers are under "Industrial" (68 of those).
  - A name search for "data" finds 2: "Data Center 0 Social Circle Parkway" (Walton, DRI 4329, 2024) and
    "Gregory Road Data Center" (Newton, DRI 4428, 2025).
  - Code-named projects such as "Project Paradise" or "Newton County Technology Park" can't be classified from this
    layer alone.
- **Personal data:** none in these fields.

### B3. Coastal Regional Commission: DRI layer

- **Endpoint:** `https://portal.segrass.org/crcarcgis/rest/services/Region/Landuse_Planning/MapServer/6`
  ("Development Regional Impact", polygons; used by the CRC "DRI Dashboard").
- **Sample:** 409 DRIs. `DevType = 'Technological Facility (including Data Centers)'` returned **1**: Project
  Camellia (DCA DRI 4801, Effingham County).
  - `ProjectDesc` is "Data center campus", and `ProjectSize` is "4 buildings with a total of 4,400,000 square feet".
  - `EstimatedValue` is 20,000,000,000.
  - Status Completed; RDC finding dated 2026-09-01.
- **Personal data to exclude:** `created_user` and `last_edited_user` (staff usernames). `Developer` is a company,
  sometimes written "c/o" a law firm; keep it to the company name or leave it out.
- **Gap:** Georgia's other regional commissions publish no public DRI layer that could be found. These include ARC,
  which covers Douglas, Fayette, Fulton, Henry, Clayton, Gwinnett and Rockdale, as well as Three Rivers (Coweta,
  Troup), Northwest Georgia (Bartow, Whitfield) and CSRA (Columbia, Richmond). ArcGIS Online searches found nothing.
  ARC lists DRIs on its web pages (**unverified** whether the build can fetch them).

### B4. County rezoning cases and agendas

| County | Site platform | Machine-readable? | Notes |
|---|---|---|---|
| Coweta | CivicPlus site; agendas on **CivicClerk** (`cowetacoga`) | **Yes**: JSON API `https://cowetacoga.api.civicclerk.com/v1/Events` (OData `$filter`, paging) and `/v1/Meetings/{agendaId}` (agenda items) | 68 meetings Jan-Sep 2026; 32 agendas searched; 4 items mention data centers (ordinance and moratorium items, June-July 2026). Moratorium from June 2026 to Dec 23, 2026 (press; **unverified** against the county record). |
| Henry | CivicPlus site; **CivicClerk** (`henrycoga`) | **Yes**, same API | 35 meetings Jan-Sep 2026; 3 data center items (ULDC-AM-24-04 data center ordinance amendment; consulting contract RFP #26-23). |
| Douglas | CivicPlus | PDF agendas only (**unverified** whether the Agenda Center RSS has items; it returned 0) | robots.txt blocks `/RSS.aspx` and Baidu/Yandex only. Data center moratorium reported in press (**unverified**). |
| Newton | CivicPlus (Agenda Center) | Agenda Center RSS returned 2 items; agendas are PDFs | |
| Columbia | CivicPlus | Agenda Center RSS returned 0 items | |
| Fayette | Revize | Not found | robots.txt 404 |
| Bartow | Revize | Not found (RSS path 403) | County zoning *map* layer at `bartowgis.org/.../BartowZoning/FeatureServer` (zoning districts, not cases) |
| Fulton County | | Not checked beyond homepage (**unverified**) | |
| City of Atlanta | | **403 to scripts** (atlantaga.gov, including robots.txt) | Treat as blocked |

- No county was found with a case-level ArcGIS layer like Loudoun's LOLA. Douglas County's ArcGIS views are a
  customer survey and yearly KPI counts. The survey layer has `Creator`/`Editor` fields; don't use it.
- **Personal data:** CivicClerk event records include staff fields (`createdByUserId`,
  `closedCaptionUploadedByName`, …). Request or keep only the event date, body, item title and agenda link.
- **Gap:** rezoning agenda items often name the applicant or a project code, not "data center". A keyword search
  catches ordinance and moratorium items more reliably than the cases themselves.

## (c) State-level records

### C1. Georgia Public Service Commission dockets

- **Owner:** Georgia PSC (FACTS docket system).
- **Endpoint (JSON, though served as `text/html`):**
  `https://psc.ga.gov/search/service-facts-docket/?docketId=<id>&sortDirection=desc&sortColumn=DateFiled&searchText=&pageSize=200&pageNumber=1`
  returns `resultsCount` and `resultsItems` (documentId, description, filedDate, company). Files download from
  `https://services.psc.ga.gov/api/v1/External/Public/Get/Document/DownloadFile/<documentId>/<n>`.
- **Sample:** docket **55378** returned 240 filings, 10 of which are Georgia Power's quarterly "Large Load Economic
  Development Report" (latest found: Q1 2026, filed 2026-05-15, document 226607). Docket **56002** (2025 IRP)
  returned 219 filings.
- **What it gives:** statewide MW totals for large-load commitments and pipeline. Not facility locations, so it is
  context for an explainer, not map points.
- **robots.txt:** 404 on both hosts.
- **Personal data:** `companyDetailsVm` includes a `modifiedBy` staff username. Don't keep it.
- A March 2026 PSC "Data Center Fact Sheet" PDF (`psc.ga.gov/site/downloads/datacenterfactsheet.pdf`) now returns
  404.

### C2. Legislation and tax exemption reporting

- **Tax exemption:** the Georgia High-Tech Data Center Equipment sales and use tax exemption, O.C.G.A. §
  48-8-3(68.1).
  - The Department of Audits' evaluation (prepared by UGA's Carl Vinson Institute, December 2022) was downloaded
    from `https://www.audits.ga.gov/ReportSearch/download/29072` (PDF, 39 pages). It gives aggregate estimates of
    forgone revenue and says Georgia had "approximately 100 data centers". No site list.
  - A newer Department of Revenue evaluation (reported to cover 34 data centers using or applying for the exemption
    in 2025) is at `open.georgia.gov/openga/report/downloadFile?rid=33298`. That host presented a certificate for
    the wrong name, so it was **not fetched (unverified)**.
- **Bills:** HB 1192 (2024; would have paused new exemption certificates) was vetoed. SB 34 (ratepayer protection
  from data center costs) died in 2026 without a floor vote. Both are from press and bill trackers (**unverified**
  against legis.ga.gov). The legislature's site is a JavaScript app, and its API wasn't explored.
- Neither is a per-site data source.

## (d) Schools, ZIP codes, counties

- **NCES EDGE public schools:** same layer as Virginia
  (`.../EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0`). `STATE='GA'` returned **2,349** schools. NCES short names will
  need a `landmark_aliases` file as in Virginia.
- **Census ZCTA Gazetteer 2025:** Georgia ZIP prefixes 300-319 and 398-399 give **751** ZCTAs. 398-399 are
  Georgia IRS/unique ZIPs; check whether any are ZCTAs before relying on them.
- **Counties:** Census TIGERweb `https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1`
  with `STATE='13'` returned **159** counties (`NAME`, `GEOID`). Georgia has no independent cities, so there is no
  Manassas-style city/county split. Consolidated governments (Augusta-Richmond, Athens-Clarke, Columbus-Muscogee,
  Macon-Bibb) are listed under their county names.
- All three worked with the existing `pipeline/sources.py` helpers (standard library).

## Recommendation

**Feasible with the same pipeline.** Georgia has no single state layer with a data center flag like Virginia's DEQ
layer. EPA ECHO comes close: official, ArcGIS REST, daily-fetchable, with addresses, coordinates and an
operating/planned/closed status, and it joins one-to-one to EPD's AIRS numbers.

**Minimal viable source set:**

1. ECHO Air Facilities (filter above), plus a reviewed allow-list and deny-list of AIRS numbers in `data/` for the
   SIC 4813/4911 sites and false positives. This is the map.
2. NCES (GA), Census Gazetteer (GA ZCTAs) and TIGERweb counties, for search and pages.
3. Links to EPD's permit search and to each facility's EPA report (`DFR_URL`) as the record trail.

**Next, in order of value:**

4. EPD weekly Public Advisories, for applications under review. This needs pypdf in CI or a hand snapshot.
5. NEGRC and Coastal RC DRI layers, as an early-stage "regional review" marker. Other regions would need DCA's
   cooperation or hand snapshots.
6. CivicClerk agendas for Coweta and Henry (fits backlog T8's civic layer).
7. Optional: light EPD permit-search scraping for permit history, if the owner accepts form-postback HTML.

**Estimated effort:**

- Items 1-3: about 2-3 days. One fetcher, a filter, the allow-list, status mapping (no "Under Construction" stage),
  a state switch in pages and app, and tests.
- Item 4: about 1 day.
- Item 5: about 1 day.
- Item 6: about 1-2 days per platform.
- Items 1-3 and 5 also depend on the multi-state structure, which Virginia's code doesn't have yet (the paths are
  `/virginia/...`). That generalisation is the bigger, shared cost and isn't counted here.

**Owner decisions needed:**

- Whether ECHO (federal) is an acceptable primary source in place of a state layer.
- Whether to add pypdf as a dependency.
- Whether light form-postback requests to permitsearch.gaepd.org fit the no-scraping rule. It has no robots.txt and
  no blocking, but it isn't an API.
- Whether to contact DCA about a DRI feed, since apps.dca.ga.gov disallows crawling.
