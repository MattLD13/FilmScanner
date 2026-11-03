"""Browser check of the live scan preview against the fake CyberView bridge; no device access.

The fake bridge streams 30 preview rows slowly, like the USB watch does during the
image pass. The viewer must show them while the frame is read, then the saved frame.
"""
from pathlib import Path
import json
import os
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    import requests
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    fake = ROOT / 'tests/scanner/fake_cvbridge.py'
    with tempfile.TemporaryDirectory(prefix='frame-live-ui-') as temporary:
        ini = Path(temporary) / 'CyberViewX.ini'
        ini.write_text('[TOOLBAR FILMTERM]\nFilm Type=0\nFilm Term Name=Kodak 200\n[SETUPDLG DEFAULT PAGE]\nAuto Exposure=1\n',
                       encoding='latin-1')
        env = {'FRAME_DATA_DIR': temporary, 'FRAME_NATIVE_BRIDGE': str(fake), 'FRAME_CYBERVIEW_INI': str(ini),
               # Keep the half-transfer state observable even while Chromium is
               # taking screenshots or other workflow tests are using the CPU.
               'FAKE_CVBRIDGE_LIVE_DELAY': '0.12', 'FAKE_CVBRIDGE_DELAY': '1.5'}
        with patch.dict(os.environ, env):
            from services.api import main as api_main
            api_main.app.state.store.close()
            from services.scanner_host import cyberview
            with patch.object(cyberview, 'vendor_running', return_value=False), \
                 patch.object(cyberview, 'scanner_present', return_value=True), \
                 patch.object(cyberview, 'reset_available', return_value=False):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
                app = api_main.create_app(Path(temporary) / 'library')
                server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
                thread = threading.Thread(target=server.run, daemon=True); thread.start()
                origin = f'http://127.0.0.1:{port}'
                try:
                    for _ in range(100):
                        try:
                            if requests.get(origin + '/api/health', timeout=.2).ok: break
                        except requests.RequestException: pass
                        time.sleep(.05)
                    errors = []
                    with sync_playwright() as p:
                        browser = p.chromium.launch()
                        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(origin + '/?workspace=frame')
                        expect(page.get_by_label('Scanner status')).to_contain_text('PrimeFilm')
                        page.get_by_role('button', name='Scan', exact=True).click()
                        page.get_by_role('button', name='Scan frame', exact=True).click()
                        canvas = page.get_by_role('img', name='Frame 1 as the scanner reads it')
                        expect(canvas).to_be_visible(timeout=15000)
                        expect(page.get_by_text('Live preview', exact=True)).to_be_visible()
                        expect(page.locator('.cx-zoom')).to_have_text('—')
                        mini = page.locator('.cx-progress-frame')
                        expect(mini).to_be_visible()
                        page.wait_for_function("Number(document.querySelector('.cx-progress-frame')?.dataset.progress) > 0")
                        first_progress = float(mini.get_attribute('data-progress'))
                        expect(page.locator('.cx-line-count')).to_contain_text('preview lines')
                        first_lines = int(page.locator('.cx-line-count').inner_text().split()[0])
                        page.wait_for_timeout(900)
                        next_progress = float(mini.get_attribute('data-progress'))
                        assert 0 < first_progress < next_progress < 1, (first_progress, next_progress)
                        next_lines = int(page.locator('.cx-line-count').inner_text().split()[0])
                        assert next_lines > first_lines, (first_lines, next_lines)
                        assert mini.get_attribute('data-phase') == 'scanning'
                        expect(page.locator('.cx-progress-line')).to_be_visible()
                        assert float(page.locator('.cx-progress-line').evaluate('element => parseFloat(element.style.top)')) > 0
                        # Reduced motion stops decoration; actual received-row position
                        # remains visible and continues updating.
                        page.emulate_media(reduced_motion='reduce')
                        assert page.locator('.cx-frame-outline rect').evaluate('element => getComputedStyle(element).animationName') == 'none'
                        assert page.locator('.cx-progress-line').evaluate('element => getComputedStyle(element).transitionDuration') == '0s'
                        # Film base is bright in transmission; the negative preview shows it dark.
                        pixel = canvas.evaluate('c => Array.from(c.getContext("2d").getImageData(1, 1, 1, 1).data)')
                        assert pixel[3] == 255 and sum(pixel[:3]) < 200, pixel
                        evidence = ROOT / '.local/frame-ui'
                        evidence.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(evidence / 'scan-live.png'))
                        expect(page.locator('.cx-line-count')).to_have_text('20 / 40 lines', timeout=10000)
                        expect(page.locator('.cx-progress-text .cx-meta')).to_contain_text('50%')
                        page.screenshot(path=str(evidence / 'scan-line-count.png'))
                        expect(canvas).to_be_hidden(timeout=20000)
                        expect(page.get_by_role('button', name='Frame 1', exact=True)).to_be_visible()
                        assert not errors, errors
                        browser.close()
                    print(json.dumps({'result': 'passed', 'mode': 'fake direct-capture bridge; no device access',
                                      'verified': ['live preview appears while the frame is read',
                                                   'negative preview inverted', 'saved frame replaces the preview',
                                                   'miniature and beam follow received rows', 'reduced motion keeps actual progress',
                                                   'individual preview-line count and exact transfer lines with percentage'],
                                      'screenshot': '.local/frame-ui/scan-live.png',
                                      'javascript_exceptions': errors}))
                finally:
                    server.should_exit = True
                    thread.join(20)
                    assert not thread.is_alive(), 'Fixture service failed to close'


if __name__ == '__main__':
    main()
