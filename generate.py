#!/usr/bin/env python3
"""Open Tally — static site generator.
Reads verified CSVs from the data/ directory beside this file and writes a
host-agnostic static site (HTML/CSS, no JS needed for content) to site/
beside this file. Python stdlib only. The map step reads us-atlas TopoJSON
from data/maps/ (see fetch_maps(), which refetches only if a file is missing).
"""
from ballot_measures import state_measure, county_measure, ballot_value, BALLOT_KINDS
import csv, hashlib, io, json, math, os, re, shutil, sys, urllib.request
from html import escape as esc
import alaska_geography as ak_geo
from population_comparison import comparisons as population_comparisons

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "site")
MAPDIR = os.path.join(BASE, "data", "maps")
ASSET_VERSIONS = {}
for _asset in ("navigation.css", "navigation.js"):
    with open(os.path.join(BASE, "assets", _asset), "rb") as _f:
        ASSET_VERSIONS[_asset] = hashlib.sha256(_f.read()).hexdigest()[:12]

GREEN, YELLOW, ORANGE, GREY = "#15803d", "#eab308", "#ea580c", "#9ca3af"
VIOLET = "#7C3AED"
PL_URL = ""  # set in main() from citations.csv

# The standing notice printed under the masthead on every page, in the
# owner's words: the count is still moving, and every figure is only
# what an office published, when it published it.
STANDING_NOTICE = ("The count is still being updated. Every figure here "
                   "comes from the office named beside it, dated when it "
                   "was read. Where no office has published a figure, "
                   "this page shows no data.")

# The Election Day vs today spine lives in the tracker folder: the
# daily updates land there, so every generation first refreshes the
# spine inputs in data/ from it. Where the tracker folder does not
# exist (a host building from this repo alone), the copies in data/
# are the record and nothing is refreshed.
TRACKER = os.path.join(os.path.dirname(BASE), "economic-tracker")
SPINE_FILES = ["RECORD-LOG.md", "BASELINE-2026-11-03.md",
               "state-factors-expanded.csv", "state-claims-weeks.csv",
               "gas-aaa-2026-11-03.csv", "gas-aaa-2026-11-05.csv",
               "gas-aaa-2026-11-07.csv", "gas-aaa-2026-11-08.csv"]

def refresh_spine():
    if not os.path.isdir(TRACKER): return
    for fn in SPINE_FILES:
        src = os.path.join(TRACKER, fn)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(SRC, fn))

STATE_ABBR = {}  # filled below
STATES_ORDER = []  # 51 names, alphabetical as in turnout CSV

# 2026 county ballots files (data/county-ballots-<suffix>.csv) and the
# plain label for what each file's figure is, per the collection log:
# a labeled ballots-cast figure stays "Ballots cast"; votes in one race
# are labeled as that race's votes, never as ballots cast.
BALLOTS26_FILES = {"Alabama": "al", "Colorado": "co", "North Carolina": "nc",
                   "Alaska": "ak", "New Mexico": "nm", "Wyoming": "wy",
                   "Minnesota": "mn", "Maryland": "md", "California": "ca",
                   "Kansas": "ks", "Virginia": "va", "Pennsylvania": "pa",
                   "Florida": "fl", "Arizona": "az", "Ohio": "oh",
                   "Louisiana": "la", "Hawaii": "hi", "Georgia": "ga",
                   "New York": "ny", "West Virginia": "wv",
                   "South Carolina": "sc", "Oklahoma": "ok",
                   "Oregon": "or", "Tennessee": "tn",
                   "Vermont": "vt", "Iowa": "ia",
                   "Indiana": "in", "Missouri": "mo",
                   "North Dakota": "nd",
                   "South Dakota": "sd",
                   "Nebraska": "ne",
                   "Utah": "ut",
                   "Nevada": "nv"}
BALLOTS26_LABEL = {"Alabama": "Ballots cast",
                   "Colorado": "Ballots returned (Nov 5)",
                   "North Carolina": "Votes — U.S. Senate race",
                   "Alaska": "Ballots cast",
                   "New Mexico": "Votes — Governor's race",
                   "Wyoming": "Ballots cast",
                   "Minnesota": "Votes — Governor's race",
                   "Maryland": "Votes — Governor's race",
                   "California": "Votes — Governor's race",
                   "Kansas": "Votes — U.S. Senate race",
                   "Virginia": "Votes — U.S. Senate race",
                   "Pennsylvania": "Votes — Governor's race",
                   "Florida": "Votes — Governor's race",
                   "Arizona": "Votes — Governor's race",
                   "Ohio": "Votes — Governor's race",
                   "Louisiana": "Votes — U.S. Senate race",
                   "Hawaii": "Ballots cast",
                   "Georgia": "Votes — Governor's race",
                   "New York": "Votes — Governor's race",
                   "West Virginia": "Votes — U.S. Senate race",
                   "South Carolina": "Votes — Governor's race",
                   "Oklahoma": "Votes — Governor's race",
                   "Oregon": "Votes — Governor's race",
                   "Tennessee": "Votes — Governor's race",
                   "Vermont": "Votes — Governor's race (towns added up)",
                   "Iowa": "Votes — Governor's race",
                   "Indiana": "Votes — Secretary of State race",
                   "Missouri": "Votes — State Auditor race",
                   "North Dakota": "Votes — Representative in Congress race",
                   "South Dakota": "Votes — Governor's race",
                   "Nebraska": "Votes — Governor's race",
                   "Utah": "Votes — Constitutional Amendment B",
                   "Nevada": "Votes — Governor's race",
                   "Montana": "Ballots cast"}
# combination-quadrants.csv group values in the owner's plain words
QUAD_LABELS = {"high rolls / high ballots": "Big voter list · many ballots",
               "high rolls / low ballots": "Big voter list · few ballots",
               "low rolls / high ballots": "Small voter list · many ballots",
               "low rolls / low ballots": "Small voter list · few ballots",
               "not classifiable": "Not enough published numbers to place"}

def band(pct):
    """Shading band for Registered % of adults."""
    if pct is None: return GREY
    if pct < 90: return GREEN
    if pct <= 100: return YELLOW
    return ORANGE

def chip(pct):
    return f'<span class="chip" style="background:{band(pct)}"></span>'

def vchip():
    return f'<span class="chip" style="background:{VIOLET}"></span>'

def _on(color):
    """Readable text color on a filled band cell."""
    return "#111111" if color == YELLOW else "#ffffff"

def fill_td(inner, color, cls=None):
    """A table cell filled with a band/change color, number on top —
    color carries the meaning, not a small square beside the number."""
    a = f' class="{cls}"' if cls else ""
    return (f'<td{a} style="background:{color};color:{_on(color)}">'
            f'{inner}</td>')

def band_td(inner, pct):
    """Filled cell for a share: green under 90%, yellow 90-100%,
    orange over 100%, grey when there is no figure."""
    return fill_td(inner, GREY if pct is None else band(pct))

def plain_src(text):
    """A data file's source note in plain words at render time: field
    names used as terms are spelled out, and a file-path code in
    parentheses is dropped (the page's citation link still points at
    the issuing body's own file). The data files are unchanged."""
    if not text: return text
    text = text.replace("ballots_cast", "ballots cast")
    text = text.replace("election_date", "election date")
    text = text.replace("update_date", "update date")
    text = re.sub(r"\s*\(voter_stats_\d+\.txt, ENRS/[\d_]+\)", "", text)
    text = re.sub(r"\s*\(voter_stats_\d+\.zip\)", "", text)
    text = re.sub(r"\s*\(voter_stats_\d+\)", "", text)
    text = re.sub(r"voter_stats_\d+(?:\.(?:txt|zip))?", "the voter statistics file", text)
    return text

def fmt_int(v):
    if v is None or v == "": return "—"
    return f"{int(v):,}"

def fmt_pct(v, digits=1):
    if v is None or v == "": return "—"
    return f"{float(v):.{digits}f}%"

def num(v):
    """CSV cell -> int or None. Leaves 'no registration' as None."""
    if v is None: return None
    v = str(v).strip()
    if v == "" or v.lower() == "no registration": return None
    try: return int(v)
    except ValueError:
        try: return int(float(v))
        except ValueError: return None

def fnum(v):
    if v is None: return None
    v = str(v).strip()
    if v == "": return None
    try: return float(v)
    except ValueError: return None

def slugify(name):
    s = name.lower()
    s = s.replace("ñ", "n").replace(".", "").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _name_tokens(name):
    # the Census county file carries one mojibake name — "Do\ufffda Ana"
    # for Doña Ana — where the lost letter is the ñ; restore it so the
    # name keys the same as every other file's spelling. "Saint" and
    # "St." are the same token (Saint Mary's file, St. Mary's County).
    s = name.lower().replace("ñ", "n").replace("\ufffd", "n").replace("&", " and ")
    return ["st" if t == "saint" else t
            for t in re.sub(r"[^a-z0-9]+", " ", s).split()]

def county_key(name):
    """Normalized county join key: (base, kind). Case, punctuation and
    '&' vs 'and' are unified; a trailing County/Parish/Borough/Census
    Area/Municipality marks kind 'county', a trailing City marks kind
    'city' (independent city), and a bare name reads as 'county'."""
    toks = _name_tokens(name)
    kind = "county"
    if len(toks) >= 3 and toks[-2:] == ["census", "area"]:
        toks = toks[:-2]
    elif toks and toks[-1] in ("county", "parish", "borough", "municipality"):
        toks = toks[:-1]
    elif toks and toks[-1] == "city":
        kind = "city"
        toks = toks[:-1]
    return (" ".join(toks), kind)

def county_key_variants(name):
    """Join keys to try for a data-file county name, most specific first.
    A trailing 'City' can be part of a county's own name (Charles City
    County, James City County), so the city reading is followed by the
    county reading of the full name."""
    key = county_key(name)
    yield key
    if key[1] == "city":
        yield (" ".join(_name_tokens(name)), "county")

def resolve_county_rows(rows, counties_by_state, field):
    """Join data-file rows to Census counties on normalized names.
    Returns {(state, county_key): row}; a row joins the first of its
    name variants that names a real county in its state, and a row
    naming no county in the file is dropped, as an unmatched join was.
    A name spelled with its words run together ("Leflore" in
    Oklahoma's file, for Le Flore County) joins the same county: the
    squashed spelling is tried after the exact one, on both sides of
    the join, and the row is filed under the Census county's key."""
    valid = {}
    for c_st, clist in counties_by_state.items():
        for c in clist:
            valid[(c_st, c["_nkey"])] = c["_nkey"]
    for c_st, clist in counties_by_state.items():
        for c in clist:
            sq = (c["_nkey"][0].replace(" ", ""), c["_nkey"][1])
            valid.setdefault((c_st, sq), c["_nkey"])
    out = {}
    for r in rows:
        st = r["state"]
        keys = list(county_key_variants(r[field]))
        keys += [(k[0].replace(" ", ""), k[1]) for k in keys]
        for k in keys:
            hit = valid.get((st, k))
            if hit is not None:
                out[(st, hit)] = r
                break
    return out

MONTHS = ["January","February","March","April","May","June","July",
          "August","September","October","November","December"]
def fmt_date(iso):
    if not iso: return ""
    parts = iso.split("-")
    if len(parts) == 2:
        return f"{MONTHS[int(parts[1])-1]} {parts[0]}"
    y, m, d = parts
    return f"{MONTHS[int(m)-1]} {int(d)}, {y}"

# ---------------------------------------------------------------- data load
def load():
    d = {}
    with open(f"{SRC}/turnout-2026-11-03.csv") as f:
        d["turnout"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/census-registered-2026.csv") as f:
        d["census"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/vap-2020-pl.csv") as f:
        d["vap"] = {r["state"]: num(r["voting_age_population_2020"]) for r in csv.DictReader(f)}
    with open(f"{SRC}/county-vap-2020.csv") as f:
        d["counties"] = list(csv.DictReader(f))
    with open(f"{SRC}/county-registered-all.csv") as f:
        d["county_reg"] = list(csv.DictReader(f))
    with open(f"{SRC}/county-roll-integrity-all.csv") as f:
        d["roll_co_de"] = list(csv.DictReader(f))
    with open(f"{SRC}/ak-district-roll-integrity.csv") as f:
        d["roll_ak_raw"] = list(csv.DictReader(f))
    with open(os.path.join(SRC, ak_geo.POPULATION_FILE)) as f:
        d["roll_ak"] = ak_geo.district_comparisons(
            d["roll_ak_raw"], list(csv.DictReader(f)))
    with open(f"{SRC}/turnout-history-national.csv") as f:
        d["hist_nat"] = list(csv.DictReader(f))
    with open(f"{SRC}/turnout-history-states.csv") as f:
        d["hist_states"] = list(csv.DictReader(f))
    with open(f"{SRC}/PAST-ELECTION-DAYS.md") as f:
        # the past Election Days record: a markdown table (factors x past
        # Election Days, as known on the day) plus its Sources/Caveats lines
        tbl, srcs, cavs = [], "", ""
        for ln in f:
            ln = ln.strip()
            if ln.startswith("|"):
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if cells and set(cells[0]) <= set("-: "):
                    continue
                tbl.append(cells)
            elif ln.startswith("Sources:"):
                srcs = ln[len("Sources:"):].strip()
            elif ln.startswith("Caveats:"):
                cavs = ln[len("Caveats:"):].strip()
        d["past_days"] = (tbl, srcs, cavs)
    with open(f"{SRC}/RECORD-LOG.md") as f:
        d["log_lines"] = [ln.strip() for ln in f if ln.strip()]
    with open(f"{SRC}/citations.csv") as f:
        d["citations"] = {r["source_key"]: r for r in csv.DictReader(f)}
    for c in d["citations"].values():
        c["title"] = plain_src(c["title"])
    with open(f"{SRC}/citation-map.csv") as f:
        cmap = {}
        for r in csv.DictReader(f):
            cmap.setdefault((r["data_file"], r["state"]), []).append(r["source_key"])
        d["citemap"] = cmap
    with open(f"{SRC}/flags.csv") as f:
        d["flag_rows"] = list(csv.DictReader(f))
    d["state_flags"] = {(r["state"], r["field"]): r for r in d["flag_rows"] if r["scope"] == "state"}
    d["flag_rule"] = next(r for r in d["flag_rows"] if r["scope"] == "rule")
    with open(f"{SRC}/county-anomalies.csv") as f:
        d["county_anoms"] = list(csv.DictReader(
            ln for ln in f if not ln.startswith("#")))
    with open(f"{SRC}/anomalies-vs-history.csv") as f:
        d["anoms"] = list(csv.DictReader(f))
    with open(f"{SRC}/registration-splits.csv") as f:
        d["splits"] = {r["state"]: r for r in csv.DictReader(f)}
    # --- wave-3 datasets (folded in 2026-11-07) ---
    with open(f"{SRC}/state-economics-tracker.csv") as f:
        d["econ"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/cvap-state.csv") as f:
        d["cvap_state"] = {r["state"]: r for r in csv.DictReader(f)}
    # Census Bureau population estimates, Vintage 2025 (July 1, 2025):
    # a second, newer denominator set that sits beside the 2020 counts —
    # never blended with them, and never in place of the citizen-adult
    # (CVAP) figures, which are a different basis entirely.
    with open(f"{SRC}/census-estimates-state.csv") as f:
        d["est_state"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/census-estimates-county.csv") as f:
        d["est_county_rows"] = list(csv.DictReader(f))
    with open(f"{SRC}/state-roll-integrity-cvap.csv") as f:
        d["cvap_roll"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/cvap-county.csv") as f:
        d["cvap_county"] = list(csv.DictReader(f))
    with open(f"{SRC}/removals.csv") as f:
        d["removals"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/ballots-detail.csv") as f:
        d["ballots24"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/mail-rejection-reasons.csv") as f:
        rr = {}
        for r in csv.DictReader(f):
            rr.setdefault(r["state"], []).append(r)
        d["rej_reasons"] = rr
    with open(f"{SRC}/rules-facts.csv") as f:
        d["rules"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/polling-places.csv") as f:
        d["polling"] = {r["state"]: r for r in csv.DictReader(f)}
    with open(f"{SRC}/county-history-eavs.csv") as f:
        d["county_hist"] = list(csv.DictReader(f))
    with open(f"{SRC}/county-history-eavs-older.csv") as f:
        d["county_hist_older"] = list(csv.DictReader(f))
    with open(f"{SRC}/not-published.csv") as f:
        d["notpub"] = list(csv.DictReader(f))
    with open(f"{SRC}/unofficial-vs-certified-2024.csv") as f:
        d["uvc"] = list(csv.DictReader(f))
    with open(f"{SRC}/combination-quadrants.csv") as f:
        d["quadrants"] = list(csv.DictReader(f))
    with open(f"{SRC}/county-ballots-mt.csv") as f:
        d["mt_ballots"] = list(csv.DictReader(f))
    # 2026 ballots by county, collected state by state from official
    # files (see the collection log in the tracker folder). Each file's
    # figure is what its source labels it — ballots cast, ballots
    # returned, or votes in the top race; BALLOTS26_LABEL carries the
    # label, never a relabeling. Alaska's file is by House district.
    d["ballots26_rows"] = {}
    for st, suf in BALLOTS26_FILES.items():
        with open(f"{SRC}/county-ballots-{suf}.csv") as f:
            d["ballots26_rows"][st] = list(csv.DictReader(f))
    # 2026 Governor results, one row per state that held a race, from
    # each state's own published results (governor-results-2026.csv;
    # the notes file in the tracker folder carries its flags: AK and
    # KS uncalled, nine states with no official statewide figures yet).
    usps = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona",
            "AR": "Arkansas", "CA": "California", "CO": "Colorado",
            "CT": "Connecticut", "DE": "Delaware",
            "DC": "District of Columbia", "FL": "Florida",
            "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
            "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
            "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
            "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
            "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
            "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
            "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
            "NM": "New Mexico", "NY": "New York",
            "NC": "North Carolina", "ND": "North Dakota",
            "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
            "PA": "Pennsylvania", "RI": "Rhode Island",
            "SC": "South Carolina", "SD": "South Dakota",
            "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
            "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
            "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
    with open(f"{SRC}/governor-results-2026.csv") as f:
        d["gov26"] = {usps[r["state"]]: r for r in csv.DictReader(f)
                      if r["state"] in usps}
    # 2026 U.S. Senate results, one row per state (senate-results-
    # 2026.csv; the notes file in the tracker folder carries the
    # national count, the previous-holder table and its flags: AK
    # uncalled with a leader, MS uncalled with no published total,
    # twelve race states with no verified statewide figures yet,
    # fifteen states with no race; DC elects no Senator and has
    # no row).
    with open(f"{SRC}/senate-results-2026.csv") as f:
        d["sen26"] = {usps[r["state"]]: r for r in csv.DictReader(f)
                      if r["state"] in usps}
    # 2026 U.S. House results (house-results-2026.csv: one row per
    # state — the delegation as seated before Election Day from the
    # Clerk of the House, and the split on the districts verified so
    # far; house-districts-2026.csv: the district list behind it).
    # A state whose districts are not in the record yet carries no
    # split after, and prints at exactly that strength.
    with open(f"{SRC}/house-results-2026.csv") as f:
        d["house"] = {usps[r["state"]]: r for r in csv.DictReader(f)
                      if r["state"] in usps}
    with open(f"{SRC}/house-districts-2026.csv") as f:
        d["house_districts"] = list(csv.DictReader(f))
    # --- Election Day vs today spine (frozen baseline + dated record) ---
    with open(f"{SRC}/BASELINE-2026-11-03.md") as f:
        d["baseline_text"] = f.read()
    with open(f"{SRC}/state-factors-expanded.csv") as f:
        fac = {}
        for r in csv.DictReader(f):
            fac.setdefault(r["state"], {})[r["factor"]] = r
        d["factors"] = fac
    with open(f"{SRC}/state-claims-weeks.csv") as f:
        cl = {}
        for r in csv.DictReader(f):
            cl.setdefault(r["state"], []).append(r)
        for v in cl.values():
            v.sort(key=lambda r: r["week ended"])
        d["claims"] = cl
    def _gas(fn):
        out = {}
        with open(f"{SRC}/{fn}") as f:
            for r in csv.DictReader(f):
                if r["price"] != "NO DATA":
                    out[r["state"]] = fnum(r["price"])
        return out
    d["gas3"] = _gas("gas-aaa-2026-11-03.csv")
    d["gas5"] = _gas("gas-aaa-2026-11-05.csv")
    d["gas7"] = _gas("gas-aaa-2026-11-07.csv")
    d["gas8"] = _gas("gas-aaa-2026-11-08.csv")
    gov, in_spot = {}, False
    for ln in d["baseline_text"].splitlines():
        if ln.startswith("## States that flipped"): in_spot = True; continue
        if in_spot:
            m = re.match(r"- ([A-Z][\w ]*) — (.*?) \(D\), flip R→D", ln)
            if m: gov[m.group(1)] = m.group(2)
            elif ln.startswith("Republicans flipped"): break
    d["gov_flips"] = gov
    fu, in_fb = {}, False
    for ln in d["baseline_text"].splitlines():
        if ln.startswith("## Flipped-state baselines"): in_fb = True; continue
        if in_fb:
            m = re.match(r"- ([A-Z][\w ]*): ([\d.]+)%", ln)
            if m: fu[m.group(1)] = m.group(2)
            elif fu and ln.startswith("## "): break
    d["flip_unemp"] = fu
    return d

def build_states(d):
    """Joined state records."""
    states = {}
    for name, t in d["turnout"].items():
        c = d["census"][name]
        vap = d["vap"][name]
        reg = num(t["registered_voters"])
        published_count = num(t["ballots_cast"])
        kind, measure_label = state_measure(name, t, d["state_flags"].get((name, "ballots_cast")))
        bal = ballot_value(kind, published_count)
        est = d["est_state"].get(name)
        est_adults = num(est["adults_18plus"]) if est else None
        states[name] = {
            "name": name, "slug": slugify(name),
            "registered": reg, "ballots": bal,
            "published_count": published_count, "count_kind": kind, "count_label": measure_label,
            "turnout_pct": (bal / reg * 100 if bal is not None and reg else None),
            "status": t["status"], "source": plain_src(t["source"]),
            "vap": vap,
            "census_pop": num(c["census_2020"]),
            "pct_census_registered": fnum(c["pct_census_registered"]),
            "pct_census_ballots": (fnum(c["pct_census_ballots"]) if bal is not None else None),
            "reg_pct_adults": (round(reg / vap * 100, 1) if reg and vap else None),
            "bal_pct_adults": (round(bal / vap * 100, 1) if bal and vap else None),
            "est_adults": est_adults,
            "est_pop": (num(est["total_population"]) if est else None),
            "est_src": (est["source"] if est else ""),
            "est_url": (est["source_url"] if est else ""),
            "reg_pct_est": (reg / est_adults * 100 if reg is not None and est_adults else None),
            "bal_pct_est": (bal / est_adults * 100 if bal is not None and est_adults else None),
        }
    return states

# ---------------------------------------------------------------- maps
def fetch_maps():
    os.makedirs(MAPDIR, exist_ok=True)
    for fn in ("states-10m.json", "counties-10m.json"):
        p = os.path.join(MAPDIR, fn)
        if not os.path.exists(p):
            url = f"https://cdn.jsdelivr.net/npm/us-atlas@3/{fn}"
            urllib.request.urlretrieve(url, p)

def load_topo(path, obj):
    t = json.load(open(path))
    sc, tr = t["transform"]["scale"], t["transform"]["translate"]
    arcs = []
    for arc in t["arcs"]:
        pts, x, y = [], 0, 0
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)
    geoms = {g["id"]: g for g in t["objects"][obj]["geometries"]}
    return arcs, geoms

def _arc(arcs, idx):
    return arcs[idx] if idx >= 0 else arcs[~idx][::-1]

def _ring(arcs, idxs):
    pts = []
    for i, idx in enumerate(idxs):
        a = _arc(arcs, idx)
        pts.extend(a if i == 0 else a[1:])
    return pts

def geom_polys(geom, arcs):
    """Geometry -> list of polygons; polygon = list of rings of (lon, lat)."""
    if geom["type"] == "Polygon":
        return [[_ring(arcs, r) for r in geom["arcs"]]]
    if geom["type"] == "MultiPolygon":
        return [[_ring(arcs, r) for r in poly] for poly in geom["arcs"]]
    return []

_COUNTY_POLYS = None

def county_polys():
    """{county fips: (name, polys)} for every county the site draws:
    the us-atlas counties TopoJSON, plus the two Alaska census areas
    the Census county file carries that the TopoJSON's vintage
    predates — Chugach (02063) and Copper River (02066), split out
    of Valdez-Cordova in 2019. Their boundaries are the Census
    Bureau's own (TIGERweb, Census 2020 vintage), kept in
    data/maps/ak-successors.json. Valdez-Cordova (02261) is not a
    current county — the Census file carries no such county — and
    its retired outline is never drawn; its ground is the two
    successor census areas above."""
    global _COUNTY_POLYS
    if _COUNTY_POLYS is not None: return _COUNTY_POLYS
    arcs, geoms = load_topo(f"{MAPDIR}/counties-10m.json", "counties")
    out = {fips: (g["properties"]["name"], geom_polys(g, arcs))
           for fips, g in geoms.items()}
    p = os.path.join(MAPDIR, "ak-successors.json")
    if os.path.exists(p):
        for fips, rec in json.load(open(p)).items():
            polys = [[[(float(x), float(y)) for x, y in ring]
                      for ring in poly] for poly in rec["polys"]]
            out[fips] = (rec["name"], polys)
    _COUNTY_POLYS = out
    return out

def albers(lon, lat, lon0, lat0, p1, p2):
    """Spherical Albers equal-area conic (unit sphere). y grows north."""
    la, lo = math.radians(lat), math.radians(lon)
    a0, a1, a2 = math.radians(lat0), math.radians(p1), math.radians(p2)
    n = (math.sin(a1) + math.sin(a2)) / 2.0
    C = math.cos(a1) ** 2 + 2 * n * math.sin(a1)
    rho0 = math.sqrt(max(C - 2 * n * math.sin(a0), 0.0)) / n
    rho = math.sqrt(max(C - 2 * n * math.sin(la), 0.0)) / n
    th = n * (lo - math.radians(lon0))
    return (rho * math.sin(th), rho0 - rho * math.cos(th))

CONUS = dict(lon0=-96.0, lat0=37.5, p1=29.5, p2=45.5)
AKP   = dict(lon0=-154.0, lat0=50.0, p1=55.0, p2=65.0)
HIP   = dict(lon0=-157.0, lat0=13.0, p1=8.0, p2=18.0)

def region_of(lon, lat):
    if lat >= 50.5 and (lon <= -129.5 or lon >= 168.0): return "AK"
    if 18.5 <= lat <= 22.5 and -161.5 <= lon <= -154.5: return "HI"
    return "CONUS"

def project_polys(polys, proj):
    return [[[albers(lon, lat, **proj) for lon, lat in ring] for ring in poly] for poly in polys]

def _fit_params(polys_list, width, height, pad=4):
    """The fit transform for a set of projected polys: (minx, maxy,
    scale, ox, oy). Kept separate from applying it so a second set of
    shapes (the counties under the states) can ride the exact same
    transform the states were fitted with."""
    xs = [p[0] for polys in polys_list for poly in polys for ring in poly for p in ring]
    ys = [p[1] for polys in polys_list for poly in polys for ring in poly for p in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    bw, bh = maxx - minx, maxy - miny
    s = min((width - 2 * pad) / bw, (height - 2 * pad) / bh)
    ox = pad + ((width - 2 * pad) - bw * s) / 2.0
    oy = pad + ((height - 2 * pad) - bh * s) / 2.0
    return (minx, maxy, s, ox, oy)

def _apply_fit(polys, prm):
    minx, maxy, s, ox, oy = prm
    return [[[(ox + (x - minx) * s, oy + (maxy - y) * s) for x, y in ring]
             for ring in poly] for poly in polys]

def fit(polys_list, width, height, pad=4):
    """Fit projected polys into width x height. Returns (mapped_polys, scale)."""
    prm = _fit_params(polys_list, width, height, pad)
    return [_apply_fit(polys, prm) for polys in polys_list], prm[2]

def simplify(ring, eps):
    """Douglas-Peucker on a projected (screen-space) ring."""
    if len(ring) < 4 or eps <= 0: return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = ring[a]; bx, by = ring[b]
        dx, dy = bx - ax, by - ay
        denom = math.hypot(dx, dy) or 1e-12
        worst, wi = -1.0, -1
        for i in range(a + 1, b):
            px, py = ring[i]
            dist = abs(dy * px - dx * py + bx * ay - by * ax) / denom
            if dist > worst: worst, wi = dist, i
        if worst > eps and wi > 0:
            keep[wi] = True
            stack.append((a, wi)); stack.append((wi, b))
    pts = [p for p, k in zip(ring, keep) if k]
    return pts if len(pts) >= 3 else ring

def polys_to_path(polys, eps=0.7):
    parts = []
    for poly in polys:
        for ring in poly:
            r = simplify(ring, eps)
            if len(r) < 3: continue
            d = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r) + "Z"
            parts.append(d)
    return "".join(parts)

def national_map(state_fips, fills, links=None, county_fills=None,
                 county_names=None, state_fill_opacity=None,
                 county_strong=None, collect=None):
    """Composite Albers USA SVG. state_fips: {fips: state name}; fills: {name: color};
    links: optional {name: href} — each state path becomes a link.
    With county_fills ({county fips: color}), the drawing is the
    counties: every county in the 51 jurisdictions is drawn, shaded
    from county_fills (grey where a county carries no figure), and
    the state paths draw over them as outlines in the state colors —
    the state fill is transparent, so the counties show through,
    the state's border carries its color, and the state path still
    takes the tap that opens the state's panel."""
    arcs, geoms = load_topo(f"{MAPDIR}/states-10m.json", "states")
    W, H = 960, 600
    by_region = {"CONUS": [], "AK": [], "HI": []}
    meta = []  # (region idx placeholder, name)
    layout = {}  # state name -> (region, projection)
    for fips, name in state_fips.items():
        g = geoms.get(fips)
        if not g: continue
        polys = geom_polys(g, arcs)
        # region from centroid of first ring of first polygon
        ring0 = polys[0][0]
        clon = sum(p[0] for p in ring0) / len(ring0)
        clat = sum(p[1] for p in ring0) / len(ring0)
        reg = region_of(clon, clat)
        proj = {"CONUS": CONUS, "AK": AKP, "HI": HIP}[reg]
        layout[name] = (reg, proj)
        pp = project_polys(polys, proj)
        # AK polygons crossing the antimeridian: re-project wrapped longitudes
        if reg == "AK":
            wrapped = []
            for poly in polys:
                wpoly = []
                for ring in poly:
                    wr = []
                    for lon, lat in ring:
                        lo = lon - 360 if lon > 0 else lon
                        wr.append(albers(lo, lat, **AKP))
                    wpoly.append(wr)
                wrapped.append(wpoly)
            pp = wrapped
        by_region[reg].append(pp)
        meta.append((reg, len(by_region[reg]) - 1, name))
    flat = by_region["CONUS"] + by_region["AK"] + by_region["HI"]
    prm = _fit_params(flat, W, H, pad=6)
    mapped = [_apply_fit(polys, prm) for polys in flat]
    idx = {"CONUS": 0, "AK": len(by_region["CONUS"]), "HI": len(by_region["CONUS"]) + len(by_region["AK"])}
    # rescale AK by 0.35 and HI by 1.0 around their own bboxes, then place:
    paths = {}
    rescale_prm = {}  # state name -> its placement transform, for its counties
    for reg, i, name in meta:
        polys = mapped[idx[reg] + i]
        if reg == "AK":
            rp = _rescale_params(polys, 0.35, W, H, anchor="bl")
            rescale_prm[name] = rp
            polys = _apply_rescale(polys, rp)
        elif reg == "HI":
            rp = _rescale_params(polys, 1.0, W, H, anchor="hi")
            rescale_prm[name] = rp
            polys = _apply_rescale(polys, rp)
        paths[name] = polys_to_path(polys)
    svg = [f'<svg viewBox="0 0 {W} {H}" class="map" role="img" aria-label="United States">']
    if county_fills is not None:
        # the counties ride the states' own transforms: each county
        # is projected with its state's projection, fitted with the
        # states' fit, and placed with its state's placement — so a
        # county lands exactly inside its state's outline
        # the drawn counties are exactly the site's counties — the
        # keys of county_fills, which the caller builds from the
        # Census county file. A geometry unit the Census file does
        # not carry (the retired Valdez-Cordova) is never drawn.
        by_state = {}
        allp = county_polys()
        for cfips in county_fills:
            rec = allp.get(cfips)
            sname = state_fips.get(cfips[:2])
            if rec is not None and sname is not None and sname in layout:
                by_state.setdefault(sname, []).append((cfips, rec[0], rec[1]))
        cpaths = {}
        for sname, clist in by_state.items():
            reg, proj = layout[sname]
            for cfips, cname, cpolys in clist:
                if reg == "AK":
                    pp = [[ [albers(lon - 360 if lon > 0 else lon, lat, **AKP)
                             for lon, lat in ring]
                            for ring in poly] for poly in cpolys]
                else:
                    pp = project_polys(cpolys, proj)
                mp = _apply_fit(pp, prm)
                if sname in rescale_prm:
                    mp = _apply_rescale(mp, rescale_prm[sname])
                disp = (county_names or {}).get(cfips, cname)
                cpaths[cfips] = (f'<path class="cb" data-f="{cfips}" '
                           f'd="{polys_to_path(mp)}" '
                           f'fill="{county_fills.get(cfips, GREY)}" '
                           f'stroke="#ffffff" stroke-opacity="0.5" '
                           f'stroke-width="0.6">'
                           f'<title>{esc(disp)}, {esc(sname)}</title></path>')
                svg.append(cpaths[cfips])
                if collect is not None: collect.append(cfips)
        if state_fill_opacity is not None:
            # the state layer over the counties: each state's own
            # shading as a fill the county texture shows through,
            # then the standout counties again at full strength
            for name, dpath in paths.items():
                svg.append(f'<path d="{dpath}" fill="{fills.get(name, GREY)}" '
                           f'fill-opacity="{state_fill_opacity}">'
                           f'<title>{esc(name)}</title></path>')
            svg.append('<g id="cstrong">')
            for cfips in (county_strong or ()):
                if cfips in cpaths:
                    svg.append(cpaths[cfips].replace(
                        'class="cb"', 'class="cs"'))
            svg.append('</g>')
    for name, d in paths.items():
        if county_fills is not None:
            p = (f'<path class="sout" d="{d}" fill="#000000" fill-opacity="0" '
                 f'style="stroke:{fills.get(name, GREY)}">'
                 f'<title>{esc(name)}</title></path>')
        else:
            p = f'<path d="{d}" fill="{fills.get(name, GREY)}"><title>{esc(name)}</title></path>'
        if links and name in links:
            p = f'<a href="{esc(links[name])}">{p}</a>'
        svg.append(p)
    svg.append("</svg>")
    return "".join(svg)

def _rescale_params(polys, factor, W, H, anchor):
    """The rescale_place transform for a set of polys, as parameters:
    (cx, cy, factor, tx, ty) — scale about the bbox center, then
    translate so the scaled bbox lands on the anchor box. Separate
    from applying it so shapes that tile the same ground (a state's
    counties under the state) can ride the state's own transform."""
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    sminx, smaxx = cx + (minx - cx) * factor, cx + (maxx - cx) * factor
    sminy, smaxy = cy + (miny - cy) * factor, cy + (maxy - cy) * factor
    if anchor == "bl":    tx, ty = 4 - sminx, (H - 2) - smaxy
    elif anchor == "hi":  tx, ty = 300 - sminx, (H - 4) - smaxy
    else:                 tx, ty = 0, 0
    return (cx, cy, factor, tx, ty)

def _apply_rescale(polys, prm):
    cx, cy, factor, tx, ty = prm
    return [[[(cx + (x - cx) * factor + tx, cy + (y - cy) * factor + ty)
              for x, y in ring] for ring in poly] for poly in polys]

def rescale_place(polys, factor, W, H, anchor):
    """Shrink polys by factor about their bbox center, then move bbox to an anchor box."""
    return _apply_rescale(polys, _rescale_params(polys, factor, W, H, anchor))

def state_map(state_name, county_fips_names, fills, links=None):
    """Single-state county map, fitted Albers. county_fips_names: {fips: display name};
    links: optional {display name: href} — each county path becomes a link."""
    allp = county_polys()
    raw, names = [], []
    for fips, nm in county_fips_names.items():
        rec = allp.get(fips)
        if not rec: continue
        raw.append(rec[1]); names.append(nm)
    if not raw: return ""
    lons = [p[0] for polys in raw for poly in polys for ring in poly for p in ring]
    lats = [p[1] for polys in raw for poly in polys for ring in poly for p in ring]
    lon0 = (min(lons) + max(lons)) / 2; lat0 = (min(lats) + max(lats)) / 2
    p1 = lat0 - max((max(lats) - min(lats)) / 4, 1.0)
    p2 = lat0 + max((max(lats) - min(lats)) / 4, 1.0)
    proj = dict(lon0=lon0, lat0=lat0, p1=p1, p2=p2)
    projected = [project_polys(polys, proj) for polys in raw]
    W, H = 960, 620
    mapped, s = fit(projected, W, H, pad=6)
    svg = [f'<svg viewBox="0 0 {W} {H}" class="map" role="img" aria-label="{esc(state_name)}">']
    for nm, polys in zip(names, mapped):
        p = f'<path d="{polys_to_path(polys)}" fill="{fills.get(nm, GREY)}"><title>{esc(nm)}</title></path>'
        if links and nm in links:
            p = f'<a href="{esc(links[nm])}">{p}</a>'
        svg.append(p)
    svg.append("</svg>")
    return "".join(svg)

def state_outline_map(state_name, fill):
    """One state's outline from the states TopoJSON, in a single fill,
    fitted on its own Albers projection (same treatment as state_map)."""
    arcs, geoms = load_topo(f"{MAPDIR}/states-10m.json", "states")
    fips = next((f for f, n in FIPS_STATE.items() if n == state_name), None)
    g = geoms.get(fips) if fips else None
    if not g: return ""
    polys = geom_polys(g, arcs)
    if state_name == "Alaska":
        # antimeridian crossing: wrap longitudes before projecting
        polys = [[[(lon - 360 if lon > 0 else lon, lat) for lon, lat in ring]
                  for ring in poly] for poly in polys]
    lons = [p[0] for poly in polys for ring in poly for p in ring]
    lats = [p[1] for poly in polys for ring in poly for p in ring]
    if not lons: return ""
    lon0 = (min(lons) + max(lons)) / 2; lat0 = (min(lats) + max(lats)) / 2
    p1 = lat0 - max((max(lats) - min(lats)) / 4, 1.0)
    p2 = lat0 + max((max(lats) - min(lats)) / 4, 1.0)
    proj = dict(lon0=lon0, lat0=lat0, p1=p1, p2=p2)
    mapped, _s = fit([project_polys(polys, proj)], 960, 620, pad=6)
    return (f'<svg viewBox="0 0 960 620" class="map" role="img" '
            f'aria-label="{esc(state_name)} outline">'
            f'<path d="{polys_to_path(mapped[0])}" fill="{fill}">'
            f'<title>{esc(state_name)}</title></path></svg>')

# ---------------------------------------------------------------- rendering
CSS = """
:root{
  --bg:#ffffff; --panel:#ffffff; --ink:#111111; --ink2:#5f5f5f; --line:#e4e4e0; --line2:#c9c9c4;
  --hover:#f7f7f5;
  --serif:"Playfair Display",Georgia,"Times New Roman",Times,serif;
  --bodyserif:Georgia,"Times New Roman",Times,serif;
  --sans:Inter,"Helvetica Neue",Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0 auto;max-width:1100px;padding:0 22px 56px;background:var(--bg);color:var(--ink);
  font-family:var(--sans);font-size:15.5px;line-height:1.5;
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}
.site-head{padding:26px 0 12px;border-bottom:4px double var(--ink)}
.wordmark{font-family:var(--serif);font-size:clamp(42px,6.5vw,64px);font-weight:800;
  letter-spacing:-.015em;line-height:1.04;color:var(--ink)}
.wordmark .accent{color:var(--ink)}
.tagline{font-family:var(--bodyserif);font-style:italic;font-size:20px;line-height:1.55;
  color:var(--ink);max-width:42em;margin:16px 0 0}
.mainnav{display:flex;gap:26px;margin-top:16px;font-size:12.5px;font-weight:700;
  letter-spacing:.15em;text-transform:uppercase}
.mainnav a{color:var(--ink2)}
.mainnav a:hover{color:var(--ink);text-decoration:underline;text-underline-offset:5px}
.crumb{font-size:12px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);margin:20px 0 0}
.crumb a{color:var(--ink2)}
h1{font-family:var(--serif);font-size:34px;font-weight:800;letter-spacing:-.01em;
  line-height:1.1;margin:14px 0 6px}
h2{font-size:13px;font-weight:700;letter-spacing:.17em;text-transform:uppercase;
  margin:52px 0 18px;color:var(--ink)}
h3{font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink2);margin:26px 0 10px}
.edsub{font-size:12px;font-weight:600;letter-spacing:.15em;text-transform:uppercase;
  color:var(--ink2);margin:-6px 0 14px}
.cards{display:flex;flex-wrap:wrap;border-top:2px solid var(--ink);
  border-bottom:1px solid var(--line2);padding:20px 0 18px;margin:14px 0 4px}
.card{flex:1 1 240px;padding:2px 20px;border-left:1px solid var(--line);min-width:0}
.card:first-child{padding-left:0;border-left:0}
.card .v{font-size:30px;font-weight:800;letter-spacing:-.025em;line-height:1.1;margin:5px 0 2px}
.card .k{font-size:11px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);margin-top:5px}
.card .sub{font-size:13.5px;color:var(--ink2);margin-top:6px;line-height:1.5}
.govline{border-top:2px solid var(--ink);padding:16px 0 2px;font-size:16.5px;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:14.5px;margin:14px 0 18px}
th{font-size:11px;font-weight:600;letter-spacing:.11em;text-transform:uppercase;
  color:var(--ink2);text-align:right;padding:2px 10px 9px;border-bottom:2px solid var(--ink)}
th.l,td.l{text-align:left}
td{border-bottom:1px solid var(--line);text-align:right;padding:8px 10px}
td.l{white-space:normal}
tr.hl td{font-weight:700}
.chip{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:7px}
.map{width:100%;height:auto;display:block;margin:14px 0}
.map path{stroke:var(--panel);stroke-width:1.1}
.map path.sout{stroke-width:1.8}
.legend{font-size:13px;color:var(--ink2);margin:10px 0 16px;line-height:1.7}
.small{font-size:13.5px;color:var(--ink2);line-height:1.6}
.src{font-size:13px;color:var(--ink2);margin:6px 0 14px;line-height:1.55}
.notice{font-size:13.5px;color:var(--ink2);line-height:1.55;
  padding:10px 0;border-bottom:1px solid var(--line);margin:0}
.log{font-size:15px;line-height:1.55}
.log div{padding:13px 0;border-top:1px solid var(--line)}
.log div:first-child{border-top:0;padding-top:2px}
dl.defs{font-size:15.5px;line-height:1.6}
dl.defs dt{font-weight:700;margin-top:14px}
dl.defs dd{margin:2px 0 0 0;color:var(--ink2)}
.footer{border-top:1px solid var(--ink);margin-top:64px;padding-top:15px;font-size:13px;
  color:var(--ink2);line-height:1.6;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
a.cite{color:inherit;text-decoration:underline dotted;text-underline-offset:2px}
.flag{background:#7C3AED;color:#fff;padding:1px 6px;border-radius:3px;font-weight:700;white-space:nowrap}
.flag a.cite{color:#fff}
.flaglab{color:#7C3AED;font-weight:700;font-size:12.5px;margin-left:6px;white-space:nowrap}
.flags div{font-size:14.5px;margin:6px 0;line-height:1.55}
.adds{font-size:15.5px;line-height:1.55}
.adds div{padding:10px 0;border-top:1px solid var(--line)}
.adds div:first-child{border-top:0;padding-top:0}
.adds a,td.l a{font-weight:600}
.plainline{border-top:2px solid var(--ink);padding:14px 0 2px;font-size:16.5px;
  font-weight:600;margin:14px 0 4px}
.tline{font-size:14.5px;color:var(--ink);line-height:1.55;margin:18px 0 -4px}
.modmap{min-height:0;justify-content:flex-start;padding-top:24px}
.pblock{min-width:0}
svg.map{max-width:100%}
@media (max-width:760px){
.frontmap{margin-left:-16px;margin-right:-16px}
.frontmap .map{margin-top:6px}
}
@media (max-width:760px){
body{padding:0 16px 48px}
.tagline{font-size:18px}
h1{font-size:29px}
h2{margin-top:46px}
.mainnav{flex-wrap:wrap;gap:10px 22px}
.cards{flex-direction:column}
.card{flex:1 1 auto;padding:12px 0;border-left:0;border-top:1px solid var(--line)}
.card:first-child{padding-top:2px;border-top:0}
.card .v{font-size:25px}
table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;
  max-width:100%;border:1px solid var(--line2)}
td.l{white-space:normal}
th:first-child,td:first-child{position:sticky;left:0;background:var(--bg);
  min-width:104px;box-shadow:10px 0 12px -10px rgba(17,17,17,.35)}
.govline,.plainline{font-size:15.5px}
.footer{flex-direction:column;gap:2px}
.jumpbar{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
.jumpbar::-webkit-scrollbar{display:none}
.jumpbar a{white-space:nowrap;padding:12px 0}
.mt-tabs{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
.mt-tabs::-webkit-scrollbar{display:none}
.mt-tabs label{white-space:nowrap}
}
.maptoggle{position:relative}
.mt-in{position:absolute;opacity:0;pointer-events:none}
.mt-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px}
.mt-tabs label{font-size:12px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);border:1px solid var(--line2);padding:6px 14px;cursor:pointer}
#frontmap-list:checked~.mt-tabs label[for=frontmap-list],
#frontmap-base:checked~.mt-tabs label[for=frontmap-base],
#frontmap-cur:checked~.mt-tabs label[for=frontmap-cur]{color:var(--ink);border-color:var(--ink)}
.mt-pane{display:none}
#frontmap-list:checked~.mt-list{display:block}
#frontmap-base:checked~.mt-base{display:block}
#frontmap-cur:checked~.mt-cur{display:block}
.jumpbar{position:sticky;top:0;z-index:10;background:var(--bg);display:flex;flex-wrap:wrap;
  gap:6px 20px;padding:9px 0;border-bottom:1px solid var(--line2);
  font-size:11.5px;font-weight:700;letter-spacing:.13em;text-transform:uppercase}
.jumpbar a{color:var(--ink2)}
.jumpbar a:hover{color:var(--ink);text-decoration:underline;text-underline-offset:4px}
h2,h3{scroll-margin-top:52px}
.flaglabw{color:#fff;font-weight:700;font-size:12.5px;margin-left:6px;white-space:nowrap}
.bigflag{background:#7C3AED;color:#fff;font-weight:700;font-size:16.5px;
  padding:12px 14px;margin:14px 0 4px;line-height:1.45}
.map a{cursor:pointer}
.map a:hover path{opacity:.8}
.statelist{columns:3;column-gap:28px;margin:14px 0 18px}
.statelist a{display:block;padding:5px 0;border-bottom:1px solid var(--line);
  font-weight:600;break-inside:avoid}
@media (max-width:760px){.statelist{columns:2}}
html{scroll-snap-type:y proximity;scroll-padding-top:56px}
.mod{min-height:100svh;scroll-snap-align:start;display:flex;flex-direction:column;
  justify-content:center;padding:8px 0 calc(84px + env(safe-area-inset-bottom))}
.footer{margin-bottom:96px}
.botnav{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--bg);
  border-top:2px solid var(--ink)}
.botnav-in{max-width:1100px;margin:0 auto;display:flex;justify-content:space-between;
  gap:14px;padding:6px 22px calc(6px + env(safe-area-inset-bottom))}
.botnav a{font-size:12px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);padding:9px 0}
.botnav a:hover{color:var(--ink);text-decoration:underline;text-underline-offset:4px}
.yrsw{position:relative}
.yr-in{position:absolute;opacity:0;pointer-events:none}
.yr-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px}
.yr-tabs label{font-size:12px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);border:1px solid var(--line2);padding:6px 14px;cursor:pointer}
#yr2026:checked~.yr-tabs label[for=yr2026],
#yr2024:checked~.yr-tabs label[for=yr2024],
#yr2022:checked~.yr-tabs label[for=yr2022],
#yr2020:checked~.yr-tabs label[for=yr2020],
#yr2018:checked~.yr-tabs label[for=yr2018],
#yr2016:checked~.yr-tabs label[for=yr2016]{color:var(--ink);border-color:var(--ink)}
.yr-pane{display:none}
#yr2026:checked~.yp2026{display:block}
#yr2024:checked~.yp2024{display:block}
#yr2022:checked~.yp2022{display:block}
#yr2020:checked~.yp2020{display:block}
#yr2018:checked~.yp2018{display:block}
#yr2016:checked~.yp2016{display:block}
.yrbar{position:fixed;left:0;right:0;bottom:51px;z-index:29;background:var(--bg);
  border-top:1px solid var(--line2)}
.yrbar-in{max-width:1100px;margin:0 auto;display:flex;align-items:center;
  gap:8px;padding:7px 22px;overflow-x:auto;scrollbar-width:none}
.yrbar-in::-webkit-scrollbar{display:none}
.yrbar .yrlab,.fyr-tabs .yrlab{font-size:11px;font-weight:700;
  letter-spacing:.13em;text-transform:uppercase;color:var(--ink2);
  white-space:nowrap}
.yrbar label{font-size:12px;font-weight:700;letter-spacing:.08em;
  color:var(--ink2);border:1px solid var(--line2);padding:5px 12px;
  cursor:pointer;white-space:nowrap}
body:has(#yr2026:checked) .yrbar label[for=yr2026],
body:has(#yr2024:checked) .yrbar label[for=yr2024],
body:has(#yr2022:checked) .yrbar label[for=yr2022],
body:has(#yr2020:checked) .yrbar label[for=yr2020],
body:has(#yr2018:checked) .yrbar label[for=yr2018],
body:has(#yr2016:checked) .yrbar label[for=yr2016],
body:has(#fyr2026:checked) .yrbar label[for=fyr2026],
body:has(#fyr2024:checked) .yrbar label[for=fyr2024],
body:has(#fyr2022:checked) .yrbar label[for=fyr2022],
body:has(#fyr2020:checked) .yrbar label[for=fyr2020],
body:has(#fyr2018:checked) .yrbar label[for=fyr2018],
body:has(#fyr2016:checked) .yrbar label[for=fyr2016],
body:has(#fyr2026:checked) .fyr-tabs label[for=fyr2026],
body:has(#fyr2024:checked) .fyr-tabs label[for=fyr2024],
body:has(#fyr2022:checked) .fyr-tabs label[for=fyr2022],
body:has(#fyr2020:checked) .fyr-tabs label[for=fyr2020],
body:has(#fyr2018:checked) .fyr-tabs label[for=fyr2018],
body:has(#fyr2016:checked) .fyr-tabs label[for=fyr2016]
{color:var(--ink);border-color:var(--ink)}
body.yrb .mod{padding-bottom:calc(136px + env(safe-area-inset-bottom))}
body.yrb .footer{margin-bottom:148px}
@media (max-width:760px){
.yrbar-in{padding:7px 16px;gap:5px}
.yrbar label{padding:5px 8px;font-size:11px}
.yrbar .yrlab{font-size:10px}
.botnav-in{padding:6px 16px calc(6px + env(safe-area-inset-bottom));gap:8px}
.botnav a{font-size:11px;letter-spacing:.1em}
.yr-tabs{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
.yr-tabs::-webkit-scrollbar{display:none}
.yr-tabs label{white-space:nowrap}
}
.panelcol{border-top:2px solid var(--ink);padding-top:10px;margin-top:16px}
.spanel h3{font-family:var(--serif);font-size:25px;font-weight:800;
  letter-spacing:-.01em;text-transform:none;color:var(--ink);margin:2px 0 8px}
.spanel .govline{margin:8px 0}
.mapsum{border-top:2px solid var(--ink);padding-top:10px;margin-top:16px}
@media (min-width:1024px){
.mapflex{display:flex;gap:30px;align-items:flex-start}
.mapcol{flex:1.6 1 0;min-width:0}
.frontmap .mapcol{flex:2.3 1 0}
.panelcol{flex:1 1 0;min-width:260px;margin-top:0}
.mapsum{flex:1 1 0;min-width:260px;margin-top:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));
  gap:8px 26px}
.statelist{columns:5}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px 38px;align-items:start}
.pgrid .wide{grid-column:1/-1}
.yrsw{display:flex;gap:30px;align-items:flex-start}
.yr-tabs{flex-direction:column;margin:12px 0}
.yr-pane{flex:1 1 0;min-width:0}
.paneflex{display:flex;gap:30px;align-items:flex-start}
.paneflex .panecol{flex:1 1 0;min-width:0}
}
"""

def section_index(body, collapsible=False):
    """Add stable, static links to every top-level section of long reference pages."""
    links = []
    used = set(re.findall(r'\bid=["\']([^"\']+)', body))
    def heading(match):
        attrs, label = match.groups()
        existing = re.search(r'\bid=["\']([^"\']+)', attrs)
        if existing:
            anchor = existing.group(1)
        else:
            base = slugify(re.sub(r"<[^>]+>", "", label)) or "section"
            anchor, i = base, 2
            while anchor in used:
                anchor, i = f"{base}-{i}", i + 1
            used.add(anchor)
            attrs += f' id="{anchor}"'
        links.append(f'<li><a href="#{esc(anchor)}">{label}</a></li>')
        return f'<h2{attrs}>{label}</h2>'
    body = re.sub(r"<h2([^>]*)>(.*?)</h2>", heading, body, flags=re.S)
    if collapsible:
        chunks = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.S)
        rebuilt = [chunks[0]]
        for i in range(1, len(chunks), 2):
            label = re.sub(r"<[^>]+>", "", chunks[i])
            rebuilt.append('<details class="supporting-record reference-section"><summary>' + label + '</summary>' + chunks[i] + chunks[i + 1] + '</details>')
        body = "".join(rebuilt)
    index = ('<nav class="section-index" aria-label="On this page">'
             '<h2>On this page</h2><ul>' + "".join(links) + '</ul></nav>')
    return re.sub(r"(</h1>)", lambda m: m.group(1) + index, body, count=1)


MEASURE_NOTE = ('<p class="measure-note">Current comparisons use Census Bureau '
                'resident age-18+ estimates for July 1, 2025 where the geography '
                'matches. These include population growth and decline through '
                'that date, not an extrapolated 2026 count or a count of eligible '
                'voters. Historical 2020 comparisons remain labeled separately. '
                'Registration dates and active/inactive coverage vary; see the '
                'source beside each record.</p>')


def page(title, body, depth=0, src_html=None, jump=None, yearbar=None):
    root = "../" * depth
    if src_html is None:
        src_html = (f'Sources: <a class="cite" href="{esc(PL_URL)}">U.S. Census Bureau</a>'
                    ' · State election offices')
    active = ("states" if depth >= 2 or title == "States & Counties" else
              "rankings" if title == "Compare states" else
              "data" if title in ("Data & Sources", "Definitions") else "overview")
    destinations = [("overview", "index.html", "Overview"),
                    ("states", "states/index.html", "States & Counties"),
                    ("rankings", "rankings/index.html", "Compare"),
                    ("data", "data/index.html", "Data & Sources")]
    nav = "".join(f'<a href="{root}{path}"' +
                  (' aria-current="page"' if key == active else '') +
                  f'><span class="nav-symbol" aria-hidden="true">{dict(overview="◫", states="⌖", rankings="≡", data="▤")[key]}</span><span>{label}</span></a>' for key, path, label in destinations)
    jump_html = ""
    if jump:
        jump_html = ('<nav class="jumpbar" aria-label="On this page"><span class="jumpbar-label">On this page</span>' + "".join(
            f'<a href="#{esc(i)}">{esc(l)}</a>' for i, l in jump) + "</nav>\n")
    yrbar_html = ""
    bodycls = ""
    if yearbar:
        prefix, years = yearbar
        year_label = "Map year" if prefix == "fyr" else "Count year"
        items = "".join(f'<label for="{prefix}{y}">{y}</label>'
                        for y in years)
        yrbar_html = (f'<nav class="yrbar"><div class="yrbar-in">'
                      f'<span class="yrlab">{year_label}</span>{items}'
                      f'</div></nav>\n')
        bodycls = ' class="yrb"'
    if yearbar and yearbar[0] == "fyr":
        body = body.replace('<h2 id="map">The Map</h2>', '<h2 id="map">The Map</h2>' + yrbar_html, 1)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Open Tally</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Inter:wght@400;500;600;700;800&display=swap">
<style>{CSS}</style>
<link rel="stylesheet" href="{root}assets/navigation.css?v={ASSET_VERSIONS['navigation.css']}">
<script src="{root}assets/navigation.js?v={ASSET_VERSIONS['navigation.js']}" defer></script>
</head>
<body{bodycls}>
<a class="skip-link" href="#main-content">Skip to content</a>
<header class="site-head"><div class="brand-lockup"><div class="wordmark"><a href="{root}index.html" aria-label="Open Tally home">Open <span class="accent">Tally</span></a></div><span class="brand-caption">Public records. In view.</span></div><nav class="mainnav" aria-label="Primary">{nav}</nav></header>
<details class="record-notice"><summary>The count is still being updated. <span>About the records</span></summary><p class="notice">{STANDING_NOTICE}</p></details>
{jump_html}<main id="main-content">{body}</main>
<div class="footer"><span>Open Tally · <a href="{root}definitions/index.html">Definitions & methods</a> · <a href="#main-content">Back to top</a></span><span>{src_html}</span></div>
</body>
</html>"""

def write(path, content):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f: f.write(content)

FIPS_STATE = {
 "01":"Alabama","02":"Alaska","04":"Arizona","05":"Arkansas","06":"California",
 "08":"Colorado","09":"Connecticut","10":"Delaware","11":"District of Columbia",
 "12":"Florida","13":"Georgia","15":"Hawaii","16":"Idaho","17":"Illinois",
 "18":"Indiana","19":"Iowa","20":"Kansas","21":"Kentucky","22":"Louisiana",
 "23":"Maine","24":"Maryland","25":"Massachusetts","26":"Michigan","27":"Minnesota",
 "28":"Mississippi","29":"Missouri","30":"Montana","31":"Nebraska","32":"Nevada",
 "33":"New Hampshire","34":"New Jersey","35":"New Mexico","36":"New York",
 "37":"North Carolina","38":"North Dakota","39":"Ohio","40":"Oklahoma",
 "41":"Oregon","42":"Pennsylvania","44":"Rhode Island","45":"South Carolina",
 "46":"South Dakota","47":"Tennessee","48":"Texas","49":"Utah","50":"Vermont",
 "51":"Virginia","53":"Washington","54":"West Virginia","55":"Wisconsin","56":"Wyoming"}

LEGEND = ('<div class="legend">Registered % of adults: '
          f'{chip(80)}Under 90% &nbsp; {chip(95)}90% – 100% &nbsp; '
          f'{vchip()}More registered voters than adults in the population denominator shown &nbsp; {chip(None)}No data</div>')

# ---------------------------------------------------------------- citations + flags
def reg_key(d, state):
    """Citation key for a state's registered-voter figures (turnout file)."""
    keys = d["citemap"].get(("turnout-2026-11-03.csv", state), [])
    if not keys: return None
    for k in keys:
        if "registration" in k or "voter" in k: return k
    return keys[0]

def bal_key(d, state):
    """Citation key for a state's ballots-cast figures (turnout file)."""
    keys = d["citemap"].get(("turnout-2026-11-03.csv", state), [])
    if not keys: return None
    rk = reg_key(d, state)
    for k in keys:
        if k != rk and any(t in k for t in ("ballot", "unprocessed", "results", "enr")):
            return k
    return rk

def county_reg_key(d, state):
    keys = d["citemap"].get(("county-registered-all.csv", state), [])
    return keys[0] if keys else None

def hist_key_for_year(d, state, year):
    keys = d["citemap"].get(("turnout-history-states.csv", state), [])
    for k in keys:
        if str(year) in k: return k
    return keys[0] if keys else None

# the year switch: 2026 in front, then the past cycles the federal
# survey publishes county figures for
YEARS = ["2026", "2024", "2022", "2020", "2018", "2016"]
EAVS_YEARS = YEARS[1:]
EAVS_KEY = {"2024": "eac-eavs-2024-report", "2022": "eac-eavs-2022-report",
            "2020": "eac-eavs-2020", "2016": "eac-eavs-2016"}

def hist_county_row(d, state, fips, year):
    """A county's EAVS row for one year, from whichever history file
    carries that cycle (2024/2022 in county-history-eavs.csv,
    2020/2018/2016 in county-history-eavs-older.csv)."""
    if year in ("2024", "2022"):
        return d["hist_by_fips"].get((state, fips))
    return d["hist_older_by_fips"].get((state, fips))

def hist_county_vals(row, year):
    if row is None: return None, None
    return num(row[f"reg_{year}"]), num(row[f"ballots_{year}"])

def year_switch(panes):
    """The year switcher: CSS radio panes, the front map switch's
    mechanism. panes: [(year, pane_html)] in display order; the first
    (2026) is selected. Zero JavaScript."""
    out = ['<p class="context-note">Choose a year for the count below. Other sections keep their labeled dates. Adult ratios use the 2020 Census unless labeled otherwise.</p><div class="yrsw">']
    for i, (y, _h) in enumerate(panes):
        chk = " checked" if i == 0 else ""
        out.append(f'<input class="yr-in" type="radio" name="yrsw" '
                   f'id="yr{y}"{chk}>')
    out.append('<div class="yr-tabs">' + "".join(
        f'<label for="yr{y}">{y}</label>' for y, _h in panes) + "</div>")
    for y, h in panes:
        out.append(f'<div class="yr-pane yp{y}" aria-label="{y} count"><h3>{y} count</h3>{h}</div>')
    out.append("</div>")
    return "\n".join(out)

def mod(inner, cls=""):
    """One screen-sized page module: fills the screen, scroll-snaps
    at its start edge, content never clipped."""
    return f'<section class="mod{cls}">{inner}</section>'

def tline(text):
    """The one plain headline line a table carries on top of it:
    what the table shows and what stands out in it, computed from
    the table's own numbers — never an interpretation."""
    return f'<p class="tline">{text}</p>'

def linked(d, key, text_html):
    """Wrap a figure in its citation link (dotted underline, inherits color)."""
    if not key or key not in d["citations"] or text_html == "—":
        return text_html
    return f'<a class="cite" href="{esc(d["citations"][key]["url"])}">{text_html}</a>'

def flagged(d, state, field, inner_html):
    """Violet-wrap a figure if flags.csv names it. Returns (html, flag_row|None)."""
    fr = d["state_flags"].get((state, field))
    if not fr: return inner_html, None
    return (f'<span class="flag">{inner_html}</span>'
            f'<span class="flaglab">{esc(fr["flag_label"])}</span>'), fr

def pct_td_html(d, pct, citekey=None, bare_none=False):
    """Registered-% -of-adults cell as a FILLED <td>: the band color is
    the cell background, the number on top. Over 100 -> violet fill
    (flag rule), the flag label in white inside the cell.
    Returns (td_html, rule_fired). bare_none is kept for signature
    compatibility; a missing figure is a grey filled cell either way."""
    if pct is None:
        return fill_td("—", GREY), False
    if pct > 100:
        inner = linked(d, citekey, fmt_pct(pct))
        return (f'<td style="background:{VIOLET};color:#fff">{inner}'
                f'<span class="flaglabw">{esc(d["flag_rule"]["flag_label"])}</span></td>'), True
    return band_td(linked(d, citekey, fmt_pct(pct)), pct), False

def est_num_html(v, url):
    """A 2025-estimate figure, linked to its Census Bureau source file."""
    if v is None or not url: return fmt_int(v)
    return f'<a class="cite" href="{esc(url)}">{fmt_int(v)}</a>'

def est_pct_td(pct, url):
    """A share of adults on the 2025-estimate base, as a FILLED <td>.
    A different denominator, not two figures for the same measure
    disagreeing: banded normally (orange over 100), never violet,
    never the flag rule."""
    if pct is None: return fill_td("—", GREY)
    txt = fmt_pct(pct)
    if url: txt = f'<a class="cite" href="{esc(url)}">{txt}</a>'
    return band_td(txt, pct)

def _detail_numbers(detail):
    """Integers of 10,000+ in a flag detail, in order (the totals)."""
    return [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", detail)
            if int(x.replace(",", "")) >= 10000]

def _first_int(text):
    m = re.search(r"\d[\d,]*", text or "")
    return int(m.group(0).replace(",", "")) if m else None

def flag_sentence(d, row, s):
    """A flag as one plain sentence: it names the place, uses commas in
    numbers, and states only the numbers that disagree. flags.csv stays
    the data record unchanged; this wording is render-time only."""
    st, label = row["state"], row["flag_label"]
    if label in ("Two published totals", "Two published series"):
        a, b = _detail_numbers(row["flag_detail"])[:2]
        return (f"{st} published two different totals for its own "
                f"registered voters: {a:,} and {b:,}.")
    if label == "Count incomplete":
        m = re.search(r"[\d.]+ million", row["flag_detail"])
        return (f"{st} reported {s['ballots']:,} ballots. Another "
                f"{m.group(0)} ballots were still uncounted on November 6.")
    if label == "Voter-file count":
        return (f"{st} has no official total for its registered voters. "
                f"The number shown is a count of a voter file.")
    if label == "No official total":
        return (f"{st} has no official total for its registered voters. "
                f"The number shown was put together from town clerk reports.")
    if label == "Estimate":
        return (f"{st} reports an estimated voter count derived from the "
                f"Governor race: {s['published_count']:,}. This is not a ballot count.")
    if label == "Top-race votes":
        return (f"In {st}, the ballots number is the votes for the top "
                f"race, not a count of ballots.")
    return f"{st} — {row['flag_detail']}"

def flags_block(sentences, anchor=None):
    if not sentences: return ""
    h2 = f'<h2 id="{anchor}">Data notes</h2>' if anchor else "<h2>Data notes</h2>"
    out = [h2, '<div class="flags">']
    for snt in sentences:
        out.append(f"<div>{esc(snt)}</div>")
    out.append("</div>")
    return "\n".join(out)

def over_pop(d, counties_by_state):
    """Counties whose registered voters exceed their total population
    (2020 Census, all ages), from the site's own published figures."""
    if "over_pop" in d: return d["over_pop"]
    out = {}
    for st, clist in counties_by_state.items():
        lst = []
        for c in clist:
            gr = d["reg_by_county"].get((st, c["_nkey"]))
            reg = num(gr["registered_voters"]) if gr else None
            er = d["est_by_county"].get((st, c["_nkey"]))
            pop = num(er["total_population"]) if er else None
            if reg and pop and reg > pop:
                lst.append({"name": c["county_name"], "slug": c["_slug"],
                            "reg": reg, "pop": pop})
        if lst: out[st] = lst
    d["over_pop"] = out
    return out

def current_county(d, key):
    return d.get("population_comparisons", {}).get(key)

def current_county_pct(d, key):
    row = current_county(d, key)
    return row["ratio"] if row else None

def current_over_line_counts(d):
    out = {}
    for row in d.get("population_comparisons", {}).values():
        x, y = out.get(row["state"], (0, 0))
        out[row["state"]] = (x + int(row["above"]), y + 1)
    return out

def over_line_counts(d):
    """{state: (counties over 100% of adults, counties measured)} —
    recomputed from the county roll file's rows on every build."""
    out = {}
    for r in d["roll_co_de"]:
        x, y = out.get(r["state"], (0, 0))
        pct = fnum(r["registered_pct_of_vap"])
        out[r["state"]] = (x + (1 if (pct or 0) > 100 else 0), y + 1)
    return out

def active_only_states(d):
    """States whose county voter lists in the record count active
    voters only — their rows say so in the basis. A county over the
    line on the active list is over the line on the full list too
    (the full list is larger); the basis is named wherever the
    over-the-line count prints."""
    if "active_only" in d: return d["active_only"]
    out = set()
    for r in d["roll_co_de"]:
        b = (r["registration_basis"] or "").lower()
        if "active" in b and "only" in b: out.add(r["state"])
    d["active_only"] = out
    return out

def _link_state(text, st, states):
    return text.replace(esc(st),
        f'<a href="states/{states[st]["slug"]}/index.html">{esc(st)}</a>', 1)

def footer_src(d, key):
    base = f'Sources: <a class="cite" href="{esc(PL_URL)}">U.S. Census Bureau</a>'
    if key and key in d["citations"]:
        c = d["citations"][key]
        base += f' · <a class="cite" href="{esc(c["url"])}">{esc(c["publisher"])}</a>'
    else:
        base += ' · State election offices'
    return base

def cards_html(cards):
    """Summary numbers as designed blocks. Card = (big, label, sub[, tint])."""
    out = ['<div class="cards">']
    for c in cards:
        vio = ' vio' if len(c) > 3 and c[3] else ''
        out.append(f'<div class="card{vio}"><div class="v">{esc(c[0])}</div>'
                   f'<div class="k">{esc(c[1])}</div>'
                   f'<div class="sub">{esc(c[2])}</div></div>')
    out.append('</div>')
    return "\n".join(out)

def national_ed_cards(d):
    """National Election Day baseline vs the latest published number,
    from BASELINE-2026-11-03.md and the dated RECORD-LOG.md."""
    base, log = d["baseline_text"], "\n".join(d["log_lines"])
    def find(pat, text):
        ms = re.findall(pat, text)
        return ms[-1] if ms else None
    cards = []
    def card(label, bv, bw, cv, cw):
        if bv is None: return
        if cv:
            left = "Election Day" if bw == "Election Day" else f"Election Day ({bw})"
            cards.append((f"{bv} → {cv}", label,
                          f"{left} → latest ({cw})"))
        else:
            cards.append((bv, label,
                          f"Election Day ({bw}). No newer number yet."))
    card("Unemployment", find(r"Unemployment: ([\d.]+%)", base), "Sep 2026",
         find(r"unemployment ([\d.]+%)", log), "Oct 2026")
    pv = find(r"Payrolls \+([\d,]+) in October", log)
    card("Payrolls", find(r"Payrolls: (\+[\d,]+)", base), "Sep 2026",
         ("+" + pv) if pv else None, "Oct 2026")
    g3, g7 = d["gas3"].get("United States"), d["gas8"].get("United States")
    card("Gas — national average",
         f"${g3:.2f}" if g3 is not None else None, "Nov 3",
         f"${g7:.2f}" if g7 is not None else None, "Nov 8")
    card("Mortgage rate", find(r"Election Day baseline: ([\d.]+%)", log),
         "Election Day", find(r"Mortgage rate ([\d.]+%)", log),
         "week ending Nov 5")
    card("Jobless claims", find(r"\(baseline: ([\d,]+)\)", log),
         "week ended Oct 24", find(r"Jobless claims (\d{1,3}(?:,\d{3})+)", log),
         "week ended Oct 31")
    card("Consumer sentiment", find(r"from ([\d.]+) in October", log), "Oct",
         find(r"Consumer sentiment ([\d.]+)", log), "Nov, first reading")
    card("Inflation (CPI)", find(r"CPI inflation: ([\d.]+%)", base),
         "Sep 2026", None, "")
    card("Inflation, without food and energy",
         find(r"core CPI ([\d.]+%)", base), "Sep 2026", None, "")
    card("Average hourly earnings",
         find(r"Average hourly earnings: (\+[\d.]+%)", base),
         "Sep 2026, over the year", None, "")
    card("Labor force participation",
         find(r"Labor force participation: ([\d.]+%)", base),
         "Sep 2026", None, "")
    card("Real GDP growth", find(r"(\+[\d.]+%) advance Q3", base),
         "Q3 2026, first estimate", None, "")
    return cards

def governor_ed_cards(d):
    flips = d["gov_flips"]
    cards = []
    five = [(s, flips[s]) for s in
            ("Texas", "Georgia", "Ohio", "Iowa", "Nevada") if s in flips]
    if five:
        names = " · ".join(f"{s} — {n}" for s, n in five)
        cards.append((str(len(five)),
                      "States changed from Republican to Democrat",
                      names, True))
    if "Alaska" in flips:
        cards.append(("Alaska", "Governor — projected Democrat",
                      f"{flips['Alaska']}. Not yet called."))
    if "Kansas governor: not yet called" in d["baseline_text"]:
        cards.append(("Kansas", "Governor — not called",
                      "The Democrat is narrowly ahead. A Democrat held "
                      "the office going in."))
    return cards

def senate_ed_lines(d):
    """The national U.S. Senate picture in plain lines. The count
    after Election Day is computed from senate-results-2026.csv
    at build time and covers only what is decided: the 65 seats
    that were not on the ballot (31 Republicans, 32 Democrats,
    2 Independents — the before count of 53 / 45 / 2 minus the
    22 Republican and 13 Democratic seats that were voted on;
    senate-results-2026-notes.md) plus the races with a verified
    winner. A seat whose race is not decided is never carried
    for the party that held it: Alaska is not called, with the
    Democrat leading the first choices, so it stands in no
    party's count until the ranked-choice count lands. The open
    races are named, each with its state. (Computed, not typed,
    so the count cannot go stale against the file again.)"""
    flips = [s for s in ("Iowa", "Kansas", "North Carolina", "Ohio",
                         "South Carolina", "Texas")
             if s in SEN26_FLIPS]

    def party_family(p):
        p = (p or "").strip().upper()
        if p.startswith("DEM") or p == "D":
            return "D"
        if p.startswith("REP") or p == "R":
            return "R"
        return None

    won = {"R": 0, "D": 0}
    open_states = []
    for st, row in d["sen26"].items():
        status = (row["status"] or "").strip()
        if status == "No Senate race in 2026":
            continue
        if (num(row["winner_votes"]) is not None
                and "uncalled" not in status.lower()):
            fam = party_family(row["winner_party"])
            if fam:
                won[fam] += 1
        else:
            open_states.append(st)
    r_after, d_after = 31 + won["R"], 32 + won["D"]
    decided = r_after + d_after + 2
    lines = [
        "U.S. Senate before Election Day: 53 Republicans, "
        "45 Democrats, 2 Independents.",
        f"On the races decided so far — the seats that were not "
        f"on the ballot plus the races with a verified winner — "
        f"the count stands at {r_after} Republicans, "
        f"{d_after} Democrats, 2 Independents: {decided} of the "
        f"100 seats. {len(open_states)} seats are not decided "
        f"yet, and no undecided seat is counted for either party.",
        "35 seats were voted on (held going in by 22 Republicans "
        "and 13 Democrats). 65 seats were not on the ballot and "
        "do not change.",
        "Changed from Republican to Democrat: "
        + ", ".join(flips) + ".",
    ]
    ak = d["sen26"].get("Alaska")
    open_bits = []
    if ak is not None and "Alaska" in open_states:
        open_bits.append(
            f"Alaska is not called — "
            f"{esc(_gov_name(ak['winner']))}, the Democrat, leads "
            f"the first choices {num(ak['winner_votes']):,} to "
            f"{num(ak['runner_up_votes']):,}, and the ranked-choice "
            f"count lands November 18, 2026")
    if "Mississippi" in open_states:
        open_bits.append("Mississippi is still counting and has "
                         "published no statewide total")
    no_figs = [s for s in ("Arkansas", "Illinois", "Maine",
                           "Massachusetts", "New Jersey")
               if s in open_states]
    if no_figs:
        names = (", ".join(no_figs[:-1])
                 + (" and " if len(no_figs) > 1 else "")
                 + no_figs[-1])
        open_bits.append(f"{names} "
                         + ("have" if len(no_figs) > 1 else "has")
                         + " published no verified statewide "
                         "figures yet")
    if open_bits:
        lines.append("Not decided: " + "; ".join(open_bits) + ".")
    return lines

# ---------------------------------------------------------------- tracker economics
# Ranking method recovered from the tracker artifact (its COMP table and
# compScores function): every state is scored on the same fourteen
# numbers. For each number the 50 states are ranked and a state earns
# (49 - position) / 49 * 100 / 14 points. The Election Day score reads
# the Election Day gas price; the Today score reads the current gas
# price; the other thirteen numbers are the same in both. Rank order is
# score, then lowest unemployment, then name (the artifact's tie-break).
# District of Columbia is not ranked.
ECON_COMP = [("unemp", 1), ("jobs_move", 0), ("lf_move", 0), ("gdp_move", 0),
             ("pcpi", 0), ("gas_base", 1), ("claims_move", 1), ("hpi_move", 1),
             ("biz_apps", 0), ("permits", 0), ("lfpr", 0), ("wage", 0),
             ("elec", 1), ("poverty", 1)]
ECON_FILL = {"green": "#2e9e49", "yellow": "#e7b81f", "orange": "#dd741f",
             "grey": "#c9ced3"}
FACTOR_CITE = {"Average weekly wage": "bls-qcew-release",
               "New business applications": "census-bfs",
               "Building permits": "census-bps",
               "Labor force participation rate": "bls-laus-release",
               "Electricity price - all sectors": "eia-epm",
               "Poverty rate": "census-acs-b17001"}

def econ_states(d):
    """The 50 ranked states in the artifact's own (abbreviation) order."""
    rows = [r for r in d["econ"].values() if r["state"] != "District of Columbia"]
    rows.sort(key=lambda r: r["abbr"])
    return rows

def econ_scores(d, gas_field):
    ranked = econ_states(d)
    n = len(ranked)
    sc = {}
    for f0, low in ECON_COMP:
        f = gas_field if f0 == "gas_base" else f0
        srt = sorted(ranked, key=lambda r: fnum(r[f]), reverse=not low)
        for i, r in enumerate(srt):
            sc[r["state"]] = (sc.get(r["state"], 0.0)
                              + (n - 1 - i) / (n - 1) * 100 / len(ECON_COMP))
    return sc

def econ_ranks(d):
    """(base_rank, cur_rank) keyed by state name."""
    bs, cs = econ_scores(d, "gas_base"), econ_scores(d, "gas")
    def order(scores):
        return sorted(econ_states(d),
                      key=lambda r: (-scores[r["state"]], fnum(r["unemp"]), r["state"]))
    br = {r["state"]: i + 1 for i, r in enumerate(order(bs))}
    cr = {r["state"]: i + 1 for i, r in enumerate(order(cs))}
    return br, cr

def _head_score_up(m):    # jobs / labor force headings: up is good
    return 1 if m > 0 else (-1 if m < 0 else 0)

def _head_score_down(m):  # unemployment heading: down is good
    return 1 if m < 0 else (-1 if m > 0 else 0)

def econ_baseline_color(e):
    """The tracker's Election Day map shading: unemployment heading
    counted double, plus jobs and labor-force headings."""
    sc = (2 * _head_score_down(fnum(e["unemp_move"]))
          + _head_score_up(fnum(e["jobs_move"]))
          + _head_score_up(fnum(e["lf_move"])))
    return "green" if sc >= 2 else "orange" if sc <= -2 else "yellow"

def econ_today_color(e):
    """The tracker's Today map shading: jobless claims carry the
    direction (down is better, counted double on a 5%+ move); a gas
    fall of 12 cents or more adds a point."""
    ct, c = fnum(e["claims_today"]), fnum(e["claims"])
    g, gb = fnum(e["gas"]), fnum(e["gas_base"])
    if ct is None or c is None or g is None or gb is None or not c:
        return "grey"
    cp = (ct - c) / c * 100
    sc = 0
    if cp <= -5: sc += 2
    elif cp < 0: sc += 1
    elif cp >= 10: sc -= 2
    elif cp > 0: sc -= 1
    if gb - g >= 0.12: sc += 1
    return "green" if sc >= 2 else "orange" if sc <= -2 else "yellow"

def econ_chip(color_name):
    return f'<span class="chip" style="background:{ECON_FILL[color_name]}"></span>'

# the county layer's pale fills: the same bands, washed out, so the
# counties read as texture under the state shading and only the
# standouts carry full-strength color
PALE = {GREEN: "#bfe0cc", YELLOW: "#f5e3a1", ORANGE: "#f6cdb2"}

def pale_chip(pct):
    col = band(pct)
    return (f'<span class="chip" style="background:'
            f'{PALE.get(col, col)}"></span>')

def front_map_block(d, states):
    """One map, one view: the count. The state layer is the primary
    read — each state filled with its voter-list shading, registered
    voters as a share of adults, as the map read before counties
    joined it. Under that shading, every county is drawn: its fill a
    pale version of its 2026 ballots as a share of the adults who
    live there, grey where no office has published a county figure.
    A county whose ballots exceed its adults is no texture — it
    draws solid violet, on top. Each state's outline is drawn over
    its counties in the state's shading color, and tapping a state
    opens its panel, as before."""
    fills = {n: (VIOLET if (s["reg_pct_est"] or 0) > 100
                 else band(s["reg_pct_est"]))
             for n, s in states.items()}
    # the county layer by year: one shading code per county per
    # year — 0 no figure published (grey), 1 ballots under 90% of
    # adults, 2 ballots 90–100% of adults, 4 more ballots than
    # adults (violet). 2026 from the county ballots file; the past
    # cycles from the federal survey's county files. The state
    # layer carries no year: it is the voter lists as they stand.
    def ycode(bal, vap):
        if bal is None or not vap: return "0"
        p = round(bal / vap * 100, 1)
        return "4" if p > 100 else ("2" if p >= 90 else "1")
    codes = {y: {} for y in YEARS}
    cfills, strong = {}, []
    for c in d["counties"]:
        old_vap = num(c["voting_age_population_2020"])
        er = d["est_by_county"].get((c["state"], c["_nkey"]))
        vap = num(er["adults_18plus"]) if er else None
        r = d["ballots26_by_county"].get((c["state"], c["_nkey"]))
        bal = ballot_value(county_measure(BALLOTS26_LABEL[c["state"]]), num(r["ballots_cast"])) if r else None
        pct = (round(bal / vap * 100, 1)
               if (bal is not None and vap) else None)
        if (pct or 0) > 100:
            cfills[c["county_fips"]] = VIOLET
            strong.append(c["county_fips"])
        elif pct is None:
            cfills[c["county_fips"]] = GREY
        else:
            cfills[c["county_fips"]] = PALE[band(pct)]
        for y in YEARS:
            if y == "2026":
                b = bal
            else:
                _reg, b = hist_county_vals(
                    hist_county_row(d, c["state"], c["county_fips"], y), y)
            codes[y][c["county_fips"]] = ycode(b, vap if y == "2026" else old_vap)
    fips = {f: n for f, n in FIPS_STATE.items()}
    links = {n: f'states/{s["slug"]}/index.html' for n, s in states.items()}
    cnames = {c["county_fips"]: c["county_name"] for c in d["counties"]}
    leg_states = ('<div class="legend">States — registered voters '
                  'for every 100 adults (July 2025 estimate): ' + chip(80) + 'Under 90% &nbsp; '
                  + chip(95) + '90% – 100% &nbsp; ' + vchip()
                  + 'More registered voters than adults in the population denominator shown '
                  '&nbsp; ' + chip(None) + 'No data</div>')
    leg_counties = ('<div class="legend">Counties, under the state '
                    'shading — ballots for every 100 adults, '
                    '<span id="mapyr">2026</span> (2026 uses July 2025 adults; past cycles use the historical 2020 baseline): '
                    + pale_chip(80) + 'Under 90% &nbsp; '
                    + pale_chip(95) + '90% – 100% &nbsp; ' + vchip()
                    + 'More ballots than adults in the population denominator shown &nbsp; '
                    + chip(None) + 'No comparable ballot figure (race votes and returned ballots excluded)</div>')
    order = []
    svg = national_map(fips, fills, links, county_fills=cfills,
                       county_names=cnames, state_fill_opacity=0.45,
                       county_strong=strong, collect=order)
    ydata = {y: "".join(codes[y][f] for f in order) for y in YEARS}
    radios = "".join(
        f'<input class="yr-in" type="radio" name="fyrsw" '
        f'id="fyr{y}"{" checked" if y == "2026" else ""}>' for y in YEARS)
    tabs = ('<div class="yr-tabs fyr-tabs">'
            '<span class="yrlab">County ballots</span>' + "".join(
                f'<label for="fyr{y}">{y}</label>' for y in YEARS)
            + '</div>')
    return "\n".join([
        '<div class="maptoggle">',
        radios + tabs,
        svg,
        leg_states,
        leg_counties,
        f'<div id="yeardata" hidden>{json.dumps(ydata)}</div>',
        '</div>'])

def econ_rank_tables(d, states, prefix=""):
    br, cr = econ_ranks(d)
    by_name = d["econ"]
    def row(rank_map, name, other=None, color=None):
        e = by_name[name]
        cells = (f'<td>{rank_map[name]}</td>'
                 f'<td class="l">{econ_chip(color) if color else ""}'
                 f'<a href="{prefix}states/{states[name]["slug"]}/index.html">{esc(name)}</a></td>')
        if other is not None:
            diff = other[name] - rank_map[name]
            chg = f'↑ {diff}' if diff > 0 else f'↓ {-diff}' if diff < 0 else '→ 0'
            if diff > 0:
                cell = fill_td(chg, GREEN, cls="l")
            elif diff < 0:
                cell = fill_td(chg, ORANGE, cls="l")
            else:
                cell = f'<td class="l">{chg}</td>'
            cells += f'<td>{other[name]}</td>' + cell
        cells += (f'<td>{fmt_pct(fnum(e["unemp"]))}</td>'
                  f'<td>{fnum(e["jobs_move"]):+.1f}%</td>')
        return f'<tr>{cells}</tr>'
    first_ed = min(br, key=lambda n: br[n])
    first_td = min(cr, key=lambda n: cr[n])
    moved = sum(1 for n in br if br[n] != cr[n])
    out = ['<h3>State rankings — Election Day</h3>',
           tline(f"Each state's place is built from all fourteen "
                 f"numbers the record holds for a state — "
                 f"unemployment, jobs, labor force, jobless claims, "
                 f"gas, gross domestic product, house prices, "
                 f"personal income, new business applications, "
                 f"building permits, labor force participation, "
                 f"average weekly wage, electricity price and "
                 f"poverty rate — never from jobs alone. Every one "
                 f"of the fourteen is shown for every state on this "
                 f"page and on the state's own page. "
                 f"{esc(first_ed)} stood first on Election Day."),
           "<table><tr><th>Rank</th><th class='l'>State</th>"
           "<th>Unemployment</th><th>Jobs, year to Election Day</th></tr>"]
    for name in sorted(br, key=lambda n: br[n]):
        out.append(row(br, name, color=econ_baseline_color(by_name[name])))
    out.append('</table>')
    out.append('<h3>State rankings — Today</h3>')
    out.append(tline(f"The same fourteen numbers, ranked again on "
                     f"today's readings where newer numbers exist. "
                     f"{esc(first_td)} stands first; {moved} of the "
                     f"50 states hold a different place than on "
                     f"Election Day."))
    out.append("<table><tr><th>Rank</th><th class='l'>State</th>"
               "<th>Election Day rank</th><th class='l'>Change</th>"
               "<th>Unemployment</th><th>Jobs, year to Election Day</th></tr>")
    for name in sorted(cr, key=lambda n: cr[n]):
        out.append(row(cr, name, other=br, color=econ_today_color(by_name[name])))
    out.append('</table>')
    out.append('<p class="small">District of Columbia is not ranked.</p>')
    return "\n".join(out)

def econ_full_tables(d, states):
    """Every per-state indicator behind the economy ranks, one
    table per indicator, in the standing columns — Election Day |
    Today | Change — each with its meaning in its headline line,
    its period in its cells and its source under it. A state the
    record holds no figure for shows 'no data'; nothing is
    borrowed. The District of Columbia is listed with the states:
    these tables list figures, they do not rank."""
    names = sorted(states)
    out = ["<h2>Every number behind the ranks</h2>"]
    def head(label, meaning, standout):
        out.append(f"<h3>{label}</h3>")
        out.append(tline(f"{meaning} {standout}"))
        out.append("<table><tr><th class='l'>State</th>"
                   "<th>Election Day</th><th>Today</th>"
                   "<th>Change</th></tr>")
    def level_rows(field, ed_fmt, move_field, unit, up_good, span):
        for n in names:
            e = d["econ"].get(n)
            v = fnum(e[field]) if e else None
            if v is None:
                out.append(f'<tr><td class="l">{esc(n)}</td>'
                           f'<td>no data</td><td>no data</td>'
                           f'<td>no data</td></tr>')
                continue
            chg, fill = _move_cell(fnum(e[move_field]), unit,
                                   up_good, span)
            ccell = (fill_td(chg, fill) if fill else
                     f"<td>{chg}</td>" if chg else fill_td("—", GREY))
            out.append(f'<tr><td class="l">{esc(n)}</td>'
                       f'<td>{ed_fmt(v, e)}</td>'
                       f'<td>No newer number yet.</td>{ccell}</tr>')
        out.append("</table>")
    def top(field, fmt, rev=True):
        vals = [(fnum(d["econ"][n][field]), n) for n in names
                if d["econ"].get(n) and fnum(d["econ"][n][field]) is not None]
        v, n = (max if rev else min)(vals)
        return n, fmt(v)
    YR = "in the year to Election Day"
    n, v = top("unemp", lambda x: f"{x}%")
    head("Unemployment rate",
         "Out of every 100 people who are working or looking for "
         "work, how many do not have a job.",
         f"{esc(n)} was highest at {v}.")
    level_rows("unemp", lambda v, e: f"{e['unemp']}% (Sep 2026)",
               "unemp_move", " pts", False, YR)
    out.append('<p class="src">Bureau of Labor Statistics, Sep 2026.</p>')
    n, v = top("jobs", lambda x: f"{int(x):,}")
    head("Jobs", "How many people hold a payroll job.",
         f"{esc(n)} held the most, {v}.")
    level_rows("jobs", lambda v, e: f"{int(v):,} (Sep 2026)",
               "jobs_move", "%", True, YR)
    out.append('<p class="src">Bureau of Labor Statistics, Sep 2026.</p>')
    n, v = top("lf", lambda x: f"{int(x):,}")
    head("Labor force", "How many people are working or looking "
         "for work.", f"{esc(n)} was largest, {v}.")
    level_rows("lf", lambda v, e: f"{int(v):,} (Sep 2026)",
               "lf_move", "%", True, YR)
    out.append('<p class="src">Bureau of Labor Statistics, Sep 2026.</p>')
    # jobless claims: the record's true week-to-week pair
    up = dn = 0
    for n in names:
        cl = d["claims"].get(n, [])
        if len(cl) >= 2:
            dv = num(cl[-1]["claims"]) - num(cl[0]["claims"])
            if dv > 0: up += 1
            elif dv < 0: dn += 1
    head("Jobless claims in a week",
         "How many people asked for unemployment payments in a "
         "week — a first ask.",
         f"Claims fell in {dn} states and rose in {up} between "
         f"the two weeks.")
    for n in names:
        cl = d["claims"].get(n, [])
        if len(cl) < 2:
            out.append(f'<tr><td class="l">{esc(n)}</td>'
                       f'<td>no data</td><td>no data</td>'
                       f'<td>no data</td></tr>')
            continue
        a, bb = cl[0], cl[-1]
        va, vb = num(a["claims"]), num(bb["claims"])
        diff = vb - va
        if diff == 0: chg, fill = "→ No change", None
        else:
            chg = f"{diff:+,}"
            fill = GREEN if diff < 0 else ORANGE
        ccell = fill_td(chg, fill) if fill else f"<td>{chg}</td>"
        out.append(f'<tr><td class="l">{esc(n)}</td>'
                   f'<td>{va:,} (week ended {fmt_date(a["week ended"])})</td>'
                   f'<td>{vb:,} (week ended {fmt_date(bb["week ended"])})</td>'
                   f'{ccell}</tr>')
    out.append("</table>")
    out.append('<p class="src">U.S. Department of Labor, weekly '
               'claims releases.</p>')
    # gas: Election Day where AAA published a Nov 3 state price,
    # otherwise the state's Nov 5 price — each cell carries its date
    hi = max(((d["gas8"].get(n), n) for n in names
              if d["gas8"].get(n) is not None))
    head("Gas, regular",
         "The average pump price of a gallon of regular gas.",
         f"{esc(hi[1])} was highest on Nov 8 at ${hi[0]:.2f}.")
    for n in names:
        g8 = d["gas8"].get(n)
        g3, g5 = d["gas3"].get(n), d["gas5"].get(n)
        base, blab = (g3, "Nov 3") if g3 is not None else (g5, "Nov 5")
        if g8 is None or base is None:
            out.append(f'<tr><td class="l">{esc(n)}</td>'
                       f'<td>no data</td><td>no data</td>'
                       f'<td>no data</td></tr>')
            continue
        diff = round(g8 - base, 2)
        if diff == 0: chg, fill = "→ No change", None
        else:
            chg = (("+$" if diff > 0 else "−$") + f"{abs(diff):.2f}")
            fill = GREEN if diff < 0 else ORANGE
        ccell = fill_td(chg, fill) if fill else f"<td>{chg}</td>"
        out.append(f'<tr><td class="l">{esc(n)}</td>'
                   f'<td>${base:.2f} ({blab})</td>'
                   f'<td>${g8:.2f} (Nov 8)</td>{ccell}</tr>')
    out.append("</table>")
    out.append('<p class="src">AAA daily gas prices.</p>')
    n, v = top("gdp_b", lambda x: f"${x:,.1f} billion")
    head("Gross domestic product",
         "Everything a state makes and does, in dollars.",
         f"{esc(n)} was largest, {v}.")
    level_rows("gdp_b", lambda v, e: f"${v:,.1f} billion (Q2 2026)",
               "gdp_move", "%", True, "in Q2 2026, at a yearly rate")
    out.append('<p class="src">Bureau of Economic Analysis, Q2 2026.</p>')
    mv = [(fnum(d["econ"][n]["hpi_move"]), n) for n in names
          if d["econ"].get(n) and fnum(d["econ"][n]["hpi_move"]) is not None]
    hv, hn = max(mv)
    head("House price index",
         "How house prices move. The index follows the same "
         "houses over time; a higher number means pricier houses "
         "than when the index started.",
         f"Prices rose fastest in {esc(hn)}, {hv:+.1f}% in the "
         f"year to Election Day.")
    level_rows("hpi", lambda v, e: f"{e['hpi']} (Q2 2026)",
               "hpi_move", "%", True, YR)
    out.append('<p class="src">Federal Housing Finance Agency, '
               'Q2 2026.</p>')
    n, v = top("pcpi", lambda x: f"${int(x):,}")
    head("Personal income per person",
         "All the income in a state, divided by the people who "
         "live there.", f"{esc(n)} was highest, {v}.")
    level_rows("pcpi", lambda v, e: f"${int(v):,} (2025)",
               "pcpi_move", "%", True, YR)
    out.append('<p class="src">Bureau of Economic Analysis, 2025.</p>')
    # the six dated readings from the expanded factor file
    fnames = ["Average weekly wage", "Electricity price - all sectors",
              "New business applications", "Building permits",
              "Labor force participation rate", "Poverty rate"]
    wv = [(fnum(d["factors"][n]["Average weekly wage"]["value"]), n)
          for n in names if d["factors"].get(n, {}).get("Average weekly wage")]
    wmax, wn = max((v, n) for v, n in wv)
    out.append("<h3>Six more readings</h3>")
    out.append(tline(
        "Six more readings the record holds for every state, each "
        "with its own date in its column head. "
        f"{esc(wn)} had the highest average weekly wage, "
        f"${int(wmax):,} in Q1 2026."))
    out.append("<table><tr><th class='l'>State</th>" + "".join(
        f"<th>{esc(fn)} ({esc(d['factors'][names[0]][fn]['period'])})</th>"
        if d["factors"].get(names[0], {}).get(fn) else
        f"<th>{esc(fn)}</th>" for fn in fnames) + "</tr>")
    for n in names:
        cells = []
        for fn in fnames:
            r = d["factors"].get(n, {}).get(fn)
            cells.append(f"<td>{linked(d, FACTOR_CITE.get(fn), fmt_factor(r))}</td>"
                         if r else "<td>no data</td>")
        out.append(f'<tr><td class="l">{esc(n)}</td>'
                   + "".join(cells) + "</tr>")
    out.append("</table>")
    out.append('<p class="src">Average weekly wage — Bureau of '
               'Labor Statistics. Electricity price — Energy '
               'Information Administration. New business '
               'applications and building permits — Census Bureau. '
               'Labor force participation — Bureau of Labor '
               'Statistics. Poverty rate — Census Bureau.</p>')
    return "\n".join(out)

def national_ed_table(d):
    """The country's Election Day vs today measures in the standing
    columns. Same values and periods as the national cards carried."""
    base, log = d["baseline_text"], "\n".join(d["log_lines"])
    def find(pat, text):
        ms = re.findall(pat, text)
        return ms[-1] if ms else None
    rows = []
    def row(label, bv, bw, cv, cw, chg, diff=None, up_good=False):
        if bv is None: return
        if cv:
            # change cell filled by direction: green improving,
            # orange worsening; a zero move stays plain
            fill = None
            if diff:
                fill = GREEN if (diff > 0) == up_good else ORANGE
            rows.append((label, f"{bv} ({bw})", f"{cv} ({cw})", chg, fill))
        else:
            rows.append((label, f"{bv} ({bw})", "No newer number yet.", "—", GREY))
    ub, uc = find(r"Unemployment: ([\d.]+)%", base), find(r"unemployment ([\d.]+)%", log)
    row("Unemployment", (ub + "%") if ub else None, "Sep 2026",
        (uc + "%") if uc else None, "Oct 2026",
        f"{float(uc) - float(ub):+.1f} pts" if ub and uc else "—",
        diff=(float(uc) - float(ub)) if ub and uc else None, up_good=False)
    pb = find(r"Payrolls: \+([\d,]+)", base)
    pc = find(r"Payrolls \+([\d,]+) in October", log)
    row("Payrolls", ("+" + pb) if pb else None, "Sep 2026",
        ("+" + pc) if pc else None, "Oct 2026",
        f"{int(pc.replace(',', '')) - int(pb.replace(',', '')):+,}" if pb and pc else "—",
        diff=(int(pc.replace(',', '')) - int(pb.replace(',', ''))) if pb and pc else None,
        up_good=True)
    g3, g7 = d["gas3"].get("United States"), d["gas8"].get("United States")
    gd = (g7 - g3) if (g3 is not None and g7 is not None) else None
    row("Gas — national average",
        f"${g3:.2f}" if g3 is not None else None, "Nov 3",
        f"${g7:.2f}" if g7 is not None else None, "Nov 8",
        (("+$" if gd >= 0 else "−$") + f"{abs(gd):.2f}") if gd is not None else "—",
        diff=gd, up_good=False)
    mb = find(r"Election Day baseline: ([\d.]+)%", log)
    mc = find(r"Mortgage rate ([\d.]+)%", log)
    row("Mortgage rate", (mb + "%") if mb else None, "Election Day",
        (mc + "%") if mc else None, "week ending Nov 5",
        f"{float(mc) - float(mb):+.2f} pts" if mb and mc else "—",
        diff=(float(mc) - float(mb)) if mb and mc else None, up_good=False)
    cb = find(r"\(baseline: ([\d,]+)\)", log)
    cc = find(r"Jobless claims (\d{1,3}(?:,\d{3})+)", log)
    row("Jobless claims", cb, "week ended Oct 24", cc, "week ended Oct 31",
        f"{int(cc.replace(',', '')) - int(cb.replace(',', '')):+,}" if cb and cc else "—",
        diff=(int(cc.replace(',', '')) - int(cb.replace(',', ''))) if cb and cc else None,
        up_good=False)
    sb = find(r"from ([\d.]+) in October", log)
    sc_ = find(r"Consumer sentiment ([\d.]+)", log)
    row("Consumer sentiment", sb, "Oct", sc_, "Nov, first reading",
        f"{float(sc_) - float(sb):+.1f}" if sb and sc_ else "—",
        diff=(float(sc_) - float(sb)) if sb and sc_ else None, up_good=True)
    cpi = find(r"CPI inflation: ([\d.]+)%", base)
    row("Inflation (CPI)", (cpi + "%") if cpi else None, "Sep 2026", None, "", "—")
    core = find(r"core CPI ([\d.]+)%", base)
    row("Inflation, without food and energy", (core + "%") if core else None,
        "Sep 2026", None, "", "—")
    ehr = find(r"Average hourly earnings: \+([\d.]+)%", base)
    row("Average hourly earnings", ("+" + ehr + "% over the year") if ehr else None,
        "Sep 2026", None, "", "—")
    lfp = find(r"Labor force participation: ([\d.]+)%", base)
    row("Labor force participation", (lfp + "%") if lfp else None,
        "Sep 2026", None, "", "—")
    gdp = find(r"(\+[\d.]+)% advance Q3", base)
    row("Real GDP growth", (gdp + "%") if gdp else None,
        "Q3 2026, first estimate", None, "", "—")
    # S&P 500: the tracker record carries the move since Election Day
    # and Friday's close, not an Election Day close of its own — the
    # baseline cell stays empty rather than backing a close out of
    # the percentage.
    rows.append(("S&P 500", "—", "7,376.86 (Fri, Nov 6 close)",
                 "−2.54% since Election Day", ORANGE))
    out = ["<table><tr><th class='l'>Measure</th><th>Election Day</th>"
           "<th>Today</th><th>Change</th></tr>"]
    for label, b, c, chg, fill in rows:
        cell = (fill_td(esc(chg), fill) if fill else f'<td>{esc(chg)}</td>')
        out.append(f'<tr><td class="l">{esc(label)}</td><td>{esc(b)}</td>'
                   f'<td>{esc(c)}</td>{cell}</tr>')
    out.append("</table>")
    out.append('<p class="src">S&amp;P 500 — the tracker record '
               '(CNBC market data).</p>')
    return "\n".join(out)

def fmt_factor(r):
    v, u = r["value"], r["unit"]
    fv = fnum(v)
    if u == "%": return f"{v}%"
    if u == "USD per week": return f"${int(fv):,}"
    if "cents" in u: return f"{v}¢"
    if fv is not None and fv == int(fv): return f"{int(fv):,}"
    return v

ECON_SRC = ('<p class="src">Unemployment, jobs and labor force — '
            'Bureau of Labor Statistics. Jobless claims — U.S. '
            'Department of Labor. Gas — AAA. Gross domestic product '
            'and personal income — Bureau of Economic Analysis. '
            'House price index — Federal Housing Finance Agency.</p>')

def _move_cell(move, unit, up_good, span):
    """A change cell for a baseline heading: the move the record
    holds, with the span it covers named in the cell itself."""
    if move is None: return None, GREY
    if move == 0: return f"No change {span}", None
    fill = GREEN if (move > 0) == up_good else ORANGE
    return f"{move:+.1f}{unit} {span}", fill

def econ_rows(d, st):
    """Every per-state indicator the record holds, as rows of
    (measure, Election Day, today, change, change fill) in the
    standing columns. The paired numbers the record holds print as
    pairs (claims week to week, gas day to day); the baseline
    readings print with the move the record holds for them, its
    span named in the cell; a reading with no newer number and no
    recorded move prints 'No newer number yet.' Nothing is borrowed
    from another state or another date."""
    e = d["econ"].get(st)
    rows = []
    if e:
        u = fnum(e["unemp"])
        if u is not None:
            chg, fill = _move_cell(fnum(e["unemp_move"]), " pts",
                                   False, "in the year to Election Day")
            rows.append(("Unemployment rate", f"{e['unemp']}% (Sep 2026)",
                         None, chg, fill))
        j = fnum(e["jobs"])
        if j is not None:
            chg, fill = _move_cell(fnum(e["jobs_move"]), "%",
                                   True, "in the year to Election Day")
            rows.append(("Jobs", f"{int(j):,} (Sep 2026)",
                         None, chg, fill))
        lf = fnum(e["lf"])
        if lf is not None:
            chg, fill = _move_cell(fnum(e["lf_move"]), "%",
                                   True, "in the year to Election Day")
            rows.append(("Labor force", f"{int(lf):,} (Sep 2026)",
                         None, chg, fill))
    cl = d["claims"].get(st, [])
    if len(cl) >= 2:
        a, bb = cl[0], cl[-1]
        va, vb = num(a["claims"]), num(bb["claims"])
        diff = vb - va
        if diff == 0:
            chg, fill = "→ No change", None
        else:
            chg = f"{diff:+,}"
            fill = GREEN if diff < 0 else ORANGE
        rows.append(("Jobless claims in a week",
                     f"{va:,} (week ended {fmt_date(a['week ended'])})",
                     f"{vb:,} (week ended {fmt_date(bb['week ended'])})", chg, fill))
    g3, g7 = d["gas3"].get(st), d["gas8"].get(st)
    if g3 is not None and g7 is not None:
        diff = round(g7 - g3, 2)
        gtxt = (("+$" if diff > 0 else "−$") + f"{abs(diff):.2f}")
        if diff == 0:
            chg, fill = "→ No change", None
        else:
            chg = gtxt
            fill = GREEN if diff < 0 else ORANGE
        rows.append(("Gas, regular", f"${g3:.2f} (Nov 3)",
                     f"${g7:.2f} (Nov 8)", chg, fill))
    # the per-state pair every state has: Nov 5 to Nov 8 (AAA). The
    # Nov 5 figure is the state baseline — it is never labeled
    # Election Day; only five states have a Nov 3 figure.
    g5, g7b = d["gas5"].get(st), d["gas8"].get(st)
    if g5 is not None and g7b is not None:
        diff = round(g7b - g5, 2)
        gtxt = (("+$" if diff > 0 else "−$") + f"{abs(diff):.2f}")
        if diff == 0:
            chg, fill = "→ No change", None
        else:
            chg = gtxt
            fill = GREEN if diff < 0 else ORANGE
        rows.append(("Gas, regular — from Nov 5", f"${g5:.2f} (Nov 5)",
                     f"${g7b:.2f} (Nov 8)", chg, fill))
    if e:
        g = fnum(e["gdp_b"])
        if g is not None:
            chg, fill = _move_cell(fnum(e["gdp_move"]), "%",
                                   True, "in Q2 2026, at a yearly rate")
            rows.append(("Gross domestic product",
                         f"${g:,.1f} billion (Q2 2026)", None, chg, fill))
        h = fnum(e["hpi"])
        if h is not None:
            chg, fill = _move_cell(fnum(e["hpi_move"]), "%",
                                   True, "in the year to Election Day")
            rows.append(("House price index", f"{e['hpi']} (Q2 2026)",
                         None, chg, fill))
        p = fnum(e["pcpi"])
        if p is not None:
            chg, fill = _move_cell(fnum(e["pcpi_move"]), "%",
                                   True, "in the year to Election Day")
            rows.append(("Personal income per person",
                         f"${int(p):,} (2025)", None, chg, fill))
    fac = d["factors"].get(st, {})
    for fname in ("Average weekly wage", "New business applications",
                  "Building permits", "Labor force participation rate",
                  "Electricity price - all sectors", "Poverty rate"):
        r = fac.get(fname)
        if r:
            val = linked(d, FACTOR_CITE.get(fname), fmt_factor(r))
            rows.append((fname, f"{val} ({r['period']})", None, None, GREY))
    return rows

def ed_rows_table(rows):
    """The standing Election Day | Today | Change table for a set
    of econ_rows. A row with no today value says so; a recorded
    change still prints, with its span named in its cell."""
    out = ["<table><tr><th class='l'>Measure</th><th>Election Day</th>"
           "<th>Today</th><th>Change</th></tr>"]
    for label, b, c, chg, fill in rows:
        tcell = f"<td>{c}</td>" if c is not None else \
            "<td>No newer number yet.</td>"
        if chg is None:
            ccell = fill_td("—", GREY)
        elif fill:
            ccell = fill_td(chg, fill)
        else:
            ccell = f"<td>{chg}</td>"
        out.append(f'<tr><td class="l">{esc(label)}</td><td>{b}</td>'
                   f'{tcell}{ccell}</tr>')
    out.append("</table>")
    return "\n".join(out)

def state_ed_html(d, s):
    """A state's Election Day vs today block: governor where the record
    carries it, then one table in the standing columns — Election Day |
    Today | Change — carrying every per-state indicator the record
    holds for the state."""
    st = s["name"]
    gov = gov_line_html(d, st)
    sen = senate_line_html(d, st)
    house = house_line_html(d, st)
    rows = econ_rows(d, st)
    if not gov and not sen and not house and not rows: return ""
    out = ['<h2 id="election-day">Election Day vs today</h2>']
    if gov: out.append(f'<div class="govline">{gov}</div>')
    if sen: out.append(f'<div class="govline">{sen}</div>')
    if house: out.append(f'<div class="govline">{house}</div>')
    if rows:
        grows = next((r for r in rows if r[0] == "Gas, regular"), None)
        if grows is not None:
            out.append(tline(f"{esc(st)}'s measures on Election Day "
                             f"beside today's. Gas was {grows[1]} and "
                             f"is {grows[2]}."))
        else:
            out.append(tline(f"{esc(st)}'s measures on Election Day "
                             f"beside today's, where a newer number "
                             f"exists."))
        out.append(ed_rows_table(rows))
        out.append(ECON_SRC)
    return "\n".join(out)

def state_extra_sections(d, s, collect=None):
    """Registration splits, removals, the 2024 ballots detail, polling
    places, and rules for one state. Every figure comes from its own
    file and keeps that file's source line; gaps stay gaps. When
    collect is a list, each emitted section's (anchor, label) is
    appended to it for the page's jump bar."""
    st = s["name"]
    out = []
    sr = d["splits"].get(st)
    if sr:
        tot = num(sr["registered_total"])
        act = num(sr["registered_active"])
        ina = num(sr["registered_inactive"])
        if tot or act:
            out.append('<h2 id="registration">Registration</h2>')
            if tot and act and ina:
                out.append(tline(
                    f"The voter list as the state splits it: "
                    f"{tot:,} registered voters in all — {act:,} "
                    f"active and {ina:,} inactive."))
            elif tot:
                out.append(tline(
                    f"The voter list as the state splits it: "
                    f"{tot:,} registered voters in all."))
            out.append('<table>')
            if collect is not None: collect.append(("registration", "Registration"))
            if tot: out.append(f'<tr><td class="l">Registered voters — total</td><td>{fmt_int(tot)}</td></tr>')
            if act: out.append(f'<tr><td class="l">Active</td><td>{fmt_int(act)}</td></tr>')
            if ina: out.append(f'<tr><td class="l">Inactive</td><td>{fmt_int(ina)}</td></tr>')
            if sr["inactive_pct"]:
                out.append(f'<tr><td class="l">Inactive % of the list</td><td>{esc(sr["inactive_pct"])}%</td></tr>')
            for lab, col in (("Democrat", "dem_rv"), ("Republican", "rep_rv"),
                             ("Other / unaffiliated", "other_unaffiliated_rv")):
                v = num(sr[col])
                if v is not None:
                    out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
            out.append("</table>")
            if sr["basis"]:
                out.append(f'<p class="src">Who is counted: {esc(sr["basis"])}.</p>')
            if act or ina:
                out.append('<p class="src">Active and inactive are '
                           'the office\'s two marks on a name — '
                           'every name on the list is registered '
                           'either way, and an inactive voter can '
                           'still vote.</p>')
            if act and tot and s["registered"] == act and tot > act:
                out.append(f'<p class="src">The registration number at the '
                           f'top of this page counts active voters only; '
                           f'the full voter list is {tot:,}.</p>')
            out.append(f'<p class="src">Source: {esc(plain_src(sr["source"]))}</p>')
    rm = d["removals"].get(st)
    if rm and num(rm["removed_total"]):
        rt = num(rm["removed_total"])
        out.append('<h2 id="removals">Removals</h2>')
        out.append(tline(f"{rt:,} voters came off {esc(st)}'s voter "
                         f"list in the period in this table."))
        out.append('<table>')
        if collect is not None: collect.append(("removals", "Removals"))
        out.append(f'<tr><td class="l">Removed from the voter list</td><td>{fmt_int(rt)}</td></tr>')
        out.append(f'<tr><td class="l">Period</td><td class="l">'
                   f'{fmt_date(rm["period_start"])} – {fmt_date(rm["period_end"])}</td></tr>')
        if s["registered"]:
            share = rt / s["registered"] * 100
            out.append(f'<tr><td class="l">Share of the voter list</td>'
                       f'{band_td(f"{share:.1f}%", share)}</tr>')
        for lab, col in (("Moved", "removed_moved"), ("Deceased", "removed_deceased"),
                         ("Felony", "removed_felony"), ("Duplicate", "removed_duplicate"),
                         ("At the voter's request", "removed_request"),
                         ("Confirmation process", "removed_confirmation_process"),
                         ("Other", "removed_other")):
            v = num(rm[col])
            if v is not None:
                out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
        if num(rm["added_total"]):
            out.append(f'<tr><td class="l">Added to the voter list</td>'
                       f'<td>{fmt_int(num(rm["added_total"]))}</td></tr>')
        if num(rm["confirmation_notices_mailed"]):
            out.append(f'<tr><td class="l">Confirmation notices mailed</td>'
                       f'<td>{fmt_int(num(rm["confirmation_notices_mailed"]))}</td></tr>')
        out.append("</table>")
        out.append(f'<p class="src">Source: {esc(plain_src(rm["source"]))}</p>')
    b = d["ballots24"].get(st)
    if b:
        rows = []
        mret, mcnt, mrej = num(b["mail_returned"]), num(b["mail_counted"]), num(b["mail_rejected"])
        if mret is not None: rows.append(("Mail ballots returned", mret, None))
        if mcnt is not None: rows.append(("Mail ballots counted", mcnt, None))
        if mrej is not None:
            rate = (mrej / mret * 100) if mret else None
            rows.append(("Mail ballots rejected", mrej, rate))
        if num(b["mail_cured"]) is not None:
            rows.append(("Mail ballots cured", num(b["mail_cured"]), None))
        for lab, col in (("Provisional ballots cast", "provisional_cast"),
                         ("Provisional ballots counted", "provisional_counted"),
                         ("Provisional ballots rejected", "provisional_rejected"),
                         ("UOCAVA ballots transmitted", "uocava_sent"),
                         ("UOCAVA ballots returned", "uocava_returned"),
                         ("UOCAVA ballots counted", "uocava_counted"),
                         ("UOCAVA ballots rejected", "uocava_rejected")):
            v = num(b[col])
            if v is not None: rows.append((lab, v, None))
        if rows:
            out.append('<h2 id="ballots-2024">Ballots — 2024</h2>')
            if mret is not None and mrej is not None:
                out.append(tline(
                    f"In 2024, {mret:,} mail ballots came back to "
                    f"{esc(st)} and {mrej:,} of them were rejected."))
            elif mret is not None:
                out.append(tline(
                    f"In 2024, {mret:,} mail ballots came back to "
                    f"{esc(st)}."))
            out.append('<table>')
            if collect is not None: collect.append(("ballots-2024", "Ballots — 2024"))
            for lab, v, rate in rows:
                out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
                if rate is not None:
                    out.append(f'<tr><td class="l">Mail rejection rate</td>'
                               f'{band_td(f"{rate:.2f}%", rate)}</tr>')
            out.append("</table>")
            out.append(f'<p class="src">Source: {esc(plain_src(b["source"]))}</p>')
    pp = d["polling"].get(st)
    if pp:
        out.append('<h2 id="polling">Polling places — 2024</h2>')
        if num(pp["polling_places_election_day"]) is not None:
            out.append(tline(
                f"{esc(st)} opened "
                f"{num(pp['polling_places_election_day']):,} polling "
                f"places on Election Day 2024."))
        out.append('<table>')
        if collect is not None: collect.append(("polling", "Polling places — 2024"))
        if num(pp["polling_places_election_day"]) is not None:
            out.append(f'<tr><td class="l">Polling places, Election Day</td>'
                       f'<td>{fmt_int(num(pp["polling_places_election_day"]))}</td></tr>')
        if pp["places_per_10k_adults"]:
            out.append(f'<tr><td class="l">Polling places per 10,000 adults</td>'
                       f'<td>{esc(pp["places_per_10k_adults"])}</td></tr>')
        if num(pp["early_voting_sites"]) is not None:
            out.append(f'<tr><td class="l">Early voting sites</td>'
                       f'<td>{fmt_int(num(pp["early_voting_sites"]))}</td></tr>')
        if num(pp["drop_boxes"]) is not None:
            out.append(f'<tr><td class="l">Drop boxes</td>'
                       f'<td>{fmt_int(num(pp["drop_boxes"]))}</td></tr>')
        if pp["drop_boxes_per_10k_adults"]:
            out.append(f'<tr><td class="l">Drop boxes per 10,000 adults</td>'
                       f'<td>{esc(pp["drop_boxes_per_10k_adults"])}</td></tr>')
        out.append("</table>")
        out.append(f'<p class="src">Source: <a class="cite" href="{esc(pp["source_url"])}">'
                   f'{esc(pp["source"])}</a></p>')
    rl = d["rules"].get(st)
    if rl:
        out.append('<h2 id="rules">Rules</h2>')
        out.append(tline(f"How {esc(st)} runs its elections, as "
                         f"the state publishes it."))
        out.append('<table>')
        if collect is not None: collect.append(("rules", "Rules"))
        def rrow(lab, val):
            if val:
                out.append(f'<tr><td class="l">{lab}</td><td class="l">{esc(val)}</td></tr>')
        rrow("Registration deadline",
             f'{rl["registration_deadline_days_before_election"]} days before Election Day'
             if rl["registration_deadline_days_before_election"] else "")
        rrow("Same-day registration", rl["same_day_registration"])
        rrow("Mail ballot request deadline", rl["mail_ballot_request_deadline"])
        rrow("Mail ballot receipt rule", rl["mail_ballot_receipt_rule"])
        if rl["ballot_cure_available"]:
            rrow("Ballot cure", rl["ballot_cure_available"]
                 + (f' — {rl["cure_period_days"]} days' if rl["cure_period_days"] else ""))
        rrow("Recount", rl["recount_margin_threshold"])
        rrow("Post-election audit", rl["post_election_audit_type"])
        rrow("Early voting", f'{rl["early_voting_days"]} days' if rl["early_voting_days"] else "")
        out.append("</table>")
        out.append(f'<p class="src">Source: <a class="cite" href="{esc(rl["source_url"])}">'
                   f'{esc(rl["source"])}</a> (as of {fmt_date(rl["as_of"])}).</p>')
    return "\n".join(out)

def ballots26_note(d, st):
    note = _ballots26_source_note(d, st)
    if not note:
        return note
    label = BALLOTS26_LABEL.get(st, "Published count")
    rows = d["ballots26_rows"].get(st, d["mt_ballots"] if st == "Montana" else [])
    sources = list(dict.fromkeys(r["source"] for r in rows))
    urls = list(dict.fromkeys(r["source_url"] for r in rows))
    scope = ('County figures measure ' + label + '. These are source-record snapshots, '
             'not a synchronized county/state reconciliation. A difference between contest votes '
             'and ballots, or between reporting times, is not a missing-ballot total.')
    return ('<p class="src">' + esc(scope) + '</p>' + note +
            '<details><summary>County source and reporting date</summary><p>' +
            esc('; '.join(sources)) + '</p>' +
            ''.join('<p><a class="cite" href="' + esc(u) + '">Original source</a></p>' for u in urls) + '</details>')


def _ballots26_source_note(d, st):
    """The county-ballots reconciliation for one state, as published:
    the county parts summed at build time against the total the state
    itself published (collection log, 2026-11-07). Where the two
    disagree, both numbers print with the difference; nothing is
    adjusted. States whose parts match print the match."""
    parts = d["ballots26_sum"].get(st)
    if parts is None: return ""
    if st == "Alaska":
        return (f'<p class="src">The 40 district figures add up to '
                f'{parts:,}. The same report prints three statewide '
                f'totals for ballots cast: 215,912 in its header, '
                f'215,906 in its Senate section, and 215,776 in its '
                f'Governor section. Nothing has been adjusted.</p>')
    if st == "North Carolina":
        return (f'<p class="src">The 100 county figures add up to '
                f'{parts:,} — the Senate total in the State Board\'s '
                f'statewide file. The Board\'s dashboard puts ballots '
                f'cast at 4,223,102, which is {4223102 - parts:,} more. '
                f'Both numbers stand as published.</p>')
    if st == "California":
        return (f'<p class="src">The 58 county figures add up to '
                f'{parts:,} — the Governor total in the Secretary of '
                f'State\'s file. The same file puts ballots cast at '
                f'10,441,726, which is {10441726 - parts:,} more. Both '
                f'numbers stand as published.</p>')
    if st == "New Mexico":
        return (f'<p class="src">All 33 county figures add up to '
                f'{parts:,} — the statewide Governor total, '
                f'725,612.</p>')
    if st == "Louisiana":
        return (f'<p class="src">The 64 parish figures add up to '
                f'{parts:,} — the statewide Senate total the portal '
                f'displays now. An earlier read on November 7 put that '
                f'total at 1,466,069; the later read the same evening '
                f'put it at 1,466,072 — the count moved by 3 between '
                f'reads. Both readings stand as published.</p>')
    if st == "Hawaii":
        return (f'<p class="src">The four county figures add up to '
                f'{parts:,}. The statewide report puts turnout at '
                f'391,251 — {parts - 391251} fewer. Both numbers stand '
                f'as published.</p>')
    if st == "Vermont":
        return (f'<p class="src">The 14 county figures add up to '
                f'{parts:,} — Governor candidate votes, the towns '
                f'added up within each county (Vermont reports by '
                f'town). The town file\'s own Total Votes column adds '
                f'up to 311,510 — the Total Votes Cast the site '
                f'displays — which includes 2,131 blank votes and '
                f'324 overvotes as printed. Both numbers stand as '
                f'published.</p>')
    if st == "Wyoming":
        return (f'<p class="src">20 of Wyoming\'s 23 counties are '
                f'shown; they add up to {parts:,}. The files for '
                f'Converse, Lincoln, and Park counties could not be '
                f'read, and no statewide total could be read either. '
                f'Nothing has been filled in.</p>')
    if st == "South Carolina":
        return (f'<p class="src">The 46 county figures add up to '
                f'{parts:,} — the statewide Vote Cast for the Governor '
                f'contest in the State Election Commission\'s file. '
                f'The two leading candidates hold 2,011,279 of those '
                f'votes; the rest are two more candidates — Addison '
                f'with 16,123 and Hakim with 9,077 — and 1,143 '
                f'write-in votes.</p>')
    if st == "Oregon":
        return (f'<p class="src">The 36 county figures add up to '
                f'{parts:,} — the statewide Governor total on the '
                f'Secretary of State\'s results page. The same page '
                f'puts ballots counted at 1,891,605, which is '
                f'{1891605 - parts:,} more; the state publishes no '
                f'county figures for ballots counted. Both numbers '
                f'stand as published.</p>')
    if st == "Indiana":
        return (f'<p class="src">The 92 county figures add up to '
                f'{parts:,} — the sum of the five candidates the '
                f'Secretary of State\'s results portal displays '
                f'statewide (Bayh 1,004,067; Engling 826,017; Ballard '
                f'69,857; Shillings 36,308; Delano 70); the portal '
                f'prints no combined total. The count is still in '
                f'progress: 95.3% of precincts were reporting as of '
                f'November 7.</p>')
    if st == "Missouri":
        return (f'<p class="src">The 115 county figures add up to '
                f'{parts:,}. The Secretary of State\'s page prints a '
                f'separate Kansas City row of 96,991 votes '
                f'(Fitzpatrick 14,986; Wilson 79,985; Coffell 2,020); '
                f'all 116 printed rows together add up to 2,083,601 '
                f'— the statewide total the page displays, candidate '
                f'by candidate. The county figures stand as printed, '
                f'net of Kansas City; nothing has been adjusted.</p>')
    if st == "North Dakota":
        return (f'<p class="src">The 53 county figures add up to '
                f'{parts:,} — the statewide Total Votes for the '
                f'Representative in Congress contest in the '
                f'Secretary of State\'s results app. The same app '
                f'puts ballots cast statewide at 239,057, which is '
                f'{239057 - parts:,} more. Both numbers stand as '
                f'published.</p>')
    if st == "South Dakota":
        return (f'<p class="src">The 66 county figures add up to '
                f'{parts:,} — the statewide Governor total the '
                f'Secretary of State\'s results site displays. The '
                f'same site puts ballots cast statewide at 310,298, '
                f'which is {310298 - parts:,} more. Both numbers '
                f'stand as published.</p>')
    if st == "Nebraska":
        return (f'<p class="src">The 93 county figures add up to '
                f'{parts:,} — the statewide Governor total the '
                f'Secretary of State\'s results page displays. The '
                f'same page puts ballots cast statewide at 767,046, '
                f'which is {767046 - parts:,} more. Both numbers '
                f'stand as published.</p>')
    if st == "Utah":
        return (f'<p class="src">The 29 county figures add up to '
                f'{parts:,} — the statewide total for Constitutional '
                f'Amendment B in the state\'s media export. The '
                f'export publishes no ballots-cast figure; nothing '
                f'else is recorded.</p>')
    if st == "Nevada":
        return (f'<p class="src">The 17 county figures add up to '
                f'{parts:,} — the statewide total the Secretary of '
                f'State\'s results app displays for the Governor '
                f'contest. The feed publishes no ballots-cast '
                f'figure; nothing else is recorded.</p>')
    pub = {"Alabama": (1693621, "the statewide total the Secretary of State published"),
           "Colorado": (2761449, "the total in the Secretary of State's release"),
           "Minnesota": (2830125, "the statewide Governor total in the Secretary of State's file"),
           # Maryland's county figures come from the Board's county
           # detail page (refreshed Nov 7, 7:34 PM; they add to
           # 2,033,639); the Board's statewide page refreshed later
           # that evening (9:37 PM) and prints 2,045,846 — the total
           # the governor file carries (governor-results-2026-
           # notes.md). The pair therefore disagrees and both
           # numbers print.
           "Maryland": (2045846, "the statewide Governor total on the State Board's statewide page"),
           "Kansas": (1099896, "the statewide Senate total on the Secretary of State's statewide page"),
           "Virginia": (3590246, "the statewide Senate total the Department of Elections' results site displays"),
           "Pennsylvania": (4985374, "the sum of the statewide candidate totals the Department of State displays"),
           "Florida": (8270224, "the statewide Governor total published from the same system"),
           "Arizona": (2549311, "the statewide Governor total in the same file"),
           "Ohio": (4597270, "the statewide total row in the Secretary of State's file"),
           "Georgia": (4181543, "the sum of the statewide candidate totals the Secretary of State's results site displays; the site prints no combined total"),
           "New York": (6102694, "the statewide Governor total the State Board's election-night site displays"),
           "West Virginia": (456128, "the statewide Senate total in the Secretary of State's file"),
           "Oklahoma": (1120930, "the statewide total displayed on the State Election Board's portal"),
           "Tennessee": (2102474, "the sum of the dashboard's 15 printed statewide candidates; the dashboard prints no statewide total"),
           "Iowa": (1366516, "the statewide Vote Cast in the Secretary of State's file"),
           "Montana": (486746, "the statewide total the Secretary of State published")}
    if st in pub:
        total, who = pub[st]
        if parts == total:
            return (f'<p class="src">The county figures add up to '
                    f'{parts:,} — {who}.</p>')
        return (f'<p class="src">The county figures add up to '
                f'{parts:,}; the published statewide total is '
                f'{total:,}. Both numbers stand as published.</p>')
    return ""

def anoms_tline(rows):
    """Archived values are not a validated like-for-like trend series."""
    if not rows: return ""
    return ("Archived figures, not a comparable change series. The 2026 record "
            "mixes reporting dates, incomplete coverage and count types; "
            "changes from earlier elections are not calculated here.")


def archived_quadrants_html(rows):
    """Preserve source ratios without repeating unsupported ballot groups."""
    out = ['<p class="archive-note">Archived source ratios using the 2020 adult '
           'population baseline. The recorded election-count numerator can be '
           'ballots, returned ballots or votes in one contest. These ratios are '
           'not comparable turnout measures; the former high/low groups are '
           'not used. The unchanged source file retains its original fields.</p>',
           "<table><tr><th class='l'>State</th><th>Recorded registration / 2020 adults (%)</th>"
           "<th>Recorded election count / 2020 adults (%) — mixed measures</th></tr>"]
    for row in rows:
        def ratio(field):
            value = (row.get(field) or "").strip()
            return esc(value) + "%" if value else "—"
        out.append(f'<tr><td class="l">{esc(row["state"])}</td>'
                   f'<td>{ratio("registered_pct_of_vap")}</td>'
                   f'<td>{ratio("ballots_pct_of_vap")}</td></tr>')
    out.append('</table>')
    return "\n".join(out)


def patterns_html(d, states, counties_by_state):
    """The front page's pattern summaries — joins that already exist
    in the data files, in plain words, each linked to the full table
    behind it. Summaries only; no number is computed here that the
    files do not carry, beyond the sums the builders already make."""
    blocks = []
    out = []
    # Current primary comparison uses the published 2025 adult estimates.
    # The 2020 record remains available separately, not a present-day claim.
    rows, missing = population_comparisons(
        d["counties"], d["reg_by_county"], d["est_by_county"], num)
    above = sum(r["above"] for r in rows)
    out.append('<h3>Registration and the latest recorded adult estimates</h3>')
    out.append(f'<p>{above:,} of {len(rows):,} comparable counties have '
               'more registered voters in the recorded election-office figures '
               'than residents age 18+ in the Census Bureau’s July 1, 2025 estimates.</p>')
    out.append('<p class="measure-note">These age-specific estimates account for '
               'population change through July 1, 2025. They are not a count of '
               'eligible voters or an Election Day 2026 population count. '
               'Registration dates and active/inactive coverage vary and are '
               'shown in the county record. No 2026 population is extrapolated.</p>')
    if missing:
        out.append(f'<p>{len(missing):,} counties with registration figures lack '
                   'a comparable 2025 adult estimate and are excluded.</p>')
    out.append('<p><a href="downloads/county-registration-population-2025.csv">'
               'Download every comparison, source, date and population change</a></p>')
    out.append('<details class="supporting-record"><summary>Historical 2020 comparison</summary>')
    olc = over_line_counts(d)
    out.append(f'<p>{sum(x for x, _ in olc.values()):,} of '
               f'{sum(y for _, y in olc.values()):,} counties exceed the '
               '2020 Census adult count. This historical comparison does not '
               'account for subsequent population growth or decline.</p></details>')
    blocks.append("\n".join(out)); out = []
    # Preserve old ratios as an archive, not current ballot-based groups.
    out.append('<details class="supporting-record"><summary>Archived 2020-baseline source ratios</summary>')
    out.append(archived_quadrants_html(d["quadrants"]))
    out.append('<p><a href="data/combination-quadrants.csv">Original source file (CSV)</a></p></details>')
    blocks.append("\n".join(out)); out = []
    # (c) 2026 next to past elections: the same side-by-side numbers
    # as the full table, change cells filled by direction
    out.append("<h3>2026 next to past elections</h3>")
    _at = anoms_tline(d["anoms"])
    if _at: out.append(tline(_at))
    out.append("<table><tr><th class='l'>State</th><th class='l'>Measure</th>"
               "<th>2026</th><th>2022</th><th>2018</th>"
               "<th>Change from 2022</th><th>Change from 2018</th></tr>")
    out.extend(anoms_rows_html(d["anoms"], with_state=True))
    out.append("</table>")
    out.append(ANOMS_SRC)
    out.append('<p class="small">The full table: '
               '<a href="data/index.html#next-to-past">Data — 2026 next '
               'to past elections</a></p>')
    blocks.append("\n".join(out)); out = []
    # (d) official numbers that disagree with each other, as violet
    # blocks carrying both numbers
    out.append("<h3>Numbers that do not agree</h3>")
    parts = d["ballots26_sum"].get("Alaska")
    if parts is not None:
        out.append(f'<p class="bigflag"><a href="states/{states["Alaska"]["slug"]}/index.html">'
                   f'Alaska</a>\'s election summary report prints three '
                   f'different totals for ballots cast: 215,912 in its '
                   f'header, 215,906 in its Senate section, and '
                   f'{parts:,} in its Governor section — the figure its '
                   f'40 district numbers add up to.</p>')
    for st in ("North Carolina", "Delaware"):
        row = next((r for r in d["flag_rows"]
                    if r["scope"] == "state" and r["state"] == st
                    and r["flag_label"] in ("Two published totals",
                                            "Two published series")), None)
        if row:
            snt = _link_state(esc(flag_sentence(d, row, states[st])), st, states)
            out.append(f'<p class="bigflag">{snt}</p>')
    blocks.append("\n".join(out))
    # the blocks compose in columns across a wide screen; the
    # side-by-side history table (third block) spans both columns
    grid = ['<div class="pgrid">']
    for i, b in enumerate(blocks):
        cls = "pblock wide" if i == 2 else "pblock"
        grid.append(f'<div class="{cls}">{b}</div>')
    grid.append('</div>')
    return "\n".join(['<h2 id="patterns">Patterns</h2>'] + grid)

def front_adds_lines(d, states, counties_by_state):
    """The front-page "What doesn't add up" lines, built from the data:
    counts of people first, each line linked to the page behind it."""
    lines = []
    op = over_pop(d, counties_by_state)
    for st, entries in sorted(op.items()):
        for row in entries:
            lines.append(f'<a href="counties/{states[st]["slug"]}/{row["slug"]}/index.html">'
                         f'{esc(row["name"])}, {esc(st)}</a> — '
                         f'{row["reg"]:,} registered voters; {row["pop"]:,} '
                         'residents estimated for July 2025.')
    for r in ak_geo.over_total_population(d["roll_ak"]):
        lines.append(f'<a href="states/alaska/index.html#districts">'
                     f'Alaska {esc(r["district"])}</a> — '
                     f'{int(r["registered_voters"]):,} registered voters in 2026, '
                     f'{int(r["total_population_2020"]):,} residents counted in '
                     '2020 on the same district boundaries.')
    # offices that published two different totals for the same thing
    for row in d["flag_rows"]:
        if row["scope"] == "state" and row["flag_label"] in (
                "Two published totals", "Two published series"):
            snt = esc(flag_sentence(d, row, states[row["state"]]))
            lines.append(_link_state(snt, row["state"], states))
    # states with no official registration total
    for st in ("Ohio", "Maine"):
        row = d["state_flags"].get((st, "registered_voters"))
        if row:
            snt = esc(flag_sentence(d, row, states[st]))
            lines.append(_link_state(snt, st, states))
    # ballots published, no registration total published
    mi = states.get("Michigan")
    if mi and mi["registered"] is None and mi["ballots"] is not None:
        lines.append(f'<a href="states/{mi["slug"]}/index.html">Michigan</a>'
                     f' — {mi["ballots"]:,} ballots counted so far. '
                     f'No registration total has been published.')
    # states whose voter lists outnumber their adults (2020 counts)
    for nm in sorted(states):
        s = states[nm]
        if (s["reg_pct_est"] or 0) > 100:
            lines.append(f'<a href="states/{s["slug"]}/index.html">'
                         f'{esc(nm)}</a> — {s["registered"]:,} registered '
                         f'voters, {s["est_adults"]:,} adults estimated for July 2025.')
    # a published figure that counts active voters only, full roll larger
    for st, sr in d["splits"].items():
        if st not in states: continue
        act, tot = num(sr["registered_active"]), num(sr["registered_total"])
        if act and tot and states[st]["registered"] == act and tot > act:
            lines.append(f'<a href="states/{states[st]["slug"]}/index.html">'
                         f'{esc(st)}</a> — the published registration number '
                         f'({act:,}) counts active voters only. The full '
                         f'voter list is {tot:,}.')
    # Minnesota's voter list against 2022, from the history comparison
    for r in d["anoms"]:
        if r["state"] == "Minnesota" and r["measure"] == "registered_voters":
            r26, r22 = _first_int(r["value_2026"]), _first_int(r["value_2022"])
            if r26 and r22:
                lines.append(f'<a href="states/{states["Minnesota"]["slug"]}/index.html">'
                             f'Minnesota</a> — registered voters: {r26:,} '
                             f'in 2026; {r22:,} in 2022.')
    # a count its own office has not finished
    row = d["state_flags"].get(("California", "ballots_cast"))
    if row:
        snt = esc(flag_sentence(d, row, states["California"]))
        lines.append(_link_state(snt, "California", states))
    # ballots numbers that are top-race vote totals, one line for all
    tr = [r["state"] for r in d["flag_rows"] if r["flag_label"] == "Top-race votes"]
    if tr:
        names = ", ".join(
            f'<a href="states/{states[s]["slug"]}/index.html">{esc(s)}</a>'
            for s in tr)
        lines.append(f'In {len(tr)} states the ballots number is the votes '
                     f'for the top race, not a count of ballots: {names}.')
    return lines

def state_adds_lines(d, s, counties_by_state):
    """The state-page "What doesn't add up" lines: only what is true for
    this state, in plain sentences."""
    st = s["name"]
    lines = []
    for row in d["flag_rows"]:
        if row["scope"] == "state" and row["state"] == st:
            lines.append(flag_sentence(d, row, s))
    if (s["reg_pct_est"] or 0) > 100:
        lines.append(f"{st} has more registered voters than adults who "
                     f"live there: {s['registered']:,} registered voters, "
                     f"{s['est_adults']:,} adults estimated for July 2025.")
    op = over_pop(d, counties_by_state).get(st, [])
    if op:
        top = max(op, key=lambda e: e["reg"] / e["pop"])
        if len(op) == 1:
            lines.append(f"1 county in {st} has more registered voters "
                         f"than residents — the most is {top['name']}: "
                         f"{top['reg']:,} registered, {top['pop']:,} residents estimated for July 2025.")
        else:
            lines.append(f"{len(op)} counties in {st} have more registered "
                         f"voters than residents — the most is {top['name']}: "
                         f"{top['reg']:,} registered, {top['pop']:,} residents estimated for July 2025.")
    if st == "Alaska":
        for r in ak_geo.over_total_population(d["roll_ak"]):
            reg = int(r["registered_voters"])
            pop = int(r["total_population_2020"])
            lines.append(f"Alaska {r['district']} has {reg:,} registered "
                         f"voters in 2026 and {pop:,} residents counted in "
                         "2020 on the same district boundaries.")
    if st == "Pennsylvania":
        lines.append("In Bedford County, the parts of the state's own "
                     "feed — Election Day, mail, and provisional votes — "
                     "add up to 46 fewer votes than the totals printed "
                     "on the same rows: 14 on one candidate's row, 30 "
                     "on another, 2 on the third. Every other county's "
                     "rows add up exactly.")
    if st == "Virginia":
        lines.append("Fairfax County cast 481,742 ballots by its own "
                     "county's summary; the votes in the Senate race "
                     "add up to 478,783. These are different measures, not a missing-ballot count. Both source readings are retained.")
    if st == "Georgia":
        lines.append("In Fulton County, the state's own export prints "
                     "the winning candidate's county total as 337,159, "
                     "while her precinct figures in the same export add "
                     "up to 337,156 — 3 apart. The county total is the "
                     "one shown on this page; nothing has been adjusted.")
    if st == "New York":
        lines.append("Westchester County's figure — 338,393 — is "
                     "incomplete as published. The State Board's site "
                     "carries this warning, word for word: \"Please be "
                     "advised that these results do not include a "
                     "significant number of unscanned emergency Election "
                     "Day ballots from Westchester County. Accordingly, "
                     "the results are incomplete and are subject to "
                     "change as additional ballots are scanned and "
                     "tabulated.\"")
    return lines

def alaska_geography_note():
    """Keep boundary vintage and the retained legacy inputs visible."""
    return ('<p class="small" id="alaska-geography">Alaska district comparisons '
            'use <a class="cite" href="' + esc(ak_geo.SOURCE_URL) + '">'
            '2020 Census adult populations retabulated to 2024 district '
            'boundaries</a>, matching the <a class="cite" href="' +
            esc(ak_geo.BOUNDARIES_URL) + '">final 2023 House plan</a>. '
            'The ratios compare registration from 2026 with the population '
            'age 18 and over counted in 2020. '
            'The original ak-district-vap-2020 and ak-district-roll-integrity '
            'files remain available unchanged, but their population figures '
            'use the previous 2013 districts. Their ratios and the Alaska '
            'row in county-anomalies.csv must not be reused for current '
            'district comparisons. See ALASKA-GEOGRAPHY.md in the source '
            'files for the extraction and validation record.</p>')

NAT_HIST_KEY = {"2014": "eac-eavs-2014", "2016": "eac-eavs-2016",
                "2018": "international-idea-turnout", "2020": "eac-eavs-2020",
                "2022": "eac-eavs-2022-report", "2024": "eac-eavs-2024-report"}

def national_history_table(d):
    """The national past-election series (turnout-history-national.csv)
    as two single-subject tables: ballots and voter lists first, then
    turnout against each labeled denominator. A figure no source
    published stays blank (—)."""
    # 2026, computed at build time from the project's own collection
    # (turnout-2026-11-03.csv, state election offices). Each sum covers
    # only the jurisdictions that published that figure; the turnout
    # percentages use matched sets — never the two grand sums divided.
    bal = {s: ballot_value(state_measure(s, r, d["state_flags"].get((s, "ballots_cast")))[0], num(r["ballots_cast"])) for s, r in d["turnout"].items()}
    reg = {s: num(r["registered_voters"]) for s, r in d["turnout"].items()}
    bset = {s: v for s, v in bal.items() if v is not None}
    rset = {s: v for s, v in reg.items() if v is not None}
    both = set(bset) & set(rset)
    t_reg26 = 100.0 * sum(bset[s] for s in both) / sum(rset[s] for s in both)
    matched_adults = {s: num(d["est_state"][s]["adults_18plus"]) for s in bset if s in d["est_state"] and num(d["est_state"][s]["adults_18plus"])}
    t_vap26 = (100.0 * sum(bset[s] for s in matched_adults) / sum(matched_adults.values())) if matched_adults else None
    counts = ["<h3>Ballots and voter lists</h3>",
              "<table><tr><th>Year</th><th class='l'>Election</th>"
              "<th>Ballots cast</th><th>Registered voters</th></tr>"]
    turnout = ["<h3>Turnout</h3>",
               "<table><tr><th>Year</th><th class='l'>Election</th>"
               "<th>Turnout % of registered</th><th>Turnout % of adults</th>"
               "<th>Turnout % of eligible voters</th></tr>"]
    for r in d["hist_nat"]:
        k = NAT_HIST_KEY.get(r["election_year"])
        t_reg, t_vap, t_vep = (fnum(r["turnout_pct_registered"]),
                               fnum(r["turnout_pct_vap"]),
                               fnum(r["turnout_pct_vep"]))
        counts.append(
            f'<tr><td>{esc(r["election_year"])}</td>'
            f'<td class="l">{esc(r["election_type"].capitalize())}</td>'
            f'<td>{linked(d, k, fmt_int(num(r["ballots_cast"])))}</td>'
            f'<td>{linked(d, k, fmt_int(num(r["registered_voters"])))}</td></tr>')
        turnout.append(
            f'<tr><td>{esc(r["election_year"])}</td>'
            f'<td class="l">{esc(r["election_type"].capitalize())}</td>'
            f'{band_td(linked(d, k, fmt_pct(t_reg)), t_reg)}'
            f'{band_td(linked(d, "census-cps-voting", fmt_pct(t_vap)), t_vap)}'
            f'{band_td(linked(d, "uf-election-lab-turnout", fmt_pct(t_vep)), t_vep)}</tr>')
    counts.append(
        f'<tr><td>2026</td><td class="l">Partial reporting states; not comparable to completed national totals. Ballot coverage: {len(bset)}; registration coverage: {len(rset)}; matched turnout: {len(both)}.</td>'
        f'<td>{fmt_int(sum(bset.values()))}</td>'
        f'<td>{fmt_int(sum(rset.values()))}</td></tr>')
    counts.append("</table>")
    turnout.append(
        f'<tr><td>2026</td><td class="l">Partial reporting states; not comparable to completed national totals. Ballot coverage: {len(bset)}; registration coverage: {len(rset)}; matched turnout: {len(both)}.</td>'
        f'<td>{fmt_pct(t_reg26)}</td>'
        f'<td>{fmt_pct(t_vap26)}</td>'
        f'{fill_td("—", GREY)}</tr>')
    turnout.append("</table>")
    srcs = ['<p class="src">Ballots cast and registered voters: '
            'U.S. Election Assistance Commission, EAVS reports. '
            'Turnout % of adults: U.S. Census Bureau, Current '
            'Population Survey. Turnout % of eligible voters: '
            'UF Election Lab.</p>',
            '<p class="src">2026: state election offices, November 3, 2026 '
            'general election — the count is still going. Ballots cast is '
            f'counted so far in the {len(bset)} states that have published '
            f'a total; registered voters covers the {len(rset)} jurisdictions '
            f'that have published one. Turnout % of registered uses only '
            f'the {len(both)} jurisdictions that published both figures; '
            'turnout % of adults uses matching reporting states and the July 2025 '
            'Census Bureau adult population estimates, not an extrapolated 2026 population. No turnout % of '
            'eligible voters has been published for 2026.</p>']
    return "\n".join(counts + turnout + srcs)

def past_days_table_html(d):
    """PAST-ELECTION-DAYS.md rendered as published: national numbers as
    known on each past Election Day, with the file's own sources and
    caveats lines."""
    tbl, srcs, cavs = d["past_days"]
    if not tbl: return ""
    out = ["<table><tr>" + "".join(
        f'<th class="l">{esc(c)}</th>' if i == 0 else f"<th>{esc(c)}</th>"
        for i, c in enumerate(tbl[0])) + "</tr>"]
    for row in tbl[1:]:
        out.append("<tr>" + "".join(
            f'<td class="l">{esc(c)}</td>' if i == 0 else f"<td>{esc(c)}</td>"
            for i, c in enumerate(row)) + "</tr>")
    out.append("</table>")
    if srcs: out.append(f'<p class="src">Sources: {esc(srcs)}</p>')
    if cavs: out.append(f'<p class="src">Caveats: {esc(cavs)}</p>')
    return "\n".join(out)

ANOM_MEASURES = {"ballots": ("Ballots cast", False),
                 "registered_voters": ("Registered voters", False),
                 "turnout_pct_registered": ("Turnout % of registered", True),
                 "ballots_pct_of_vap": ("Ballots % of adults", True)}

def anoms_rows_html(rows, with_state=False):
    """Keep archived values, withholding unverified cross-election deltas."""
    archive_labels = {
        "ballots": ("Election count (archived; count types may differ)", False),
        "registered_voters": ("Registered voters (archived; coverage may differ)", False),
        "turnout_pct_registered": ("Recorded count / registered (%) — archived, not comparable turnout", True),
        "ballots_pct_of_vap": ("Recorded count / adults (%) — archived, bases may differ", True),
    }
    out = []
    for r in rows:
        label, is_pct = archive_labels.get(r["measure"], (r["measure"] + " (archived)", False))
        def v(x):
            x = (x or "").strip()
            if not x: return "—"
            return esc(x) + ("%" if is_pct and not x.endswith("%") else "")
        st = f'<td class="l">{esc(r["state"])}</td>' if with_state else ""
        unavailable = '<td title="Comparable measures, coverage and reporting status have not been verified">Not comparable</td>'
        out.append(f'<tr>{st}<td class="l">{esc(label)}</td>'
                   f'<td>{v(r["value_2026"])}</td><td>{v(r["value_2022"])}</td>'
                   f'<td>{v(r["value_2018"])}</td>{unavailable}{unavailable}</tr>')
    return out

ANOMS_SRC = ('<p class="src">Archived values from anomalies-vs-history.csv. '
             '2026 figures were recorded from preliminary state reports with '
             'different dates, coverage and count types. Earlier figures come '
             'from EAVS reports and state election offices. No comparable '
             'change is established by placing these values side by side. '
             'Original values and earlier calculated differences remain in '
             'the downloadable source file; those differences are not validated '
             'comparisons or evidence of wrongdoing.</p>')

DEM_BLUE = "#2563eb"  # party color: blue is a Democrat's, here as everywhere
REP_RED = "#dc2626"   # party color: red is a Republican's

def ballots_basis(d, s):
    """The plain label for what a state's 2026 ballots figure is,
    from the record's own flags and status: a top-race vote total
    is labeled as one, an unfinished count says so."""
    return s.get("count_label", "Ballots cast")


def count_summary_rows(d, s):
    """A state's headline count as a small table: the ballots figure
    under its own label, the voter list and the adults as the two
    real counts, and the filled share cell. The same figures the
    state page's count tables carry — nothing computed anew."""
    if s["registered"] is None:
        reg_txt = "No registration" if s["name"] == "North Dakota" else "—"
    else:
        reg_txt = fmt_int(s["registered"])
    pct_td, _r = pct_td_html(d, s["reg_pct_est"], None)
    return ("<table>"
            f'<tr><td class="l">{esc(ballots_basis(d, s))}</td>'
            f'<td>{fmt_int(s["published_count"])}</td></tr>'
            f'<tr><td class="l">Registered voters</td><td>{reg_txt}</td></tr>'
            f'<tr><td class="l">Adults (July 2025 estimate)</td><td>{fmt_int(s["est_adults"])}</td></tr>'
            f'<tr><td class="l">Registered % of adults</td>{pct_td}</tr>'
            "</table>")

# Race states whose governor rows carry no verified statewide
# figures: six with no official figures published yet (collection
# notes).
GOV26_NO_VERIFIED = {"Illinois", "Maine", "Massachusetts",
                     "New Hampshire", "Wisconsin"}

def _gov_party(raw):
    """The plain party word for a governor-results party string, and
    its color where party is the meaning: blue for a Democrat, red
    for a Republican, no color for anyone else."""
    low = (raw or "").strip().lower()
    if "democratic-farmer-labor" in low:
        return "Democratic-Farmer-Labor", DEM_BLUE
    if low in ("d", "dem") or "dem" in low or low.startswith("(d)"):
        return "Democrat", DEM_BLUE
    if low in ("r", "rep") or "rep" in low or low.startswith("(r)"):
        return "Republican", REP_RED
    if low == "ind": return "Independent", None
    if "constitution" in low: return "Constitution", None
    return (raw or "").strip(), None

def _gov_party_span(raw):
    word, color = _gov_party(raw)
    if color: return f'<span style="color:{color}">{word}</span>'
    return esc(word)

def _gov_name(raw):
    """A candidate name as printed in the file; a name printed in
    all capitals is set in ordinary case, nothing else changed."""
    n = (raw or "").strip()
    if n and n.upper() == n and any(c.isalpha() for c in n):
        return n.title()
    return n

def gov_line_html(d, st):
    """The governor line for one state, shared by the front panel
    and the state page's Election Day block. Figures come from
    governor-results-2026.csv: verified rows print the winner, the
    runner-up and both vote counts with the file's status and date;
    Alaska and Kansas print both leaders and 'Not called', never a
    winner; race states without verified figures print the standing
    sentence and nothing from the file. Flip wording the Election
    Day record already carries stays, and the file's figures govern
    where both cover a state. States with no 2026 Governor's race
    and no line in the record get no line."""
    dem = f'<span style="color:{DEM_BLUE}">Democrat</span>'
    rep = f'<span style="color:{REP_RED}">Republican</span>'
    flip = None
    if st in d["gov_flips"] and st != "Alaska":
        flip = (f"Governor — the office changed from {rep} to {dem}. "
                f"{esc(d['gov_flips'][st])}, a {dem}, won.")
    row = d["gov26"].get(st)
    if row is None:
        if flip: return flip
        if st == "Alaska" and "Alaska" in d["gov_flips"]:
            return (f"Governor — projected for "
                    f"{esc(d['gov_flips']['Alaska'])}, a {dem}. "
                    f"Not yet called.")
        if st == "Kansas" and \
                "Kansas governor: not yet called" in d["baseline_text"]:
            return (f"Governor — not called. The {dem} is narrowly "
                    f"ahead. A {dem} held the office going in.")
        return ""
    status = (row["status"] or "").strip()
    wv, rv = num(row["winner_votes"]), num(row["runner_up_votes"])
    if "uncalled" in status.lower():
        line = (f"Governor — not called. "
                f"{esc(_gov_name(row['winner']))} "
                f"({_gov_party_span(row['winner_party'])}) leads with "
                f"{wv:,} votes; {esc(_gov_name(row['runner_up']))} "
                f"({_gov_party_span(row['runner_up_party'])}) has "
                f"{rv:,}.")
        if st == "Kansas":
            line += f" A {dem} held the office going in."
        line += f" Unofficial, as of {fmt_date(row['as_of'])}."
        return line
    if st in GOV26_NO_VERIFIED or wv is None or rv is None:
        sent = ("Governor: no verified statewide figures in the "
                "record yet.")
        return f"{flip} {sent}" if flip else sent
    status_disp = status[:1].upper() + status[1:]
    if flip:
        return (f"{flip} {esc(_gov_name(row['winner']))} received "
                f"{wv:,} votes; {esc(_gov_name(row['runner_up']))} "
                f"received {rv:,}. {esc(status_disp)}, as of "
                f"{fmt_date(row['as_of'])}.")
    return (f"Governor — {esc(_gov_name(row['winner']))} "
            f"({_gov_party_span(row['winner_party'])}) won with "
            f"{wv:,} votes. {esc(_gov_name(row['runner_up']))} "
            f"({_gov_party_span(row['runner_up_party'])}) received "
            f"{rv:,}. {esc(status_disp)}, as of "
            f"{fmt_date(row['as_of'])}.")

def panel_gov_html(d, name):
    """A front-panel governor line — the same governor line the
    state page's Election Day block carries."""
    inner = gov_line_html(d, name)
    return f'<div class="govline">{inner}</div>' if inner else ""

# Senate seats that changed from Republican to Democratic, each
# verified on the state's own figures (senate-results-2026-notes.md,
# previous-holder table). Maine's alleged flip is not among them:
# the state has published no statewide tabulation.
SEN26_FLIPS = {"Iowa", "Kansas", "North Carolina", "Ohio",
               "South Carolina", "Texas"}

def senate_line_html(d, st):
    """The U.S. Senate line for one state, shared by the front
    panel and the state page's Election Day block, in the governor
    line's style. Figures come from senate-results-2026.csv:
    verified rows print the winner, the runner-up and both vote
    counts with the file's status and date, and a seat that
    changed party says so in the governor line's changed-office
    wording; Alaska prints both leaders and 'not called', never a
    winner, with its ranked-choice tabulation date; Mississippi,
    still counting with no state-published total, says so; race
    states without verified figures print the standing sentence
    and nothing from the file; states with no 2026 Senate race
    say so. DC elects no Senator and has no row — it prints the
    standing sentence, as a race state without figures does."""
    dem = f'<span style="color:{DEM_BLUE}">Democrat</span>'
    rep = f'<span style="color:{REP_RED}">Republican</span>'
    row = d["sen26"].get(st)
    if row is None:
        return ("U.S. Senate: no verified statewide figures in the "
                "record yet.")
    status = (row["status"] or "").strip()
    if status == "No Senate race in 2026":
        return "U.S. Senate — no race in 2026."
    if st == "Mississippi":
        return ("U.S. Senate — still counting; the state has "
                "published no statewide total yet.")
    wv, rv = num(row["winner_votes"]), num(row["runner_up_votes"])
    if "uncalled" in status.lower():
        line = (f"U.S. Senate — not called. "
                f"{esc(_gov_name(row['winner']))} "
                f"({_gov_party_span(row['winner_party'])}) leads with "
                f"{wv:,} votes; {esc(_gov_name(row['runner_up']))} "
                f"({_gov_party_span(row['runner_up_party'])}) has "
                f"{rv:,}.")
        line += (" The ranked-choice count lands November 18, "
                 "2026 — in it, ballots for last-place candidates "
                 "move to each voter's next choice.")
        line += f" Unofficial, as of {fmt_date(row['as_of'])}."
        return line
    if wv is None or rv is None:
        return ("U.S. Senate: no verified statewide figures in the "
                "record yet.")
    status_disp = status[:1].upper() + status[1:]
    if st in SEN26_FLIPS:
        flip = (f"U.S. Senate — the seat changed from {rep} to "
                f"{dem}. {esc(_gov_name(row['winner']))}, a {dem}, "
                f"won.")
        return (f"{flip} {esc(_gov_name(row['winner']))} received "
                f"{wv:,} votes; {esc(_gov_name(row['runner_up']))} "
                f"received {rv:,}. {esc(status_disp)}, as of "
                f"{fmt_date(row['as_of'])}.")
    return (f"U.S. Senate — {esc(_gov_name(row['winner']))} "
            f"({_gov_party_span(row['winner_party'])}) won with "
            f"{wv:,} votes. {esc(_gov_name(row['runner_up']))} "
            f"({_gov_party_span(row['runner_up_party'])}) received "
            f"{rv:,}. {esc(status_disp)}, as of "
            f"{fmt_date(row['as_of'])}.")

def panel_senate_html(d, name):
    """A front-panel Senate line — the same Senate line the state
    page's Election Day block carries."""
    inner = senate_line_html(d, name)
    return f'<div class="govline">{inner}</div>' if inner else ""

USPS_BY_NAME = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ",
    "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
    "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY"}

def _split_plain(raw):
    """A House file split ('9 REP / 5 DEM', '8 REP / 43 DEM / 1 IND',
    '20 REP / 7 DEM / 1 VACANT') in plain words, party words colored
    as everywhere on the site: '9 Republicans, 5 Democrats'."""
    dem = f'<span style="color:{DEM_BLUE}">Democrats</span>'
    rep = f'<span style="color:{REP_RED}">Republicans</span>'
    words = {"REP": rep, "DEM": dem, "IND": "Independents",
             "VACANT": "vacant seats"}
    one = {"REP": f'<span style="color:{REP_RED}">Republican</span>',
           "DEM": f'<span style="color:{DEM_BLUE}">Democrat</span>',
           "IND": "Independent", "VACANT": "vacant seat"}
    parts = []
    for seg in (raw or "").split(" / "):
        n, _, code = seg.strip().partition(" ")
        if not n.isdigit() or code not in words: return esc(raw or "")
        parts.append(f"{n} {one[code] if int(n) == 1 else words[code]}")
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + ", and " + parts[-1]
    return "".join(parts)

def house_line_html(d, st):
    """The U.S. House delegation line for one state, shared by the
    front panel and the state page's Election Day block, in the
    governor line's style and at exactly the strength of
    house-results-2026.csv: a delegation whose districts are all
    counted prints its split before and after; a partly counted
    state prints how many of its districts are counted and names
    the ones not called; an uncalled at-large seat prints its
    leader; a state with no district results in the record says
    so, with the delegation it seated going in."""
    row = d["house"].get(st)
    if row is None: return ""
    if st == "District of Columbia":
        return ("U.S. House — the District elects a non-voting "
                "delegate; that race is not in the record yet.")
    seats = row["seats"]
    after = (row["split_after"] or "").strip()
    if after:
        line = (f"U.S. House — all {seats} districts counted: "
                f"{_split_plain(after)}.")
        chg = (row["change"] or "").strip()
        if chg.startswith("+"):
            k = chg.split()[0][1:]
            line += (f" {k} seat{'s' if k != '1' else ''} changed "
                     f"from Republican to Democratic.")
        line += (f" Going in: {_split_plain(row['split_before'])}. "
                 f"Unofficial, as of {fmt_date(row['as_of'])}.")
        return line
    counted = [r for r in d["house_districts"]
               if r["state"] == USPS_BY_NAME.get(st)]
    decided = [r for r in counted
               if r["result"] == "hold" or r["result"].startswith("flip")]
    if decided:
        nd = sum(1 for r in decided if r["winner_party"] == "DEM")
        nr = sum(1 for r in decided if r["winner_party"] == "REP")
        dem = f'<span style="color:{DEM_BLUE}">Democrats</span>'
        rep = f'<span style="color:{REP_RED}">Republicans</span>'
        line = (f"U.S. House — {len(decided)} of {seats} districts "
                f"counted: {nd} {dem}, {nr} {rep}.")
        unc = (row["uncalled_districts"] or "").strip()
        if unc:
            parts = [x.strip() for x in unc.split(";") if x.strip()]
            if len(parts) == 1:
                line += f" {parts[0]} is not called yet."
            else:
                nums = [p.replace("District ", "") for p in parts]
                line += (f" Districts {', '.join(nums[:-1])} and "
                         f"{nums[-1]} are not called yet.")
        line += f" Unofficial, as of {fmt_date(row['as_of'])}."
        return line
    unc = [r for r in counted if "not called" in (r["result"] or "")]
    if unc:
        r = unc[0]
        w = _gov_name(r["winner"])
        wp = _gov_party_span(
            {"REP": "Republican", "DEM": "Democratic"}.get(
                r["winner_party"], r["winner_party"]))
        line = (f"U.S. House — not called. {esc(w)} ({wp}) leads "
                f"with {num(r['winner_votes']):,} votes.")
        if st == "Alaska":
            line += (" The ranked-choice count lands November 18, "
                     "2026 — in it, ballots for last-place "
                     "candidates move to each voter's next choice.")
        line += f" Unofficial, as of {fmt_date(row['as_of'])}."
        return line
    return (f"U.S. House — no district results in the record yet. "
            f"Going in: {_split_plain(row['split_before'])}.")

def panel_house_html(d, name):
    """A front-panel House line — the same House line the state
    page's Election Day block carries."""
    inner = house_line_html(d, name)
    return f'<div class="govline">{inner}</div>' if inner else ""

def house_ed_lines(d):
    """The national U.S. House picture in plain lines, at exactly
    the strength of house-results-2026.csv and its notes: the
    division as seated before Election Day (Clerk of the House,
    November 2, 2026), the districts verified so far with their
    flips, and the control arithmetic — 117 verified districts do
    not make a chamber, and the lines never present them as one."""
    decided = [r for r in d["house_districts"]
               if r["result"] == "hold" or r["result"].startswith("flip")]
    nd = sum(1 for r in decided if r["winner_party"] == "DEM")
    nr = sum(1 for r in decided if r["winner_party"] == "REP")
    flips = sum(1 for r in decided if r["result"].startswith("flip"))
    dem = f'<span style="color:{DEM_BLUE}">Democrats</span>'
    rep = f'<span style="color:{REP_RED}">Republicans</span>'
    return [
        "U.S. House before Election Day: 218 Republicans, "
        "214 Democrats, 1 Independent, and 2 vacant seats. All "
        "435 seats were voted on.",
        f"Counted so far: {len(decided)} of the 435 districts — "
        f"{nd} {dem}, {nr} {rep}. {flips} seats changed from "
        f"Republican to Democratic; none changed the other way.",
        "Control of the House is not decided on the counted "
        "results: 318 districts are still outstanding — 313 not "
        "yet in the record and 5 not called: Alaska's seat (voted "
        "on by the whole state), North Carolina Districts 3, 5 "
        "and 7, and South Carolina District 2.",
    ]

def state_panel_html(d, s, br, cr):
    """One state's panel for the front map, embedded in the page's
    static HTML for all 51 states and shown beside the map when the
    state is tapped: its governor result where the record carries
    one, its 2026 count, and — for the map's two economy shadings —
    its economy rank and direction in that view."""
    st = s["name"]
    if st == "District of Columbia":
        rank_line = ('<p class="small">District of Columbia is not '
                     'ranked.</p>')
    else:
        rank_line = (f'<p class="small">Economy rank — Election '
                     f'Day: {br[st]} of 50 · today: {cr[st]} of 50. '
                     f'The rank is built from all fourteen numbers '
                     f'in this panel.</p>')
    econ_block = (rank_line + ed_rows_table(econ_rows(d, st))
                  + ECON_SRC)
    return (f'<div class="spanel" id="sp-{s["slug"]}" hidden>'
            f'<h3>{esc(st)}</h3>'
            + panel_gov_html(d, st)
            + panel_senate_html(d, st)
            + panel_house_html(d, st)
            + f'<div class="pview pv-list">{count_summary_rows(d, s)}</div>'
            + econ_block
            + f'<p class="small"><a href="states/{s["slug"]}/index.html">'
              'Full record</a></p></div>')

# The one script on the site, on the front page only: tapping a
# state on the map opens its panel beside the map instead of
# leaving the page, and the year switch recolors the map's county
# shading. Every figure it shows is already in the page's static
# HTML; the year switch only recolors paths already drawn.
FRONT_SCRIPT = """<script>
(function(){
  var panels = {};
  var list = document.querySelectorAll('.spanel');
  for (var i = 0; i < list.length; i++) panels[list[i].id.slice(3)] = list[i];
  var hint = document.getElementById('panelhint');
  var nat = document.getElementById('natpanel');
  var current = null;
  function show(slug){
    var p = panels[slug];
    if (!p) return;
    if (current) current.hidden = true;
    current = p;
    p.hidden = false;
    if (hint) hint.hidden = true;
    if (nat) nat.hidden = true;
    if (window.innerWidth < 1024)
      document.getElementById('statepanel').scrollIntoView({block: 'nearest'});
  }
  var links = document.querySelectorAll('.maptoggle .map a');
  for (var i = 0; i < links.length; i++){
    (function(a){
      a.addEventListener('click', function(ev){
        var m = (a.getAttribute('href') || '').match(/states\\/([^/]+)\\//);
        if (m && panels[m[1]]){ ev.preventDefault(); show(m[1]); }
      });
    })(links[i]);
  }
  // the year switch for the map's county shading: one code per
  // county per year, carried in the page; the state shading does
  // not change — the voter lists carry no year. A county whose
  // ballots exceed its adults is redrawn on top, solid violet,
  // in whichever year is shown.
  var ydata = null;
  var yd = document.getElementById('yeardata');
  if (yd) { try { ydata = JSON.parse(yd.textContent); } catch (e) {} }
  var cpaths = document.querySelectorAll('.maptoggle path.cb');
  var strongG = document.getElementById('cstrong');
  var YCOL = {'0': '#9ca3af', '1': '#bfe0cc', '2': '#f5e3a1',
              '4': '#7C3AED'};
  function paintYear(y){
    var s = ydata && ydata[y];
    if (!s || s.length !== cpaths.length) return;
    if (strongG) while (strongG.firstChild)
      strongG.removeChild(strongG.firstChild);
    for (var i = 0; i < cpaths.length; i++){
      var code = s.charAt(i);
      cpaths[i].setAttribute('fill', YCOL[code] || '#9ca3af');
      if (code === '4' && strongG){
        var cl = cpaths[i].cloneNode(true);
        cl.setAttribute('class', 'cs');
        strongG.appendChild(cl);
      }
    }
    var my = document.getElementById('mapyr');
    if (my) my.textContent = y;
  }
  var yradios = document.querySelectorAll('input[name="fyrsw"]');
  for (var j = 0; j < yradios.length; j++)
    yradios[j].addEventListener('change', function(){
      if (this.checked) paintYear(this.id.replace('fyr', ''));
    });
})();
</script>"""

def national_panel_html(d, states):
    """The panel beside the front map before any state is tapped:
    the country's headline numbers — the voter lists and the adults
    they are counted against, added up from the states that have
    published a figure, and the over-the-line county count on the
    measured base. Never an empty box."""
    matched = [s for s in states.values()
               if s["registered"] is not None and s["est_adults"]]
    reg = sum(s["registered"] for s in matched)
    vap = sum(s["est_adults"] for s in matched)
    pct = reg / vap * 100 if vap else None
    pct_td = band_td(fmt_pct(pct), pct)
    olc = current_over_line_counts(d)
    n_over = sum(x for x, _ in olc.values())
    n_meas = sum(y for _, y in olc.values())
    return (f'<div class="spanel" id="natpanel">'
            f'<h3>The country</h3>'
            f'<p class="bigflag">{n_over} of the {n_meas:,} counties '
            f'measured have more registered voters than adults '
            f'in the July 2025 estimates.</p>'
            f'<table>'
            f'<tr><td class="l">Registered voters</td>'
            f'<td>{reg:,}</td></tr>'
            f'<tr><td class="l">Adults (July 2025 estimate)</td>'
            f'<td>{vap:,}</td></tr>'
            f'<tr><td class="l">Registered % of adults</td>'
            f'{pct_td}</tr>'
            f'</table>'
            f'<p class="small">Registered voters: the states that '
            f'have published a statewide figure and a comparable adult estimate, added up on both sides. North '
            f'Dakota does not register voters.</p>'
            f'<p class="small">Tap a state on the map for its '
            f'numbers.</p></div>')

def build_front(d, states, counties_by_state):
    jump = [("map", "The Map"), ("election-day", "Election Day"),
            ("patterns", "Patterns"), ("states", "Every state"),
            ("record", "Latest updates")]
    mods = ['<section class="finder" aria-label="Find a place">'
            '<h1>Find the numbers for your community.</h1>'
            '<p>Explore election records by state and county, compare places, '
            'and follow each figure to its source.</p>'
            '<form action="states/index.html" method="get"><div class="field">'
            '<label for="find-state">Start with a state</label>'
            '<input id="find-state" name="q" type="search" '
            'placeholder="State name or abbreviation" autocomplete="off">'
            '</div><button type="submit">Find my state</button></form>'
            '<p class="context-note">Choose your state, then search its counties.</p></section>'
            '<nav class="explore-grid" aria-label="Explore records">'
            '<a href="#election-day"><span>Election results</span><small>Governors, Senate & House</small></a>'
            '<a href="rankings/index.html"><span>Compare states</span><small>See places side by side</small></a>'
            '<a href="data/index.html"><span>Go to the source</span><small>Read & download the records</small></a></nav>']
    # one map, leading the front page at the full width of its
    # module; beside it, the country's numbers before any tap, then
    # a panel per state (all 51 in the static HTML) that the one
    # front-page script swaps in when a state is tapped
    br, cr = econ_ranks(d)
    panels = "".join(state_panel_html(d, states[n], br, cr)
                     for n in sorted(states))
    mods.append(mod("\n".join([
        '<h2 id="map">The Map</h2>',
        '<div class="mapflex frontmap"><div class="mapcol">',
        front_map_block(d, states),
        '</div><div class="panelcol" id="statepanel">',
        national_panel_html(d, states),
        panels,
        '</div></div>']), cls=" modmap"))
    # Election Day — who won: the governors, the Senate and the
    # House as plain summary lines, then the country's headline
    # figures as cards (the full national table lives on the
    # Data page)
    seg = ['<h2 id="election-day">Election Day — who won</h2>',
           '<p class="edsub">Election Day — Tuesday, November 3, 2026</p>',
           "<h3>Governors</h3>", cards_html(governor_ed_cards(d))]
    gm = re.search(r"Going in: (\d+) D / (\d+) R governors\. "
                   r"For 2027: (\d+) D / (\d+) R", d["baseline_text"])
    if gm:
        seg.append(f'<p class="small">Going in, {gm.group(1)} governors '
                   f'were Democrats and {gm.group(2)} were Republicans. '
                   f'For 2027: {gm.group(3)} Democrats, {gm.group(4)} '
                   f'Republicans, Kansas not decided.</p>')
    seg.append("<h3>U.S. Senate</h3>")
    for ln in senate_ed_lines(d):
        seg.append(f'<p class="small">{ln}</p>')
    seg.append("<h3>U.S. House</h3>")
    for ln in house_ed_lines(d):
        seg.append(f'<p class="small">{ln}</p>')
    seg.append('<details class="record-details"><summary>National economic indicators</summary>')
    seg.append(cards_html(national_ed_cards(d)))
    seg.append("</details>")
    mods.append(mod("\n".join(seg)))
    # pattern summaries built from the joins already in the data
    mods.append(mod(patterns_html(d, states, counties_by_state)))
    # the states list: names, linked — the every-state table with its
    # numbers lives on the States page; the rankings summaries ride
    # in the same module
    seg = ['<h2 id="states">Every state</h2>',
           '<p class="small">Every state with its numbers: '
           '<a href="states/index.html">States — the full table</a></p>',
           '<div class="statelist">']
    for name in sorted(states):
        s = states[name]
        seg.append(f'<a href="states/{s["slug"]}/index.html">{esc(name)}</a>')
    seg.append('</div>')
    ranked = [s for s in states.values() if s["bal_pct_est"] is not None and s["name"] != "District of Columbia"]
    ranked.sort(key=lambda s: -s["bal_pct_est"])
    if ranked:
        top, bot = ranked[0], ranked[-1]
        seg.append(f'<p class="small">Ranked by ballots for every '
                   f'100 adults, {esc(top["name"])} stands first at '
                   f'{fmt_pct(top["bal_pct_est"])} and '
                   f'{esc(bot["name"])} last at '
                   f'{fmt_pct(bot["bal_pct_est"])} — every state '
                   f'ranked: <a href="rankings/index.html">Rankings</a></p>')
    mods.append(mod("\n".join(seg)))
    # the record: the latest entries on the front page; the full
    # dated record lives on the Data page
    seg = ['<h2 id="record">The record</h2><div class=\'log\'>']
    for ln in list(reversed(d["log_lines"]))[:3]:
        seg.append(f"<div>{esc(ln)}</div>")
    seg.append("</div>")
    seg.append('<p class="small">The full record: '
               '<a href="data/index.html#record">Data — the record</a></p>')
    seg.append('<p class="small"><a href="data/index.html">Data</a> · '
               '<a href="definitions/index.html">Definitions</a></p>')
    mods.append(mod("\n".join(seg)))
    # Keep the complete record in the document; let readers choose supporting sections.
    for index, label in ((1, "Explore the map"), (3, "Compare published figures"),
                         (4, "Browse all states"), (5, "Latest record updates")):
        mods[index] = '<details class="supporting-record home-section"><summary>' + label + '</summary>' + mods[index] + '</details>'
    write("index.html", page("Open Tally",
                             "\n".join(mods) + "\n" + FRONT_SCRIPT,
                             depth=0, jump=jump, yearbar=("fyr", YEARS)))

def build_states_page(d, states):
    """The States page: the every-state count table that used to sit
    on the front page, unchanged — State | Registered | Ballots cast |
    Adults (July 2025 estimate) | Ballots % of adults, every figure cited as before."""
    ranked = [s for s in states.values()
              if s["bal_pct_est"] is not None
              and s["name"] != "District of Columbia"]
    ranked.sort(key=lambda s: -s["bal_pct_est"])
    body = ['<div class="crumb"><a href="../index.html">Open Tally</a></div>',
            "<h1>States & Counties</h1>", '<p>Ballot columns exclude race votes, returned ballots and voter estimates. Open a state for every original count with its measure and reporting date.</p>',
            '<p>Find a state, then open its county directory. Search by name or postal abbreviation.</p>', MEASURE_NOTE]
    if ranked:
        top, bot = ranked[0], ranked[-1]
        body.append(tline(
            f"Among states with a recorded ballot count (reporting dates and completeness differ), "
            f"{esc(top['name'])} has the most recorded ballots for "
            f"every 100 adults — {fmt_pct(top['bal_pct_est'])} — "
            f"and {esc(bot['name'])} the fewest, "
            f"{fmt_pct(bot['bal_pct_est'])}."))
    body.append("<table data-filter-table='states'><tr><th class='l'>State</th><th>Registered</th>"
                "<th>Ballots cast</th><th>Adults (July 2025 estimate)</th>"
                "<th>Ballots % of adults</th></tr>")
    for name in sorted(states):
        s = states[name]
        rk, bk = reg_key(d, name), bal_key(d, name)
        if s["registered"] is not None:
            reg_cell, _ = flagged(d, name, "registered_voters",
                                  linked(d, rk, fmt_int(s["registered"])))
        else:
            reg_cell = "No registration" if name == "North Dakota" else "—"
        if s["ballots"] is not None:
            bal_cell, _ = flagged(d, name, "ballots_cast",
                                  linked(d, bk, fmt_int(s["ballots"])))
        else:
            bal_cell = fmt_int(s["ballots"])
        body.append(
            f'<tr data-search="{esc(name)}" data-abbreviation="{USPS_BY_NAME.get(name, "")}"><td class="l"><a href="{s["slug"]}/index.html">{esc(name)}</a><br><a class="small" href="{s["slug"]}/index.html#counties">Find a county</a></td>'
            f'<td>{reg_cell}</td><td>{bal_cell}</td>'
            f'<td>{est_num_html(s["est_adults"], s["est_url"])}</td>'
            f'{band_td(linked(d, bk, fmt_pct(s["bal_pct_est"])), s["bal_pct_est"])}</tr>')
    body.append("</table>")
    body.append('<p class="small">Rankings: <a href="../rankings/index.html">Rankings</a>'
                ' · Downloads: <a href="../data/index.html">Data</a></p>')
    write("states/index.html", page("States & Counties", "\n".join(body), depth=1))

def build_rankings_page(d, states):
    """The Rankings page: the full ranking tables — every state ranked
    by ballots % of adults, and the state economy rankings for
    Election Day and today that used to sit on the front page."""
    body = ['<div class="crumb"><a href="../index.html">Open Tally</a></div>',
            "<h1>Compare states</h1>", MEASURE_NOTE, '<p>Only recorded ballot counts enter this ranking. Race votes, returned ballots and estimated voter counts are excluded. Reporting dates and count completion differ; rankings are not final turnout comparisons.</p>']
    ranked = [s for s in states.values() if s["bal_pct_est"] is not None and s["name"] != "District of Columbia"]
    ranked.sort(key=lambda s: -s["bal_pct_est"])
    ranks, prev, rk_ = {}, None, 0
    for i, s in enumerate(ranked):
        if s["bal_pct_est"] != prev: rk_ = i + 1; prev = s["bal_pct_est"]
        ranks[s["name"]] = rk_
    body.append("<h2>Ballots % of adults — every state</h2>")
    if ranked:
        top, bot = ranked[0], ranked[-1]
        body.append(tline(
            f"All {len(ranked)} states ranked by ballots cast for "
            f"every 100 adults. {esc(top['name'])} stands first at "
            f"{fmt_pct(top['bal_pct_est'])}; {esc(bot['name'])} "
            f"stands last at {fmt_pct(bot['bal_pct_est'])}."))
    body.append("<table><tr><th>Rank</th><th class='l'>State</th>"
                "<th>Ballots % of adults</th><th>Ballots cast</th>"
                "<th>Adults (July 2025 estimate)</th></tr>")
    for s in ranked:
        bk = bal_key(d, s["name"])
        bal_r, _ = flagged(d, s["name"], "ballots_cast",
                           linked(d, bk, fmt_int(s["ballots"])))
        body.append(f'<tr><td>{ranks[s["name"]]}</td>'
                    f'<td class="l"><a href="../states/{s["slug"]}/index.html">{esc(s["name"])}</a></td>'
                    f'{band_td(linked(d, bk, fmt_pct(s["bal_pct_est"])), s["bal_pct_est"])}'
                    f'<td>{bal_r}</td>'
                    f'<td>{est_num_html(s["est_adults"], s["est_url"])}</td></tr>')
    body.append("</table>")
    body.append('<p class="small">District of Columbia is not ranked.</p>')
    body.append("<h2>State economies</h2>")
    body.append(econ_rank_tables(d, states, prefix="../"))
    body.append(econ_full_tables(d, states))
    write("rankings/index.html", page("Compare states", section_index("\n".join(body)), depth=1))

def build_state_pages(d, states, counties_by_state, county_info):
    hist = {}
    for r in d["hist_states"]:
        hist.setdefault(r["state"], []).append(r)
    roll_co_de = d["roll_by_county"]
    reg_rows = d["reg_by_county"]
    for name, s in states.items():
        hist_by_year = {r["election_year"]: r for r in hist.get(name, [])}
        seg_map = [f'<div class="crumb"><a href="../../index.html">Overview</a> · <a href="../index.html">States & Counties</a></div>', f"<h1>{esc(name)}</h1>"]
        # one map leads the state page: the shaded county map where the
        # state has one; the state's own outline in its band color only
        # where there is no county map to show
        clist = counties_by_state.get(name, [])
        fills, fips_names = {}, {}
        has_roll = any(roll_co_de.get((name, c["_nkey"])) for c in clist)
        map_note = "County shading uses resident age-18+ estimates for July 1, 2025."
        for c in clist:
            key = (name, c["_nkey"])
            fips_names[c["county_fips"]] = c["county_name"]
            if has_roll:
                rr = roll_co_de.get(key)
                pct = current_county_pct(d, key)
                fills[c["county_name"]] = VIOLET if (pct or 0) > 100 else band(pct)
            elif name == "Alaska":
                fills[c["county_name"]] = GREY
            else:
                # no 2026 county roll for this state: shade the 2024
                # county figures from the EAVS history file, labeled
                hr = d["hist_by_fips"].get((name, c["county_fips"]))
                vapc = num(c["voting_age_population_2020"])
                if name == "North Dakota":
                    v24 = num(hr["ballots_2024"]) if hr else None
                else:
                    v24 = num(hr["reg_2024"]) if hr else None
                pct = round(v24 / vapc * 100, 1) if (v24 and vapc) else None
                fills[c["county_name"]] = VIOLET if (pct or 0) > 100 else band(pct)
        if not has_roll and name != "Alaska":
            map_note = ("County shading: 2024 ballots / 2020 Census adults (historical comparison)."
                        if name == "North Dakota" else
                        "County shading: 2024 — registered voters "
                        "for every 100 adults counted in the 2020 Census (historical comparison).")
        county_links = {c["county_name"]:
                        f'../../counties/{s["slug"]}/{c["_slug"]}/index.html'
                        for c in clist}
        cmap = state_map(name, fips_names, fills, county_links)
        # on a wide screen the module composes sideways: the county
        # map on the left, the state's count summary beside it
        seg_map.append('<div class="mapflex"><div class="mapcol">')
        if cmap:
            # the county map is this page's map — a separate state
            # outline above it would draw the same state twice
            outline = cmap
            seg_map.append(cmap.replace("<svg ", '<svg id="map" ', 1))
        else:
            outline_fill = (VIOLET if (s["reg_pct_est"] or 0) > 100
                            else band(s["reg_pct_est"]))
            outline = state_outline_map(name, outline_fill)
            if outline:
                outline = outline.replace("<svg ", '<svg id="map" ', 1)
            seg_map.append(outline)
        if map_note:
            seg_map.append(f'<p class="src">{map_note}</p>')
        if name == "North Dakota":
            seg_map.append('<div class="legend">Ballots per 100 adults: '
                        f'{chip(80)}Under 90 &nbsp; {chip(95)}90 – 100 &nbsp; '
                        f'{vchip()}More ballots than adults in the population denominator shown '
                        f'&nbsp; {chip(None)}No data</div>')
        else:
            seg_map.append(LEGEND)
        seg_map.append('</div>')
        seg_map.append(f'<div class="mapsum"><h3>Count summary</h3>'
                       f'{count_summary_rows(d, s)}</div>')
        seg_map.append('</div>')
        ed = state_ed_html(d, s)
        seg_adds = []
        adds = state_adds_lines(d, s, counties_by_state)
        if adds:
            adds_title = "Published comparisons"
            seg_adds.append(f'<h2 id="adds">{esc(adds_title)}</h2><div class="adds">')
            for ln in adds: seg_adds.append(f"<div>{esc(ln)}</div>")
            seg_adds.append("</div>")
        # --- The count, with the year switch: 2026 in front, then the
        # past cycles; each pane carries that year's state figures and
        # its county map, so counts and shading move together ---
        seg_count = ['<h2 id="count">The count</h2>']
        rk, bk = reg_key(d, name), bal_key(d, name)
        if s["registered"] is not None:
            reg_html, reg_flag = flagged(d, name, "registered_voters",
                                         linked(d, rk, fmt_int(s["registered"])))
        else:
            reg_html = "No registration" if name == "North Dakota" else "—"
            reg_flag = None
        if s["ballots"] is not None:
            bal_html, bal_flag = flagged(d, name, "ballots_cast",
                                         linked(d, bk, fmt_int(s["ballots"])))
        else:
            bal_html, bal_flag = fmt_int(s["ballots"]), None
        pct_td, pct_rule = pct_td_html(d, s["reg_pct_est"], rk)
        cvr = d["cvap_roll"].get(name)
        cvap_rows = ""
        if cvr:
            cvap_td, _cr = pct_td_html(d, fnum(cvr["pct_of_cvap"]), None)
            cvap_rows = (
                f'<tr><td class="l">Citizen adults (2020–2024)</td>'
                f'<td>{fmt_int(num(cvr["cvap"]))}</td></tr>'
                f'<tr><td class="l">Registered % of citizen adults</td>'
                f'{cvap_td}</tr>')
        fired = [f for f in (reg_flag, bal_flag) if f]
        county_rule = False
        p26 = []
        if (s["reg_pct_est"] or 0) > 100:
            p26.append(tline(
                f"{esc(name)} has more registered voters than "
                f"adults in the population denominator shown: {s['registered']:,} "
                f"registered voters, {s['est_adults']:,} adults."))
        elif s["registered"] is not None and s["ballots"] is not None:
            p26.append(tline(
                f"{s['registered']:,} registered voters and "
                f"{s['ballots']:,} ballots cast, counted against "
                f"{s['est_adults']:,} adults estimated for July 2025."))
        elif s["registered"] is not None:
            p26.append(tline(
                f"{s['registered']:,} registered voters, counted "
                f"against {s['est_adults']:,} adults."))
        elif name == "North Dakota":
            p26.append(tline(
                "North Dakota does not register voters; its count "
                "is ballots against adults."))
        p26.append('<h3>The voter list</h3>')
        p26.append("<table>"
            f'<tr><td class="l">Registered voters</td><td>{reg_html}</td></tr>'
            f'<tr><td class="l">Adults (July 2025 estimate)</td><td>{est_num_html(s["est_adults"], s["est_url"])}</td></tr>'
            f'<tr><td class="l">Registered % of adults</td>{pct_td}</tr>'
            f'<tr><td class="l">Adults (2020 Census, historical)</td><td>{linked(d, "census-pl-94171", fmt_int(s["vap"]))}</td></tr>'
            f'<tr><td class="l">Registered / 2020 adults (historical)</td>{band_td(fmt_pct(s["reg_pct_adults"]), s["reg_pct_adults"])}</tr>'
            + cvap_rows +
            "</table>")
        p26.append(f'<p class="src">Source: {esc(s["source"])}</p>')
        if cvr:
            p26.append(f'<p class="src">Citizen adults — '
                        f'{esc(d["cvap_state"][name]["source"])}.</p>')
        if s["est_adults"]:
            p26.append(f'<p class="src">Adults (2025 estimate) — '
                        f'{esc(s["est_src"])}.</p>')
        p26.append('<h3>Election count and basis</h3>')
        p26.append(f'<p><strong>{esc(s["count_label"])}</strong>: {fmt_int(s["published_count"])}. '
                   'Source description and reporting date: ' + esc(s["source"]) + '</p>')
        if s["count_kind"] not in BALLOT_KINDS:
            p26.append('<p>This figure is preserved, but is not a ballots-cast total. It is excluded from ballot turnout ratios and ballot rankings.</p>')
        p26.append("<table>"
            f'<tr><td class="l">Ballots cast</td><td>{bal_html}</td></tr>'
            f'<tr><td class="l">Ballots / 2020 adults (historical)</td>{band_td(linked(d, bk, fmt_pct(s["bal_pct_adults"])), s["bal_pct_adults"])}</tr>'
            f'<tr><td class="l">Ballots % of adults (2025 estimate)</td>{est_pct_td(s["bal_pct_est"], s["est_url"])}</tr>'
            f'<tr><td class="l">Turnout % of registered</td>{band_td(linked(d, bk, fmt_pct(s["turnout_pct"])), s["turnout_pct"])}</tr>'
            "</table>")
        if s["status"] == "still counting":
            p26.append('<p class="src">Status: still counting.</p>')
        p26.append('<h3>Population</h3>')
        p26.append("<table>"
            f'<tr><td class="l">Population (2020 Census)</td><td>{linked(d, "census-2020-apportionment", fmt_int(s["census_pop"]))}</td></tr>'
            f'<tr><td class="l">Registered % of population</td>{band_td(linked(d, rk, fmt_pct(s["pct_census_registered"])), s["pct_census_registered"])}</tr>'
            f'<tr><td class="l">Ballots % of population</td>{band_td(linked(d, bk, fmt_pct(s["pct_census_ballots"])), s["pct_census_ballots"])}</tr>'
            "</table>")
        if name == "Alaska":
            p26.append('<p class="src">Alaska reports by House '
                       'district — see House Districts below.</p>')
        elif has_roll:
            p26.append('<p class="src">County map for 2026: top of '
                       'this page.</p>')
        elif name == "North Dakota":
            p26.append('<p class="src">No county figures published '
                       'for 2026.</p>')
        else:
            p26.append('<p class="src">No county voter lists '
                       'published for 2026.</p>')

        def past_pane(year):
            parts = []
            row = hist_by_year.get(year)
            if row is not None:
                hk = hist_key_for_year(d, name, year)
                regv = num(row["registered_voters"])
                balv = num(row["ballots_cast"])
                tp = fnum(row["turnout_pct_registered"])
                reg_html_y = ("No registration" if regv is None
                              and name == "North Dakota"
                              else linked(d, hk, fmt_int(regv)))
                parts.append("<table>"
                    f'<tr><td class="l">Registered voters</td><td>{reg_html_y}</td></tr>'
                    f'<tr><td class="l">Ballots cast</td><td>{linked(d, hk, fmt_int(balv))}</td></tr>'
                    f'<tr><td class="l">Turnout % of registered</td>{band_td(linked(d, hk, fmt_pct(tp)), tp)}</tr>'
                    "</table>")
                parts.insert(0, tline(
                    f"In {year}, {esc(name)} recorded "
                    f"{fmt_int(regv)} registered voters and "
                    f"{fmt_int(balv)} ballots cast."))
            elif name == "Alaska" and year in d["ak_eavs"]:
                regv, balv = d["ak_eavs"][year]
                tp = (round(balv / regv * 100, 1)
                      if (regv and balv is not None) else None)
                parts.append("<table>"
                    f'<tr><td class="l">Registered voters</td><td>{fmt_int(regv)}</td></tr>'
                    f'<tr><td class="l">Ballots cast</td><td>{fmt_int(balv)}</td></tr>'
                    f'<tr><td class="l">Turnout % of registered</td>{band_td(fmt_pct(tp), tp)}</tr>'
                    "</table>")
                parts.insert(0, tline(
                    f"In {year}, Alaska recorded {fmt_int(regv)} "
                    f"registered voters and {fmt_int(balv)} ballots "
                    f"cast."))
                parts.append('<p class="src">Alaska is one statewide '
                             'jurisdiction in the federal survey — '
                             'U.S. Election Assistance Commission, '
                             'Election Administration and Voting '
                             'Survey.</p>')
            elif (name, year) in d["eavs_sums"]:
                e = d["eavs_sums"][(name, year)]
                tp = (round(e["mbal"] / e["mreg"] * 100, 1)
                      if e["mreg"] else None)
                reg_html_y = ("No registration" if e["reg"] is None
                              and name == "North Dakota"
                              else fmt_int(e["reg"]))
                parts.append("<table>"
                    f'<tr><td class="l">Registered voters</td><td>{reg_html_y}</td></tr>'
                    f'<tr><td class="l">Ballots cast</td><td>{fmt_int(e["bal"])}</td></tr>'
                    f'<tr><td class="l">Turnout % of registered</td>{band_td(fmt_pct(tp), tp)}</tr>'
                    "</table>")
                parts.insert(0, tline(
                    f"In {year}, {esc(name)}'s counties add up to "
                    f"{fmt_int(e['reg'])} registered voters and "
                    f"{fmt_int(e['bal'])} ballots cast."))
                cov = ""
                if tp is not None and e["nmatch"] < e["nc"]:
                    cov = (f' — {e["nmatch"]} of the {e["nc"]} '
                           f'counties in this sum, holding '
                           f'{fmt_int(e["mreg"])} of the '
                           f'{fmt_int(e["reg"])} registered voters '
                           f'added up above')
                parts.append('<p class="src">State figures added up '
                             'from this state\'s counties in the '
                             'federal survey file — U.S. Election '
                             'Assistance Commission, Election '
                             'Administration and Voting Survey. '
                             'Turnout uses the counties that published '
                             f'both figures{cov}.</p>')
            else:
                return f"<p>No data published for {year}.</p>"
            # the year's county map rides in its own list: where a
            # pane carries both a table and a map, the two compose
            # side by side on a wide screen (paneflex)
            mparts = []
            if name == "Alaska":
                parts.append(f'<p class="src">No county figures '
                             f'published for {year} — Alaska reports '
                             f'as one statewide jurisdiction.</p>')
            elif year == "2024" and not has_roll:
                parts.append('<p class="src">County map for 2024: top '
                             'of this page.</p>')
            else:
                yfills = {}
                any_data = False
                for c in clist:
                    hr = hist_county_row(d, name, c["county_fips"], year)
                    rg_y, bl_y = hist_county_vals(hr, year)
                    v = bl_y if name == "North Dakota" else rg_y
                    if v is not None: any_data = True
                    vapc = num(c["voting_age_population_2020"])
                    pct = (round(v / vapc * 100, 1)
                           if (v is not None and vapc) else None)
                    yfills[c["county_name"]] = (VIOLET if (pct or 0) > 100
                                                else band(pct))
                if not any_data:
                    parts.append(f'<p class="src">No county figures '
                                 f'published for {year}.</p>')
                elif name == "North Dakota":
                    mparts.append(f'<p class="src">County shading: '
                                 f'{year} — ballots per 100 adults counted in the 2020 Census (historical baseline).</p>')
                    mparts.append(state_map(name, fips_names, yfills,
                                           county_links))
                    mparts.append('<div class="legend">Ballots per 100 adults: '
                                 f'{chip(80)}Under 90 &nbsp; {chip(95)}90 – 100 &nbsp; '
                                 f'{vchip()}More ballots than adults in the population denominator shown '
                                 f'&nbsp; {chip(None)}No data</div>')
                else:
                    mparts.append(f'<p class="src">County shading: '
                                 f'{year} — registered voters for '
                                 f'every 100 adults counted in the 2020 Census (historical baseline).</p>')
                    mparts.append(state_map(name, fips_names, yfills,
                                           county_links))
                    mparts.append(LEGEND)
            body = "\n".join(parts)
            if mparts:
                return (f'<div class="paneflex"><div class="panecol">'
                        f'{body}</div><div class="panecol">'
                        + "\n".join(mparts) + '</div></div>')
            return body

        panes = [("2026", "\n".join(p26))]
        for y in EAVS_YEARS:
            panes.append((y, past_pane(y)))
        seg_count.append(year_switch(panes))
        cite_keys = []
        for k in (rk, bk, "census-pl-94171", "census-2020-apportionment"):
            if k and k not in cite_keys: cite_keys.append(k)
        if name in hist:
            for k in d["citemap"].get(("turnout-history-states.csv", name), []):
                if k not in cite_keys: cite_keys.append(k)
        cites = " · ".join(
            f'<a class="cite" href="{esc(d["citations"][k]["url"])}">'
            f'{esc(d["citations"][k]["publisher"])} — {esc(d["citations"][k]["title"])}</a>'
            for k in cite_keys if k in d["citations"])
        seg_count.append(f'<p class="src">Citations: {cites}</p>')
        # 2026 next to past elections (series states): its own module
        seg_past = []
        if name in hist:
            arows = [r for r in d["anoms"] if r["state"] == name]
            if arows:
                seg_past.append('<h2 id="next-to-past">2026 next to past elections</h2>')
                _at = anoms_tline(arows)
                if _at: seg_past.append(tline(_at))
                seg_past.append("<table><tr><th class='l'>Measure</th><th>2026</th>"
                            "<th>2022</th><th>2018</th><th>Change from 2022</th>"
                            "<th>Change from 2018</th></tr>")
                seg_past.extend(anoms_rows_html(arows))
                seg_past.append("</table>")
                seg_past.append(ANOMS_SRC)
        # counties
        seg_counties = ['<h2 id="counties">Counties</h2>',
                        '<p class="small">Search for a county or county equivalent. Open its name for the full record and past elections.</p>']
        est_any = any(d["est_by_county"].get((name, c["_nkey"])) for c in clist)
        has_b26 = any(d["ballots26_by_county"].get((name, c["_nkey"])) for c in clist)
        _cvals = []
        for c in clist:
            _gr = reg_rows.get((name, c["_nkey"]))
            _reg = num(_gr["registered_voters"]) if _gr else None
            _er = d["est_by_county"].get((name, c["_nkey"]))
            _vap = num(_er["adults_18plus"]) if _er else None
            if _reg is not None and _vap:
                _cvals.append((c["county_name"], _reg,
                               _reg / _vap * 100))
        if _cvals:
            _top = max(_cvals, key=lambda x: x[2])
            _over = sum(1 for v in _cvals if v[2] > 100)
            _tl = (f"{len(_cvals)} counties with a published voter "
                   f"list. {esc(_top[0])} has the most registered "
                   f"voters for every 100 adults estimated for July 2025 — {_top[2]:.1f}.")
            if _over:
                _tl += (f" {_over} counties have more registered "
                        f"voters than adults in the population denominator shown.")
            seg_counties.append(tline(_tl))
        elif has_b26:
            seg_counties.append(tline(
                f"{len(clist)} counties, with their 2026 {esc(BALLOTS26_LABEL[name])} "
                f"beside their adults. No county voter lists "
                f"published for 2026."))
        else:
            seg_counties.append(tline(
                f"{len(clist)} counties. No county figures "
                f"published for 2026."))
        seg_counties.append("<table data-filter-table='counties'><tr><th class='l'>County</th><th>Registered</th><th>Adults (July 2025 estimate)</th><th>Registered % of adults (July 2025 estimate)</th>"
                    + (f"<th>{esc(BALLOTS26_LABEL[name])}</th>" if has_b26 else "")
                    + ("<th>Adults (2020 Census, historical)</th><th>Registered / 2020 adults (historical)</th>" if est_any else "")
                    + ("<th>Registered % of citizen adults</th>" if has_roll else "")
                    + "</tr>")
        ck = county_reg_key(d, name)
        county_csv_rows = []
        for c in clist:
            key = (name, c["_nkey"])
            rr = roll_co_de.get(key)
            gr = reg_rows.get(key)
            reg = num(gr["registered_voters"]) if gr else None
            pct = current_county_pct(d, key)
            reg_c = linked(d, ck, fmt_int(reg)) if reg is not None else fmt_int(reg)
            pct_td_c, fired_rule = pct_td_html(d, pct, ck)
            if fired_rule: county_rule = True
            cvap_cell = ""
            if has_roll:
                cv = d["cvap_by_fips"].get(c["county_fips"])
                cpct = round(reg / cv * 100, 1) if (reg and cv) else None
                cc_td, _r = pct_td_html(d, cpct, None)
                cvap_cell = cc_td
            er = d["est_by_county"].get(key)
            ea = num(er["adults_18plus"]) if er else None
            eurl = er["source_url"] if er else ""
            est_cell = ""
            if est_any:
                er = d["est_by_county"].get(key)
                ea = num(er["adults_18plus"]) if er else None
                epct = round(reg / ea * 100, 1) if (reg and ea) else None
                eurl = er["source_url"] if er else ""
                old_adults = num(c["voting_age_population_2020"])
                old_pct = (reg / old_adults * 100 if reg is not None and old_adults else None)
                est_cell = (f'<td>{linked(d, "census-pl-94171", fmt_int(old_adults))}</td>'
                            f'{band_td(fmt_pct(old_pct), old_pct)}')
            bal26_cell = ""
            if has_b26:
                brow = d["ballots26_by_county"].get(key)
                bv = num(brow["ballots_cast"]) if brow else None
                if brow and bv is not None:
                    bal26_cell = (f'<td><a class="cite" href="{esc(brow["source_url"])}">'
                                  f'{fmt_int(bv)}</a></td>')
                else:
                    bal26_cell = "<td>—</td>"
            _csv_row = [c["county_name"],
                        "" if reg is None else reg,
                        "" if ea is None else ea,
                        "" if pct is None else pct]
            if has_b26:
                _csv_row.append("" if bv is None else bv)
            if est_any:
                _csv_row += ["" if old_adults is None else old_adults,
                             "" if old_pct is None else old_pct]
            if has_roll:
                _csv_row.append("" if cpct is None else cpct)
            county_csv_rows.append(_csv_row)
            seg_counties.append(f'<tr><td class="l"><a href="../../counties/{s["slug"]}/{c["_slug"]}/index.html">{esc(c["county_name"])}</a></td>'
                        f'<td>{reg_c}</td><td>{est_num_html(ea, eurl)}</td>'
                        f'{pct_td_c}{bal26_cell}{est_cell}{cvap_cell}</tr>')
        seg_counties.append("</table>")
        # the counties table as a file beside the page — exactly the
        # rows the table shows, in the same order and columns
        _hdr = ["County", "Registered", "Adults (July 2025 estimate)",
                "Registered % of adults (July 2025 estimate)"]
        if has_b26: _hdr.append(BALLOTS26_LABEL[name])
        if est_any: _hdr += ["Adults (2020 Census, historical)",
                             "Registered / 2020 adults (historical)"]
        if has_roll: _hdr.append("Registered % of citizen adults")
        _buf = io.StringIO()
        _w = csv.writer(_buf)
        _w.writerow(_hdr)
        _w.writerows(county_csv_rows)
        write(f'states/{s["slug"]}/counties.csv', _buf.getvalue())
        seg_counties.append('<p class="small"><a href="counties.csv">'
                            'Download this table (CSV)</a></p>')
        if name != "Alaska":
            note26 = ballots26_note(d, name)
            if note26: seg_counties.append(note26)
        if name == "Alaska":
            seg_counties.append('<h2 id="districts">House Districts</h2>')
            _ax = sum(1 for r in d["roll_ak"]
                      if (fnum(r["registered_pct_of_vap"]) or 0) > 100)
            seg_counties.append(tline(
                f"Alaska reports by its {len(d['roll_ak'])} House "
                f"districts, not by county. {_ax} districts have "
                f"2026 registration totals above their 2020 adult "
                f"populations, using the same district boundaries."))
            seg_counties.append(alaska_geography_note())
            seg_counties.append("<table><tr><th class='l'>District</th><th>Registered</th><th>Adults (2020)</th><th>Registered % of adults</th><th>Ballots cast</th></tr>")
            ak_ck = county_reg_key(d, "Alaska")
            for r in sorted(d["roll_ak"], key=lambda x: int(x["district"].split()[-1])):
                pct = fnum(r["registered_pct_of_vap"])
                pct_td_a, fired_rule = pct_td_html(d, pct, ak_ck)
                if fired_rule: county_rule = True
                seg_counties.append(f'<tr><td class="l">{esc(r["district"])}</td><td>{linked(d, ak_ck, fmt_int(num(r["registered_voters"])))}</td>'
                            f'<td><a class="cite" href="{esc(ak_geo.SOURCE_URL)}">{fmt_int(num(r["voting_age_population_2020"]))}</a></td>'
                            f'{pct_td_a}<td>{fmt_int(d["ak_ballots"].get(r["district"]))}</td></tr>')
            seg_counties.append("</table>")
            ak_src = next((r["source"] for r in d["county_reg"] if r["state"] == "Alaska"), "")
            seg_counties.append(f'<p class="src">Source: {esc(plain_src(ak_src))}</p>')
            if ak_ck in d["citations"]:
                cc = d["citations"][ak_ck]
                seg_counties.append(f'<p class="src">Citation: <a class="cite" href="{esc(cc["url"])}">'
                            f'{esc(cc["publisher"])} — {esc(cc["title"])}</a></p>')
            note26 = ballots26_note(d, "Alaska")
            if note26: seg_counties.append(note26)
        seg_tail = []
        extra_jump = []
        extra = state_extra_sections(d, s, collect=extra_jump)
        if extra: seg_tail.append(extra)
        sents = [flag_sentence(d, fr, s) for fr in fired]
        # the over-the-line county count is a headline figure on every
        # measured state's page: X of Y counties (districts in Alaska)
        precise = False
        if name == "Alaska":
            ax = sum(1 for r in d["roll_ak"]
                     if (fnum(r["registered_pct_of_vap"]) or 0) > 100)
            if ax:
                sents.insert(0, f"{ax} of {len(d['roll_ak'])} House "
                                f"districts in Alaska have 2026 registration "
                                f"totals above their 2020 adult populations "
                                f"on the same boundaries.")
                precise = True
        else:
            olc = current_over_line_counts(d).get(name)
            if olc and olc[0]:
                sents.insert(0, f"{olc[0]} of {olc[1]} counties in {name} "
                                f"have more registered voters than adults "
                                f"who live there.")
                if name in active_only_states(d):
                    sents.insert(1, f"{name}'s county figures count "
                                    f"active voters only; the full "
                                    f"voter list is larger.")
                precise = True
        if pct_rule or county_rule:
            if (s["reg_pct_est"] or 0) > 100:
                sents.append(f"{name} has more registered voters than adults "
                             f"who live there: {s['registered']:,} registered "
                             f"voters, {s['est_adults']:,} adults.")
            elif not precise:
                sents.append(f"Some counties in {name} have more registered "
                             f"voters than adults in the population denominator shown.")
        fb = flags_block(sents, anchor="flags")
        if fb: seg_tail.append(fb)
        # assemble the screen-sized modules in page order: the
        # state's Election Day story leads (its name, its governor,
        # Senate and House lines), then the map with the count
        # summary, then the detail
        head = seg_map[:2]
        seg_map_body = seg_map[2:]
        mods = ["\n".join(head)]
        mods.append('<a class="county-shortcut" href="#counties">Find a county in ' + esc(name) + ' <span aria-hidden="true">↓</span></a>')
        mods.append(mod("\n".join(seg_count)))
        mods.append('<details class="supporting-record"><summary>Explore the county map</summary>' + mod("\n".join(seg_map_body)) + "</details>")
        mods.append(mod("\n".join(seg_counties)))
        if ed:
            mods.append('<details class="supporting-record"><summary>Election Day results & economic context</summary>' + mod(ed) + '</details>')
        if seg_adds: mods.append(mod("\n".join(seg_adds)))
        if seg_past: mods.append('<details class="supporting-record"><summary>Compare past elections</summary>' + mod("\n".join(seg_past)) + "</details>")
        if seg_tail: mods.append(mod("\n".join(seg_tail)))
        # the cleaned top jump bar: the page's main sections only,
        # at most five, in page order
        jump = []
        if ed: jump.append(("election-day", "Results & context"))
        if outline: jump.append(("map", "Map"))
        jump.append(("count", "The count"))
        if seg_past: jump.append(("next-to-past", "Past elections"))
        jump.append(("counties", "Find a county"))
        jump.extend(extra_jump)
        if fb: jump.append(("flags", "Data notes"))
        write(f'states/{s["slug"]}/index.html',
              page(name, "\n".join(mods), depth=2, src_html=footer_src(d, rk),
                   jump=jump,
                   yearbar=("yr", [y for y, _h in panes])))

def build_county_pages(d, states, counties_by_state):
    roll_co_de = d["roll_by_county"]
    reg_rows = d["reg_by_county"]
    n = 0
    for name, clist in counties_by_state.items():
        s = states[name]
        for c in clist:
            key = (name, c["_nkey"])
            rr = roll_co_de.get(key); gr = reg_rows.get(key)
            reg = num(gr["registered_voters"]) if gr else None
            pct = current_county_pct(d, key)
            ck = county_reg_key(d, name)
            reg_c = linked(d, ck, fmt_int(reg)) if reg is not None else fmt_int(reg)
            pct_td_c, fired_rule = pct_td_html(d, pct, ck, bare_none=True)
            er = d["est_by_county"].get(key)
            ea = num(er["adults_18plus"]) if er else None
            epop = num(er["total_population"]) if er else None
            epct = round(reg / ea * 100, 1) if (reg and ea) else None
            pop = num(c["total_population_2020"])
            vap = num(c["voting_age_population_2020"])
            # the 2026 pane: this county's Election Day table, as it
            # has always rendered
            tbl = [f'<tr><td class="l">State</td><td class="l"><a href="../../../states/{s["slug"]}/index.html">{esc(name)}</a></td></tr>',
                   f'<tr><td class="l">Population (2020)</td><td>{linked(d, "census-pl-94171", fmt_int(pop))}</td></tr>']
            if er:
                tbl.append(f'<tr><td class="l">Population (2025 estimate)</td><td>{est_num_html(epop, er["source_url"])}</td></tr>')
            tbl.append(f'<tr><td class="l">Adults (2020)</td><td>{linked(d, "census-pl-94171", fmt_int(vap))}</td></tr>')
            if er:
                tbl.append(f'<tr><td class="l">Adults (2025 estimate)</td><td>{est_num_html(ea, er["source_url"])}</td></tr>')
            tbl.append(f'<tr><td class="l">Registered voters</td><td>{reg_c}</td></tr>')
            tbl.append(f'<tr><td class="l">Registered % of adults (July 2025 estimate)</td>{pct_td_c}</tr>')
            if reg is not None and vap:
                old_pct = reg / vap * 100
                tbl.append(f'<tr><td class="l">Registered / 2020 adults (historical)</td>{band_td(fmt_pct(old_pct), old_pct)}</tr>')
            brow = d["ballots26_by_county"].get(key)
            bval = num(brow["ballots_cast"]) if brow else None
            if brow is not None and bval is not None:
                tbl.append(f'<tr><td class="l">{esc(BALLOTS26_LABEL[name])}</td>'
                           f'<td><a class="cite" href="{esc(brow["source_url"])}">{fmt_int(bval)}</a></td></tr>')
            cv = d["cvap_by_fips"].get(c["county_fips"])
            if reg and cv:
                cpct = round(reg / cv * 100, 1)
                cc_td, _cf = pct_td_html(d, cpct, ck, bare_none=True)
                tbl.append(f'<tr><td class="l">Citizen adults (2020–2024)</td><td>{fmt_int(cv)}</td></tr>')
                tbl.append(f'<tr><td class="l">Registered % of citizen adults</td>{cc_td}</tr>')
            current_sources = []
            if gr:
                current_sources.append(f'<p class="src">Registered — Who is counted: {esc(gr["basis"])} · {esc(fmt_date(gr["report_date"]))}</p>')
                current_sources.append(f'<p class="src">Source: {esc(plain_src(gr["source"]))}</p>')
                if ck in d["citations"]:
                    cc = d["citations"][ck]
                    current_sources.append(f'<p class="src">Citation: <a class="cite" href="{esc(cc["url"])}">'
                                f'{esc(cc["publisher"])} — {esc(cc["title"])}</a></p>')
            current_sources.append(f'<p class="src">Adults — <a class="cite" href="{esc(PL_URL)}">U.S. Census Bureau</a>, 2020 Census Redistricting Data (PL 94-171), Table P3</p>')
            if er:
                current_sources.append(f'<p class="src">2025 estimates — {esc(er["source"])}.</p>')
            if reg and cv:
                current_sources.append(f'<p class="src">Citizen adults — {esc(d["cvap_county_src"])}</p>')
            if brow is not None and bval is not None:
                current_sources.append(f'<p class="src">{esc(BALLOTS26_LABEL[name])} — {esc(brow["source"])}</p>')
            panes = [("2026", "<table>" + "".join(tbl) + "</table>" + "".join(current_sources))]
            # past cycles on the same switch, from the federal
            # survey's county files; a year the county published
            # nothing for stays empty, never filled
            any_eavs = False
            for year in EAVS_YEARS:
                hr = hist_county_row(d, name, c["county_fips"], year)
                rg, bl = hist_county_vals(hr, year)
                if rg is None and bl is None:
                    panes.append((year, f"<p>No data published for {year}.</p>"))
                    continue
                any_eavs = True
                hk = EAVS_KEY.get(year)
                if hk not in d["citations"]: hk = None
                hpct = round(rg / vap * 100, 1) if (rg and vap) else None
                hpct_td, _hf = pct_td_html(d, hpct, hk, bare_none=True)
                tp = round(bl / rg * 100, 1) if (rg and bl is not None) else None
                reg_html_y = ("No registration" if rg is None
                              and name == "North Dakota"
                              else linked(d, hk, fmt_int(rg)))
                pane = ("<table>"
                    f'<tr><td class="l">Registered voters</td><td>{reg_html_y}</td></tr>'
                    f'<tr><td class="l">Registered / 2020 adults (historical)</td>{hpct_td}</tr>'
                    f'<tr><td class="l">Ballots cast</td><td>{linked(d, hk, fmt_int(bl))}</td></tr>'
                    f'<tr><td class="l">Turnout % of registered</td>{band_td(fmt_pct(tp), tp)}</tr>'
                    "</table>")
                if hr.get("notes"):
                    pane += f'<p class="src">{esc(hr["notes"])}</p>'
                if hk:
                    cc = d["citations"][hk]
                    pane += (f'<p class="src">{year} source: '
                             f'<a class="cite" href="{esc(cc["url"])}">'
                             f'{esc(cc["publisher"])} — {esc(cc["title"])}</a></p>')
                pane += '<p class="src">Adult denominator: U.S. Census Bureau, 2020 Census, residents age 18+.</p>'
                panes.append((year, pane))
            body = [f'<div class="crumb"><a href="../../../index.html">Overview</a> · <a href="../../../states/index.html">States & Counties</a> · <a href="../../../states/{s["slug"]}/index.html#counties">{esc(name)}</a></div>',
                    f"<h1>{esc(c['county_name'])}</h1>",
                    '<details class="supporting-record"><summary>2026 overview & population context</summary>',
                    '<p class="context-note">Overview: 2026 election records. Select a different year in The count below.</p>']
            if reg and epop and reg > epop:
                body.append(f'<p class="bigflag">More registered voters '
                            f'than estimated residents: {reg:,} registered, {epop:,} '
                            f'residents estimated for July 2025.</p>')
            elif reg and ea and reg > ea:
                body.append(f'<p class="bigflag">More registered voters '
                            f'than estimated adults: {reg:,} registered, {ea:,} '
                            f'adults estimated for July 2025.</p>')
            # the county's numbers in context, before the tables:
            # its voter list against its adults, and where that
            # share stands among the counties measured in its state
            brow0 = d["ballots26_by_county"].get(key)
            bval0 = num(brow0["ballots_cast"]) if brow0 else None
            if reg is not None and pct is not None and ea:
                peers = [current_county_pct(d, (name, c2["_nkey"]))
                         for c2 in clist
                         if current_county(d, (name, c2["_nkey"]))]
                rank = 1 + sum(1 for p in peers
                               if p is not None and p > pct)
                suf = ("th" if 10 <= rank % 100 <= 20 else
                       {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th"))
                ctx = (f"{reg:,} registered voters against {ea:,} "
                       f"adults estimated for July 2025 — {pct:.1f} registered for every 100 "
                       f"July 2025 estimated adults.")
                if len(peers) > 1:
                    ctx += (f" Of the {len(peers)} counties measured "
                            f"in {esc(name)}, that count is the "
                            f"{rank}{suf} highest.")
                body.append(tline(ctx))
            elif bval0 is not None and ea:
                body.append(tline(
                    f"{bval0:,} {esc(BALLOTS26_LABEL[name])} in 2026, against "
                    f"{ea:,} adults estimated for July 2025 — "
                    f"{round(bval0 / ea * 100, 1):.1f} of this reported measure for "
                    f"every 100 adults."))
            body.append(MEASURE_NOTE)
            body.append("</details>")
            body.append('<h2 id="count">The count</h2>')
            body.append(year_switch(panes))
            if any_eavs:
                body.append('<p class="src">Past elections — U.S. Election '
                            'Assistance Commission, Election Administration '
                            'and Voting Survey (EAVS).</p>')
            if fired_rule:
                fb = flags_block([f"{c['county_name']} has more registered "
                                  f"voters than adults in the population denominator shown: "
                                  f"{reg:,} registered voters, {ea:,} "
                                  f"adults estimated for July 2025."])
                if fb: body.append(fb)
            write(f'counties/{s["slug"]}/{c["_slug"]}/index.html',
                  page(c["county_name"], mod("\n".join(body)), depth=3,
                       src_html=footer_src(d, ck),
                       yearbar=("yr", [y for y, _h in panes])))
            n += 1
    return n

def county_anoms_table(d, counties_by_state):
    """county-anomalies.csv's within-state outliers, rebuilt in plain
    words: the county's own two real counts, its registered voters for
    every 100 adults as a filled band cell, and the state's middle
    county in the same units. The file's type / value / reference /
    deviation codes are not rendered."""
    cmap = {}
    for st, clist in counties_by_state.items():
        for c in clist:
            cmap[(st, c["_nkey"])] = c
    _n = sum(1 for r in d["county_anoms"]
             if r["anomaly_type"] in ("within_state_outlier_high",
                                      "within_state_outlier_low"))
    out = [tline(f"{_n} counties stand far from their own state's "
                 f"middle county — each with its two real counts."),
           "<table><tr><th class='l'>State</th><th class='l'>County</th>"
           "<th>Registered voters</th><th>Adults (2020 Census, historical)</th>"
           "<th>Registered / 2020 adults (historical)</th>"
           "<th>Middle county in the state</th></tr>"]
    for r in d["county_anoms"]:
        if r["anomaly_type"] not in ("within_state_outlier_high",
                                     "within_state_outlier_low"):
            continue
        st = r["state"]
        c = gr = None
        for k in county_key_variants(r["county"]):
            if c is None: c = cmap.get((st, k))
            if gr is None: gr = d["reg_by_county"].get((st, k))
        regv = num(gr["registered_voters"]) if gr else None
        vap = num(c["voting_age_population_2020"]) if c else None
        pct = fnum(r["value"])
        med = re.search(r"([\d.]+)", r["state_reference_value"] or "")
        pct_td_c, _ = pct_td_html(d, pct, county_reg_key(d, st))
        if c:
            name_html = (f'<a href="../counties/{slugify(st)}/{c["_slug"]}/index.html">'
                         f'{esc(c["county_name"])}</a>')
        else:
            name_html = esc(r["county"])
        out.append(f'<tr><td class="l">{esc(st)}</td>'
                   f'<td class="l">{name_html}</td>'
                   f'<td>{fmt_int(regv)}</td><td>{fmt_int(vap)}</td>'
                   f'{pct_td_c}<td>{esc(med.group(1)) if med else "—"}</td></tr>')
    out.append("</table>")
    out.append('<p class="src">Registered voters: state election '
               'offices. Adults: U.S. Census Bureau, 2020 Census.</p>')
    return "\n".join(out)

def _write_dl(dl, name, fields, rows, counts):
    """One combined download as a CSV/JSON pair. Returns nothing;
    the row counts land in counts for the Data page's listing."""
    with open(os.path.join(dl, name + ".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)
    with open(os.path.join(dl, name + ".json"), "w") as f:
        json.dump(rows, f, indent=1)
    counts[name + ".csv"] = len(rows)
    counts[name + ".json"] = len(rows)

def build_downloads(d, states):
    """The combined download files in site/downloads/, built from
    the same loaded data the pages render: every folded-in state's
    counties and their 2026 ballots, every measured county's voter
    list against its adults, and the year-switch series state by
    state and year as the panes present it. Returns {file: rows}."""
    dl = os.path.join(OUT, "downloads")
    os.makedirs(dl, exist_ok=True)
    counts = {}
    prows, _missing = population_comparisons(
        d["counties"], d["reg_by_county"], d["est_by_county"], num)
    if prows:
        _write_dl(dl, "county-registration-population-2025", list(prows[0]), prows, counts)

    brows = []
    for st in sorted(set(BALLOTS26_FILES) | {"Montana"}):
        if st == "Montana":
            srows = [{"county": r["county"],
                      "ballots_cast": r["ballots_cast"],
                      "source": r["source"],
                      "source_url": r["source_url"]}
                     for r in d["mt_ballots"]]
        else:
            srows = d["ballots26_rows"][st]
        for r in srows:
            brows.append({"state": st, "county": r["county"],
                          "reported_count": num(r["ballots_cast"]),
                          "measure_type": county_measure(BALLOTS26_LABEL[st]),
                          "ballots": ballot_value(county_measure(BALLOTS26_LABEL[st]), num(r["ballots_cast"])),
                          "reporting_date_basis": r["source"],
                          "basis": BALLOTS26_LABEL[st],
                          "source": r["source"],
                          "source_url": r["source_url"]})
    _write_dl(dl, "county-ballots-2026",
              ["state", "county", "reported_count", "measure_type", "ballots", "basis", "reporting_date_basis", "source",
               "source_url"], brows, counts)
    vrows = []
    for r in d["roll_co_de"]:
        vrows.append({"state": r["state"], "county": r["county"],
                      "registered_voters": num(r["registered_voters"]),
                      "adults": num(r["voting_age_population_2020"]),
                      "registered_per_100_adults":
                          fnum(r["registered_pct_of_vap"]),
                      "population_year": 2020})
    for r in d["roll_ak"]:
        vrows.append({"state": "Alaska", "county": r["district"],
                      "registered_voters": num(r["registered_voters"]),
                      "adults": num(r["voting_age_population_2020"]),
                      "registered_per_100_adults":
                          fnum(r["registered_pct_of_vap"]),
                      "population_geography": r["population_geography"],
                      "population_year": r["population_year"],
                      "population_boundary_vintage": r["population_boundary_vintage"],
                      "registration_year": r["registration_year"],
                      "population_source_url": r["population_source_url"]})
    _write_dl(dl, "county-voter-list",
              ["state", "county", "registered_voters", "adults",
               "registered_per_100_adults", "population_geography",
               "population_year", "population_boundary_vintage",
               "registration_year",
               "population_source_url"], vrows, counts)
    hist = {}
    for r in d["hist_states"]:
        hist.setdefault(r["state"], {})[r["election_year"]] = r
    srows = []
    for name in sorted(states):
        s = states[name]
        for y in YEARS:
            cov = ""
            if y == "2026":
                reg, bal, tp = s["registered"], s["ballots"], s["turnout_pct"]
                basis = s["count_label"] + " — " + s["source"]
            elif name in hist and y in hist[name]:
                row = hist[name][y]
                reg, bal = num(row["registered_voters"]), num(row["ballots_cast"])
                tp = fnum(row["turnout_pct_registered"])
                basis = "State history series"
            elif name == "Alaska" and y in d["ak_eavs"]:
                reg, bal = d["ak_eavs"][y]
                tp = (round(bal / reg * 100, 1)
                      if (reg and bal is not None) else None)
                basis = "Federal survey (EAVS) — statewide jurisdiction"
            elif (name, y) in d["eavs_sums"]:
                e = d["eavs_sums"][(name, y)]
                reg, bal = e["reg"], e["bal"]
                tp = (round(e["mbal"] / e["mreg"] * 100, 1)
                      if e["mreg"] else None)
                basis = "Federal survey (EAVS) — counties added up"
                if tp is None:
                    cov = ""
                elif e["nmatch"] < e["nc"]:
                    cov = (f'{e["nmatch"]} of {e["nc"]} counties '
                           f'in the sum')
                else:
                    cov = f'all {e["nc"]} counties in the sum'
            else:
                reg = bal = tp = None
                basis = "No data published"
            srows.append({"state": name, "year": int(y),
                          "registered_voters": reg, "ballots_cast": bal,
                          "turnout_pct_registered": tp,
                          "turnout_coverage": cov, "basis": basis,
                          "reported_count": s["published_count"] if y == "2026" else bal,
                          "measure_type": s["count_kind"] if y == "2026" else "ballots_cast",
                          "source_and_reporting_date": s["source"] if y == "2026" else basis})
    _write_dl(dl, "state-figures-by-year",
              ["state", "year", "registered_voters", "ballots_cast",
               "turnout_pct_registered", "turnout_coverage", "basis", "reported_count", "measure_type", "source_and_reporting_date"], srows, counts)
    return counts

def build_data(d, states, counties_by_state):
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    csvs = ["turnout-2026-11-03.csv", "census-registered-2026.csv", "vap-2020-pl.csv",
            "county-vap-2020.csv", "census-estimates-state.csv",
            "census-estimates-county.csv", "county-registered-all.csv",
            "county-roll-integrity-all.csv", "ak-district-roll-integrity.csv",
            "turnout-history-national.csv", "turnout-history-states.csv",
            "cvap-state.csv", "cvap-county.csv", "state-roll-integrity-cvap.csv",
            "removals.csv", "ballots-detail.csv", "mail-rejection-reasons.csv",
            "rules-facts.csv", "registration-splits.csv", "polling-places.csv",
            "county-history-eavs.csv", "not-published.csv",
            "unofficial-vs-certified-2024.csv", "combination-quadrants.csv",
            "county-anomalies.csv", "county-ballots-mt.csv",
            "county-ballots-al.csv", "county-ballots-co.csv",
            "county-ballots-nc.csv", "county-ballots-ak.csv",
            "county-ballots-nm.csv", "county-ballots-wy.csv",
            "county-ballots-mn.csv", "county-ballots-md.csv",
            "county-ballots-ca.csv", "county-ballots-ks.csv",
            "county-ballots-va.csv", "county-ballots-pa.csv",
            "county-ballots-fl.csv", "county-ballots-az.csv",
            "county-ballots-oh.csv", "county-ballots-la.csv",
            "county-ballots-hi.csv", "county-ballots-ga.csv",
            "county-ballots-ny.csv", "county-ballots-wv.csv",
            "county-ballots-sc.csv", "county-ballots-ok.csv",
            "county-ballots-or.csv", "county-ballots-tn.csv",
            "county-ballots-vt.csv", "county-ballots-ia.csv",
            "county-ballots-in.csv", "county-ballots-mo.csv",
            "county-ballots-nd.csv", "county-ballots-sd.csv",
            "county-ballots-ne.csv", "county-ballots-ut.csv",
            "county-ballots-nv.csv",
            "governor-results-2026.csv",
            "senate-results-2026.csv",
            "house-results-2026.csv", "house-districts-2026.csv",
            "county-history-eavs-older.csv",
            "anomalies-vs-history.csv", "PAST-ELECTION-DAYS.md",
            "state-economics-tracker.csv", "flags.csv",
            "county-registered-co-de-ak.csv", "county-registered-co-de-ak.json",
            "county-roll-integrity-co-de.csv", "county-roll-integrity-co-de.json",
            "ak-district-vap-2020.csv", "ak-district-vap-2020.json",
            ak_geo.POPULATION_FILE, "ALASKA-GEOGRAPHY.md",
            "MANIFEST.md", "DEFINITIONS.md"]
    for fn in csvs:
        shutil.copy(os.path.join(SRC, fn), os.path.join(OUT, "data", fn))
    sj = []
    for name in sorted(states):
        s = states[name]
        sj.append({"state": name, "slug": s["slug"], "registered_voters": s["registered"],
                   "ballots_cast": s["ballots"], "turnout_pct_registered": s["turnout_pct"],
                   "reported_count": s["published_count"], "measure_type": s["count_kind"],
                   "measure_label": s["count_label"],
                   "status": s["status"], "adults_2020": s["vap"],
                   "adults_2025_estimate": s["est_adults"],
                   "registered_pct_of_adults_2025_estimate": s["reg_pct_est"],
                   "ballots_pct_of_adults_2025_estimate": s["bal_pct_est"],
                   "population_source_url_2025": s["est_url"],
                   "legacy_ratio_population_year": 2020,
                   "registered_pct_of_adults": s["reg_pct_adults"],
                   "ballots_pct_of_adults": s["bal_pct_adults"],
                   "population_2020": s["census_pop"],
                   "registered_pct_of_population": s["pct_census_registered"],
                   "ballots_pct_of_population": s["pct_census_ballots"],
                   "source": s["source"]})
    with open(os.path.join(OUT, "data", "states.json"), "w") as f:
        json.dump(sj, f, indent=1)
    ri = []
    for name in sorted(states):
        s = states[name]
        ri.append({"geography": name, "type": "state", "state": name,
                   "registered_voters": s["registered"], "adults_2020": s["vap"],
                   "registered_pct_of_adults": s["reg_pct_adults"]})
    for r in d["roll_co_de"]:
        ri.append({"geography": r["county"], "type": "county", "state": r["state"],
                   "registered_voters": num(r["registered_voters"]),
                   "adults_2020": num(r["voting_age_population_2020"]),
                   "registered_pct_of_adults": fnum(r["registered_pct_of_vap"]),
                   "registration_basis": r["registration_basis"],
                   "registration_date": r["registration_date"]})
    for r in d["roll_ak"]:
        ri.append({"geography": r["district"], "type": "house_district", "state": "Alaska",
                   "registered_voters": num(r["registered_voters"]),
                   "adults_2020": num(r["voting_age_population_2020"]),
                   "registered_pct_of_adults": fnum(r["registered_pct_of_vap"]),
                   "population_geography": r["population_geography"],
                   "population_year": r["population_year"],
                   "population_boundary_vintage": r["population_boundary_vintage"],
                   "registration_year": r["registration_year"],
                   "population_source_url": r["population_source_url"],
                   "census_geoid": r["census_geoid"]})
    for row in ri:
        row["ratio_population_year"] = 2020
        row["ratio_basis"] = "Historical 2020 Census adult count; not population-change adjusted"
    with open(os.path.join(OUT, "data", "registered-share-of-adults.json"), "w") as f:
        json.dump(ri, f, indent=1)
    files = sorted(os.listdir(os.path.join(OUT, "data")))
    body = ["<h1>Data & Sources</h1>",
            '<p>Download the records, inspect comparisons, or follow the update log. '
            '<a class="cite" href="../definitions/index.html">Read definitions and methods</a>.</p>', MEASURE_NOTE]
    body.append(alaska_geography_note())
    # the combined files lead the page: the whole record, in files,
    # each with its row count, above the per-file listing
    dlc = d.get("dl_counts", {})
    if dlc:
        body.append("<h2>The whole record, in files</h2>")
        _rows = sum(v for k, v in dlc.items() if k.endswith(".csv"))
        body.append(tline(f"The whole record as files — {_rows:,} "
                          f"rows, the same numbers the pages show."))
        body.append("<table><tr><th class='l'>File</th><th>Rows</th></tr>")
        for fn in ("county-ballots-2026.csv", "county-ballots-2026.json",
                   "county-voter-list.csv", "county-voter-list.json",
                   "state-figures-by-year.csv",
                   "state-figures-by-year.json"):
            body.append(f'<tr><td class="l"><a href="../downloads/{fn}">'
                        f'{fn}</a></td><td>{dlc.get(fn, 0):,}</td></tr>')
        body.append("</table>")
    body.append("<h2>Source files</h2>")
    body.append(tline(f"{len(files)} files — the files this site "
                      f"is built from, as they stand."))
    body.append("<table data-filter-table='files'><tr><th class='l'>File</th><th>Size</th></tr>")
    for fn in files:
        sz = os.path.getsize(os.path.join(OUT, "data", fn))
        body.append(f'<tr><td class="l"><a href="{fn}">{esc(fn)}</a></td><td>{sz:,} bytes</td></tr>')
    body.append("</table>")
    # Election Day vs today for the country — the full national table
    # (the front page carries the headline figures as cards)
    body.append("<h2>Election Day vs today — the country</h2>")
    body.append(tline("The country's measures on Election Day "
                      "beside today's, each with its period and "
                      "its source."))
    body.append(national_ed_table(d))
    # the states as two single-subject tables: voter lists, then ballots
    body.append("<h2>States — voter lists</h2>")
    _reg = sum(s["registered"] for s in states.values()
               if s["registered"] is not None)
    _vap = sum(s["est_adults"] for s in states.values() if s["registered"] is not None and s["est_adults"])
    body.append(tline(f"The voter lists added together: {_reg:,} "
                      f"registered voters against {_vap:,} adults estimated for July 2025 in the same states."))
    body.append("<table><tr><th class='l'>State</th><th>Registered</th><th>Adults (July 2025 estimate)</th>"
                "<th>Registered % of adults</th></tr>")
    for name in sorted(states):
        s = states[name]
        rk = reg_key(d, name)
        if s["registered"] is not None:
            reg_cell, _ = flagged(d, name, "registered_voters",
                                  linked(d, rk, fmt_int(s["registered"])))
        else:
            reg_cell = "No registration" if name == "North Dakota" else "—"
        pct_td, _ = pct_td_html(d, s["reg_pct_est"], rk)
        body.append(
            f'<tr><td class="l"><a href="../states/{s["slug"]}/index.html">{esc(name)}</a></td>'
            f'<td>{reg_cell}</td><td>{est_num_html(s["est_adults"], s["est_url"])}</td>'
            f'{pct_td}</tr>')
    body.append("</table>")
    body.append("<h2>Published election counts — separate measures</h2>")
    body.append('<p>Every source value is retained below. Race votes, returned ballots, estimates and lower bounds are not treated as ballots cast. Reporting dates differ; these are not a same-snapshot national result.</p>')
    body.append('<table><tr><th>State</th><th>Reported count</th><th>Measure</th><th>Source and reporting date</th></tr>')
    for name, s in sorted(states.items()):
        body.append(f'<tr><td>{esc(name)}</td><td>{fmt_int(s["published_count"])}</td><td>{esc(s["count_label"])}</td><td>{esc(s["source"])}</td></tr>')
    body.append('</table>')
    body.append("<h2>States — ballots</h2>")
    _bal = sum(s["ballots"] for s in states.values()
               if s["ballots"] is not None)
    _sc = sum(1 for s in states.values()
              if s["status"] == "still counting")
    body.append(tline(f"Recorded ballot counts add to {_bal:,} in the states "
                      f"that have published a total; {_sc} states "
                      f"are still counting. Race totals, returned ballots and voter estimates are excluded. Reporting dates differ; this is partial coverage, not a national turnout total."))
    body.append("<table><tr><th class='l'>State</th><th>Ballots cast</th><th>Adults (July 2025 estimate)</th>"
                "<th>Ballots % of adults</th><th>Turnout % of registered</th>"
                "<th class='l'>Status</th></tr>")
    for name in sorted(states):
        s = states[name]
        status = "Still counting" if s["status"] == "still counting" else "—"
        bk = bal_key(d, name)
        if s["ballots"] is not None:
            bal_cell, _ = flagged(d, name, "ballots_cast",
                                  linked(d, bk, fmt_int(s["ballots"])))
        else:
            bal_cell = fmt_int(s["ballots"])
        body.append(
            f'<tr><td class="l"><a href="../states/{s["slug"]}/index.html">{esc(name)}</a></td>'
            f'<td>{bal_cell}</td><td>{est_num_html(s["est_adults"], s["est_url"])}</td>'
            f'{band_td(linked(d, bk, fmt_pct(s["bal_pct_est"])), s["bal_pct_est"])}'
            f'{band_td(linked(d, bk, fmt_pct(s["turnout_pct"])), s["turnout_pct"])}<td class="l">{status}</td></tr>')
    body.append("</table>")
    # the past-election corpus: national series, past Election Days,
    # and 2026 next to past elections (numbers only)
    body.append("<h2>Past elections — the country</h2>")
    _yrs = [r["election_year"] for r in d["hist_nat"]]
    if _yrs:
        body.append(tline(f"The country's count in every federal "
                          f"election in the record, {min(_yrs)} to "
                          f"{max(_yrs)}."))
    body.append(national_history_table(d))
    body.append("<h2>Past Election Days</h2>")
    body.append('<p class="small">National numbers as known on the day.</p>')
    body.append(past_days_table_html(d))
    body.append('<h2 id="next-to-past">2026 next to past elections</h2>')
    _at = anoms_tline(d["anoms"])
    if _at: body.append(tline(_at))
    body.append("<table><tr><th class='l'>State</th><th class='l'>Measure</th>"
                "<th>2026</th><th>2022</th><th>2018</th>"
                "<th>Change from 2022</th><th>Change from 2018</th></tr>")
    body.extend(anoms_rows_html(d["anoms"], with_state=True))
    body.append("</table>")
    body.append(ANOMS_SRC)
    # figures no office published — the register of gaps
    body.append("<h2>Figures that are not published</h2>")
    body.append(tline(f"{len(d['notpub'])} figures no office has "
                      f"published — each row names what exists "
                      f"instead."))
    body.append("<table><tr><th class='l'>Jurisdiction</th><th class='l'>Figure</th>"
                "<th class='l'>What exists instead</th></tr>")
    for r in d["notpub"]:
        body.append(f'<tr><td class="l">{esc(r["jurisdiction"])}</td>'
                    f'<td class="l">{esc(r["figure"])}</td>'
                    f'<td class="l">{esc(r["what_exists_instead"])}</td></tr>')
    body.append("</table>")
    # election-night figures against the certified figures, 2024
    body.append("<h2>Election night and certified — 2024</h2>")
    _chg = sum(1 for r in d["uvc"]
               if r["unofficial_leader"] and r["certified_leader"]
               and r["unofficial_leader"] != r["certified_leader"])
    if _chg:
        body.append(tline(f"In {_chg} of these races, the leader "
                          f"changed between election night and the "
                          f"certified count."))
    else:
        body.append(tline("In every race here, the leader on "
                          "election night was still the leader when "
                          "the count was certified."))
    body.append("<table><tr><th class='l'>State</th><th class='l'>Race</th>"
                "<th class='l'>Election-night leader</th><th>Election-night margin</th>"
                "<th class='l'>Certified leader</th><th>Certified margin</th>"
                "<th>Margin change</th></tr>")
    for r in d["uvc"]:
        body.append(f'<tr><td class="l">{esc(r["state"])}</td>'
                    f'<td class="l">{esc(r["race"])}</td>'
                    f'<td class="l">{esc(r["unofficial_leader"]) or "—"}</td>'
                    f'<td>{fmt_int(num(r["unofficial_margin"]))}</td>'
                    f'<td class="l">{esc(r["certified_leader"]) or "—"}</td>'
                    f'<td>{fmt_int(num(r["certified_margin"]))}</td>'
                    f'<td>{fmt_int(num(r["margin_change"]))}</td></tr>')
    body.append("</table>")
    # The frozen grouping input remains an archive, not a live classification.
    body.append('<h2 id="combined">Archived 2020-baseline source ratios</h2>')
    body.append(archived_quadrants_html(d["quadrants"]))
    body.append('<p><a href="combination-quadrants.csv">Original source file (CSV)</a></p>')
    # county anomalies, rebuilt in plain words (see county_anoms_table)
    body.append("<h2>County anomalies</h2>")
    body.append(county_anoms_table(d, counties_by_state))
    # mail-ballot rejection reasons, 2024
    body.append("<h2>Mail-ballot rejection reasons — 2024</h2>")
    _rej = {}
    for _st, _rs in d["rej_reasons"].items():
        for _r in _rs:
            _rej[_r["reason"]] = (_rej.get(_r["reason"], 0)
                                  + (num(_r["rejected_count"]) or 0))
    if _rej:
        _top = max(_rej, key=lambda k: _rej[k])
        body.append(tline(f"{sum(_rej.values()):,} mailed ballots "
                          f"were rejected in 2024 across the states "
                          f"in this table. The most common reason "
                          f"was {_top.lower()} — {_rej[_top]:,}."))
    body.append("<table><tr><th class='l'>State</th><th class='l'>Reason</th>"
                "<th>Rejected</th></tr>")
    for st in sorted(d["rej_reasons"]):
        for r in d["rej_reasons"][st]:
            body.append(f'<tr><td class="l">{esc(st)}</td>'
                        f'<td class="l">{esc(r["reason"])}</td>'
                        f'<td>{fmt_int(num(r["rejected_count"]))}</td></tr>')
    body.append("</table>")
    # the full dated record (the front page carries the latest entries)
    body.append('<h2 id="record">The record</h2><div class=\'log\'>')
    for ln in reversed(d["log_lines"]):
        body.append(f"<div>{esc(ln)}</div>")
    body.append("</div>")
    write("data/index.html", page("Data & Sources", section_index("\n".join(body), collapsible=True), depth=1))

def build_definitions(d):
    defs = [
        ("Registered voters", "People on a state's voter list — the names the election office keeps of everyone signed up to vote."),
        ("Adults (2020)", "Residents age 18 and over — U.S. Census Bureau, 2020 Census."),
        ("Adults (2025 estimate)", "The Census Bureau's estimate of residents aged 18 and over on July 1, 2025. Residents, not citizens."),
        ("Registered % of adults", "The names on the voter list counted against the adults in the population denominator shown: registered voters ÷ adults. 100 would mean one name on the list for every adult."),
        ("Registered % of adults (2025 estimate)", "Registered voters ÷ adults (2025 estimate)."),
        ("Citizen adults (2020–2024)", "Residents age 18 and over who are U.S. citizens — U.S. Census Bureau, Citizen Voting Age Population tabulation from the American Community Survey."),
        ("Registered % of citizen adults", "Registered voters ÷ citizen adults."),
        ("Ballots cast", "Ballots counted in the general election of November 3, 2026."),
        ("Ballots % of adults", "Ballots cast counted against the adults in the population denominator shown: ballots cast ÷ adults."),
        ("Ballots % of adults (2025 estimate)", "Ballots cast ÷ adults (2025 estimate)."),
        ("Turnout % of registered", "Ballots cast ÷ registered voters."),
        ("Still counting", "The state has not published a final ballots-cast total."),
        ("No registration", "North Dakota does not register voters."),
        ("No data", "The office in charge has not published this number. The page shows the gap instead of filling it."),
        ("Unofficial", "Not final. The numbers can still change. A count becomes final when the office in charge finishes its checks and declares the result — that final count is the certified count."),
        ("Certified", "Declared final by the office in charge, after its checks."),
        ("Canvass", "The election office's final check of the whole count before it declares the result."),
        ("Tabulation", "A counting of ballots."),
        ("Precinct", "A neighborhood-sized piece of a county, counted separately. 'Precincts reporting' tells how many of them have sent in their numbers."),
        ("Ranked-choice", "Voters rank the candidates 1st, 2nd, 3rd. If nobody wins more than half of the first choices, the last-place candidate is dropped and each of those ballots counts for that voter's next choice. This repeats until one candidate has more than half."),
        ("At-large", "Voted on by the whole state (or the whole district), not by a smaller piece of it. Alaska's one House seat is at-large."),
        ("Active and inactive (voter list)", "Every name on the list is registered. A name marked inactive is one the office has not heard from — its mail came back, or the voter has not voted or answered in a long time. An inactive voter can still vote; voting makes the name active again."),
        ("Suspense list (Texas)", "Texas's holding list: voters whose address the office could not confirm. A voter on it can still vote after confirming an address."),
        ("Election Day baseline", "The last official numbers published before Election Day, Tuesday, November 3, 2026. Every 'today' number on this site is set beside its baseline number."),
        ("Economy rank", "A state's place among the 50 states, built from all fourteen numbers shown for it — unemployment, jobs, labor force, jobless claims, gas, gross domestic product, house prices, personal income, new business applications, building permits, labor force participation, average weekly wage, electricity price and poverty rate."),
        ("Unemployment rate", "Out of every 100 people who are working or looking for work, how many do not have a job (Bureau of Labor Statistics)."),
        ("Jobs", "How many people hold a payroll job (Bureau of Labor Statistics)."),
        ("Labor force", "How many people are working or looking for work (Bureau of Labor Statistics)."),
        ("Labor force participation rate", "Out of every 100 adults, how many are working or looking for work (Bureau of Labor Statistics)."),
        ("Payrolls", "The national count of payroll jobs, and how it moved in a month (Bureau of Labor Statistics)."),
        ("Jobless claims", "How many people asked for unemployment payments in a week — a first ask (U.S. Department of Labor)."),
        ("Inflation (CPI)", "How much more things cost than a year earlier (Bureau of Labor Statistics). 'Without food and energy' leaves out food and fuel prices, which jump around the most."),
        ("Average hourly earnings", "What the average hour of work paid, and how that pay moved over the year (Bureau of Labor Statistics)."),
        ("Mortgage rate", "The average interest rate on a 30-year home loan, published every week (Freddie Mac)."),
        ("Consumer sentiment", "How people say they feel about their own money and the economy, asked in a monthly survey (University of Michigan)."),
        ("Real GDP growth", "How much more the economy made and did than before, after taking out price rises (Bureau of Economic Analysis)."),
        ("Gross domestic product", "Everything a state makes and does, in dollars (Bureau of Economic Analysis)."),
        ("House price index", "How house prices move. The index follows the same houses over time; a higher number means pricier houses than when the index started (Federal Housing Finance Agency)."),
        ("Personal income per person", "All the income in a state, divided by the people who live there (Bureau of Economic Analysis)."),
        ("Average weekly wage", "What the average job paid per week (Bureau of Labor Statistics)."),
        ("Electricity price", "What a kilowatt-hour of electricity cost, averaged over homes, shops and factories (Energy Information Administration)."),
        ("New business applications", "How many people asked for a new business tax number — the first step in starting a business (Census Bureau)."),
        ("Building permits", "How many new homes local offices gave permission to build (Census Bureau)."),
        ("Poverty rate", "Out of every 100 people, how many live on less than the official poverty line (Census Bureau)."),
        ("Gas, regular", "The average pump price of a gallon of regular gas (AAA)."),
        ("Violet", "The number does not agree: with the same office's other number, or with the number of people who live there."),
    ]
    body = ["<h1>Definitions</h1>", '<dl class="defs">']
    for term, txt in defs:
        body.append(f"<dt>{esc(term)}</dt><dd>{esc(txt)}</dd>")
    body.append("</dl>")
    body.append("<h2>Shading</h2>")
    body.append('<p class="legend">Registered % of adults: '
                f'{chip(80)}Under 90% &nbsp; {chip(95)}90% – 100% &nbsp; '
                f'{vchip()}More registered voters than adults in the population denominator shown &nbsp; {chip(None)}No data</p>')
    write("definitions/index.html", page("Definitions", "\n".join(body), depth=1))

def main():
    global PL_URL
    refresh_spine()
    fetch_maps()
    d = load()
    PL_URL = d["citations"]["census-pl-94171"]["url"]
    states = build_states(d)
    counties_by_state = {}
    for c in d["counties"]:
        base = c["county_name"]
        for suf in (" County", " Parish", " Borough", " Census Area", " Municipality", " city"):
            if base.endswith(suf): base = base[: -len(suf)]; break
        c["_base"] = base
        c["_nkey"] = county_key(c["county_name"])
        c["_slug"] = slugify(c["county_name"])
        counties_by_state.setdefault(c["state"], []).append(c)
    for v in counties_by_state.values():
        v.sort(key=lambda c: c["county_name"])
    d["roll_by_county"] = resolve_county_rows(d["roll_co_de"], counties_by_state, "county")
    d["reg_by_county"] = resolve_county_rows(
        [r for r in d["county_reg"] if r["geography_type"] in ("county", "county-equivalent")],
        counties_by_state, "geography_name")
    d["cvap_by_fips"] = {r["county_fips"]: num(r["citizen_voting_age_population"])
                         for r in d["cvap_county"]}
    d["cvap_county_src"] = d["cvap_county"][0]["source"] if d["cvap_county"] else ""
    d["hist_by_fips"] = {(r["state"], r["fips"]): r for r in d["county_hist"]}
    d["hist_older_by_fips"] = {(r["state"], r["fips"]): r
                               for r in d["county_hist_older"]}
    # state figures for past cycles, for the year switch's panes:
    # where the state history series has no row, a state's pane shows
    # its counties in the same federal survey files added up — the
    # sum is labeled as a sum on the page, never presented as a total
    # the state published. Turnout uses the counties that published
    # both figures (a matched set), never two different county sets
    # divided. Only rows that join to a county on the site count.
    # The sum also counts its counties (nc) and the matched counties
    # (nmatch), so a turnout drawn from part of the sum is labeled
    # with the coverage it actually has.
    site_fips = {(c["state"], c["county_fips"])
                 for cl in counties_by_state.values() for c in cl}
    sums = {}
    for rows, yrs in ((d["county_hist"], ("2022", "2024")),
                      (d["county_hist_older"], ("2016", "2018", "2020"))):
        for r in rows:
            if (r["state"], r["fips"]) not in site_fips: continue
            for y in yrs:
                reg, bal = num(r[f"reg_{y}"]), num(r[f"ballots_{y}"])
                if reg is None and bal is None: continue
                e = sums.setdefault((r["state"], y),
                                    {"reg": None, "bal": None,
                                     "mreg": 0, "mbal": 0,
                                     "nc": 0, "nmatch": 0})
                e["nc"] += 1
                if reg is not None:
                    e["reg"] = (e["reg"] or 0) + reg
                if bal is not None:
                    e["bal"] = (e["bal"] or 0) + bal
                if reg is not None and bal is not None:
                    e["mreg"] += reg; e["mbal"] += bal
                    e["nmatch"] += 1
    d["eavs_sums"] = sums
    # Alaska is a single statewide jurisdiction in EAVS (fips 02000):
    # those rows are the state's own published figures in the survey,
    # used for its panes in the cycles the state series does not cover
    ak_eavs = {}
    for rows, yrs in ((d["county_hist"], ("2022", "2024")),
                      (d["county_hist_older"], ("2016", "2018", "2020"))):
        for r in rows:
            if r["state"] == "Alaska" and r["fips"] == "02000":
                for y in yrs:
                    reg, bal = num(r[f"reg_{y}"]), num(r[f"ballots_{y}"])
                    if reg is not None or bal is not None:
                        ak_eavs[y] = (reg, bal)
    d["ak_eavs"] = ak_eavs
    # 2025 population estimates join on the same normalized county
    # names. Connecticut is excluded outright: its estimates are the
    # 9 planning regions, not the 8 historic counties the site uses,
    # and the two geographies are never joined (unknown stays unknown).
    d["est_by_county"] = resolve_county_rows(
        [r for r in d["est_county_rows"] if r["state"] != "Connecticut"],
        counties_by_state, "county")
    _comparisons, d["population_comparison_missing"] = population_comparisons(
        d["counties"], d["reg_by_county"], d["est_by_county"], num)
    d["population_comparisons"] = {
        (r["state"], county_key(r["county"])): r for r in _comparisons}
    mt, mt_valid = {}, {c["_nkey"] for c in counties_by_state.get("Montana", [])}
    for r in d["mt_ballots"]:
        for k in county_key_variants(r["county"]):
            if k in mt_valid:
                mt[("Montana", k)] = num(r["ballots_cast"])
                break
    d["mt_by_county"] = mt
    if d["mt_ballots"]:
        d["mt_src"] = (d["mt_ballots"][0]["source"], d["mt_ballots"][0]["source_url"])
    # 2026 county ballots, joined to counties on the same normalized
    # names as every other county file. Montana's older file (no state
    # column) joins through the same path. Alaska's file is districts.
    rows26 = [{"state": "Montana", "county": r["county"],
               "ballots_cast": r["ballots_cast"], "source": r["source"],
               "source_url": r["source_url"]} for r in d["mt_ballots"]]
    for st, srows in d["ballots26_rows"].items():
        if st == "Alaska": continue
        rows26 += [{"state": st, "county": r["county"],
                    "ballots_cast": r["ballots_cast"], "source": r["source"],
                    "source_url": r["source_url"]} for r in srows]
    d["ballots26_by_county"] = resolve_county_rows(rows26, counties_by_state, "county")
    d["ak_ballots"] = {r["county"]: num(r["ballots_cast"])
                       for r in d["ballots26_rows"].get("Alaska", [])}
    sums = {}
    for (st, _k), r in d["ballots26_by_county"].items():
        sums[st] = sums.get(st, 0) + (num(r["ballots_cast"]) or 0)
    if d["ak_ballots"]:
        sums["Alaska"] = sum(v for v in d["ak_ballots"].values() if v)
    d["ballots26_sum"] = sums
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    for asset in ("navigation.css", "navigation.js"):
        with open(os.path.join(BASE, "assets", asset)) as f:
            write(f"assets/{asset}", f.read())
    build_front(d, states, counties_by_state)
    build_states_page(d, states)
    build_rankings_page(d, states)
    build_state_pages(d, states, counties_by_state, None)
    n_counties = build_county_pages(d, states, counties_by_state)
    d["dl_counts"] = build_downloads(d, states)
    build_data(d, states, counties_by_state)
    build_definitions(d)
    print(f"states: {len(states)}  county pages: {n_counties}")
    print(f"site: {OUT}")

if __name__ == "__main__":
    main()
