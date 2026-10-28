"""Passive decoder for the recovered 32-bit IO_BLOCK boundary.

Static evidence: PF1800U.dll 0x10003480 and daspi32u.dll 0x1000140b /
0x10001464 pass this 16-byte layout to DeviceIoControl. This is a *host API*
structure, not a USB wire packet and not proof those modules drive the AFL model.
Pointers are numbers only and are never dereferenced.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .protocol import ProtocolError

READ_REGISTERS = 0x8000200C
WRITE_REGISTERS = 0x80002010
IO_BLOCK32 = struct.Struct("<IIII")
DOC = "https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ns-usbscan-_io_block"


@dataclass(frozen=True)
class IoBlock32:
    offset: int
    length: int
    buffer_pointer: int
    index: int

    @classmethod
    def parse(cls, raw: bytes) -> "IoBlock32":
        if len(raw) != IO_BLOCK32.size:
            raise ProtocolError("Recovered x86 IO_BLOCK requires exactly 16 bytes")
        result = cls(*IO_BLOCK32.unpack(raw))
        if not 1 <= result.length <= 65535:
            raise ProtocolError("Control transfer length must be from 1 to 65535")
        return result


def decode_ioctl(code: int, raw_block: bytes, payload: bytes | None = None) -> dict:
    """Decode copied trace bytes and documented USBSCAN translation expectations.

    The actual old driver and Geneusb branch must be compared with raw USB traces;
    expected setup fields are never treated as observed traffic or dispatched.
    """
    if code not in (READ_REGISTERS, WRITE_REGISTERS):
        raise ProtocolError(f"Unmapped IOCTL 0x{code:x}")
    block = IoBlock32.parse(raw_block)
    if payload is not None and len(payload) != block.length:
        raise ProtocolError("Copied payload size differs from IO_BLOCK length")
    return {
        "layer": "host-DeviceIoControl-x86",
        "ioctl": f"0x{code:08x}", "offset": block.offset, "length": block.length,
        "index": block.index,
        # Avoid retaining machine-specific process pointers in exported reports.
        "buffer_pointer_present": block.buffer_pointer != 0,
        "payload_hex": payload.hex() if payload is not None else None,
        "documented_usbscan_setup_expectation": {
            "request_type": 0xC0 if code == READ_REGISTERS else 0x40,
            "request": 0x04 if block.length > 1 else 0x0C,
            "value": block.offset & 0xFFFF, "index": block.index & 0xFFFF,
            "length": block.length,
        },
        "source": DOC, "observed_usb_traffic": False, "device_verified": False,
    }
