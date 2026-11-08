// Runs the real browser script against a small, explicit DOM test double.
// This validates interaction logic, not browser layout, accessibility or rendering.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../assets/navigation.js'), 'utf8');
class Element {
  constructor(tag='div') { this.tag=tag; this.dataset={}; this.listeners={}; this.children=[]; this.value=''; this.hidden=false; this.textContent=''; this.disabled=false; this.attrs={}; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatchEvent(event) { for(const fn of this.listeners[event.type] || []) fn(event); }
  click() { if(!this.disabled) this.dispatchEvent({type:'click'}); }
  fill(value) { this.value=value; this.dispatchEvent({type:'input'}); }
  focus() { this.focused=true; }
  scrollIntoView() { this.scrolled=true; }
  before(node) { (this.beforeNodes ||= []).push(node); }
  after(node) { (this.afterNodes ||= []).push(node); }
  append(node) { this.children.push(node); }
  setAttribute(k,v) { this.attrs[k]=v; }
  getAttribute(k) { return k==='href'?this.href:this.attrs[k]; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    if(selector==='tr') return this.rows || [];
    if(selector==='td') return this.cells || [];
    if(selector==='button') return this.children.filter(e=>e.tag==='button');
    if(selector==='span') return this.children.filter(e=>e.tag==='span');
    if(selector==='input') return this.children.filter(e=>e.tag==='input');
    if(selector.startsWith('.')) return this.children.filter(e=>e.className===selector.slice(1));
    throw new Error('Unsupported selector '+selector);
  }
  set innerHTML(value) {
    if(value.includes('filter-controls')) {
      const input=new Element('input'), clear=new Element('button'), count=new Element('p');
      clear.className='filter-clear';count.className='filter-count';this.children=[input,clear,count];
    } else if(value.includes('Previous')) {
      this.children=[new Element('button'),new Element('span'),new Element('button'),new Element('button')];
    } else throw new Error('Unexpected test markup');
  }
}
function table(kind, names) {
  const table=new Element('table');table.dataset.filterTable=kind;
  table.rows=names.map(name=>{const row=new Element('tr');row.cells=[new Element('td')];row.cells[0].textContent=name;return row;});
  return table;
}
function run({tables=[],radios=[],links=[],href='https://preview.test/index.html'}={}) {
  const created=[],listeners={},location=new URL(href);
  const document={
    querySelectorAll(selector){ return ({'[data-filter-table]':tables,'main table':tables,'.yr-in':radios,'a[href]':links})[selector] || []; },
    createElement(tag){const e=new Element(tag);created.push(e);return e;}
  };
  const window={location,addEventListener(type,fn){listeners[type]=fn;}};
  const history={replaceState(a,b,url){location.href=String(url);}};
  vm.runInNewContext(source,{document,window,location,history,URL,Event:class{constructor(type){this.type=type;}}});
  return {created,location,listeners};
}
const visible=t=>t.rows.filter(r=>!r.hidden).map(r=>r.cells[0].textContent);
const t=table('states',['California','North Carolina','South Carolina','Texas','New York']);
['CA','NC','SC','TX','NY'].forEach((code,i)=>{t.rows[i].dataset.abbreviation=code;});
run({tables:[t],href:'https://preview.test/states/index.html?q=TX'});
const tools=t.beforeNodes[0], input=tools.querySelector('input');
assert.deepEqual(visible(t),['Texas']);
input.fill('ca');assert.deepEqual(visible(t),['California']);
input.fill('Carolina');assert.deepEqual(visible(t),['North Carolina','South Carolina']);
input.fill('zzzz');assert.deepEqual(visible(t),[]);assert.equal(t.afterNodes[0].hidden,false);
tools.querySelector('.filter-clear').click();assert.equal(visible(t).length,5);assert.equal(input.focused,true);
console.log('PASS: state query, exact postal code, partial name, no matches and clear');
const counties=table('counties',Array.from({length:254},(_,i)=>i===50?'Harris County':`County ${i+1}`));
run({tables:[counties]});
const controls=counties.beforeNodes[0],pager=counties.afterNodes[0].afterNodes[0],buttons=pager.querySelectorAll('button');
assert.equal(visible(counties).length,25);assert.equal(buttons[0].disabled,true);
buttons[1].click();assert.equal(visible(counties)[0],'County 26');assert.equal(pager.querySelector('span').textContent,'Page 2 of 11');
controls.querySelector('input').fill('Harris');assert.deepEqual(visible(counties),['Harris County']);assert.equal(pager.hidden,true);
controls.querySelector('.filter-clear').click();assert.equal(pager.querySelector('span').textContent,'Page 1 of 11');
buttons[2].click();assert.equal(visible(counties).length,254);
buttons[2].click();assert.equal(visible(counties).length,25);
for(let i=0;i<15;i++) buttons[1].click();
assert.equal(visible(counties).length,4);assert.equal(buttons[1].disabled,true);
console.log('PASS: county paging, search, reset, show all, show 25 and last-page bounds');
const files=table('files',['citations.csv','turnout-2026-11-03.csv']);run({tables:[files]});
files.beforeNodes[0].querySelector('input').fill('CITATIONS');assert.deepEqual(visible(files),['citations.csv']);
console.log('PASS: source-file search');
const radios=['2026','2024','2022'].map(year=>{const r=new Element('input');r.id='yr'+year;r.checked=year==='2026';return r;});
const links=['../../../states/texas/index.html#counties','../../../states/index.html','https://source.test/record','../other/index.html'].map(href=>{const a=new Element('a');a.href=href;return a;});
const test=run({radios,links,href:'https://preview.test/counties/texas/harris-county/index.html?year=2024'});
assert.equal(radios[1].checked,true);assert.equal(links[0].href,'/states/texas/index.html?year=2024#counties');
assert.equal(links[1].href,'../../../states/index.html');assert.equal(links[2].href,'https://source.test/record');
radios.forEach(r=>r.checked=r.id==='yr2022');radios[2].dispatchEvent({type:'change'});
assert.equal(test.location.searchParams.get('year'),'2022');assert.match(links[0].href,/year=2022#counties/);
test.location.search='?year=2024';radios.forEach(r=>r.checked=r.id==='yr2022');test.listeners.popstate();assert.equal(radios[1].checked,true);
console.log('PASS: initial year, year change URL, same-origin place links, hash preservation and history restore');
