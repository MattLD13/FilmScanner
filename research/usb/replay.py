"""Exact, ordered, offline USB transfer replay; no kernel or physical device I/O.

The shipped tests use synthetic standard USB fixtures. There is deliberately no
PF1800 profile: no request responses from that scanner have been captured yet.
This engine is ready to consume preserved evidence, without inventing responses.
"""
from dataclasses import dataclass
from collections import deque
import hashlib

from .protocol import MAX_TRANSFER, ProtocolError, SetupPacket


@dataclass(frozen=True)
class Transfer:
    setup: bytes
    outbound: bytes
    inbound: bytes

    def validate(self):
        packet = SetupPacket.parse(self.setup)
        if len(self.outbound) > MAX_TRANSFER or len(self.inbound) > MAX_TRANSFER:
            raise ProtocolError("Replay transfer exceeds bound")
        if packet.request_type & 0x80:
            if self.outbound or len(self.inbound) > packet.length:
                raise ProtocolError("Invalid replay IN transfer")
        elif self.inbound or len(self.outbound) != packet.length:
            raise ProtocolError("Invalid replay OUT transfer")


class ReplayDevice:
    """Lifecycle: detached -> replaying -> exhausted -> detached.

    Unknown transfers do not consume the next evidence record. There is no
    guessing, scan fixture generation, delay inference or hardware command path.
    """
    def __init__(self, transfers: tuple[Transfer, ...], *, provenance: str):
        if provenance not in {"synthetic-fixture", "captured-hardware", "captured-guest"}:
            raise ProtocolError("Explicit replay provenance required")
        if not transfers or len(transfers) > 4096:
            raise ProtocolError("Replay requires 1..4096 bounded transfers")
        for transfer in transfers:
            transfer.validate()
        if sum(len(t.outbound) + len(t.inbound) for t in transfers) > 16 * MAX_TRANSFER:
            raise ProtocolError("Replay data exceeds 16MiB research limit")
        self.transfers = transfers
        self.provenance = provenance
        self.state = "detached"
        self.position = 0
        self.events: deque[dict] = deque(maxlen=2048)

    def attach(self):
        if self.state != "detached":
            raise ProtocolError("Replay already attached")
        self.position = 0
        self.state = "replaying"

    def detach(self):
        self.state = "detached"

    def control(self, setup: bytes, outbound: bytes = b"") -> bytes:
        packet = SetupPacket.parse(setup)
        if len(outbound) > MAX_TRANSFER:
            raise ProtocolError("Transfer exceeds research bound")
        record = {"source": "offline-replay-harness", "profile_provenance": self.provenance,
                  "physical_device": False, "cyberview_guest": False,
                  "setup_hex": setup.hex(), "outbound_sha256": hashlib.sha256(outbound).hexdigest()}
        if self.state != "replaying":
            self.events.append(record | {"result": "rejected", "reason": self.state})
            raise ProtocolError(f"Replay not ready: {self.state}")
        expected = self.transfers[self.position]
        if setup != expected.setup or outbound != expected.outbound:
            self.events.append(record | {"result": "unknown-rejected"})
            raise ProtocolError("Uncaptured or out-of-order transfer")
        self.position += 1
        if self.position == len(self.transfers):
            self.state = "exhausted"
        self.events.append(record | {"result": "replayed", "record": self.position,
                                     "inbound_hex": expected.inbound.hex()})
        return expected.inbound
