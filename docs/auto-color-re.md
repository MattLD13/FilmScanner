# CyberView's automatic colour (reverse engineering)

**Later correction:** the actual engine table worker has now been identified as
Lagrange (`0x10104360`), including an all-zero result on duplicate endpoint x
values. Its caller state remains unresolved, so the production monotone adapter
was not replaced. The AFL's missing model gamma and exact film-term stage are
documented in [vendor-colour-pipeline.md](vendor-colour-pipeline.md). Earlier
statements below about the engine builder being unread are historical.

**Status 2026-10-31:** `iComputeAutoColor` is ported exactly to
`services/imaging/autocolor.py` (68 of 68 test images identical to the DS, including the
error path; `tests/imaging/test_autocolor.py`). Auto exposure on the PF1800 AFL is the
film-base measurement (selector 17) used as per-channel exposure; CyberView's own
auto-exposure hook for this model is a stub. Plan for using both without CyberView:
[standalone-plan.md](standalone-plan.md).

Why: scans through CyberScan X (hidden CyberView, TWAIN) look teal and flat next to
the same frame saved from CyberView's own window. Measured on the garden frame
(`Pictures/FilmScans/image001.tif` vs app capture `76e2d212…/01-e2af66a5.tif`,
2026-10-30): CyberView's own save has every channel's black point at 0; the hidden
scan has lifted, unequal blacks (R 0.08, G 0.19, B 0.32 at the 5th percentile) and a
different curve per channel (fitted gamma 0.48 / 0.45 / 0.33). Per-channel levels
alone do not close the gap.

Cause: CyberView's Auto Exposure / Auto Gamma (`[SETUPDLG DEFAULT PAGE]`, settings
object `+0x1fc` / `+0x200`) are computed from the **prescan**, and hidden scans never
prescan. Separately, the app had native capture selected (saved preference
`cv_preferences/scanner = afl-native-experimental`), whose raw transmission the app
only inverts with film base `[1, 1, 1]`, so the orange mask stays.

## What is found (CyberViewX.ds 1.4.0.0, a debug build: unoptimised, RTTI, stack checks)

- The algorithm is inside the DS, not a separate DLL ("CIP" image engine). The DS
  **exports** it: `iComputeAutoColor` (`0x10122ba0`, about 4 KB) and the class
  `CIP_RawImg` (constructor, `iLoadRAWImg(path, w, h, ?, ?)`, `iSetRAWImgInfo`,
  `iMakeHistogram_Mean_Data`, `iMakeHistogram_Mean_Data_RGB_Avg`,
  `iSet_MakeHistogram_SkipHueValue`, `iWriteRAWImg`).
- Single caller: `0x101129c0` (a curve-maker step, near `CDipAutoGamma`, vtable
  `0x101f8ec4`). It writes the prescan to `%TEMP%\~CurveMaker_HMS.raw`, builds a curve
  maker (`0x10123bd0` constructor, `0x10123d70` load/initialise, error text
  "CCurveMaker error code = %d."), then calls:

  ```
  iComputeAutoColor(curveMaker, 2, RECT{0, 0, width, height}, 0.05f, 0.05f, &this->adjust /* this+0x20 */)
  ```

- `iComputeAutoColor` reads the image descriptor (`+0x08` data, `+0x24` bits per
  sample, `+0x28`, `+0x2c`, `+0x30`), computes width x height, and selects one of
  three parameter presets by the second argument (CyberView passes 2):

  | Preset | p0 | p1 | p2 | p3 | p4 | p5 | p6 | p7 | p8 | p9 |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | 1 | 0.20 | 0.30 | 0.40 | 45 | 75 | 0.10 | 0.25 | 0.05 | 0.01 | 0.01 |
  | **2** | 0.35 | 0.55 | 0.70 | 35 | 65 | 0 | 0.75 | 0.15 | 0.01 | 0.02 |
  | 3 | 0.25 | 0.45 | 0.55 | 55 | 65 | 0.10 | 0.35 | 0.35 | 0.02 | 0.04 |

  (stack slots `-0xc0 … -0xe4`; 45/75 and 35/65 look like percent or level bounds,
  0.01–0.04 like clip fractions). The two 0.05 arguments look like shadow and
  highlight clipping.
- The result is a `tagK_IP_AUTOCOLOR_ADJUST` struct, later turned into per-channel
  curves (`m_pCurveGammaR/G/B/All`, `CGammaTable`) and applied by DoAutoGamma
  (`0x100346b0` / `0x10034780`, auto-gamma object `0x1017c820`, worker `0x1017d330`,
  "Apply auto gamma InputType=%d, OutputType=%d" in `0x1017c860`).
- Film terms are applied separately (`DoApplyFilmTerm`, `Gamma\*.ft`, readers
  `CPIEFilmTermReader` / `CKodakFilmTermReader`); `services/imaging/filmterms.py`
  already reads these.

Tools used (scratch, not committed): RTTI vtable lister, string xref, function
survey, linear disassembler, all with `research/.tools/analysis-venv` (pefile,
capstone). Recreate them from `research/cyberview/analysis/scan08_catalog.py`.

## Calling CyberView's own function (done, 2026-10-31)

`services/cyberview_bridge/bin/autocolor.exe RAW WIDTH HEIGHT [PRESET [LOW HIGH]]`
(source `autocolor.c`, built by `build.ps1`) loads CyberViewX.ds without any TWAIN
message, builds a `CIP_RawImg` with the exported constructor, sets the fields
`iLoadRAWImg` would set (`+0x08` pixels, `+0x24` bits = 8, `+0x28` samples = 3,
`+0x2c` height, `+0x30` width, `+0x34` = 1), calls
`iComputeAutoColor(img, 2, {0,0,w,h}, 0.05f, 0.05f, out)` and prints the 18 words. It
backs up and restores `CyberViewX.ini` and exits without running the DS's unload
code. `iComputeAutoColor` builds its own histograms (`iMakeHistogram_Mean_Data`,
which fills `+0x0c`) and converts pixels to HSV with `0x101254f0` (V = max / 255, so
the input must be 8-bit). Test: `tests/scanner/test_autocolor_harness.py` (ramp image, no
scanner, settings file unchanged).

Result layout, `WORD out[6][3]` (rows x R, G, B):

| Row | Meaning | Garden frame (app hidden scan, 600 dpi) |
| --- | --- | --- |
| 0 | white point in | 255 255 255 |
| 1 | white point out | 255 255 255 |
| 2 | midtone in | 113 158 156 |
| 3 | midtone out | 128 128 128 |
| 4 | black point in | 12 42 75 |
| 5 | black point out | 0 0 0 |

How CyberView turns it into curves (`0x10111be0`, called after `0x101129c0` by
`0x1005e180`; then `0x101125f0` applies them to the image):

- Curve 0 (master, all channels): one point (155, 130).
- Curves 1-3 (R, G, B): three points each, (white in, white out), (mid in, mid out),
  (black in, black out).
- **CyberView quirk:** the green black point is loaded into a stack slot that the next
  instruction overwrites (`+0x1a` and `+0x20` both go to `[ebp-0x48]`), so green's
  black point input is always 0. CyberView never corrects green's black point.
- The curve control (`0x10067100`, storing points at `+0x10d8`) builds 256-entry
  tables with Lagrange interpolation through (0,0), the points and (255,255), rounded
  and clamped (`0x10068600`). The tables actually applied are built later inside the
  image engine from the copies made by `0x10114bd0`-`0x10114d50` (`+0x670`, count
  `+0x690`); that builder is not yet read, and plain Lagrange cannot be it (duplicate x
  values would divide by zero).

### Why the curves alone do not reproduce CyberView's own save

Measured on the garden frame (hidden-scan input vs `Pictures/FilmScans/image001.tif`),
the mapping CyberView applied has black points near R 38, G 55, B 85 and much darker
mids than the computed curves. With the curves applied (linear or Lagrange, master
curve on), the mean quantile error drops from R/G/B 18/57/84 to about 7/16/30 levels
but does not reach zero. The rest is **Auto Exposure**: from the prescan CyberView
also sets per-channel scanner exposure (log lines "ScanInfo Exposure : R = %d, G = %d,
B = %d" and "ColorBalance : R, G, B" in `0x10167890`), so its own final scan reads
different raw data before the curves. The hidden scan used the default exposure.

## Two ways to finish

1. **Call CyberView's own code (exact).** cvbridge already has the DS loaded. Build a
   `CIP_RawImg`/curve-maker input from a reduced copy of the scan, call the exported
   `iComputeAutoColor` with preset 2 and 0.05/0.05, read the adjust struct, and apply
   it as CyberView does. Needs: the image-descriptor layout, the adjust struct layout,
   and the curve construction from it.
2. **Reimplement in Python.** Translate `iComputeAutoColor` and the curve building
   into `services/imaging/`, and test it against CyberView's own saves.

Either way, check with one supervised scan: hidden prescan (CyberView menu 32794,
Prescan Current Frame) + scan should match CyberView's own save. That is the ground
truth for both options.

## Next steps

1. Read `0x10167890` (exposure and colour balance from the prescan) and find how the
   values reach the scan request (`ScannerDeviceIO` selector 32 exposure words, see
   `docs/scan08-feature-catalog.md`). Then compute them for hidden scans the same way.
2. Read the engine's table builder for the points at `+0x670` (search the CIP engine
   for readers of `+0x690`; `0x10115a90` and `0x10115ff0` only log them).
3. Ground truth with one supervised session: CyberView's own window with
   **Help > Save Log** after a prescan and scan, plus a `--trace-usb` hidden scan of the
   same frame. The log gives the exposure and colour balance numbers; the trace gives
   the exposure words on the wire. Compare with step 1.
4. Then apply in the app: run `autocolor.exe` on a 600 dpi 8-bit copy of each hidden
   scan, build the curves, apply them (and the exposure once known) to the 16-bit
   original as an edit, never changing the original.
