"""Browser QA for FRAME's demo mode; starts no API or scanner backend."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PORT = 8771
URL = f'http://127.0.0.1:{PORT}/?workspace=frame&demo=1'


def run():
    evidence = ROOT / '.local' / 'frame-ui'
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='frame-skin-check-') as temporary:
        with (Path(temporary) / 'static.log').open('w') as log:
            process = subprocess.Popen([sys.executable, 'scripts/preview_skin.py', '--port', str(PORT)],
                cwd=ROOT, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(100):
                    try:
                        with urlopen(URL, timeout=1) as response:
                            assert "connect-src 'none'" in response.headers['Content-Security-Policy']
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError('Static preview did not start')
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    context = browser.new_context(viewport={'width': 1600, 'height': 1000})
                    page = context.new_page()
                    requests, sockets, errors = [], [], []
                    page.on('request', lambda request: requests.append(request.url))
                    page.on('websocket', lambda socket: sockets.append(socket.url))
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{PORT}/')
                    assert page.url == URL, 'The static entry must always select the offline demo renderer'
                    assert page.title() == 'FRAME'
                    expect(page.get_by_label('Scanner status')).to_contain_text('Sample mode')
                    expect(page.get_by_role('heading', name=re.compile('Good things'))).to_be_visible()
                    expect(page.get_by_text('SAMPLE MODE', exact=True)).to_be_visible()
                    photo = page.get_by_role('img', name=re.compile('Sample photograph'))
                    expect(photo).to_be_visible()
                    first_photo = photo.get_attribute('src')
                    page.get_by_role('button', name=re.compile('Shuffle')).click()
                    assert photo.get_attribute('src') != first_photo
                    expect(page.get_by_role('button', name='Develop', exact=True)).to_be_disabled()
                    # Material changes affect the shell, never recolour saved photographs.
                    photo_url = photo.get_attribute('src')
                    for value, label in [('bw_negative', 'Black & white'), ('positive', 'Slide'), ('color_negative', 'Color negative')]:
                        page.get_by_role('radio', name=label, exact=True).check()
                        expect(page.locator('.cx-app')).to_have_attribute('data-film-type', value)
                        expect(page.get_by_role('radio', name=label, exact=True)).to_be_checked()
                        assert photo.get_attribute('src') == photo_url
                        page.wait_for_timeout(320)
                        page.screenshot(path=str(evidence / f'home-{value}.png'))
                    page.screenshot(path=str(evidence / 'home-desktop.png'))
                    opening = page.locator('.cx-feature-open')
                    assert opening.evaluate('element => Math.abs(element.clientWidth / element.clientHeight - 1.5) < .01')
                    assert photo.evaluate('element => getComputedStyle(element).objectFit') == 'contain'
                    page.set_viewport_size({'width': 2560, 'height': 1440})
                    page.wait_for_timeout(350)
                    home_bounds = page.locator('.cx-home-intro').bounding_box()
                    cards_bounds = page.locator('.cx-home-cards').bounding_box()
                    assert home_bounds['x'] + home_bounds['width'] > 2480, home_bounds
                    assert cards_bounds['x'] + cards_bounds['width'] > 2480, cards_bounds
                    assert opening.bounding_box()['width'] > 1000, opening.bounding_box()
                    page.screenshot(path=str(evidence / 'home-wide.png'))
                    page.get_by_role('button', name='View featured photo fullscreen', exact=True).click()
                    cinema = page.get_by_role('dialog', name='Fullscreen photograph', exact=True)
                    expect(cinema).to_be_visible()
                    if page.evaluate('document.fullscreenEnabled'):
                        page.wait_for_function("() => document.fullscreenElement === document.querySelector('.cx-app')")
                    expect(cinema.get_by_role('img')).to_be_visible()
                    page.wait_for_function("(() => { const i = document.querySelector('.cx-cinema-frame img'); return i?.complete && i.naturalWidth > 0 && Math.abs(i.clientWidth / i.clientHeight - i.naturalWidth / i.naturalHeight) < .01; })()")
                    assert cinema.evaluate('element => { const r = element.getBoundingClientRect(); return r.x === 0 && r.y === 0 && Math.abs(r.width - innerWidth) < 2 && Math.abs(r.height - innerHeight) < 2; }')
                    assert cinema.get_by_role('img').evaluate('element => getComputedStyle(element).objectFit') == 'contain'
                    expect(page.get_by_role('button', name='Close fullscreen photograph', exact=True)).to_be_focused()
                    page.keyboard.press('Shift+Tab')
                    expect(page.get_by_role('button', name='Open in scanner', exact=True)).to_be_focused()
                    page.keyboard.press('Tab')
                    expect(page.get_by_role('button', name='Close fullscreen photograph', exact=True)).to_be_focused()
                    page.screenshot(path=str(evidence / 'photo-fullscreen.png'))
                    page.keyboard.press('Escape')
                    expect(cinema).to_be_hidden()
                    page.wait_for_function('() => document.fullscreenElement === null')
                    # Browsers without native fullscreen still get the viewport viewer.
                    page.evaluate("Object.defineProperty(document, 'fullscreenEnabled', {value:false, configurable:true})")
                    page.get_by_role('button', name='View featured photo fullscreen', exact=True).click()
                    expect(cinema).to_be_visible()
                    assert page.evaluate('document.fullscreenElement === null')
                    page.get_by_role('button', name='Close fullscreen photograph', exact=True).click()
                    expect(cinema).to_be_hidden()
                    page.evaluate('delete document.fullscreenEnabled')
                    page.set_viewport_size({'width': 1600, 'height': 1000})
                    page.get_by_role('button', name='Scan', exact=True).click()
                    expect(page.get_by_role('button', name='Scan frame', exact=True)).to_be_disabled()
                    expect(page.get_by_role('button', name='Scan all frames', exact=True)).to_be_disabled()
                    expect(page.get_by_role('heading', name='Street', exact=True)).to_be_visible()
                    for name in ('Original TIFF', 'Adjusted TIFF', 'Adjusted JPEG'):
                        expect(page.locator('.cx-export.disabled', has_text=name)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                    page.wait_for_function('document.querySelector(".cx-image img")?.complete')
                    geometry = page.locator('.cx-image').evaluate('''element => {
                        const image = element.querySelector('img');
                        const viewer = element.closest('.cx-viewer');
                        const dock = viewer.querySelector('[role="toolbar"]');
                        return { imageRatio: image.clientWidth / image.clientHeight,
                            sourceRatio: image.naturalWidth / image.naturalHeight,
                            imageWidth: image.clientWidth, baseWidth: element.clientWidth,
                            dockPosition: getComputedStyle(dock).position,
                            viewerDecoration: getComputedStyle(viewer, '::before').content };
                    }''')
                    assert abs(geometry['imageRatio'] - geometry['sourceRatio']) < .01, geometry
                    assert abs(geometry['imageWidth'] - geometry['baseWidth']) < 2, geometry
                    assert geometry['dockPosition'] == 'absolute', geometry
                    assert geometry['viewerDecoration'] == 'none', geometry
                    page.screenshot(path=str(evidence / 'scan-desktop.png'))

                    page.get_by_role('button', name='Frame 2', exact=True).click()
                    expect(page.get_by_role('heading', name='Coast', exact=True)).to_be_visible()
                    for value, label in [('bw_negative', 'Black & white'), ('positive', 'Slide'), ('color_negative', 'Color negative')]:
                        page.get_by_role('radio', name=label, exact=True).check()
                        expect(page.locator('.cx-app')).to_have_attribute('data-film-type', value)
                        page.wait_for_timeout(320)
                        page.screenshot(path=str(evidence / f'scan-{value}.png'))
                    expect(page.locator('.cx-viewer-edge')).to_have_text('Frame 2')
                    page.get_by_role('button', name='Actual size (100%)', exact=True).click()
                    expect(page.locator('.cx-zoom')).to_have_text('100%')
                    assert page.locator('.cx-image img').evaluate('element => Math.abs(element.clientWidth - element.naturalWidth) < 2')
                    page.get_by_role('button', name='Zoom in', exact=True).click()
                    expect(page.locator('.cx-zoom')).to_have_text('125%')
                    page.get_by_role('button', name='Fit to window', exact=True).click()
                    expect(page.get_by_role('button', name='Fit to window', exact=True)).to_have_attribute('aria-pressed', 'true')
                    fit = page.locator('.cx-image').evaluate('''element => {
                        const viewer = element.closest('.cx-viewer'), style = getComputedStyle(viewer);
                        return {width: element.clientWidth, height: element.clientHeight,
                          availableWidth: viewer.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
                          availableHeight: viewer.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
                          actualPercent: Math.round(element.clientWidth / element.querySelector('img').naturalWidth * 100)};
                    }''')
                    assert fit['width'] + 16 <= fit['availableWidth'] + 2, fit
                    assert fit['height'] + 44 <= fit['availableHeight'] + 2, fit
                    assert min(abs(fit['width'] + 16 - fit['availableWidth']), abs(fit['height'] + 44 - fit['availableHeight'])) < 3, fit
                    expect(page.locator('.cx-zoom')).to_have_text(f"{fit['actualPercent']}%")
                    zoom_button = page.get_by_role('button', name='Zoom in', exact=True)
                    zoom_button.hover()
                    expect(page.get_by_role('tooltip').filter(has_text='Inspect the image more closely.')).to_be_visible()
                    zoom_button.focus()
                    expect(page.get_by_role('tooltip').filter(has_text='Inspect the image more closely.')).to_be_visible()
                    expect(page.get_by_role('button', name='Previous frame', exact=True)).to_be_disabled()
                    expect(page.get_by_role('button', name='Next frame', exact=True)).to_be_disabled()
                    page.get_by_role('button', name='Show original', exact=True).click()
                    expect(page.get_by_role('button', name='Show adjustments', exact=True)).to_have_attribute('aria-pressed', 'true')
                    assert page.locator('.cx-image img').evaluate('element => element.style.filter') == 'none'
                    page.get_by_role('button', name='Show adjustments', exact=True).click()
                    page.get_by_role('button', name='Rotate 90 degrees', exact=True).click()
                    expect(page.locator('.cx-image')).to_have_attribute('style', re.compile(r'rotate\(90deg\)'))
                    page.wait_for_timeout(250)
                    rotated = page.locator('.cx-image').evaluate('''element => {
                        const viewer = element.closest('.cx-viewer'), style = getComputedStyle(viewer), rect = element.getBoundingClientRect();
                        return {width: rect.width, height: rect.height,
                          availableWidth: viewer.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
                          availableHeight: viewer.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)};
                    }''')
                    assert rotated['width'] + 44 <= rotated['availableWidth'] + 2, rotated
                    assert rotated['height'] + 16 <= rotated['availableHeight'] + 2, rotated
                    # Fit remains active as available space changes.
                    page.set_viewport_size({'width': 1280, 'height': 820})
                    page.wait_for_timeout(250)
                    resized = page.locator('.cx-image').evaluate('''element => {
                        const viewer = element.closest('.cx-viewer'), style = getComputedStyle(viewer), rect = element.getBoundingClientRect();
                        return {width: rect.width, height: rect.height,
                          availableWidth: viewer.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
                          availableHeight: viewer.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)};
                    }''')
                    assert resized['width'] + 44 <= resized['availableWidth'] + 2, resized
                    assert resized['height'] + 16 <= resized['availableHeight'] + 2, resized
                    page.set_viewport_size({'width': 1600, 'height': 1000})
                    mirror = page.get_by_role('button', name='Mirror', exact=True)
                    mirror.click()
                    expect(mirror).to_have_attribute('aria-pressed', 'true')
                    exposure = page.get_by_role('slider', name='Exposure', exact=True)
                    for _ in range(4):
                        exposure.press('ArrowRight')
                    expect(exposure).to_have_value('0.2')
                    matrix = page.locator('#cx-adjust feColorMatrix').get_attribute('values')
                    assert matrix.startswith('1.1487 0.0000 0.0000 0 0.0000'), matrix  # 2^0.2 on the red row
                    page.get_by_role('button', name='Reset', exact=True).click()
                    expect(exposure).to_have_value('0')
                    expect(mirror).to_have_attribute('aria-pressed', 'true')  # reset keeps the transform
                    page.get_by_role('button', name='Add to favorites', exact=True).click()
                    expect(page.get_by_role('button', name='Remove from favorites', exact=True)).to_be_visible()

                    page.get_by_role('button', name='Rolls', exact=True).click()
                    expect(page.locator('.cx-grid button')).to_have_count(3)
                    page.get_by_role('button', name='Open Forest', exact=True).click()
                    expect(page.get_by_role('heading', name='Forest', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Settings', exact=True).click()
                    expect(page.locator('.cx-settings')).to_contain_text('1800 dpi, 16-bit RGB TIFF')
                    page.get_by_role('button', name='Scan', exact=True).click()

                    mobile_context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                    mobile = mobile_context.new_page()
                    mobile.on('request', lambda request: requests.append(request.url))
                    mobile.on('websocket', lambda socket: sockets.append(socket.url))
                    mobile.on('pageerror', lambda error: errors.append(str(error)))
                    mobile.goto(URL)
                    expect(mobile.get_by_role('heading', name=re.compile('Good things'))).to_be_visible()
                    mobile.screenshot(path=str(evidence / 'home-phone.png'), full_page=True)
                    mobile.get_by_role('button', name='Scan', exact=True).click()
                    expect(mobile.get_by_role('heading', name='Street', exact=True)).to_be_visible()
                    assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'Mobile layout overflows'
                    expect(mobile.get_by_role('button', name='Scan frame', exact=True)).to_be_disabled()
                    expect(mobile.get_by_role('button', name='Scan all frames', exact=True)).to_be_disabled()
                    mobile.screenshot(path=str(evidence / 'scan-phone.png'), full_page=True)
                    for value, label in [('bw_negative', 'Black & white'), ('positive', 'Slide')]:
                        mobile.get_by_role('radio', name=label, exact=True).check()
                        expect(mobile.locator('.cx-app')).to_have_attribute('data-film-type', value)
                        assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                        mobile.wait_for_timeout(320)
                        mobile.screenshot(path=str(evidence / f'scan-phone-{value}.png'), full_page=True)
                    mobile.reload()
                    expect(mobile.get_by_role('radio', name='Slide', exact=True)).to_be_checked()
                    mobile.get_by_role('radio', name='Color negative', exact=True).check()
                    page.emulate_media(reduced_motion='reduce')
                    assert page.locator('.cx-feature').count() == 0  # still on Scan
                    page.get_by_role('button', name='Home', exact=True).click()
                    assert page.locator('.cx-feature').evaluate('(element) => getComputedStyle(element).animationName') == 'none'

                    # Older links still reach the renamed workspace.
                    mobile.goto(f'http://127.0.0.1:{PORT}/?workspace=cyberscan&demo=1')
                    assert mobile.title() == 'FRAME'
                    expect(mobile.get_by_role('heading', name=re.compile('Good things'))).to_be_visible()

                    forbidden = [url for url in requests if urlsplit(url).path.startswith(('/api', '/media'))]
                    external = [url for url in requests if urlsplit(url).netloc not in ('', f'127.0.0.1:{PORT}') and not url.startswith(('blob:', 'data:'))]
                    assert not forbidden, forbidden
                    assert not external, external
                    assert not sockets, sockets
                    assert not errors, errors
                    report = {'result': 'passed', 'mode': 'static demo mode only', 'api_requests': forbidden,
                              'websocket_connections': sockets, 'external_requests': external, 'javascript_exceptions': errors,
                              'hardware_controls': 'disabled on desktop and phone',
                              'verified': ['FRAME Home with labeled sample photographs and shuffle', 'legacy workspace alias',
                                           'frame selection with edge numbers', 'zoom/fit', 'rotate/mirror',
                                           'exposure slider drives the colour matrix', 'reset keeps transform', 'favorite',
                                           'rolls and settings', 'exports disabled for samples', '390px responsive layout',
                                           'three film materials on desktop and phone', 'theme persistence',
                                           'saved photographs unchanged by film selector', 'reduced motion'],
                              'scanner_service_started': False, 'device_access_attempted': False}
                    (evidence / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
                    print(json.dumps(report))
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    run()
