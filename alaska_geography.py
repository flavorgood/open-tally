"""Join Alaska registrations only to verified, current-boundary Census counts.

The original ak-district-roll-integrity.csv joins 2026 registrations to the
previous 2013 districts. Keep that input intact, but never use its denominator
or precomputed percentage in a rendered comparison or a combined export.
"""
import re

POPULATION_FILE = "ak-district-vap-2020-current-boundaries.csv"
SOURCE_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
              "119th-congressional-district-summary-file/Alaska/ak2020.cd19.zip")
BOUNDARIES_URL = "https://www.elections.alaska.gov/research/district-maps/"
FINAL_PLAN_URL = ("https://www.akredistrict.org/files/9116/8420/9246/"
                  "2023-May-Final-Proclamation-Plan-Deviation-Table.pdf")
POPULATION_GEOGRAPHY = "2024 Census SLDL; Alaska final 2023 House plan"


def district_comparisons(registrations, populations):
    """Return new rows with matched denominators; reject incomplete/wrong joins.

    No fallback to the legacy denominator is permitted. District numbers alone
    are not a geography key: the vintage, dataset, GEOID and variable must also
    match the verified source. All inputs remain unchanged.
    """
    populations = list(populations)
    expected = set(range(1, 41))
    population_by_district = {}
    for row in populations:
        district = int(row["district"])
        if district in population_by_district:
            raise ValueError("Duplicate Alaska population district")
        if (row["boundary_vintage"] != "2024"
                or row["dataset"] != "2020 Census CD119"
                or row["vap_variable"] != "P0100001"
                or row["census_geoid"] != f"620L900US02{district:03d}"):
            raise ValueError("Unsupported Alaska population geography or measure")
        adults = int(row["voting_age_population_2020"])
        total = int(row["total_population_2020"])
        if not 0 < adults <= total:
            raise ValueError("Invalid Alaska population counts")
        population_by_district[district] = row
    if set(population_by_district) != expected:
        raise ValueError("Alaska population source must contain districts 1–40")
    if (sum(int(r["total_population_2020"]) for r in populations) != 733391
            or sum(int(r["voting_age_population_2020"]) for r in populations) != 554003):
        raise ValueError("Alaska population source does not reconcile statewide")

    out, seen = [], set()
    for row in registrations:
        match = re.fullmatch(r"House District (\d+)", row["district"])
        if row["state"] != "Alaska" or not match:
            raise ValueError("Invalid Alaska registration district")
        district = int(match[1])
        if district not in expected or district in seen:
            raise ValueError("Duplicate or unknown Alaska registration district")
        seen.add(district)
        population = population_by_district[district]
        registered = int(row["registered_voters"])
        if registered < 0:
            raise ValueError("Invalid Alaska registration count")
        adults = int(population["voting_age_population_2020"])
        joined = dict(row)
        joined.update(voting_age_population_2020=str(adults),
                      total_population_2020=population["total_population_2020"],
                      registered_pct_of_vap=str(round(registered / adults * 100, 1)),
                      population_geography=POPULATION_GEOGRAPHY,
                      population_year=2020,
                      population_boundary_vintage=2024,
                      registration_year=2026,
                      population_source_url=SOURCE_URL,
                      census_geoid=population["census_geoid"])
        out.append(joined)
    if seen != expected:
        raise ValueError("Alaska registrations must contain districts 1–40")
    return out


def over_total_population(rows):
    return [r for r in rows
            if int(r["registered_voters"]) > int(r["total_population_2020"])]
