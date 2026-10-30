"""Known review findings from 9b65274..eb842b6; isolated synthetic libraries only.

Strict xfails keep known defects visible without breaking the ordinary suite.
Remove each marker when its production fix is made.
"""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from services.api.main import create_app
from services.scanner_host.backend import SimulatedScannerBackend


def new_ready_roll(client):
    roll = client.post('/api/rolls', json={'stock': 'Review fixture'}).json()
    assert client.post(f'/api/rolls/{roll["id"]}/ready').status_code == 200
    return roll


def finish(app, session):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = app.state.store.get('scans', session['id'])
        if result['status'] in ('complete', 'error', 'cancelled'):
            assert result['status'] == 'complete', result
            return result
        time.sleep(.01)
    raise AssertionError('Synthetic scan did not finish')


@pytest.mark.xfail(strict=True, reason='Selected-frame scans leave sparse indexes; import reuses len(frames)+1 and fails with a unique-index collision')
def test_import_after_selected_frame_scan_uses_unused_index(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post('/api/auth/local').status_code == 200
        assert client.post('/api/scanner/connect').status_code == 200
        roll = new_ready_roll(client)
        session = client.post('/api/scans', json={
            'roll_id': roll['id'], 'frame_count': 3, 'frames': [2], 'speed': 'fast'}).json()
        finish(app, session)
        stream = BytesIO()
        Image.new('RGB', (8, 8), 'orange').save(stream, 'PNG')
        imported = client.post(f'/api/rolls/{roll["id"]}/import', json={
            'data_base64': base64.b64encode(stream.getvalue()).decode()})
        assert imported.status_code == 200, imported.text
        assert imported.json()['index'] == 3


@pytest.mark.xfail(strict=True, reason='Prescan task keeps stale scan ownership; development can start and prescan overwrites roll status')
def test_prescan_owns_roll_until_its_result_is_saved(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = SimulatedScannerBackend.prescan

    async def held_prescan(backend):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.005)
        return await original(backend)

    with TestClient(app) as client:
        assert client.post('/api/auth/local').status_code == 200
        assert client.post('/api/scanner/connect').status_code == 200
        first = new_ready_roll(client)
        session = client.post('/api/scans', json={
            'roll_id': first['id'], 'frame_count': 1, 'speed': 'fast'}).json()
        finish(app, session)
        second = new_ready_roll(client)
        monkeypatch.setattr(SimulatedScannerBackend, 'prescan', held_prescan)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.post, f'/api/rolls/{second["id"]}/prescan', json={'frame_count': 2})
            try:
                assert entered.wait(2), 'Prescan did not enter the controlled gate'
                development = client.post('/api/development', json={
                    'roll_id': second['id'], 'acknowledged': True})
            finally:
                release.set()
                assert pending.result(timeout=5).status_code == 200
        assert development.status_code == 409, development.text
