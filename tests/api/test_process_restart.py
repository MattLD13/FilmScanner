"""Verify disk durability across actual independent service processes."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx


def test_real_service_process_restart_retains_library_and_timer(tmp_path):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    env = dict(os.environ, FRAME_DATA_DIR=str(tmp_path / 'library'))
    root = Path(__file__).resolve().parents[2]

    def launch():
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'services.api.main:app', '--host', '127.0.0.1', '--port', str(port)],
            cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        client = httpx.Client(base_url=url, timeout=3)
        for _ in range(80):
            try:
                if client.get('/api/health').status_code == 200:
                    assert client.post('/api/auth/local').status_code == 200
                    return process, client
            except httpx.HTTPError:
                time.sleep(.05)
        process.terminate()
        process.wait(timeout=5)
        client.close()
        raise AssertionError('Isolated service did not start')

    def stop(process, client):
        client.close()
        process.terminate()
        process.wait(timeout=5)

    process, client = launch()
    try:
        roll = client.post('/api/rolls', json={'stock': 'Restart durability fixture'}).json()
        assert client.post(f'/api/rolls/{roll["id"]}/ready').status_code == 200
        assert client.post('/api/scanner/connect').status_code == 200
        assert client.post('/api/scans', json={'roll_id': roll['id'], 'frame_count': 1, 'speed': 'fast'}).status_code == 200
        for _ in range(150):
            state = client.get('/api/state').json()
            if state['scan']['status'] == 'complete':
                break
            time.sleep(.02)
        assert state['scan']['status'] == 'complete'
        frame = state['frames'][0]
        export_path = f'/api/frames/{frame["id"]}/export?format=tiff'
        before = client.get(export_path).content
        assert client.post(f'/api/rolls/{roll["id"]}/archive').status_code == 200
        darkroom = client.post('/api/rolls', json={'stock': 'Active water rehearsal'}).json()
        development = client.post('/api/development', json={'roll_id': darkroom['id'], 'acknowledged': True}).json()
    finally:
        stop(process, client)
    time.sleep(.1)
    process, client = launch()
    try:
        after = client.get('/api/state').json()
        assert after['frames'][0]['sha256'] == frame['sha256']
        assert after['rolls'][0]['status'] == 'archived'
        assert after['development'][0]['step_started_at'] == development['step_started_at']
        assert after['development'][0]['remaining_seconds'] < 8
        exported = client.get(export_path)
        assert exported.status_code == 200, exported.text
        assert exported.content == before, 'Export bytes must be identical across independent processes'
    finally:
        stop(process, client)
