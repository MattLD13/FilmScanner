import base64
from io import BytesIO
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from services.api.main import create_app


def login(client):
    assert client.post('/api/auth/local').status_code == 200


def new_roll(client, **fields):
    response = client.post('/api/rolls', json={'stock': 'Test HP5', 'camera': 'Nikon FM2', 'date': '2026-10-27', **fields})
    assert response.status_code == 200, response.text
    return response.json()


def ready(client, roll):
    assert client.post(f'/api/rolls/{roll["id"]}/ready').status_code == 200


def scan(client, roll, **settings):
    assert client.post('/api/scanner/connect').status_code == 200
    response = client.post('/api/scans', json={'roll_id': roll['id'], 'speed': 'fast', **settings})
    assert response.status_code == 200, response.text
    return response.json()


def wait_scan(client, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get('/api/state').json()
        if state['scan']['status'] in ('complete', 'error', 'cancelled', 'interrupted'):
            return state
        time.sleep(.03)
    raise AssertionError(f'Scan did not finish: {state["scan"]}')


def test_complete_develop_scan_edit_archive_restart(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/state').status_code == 401
        assert client.post('/api/auth/local', headers={'Origin': 'https://evil.example'}).status_code == 403
        login(client)
        roll = new_roll(client, film_type='bw_negative')
        assert client.post('/api/development', json={'roll_id': roll['id']}).status_code == 422
        result = client.post('/api/development', json={'roll_id': roll['id'], 'acknowledged': True, 'temperature': 20})
        assert result.status_code == 200
        session_id = result.json()['id']
        assert client.post(f'/api/development/{session_id}/transition').status_code == 409
        for _ in range(3):
            session = app.state.store.get('development', session_id)
            session['step_started_at'] -= 20_000
            app.state.store.save('development', session)
            assert client.get('/api/state').json()['development'][0]['status'] == 'awaiting_user_transition'
            response = client.post(f'/api/development/{session_id}/transition')
            assert response.status_code == 200, response.text
        assert response.json()['status'] == 'completed'
        scan(client, roll, frame_count=36)
        state = wait_scan(client)
        assert state['scan']['status'] == 'complete', state['scan']
        frames = state['frames']
        assert len(frames) == 36 and sorted(f['index'] for f in frames) == list(range(1, 37))
        assert len({f['id'] for f in frames}) == 36
        original_hash = frames[0]['sha256']
        original_bytes = app.state.store.path(frames[0]['original_path']).read_bytes()
        edited = client.post(f'/api/frames/{frames[0]["id"]}/edit', json={'exposure': .5, 'contrast': 1.2, 'rotation': 90, 'invert': True})
        assert edited.status_code == 200, edited.text
        assert app.state.store.path(frames[0]['original_path']).read_bytes() == original_bytes
        assert edited.json()['sha256'] == original_hash
        for format in ('jpeg', 'tiff', 'original'):
            response = client.get(f'/api/frames/{frames[0]["id"]}/export?format={format}')
            assert response.status_code == 200
            with Image.open(BytesIO(response.content)) as image:
                assert image.width > 0
                if format != 'original':
                    assert image.info.get('icc_profile')
        assert client.get(f'/api/rolls/{roll["id"]}/contact-sheet').status_code == 200
        assert client.post(f'/api/rolls/{roll["id"]}/archive').json()['status'] == 'archived'
        assert list((tmp_path / 'backups').glob('v1-*.sqlite'))
    with TestClient(create_app(tmp_path)) as restarted:
        login(restarted)
        state = restarted.get('/api/state').json()
        assert len(state['frames']) == 36
        assert state['rolls'][0]['status'] == 'archived'
        assert state['development'][0]['status'] == 'completed'
        assert state['frames'][0]['sha256'] == original_hash


def test_jam17_recovery_preserves_first16(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        roll = new_roll(client)
        ready(client, roll)
        session = scan(client, roll, frame_count=36, fault='jam', fault_frame=17)
        failed = wait_scan(client)
        assert failed['scan']['status'] == 'error'
        assert len(failed['frames']) == 16
        before = {f['index']: (f['id'], f['sha256']) for f in failed['frames']}
        assert client.post(f'/api/rolls/{roll["id"]}/archive').status_code == 409
        assert client.post(f'/api/scans/{session["id"]}/recover').status_code == 200
        recovered = wait_scan(client)
        assert recovered['scan']['status'] == 'complete', recovered['scan']
        assert len(recovered['frames']) == 36
        assert all((f['id'], f['sha256']) == before[f['index']] for f in recovered['frames'] if f['index'] <= 16)


def test_cancel_serial_gate_and_recover(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        roll = new_roll(client)
        ready(client, roll)
        session = scan(client, roll, frame_count=3, speed='realtime')
        assert client.post('/api/scans', json={'roll_id': roll['id']}).status_code == 409
        assert client.post(f'/api/scans/{session["id"]}/cancel').status_code == 200
        assert wait_scan(client)['scan']['status'] == 'cancelled'
        item = app.state.store.get('scans', session['id'])
        item['speed'] = 'fast'
        app.state.store.save('scans', item)
        assert client.post(f'/api/scans/{session["id"]}/recover').status_code == 200
        assert wait_scan(client)['scan']['status'] == 'complete'


def test_import_auth_media_and_corruption(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        roll = new_roll(client, format='120')
        image = Image.new('RGB', (24, 16), '#944b2c')
        encoded = BytesIO()
        image.save(encoded, 'PNG')
        response = client.post(f'/api/rolls/{roll["id"]}/import', json={'data_base64': base64.b64encode(encoded.getvalue()).decode()})
        assert response.status_code == 200, response.text
        frame = response.json()
        assert frame['synthetic'] is False
        assert client.get('/media/' + frame['preview_path']).status_code == 200
        assert client.get('/media/frame.sqlite').status_code == 404
        assert client.get('/media/' + frame['original_path']).status_code == 404
        app.state.store.path(frame['original_path']).write_bytes(b'corrupt')
        assert client.post(f'/api/rolls/{roll["id"]}/archive').status_code == 409
        assert client.get(f'/api/frames/{frame["id"]}/export').status_code == 409


def test_authenticated_websocket_snapshot(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        login(client)
        with client.websocket_connect('/api/events', headers={'origin': 'http://testserver'}) as socket:
            message = socket.receive_json()
            assert message['type'] == 'snapshot'
            assert message['data']['scanner']['backend'] == 'simulated'


def test_corrupt_contact_sheet_blocks_archive(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        roll = new_roll(client)
        ready(client, roll)
        scan(client, roll, frame_count=1)
        result = wait_scan(client)
        assert result['scan']['status'] == 'complete'
        stored_roll = app.state.store.get('rolls', roll['id'])
        app.state.store.path(stored_roll['contact_sheet_path']).write_bytes(b'not an image')
        assert client.post(f'/api/rolls/{roll["id"]}/archive').status_code == 409


@pytest.mark.parametrize('fault', ['calibration', 'disconnect', 'timeout', 'alignment', 'write'])
def test_faults_are_not_false_completion(tmp_path, fault):
    with TestClient(create_app(tmp_path)) as client:
        login(client)
        roll = new_roll(client)
        ready(client, roll)
        scan(client, roll, frame_count=2, fault=fault, fault_frame=1)
        state = wait_scan(client)
        assert state['scan']['status'] == 'error'
        assert len(state['frames']) == 0
