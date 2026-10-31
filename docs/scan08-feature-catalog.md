# PF1800 AFL scanner module: complete feature catalogue

Every feature of the installed AFL scanner stack, and what CyberScan X can do with
it. Covers `SCAN08.dll` 1.0.3.6 (the module the native bridge pins) and the three
libraries beneath it. Written 2026-10-30.

Evidence labels:

- **Observed**: seen on this PF1800 AFL, in a scan through the app, or in the
  driver's own log on this PC.
- **Recorded**: listed in `services/scanner_host/native_validation.json` by the
  ChatGPT session. No raw trace of those runs is in the repository. See
  [cyberview-parity.md](cyberview-parity.md).
- **Static**: read from the code only. Not run.

Reproduce the machine-readable inventory without running vendor code:

```powershell
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/scan08_catalog.py --output research/cyberview/analysis/evidence/scan08-catalog-2026-10-30.json
```

The script checks the module's SHA-256 first. It reads both dispatch tables from
the machine code, follows every command into the module's own functions, and
records the scanner functions, files and strings each command reaches. Earlier
address-level notes are in
[installed-native-investigation.md](../research/cyberview/installed-native-investigation.md).

## The stack

```
CyberScan X  ->  aflbridge.exe (FRAME, x86)  ->  SCAN08.dll  ScannerDeviceIO(selector, parameter)
  ->  SQ_Scan.dll (28 exports, scanner ASIC)  ->  IO_PORT.DLL (17)  ->  FVC.DLL (12)  ->  usbscan.sys
```

| Module | SHA-256 (prefix) | Role |
| --- | --- | --- |
| SCAN08.dll | `da413438c0136338` | AFL model logic: detection, lamp and CCD calibration, transport, focus, film-base, exposure, scanning, logs |
| SQ_Scan.dll | `55a865e7119608d0` | SQ Technology ASIC commands (28 exports): motor, lamp, CCD timing, ADC, tables, image transfer |
| IO_PORT.DLL | `768442427b7bbf28` | Transport selection: USB, plus FireWire (SQ1394.DLL) and parallel port paths |
| FVC.DLL | `bbd02aed88e1a755` | Raw `\\.\USBSCANn` reads and writes |

## Every DLL CyberView X uses to reach the scanner

From each binary's imports, the module names inside it, and the modules that were
loaded in CyberView's process on 2026-10-30. Only two DLLs touch the device:
SCAN08 (it opens `\\.\USBSCANn` to read the USB descriptor during detection)
and FVC (every read, write and control request after that).

| Step | File | Location | Role | Touches the scanner |
| --- | --- | --- | --- | --- |
| 1 | PfsLoader.exe | `CyberViewX_MF` | The "CyberView X" program: a small TWAIN host that opens the driver with its UI | No |
| 2 | DSMObject.dll, bBits.dll | `CyberViewX_MF` | PfsLoader's TWAIN helper and image buffers | No |
| 3 | twain_32.dll | `C:\Windows` | Windows TWAIN source manager. It also loads `wiadss.dll` and `sti.dll` for its WIA bridge; this scanner doesn't use them | No |
| 4 | CyberViewX.ds | `CyberViewX_MF` | CyberView itself: UI, film terms, ROC/GEM, saving. Its only `DeviceIoControl` is `FSCTL_SET_SPARSE` on its own temp files | No |
| 5 | BeneScan.dll (and BeneRaw.dll, a byte-identical copy) | `CyberViewX_MF` | Model dispatcher: a 19-entry table maps model codes to modules and loads each to detect hardware | No |
| 6 | RawScan.dll | `CyberViewX_MF` | Vendor "virtual scanner" that plays back a raw file (`iWidth`/`iHeight` settings); loaded alongside, not used for real scans | No |
| 7 | **SCAN08.dll** | `CyberViewX_MF` | PF1800 AFL model logic (this catalogue) | **Detection only** |
| 8 | SQ_Scan.dll | `SysWOW64` | SQ Technology scanner-chip commands | No (builds commands) |
| 9 | IO_PORT.dll | `SysWOW64` | Chooses the transport (USB here) | No |
| 10 | **FVC.dll** | `SysWOW64` | `ReadFile`, `WriteFile` and `DeviceIoControl` on `\\.\USBSCANn` | **Yes, all traffic** |
| 11 | SQ1394.DLL | `SysWOW64` | FireWire transport (`\\.\Scanner0`), loaded as an IO_PORT dependency, unused | No |
| 12 | usbscan.sys | `System32\drivers` | Microsoft's still-image USB driver, bound by Hamrick's `scadrv60.inf` (VueScan) | Kernel |

Image-processing libraries CyberView loads, none of which talk to the scanner:
`imer.dll`/`imerD.dll` (file writing), `DRAGPIE.DLL` (ROC and GEM), `KFTERM.DLL`
(film terms), `KODAKCMS.DLL` (colour management), `BDIP.DLL` (auto contrast and
levels), `IRER.DLL` (image readers), `DICELib.dll` (infrared cleaning for other
models), `CrashRpt.dll`, `zlib.dll`. Other models' modules in the same folder:
`PF3610AFL.dll` (writes `PF3610AFL_IO_LOG.TXT` when active), `Pf3600Pro.dll`,
`RFS3600.dll`, `ProDice.Dll`, `PF7250PRO3*.dll`.

VueScan's own trace (`Pictures\VueScan\vuescan_crash.log`) shows its `pie1` backend
trying to load this same `SCAN08.dll` before falling back to its built-in driver.

## Behaviour that applies to every command

| Behaviour | Evidence | What it means for CyberScan X |
| --- | --- | --- |
| **Busy wait.** On entry, every command sleeps in 10 ms steps while global `0x10018b98` is set. The scanning threads set it. | Static | A stuck operation blocks every later command, status queries included. The app must not use a status query to probe a hung driver. Watchdogs must live outside the driver process. |
| **Always-on log.** `%TEMP%\PF1800AFL.log` gets a header at start-up (model, USB, CCD, SDK, firmware), the lamp calibration sweep, frame geometry, and one section per scan. | Observed (14 scans logged on this PC) | Read it passively. A diagnostics panel needs no device I/O (see Roadmap). |
| **Calibration cache.** `%TEMP%\AFLScanner.CFG` (16,530 bytes here) is read by every scanning path. When it's missing, a full lamp and CCD calibration runs and the file is written. | Observed (file present, updated with each session) | Deleting it forces recalibration. "Recalibrate scanner" could be offered as an explicit, explained action. Never delete it silently. |
| **Modal message box.** A RAM self-test (256-byte write and read-back through `RamRWBulk`) on every scanning path shows "RAM Test ERROR!" and fails on a mismatch. | Static | The CyberView bridge reports such dialogs. The native bridge must too: a hidden modal box would hang the session. |
| **Worker threads.** Scanning creates raised-priority threads (`SetPriorityClass`, `SetThreadPriority`). | Static | Expected. Don't run the helper at reduced priority. |
| **CCD override file.** `%TEMP%\PF1800AFL.ini` `[Check CCD] CCDType` forces CCD 548 (`0x30`) or 533 (`0x21`). Without it the module measures a line and decides. | Static. Not present here; the log shows CCD 533 | Never write it. Wrong timing could damage scans. Report the detected CCD from the log instead. |
| **Factory alignment output.** `c:\bartinfo\align.tif`, `align_data.txt`, `align_diff.txt`, `align_result.txt`, `align_ptn3_1/2.txt`, written only when an internal debug flag (`+0x58` of the alignment object) is set. | Static | Dormant factory tooling. Nothing to expose. |
| **Last error code.** Global `0x100187d8`: command 18 reads it, command 4 resets it to `0x20881`, and `0x20401` (failed lamp or calibration check) triggers recalibration. | Static | Read command 18 after a failure, to show a real reason instead of "driver error". |

## Every command

Selectors are decimal. The native bridge uses 21 and 22 for status and
capabilities (written `0x15` and `0x16` in its source). "Use" is the
recommendation for CyberScan X.

| Selector | What it does | Parameter | Effect on the scanner | Evidence | Use |
| --- | --- | --- | --- | --- | --- |
| 1 | Allocate the module's working buffers | none | None | Observed (native start-up) | **In use** |
| 2 | Free the buffers | none | None. Doesn't release the device | Observed | **In use** at shutdown |
| 3 | Find the scanner: walk `\\.\USBSCAN0..`, match the USB ID, read the identity | identity block. A string pointer at `+0x1C` is required | Writes registers. Not passive | Observed | **In use** |
| 4 | Reset the last-error code to `0x20881`. Ignores its parameter | ignored | None | Static | Call before an operation so command 18 reports only new errors |
| 5 | Open: firmware check, lamp, homing (`MotorMoveNormal` until the sensor) | identity from 3 | **Lamp on, may move film** | Observed | **In use** |
| 6 | Version string. Type 1 gives firmware "N.00" (here 4); type 2 gives "0.00" | `{u32 type; char[4] out}` | None | Static | Show firmware in Settings. The log already has it, so it isn't needed |
| 7 | No-op, returns 1 | — | None | Static | None |
| 8 | Eject: transport until the sensor clears | `{u16 direction (1 back, 2 forward), u16}` | **Moves film out** | Recorded (forward, user confirmed) | **Forward eject: candidate.** Backward: not offered |
| 9 | Move frames, then optical frame alignment (border scan, as in 23) | `{u16 direction, u16 count}` | **Moves film, lamp, short scan** | Next observed (TWAIN menu command); next/previous recorded (native) | **Next: in use.** Previous: native only; it hung through CyberView |
| 10 | Fine movement by steps, with alignment | `{u16, u16 steps}` | **Moves film** | Static | Possible "nudge frame" for misaligned frames. Needs a supervised test |
| 11 | Long travel: runs 9 with count 99, then checks status | as 9 | **Runs the whole roll through** | Static | Not offered. Eject (8) covers the use |
| 12 | Current frame on a strip (0 when not a strip) | `u32 *` out | Status read | Recorded | **Show the frame counter**; check position after moves |
| 13 | Mount slot, or 40 (capacity) for a strip | `u32 *` out | Status read | Static | Show roll capacity |
| 14 | Autofocus: scans a small area, computes sharpness, stores the best step | `float[2]` point in inches | **Lamp, focus motor, scan** | Recorded (step 2) | **Candidate.** Your log shows focus step 0 in every scan, so autofocus has never run here |
| 15 | Read the stored focus step | `u32 *` out | None | Recorded | Show the focus step |
| 16 | Store the focus step (applied at the next scan) | `u32` value (passed by reference) | None until the next scan | Recorded | Manual focus slider, after autofocus is proven |
| 17 | Measure film-base density (DMin) for R, G, B | `u16[3]` out (100 each on failure) | **Lamp, scan of the film base** | Recorded (147/197/309; your CyberView value is 151/201/318) | **Candidate.** "Measure film base" for native negative inversion |
| 18 | Read the last error code | `u32 *` out | None | Static | **Use** after every failure |
| 19 | Scan core: calibrate if needed, set exposure and focus, scan, deliver strips | 0x48-byte scan block | **Lamp, focus, scan** | Observed (through 32) | Through 32 |
| 20 | Register begin, end and progress callbacks | `void *[3]` | None | Static | Optional. Register all three or none; a lone begin callback crashes at the end |
| 21 | Masked status: film present, strip or mount, and latching the film type | `{u32 mask, u32 out}` | Status read | Observed (`0x0e` loaded, `0x08` empty) | **In use.** "Film loaded" indicator |
| 22 | Capability block (model 37, 1800 dpi, maximum 2586 × 1708) | length-prefixed, at most 0x85 | None | Observed | **In use** as the model check |
| 23 | Frame-border alignment: scan the border, compute offset, reposition | none | **Moves film, scan** | Static | Candidate "realign frame" for frames that land off-centre |
| 24 | Model code (37) | buffer | None | Static | Model check |
| 25 | No-op, returns 1 | — | None | Static | None |
| 26 | No-op, returns 1 | none | None | Static | None |
| 27 | DMin measurement, then border alignment (17 + 23) | as 17 | **Moves film, scan** | Static | Covered by 17 and 23 |
| 28–31 | Not implemented (returns 0) | — | — | Static | Never call |
| 32 | **Scan request:** flags word plus the 0x48-byte block (see next section) | `{u32 flags; block}` | **Lamp, focus, scan** | Observed (native, 1800 and 600 dpi) | **In use** |
| 33 | Read the module's colour balance (default 100/100/100) | `u16[3]` out | None | Static | Diagnostics only |
| 34 | Not implemented | — | — | Static | Never call |
| 35 | Extended capability block (fixed: 0x28, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0) | length-prefixed | None | Static | Fold into the capability record. Field meanings unknown |
| 1001 | Raw motor move: `MotorMoveNormal` with a caller-supplied drive setting | drive block | **Unbounded motor movement** | Static | **Never expose** |
| 1002 | Start the diagnostic line reader (reads the calibration cache, logs the CCD) | none | **Lamp, CCD** | Static | Not offered (factory diagnostic) |
| 1003 | Run transport until the sensor changes (register 6, 5 s limit per phase) | none | **Moves film** | Static | Not offered. Load and eject cover it |
| 1004 | Apply the stored focus by stepping the motor (`0xE9` command per step) | none | **Focus motor** | Static | Not needed. Scans apply focus themselves |
| 1005 | Read lines from the diagnostic reader | buffer | **CCD** | Static | Possible live line view. Not offered without a bounded design |
| 1006 | Stop the diagnostic reader | none | Lamp state | Static | Pairs with 1002 |
| 1007 | Read ASIC status register 3 | none | Status read | Static | None |

### Scan request (selector 32)

The flags word comes first:

| Flag | Meaning | Evidence | Use |
| --- | --- | --- | --- |
| 0 | Normal scan through the scan core | Observed | In use |
| bit 0 (`1`) | **Vendor auto-exposure.** Scans 300 dpi 8-bit RGB first, computes per-channel exposure (`0x10004a7f`), then scans with it. When the request itself is 300 dpi 8-bit, the pre-pass image is delivered directly. | Static | **Candidate:** "Auto exposure" toggle for native scans. Needs one supervised scan |
| bits 1–6 | Rejected: the call returns 0 without scanning | Static | Never set |

The 0x48-byte block (from the existing investigation, confirmed here):

| Offset | Field | Native bridge today | Candidate |
| --- | --- | --- | --- |
| 0x00 | DPI. Buckets 300/360/450/600/900/1800 | 1800, 600 and 300 recorded | 360, 450 and 900 need a test each |
| 0x04 | Left, top, right, bottom in inches (maximum 2586 × 1708 px at 1800) | Default crop | **Custom scan area**: any box within the limits |
| 0x14 | Mode: 7 = RGB 16-bit containers, 3 = RGB 8-bit, 6 = grey 16, 2 = grey 8 | 7 and 3 recorded | Greyscale for black-and-white film needs a test |
| 0x18 | Per-channel exposure (colour balance; the film-base values come here) | 100/100/100 | Feed the DMin result from 17. Your CyberView used 153/205/323 |
| 0x1E | Highlight enhance per channel (normal 100) | 100 | Exposure for dense negatives |
| 0x24 | Three 4096-entry lookup tables | Identity | Keep identity. Tone belongs in the edit recipe |
| 0x30 | Shadow enhance per channel | 0 | Lift shadows in thin negatives |
| 0x35 | Film class: greater than 0x10 selects negative calibration | 0x20 (negative) | 0x10 for slides and positive film needs a test |
| 0x40 / 0x44 | Strip callback / lines per strip | Set | — |

### What a scan writes in the log (observed values here)

| Field | Value on this unit | Meaning |
| --- | --- | --- |
| Model / USB / CCD / SDK / firmware | 37 / USB 1.1 / 533 / 1,0,3,6 / 4 | Hardware identity. USB 1.1 explains the transfer speed |
| Lamp sweep | Lamp level 245 down to 65, until the CCD stops saturating | Lamp calibration. A rising final level over months would indicate an ageing lamp |
| `wStartPos`, `wLeftEdge`, `wBkLinePos`, `wCaliBorPos`, `wFilmHolePos` | 1581, 158, 70, 81, 284 | Transport and frame-detection geometry |
| Film type / media | Film Strip / Negative Film | What the status latch decided |
| Focus step | 0 | No autofocus has run |
| Colour balance | 153 / 205 / 323 | The orange-mask exposure CyberView passed |
| Highlight / shadow enhance | 100 / 0 | Defaults |
| Gain / DC | 2 / 252, 248, 227 | Analogue gain and black-level offsets from calibration |

## SQ_Scan.dll (scanner ASIC library)

SCAN08 imports 21 of its 28 exports: `OpenScanner`, `CloseScanner`,
`MotorMoveNormal`, `SetScanAccDecFormula`, `SetMotorType`, `RamRWBulk`, `SetLamp`,
`SetGPIO`, `SetCCDPixelNumber`, `SetCCDTiming`, `SetADC`, `SetLineOffset`,
`WriteTable`, `SetImageBufferRange`, `SetAutoScan`, `GetAutoScanImage`,
`StopAutoScan`, `GetStatus`, `DrivingCapabilitySetting`, `SafeInitialChip` and
`QuickInitialAutoScan`. `SafeInitialChip` and `StopAutoScan` are two names for
one function: "safe chip initialise" stops any running scan.

These seven are never called by the AFL module: `MotorBackNormal`,
`MotorBackAccDec`, `SetMotorAccDecFormula`, `RamRWByte`, `SetPowerSave`,
`FastInitialAutoScan` and `Quick1InitialAutoScan`. They are reachable only by
calling SQ_Scan directly, which would bypass the model's calibration and bounds.
**Not for CyberScan X.** A lamp power-save could matter for long sessions, but
nothing shows the AFL wires it, and the lamp is managed by SCAN08.

## IO_PORT.DLL and FVC.DLL

- **USB** is the only path SQ_Scan uses here: `OpenTransferPort` →
  `fvc!openusb` → `\\.\USBSCANn`, then `general_ReadLine`/`WriteLine`/`SendData`/
  `ReceiveData` → `usbinp`/`usboutp` (`ReadFile`/`WriteFile`) and `SystemRequest`
  (`DeviceIoControl`).
- **FireWire** (`SQ1394.DLL`, SBP-2) and **parallel port** (SPP/EPP) paths exist
  for other scanners. They are not used by this unit.
- **Hardware compression** (`general_SetupCompressParameter`, `general_Decompress`,
  FVC `FVCConfiguration`/`FVCBypass`/`FVCDecompress`) writes registry keys. It
  isn't called on the AFL path. **Never call it.**
- **Message boxes**: IO_PORT warns with a modal box on a version mismatch
  ("Version error or not call GetIOPortVersion") and on file-version checks. A
  replaced or mismatched DLL would hang a hidden session, which is one more
  reason the native bridge pins the module hash.

## CyberView-level features (for comparison)

These live in `CyberViewX.ds`, not in SCAN08. CyberScan X can only get them
through the TWAIN bridge, or reimplement them on the 16-bit original.

| CyberView feature | Where | CyberScan X equivalent |
| --- | --- | --- |
| Film terms (`.ft` curves, Kodak 200 etc.) | GAMMA folder | Done: native edit recipe can apply installed film profiles |
| Prescan current / 1–36 / 1–50 / all | Menu 32794–32851 | Native 300 dpi prescan recorded. Roll prescan = prescan + next, repeated |
| Scan current / selected / all, to host or file | Menu 32874–32853 | Done: "Scan N frames" |
| Forward / backward one frame, forward / backward eject, go to frame, reset frame count | Menu 32861–32884 | Next done. Others: see selectors 8, 9, 12 |
| DMin, focus | Menu 32854, 32855 | Selectors 17, 14 (candidates) |
| ROC (colour restoration), GEM (grain), ICE | Settings, menu 32877–32886 | Not in SCAN08. The AFL has no infrared channel, so no ICE. ROC and GEM are CyberView software filters that could be rewritten as edit-recipe steps |
| Auto exposure, auto gamma, uniform colour | `[SETUPDLG DEFAULT PAGE]` | Vendor auto-exposure via flag bit 0; levels are already in the recipe |
| Save Raw When Scan (stage dumps `1_Raw.raw`…`4_AfterUC.raw`) | `[Others Setting]` | Not needed natively: the native original already precedes CyberView's processing |
| Multi-scan, multisample pass | `[Others Setting]`, `[SETUPDLG SCAN PAGE]` | Not in SCAN08. CyberScan X could average N native scans of the same frame for lower noise (multi-exposure stacking) without vendor support |
| Auto calibrate (hidden menu), save ini, prescan simulator, virtual button key (QA) | Menu 32906, 32881, 32895, 32909 | Not offered |

## Roadmap for CyberScan X

**Ready now, no scanner I/O:**

1. Scanner diagnostics panel from `%TEMP%\PF1800AFL.log`: model, CCD,
   firmware, USB, lamp calibration level, frame geometry, and the last scan's
   colour balance, gain and DC. (Implemented with this catalogue.)
2. Report the calibration cache's presence and age.
3. A clearer error text when native selector 18 returns a code (bridge change).

**Need one supervised scanner test each, then promotion in `native_validation.json`:**

4. Vendor auto-exposure (flag bit 0) for native scans.
5. Film-base measurement (17) feeding the native exposure fields and the
   negative-inversion film base.
6. Autofocus (14), then a manual focus step (16) with a before/after sharpness check.
7. Custom scan area (block 0x04) and the remaining native DPI buckets (360, 450, 900).
8. Greyscale modes for black-and-white film, and film class 0x10 for slides.
9. Frame realignment (23) and fine nudge (10) for frames that land off-centre.
   **Built:** `film nudge back|forward N` (selector 10, 1–300 steps, must stay on the
   same frame) drives the stitched 35 mm auto-align scan. It stays off until one
   supervised test adds `nudge` to `native_validation.json`. See
   [auto-align.md](auto-align.md).
10. Frame counter from 12 in the UI.
11. Multi-scan averaging in CyberScan X (software, built on validated 32).

**Never expose:** 1001 (raw motor), 11 (99-frame travel), 1002–1006 (diagnostic
line reader), 28–31 and 34, the CCD override file, direct SQ_Scan/IO_PORT/FVC
calls, and the compression and registry paths.
Why the line reader is unsafe, and the full register and USB wire map, are in
[scanner-protocol.md](scanner-protocol.md).
