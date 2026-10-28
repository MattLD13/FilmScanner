# PF1800AFL arrival plan

No physical scanner is attached or tested in this research. All capabilities
remain DOCUMENTED, INFERRED, EXPERIMENTAL or UNAVAILABLE until this actual unit
supplies evidence. The production USB/TWAIN backends remain disabled.

## Preserve and identify first

1. Preserve the supplied CD as an ISO where practical; calculate SHA256 and retain
   the original media. Inventory any differences from the archived installer.
2. Confirm the unit's exact model, external power supply ratings, connectors and
   visible condition against its model-specific manual. Do not open the housing
   or probe the lamp inverter. Respect the return period.
3. Use an offline, licensed guest for original vendor software and drivers. Capture
   a baseline with the scanner disconnected. Keep archive data and credentials out
   of the guest. Do not install legacy scanner drivers on the main Windows system.
4. With no film loaded, record ordinary OS enumeration: VID/PID, revision,
   device/configuration/interface/endpoint/string descriptors, port speed and
   driver binding. Capture with a known capture tool in the isolated environment;
   installing any host capture/filter driver requires its own explicit approval.
   Do not issue a custom vendor request to obtain this first trace.

## One original-software action per capture

Read the PF1800AFL manual's loading and operation instructions before motion. Use
expendable film for supervised first transport tests. Store capture files and
images in ignored research artifacts with hashes, wall-clock start/end, software
versions, UI action and visible result. Preserve raw traffic before filtering.

| Order | Original CyberView action | Observation and stop condition |
| --- | --- | --- |
| 1 | Launch/detect with film absent | Match enumeration and first successful device identity; stop on unexpected motion or repeated reset. |
| 2 | Documented initialization/calibration | Capture status and duration; stop on repeated cycling, abnormal lamp behavior, heat, sound or stall. |
| 3 | Load one supported sacrificial strip | Confirm correct orientation/entry and manual-supported strip length. Stop at resistance, skew, roller slip or unexpected movement. |
| 4 | One prescan | Retain preview and frame map; identify command boundaries and data transfer. Stop if alignment is unsafe. |
| 5 | One documented focus/acquisition | Preserve exact acquired bytes and metadata. Measure effective sample precision, channel order and dimensions. Do not call processed driver output raw. |
| 6 | Documented ejection | Verify transport stops and film is undamaged. Record final device state. |

Do not combine forward/reverse/jog experiments into the first scan. Custom motor
commands, unknown update commands and firmware writes are forbidden. Explicit
user authorization is required before any later novel physical motion experiment,
with a known bound, expected response, stop method and expendable film. A timeout
must not automatically retry an operation that might already have moved film.

## Virtual-versus-physical comparison

Compare exact descriptor bytes and endpoint types/max-packet sizes; command and
response lengths; setup request direction/value/index; bulk framing and byte
order; status/error/sense values; initialization ordering; calibration outputs;
focus/position units and limits; timing distributions; actual transferred frame
size, bit depth, channel ordering and checksums. Check disconnect, cancellation,
timeout and jam behavior without inducing a physical jam.

An emulator success never establishes safe motor limits, lamp timings, calibration
quality or optical resolution. Promote one operation at a time only after
repeatable traces from this exact unit, a safe bounded implementation, targeted
tests, and the unchanged FRAME workflow suite all pass. Unsupported operations
must remain explicit errors, never fall through to the production simulator.
