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
               'FAKE_CVBRIDGE_MODE': 'strip', 'FAKE_CVBRIDGE_RESPECT_SETTINGS': '1',
               'FRAME_FILMTERM_DIRS': str(Path(temporary) / 'absent')}
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
                        assert page.get_by_label('Frames to scan').count() == 0
                        expect(page.get_by_role('button', name='Scan all frames', exact=True)).to_be_disabled()
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
                        toggled = page.request.get(origin + '/api/cyberview/captures').json()['captures'][0]['adjustments']
                        assert bool(toggled['auto_color'] or toggled.get('vendor_auto_gamma_tables')) == auto.is_checked(), toggled
                        page.get_by_label('Film rendering profile', exact=True).select_option(profile_id)
                        page.wait_for_timeout(1000)
                        assert page.locator('img[src*="processing-preview"]').count() >= 1
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
                        # The helper now marks its images synthetic. Home must not
                        # present them as real photographs from the user's library.
                        assert capture['hardware'] is False
                        expect(page.get_by_text('Your photographs', exact=False)).to_be_visible()
                        assert page.get_by_role('img', name='Saved photograph', exact=False).count() == 0
                        page.get_by_role('button', name='Develop', exact=True).click()
                        expect(page.get_by_role('heading', name='Time to develop.')).to_be_visible()
                        expect(page.get_by_text('Developing records and scanned rolls are currently separate.')).to_be_visible()
                        page.get_by_role('button', name='Scan', exact=True).click()
                        expect(page.get_by_role('button', name='Scan frame', exact=True)).to_be_visible()
                        # Exercise wider stitched geometry using only the synthetic helper.
                        with patch.object(workspace, 'validation', return_value=json.loads(workspace.VALIDATION.read_text()) | {'actions': ['next', 'previous', 'nudge']}):
                            response = page.request.post(origin + '/api/cyberview/stitched-scan', data={'acknowledged': True})
                            assert response.ok, response.text()
                            deadline = time.monotonic() + 60
                            while time.monotonic() < deadline:
                                result = page.request.get(origin + '/api/cyberview/status').json()['session']
                                if result['state'] in ('complete', 'error', 'cancelled'):
                                    break
                                time.sleep(.1)
                            assert result['state'] == 'complete', result
                            page.reload()
                            page.get_by_role('button', name='Scan', exact=True).click()
                            page.get_by_role('button', name='Frame 2 · stitched', exact=True).click()
                            expect(page.locator('.cx-cropped-image')).to_be_visible()
                            evidence_dir = ROOT / '.local' / 'frame-ui-current'
                            evidence_dir.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(evidence_dir / 'stitched.png'))
                            page.get_by_role('button', name='Source scan 1: tile-1', exact=True).click()
                            assert page.locator('.cx-cropped-image').count() == 0
                            source = page.locator('.cx-image img')
                            expect(source).to_be_visible()
                            page.wait_for_function("() => { const img = document.querySelector('.cx-image img'); return img && img.complete && img.naturalWidth > 0; }")
                            assert source.get_attribute('src').endswith('/sources/1/preview')
                            page.screenshot(path=str(evidence_dir / 'source.png'))
                            page.get_by_role('button', name='Stitched', exact=True).click()
                            expect(page.locator('.cx-cropped-image')).to_be_visible()
                            # Separate actions must send their own intent without stale menu state.
                            intents = []
                            def capture_intent(route):
                                intents.append((route.request.url.rsplit('/', 1)[-1], route.request.post_data_json))
                                route.fulfill(status=409, content_type='application/json', body='{"detail":"Synthetic request inspection"}')
                            page.route('**/api/cyberview/scan', capture_intent)
                            page.route('**/api/cyberview/scan-all-verified', capture_intent)
                            expect(page.get_by_role('button', name='Scan all frames', exact=True)).to_be_enabled()
                            page.get_by_role('button', name='Scan all frames', exact=True).click()
                            expect(page.get_by_role('alert')).to_contain_text('Synthetic request inspection')
                            page.locator('.cx-roll-menu summary').click()
                            page.get_by_label('After scanning').select_option('hold_at_end')
                            page.get_by_label('Expected frames · optional', exact=True).fill('6')
                            page.get_by_role('button', name='Scan all frames', exact=True).click()
                            page.wait_for_timeout(200)
                            page.get_by_role('button', name='Scan frame', exact=True).click()
                            page.wait_for_timeout(200)
                            assert intents[0] == ('scan-all-verified', {'roll': '', 'end_action': 'return_to_frame_1', 'repeat_samples': 1, 'expected_frames': None})
                            assert intents[1] == ('scan-all-verified', {'roll': '', 'end_action': 'hold_at_end', 'repeat_samples': 1, 'expected_frames': 6})
                            assert intents[2][0] == 'scan' and intents[2][1]['count'] == 1 and not intents[2][1]['until_end'], intents
                            page.unroute('**/api/cyberview/scan', capture_intent)
                            page.unroute('**/api/cyberview/scan-all-verified', capture_intent)
                            # A refused advance must expose reachable user actions.
                            # Route only this UI scenario; no driver command is sent.
                            stopped_status=page.request.get(origin+'/api/cyberview/status').json()
                            stopped_status['session']=stopped_status['session'] | {
                                'state':'complete','awaiting_end_confirmation':True,
                                'purpose':'scan_all','end_action':'hold_at_end',
                                'warning_code':'WARNING_EARLY_ADVANCE_REFUSED',
                                'end_of_roll_note':'Stopped at a refused advance; confirm or retry.'}
                            def stopped_snapshot(route):
                                route.fulfill(status=200,content_type='application/json',body=json.dumps(stopped_status))
                            resolved=[]
                            def resolve_stop(route):
                                resolved.append(route.request.post_data_json)
                                stopped_status['session']=stopped_status['session'] | {'awaiting_end_confirmation':False}
                                route.fulfill(status=200,content_type='application/json',body=json.dumps(stopped_status['session']))
                            page.route('**/api/cyberview/status',stopped_snapshot)
                            page.route('**/api/cyberview/refused-advance',resolve_stop)
                            expect(page.get_by_role('button',name='Retry advance',exact=True)).to_be_visible(timeout=10000)
                            expect(page.get_by_role('button',name='Confirm end and finish',exact=True)).to_be_visible()
                            expect(page.get_by_role('button',name='Keep film and stop',exact=True)).to_be_visible()
                            page.screenshot(path=str(evidence_dir/'refused-advance.png'))
                            page.get_by_role('button',name='Confirm end and finish',exact=True).click()
                            expect(page.get_by_role('button',name='Retry advance',exact=True)).not_to_be_visible()
                            assert resolved==[{'session_id':stopped_status['session']['id'],'action':'confirm_end'}]
                            page.unroute('**/api/cyberview/status',stopped_snapshot)
                            page.unroute('**/api/cyberview/refused-advance',resolve_stop)
                            page.get_by_role('button', name='Previous frame', exact=True).click()
                            expect(page.get_by_role('dialog', name='Previous frame?', exact=True)).to_be_visible()
                            navigation = []
                            def capture_previous(route):
                                navigation.append(route.request.post_data_json)
                                route.fulfill(status=409, content_type='application/json', body='{"detail":"Previous frame request inspected"}')
                            page.route('**/api/cyberview/film', capture_previous)
                            page.get_by_role('button', name='Continue', exact=True).click()
                            expect(page.get_by_role('alert')).to_contain_text('Previous frame request inspected')
                            assert navigation == [{'action': 'previous', 'acknowledged': True}]
                            page.unroute('**/api/cyberview/film', capture_previous)
                            # Border finding uses real-sized low-resolution previews, not
                            # three archival captures. Wider recovery follows the result.
                            with patch.dict(os.environ, {'FAKE_CVBRIDGE_RESPECT_SETTINGS': '1',
                                                         'FAKE_FRAME_WIDTH_MM': '37.2', 'FAKE_FRAME_OFFSET_MM': '0'}):
                                changed = page.request.post(origin + '/api/cyberview/backend', data={
                                    'backend': 'afl-native-experimental', 'acknowledged': True})
                                assert changed.ok, changed.text()
                                page.reload()
                                page.get_by_role('button', name='Scan', exact=True).click()
                                assert page.get_by_role('button', name='Stitched scan', exact=True).count() == 0
                                page.get_by_role('button', name='Auto find borders', exact=True).click()
                                expect(page.get_by_role('img', name='Frame borders: green detected, amber estimated')).to_be_visible(timeout=30000)
                                # The capture event precedes the final session event;
                                # review the overlay only after the preview task settles.
                                page.wait_for_function("async () => { const r = await fetch('/api/cyberview/status'); const s = (await r.json()).session; return s?.state === 'complete'; }")
                                expect(page.get_by_role('button', name='Scan frame', exact=True)).to_be_enabled()
                                expect(page.locator('.cx-border-help')).to_contain_text('beyond the current scan window')
                                assert page.locator('.cx-border-overlay line[data-border^="x-"][data-detected="true"]').count() == 2
                                assert page.locator('.cx-strip button').count() == 2, 'Border previews must not count as frames'
                                assert page.locator('.cx-cropped-image').count() == 0
                                page.screenshot(path=str(evidence_dir / 'auto-borders.png'))
                                recovery = []
                                def capture_recovery(route):
                                    recovery.append(route.request.post_data_json)
                                    route.fulfill(status=409, content_type='application/json', body='{"detail":"Wider capture request inspected"}')
                                page.route('**/api/cyberview/scan-frame', capture_recovery)
                                with page.expect_request(lambda request: request.method == 'POST' and '/api/cyberview/' in request.url) as capture_request:
                                    page.get_by_role('button', name='Scan frame', exact=True).click()
                                assert capture_request.value.url.endswith('/scan-frame'), capture_request.value.url
                                expect(page.get_by_role('alert')).to_contain_text('Wider capture request inspected')
                                assert len(recovery) == 1 and recovery[0]['acknowledged']
                                page.unroute('**/api/cyberview/scan-frame', capture_recovery)
                        # Changing film material persists without opening/commanding
                        # the scanner and does not reprocess an existing photograph.
                        saved_before = page.request.get(origin + '/api/cyberview/captures').json()['captures']
                        for kind, label in [('bw_negative', 'Black & white'), ('positive', 'Slide')]:
                            page.get_by_role('radio', name=label, exact=True).click()
                            expect(page.get_by_role('radio', name=label, exact=True)).to_be_checked()
                            expect(page.get_by_role('radio', name=label, exact=True)).to_be_enabled()
                            expect(page.locator('.cx-app')).to_have_attribute('data-film-type', kind)
                            saved_workspace = page.request.get(origin + '/api/cyberview/workspace').json()
                            assert saved_workspace['film_type'] == kind
                        page.reload()
                        expect(page.get_by_role('radio', name='Slide', exact=True)).to_be_checked()
                        saved_after = page.request.get(origin + '/api/cyberview/captures').json()['captures']
                        assert [c['adjustments'] for c in saved_before] == [c['adjustments'] for c in saved_after]
                        page.get_by_role('button', name='Develop', exact=True).click()
                        expect(page.locator('.app')).to_have_attribute('data-film-type', 'positive')
                        expect(page.get_by_role('heading', name='Time to develop.')).to_be_visible()
                        page.get_by_role('button', name='Scan', exact=True).click()
                        expect(page.get_by_role('radio', name='Slide', exact=True)).to_be_checked()
                        page.get_by_role('radio', name='Color negative', exact=True).check()
                        expect(page.get_by_role('radio', name='Color negative', exact=True)).to_be_enabled()
                        def reject_film_change(route):
                            route.fulfill(status=409, content_type='application/json', body='{"detail":"Synthetic film selection failure"}')
                        page.route('**/api/cyberview/film-type', reject_film_change)
                        page.get_by_role('radio', name='Black & white', exact=True).click()
                        expect(page.get_by_role('alert')).to_contain_text('Synthetic film selection failure')
                        expect(page.get_by_role('radio', name='Color negative', exact=True)).to_be_checked()
                        expect(page.locator('.cx-app')).to_have_attribute('data-film-type', 'color_negative')
                        page.unroute('**/api/cyberview/film-type', reject_film_change)
                        assert not errors, errors
                        browser.close()
                    print(json.dumps({'result': 'passed', 'mode': 'synthetic pipe helper; no device access',
                                      'verified': ['FRAME Home excludes synthetic captures from real-photo collection', 'Develop and return to scanner',
                                                   'direct capture by default', 'auto colour toggle', 'separate scan buttons and request intents',
                                                   'stitched crop and natural source geometry',
                                                   'quick border previews, overlays and automatic wider-capture routing',
                                                   'native capture provenance', 'negative inversion', 'manual film base',
                                                   'negative balance and response preview', 'private reference profile preview/export',
                                                   '16-bit export', 'immutable original', 'three film themes with API persistence',
                                                   'unchanged saved edits', 'Develop theme handoff', 'failed selection rollback'],
                                      'javascript_exceptions': errors}))
                finally:
                    server.should_exit = True
                    thread.join(20)
                    assert not thread.is_alive(), 'Fixture service failed to close'


if __name__ == '__main__':
    main()
