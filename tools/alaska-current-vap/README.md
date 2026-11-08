# Alaska House districts: verified 2020 voting-age population on 2024 boundaries

## Result

`alaska_house_2020_vap_2024_boundaries.csv` has one record for each of 40 Alaska House districts. These are 2020 Census counts retabulated to 2024 state legislative district boundaries. The population reference year is 2020. VAP means all residents age 18 and over, regardless of citizenship.

All 40 Census P0010001 totals and geographic POP100 totals match Alaska's official May 2023 final plan district totals exactly. Statewide sum is 733,391 persons and 554,003 persons age 18+. District 6 is 18,434 total and 14,788 age 18+.

## Sources to download for reproduction

- Census data ZIP (save as `ak2020.cd19.zip`): https://www2.census.gov/programs-surveys/decennial/2020/data/119th-congressional-district-summary-file/Alaska/ak2020.cd19.zip
- Dataset/boundary documentation (save as `census_sld2024.html`): https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.2024.html
- Technical PDF (save as `cd119_techdoc.pdf`, extract text to `.txt`): https://www2.census.gov/programs-surveys/decennial/2020/technical-documentation/complete-tech-docs/119th-congressional-district-summary-file/2020census-119thcongressional-districts-techdoc.pdf
- Geographic field order (save under the URL filename): https://www2.census.gov/programs-surveys/decennial/2020/technical-documentation/complete-tech-docs/119th-congressional-district-summary-file/cd119-geographic-header-record.xlsx
- Table variables and segment order (save under the URL filename): https://www2.census.gov/programs-surveys/decennial/2020/technical-documentation/complete-tech-docs/119th-congressional-district-summary-file/cd119-table-matrix.xlsx
- Independent Alaska final-plan totals (save as `alaska2023_final_totals.pdf`, extract text to `.txt`): https://www.akredistrict.org/files/9116/8420/9246/2023-May-Final-Proclamation-Plan-Deviation-Table.pdf

Retrieved 2026-11-08 UTC. `source-sha256.json` records SHA-256 hashes of the originals and extraction artifacts used for verification. Large source binaries are not committed; download them from the links above into this directory before reproducing the extraction. The generated CSV is committed separately as `data/ak-district-vap-2020-current-boundaries.csv`. No API credentials were used.

## Exact extraction

Run `python extract.py` in this directory (requires openpyxl). The script reads field order and segment order from the official XLSX documentation, joins on LOGRECNO, validates the full set and totals, and recreates CSV and hashes. The final-plan text can be regenerated with `pdftotext -layout alaska2023_final_totals.pdf alaska2023_final_totals.txt`.

Select geographic records from `akgeo2020.cd19` with SUMLEV=620 (state lower legislative chamber), GEOVAR=L9, GEOCOMP=00, CHARITER=000. The current district identifier is SLDL24, codes 001..040. Full GEOIDs are 620L900US02001 through 620L900US02040. Do not use SLDL18 or assume old and current district numbers refer to identical territory.

The five initial data segment fields are FILEID, STUSAB, CHARITER, CIFSN, LOGRECNO. Table P1 starts segment 05 (`ak000052020.cd19`); its first data value is P0010001 (total population). Table P10 starts segment 06 (`ak000062020.cd19`); its first data value is P0100001 (total population age 18 and over). Both are zero-based column index 5. P10's full title and universe are specified in the table matrix. Geographic POP100 is an additional independent-within-file total check.

Census describes CD119 as the same subject content as the 2020 Demographic and Housing Characteristics file, retabulated to 119th congressional and 2024 state legislative districts. The 2024 boundary documentation states the districts are those submitted by state liaisons and in effect for the 2024 election cycle. The exact match with the 40 May 2023 Alaska final-plan totals provides a further boundary consistency check. This extraction itself does not independently re-audit whether any boundaries changed after 2024; the application should retain the 2024 geographic-vintage label and only use it with election districts independently established to have the same boundaries.

## Dates and definitions

- Population date and registration date differ. The displayed ratio is 2026 registrations divided by the 2020 adult population on the same district boundaries.
- VAP includes all residents age 18 and over, regardless of citizenship. Registration counts retain the values reported by their source.
- Census confidentiality protections apply. No rounding, adjustment, interpolation, or forced reconciliation was used. All 40 total-population comparisons happen to match exactly; this does not make VAP identical to another Census product's VAP.
- Existing old-plan/raw data should remain unchanged. Add this distinctly named derived source and record its source URL, dataset, population year, and boundary vintage.

## Subsequent boundary continuity

The Division of Elections confirms its April 2024 precinct maps conform to the May 15, 2023 final plan: https://www.elections.alaska.gov/research/district-maps/. The Redistricting Board states that this plan remains in effect until a new plan is adopted following the 2030 Census: https://www.akredistrict.org/. Both pages were checked on November 8, 2026. All 40 current-boundary totals match the final-plan PDF exactly.
