"""Evidence-backed PF1800 AFL USB command plans; never opens a device.

These are the IO_PORT/FVC wire operations documented in scanner-protocol.md,
not SCAN08 selector numbers. A plan is not a verified hardware capability.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Mapping

READ_REGISTERS = 0x8000200C
WRITE_REGISTERS = 0x80002010
MAX_TRANSFER = 0xFC00  # largest vendor bulk read observed on this path
MAX_BLOCK = 0xFFFF     # announced count occupies USB wIndex


class CommandError(ValueError):
    pass


def integer(value, name: str, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CommandError(f'{name} must be an integer from {minimum} to {maximum}')
    return value


@dataclass(frozen=True)
class Transfer:
    kind: str
    size: int
    offset: int = 0
    index: int = 0
    data: bytes = b''

    def __post_init__(self):
        if self.kind not in ('control_in', 'control_out', 'bulk_in', 'bulk_out'):
            raise CommandError('Unknown transfer kind')
        integer(self.size, 'size', MAX_TRANSFER, 1)
        integer(self.offset, 'offset', 0xFFFF)
        integer(self.index, 'index', 0xFFFF)
        if not isinstance(self.data, bytes):
            raise CommandError('Transfer data must be bytes')
        if self.kind.endswith('out') and len(self.data) != self.size:
            raise CommandError('Output data length must equal transfer size')
        if self.kind.endswith('in') and self.data:
            raise CommandError('Input transfers cannot contain output data')
        if self.kind.startswith('bulk') and (self.offset or self.index):
            raise CommandError('Bulk transfers cannot contain control fields')

    def as_dict(self) -> dict:
        result = {'kind': self.kind, 'size': self.size}
        if self.kind.startswith('control'):
            result.update(ioctl=READ_REGISTERS if self.kind == 'control_in' else WRITE_REGISTERS,
                          offset=self.offset, index=self.index)
        if self.data:
            result['data_hex'] = self.data.hex()
        return result


@dataclass(frozen=True)
class CommandPlan:
    operation: str
    transfers: tuple[Transfer, ...]

    def as_dict(self) -> dict:
        return {'operation': self.operation, 'evidence': 'docs/scanner-protocol.md',
                'raw_path_verified_on_device': False,
                'transfers': [step.as_dict() for step in self.transfers]}


def _out(offset, index, data):
    return Transfer('control_out', len(data), offset, index, data)


def _read_register(register: int) -> tuple[Transfer, ...]:
    return (_out(0xB0, 0, bytes([register])), Transfer('control_in', 1, 7))


def compile_command(command: Mapping) -> CommandPlan:
    """Reject unknown operations/fields, and produce exact ordered wire transfers.

    Bulk-read requests a bounded RAM/calibration block. Stream-read only reads
    bytes from an already armed stream; it does not initialize or start a scan.
    """
    if not isinstance(command, dict):
        raise CommandError('Command must be a JSON object')
    op = command.get('op')
    fields = {'register_read': {'register'}, 'register_write': {'register', 'value'},
              'status_read': {'page'}, 'bulk_read': {'length'}, 'bulk_write': {'data_hex'},
              'stream_read': {'length'}}
    if not isinstance(op, str) or op not in fields:
        raise CommandError('Unknown operation; use ' + ', '.join(fields))
    if set(command) != fields[op] | {'op'}:
        raise CommandError(f'{op} requires exactly these fields: ' + ', '.join(sorted(fields[op])))
    if op.startswith('register_'):
        register = integer(command['register'], 'register', 255)
        if op == 'register_read':
            transfers = _read_register(register)
        else:
            value = integer(command['value'], 'value', 255)
            transfers = (_out(0xB0, 0, bytes([register, value])),)
    elif op == 'status_read':
        # Only the low status page range has this short sequence. Higher pages
        # involve 0xCF and are not inferred here.
        page = integer(command['page'], 'page', 0xE)
        transfers = (_out(0xB0, 0, bytes([0x97, page])), *_read_register(0x8B))
    elif op in ('bulk_read', 'stream_read'):
        length = integer(command['length'], 'length', MAX_BLOCK if op == 'bulk_read' else MAX_TRANSFER, 1)
        prefix = (_out(3, length, b'\x00'),) if op == 'bulk_read' else ()
        # 00 was observed in the existing local vendor trace
        # usb-traced-scan-2.jsonl, records 250 and 278 (offset 3, length 1).
        transfers = prefix + tuple(Transfer('bulk_in', min(MAX_TRANSFER, length - pos))
                                   for pos in range(0, length, MAX_TRANSFER))
    else:
        text = command['data_hex']
        if not isinstance(text, str) or len(text) > MAX_BLOCK * 2:
            raise CommandError('data_hex must contain at most 65535 bytes of hexadecimal')
        try:
            data = bytes.fromhex(text)
        except ValueError as exc:
            raise CommandError('data_hex is not valid hexadecimal') from exc
        integer(len(data), 'payload length', MAX_BLOCK, 1)
        transfers = (_out(2, len(data), b'\x02'),) + tuple(
            Transfer('bulk_out', len(data[pos:pos + MAX_TRANSFER]), data=data[pos:pos + MAX_TRANSFER])
            for pos in range(0, len(data), MAX_TRANSFER))
    return CommandPlan(op, transfers)


class IoBlock(ctypes.Structure):
    """Native-width usbscan IO_BLOCK; unsigned stays 32-bit on x86 and x64.

    Microsoft: usbscan/ns-usbscan-_io_block. Never serialize this pointer-bearing
    structure into a file or reuse an x86 vendor process's memory layout on x64.
    """
    _fields_ = [('offset', ctypes.c_uint32), ('length', ctypes.c_uint32),
                ('data', ctypes.POINTER(ctypes.c_ubyte)), ('index', ctypes.c_uint32)]


def control_block(transfer: Transfer):
    """Build the native ABI envelope while retaining its pointed-to byte buffer."""
    if not transfer.kind.startswith('control'):
        raise CommandError('An IO_BLOCK is only used for control transfers')
    buffer = (ctypes.c_ubyte * transfer.size)()
    if transfer.data:
        buffer[:] = transfer.data
    return IoBlock(transfer.offset, transfer.size, buffer, transfer.index), buffer
