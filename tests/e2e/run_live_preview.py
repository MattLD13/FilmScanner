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
        env = {'FRAME_DATA_DIR': temporary, 'FRAME_CVBRIDGE': str(fake), 'FRAME_CYBERVIEW_INI': str(ini),
               'FAKE_CVBRIDGE_LIVE_DELAY': '0.12'}
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
                        page.goto(origin + '/?workspace=cyberscan')
                        expect(page.get_by_label('Scanner status')).to_contain_text('PrimeFilm')
                        page.get_by_role('button', name='Scan frame', exact=True).click()
                        canvas = page.get_by_role('img', name='Frame 1 as the scanner reads it')
                        expect(canvas).to_be_visible(timeout=15000)
                        expect(page.get_by_text('Live from the scanner · uncorrected')).to_be_visible()
                        page.wait_for_timeout(1500)
                        # Film base is bright in transmission; the negative preview shows it dark.
                        pixel = canvas.evaluate('c => Array.from(c.getContext("2d").getImageData(1, 1, 1, 1).data)')
                        assert pixel[3] == 255 and sum(pixel[:3]) < 200, pixel
                        page.screenshot(path=str(ROOT / 'docs/screenshots/cyberscan-live.png'))
                        expect(canvas).to_be_hidden(timeout=20000)
                        expect(page.get_by_role('button', name='Frame 1,', exact=False)).to_be_visible()
                        assert not errors, errors
                        browser.close()
                    print(json.dumps({'result': 'passed', 'mode': 'fake CyberView bridge; no device access',
                                      'verified': ['live preview appears while the frame is read',
                                                   'negative preview inverted', 'saved frame replaces the preview'],
                                      'screenshot': 'docs/screenshots/cyberscan-live.png',
                                      'javascript_exceptions': errors}))
                finally:
                    server.should_exit = True
                    thread.join(20)
                    assert not thread.is_alive(), 'Fixture service failed to close'


if __name__ == '__main__':
    main()
