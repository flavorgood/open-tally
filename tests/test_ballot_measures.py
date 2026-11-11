import csv
import unittest
import generate as g
from ballot_measures import state_measure, county_measure, ballot_value

class BallotMeasuresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=g.load();cls.s=g.build_states(cls.d)
    def test_state_race_and_estimate_exclusions(self):
        for name in ['New York','New Jersey','Missouri','Minnesota','Oklahoma','Pennsylvania','Rhode Island','Tennessee','Virginia','Wisconsin','Colorado','Washington','New Hampshire']:
            with self.subTest(name=name):
                s=self.s[name]
                self.assertIsNotNone(s['published_count'])
                self.assertIsNone(s['ballots'])
                self.assertIsNone(s['turnout_pct'])
                self.assertIsNone(s['bal_pct_est'])
    def test_actual_ballots_preserved(self):
        self.assertEqual(self.s['Florida']['ballots'],8335497)
        self.assertEqual(self.s['California']['ballots'],8906017)
    def test_race_source_not_inferred_as_ballot(self):
        kind,label=state_measure('X',{'source':'total votes in the U.S. Senate race'})
        self.assertEqual(kind,'contest_votes');self.assertIsNone(ballot_value(kind,123))
    def test_returned_separate(self):
        kind,_=state_measure('X',{'source':'Ballots Returned'})
        self.assertEqual(kind,'ballots_returned');self.assertIsNone(ballot_value(kind,123))
    def test_county_classifications(self):
        kinds=[county_measure(label) for label in g.BALLOTS26_LABEL.values()]
        self.assertEqual(kinds.count('contest_votes'),28)
        self.assertEqual(kinds.count('ballots_returned'),1)
        self.assertEqual(kinds.count('ballots_cast'),5)
    def test_summary_retains_raw_count_and_basis(self):
        h=g.count_summary_rows(self.d,self.s['Colorado'])
        self.assertIn('Ballots returned',h);self.assertIn('2,761,449',h)
    def test_national_sum_excludes_nonballots(self):
        h=g.national_history_table(self.d)
        expected=sum(s['ballots'] or 0 for s in self.s.values())
        self.assertIn(f'{expected:,}',h)
        original=sum(g.num(r['ballots_cast']) or 0 for r in self.d['turnout'].values())
        self.assertNotEqual(expected,original)
    def test_unspecified_contest_never_invented(self):
        self.assertNotIn('Governor',self.s['Texas']['count_label'])
    def test_national_coverage_label_on_row(self):
        h=g.national_history_table(self.d)
        self.assertIn('Partial reporting states; not comparable',h)
    def test_estimate_flag_truthful(self):
        row=self.d['state_flags'][('Minnesota','ballots_cast')]
        h=g.flag_sentence(self.d,row,self.s['Minnesota'])
        self.assertIn('estimated voter count',h)
    def test_raw_source_numbers_unchanged_in_model(self):
        for name,s in self.s.items():
            self.assertEqual(s['published_count'],g.num(self.d['turnout'][name]['ballots_cast']))

if __name__ == '__main__': unittest.main()
