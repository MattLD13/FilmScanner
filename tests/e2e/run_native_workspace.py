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
        env = {'FRAME_DATA_DIR': temporary, 'FRAME_CVBRIDGE': str(fake), 'FRAME_NATIVE_BRIDGE': str(fake),
               'FAKE_CVBRIDGE_MODE': 'strip', 'FRAME_FILMTERM_DIRS': str(Path(temporary) / 'absent')}
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
                # A private synthetic reference curve, independent of installed vendor data.
                from services.imaging import filmterms, reference_tone, vendor_negative
                reference_profile = reference_tone.identify({
                    'kind': 'reference-tone', 'input_response': .5,
                    'name': 'Synthetic reference appearance', 'maker': 'Workflow fixture',
                    'film_class': 'negative', 'rows': 4096, 'scale': 4095,
                    'lut': [[4095 * (i / 4095) ** power for power in (1.2, 1.4, 1.3)] for i in range(4096)],
                    'matrix': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
                    'source_file': 'synthetic', 'source_folder': 'Reference profiles'})
                profile_id = reference_profile['id']
                filmterms.remember(app.state.store, reference_profile)
                film_data = ('FilmClass NEG;\nFilmName Synthetic AFL stock;\nFilmMfgr Fixture;\nFilmLut\n' +
                             '\n'.join(f'{i} {i} {i}' for i in range(256)) + ';\n' +
                             'FilmMatR 1 0 0 0;\nFilmMatG 0 1 0 0;\nFilmMatB 0 0 1 0;').encode()
                gamma_data = ('FilmLut\n' + '\n'.join(f'{i} {i} {i}' for i in range(4096)) + ';').encode()
                vendor_profile = vendor_negative.create(film_data, gamma_data, 'fixture.ft', 'Fixture')
                filmterms.remember(app.state.store, vendor_profile)
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
                        assert page.title() == 'FRAME'
                        expect(page.get_by_role('heading', name='Good things take their time.')).to_be_visible()
                        expect(page.get_by_label('Scanner status')).to_contain_text('PrimeFilm')
                        # Direct capture is the default; CyberView capture is no longer offered.
                        page.get_by_role('button', name='Settings', exact=True).click()
                        expect(page.get_by_text('CyberView X is not used', exact=False)).to_be_visible()
                        assert page.get_by_role('button', name='Use CyberView capture').count() == 0
                        page.get_by_role('button', name='Scan', exact=True).click()
                        expect(page.get_by_role('button', name='Next frame', exact=True)).to_be_disabled()
                        assert page.get_by_label('Frames to scan').locator('option').all_inner_texts() == ['Current frame', 'All frames']
                        page.get_by_role('button', name='Scan frame', exact=True).click()
                        expect(page.get_by_label('Invert negative', exact=True)).to_be_checked(timeout=15000)
                        page.get_by_text('Film & colour', exact=True).click()
                        response_control = page.get_by_role('slider', name='Negative response', exact=True)
                        expect(response_control).to_have_value('0.5')
                        strip_image = page.locator('.cx-strip button img').first
                        old_thumbnail = strip_image.get_attribute('src')
                        response_control.fill('0.8')
                        page.wait_for_timeout(600)
                        assert page.locator('feFuncR').first.get_attribute('exponent') == '0.8'
                        assert strip_image.get_attribute('src') != old_thumbnail, 'Thumbnail must refresh after the edit saves'
                        assert '/rendered/thumb' in strip_image.get_attribute('src')
                        page.get_by_role('button', name='Balance negative', exact=True).click()
                        expect(response_control).to_have_value('0.5')
                        page.get_by_role('button', name='Reset', exact=True).click()
                        expect(response_control).to_have_value('0.5')
                        auto = page.get_by_label('Auto colour', exact=True)
                        expect(auto).to_be_visible()
                        before = auto.is_checked()
                        auto.click()   # the box follows the server's answer, not the click
                        page.wait_for_timeout(1500)
                        error = page.get_by_role('alert').filter(has_text='near-neutral')
                        assert auto.is_checked() != before or error.count(), 'auto colour did not toggle or explain why'
                        toggled = page.request.get(origin + '/api/cyberview/captures').json()['captures'][0]['adjustments']['auto_color']
                        assert (toggled is not None) == auto.is_checked(), toggled
                        page.get_by_label('Film rendering profile', exact=True).select_option(profile_id)
                        page.wait_for_timeout(1000)
                        assert page.locator('img[src*="profile-preview"]').count() >= 1
                        expect(auto).not_to_be_checked()
                        response = page.request.get(origin + '/api/cyberview/captures').json()
                        capture = response['captures'][0]
                        assert capture['backend'] == 'afl-native-experimental'
                        assert capture['image_kind'] == 'vendor-calibrated-transmission'
                        assert capture['effective_bits'] is None
                        original = page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/original').body()
                        assert hashlib.sha256(original).hexdigest() == capture['sha256']
                        output = page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/tiff').body()
                        assert tifffile.imread(BytesIO(output)).dtype.name == 'uint16'
                        with tifffile.TiffFile(BytesIO(output)) as tif:
                            metadata = json.loads(tif.pages[0].description)
                            assert metadata['adjustments']['negative_response'] == .5
                            assert metadata['adjustments']['film_profile'] == profile_id
                        screenshot = ROOT / '.local/color-review/balanced-workspace.png'
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                        page.get_by_label('Red base', exact=True).fill('0.6')
                        page.wait_for_timeout(500)
                        saved = page.request.get(origin + '/api/cyberview/captures').json()['captures'][0]
                        assert saved['adjustments']['film_base'] == [.6, *capture['adjustments']['film_base'][1:]]
                        assert page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/original').body() == original
                        page.get_by_label('Film rendering profile', exact=True).select_option(vendor_profile['id'])
                        expect(page.get_by_label('Invert negative', exact=True)).to_be_disabled()
                        expect(response_control).not_to_be_visible()
                        page.wait_for_timeout(600)
                        converted = page.request.get(origin + f'/api/cyberview/captures/{capture["id"]}/export/tiff').body()
                        with tifffile.TiffFile(BytesIO(converted)) as tif:
                            assert json.loads(tif.pages[0].description)['film_profile_engine'] == vendor_negative.VERSION
                        page.wait_for_function("() => { const img = document.querySelector('.cx-image img'); return img && img.complete && img.naturalWidth > 0; }", timeout=15000)
                        page.get_by_role('button', name='Home', exact=True).click()
                        saved_photo = page.get_by_role('img', name='Saved photograph', exact=False)
                        expect(saved_photo).to_be_visible()
                        assert '/rendered/preview' in saved_photo.get_attribute('src')
                        page.wait_for_function("() => { const img = document.querySelector('.cx-feature-image img'); return img && img.complete && img.naturalWidth > 0; }", timeout=15000)
                        page.get_by_role('button', name='Develop', exact=True).click()
                        expect(page.get_by_role('heading', name='Time to develop.')).to_be_visible()
                        expect(page.get_by_text('Developing records and scanned rolls are currently separate.')).to_be_visible()
                        page.get_by_role('button', name='Scan', exact=True).click()
                        expect(page.get_by_role('button', name='Scan frame', exact=True)).to_be_visible()
                        assert not errors, errors
                        browser.close()
                    print(json.dumps({'result': 'passed', 'mode': 'synthetic pipe helper; no device access',
                                      'verified': ['FRAME Home with saved edited photo', 'Develop and return to scanner',
                                                   'direct capture by default', 'auto colour toggle', 'current-frame-only controls',
                                                   'native capture provenance', 'negative inversion', 'manual film base',
                                                   'negative balance and response preview', 'private reference profile preview/export',
                                                   '16-bit export', 'immutable original'],
                                      'javascript_exceptions': errors}))
                finally:
                    server.should_exit = True
                    thread.join(20)
                    assert not thread.is_alive(), 'Fixture service failed to close'


if __name__ == '__main__':
    main()
