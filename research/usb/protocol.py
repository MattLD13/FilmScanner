"""Bounded passive USB decoders. No device access and no command transmission.

USB descriptor layouts follow USB 2.0 chapter 9. Descriptor bytes must come from
an actual capture before being used as a PF1800 profile. Static INF identities
alone do not establish a device descriptor, endpoint or vendor command format.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import struct

MAX_TRANSFER = 1024 * 1024


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class SetupPacket:
    request_type: int
    request: int
    value: int
    index: int
    length: int

    @classmethod
    def parse(cls, data: bytes) -> "SetupPacket":
        if len(data) != 8:
            raise ProtocolError("USB setup packet must contain exactly 8 bytes")
        return cls(*struct.unpack("<BBHHH", data))

    def to_dict(self) -> dict:
        return asdict(self) | {"direction": "in" if self.request_type & 0x80 else "out",
                               "type": (self.request_type >> 5) & 3,
                               "recipient": self.request_type & 0x1F}


def parse_descriptors(data: bytes) -> list[dict]:
    """Decode a descriptor sequence, preserving unknown descriptor bytes.

    A configuration transfer may contain multiple interface/endpoint records.
    No synthetic default descriptor values are ever substituted.
    """
    if not data or len(data) > 65535:
        raise ProtocolError("Descriptor buffer must contain 1..65535 bytes")
    records = []
    offset = 0
    while offset < len(data):
        if offset + 2 > len(data):
            raise ProtocolError(f"Truncated descriptor header at {offset}")
        length, kind = data[offset:offset + 2]
        if length < 2 or offset + length > len(data):
            raise ProtocolError(f"Invalid descriptor length {length} at {offset}")
        raw = data[offset:offset + length]
        row = {"offset": offset, "length": length, "type": kind, "raw_hex": raw.hex()}
        expected = {1: 18, 2: 9, 4: 9, 5: 7}.get(kind)
        if expected is not None and length != expected:
            raise ProtocolError(f"Descriptor type {kind} requires length {expected}")
        if kind == 1:
            values = struct.unpack("<BBHBBBBHHHBBBB", raw)
            row.update(zip(("bLength", "bDescriptorType", "bcdUSB", "bDeviceClass",
                "bDeviceSubClass", "bDeviceProtocol", "bMaxPacketSize0", "idVendor",
                "idProduct", "bcdDevice", "iManufacturer", "iProduct", "iSerialNumber",
                "bNumConfigurations"), values))
        elif kind == 2:
            values = struct.unpack("<BBHBBBBB", raw)
            row.update(zip(("bLength", "bDescriptorType", "wTotalLength", "bNumInterfaces",
                "bConfigurationValue", "iConfiguration", "bmAttributes", "bMaxPower"), values))
            total = row["wTotalLength"]
            if total < 9 or offset + total > len(data):
                raise ProtocolError("Truncated or invalid configuration wTotalLength")
        elif kind == 4:
            row.update(zip(("bLength", "bDescriptorType", "bInterfaceNumber", "bAlternateSetting",
                "bNumEndpoints", "bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol",
                "iInterface"), raw))
        elif kind == 5:
            row.update(zip(("bLength", "bDescriptorType", "bEndpointAddress", "bmAttributes",
                "wMaxPacketSize", "bInterval"), struct.unpack("<BBBBHB", raw)))
        elif kind == 3:
            if length % 2:
                raise ProtocolError("USB string descriptor length must be even")
            # String zero contains language IDs; index is not present in the bytes.
            row["utf16le_or_language_ids_hex"] = raw[2:].hex()
        records.append(row)
        offset += length
    return records


@dataclass(frozen=True)
class CommandEvidence:
    opcode: int
    length: int
    name: str
    source: str


def decode_command(payload: bytes, evidence: tuple[CommandEvidence, ...] = ()) -> dict:
    """Recognize only an explicitly recovered command layout, never send it.

    A recovered opcode and exact CDB length are minimum identification evidence;
    response content, successful execution and transport encapsulation are separate
    facts. Unknown payloads are rejected, including when no profile is supplied.
    """
    if not payload or len(payload) > MAX_TRANSFER:
        raise ProtocolError("Command payload outside bounded length")
    matches = [e for e in evidence if e.opcode == payload[0] and e.length == len(payload)]
    if len(matches) != 1:
        raise ProtocolError(f"Unknown/ambiguous command opcode=0x{payload[0]:02x} length={len(payload)}")
    entry = matches[0]
    if not entry.source:
        raise ProtocolError("Command identification requires an evidence source")
    return {"name": entry.name, "opcode": payload[0], "length": len(payload),
            "raw_hex": payload.hex(), "evidence": entry.source, "execution_verified": False}
