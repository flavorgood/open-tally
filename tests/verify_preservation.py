"""Compare a pre-change generated site against this presentation-only build."""
import hashlib,json,sys,re
from pathlib import Path
from collections import Counter
from lxml import html
base=Path(sys.argv[1]);site=Path(__file__).resolve().parents[1]/'site'
paths=lambda root:{str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
before,after=paths(base),paths(site)
assert before==after,(before-after,after-before)
def text(node):return ' '.join(' '.join(node.itertext()).split())
def facts(path):
 d=html.parse(str(path))
 tables=Counter(tuple(tuple(text(c) for c in r.xpath('./th|./td')) for r in t.xpath('.//tr')) for t in d.xpath('//main//table'))
 cites=Counter((a.get('href'),text(a)) for a in d.xpath('//a[contains(concat(" ",@class," ")," cite ")]'))
 panes=Counter((p.get('class'),text(p)) for p in d.xpath('//div[contains(concat(" ",@class," ")," yr-pane ")]'))
 words=Counter(re.findall(r"\S+",text(d.xpath("//main")[0])))
 return tables,cites,panes,words
n=0;downloads=0
for rel in sorted(before):
 if rel.endswith('.html'):
  old,new=facts(base/rel),facts(site/rel)
  assert old[:3]==new[:3],rel
  assert not (old[3]-new[3]),(rel,old[3]-new[3])
  n+=1
 elif not rel.startswith('assets/'):
  assert (base/rel).read_bytes()==(site/rel).read_bytes(),rel
  downloads+=1
print(f'PASS: {n} page route/table/citation/year-pane records; {downloads} other generated files byte-identical')
