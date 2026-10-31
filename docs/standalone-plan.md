# CyberScan X without CyberView (plan, 2026-10-31)

Decision (user, 2026-10-31): CyberScan X scans with **no CyberView X app, window or
TWAIN driver**. It keeps only the scanner's own low-level driver DLLs
(`SCAN08.dll` → `SQ_Scan.dll` → `IO_PORT.dll` → `FVC.dll` → usbscan.sys), driven by
`services/native_bridge/aflbridge.c`. Everything CyberView adds on top (exposure
choice, negative conversion, automatic colour, film terms) becomes CyberScan X code.

## What CyberView actually does to a negative, and where it now lives

| CyberView step | How it works (evidence) | CyberScan X |
| --- | --- | --- |
| Film-base exposure ("ColorBalance", e.g. 153/205/323) | Prescan measures the film base with SCAN08 selector 17; the values become the scan block's per-channel exposure (`+0x18`). On the PF1800 AFL, CyberView's own auto-exposure hook (AFL vtable `+0x1a8` → `0x10141630`) is a stub returning 0, so this **is** its auto exposure. (`docs/scan08-feature-catalog.md`, `docs/auto-color-re.md`) | aflbridge `calibrate` already runs selector 17. **To do:** pass the measured values as exposure; the 50-200 bound in `aflbridge.c` and `workspace.py` must rise (blue is about 320) after one supervised scan |
| Vendor auto exposure | Selector 32 flag bit 0 (300 dpi pre-pass) | Optional; not what CyberView uses on this model |
| Negative to positive (film term) | `DoApplyFilmTerm`, `Gamma\*.ft` | `services/imaging/filmterms.py` reads the terms (approximate, see its docs) |
| Auto colour (Auto Gamma) | `iComputeAutoColor` on the prescan, curves via `0x10111be0` | **Done:** `services/imaging/autocolor.py`, exact port (68 of 68 images, word for word, against the DS) |
| Applying the curves | Engine table builder for points at `+0x670` (not yet read) | **To do:** read it, or use a monotone interpolation through the same points and label it |

## Status (2026-10-31, evening)

Done without the scanner (192 tests and all workflow suites pass):

1. **Auto colour in the recipe.** `Adjustments.auto_color` (the 18 words), computed for
   every new scan from a reduced copy of the positive, applied in `before_levels`, toggled
   per frame (`POST /api/cyberview/captures/{id}/auto-color`, "Auto colour" in Adjust) and
   mirrored in the preview filter. Curve shape: monotone cubic through CyberView's exact
   points (the engine's own builder is still unread).
2. **Film-base exposure plumbing.** `calibrate` (selector 17) now sets the next scans'
   exposure to the measured film base; the bound is 50-400 in `workspace.py` and
   `aflbridge.c`. Scans at such exposures stay refused until `native_validation.json`
   gets an `exposure_range` after a supervised scan.
3. **Direct path parity.** Live preview from SCAN08's strips (`usbwatch.h` shared, now in
   `services/native_bridge/`); stuck detection reports `position_sensor` from the watch
   and the service ends the stuck bridge.
4. **Direct capture is the default; the CyberView switch is gone from the UI.**
   `FRAME_SCANNER_BACKEND=cyberview-twain` keeps the old path for tests and research.
5. **Own driver copy.** `services/native_bridge/driver.py` copies the five files in
   `driver_manifest.json` (hash-checked) to `%LOCALAPPDATA%\CyberScanX\driver` when direct
   capture starts; `aflbridge` loads them bottom-up from there (verified: all five load
   from that folder), else from the CyberView install.

Needs one supervised session: a direct scan with film-base exposure (then record
`exposure_range`), the live preview on a real direct scan, and the fine film move for
stitched scans (then add `nudge`). Only after that, CyberView X can be uninstalled.

## Supervised session on the scanner (2026-10-31, 15:00-15:50)

Direct capture only (aflbridge, CyberScan's own driver copy, USB trace on). Results:

| Check | Result |
| --- | --- |
| Driver copy in `%LOCALAPPDATA%\CyberScanX\driver` | Works (after the vendor fix and a power cycle) |
| **Vendor bug: IO_PORT close write** | Every driver close wrote 2 uninitialised bytes as a register write. Seen hitting `0x78`, `0x17`, `0x23`, `0x27` (AFE): frames went white and stayed white until a power cycle; status page `0x0d` read `0xaa`, as before the earlier "Preparing film scanner" hang. Fixed in both bridges by `services/native_bridge/vendorfix.h` (zeros, as the parallel transport sends) |
| Film-base exposure | 1800 dpi 16-bit at 120/168/269 scanned normally; base came out 0.84/0.855/0.856 for a 0.85 target, so exposure is linear. Ratio 1 : 1.40 : 2.24 against CyberView's 1 : 1.34 : 2.11 |
| Selector 17 (film-base measurement) | Returned zeros twice, while the scanner was in the poked state; not retested. CyberScan measures the base from its own scans instead (`film_base_exposure` in the routes) |
| Live preview on the real scanner | 212 preview rows per 1800 dpi frame |
| 8-bit prescan (300 dpi) | Works with the identity table (an earlier flat frame was the poked state) |
| Fine film move (selector 10) | 20 steps back = 1.20 mm (28.4 px at 600 dpi); 20 forward returned within 0.11 mm |
| Stitched scan through the app code | Back 20, forward 28, back 8; 2648 x 1713 px mosaic, one edge found, exact 36.00 x 24.00 mm crop, skew -0.46 deg, 15.3 steps per mm learned |

Recorded in `native_validation.json`: `nudge`, and `exposure_range` 50-300 (nothing above 269
was scanned). The bright, slightly cyan tone was the next software task at this
checkpoint. A subsequent offline comparison and adjustable conversion are in
[negative-conversion.md](negative-conversion.md). Broader photographic colour
validation remains open.

## Order of work (original plan)

1. **Auto colour in the render recipe.** Add per-channel curves (master, R, G, B points)
   to the adjustments, render them in `services/imaging/pipeline.py`, compute them with
   `autocolor.compute` on a 600 dpi 8-bit render of the inverted frame when a capture is
   saved, and show them in the UI (an "Auto colour" toggle). Originals never change.
2. **Film-base exposure for direct scans.** Use the `calibrate` result as exposure;
   raise the bounds; one supervised scan to validate, then record it in
   `native_validation.json`.
3. **Make direct capture the default and remove CyberView from the UI.** Port the
   remaining CyberView-path features to aflbridge first:
   - live preview: include `services/cyberview_bridge/usbwatch.h` in aflbridge (the
     `usbtrace.h` hooks are already there);
   - stuck detection: the same watch;
   - stitched scans: native `nudge` (selector 10) is already wired, needs its supervised test;
   - next frame: validated (`next`).
   Then switch the default backend, delete the CyberView capture option and texts, and
   move `services/cyberview_bridge` to research tooling (the tracer and `autocolor.exe`
   stay useful as references).
4. **Ship the driver DLLs with CyberScan X** so CyberView can be uninstalled: load the
   four DLLs (same pinned hashes) from CyberScan's own folder, never committed to git.

Each step keeps the rule that a scanner operation is enabled only after a supervised
test is recorded in a validation file.
