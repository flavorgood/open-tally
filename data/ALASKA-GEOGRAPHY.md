# Alaska district comparison correction

Checked November 8, 2026. No existing source file was changed.

## Correct population geography

`ak-district-vap-2020-current-boundaries.csv` contains 2020 Census adult populations retabulated to 2024 state legislative lower-chamber districts. These match Alaska’s final May 2023 House plan, used by the 2026 registration districts. The generator joins the preserved registration counts to this separately named source, calculates every ratio again, and rejects incomplete, duplicate, or unsupported district geography.

The population reference year is 2020 and the registration reference year is 2026. Voting-age population means all residents age 18 and over, regardless of citizenship. The displayed ratio is 2026 registrations divided by the 2020 adult population on the same district boundaries.

## Original inputs retained

The original `ak-district-vap-2020.csv` and JSON, `ak-district-roll-integrity.csv`, and Alaska row of `county-anomalies.csv` remain unchanged for traceability. Their populations use the previous 2013 district boundaries. All 40 total-population values match the old-plan archive, so the old denominators and ratios must not be joined to 2026 district registrations.

The Alaska page, combined voter-list downloads, and registered-share-of-adults JSON now use the current-boundary source. House District 6 has 18,567 registered voters in the recorded 2026 snapshot, 14,788 adults and 18,434 total residents in the 2020 Census on those same boundaries. Its ratio is 125.6%, not 149.6%; the difference from total population is 133, not 2,275. The number of districts above 100% of 2020 VAP is 29, not 31. These differences remain visible with their dates.

## Source and extraction

- Census bulk data: https://www2.census.gov/programs-surveys/decennial/2020/data/119th-congressional-district-summary-file/Alaska/ak2020.cd19.zip
- Census boundary documentation: https://www.census.gov/programs-surveys/decennial-census/about/rdo/state-legislative-district.2024.html
- Official current-plan population table: https://www.akredistrict.org/files/9116/8420/9246/2023-May-Final-Proclamation-Plan-Deviation-Table.pdf
- Division of Elections maps: https://www.elections.alaska.gov/research/district-maps/
- Board statement that the final plan remains until redistricting following 2030: https://www.akredistrict.org/
- Old-plan population archive: https://www.akredistrict.org/alaska-population/deviation.php?c=1&d=ASC&o=district

Select akgeo2020.cd19 records with SUMLEV=620, GEOVAR=L9, GEOCOMP=00, CHARITER=000. SLDL24 identifies districts 001–040. Join by LOGRECNO to P0010001 (segment 05) and P0100001, population age 18 and over (segment 06). All 40 P0010001 and geographic POP100 totals exactly match the official final-plan population table. The district sums reconcile to 733,391 total residents and 554,003 adults. No adjustment, interpolation, or forced reconciliation was applied.

The repository’s tools/alaska-current-vap directory contains the reproduction script, official layout URLs, and source hashes. The original ZIP SHA-256 is 1b92860b2b32a86ab0c9403e1694642cd493cdb9e6aa8d0f1cd38152cd604dc6.
