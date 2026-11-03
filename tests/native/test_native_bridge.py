"""Real x86 host against a synthetic DLL; never loads the genuine vendor driver.

Build once with services/native_bridge/build.ps1 -Fixtures. Tests are skipped on
other platforms or when that optional compiler output is unavailable.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import numpy as np
import pytest
import tifffile

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'services' / 'native_bridge' / 'bin'
EXE = BIN / 'aflbridge.exe'
FIXTURE_EXE = BIN / 'aflbridge-fixture.exe'
DLL = BIN / 'fake-model.dll'
pytestmark = pytest.mark.skipif(
    sys.platform != 'win32' or not all(p.is_file() for p in (EXE, FIXTURE_EXE, DLL)),
    reason='Optional native x86 fixture not built; run services/native_bridge/build.ps1 -Fixtures')


class Fixture:
    def __init__(self, mode='ok', timeout=300, extra=()):
        self.process = subprocess.Popen(
            [str(FIXTURE_EXE), 'serve', '--fixture-dll', str(DLL), '--timeout', str(timeout), *extra],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env={**os.environ, 'FRAME_NATIVE_FIXTURE_MODE': mode})
        self.output = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.output.put(json.loads(line))
            self.output.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def send(self, line):
        self.process.stdin.write(line + '\n')
        self.process.stdin.flush()

    def until(self, event):
        events = []
        while True:
            item = self.output.get(timeout=10)
            assert item is not None, (events, self.process.poll(), self.process.stderr.read())
            events.append(item)
            if item['event'] == event:
                return events

    def close(self):
        if self.process.poll() is None:
            self.send('quit')
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()


@pytest.fixture
def fixture():
    active = []
    def create(mode='ok', timeout=300, extra=()):
        item = Fixture(mode, timeout, extra)
        active.append(item)
        return item
    yield create
    for item in active:
        item.close()


def test_cpu_commands_and_production_gates_do_not_load_vendor():
    for option, event in [('--describe', 'description'), ('--self-test', 'self_test')]:
        result = subprocess.run([str(EXE), option], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        record = json.loads(result.stdout)
        assert record['event'] == event and record['device_io'] is False
        if event == 'description':
            assert record['bits'] == 16 and record['expected_adc_bits'] == 12
            assert record['measured_effective_bits'] is None
            assert 'native_effective_bits' not in record
    result = subprocess.run([str(EXE), 'serve'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 3
    assert json.loads(result.stdout)['code'] == 'experimental_disabled'
    result = subprocess.run([str(EXE), 'serve', '--fixture-dll', str(DLL)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and json.loads(result.stdout)['code'] == 'usage'


def test_process_mutex_blocks_even_explicit_experimental_start():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, r'Local\FRAME_PF1800AFL')
    assert mutex
    try:
        result = subprocess.run([str(EXE), 'serve', '--allow-experimental-device-io'],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 3 and json.loads(result.stdout)['code'] == 'busy'
    finally:
        kernel.CloseHandle(mutex)


def test_native_abi_tiff_bytes_and_persistent_session(tmp_path, fixture):
    native = fixture()
    opened = native.until('ready')
    assert any(e['event'] == 'opened' and e['synthetic'] is True for e in opened)
    for index in range(2):
        path = tmp_path / f'film é 漢字-{index}.tif'
        native.send(f'scan 1 {path}')
        events = native.until('scan_done')
        assert events[-1] == {'event': 'scan_done', 'images': 1, 'result': 1}, events
        assert [e['rows'] for e in events if e['event'] == 'progress'] == [3, 6, 8]
        image = next(e for e in events if e['event'] == 'image')
        assert image['synthetic'] and image['width'] == 7 and image['height'] == 8
        with tifffile.TiffFile(path) as tif:
            values = tif.asarray()
            assert tif.pages[0].tags['BitsPerSample'].value == (16, 16, 16)
            assert tif.pages[0].tags['XResolution'].value == (1800, 1)
        y, x, c = np.indices((8, 7, 3))
        expected = ((y * 100 + x * 7 + c) << 4).astype(np.uint16)
        assert values.dtype == np.uint16 and np.array_equal(values, expected)
        assert not list(tmp_path.glob('*.partial-*'))
        native.until('ready')


@pytest.mark.parametrize('mode', ['bad-remaining', 'bad-size', 'truncated', 'no-image'])
def test_incomplete_or_malformed_callbacks_never_finalize(tmp_path, fixture, mode):
    native = fixture(mode)
    native.until('ready')
    path = tmp_path / 'scan.tif'
    native.send(f'scan 1 {path}')
    events = native.until('scan_done')
    assert events[-1]['images'] == 0 and events[-1]['result'] == 0
    assert any(e['event'] == 'error' and e['code'] == 'native_transfer' for e in events)
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


def test_cancellation_uses_vendor_abort_flag_without_finalizing(tmp_path, fixture):
    native = fixture('slow')
    native.until('ready')
    path = tmp_path / 'cancelled.tif'
    native.send(f'scan 1 {path}')
    native.until('progress')
    native.send('cancel')
    events = native.until('scan_done')
    assert events[-1] == {'event': 'scan_done', 'images': 0, 'result': -1}
    assert any(e['event'] == 'cancelled' for e in events)
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


def test_input_eof_cancels_an_acquisition_and_releases_process(tmp_path, fixture):
    native = fixture('slow')
    native.until('ready')
    path = tmp_path / 'parent-ended.tif'
    native.send(f'scan 1 {path}')
    native.until('progress')
    native.process.stdin.close()
    events = native.until('done')
    assert any(e['event'] == 'cancelled' for e in events)
    assert native.process.wait(timeout=5) == 0
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


def test_full_queue_still_receives_cancellation(tmp_path, fixture):
    native = fixture('slow')
    native.until('ready')
    path = tmp_path / 'queue.tif'
    native.send(f'scan 1 {path}')
    native.until('progress')
    for _ in range(12):
        native.send('unimplemented')
    native.send('cancel')
    events = native.until('scan_done')
    assert events[-1]['result'] == -1
    assert not path.exists()


def test_cancel_queued_with_scan_is_not_erased_before_dispatch(tmp_path, fixture):
    native = fixture('slow')
    native.until('ready')
    for index in range(3):
        path = tmp_path / f'queued-cancel-{index}.tif'
        native.process.stdin.write(f'scan 1 {path}\ncancel\n')
        native.process.stdin.flush()
        events = native.until('scan_done')
        assert events[-1]['result'] == -1 and events[-1]['images'] == 0
        assert not path.exists()
        native.until('ready')


def test_scan_plus_cancel_and_eof_never_finalizes(tmp_path, fixture):
    native = fixture('slow')
    native.until('ready')
    path = tmp_path / 'queued-eof.tif'
    native.process.stdin.write(f'scan 1 {path}\ncancel\n')
    native.process.stdin.flush()
    native.process.stdin.close()
    events = native.until('done')
    assert not any(e['event'] == 'image' for e in events)
    assert native.process.wait(timeout=5) == 0
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


def test_existing_final_and_partial_files_are_preserved(tmp_path, fixture):
    native = fixture()
    native.until('ready')
    existing = tmp_path / 'existing.tif'
    existing.write_bytes(b'previous original')
    path = tmp_path / 'new.tif'
    partial = Path(f'{path}.partial-{native.process.pid}')
    partial.write_bytes(b'earlier interrupted acquisition')
    for target in (existing, path):
        native.send(f'scan 1 {target}')
        events = native.until('scan_done')
        assert events[-1]['images'] == 0 and any(e.get('code') == 'write' for e in events)
        native.until('ready')
    assert existing.read_bytes() == b'previous original'
    assert partial.read_bytes() == b'earlier interrupted acquisition'


def test_wrong_model_cannot_be_opened_as_afl(fixture):
    native = fixture('wrong-model')
    events = native.until('done')
    assert any(e.get('code') == 'native_model' for e in events)
    assert not any(e['event'] in ('opened', 'ready') for e in events)
    assert native.process.wait(timeout=5) == 1


def test_unimplemented_transport_and_scan_counts_are_rejected(fixture):
    native = fixture()
    native.until('ready')
    for command in ('film next', 'film previous', 'scan 2 ignored.tif', 'focus 2'):
        native.send(command)
        events = native.until('ready')
        assert any(e.get('code') in ('unsupported', 'unverified_control') for e in events)
        assert not any(e['event'] in ('enabled', 'image') for e in events)


def test_callback_timeout_is_an_error_not_unrequested_cancellation(tmp_path, fixture):
    native = fixture('timeout', timeout=1)
    native.until('ready')
    path = tmp_path / 'timed-out.tif'
    native.send(f'scan 1 {path}')
    events = native.until('scan_done')
    assert any(e['event'] == 'error' and e['code'] == 'timeout' for e in events)
    assert not any(e['event'] in ('cancelled', 'image') for e in events)
    assert events[-1] == {'event': 'scan_done', 'images': 0, 'result': 0}
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


@pytest.mark.parametrize(('mode', 'code'), [('no-film', 'no_film'), ('status-failure', 'native_status')])
def test_film_status_required_before_creating_output_or_starting_acquisition(tmp_path, fixture, mode, code):
    native = fixture(mode)
    native.until('ready')
    path = tmp_path / 'never-started.tif'
    native.send(f'scan 1 {path}')
    events = native.until('scan_done')
    assert any(e['event'] == 'error' and e['code'] == code for e in events)
    assert not any(e['event'] in ('enabled', 'image_start', 'progress', 'image') for e in events)
    assert events[-1] == {'event': 'scan_done', 'images': 0, 'result': 0}
    assert not path.exists() and not list(tmp_path.glob('*.partial-*'))


@pytest.mark.parametrize('dpi,bits,channel,shape', [(300,8,'rgb',(8,7,3)),(600,8,'gray',(8,7)),(900,16,'gray',(8,7)),(1800,8,'bw',(8,7))])
def test_configured_capture_preserves_format(tmp_path,fixture,dpi,bits,channel,shape):
    native=fixture(extra=['--allow-experimental-settings'])
    native.until('ready')
    native.send(f'settings {dpi} {bits} {channel} negative 0.03 0.003 1.407 0.95 110 100 90')
    events=native.until('ready')
    assert any(e['event']=='configured' for e in events),events
    target=tmp_path/'configured.tif'
    native.send(f'scan 1 {target}')
    events=native.until('scan_done')
    assert events[-1]['result']==1,events
    with tifffile.TiffFile(target) as tif:
        values=tif.asarray()
        assert values.shape==shape
        assert values.dtype==(np.uint16 if bits==16 else np.uint8)
        assert tif.pages[0].tags['XResolution'].value==(dpi,1)
        if channel=='bw':assert len(np.unique(values))>2  # Acquired gray is preserved; thresholding is a recipe.


@pytest.mark.parametrize('dpi,bits,film',[(300,8,'negative'),(1800,16,'negative'),(600,16,'positive')])
def test_vendor_auto_exposure_flag_is_separate_and_reports_only_known_values(tmp_path,fixture,dpi,bits,film):
    native=fixture(extra=['--allow-experimental-settings','--allow-experimental-controls','--controls','auto_exposure'])
    native.until('ready')
    native.send(f'settings {dpi} {bits} rgb {film} 0 0 1.4366666 .95 110 100 90 1')
    configured=native.until('ready')
    assert next(e for e in configured if e['event']=='configured')['auto_exposure'] is True
    native.send(f'scan 1 {tmp_path / "auto.tif"}')
    events=native.until('scan_done')
    assert events[-1]['result']==1,events
    report=next(e for e in events if e['event']=='vendor_auto_exposure')
    assert report['request_flags']==1 and report['requested_exposure']==[110,100,90]
    assert report['request_exposure_after']==[101,123,157]  # fixture-observable mutation only
    assert report['effective_exposure'] is None and report['synthetic'] is True
    assert next(e for e in events if e['event']=='image')['vendor_auto_exposure'] is True
    assert next(e for e in events if e['event']=='frame_position')['position']==1
    native.until('ready')
    # Omitting the optional field restores legacy false, rather than retaining true.
    native.send('settings 1800 16 rgb negative .03 .003 1.407 .95 100 100 100')
    events=native.until('ready')
    assert next(e for e in events if e['event']=='configured')['auto_exposure'] is False


def test_auto_exposure_requires_control_gate_and_rejects_trailing_garbage(tmp_path,fixture):
    native=fixture(extra=['--allow-experimental-settings']);native.until('ready')
    native.send('settings 1800 16 rgb negative .03 .003 1.407 .95 100 100 100 1')
    events=native.until('ready')
    assert any(e.get('code')=='unverified_auto_exposure' for e in events)
    for tail in ('2','junk','1 junk','0 junk'):
        native.send('settings 1800 16 rgb negative .03 .003 1.407 .95 100 100 100 '+tail)
        events=native.until('ready')
        assert any(e['event']=='error' for e in events) and not any(e['event']=='configured' for e in events)
    native.send(f'scan 1 {tmp_path / "unchanged.tif"}')
    events=native.until('scan_done')
    assert events[-1]['result']==1
    assert not any(e['event']=='vendor_auto_exposure' for e in events)


@pytest.mark.parametrize('auto,success',[(True,True),(False,False)])
def test_legacy_auto_preview_callback_tail_is_ignored_only_in_exact_reviewed_branch(tmp_path,fixture,auto,success):
    native=fixture(mode='legacy-auto-preview',extra=['--allow-experimental-settings','--allow-experimental-controls','--controls','auto_exposure'])
    native.until('ready')
    native.send(f'settings 300 8 rgb negative 0 0 1.4366666 .95 100 100 100 {1 if auto else 0}')
    native.until('ready')
    native.send(f'scan 1 {tmp_path / "legacy.tif"}')
    events=native.until('scan_done')
    assert (events[-1]['result']==1)==success,events
    assert (tmp_path/'legacy.tif').exists()==success


def test_vendor_realign_is_gated_initialized_and_checks_frame_counter(fixture,tmp_path):
    native=fixture(extra=['--allow-experimental-controls','--controls','realign'])
    native.until('ready')
    native.send('film realign');events=native.until('ready')
    assert any(e.get('code')=='prescan_required' for e in events)
    native.send(f'scan 1 {tmp_path / "initialized.tif"}');events=native.until('ready')
    assert next(e for e in events if e['event']=='frame_position')['position']==1
    native.send('film realign');events=native.until('ready')
    realign=next(e for e in events if e['event']=='realignment')
    assert realign['position']==1 and realign['optical_verification_required'] is True
    assert next(e for e in events if e['event']=='command_done')['position']==1


def test_realign_that_changes_frame_never_reports_success(fixture,tmp_path):
    native=fixture(mode='realign-slips',extra=['--allow-experimental-controls','--controls','realign'])
    native.until('ready');native.send(f'scan 1 {tmp_path / "initialized.tif"}');native.until('ready')
    native.send('film realign');events=native.until('ready')
    assert any(e.get('code')=='position' for e in events)
    assert not any(e['event']=='command_done' for e in events)


def test_bad_settings_do_not_replace_current_configuration(tmp_path,fixture):
    native=fixture(extra=['--allow-experimental-settings']);native.until('ready')
    for line in ['settings 9000 16 rgb negative 0 0 1 .9 100 100 100','settings 300 8 rgb negative nan 0 1 .9 100 100 100','settings 300 8 rgb negative 0 0 1 .9 100 999 100','settings 300 16 bw negative 0 0 1 .9 100 100 100']:
        native.send(line);events=native.until('ready')
        assert any(e['event']=='error' for e in events),events
    native.send(f'scan 1 {tmp_path / "default.tif"}');events=native.until('scan_done')
    assert next(e for e in events if e['event']=='image')['dpi']==1800


def test_zero_manual_focus_is_a_valid_stored_position(fixture,tmp_path):
    native=fixture(extra=['--allow-experimental-controls','--controls','focus'])
    native.until('ready')
    native.send('focus 0');events=native.until('ready')
    done=next(e for e in events if e['event']=='command_done')
    assert done['focus']==0 and done['position'] is None


def test_workspace_normalizes_old_evidence_and_requires_vendor_exposure_gate(monkeypatch):
    from services.scanner_host import workspace
    old=dict(workspace.DEFAULT_OPTIONS)
    old.pop('auto_exposure')
    monkeypatch.setattr(workspace,'validation',lambda:{'configurations':[old],'actions':[]})
    assert workspace.validated_options(workspace.DEFAULT_OPTIONS)
    assert not workspace.validated_options(workspace.DEFAULT_OPTIONS | {'auto_exposure':True})
    monkeypatch.setattr(workspace,'validation',lambda:{'configurations':[old],'actions':['auto_exposure']})
    assert workspace.validated_options(workspace.DEFAULT_OPTIONS | {'auto_exposure':True})
    assert not workspace.validated_options(workspace.DEFAULT_OPTIONS | {'auto_exposure':True,'dpi':900})
    assert workspace.border_preview_options(workspace.DEFAULT_OPTIONS | {'auto_exposure':True})['auto_exposure'] is False


@pytest.mark.parametrize('limits',[[3,2],[-1,3],[2,201],[2],['2',3],[False,3],None,[2.0,3]])
def test_invalid_recorded_focus_range_rejects_before_io(monkeypatch,limits):
    import asyncio
    from services.scanner_host import workspace
    from services.scanner_host.native import NativeAflBridge
    from services.scanner_host.backend import ScannerError
    monkeypatch.setattr(workspace,'validation',lambda:{'actions':['focus'],'focus_range':limits})
    bridge=NativeAflBridge(exe=Path('unused.py'))
    async def forbidden():
        pytest.fail('Invalid focus evidence must not start a scanner process')
    monkeypatch.setattr(bridge,'_start',forbidden)
    with pytest.raises(ScannerError,match='range is invalid'):
        asyncio.run(bridge.control('focus',value=2))
    capabilities=workspace.capabilities(bridge,workspace.DEFAULT_OPTIONS)
    assert capabilities['focus_range']==[] and not capabilities['actions']['focus']['available']
    assert bridge.process is None


def test_recorded_focus_range_accepts_only_tested_steps(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from services.scanner_host import workspace,cyberview
    from services.scanner_host.native import NativeAflBridge
    from services.scanner_host.backend import ScannerError
    monkeypatch.setattr(workspace,'validation',lambda:{'actions':['focus'],'focus_range':[2,3]})
    sent=[]
    async def exchange(self,line,*args,**kwargs):
        sent.append(line)
        return [],None
    monkeypatch.setattr(cyberview.CyberViewBridge,'_exchange',exchange)
    async def scenario():
        bridge=NativeAflBridge(exe=Path('unused.py'))
        bridge.process=SimpleNamespace(returncode=None)
        for target in (2,3):
            await bridge.control('focus',value=target)
        for target in (1,4,200,2.0,True,None):
            with pytest.raises(ScannerError,match='validated steps'):
                await bridge.control('focus',value=target)
        assert workspace.capabilities(bridge,workspace.DEFAULT_OPTIONS)['focus_range']==[2,3]
    asyncio.run(scenario())
    assert sent==['focus 2','focus 3']


def test_focus_range_without_new_evidence_retains_legacy_bounds(monkeypatch):
    from services.scanner_host import workspace
    monkeypatch.setattr(workspace,'validation',lambda:{})
    assert workspace.focus_limits()==[0,200]


def test_explicit_control_allowlist_and_position_verification(fixture,tmp_path):
    native=fixture(extra=['--allow-experimental-controls','--controls','next,previous,goto,eject_forward,autofocus,focus,calibrate']);native.until('ready')
    native.send('film next');events=native.until('ready')
    assert any(e.get('code')=='prescan_required' for e in events)
    native.send(f'scan 1 {tmp_path / "initialize.tif"}');native.until('ready')
    for line,name in [('film next','next'),('film previous','previous'),('film goto 3','goto'),('focus auto','autofocus'),('focus 12','focus'),('calibrate','calibrate'),('film eject_forward','eject_forward')]:
        native.send(line);events=native.until('ready')
        assert any(e['event']=='command_done' and e['name']==name for e in events),events
        done=next(e for e in events if e['event']=='command_done')
        if name in ('next','previous','goto'):
            assert done['position']=={'next':2,'previous':1,'goto':3}[name]
        else:
            assert done['position'] is None, 'Non-frame controls must not invent frame 1'
    native.send('film next');events=native.until('ready')
    assert any(e.get('code') in ('no_film','prescan_required') for e in events),events
    native.send('film eject_backward');events=native.until('ready')
    assert any(e.get('code')=='unverified_control' for e in events)


def test_backward_eject_runs_only_when_explicitly_allowlisted(fixture,tmp_path):
    native=fixture(extra=['--allow-experimental-controls','--controls','eject_backward']);native.until('ready')
    native.send(f'scan 1 {tmp_path / "loaded.tif"}');native.until('ready')
    native.send('film eject_backward');events=native.until('ready')
    assert any(e['event']=='command_done' and e['name']=='eject_backward' for e in events),events


def test_nudge_is_allowlisted_bounded_and_must_stay_on_the_frame(fixture, tmp_path):
    native = fixture(extra=['--allow-experimental-controls', '--controls', 'nudge']); native.until('ready')
    native.send('film nudge back 20'); events = native.until('ready')
    assert any(e.get('code') == 'prescan_required' for e in events), events
    native.send(f'scan 1 {tmp_path / "first.tif"}'); native.until('ready')
    native.send('film nudge back 20'); events = native.until('ready')
    assert any(e['event'] == 'nudge' and e['direction'] == 'back' and e['steps'] == 20 for e in events), events
    assert any(e['event'] == 'command_done' and e['name'] == 'nudge' for e in events)
    for bad in ('film nudge back 0', 'film nudge back 301', 'film nudge sideways 5'):
        native.send(bad); events = native.until('ready')
        assert any(e['event'] == 'error' for e in events) and not any(e['event'] == 'nudge' for e in events), (bad, events)


def test_nudge_that_slips_a_frame_is_an_error(fixture, tmp_path):
    native = fixture(mode='nudge-slips', extra=['--allow-experimental-controls', '--controls', 'nudge']); native.until('ready')
    native.send(f'scan 1 {tmp_path / "first.tif"}'); native.until('ready')
    native.send('film nudge forward 40'); events = native.until('ready')
    assert any(e.get('code') == 'position' for e in events), events


def test_nudge_needs_the_allowlist(fixture, tmp_path):
    native = fixture(extra=['--allow-experimental-controls', '--controls', 'next']); native.until('ready')
    native.send(f'scan 1 {tmp_path / "first.tif"}'); native.until('ready')
    native.send('film nudge back 20'); events = native.until('ready')
    assert any(e.get('code') == 'unverified_control' for e in events), events


def test_usb_trace_logs_vendor_kernel_calls_without_changing_them(tmp_path, fixture):
    # fake-fvc.dll stands in for FVC.dll: its calls go to the NUL device, never USB.
    trace = tmp_path / 'usb.jsonl'
    native = fixture(mode='trace', extra=('--trace-usb', str(trace)))
    events = native.until('ready')
    assert any(e['event'] == 'trace' and e['slots'] >= 5 for e in events)
    native.close()
    records = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    hooked = {r['module']: r for r in records if r['call'] == 'hooked'}
    assert hooked['fake-fvc.dll']['slots'] == 5 and not hooked['fvc.dll']['loaded']
    calls = [r for r in records if r['call'] != 'hooked' and r.get('handle') == records[-1]['handle']]
    assert [r['call'] for r in calls] == ['CreateFileA', 'DeviceIoControl', 'DeviceIoControl', 'WriteFile', 'ReadFile', 'CloseHandle']
    create, write_regs, read_regs, write = calls[:4]
    assert create['name'] == 'NUL' and create['ok'] == 1
    assert write_regs['ioctl'] == 0x80002010 and write_regs['block'] == {'offset': 0xB0, 'length': 2, 'index': 0}
    assert write_regs['data'] == '8d41' and write_regs['ok'] == 0   # NUL refuses; the failure is passed through
    assert read_regs['ioctl'] == 0x8000200C and read_regs['block']['offset'] == 7
    assert write['data'] == '8d41' and write['done'] == 2 and write['ok'] == 1
    assert all(r['n'] > 0 for r in calls) and [r['n'] for r in calls] == sorted(r['n'] for r in calls)


def test_direct_scans_stream_a_live_preview_from_the_strips(tmp_path, fixture):
    import base64
    native = fixture(mode='wide')
    native.until('ready')
    native.send(f'scan 1 {tmp_path / "wide.tif"}')
    events = native.until('scan_done')
    assert events[-1]['result'] == 1, events
    start = next(e for e in events if e['event'] == 'live_start')
    assert start['width'] == 150 and start['source_width'] == 1200 and start['scale'] == 8
    rows = [e for e in events if e['event'] == 'live']
    assert [r['y'] for r in rows] == list(range(16))          # 128 lines / 8
    pixels = base64.b64decode(rows[5]['data'])
    assert list(pixels[30 * 3:30 * 3 + 3]) == [(5 + 30 + c * 50) & 0xff for c in range(3)]
    # The preview rows arrive between strips, before the image is finished.
    assert events.index(rows[0]) < next(i for i, e in enumerate(events) if e['event'] == 'image')
