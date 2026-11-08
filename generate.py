#!/usr/bin/env python3
"""Open Tally — static site generator.
Reads verified CSVs from the data/ directory beside this file and writes a
host-agnostic static site (HTML/CSS, no JS needed for content) to site/
beside this file. Python stdlib only. The map step reads us-atlas TopoJSON
from data/maps/ (see fetch_maps(), which refetches only if a file is missing).
"""
import csv, json, math, os, re, shutil, sys, urllib.request
from html import escape as esc

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "site")
MAPDIR = os.path.join(BASE, "data", "maps")

GREEN, YELLOW, ORANGE, GREY = "#15803d", "#eab308", "#ea580c", "#9ca3af"
VIOLET = "#7C3AED"
PL_URL = ""  # set in main() from citations.csv

STATE_ABBR = {}  # filled below
STATES_ORDER = []  # 51 names, alphabetical as in turnout CSV

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
    s = name.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).split()

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
    naming no county in the file is dropped, as an unmatched join was."""
    valid = {(c_st, c["_nkey"]) for c_st, clist in counties_by_state.items() for c in clist}
    out = {}
    for r in rows:
        st = r["state"]
        for k in county_key_variants(r[field]):
            if (st, k) in valid:
                out[(st, k)] = r
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
        d["roll_ak"] = list(csv.DictReader(f))
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
    with open(f"{SRC}/not-published.csv") as f:
        d["notpub"] = list(csv.DictReader(f))
    with open(f"{SRC}/unofficial-vs-certified-2024.csv") as f:
        d["uvc"] = list(csv.DictReader(f))
    with open(f"{SRC}/combination-quadrants.csv") as f:
        d["quadrants"] = list(csv.DictReader(f))
    with open(f"{SRC}/county-ballots-mt.csv") as f:
        d["mt_ballots"] = list(csv.DictReader(f))
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
    d["gas7"] = _gas("gas-aaa-2026-11-07.csv")
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
        bal = num(t["ballots_cast"])
        states[name] = {
            "name": name, "slug": slugify(name),
            "registered": reg, "ballots": bal,
            "turnout_pct": fnum(t["turnout_pct"]),
            "status": t["status"], "source": t["source"],
            "vap": vap,
            "census_pop": num(c["census_2020"]),
            "pct_census_registered": fnum(c["pct_census_registered"]),
            "pct_census_ballots": fnum(c["pct_census_ballots"]),
            "reg_pct_adults": (round(reg / vap * 100, 1) if reg and vap else None),
            "bal_pct_adults": (round(bal / vap * 100, 1) if bal and vap else None),
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

def fit(polys_list, width, height, pad=4):
    """Fit projected polys into width x height. Returns (mapped_polys, scale)."""
    xs = [p[0] for polys in polys_list for poly in polys for ring in poly for p in ring]
    ys = [p[1] for polys in polys_list for poly in polys for ring in poly for p in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    bw, bh = maxx - minx, maxy - miny
    s = min((width - 2 * pad) / bw, (height - 2 * pad) / bh)
    ox = pad + ((width - 2 * pad) - bw * s) / 2.0
    oy = pad + ((height - 2 * pad) - bh * s) / 2.0
    out = []
    for polys in polys_list:
        out.append([[[(ox + (x - minx) * s, oy + (maxy - y) * s) for x, y in ring]
                     for ring in poly] for poly in polys])
    return out, s

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

def national_map(state_fips, fills):
    """Composite Albers USA SVG. state_fips: {fips: state name}; fills: {name: color}."""
    arcs, geoms = load_topo(f"{MAPDIR}/states-10m.json", "states")
    W, H = 960, 600
    by_region = {"CONUS": [], "AK": [], "HI": []}
    meta = []  # (region idx placeholder, name)
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
    mapped, s = fit(flat, W, H, pad=6)
    idx = {"CONUS": 0, "AK": len(by_region["CONUS"]), "HI": len(by_region["CONUS"]) + len(by_region["AK"])}
    # rescale AK by 0.35 and HI by 1.0 around their own bboxes, then place:
    paths = {}
    for reg, i, name in meta:
        polys = mapped[idx[reg] + i]
        if reg == "AK":
            polys = rescale_place(polys, 0.35, W, H, anchor="bl")
        elif reg == "HI":
            polys = rescale_place(polys, 1.0, W, H, anchor="hi")
        paths[name] = polys_to_path(polys)
    svg = [f'<svg viewBox="0 0 {W} {H}" class="map" role="img" aria-label="United States">']
    for name, d in paths.items():
        svg.append(f'<path d="{d}" fill="{fills.get(name, GREY)}"><title>{esc(name)}</title></path>')
    svg.append("</svg>")
    return "".join(svg)

def rescale_place(polys, factor, W, H, anchor):
    """Shrink polys by factor about their bbox center, then move bbox to an anchor box."""
    xs = [p[0] for poly in polys for ring in poly for p in ring]
    ys = [p[1] for poly in polys for ring in poly for p in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    scaled = [[[(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in ring]
               for ring in poly] for poly in polys]
    xs = [p[0] for poly in scaled for ring in poly for p in ring]
    ys = [p[1] for poly in scaled for ring in poly for p in ring]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    if anchor == "bl":    tx, ty = 4 - minx, (H - 2) - maxy
    elif anchor == "hi":  tx, ty = 300 - minx, (H - 4) - maxy
    else:                 tx, ty = 0, 0
    return [[[(x + tx, y + ty) for x, y in ring] for ring in poly] for poly in scaled]

def state_map(state_name, county_fips_names, fills):
    """Single-state county map, fitted Albers. county_fips_names: {fips: display name}."""
    arcs, geoms = load_topo(f"{MAPDIR}/counties-10m.json", "counties")
    raw, names = [], []
    for fips, nm in county_fips_names.items():
        g = geoms.get(fips)
        if not g: continue
        raw.append(geom_polys(g, arcs)); names.append(nm)
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
        svg.append(f'<path d="{polys_to_path(polys)}" fill="{fills.get(nm, GREY)}"><title>{esc(nm)}</title></path>')
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
.legend{font-size:13px;color:var(--ink2);margin:10px 0 16px;line-height:1.7}
.small{font-size:13.5px;color:var(--ink2);line-height:1.6}
.src{font-size:13px;color:var(--ink2);margin:6px 0 14px;line-height:1.55}
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
@media (max-width:760px){
body{padding:0 16px 48px}
.tagline{font-size:18px}
h1{font-size:29px}
h2{margin-top:46px}
.card{flex:1 1 160px;padding:2px 14px}
.card .v{font-size:25px}
table{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;white-space:nowrap}
td.l{white-space:nowrap}
.govline,.plainline{font-size:15.5px}
.footer{flex-direction:column;gap:2px}
}
.maptoggle{position:relative}
.mt-in{position:absolute;opacity:0;pointer-events:none}
.mt-tabs{display:flex;gap:8px;margin:12px 0 4px}
.mt-tabs label{font-size:12px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:var(--ink2);border:1px solid var(--line2);padding:6px 14px;cursor:pointer}
#ecomap-base:checked~.mt-tabs label[for=ecomap-base],
#ecomap-cur:checked~.mt-tabs label[for=ecomap-cur]{color:var(--ink);border-color:var(--ink)}
.mt-pane{display:none}
#ecomap-base:checked~.mt-base{display:block}
#ecomap-cur:checked~.mt-cur{display:block}
"""

def page(title, body, depth=0, src_html=None):
    root = "../" * depth
    if src_html is None:
        src_html = (f'Sources: <a class="cite" href="{esc(PL_URL)}">U.S. Census Bureau</a>'
                    ' · State election offices')
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
</head>
<body>
<header class="site-head"><div class="wordmark">Open <span class="accent">Tally</span></div><div class="tagline">Every election number, from the office that issued it.</div><nav class="mainnav"><a href="{root}index.html#states">States</a><a href="{root}data/index.html">Data</a><a href="{root}definitions/index.html">Definitions</a></nav></header>
{body}
<div class="footer"><span>Open Tally</span><span>{src_html}</span></div>
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
          f'{vchip()}More registered voters than adults who live there &nbsp; {chip(None)}No data</div>')

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

def pct_cell_html(d, pct, citekey=None, bare_none=False):
    """Registered-% -of-adults cell. Over 100 -> violet block (flag rule).
    Returns (html, rule_fired)."""
    if pct is None:
        return ("—", False) if bare_none else (chip(None) + fmt_pct(None), False)
    if pct > 100:
        inner = linked(d, citekey, fmt_pct(pct))
        return (f'<span class="flag">{inner}</span>'
                f'<span class="flaglab">{esc(d["flag_rule"]["flag_label"])}</span>'), True
    return chip(pct) + linked(d, citekey, fmt_pct(pct)), False

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
        return (f"{st}'s ballots number is the vote total for the "
                f"governor's race: {s['ballots']:,}.")
    if label == "Top-race votes":
        return (f"In {st}, the ballots number is the votes for the top "
                f"race, not a count of ballots.")
    return f"{st} — {row['flag_detail']}"

def flags_block(sentences):
    if not sentences: return ""
    out = ["<h2>Flags</h2>", '<div class="flags">']
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
            pop = num(c["total_population_2020"])
            if reg and pop and reg > pop:
                lst.append({"name": c["county_name"], "slug": c["_slug"],
                            "reg": reg, "pop": pop})
        if lst: out[st] = lst
    d["over_pop"] = out
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
    g3, g7 = d["gas3"].get("United States"), d["gas7"].get("United States")
    card("Gas — national average",
         f"${g3:.2f}" if g3 is not None else None, "Nov 3",
         f"${g7:.2f}" if g7 is not None else None, "Nov 7")
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

def econ_map_block(d):
    fills_b = {n: ECON_FILL[econ_baseline_color(e)] for n, e in d["econ"].items()}
    fills_c = {n: ECON_FILL[econ_today_color(e)] for n, e in d["econ"].items()}
    fips = {f: n for f, n in FIPS_STATE.items()}
    leg_b = ('<div class="legend">Election Day: ' + econ_chip("green")
             + 'Getting better &nbsp; ' + econ_chip("yellow") + 'Mixed &nbsp; '
             + econ_chip("orange") + 'Getting worse</div>')
    leg_c = ('<div class="legend">Today: ' + econ_chip("green") + 'Better &nbsp; '
             + econ_chip("yellow") + 'Mixed &nbsp; ' + econ_chip("orange")
             + 'Worse &nbsp; ' + econ_chip("grey") + 'No new numbers yet</div>')
    return "\n".join([
        '<h3>State economies</h3>',
        '<div class="maptoggle">',
        '<input class="mt-in" type="radio" name="ecomap" id="ecomap-base" checked>',
        '<input class="mt-in" type="radio" name="ecomap" id="ecomap-cur">',
        '<div class="mt-tabs"><label for="ecomap-base">Election Day</label>'
        '<label for="ecomap-cur">Today</label></div>',
        f'<div class="mt-pane mt-base">{national_map(fips, fills_b)}{leg_b}</div>',
        f'<div class="mt-pane mt-cur">{national_map(fips, fills_c)}{leg_c}</div>',
        '</div>'])

def econ_rank_tables(d, states):
    br, cr = econ_ranks(d)
    by_name = d["econ"]
    def row(rank_map, name, other=None, color=None):
        e = by_name[name]
        cells = (f'<td>{rank_map[name]}</td>'
                 f'<td class="l">{econ_chip(color) if color else ""}'
                 f'<a href="states/{states[name]["slug"]}/index.html">{esc(name)}</a></td>')
        if other is not None:
            diff = other[name] - rank_map[name]
            chg = f'↑ {diff}' if diff > 0 else f'↓ {-diff}' if diff < 0 else '→ 0'
            if diff:
                chg = (f'<span style="color:{GREEN if diff > 0 else ORANGE}">'
                       f'{chg}</span>')
            cells += f'<td>{other[name]}</td><td class="l">{chg}</td>'
        cells += (f'<td>{fmt_pct(fnum(e["unemp"]))}</td>'
                  f'<td>{fnum(e["jobs_move"]):+.1f}%</td>')
        return f'<tr>{cells}</tr>'
    out = ['<h3>State rankings — Election Day</h3>',
           "<table><tr><th>Rank</th><th class='l'>State</th>"
           "<th>Unemployment</th><th>Jobs, year to Election Day</th></tr>"]
    for name in sorted(br, key=lambda n: br[n]):
        out.append(row(br, name, color=econ_baseline_color(by_name[name])))
    out.append('</table>')
    out.append('<h3>State rankings — Today</h3>')
    out.append("<table><tr><th>Rank</th><th class='l'>State</th>"
               "<th>Election Day rank</th><th class='l'>Change</th>"
               "<th>Unemployment</th><th>Jobs, year to Election Day</th></tr>")
    for name in sorted(cr, key=lambda n: cr[n]):
        out.append(row(cr, name, other=br, color=econ_today_color(by_name[name])))
    out.append('</table>')
    out.append('<p class="small">District of Columbia is not ranked.</p>')
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
            if diff:
                color = GREEN if (diff > 0) == up_good else ORANGE
                chg = f'<span style="color:{color}">{chg}</span>'
            rows.append((label, f"{bv} ({bw})", f"{cv} ({cw})", chg))
        else:
            rows.append((label, f"{bv} ({bw})", "No newer number yet.", "—"))
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
    g3, g7 = d["gas3"].get("United States"), d["gas7"].get("United States")
    gd = (g7 - g3) if (g3 is not None and g7 is not None) else None
    row("Gas — national average",
        f"${g3:.2f}" if g3 is not None else None, "Nov 3",
        f"${g7:.2f}" if g7 is not None else None, "Nov 7",
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
    gdp = find(r"(\+[\d.]+)% advance Q3", base)
    row("Real GDP growth", (gdp + "%") if gdp else None,
        "Q3 2026, first estimate", None, "", "—")
    out = ["<table><tr><th class='l'>Measure</th><th>Election Day</th>"
           "<th>Today</th><th>Change</th></tr>"]
    for label, b, c, chg in rows:
        out.append(f'<tr><td class="l">{esc(label)}</td><td>{esc(b)}</td>'
                   f'<td>{esc(c)}</td><td>{chg}</td></tr>')
    out.append("</table>")
    return "\n".join(out)

def fmt_factor(r):
    v, u = r["value"], r["unit"]
    fv = fnum(v)
    if u == "%": return f"{v}%"
    if u == "USD per week": return f"${int(fv):,}"
    if "cents" in u: return f"{v}¢"
    if fv is not None and fv == int(fv): return f"{int(fv):,}"
    return v

def state_ed_html(d, s):
    """A state's Election Day vs today block: governor where the record
    carries it, then one table in the standing columns — Election Day |
    Today | Change — with claims and gas where newer numbers exist, and
    the Election Day baseline factors with 'No newer number yet.'"""
    st = s["name"]
    gov = None
    if st in d["gov_flips"] and st != "Alaska":
        gov = (f"Governor — the office changed from Republican to "
               f"Democrat. {d['gov_flips'][st]}, a Democrat, won.")
    elif st == "Alaska" and "Alaska" in d["gov_flips"]:
        gov = (f"Governor — projected for {d['gov_flips']['Alaska']}, "
               f"a Democrat. Not yet called.")
    elif st == "Kansas" and "Kansas governor: not yet called" in d["baseline_text"]:
        gov = ("Governor — not called. The Democrat is narrowly ahead. "
               "A Democrat held the office going in.")
    rows = []
    if st in d["flip_unemp"]:
        rows.append(("Unemployment rate",
                     f"{d['flip_unemp'][st]}% (Sep 2026)", None, None))
    cl = d["claims"].get(st, [])
    if len(cl) >= 2:
        a, bb = cl[0], cl[-1]
        va, vb = num(a["claims"]), num(bb["claims"])
        diff = vb - va
        chg = ("→ No change" if diff == 0 else
               f'<span style="color:{GREEN if diff < 0 else ORANGE}">{diff:+,}</span>')
        rows.append(("Jobless claims in a week",
                     f"{va:,} (week ended {fmt_date(a['week ended'])})",
                     f"{vb:,} (week ended {fmt_date(bb['week ended'])})", chg))
    g3, g7 = d["gas3"].get(st), d["gas7"].get(st)
    if g3 is not None and g7 is not None:
        diff = round(g7 - g3, 2)
        gtxt = (("+$" if diff > 0 else "−$") + f"{abs(diff):.2f}")
        chg = ("→ No change" if diff == 0 else
               f'<span style="color:{GREEN if diff < 0 else ORANGE}">{gtxt}</span>')
        rows.append(("Gas, regular", f"${g3:.2f} (Nov 3)",
                     f"${g7:.2f} (Nov 7)", chg))
    fac = d["factors"].get(st, {})
    for fname in ("Average weekly wage", "New business applications",
                  "Building permits", "Labor force participation rate",
                  "Electricity price - all sectors", "Poverty rate"):
        r = fac.get(fname)
        if r:
            val = linked(d, FACTOR_CITE.get(fname), fmt_factor(r))
            rows.append((fname, f"{val} ({r['period']})", None, None))
    if not gov and not rows: return ""
    out = ["<h2>Election Day vs today</h2>"]
    if gov: out.append(f'<div class="govline">{esc(gov)}</div>')
    if rows:
        out.append("<table><tr><th class='l'>Measure</th><th>Election Day</th>"
                   "<th>Today</th><th>Change</th></tr>")
        for label, b, c, chg in rows:
            if c is None:
                out.append(f'<tr><td class="l">{esc(label)}</td><td>{b}</td>'
                           f'<td>No newer number yet.</td><td>—</td></tr>')
            else:
                out.append(f'<tr><td class="l">{esc(label)}</td><td>{b}</td>'
                           f'<td>{c}</td><td>{chg}</td></tr>')
        out.append("</table>")
    return "\n".join(out)

def state_extra_sections(d, s):
    """Registration splits, removals, the 2024 ballots detail, polling
    places, and rules for one state. Every figure comes from its own
    file and keeps that file's source line; gaps stay gaps."""
    st = s["name"]
    out = []
    sr = d["splits"].get(st)
    if sr:
        tot = num(sr["registered_total"])
        act = num(sr["registered_active"])
        ina = num(sr["registered_inactive"])
        if tot or act:
            out.append("<h2>Registration</h2><table>")
            if tot: out.append(f'<tr><td class="l">Registered voters — total</td><td>{fmt_int(tot)}</td></tr>')
            if act: out.append(f'<tr><td class="l">Active</td><td>{fmt_int(act)}</td></tr>')
            if ina: out.append(f'<tr><td class="l">Inactive</td><td>{fmt_int(ina)}</td></tr>')
            if sr["inactive_pct"]:
                out.append(f'<tr><td class="l">Inactive share</td><td>{esc(sr["inactive_pct"])}%</td></tr>')
            for lab, col in (("Democrat", "dem_rv"), ("Republican", "rep_rv"),
                             ("Other / unaffiliated", "other_unaffiliated_rv")):
                v = num(sr[col])
                if v is not None:
                    out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
            out.append("</table>")
            if sr["basis"]:
                out.append(f'<p class="src">Basis: {esc(sr["basis"])}.</p>')
            if act and tot and s["registered"] == act and tot > act:
                out.append(f'<p class="src">The registration number at the '
                           f'top of this page counts active voters only; '
                           f'the full roll is {tot:,}.</p>')
            out.append(f'<p class="src">Source: {esc(sr["source"])}</p>')
    rm = d["removals"].get(st)
    if rm and num(rm["removed_total"]):
        rt = num(rm["removed_total"])
        out.append("<h2>Removals</h2><table>")
        out.append(f'<tr><td class="l">Removed from the rolls</td><td>{fmt_int(rt)}</td></tr>')
        out.append(f'<tr><td class="l">Period</td><td class="l">'
                   f'{fmt_date(rm["period_start"])} – {fmt_date(rm["period_end"])}</td></tr>')
        if s["registered"]:
            share = rt / s["registered"] * 100
            out.append(f'<tr><td class="l">Share of the roll</td>'
                       f'<td>{chip(share)}{share:.1f}%</td></tr>')
        for lab, col in (("Moved", "removed_moved"), ("Deceased", "removed_deceased"),
                         ("Felony", "removed_felony"), ("Duplicate", "removed_duplicate"),
                         ("At the voter's request", "removed_request"),
                         ("Confirmation process", "removed_confirmation_process"),
                         ("Other", "removed_other")):
            v = num(rm[col])
            if v is not None:
                out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
        if num(rm["added_total"]):
            out.append(f'<tr><td class="l">Added to the rolls</td>'
                       f'<td>{fmt_int(num(rm["added_total"]))}</td></tr>')
        if num(rm["confirmation_notices_mailed"]):
            out.append(f'<tr><td class="l">Confirmation notices mailed</td>'
                       f'<td>{fmt_int(num(rm["confirmation_notices_mailed"]))}</td></tr>')
        out.append("</table>")
        out.append(f'<p class="src">Source: {esc(rm["source"])}</p>')
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
            out.append("<h2>Ballots — 2024</h2><table>")
            for lab, v, rate in rows:
                out.append(f'<tr><td class="l">{lab}</td><td>{fmt_int(v)}</td></tr>')
                if rate is not None:
                    out.append(f'<tr><td class="l">Mail rejection rate</td>'
                               f'<td>{chip(rate)}{rate:.2f}%</td></tr>')
            out.append("</table>")
            out.append(f'<p class="src">Source: {esc(b["source"])}</p>')
    pp = d["polling"].get(st)
    if pp:
        out.append("<h2>Polling places — 2024</h2><table>")
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
        out.append("<h2>Rules</h2><table>")
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

def front_adds_lines(d, states, counties_by_state):
    """The front-page "What doesn't add up" lines, built from the data:
    counts of people first, each line linked to the page behind it."""
    lines = []
    op = over_pop(d, counties_by_state)
    # registered voters over total population, in the analysis file's order
    for r in d["county_anoms"]:
        if r["anomaly_type"] != "rolls_over_total_population": continue
        st, geo = r["state"], r["county"]
        reg = _first_int(r["value"]); pop = _first_int(r["state_reference_value"])
        if geo.startswith("House District"):
            lines.append(f'<a href="states/{states[st]["slug"]}/index.html">'
                         f'{esc(st)} {esc(geo)}</a> — {reg:,} registered '
                         f'voters, {pop:,} residents.')
            continue
        match = next((e for e in op.get(st, [])
                      if county_key(e["name"]) == county_key(geo)), None)
        if match:
            lines.append(f'<a href="counties/{states[st]["slug"]}/{match["slug"]}/index.html">'
                         f'{esc(match["name"])}, {esc(st)}</a> — '
                         f'{match["reg"]:,} registered voters, '
                         f'{match["pop"]:,} residents.')
        else:
            lines.append(f'{esc(geo)} County, {esc(st)} — {reg:,} '
                         f'registered voters, {pop:,} residents.')
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
    # a published figure that counts active voters only, full roll larger
    for st, sr in d["splits"].items():
        if st not in states: continue
        act, tot = num(sr["registered_active"]), num(sr["registered_total"])
        if act and tot and states[st]["registered"] == act and tot > act:
            lines.append(f'<a href="states/{states[st]["slug"]}/index.html">'
                         f'{esc(st)}</a> — the published registration number '
                         f'({act:,}) counts active voters only. The full '
                         f'roll is {tot:,}.')
    # largest ballots change against 2022 in the history comparison
    cands = []
    for r in d["anoms"]:
        if r["measure"] == "ballots" and r["classification"] == "unexplained":
            dev = fnum(str(r["deviation_vs_2022_pp_or_pct"]).replace("%", ""))
            if dev is not None: cands.append((abs(dev), r))
    if cands:
        r = max(cands, key=lambda t: t[0])[1]
        st = r["state"]
        b26, b22 = _first_int(r["value_2026"]), _first_int(r["value_2022"])
        r26 = states[st]["registered"]
        r22 = next((num(h["registered_voters"]) for h in d["hist_states"]
                    if h["state"] == st and h["election_year"] == "2022"), None)
        lines.append(f'<a href="states/{states[st]["slug"]}/index.html">'
                     f'{esc(st)}</a> — {b26:,} ballots in 2026; {b22:,} in '
                     f'2022. Registered voters: {r26:,} in 2026; {r22:,} '
                     f'in 2022.')
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
    if (s["reg_pct_adults"] or 0) > 100:
        lines.append(f"{st} has more registered voters than adults who "
                     f"live there: {s['registered']:,} registered voters, "
                     f"{s['vap']:,} adults.")
    op = over_pop(d, counties_by_state).get(st, [])
    if op:
        top = max(op, key=lambda e: e["reg"] / e["pop"])
        if len(op) == 1:
            lines.append(f"1 county in {st} has more registered voters "
                         f"than residents — the most is {top['name']}: "
                         f"{top['reg']:,} registered, {top['pop']:,} residents.")
        else:
            lines.append(f"{len(op)} counties in {st} have more registered "
                         f"voters than residents — the most is {top['name']}: "
                         f"{top['reg']:,} registered, {top['pop']:,} residents.")
    if st == "Alaska":
        for r in d["county_anoms"]:
            if (r["anomaly_type"] == "rolls_over_total_population"
                    and r["state"] == "Alaska"):
                reg = _first_int(r["value"])
                pop = _first_int(r["state_reference_value"])
                lines.append(f"Alaska {r['county']} has more registered "
                             f"voters than residents: {reg:,} registered "
                             f"voters, {pop:,} residents.")
    return lines

NAT_HIST_KEY = {"2014": "eac-eavs-2014", "2016": "eac-eavs-2016",
                "2018": "international-idea-turnout", "2020": "eac-eavs-2020",
                "2022": "eac-eavs-2022-report", "2024": "eac-eavs-2024-report"}

def national_history_table(d):
    """The national past-election series (turnout-history-national.csv):
    past elections on the same basis as 2026 — ballots cast, registered
    voters, and turnout against each labeled denominator. A figure no
    source published stays blank (—)."""
    rows = ["<table><tr><th>Year</th><th class='l'>Election</th>"
            "<th>Ballots cast</th><th>Registered voters</th>"
            "<th>Turnout % of registered</th><th>Turnout % of adults</th>"
            "<th>Turnout % of eligible voters</th></tr>"]
    for r in d["hist_nat"]:
        k = NAT_HIST_KEY.get(r["election_year"])
        t_reg, t_vap, t_vep = (fnum(r["turnout_pct_registered"]),
                               fnum(r["turnout_pct_vap"]),
                               fnum(r["turnout_pct_vep"]))
        rows.append(
            f'<tr><td>{esc(r["election_year"])}</td>'
            f'<td class="l">{esc(r["election_type"].capitalize())}</td>'
            f'<td>{linked(d, k, fmt_int(num(r["ballots_cast"])))}</td>'
            f'<td>{linked(d, k, fmt_int(num(r["registered_voters"])))}</td>'
            f'<td>{chip(t_reg)}{linked(d, k, fmt_pct(t_reg))}</td>'
            f'<td>{chip(t_vap)}{linked(d, "census-cps-voting", fmt_pct(t_vap))}</td>'
            f'<td>{chip(t_vep)}{linked(d, "uf-election-lab-turnout", fmt_pct(t_vep))}</td></tr>')
    rows.append("</table>")
    rows.append('<p class="src">Ballots cast and registered voters: '
                'U.S. Election Assistance Commission, EAVS reports. '
                'Turnout % of adults: U.S. Census Bureau, Current '
                'Population Survey. Turnout % of eligible voters: '
                'UF Election Lab.</p>')
    return "\n".join(rows)

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
    """anomalies-vs-history.csv as plain side-by-side numbers: 2026 next
    to 2022 and 2018, with the file's own change figures. No
    classification and no evidence text is rendered."""
    out = []
    for r in rows:
        label, is_pct = ANOM_MEASURES.get(r["measure"], (r["measure"], False))
        def v(x):
            x = (x or "").strip()
            if not x: return "—"
            return esc(x) + ("%" if is_pct and not x.endswith("%") else "")
        def dv(x):
            x = (x or "").strip()
            return esc(x) if x else "—"
        st = f'<td class="l">{esc(r["state"])}</td>' if with_state else ""
        out.append(f'<tr>{st}<td class="l">{esc(label)}</td>'
                   f'<td>{v(r["value_2026"])}</td><td>{v(r["value_2022"])}</td>'
                   f'<td>{v(r["value_2018"])}</td>'
                   f'<td>{dv(r["deviation_vs_2022_pp_or_pct"])}</td>'
                   f'<td>{dv(r["deviation_vs_2018_pp_or_pct"])}</td></tr>')
    return out

ANOMS_SRC = ('<p class="src">2026 figures: as published on this site. '
             '2022 and 2018 figures: U.S. Election Assistance Commission, '
             'EAVS reports, and state election offices.</p>')

def build_front(d, states, counties_by_state):
    body = []
    # map first — the owner's brief has the map leading the front page
    fills = {n: (VIOLET if (s["reg_pct_adults"] or 0) > 100 else band(s["reg_pct_adults"]))
             for n, s in states.items()}
    body.append("<h2>The Map</h2>")
    body.append(national_map({f: n for f, n in FIPS_STATE.items()}, fills))
    body.append(LEGEND)
    body.append(econ_map_block(d))
    body.append("<h2>Election Day vs today</h2>")
    body.append('<p class="edsub">Election Day — Tuesday, November 3, 2026</p>')
    body.append("<h3>Governors</h3>")
    body.append(cards_html(governor_ed_cards(d)))
    gm = re.search(r"Going in: (\d+) D / (\d+) R governors\. "
                   r"For 2027: (\d+) D / (\d+) R", d["baseline_text"])
    if gm:
        body.append(f'<p class="small">Going in, {gm.group(1)} governors '
                    f'were Democrats and {gm.group(2)} were Republicans. '
                    f'For 2027: {gm.group(3)} Democrats, {gm.group(4)} '
                    f'Republicans, Kansas not decided.</p>')
    body.append("<h3>The country</h3>")
    body.append(national_ed_table(d))
    body.append("<h2>The record</h2><div class='log'>")
    for ln in reversed(d["log_lines"]):
        body.append(f"<div>{esc(ln)}</div>")
    body.append("</div>")
    body.append("<h3>Past elections — the country</h3>")
    body.append(national_history_table(d))
    body.append("<h3>Past Election Days</h3>")
    body.append('<p class="small">National numbers as known on the day.</p>')
    body.append(past_days_table_html(d))
    adds = front_adds_lines(d, states, counties_by_state)
    if adds:
        body.append('<h2>What doesn\'t add up</h2><div class="adds">')
        for ln in adds: body.append(f"<div>{ln}</div>")
        body.append("</div>")
    # states as simple linked rows (the full table lives on the Data page)
    body.append('<h2 id="states">Every state</h2>')
    body.append("<table><tr><th class='l'>State</th><th>Registered</th>"
                "<th>Ballots % of adults</th></tr>")
    for name in sorted(states):
        s = states[name]
        rk, bk = reg_key(d, name), bal_key(d, name)
        if s["registered"] is not None:
            reg_cell, _ = flagged(d, name, "registered_voters",
                                  linked(d, rk, fmt_int(s["registered"])))
        else:
            reg_cell = "No registration" if name == "North Dakota" else "—"
        body.append(
            f'<tr><td class="l"><a href="states/{s["slug"]}/index.html">{esc(name)}</a></td>'
            f'<td>{reg_cell}</td>'
            f'<td>{linked(d, bk, fmt_pct(s["bal_pct_adults"]))}</td></tr>')
    body.append("</table>")
    # rankings by ballots % of adults — highest 10 and lowest 10
    body.append("<h2>Rankings</h2>")
    ranked = [s for s in states.values() if s["bal_pct_adults"] is not None and s["name"] != "District of Columbia"]
    ranked.sort(key=lambda s: -s["bal_pct_adults"])
    ranks, prev, rk_ = {}, None, 0
    for i, s in enumerate(ranked):
        if s["bal_pct_adults"] != prev: rk_ = i + 1; prev = s["bal_pct_adults"]
        ranks[s["name"]] = rk_
    def rank_rows(rows):
        out = []
        for s in rows:
            bk = bal_key(d, s["name"])
            bal_r, _ = flagged(d, s["name"], "ballots_cast",
                               linked(d, bk, fmt_int(s["ballots"])))
            out.append(f'<tr><td>{ranks[s["name"]]}</td><td class="l"><a href="states/{s["slug"]}/index.html">{esc(s["name"])}</a></td>'
                       f'<td>{chip(s["bal_pct_adults"])}{linked(d, bk, fmt_pct(s["bal_pct_adults"]))}</td><td>{bal_r}</td>'
                       f'<td>{linked(d, "census-pl-94171", fmt_int(s["vap"]))}</td></tr>')
        return out
    rhead = ("<table><tr><th>Rank</th><th class='l'>State</th>"
             "<th>Ballots % of adults</th><th>Ballots cast</th>"
             "<th>Adults (2020)</th></tr>")
    body.append("<h3>Ballots % of adults — highest 10</h3>")
    body.append(rhead); body.extend(rank_rows(ranked[:10])); body.append("</table>")
    body.append("<h3>Ballots % of adults — lowest 10</h3>")
    body.append(rhead); body.extend(rank_rows(ranked[-10:])); body.append("</table>")
    body.append(econ_rank_tables(d, states))
    body.append('<p class="small"><a href="data/index.html">Data</a> · <a href="definitions/index.html">Definitions</a></p>')
    write("index.html", page("Open Tally", "\n".join(body), depth=0))

def build_state_pages(d, states, counties_by_state, county_info):
    hist = {}
    for r in d["hist_states"]:
        hist.setdefault(r["state"], []).append(r)
    roll_co_de = d["roll_by_county"]
    reg_rows = d["reg_by_county"]
    for name, s in states.items():
        body = [f'<div class="crumb"><a href="../../index.html">Open Tally</a></div>', f"<h1>{esc(name)}</h1>"]
        # maps lead the state page: the state's own outline in its band
        # color, then the shaded county map (2026 where it exists, the
        # labeled 2024 map otherwise)
        clist = counties_by_state.get(name, [])
        fills, fips_names = {}, {}
        has_roll = any(roll_co_de.get((name, c["_nkey"])) for c in clist)
        map_note = ""
        for c in clist:
            key = (name, c["_nkey"])
            fips_names[c["county_fips"]] = c["county_name"]
            if has_roll:
                rr = roll_co_de.get(key)
                pct = fnum(rr["registered_pct_of_vap"]) if rr else None
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
                fills[c["county_name"]] = band(pct)
        if not has_roll and name != "Alaska":
            map_note = ("County shading: 2024 — ballots per 100 adults."
                        if name == "North Dakota" else
                        "County shading: 2024 — registered voters as a "
                        "share of adults.")
        outline_fill = (VIOLET if (s["reg_pct_adults"] or 0) > 100
                        else band(s["reg_pct_adults"]))
        body.append(state_outline_map(name, outline_fill))
        body.append(state_map(name, fips_names, fills))
        if map_note:
            body.append(f'<p class="src">{map_note}</p>')
        body.append(LEGEND)
        ed = state_ed_html(d, s)
        if ed: body.append(ed)
        adds = state_adds_lines(d, s, counties_by_state)
        if adds:
            body.append('<h2>What doesn\'t add up</h2><div class="adds">')
            for ln in adds: body.append(f"<div>{esc(ln)}</div>")
            body.append("</div>")
        body.append("<h2>Election Day</h2>")
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
        pct_html, pct_rule = pct_cell_html(d, s["reg_pct_adults"], rk)
        cvr = d["cvap_roll"].get(name)
        cvap_rows = ""
        if cvr:
            cvap_pct, _cr = pct_cell_html(d, fnum(cvr["pct_of_cvap"]), None)
            cvap_rows = (
                f'<tr><td class="l">Citizen adults (2020–2024)</td>'
                f'<td>{fmt_int(num(cvr["cvap"]))}</td></tr>'
                f'<tr><td class="l">Registered % of citizen adults</td>'
                f'<td>{cvap_pct}</td></tr>')
        fired = [f for f in (reg_flag, bal_flag) if f]
        county_rule = False
        body.append("<table>"
            f'<tr><td class="l">Registered voters</td><td>{reg_html}</td></tr>'
            f'<tr><td class="l">Adults (2020)</td><td>{linked(d, "census-pl-94171", fmt_int(s["vap"]))}</td></tr>'
            f'<tr><td class="l">Registered % of adults</td><td>{pct_html}</td></tr>'
            + cvap_rows +
            f'<tr><td class="l">Ballots cast</td><td>{bal_html}</td></tr>'
            f'<tr><td class="l">Ballots % of adults</td><td>{chip(s["bal_pct_adults"])}{linked(d, bk, fmt_pct(s["bal_pct_adults"]))}</td></tr>'
            f'<tr><td class="l">Turnout % of registered</td><td>{linked(d, bk, fmt_pct(s["turnout_pct"]))}</td></tr>'
            f'<tr><td class="l">Population (2020 Census)</td><td>{linked(d, "census-2020-apportionment", fmt_int(s["census_pop"]))}</td></tr>'
            f'<tr><td class="l">Registered % of population</td><td>{chip(s["pct_census_registered"])}{linked(d, rk, fmt_pct(s["pct_census_registered"]))}</td></tr>'
            f'<tr><td class="l">Ballots % of population</td><td>{chip(s["pct_census_ballots"])}{linked(d, bk, fmt_pct(s["pct_census_ballots"]))}</td></tr>'
            f'<tr><td class="l">Status</td><td class="l">{"Still counting" if s["status"]=="still counting" else "—"}</td></tr>'
            "</table>")
        body.append(f'<p class="src">Source: {esc(s["source"])}</p>')
        if cvr:
            body.append(f'<p class="src">Citizen adults — '
                        f'{esc(d["cvap_state"][name]["source"])}.</p>')
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
        body.append(f'<p class="src">Citations: {cites}</p>')
        if name in hist:
            body.append("<h2>Past Elections</h2>")
            body.append("<table><tr><th>Year</th><th>Registered</th><th>Ballots cast</th><th>Turnout % of registered</th></tr>")
            for r in sorted(hist[name], key=lambda x: x["election_year"]):
                hk = hist_key_for_year(d, name, r["election_year"])
                body.append(f'<tr><td>{esc(r["election_year"])}</td><td>{linked(d, hk, fmt_int(num(r["registered_voters"])))}</td>'
                            f'<td>{linked(d, hk, fmt_int(num(r["ballots_cast"])))}</td><td>{chip(fnum(r["turnout_pct_registered"]))}{linked(d, hk, fmt_pct(fnum(r["turnout_pct_registered"])))}</td></tr>')
            body.append("</table>")
            arows = [r for r in d["anoms"] if r["state"] == name]
            if arows:
                body.append("<h2>2026 next to past elections</h2>")
                body.append("<table><tr><th class='l'>Measure</th><th>2026</th>"
                            "<th>2022</th><th>2018</th><th>Change from 2022</th>"
                            "<th>Change from 2018</th></tr>")
                body.extend(anoms_rows_html(arows))
                body.append("</table>")
                body.append(ANOMS_SRC)
        # counties
        body.append("<h2>Counties</h2>")
        body.append("<table><tr><th class='l'>County</th><th>Registered</th><th>Adults (2020)</th><th>Registered % of adults</th>"
                    + ("<th>Registered % of citizen adults</th>" if has_roll else "")
                    + "</tr>")
        ck = county_reg_key(d, name)
        for c in clist:
            key = (name, c["_nkey"])
            rr = roll_co_de.get(key)
            gr = reg_rows.get(key)
            reg = num(gr["registered_voters"]) if gr else None
            pct = fnum(rr["registered_pct_of_vap"]) if rr else None
            reg_c = linked(d, ck, fmt_int(reg)) if reg is not None else fmt_int(reg)
            pct_c, fired_rule = pct_cell_html(d, pct, ck)
            if fired_rule: county_rule = True
            cvap_cell = ""
            if has_roll:
                cv = d["cvap_by_fips"].get(c["county_fips"])
                cpct = round(reg / cv * 100, 1) if (reg and cv) else None
                cc_, _r = pct_cell_html(d, cpct, None)
                cvap_cell = f'<td>{cc_}</td>'
            body.append(f'<tr><td class="l"><a href="../../counties/{s["slug"]}/{c["_slug"]}/index.html">{esc(c["county_name"])}</a></td>'
                        f'<td>{reg_c}</td><td>{linked(d, "census-pl-94171", fmt_int(num(c["voting_age_population_2020"])))}</td>'
                        f'<td>{pct_c}</td>{cvap_cell}</tr>')
        body.append("</table>")
        if name == "Alaska":
            body.append("<h2>House Districts</h2>")
            body.append("<table><tr><th class='l'>District</th><th>Registered</th><th>Adults (2020)</th><th>Registered % of adults</th></tr>")
            ak_ck = county_reg_key(d, "Alaska")
            for r in sorted(d["roll_ak"], key=lambda x: int(x["district"].split()[-1])):
                pct = fnum(r["registered_pct_of_vap"])
                pct_a, fired_rule = pct_cell_html(d, pct, ak_ck)
                if fired_rule: county_rule = True
                body.append(f'<tr><td class="l">{esc(r["district"])}</td><td>{linked(d, ak_ck, fmt_int(num(r["registered_voters"])))}</td>'
                            f'<td>{linked(d, "census-pl-94171", fmt_int(num(r["voting_age_population_2020"])))}</td>'
                            f'<td>{pct_a}</td></tr>')
            body.append("</table>")
            ak_src = next((r["source"] for r in d["county_reg"] if r["state"] == "Alaska"), "")
            body.append(f'<p class="src">Source: {esc(ak_src)}</p>')
            if ak_ck in d["citations"]:
                cc = d["citations"][ak_ck]
                body.append(f'<p class="src">Citation: <a class="cite" href="{esc(cc["url"])}">'
                            f'{esc(cc["publisher"])} — {esc(cc["title"])}</a></p>')
        extra = state_extra_sections(d, s)
        if extra: body.append(extra)
        sents = [flag_sentence(d, fr, s) for fr in fired]
        if pct_rule or county_rule:
            if (s["reg_pct_adults"] or 0) > 100:
                sents.append(f"{name} has more registered voters than adults "
                             f"who live there: {s['registered']:,} registered "
                             f"voters, {s['vap']:,} adults.")
            else:
                sents.append(f"Some counties in {name} have more registered "
                             f"voters than adults who live there.")
        fb = flags_block(sents)
        if fb: body.append(fb)
        write(f'states/{s["slug"]}/index.html',
              page(name, "\n".join(body), depth=2, src_html=footer_src(d, rk)))

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
            pct = fnum(rr["registered_pct_of_vap"]) if rr else None
            ck = county_reg_key(d, name)
            reg_c = linked(d, ck, fmt_int(reg)) if reg is not None else fmt_int(reg)
            pct_c, fired_rule = pct_cell_html(d, pct, ck, bare_none=True)
            body = [f'<div class="crumb"><a href="../../../index.html">Open Tally</a> · <a href="../../../states/{s["slug"]}/index.html">{esc(name)}</a></div>',
                    f"<h1>{esc(c['county_name'])}</h1>", "<h2>Election Day</h2>", "<table>",
                    f'<tr><td class="l">State</td><td class="l"><a href="../../../states/{s["slug"]}/index.html">{esc(name)}</a></td></tr>',
                    f'<tr><td class="l">Population (2020)</td><td>{linked(d, "census-pl-94171", fmt_int(num(c["total_population_2020"])))}</td></tr>',
                    f'<tr><td class="l">Adults (2020)</td><td>{linked(d, "census-pl-94171", fmt_int(num(c["voting_age_population_2020"])))}</td></tr>',
                    f'<tr><td class="l">Registered voters</td><td>{reg_c}</td></tr>',
                    f'<tr><td class="l">Registered % of adults</td><td>{pct_c}</td></tr>',
                    "</table>"]
            mtb = d["mt_by_county"].get(key) if name == "Montana" else None
            if mtb is not None:
                body.insert(len(body) - 1,
                    f'<tr><td class="l">Ballots cast</td>'
                    f'<td><a class="cite" href="{esc(d["mt_src"][1])}">{fmt_int(mtb)}</a></td></tr>')
            cv = d["cvap_by_fips"].get(c["county_fips"])
            if reg and cv:
                cpct = round(reg / cv * 100, 1)
                cc_, _cf = pct_cell_html(d, cpct, ck, bare_none=True)
                body.insert(len(body) - 1,
                    f'<tr><td class="l">Citizen adults (2020–2024)</td><td>{fmt_int(cv)}</td></tr>'
                    f'<tr><td class="l">Registered % of citizen adults</td><td>{cc_}</td></tr>')
            pop = num(c["total_population_2020"])
            vap = num(c["voting_age_population_2020"])
            if reg and pop and reg > pop:
                body.insert(2, f'<p class="plainline">More registered voters '
                               f'than residents: {reg:,} registered, {pop:,} '
                               f'total residents.</p>')
            elif reg and vap and reg > vap:
                body.insert(2, f'<p class="plainline">More registered voters '
                               f'than adults: {reg:,} registered, {vap:,} '
                               f'adults.</p>')
            if gr:
                body.append(f'<p class="src">Registered — Basis: {esc(gr["basis"])} · {esc(fmt_date(gr["report_date"]))}</p>')
                body.append(f'<p class="src">Source: {esc(gr["source"])}</p>')
                if ck in d["citations"]:
                    cc = d["citations"][ck]
                    body.append(f'<p class="src">Citation: <a class="cite" href="{esc(cc["url"])}">'
                                f'{esc(cc["publisher"])} — {esc(cc["title"])}</a></p>')
            body.append(f'<p class="src">Adults — <a class="cite" href="{esc(PL_URL)}">U.S. Census Bureau</a>, 2020 Census Redistricting Data (PL 94-171), Table P3</p>')
            if reg and cv:
                body.append(f'<p class="src">Citizen adults — {esc(d["cvap_county_src"])}</p>')
            if name == "Montana" and mtb is not None:
                body.append(f'<p class="src">Ballots — {esc(d["mt_src"][0])}</p>')
            hr = d["hist_by_fips"].get((name, c["county_fips"]))
            if hr and any(num(hr[k]) for k in ("reg_2022", "ballots_2022", "reg_2024", "ballots_2024")):
                body.append("<h2>Past Elections</h2>")
                body.append("<table><tr><th>Year</th><th>Registered</th><th>Ballots cast</th><th>Turnout % of registered</th></tr>")
                for yr in ("2022", "2024"):
                    rg, bl = num(hr[f"reg_{yr}"]), num(hr[f"ballots_{yr}"])
                    tp = round(bl / rg * 100, 1) if (rg and bl is not None) else None
                    hk = "eac-eavs-2022-report" if yr == "2022" else "eac-eavs-2024-report"
                    body.append(f'<tr><td>{yr}</td><td>{linked(d, hk, fmt_int(rg))}</td>'
                                f'<td>{linked(d, hk, fmt_int(bl))}</td><td>{chip(tp)}{fmt_pct(tp)}</td></tr>')
                body.append("</table>")
                if name == "Wisconsin" and hr["notes"]:
                    body.append(f'<p class="src">{esc(hr["notes"])}</p>')
            if fired_rule:
                fb = flags_block([f"{c['county_name']} has more registered "
                                  f"voters than adults who live there: "
                                  f"{reg:,} registered voters, {vap:,} "
                                  f"adults."])
                if fb: body.append(fb)
            write(f'counties/{s["slug"]}/{c["_slug"]}/index.html',
                  page(c["county_name"], "\n".join(body), depth=3, src_html=footer_src(d, ck)))
            n += 1
    return n

def build_data(d, states):
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    csvs = ["turnout-2026-11-03.csv", "census-registered-2026.csv", "vap-2020-pl.csv",
            "county-vap-2020.csv", "county-registered-all.csv",
            "county-roll-integrity-all.csv", "ak-district-roll-integrity.csv",
            "turnout-history-national.csv", "turnout-history-states.csv",
            "cvap-state.csv", "cvap-county.csv", "state-roll-integrity-cvap.csv",
            "removals.csv", "ballots-detail.csv", "mail-rejection-reasons.csv",
            "rules-facts.csv", "registration-splits.csv", "polling-places.csv",
            "county-history-eavs.csv", "not-published.csv",
            "unofficial-vs-certified-2024.csv", "combination-quadrants.csv",
            "county-anomalies.csv", "county-ballots-mt.csv",
            "anomalies-vs-history.csv", "PAST-ELECTION-DAYS.md",
            "state-economics-tracker.csv", "flags.csv"]
    for fn in csvs:
        shutil.copy(os.path.join(SRC, fn), os.path.join(OUT, "data", fn))
    sj = []
    for name in sorted(states):
        s = states[name]
        sj.append({"state": name, "slug": s["slug"], "registered_voters": s["registered"],
                   "ballots_cast": s["ballots"], "turnout_pct_registered": s["turnout_pct"],
                   "status": s["status"], "adults_2020": s["vap"],
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
                   "registered_pct_of_adults": fnum(r["registered_pct_of_vap"])})
    with open(os.path.join(OUT, "data", "registered-share-of-adults.json"), "w") as f:
        json.dump(ri, f, indent=1)
    files = sorted(os.listdir(os.path.join(OUT, "data")))
    body = ["<h1>Data</h1>", "<table><tr><th class='l'>File</th><th>Size</th></tr>"]
    for fn in files:
        sz = os.path.getsize(os.path.join(OUT, "data", fn))
        body.append(f'<tr><td class="l"><a href="{fn}">{esc(fn)}</a></td><td>{sz:,} bytes</td></tr>')
    body.append("</table>")
    # the full state table (the front page carries the simple list)
    body.append("<h2>States — the full table</h2>")
    body.append("<table><tr><th class='l'>State</th><th>Registered</th><th>Adults (2020)</th>"
                "<th>Registered % of adults</th><th>Ballots cast</th><th>Ballots % of adults</th>"
                "<th>Turnout % of registered</th><th class='l'>Status</th></tr>")
    for name in sorted(states):
        s = states[name]
        status = "Still counting" if s["status"] == "still counting" else "—"
        rk, bk = reg_key(d, name), bal_key(d, name)
        if s["registered"] is not None:
            reg_cell, _ = flagged(d, name, "registered_voters",
                                  linked(d, rk, fmt_int(s["registered"])))
        else:
            reg_cell = "No registration" if name == "North Dakota" else "—"
        pct_cell, _ = pct_cell_html(d, s["reg_pct_adults"], rk)
        if s["ballots"] is not None:
            bal_cell, _ = flagged(d, name, "ballots_cast",
                                  linked(d, bk, fmt_int(s["ballots"])))
        else:
            bal_cell = fmt_int(s["ballots"])
        body.append(
            f'<tr><td class="l"><a href="../states/{s["slug"]}/index.html">{esc(name)}</a></td>'
            f'<td>{reg_cell}</td><td>{linked(d, "census-pl-94171", fmt_int(s["vap"]))}</td>'
            f'<td>{pct_cell}</td>'
            f'<td>{bal_cell}</td><td>{chip(s["bal_pct_adults"])}{linked(d, bk, fmt_pct(s["bal_pct_adults"]))}</td>'
            f'<td>{linked(d, bk, fmt_pct(s["turnout_pct"]))}</td><td class="l">{status}</td></tr>')
    body.append("</table>")
    # the past-election corpus: national series, past Election Days,
    # and 2026 next to past elections (numbers only)
    body.append("<h2>Past elections — the country</h2>")
    body.append(national_history_table(d))
    body.append("<h2>Past Election Days</h2>")
    body.append('<p class="small">National numbers as known on the day.</p>')
    body.append(past_days_table_html(d))
    body.append("<h2>2026 next to past elections</h2>")
    body.append("<table><tr><th class='l'>State</th><th class='l'>Measure</th>"
                "<th>2026</th><th>2022</th><th>2018</th>"
                "<th>Change from 2022</th><th>Change from 2018</th></tr>")
    body.extend(anoms_rows_html(d["anoms"], with_state=True))
    body.append("</table>")
    body.append(ANOMS_SRC)
    # figures no office published — the register of gaps
    body.append("<h2>Figures that are not published</h2>")
    body.append("<table><tr><th class='l'>Jurisdiction</th><th class='l'>Figure</th>"
                "<th class='l'>What exists instead</th></tr>")
    for r in d["notpub"]:
        body.append(f'<tr><td class="l">{esc(r["jurisdiction"])}</td>'
                    f'<td class="l">{esc(r["figure"])}</td>'
                    f'<td class="l">{esc(r["what_exists_instead"])}</td></tr>')
    body.append("</table>")
    # election-night figures against the certified figures, 2024
    body.append("<h2>Election night and certified — 2024</h2>")
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
    # rolls and ballots combined
    body.append("<h2>Rolls and ballots, combined</h2>")
    body.append("<table><tr><th class='l'>State</th><th>Registered % of adults</th>"
                "<th>Ballots % of adults</th><th class='l'>Quadrant</th></tr>")
    for r in d["quadrants"]:
        body.append(f'<tr><td class="l">{esc(r["state"])}</td>'
                    f'<td>{chip(fnum(r["registered_pct_of_vap"]))}{fmt_pct(fnum(r["registered_pct_of_vap"]))}</td>'
                    f'<td>{chip(fnum(r["ballots_pct_of_vap"]))}{fmt_pct(fnum(r["ballots_pct_of_vap"]))}</td>'
                    f'<td class="l">{esc(r["quadrant"])}</td></tr>')
    body.append("</table>")
    # county anomalies, as published
    body.append("<h2>County anomalies</h2>")
    body.append("<table><tr><th class='l'>State</th><th class='l'>County</th>"
                "<th class='l'>Type</th><th class='l'>Value</th>"
                "<th class='l'>State reference</th><th>Deviation</th></tr>")
    for r in d["county_anoms"]:
        body.append(f'<tr><td class="l">{esc(r["state"])}</td>'
                    f'<td class="l">{esc(r["county"])}</td>'
                    f'<td class="l">{esc(r["anomaly_type"])}</td>'
                    f'<td class="l">{esc(r["value"])}</td>'
                    f'<td class="l">{esc(r["state_reference_value"])}</td>'
                    f'<td>{esc(r["deviation"])}</td></tr>')
    body.append("</table>")
    # mail-ballot rejection reasons, 2024
    body.append("<h2>Mail-ballot rejection reasons — 2024</h2>")
    body.append("<table><tr><th class='l'>State</th><th class='l'>Reason</th>"
                "<th>Rejected</th></tr>")
    for st in sorted(d["rej_reasons"]):
        for r in d["rej_reasons"][st]:
            body.append(f'<tr><td class="l">{esc(st)}</td>'
                        f'<td class="l">{esc(r["reason"])}</td>'
                        f'<td>{fmt_int(num(r["rejected_count"]))}</td></tr>')
    body.append("</table>")
    write("data/index.html", page("Data", "\n".join(body), depth=1))

def build_definitions(d):
    defs = [
        ("Registered voters", "People on a state's voter rolls."),
        ("Adults (2020)", "Residents age 18 and over — U.S. Census Bureau, 2020 Census."),
        ("Registered % of adults", "Registered voters ÷ adults."),
        ("Citizen adults (2020–2024)", "Residents age 18 and over who are U.S. citizens — U.S. Census Bureau, Citizen Voting Age Population tabulation from the American Community Survey."),
        ("Registered % of citizen adults", "Registered voters ÷ citizen adults."),
        ("Ballots cast", "Ballots counted in the general election of November 3, 2026."),
        ("Ballots % of adults", "Ballots cast ÷ adults."),
        ("Turnout % of registered", "Ballots cast ÷ registered voters."),
        ("Still counting", "The state has not published a final ballots-cast total."),
        ("No registration", "North Dakota does not register voters."),
        ("Violet", "The number does not agree: with the same office's other number, or with the number of people who live there."),
    ]
    body = ["<h1>Definitions</h1>", '<dl class="defs">']
    for term, txt in defs:
        body.append(f"<dt>{esc(term)}</dt><dd>{esc(txt)}</dd>")
    body.append("</dl>")
    body.append("<h2>Shading</h2>")
    body.append('<p class="legend">Registered % of adults: '
                f'{chip(80)}Under 90% &nbsp; {chip(95)}90% – 100% &nbsp; '
                f'{vchip()}More registered voters than adults who live there &nbsp; {chip(None)}No data</p>')
    write("definitions/index.html", page("Definitions", "\n".join(body), depth=1))

def main():
    global PL_URL
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
    mt, mt_valid = {}, {c["_nkey"] for c in counties_by_state.get("Montana", [])}
    for r in d["mt_ballots"]:
        for k in county_key_variants(r["county"]):
            if k in mt_valid:
                mt[("Montana", k)] = num(r["ballots_cast"])
                break
    d["mt_by_county"] = mt
    if d["mt_ballots"]:
        d["mt_src"] = (d["mt_ballots"][0]["source"], d["mt_ballots"][0]["source_url"])
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    build_front(d, states, counties_by_state)
    build_state_pages(d, states, counties_by_state, None)
    n_counties = build_county_pages(d, states, counties_by_state)
    build_data(d, states)
    build_definitions(d)
    print(f"states: {len(states)}  county pages: {n_counties}")
    print(f"site: {OUT}")

if __name__ == "__main__":
    main()
