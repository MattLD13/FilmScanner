# Independent scanner driver development

FRAME now has a working independent Windows USB communication path for the PF1800
AFL. Device identity and a fixed page-0 status read were verified on the actual
scanner without loading vendor DLLs. Raw control/bulk primitives are implemented
and tested with stand-ins; independent initialization, calibration, image capture,
focus/exposure/transport and extended scans remain unfinished. The normal scanner
workspace still uses its verified vendor-assisted acquisition path.

| Layer | Current evidence |
| --- | --- |
| Independent USB identification | Verified on the attached 2770:0119 unit, USB bcdDevice 0100 |
| Independent status-page selection/read | Verified: register 0x8B, page 0 returned 0x3F |
| Control/bulk transfer implementation | Implemented with bounds, exact-transfer checks, overlapped I/O and isolated deadlines; arbitrary register/bulk commands are not enabled live |
| Independent initialization/calibration/acquisition | Not implemented/validated yet |
| Independent motor, focus, gain/exposure and longer scan control | Not enabled; physical behavior and initialization dependencies still need verification |

## Live independent reads

Finish scanning and release FRAME's or other applications' scanner connection
before using the direct console. It opens an exclusive USB handle and refuses an
existing owner; it does not reset, detach, or displace another connection.

```powershell
python -m services.scanner_host.custom_driver --identify
python -m services.scanner_host.custom_driver --status
python -m services.scanner_host.custom_driver --mode hardware --command '{"op":"status_read","page":0}'
```

`npm run driver:console -- --status` invokes the same direct status read.
`--device-index 0 --timeout-ms 2000` selects an explicit USBSCAN index and bounded
I/O deadline. Every live worker checks the target identity before register I/O.
Only the exact page-0 status template is admitted in JSON hardware mode; another
page, address, data payload, register read/write or bulk request remains blocked.
A mixed batch is rejected in full before its first hardware operation.

Identification reads Windows' eight-byte scanner descriptor and issues no register
write. Status selects page zero with `97 00`, selects address `8B`, then reads one
byte. These are two control writes but only one register-value write; neither is
a motor/lamp command. The raw result is not decoded into film presence, jams or
readiness. `3F` was observed in an already initialized device state, not after an
independently implemented cold startup.

## Use the command console

From the repository root in PowerShell:

```powershell
'{"op":"register_read","register":139}' | python -m services.scanner_host.custom_driver
'{"op":"register_write","register":151,"value":0}' | python -m services.scanner_host.custom_driver
'{"op":"status_read","page":0}' | python -m services.scanner_host.custom_driver
'{"op":"stream_read","length":14874}' | python -m services.scanner_host.custom_driver
python -m services.scanner_host.custom_driver --help
```

`npm run driver:console` starts the same console. For JSON-line output intended
for another program, invoke Python directly so npm's banner is not included.

In default dry-run mode each input line is one JSON command; each output line describes the actual ordered
control/bulk transfers. `executed: false` means only a plan was produced. It is
never a successful device response. No command changes scanner state in dry-run.
Up to 256 commands can also be supplied as a JSON array using `--commands PATH`.

Supported operations:

| Operation | Required fields | Meaning |
| --- | --- | --- |
| `register_read` | `register` 0–255 | Select one register, then read one byte |
| `register_write` | `register`, `value`, each 0–255 | Write the explicit two-byte register/value pair |
| `status_read` | `page` 0–14 | Select low status page, then read register 0x8B |
| `bulk_read` | `length` 1–65535 | Announce a bounded block, then read chunks up to 0xFC00 bytes |
| `bulk_write` | `data_hex`, 1–65535 bytes | Announce an explicit block and send bounded chunks |
| `stream_read` | `length` 1–64512 | Read bytes from an already armed stream; does not start a scan |

Integers use JSON decimal notation (`139` is register `0x8B`). Unknown operations,
extra fields, invalid hexadecimal and out-of-range values are errors. Raw register
addresses are deliberately available for plan development; that does not establish
their meaning, useful range, or safety on a physical scanner.

`--mode replay --responses PATH` checks synthetic responses. The response file
contains a JSON array, one entry per expected transfer, for example:

```json
[
  {"expected":{"kind":"control_out","size":1,"ioctl":2147491856,"offset":176,"index":0,"data_hex":"8b"},"transferred":1},
  {"expected":{"kind":"control_in","size":1,"ioctl":2147491852,"offset":7,"index":0},"data_hex":"6f"}
]
```

Replay compares every expected transfer, its bytes, and its position in the
sequence. Short input/output, missing responses, mismatched order, and unused
responses fail. Output transfers are never automatically retried. Responses are
explicitly labeled synthetic and cannot promote hardware validation.

## Evidence and limits

The register and block wire formats come from
[scanner-protocol.md](scanner-protocol.md), the disassembled IO_PORT/FVC layer,
and the existing physical vendor traces. The bulk-read announcement byte `00`
was observed offline in local `data/traces/usb-traced-scan-2.jsonl`, records 250 and
278: WRITE_REGISTERS, offset 3, index 1, one byte `00`. These are observations of
the vendor's path, not tests of this new implementation. Source acquisitions and
trace files were read without modification; no scanner command was issued.

The native-width IO_BLOCK layout is defined in `custom_protocol.py` and tested
for 32-bit unsigned members and a native pointer. Microsoft documents the
[IO_BLOCK structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ns-usbscan-_io_block),
[control reads](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_read_registers),
[control writes](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_write_registers),
and [bulk access through usbscan.sys](https://learn.microsoft.com/en-us/windows-hardware/drivers/image/usb-driver).
Control reads return through DeviceIoControl's output buffer; control writes use
the IO_BLOCK data pointer and have no output buffer. The independent transport
preserves that distinction. This work does not install a kernel driver or change
the device binding.

The existing successful scan contains initialization, AFE offset/gain calibration,
gamma/shading RAM tables, indexed CCD timing and line offsets, motor setup, and
image streaming. Those stages still need an independent implementation and
controlled validation; replaying an arbitrary full historical write sequence is
not a safe substitute. The live opener admits only independent identity and the
fixed verified status operation. There is no permissive flag for arbitrary raw
commands; `--mode hardware` without an approved explicit command fails before
loading Windows APIs.

## Wider scans and additional controls

The known 2586 × 1708 scan-window clamp is in SCAN08 and FRAME's current bridge.
That establishes a software limit; it does not establish the mechanics can move
the sensor/film through a two-frame image in one acquisition. Extra requested
lines alone are insufficient: acquisition direction, line spacing, RGB offsets,
buffer limits, film travel, detection, calibration and safe stopping all matter.
In particular, the existing stitch nudges add horizontal **x** coverage (up to
2586 columns in one vendor scan); requesting more CCD rows extends the **y**
dimension (currently up to 1708 rows). We have not established that the scan
motion can be redirected or continued along the same film axis as those nudges.
The physical CCD/scan-motion axes must be established before claiming that twice
as many lines can cover two successive frames.

Exposure is not a single raw register. Indexed CCD timing and AFE gains/offsets
are separate from the vendor's per-channel exposure tables. A custom focus or
film-movement routine likewise needs a known bounded motor sequence and status
conditions. These high-level controls are not implemented by merely exposing a
register console.

The next stages are:

1. Reconstruct independent initialization, calibration and one ordinary archival acquisition;
   compare exact image geometry, sample precision, colour and return position.
2. Implement bounded film movement, focus and exposure, one operation per trace,
   with explicit supervision required by FRAME_SPEC.md.
3. Establish physical scan-axis/travel limits, then test a bounded extended capture.
   If a long continuous scan is unsupported, acquire overlapping windows and
   recover each frame from observed borders while preserving every source.

## Independent transport milestone, October 31, 2026

`usbscan_transport.py` implements native-width descriptor/OVERLAPPED structures,
exclusive `CreateFileW`, control and bulk buffers, transfer-count checks,
completion events and cancellation. A separate helper process bounds open,
transfer and close. Cancellation is drained before releasing its buffers/event;
the parent applies a final process deadline without resetting or retrying I/O.
If a helper cannot settle, another attempt in that controller process is refused
as ownership-uncertain. Separate CLI invocations still rely on OS handle
exclusivity; persistent cross-invocation recovery is not claimed.
Worker output is checked before reporting successful device access.

Microsoft's [descriptor structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ns-usbscan-_device_descriptor)
and [descriptor IOCTL](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_get_device_descriptor)
define the identity query. [CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex)
only requests cancellation; [GetOverlappedResult](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresult)
establishes completion before buffers can be released.

Actual tests on the attached unit returned descriptor `7027190100010000` and
status `3f`, repeatedly, through independent Python/Windows calls. The worker
checked that SCAN08, SQ_SCAN, IO_PORT, FVC, CyberViewX.ds and BeneScan were absent.
No image was acquired, bulk data transferred, motor/lamp commanded, driver
installed or firmware changed by this milestone. This does not establish
power-on initialization, physical cancellation recovery, or raw sensor precision.

Evidence is separate from vendor-assisted capabilities in
`services/scanner_host/custom_validation.json`. Private observations and the live
JSON-console response remain under ignored `.local/custom-driver/`. The planned
idle FRAME release found its earlier API already closed; no application was
interrupted. The independent exclusive opens then succeeded.

## Rea scan-window investigation, October 31, 2026

Rea 6.8.0 was installed in an isolated tools folder with Node 24.22.1. Its
Ghidra provider passed prerequisite checks using the existing Ghidra 12.1.4
and Android Studio JDK 21. Global Node/Java and agent registration were unchanged.
Rea was used directly from the command line for static analysis; it did not
load the vendor DLL as executable code or access the scanner.

`rea decompile SCAN08.dll 0x100110af --provider ghidra --snapshot PATH --format json`
confirmed the clamp in the installed DLL with SHA-256
`da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f`.
The function limits horizontal coordinates to `0xA1A` (2586), vertical
coordinates to `0x6AC` (1708), and reflects horizontal coordinates for the
opposite scan direction. This confirms a software clamp, not a physical
two-frame capability. The decompiler leaves x87 conversion inputs implicit;
the pseudocode is not sufficient to implement a new coordinate conversion.
Full local evidence and the snapshot are under ignored `.local/frame-rea/`.

Rea is useful here as an interface to Ghidra; it does not reconstruct scanner
calibration or validate arbitrary motor commands automatically. Its
[Windows native analysis documentation](https://github.com/morluto/rea/blob/main/docs/windows-ghidra-p0.md)
describes the supported static-analysis boundary.

Validation of this software foundation:

```powershell
python -m pytest -q tests/scanner/test_custom_driver.py tests/scanner/test_usbscan_transport.py
```

These automated tests use stand-ins for device I/O. They cover protocol bytes,
ABI, limits, replay, partial transfers, pending completion/cancellation, process
deadlines, exclusive ownership, whole-batch admission, evidence gates and malformed
worker output. The separate observed identity/status checks above are actual
hardware evidence; simulated bulk and cancellation checks do not verify those
behaviors on the physical scanner.
