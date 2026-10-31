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

2026-10-30 addendum: the USB wire format and the SQ_Scan register map are now
reconstructed statically in [docs/scanner-protocol.md](../../docs/scanner-protocol.md),
and both bridges can record a passive trace of FVC.dll's usbscan calls
(`--trace-usb`). No trace of the physical scanner has been captured yet.

## Identification

`INF_*/PF1800U.INF` and PF1800U.dll `0x10001cb0` agree on `05e3:0120`. The
application has a distinct `CPfs1800AFL` class that selects `SCAN08`, while the U
class selects `PF1800U`. The exact AFL VID/PID is therefore **not established** by
that U evidence. No physical/guest descriptor is synthesized from an INF.

2026-10-28 addendum ([scan08-investigation](scan08-investigation.md)): the
SCAN08 lineage, "SQ Scan08 ASIC", accepts two other identities through USBSCAN
`IOCTL_GET_DEVICE_DESCRIPTOR` (`0x80002018`). `LC.dll`, whose version resource
says SCAN08.DLL 1.0.9.4, accepts only `2770:011C`. WIA `PF1800LC.Dll`, whose
export name is Scan08.dll 1.0.0.1, accepts `0461:034A` or `2770:011C`. The vendor
binds both modules to the **1800P / "Low Cost"** model, code 42. The LC and
PF3600U INFs bind `2770:011C`. No INF names `0461:034A`. These are candidate
lineage identities and are **not** attributed to the AFL.

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

### SQ stack host framing (static)

LC.dll → `SQ_Scan.dll` (SQ Tech 1.0.0.1) → `IO_PORT.DLL` ("Service & Quality
Technology") → `FVC.DLL`. FVC.DLL `openusb` `0x10001af0` opens the first openable
`\\.\USBSCAN0..127`, with no VID filter of its own, and returns VID/PID from
`0x80002018`. Its user-mode calls are:

| FVC export | Host call | Bytes |
| --- | --- | --- |
| `usboutp` `0x10001db0` | `WriteFile` on the USBSCAN handle | 2 bytes: `reg − 0x78`, `value` |
| `usbinp` `0x10001de0` | `WriteFile` then `ReadFile` | 2 bytes `0xF0`, `reg − 0x78`; then 1 byte back |
| `SystemRequest` `0x10001bc0` | `DeviceIoControl` `0x8000200c` / `0x80002010` with a 16-byte block; `0x80002008` with a 1-byte output | Register/control path |

Microsoft documents that USBSCAN maps `ReadFile`/`WriteFile` onto bulk pipes and
register IOCTLs onto vendor control requests. That makes the wire mapping
DOCUMENTED, not observed. The layer is the 1800P/LC path. Whether the missing AFL
SCAN08.dll uses the same SQ stack is INFERRED from the shared "Scan08" name only.
No register meaning, response value or safe register set is known.

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

## Evidence classes (2026-10-28)

| Claim | Class |
| --- | --- |
| AFL class → `SCAN08` → BeneScan model 37 → `SCAN08.dll`; file absent from payload | STATIC |
| Missing module makes BeneScan discovery skip the AFL silently | GUEST OBSERVED 2026-10-28 (no-device trace) |
| BeneScan probes model records 18→1 and loads each present module | GUEST OBSERVED 2026-10-28 |
| `2770:011C` / `0461:034A` accepted by SCAN08-lineage builds bound to 1800P | STATIC |
| Either ID is the AFL's | UNKNOWN |
| USBSCAN register IOCTL → vendor control request; ReadFile/WriteFile → bulk | DOCUMENTED |
| FVC 2-byte register framing on the SQ stack | STATIC (host side only) |
| USB/IP DEVLIST/IMPORT exchange, replay fixtures | HARNESS ONLY |
| CyberView no-device startup: model probe, "Unable to communicate" error, exit | GUEST OBSERVED 2026-10-28 |
| CyberView → model-module scan block layout, status bits, idle polling | GUEST OBSERVED against the FRAME simulator ([afl-simulator.md](afl-simulator.md)) |
| SCAN08-family device commands `0x15`/`0x0A`/`0x0F`/`0xDD`/`0xE2`–`0xE8` (LC.dll `0x10011330`) | STATIC, 1800P path only; never issued |
| Guest USB enumeration of any scanner, real or virtual | none |
| Any device behavior | none: VERIFIED ON DEVICE is empty |

## Next evidence required

Complete ordinary guest setup with permitted UI control, preserve a clean
CyberView no-device baseline, resolve model-module packaging, then capture actual
descriptors and the first initialization sequence. Only after observed bytes are
available should a replay profile or QEMU/usbredir scanner device be created.
Each later calibration, documented movement, focus, prescan, acquisition and eject
action needs its own original-software trace. Unknown operations must stall/log.
No production hardware operation becomes enabled from these static findings.
