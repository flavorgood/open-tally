"""Comparable county registration/adult rows; never extrapolate missing years."""
def comparisons(counties, registrations, estimates, number):
    rows, missing = [], []
    for county in counties:
        key = (county['state'], county['_nkey'])
        registration = registrations.get(key)
        if registration is None:
            continue
        registered = number(registration['registered_voters'])
        if registered is None:
            continue
        estimate = estimates.get(key)
        adults = number(estimate.get('adults_18plus')) if estimate else None
        if (not estimate or estimate.get('estimate_year') != '2025'
                or adults is None or adults <= 0 or not estimate.get('source_url')):
            missing.append(key)
            continue
        old = number(county['voting_age_population_2020'])
        rows.append(dict(state=county['state'], county=county['county_name'],
            slug=county.get('_slug'), registered=registered,
            registration_date=registration['report_date'],
            registration_basis=registration['basis'],
            registration_source=registration['source'],
            adults=adults, population_date='2025-07-01',
            population_basis='Census Bureau resident age 18+ estimate, Vintage 2025',
            population_source_url=estimate['source_url'],
            ratio=registered/adults*100, above=registered>adults,
            adults_2020=old,
            change_since_2020=(adults-old if old is not None else None),
            change_pct_since_2020=((adults-old)/old*100 if old else None)))
    return rows, missing
