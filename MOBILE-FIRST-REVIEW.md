# Open Tally mobile-first presentation

Base: `a9728a4f2214b43a7a2620db9e988e754c7aad8f` (main rechecked 2026-11-10; unchanged).

## What changed

- A compact masthead, four persistent mobile destinations and prominent state lookup replace competing navigation stacks. Desktop keeps a familiar top navigation.
- Home offers direct paths to results, comparisons and sources. Map exploration, comparisons, all-state links and record history are expandable rather than a huge default stack.
- State pages put counts and county finding ahead of economic context. County pages present counts before the expandable 2026 narrative. Context remains dated and available.
- Year choices sit beside the content they control, not a fixed global bar implying every section changes year.
- Searchable directories become labelled mobile records with all source links and original colors. Wide comparisons remain side by side in bounded scrolling regions. Mobile counties show eight records at a time with search, paging and Show all.
- Source sections are directly addressable disclosures. Hash navigation opens the relevant section. Full static content and no-JavaScript controls remain available.
- The update notice remains on every page; its first sentence is always visible, with full unchanged wording in the source disclosure.

## Proof

- `python3 generate.py`: 51 states, 3,143 counties; 3,199 HTML pages total.
- 15 Python/static tests and four JavaScript interaction groups pass.
- Real local Chromium/Blink browser checks at 320, 390, 768 and 1280 pixels pass: no page overflow, search/empty/clear, state abbreviations, county pagination/show-all, scoped year URL/reload/Back, source filtering, no-JavaScript table/year fallback; no console exceptions.
- Browser tests use the supported standalone Chrome Headless Shell and locally intercepted generated files. No remote data, customer action, public listener or deployment is used. External font requests are blocked in this deterministic test; screenshots show fallback typography.
- All 91 source files remain byte-identical. All 137 generated non-asset files/downloads remain byte-identical. All 3,199 routes, table values/labels, citation text/URLs, year panes, and existing main-content prose tokens match the pre-change build. Layout, order and added navigation text may differ.
- Independent review found and corrected malformed-hash handling, navigation collision at tablet width, and excessive mobile stacking. Follow-up rendered measurements: home 2,716 px and Data 2,540 px high at 390px versus 12,433 and 60,060 in the first candidate. These are viewport/content measurements, not performance claims.

## Reproduce

```
python3 generate.py
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_navigation_logic.cjs
BROWSER_EXECUTABLE=/path/to/chrome-headless-shell python3 tests/test_navigation.py
python3 tests/verify_preservation.py /path/to/pre-change/site
```

Thomas authorized publication and deployment on 2026-11-10 after reviewing this candidate. Release verification is recorded separately after the exact revision reaches Render. Election numbers and their accuracy were not re-audited; this change deliberately preserves the existing source record without endorsing or correcting it.
