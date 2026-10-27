# Synthetic scanner host

`SimulatedScannerBackend` implements the shared async scanner contract with no
hardware access. RGB arrays are 192 × 128 **synthetic film transmission charts**,
uint8 with 8 effective bits per channel. They are neither personal photographs nor
PF1800 acquisitions. The simulator exposes no real hardware capability as verified.

Lifecycle: `connect`, `initialize`, `calibrate`, `load`, `prescan`, then
`position_frame(index)` and `acquire(index)` for each 1-based index. Uncut rolls and
strips accept 1–72 frames. A repeated successful acquisition is idempotent and does
not emit another completion event. `eject` clears the loaded frame map.

The default `delay=0.02` is accelerated review timing; use `delay=0` for tests and
`delay=0.5` for a slower UI review. All timing is simulated, not measured device
performance. Acquisition emits four synthetic row-progress events. It does not
pretend to stream genuine CCD image data. `saving` marks the synthetic save boundary;
the API must still persist and verify the returned original before reporting it saved.

Commands serialize through a queue bounded to 16 pending operations. Cancellation
and disconnect interrupt the current simulated wait. A cancelled acquisition adds
no completion; call `recover` before retrying. Async event subscribers receive
metadata through a bounded 128-event queue. A slow subscriber can lose old events;
clients should use the API status snapshot after reconnecting. The last 2,048
metadata events are replayable through `event_log`; neither queue contains images.
`flush_events` waits for delivery for diagnostics/tests. Subscriber failures and
timeouts do not fail acquisition.

Fault injection accepts `jam`, `calibration`, `disconnect`, `timeout`, `alignment`,
or `write`, with `fault_frame=17` by default. Calibration faults occur in calibration;
jam/alignment occur in positioning; disconnect/timeout occur midway through
acquisition; write occurs before returning data. Every fault requires an explicit
`recover`, retains frame mapping and completed frame indexes, and triggers only
once. A disconnect additionally requires `connect` before `recover`. A calibration
failure still requires successful calibration. API code owns filesystem writes,
durable session recovery, original hashes, and avoiding duplicate archive records.

TWAIN and USB backends reject all hardware operations as explicitly unsupported.
No driver compatibility or physical scanner operation has been validated.

Targeted check: `python -m pytest tests/scanner -q`.
