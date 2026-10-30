"""Browser QA for static CyberScan skin; starts no API or scanner backend."""
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

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PORT = 8771
URL = f'http://127.0.0.1:{PORT}/?workspace=cyberscan'


def run():
    evidence = ROOT / 'docs' / 'screenshots'
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
                    assert page.url == URL, 'The static entry must always select the safe renderer'
                    expect(page.get_by_role('heading', name='Scan studio.')).to_be_visible()
                    expect(page.get_by_role('button', name='Export preview', exact=True)).to_be_enabled()
                    expect(page.locator('.cs-safety')).to_contain_text('scanner access disabled')
                    for name in ('Connect scanner', 'Prescan', 'Scan frame'):
                        expect(page.get_by_role('button', name=name, exact=True)).to_be_disabled()
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                    page.screenshot(path=str(evidence / 'cyberscan-desktop.png'), full_page=True)

                    page.get_by_role('button', name='Select Coast, demo image', exact=True).click()
                    expect(page.get_by_role('heading', name=re.compile('^Coast'))).to_be_visible()
                    expect(page.get_by_role('button', name='Export preview', exact=True)).to_be_enabled()
                    page.get_by_role('button', name='Zoom in', exact=True).click()
                    expect(page.locator('.cs-zoom')).to_have_text('110%')
                    page.get_by_role('button', name='Fit image', exact=True).click()
                    expect(page.locator('.cs-zoom')).to_have_text('100%')
                    page.get_by_role('button', name='Rotate clockwise', exact=True).click()
                    page.get_by_role('button', name='Mirror image', exact=True).click()
                    page.get_by_role('button', name='Toggle framing guides', exact=True).click()
                    expect(page.get_by_label('Framing guides', exact=True)).to_be_visible()
                    exposure = page.get_by_role('slider', name=re.compile('^Exposure'))
                    page.get_by_role('button', name='Warm', exact=True).click()
                    expect(exposure).to_have_value('0.1')
                    expect(page.locator('.cs-image-box img')).to_have_attribute('style', re.compile(r'sepia\(0.12\)'))
                    page.get_by_role('button', name='Reset all adjustments', exact=True).click()
                    expect(page.get_by_role('button', name='Mirror image', exact=True)).to_have_attribute('aria-pressed', 'false')
                    page.get_by_role('button', name='Rotate clockwise', exact=True).click()
                    page.get_by_role('button', name='Mirror image', exact=True).click()
                    for _ in range(3):
                        exposure.press('ArrowRight')
                    expect(exposure).to_have_value('0.3')
                    with page.expect_download() as recipe_download:
                        page.get_by_role('button', name='Save preview recipe', exact=True).click()
                    recipe = json.loads(Path(recipe_download.value.path()).read_text())
                    assert recipe['rotation'] == 90 and recipe['mirror'] is True and recipe['exposure'] == .3
                    with page.expect_download() as preview_download:
                        page.get_by_role('button', name='Export preview', exact=True).click()
                    with Image.open(preview_download.value.path()) as exported, Image.open(ROOT / 'apps/web/public/demo/coast.jpg') as source:
                        assert exported.format == 'JPEG'
                        assert exported.size == (source.height, source.width)
                    page.get_by_role('button', name='Dismiss message', exact=True).click()
                    page.get_by_role('button', name='Reset all adjustments', exact=True).click()
                    expect(exposure).to_have_value('0')
                    page.locator('input[type=file]').set_input_files(str(ROOT / 'apps/web/public/demo/coast.jpg'))
                    expect(page.get_by_role('heading', name=re.compile('^coast.jpg'))).to_be_visible()
                    expect(page.locator('.cs-stage-top')).to_contain_text('LOCAL PREVIEW')
                    page.get_by_role('button', name='Preview library', exact=True).click()
                    expect(page.locator('.cs-library-grid button')).to_have_count(4)
                    page.get_by_role('button', name='Preferences', exact=True).click()
                    expect(page.locator('.cs-pref-card')).to_contain_text('DISABLED')
                    page.reload()
                    expect(page.locator('.cs-filmstrip button')).to_have_count(4)  # 3 samples and Import
                    expect(page.get_by_role('button', name='Export preview', exact=True)).to_be_enabled()

                    mobile_context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                    mobile = mobile_context.new_page()
                    mobile.on('request', lambda request: requests.append(request.url))
                    mobile.on('websocket', lambda socket: sockets.append(socket.url))
                    mobile.on('pageerror', lambda error: errors.append(str(error)))
                    mobile.goto(URL)
                    expect(mobile.get_by_role('button', name='Export preview', exact=True)).to_be_enabled()
                    assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'Mobile layout overflows'
                    for name in ('Connect scanner', 'Prescan', 'Scan frame'):
                        expect(mobile.get_by_role('button', name=name, exact=True)).to_be_disabled()
                    mobile.screenshot(path=str(evidence / 'cyberscan-phone.png'), full_page=True)

                    forbidden = [url for url in requests if urlsplit(url).path.startswith(('/api', '/media'))]
                    external = [url for url in requests if urlsplit(url).netloc not in ('', f'127.0.0.1:{PORT}') and not url.startswith(('blob:', 'data:'))]
                    assert not forbidden, forbidden
                    assert not external, external
                    assert not sockets, sockets
                    assert not errors, errors
                    report = {'result': 'passed', 'mode': 'static UI only', 'api_requests': forbidden,
                              'websocket_connections': sockets, 'external_requests': external, 'javascript_exceptions': errors,
                              'hardware_controls': 'disabled on desktop and phone',
                              'verified': ['local demo images', 'frame selection', 'zoom/fit', 'rotate/mirror', 'guides',
                                           'exposure', 'recipe download', 'rotated JPEG export', 'local memory import',
                                           'library/preferences', 'reload clears imports', '390px responsive layout'],
                              'scanner_service_started': False, 'device_access_attempted': False}
                    (ROOT / 'docs/cyberscan-validation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
                    print(json.dumps(report))
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    run()
