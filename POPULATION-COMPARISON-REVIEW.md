# Population comparison repair — 2026-11-11

Base: 8324f03b96e6f1d9930b7e084bef669b53201426. Remote main still matched at final pre-publication check. Not deployed by this worker.

## Verified defect and repair
Current voter-list comparisons used the 2020 adult count although the repository already contained 2025 adult estimates. Main current headline, current maps, rankings, state/county summaries and current downloadable comparisons now use July 1, 2025 resident age-18-plus estimates. Historical 2020 comparisons remain explicitly dated; original source files are unchanged. No extrapolated 2026 population has been invented. Resident adults are not synonymous with eligible voters.

Same 2,515 matched counties: 244 above the 2025 estimate, versus 462 above the 2020 count. This is a comparison, not proof of misconduct. Registration date/basis, population date/basis and sources are carried with each downloadable row. Geographic exceptions remain separate: Connecticut's current planning regions are not joined to historical counties; Alaska legislative districts are not joined to borough estimates.

National ratios now use the same reporting jurisdictions in numerator and denominator. Thresholds use unrounded values; formatting rounds only for display. Raw historical API fields remain preserved, explicitly labeled historical, with current companion state fields and a county-comparison download.

## Independent issuing-office verification
Retrieved 2026-11-11:
- https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/asrh/cc-est2025-agesex-all.csv
  SHA256 9220eb2b4eabfd267a633665028164fced81d1b11c74425006e8a0bd6aeb8f7a
  YEAR=7: all 3,144 repository county rows exactly match AGE18PLUS_TOT and POPESTIMATE.
- https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/state/asrh/sc-est2025-alldata6.csv
  SHA256 505fd45bfb15b96c0da1d67cf54d47b3b4cb8765a7814de6e0629dabd13258aa
  SEX=0, ORIGIN=0, all RACE1..6; ages18..85 vs0..85: all51 repository state rows exactly match POPESTIMATE2025 adult/total sums.

Repository CSV SHA256:
- county: f48bcbec7b885113c9d162c7813b2e3b1cf65196c6fb75d787bf1611ecb69258
- state: 81d304dd767df46200941d720c1d3e775467130adb6ddef171cbd9cdab5b8609

## Checks
Generator succeeds: 51 states, 3,143 county pages. Python regression suite27/27; navigation JavaScript tests pass; git diff --check passes; no raw data modifications. Independent reviewer reviewed thresholds, map years, current vs historical consumers and APIs; second independent review confirms current comparison arithmetic, dates and source URLs; final legacy-download year labeling corrected afterward.

## Not proven by this repair
This is not an audit of every election-office figure. Existing ballot-field source flags include top-race votes and incomplete counts; a separate metric-consistency repair must ensure rankings never equate race votes with ballots. Population estimates are the latest published official age estimates, not a current election-day census or an eligibility count. No fraud finding is made.
