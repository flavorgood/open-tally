#!/usr/bin/env python3
"""Extract current Alaska House district 2020 VAP from official Census CD119.
Requires Python 3 + openpyxl + pdftotext (only to regenerate final-plan text).
Download the official source files beside this script as documented in README.
Extraction then runs offline; no API key is needed.
"""
from pathlib import Path
import csv, hashlib, io, json, re, zipfile
import openpyxl
BASE = Path(__file__).resolve().parent
fields = [r[1] for r in openpyxl.load_workbook(BASE/'cd119-geographic-header-record.xlsx', data_only=True).active.values if isinstance(r[2], int)]
assert len(fields)==97
matrix = openpyxl.load_workbook(BASE/'cd119-table-matrix.xlsx', data_only=True)
# The Table_Segments sheet defines physical table order within each segment.
segments = {}
for table, segment, n, order in list(matrix['CD119 Table_Segments'].values)[1:]:
    if table and isinstance(segment,int): segments.setdefault(segment,[]).append((int(order),table.strip(),int(n)))
positions = {}
for segment,tables in segments.items():
    pos=5 # five linking fields precede data values
    for order,table,n in sorted(tables):
        positions[table]=(segment,pos)
        pos+=n
assert positions['P1']==(5,5) and positions['P10']==(6,5)
assert any(r[1]=='P10' and r[2]=='P0100001' and r[3]==6 and r[5].strip().startswith('Total') for r in matrix.active.values)
z=zipfile.ZipFile(BASE/'ak2020.cd19.zip')
def rows(name): return csv.reader(io.TextIOWrapper(z.open(name),encoding='utf-8'),delimiter='|')
geo=[dict(zip(fields,r)) for r in rows('akgeo2020.cd19')]
districts=[g for g in geo if g['SUMLEV']=='620' and g['GEOVAR']=='L9' and g['GEOCOMP']=='00' and g['CHARITER']=='000']
assert len(districts)==40 and sorted(int(g['SLDL24']) for g in districts)==list(range(1,41))
def data(table):
    seg,pos=positions[table]
    return {r[4]:int(r[pos]) for r in rows(f'ak{seg:05}2020.cd19') if r[2]=='000'}
pop,vap=data('P1'),data('P10')
final_totals={int(m[1]):int(m[2].replace(',','')) for m in re.finditer(r'^\s+(\d+)\s+([\d,]+)\s+18,335',(BASE/'alaska2023_final_totals.txt').read_text(),re.M)}
assert len(final_totals)==40
out=[]
for g in sorted(districts,key=lambda g:int(g['SLDL24'])):
    d=int(g['SLDL24']); log=g['LOGRECNO']
    assert pop[log]==int(g['POP100'])==final_totals[d], (d,pop[log],g['POP100'],final_totals[d])
    assert 0<vap[log]<pop[log]
    out.append(dict(district=d,total_population_2020=pop[log],voting_age_population_2020=vap[log],census_geoid=g['GEOID'],logrecno=log,boundary_vintage=2024,dataset='2020 Census CD119',vap_variable='P0100001'))
state=next(g for g in geo if g['SUMLEV']=='040')
assert sum(r['total_population_2020'] for r in out)==pop[state['LOGRECNO']]==733391
assert sum(r['voting_age_population_2020'] for r in out)==vap[state['LOGRECNO']]
with (BASE/'alaska_house_2020_vap_2024_boundaries.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(BASE.iterdir()) if p.is_file() and p.name!='sha256.json'}
(BASE/'sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'districts':len(out),'all_final_plan_totals_match':True,'state_population':sum(r['total_population_2020'] for r in out),'state_vap':sum(r['voting_age_population_2020'] for r in out)},indent=2))
