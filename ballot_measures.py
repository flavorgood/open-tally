"""Interpret legacy count columns without changing their source records.

A field named ballots_cast is not evidence of a ballot measure. Classifications
follow the source text and recorded flags; incompatible measures never enter
ballot ratios or sums. Dates are retained verbatim, not guessed from election day.
"""
BALLOT_KINDS = {'ballots_cast', 'ballots_counted'}

def state_measure(name, row, flag=None):
    source = row.get('source', '')
    text = source.lower()
    flag = (flag or {}).get('flag_label', '')
    if 'ballots returned' in text or 'ballot return statistics' in text:
        return 'ballots_returned', 'Ballots returned'
    if 'estimated total number of voters' in text or name == 'Minnesota':
        return 'estimated_voters', 'Estimated voters (derived from Governor race)'
    if name == 'New Hampshire' and 'more than' in text:
        return 'lower_bound_voters', 'Reported minimum voters (not an exact total)'
    if flag == 'Top-race votes' or any(x in text for x in ('top-of-ballot contest', 'total votes in highest-turnout', 'votes in the governor race', 'total votes in the u.s. senate race', 'ballots in the governor race')):
        contest = ('U.S. Senate race' if 'senate' in text else
                   'Constitutional Amendment 3' if name == 'Missouri' else
                   'Governor race' if 'governor' in text else 'top race (contest not specified in this record)')
        return 'contest_votes', 'Votes — ' + contest
    if flag == 'Estimate':
        return 'estimated_voters', 'Estimated voters (not a ballot count)'
    if 'ballots counted' in text or 'counted to date' in text:
        return 'ballots_counted', 'Ballots counted (dated preliminary total)'
    return 'ballots_cast', 'Ballots cast (as recorded by source)'

def county_measure(label):
    if label.startswith('Votes'):
        return 'contest_votes'
    if 'returned' in label.lower():
        return 'ballots_returned'
    return 'ballots_cast'

def ballot_value(kind, value):
    return value if kind in BALLOT_KINDS else None
