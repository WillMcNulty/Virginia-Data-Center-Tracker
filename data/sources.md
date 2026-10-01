# Sources and their limits

Checked 2026-09-27 and 2026-09-28.

## Virginia DEQ: Air Sites (Daily)

- `https://apps.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/294` ("Air Sites (Daily)"), queried
  with `PLA_DATA_CENTER_YN = 'Y'`. DEQ describes the layer as all active DEQ-permitted air facilities, located from
  911 addresses or other information confirmed by DEQ staff, and updated daily (see DEQ's Active Air Sites fact
  sheet).
- Used fields: `PLA_REG_NUM` (registration number), `PLA_NAME`, `FAC_L_ADDR_1`, `FAC_L_CITY`, `FAC_L_ZIP5`,
  `AIR_OP_STATUS` (Planned, Under Construction, Operating, Temporarily Shutdown), `PCL_STATE_DESC` (permit class),
  point geometry.
- On 2026-09-28: 198 sites (43 planned, 1 under construction, 153 operating, 1 temporarily shut down).
- **Limit:** a data center appears only once it applies for an air permit for its generators. Earlier stages
  (rezoning, special exception) are county records and not included yet.
- DEQ's data notice (the layer's `Data_Disclaimer` field) is shown on the site as published.

## Virginia DEQ: issued air permits for data centers (snapshot)

- `https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers`
- The page blocks automated requests (an Akamai 403, even for `robots.txt`), so it is not fetched by the build.
  It was opened in a normal browser and its table saved as `deq_issued_permits_2026-09-21.tsv` (the page's "as of"
  date): 194 permits for 183 facilities in 19 localities. The saved counts match the page's own.
- It's joined to the Air Sites layer by registration number (the part of the permit number before the dash). All
  183 facilities are in the layer. 15 layer sites have no row yet, probably permits still in progress, and the site
  says so for them.
- Known quirks, handled in `build.py`: one malformed date ("03/26-2026"), inconsistent program spelling ("Article 6
  - mNSR", "Article 6 mNSR", "Article 6-mNSR"), entries that cover several buildings.

## Virginia DEQ: county boundaries

- Layer 157 of the same service: the 133 counties and independent cities (FIPS 510 and up are cities), simplified
  to about 100 m for point-in-polygon.
- **Known disagreement:** three sites near the Manassas airport (registration numbers 74118, 74240, 74246) fall in
  Prince William County by these boundaries (confirmed with DEQ's own server-side spatial query), but DEQ's permit
  list says Manassas City. The site shows both rather than pick one.

## Loudoun County: Loudoun Online Land Applications (LOLA)

- `https://logis.loudoun.gov/gis/rest/services/Projects/LOLA_DATA/MapServer/0`, queried for applications whose name
  or description mentions "data center" or "datacenter" (508 records on 2026-09-30). Fields requested: `PlanNumber`,
  `PlanApplicationDate`, `PlanType`, `PlanStatus`, `PlanName`, `PlanDescription` and the parcel outline. The
  staff-assignment fields (a reviewer's name and email) are never requested.
- `pipeline/filings.py` keeps land-use applications (legislative applications, rezonings, special exceptions,
  concept plan amendments, commission permits) and site plans (engineering plans), drops paperwork (bonds, plats,
  studies, correspondence) and decided applications filed before 2021, and folds "SEE LEGI-... FOR DOCUMENTS"
  sub-applications into their umbrella: 173 filings on 2026-09-30 (78 in review, 95 approved). Each point is the
  center of the application's parcel outline; each links to its record on the county's server.
- **Personal data:** descriptions often end with the reviewing planner's initials, and some name an attorney or an
  owner; initials and review-session numbers are stripped, descriptions that name someone "on behalf of" an owner
  are replaced with a pointer to the county record, and one plan name that is a private person's name is withheld.
- **Limits:** the server is sometimes down (it answers with an HTML error page). The build then keeps the last
  published filings (`site/virginia/data/filings.json`), as it does when the data fails its checks (far fewer
  filings than last time, points outside Loudoun, missing fields). Statuses are the county's; a few old
  applications still show "In Review" years later.

## National Center for Education Statistics: public school locations

- `https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0`,
  queried with `STATE = 'VA'`: 2,159 schools with name, street, city, ZIP and coordinates (2024-25).
- **Limit:** official names are often short ("Carson Middle", not "Rachel Carson Middle School"). The search
  matches partial names, and `landmark_aliases.json` adds common names by NCES school ID.

## U.S. Census Bureau: ZIP Code Tabulation Areas

- 2025 Gazetteer (`2025_Gaz_zcta_national.zip`), internal point of each ZCTA. Virginia is taken as ZIP prefixes 201
  and 220-246 (200 and 202-205 are DC; 206-219 are Maryland): 903 ZIP codes.
- **Limit:** a ZIP code's center can be a few miles from any given home in it; the page says distances are measured
  from the center, and a school or a pin gives a precise point.

## Map

- MapLibre GL JS 6.11.2, served from `site/vendor/` (BSD-3-Clause; `site/vendor/LICENSE`).
- Basemap tiles from OpenFreeMap (free, no key, no cookies), positron (light) and dark styles; attribution shown on
  the map.
