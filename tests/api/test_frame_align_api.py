"""35 mm auto-align through the API, against the fake bridge's synthetic film strip."""
from pathlib import Path
import asyncio
import hashlib
import threading
import time

from fastapi.testclient import TestClient
import pytest

from services.api.main import create_app
from services.scanner_host import cyberview, workspace
from services.scanner_host.native import NativeAflBridge
from services.scanner_host.backend import ScannerError
from services.imaging import frame_align, film_type_detection
from test_cyberview import FAKE
from test_workflow import login


def wait_session(client, states=('complete', 'cancelled', 'error'), timeout=20):
    """Wait for the public job, not its transiently completed local-search child."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = client.get('/api/cyberview/status').json()['session']
        if session and session['state'] in states and not session.get('roll_preview_parent_id'):
            return session
        time.sleep(.03)
    raise AssertionError(f'Parent session did not reach {states}: {session}')


@pytest.fixture
def strip_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS',str(tmp_path/'no-installed-vendor-curves'))
    ini = tmp_path / 'CyberViewX.ini'
    ini.write_text('[TOOLBAR FILMTERM]\nFilm Term Name=Kodak 200\n', encoding='latin-1')
    monkeypatch.setenv('FRAME_CVBRIDGE', str(FAKE))
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'cyberview-twain')  # the legacy path these tests cover
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', str(FAKE))
    monkeypatch.setenv('FRAME_CYBERVIEW_INI', str(ini))
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'strip')
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: False)
    monkeypatch.setattr(cyberview, 'scanner_present', lambda: True)
    monkeypatch.setattr(cyberview, 'reset_available', lambda: False)


def native(monkeypatch, actions=('next', 'nudge')):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    real = workspace.validation()
    monkeypatch.setattr(workspace, 'validation', lambda: {**real, 'actions': list(actions)})


def test_border_search_continues_lowres_until_a_feasible_plan_exists(tmp_path,strip_bridge,monkeypatch):
    from services.imaging import acquisition_plan
    native(monkeypatch)
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM','37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM','0')
    original=acquisition_plan.plan_archival
    rejected=[]
    def needs_another_measured_window(record):
        if len((record.get('derived') or {}).get('sources',[]))==3:
            rejected.append(record['width'])
            raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: rounded canvas is not an acquired window')
        return original(record)
    monkeypatch.setattr(acquisition_plan,'plan_archival',needs_another_measured_window)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        response=client.post('/api/cyberview/find-borders',json={'acknowledged':True})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=60)
        assert session['state']=='complete',session
        assert rejected and session['border_search_state']['probes']>=1
        assert session['border_search_state']['tile_plan_feasible'] is True
        capture=client.get('/api/cyberview/captures').json()['captures'][-1]
        assert len(capture['derived']['sources'])>=4
        assert all(source['dpi']==300 for source in capture['derived']['sources'])
        assert len(capture['derived']['acquisition_plan']['tiles'])<=2


def local_motion_session(app, session):
    """Native archival scans use a low-resolution child for exploratory motion."""
    searches = session.get('border_search_sessions') or []
    return app.state.store.get('cv_sessions', searches[-1]) if searches else session


def test_auto_align_on_a_single_full_window_scan(tmp_path, strip_bridge):
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        capture = client.get('/api/cyberview/captures').json()['captures'][0]
        assert capture['width'] == round(36.5 / 25.4 * 600)
        response = client.post(f"/api/cyberview/captures/{capture['id']}/auto-align", json={'bleed_mm': 0})
        assert response.status_code == 200, response.text
        alignment = response.json()['alignment']
        # A 36.5 mm window always fits an exact 36 mm crop, whether or not an edge was found
        # (the fake strip's polarity is not CyberView's; detection quality is covered in
        # tests/imaging/test_frame_align.py).
        assert alignment['exact'] and alignment['crop_mm'][0] == pytest.approx(36, abs=.05)
        saved = client.get('/api/cyberview/captures').json()['captures'][0]
        assert saved['adjustments']['crop']['right'] - saved['adjustments']['crop']['left'] == pytest.approx(36 / 36.5, abs=.003)
        assert client.post(f"/api/cyberview/captures/{capture['id']}/auto-align", json={'bleed_mm': 3}).status_code == 422


def test_auto_align_setting_aligns_new_scans(tmp_path, strip_bridge):
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        settings = client.put('/api/cyberview/align', json={'auto': True, 'bleed_mm': -.25}).json()['settings']
        assert settings['auto'] and settings['bleed_mm'] == -.25
        client.post('/api/cyberview/scan', json={'count': 1})
        wait_session(client)
        capture = client.get('/api/cyberview/captures').json()['captures'][0]
        assert capture['alignment']['crop_mm'][0] == pytest.approx(35.5, abs=.05)


def test_stitched_scan_needs_a_tested_fine_move_on_either_path(tmp_path, strip_bridge, monkeypatch):
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        assert response.status_code == 409 and "CyberView's step moves" in response.json()['detail']
    native(monkeypatch, actions=('next',))
    with TestClient(create_app(tmp_path / 'library2')) as client:
        login(client)
        assert client.get('/api/cyberview/align').json()['stitched_scan']['available'] is False
        response = client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        assert response.status_code == 409 and 'supervised test' in response.json()['detail']


def test_stitched_scan_uses_optical_plan_and_crops_exactly(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cyberview/stitched-scan', json={}).status_code == 422  # must acknowledge film movement
        started = client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'roll': 'Gold 200', 'offset_mm': 1.5})
        assert started.status_code == 200, started.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete', session
        assert session['transport']['fine_step_offset'] == 0
        assert session['transport']['position_known'] is True
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert len(capture['derived']['sources']) == 2
        assert capture['derived']['offsets_px'][0] == {'dx': 0.0, 'dy': 0.0}
        plan = capture['derived']['acquisition_plan']
        assert plan['basis'] == 'locally_registered_preview_windows_not_nominal_motor_pitch'
        child = local_motion_session(app, session)
        lowres = app.state.store.get('cv_captures', child['captures'][-1])
        assert lowres['derived']['sources'][0]['label'] == 'centre'
        assert lowres['derived']['offsets_px'][0] == {'dx': 0.0, 'dy': 0.0}
        assert capture['alignment']['confidence'] == 'frame_found' and capture['alignment']['exact']
        assert capture['alignment']['crop_mm'] == pytest.approx([36, 24], abs=.05)
        assert capture['width'] > round(36.5 / 25.4 * 1800)          # longer than any single scan
        assert capture['adjustments']['negative_response'] == .5
        assert capture['negative_balance']['method'] == 'brightest-0.5-percent'
        assert capture['adjustments']['film_base'][0] > capture['adjustments']['film_base'][2]
        exported = client.get(f"/api/cyberview/captures/{capture['id']}/export/tiff")
        assert exported.status_code == 200


def test_stitched_scan_through_cyberview_step_commands(tmp_path, strip_bridge, monkeypatch):
    # Forward/Backward One Step reach the same selector 10 as the native nudge.
    monkeypatch.setattr(cyberview, 'validated_commands', lambda: {'next', 'step_forward', 'step_back'})
    log = tmp_path / 'bridge.log'
    monkeypatch.setenv('FAKE_CVBRIDGE_LOG', str(log))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.get('/api/cyberview/align').json()['stitched_scan']['available'] is True
        started = client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'offset_mm': 1.5})
        assert started.status_code == 200, started.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'error', session
        assert 'not marked as a complete frame' in session['error']
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert capture['backend'] == 'cyberview-twain'
        assert capture['alignment']['confidence'] == 'centered'
        assert not capture['alignment']['crop_applied']
        assert capture['adjustments']['crop'] == {'left': 0, 'top': 0, 'right': 1, 'bottom': 1}
    sent = log.read_text()
    assert 'film step back' in sent and 'film step forward' in sent and 'film nudge' not in sent


def test_new_scans_get_cyberviews_auto_colour_and_it_can_be_toggled(tmp_path, strip_bridge):
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 200
        assert wait_session(client)['state'] == 'complete'
        capture = client.get('/api/cyberview/captures').json()['captures'][0]
        words = capture['adjustments']['auto_color']
        assert words and len(words) == 18 and words[9:12] == [128, 128, 128]
        off = client.post(f"/api/cyberview/captures/{capture['id']}/auto-color", json={'enabled': False}).json()
        assert off['adjustments']['auto_color'] is None
        on = client.post(f"/api/cyberview/captures/{capture['id']}/auto-color", json={'enabled': True}).json()
        assert on['adjustments']['auto_color'] == words
        assert client.get(f"/api/cyberview/captures/{capture['id']}/export/tiff").status_code == 200


def wait_for_event(event):
    assert event.wait(10), 'The synthetic test did not reach its controlled boundary'


async def held_until(release):
    while not release.is_set():
        await asyncio.sleep(.005)


@pytest.mark.parametrize('route', ['stitched-scan', 'find-borders'])
def test_stitched_cancel_between_scans_latches_without_further_motion(tmp_path, strip_bridge, monkeypatch, route):
    native(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = NativeAflBridge.scan
    calls = []

    async def hold_completed_scan(bridge, out, count, on_event):
        calls.append(Path(out).name)
        result = await original(bridge, out, count, on_event)
        if Path(out).name == 'source-centre.tif':
            assert bridge.busy is False
            entered.set()
            await held_until(release)
        return result

    monkeypatch.setattr(NativeAflBridge, 'scan', hold_completed_scan)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cyberview/' + route, json={'acknowledged': True}).status_code == 200
        try:
            wait_for_event(entered)
            stopped = client.post('/api/cyberview/cancel')
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()['cancel_requested'] is True
        finally:
            release.set()
        session = wait_session(client, timeout=60)
        assert session['state'] == 'cancelled'
        assert calls == ['source-centre.tif']
        motion = local_motion_session(app, session)
        assert motion['stitch']['position']['net_completed_steps'] == 0
        [source] = motion['stitch']['sources']
        assert app.state.store.path(source['path']).is_file()
        assert hashlib.sha256(app.state.store.path(source['path']).read_bytes()).hexdigest() == source['sha256']
        assert client.get('/api/cyberview/captures').json()['captures'] == []


def test_second_stitched_acquisition_failure_reports_offset_and_does_not_return(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    original_scan, original_control = NativeAflBridge.scan, NativeAflBridge.control
    moves = []

    async def fail_back_scan(bridge, out, count, on_event):
        if Path(out).name == 'source-back.tif':
            raise ScannerError('Injected synthetic second acquisition failure')
        return await original_scan(bridge, out, count, on_event)

    async def track_control(bridge, action, on_event=None, value=None):
        moves.append(value)
        return await original_control(bridge, action, on_event, value)

    monkeypatch.setattr(NativeAflBridge, 'scan', fail_back_scan)
    monkeypatch.setattr(NativeAflBridge, 'control', track_control)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client, timeout=60)
        assert session['state'] == 'error'
        assert moves == ['back 20']
        motion = local_motion_session(app, session)
        position = motion['stitch']['position']
        assert position['position_known'] and position['net_completed_steps'] == -20
        assert position['returned_to_start'] is False
        assert '20 steps back' in session['error'] and 'No automatic return' in session['error']
        assert len(motion['stitch']['sources']) == 1


def test_failed_stitched_motion_reports_uncertain_position_without_return(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    original = NativeAflBridge.control
    moves = []

    async def fail_forward(bridge, action, on_event=None, value=None):
        moves.append(value)
        if value.startswith('forward'):
            raise ScannerError('Injected synthetic motion failure')
        return await original(bridge, action, on_event, value)

    monkeypatch.setattr(NativeAflBridge, 'control', fail_forward)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client)
        assert session['state'] == 'error'
        assert len(moves) == 2 and moves[0] == 'back 20' and moves[1].startswith('forward ')
        motion = local_motion_session(app, session)
        position = motion['stitch']['position']
        assert position['position_known'] is False and position['net_completed_steps'] == -20
        assert position['pending_move']['direction'] == 'forward'
        assert 'position is uncertain' in session['error'] and 'No automatic return' in session['error']
        assert len(motion['stitch']['sources']) == 2


def test_cancel_between_stitched_nudge_chunks_prevents_following_chunks(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    original = NativeAflBridge.control
    entered, release = threading.Event(), threading.Event()
    moves = []
    # The forward move is two 20-step commands; cancel after the first.
    monkeypatch.setattr(frame_align, 'phase_shift', lambda *args, **kwargs: (0, 2, .9))

    async def hold_forward_chunk(bridge, action, on_event=None, value=None):
        moves.append(value)
        result = await original(bridge, action, on_event, value)
        if value.startswith('forward'):
            assert value == 'forward 20' and bridge.busy is False
            entered.set()
            await held_until(release)
        return result

    monkeypatch.setattr(NativeAflBridge, 'control', hold_forward_chunk)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'offset_mm': 3})
        try:
            wait_for_event(entered)
            assert client.post('/api/cyberview/cancel').status_code == 200
        finally:
            release.set()
        session = wait_session(client)
        assert session['state'] == 'cancelled'
        assert moves == ['back 20', 'forward 20']
        motion = local_motion_session(app, session)
        assert motion['stitch']['position']['position_known'] is True
        assert motion['stitch']['position']['net_completed_steps'] == 0


def test_unreliable_forward_registration_never_publishes_stitched_image(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    original = frame_align.stitch

    def unreliable_forward(*args, **kwargs):
        result = original(*args, **kwargs)
        result['match_strength'][-1] = .01
        return result

    monkeypatch.setattr(frame_align, 'stitch', unreliable_forward)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client, timeout=60)
        assert session['state'] == 'error' and 'matched reliably' in session['error']
        motion = local_motion_session(app, session)
        assert len(motion['stitch']['sources']) == 3
        assert motion['stitch']['position']['net_completed_steps'] == 0
        assert client.get('/api/cyberview/captures').json()['captures'] == []


def test_stitched_capture_serves_its_two_planned_source_previews(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'offset_mm': 1.5}).status_code == 200
        assert wait_session(client, timeout=60)['state'] == 'complete'
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert len(capture['derived']['sources']) == 2
        for number in (1, 2):
            preview = client.get(f"/api/cyberview/captures/{capture['id']}/sources/{number}/preview")
            assert preview.status_code == 200 and preview.headers['content-type'] == 'image/jpeg'
        assert client.get(f"/api/cyberview/captures/{capture['id']}/sources/3/preview").status_code == 404


def test_find_borders_uses_quick_previews_without_changing_scan_settings(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        before = client.get('/api/cyberview/workspace').json()['settings']
        assert client.get('/api/cyberview/align').json()['find_borders']['available']
        assert client.post('/api/cyberview/find-borders', json={}).status_code == 422
        started = client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'Borders'})
        assert started.status_code == 200, started.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        assert session['border_search'] and session['purpose'] == 'prescan'
        assert session['completed'] == 3
        record, = client.get('/api/cyberview/captures').json()['captures']
        assert record['border_preview'] and record['purpose'] == 'prescan'
        assert record['hardware'] is False
        assert record['dpi'] == 300 and record['bits'] == 8
        assert record['alignment']['confidence'] == 'frame_found'
        assert record['alignment']['edges_x']['measured_mm'] == pytest.approx(37.2, abs=.2)
        assert not record['alignment']['crop_applied']
        assert record['adjustments']['crop'] == {'left': 0, 'top': 0, 'right': 1, 'bottom': 1}
        assert record['derived']['requires_wider_capture']
        assert not record['derived']['single_pass_eligible']
        for source in record['derived']['sources']:
            assert source['dpi'] == 300 and source['bits'] == 8
            assert hashlib.sha256(app.state.store.path(source['path']).read_bytes()).hexdigest() == source['sha256']
        assert client.get('/api/cyberview/workspace').json()['settings'] == before
        assert session['stitch']['position']['net_completed_steps'] == 0


def test_find_borders_stops_without_motion_when_first_preview_contains_both_edges(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    log = tmp_path / 'bridge.log'
    monkeypatch.setenv('FAKE_CVBRIDGE_LOG', str(log))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/find-borders', json={'acknowledged': True}).status_code == 200
        session = wait_session(client)
        assert session['state'] == 'complete', session
        assert session['completed'] == session['count'] == 1
        assert 'film nudge' not in log.read_text()
        record, = client.get('/api/cyberview/captures').json()['captures']
        assert len(record['derived']['sources']) == 1
        assert not record['derived']['requires_wider_capture']
        assert record['derived']['single_pass_eligible']


def test_find_borders_keeps_probing_toward_missing_edge_until_found(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '4.2')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'Off centre'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete', session
        record, = client.get('/api/cyberview/captures').json()['captures']
        assert session['border_search_state']['probes'] > 0
        assert session['border_search_state']['probes'] <= session['border_search_state']['probe_limit']
        assert session['border_search_state']['last_direction'] == 'back'
        assert session['stitch']['position']['net_completed_steps'] == 0
        assert session['stitch']['position']['returned_to_start'] is True
        assert record['alignment']['confidence'] == 'frame_found'
        assert record['derived']['sources'][-1]['label'].startswith('border-search-')


def test_scan_frame_uses_verified_full_window_for_fitting_frame(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    log = tmp_path / 'bridge.log'
    monkeypatch.setenv('FAKE_CVBRIDGE_LOG', str(log))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        started = client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'Fast'}).json()
        assert wait_session(client)['state'] == 'complete'
        preview, = client.get('/api/cyberview/captures').json()['captures']
        assert preview['derived']['single_pass_eligible']
        response = client.post('/api/cyberview/scan-frame', json={'acknowledged': True, 'roll': 'Fast'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'scan')
        assert capture['requested_settings']['crop']['left'] == 0
        assert capture['requested_settings']['crop']['right'] == pytest.approx(2586 / 1800)
        assert capture['coverage_verification']['verified']
        assert capture['alignment']['crop_applied']
        assert 'film nudge' not in log.read_text()


def test_scan_frame_routes_oversized_frame_to_overlap_recovery(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    log = tmp_path / 'bridge.log'
    monkeypatch.setenv('FAKE_CVBRIDGE_LOG', str(log))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'Wide'})
        assert wait_session(client)['state'] == 'complete'
        response = client.post('/api/cyberview/scan-frame', json={'acknowledged': True, 'roll': 'Wide'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete', session
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert len(capture['derived']['sources']) == 2
        assert capture['alignment']['confidence'] == 'frame_found'
        assert capture['alignment']['crop_applied']


def test_scan_frame_halts_without_highres_search_when_full_resolution_witness_fails(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_1800_MM', '37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'Shifted'})
        assert wait_session(client)['state'] == 'complete'
        response = client.post('/api/cyberview/scan-frame', json={'acknowledged': True, 'roll': 'Shifted'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'error' and 'UNVERIFIED_FRAME_COVERAGE' in session['error'], session
        captures = client.get('/api/cyberview/captures').json()['captures']
        attempt = next(c for c in captures if c['purpose'] == 'coverage_attempt')
        assert not attempt['coverage_verification']['verified']
        assert len(attempt['derived']['sources']) == 1
        assert all(c['purpose'] not in ('scan', 'stitched') for c in captures)
        assert len([source for source in session['retained_sources'] if source['dpi'] == 1800]) == 1


def test_roll_preview_saves_all_frames_as_low_resolution_non_archival_captures(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '3')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'all', 'dpi': 300, 'roll': 'Contact sheet'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete' and session['completed'] == 3, session
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len(captures) == 3
        assert [c['purpose'] for c in captures] == ['roll_preview'] * 3
        assert [c['index'] for c in captures] == [1, 2, 3]
        assert all(c['dpi'] == 300 and c['bits'] == 8 for c in captures)
        assert all(c['alignment']['confidence'] == 'frame_found' for c in captures)
        assert all(c['derived']['single_pass_eligible'] for c in captures)


def test_detailed_roll_preview_uses_recorded_600dpi_configuration(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'one', 'dpi': 600, 'roll': 'Detailed'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        capture, = [c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'roll_preview']
        assert capture['purpose'] == 'roll_preview'
        assert capture['dpi'] == 600 and capture['bits'] == 16
        assert capture['width'] > 800 and capture['height'] > 560


def test_auto_film_type_preview_updates_workspace_from_orange_negative_base(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/film-type/auto-detect', json={'roll': 'Auto test'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        assert session['film_type_detection']['film_type'] == 'color_negative'
        assert session['film_type_detection']['confidence'] >= .9
        assert client.get('/api/cyberview/workspace').json()['film_type'] == 'color_negative'
        preview, = client.get('/api/cyberview/captures').json()['captures']
        assert preview['film_type'] == 'color_negative'
        assert preview['film_type_detection']['method'] == 'orange_film_base'


def test_auto_film_type_keeps_manual_choice_when_first_frame_is_ambiguous(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setattr(film_type_detection, 'detect', lambda *_args, **_kwargs: {
        'film_type': 'positive', 'confidence': .58, 'method': 'neutral_rebate_color_frame',
        'note': 'No orange negative mask was found.'})
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/film-type/auto-detect', json={'roll': 'Ambiguous'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        assert not session['film_type_detection']['applied']
        assert session['film_type_detection']['previous_type'] == 'color_negative'
        assert client.get('/api/cyberview/workspace').json()['film_type'] == 'color_negative'


def test_roll_preview_preserves_frames_when_transport_does_not_advance_at_end(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '2')
    monkeypatch.setenv('FAKE_CVBRIDGE_END_MESSAGE', 'The driver did not confirm the requested frame movement')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'all', 'dpi': 300, 'roll': 'End of strip'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete' and session['completed'] == 2, session
        assert session['end_of_roll_unconfirmed']
        assert session['awaiting_end_confirmation']
        assert session['stop_reason']=='STOPPED_AT_REFUSED_ADVANCE'
        assert 'no return or eject was attempted' in session['end_of_roll_note']
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len([c for c in captures if c['purpose'] == 'roll_preview']) == 2


def test_scan_favorites_acquires_only_starred_previews_at_full_resolution(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '3')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'all', 'dpi': 300, 'roll': 'Favorites','expected_frames':3})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client)
        assert preview_session['state'] == 'complete', preview_session
        previews = [c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'roll_preview']
        for frame in (previews[0], previews[2]):
            assert client.patch(f"/api/cyberview/captures/{frame['id']}", json={'favorite': True}).status_code == 200
        response = client.post('/api/cyberview/scan-favorites', json={
            'preview_session_id': preview_session['id'], 'roll': 'Favorites',
            'preview_ids': [previews[0]['id'], previews[2]['id']],
        })
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete' and session['completed'] == 2, session
        captures = client.get('/api/cyberview/captures').json()['captures']
        finals = [c for c in captures if c.get('purpose') == 'scan']
        assert [c['index'] for c in finals] == [1, 3]
        assert all(c['dpi'] == 1800 and c['coverage_verification']['verified'] for c in finals)
        assert len([c for c in captures if c.get('purpose') == 'roll_preview']) == 3


def test_favorite_seek_starts_at_last_preview_even_when_it_is_not_selected(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '3')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    moves = []
    original_film = NativeAflBridge.film

    async def film(self, action, *args, **kwargs):
        moves.append(action)
        return await original_film(self, action, *args, **kwargs)

    monkeypatch.setattr(NativeAflBridge, 'film', film)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'all', 'dpi': 300, 'roll': 'Seek ledger','expected_frames':3})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client)
        assert preview_session['state'] == 'complete', preview_session
        previews = client.get('/api/cyberview/captures').json()['captures']
        selected = next(item for item in previews if item['purpose'] == 'roll_preview' and item['index'] == 2)
        client.patch(f"/api/cyberview/captures/{selected['id']}", json={'favorite': True})
        moves.clear()
        response = client.post('/api/cyberview/scan-favorites', json={
            'preview_session_id': preview_session['id'], 'roll': 'Seek ledger', 'preview_ids': [selected['id']]})
        assert response.status_code == 200, response.text
        assert response.json()['transport']['current_preview_index'] == 3
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete', session
        # Frame 3 -> selected frame 2, then frame 2 -> frame 1 after capture.
        assert moves == ['previous', 'previous']
        assert session['transport']['current_preview_index'] == 1


def test_scan_favorite_uses_overlap_for_preview_known_to_be_too_wide(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'scope': 'one', 'dpi': 300, 'roll': 'Wide favorite'})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client)
        assert preview_session['state'] == 'complete', preview_session
        preview, = client.get('/api/cyberview/captures').json()['captures']
        assert not preview['derived']['single_pass_eligible']
        client.patch(f"/api/cyberview/captures/{preview['id']}", json={'favorite': True})
        response = client.post('/api/cyberview/scan-favorites', json={
            'preview_session_id': preview_session['id'], 'roll': 'Wide favorite', 'preview_ids': [preview['id']],
        })
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete' and session['completed'] == 1, session
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert capture['alignment']['confidence'] == 'frame_found' and capture['alignment']['crop_applied']
        assert capture['derived']['border_preview_capture_id'] != preview['id']
        assert session['arrival_verifications'][0]['preview_id'] == preview['id']
        assert capture['coverage_verification']['verified']
        assert len(capture['derived']['acquisition_plan']['tiles']) == 2


def test_scan_all_verified_runs_border_find_for_each_frame_before_archival_scan(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '3')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Whole roll','expected_frames':3})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete' and session['completed'] == 3, session
        captures = client.get('/api/cyberview/captures').json()['captures']
        previews = [c for c in captures if c['purpose'] == 'roll_preview']
        finals = [c for c in captures if c['purpose'] == 'scan']
        assert [c['index'] for c in previews] == [1, 2, 3]
        assert [c['index'] for c in finals] == [1, 2, 3]
        assert all(c['dpi'] == 300 and c['alignment']['confidence'] == 'frame_found' for c in previews)
        assert all(c['dpi'] == 1800 and c['coverage_verification']['verified'] for c in finals)
        assert session['transport']['returned_to_first'] is True


def test_scan_all_returns_to_frame_one_after_user_confirms_refused_advance(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '2')
    monkeypatch.setenv('FAKE_CVBRIDGE_END_MESSAGE', 'The driver did not confirm the requested frame movement')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'End and return'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete' and session['completed'] == 2, session
        assert session['end_of_roll_unconfirmed'] is True
        assert session['awaiting_end_confirmation']
        assert 'end_action_result' not in session
        client.post('/api/cyberview/refused-advance',json={'session_id':session['id'],'action':'confirm_end'}).raise_for_status()
        session=wait_session(client,timeout=60)
        assert session['user_confirmed_end']
        assert session['return_verification']['verified']
        assert session['transport']['returned_to_first'] is True
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len([item for item in captures if item['purpose'] == 'roll_preview']) == 2
        assert len([item for item in captures if item['purpose'] == 'scan']) == 2


def test_scan_frame_stops_at_planned_tile_limit_when_highres_geometry_changes(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_1800_MM', '37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '4.2')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/find-borders', json={'acknowledged': True, 'roll': 'High-res recovery'})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client)
        assert preview_session['state'] == 'complete', preview_session
        response = client.post('/api/cyberview/scan-frame', json={'acknowledged': True, 'roll': 'High-res recovery'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'error', session
        assert any(code in session['error'] for code in ('UNVERIFIED_FRAME_COVERAGE', 'UNVERIFIED_STITCH_ALIGNMENT')), session
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert not any(c.get('purpose') in ('scan', 'stitched') for c in captures)
        retained = [source for source in session['retained_sources'] if source['dpi'] == 1800]
        assert 1 <= len(retained) <= 2
        assert all((tmp_path / 'library' / source['path']).exists() for source in retained)


def test_cyberscan_archive_delete_removes_roll_captures_and_source_files(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/cyberview/scan', json={'count': 1, 'roll': 'Archive delete'})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len(captures) == 1 and captures[0]['roll'] == 'Archive delete'
        folder = app.state.store.root / 'cyberview' / session['id']
        assert folder.exists()
        deleted = client.request('DELETE', '/api/cyberview/rolls', json={'roll': 'Archive delete'})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()['deleted'] and deleted.json()['captures_deleted'] == 1
        assert not folder.exists()
        assert not client.get('/api/cyberview/captures').json()['captures']
        with pytest.raises(KeyError):
            app.state.store.get('cv_sessions', session['id'])


def test_find_borders_refuses_an_unverified_full_window(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    proved = workspace.validation()
    monkeypatch.setattr(workspace, 'validation', lambda: proved | {'configurations': []})
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert not client.get('/api/cyberview/align').json()['find_borders']['available']
        response = client.post('/api/cyberview/find-borders', json={'acknowledged': True})
        assert response.status_code == 409
        assert 'supervised' in response.json()['detail']


@pytest.mark.parametrize('confidence', ['one_edge', 'centered'])
def test_uncertain_stitched_boundary_does_not_replace_saved_crop(tmp_path, strip_bridge, monkeypatch, confidence):
    native(monkeypatch)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        record = client.get('/api/cyberview/captures').json()['captures'][0]
        record['purpose'] = 'stitched'
        record['adjustments']['crop'] = {'left': .1, 'top': .2, 'right': .85, 'bottom': .9}
        app.state.store.save('cv_captures', record)
        before_crop = record['adjustments']['crop']
        original_align = frame_align.align_35mm

        def one_edge(*args, **kwargs):
            result = original_align(*args, **kwargs)
            result.update(confidence=confidence, exact=True)
            result['x'] = {'found': 'start', 'start': 10} if confidence == 'one_edge' else {'found': 'none'}
            return result

        monkeypatch.setattr(frame_align, 'align_35mm', one_edge)
        result = client.post(f"/api/cyberview/captures/{record['id']}/auto-align", json={}).json()
        assert result['alignment']['exact']
        assert not result['alignment']['crop_applied'] and not result['applied']
        assert result['capture']['adjustments']['crop'] == before_crop
        assert 'Both frame borders were not detected' in result['alignment']['note']
        assert app.state.store.get('cv_captures', record['id'])['adjustments']['crop'] == before_crop
