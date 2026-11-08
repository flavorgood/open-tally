# Open Tally — dataset manifest

Prepared 2026-11-07 from the verified tables in ~/workspace/economic-tracker/.
Each dataset ships as CSV and JSON with the same fields and row counts.
Election Day record: 2026-11-03, frozen. Figures are preliminary until states certify.

| Dataset | Rows | Contents |
|---|---|---|
| turnout-2026-11-03 | 51 | Registered voters, ballots cast, turnout % per state + DC, with status and source per state |
| census-registered-2026 | 51 | 2020 Census population, registered voters, % of census registered, ballots, % of census ballots per state + DC |
| vap-2020-pl | 51 | 2020 Census voting-age population per state + DC (PL 94-171 Table P3) |
| county-vap-2020 | 3,143 | Total and voting-age population per county; each state's counties sum exactly to its state total |
| county-registered-co-de-ak | 107 | County registrations: Colorado 64 counties, Delaware 3 counties, Alaska 40 House districts, with basis, report date and source |
| county-roll-integrity-co-de | 67 | Registrations as % of adults per county, Colorado + Delaware |
| ak-district-roll-integrity | 40 | Registrations as % of adults per Alaska House district |
| ak-district-vap-2020 | 40 | Total and voting-age population per Alaska House district (2020 Census) |
| turnout-history-national | 6 | National turnout 2014–2024; registered / voting-age / voting-eligible series kept in separate fields |
| turnout-history-states | 30 | Turnout history for the ten anomaly states |

## Gaps, shown as empty / grey, never estimated

- County registrations exist only for Colorado, Delaware and Alaska (district geography). The other 47 states + DC are not yet pulled.
- 12 states + DC have no official ballots-cast total yet. Arizona canvass: 2026-11-23. DC accepts mail ballots until 2026-11-13.
- Michigan, Missouri, New Hampshire: ballots published, no exact registration total published.
- Ohio: registration figure is a voter-file count, not an official total.
- Delaware: county report (2026-11-01) sums to 809,631; statewide snapshot (2026-11-04) is 810,407. Both stand; they are not blended.
- Alaska: the state's own report carries two statewide registration totals — 605,433 and 604,611. The district parts sum to 604,611.
- Economic record tables (baseline, state factors, AAA gas dailies) stay with the tracker record until the rebuild's structure is stood up; they are not part of this election dataset set.
