"""Windows boundary stand-ins: no device or vendor library is opened by tests."""
import ctypes as ct
import json
import subprocess

import pytest

from services.scanner_host import usbscan_transport as usb
from services.scanner_host.custom_protocol import CommandError, Transfer
from services.scanner_host.custom_driver import main


class Kernel:
    def __init__(self):
        self.calls = []
        self.last_error = 0
        self.descriptor = bytes.fromhex('7027190100010000')
        self.pending = None
        self.cancelled = False
        self.wait_result = usb.WAIT_OBJECT_0
        self.async_next = False
        self.reported = None
        self.vendor_loaded = False
        self.fail_open = False

    def GetModuleHandleW(self, name):
        return 1 if self.vendor_loaded and name == 'FVC.dll' else 0

    def CreateFileW(self, path, access, share, security, disposition, flags, template):
        self.calls.append(('open', path, access, share, disposition, flags))
        if self.fail_open:
            self.last_error = 32
            return usb.INVALID_HANDLE_VALUE
        return 100

    def CreateEventW(self, *args):
        self.calls.append(('event',))
        return 200

    def CloseHandle(self, handle):
        self.calls.append(('close', handle))
        return True

    def _deliver(self, output, payload, count):
        if output is not None and payload:
            ct.memmove(output, payload, len(payload))
        count._obj.value = self.reported if self.reported is not None else len(payload)

    def DeviceIoControl(self, handle, code, input_buffer, input_size, output, output_size, count, overlapped):
        self.calls.append(('ioctl', code, input_size, output_size, input_buffer._obj))
        if code == usb.GET_DEVICE_DESCRIPTOR:
            assert input_size == output_size == 8
            payload = self.descriptor
        elif code == usb.READ_REGISTERS:
            assert input_buffer._obj.offset == 7
            payload = b'\x6f' * output_size
        else:
            assert code == usb.WRITE_REGISTERS and output is None
            payload = b''
        if self.async_next:
            self.async_next = False
            self.pending = output, payload, count, overlapped
            self.last_error = usb.ERROR_IO_PENDING
            return False
        self._deliver(output, payload, count)
        return True

    def ReadFile(self, handle, output, size, count, overlapped):
        self.calls.append(('read', size))
        self._deliver(output, bytes(range(size)), count)
        return True

    def WriteFile(self, handle, data, size, count, overlapped):
        self.calls.append(('write', bytes(data._obj)))
        count._obj.value = self.reported if self.reported is not None else size
        return True

    def WaitForSingleObject(self, event, timeout):
        self.calls.append(('wait', timeout))
        return self.wait_result

    def CancelIoEx(self, handle, overlapped):
        assert self.pending[3]._obj is overlapped._obj
        self.calls.append(('cancel',))
        self.cancelled = True
        return True

    def GetOverlappedResult(self, handle, overlapped, count, wait):
        self.calls.append(('result', bool(wait)))
        assert self.pending[3]._obj is overlapped._obj
        # The buffers/OVERLAPPED are still alive when cancellation completes.
        assert self.pending[3]._obj.event == 200
        if self.cancelled:
            self.last_error = 995
            return False
        output, payload, _, _ = self.pending
        self._deliver(output, payload, count)
        return True


@pytest.fixture
def kernel(monkeypatch):
    value = Kernel()
    monkeypatch.setattr(ct, 'get_last_error', lambda: value.last_error, raising=False)
    return value


def test_descriptor_and_overlapped_native_layouts():
    assert ct.sizeof(usb.DeviceDescriptor) == 8
    assert usb.DeviceDescriptor.product.offset == 2
    assert usb.DeviceDescriptor.bcd_device.offset == 4
    assert usb.Overlapped.event.offset == 2 * ct.sizeof(ct.c_void_p) + 8
    assert ct.sizeof(usb.Overlapped) == (32 if ct.sizeof(ct.c_void_p) == 8 else 20)


def test_identity_uses_exclusive_handle_and_only_descriptor_ioctl(kernel):
    with usb._UsbscanDevice(kernel=kernel) as device:
        assert device.identity['vid_pid'] == '2770:0119'
        assert device.identity['usb_bcd_device'] == '0100'
        assert device.identity['vendor_modules_present'] == []
    assert kernel.calls[0] == ('open', r'\\.\USBSCAN0', usb.GENERIC_READ, 0, 3, 0x40000000)
    assert [call[1] for call in kernel.calls if call[0] == 'ioctl'] == [usb.GET_DEVICE_DESCRIPTOR]
    assert kernel.calls[-1] == ('close', 100)


def test_wrong_scanner_is_closed_before_any_register_or_bulk_call(kernel):
    kernel.descriptor = bytes.fromhex('1111222200010000')
    with pytest.raises(usb.UsbscanError, match='not the PF1800'):
        with usb._UsbscanDevice(kernel=kernel):
            pytest.fail('Wrong device must not be admitted')
    assert kernel.calls[-1] == ('close', 100)
    assert len([call for call in kernel.calls if call[0] == 'ioctl']) == 1


@pytest.mark.parametrize('reported', [0, 7, 9])
def test_short_or_invalid_descriptor_is_not_accepted(kernel, reported):
    kernel.reported = reported
    with pytest.raises(usb.UsbscanError, match='complete scanner descriptor'):
        with usb._UsbscanDevice(kernel=kernel):
            pass
    assert kernel.calls[-1] == ('close', 100)


def test_an_existing_owner_is_not_displaced(kernel):
    kernel.fail_open = True
    with pytest.raises(usb.UsbscanError, match='Windows error 32'):
        with usb._UsbscanDevice(kernel=kernel):
            pass
    assert len(kernel.calls) == 1


def test_vendor_module_presence_fails_before_open(kernel):
    kernel.vendor_loaded = True
    with pytest.raises(usb.UsbscanError, match='Vendor modules'):
        with usb._UsbscanDevice(kernel=kernel):
            pass
    assert kernel.calls == []


def test_overlapped_read_waits_then_reports_actual_count(kernel):
    kernel.async_next = True
    with usb._UsbscanDevice(kernel=kernel, timeout_ms=500) as device:
        assert device.identity['vid_pid'] == '2770:0119'
    assert ('wait', 500) in kernel.calls and ('result', False) in kernel.calls
    assert ('cancel',) not in kernel.calls


def test_timeout_drains_cancellation_before_freeing_event_and_closing_device(kernel):
    kernel.async_next = True
    kernel.wait_result = usb.WAIT_TIMEOUT
    with pytest.raises(usb.UsbscanTimeout, match='without retry'):
        with usb._UsbscanDevice(kernel=kernel):
            pass
    assert kernel.calls[-4:] == [('cancel',), ('result', True), ('close', 200), ('close', 100)]
    assert len([call for call in kernel.calls if call[0] == 'ioctl']) == 1


def test_internal_control_and_bulk_buffers_follow_the_native_contract(kernel):
    with usb._UsbscanDevice(kernel=kernel, access=usb.GENERIC_READ | usb.GENERIC_WRITE) as device:
        assert device._transfer(Transfer('control_in', 1, 7)) == b'\x6f'
        assert device._transfer(Transfer('control_out', 2, 0xB0, 0, b'\x97\x00')) == 2
        assert device._transfer(Transfer('bulk_in', 3)) == b'\x00\x01\x02'
        assert device._transfer(Transfer('bulk_out', 3, data=b'abc')) == 3
        control = next(call for call in kernel.calls if call[0] == 'ioctl' and call[1] == usb.WRITE_REGISTERS)
        assert bytes(control[4].data[:2]) == b'\x97\x00'
        assert ('write', b'abc') in kernel.calls


@pytest.mark.parametrize('step', [Transfer('control_in', 2, 7),
                                 Transfer('control_out', 2, 0xB0, 0, b'\x97\x00'),
                                 Transfer('bulk_in', 3), Transfer('bulk_out', 3, data=b'abc')])
def test_short_transfers_stop_without_retry(kernel, step):
    with usb._UsbscanDevice(kernel=kernel) as device:
        before = len(kernel.calls)
        kernel.reported = 1
        with pytest.raises(usb.UsbscanError, match='Short'):
            device._transfer(step)
        assert len([call for call in kernel.calls[before:] if call[0] in ('ioctl', 'read', 'write')]) == 1


@pytest.mark.parametrize('index,timeout', [(-1, 2000), (128, 2000), (0, 0), (0, 10001)])
def test_invalid_parameters_never_load_windows(index, timeout, monkeypatch):
    monkeypatch.setattr(usb, '_kernel32', lambda: pytest.fail('Must validate before loading Windows'))
    with pytest.raises(CommandError):
        usb._UsbscanDevice(index, timeout)


def test_cli_identification_cannot_be_combined_with_raw_commands(monkeypatch, capsys):
    monkeypatch.setattr(usb, 'identify_scanner', lambda *args: pytest.fail('Invalid mixed request must not access hardware'))
    assert main(['--identify', '--command', '{"op":"register_write","register":132,"value":1}']) == 2
    assert json.loads(capsys.readouterr().err)['hardware_accessed'] is False


def test_cli_identification_has_separate_live_evidence(monkeypatch, capsys):
    result = {'operation': 'identify', 'hardware_accessed': True, 'raw_commands_enabled': False}
    monkeypatch.setattr(usb, 'identify_scanner', lambda index, timeout: result)
    assert main(['--identify']) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_parent_deadline_stops_worker_without_reset_or_retry(monkeypatch):
    calls = []
    class Worker:
        returncode = None
        def communicate(self, timeout):
            calls.append(('communicate', timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired('USB helper', timeout)
            return b'', b''
        def kill(self):
            calls.append(('kill',)); self.returncode = -1
        def poll(self): return self.returncode
    monkeypatch.setattr(usb, '_unsettled_workers', [])
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Worker())
    with pytest.raises(usb.UsbscanTimeout) as stopped:
        usb.identify_scanner(timeout_ms=100)
    assert stopped.value.hardware_accessed is None
    assert calls == [('communicate', 3.1), ('kill',), ('communicate', 2)]


def test_unsettled_worker_blocks_another_device_attempt(monkeypatch):
    class Worker:
        def poll(self): return None
    monkeypatch.setattr(usb, '_unsettled_workers', [Worker()])
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('No second helper'))
    with pytest.raises(usb.UsbscanError, match='ownership is uncertain'):
        usb.identify_scanner()


def test_fixed_status_worker_sends_only_the_reviewed_status_sequence(kernel, monkeypatch, capsys):
    monkeypatch.setattr(usb, '_kernel32', lambda: kernel)
    assert usb._device_worker(0, 2000, read_status=True) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['operation'] == 'status' and result['value_hex'] == '6f'
    assert result['register_writes'] == 1 and result['control_writes'] == 2
    assert result['bulk_transfers'] == 0 and not result['arbitrary_commands_enabled']
    controls = [call for call in kernel.calls if call[0] == 'ioctl']
    assert [call[1] for call in controls] == [usb.GET_DEVICE_DESCRIPTOR, usb.WRITE_REGISTERS,
                                           usb.WRITE_REGISTERS, usb.READ_REGISTERS]
    assert bytes(controls[1][4].data[:2]) == b'\x97\x00'
    assert bytes(controls[2][4].data[:1]) == b'\x8b'
    assert controls[3][4].offset == 7


def test_live_console_runs_only_a_verified_whole_status_command(monkeypatch, capsys):
    calls = []
    def status(index, timeout):
        calls.append((index, timeout))
        return {'operation': 'status', 'hardware_accessed': True, 'value_hex': '3f'}
    monkeypatch.setattr(usb, 'read_scanner_status', status)
    assert main(['--mode', 'hardware', '--command', '{"op":"status_read","page":0}']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['plan']['raw_path_verified_on_device']
    assert result['result']['value_hex'] == '3f'
    assert calls == [(0, 2000)]


@pytest.mark.parametrize('command', [
    '{"op":"status_read","page":1}',
    '{"op":"register_write","register":132,"value":20}',
    '{"op":"register_read","register":139}',
    '{"op":"stream_read","length":14874}',
])
def test_unverified_raw_commands_are_blocked_before_windows(command, monkeypatch, capsys):
    monkeypatch.setattr(usb, 'read_scanner_status', lambda *args: pytest.fail('No live command'))
    monkeypatch.setattr(ct, 'WinDLL', lambda *args, **kwargs: pytest.fail('No Windows load'), raising=False)
    assert main(['--mode', 'hardware', '--command', command]) == 2
    assert json.loads(capsys.readouterr().err)['hardware_accessed'] is False


def test_mixed_batch_is_rejected_before_even_a_verified_read(tmp_path, monkeypatch, capsys):
    file = tmp_path / 'commands.json'
    file.write_text('[{"op":"status_read","page":0},{"op":"register_write","register":132,"value":20}]')
    monkeypatch.setattr(usb, 'read_scanner_status', lambda *args: pytest.fail('Batch admission must precede I/O'))
    assert main(['--mode', 'hardware', '--commands', str(file)]) == 2
    assert json.loads(capsys.readouterr().err)['hardware_accessed'] is False


@pytest.mark.parametrize('evidence', [[], {}, {'schema': True},
    {'schema': 1, 'vid_pid': '2770:0119', 'operations': None},
    {'schema': 1, 'vid_pid': '2770:0119', 'operations': ['register_write']},
])
def test_invalid_validation_evidence_fails_closed(evidence, tmp_path, monkeypatch, capsys):
    file = tmp_path / 'validation.json'; file.write_text(json.dumps(evidence))
    monkeypatch.setattr(usb, 'VALIDATION', file)
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('No hardware worker'))
    assert main(['--mode', 'hardware', '--command', '{"op":"status_read","page":0}']) == 2
    assert json.loads(capsys.readouterr().err)['hardware_accessed'] is False


def test_hardware_failures_do_not_claim_no_device_access(monkeypatch, capsys):
    def failed(*args):
        raise usb.UsbscanError('Close failed', hardware_accessed=True, ownership_uncertain=True)
    monkeypatch.setattr(usb, 'read_scanner_status', failed)
    assert main(['--status']) == 2
    result = json.loads(capsys.readouterr().err)
    assert result['hardware_accessed'] and result['ownership_uncertain']


@pytest.mark.parametrize('result', [[], {}, {'operation': 'identify', 'hardware_accessed': False},
                                  {'operation': 'status', 'hardware_accessed': True, 'identity': {'vid_pid': 'wrong'}}])
def test_parent_does_not_promote_incomplete_worker_results(result, monkeypatch):
    class Worker:
        returncode = 0
        def communicate(self, timeout): return json.dumps(result).encode(), b''
        def poll(self): return 0
    monkeypatch.setattr(usb, '_unsettled_workers', [])
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Worker())
    with pytest.raises(usb.UsbscanError) as failed:
        usb.identify_scanner()
    assert failed.value.hardware_accessed is None
