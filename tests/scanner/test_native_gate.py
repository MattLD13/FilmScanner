"""Native integration guards and passive installation inspection; no hardware."""
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from services.api.main import create_app
from services.scanner_host import cyberview, vendor_evidence
from services.scanner_host.backend import ScannerError
from services.scanner_host.native import NativeAflBridge


FAKE = Path(__file__).with_name('fake_cvbridge.py')


@pytest.fixture(autouse=True)
def isolate_device_validation(monkeypatch):
    from services.scanner_host import workspace
    monkeypatch.setattr(workspace,'validation',lambda:{})


def test_native_gate_does_not_start_any_process(tmp_path, monkeypatch):
    monkeypatch.delenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', raising=False)
    async def no_process(*args, **kwargs):
        pytest.fail('A disabled native backend must not start a process')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_process)
    bridge = NativeAflBridge(exe=FAKE)
    with pytest.raises(ScannerError, match='approval'):
        asyncio.run(bridge.scan(tmp_path / 'denied.tif', 1, lambda event: None))
    assert not list(tmp_path.iterdir())


def test_native_transports_and_batches_never_open_driver(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', '1')
    bridge = NativeAflBridge(exe=FAKE)
    with pytest.raises(ScannerError, match='only the current frame'):
        asyncio.run(bridge.scan(tmp_path / 'batch.tif', 2, lambda event: None))
    with pytest.raises(ScannerError, match='not been validated'):
        asyncio.run(bridge.film('next'))
    assert bridge.process is None


def test_passive_inspection_does_not_load_or_open_driver(tmp_path, monkeypatch):
    (tmp_path / 'SCAN08.dll').write_bytes(b'Unknown vendor module')
    monkeypatch.setenv('WINDIR', str(tmp_path / 'no-windows-here'))
    def no_device(*args, **kwargs):
        pytest.fail('Passive installation inspection must not query or initialize a device')
    monkeypatch.setattr(cyberview, 'scanner_present', no_device)
    monkeypatch.setattr(cyberview, '_quiet_run', no_device)
    inspected = vendor_evidence.inspect_installation(tmp_path)
    assert inspected['device_io_performed'] is False
    assert inspected['native_module_recognized'] is False
    assert inspected['files'][-1]['sha256']
    assert inspected['files'][-1]['version'] is None
    with TestClient(create_app(tmp_path / 'library')) as client:
        assert client.get('/api/cyberview/diagnostics').status_code == 401
        client.post('/api/auth/local')
        result = client.get('/api/cyberview/diagnostics')
        assert result.status_code == 200
        assert result.json()['device_io_performed'] is False


def test_native_api_rejects_transport_and_records_truthful_originals(tmp_path, monkeypatch):
    from services.scanner_host import workspace
    monkeypatch.setattr(workspace, 'validation', lambda: {})
    monkeypatch.setenv('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', '1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', str(FAKE))
    monkeypatch.setattr(cyberview, 'scanner_present', lambda: True)
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: False)
    monkeypatch.setattr(cyberview, 'reset_available', lambda: False)
    with TestClient(create_app(tmp_path / 'library')) as client:
        client.post('/api/auth/local')
        status = client.get('/api/cyberview/status').json()
        assert status['backend'] == 'afl-native-experimental'
        assert status['max_count'] == 1 and not status['supports_next']
        assert status['image_kind'] == 'vendor-calibrated-transmission'
        assert client.post('/api/cyberview/film', json={'action': 'next'}).status_code == 409
        assert client.post('/api/cyberview/scan', json={'count': 2}).status_code == 422
        assert client.get('/api/cyberview/captures').json()['captures'] == []


def test_backend_choice_persists_without_initializing_hardware(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE', str(FAKE))
    monkeypatch.setenv('FRAME_CVBRIDGE', str(FAKE))
    monkeypatch.delenv('FRAME_SCANNER_BACKEND', raising=False)
    monkeypatch.delenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', raising=False)
    monkeypatch.setattr(vendor_evidence, 'inspect_installation', lambda: {'native_module_recognized': True})
    monkeypatch.setattr(cyberview, 'scanner_present', lambda: True)
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: False)
    monkeypatch.setattr(cyberview, 'reset_available', lambda: False)
    async def no_start(*args):
        pytest.fail('Selecting an interface must not initialize a scanner')
    monkeypatch.setattr(NativeAflBridge, '_start', no_start)
    root = tmp_path / 'library'
    with TestClient(create_app(root)) as client:
        body = {'backend': 'afl-native-experimental', 'acknowledged': True}
        assert client.post('/api/cyberview/backend', json=body).status_code == 401
        client.post('/api/auth/local')
        assert client.post('/api/cyberview/backend', json={'backend': 'afl-native-experimental'}).status_code == 422
        result = client.post('/api/cyberview/backend', json=body)
        assert result.status_code == 200, result.text
        assert result.json()['backend'] == 'afl-native-experimental'
        assert result.json()['experimental_enabled'] and not result.json()['session_open']
    with TestClient(create_app(root)) as client:
        client.post('/api/auth/local')
        assert client.get('/api/cyberview/status').json()['backend'] == 'afl-native-experimental'
        assert client.post('/api/cyberview/backend', json={'backend': 'cyberview-twain'}).status_code == 200
        assert client.get('/api/cyberview/status').json()['backend'] == 'cyberview-twain'


def test_stop_during_startup_prevents_driver_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(cyberview, 'vendor_running', lambda: False)
    async def scenario():
        bridge = cyberview.CyberViewBridge(exe=FAKE)
        entered, release = asyncio.Event(), asyncio.Event()
        async def prepare():
            entered.set()
            await release.wait()
        bridge._prepare_device = prepare
        task = asyncio.create_task(bridge.scan(tmp_path / 'never.tif', 1, lambda event: None))
        await entered.wait()
        await bridge.cancel()
        release.set()
        assert await task == []
        assert bridge.process is None
    asyncio.run(scenario())
    assert not list(tmp_path.iterdir())


def test_native_timeout_reserves_session_without_killing_driver(monkeypatch):
    from types import SimpleNamespace
    async def scenario():
        bridge = NativeAflBridge(exe=FAKE, first_image_timeout=.01)
        bridge.process = SimpleNamespace(returncode=None)
        sent = []
        async def send(line):
            sent.append(line)
        bridge._send = send
        with pytest.raises(ScannerError, match='stays reserved'):
            await bridge._next()
        assert sent == ['cancel']
        assert bridge.busy and bridge.quarantined
        with pytest.raises(ScannerError, match='still handling'):
            await bridge.scan(Path('unused.tif'), 1, lambda event: None)
        with pytest.raises(ScannerError, match='remains reserved'):
            await bridge.release()
        assert sent == ['cancel']
        class Stream:
            def __aiter__(self):
                return self.values()
            async def values(self):
                yield b'{"event":"scan_done","images":0,"result":-1}\n'
                yield b'{"event":"ready"}\n'
        bridge.events.put_nowait({'event': 'stale-progress'})
        await bridge._read(SimpleNamespace(stdout=Stream()))
        assert not bridge.quarantined
        assert (await bridge.events.get())['event'] == 'ready'
        assert await bridge.events.get() is None
    asyncio.run(scenario())


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows scanner ownership mutex')
def test_reset_does_not_touch_an_owned_scanner(monkeypatch):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    held = kernel.CreateMutexW(None, False, r'Local\FRAME_PF1800AFL')
    assert held
    monkeypatch.setattr(cyberview, 'reset_available', lambda: True)
    def no_reset(*args):
        pytest.fail('Another process owns the scanner; reset must not run')
    monkeypatch.setattr(cyberview, '_quiet_run', no_reset)
    try:
        assert asyncio.run(cyberview.reset_scanner()) is False
    finally:
        kernel.CloseHandle(held)
