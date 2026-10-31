# How CyberView talks to the PF1800 AFL

This is the complete path from CyberView to the USB wire, reconstructed from the
installed binaries on 2026-10-30 and checked against one real USB trace on
2026-10-31: one hung attempt and one successful scan (see the last two sections).

Evidence: disassembly of `SCAN08.dll` 1.0.3.6 (twain_32\CyberViewX_MF),
`SQ_Scan.dll`, `IO_PORT.dll` and `FVC.dll` (SysWOW64), plus Microsoft's
documentation for usbscan.sys
([IOCTL_WRITE_REGISTERS](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbscan/ni-usbscan-ioctl_write_registers)).
The attached unit is USB `2770:0119`, firmware 4, USB 1.1, CCD 533 (2688 px per line).

## The layers

| Layer | Module | Interface | What crosses it |
| --- | --- | --- | --- |
| 1 | PfsLoader.exe → CyberViewX.ds → BeneScan.dll | TWAIN | Scan requests, images |
| 2 | SCAN08.dll | `ScannerDeviceIO(selector, param)` | 37 selectors ([catalog](scan08-feature-catalog.md)) |
| 3 | SQ_Scan.dll | 28 exports such as `SetLamp`, `MotorMoveNormal`, `GetStatus` | Register-level operations on the SQ "Scan08" ASIC |
| 4 | IO_PORT.dll | `general_SendData(reg, val)`, `general_ReceiveData(reg)`, `general_ReadLine`, `general_WriteLine`, `USB_UsbCleanBuffer` | One register or one block |
| 5 | FVC.dll | `SystemRequest`, `ReadRegData`, `WriteRegData` | usbscan.sys IOCTLs, ReadFile, WriteFile |
| 6 | usbscan.sys | `\\.\USBSCANn` | USB control and bulk transfers |

IO_PORT supports four transports (parallel SPP/EPP, IEEE 1394, USB). `OpenTransferPort`
selects transport 4 (USB) after `openusb` succeeds, and `0x10002640` fills the
function table from the USB case of the jump table at `0x100027c8`. FVC opens one
handle (`\\.\USBSCAN0`…`127`, checked with `IOCTL_GET_DEVICE_DESCRIPTOR` `0x80002018`)
and uses it for every pipe.

## The wire format

usbscan.sys turns `IOCTL_WRITE_REGISTERS` (`0x80002010`) and `IOCTL_READ_REGISTERS`
(`0x8000200C`) into a vendor control transfer. The request byte is `0x04` when the
transfer is longer than one byte and `0x0C` otherwise; `wValue` is the IO_BLOCK
offset and `wIndex` its index. Every scanner operation reduces to this:

| Operation | IO_PORT (USB) | Control SETUP (bmRequestType bRequest wValue wIndex wLength) | Data |
| --- | --- | --- | --- |
| Write register | `SendData` `0x10001740` | `40 04 00B0 0000 0002` | `[reg, value]` |
| Select register | `ReceiveData` `0x10001840` | `40 0C 00B0 0000 0001` | `[reg]` |
| Read selected register | `ReceiveData` | `C0 0C 0007 0000 0001` | 1 byte back |
| Ask for N bulk bytes | `ReadLine` `0x10001b10` | `40 0C 0003 N 0001` | 1 byte |
| Then read them | `ReadLine` | bulk IN `ReadFile`, at most 0xFC00 bytes per request | data |
| Announce N bulk bytes | `WriteLine` `0x10001e40` | `40 0C 0002 N 0001` | `[02]` |
| Then send them | `WriteLine` | bulk OUT `WriteFile` | data |
| Clean the FIFO | `USB_UsbCleanBuffer` | `40 0C 00C0 8406 0001`, then `40 0C 00C0 0406 0001` | 1 byte |
| Port-style writes | `0x100015d0`, `0x10001500`, `0x10001690` | `40 0C 0080`/`0090`/`0004` `0000 0001` | 1 byte |

Two read paths exist:

- **Block reads** (`ReadLine` with a non-negative mode: RAM tables, calibration):
  the host asks for N bytes with request `0x03`, then reads them, in chunks of
  64,512 bytes.
- **Image streaming** (`GetAutoScanImage` → `ReadLine(buf, -3, len, 1)`): the first
  call cleans the FIFO and writes `[01]` to offset 1, then every line is a plain
  bulk IN read. The ASIC pushes lines on its own once auto-scan is armed.

`IOCTL_WAIT_ON_DEVICE_EVENT` (interrupt pipe) exists in FVC but the USB transport
never calls it. Status is polled with register reads.

## What each SQ_Scan function writes

Register writes are `W reg = value`; `idx` means the value comes from the caller.

| Function | Register sequence |
| --- | --- |
| `SetLamp` | `W a8=80`, `W 83=20`, `W 8d=idx`, `W 83=00`, `W 8d=idx`, `W 93=` 0c/06/09/05/00 by lamp mode |
| `SetPowerSave` | `W a8=80`, `W a8=idx` |
| `SetGPIO` | `W 83=00`, `W a3`, `W a4=00`, `W a1`, `W a2=00` |
| `SetCCDPixelNumber` | `W 83=22`, `W 87=idx`, `W 83=02`, `W 87=00` |
| `SetCCDTiming` | `W a0`, `W 83=00`, `W a0`, `W 9c..9f`, `W 83=20`, `W a5..a7` |
| `SetADC` | `W 80=00`, `W 80=01`, `W 04=80`, `W 04=00`, `W 00=00`, `W 01=03/07`, `W 03`, `W 02=04`, `W 05=00`, gains `W 28..2a`, offsets `W 20..22`, `W 24..26=00` |
| `SetLineOffset` | for index 0..3 in `9b`: `W 98..9a` (R/G/B line delays) |
| `MotorMoveNormal` | `W c0=00`, `W 80=41`, `W 84` (steps), `W c8`, `W 88` (speed), `W 89`, `W 86=00` (go) |
| `MotorBackNormal` | `W c0=00`, `W 84`, `W c8`, `W 89`, `W 97`, `W 82=00`, `W 80=` d1/c1/51/41 |
| `MotorBackAccDec` | `W c0=00`, `W 84=00`, `W 97`, `W 84`, `W 80=51`, `W 82=ff`, `W 82=00` |
| `SetMotorAccDecFormula` | `W c1..c8`, `W c0`, `W 89`, `W 86=00` |
| `SetScanAccDecFormula` | `W 83=00`/`20` + `W 85` (indexed), `W bc`, `W bd`, `W 88`, `W c1..c3`, `W c6..c8`, `W c0`, `W 89`, `W 86=00` |
| `SetMotorType` | `W 84=00`, `W 80=01`, `W 84`, `W 80=` e1/c1/61/41 |
| `RamRWByte` / `RamRWBulk` | `W 94` (RAM select), `W b0..b2` (start), `W b3..b5` (end), then data through `8f` (byte) or a bulk block |
| `WriteTable` | Three gamma/shading tables to RAM at `0x001000`, `0x002000`, `0x003000` (end `0x1fffff`), then `RamRWBulk` read-backs |
| `SetImageBufferRange` | `W 94`, `W b0..b8`, `W b9=00` |
| `DrivingCapabilitySetting` | `W ce`, `W cf` |
| `SetAutoScan` | `W bb`, `W 9b`, `W 8e`, `W 8e=00`, `W 8b=00`, `W bf`, `W 90` (start), `W 91=00`, `W 83=82`, clean FIFO, read the first line, `W be` |
| `GetAutoScanImage` | streamed bulk read of one line |
| `StopAutoScan` (= `SafeInitialChip`) | `W 90=00`, `W 80=00`, `W 84=00`, `W be=00`, `W c0=00`, `W 86=00`, `W 89=00`, `W 94=00`, `W 01=02`, clean FIFO |
| `GetStatus` | `W 97=page`, then read `8b`; masks pick a bit. Pages above 0xe00 also use `cf` |
| `OpenScanner` / `CloseScanner` | open the transport, then four port-style writes (64 65 44 45 / 64 65 16 17) |

Observations:

- Registers below `0x30` go to the analog front end (AFE). The layout (setup
  registers 1–5, offsets at `0x20–0x22`, gains at `0x28–0x2a`) matches the Wolfson
  WM819x family. That is a hypothesis; the chip is not identified.
- `0x83` is an index register: the same data register (`0x85`, `0x87`, `0x8d`)
  takes different meanings by index. The lamp has two indexed values.
- There is no single "exposure" register. Exposure is the CCD timing registers
  (`0x9c–0xa0`, `0xa5–0xa7`) together with the AFE gain and offset per channel.
  SCAN08 computes these values at run time; the trace will show the real numbers.

The decoder [usb_trace.py](../research/cyberview/analysis/usb_trace.py) holds the
same names in `REGISTERS`.

## Why the diagnostic line reader stays unexposed

SCAN08 selectors 1002, 1005 and 1006 call the line reader at `0x10014563`
(mode 0 start, 1 read, 2 stop):

- **Start** runs the whole setup chain (`SetGPIO e1fd/f1ff`, `SetCCDPixelNumber`,
  `SetCCDTiming`, `SetADC`, `SetImageBufferRange`, `DrivingCapabilitySetting`,
  `SetMotorType`, `SetScanAccDecFormula`, `SetAutoScan`), turns the lamp on and
  loads the tables. It sets 1708 lines at 300 dpi.
- **Read** returns one RGB line (pixel count × 3 bytes), then sleeps 200 ms. At
  line 1708 it stops and starts again on its own, with no limit.
- **Stop** frees three buffers that the normal scan code also uses (`0x10018bd0`,
  `0x10018870`, `0x10018868`, allocated by `0x10008250`), then calls `StopAutoScan`
  and `CloseScanner`.

So it moves the film motor and runs the lamp continuously, with no film or position
check and no end. Stopping it frees memory that a later normal scan still points
to. A live line view is possible, but it should be built from the register
sequence above in a bounded way, not by calling these selectors.

## Passive USB trace

Both bridges accept `--trace-usb PATH` (code: `services/native_bridge/usbtrace.h`).
The bridge patches the kernel32 import slots of the vendor modules
(`CreateFileA`, `DeviceIoControl`, `ReadFile`, `WriteFile`, `GetOverlappedResult`,
`CloseHandle`) and writes one JSON line per call, then calls the real function
with the same arguments. It sends nothing itself. Payloads are cut to 64 bytes, so
image data stays out of the log.

- **cvbridge** (CyberView TWAIN path) loads `fvc.dll` before the driver does, so
  the driver's own load reuses the hooked copy. Verified: 6 slots hooked, and
  listing sources makes no device calls.
- **aflbridge** (direct model path) hooks `fvc.dll`, `IO_PORT.dll`, `SQ_Scan.dll` and
  `SCAN08.dll` after loading SCAN08, before `ScannerDeviceIO(1)`.
- In the app, set `FRAME_USB_TRACE_DIR` before starting the service. Each driver
  session writes `usb-<time>-<pid>.jsonl` there. Keep traces under `data/`
  (ignored by git).

Decode a trace:

```bash
python research/cyberview/analysis/usb_trace.py data/traces/usb-20261030-120000-1234.jsonl
python research/cyberview/analysis/usb_trace.py data/traces/usb-20261030-120000-1234.jsonl --summary
```

Tests: `tests/native/test_native_bridge.py::test_usb_trace_logs_vendor_kernel_calls_without_changing_them`
(a stand-in FVC whose calls go to the NUL device), `tests/research/test_usb_trace.py`
and `tests/api/test_cyberview.py::test_usb_trace_is_requested_only_when_a_trace_folder_is_set`.

## First real trace (2026-10-31)

One hidden 1800 dpi 16-bit scan through cvbridge with `--trace-usb`, with film loaded
and the USB device restarted first. The driver reported "Autofocusing", then
"Preparing film scanner", and delivered no image before the 360 s timeout. The
decoded evidence is in
[usb-trace-2026-10-31.json](../research/cyberview/analysis/evidence/usb-trace-2026-10-31.json).
The 37 MB raw trace stays in `data/traces/` and is not committed.

What the wire confirmed:

- The device handle is `\\.\USBSCAN0`. The descriptor reads back VID `2770`, PID `0119`.
- Every SCAN08 call opens the device, sends the four port-style bytes
  `64 65 44 45` (offset `0x90`), does its work, sends `64 65 16 17`, and closes. The
  driver opened and closed the device 12 times in the first 3 seconds.
- Just before each close there is one more 2-byte register write whose bytes vary
  (`fb f2`, `8b f2`, `8f 1a`, `57 10`). It looks like an uninitialised buffer in the
  close path, not a deliberate command.
- `SafeInitialChip`, `SetGPIO` (`a3=02 a4=1e a1=ff a2=f1`), `DrivingCapabilitySetting`
  (`ce=00 cf=0c`) and `MotorMoveNormal` (`c0=00 80=e1 84=b1 c8=00 88=dc 89=c8 86=00`)
  appear exactly as the static map predicts.
- Status: `GetStatus(mask)` writes page `0x97=00`, then reads `0x8b`. It returns 1
  when all bits of `mask` are set. At idle the status was `0x6f`. While the motor
  ran it was `0x69`, then `0x6b` once the motor stopped (about 220 ms).

Where it hung: SCAN08 routine `0x1000c867`. If status bit 7 is clear, it starts the
motor in direction 0 for up to 4000 steps and **loops on bit 7 with no timeout**.
The motor stopped after about 220 ms, but bit 7 never set in 51,135 polls over six
minutes. Bit 7 is a position sensor that the move is meant to reach. This is the
"Preparing film scanner" hang seen several times before. Host timing cannot cause
it, because the chip drives the motor and the sensor bit by itself. The routine is
reached through `0x1000c72e`; which mechanism it homes (film carrier or focus) is
not yet known.

When the bridge cancelled, the driver went on in a second thread (RAM tables, CCD
timing, more motor moves) until the process exited. The USB device was restarted
afterwards.

## Successful traced scan (2026-10-31)

After a power cycle and reseating the film, the same command scanned one frame:
2479 × 1703 px, 16-bit RGB, 180 s in total, no failed USB calls. Evidence:
[usb-trace-2026-10-31-scan.json](../research/cyberview/analysis/evidence/usb-trace-2026-10-31-scan.json).

- **Image data is 16-bit from the scanner.** The image pass read 1712 bulk blocks of
  14,874 bytes, which is exactly 2479 px × 3 channels × 2 bytes per line. That is
  1703 lines plus 9 extra lines for the R/G/B line offsets.
- **Seven auto-scan passes ran before and during the scan:**
  - one full-width pass (2752 px), which is calibration;
  - three narrow strips (224 px);
  - two short passes;
  - then the image.
- **Calibration searches the AFE offsets per channel.** It starts at `c8`, then tries
  `00`, `80` and so on, reading lines between steps. It ends at R/G/B `fc f8 e2`.
  The gain went from 4 to 2 and then stayed at 2 on all three channels.
- **Exposure is not analog per channel.** The CCD timing (`9c–a0`, `a5–a7`) and the
  gain are the same for all three channels, and the lamp values (`8d` = `46`/`aa`,
  `93` = `06`) are shared. So CyberView's per-channel exposure must be applied in
  the tables it writes to scanner RAM (282 × 4 KB and 42 × 16 KB bulk OUT) or in host
  software. This is an inference; the table contents are not decoded yet.
- Status `0x8b` read mostly `29`, `a9` and `b9` during the scan. The failed attempt
  began at `6f`; this one began at `47` and read `7e`/`7f` before homing.

## Where a scan's time goes, and the tables

`usb_trace.py TRACE --phases` splits a session at each auto-scan start. For the
successful 180 s scan:

| Phase | Time |
| --- | --- |
| Open, chip setup, lamp | 0-7 s |
| Offset/gain calibration before the first pass (table uploads, short reads) | 7-67 s |
| Calibration pass, full width 2752 px, 62 lines | 67.6-72.4 s |
| Three narrow strips, 224 px (focus) | 73.6-80.6 s |
| Two short passes (exposure) | 82.4-103.6 s |
| The image, 1712 lines | 105.0-157.3 s |
| CyberView processing and TWAIN transfer | 157-180 s |

Table uploads (`usb_trace.py TRACE --tables DIR`) go to scanner RAM area `0x41`:
three 4 KB tables at `0x1f1000`, `0x1f2000`, `0x1f3000` (86-94 uploads each during
calibration; likely one per channel, gamma or lookup) and three 16 KB tables at
`0x1f4000`, `0x1f8000`, `0x1fc000` (14 uploads each; likely per-pixel shading). Traces
from 2026-10-31 hold only 64 bytes of each; the tracer now logs bulk OUT in full, so
the next traced scan gives the whole tables.

## Vendor bug: random register write on every close (found 2026-10-31)

IO_PORT's `CloseTransferPort` on USB (`0x100013a5`) calls
`SystemRequest(0, 2, 0xB0, 0, 2, &stack)` with an uninitialised stack slot, so each
close writes a random register. It explains the stray "uninitialised-looking" writes noted
above, white frames that persisted until a power cycle, and likely the earlier
"Preparing film scanner" hangs. Both bridges now zero those bytes
(`services/native_bridge/vendorfix.h`). Details in [standalone-plan.md](standalone-plan.md).

## Not yet known

- The real values written during calibration, exposure and a scan (the trace gives them).
- The meaning of each status bit in `0x8b`. Seen so far: bits 0–1 clear while the
  motor runs; bit 7 is the sensor the homing move waits for.
- The firmware side: whether these registers are the ASIC itself or a microcontroller in front of it.
- Whether to drive the scanner directly over WinUSB. That would replace the
  usbscan binding and stop CyberView working, so it is not planned.
