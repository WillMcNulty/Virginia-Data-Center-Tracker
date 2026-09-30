# Maryland: Phase 0 source research

Backlog item T11. Research only: nothing here is wired into the build or the site.

Checked 2026-09-30. All endpoints were queried from Python's standard library (`urllib`) with the project's
own User-Agent (`Virginia-Data-Center-Tracker/1.0 (+https://github.com/...)`). Every count below comes from a
query run that day unless it is marked **unverified**. Facility names are companies or public bodies. No person's
name is recorded here.

## Summary

- **Maryland has nothing like Virginia DEQ's `PLA_DATA_CENTER_YN` flag.** No MDE dataset or map service marks
  data centers, gives SIC or NAICS codes, or has coordinates. MDE air data is on Maryland's Socrata portal as
  tables with addresses. Data centers can be found there only by keyword, and only after they hold a permit to
  operate or have had an inspection. Permits to construct, which are the "planned" stage, appear only on MDE
  web pages and PDFs.
- **County land-use data is better than expected.** Frederick County publishes the adopted Critical Digital
  Infrastructure (CDI) overlay zone as an ArcGIS polygon and its open planning applications as another layer.
  Montgomery Planning publishes every development application type, including conditional uses, as ArcGIS
  layers. Both are scriptable in the same way as Loudoun's LOLA.
- **State policy records are scriptable.** The General Assembly publishes a JSON master list of bills each
  session. PSC CPCN applications are an HTML list only, and data center generator exemptions are filed as
  maillog items rather than cases.
- **Schools, ZIPs and counties use the same national sources as Virginia** (NCES EDGE, Census Gazetteer), plus
  Maryland iMAP for counties and a state geocoder.
- **Verdict:** feasible with the same pipeline, but the "which sites are data centers" step needs a small
  hand-reviewed list of MDE facility IDs. Details and effort are at the end.

## (a) Air permits and generator permits: Maryland Department of the Environment (MDE)

MDE's Air and Radiation Administration (ARA) permits data center backup generators under the Clean Air Act. MDE
says this on its data centers page (<https://mde.maryland.gov/datacenters>, HTML, fetched 200 with our UA). It
issues a **permit to construct (PTC)** first and a **state permit to operate** later. Every PTC goes through
public notice and a comment period.

### A1. MDE ARA Permits (Socrata) — usable for the operating stage

- **Owner:** MDE, published on Maryland's open data portal.
- **Endpoint:** `https://opendata.maryland.gov/resource/r8cv-wcdu.json` (Socrata dataset `r8cv-wcdu`,
  "Maryland Department of the Environment - Air and Radiation Administration (ARA) Permits"). Metadata:
  `https://opendata.maryland.gov/api/views/r8cv-wcdu.json`.
- **Format:** Socrata SODA API (JSON/CSV). Table only: it has an address but **no coordinates**.
- **Fields:** `site_no` (MDE "AI" agency-interest number), `site_name`, `permit_type_activity`,
  `permit_category`, `permit_status`, `status`, `administratively_extended`, `permit_start_date`,
  `permit_end_date`, `application_recieved` [sic], `application_voided`, `application_withdrawn`,
  `permit_terminated_date`, `alternate_ai_id`, `county`, `addressinfo`, `city_state_zip`, `document` (a link to
  the permit PDF on `mdedataviewer.mde.state.md.us/OpenDataDocuments?ID=...`).
- **Sample query:** `https://opendata.maryland.gov/resource/r8cv-wcdu.json?$limit=5000` returned **456 rows**
  (`$select=count(*)` agrees). Categories: 351 State Permits to Operate and 105 Part 70 (Title V) Permits to
  Operate. **No permits to construct.** Statuses: 417 Active, 35 Pending, 3 Expired - Extended, 1 Expired.
- **How to identify data centers:** no flag, SIC or NAICS field. Searching `site_name` for "data center", "data
  services", Amazon, Microsoft and similar found **6 data center rows**:
  - Prosperity Drive Data Center (AI 10717, Silver Spring, Montgomery)
  - Fannie Mae UTC Data Center (AI 26342, Urbana, Frederick)
  - Microsoft Corporation - Yellow Facility (AI 169136, Anne Arundel)
  - Amazon Data Services LTW060 (AI 170191, Jessup, Anne Arundel)
  - Amazon Data Services LTW062 (AI 170199, Severn, Anne Arundel)
  - Amazon Data Services LTW061 (AI 170207, Laurel, Howard)

  Keyword search has false positives ("P & J Contracting", "Superior Contractor Services"), so matches need a
  reviewed allow-list of AI numbers.
- **Update frequency:** the dataset's `rowsUpdatedAt` was 2026-09-30, so it looks daily.
- **License/terms:** the metadata says `PUBLIC_DOMAIN`. It is a documented public API, so there is no bot
  blocking.
- **Personal data:** none seen in the fields listed. Don't fetch the linked PDFs in bulk.
- **Gaps:** it covers only permits to operate. The largest new campuses (Aligned, Amazon's Frederick campus)
  are not in it yet. Addresses are sometimes partial ("Sandy Farm Rd", "S Eternal RIngs Dr"), and the Microsoft
  row has no city or ZIP.

### A2. MDE ARA Compliance (Socrata) — the widest list of air-regulated data centers

- **Endpoint:** `https://opendata.maryland.gov/resource/vgrx-qjj6.json` ("... ARA Compliance"). Sibling datasets
  are Violations (`5fzz-kwyg`), Enforcement Actions (`fpps-g5hi`) and Complaints (`crti-ybyp`).
- **Fields:** `ai`, `facility_name`, `street_address`, `city_state_zip`, `county`, `facility_id` (a 10-digit
  MDE air registration number: `24` + county FIPS + serial), `result_description` (e.g. "No Violations Noted",
  "Stack Test Passed", "Source Permanent Shutdown"), `achieved_date`, `documents` (PDF link).
- **Sample query:** `...vgrx-qjj6.json?$limit=50000` returned **23,885 rows**, with inspection dates from
  2021-11-01 to 2026-10-02. Updated 2026-09-30.
- **Data centers found by keyword:** 10 distinct AI numbers. They are the six in A1, plus:
  - Amazon Data Services BWI150-BWI153 (AI 185075, 3250 Digital Drive, Frederick; first inspection 2026-07-28)
  - CUBE NA Data Center Company (AI 26893, Elkridge, Howard)
  - IBM Annapolis Data Center (AI 1233; "Source Permanent Shutdown" 2022-07-29)
  - "Quantum Maryland (former Eastalco aluminum site)" (AI 8459). This is the old smelter's air record, marked
    shut down in 2023. It is **not** a data center record and must be excluded.

  Aligned (Frederick) is not in the dataset yet.
- **Violations dataset:** 156 rows. One data center (Fannie Mae UTC Data Center) appears.
- **Personal data:** the Complaints dataset has complaint text and ZIP codes of people who complained. **Do not
  use it.** Compliance, Violations and Enforcement contain facility data only.
- **Use:** this is the best statewide signal that a site exists and is regulated for air. Its inspection history
  also works as a "last checked by MDE" date.

### A3. MDE Public Notice (Socrata) — partial

- **Endpoint:** `https://opendata.maryland.gov/resource/3iva-5cca.json` ("MDE - Public Notice"). Its
  description says it helps residents find permit applications near them, with meetings, hearings and deadlines.
- **Sample query:** 321 rows: 241 wastewater, 61 solid waste, **15 air quality permits to construct**, 4 oil
  control. Updated 2026-09-30.
- **Data centers:** **1 row.** "Atmosphere Data Center Dickerson Property Owner LLC" is listed under Wastewater
  Permits, 3.01 Surface Water Discharge Permit (Industrial), status "Informational Meeting Planned", meeting
  2026-08-05. **None of the 15 air PTC rows is a data center.** The Amazon and Aligned generator permits are
  missing, so this dataset does not cover all air PTCs.
- **Personal data:** `applicant_address` and `mde_contact_information` can include individual people's names
  (one row has an "Attn:" line with a person's name). **Exclude these fields.** Use only `project_name`,
  `project_county`, `media_type`, `type_of_permit`, `status`, the date fields and `mde_links`.
- **Use:** a useful feed of public meetings and comment deadlines for the future "take part" feature, but not a
  list of data centers.

### A4. MDE data center and air permit web pages — HTML only (hand snapshot)

- `https://mde.maryland.gov/datacenters`: general overview.
- `https://mde.maryland.gov/datacenters/Pages/FrederickDataCenter.aspx` links the **issued PTCs** and final
  determinations for Amazon Data Services BWI (2026, `.../datacenters/Documents/2026_AmazonDataServicesBWIIssuedPTC.pdf`)
  and Aligned Data Centers (issued January 2025, `.../MarylandBrownfieldVCP/Documents/AlignedDataCenterJan2025IssuedPTC.pdf`).
  It also links water appropriation permits (FR2023G001, FR2024S001, FR2025G001) and brownfield/VCP documents
  for the Quantum Frederick site.
- `https://mde.maryland.gov/programs/permits/AirManagementPermits/Pages/index.aspx` has the air permit
  public-review tables (docket, notice, meeting and deadline). On 2026-09-30 it listed an Amazon "IAD534"
  application under an alternate NSPS public participation process, with an informational-meeting notice. That
  list is a SharePoint list ("ALTERNATE NSPS PUBLIC PARTICIPATION").
- **Bot blocking:** none. Pages returned 200 to our UA, and `robots.txt` disallows only SharePoint system paths
  (`/_vti_bin/`, `/_layouts/`, `/_catalogs/`). Even so, these pages are HTML and PDF built for people, and their
  layout changes. Treat them like Virginia's DEQ issued-permits page: a **dated hand snapshot** in `data/`
  (e.g. `mde_data_center_ptcs_YYYY-MM-DD.tsv`) with a link to each PDF.
- **Gap:** there is no statewide, machine-readable list of data center PTCs, pending or issued. The Maryland
  Register may carry notices (**unverified**).

### A5. EPA ECHO (federal) — cross-check only

- **Owner:** U.S. EPA. **Endpoint:**
  `https://echodata.epa.gov/echo/air_rest_services.get_facilities?output=JSON&p_st=MD&p_ncs=518210`, then
  `air_rest_services.get_qid?qid=...` for the rows.
- **Result:** **11 Maryland facilities** with NAICS 518210 ("data processing, hosting"). They include the Amazon
  LTW sites, Microsoft Yellow, Prosperity Drive, Fannie Mae UTC, and older corporate computer rooms (ADP,
  GE, Control Data, Gannett). IBM Annapolis is marked Permanently Closed. A name search for "DATA" returns 12,
  including telecom and insurer data centers under other NAICS codes. **Aligned, Quantum and Amazon Frederick
  return 0.** For comparison, the same NAICS query for Virginia returns 135, against DEQ's 198.
- **Fields:** lat/long (`FacLat`/`FacLong`), `AIRStatus`, `AIRPrograms`, SIC, NAICS and FRS registry ID.
  Public domain. `robots.txt` exists, and this is a documented API.
- **Use:** ECHO is a second opinion for coordinates and operating status. It is too incomplete and too slow for
  new sites to be the primary list.

## (b) Local land-use filings

### B1. Frederick County — CDI overlay zone (ArcGIS REST) ★

- **Owner:** Frederick County Government, Division of Planning and Permitting.
- **Endpoint:** `https://fcgis.frederickcountymd.gov/server_pub/rest/services/PlanningAndPermitting/CDI/MapServer/0`
  ("Critical Digital Infrastructure Zone (CDI)"), a polygon layer.
- **Sample query:** `.../0/query?where=1=1&outFields=Name,Level_,Acres,SQ_MI,Plan_,last_edited_date&returnGeometry=false&f=json`
  returned **1 feature**: "CDI- Critical Digital Infrastructure Overlay Zone", Overlay Zone, **2,611.9 acres
  (4.08 sq mi)**, `Plan_` = "Ordinance 26-01-001", last edited 2026-01-29.
- **Official record:** the county's CDI page
  (`https://www.frederickcountymd.gov/9128/Critical-Digital-Infrastructure-Overlay-`, HTML, 200) lists County
  Council Resolution 26-01 (comprehensive plan amendment) and **Ordinance 26-01-001** (comprehensive zoning for
  the CDI overlay). This matches the layer. The zone is around the former Eastalco/Alcoa site near Adamstown
  (Quantum Frederick).
- **Fields to exclude:** `created_user` and `last_edited_user` are staff logins.
- **Use:** draw the zone as an outline ("where the county allows data centers"), with its ordinance number and a
  link. This is coarse and already public. It is not infrastructure detail.
- **Note:** `https://frederickcountymd.gov/9122/Data-Centers`, the county's data centers landing page that news
  articles point to, returned **404** to both our UA and a browser UA on 2026-09-30.

### B2. Frederick County — open planning applications (ArcGIS REST) ★

- **Endpoint:** `https://fcgis.frederickcountymd.gov/server_pub/rest/services/PlanningAndPermitting/PlanningProjects/MapServer/0`
  ("Open Planning Applications"), polygons. Service description: "Map of Planning Projects in Open Status."
- **Fields:** `PROJNAME`, `APDESC` (Plat / Site, Concept and Sketch Plan / Preliminary Plat), `Permit` (e.g.
  `SP278472`), `Weblink` (the county's Infor permitting portal record), `CurrentMilestone`,
  `CurrentMilestoneDate`, `GeneralInfo` (free-text description).
- **Sample query:** `where=1=1` returned **295 features**, in these statuses: 227 "Awaiting Applicant Revisions",
  49 "Under Review", 9 "Awaiting Paperwork", 6 "Hearing Preparation" and 4 "Approved, Admin Closure". Records
  are not unique: one application can have several polygons, so de-duplicate on `Permit`.
- **How to identify data centers:** the text mentions "Critical Digital Infrastructure", "data center", Quantum,
  Bauxite or Rowan. Better still, use point-in-polygon against the CDI zone from B1. Data center applications
  found:
  - **Bauxite II Expansion** (SP278472, Type 1 site plan within the CDI overlay, "Hearing Preparation" 2026-01-29)
  - **Bauxite III Expansion** (SP278497, expands previously approved "Critical Digital Infrastructure Facility"
    SP278437 by one more data center building, "Hearing Preparation" 2026-02-06)
  - several Quantum Frederick / Rowan plats and a preliminary plan revision (PL278479, PL278576, PL279063-65,
    PP279103, PL279147)
- **Gap:** open applications only. Once approved and closed, a record leaves the layer. As with Loudoun, the
  change log would have to remember what it saw. There is no application date field, only the current
  milestone date.
- **Personal data:** for residential plats, `PROJNAME` and `GeneralInfo` can name an individual owner or cite
  deed book references. Only data center matches are kept, and `GeneralInfo` should be treated as free text
  that needs review.
- **Related:** `.../PlanningAndPermitting/PlanningPublicHearings/MapServer` (layer 0 Planning Commission items,
  layer 2 Board of Appeals, layer 4 Council land use proposals) had 2 upcoming Planning Commission items on
  2026-09-30, neither a data center. It is a possible source of hearing dates, but its `Applicant`/`Owner` fields
  must be excluded.
- **Terms:** there is no `robots.txt` on the GIS host (404). `copyrightText` is "FCGMD". The county's open data
  hub (`gis-fcgmd.opendata.arcgis.com`) lists these services publicly. `robots.txt` on `www.frederickcountymd.gov`
  disallows only admin, search and map pages.

### B3. Montgomery County — development applications (ArcGIS REST) ★

- **Owner:** Montgomery Planning (M-NCPPC), the source behind the Development Activity Information Center
  (DAIC).
- **Endpoint:** `https://mcmaps.org/server11/rest/services/Overlays/MCAtlas_Development_Review/MapServer`, found
  through the ArcGIS Online web map "DAIC Regulatory Plans Map". It has 17 layers: 1 Preliminary Plans (9,123),
  3 Site Plans (3,856), 7 Sketch Plans (163), 9 Mandatory Referrals (997), **10 Conditional Uses / Special
  Exceptions (4,998)**, 15 PreApplications, and others.
- **Fields:** `APNO` (plan number), `PROJNAME`, `LOC`, `SUBMITDATE`, `ACCEPTDATE`, `PBDATE` (Planning Board
  date), `DECISIONTYPE`, `CURRENTSTAGE`, `CURRENTMILE`, `PENDING`, the proposed and approved square footage by
  type, plus `FILED`/`DISPOSITION` on layer 10. Records go back decades and include current filings (latest CU
  submitted 2026-09-24).
- **How to identify data centers:** there is no use code for data centers, because until 2026 they were
  permitted as "communications facilities". Use a keyword on `PROJNAME` plus a reviewed list of `APNO`s. Found:
  - **CU202413** "Dickerson Power Plant", submitted 2023-12-13, decision "APPRVDMOD", Planning Board 2024-12-05
  - **CU202413A** "Dickerson Power Plant" (amended conditional use), submitted 2026-03-26, "Application
    Submitted"
  - Fairland Data Center site plans 819910300 (1991) and 81991030A (2014)

  Both CU records carry `DISPOSITION` = "CABLE", and only 2 of the 4,998 do. This looks like a use code, but its
  meaning is not documented (**unverified**).
- **Personal data:** the **`EMAIL` field (reviewer email) must never be requested**, the same rule as LOLA's
  AssignedTo. Request an explicit `outFields` list.
- **Related official records:** the Montgomery County Council enacted ZTA 26-01 (defines data centers, limits
  where they can go, and per the Council's release prohibits hyperscale data centers for now) and Expedited Bill
  19-26 (an 18-month pause on permits for data centers) on 2026-07-28. Source:
  <https://www.montgomerycountymd.gov/news/council-approves-18-month-data-center-moratorium-places-limitations-data-center-development>.
  Press reports say the amended Dickerson CU hearing before the Office of Zoning and Administrative Hearings
  is set for 2026-11-12 and 13 (**unverified** against OZAH's docket).
- **Terms:** there is no `robots.txt` on `mcmaps.org` (404). It is a public MapServer with no `copyrightText`.

### B4. Prince George's County — limited

- **Owner:** M-NCPPC Prince George's Planning.
- **Endpoint:** `https://gisdata.pgplanning.org/arcgis/rest/services/Applications/Data_Centers/MapServer`.
  - Layer 0 "Existing Data Center (EDC)": **5 points** (AiNET Beltsville and Laurel, the Census Bureau/UMD
    research data center, TW Telecom Laurel, ByteGrid College Park), with company, power and square footage.
  - Layer 1 "Potential Data Center Site (EDC)": **16 polygons** marked "Data Center Ready", "For Lease" or "For
    Sale", each linking to the county Economic Development Corporation's marketing page.
  - "EDC" means the Economic Development Corporation. These are **marketing listings, not filings or permits.**
    Showing them as "planned" would mislead. If they are used at all, they need a separate, clearly labeled
    category. Recommendation: leave them out.
- **Permits:** `.../Applications/DPIE_Combined_Permits/MapServer` (12,231 permits since 2013) and
  `.../Applications/Momentum_DPIE/MapServer` (15,669 building permits). A `WORK_DESCRIPTION`/`USE_TYPE_NAME`/
  `PROPOSED_USE` LIKE '%DATA CENTER%' query returned **0** in both.
- **Policy records:** the county's Executive Orders page
  (<https://www.princegeorgescountymd.gov/departments-offices/law/executive-orders>) lists EO 1-2026, EO
  10-2026 (a temporary hold on permit applications) and EO 15-2026 (extending it). These support the
  Qualified Data Centers Task Force, whose report is listed as a project in
  `.../Applications/PGCPOngoingandActiveProjects/MapServer/0` ("Data Center Task Force Study"). Press reports
  of a two-year pause on hyperscale data centers from July 2026 are **unverified** against a Council
  bill.
- **Gap:** there is no development-case layer with data center filings, which fits the moratorium.

### B5. Other counties — not yet checked (unverified)

News coverage (not official records) points to data center activity in these counties:

- **Anne Arundel and Howard:** the Amazon LTW sites and Microsoft. These are covered by MDE A1 and A2.
- **Baltimore County:** a reported 150 MW proposal in Woodlawn.
- **Charles County:** ZTA 25-187 was withdrawn in July 2026, and a task force is planned.
- **Cecil, Calvert and St. Mary's:** reported pauses or overlays.

None of their GIS or permitting systems has been checked yet.

## (c) State-level policy and records

### C1. Maryland General Assembly: bill master list (JSON) ★

- **Endpoint:** `https://mgaleg.maryland.gov/{YYYY}RS/misc/billsmasterlist/legislation.json`. It is one JSON
  array per session with `BillNumber`, `ChapterNumber`, `Title`, `Synopsis`, `Status`, the hearing dates and
  `BroadSubjects`/`NarrowSubjects`. It returned 200 to our UA. The subject index
  (`/mgawebsite/Legislation/SubjectIndex/datac?ys=2026RS`) is the same list as HTML.
- **Counts (bills mentioning "data center"):**
  - **2026RS:** 2,677 bills, 17 matches. Enacted: **HB 1532 / Chapter 353**, the Utility RELIEF Act (the
    Speaker's bill). HB 293 and SB 56 are unrelated (a state education data system).
  - **2025RS:** 7 matches. SB 116 / HB 270, "Data Center Impact Analysis and Report", were **vetoed by the
    Governor**.
  - **2024RS:** 2 matches. **SB 474 / Chapter 411**, the "Critical Infrastructure Streamlining Act", redefined
    "generating station" so that on-site emergency backup generation can be exempt from a CPCN under certain
    conditions.
- **HB 1532 (2026, Ch. 353), from DLS's Enrolled-Revised fiscal note**
  (`https://mgaleg.maryland.gov/2026RS/fnotes/bil_0002/hb1532.pdf`):
  - It lowers the "large load customer" threshold to at least **25 MW** and a load factor over 60%. The
    previous threshold, from the Next Generation Energy Act of 2025, was 100 MW and 80%.
  - It requires PSC to set up a **large load customer registry by 2027-07-01**, with a fee of at least
    $1,000/MW. Registrants disclose backup generation type, estimated water use and source, water permit
    status, and location.
  - Registry information is **confidential** before the customer is operational. PSC reports to two legislative
    committees annually from **2027-10-01**, and that report "may be used publicly."
  - It folds in the data center impact assessments by MDE, MEA and UMD, with the final report due 2026-09-01.
  - It prohibits data center construction in tax increment financing districts in Baltimore City.
  - It generally took effect 2026-07-01.
- **Use:** a statewide "rules and process" page, and a future source once PSC's annual registry report exists.
  The registry itself will not be a public site list.

### C2. Public Service Commission (PSC)

- **CPCN applications list:** `https://webpscxb.psc.state.md.us/DMS/cpcnapplication` (HTML, 200, about 298 KB).
  It lists **176 CPCN applications** (case 9439, 2017-02-17, to case 9906, 2026-09-21): 153 solar, the rest
  transmission lines and generating stations. **None is a data center.**
- **Data center generator exemptions** are filed under PUA §7-207.1 as **maillog items**, not cases. Example:
  Aligned Data Centers (MD) Propco, 168 × 3 MW diesel generators at "IAD04" in Frederick County, Maillog No.
  302893. See Order No. 90830, 2023-10-10, provisional order on rehearing:
  `https://psc.maryland.gov/wp-content/uploads/Order-No.-90830-Provisional-Order-on-Rehearing-ML-302893-1.pdf`.
  They can be searched only through the DMS MailLog search, which is an ASP.NET postback form. That is not
  scriptable in a clean way, so these would have to be hand-linked.
- **Terms:** `psc.maryland.gov/robots.txt` allows all with `Crawl-delay: 10`. The DMS host has no `robots.txt`
  (404). No blocking was seen.
- **Gap:** since SB 474 (2024) and HB 1532 (2026), fewer data center generator projects need PSC approval, so
  PSC will list few data center sites until the registry report exists.

## (d) Schools, ZIPs, counties, geocoding

| Need | Source | Query | Result |
|---|---|---|---|
| Schools | NCES EDGE `EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0` (same as Virginia) | `STATE='MD'` count | **1,415** public schools |
| ZIPs | Census 2025 Gazetteer ZCTA file (same as Virginia) | ZCTA prefixes 206-219 | **477** ZCTAs (200 and 202-205 are DC; 201 and 220+ are Virginia) |
| Counties | Maryland iMAP `https://mdgeodata.md.gov/imap/rest/services/Boundaries/MD_PoliticalBoundaries/FeatureServer/1` | `where=1=1` | **24** (23 counties + Baltimore City), fields `COUNTY`, `COUNTY_FIP` |
| Geocoding | Maryland iMAP `.../GeocodeServices/MD_MultiroleLocator/GeocodeServer/findAddressCandidates` | 3 MDE data center addresses | 3/3 matched, scores 97-100 |

- **Geocoding matters because MDE data has no coordinates.** The Census geocoder matched only 1 of the 3 test
  addresses. It missed the new-construction addresses 3250 Digital Drive and 610 Guardian Way. The Maryland
  iMAP locator matched all three. It returns a parcel account number as part of the match address, which we
  should not keep. Coordinates should be geocoded once and stored in a reviewed file, not re-geocoded every build.
- **Host note:** `geodata.md.gov/imap/rest/services` returned **503 "Site Maintenance"** on 2026-09-30. The same
  services answered at `mdgeodata.md.gov`. Use that host, with a health check.
- MDE's own ArcGIS host (`mdewin64.mde.state.md.us/arcgis/rest/services`) lists 20 folders, all with no public
  services. Maryland iMAP's Environment folder has no air facility layer.

## Personal data to exclude (summary)

| Source | Exclude |
|---|---|
| MDE Public Notice (`3iva-5cca`) | `applicant_address`, `mde_contact_information` (these carry people's names) |
| MDE ARA Complaints (`crti-ybyp`) | do not use at all (complaint text, complainants' ZIPs) |
| Montgomery `MCAtlas_Development_Review` | `EMAIL` (reviewer email); always pass an explicit `outFields` |
| Frederick `PlanningPublicHearings` | `Applicant`, `Owner`, `TAX_ACCT` |
| Frederick `CDI` / `PlanningProjects` | `created_user`, `last_edited_user`; review `GeneralInfo` free text |
| Maryland iMAP geocoder | parcel account numbers in match addresses |
| PSC orders | commissioner and counsel names are in the PDFs; link to them, don't extract them |

## Recommendation

**Maryland is feasible with the same pipeline, but not as a copy of Virginia.** Virginia has one authoritative
state layer that flags data centers and gives their stage and coordinates. Maryland has no such layer. The build
would combine official records under a small, reviewed allow-list, which is our own classification and must be
labeled as such.

**Minimal viable source set:**

1. **MDE ARA Compliance + Permits** (Socrata `vgrx-qjj6`, `r8cv-wcdu`). Keyword candidates are checked against a
   hand-reviewed `data/md_mde_data_centers.json`, which lists MDE AI numbers to include with a note and source
   link, and excludes AI 8459, the old smelter. Coordinates are geocoded once with the Maryland iMAP locator and
   stored in that file. This gives about 9 current sites plus 1 closed (IBM Annapolis), and a "last MDE
   inspection" date for each.
2. **MDE issued/pending PTC snapshot**: a dated hand snapshot from the MDE data centers and air permit
   public-review pages. It is the same pattern as the DEQ issued-permits TSV, with a PDF link per permit. This is
   the only source for the planned and under-construction stages (Aligned, Amazon Frederick, Amazon IAD534).
3. **Frederick CDI overlay + open planning applications** (B1, B2). Plot the zone outline and the data center
   applications inside it, de-duplicated by `Permit`.
4. **Montgomery conditional uses** (B3, layer 10), filtered by a reviewed `APNO` list (CU202413, CU202413A).
5. **Same national layers:** NCES, Census ZCTA and Maryland iMAP counties.

Leave out for now: the Prince George's "potential sites" layer (marketing listings), EPA ECHO (cross-check only),
and PSC (no machine-readable data center records until the 2027 registry report). Add MGA JSON later for a
"rules in Maryland" page.

**Build guards to add** (in the style of `check()`):

- MDE dataset row counts inside expected bounds (for example, ARA compliance has more than 15,000 rows).
- Every allow-listed AI still present, or explicitly marked as closed.
- Every allow-listed site has stored coordinates inside Maryland's county polygons.
- The Frederick CDI layer returns exactly 1 polygon.
- County sources are optional, with health checks like LOLA's. The build never fails on them.

**Estimated effort:**

- About **1-2 days** to generalize the pipeline for more than one state: state-parameterized sources, paths and
  pages. This is shared with Georgia (T12) and is the bigger part of the work.
- About **2-3 days** for the Maryland adapters, the allow-list and geocoding file, the PTC snapshot, the
  Frederick and Montgomery filings adapters, guards and tests.
- Ongoing: a short **monthly manual review** of new keyword candidates in the MDE datasets and of the MDE PTC
  pages. Maryland will need more hand-curation than Virginia's fully automatic daily build.

**Open questions for the owner:**

- Is a hand-maintained allow-list, labeled as our classification with each entry linked to the MDE record,
  acceptable as the basis for "this is a data center"?
- Should Frederick's CDI zone outline be shown on the map?
- Should the next pass check Baltimore, Charles, Cecil, Anne Arundel and Howard county systems?
