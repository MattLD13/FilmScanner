# Current handoff — FRAME, October 31, 2026

Read AGENTS.md and FRAME_SPEC.md first. The scanner session is complete. The current
continuation improves software negative conversion using saved acquisitions only.

## Latest continuation: FRAME UI and recovered vendor colour

- The scanner product is now **FRAME**. Open `npm run frame`, the FRAME Start-menu
  or desktop shortcut, or `/?workspace=frame`. Old `--cyberscan` and workspace URLs
  remain compatible; driver storage and runtime identity were not renamed.
- Home shows a random real saved edited photo with shuffle. Scan retains controls
  and moves advanced adjustments into disclosure panels. Rolls/filmstrip show
  edited previews. Brown/cream/orange styling and serif headings match the original
  brief; phone navigation is labeled. Develop links to the existing workflow and
  clearly states that developing and scanned-roll records are still separate.
- The AFL's actual model gamma (37.GG), its complement for negative film, and
  exact 16-bit film-term LUT/matrix were recovered. New explicit stock profiles
  ending **AFL conversion** use these stages without reference-image colour fitting.
  Existing saved recipes/defaults are not migrated. See
  [vendor-colour-pipeline.md](vendor-colour-pipeline.md) for addresses, tests,
  private output and remaining differences. Full Auto Gamma parity is unresolved;
  its duplicate-endpoint zero-table case was not promoted into production.
- Local recovered profile: `4fe5c640f76366f8` (Kodak 200). Its acquisition/recipe
  outputs are `.local/color-review/vendor-pipeline/`. The older garden-fitted
  profile remains separately experimental.
- New rendered Home/Rolls image API is authenticated, read-only and uses saved
  recipes, a bounded JPEG cache and one processing worker at a time. Source hashes
  and cached profile identities are checked. Originals remain unchanged.
- UI screenshots using the saved acquisition in an isolated review library:
  `.local/frame-ui/frame-home-saved.png`, `frame-scan-saved.png`,
  `frame-phone-saved.png`. Scanner discovery and bridge were mocked for review.
- Latest tests/results are at the top of [progress.md](progress.md). No physical
  scanner operation was performed and no live service was restarted. Shortcuts
  were renamed after the build/checks passed. Source changes remain uncommitted.

## Checkout and hardware

- Last committed checkpoint: `5fb63e2`, vendor close-write fix and supervised direct
  capture. The checkout was clean when this continuation began; subsequent colour
  changes are uncommitted. Never commit `data/`, `.local/`, vendor DLLs or tokens.
- Direct SCAN08 capture is the default. CyberView/TWAIN is a research/test path via
  `FRAME_SCANNER_BACKEND=cyberview-twain`.
- Hardware session evidence: [standalone-plan.md](standalone-plan.md). Direct
  1800 dpi 16-bit transmission, 300 dpi 8-bit prescan, real live preview, exposure
  120/168/269, native fine moves and a three-source stitched scan were verified.
  Effective sensor precision remains unmeasured. Preserve stitch sources and hashes.
- `services/native_bridge/vendorfix.h` prevents the vendor's uninitialised close
  register write. Earlier white scans required a power cycle to clear that damage.
- Native validation records nudge and exposure 50–300; nothing above 269 was scanned.
  Selector 17 returned zeros before the fix and has **not been retested**. The app
  derives subsequent exposure from scans instead. Backward One Frame previously
  hung. Native nudge evidence does not verify CyberView's separate step entry points.
- **No scanner commands, hardware-validation changes or driver installation were
  performed in this software continuation.** Keep per-action supervision for film
  moves and new command types; do not infer current loading or ownership state.

## Software continuation

**Latest:** User review rejected the nominal `0.5` conversion's flower detail and
colour. An experimental reference-derived RGB profile now recovers much more of
both on the saved negative; see [reference-tone.md](reference-tone.md). Private
outputs are in `.local/color-review/reference-profile/`, including `corrected.tif`,
whole-frame/detail comparisons and exact profile/recipe. The local profile is
available in CyberScan as Garden - CyberView reference (experimental). Balance an
older negative first, then select it; existing edits were not migrated. Do not
claim a general negative-conversion solution: other subjects/stocks remain untested.

Details, evidence and limitations: [negative-conversion.md](negative-conversion.md).

- New direct negatives suggest a film base and nominal response `0.5` when the scan
  has usable range. Old recipes missing the field keep their exact `1.6` response.
- Single and stitched scans receive the same automatic conversion. Coverage masks
  exclude uncovered stitch margins from base and automatic-colour estimation.
- **Balance negative** in Adjust suggests a conversion for a saved direct negative,
  without acquiring or changing exposure. Existing saved recipes are not migrated.
- **Negative response** controls preview and export. Conversion edits clear stale
  automatic colour. Reset preserves the response; other viewing adjustments reset.
- Processed TIFFs include the engine version, complete recipe and source checksum.
  Balancing rejects conflicting simultaneous adjustments and preserves metadata.
- Private comparisons: `.local/color-review/final/` (120/168/269) and
  `.local/color-review/default-exposure/` (100/100/100). Each has `comparison.jpg`,
  component JPEGs and `comparison.json`. Input acquisitions remain untouched.
- Reproduce offline with:
  `python scripts/compare_negative.py SOURCE.tif REFERENCE.tif OUTPUT_DIR`.

The evidence is **one garden negative at two exposures** against its saved CyberView
reference. This improves appearance; it is not a calibrated film profile or proof
of exact CyberView matching. Foliage/paving still differ. Current checks and their
actual results are in [progress.md](progress.md).

## Next work

1. Review the private comparisons. Use Balance negative on saved scans as desired.
   Compare another existing negative/reference pair before broader accuracy claims.
2. Exact vendor film-term and curve application remains approximate; investigation
   notes: [auto-color-re.md](auto-color-re.md). Auto Gamma word computation is exact,
   but the interpolation through those points is an approximation.
3. Selector 17 and faster repeated scans require a separate supervised hardware
   session. Keep them separate from software colour work.

Build fixtures with `services/native_bridge/build.ps1 -Fixtures` and
`services/cyberview_bridge/build.ps1 -Tests` (Visual Studio 2022 x86 Build Tools).
Missing fixtures may skip tests; report actual skips. A synthetic workflow does not
verify hardware. Operational details remain in [scanner-protocol.md](scanner-protocol.md),
[native-scanner.md](native-scanner.md), [auto-align.md](auto-align.md), and
[cyberview-bridge.md](cyberview-bridge.md).
