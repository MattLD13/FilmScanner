# USB protocol notebook

This notebook contains **static observations and explicit unknowns**, not a
captured PF1800AFL protocol. No vendor USB trace or physical scanner capture has
been acquired. All shipped communication logs are labeled with their true source.

## Evidence layers

| Layer | Available evidence | What it does not establish |
| --- | --- | --- |
| CyberView host API | AFL RTTI/vtable, `BeneScan.dll!ScannerDeviceIO` selectors | USB command bytes or endpoint addresses |
| User/driver boundary | PF1800U and generic daspi32u DeviceIoControl wrappers | Actual AFL model selection or driver response |
| Driver documentation | Microsoft USBSCAN IO_BLOCK and documented request mapping | Behavior of the exact old Geneusb/USBSCAN binary on this unit |
| USB wire | None from vendor software/hardware | Descriptors, actual initialization, status or frame payloads |
| Laboratory transport | Real loopback USB/IP management traffic; QEMU infrastructure smoke | Windows USB enumeration or CyberView detection |

## Identification

`INF_*/PF1800U.INF` and PF1800U.dll `0x10001cb0` agree on `05e3:0120`. The
application has a distinct `CPfs1800AFL` class that selects `SCAN08`, while the U
class selects `PF1800U`. The exact AFL VID/PID is therefore **not established** by
that U evidence. No physical/guest descriptor is synthesized from an INF.

Still unknown: bcdUSB/bcdDevice, device class/protocol, endpoint-zero packet size,
configuration power attributes, interfaces, alternate settings, bulk/interrupt
endpoint addresses and sizes, strings/language IDs, serial behavior, device speed,
and any reset/re-enumeration sequence. In particular, a user-mode register offset
`0x82` is not an endpoint descriptor for endpoint0x82.

## Recovered host control structure

PF1800U.dll `0x10003480`, daspi32u.dll `0x1000140b` and `0x10001464` build the
following **x86 host-memory** structure passed to `DeviceIoControl`:

| Byte offset | Size | Field | Evidence |
| --- | --- | --- | --- |
| 0 | 4 | uOffset | Low-byte mask in wrappers |
| 4 | 4 | uLength | Low-byte mask in wrappers |
| 8 | 4 | pbyData | Process pointer; never dereference in the passive parser |
| 12 | 4 | uIndex | Explicit zero in several callers; generic wrapper may leave stack-derived data |

IOCTL0x8000200c reads registers; IOCTL0x80002010 writes them. This matches
[Microsoft IO_BLOCK documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ns-usbscan-_io_block).
The documented USBSCAN translation uses value=uOffset, index=uIndex and
length=uLength; register reads/writes use IN/OUT vendor-device request types and
request0x04 for multiple bytes or0x0c for one byte.
[Read mapping](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_read_registers),
[write mapping](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_write_registers).

That mapping is a **documented expectation**, never an observed scanner setup
packet. The old driver/Geneusb branch must be compared with a raw trace. A pointer
in the host structure is not transmitted on USB and is omitted from exported
decoder output. No checksums, handshakes, response bytes or operation timings are
invented.

## Static register and data observations

* PF1800U read helper`0x100034f0` writes offset0x82,8-byte block, then ReadFile;
  chunks are≤0xf000. Another helper`0x10002260` uses≤0xffff chunks. These are
  host transfer limits, not a measured USB maximum packet size or image row size.
* PF1800U helpers`0x10002140`/`0x100021d0` access offsets0x83,0x85,0x84. Meanings
  remain unknown; request addresses alone do not establish safe queries.
* daspi32u motor export`0x10001c15` writes offset0x89 with six bytes containing
  two16-bit and two8-bit arguments. Physical units, direction, endpoints, motor
  limits and actual model applicability remain unknown. It is blocked from use.
* Generic `_UsbWriteScannerFw@8` exists. No firmware command is allowlisted.

There is no evidenced complete PF1800AFL command CDB/framing registry. The default
`decode_command` consequently rejects every vendor payload. Host API selectors9,
10,0x15 and0x20 are **not** inserted into that registry as USB opcodes.

## Implemented research tools and actual results

`research/usb/protocol.py` passively decodes exact8-byte USB setup packets and
descriptor sequences; it validates lengths, preserves unknown descriptor bytes,
and rejects malformed/truncated data. `legacy_ioctl.py` decodes copied16-byte
x86 IO_BLOCK data and reports the documented mapping separately from observations.
It never reads process memory or opens a device.

`inspect_trace.py` reads explicit JSONL hex records; malformed/unknown rows are
reported and parsing continues. It will not overwrite a source or existing output.
Example input format: `{"kind":"setup","hex":"8006000100001200"}`. This is a
generic standard-USB example, **not a PF1800 capture**. Run:

```powershell
python -m research.usb.inspect_trace input.jsonl new-analysis.jsonl
python -m pytest -q tests/research
python -m research.usb.usbip --exercise-log new-harness-run.jsonl
```

`usbip.py` implements the actual standard USB/IP **management plane** on
127.0.0.1: fragmented8-byte DEVLIST request→empty list; IMPORT→failure; unsupported
operation→close/log. It accepts≤8 active connections,2-second bounded reads,
≤2048 retained events and no physical USB access. The passive CMD_SUBMIT decoder
validates direction, endpoint, transfer size and control wLength; isochronous
transfers are rejected. It does not claim a kernel-importable PF1800 device.
Protocol reference: [Linux USB/IP](https://docs.kernel.org/usb/usbip_protocol.html).

`replay.py` implements detached→replaying→exhausted state with exact request/order
matching and explicit unknown-transfer rejection. A profile requires provenance
and bounded data; no PF1800 profile is supplied. Its tests use fictitious1234:5678
standard descriptor fixtures. Those fixtures never advertise a scanner to Windows.

Actual [harness-usbip-2026-10-27.jsonl](../usb/evidence/harness-usbip-2026-10-27.jsonl)
contains four real loopback-management events. Each has `source=harness-only`,
`cyberview_guest=false`, `physical_device=false`. There is no original CyberView
traffic to compare yet. [QEMU smoke](../usb/evidence/qemu-smoke-2026-10-27.json)
records stopped CPU state and infrastructure availability; it is not enumeration.

## Next evidence required

Complete ordinary guest setup with permitted UI control, preserve a clean
CyberView no-device baseline, resolve model-module packaging, then capture actual
descriptors and the first initialization sequence. Only after observed bytes are
available should a replay profile or QEMU/usbredir scanner device be created.
Each later calibration, documented movement, focus, prescan, acquisition and eject
action needs its own original-software trace. Unknown operations must stall/log.
No production hardware operation becomes enabled from these static findings.
