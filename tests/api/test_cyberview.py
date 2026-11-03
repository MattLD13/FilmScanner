"""CyberScan X API against a fake cvbridge: no driver, no scanner, same protocol."""
import hashlib
import json
from io import BytesIO
from pathlib import Path
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest
import tifffile

from services.api import cyberview_routes
from services.api.main import create_app
from services.scanner_host import cyberview
from test_workflow import login

FAKE = Path(__file__).resolve().parents[1] / 'scanner' / 'fake_cvbridge.py'


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS',str(tmp_path/'no-installed-vendor-curves'))
    log = tmp_path / 'bridge.log'
    ini = tmp_path / 'CyberViewX.ini'
    ini.write_text('[TOOLBAR FILMTERM]\nFilm Term Name=Kodak 200\n[SETUPDLG DEFAULT PAGE]\nAuto Exposure=1\n'
                   'Default Crop Area Left=0.03\nDefault Crop Area Top=0.003\nDefault Crop Area Right=1.407\n'
                   'Default Crop Area Bottom=0.95\n', encoding='latin-1')
    monkeypatch.setenv('FRAME_CVBRIDGE', str(FAKE))
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'cyberview-twain')  # the legacy path these tests cover
    monkeypatch.setenv('FRAME_CYBERVIEW_INI', str(ini))
    monkeypatch.setenv('FAKE_CVBRIDGE_LOG', str(log))
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: False)
    monkeypatch.setattr(cyberview, 'scanner_present', lambda: True)
    monkeypatch.setattr(cyberview, 'reset_available', lambda: False)
    return log


def wait_session(client, states=('complete', 'cancelled', 'error'), timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = client.get('/api/cyberview/status').json()['session']
        if session and session['state'] in states:
            return session
        time.sleep(.05)
    raise AssertionError(f'Session did not reach {states}: {session}')


def test_scan_keeps_original_and_exports(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        assert client.get('/api/cyberview/status').status_code == 401
        login(client)
        status = client.get('/api/cyberview/status').json()
        assert status['bridge_built'] and status['settings']['film_term'] == 'Kodak 200' and not status['session_open']
        started = client.post('/api/cyberview/scan', json={'count': 1, 'roll': 'Gold 200'})
        assert started.status_code == 200, started.text
        session = wait_session(client)
        assert session['state'] == 'complete' and session['completed'] == 1
        assert session['driver_status'].startswith('Preparing film scanner')
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len(captures) == 1
        capture = captures[0]
        assert capture['roll'] == 'Gold 200' and capture['bits'] == 16 and capture['dpi'] == 1800 and capture['hardware']
        assert capture['cyberview']['film_term'] == 'Kodak 200'
        original = app.state.store.path(capture['original_path'])
        assert hashlib.sha256(original.read_bytes()).hexdigest() == capture['sha256']
        assert not list(original.parent.glob('incoming*'))

        for kind in ('preview', 'thumb'):
            response = client.get(f'/api/cyberview/captures/{capture["id"]}/{kind}')
            assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
        exported = client.get(f'/api/cyberview/captures/{capture["id"]}/export/original')
        assert exported.content == original.read_bytes()

        patch = client.patch(f'/api/cyberview/captures/{capture["id"]}',
                             json={'adjustments': {'exposure': .5, 'rotation': 90, 'mirror': True}, 'favorite': True})
        assert patch.status_code == 200 and patch.json()['favorite'] is True
        assert client.patch(f'/api/cyberview/captures/{capture["id"]}', json={'adjustments': {'rotation': 45}}).status_code == 422
        tiff = client.get(f'/api/cyberview/captures/{capture["id"]}/export/tiff')
        assert tiff.status_code == 200
        values = tifffile.imread(BytesIO(tiff.content))
        assert values.dtype == np.uint16 and values.shape == (60, 40, 3)  # rotated 90 degrees
        jpeg = client.get(f'/api/cyberview/captures/{capture["id"]}/export/jpeg')
        with Image.open(BytesIO(jpeg.content)) as image:
            assert image.format == 'JPEG' and image.size == (40, 60)
        # The original is untouched by edits and exports.
        assert hashlib.sha256(original.read_bytes()).hexdigest() == capture['sha256']
        assert client.get(f'/api/cyberview/captures/{capture["id"]}/export/png').status_code == 404


def test_one_driver_session_serves_many_scans(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cyberview/scan', json={'count': 3}).status_code == 200
        assert wait_session(client)['completed'] == 3
        assert client.get('/api/cyberview/status').json()['session_open']
        assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 200
        assert wait_session(client)['completed'] == 1
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert [c['index'] for c in captures] == [1, 2, 3, 1]
        assert len({c['original_path'] for c in captures}) == 4
        # Frames 2 and 3 were reached with CyberView's own "next frame" command.
        assert len({c['sha256'] for c in captures[:3]}) == 3
        assert client.post('/api/cyberview/film', json={'action': 'next'}).status_code == 200
        # Backward One Frame hung the real driver; it is not offered.
        assert client.post('/api/cyberview/film', json={'action': 'previous'}).status_code == 409
        released = client.post('/api/cyberview/release').json()
        assert released['session_open'] is False
    calls = bridge.read_text().splitlines()
    assert sum(line.startswith('serve') for line in calls) == 1, calls


def test_usb_trace_is_requested_only_when_a_trace_folder_is_set(tmp_path, bridge, monkeypatch):
    traces = tmp_path / 'traces'
    monkeypatch.setenv('FRAME_USB_TRACE_DIR', str(traces))
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 200
        assert wait_session(client)['state'] == 'complete'
        client.post('/api/cyberview/release')
    serve = next(line for line in bridge.read_text().splitlines() if line.startswith('serve'))
    assert '--trace-usb' in serve
    [trace] = traces.glob('usb-*.jsonl')
    assert json.loads(trace.read_text())['module'] == 'fvc.dll'
    monkeypatch.delenv('FRAME_USB_TRACE_DIR')
    assert cyberview.trace_args() == []


def test_live_preview_rows_reach_clients_and_late_joiners(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        with client.websocket_connect('/api/events', headers={'origin': 'http://testserver'}) as socket:
            assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 200
            seen = []
            while not any(e.get('type') == 'cyberview_capture' for e in seen):
                seen.append(socket.receive_json())
        start = next(e for e in seen if e['type'] == 'cyberview_live_start')
        assert start['width'] == 48 and start['scale'] == 8 and start['frame'] == 1
        assert [e['y'] for e in seen if e['type'] == 'cyberview_live'] == list(range(30))
        live = client.get('/api/cyberview/live').json()['live']
        assert live['width'] == 48 and len(live['rows']) == 30
        sys.path.insert(0, str(FAKE.parent))
        from fake_cvbridge import live_row
        assert __import__('base64').b64decode(live['rows'][7]) == live_row(7)


def test_stuck_position_sensor_asks_for_a_power_cycle_without_usb_retry(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'sensor')
    monkeypatch.setattr(cyberview, 'reset_available', lambda: True)
    resets = []
    async def reset():
        resets.append(1)
        return True
    monkeypatch.setattr(cyberview, 'reset_scanner', reset)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 200
        session = wait_session(client)
        assert session['state'] == 'error' and 'take the film out' in session['error']
        assert client.get('/api/cyberview/status').json()['session_open'] is False
    # Only the routine restart before the session; no automatic retry for this failure.
    assert len(resets) <= 1


def test_stuck_driver_reports_power_cycle_and_reopens(tmp_path, bridge, monkeypatch):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'timeout')
        client.post('/api/cyberview/scan', json={'count': 1})
        session = wait_session(client)
        assert session['state'] == 'error' and 'turn it off and on' in session['error']
        assert not client.get('/api/cyberview/status').json()['session_open']
        monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'ok')
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
    assert sum(line.startswith('serve') for line in bridge.read_text().splitlines()) == 2


def test_stuck_scan_is_retried_after_usb_reset(tmp_path, bridge, monkeypatch):
    resets = []

    async def reset():
        resets.append(1)
        if len(resets) > 1:  # the first reset precedes the stall; the recovery reset clears it
            monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'ok')
        return True

    monkeypatch.setattr(cyberview, 'reset_scanner', reset)
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'timeout')
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 2})
        session = wait_session(client)
        # Before opening, to recover the stall, and before reopening.
        assert len(resets) == 3
        assert session['state'] == 'complete' and session['completed'] == 2, session
        assert len(client.get('/api/cyberview/captures').json()['captures']) == 2


def test_crash_is_an_error_not_a_success(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'crash')
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 2})
        session = wait_session(client)
        assert session['state'] == 'error' and 'stopped unexpectedly' in session['error']
        assert client.get('/api/cyberview/captures').json()['captures'] == []


def test_empty_transfer_is_an_error_not_a_success(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE', 'empty')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 1})
        session = wait_session(client)
        assert session['state'] == 'error'
        assert 'delivered 0 of 1' in session['error']


def test_parallel_start_requests_reserve_one_session(tmp_path, bridge, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def held_vendor_check():
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return False
    monkeypatch.setattr(cyberview, 'vendor_running', held_vendor_check)
    monkeypatch.setenv('FAKE_CVBRIDGE_DELAY', '.15')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, '/api/cyberview/scan', json={'count': 1})
            assert entered.wait(3)
            second = pool.submit(client.post, '/api/cyberview/scan', json={'count': 1})
            try:
                time.sleep(.05)
                assert not second.done()
            finally:
                release.set()
            accepted, refused = first.result(timeout=5), second.result(timeout=5)
        assert accepted.status_code == 200
        assert refused.status_code == 409
        session = wait_session(client)
        assert session['id'] == accepted.json()['id'] and session['state'] == 'complete'
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert len(captures) == 1 and captures[0]['session_id'] == session['id']
        assert session['captures'] == [captures[0]['id']]


def test_cancel_between_frames(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_DELAY', '0.4')
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 6})
        wait_session(client, states=('scanning',))
        assert client.post('/api/cyberview/cancel').status_code == 200
        session = wait_session(client)
        assert session['state'] == 'cancelled' and session['completed'] < 6
        assert client.post('/api/cyberview/cancel').status_code == 409


def test_vendor_open_blocks_scan(tmp_path, bridge, monkeypatch):
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: True)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/cyberview/scan', json={'count': 1})
        assert response.status_code == 409 and 'CyberView is open' in response.json()['detail']
        assert client.post('/api/cyberview/scan', json={'count': 0}).status_code == 422


def test_interrupted_session_is_marked_on_restart(tmp_path, bridge):
    library = tmp_path / 'library'
    app = create_app(library)
    app.state.store.save('cv_sessions', {'id': 'x', 'state': 'scanning', 'count': 2})
    app.state.store.close()
    restarted = create_app(library)
    assert restarted.state.store.get('cv_sessions', 'x')['state'] == 'error'


def test_neutral_adjustments_are_identity_and_match_client_formula():
    samples = np.random.default_rng(1).random((4, 5, 3)).astype(np.float32)
    neutral = cyberview_routes.Adjustments()
    assert np.allclose(cyberview_routes.apply(samples, neutral), samples, atol=1e-6)
    matrix, offset = cyberview_routes.color_matrix(cyberview_routes.Adjustments(exposure=1, contrast=20, saturation=-50, temperature=40))
    # Values computed with colorMatrix() in apps/web/src/cyberscan.tsx for the same settings.
    assert np.allclose(matrix[0], [1.5424, .8582, .0814], atol=1e-3) and offset == pytest.approx(-.1)


def test_negative_conversion_uses_explicit_film_base_and_keeps_input():
    original = np.array([[[.5, .25, .125], [1, 1, 1], [0, 0, 0]]], dtype=np.float32)
    before = original.copy()
    result = cyberview_routes.apply(original, cyberview_routes.Adjustments(invert=True, film_base=[.5, .25, .125]))
    assert np.array_equal(original, before)
    assert np.allclose(result[0, :2], 0)
    assert np.allclose(result[0, 2], 1)
    with pytest.raises(ValueError):
        cyberview_routes.Adjustments(invert=True, film_base=[0, 1, 1])
