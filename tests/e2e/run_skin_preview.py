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
                    page.screenshot(path=str(evidence / 'home-desktop.png'))
                    page.get_by_role('button', name='Scan', exact=True).click()
                    expect(page.get_by_role('button', name='Scan frame', exact=True)).to_be_disabled()
                    expect(page.get_by_role('heading', name='Street', exact=True)).to_be_visible()
                    for name in ('Original TIFF', 'Adjusted TIFF', 'Adjusted JPEG'):
                        expect(page.locator('.cx-export.disabled', has_text=name)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                    page.screenshot(path=str(evidence / 'scan-desktop.png'))

                    page.get_by_role('button', name='Frame 2', exact=True).click()
                    expect(page.get_by_role('heading', name='Coast', exact=True)).to_be_visible()
                    expect(page.locator('.cx-viewer-edge')).to_have_text('Frame 2')
                    page.get_by_role('button', name='Zoom in', exact=True).click()
                    expect(page.locator('.cx-zoom')).to_have_text('125%')
                    page.get_by_role('button', name='Fit to window', exact=True).click()
                    expect(page.locator('.cx-zoom')).to_have_text('100%')
                    page.get_by_role('button', name='Rotate 90 degrees', exact=True).click()
                    expect(page.locator('.cx-image')).to_have_attribute('style', re.compile(r'rotate\(90deg\)'))
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
                    mobile.screenshot(path=str(evidence / 'scan-phone.png'), full_page=True)

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
                                           'rolls and settings', 'exports disabled for samples', '390px responsive layout'],
                              'scanner_service_started': False, 'device_access_attempted': False}
                    (evidence / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
                    print(json.dumps(report))
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    run()
