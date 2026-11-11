import unittest
import generate as g


class HistoryMeasureSafeguards(unittest.TestCase):
    def row(self, measure='ballots'):
        return {'state': 'Example', 'measure': measure, 'value_2026': '1,000',
                'value_2022': '2,000', 'value_2018': '3,000',
                'deviation_vs_2022_pp_or_pct': '-50%',
                'deviation_vs_2018_pp_or_pct': '-66.7%'}

    def test_archive_preserves_values_but_not_invalid_deltas(self):
        result=''.join(g.anoms_rows_html([self.row()], with_state=True))
        for value in ('1,000', '2,000', '3,000', 'Example'):
            self.assertIn(value, result)
        self.assertNotIn('-50%', result)
        self.assertNotIn('-66.7%', result)
        self.assertEqual(result.count('Not comparable'), 2)
        self.assertNotIn('background', result)

    def test_no_biggest_change_claim(self):
        text=g.anoms_tline([self.row()])
        self.assertNotIn('biggest', text)
        self.assertIn('not a comparable change series', text)
        self.assertEqual(g.anoms_tline([]), '')

    def test_ratios_are_archival_not_turnout_claims(self):
        for measure in ('turnout_pct_registered', 'ballots_pct_of_vap', 'registered_voters'):
            text=''.join(g.anoms_rows_html([self.row(measure)]))
            self.assertIn('archived', text)
            self.assertIn('Not comparable', text)

    def test_groups_are_not_reasserted(self):
        rows=[{'state':'Example','registered_pct_of_vap':'98.4','ballots_pct_of_vap':'43.2',
               'quadrant':'high rolls / low ballots'}]
        text=g.archived_quadrants_html(rows)
        self.assertIn('98.4%', text)
        self.assertIn('43.2%', text)
        self.assertNotIn('high rolls / low ballots', text)
        self.assertNotIn('Big voter list', text)
        self.assertIn('mixed measures', text)

    def test_empty_and_untrusted_values(self):
        row=self.row();row['state']='<script>';row['value_2026']='';row['value_2022']='<img>'
        text=''.join(g.anoms_rows_html([row],with_state=True))
        self.assertNotIn('<script>', text);self.assertNotIn('<img>',text)
        self.assertIn('—',text)

if __name__ == '__main__': unittest.main()
