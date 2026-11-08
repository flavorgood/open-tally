"""Check built navigation contracts without a browser. Run after python generate.py."""
from pathlib import Path
import unittest
from lxml import html

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT/'site'

def page(path): return html.parse(str(SITE/path))

class NavigationTests(unittest.TestCase):
    def test_primary_navigation_consistency_and_local_assets(self):
        samples = ['index.html','states/index.html','states/texas/index.html',
                   'counties/texas/harris-county/index.html','rankings/index.html',
                   'data/index.html','definitions/index.html']
        for path in samples:
            with self.subTest(path=path):
                doc=page(path)
                nav=doc.xpath('//nav[@aria-label="Primary"]/a')
                self.assertEqual([a.text for a in nav],['Overview','States & Counties','Compare','Data & Sources'])
                self.assertEqual(len(doc.xpath('//nav[@aria-label="Primary"]/a[@aria-current="page"]')),1)
                self.assertEqual(len(doc.xpath('//main[@id="main-content"]')),1)
                self.assertFalse(doc.xpath('//nav[@class="botnav"]'))
                for link in nav:
                    self.assertTrue((SITE/path).parent.joinpath(link.get('href')).resolve().exists())
                for url in doc.xpath('//link[contains(@href,"assets/")]/@href | //script[contains(@src,"assets/")]/@src'):
                    self.assertTrue((SITE/path).parent.joinpath(url).resolve().exists())
    def test_state_and_county_static_fallback(self):
        doc=page('states/index.html')
        rows=doc.xpath('//table[@data-filter-table="states"]//tr[td]')
        self.assertEqual(len(rows),51)
        self.assertEqual(len([r for r in rows if r.get('data-abbreviation')=='TX']),1)
        texas=page('states/texas/index.html')
        self.assertEqual(len(texas.xpath('//table[@data-filter-table="counties"]//tr[td]')),254)
        self.assertEqual(len(texas.xpath('//table[@data-filter-table="counties"]//tr[@hidden]')),0)
        self.assertEqual(len((SITE/'states/texas/counties.csv').read_text().splitlines()),255)
    def test_year_scoped_county_sources(self):
        doc=page('counties/texas/harris-county/index.html')
        for year in ['2026','2024','2022','2020','2018','2016']:
            panes=doc.xpath(f'//div[contains(concat(" ",@class," ")," yp{year} ")]')
            self.assertEqual(len(panes),1)
            self.assertIn(f'{year} count',panes[0].text_content())
            if year != '2026': self.assertNotIn('November 2026 Voter Registration Figures',panes[0].text_content())
        self.assertIn('November 2026 Voter Registration Figures',doc.xpath('//div[contains(@class,"yp2026")]')[0].text_content())
        self.assertIn('2024 source:',doc.xpath('//div[contains(@class,"yp2024")]')[0].text_content())
    def test_section_index_targets(self):
        for path in ['data/index.html','rankings/index.html']:
            doc=page(path)
            links=doc.xpath('//nav[@class="section-index"]//a')
            self.assertGreaterEqual(len(links),10 if path.startswith("data") else 3)
            for link in links:
                self.assertEqual(len(doc.xpath('//*[@id=$anchor]',anchor=link.get('href')[1:])),1)
    def test_state_jump_targets(self):
        for path in ['states/texas/index.html','states/alaska/index.html']:
            doc=page(path)
            for anchor in doc.xpath('//nav[@class="jumpbar"]/a/@href'):
                self.assertEqual(len(doc.xpath('//*[@id=$anchor]',anchor=anchor[1:])),1,anchor)
    def test_public_context_is_source_focused(self):
        for path in ['index.html','states/texas/index.html','states/alaska/index.html',
                     'counties/texas/harris-county/index.html','data/index.html']:
            doc=page(path)
            for note in doc.xpath('//p[@class="measure-note"]'):
                text=note.text_content().lower()
                self.assertIn('2020 census',text)
                self.assertNotIn('invalid',text)
                self.assertNotIn('fraud',text)
            self.assertNotIn("What doesn't add up",' '.join(doc.xpath('//h2/text()')))

    def test_all_geography_pages_exist(self):
        self.assertEqual(len(list((SITE/'states').glob('*/index.html'))),51)
        self.assertEqual(len(list((SITE/'counties').glob('*/*/index.html'))),3143)

if __name__=='__main__': unittest.main()
