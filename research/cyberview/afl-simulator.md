# Original CyberView against a simulated PF1800 AFL

Run date 2026-10-28 UTC. **Result: original CyberView X SF v1.30 detected,
opened, prescanned and scanned to a TIFF through FRAME's simulated model-37
module.** This is GUEST OBSERVED application behavior against a SIMULATOR.
It verifies the reconstructed host-API contract between CyberView and an AFL
model module. It says nothing about the physical scanner's USB protocol,
optics, transport or image quality.

Evidence: [afl-simulator-2026-10-28.json](analysis/evidence/afl-simulator-2026-10-28.json),
[prescan screenshot](analysis/evidence/cyberview-sim-prescan-2026-10-28.png),
[scanned image001.tif rendered](analysis/evidence/cyberview-sim-scan-image001-2026-10-28.png).
Tests: `tests/research/test_afl_simulator.py`.

## Why the simulation is a module, not a USB device

The AFL class binds BeneScan model 37 → `SCAN08.dll`. That file is absent from the
official package; see [runtime-baseline.md](runtime-baseline.md). CyberView never
reaches USB for an AFL, so a guest-visible USB device could not be recognized as
one. The layer that can be simulated is the model-module interface BeneScan
calls on every model DLL:

```c
int __cdecl ScannerDeviceIO(int selector, void *param);
```

The user decided that reverse engineering this unmaintained software for
interoperability and repair is acceptable. The CyberView EULA's section 4
prohibition is recorded alongside that decision.

## Contract recovered (STATIC, from SCAN08-lineage LC.dll)

Ghidra 12.1.4 headless on LC.dll (SHA-256 `5486ACE5…`). Selector switch
`0x1000f020`. Handlers:

| Selector | LC.dll behavior | Simulator |
| --- | --- | --- |
| 1 / 2 | init / close | 1 |
| 3 / 5 | detect / open. Fill vendor(8) `PIE`, product(16) `SF Film Scanner`, revision(4), then 3 zero bytes (`0x100115f0`, `0x1000f930`) | same identity |
| 0x16 | copy the 0x84-byte capability block (`0x100122c0`) to `param+1`. DPI at +0x24/+0x26, full frame px at +0x28/+0x2a, model code at +0x74 (LC `0x2a`) | LC layout, 1800 dpi, 2496×1708, **model `0x25`** |
| 0x15 | status. `param[0]` request mask, `param[1]` result | see below |
| 0x20 | 4-byte flags + 0x48-byte scan block → scan with strip callback (`0x10010f90` → `0x10010640`) | synthetic image in strips |
| 0x0c | 1 | 1 (CyberView: `GetNowFilmLocation`) |
| 0x11/0x1b/0x21 | three u16 = 100 | same |
| 0x14, 0x23, 0x2a | store pointers / fill small block / status-notify window | same |
| 9, 10 | 1 | 1, plus a logged simulated frame advance |
| other | 0 | 0, logged |

Scan callback: `cdecl`, one argument. The strip block holds mode +4, width +8,
height +0xc, lines +0x14, abort flag +0x18 (checked at LC `0x10010b38`), last +0x1c,
data pointer +0x20 and bytes/line +0x28.

LC.dll also exposes the SCAN08 family's **device commands** (STATIC). Each is a
6-byte CDB-like block through `0x10011330`:

* `0x15` set window: 16 bytes, dpi and mode.
* `0x0A` with sub-codes 0x13/0x14/0x15: per-channel exposure, offset and gain.
* `0x0F` read width and height.
* `0xDD` status.
* `0xE2`–`0xE8` vendor commands: read gains, lamp, power, close.

These belong to the 1800P/LC path. They are recorded as candidates only, never
issued.

## CyberView-side semantics learned (GUEST OBSERVED + STATIC)

* Status (`0x100bb1a0` GetScannerStatus, mask `0x1f`):
  * bit 0 → 4, which the ScannerStatus timer `0x100373b0` treats as **film inserted**
    and answers by starting an automatic Final Scan;
  * bit 5 → `0x10`;
  * bit 1 → ready (2, or 1 with bit 2), with bit 3 OR-ed in.
  * `IsDocumentInFeeder` (`0x100bb240`) reports film present when bit 4 is clear.
* Idle loop: every ~1.5–2 s, status (`0x15`) then `GetNowFilmLocation` (`0x0c`).
* Scan request (selector 0x20), **as CyberView actually sent it**:
  * dpi u16 +0x00;
  * window floats in inches: left +0x04, top +0x08, width +0x0c, height +0x10;
  * mode +0x14;
  * exposure u16×3 +0x18 (140), offset u16×3 +0x1e (100);
  * three LUT pointers +0x24;
  * gain bytes +0x30;
  * callback +0x40;
  * 255 lines per strip +0x44.

  Decoder: `analysis/afl_contract.py`.

## Runs

1. **Simulator only.** Detect and open succeeded (selectors 1, 3, 2, then 1, 3, 5,
   0x16 ×2, 0x14, 0x23). Then an access violation hit `CyberViewX.ds+0xcf74`.
   Cause: model 37 loads film terms from `GAMMA\*.ft` (jump table at
   `0x100222f3`), and **the official package ships none there**. The film menu
   builder `0x1001e580` then dereferenced an empty list. This is a second
   packaging gap, independent of the simulator. Models 34 and 42 use
   `Gamma\3600U`; 46, 48, 54 and 60 use `Gamma\3650U`.
2. **With `GAMMA\Original\*.ft` copied to `GAMMA\` (test-only).** The main window
   opened. The simulator's first status answer `0x0b` set bit 0, so CyberView
   started an automatic Final Scan and waited at "Preparing film scanner".
3. **Status answer `0x0a` (bits 1 and 3).** The main window was idle: 1800 dpi,
   1.386 × 0.948 in, Location 1. *Prescan Current Frame* showed the synthetic
   frame. The orange band confirms R,G,B channel order through the strip format.
   *Scan Current Frame to File* at 300 dpi wrote `image001.tif`: 416×284, RGB
   8-bit, 300 dpi, SHA-256 in the evidence JSON. This matches the simulator's
   geometry exactly.

## Limits

* Every response is SIMULATED. LC.dll layouts are reused because LC is the
  only SCAN08-lineage module available. The real AFL module may differ, for
  example in other capability fields, roll and frame-count behavior, or
  transport selectors 9 and 10, which were never exercised.
* Exposure, offset and gain values were received but not applied. The image is
  synthetic.
* The film-term copy and the simulator DLL exist only in the guest overlay.
  The production `SimulatedScannerBackend` is untouched.

## Reproduce

```powershell
powershell -File research/cyberview/simulator/build.ps1        # x86 MSVC 2022 Build Tools
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/guest_lab.py refresh-media
python research/cyberview/analysis/guest_lab.py insert --media evidence
python research/cyberview/analysis/guest_lab.py insert --media tools
# in the guest, via Run: D:\FILMTERM.CMD, D:\INSTSIM.CMD, D:\BASELINE.CMD; use CyberView; D:\COLLECT.CMD
python research/cyberview/analysis/guest_lab.py read-evidence
```

`SIMSET.CMD key value` changes simulator answers live: `StatusBits`, `FilmLoaded`,
`Present`, `StripDelayMs`. `ENDCV.CMD` ends `PfsLoader.exe` so the DLL can be
replaced.
