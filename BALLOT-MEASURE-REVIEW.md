# Ballot-measure correction — November 11, 2026

Base: 5a397106 (verified current main before publication).

The source CSV figures are unchanged. Legacy fields named ballots_cast are classified from their own source descriptions/recorded flags before derived calculations. Contest votes, returned ballots, estimated voters and lower bounds retain their original values and basis, but no longer enter ballot sums, ratios, rankings or the county ballot map. Current typed downloads expose reported_count separately from ballots and include measure and original source/reporting-date text. Exact dates are not guessed where a source description does not provide one.

Historical stored values remain downloadable. Cross-election deltas and high/low quadrant classifications are no longer presented as comparable results. The 2026 national row declares partial reporting-state coverage directly. County/state source notes identify differing measures and reporting snapshots rather than implying missing ballots.

Verification: 43 Python tests, JavaScript navigation logic checks, generated 51 state and 3,143 county pages; typed export assertions cover 2,200 county rows including 1,949 contest-vote rows. Independent review completed; its national-row and Minnesota-label findings corrected. No numerical source CSV changed. Population correction remains intact. Browser visual acceptance not performed in this change.

Limitations: existing source figures are not re-certified here. Current source set is classified from recorded metadata, not a new official-source fetch. New imports require explicit measure review; generic source text cannot establish ballots by its column name. Dates, coverage, preliminary status and registration definitions still vary. No fraud finding is made.
