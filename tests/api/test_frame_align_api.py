"""35 mm auto-align through the API, against the fake bridge's synthetic film strip."""
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from services.api.main import create_app
from services.scanner_host import cyberview, workspace
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
        capture = next(c for c in client.get('/api/cyberview/captures').json()['captures'] if c['purpose'] == 'stitched')
        assert len(capture['derived']['sources']) == 3
        # Learned from the probe: 600 dpi / 25.4 / 1.37 px per step = 17.2 steps per mm.
        assert capture['derived']['steps_per_mm'] == pytest.approx(600 / 25.4 / 1.37, rel=.05)
        assert capture['alignment']['confidence'] == 'frame_found' and capture['alignment']['exact']
        assert capture['alignment']['crop_mm'] == pytest.approx([36, 24], abs=.05)
        assert capture['width'] > round(36.5 / 25.4 * 600)          # longer than any single scan
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
