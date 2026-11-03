# FRAME engineering review handoff

Prepared November 2, 2026, after the user's preference for preview tone **off**.

November 3 update: source, tests and documentation are committed in the sequence
recorded in [the commit review and execution record](COMMIT_REVIEW_PLAN.md).
Staged backend full suite: 427 passed, 63 skipped, 2 xfailed; overlapping compiled
helper/imaging subset: 83 passed. Build, native UI, simulated 36-frame workflow,
skin and live-preview checks passed. This adds software verification, not new
physical scanner qualification. Earlier dated checkpoints below remain historical.

**Latest review follow-up:** [response and implementation evidence](ENGINEER_REVIEW_RESPONSE.md)
records guarded statistics, persistent uncertain-position handling, refused-advance
confirm/retry/stop controls, and built-in optical return verification. The corrected
full suite passed486 tests with2 expected failures; the later safety subset passed9.
No new physical qualification is claimed for these guards. Read that response
before treating the older validation checkpoints below as the current behavior.

## What I want reviewed

FRAME is a local Windows film-scanning application for a Pacific Image PrimeFilm
PF1800 AFL. Please review the current implementation and evidence, identify
remaining correctness risks, and propose the smallest useful next experiments.
The priority is reliable acquisition of the entire picture and preservation of
original samples. A generally usable negative conversion matters more than
matching one reference photograph or adding cosmetic brightness.

Please provide findings with file/function references, explain which are observed
failures versus hypotheses, and specify acceptance tests for proposed changes.

## Material to provide

1. **The current committed project**, including source, tests, contracts and
   documents. Supply the November 3 documentation commit and its ancestors;
   an archive of an older checkpoint omits important implementation work.
2. **This document** as the starting point, followed by the reports linked below.
3. **A small evidence selection**, separately from source: the before/after and
   bottom-edge images, their reports/manifests, and corresponding original TIFFs
   if image-level investigation is needed. Full acquisition logs/source tiles can
   be supplied for a specific reproduced case; the entire photo library is not
   necessary for an initial review.

Runtime libraries, authentication tokens, local databases and installed vendor
binaries are not part of the source handoff. Vendor-dependent physical/CPU tests
need the user's local pinned driver installation. Simulator tests are separate
and do not establish hardware behavior.

## Architecture and source map

The normal acquisition path is:

`React/TypeScript client -> authenticated local Python API -> x86 aflbridge.exe`
`-> SCAN08.dll -> vendor transport libraries -> usbscan.sys -> PF1800 AFL`.

The normal product does not drive the CyberView window or use TWAIN. A retained
TWAIN bridge is used for vendor comparisons/research. A separate experimental
independent USB path is unfinished and is not the normal acquisition backend.

| Responsibility | Main files |
| --- | --- |
| Product specification and project rules | `FRAME_SPEC.md`, `AGENTS.md` |
| API, scan orchestration, transport accounting and recipes | `services/api/cyberview_routes.py` |
| Scanner host and validated configurations | `services/scanner_host/native.py`, `workspace.py`, `native_validation.json` |
| Native x86 vendor bridge | `services/native_bridge/aflbridge.c` |
| Border detection and optical one/two-tile planning | `services/imaging/frame_align.py`, `acquisition_plan.py` |
| Negative/film conversion and optional automatic tone | `services/imaging/negative.py`, `vendor_negative.py`, `vendor_filmterm.py`, `vendor_autogamma.py` |
| Isolated vendor CPU oracle | `services/cyberview_bridge/vendorcolour.c` |
| Repeat normalization and precision diagnostics | `services/imaging/scan_filters.py`, `sensor_precision.py` |
| Scanner UI and shared contracts | `apps/web/src/cyberscan.tsx`, `packages/contracts/schema.ts` |
| Main regression tests for recent work | `tests/api/test_planned_scan_api.py`, `test_vendor_auto_tone_api.py`, `tests/imaging/test_acquisition_plan.py`, `test_vendor_autogamma.py` |

Original acquisitions are immutable TIFFs with SHA-256 records. Stitching,
repeat means, negative conversion, tone and exports are separately recorded
derived products/recipes. Do not equate a stitched master with an untouched
sensor original.

## Current behavior and preferences

- Border finding uses bounded **300 DPI RGB8** captures and optical registration.
  Measured borders and source footprints guide one or two1800 DPI RGB16 archival
  tiles. It does not rely solely on nominal motor steps or one fixed frame pitch.
- Each frame gets a fresh local check. Fine moves are tracked and reconciled
  before whole-frame advances. Multi-tile exposures are fixed across a frame;
  vendor auto exposure is disabled across those tiles.
- End-of-strip handling verifies the image immediately before/after a refused
  advance and requires an unchanged vendor counter. Default batch behavior returns
  to relative frame1 only after a matching expected count or user-confirmed end;
  otherwise it waits at the checked stopped frame. A return now gets a built-in
  optical arrival check. It is not an absolute encoder or exact pixel repositioning.
- Review previews can be Quick300 DPI or Detailed600 DPI, for one frame or all.
  Previews appear in the archive. Favorites can be selected for archival scanning.
- **Current preferred appearance:** recovered Generic Negative conversion with
  extra automatic preview tone **off by default**. Auto colour is optional. A
  favorite retains a deliberately selected preview tone or disabled choice.
  Older saved edits are preserved. Do not restore default-on tone based on the
  historical processing report.
- Roll deletion, editing/export and forward/backward eject controls exist.

## Evidence established so far

| Result | Scope and limitation |
| --- | --- |
| Six-frame physical batch passed | All six independently counted photographs saved in order; horizontal borders verified; all six masters reconstructed exactly;89 recorded file hashes matched; photographic return to frame1 verified twice. One strip, not an uncut-roll reliability qualification. |
| Fresh preview/favorite physical check passed | One frame, two archival tiles, exact preview-tone reuse,20 hashes matched; final relative frame1/fine offset0. This tested the preceding default-on implementation; the user's later default-off preference has API/UI verification. |
| CyberView processing sequence observed | Generic Negative RGB8 prescan: model negative LUT -> film table/matrix -> negative histogram automatic table -> mode7 application. Mode8 changed no pixels at the observed intensity0. |
| Exact image-stage replay | The CPU worker reproduced both observed prescan tables. Python mode7 applied the selected prescan table to CyberView's copied film-converted RGB16 data and reproduced its saved TIFF pixel-for-pixel. This is not full acquisition/calibration/color-management parity. |
| Vendor height limit confirmed | The pinned model module clamps Y to1708 rows at1800 DPI; FRAME already requests its supported maximum. Declared-DPI height is24.1018mm, not independently calibrated geometric height. |
| Output-code structure measured | Observed original16-bit output uses16-code spacing/four zero low bits. This is12-bit-aligned output, not a calibrated sensor/ADC ENOB measurement. |

## Main open engineering questions

1. **What causes the lower light band?** It occurs in FRAME and in CyberView's own
   copied pixels before film/automatic tone, as well as its saved TIFF. Thus a
   unique FRAME TIFF/display cause is ruled out for those observations. The exact
   optical, per-pass calibration, carriage or line-processing mechanism remains
   unisolated. The comparison used unequal exposure/crop/calibration, so it must
   not be described as an equal-settings sensor benchmark. Which bounded
   measurement would discriminate the remaining causes?
2. **Can vertical containment be demonstrated on this supported path?** Three
   fresh captures plus twelve original strip tiles did not establish both true
   top/bottom film-base borders. Full acquired height is retained. Moving the
   strip longitudinally cannot prove extra vertical coverage. Are the detector's
   evidence requirements appropriate, and is any additional field actually
   exposed by the supported vendor interface? Do not turn a digital scan edge,
   nominal24mm crop, resize or padded pixels into evidence of film containment.
3. **Are transport and planning failure paths sufficiently conservative?** Review
   fresh arrival checks, pending versus acknowledged moves, cancellation, failed
   advance handling, original retention and return-to-first behavior. The18-pixel
   cross-resolution uncertainty allowance is provisional, not a measured universal
   repeatability bound. End detection has optical/counter evidence and an
   independent strip count, not a separate physical-tail sensor measurement.
4. **Is the negative pipeline suitable as a general default?** Review acquisition
   exposure balance separately from reversible display conversion. Optional tone
   can clip displayed endpoints and cannot restore acquisition information. Keep
   it off by default per the user's preference. Broader vendor auto-exposure state,
   other film/mode behavior, nonzero mode8 and exact ROC/GEM remain separate gaps.
5. **What is needed before broader release?** Propose tests on different negatives,
   low-texture/dark scenes, skewed or wide frames, longer strips/uncut rolls,
   cancellation and driver recovery. Mounted slides and calibrated sensor precision
   are not currently qualified. The user has a film strip only and cannot perform
   calibrated precision testing now; that is not a blocker for reviewing the
   usable scanning workflow.

## Read these reports in order

1. [Six-frame acceptance](strip-acceptance-2026-11-02.md): actual failures, fixes,
   final batch/end/return result and preservation audit.
2. [Processing and lower-band comparison](cyberview-processing-validation-2026-11-02.md):
   vendor observations, exact versus approximate claims, new processing code,
   recovery history and the later default-off preference.
3. [Vertical investigation](vertical-containment-2026-11-02.md): module clamp,
   source audit and limitations.
4. [Feature-port evidence](cyberview-feature-port-2026-11-01.md) and
   [precision method](sensor-precision-method.md): validated modes/controls,
   vendor exposure, repeats and precision terminology.
5. [Conversation summary](../FRAME_SUMMARY.md): historical context if needed.

Older reports contain dated checkpoints. The appearance preference at the top
of this handoff and the actual current evidence/configuration gates take priority
over an older assertion that automatic tone is a default or still unrecovered.

## Validation commands and exact checkpoint

```powershell
python -m pytest -q
npm run build
npm run test:native-ui
npm run test:e2e
```

The latest full suite **before** the final default-off preference change passed
475 tests with2 expected failures in450.44s; build/native UI/simulated workflow
passed. After changing the default off:

```powershell
python -m pytest -q tests/api/test_vendor_auto_tone_api.py
```

passed9 tests in63.48s, including no default generation, explicit opt-in, optional
failure preservation, planned scans with tone off, and favorite choice retention.
Build and native UI workflow passed again. A new full475-test run and another
physical strip run were not claimed for that final display-default-only change.

## Optional local evidence selection

- `.local/cyberview-completion/bottom-edge-comparison.jpg`,
  `bottom-edge-results.json`, `replay-results.json`, `final-evidence-audit.json`.
- `.local/cyberview-completion/full-scan/cyberview-original-output.tif` and its
  image-stage observations/buffers if exact vendor replay is being reviewed.
- `.local/cyberview-completion/physical-frame-before-after.jpg` and
  `offline-replay-20261103T003407Z/before-after-six-frames.jpg`.
- `.local/strip-acceptance/20261102T201552Z/`: contact sheet, manifest, session log,
  hash checks and return registrations. Corresponding TIFFs/source tiles live in
  that run's isolated `library/`.
- `.local/vertical-containment/20261102T210150Z/`: fresh original TIFFs,
  `vertical-audit.json`, inspection figure and static clamp evidence.

The UTC folder date can be November3 while the local work date is November2 in
New York. Local evidence is intentionally ignored by git, so source access alone
will not include these files. Use the manifest/hash links when choosing which
originals accompany a reported case.
