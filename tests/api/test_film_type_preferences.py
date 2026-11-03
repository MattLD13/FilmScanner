"""Film material selects new processing defaults without moving the scanner."""
import hashlib
import os
from io import BytesIO

import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient

from services.api.main import create_app
from services.scanner_host import workspace
from test_cyberview import bridge, wait_session
from test_workflow import login


def test_film_selection_persists_without_opening_driver(tmp_path, bridge):
    root = tmp_path / 'library'
    with TestClient(create_app(root)) as client:
        assert client.put('/api/cyberview/film-type', json={'film_type': 'bw_negative'}).status_code == 401
        login(client)
        for value in ('bw_negative', 'positive', 'color_negative', 'bw_negative'):
            response = client.put('/api/cyberview/film-type', json={'film_type': value})
            assert response.status_code == 200
            assert response.json()['film_type'] == value
            assert response.json()['settings']['film'] == ('positive' if value == 'positive' else 'negative')
        assert not bridge.exists(), 'Changing film type must not initialize the driver'
        assert client.put('/api/cyberview/film-type', json={'film_type': 'invented'}).status_code == 422
    with TestClient(create_app(root)) as client:
        login(client)
        assert client.get('/api/cyberview/workspace').json()['film_type'] == 'bw_negative'


def test_bw_acquisition_keeps_tones_and_existing_edits(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', os.environ['FRAME_CVBRIDGE'])
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        existing = client.get('/api/cyberview/captures').json()['captures'][0]
        client.put('/api/cyberview/film-type', json={'film_type': 'bw_negative'}).raise_for_status()
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        captures = client.get('/api/cyberview/captures').json()['captures']
        assert captures[0]['adjustments'] == existing['adjustments']
        bw = captures[-1]
        assert bw['film_type'] == 'bw_negative'
        assert bw['adjustments']['saturation'] == -100
        assert not bw['adjustments']['monochrome'], 'Photographic B&W must not threshold tones'
        result = client.get(f"/api/cyberview/captures/{bw['id']}/export/tiff")
        samples = tifffile.imread(BytesIO(result.content))
        assert np.array_equal(samples[..., 0], samples[..., 1])
        assert np.array_equal(samples[..., 1], samples[..., 2])
        assert len(np.unique(samples)) > 16
        assert hashlib.sha256(app.state.store.path(existing['original_path']).read_bytes()).hexdigest() == existing['sha256']


def test_slide_selection_does_not_promote_unverified_hardware(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', os.environ['FRAME_CVBRIDGE'])
    monkeypatch.setattr(workspace, 'validation', lambda: {})
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        result = client.put('/api/cyberview/film-type', json={'film_type': 'positive'}).json()
        assert result['film_type'] == 'positive'
        assert not result['capabilities']['actions']['scan']['available']
        assert client.post('/api/cyberview/scan', json={'count': 1}).status_code == 409
        assert not bridge.exists()


def test_verified_slide_fixture_creates_positive_edit_without_inversion(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', os.environ['FRAME_CVBRIDGE'])
    # Synthetic-only capability; this does not promote the physical scanner.
    positive = workspace.ScanOptions(film='positive').model_dump()
    monkeypatch.setattr(workspace, 'validation', lambda: {'configurations': [positive]})
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.put('/api/cyberview/film-type', json={'film_type': 'positive'}).raise_for_status()
        client.post('/api/cyberview/scan', json={'count': 1}).raise_for_status()
        assert wait_session(client)['state'] == 'complete'
        capture, = client.get('/api/cyberview/captures').json()['captures']
        assert capture['film_type'] == 'positive'
        assert not capture['adjustments']['invert']
        assert capture['adjustments']['saturation'] == 0
        assert 'settings 1800 16 rgb positive' in bridge.read_text()


def test_film_selection_is_blocked_during_active_acquisition(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_DELAY', '.8')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        client.post('/api/cyberview/scan', json={'count': 1})
        response = client.put('/api/cyberview/film-type', json={'film_type': 'bw_negative'})
        assert response.status_code == 409
        assert client.get('/api/cyberview/workspace').json()['film_type'] == 'color_negative'
        assert wait_session(client)['state'] == 'complete'
