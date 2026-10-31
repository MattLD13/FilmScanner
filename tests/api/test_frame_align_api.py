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
from services.imaging import frame_align
from test_cyberview import FAKE, wait_session
from test_workflow import login


@pytest.fixture
def strip_bridge(tmp_path, monkeypatch):
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
    real = workspace.validation()
    monkeypatch.setattr(workspace, 'validation', lambda: {**real, 'actions': list(actions)})


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


def test_stitched_scan_calibrates_stitches_and_crops_exactly(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/stitched-scan', json={}).status_code == 422  # must acknowledge film movement
        started = client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'roll': 'Gold 200', 'offset_mm': 1.5})
        assert started.status_code == 200, started.text
        session = wait_session(client, timeout=60)
        assert session['state'] == 'complete', session
        assert session['stitch']['position']['net_completed_steps'] == 0
        assert session['stitch']['position']['position_known'] is True
        assert session['stitch']['position']['returned_to_start'] is True
        assert 'not been remeasured' in session['stitch']['position']['note']
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert len(capture['derived']['sources']) == 3
        # Learned from the probe: 600 dpi / 25.4 / 1.37 px per step = 17.2 steps per mm.
        assert capture['derived']['steps_per_mm'] == pytest.approx(600 / 25.4 / 1.37, rel=.05)
        assert capture['alignment']['confidence'] == 'frame_found' and capture['alignment']['exact']
        assert capture['alignment']['crop_mm'] == pytest.approx([36, 24], abs=.05)
        assert capture['width'] > round(36.5 / 25.4 * 600)          # longer than any single scan
        assert capture['adjustments']['negative_response'] == .5
        assert capture['negative_balance']['method'] == 'brightest-0.5-percent'
        assert capture['adjustments']['film_base'][0] > capture['adjustments']['film_base'][2]
        assert client.get('/api/cyberview/align').json()['settings']['steps_per_mm'] == capture['derived']['steps_per_mm']
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
        assert session['state'] == 'complete', session
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert capture['backend'] == 'cyberview-twain'
        assert capture['alignment']['exact'] and capture['alignment']['crop_mm'] == pytest.approx([36, 24], abs=.05)
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


def test_stitched_cancel_between_scans_latches_without_further_motion(tmp_path, strip_bridge, monkeypatch):
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
        assert client.post('/api/cyberview/stitched-scan', json={'acknowledged': True}).status_code == 200
        try:
            wait_for_event(entered)
            stopped = client.post('/api/cyberview/cancel')
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()['cancel_requested'] is True
        finally:
            release.set()
        session = wait_session(client)
        assert session['state'] == 'cancelled'
        assert calls == ['source-centre.tif']
        assert session['stitch']['position']['net_completed_steps'] == 0
        [source] = session['stitch']['sources']
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
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client)
        assert session['state'] == 'error'
        assert moves == ['back 20']
        position = session['stitch']['position']
        assert position['position_known'] and position['net_completed_steps'] == -20
        assert position['returned_to_start'] is False
        assert '20 steps back' in session['error'] and 'No automatic return' in session['error']
        assert len(session['stitch']['sources']) == 1


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
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client)
        assert session['state'] == 'error'
        assert len(moves) == 2 and moves[0] == 'back 20' and moves[1].startswith('forward ')
        position = session['stitch']['position']
        assert position['position_known'] is False and position['net_completed_steps'] == -20
        assert position['pending_move']['direction'] == 'forward'
        assert 'position is uncertain' in session['error'] and 'No automatic return' in session['error']
        assert len(session['stitch']['sources']) == 2


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
    with TestClient(create_app(tmp_path / 'library')) as client:
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
        assert session['stitch']['position']['position_known'] is True
        assert session['stitch']['position']['net_completed_steps'] == 0


def test_unreliable_forward_registration_never_publishes_stitched_image(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    original = frame_align.stitch

    def unreliable_forward(*args, **kwargs):
        result = original(*args, **kwargs)
        result['match_strength'][-1] = .01
        return result

    monkeypatch.setattr(frame_align, 'stitch', unreliable_forward)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/stitched-scan', json={'acknowledged': True})
        session = wait_session(client, timeout=60)
        assert session['state'] == 'error' and 'matched reliably' in session['error']
        assert len(session['stitch']['sources']) == 3
        assert session['stitch']['position']['net_completed_steps'] == 0
        assert client.get('/api/cyberview/captures').json()['captures'] == []


def test_stitched_capture_serves_its_three_source_previews(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/stitched-scan', json={'acknowledged': True, 'offset_mm': 1.5}).status_code == 200
        assert wait_session(client, timeout=60)['state'] == 'complete'
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        for number in (1, 2, 3):
            preview = client.get(f"/api/cyberview/captures/{capture['id']}/sources/{number}/preview")
            assert preview.status_code == 200 and preview.headers['content-type'] == 'image/jpeg'
        assert client.get(f"/api/cyberview/captures/{capture['id']}/sources/4/preview").status_code == 404
