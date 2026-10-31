"""Actual browser/native-workspace workflow against a synthetic pipe helper.

No vendor module is loaded; hardware discovery and installed evidence are mocked.
"""
from pathlib import Path
import hashlib
from io import BytesIO
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
    import tifffile
    import uvicorn
    from playwright.sync_api import sync_playwright, expect

    fake = ROOT / 'tests/scanner/fake_cvbridge.py'
    with tempfile.TemporaryDirectory(prefix='frame-native-ui-') as temporary:
        env = {'FRAME_DATA_DIR': temporary, 'FRAME_CVBRIDGE': str(fake), 'FRAME_NATIVE_BRIDGE': str(fake)}
        with patch.dict(os.environ, env):
            from services.api import main as api_main
            # Importing main also creates an unused default app in this fixture
            # library; close that connection before Windows temporary cleanup.
            api_main.app.state.store.close()
            create_app = api_main.create_app
            from services.scanner_host import cyberview, vendor_evidence, workspace
            evidence = {'inspection': 'files_only', 'device_io_performed': False, 'files': [],
                        'native_bridge_built': True, 'native_module_recognized': True,
                        'native_device_validation': 'current_frame_verified',
                        'native_note': 'Synthetic workflow fixture. No device access.', 'features': []}
            with patch.object(cyberview, 'vendor_running', return_value=False), \
                 patch.object(cyberview, 'scanner_present', return_value=True), \
                 patch.object(cyberview, 'reset_available', return_value=False), \
                 patch.object(workspace, 'validation', return_value={}), \
                 patch.object(vendor_evidence, 'inspect_installation', return_value=evidence):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
                app = create_app(Path(temporary))
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
                        # Direct capture is the default; CyberView capture is no longer offered.
                        page.get_by_role('button', name='Settings', exact=True).click()
                        expect(page.get_by_text('CyberView X is not used', exact=False)).to_be_visible()
                        assert page.get_by_role('button', name='Use CyberView capture').count() == 0
                        page.get_by_role('button', name='Scan', exact=True).click()
                        expect(page.get_by_role('button', name='Next frame', exact=True)).to_be_disabled()
                        assert page.get_by_label('Frames to scan').locator('option').count() == 1
                        page.get_by_role('button', name='Scan frame', exact=True).click()
                        expect(page.get_by_label('Invert negative', exact=True)).to_be_checked(timeout=15000)
                        auto = page.get_by_label('Auto colour', exact=True)
                        expect(auto).to_be_visible()
                        before = auto.is_checked()
                        auto.click()   # the box follows the server's answer, not the click
                        page.wait_for_timeout(1500)
                        error = page.get_by_role('alert').filter(has_text='near-neutral')
                        assert auto.is_checked() != before or error.count(), 'auto colour did not toggle or explain why'
                        toggled = page.request.get(origin + '/api/cyberview/captures').json()['captures'][0]['adjustments']['auto_color']
                        assert (toggled is not None) == auto.is_checked(), toggled
                        response = page.request.get(origin + '/api/cyberview/captures').json()
                        capture = response['captures'][0]
                        assert capture['backend'] == 'afl-native-experimental'
                        assert capture['image_kind'] == 'vendor-calibrated-transmission'
                        assert capture['effective_bits'] is None
                        original = page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/original').body()
                        assert hashlib.sha256(original).hexdigest() == capture['sha256']
                        output = page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/tiff').body()
                        assert tifffile.imread(BytesIO(output))[0, 0, 0] == 65535
                        page.get_by_label('Red base', exact=True).fill('0.6')
                        page.wait_for_timeout(500)
                        saved = page.request.get(origin + '/api/cyberview/captures').json()['captures'][0]
                        assert saved['adjustments']['film_base'] == [.6, 1, 1]
                        assert page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/original').body() == original
                        assert not errors, errors
                        browser.close()
                    print(json.dumps({'result': 'passed', 'mode': 'synthetic pipe helper; no device access',
                                      'verified': ['direct capture by default', 'auto colour toggle', 'current-frame-only controls',
                                                   'native capture provenance', 'negative inversion', 'manual film base',
                                                   '16-bit export', 'immutable original'],
                                      'javascript_exceptions': errors}))
                finally:
                    server.should_exit = True
                    thread.join(20)
                    assert not thread.is_alive(), 'Fixture service failed to close'


if __name__ == '__main__':
    main()
