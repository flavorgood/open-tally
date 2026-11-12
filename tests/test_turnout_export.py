"""Build with python generate.py before running export acceptance checks."""
import csv
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TurnoutExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / 'site/downloads/state-figures-by-year.csv').open() as f:
            cls.rows = list(csv.DictReader(f))
        cls.json_rows = json.loads((ROOT / 'site/downloads/state-figures-by-year.json').read_text())

    def test_arizona_partial_coverage_is_reproducible(self):
        r = next(r for r in self.rows if r['state'] == 'Arizona' and r['year'] == '2016')
        self.assertEqual(r['registered_voters'], '4080680')
        self.assertEqual(r['turnout_matched_registered_voters'], '1642199')
        self.assertEqual(r['turnout_matched_ballots_cast'], '1072699')
        self.assertEqual(r['turnout_coverage'], '14 of 15 counties in the sum')
        self.assertEqual(round(int(r['turnout_matched_ballots_cast']) / int(r['turnout_matched_registered_voters']) * 100, 1), float(r['turnout_pct_registered']))

    def test_all_county_sum_rates_reproduce_and_json_matches(self):
        count = 0
        by_key = {(r['state'], str(r['year'])): r for r in self.json_rows}
        for r in self.rows:
            j = by_key[r['state'], r['year']]
            for field in ('turnout_matched_registered_voters', 'turnout_matched_ballots_cast'):
                self.assertEqual(r[field], '' if j[field] is None else str(j[field]))
            if r['basis'] == 'Federal survey (EAVS) — counties added up':
                count += 1
                reg = int(r['turnout_matched_registered_voters'])
                bal = int(r['turnout_matched_ballots_cast'])
                self.assertEqual(r['turnout_pct_registered'], str(round(bal / reg * 100, 1)) if reg else '')
            else:
                self.assertEqual(r['turnout_matched_registered_voters'], '')
                self.assertEqual(r['turnout_matched_ballots_cast'], '')
        self.assertGreater(count, 0)

if __name__ == '__main__': unittest.main()
