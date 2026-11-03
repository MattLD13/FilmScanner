"""Independent Windows usbscan transport. No vendor library is loaded.

Only device identification and a fixed page-0 status read are exposed. Raw
control and bulk primitives below are development infrastructure, tested with
stand-ins; they are not a verified live scanner command interface.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .custom_protocol import (CommandError, READ_REGISTERS, WRITE_REGISTERS,
                              Transfer, compile_command, control_block, integer)

GET_DEVICE_DESCRIPTOR = 0x80002018
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
ERROR_IO_PENDING, ERROR_IO_INCOMPLETE = 997, 996
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 258
INVALID_HANDLE_VALUE = ct.c_void_p(-1).value
TARGET = (0x2770, 0x0119)
VENDOR_MODULES = ('SCAN08.dll', 'SQ_SCAN.dll', 'IO_PORT.dll', 'FVC.dll',
                  'CyberViewX.ds', 'BeneScan.dll')
_unsettled_workers: list[subprocess.Popen] = []
VALIDATION = Path(__file__).with_name('custom_validation.json')


class UsbscanError(RuntimeError):
    def __init__(self, message, *, hardware_accessed=False, ownership_uncertain=False):
        super().__init__(message)
        self.hardware_accessed = hardware_accessed
        self.ownership_uncertain = ownership_uncertain


class UsbscanTimeout(UsbscanError):
    pass


def require_verified_operation(operation):
    # The manifest cannot enable arbitrary opcodes, pages, or registers. Templates
    # must also be implemented explicitly in this module after physical validation.
    known = {'identify', 'status_read_page0'}
    try:
        evidence = json.loads(VALIDATION.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}
    operations = evidence.get('operations')
    if (operation not in known or type(evidence.get('schema')) is not int or evidence['schema'] != 1
            or evidence.get('vid_pid') != '2770:0119' or not isinstance(operations, list)
            or operation not in operations):
        raise UsbscanError('This independent operation has not been validated; hardware access is disabled')


class DeviceDescriptor(ct.Structure):
    _fields_ = [('vendor', ct.c_uint16), ('product', ct.c_uint16),
                ('bcd_device', ct.c_uint16), ('language', ct.c_uint16)]


class Overlapped(ct.Structure):
    _fields_ = [('internal', ct.c_size_t), ('internal_high', ct.c_size_t),
                ('offset', ct.c_uint32), ('offset_high', ct.c_uint32),
                ('event', ct.c_void_p)]


def _kernel32():
    if os.name != 'nt':
        raise UsbscanError('Independent USB identification requires Windows')
    kernel = ct.WinDLL('kernel32.dll', use_last_error=True, winmode=0x800)
    handle, ptr, dword, boolean = ct.c_void_p, ct.c_void_p, ct.c_uint32, ct.c_int
    specs = {
        'CreateFileW': (handle, [ct.c_wchar_p, dword, dword, ptr, dword, dword, handle]),
        'CreateEventW': (handle, [ptr, boolean, boolean, ct.c_wchar_p]),
        'CloseHandle': (boolean, [handle]),
        'DeviceIoControl': (boolean, [handle, dword, ptr, dword, ptr, dword,
                                     ct.POINTER(dword), ct.POINTER(Overlapped)]),
        'ReadFile': (boolean, [handle, ptr, dword, ct.POINTER(dword), ct.POINTER(Overlapped)]),
        'WriteFile': (boolean, [handle, ptr, dword, ct.POINTER(dword), ct.POINTER(Overlapped)]),
        'WaitForSingleObject': (dword, [handle, dword]),
        'GetOverlappedResult': (boolean, [handle, ct.POINTER(Overlapped), ct.POINTER(dword), boolean]),
        'CancelIoEx': (boolean, [handle, ct.POINTER(Overlapped)]),
        'GetModuleHandleW': (handle, [ct.c_wchar_p]),
    }
    for name, (result, args) in specs.items():
        function = getattr(kernel, name)
        function.restype, function.argtypes = result, args
    return kernel


class _UsbscanDevice:
    """Owned handle used inside an isolated helper, never the production backend.

    Identification is the public path. ``_transfer`` is unverified development
    infrastructure: no console/worker option dispatches those register/bulk calls.
    The helper process provides the outer deadline, including device open/close.
    """
    def __init__(self, device_index=0, timeout_ms=2000, *, kernel=None, access=GENERIC_READ):
        self.index = integer(device_index, 'device_index', 127)
        self.timeout_ms = integer(timeout_ms, 'timeout_ms', 10000, 100)
        self.kernel = kernel if kernel is not None else _kernel32()
        self.access, self.handle, self.identity = access, None, None
        self.hardware_accessed = False

    def _error(self, operation, code=None):
        code = ct.get_last_error() if code is None else code
        return UsbscanError(f'{operation} failed (Windows error {code})',
                            hardware_accessed=self.hardware_accessed)

    def __enter__(self):
        modules = [name for name in VENDOR_MODULES if self.kernel.GetModuleHandleW(name)]
        if modules:
            raise UsbscanError('Vendor modules are already loaded in the identification helper')
        # Exclusive ownership. Do not reset pipes, detach drivers, or steal a handle.
        self.handle = self.kernel.CreateFileW(rf'\\.\USBSCAN{self.index}', self.access,
                                              0, None, 3, 0x40000000, None)
        if self.handle in (None, 0, INVALID_HANDLE_VALUE):
            self.handle = None
            raise self._error('Opening the USB scanner exclusively')
        self.hardware_accessed = True
        try:
            descriptor = DeviceDescriptor()
            count = self._request('ioctl', descriptor, descriptor, GET_DEVICE_DESCRIPTOR)
            if count != ct.sizeof(descriptor):
                raise self._error('Reading the complete scanner descriptor', 13)
            if (descriptor.vendor, descriptor.product) != TARGET:
                raise UsbscanError('The opened USB scanner is not the PF1800 AFL (2770:0119)',
                                   hardware_accessed=True)
            self.identity = {'vid_pid': f'{descriptor.vendor:04X}:{descriptor.product:04X}',
                             'usb_bcd_device': f'{descriptor.bcd_device:04X}',
                             'descriptor_hex': bytes(descriptor).hex(),
                             'device_index': self.index, 'exclusive_handle': True,
                             'vendor_modules_present': modules}
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise UsbscanError(f'Closing the scanner handle failed (Windows error {ct.get_last_error()})',
                                   hardware_accessed=self.hardware_accessed, ownership_uncertain=True)

    def _request(self, kind, input_buffer, output_buffer, ioctl=0):
        if self.handle is None:
            raise UsbscanError('No owned scanner handle')
        event = self.kernel.CreateEventW(None, True, False, None)
        if not event:
            raise self._error('Creating the transfer completion event')
        overlapped = Overlapped(event=event)
        count = ct.c_uint32()
        pending, settled = False, False
        try:
            if kind == 'ioctl':
                ok = self.kernel.DeviceIoControl(self.handle, ioctl,
                    ct.byref(input_buffer) if input_buffer is not None else None,
                    ct.sizeof(input_buffer) if input_buffer is not None else 0,
                    ct.byref(output_buffer) if output_buffer is not None else None,
                    ct.sizeof(output_buffer) if output_buffer is not None else 0,
                    ct.byref(count), ct.byref(overlapped))
            else:
                buffer = output_buffer if kind == 'read' else input_buffer
                function = self.kernel.ReadFile if kind == 'read' else self.kernel.WriteFile
                ok = function(self.handle, ct.byref(buffer), ct.sizeof(buffer),
                              ct.byref(count), ct.byref(overlapped))
            if ok:
                settled = True
                return count.value
            code = ct.get_last_error()
            if code != ERROR_IO_PENDING:
                raise self._error('Starting the USB transfer', code)
            pending = True
            result = self.kernel.WaitForSingleObject(event, self.timeout_ms)
            if result == WAIT_TIMEOUT:
                raise UsbscanTimeout('USB transfer timed out; cancellation requested without retry',
                                     hardware_accessed=True)
            if result != WAIT_OBJECT_0:
                raise self._error('Waiting for USB transfer completion')
            if not self.kernel.GetOverlappedResult(self.handle, ct.byref(overlapped), ct.byref(count), False):
                code = ct.get_last_error()
                settled = code != ERROR_IO_INCOMPLETE
                raise self._error('Completing the USB transfer', code)
            settled = True
            return count.value
        finally:
            if pending and not settled:
                self.kernel.CancelIoEx(self.handle, ct.byref(overlapped))
                # CancelIoEx is only a request. Keep every input/output buffer and
                # OVERLAPPED alive until completion, even when cancellation is slow.
                # This wait is isolated: the parent enforces a process deadline.
                while not self.kernel.GetOverlappedResult(self.handle, ct.byref(overlapped), ct.byref(count), True):
                    if ct.get_last_error() != ERROR_IO_INCOMPLETE:
                        break
            self.kernel.CloseHandle(event)

    def _transfer(self, step: Transfer):
        """Internal primitives; not enabled by any live-console command."""
        if self.identity is None:
            raise UsbscanError('Scanner identity has not been checked')
        if step.kind.startswith('control'):
            block, buffer = control_block(step)
            if step.kind == 'control_in':
                count = self._request('ioctl', block, buffer, READ_REGISTERS)
                if count != step.size:
                    raise UsbscanError('Short control read; no retry', hardware_accessed=True)
                return bytes(buffer)
            count = self._request('ioctl', block, None, WRITE_REGISTERS)
            # WRITE_REGISTERS has no output buffer. usbscan versions may report
            # zero output bytes or the full data length; a partial count is invalid.
            if count not in (0, step.size):
                raise UsbscanError('Short control write; no retry', hardware_accessed=True)
            return step.size
        buffer = (ct.c_ubyte * step.size)()
        if step.data:
            buffer[:] = step.data
        count = self._request('read' if step.kind == 'bulk_in' else 'write',
                              buffer if step.kind == 'bulk_out' else None,
                              buffer if step.kind == 'bulk_in' else None)
        if count != step.size:
            raise UsbscanError('Short bulk transfer; no retry', hardware_accessed=True)
        return bytes(buffer) if step.kind == 'bulk_in' else count


def _device_worker(index, timeout_ms, read_status=False):
    device = None
    try:
        require_verified_operation('status_read_page0' if read_status else 'identify')
        device = _UsbscanDevice(index, timeout_ms, access=GENERIC_READ | GENERIC_WRITE if read_status else GENERIC_READ)
        with device:
            result = {'operation': 'identify', 'hardware_accessed': True,
                      'identity': device.identity, 'register_writes': 0,
                      'bulk_transfers': 0, 'arbitrary_commands_enabled': False}
            if read_status:
                # Fixed, evidence-backed status-page selection; no motor/lamp
                # register and no caller-supplied address, page, or value.
                for step in compile_command({'op': 'status_read', 'page': 0}).transfers:
                    response = device._transfer(step)
                result.update(operation='status', page=0, register='8B',
                              value_hex=response.hex(), register_writes=1, control_writes=2)
        print(json.dumps(result), flush=True)
        return 0
    except (UsbscanError, OSError, CommandError) as exc:
        print(json.dumps({'error': str(exc), 'hardware_accessed': bool(device and device.hardware_accessed),
                          'ownership_uncertain': getattr(exc, 'ownership_uncertain', False)}), flush=True)
        return 2


def _run_worker(operation, device_index=0, timeout_ms=2000):
    if operation not in ('identify', 'status'):
        raise CommandError('No verified worker operation was selected')
    integer(device_index, 'device_index', 127)
    integer(timeout_ms, 'timeout_ms', 10000, 100)
    if any(worker.poll() is None for worker in _unsettled_workers):
        raise UsbscanError('A previous USB helper has not stopped; device ownership is uncertain',
                           hardware_accessed=True, ownership_uncertain=True)
    _unsettled_workers.clear()
    command = [sys.executable, '-m', __name__, f'--{operation}-worker',
               '--device-index', str(device_index), '--timeout-ms', str(timeout_ms)]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=Path(__file__).resolve().parents[2],
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        output, error = process.communicate(timeout=timeout_ms / 1000 + 3)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            _unsettled_workers.append(process)
        raise UsbscanTimeout('USB helper exceeded its deadline; no reset or retry was attempted',
                              hardware_accessed=None, ownership_uncertain=process.poll() is None) from None
    if len(output) > 16384 or len(error) > 16384:
        raise UsbscanError('USB helper returned oversized diagnostics', hardware_accessed=None)
    try:
        result = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise UsbscanError('USB helper did not return a complete result', hardware_accessed=None) from None
    if not isinstance(result, dict):
        raise UsbscanError('USB helper returned an invalid result object', hardware_accessed=None)
    if process.returncode or result.get('error'):
        raise UsbscanError(result.get('error') or 'USB helper failed',
                           hardware_accessed=result.get('hardware_accessed', False),
                           ownership_uncertain=result.get('ownership_uncertain', False))
    identity = result.get('identity')
    if (result.get('operation') != operation or result.get('hardware_accessed') is not True
            or not isinstance(identity, dict) or identity.get('vid_pid') != '2770:0119'
            or identity.get('exclusive_handle') is not True or identity.get('vendor_modules_present') != []
            or (operation == 'status' and (result.get('page') != 0 or result.get('register') != '8B'
                or not isinstance(result.get('value_hex'), str) or re.fullmatch('[0-9a-fA-F]{2}', result['value_hex']) is None))):
        raise UsbscanError('USB helper result did not establish the requested operation and device identity',
                           hardware_accessed=None)
    return result


def identify_scanner(device_index=0, timeout_ms=2000):
    """Read cached USB identity in an isolated process; never sends a register write."""
    require_verified_operation('identify')
    return _run_worker('identify', device_index, timeout_ms)


def read_scanner_status(device_index=0, timeout_ms=2000):
    """Fixed status page 0 only. No caller-supplied register, value or actuator command."""
    require_verified_operation('status_read_page0')
    return _run_worker('status', device_index, timeout_ms)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Read-only independent scanner identification worker')
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument('--identify-worker', action='store_true')
    operations.add_argument('--status-worker', action='store_true')
    parser.add_argument('--device-index', type=int, default=0)
    parser.add_argument('--timeout-ms', type=int, default=2000)
    args = parser.parse_args()
    raise SystemExit(_device_worker(args.device_index, args.timeout_ms, args.status_worker))
