"""Minimal loopback USB/IP laboratory with honest missing-device behavior.

Only the management plane is served until a complete evidenced device profile is
available. DEVLIST returns zero devices; IMPORT fails. There is no host USB API,
kernel driver, USB passthrough, claimed PF1800 enumeration, or vendor execution.
Wire layout: https://docs.kernel.org/usb/usbip_protocol.html
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
from collections import deque

from .protocol import MAX_TRANSFER, ProtocolError, SetupPacket

VERSION = 0x0111
REQ_IMPORT, REP_IMPORT = 0x8003, 0x0003
REQ_DEVLIST, REP_DEVLIST = 0x8005, 0x0005
COMMON = struct.Struct("!HHI")
SUBMIT = struct.Struct("!IIIII Iiiii8s")


def parse_management_header(data: bytes) -> tuple[int, int, int]:
    if len(data) != COMMON.size:
        raise ProtocolError("USB/IP operation header requires 8 bytes")
    version, code, status = COMMON.unpack(data)
    if version != VERSION or status != 0:
        raise ProtocolError("Unsupported USB/IP version or request status")
    if code not in (REQ_DEVLIST, REQ_IMPORT):
        raise ProtocolError(f"Unsupported USB/IP management opcode 0x{code:04x}")
    return version, code, status


def parse_submit(data: bytes) -> dict:
    """Passive parser for a complete CMD_SUBMIT, never dispatches to hardware."""
    if len(data) < SUBMIT.size:
        raise ProtocolError("Truncated USB/IP CMD_SUBMIT")
    command, sequence, device, direction, endpoint, flags, length, start, count, interval, setup = SUBMIT.unpack_from(data)
    if command != 1 or direction not in (0, 1) or endpoint > 15:
        raise ProtocolError("Invalid CMD_SUBMIT command, direction or endpoint")
    if length < 0 or length > MAX_TRANSFER or count != 0:
        raise ProtocolError("Oversized/negative transfer or unsupported isochronous transfer")
    expected = SUBMIT.size + (length if direction == 0 else 0)
    if len(data) != expected:
        raise ProtocolError("CMD_SUBMIT payload length mismatch")
    result = {"sequence": sequence, "device": device, "direction": direction,
              "endpoint": endpoint, "flags": flags, "length": length,
              "start_frame": start, "interval": interval, "setup_hex": setup.hex(),
              "payload_hex": data[SUBMIT.size:].hex()}
    if endpoint == 0:
        packet = SetupPacket.parse(setup)
        if packet.length != length:
            raise ProtocolError("Control setup wLength differs from transfer length")
        if bool(packet.request_type & 0x80) != bool(direction):
            raise ProtocolError("Control setup direction differs from USB/IP direction")
        result["setup"] = packet.to_dict()
    return result


class ResearchServer:
    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path
        self.events: deque[dict] = deque(maxlen=2048)
        self._sequence = 0
        self.active_connections = 0
        self.server: asyncio.Server | None = None

    def log(self, event: str, **values):
        self._sequence += 1
        row = {"sequence": self._sequence, "source": "harness-only",
               "physical_device": False, "cyberview_guest": False, "event": event} | values
        self.events.append(row)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")

    async def start(self, port: int = 0) -> int:
        if self.server is not None:
            raise RuntimeError("Server already running")
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", port, limit=4096)
        actual = self.server.sockets[0].getsockname()[1]
        self.log("listening", binding="127.0.0.1", port=actual,
                 device_profile="unavailable: no captured PF1800 descriptors")
        return actual

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if self.active_connections >= 8:
            self.log("connection-rejected", reason="Eight active connections limit")
            writer.close()
            await writer.wait_closed()
            return
        self.active_connections += 1
        try:
            data = await asyncio.wait_for(reader.readexactly(COMMON.size), timeout=2)
            _, code, _ = parse_management_header(data)
            if code == REQ_DEVLIST:
                response = COMMON.pack(VERSION, REP_DEVLIST, 0) + struct.pack("!I", 0)
                self.log("devlist", request_hex=data.hex(), response_hex=response.hex(), devices=0)
            else:
                busid = await asyncio.wait_for(reader.readexactly(32), timeout=2)
                response = COMMON.pack(VERSION, REP_IMPORT, 1)
                self.log("import-rejected", request_hex=(data + busid).hex(),
                         response_hex=response.hex(), reason="No evidenced device profile")
            writer.write(response)
            await writer.drain()
        except (ProtocolError, asyncio.IncompleteReadError, TimeoutError) as error:
            self.log("malformed-rejected", reason=str(error))
        finally:
            self.active_connections -= 1
            writer.close()
            await writer.wait_closed()


async def exercise(log_path: Path):
    """Real TCP exchanges made by our harness, explicitly unrelated to CyberView."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents mixing a new run into an old evidence record.
    with log_path.open("x", encoding="utf-8"):
        pass
    lab = ResearchServer(log_path)
    port = await lab.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = COMMON.pack(VERSION, REQ_DEVLIST, 0)
        # Exercise legitimate TCP fragmentation, not message-boundary assumptions.
        writer.write(request[:3]); await writer.drain()
        writer.write(request[3:]); await writer.drain()
        assert await reader.readexactly(12) == COMMON.pack(VERSION, REP_DEVLIST, 0) + bytes(4)
        writer.close(); await writer.wait_closed()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(COMMON.pack(VERSION, REQ_IMPORT, 0) + b"1-1".ljust(32, b"\0"))
        await writer.drain()
        assert await reader.readexactly(8) == COMMON.pack(VERSION, REP_IMPORT, 1)
        writer.close(); await writer.wait_closed()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(COMMON.pack(VERSION, 0xFFFF, 0)); await writer.drain()
        assert await reader.read() == b""
        writer.close(); await writer.wait_closed()
    finally:
        await lab.close()
    print(json.dumps({"result": "harness-only management exchange passed",
                      "pf1800_emulation": "blocked: missing descriptors and protocol traces",
                      "cyberview_detection_attempted": False, "events": len(lab.events)}))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise-log", required=True, type=Path)
    asyncio.run(exercise(parser.parse_args().exercise_log))
