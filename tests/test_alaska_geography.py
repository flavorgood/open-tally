"""Run after python3 generate.py. No network or browser required."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import unittest
from lxml import html

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import alaska_geography as ak


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


class AlaskaJoinTests(unittest.TestCase):
    def setUp(self):
        self.raw = read_csv(ROOT / "data/ak-district-roll-integrity.csv")
        self.population = read_csv(ROOT / "data" / ak.POPULATION_FILE)

    def test_verified_extraction_and_current_boundary_values(self):
        # Exact artifact independently extracted from Census CD119 and checked
        # against all 40 rows of Alaska's final-plan population table.
        digest = hashlib.sha256((ROOT / "data" / ak.POPULATION_FILE).read_bytes()).hexdigest()
        self.assertEqual(digest, "2c2fbc1a4c1a40528b1298f4cd8ea1448459bf83a47e1e261eb3186bd2eeca50")
        rows = ak.district_comparisons(self.raw, self.population)
        self.assertEqual(len(rows), 40)
        self.assertEqual(sum(int(r["registered_voters"]) for r in rows), 604611)
        self.assertEqual(sum(int(r["total_population_2020"]) for r in rows), 733391)
        self.assertEqual(sum(int(r["voting_age_population_2020"]) for r in rows), 554003)
        self.assertEqual(sum(float(r["registered_pct_of_vap"]) > 100 for r in rows), 29)
        hd6 = next(r for r in rows if r["district"] == "House District 6")
        self.assertEqual((hd6["voting_age_population_2020"], hd6["registered_pct_of_vap"]), ("14788", "125.6"))
        over = ak.over_total_population(rows)
        self.assertEqual([r["district"] for r in over], ["House District 6"])
        self.assertEqual(int(hd6["registered_voters"]) - int(hd6["total_population_2020"]), 133)

    def test_original_inputs_untouched_and_legacy_ratios_ignored(self):
        before_raw, before_pop = copy.deepcopy(self.raw), copy.deepcopy(self.population)
        expected = ak.district_comparisons(self.raw, self.population)
        self.assertEqual(self.raw, before_raw)
        self.assertEqual(self.population, before_pop)
        for row in self.raw:
            row["voting_age_population_2020"] = "0"
            row["registered_pct_of_vap"] = "99999"
        self.assertEqual(ak.district_comparisons(self.raw, self.population), expected)

    def test_rejects_missing_duplicate_or_wrong_geographies(self):
        for key, value in [("boundary_vintage", "2013"),
                           ("dataset", "2020 PL"),
                           ("vap_variable", "P0010001"),
                           ("census_geoid", "620L900US02040")]:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.population)
                bad[0][key] = value
                with self.assertRaises(ValueError):
                    ak.district_comparisons(self.raw, bad)
        for bad in (self.population[:-1], self.population + [self.population[0]]):
            with self.assertRaises(ValueError):
                ak.district_comparisons(self.raw, bad)
        for bad in (self.raw[:-1], self.raw + [self.raw[0]]):
            with self.assertRaises(ValueError):
                ak.district_comparisons(bad, self.population)

    def test_rejects_invalid_counts_and_broken_reconciliation(self):
        for value in ("-1", "999999", "13931"):
            bad = copy.deepcopy(self.population)
            bad[0]["voting_age_population_2020"] = value
            with self.assertRaises(ValueError):
                ak.district_comparisons(self.raw, bad)
        bad = copy.deepcopy(self.raw)
        bad[0]["registered_voters"] = "-1"
        with self.assertRaises(ValueError):
            ak.district_comparisons(bad, self.population)


class AlaskaOutputTests(unittest.TestCase):
    def test_state_table_and_headlines_use_correct_boundaries(self):
        doc = html.parse(str(ROOT / "site/states/alaska/index.html"))
        rows = doc.xpath('//tr[td[1][normalize-space(.)="House District 6"]]')
        self.assertEqual(len(rows), 1)
        cells = [c.text_content() for c in rows[0].xpath("./td")]
        self.assertEqual(cells[:3], ["House District 6", "18,567", "14,788"])
        self.assertIn("125.6%", cells[3])
        self.assertEqual(rows[0].xpath("./td[3]/a/@href"), [ak.SOURCE_URL])
        text = doc.getroot().text_content()
        self.assertIn("29 of 40 House districts", text)
        self.assertNotIn("31 of 40 House districts", text)
        self.assertIn("18,434 residents counted in 2020", text)
        self.assertIn("2020 Census adult populations retabulated to 2024 district boundaries", text)
        self.assertNotIn("16,292 residents", text)
        front = html.parse(str(ROOT / "site/index.html")).xpath('//main')[0].text_content()
        # The current overview does not render a district comparison. It must
        # not resurrect the obsolete 16,292-resident Alaska claim either.
        self.assertNotIn("16,292 residents", front)

    def test_all_combined_exports_match_recomputed_rows(self):
        expected = ak.district_comparisons(
            read_csv(ROOT / "data/ak-district-roll-integrity.csv"),
            read_csv(ROOT / "data" / ak.POPULATION_FILE))
        expected = {r["district"]: r for r in expected}
        paths = [("site/downloads/county-voter-list.csv", "county", "adults", "registered_per_100_adults"),
                 ("site/downloads/county-voter-list.json", "county", "adults", "registered_per_100_adults"),
                 ("site/data/registered-share-of-adults.json", "geography", "adults_2020", "registered_pct_of_adults")]
        for path, geography, adults, ratio in paths:
            with self.subTest(path=path):
                rows = read_csv(ROOT / path) if path.endswith(".csv") else json.loads((ROOT / path).read_text())
                rows = [r for r in rows if r["state"] == "Alaska" and r[geography].startswith("House District ")]
                self.assertEqual(len(rows), 40)
                for row in rows:
                    correct = expected[row[geography]]
                    self.assertEqual(int(row[adults]), int(correct["voting_age_population_2020"]))
                    self.assertEqual(float(row[ratio]), float(correct["registered_pct_of_vap"]))
                    self.assertEqual(row["population_geography"], ak.POPULATION_GEOGRAPHY)
                    self.assertEqual(int(row["population_year"]), 2020)
                    self.assertEqual(int(row["population_boundary_vintage"]), 2024)
                    self.assertEqual(int(row["registration_year"]), 2026)
                    self.assertEqual(row["population_source_url"], ak.SOURCE_URL)

    def test_raw_downloads_preserved_and_limitation_disclosed(self):
        for name in ("ak-district-vap-2020.csv", "ak-district-vap-2020.json",
                     "ak-district-roll-integrity.csv", "county-anomalies.csv"):
            self.assertEqual((ROOT / "data" / name).read_bytes(), (ROOT / "site/data" / name).read_bytes())
        data = html.parse(str(ROOT / "site/data/index.html")).getroot().text_content()
        self.assertIn("previous 2013 districts", data)
        self.assertIn("must not be reused for current district comparisons", data)
        self.assertTrue((ROOT / "site/data/ALASKA-GEOGRAPHY.md").is_file())
        self.assertTrue((ROOT / "site/data" / ak.POPULATION_FILE).is_file())

    def test_public_alaska_notes_are_neutral_data_descriptions(self):
        doc = html.parse(str(ROOT / "site/states/alaska/index.html"))
        self.assertEqual(doc.xpath('//h2[@id="adds"]/text()'), ["Published comparisons"])
        texts = [doc.xpath('//*[@id="alaska-geography"]')[0].text_content(),
                 doc.xpath('//h2[@id="adds"]/following-sibling::div[1]')[0].text_content(),
                 (ROOT / "site/data/ALASKA-GEOGRAPHY.md").read_text(),
                 (ROOT / "tools/alaska-current-vap/README.md").read_text()]
        for text in texts:
            self.assertNotRegex(text.lower(), r"fraud|ineligible|suspicious")


if __name__ == "__main__":
    unittest.main()
