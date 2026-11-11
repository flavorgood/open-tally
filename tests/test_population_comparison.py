import unittest
import generate as g
from population_comparison import comparisons

class PopulationComparisonTests(unittest.TestCase):
    def fixture(self, adults='120', registered='110', old='100'):
        c={'state':'Test','_nkey':'one','county_name':'One','voting_age_population_2020':old}
        r={'registered_voters':registered,'report_date':'2026-11-01','basis':'Active only','source':'Office'}
        e={'adults_18plus':adults,'estimate_year':'2025','source_url':'https://www.census.gov/source'}
        return [c], {('Test','one'):r}, {('Test','one'):e}
    def run_case(self, *args): return comparisons(*args, g.num)
    def test_growth(self):
        rows,missing=self.run_case(*self.fixture());self.assertFalse(rows[0]['above']);self.assertEqual(rows[0]['change_since_2020'],20)
    def test_decline(self):
        rows,_=self.run_case(*self.fixture('90'));self.assertTrue(rows[0]['above']);self.assertEqual(rows[0]['change_since_2020'],-10)
    def test_zero_registration_is_present(self):
        rows,_=self.run_case(*self.fixture(registered='0'));self.assertEqual(rows[0]['ratio'],0)
    def test_missing_never_falls_back(self):
        c,r,e=self.fixture();rows,missing=self.run_case(c,r,{});self.assertFalse(rows);self.assertEqual(len(missing),1)
    def test_wrong_year_never_blends(self):
        c,r,e=self.fixture();e[('Test','one')]['estimate_year']='2024';self.assertFalse(self.run_case(c,r,e)[0])
    def test_unrounded_threshold(self):
        rows,_=self.run_case(*self.fixture('10000','10001'));self.assertTrue(rows[0]['above'])
    def test_source_and_dates_preserved(self):
        rows,_=self.run_case(*self.fixture());self.assertEqual(rows[0]['registration_basis'],'Active only');self.assertEqual(rows[0]['population_date'],'2025-07-01')
    def test_real_record_counts(self):
        d=g.load(); by={}
        for c in d['counties']:
            c['_nkey']=g.county_key(c['county_name']);by.setdefault(c['state'],[]).append(c)
        r=g.resolve_county_rows([x for x in d['county_reg'] if x['geography_type'] in ('county','county-equivalent')],by,'geography_name')
        e=g.resolve_county_rows([x for x in d['est_county_rows'] if x['state']!='Connecticut'],by,'county')
        rows,missing=self.run_case(d['counties'],r,e)
        self.assertEqual((len(rows),sum(x['above'] for x in rows),len(missing)),(2515,244,0))

if __name__=='__main__': unittest.main()

class GeneratedPopulationTests(unittest.TestCase):
    def test_all_primary_surfaces_name_latest_year(self):
        from pathlib import Path
        for path in ['index.html','rankings/index.html','states/index.html','states/texas/index.html','counties/texas/harris-county/index.html','data/index.html']:
            s=(Path(g.OUT)/path).read_text()
            self.assertIn('2025',s,path)
            self.assertNotIn('adults who in',s,path)
    def test_download_matches_headline_without_rounding(self):
        import csv
        from pathlib import Path
        rows=list(csv.DictReader((Path(g.OUT)/'downloads/county-registration-population-2025.csv').read_text().splitlines()))
        self.assertEqual(len(rows),2515)
        self.assertEqual(sum(int(r['registered'])>int(r['adults']) for r in rows),244)
    def test_legacy_api_is_explicitly_historical(self):
        import json
        from pathlib import Path
        rows=json.loads((Path(g.OUT)/'data/registered-share-of-adults.json').read_text())
        self.assertTrue(all(r['ratio_population_year']==2020 for r in rows))
    def test_current_state_api_matches_actual_denominator(self):
        import json
        from pathlib import Path
        rows=json.loads((Path(g.OUT)/'data/states.json').read_text())
        for r in rows:
            if r['registered_voters'] is not None and r['adults_2025_estimate']:
                self.assertAlmostEqual(r['registered_pct_of_adults_2025_estimate'],r['registered_voters']/r['adults_2025_estimate']*100)
