"""Deterministic, explicitly synthetic scanner implementing FRAME's async contract.

No USB, TWAIN, motor commands, persistence, or claims of hardware verification live
here. The API owns original-file persistence and the single active scan session.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Protocol

import numpy as np

EventCallback = Callable[[dict], Awaitable[None] | None]


class ScannerError(RuntimeError):
    """A scanner operation was rejected or failed."""


class ScannerFault(ScannerError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ScannerCancelled(ScannerError):
    """Cancellation requires controlled recovery before another command."""


class UnsupportedOperation(ScannerError):
    """The backend has no verified implementation of the requested operation."""


class ScannerBackend(Protocol):
    async def discover(self) -> list[dict]: ...
    def capabilities(self) -> dict: ...
    def subscribe(self, callback: EventCallback) -> Callable[[], None]: ...
    async def connect(self) -> dict: ...
    async def initialize(self) -> None: ...
    async def calibrate(self) -> None: ...
    async def load(self, frame_count: int, media: str = "uncut") -> None: ...
    async def prescan(self) -> list[dict]: ...
    async def list_frames(self) -> list[dict]: ...
    async def position_frame(self, index: int) -> None: ...
    async def acquire(self, index: int) -> np.ndarray: ...
    async def cancel(self) -> None: ...
    async def recover(self) -> None: ...
    async def eject(self) -> None: ...
    async def disconnect(self) -> None: ...


class SimulatedScannerBackend:
    """Serial scanner with repeatable positions, progress, and transmission data.

    delay is seconds per simulator tick: 0 accelerates tests; 0.5 gives a human
    review pace. Neither setting models measured PF1800 timings. Event delivery
    uses one bounded dispatcher, so a slow phone subscriber cannot stall scans.
    Logs contain metadata only, never image arrays. Faults remain latched until
    recover() and are injected only once per backend instance.
    """

    FAULTS = {"jam", "calibration", "disconnect", "timeout", "alignment", "write"}
    MAX_PENDING_COMMANDS = 16
    EVENT_QUEUE_SIZE = 128

    def __init__(self, delay: float = 0.02, fault: str | None = None, fault_frame: int = 17):
        if not np.isfinite(delay) or delay < 0 or delay > 60:
            raise ValueError("Simulator delay must be between 0 and 60 seconds")
        if fault is not None and fault not in self.FAULTS:
            raise ValueError(f"Unknown simulator fault: {fault}")
        if isinstance(fault_frame, bool) or not isinstance(fault_frame, int) or not 1 <= fault_frame <= 72:
            raise ValueError("Fault frame must be from 1 to 72")
        self.delay = delay
        self.fault = fault
        self.fault_frame = fault_frame
        self.status = "idle"
        self.connected = False
        self.initialized = False
        self.calibrated = False
        self.frame_count = 0
        self.media = "uncut"
        self.current_frame: int | None = None
        self.completed_frames: set[int] = set()
        self.frames: list[dict] = []
        self.error: str | None = None
        self.event_log: deque[dict] = deque(maxlen=2048)
        self._lock = asyncio.Lock()
        self._pending = 0
        self._cancelled = False
        self._interrupt = asyncio.Event()
        self._fault_latched = False
        self._fault_used = False
        self._subscribers: list[EventCallback] = []
        self._events: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.EVENT_QUEUE_SIZE)
        self._dispatcher: asyncio.Task | None = None
        self._sequence = 0
        self._ticks = 0

    async def discover(self) -> list[dict]:
        return [{"id": "frame-simulator", "name": "PF1800 workflow simulator",
                 "backend": "simulated", "synthetic": True, "hardware_verified": False}]

    def capabilities(self) -> dict:
        return {
            "backend": "simulated", "synthetic": True, "hardware_verified": False,
            "evidence": "synthetic software fixture; no real device validation",
            "media": ["uncut", "strip"], "frame_count_min": 1, "frame_count_max": 72,
            "bit_depth": 8, "channels": "RGB", "sample_type": "uint8",
            "image_kind": "synthetic film transmission", "fixture_size": [192, 128],
            "progressive_image_transfer": False, "progress_events": True,
            "cancel": True, "recover": True, "real_hardware_commands": False,
            "timing": "simulator ticks, not measured hardware timing",
        }

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    async def _dispatch(self) -> None:
        while not self._events.empty():
            event = self._events.get_nowait()
            try:
                for callback in tuple(self._subscribers):
                    try:
                        result = callback(dict(event))
                        if inspect.isawaitable(result):
                            await asyncio.wait_for(result, timeout=0.25)
                    except Exception:
                        # Subscriber failures never fail or hold scanner acquisition.
                        continue
            finally:
                self._events.task_done()

    async def flush_events(self) -> None:
        """Wait for bounded delivery, useful for diagnostic replay and tests."""
        await self._events.join()

    def _emit(self, kind: str = "status", **data: object) -> None:
        self._sequence += 1
        event = {"type": kind, "sequence": self._sequence, "status": self.status,
                 "synthetic": True, "backend": "simulated", "frame": self.current_frame,
                 "simulator_tick": self._ticks, **data}
        self.event_log.append(dict(event))
        if not self._subscribers:
            return
        if self._events.full():
            self._events.get_nowait()
            self._events.task_done()
        self._events.put_nowait(event)
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(self._dispatch())

    def _state(self, status: str, **data: object) -> None:
        self.status = status
        self._emit(**data)

    def _check(self) -> None:
        if not self.connected:
            raise ScannerError("Simulator disconnected; connect and recover before continuing")
        if self._cancelled:
            raise ScannerCancelled("Simulated acquisition cancelled; controlled recovery required")
        if self._fault_latched:
            raise ScannerError(self.error or "Simulator fault requires controlled recovery")

    @asynccontextmanager
    async def _command(self, check: bool = True):
        if self._pending >= self.MAX_PENDING_COMMANDS:
            raise ScannerError("Scanner command queue full; retry after current operation")
        self._pending += 1
        try:
            async with self._lock:
                if check:
                    self._check()
                try:
                    yield
                except asyncio.CancelledError:
                    self._cancelled = True
                    self._interrupt.set()
                    self.error = "Simulator task interrupted; controlled recovery required"
                    self._state("error", error=self.error, cancelled=True)
                    raise
        finally:
            self._pending -= 1

    async def _tick(self) -> None:
        # Yield even at delay=0 to allow cancellation and event delivery.
        if self.delay:
            try:
                await asyncio.wait_for(self._interrupt.wait(), timeout=self.delay)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(0)
        self._ticks += 1
        self._check()

    def _inject(self, fault: str, index: int | None = None) -> None:
        if self.fault != fault or self._fault_used or (index is not None and index != self.fault_frame):
            return
        self._fault_used = True
        self._fault_latched = True
        messages = {
            "jam": f"Simulated film jam suspected at frame {index}; clear and recover",
            "calibration": "Simulated calibration failed; controlled recovery required",
            "disconnect": f"Simulated USB disconnection at frame {index}; reconnect and recover",
            "timeout": f"Simulated acquisition timeout at frame {index}; controlled recovery required",
            "alignment": f"Simulated bad alignment at frame {index}; realign and recover",
            "write": f"Simulated file write failure at frame {index}; check destination and recover",
        }
        self.error = messages[fault]
        if fault == "disconnect":
            self.connected = False
        self._state("disconnected" if fault == "disconnect" else "error", error=self.error, fault=fault)
        raise ScannerFault(fault, self.error)

    async def connect(self) -> dict:
        async with self._command(check=False):
            self.connected = True
            if not self._cancelled and not self._fault_latched:
                self._interrupt.clear()
            self._state("connected")
            return {"connected": True, "status": self.status, **self.capabilities()}

    async def initialize(self) -> None:
        async with self._command():
            self._state("initializing")
            await self._tick()
            self.initialized = True
            self._state("ready")

    async def calibrate(self) -> None:
        async with self._command():
            if not self.initialized:
                raise ScannerError("Initialize simulator before calibration")
            self._state("calibrating")
            await self._tick()
            self._inject("calibration")
            self.calibrated = True
            self._state("ready")

    async def load(self, frame_count: int, media: str = "uncut") -> None:
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or not 1 <= frame_count <= 72:
            raise ValueError("Frame count must be from 1 to 72")
        if media not in {"uncut", "strip"}:
            raise UnsupportedOperation("Only synthetic uncut rolls and precut strips are supported")
        async with self._command():
            if not self.calibrated:
                raise ScannerError("Calibrate simulator before loading film")
            self._state("loading", frame_count=frame_count, media=media)
            await self._tick()
            self.frame_count = frame_count
            self.media = media
            self.current_frame = None
            self.completed_frames.clear()
            self.frames = [{"index": i, "position_mm": round((i - 1) * 38.0, 2),
                            "width_mm": 36.0, "height_mm": 24.0, "synthetic": True}
                           for i in range(1, frame_count + 1)]
            self._state("ready")

    async def prescan(self) -> list[dict]:
        async with self._command():
            if not self.frames:
                raise ScannerError("Load synthetic film before prescan")
            self._state("prescanning")
            await self._tick()
            self._state("ready", frame_count=self.frame_count)
            return [dict(frame) for frame in self.frames]

    async def list_frames(self) -> list[dict]:
        return [dict(frame) for frame in self.frames]

    def _validate_index(self, index: int) -> None:
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= self.frame_count:
            raise ValueError("Frame index is outside the loaded film")

    async def position_frame(self, index: int) -> None:
        async with self._command():
            self._validate_index(index)
            self.current_frame = index
            self._state("positioning")
            await self._tick()
            self._inject("jam", index)
            self._inject("alignment", index)
            self._state("ready")

    @staticmethod
    def transmission_fixture(index: int) -> np.ndarray:
        """Small repeatable RGB negative-like chart; entirely synthetic data."""
        y, x = np.indices((128, 192), dtype=np.int32)
        r = 90 + ((x * 2 + y + index * 13) % 150)
        g = 45 + ((x + y * 2 + index * 7) % 125)
        b = 30 + ((x // 2 + y + index * 19) % 110)
        fixture = np.stack((r, g, b), axis=-1).astype(np.uint8)
        # Black perimeter, color patches and index bars expose crop/order bugs.
        fixture[:4] = 8
        fixture[-4:] = 8
        fixture[:, :4] = 8
        fixture[:, -4:] = 8
        for bit in range(7):
            fixture[8:16, 8 + bit * 12:16 + bit * 12] = 220 if index & (1 << bit) else 25
        return fixture

    async def acquire(self, index: int) -> np.ndarray:
        async with self._command():
            self._validate_index(index)
            if self.current_frame != index:
                raise ScannerError("Position the requested frame before acquiring")
            if index in self.completed_frames:
                # Repeated requests are idempotent; no duplicate completion event.
                return self.transmission_fixture(index)
            self._state("focusing")
            await self._tick()
            self._state("scanning")
            for chunk in range(1, 5):
                await self._tick()
                if chunk == 2:
                    self._inject("disconnect", index)
                    self._inject("timeout", index)
                self._emit("progress", progress=chunk / 4, acquired_rows=chunk * 32,
                           total_rows=128, image_kind="synthetic film transmission")
            self._state("saving", simulated=True)
            self._inject("write", index)
            result = self.transmission_fixture(index)
            self.completed_frames.add(index)
            self._state("complete" if len(self.completed_frames) == self.frame_count else "ready")
            self._emit("frame_complete", index=index, completed_frames=len(self.completed_frames))
            return result

    async def cancel(self) -> None:
        # Cancellation is an interrupt signal, never queued behind acquisition.
        self._cancelled = True
        self._interrupt.set()
        self.error = "Simulated acquisition cancelled; controlled recovery required"
        self._state("error", error=self.error, cancelled=True)

    async def recover(self) -> None:
        async with self._command(check=False):
            if not self.connected:
                raise ScannerError("Connect simulator before controlled recovery")
            self._cancelled = False
            self._interrupt.clear()
            self._fault_latched = False
            self.error = None
            self._state("ready", recovered=True, completed_frames=len(self.completed_frames))

    async def eject(self) -> None:
        async with self._command():
            self.frame_count = 0
            self.frames = []
            self.current_frame = None
            self.completed_frames.clear()
            self._state("ready", ejected=True)

    async def disconnect(self) -> None:
        self.connected = False
        self._interrupt.set()
        self.initialized = False
        self.calibrated = False
        self._state("disconnected")


class _DisabledHardwareBackend:
    def capabilities(self) -> dict:
        return {"backend": self.name, "available": False, "hardware_verified": False,
                "real_hardware_commands": False, "evidence": "UNAVAILABLE: not validated on device"}

    async def discover(self) -> list[dict]:
        return []

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        return lambda: None

    async def _unsupported(self, *args, **kwargs):
        raise UnsupportedOperation(f"{self.name} hardware backend disabled: no verified device implementation")

    connect = initialize = calibrate = load = prescan = list_frames = _unsupported
    position_frame = acquire = cancel = recover = eject = disconnect = _unsupported


class TwainScannerBackend(_DisabledHardwareBackend):
    name = "twain"


class UsbScannerBackend(_DisabledHardwareBackend):
    name = "usb"
