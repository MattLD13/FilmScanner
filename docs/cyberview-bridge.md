# CyberView X bridge (headless TWAIN)

CyberScan X scans with the installed **CyberView X - MF** TWAIN driver
(`CyberViewX.ds` 1.4.0.0, `SCAN08.dll` 1.0.3.6) and keeps CyberView's window
hidden. All scanner I/O stays inside Pacific Image's driver. FRAME sends no USB
command of its own. Every result below is hardware evidence from the PrimeFilm
1800 AFL (USB `2770:0119`) on 2026-10-30, unless marked as static analysis.

```
CyberScan X (Electron / browser)  ->  FRAME service (Python, /api/cyberview/*)
  ->  cvbridge.exe serve (x86, stdin/stdout JSON lines)  ->  twain_32.dll  ->  CyberViewX.ds
```

## Build and run

```powershell
npm run build:bridge          # x86 MSVC 2022 Build Tools; writes services/cyberview_bridge/bin/cvbridge.exe
npm run build                 # web client
npm run cyberscan             # Electron window with the CyberScan X front end
```

Optional, once, from an administrator PowerShell, so a stalled scanner recovers
without unplugging:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-scanner-reset.ps1
```

The script registers `\FRAME\Reset PF1800 AFL`. The task has no trigger. When
started, it restarts only USB devices `2770:0119`. The service starts it with
`schtasks /Run` before a new driver session, and once more if a scan stalls.

## How hidden mode works

Static analysis of `CyberViewX.ds`. The driver reads `[Non UI Information]` from
`%APPDATA%\PIE\MF\CyberViewX.ini` when the TWAIN source manager loads it. It
hides its UI when `Hide UI=1` and `Host Handle` names a live window (or
`Is SmartTest=1`). The bridge writes those keys before it loads the source
manager, then opens the source and enables it with `ShowUI=FALSE`.

Hidden mode is incomplete in practice. The MFC main window sometimes stays
visible, and sometimes it is only minimized. The progress dialog also appears.
The bridge hides every driver window except a plain message box. It forwards the
progress text as `driver_status` (for example "Preparing film scanner",
"Scanning frame 002, block 01", "Measuring the film's minimum density (D Min)
and location"). A message box is left visible and is reported as
`driver_dialog`.

## What a hidden scan delivers

| Observation | Value |
| --- | --- |
| Image | Current frame, 2479 × 1703 px, RGB, 16 bits per sample, 1800 dpi |
| Processing | Already inverted with CyberView's selected film term (here Kodak 200) and its auto exposure. Cropped to CyberView's default crop box. |
| Resolution / depth negotiation | `ICAP_XRESOLUTION` lists only 100 dpi, and setting other values fails. Settings-file overrides of DPI and depth were also ignored. Every scan arrives at native 1800 dpi, 16-bit. |
| Timing | First scan of a session: 170–180 s (warm-up, focus, scan, about 6 s transfer). Later scans in the same session: about 60–70 s. |
| Transfer | `DAT_IMAGEMEMXFER`. The bridge writes an uncompressed little-endian TIFF. |

The service keeps that TIFF unchanged as the original. It records the
original's SHA-256 and writes preview, thumbnail and JSON sidecar files next to
it. Adjustments (exposure, contrast, saturation, temperature, rotation, mirror)
are a recipe. The screen uses an SVG `feColorMatrix`, and exports apply the same
matrix to the 16-bit samples (`color_matrix()` in
`services/api/cyberview_routes.py`).

## Film transport

TWAIN auto-feed (`CAP_AUTOFEED`) cannot be set, so `CAP_XFERCOUNT` > 1 scans the
same frame again. CyberView's own menu commands work instead. The bridge sends
`WM_COMMAND` to the hidden main window (menu resources 5160 and 5231):

| Command | Id | Result |
| --- | --- | --- |
| Forward One Frame | 32867 | Works. Took 3.4 s, and the next scan reported "Scanning frame 002". This is how "Scan N frames" advances. |
| Backward One Frame | 32866 | Hung the driver for more than 6 minutes, after which the bridge was killed. **Not offered.** |
| Forward / Backward Eject | 32864 / 32861 | Not tested. Not offered. |

## Driver sessions and the stuck "Preparing film scanner"

- Opening and closing the driver several times without scanning left the AFL stuck
  at "Preparing film scanner" until it was power-cycled.
- After any session that scanned, the next fresh session stalled. Before the
  calibration fix it stalled at "Preparing film scanner". After it, it stalled
  at "Measuring the film's minimum density (D Min) and location". Within one
  session, repeated scans always worked.
- `pnputil /restart-device` on the scanner (as administrator) cleared a stall.
  The next session started scanning after about 30 s.

The resulting design:

1. The service keeps **one driver session open** (`cvbridge serve`) for all
   scans, the way CyberView does. Settings → Release scanner closes it so
   CyberView X itself can be opened.
2. With the reset task installed, every new session starts with a USB restart.
   If a scan still produces nothing for 300 s, the service restarts the device
   and continues with the remaining frames.
3. If the service dies, the bridge notices that its parent process has gone. It
   then closes the driver properly. Before this fix an orphaned bridge kept the
   scanner.

## CyberView's settings file

The driver rewrites the whole file when it closes, and it also rewrites it as
soon as the source manager loads it. The bridge copies the file aside before
loading anything. After the bridge process exits (a helper waits for it), the
following keys are restored from that copy:

- the hidden-mode flags (`Hide UI`, `Host Handle`, `Pfs Loader Call`, `Pfs Loader Handle`);
- window layout keys (any key containing `Layout` or `Maximized`);
- film-base and focus calibration (`DMin Value R/G/B`, `Focus Value *`, `Block Number`);
- any `--set` override.

Hidden sessions write default calibration (DMin 100/100/100) even when their
scans are good. A session started with those defaults produced unusable colour
(one frame all white, the next dark blue), so only CyberView itself changes
calibration. `First Current Location` is left as the driver wrote it. A copy
left behind by a crash is merged the same way on the next start.

## Tests

- `tests/api/test_cyberview.py` runs the API against `tests/scanner/fake_cvbridge.py`.
  The fake speaks the same JSON-lines protocol. It never loads a driver or touches
  the scanner.
- Hardware runs on 2026-10-30 used the scratch harnesses described above. Personal
  scan images are not part of the repository.

## Limits

- Output is CyberView-processed, not raw. The film term, auto exposure and crop
  come from CyberView's saved settings. To change them, open CyberView X, adjust,
  scan once, close it, then return to CyberScan X.
- No resolution or depth choice: 1800 dpi, 16-bit only.
- Previous frame and eject are not available from CyberScan X.
- The reset task needs administrator rights once. Without it, a stall still
  needs the scanner switched off and on.
