import asyncio
import hashlib

import numpy as np
import pytest

from services.scanner_host.backend import (
    ScannerCancelled,
    ScannerError,
    ScannerFault,
    SimulatedScannerBackend,
    TwainScannerBackend,
    UnsupportedOperation,
    UsbScannerBackend,
)


async def prepared(count=36, media="uncut", **kwargs):
    backend = SimulatedScannerBackend(delay=0, **kwargs)
    await backend.connect()
    await backend.initialize()
    await backend.calibrate()
    await backend.load(count, media)
    return backend


def test_complete_36_frame_roll_repeatable_transmission_and_events():
    async def run():
        backend = await prepared()
        events = []

        async def subscriber(event):
            events.append(event)

        backend.subscribe(subscriber)
        frames = await backend.prescan()
        assert [f["index"] for f in frames] == list(range(1, 37))
        assert frames[16]["position_mm"] == 608.0
        hashes = []
        for index in range(1, 37):
            await backend.position_frame(index)
            data = await backend.acquire(index)
            assert data.dtype == np.uint8
            assert data.shape == (128, 192, 3)
            hashes.append(hashlib.sha256(data.tobytes()).hexdigest())
        await backend.flush_events()
        assert backend.status == "complete"
        assert backend.completed_frames == set(range(1, 37))
        assert len(set(hashes)) == 36
        completed = [e["index"] for e in events if e["type"] == "frame_complete"]
        assert completed == list(range(1, 37))
        assert all(e["synthetic"] for e in events)
        assert [e["progress"] for e in events if e["type"] == "progress" and e["frame"] == 1] == [.25, .5, .75, 1]
        np.testing.assert_array_equal(data, backend.transmission_fixture(36))
        count_before = len([e for e in backend.event_log if e["type"] == "frame_complete"])
        np.testing.assert_array_equal(await backend.acquire(36), data)
        assert len([e for e in backend.event_log if e["type"] == "frame_complete"]) == count_before
        assert not backend.capabilities()["hardware_verified"]

    asyncio.run(run())


def test_jam_at_17_controlled_recovery_preserves_first_16_no_duplicates():
    async def run():
        backend = await prepared(fault="jam")
        originals = {}
        for index in range(1, 17):
            await backend.position_frame(index)
            originals[index] = (await backend.acquire(index)).tobytes()
        with pytest.raises(ScannerFault, match="frame 17") as failure:
            await backend.position_frame(17)
        assert failure.value.code == "jam"
        assert backend.status == "error"
        assert backend.completed_frames == set(range(1, 17))
        with pytest.raises(ScannerError, match="jam"):
            await backend.acquire(17)
        await backend.recover()
        for index in range(17, 37):
            await backend.position_frame(index)
            await backend.acquire(index)
        assert backend.status == "complete"
        completed = [e["index"] for e in backend.event_log if e["type"] == "frame_complete"]
        assert completed == list(range(1, 37))
        for index, original in originals.items():
            assert original == backend.transmission_fixture(index).tobytes()

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["alignment", "disconnect", "timeout", "write"])
def test_acquisition_faults_fail_without_false_completion_then_resume(fault):
    async def run():
        backend = await prepared(2, fault=fault, fault_frame=2)
        await backend.position_frame(1)
        original = await backend.acquire(1)
        with pytest.raises(ScannerFault) as failure:
            await backend.position_frame(2)
            await backend.acquire(2)
        assert failure.value.code == fault
        assert backend.completed_frames == {1}
        assert backend.status in {"error", "disconnected"}
        if fault == "disconnect":
            with pytest.raises(ScannerError, match="Connect"):
                await backend.recover()
            await backend.connect()
        await backend.recover()
        await backend.position_frame(2)
        await backend.acquire(2)
        assert backend.completed_frames == {1, 2}
        assert backend.status == "complete"
        np.testing.assert_array_equal(original, backend.transmission_fixture(1))

    asyncio.run(run())


def test_calibration_failure_is_explicit_and_one_shot():
    async def run():
        backend = SimulatedScannerBackend(delay=0, fault="calibration")
        await backend.connect()
        await backend.initialize()
        with pytest.raises(ScannerFault, match="calibration failed"):
            await backend.calibrate()
        assert not backend.calibrated
        await backend.recover()
        await backend.calibrate()
        assert backend.calibrated

    asyncio.run(run())


def test_cancel_during_acquisition_requires_recovery_and_retains_frame_map():
    async def run():
        backend = await prepared(3, media="strip")
        await backend.position_frame(1)
        task = asyncio.create_task(backend.acquire(1))
        while not any(e["type"] == "progress" for e in backend.event_log):
            await asyncio.sleep(0)
        await backend.cancel()
        with pytest.raises(ScannerCancelled):
            await task
        assert backend.completed_frames == set()
        assert len(await backend.list_frames()) == 3
        with pytest.raises(ScannerCancelled):
            await backend.acquire(1)
        await backend.recover()
        await backend.acquire(1)
        assert backend.completed_frames == {1}

    asyncio.run(run())


def test_cancel_interrupts_realtime_wait_and_external_task_cancel_is_recoverable():
    async def run():
        backend = await prepared(1)
        await backend.position_frame(1)
        backend.delay = 60
        task = asyncio.create_task(backend.acquire(1))
        await asyncio.sleep(0)
        await backend.cancel()
        with pytest.raises(ScannerCancelled):
            await asyncio.wait_for(task, timeout=0.5)
        await backend.recover()
        task = asyncio.create_task(backend.acquire(1))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert backend.status == "error"
        assert backend.completed_frames == set()
        await backend.recover()
        backend.delay = 0
        await backend.acquire(1)
        assert backend.status == "complete"

    asyncio.run(run())


def test_event_log_replays_deterministically():
    async def capture():
        backend = await prepared(2)
        await backend.prescan()
        for index in range(1, 3):
            await backend.position_frame(index)
            await backend.acquire(index)
        return list(backend.event_log)

    assert asyncio.run(capture()) == asyncio.run(capture())


@pytest.mark.parametrize("count,media", [(1, "strip"), (6, "strip"), (72, "uncut")])
def test_variable_frame_maps_and_bounds(count, media):
    async def run():
        backend = await prepared(count, media)
        assert len(await backend.prescan()) == count
        with pytest.raises(ValueError):
            await backend.position_frame(count + 1)
        with pytest.raises(ValueError):
            await backend.load(73)
        with pytest.raises(ValueError):
            await backend.load(True)
        with pytest.raises(UnsupportedOperation):
            await backend.load(1, "slide")
        with pytest.raises(ScannerError, match="Position"):
            await backend.acquire(1)
        await backend.position_frame(count)
        await backend.acquire(count)
        await backend.eject()
        assert await backend.list_frames() == []
        await backend.disconnect()
        with pytest.raises(ScannerError, match="disconnected"):
            await backend.initialize()

    asyncio.run(run())


def test_command_queue_is_bounded_and_serial():
    async def run():
        backend = await prepared(1)
        backend.delay = 0.001
        jobs = [asyncio.create_task(backend.position_frame(1)) for _ in range(17)]
        results = await asyncio.gather(*jobs, return_exceptions=True)
        assert sum(isinstance(result, ScannerError) for result in results) == 1
        assert "queue full" in str(results[-1])
        statuses = [e["status"] for e in backend.event_log if e["type"] == "status"]
        assert statuses[-32:] == [state for _ in range(16) for state in ("positioning", "ready")]
        assert backend._pending == 0

    asyncio.run(run())


def test_slow_or_failed_subscriber_does_not_block_acquisition_and_queue_is_bounded():
    async def run():
        backend = await prepared(36)
        gate = asyncio.Event()

        async def slow_subscriber(event):
            await gate.wait()

        backend.subscribe(slow_subscriber)
        for index in range(1, 37):
            await backend.position_frame(index)
            await backend.acquire(index)
        assert backend.status == "complete"
        assert backend._events.qsize() <= backend.EVENT_QUEUE_SIZE
        assert len(backend.event_log) <= 2048
        gate.set()
        await backend.flush_events()
        backend.subscribe(lambda event: 1 / 0)
        await backend.eject()
        await backend.flush_events()
        assert backend.status == "ready"

    asyncio.run(run())


@pytest.mark.parametrize("backend_class", [TwainScannerBackend, UsbScannerBackend])
def test_real_backends_never_silently_simulate(backend_class):
    async def run():
        backend = backend_class()
        assert await backend.discover() == []
        assert backend.capabilities()["real_hardware_commands"] is False
        for operation in (backend.connect, backend.initialize, backend.cancel):
            with pytest.raises(UnsupportedOperation, match="disabled"):
                await operation()

    asyncio.run(run())
