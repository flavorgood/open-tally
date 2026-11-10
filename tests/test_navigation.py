"""Browser regression checks. Build with python generate.py; serve site on port 8767."""
import json, os, mimetypes
from urllib.parse import urlparse, unquote
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8767'
ARTIFACTS = Path('/tmp/open-tally-ux-proof')
ARTIFACTS.mkdir(exist_ok=True)

def run():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('BROWSER_EXECUTABLE','/usr/bin/chromium'), headless=True, args=['--no-sandbox'])
        def local_route(route):
            url=urlparse(route.request.url)
            if url.hostname!='127.0.0.1':
                return route.abort()
            root=Path(__file__).resolve().parents[1]/'site'
            path=(root/unquote(url.path).lstrip('/')).resolve()
            if root not in path.parents or not path.is_file():
                return route.fulfill(status=404,body='Not found')
            return route.fulfill(body=path.read_bytes(),content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')
        browser_context=browser.new_context()
        browser_context.route('**/*',local_route)
        page = browser_context.new_page()
        page.set_viewport_size({'width':1280,'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/index.html', wait_until='domcontentloaded')
        assert page.get_by_role('navigation',name='Primary').locator('a > span:last-child').all_text_contents() == ['Overview','States & Counties','Compare','Data & Sources']
        assert page.locator('nav.mainnav a[aria-current=page] > span:last-child').inner_text() == 'Overview'
        page.get_by_label('Start with a state').fill('TX')
        page.get_by_role('button',name='Find my state').click()
        page.wait_for_url('**/states/index.html?q=TX')
        assert page.locator('[data-filter-table=states] tr:visible').count() == 2
        assert page.locator('[data-filter-table=states] tr:visible').last.inner_text().startswith('Texas')
        page.get_by_role('button',name='Clear',exact=True).click()
        assert page.locator('[data-filter-table=states] tr:visible').count() == 13
        page.get_by_role('button',name='Show all 51',exact=True).click()
        assert page.locator('[data-filter-table=states] tr:visible').count() == 52
        page.get_by_label('Search states').fill('zzzz')
        assert page.locator('.filter-empty').is_visible()
        page.get_by_role('button',name='Clear',exact=True).click()
        results.append('Home finder, postal abbreviation, empty state and reset pass')
        page.goto(BASE+'/states/texas/index.html#counties',wait_until='domcontentloaded')
        assert page.locator('[data-filter-table=counties] tr:visible').count() == 26
        page.get_by_role('button',name='Next',exact=True).click()
        assert page.locator('.filter-pager span').inner_text() == 'Page 2 of 11'
        page.get_by_label('Search counties').fill('Harris County')
        assert page.locator('[data-filter-table=counties] tr:visible').count() == 2
        assert page.locator('[data-filter-table=counties] tr:visible').last.inner_text().startswith('Harris County')
        page.get_by_role('button',name='Clear',exact=True).click()
        page.get_by_role('button',name='Show all 254').click()
        assert page.locator('[data-filter-table=counties] tr:visible').count() == 255
        page.get_by_role('button',name='Show 25 at a time').click()
        assert page.locator('[data-filter-table=counties] tr:visible').count() == 26
        results.append('Texas 254-county search, pagination and show-all/reset pass')
        page.goto(BASE+'/counties/texas/harris-county/index.html?year=2024',wait_until='domcontentloaded')
        assert page.locator('#yr2024').is_checked()
        assert page.locator('.yp2024').is_visible()
        assert not page.locator('.yp2026').is_visible()
        assert '2024 source:' in page.locator('.yp2024').inner_text()
        assert 'November 2026 Voter Registration Figures' not in page.locator('main').inner_text()
        page.locator('.yr-tabs label[for=yr2022]').click()
        assert 'year=2022' in page.url
        page.reload(wait_until='domcontentloaded')
        assert page.locator('#yr2022').is_checked()
        page.locator('.crumb a').last.click()
        page.wait_for_url('**/states/texas/index.html?year=2022#counties')
        assert page.locator('#yr2022').is_checked()
        page.go_back(wait_until='domcontentloaded')
        assert page.locator('#yr2022').is_checked()
        results.append('County year-specific sources, URL/reload, parent navigation and Back pass')
        page.goto(BASE+'/data/index.html',wait_until='domcontentloaded')
        assert page.locator('.section-index a').count() >= 10
        anchors = page.locator('.section-index a').evaluate_all('(links)=>links.map(a=>a.hash.slice(1))')
        assert all(page.locator('[id="'+anchor+'"]').count()==1 for anchor in anchors)
        page.get_by_text('Source files',exact=True).filter(visible=True).last.click()
        page.get_by_label('Search files').fill('county')
        assert page.locator('[data-filter-table=files] tr:visible').count() >= 2
        results.append('Data section index targets and source file filtering pass')
        for width in [1280,768,390,320]:
            page.set_viewport_size({'width':width,'height':900})
            for path,name in [('/index.html','home'),('/states/texas/index.html#counties','texas'),('/counties/texas/harris-county/index.html?year=2024','harris'),('/data/index.html','data')]:
                page.goto(BASE+path,wait_until='domcontentloaded')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), (width,path,'overflow',page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>[e.tagName,e.className,e.getBoundingClientRect().right])'))
                page.screenshot(path=str(ARTIFACTS/f'{name}-{width}.png'),full_page=False)
        results.append('No horizontal page overflow at 320px, 390px, 768px and 1280px; screenshots saved')
        assert not errors, errors
        # Progressive fallback: no JavaScript still exposes every county and radio year panes.
        fallback_context=browser.new_context(java_script_enabled=False,viewport={'width':390,'height':900})
        fallback_context.route('**/*',local_route)
        fallback=fallback_context.new_page()
        fallback.goto(BASE+'/states/texas/index.html',wait_until='domcontentloaded')
        assert fallback.locator('[data-filter-table=counties] tr').count()==255
        fallback.locator('.yr-tabs label[for=yr2024]').click()
        assert fallback.locator('.yp2024').is_visible()
        results.append('No-JavaScript full table and year switch fallback pass')
        browser.close()
    print(json.dumps({'results':results,'console_errors':errors,'artifacts':str(ARTIFACTS)},indent=2))

if __name__=='__main__': run()
