# Open Tally — dataset definitions

One definition per measure. Denominators are never blended.

- **Registered voters** — the count on a state's voter rolls for the 2026-11-03 election, as published by that state's election office. Some states publish active voters only; some publish active + inactive. The basis is recorded in the dataset where the source states it.
- **Ballots cast** — ballots counted for the 2026-11-03 election, as published by the state's election office. Where a state has not published a ballots-cast total, the field is empty. In 11 states the figure is the vote total for the top statewide race, the standard count until a ballots-cast total is published; the dataset's source field says which.
- **Turnout %** — ballots cast ÷ registered voters × 100. Preliminary until a state certifies.
- **2020 Census population** — total resident population, 2020 Census.
- **Voting-age population (adults)** — population 18 years and over, 2020 Census Redistricting Data (PL 94-171), Table P3.
- **% of census registered** — registered voters ÷ 2020 Census population × 100.
- **Registrations as % of adults** — registered voters ÷ voting-age population × 100. A value over 100 means the rolls hold more names than the state or county has adults (2020 count).
- **Ballots per adult** — ballots cast ÷ voting-age population × 100.
- **Still counting** — the state has not published the figure yet. The field is left empty, never estimated.
