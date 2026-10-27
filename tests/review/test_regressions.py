"""Independent review regressions for persistence and workflow invariants."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from services.api import developing
from services.api.main import create_app


def prepared(client):
    assert client.post('/api/auth/local').status_code == 200
    assert client.post('/api/scanner/connect').status_code == 200
    roll = client.post('/api/rolls', json={'stock': 'Review fixture'}).json()
    assert client.post(f'/api/rolls/{roll["id"]}/ready').status_code == 200
    return roll


def start(client, roll, **options):
    response = client.post('/api/scans', json={
        'roll_id': roll['id'], 'frame_count': 1, 'speed': 'fast', **options})
    assert response.status_code == 200, response.text
    return response.json()


def finished(app, session):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        item = app.state.store.get('scans', session['id'])
        if item['status'] in ('complete', 'error', 'cancelled', 'interrupted'):
            return item
        time.sleep(.01)
    raise AssertionError(item)


def test_missing_original_uses_existing_integrity_error_path(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        roll = prepared(client)
        assert finished(app, start(client, roll))['status'] == 'complete'
        frame = app.state.store.all('frames')[0]
        app.state.store.path(frame['original_path']).unlink()
        assert client.post(f'/api/rolls/{roll["id"]}/archive').status_code == 409
        assert client.get(f'/api/frames/{frame["id"]}/export').status_code == 409


def test_disconnect_snapshot_uses_actual_backend_state(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        roll = prepared(client)
        assert finished(app, start(client, roll, fault='disconnect', fault_frame=1))['status'] == 'error'
        scanner = client.get('/api/state').json()['scanner']
        assert scanner['connected'] is False
        assert scanner['status'] == 'disconnected'


def test_recovery_cannot_scan_roll_in_active_development(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        roll = prepared(client)
        session = start(client, roll, fault='jam', fault_frame=1)
        assert finished(app, session)['status'] == 'error'
        response = client.post('/api/development', json={'roll_id': roll['id'], 'acknowledged': True})
        assert response.status_code == 200
        assert client.post(f'/api/scans/{session["id"]}/recover').status_code == 409


def test_recovery_reconciles_last_frame_committed_before_progress(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        roll = prepared(client)
        session = finished(app, start(client, roll))
        assert session['status'] == 'complete'
        # This is the durable state if the process stops between committing a
        # frame and committing the associated session progress.
        session.update(status='interrupted', completed_frames=0, completed_at=None)
        app.state.store.save('scans', session)
        persisted_roll = app.state.store.get('rolls', roll['id'])
        persisted_roll['status'] = 'scanning'
        app.state.store.save('rolls', persisted_roll)
        assert client.post(f'/api/scans/{session["id"]}/recover').status_code == 200
        recovered = finished(app, session)
        assert recovered['status'] == 'complete'
        assert recovered['completed_frames'] == 1
        assert len(app.state.store.all('frames')) == 1


def test_clock_guard_requires_review_after_both_clock_jump_directions(monkeypatch):
    wall = [100.0]
    monotonic = [100.0]
    monkeypatch.setattr(developing, 'time', SimpleNamespace(
        time=lambda: wall[0], monotonic=lambda: monotonic[0]))
    for jump in (-3, 3600):
        session = developing.create_session('review', developing.DEMO_RECIPE, 20)
        guard = developing.ClockGuard()
        guard.check(session)
        monotonic[0] += 6
        wall[0] += 6
        guard.check(session)
        monotonic[0] += 1
        wall[0] += 1 + jump
        result = guard.check(session)
        assert result['status'] == 'interrupted'
        assert result['events'][-1]['type'] == 'clock_discontinuity'


def test_websocket_rejects_missing_auth_and_foreign_origin(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        with pytest.raises(WebSocketDisconnect) as missing:
            with client.websocket_connect('/api/events', headers={'Origin': 'http://testserver'}):
                pass
        assert missing.value.code == 1008
        prepared(client)
        with pytest.raises(WebSocketDisconnect) as foreign:
            with client.websocket_connect('/api/events', headers={'Origin': 'https://evil.example'}):
                pass
        assert foreign.value.code == 1008


def test_shutdown_interrupts_worker_and_restart_recovers_existing_frames(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        roll = prepared(client)
        session = start(client, roll, frame_count=8)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            prior = app.state.store.all('frames')
            if prior:
                break
            time.sleep(.01)
        assert prior
        assert not app.state.runtime['task'].done()
    restarted = create_app(tmp_path)
    with TestClient(restarted) as client:
        assert client.post('/api/auth/local').status_code == 200
        assert restarted.state.store.get('scans', session['id'])['status'] == 'interrupted'
        assert client.post(f'/api/scans/{session["id"]}/recover').status_code == 200
        assert finished(restarted, session)['status'] == 'complete'
        recovered = restarted.state.store.all('frames')
        assert len(recovered) == len({f['index'] for f in recovered}) == 8
        assert {(f['id'], f['sha256']) for f in prior}.issubset(
            {(f['id'], f['sha256']) for f in recovered})
