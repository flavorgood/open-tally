# Open Tally — dataset definitions

One definition per measure. Different measures and reporting dates are not interchangeable.

- **Registered voters** — the issuing office's voter-list count, with active, inactive or total basis where stated. Registration is not a count of votes or proof of eligibility.
- **Ballots cast / counted** — the recorded ballot measure, kept separate from votes in a contest. Counts are preliminary or incomplete where the source says so.
- **Votes in a contest** — candidate or question vote totals in the named race. They exclude ballots without a valid vote in that race and are not used as ballot turnout totals.
- **Ballots returned** — returns received, not necessarily accepted or counted. They do not enter the ballots-cast ranking or aggregate.
- **Estimated voters / minimum voters** — an estimate or lower bound is retained under that label, never used as an exact ballot count.
- **Legacy raw files** — historical source CSVs retain their original column names and values. Some `ballots_cast` fields contain a different measure described in the source text. Use the typed downloads and states JSON for calculation: `reported_count` preserves every original value, `measure_type` identifies its basis, and derived `ballots` / `ballots_cast` is empty for incompatible measures. Raw historical computed ratios are archival, not corrected current comparisons.
- **Turnout % of registered** — recorded ballot count divided by recorded registered voters. Only compatible ballot measures enter this calculation. Reporting dates and registration bases can differ and are disclosed; this is not final turnout until the office certifies it.
- **Current adults** — Census Bureau July 1, 2025 age-18+ resident population estimates, explicitly dated. This is not Election Day 2026 population and is not citizen voting-age population.
- **Historical adults** — 2020 Census PL 94-171 Table P3, retained as a separately labeled historical comparison.
- **Citizen adults (CVAP)** — a different population measure with its own source/vintage. Never substituted for all resident adults.
- **Incomplete / no data** — figures remain absent when no compatible published figure is recorded. No extrapolation, population projection or invented ballot count fills a gap.
- **Comparisons** — same-measure and same-snapshot reconciliation requires matching election, geography, source date and measure. Differences between race votes and ballots or between reporting times are not evidence of missing ballots. Partial 2026 coverage versus completed past elections does not establish a turnout change.
