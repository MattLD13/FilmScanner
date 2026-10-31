# CyberScan X

CyberScan X runs in FRAME's Electron shell. It supports a direct AFL module
backend for current-frame acquisition and the existing hidden CyberView TWAIN
backend for batch/forward operation. See [native capture](native-scanner.md)
and the [TWAIN bridge](cyberview-bridge.md) for evidence and limits.

## Run

```powershell
npm run build:bridge   # once; x86 TWAIN bridge
npm run build:native   # once; direct AFL module bridge
npm run build          # web client
npm run cyberscan      # Electron window, starts or attaches to the local service
```

Run the `npm` commands from the FRAME folder. To open CyberScan X like any other
program, add Start menu and desktop shortcuts once (per user, no administrator
rights):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-cyberscan-shortcut.ps1
```

The shortcut starts this checkout's Electron shell with `--cyberscan`. In that
mode it has its own icon (`apps/desktop-shell/assets/cyberscan.ico`), taskbar
group, logs (`%APPDATA%\cyberscan-x\logs`) and single-instance lock, separate
from the FRAME desktop app.

In a browser, use `http://127.0.0.1:8765/?workspace=cyberscan` while `npm start`
runs. `npm run preview:skin` serves an offline demo (`&demo=1`) with sample photos.
That demo makes no network requests and cannot scan.

## What it does

- **Scan**: scans the current frame, or the next 2–36 frames. The film is
  advanced with CyberView's "Forward One Frame" between scans. Progress shows
  the driver's own status ("Preparing film scanner", "Scanning frame 002"), the
  lines received, elapsed time and frames saved. A scan can be stopped.
- **Next frame**: moves the film one frame without scanning.
- **Viewer and filmstrip**: the selected scan, zoom, rotate, mirror, favourite,
  and edge-print frame numbers (01A, 02A…) for every frame on the roll.
- **Adjust**: exposure, contrast, saturation and temperature. They are saved per
  scan as a recipe. Previews and exports use the same colour matrix.
- **Export**: the original TIFF (byte-identical, checked against its SHA-256),
  a 16-bit adjusted TIFF, or an 8-bit JPEG.
- **Library**: all scans, grouped by roll.
- **Settings**: the CyberView settings that shape scans, scanner and bridge
  state, automatic recovery status, and Release scanner (closes the driver
  session so CyberView X itself can be opened).
- **Native integration**: acknowledged, saved backend choice; passive installed
  driver fingerprints and feature evidence. Native capture scans only the current
  frame. Negative inversion and manual film-base references are nondestructive.

## Design

Built to the [unslop](https://github.com/heydamir/unslop) rules (CC BY 4.0, Damir
Sokolovsky):

- **Product**: a modern front end that scans 35 mm frames from the PF1800 AFL
  through CyberView's own driver and keeps the 16-bit originals.
- **Character**: calm, exact, darkroom.
- **World**: the warm neutral dark ramp. The FRAME orange is the only accent,
  used for the primary action, the selected frame and scan progress.
- **Moments**: the large scan in the viewer, and scan progress that fills a
  frame outline as real lines arrive.
- **Signature**: film edge-print frame numbers in mono (`01A`).
- Type is Segoe UI Variable with Cascadia Mono, the Windows system fonts. The
  Electron shell blocks network requests, so no web fonts are used.
- 4 px spacing grid. Three text roles. Hairline borders at 8% and 14%. One
  1.5 px icon set. Sentence case throughout. Neutral sliders. One easing curve,
  with 120–220 ms transitions.

## Validation

```powershell
npm run lint; npm run build
python -m pytest -q tests/api/test_cyberview.py   # API against a fake bridge
npm run test:skin                                  # offline demo in Chromium, desktop and 390 px
```

Hardware results from 2026-10-30 are listed in
[cyberview-bridge.md](cyberview-bridge.md). Screenshots: [desktop demo](screenshots/cyberscan-desktop.png),
[phone demo](screenshots/cyberscan-phone.png).
