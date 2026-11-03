# FRAME Scanner Conversation Summary

**Prepared and reviewed against code and saved measurements:** November 3, 2026

**Project:** FRAME film-scanning application

**Scanner:** Pacific Image PrimeFilm PF1800 AFL

## Purpose

**November3 commit review:** [logical commit plan and bounded review](docs/COMMIT_REVIEW_PLAN.md)
records the fixed native position-sensor forced-termination path, focused tests,
and actual per-side statistics cutoff. The user subsequently authorized committing
the source, tests and documents in five logical groups. The staged backend suite
passed 427 tests with 63 skips and 2 expected failures; the overlapping compiled
helper/imaging subset passed 83. Build, native UI, 36-frame simulated workflow,
skin and live-preview checks passed. Preview tone stays off. No new hardware
experiment was performed, and private data/vendor binaries remain outside git.

**Engineering-review follow-up:** [review response](docs/ENGINEER_REVIEW_RESPONSE.md)
records new statistics-only edge guards, persistent movement-uncertainty gates,
expected-count/confirm/retry/stop handling for refused advances, separate X/Y
containment fields and built-in optical return checks. Software verification is
recorded separately from the older physical acquisitions; the band mechanism and
full vertical containment remain unresolved. Preview tone stays off by default.

**Current appearance preference:** the user preferred the comparison with preview
tone off. New negative previews/scans therefore keep the generic vendor conversion
without automatic preview tone by default. Auto colour remains opt-in, and a
favorite retains an explicitly chosen preview tone. Existing saved edits are kept.

This document consolidates the decisions, reported hardware observations, implementation work, and outstanding checks discussed in this conversation. It is intended as a handoff and project reference. Hardware observations are distinguished from simulator/API test results.

**Latest automatic-processing continuation:** [vendor processing validation](docs/cyberview-processing-validation-2026-11-02.md) records an actual Generic Negative UI prescan and16-bit scan, exact replay of its automatic tables and saved TIFF stage, and new FRAME defaults that reuse each preview's tone on its archival scan/favorite. The lower light band is also present before film/tone processing in CyberView's own path; its exact optical/calibration mechanism remains unisolated. Full vertical containment and calibrated sensor precision are still not claimed. Older statements below about unresolved stage order describe earlier checkpoints.

Final verification of that continuation:475 tests passed,2 expected failures,
successful build/native UI/simulated workflow, and a physical first-frame
preview/favorite scan with20 matching hashes. The film remains at relative frame1,
fine offset0; driver closed.97 successful vendor processing-buffer hashes matched.

**November 2 physical strip validation:** the corrected ordinary API captured all six independently reported photographs, verified their side borders and padded two-tile coverage, recognized a refused further advance using a fresh same-frame witness and unchanged vendor counter, and returned to frame 1. A new image strongly matched the starting photograph. All six masters reproduced exactly from retained sources and plans. The current software suite passed 467 tests with 2 expected failures; build, native UI, and simulated workflow passed. Supplementary favorite/repeat testing and final integrity checks are recorded in [the loaded-strip report](docs/strip-acceptance-2026-11-02.md). This establishes a six-frame-strip result, not uncut-roll or vertical-containment validation.

**Vertical follow-up completed:** [maximum-height investigation](docs/vertical-containment-2026-11-02.md) verifies the installed vendor module clamps Y to1708 rows and FRAME already requests its full supported height. Three fresh captures plus twelve retained original tiles did not establish both top/bottom film-base borders. Full height remains retained; unknown vertical containment is not promoted to verified. CyberView's output bit-depth and LUT information cannot replace calibrated sensor/ADC precision measurements.

**Latest CyberView feature continuation:** [the feature-port report](docs/cyberview-feature-port-2026-11-01.md) records gated acquisition modes, vendor exposure, go-to/focus/realignment, software frame labels, optional exact-worker tone, cleanup filters, aligned repeat sampling, and the actual 12-bit-spaced output-code observation. Full automatic UI parity, exact ROC/GEM, mounted-slide handling, and calibrated effective sensor precision are not falsely marked complete. The user has only a film strip available; no calibration target or mounted slide is available for those latter checks. Work continued solo after the user's instruction to stop using agents.

**Repeat/stitch refinement:** repeat means now subtract per-channel median offsets measured over the shared acquired unclipped interior, with processing vectors and final range-clipping counts embedded in metadata. Wide-frame archival tiles use one frozen manual/film-base-balanced exposure with vendor auto exposure disabled for the entire frame; single-tile preference is preserved. The retained real originals were reprocessed offline and checked unchanged. The 300 DPI search remains in place; 600 DPI is about 42.3 µm/pixel, and the available timing samples do not establish universal equal-cost 300/600 acquisition.

**Latest implementation update:** The optical planner, padded 300 DPI search, one/two-tile archival acquisition, fine-offset reconciliation, in-place whole-roll scanning, configurable end actions, and favorites arrival verification are now implemented in the actual FRAME project. See [the implementation and validation report](docs/planned-scanning-validation-2026-11-01.md) for test results, physical evidence, and remaining limits. The engineering review at the end of this document records the preceding design assessment.

**Default appearance follow-up:** The user requested a generally usable immediate conversion rather than a profile fitted to one lab JPEG. The latest default uses the recovered manufacturer **Generic Negative** model/film conversion when its local tables are available, with explicitly recorded measured-input balance and neutral display controls. Earlier nominal rendering is retained only as a fallback when the vendor tables are unavailable, and existing saved recipes retain their prior behavior unless explicitly rebalanced. An audit removed automatic endpoint clipping and restored the previously omitted per-channel acquisition-exposure stage. No photographic-reference fitting is used by the new default. See the report for comparisons, preservation limits, and verification.

## Product and backend context

FRAME is a local-first film scanning and archiving application. The user wants reliable border finding to guide frame acquisition, whole-roll previews and scans, clear film transport controls, and an archive that supports practical roll management.

The Python backend coordinates scanner work and image processing; the React/TypeScript client provides the scanner and archive interface. The project has a retained CyberView/TWAIN path and an experimental native path using an x86 helper around the vendor `SCAN08.dll` interface. The native path exposes scanner operations such as scanning, prescan, frame movement, nudging, and ejection only when their evidence and validation gates allow them. The conversation did not establish SANE `pieusb` or direct application-level `libusb`/`pyusb` as the active acquisition path.

Original acquired images are retained separately from crops, previews, and processed exports. Simulated results and physical-scanner observations must remain clearly distinguished.

The line-scan discussion described the scanner as building an image from successive sensor lines while the film transport advances along the strip. That is the working physical model for the feature discussion; the conversation did not report a separate instrumented measurement of the sensor's line orientation. The user also proposed measuring the distance between neighboring frames and using it to improve subsequent frame positioning. The implemented whole-roll approach instead performs a border check per frame and advances the transport between frames, rather than relying only on one fixed frame-spacing estimate.

## Decisions and requested behavior

### Border finding and frame acquisition

- Automatic border finding should guide the later full-resolution scan, so the scan does not clip the frame or leave it uncropped.
- When a border is outside the first scan window, the software should move toward the unknown side, capture another line/window, register it, and continue within a bounded search until it finds the edge or reports the limit.
- Border finding should happen for each frame during whole-roll preview/scan, because frame position and width can vary.
- Measured frame-to-frame spacing was discussed as a possible transport aid; per-frame border checks are the current safety basis, with spacing measurement available as a future optimization.
- A frame that is wider than the verified one-pass window needs overlapping, wider coverage. Detecting both borders alone is not enough: the acquired image also needs sufficient film-base margin to verify full coverage.
- The original stitched or acquired image should remain available if a crop cannot be verified. The software should not silently claim a complete frame.

### Preview and scan modes

- Preview scope should be either **one frame** or **the whole roll**. No preview mode for a user-selected subset of individual frames was requested.
- The two preview quality choices are **Quick** and **Detailed**. Both run the automatic border-finding routine. Quick uses low resolution for speed; Detailed uses a higher-resolution image for judging the photographs.
- Roll previews are saved in the archive and clearly labeled as previews.
- Users can favorite preview frames and start a high-quality scan of favorites.
- Whole-roll scanning should perform border checks for every frame before the full-resolution acquisition.
- A scan that reaches the physical end of a roll should preserve completed work and avoid treating a failed next-frame move as an extra frame.
- After a successful whole-roll scan, return the film to frame 1 when verified backward movement is available.

### Film type and archive controls

- Film type has Color, B&W, Slide, and Auto choices. Auto should use the first frame as evidence, apply a result only when confidence is sufficiently high, and otherwise keep the current selection while showing the uncertain suggestion.
- Each saved roll needs a visible delete action in the archive itself, with confirmation before deleting its scans and source files.
- Scanner controls should expose both forward and backward eject actions where validated, and the UI spacing should be cleaned up.

## Reported hardware observations

The following were reported from work with the physical scanner during the conversation:

- A full-window 1800 DPI request was accepted by `SCAN08.dll` and returned 2585 × 1708 pixels for the measured acquisition bounds.
- In the October 31 zero-nudge test, bounds were `[0.0, 1.4366666667] × [0.0, 0.95]` inches. The 300 DPI previews were 430 × 284 pixels; the 1800 DPI image was 2585 × 1708. Scale ratios were 6.0116 horizontally and 6.0141 vertically.
- Stationary previews registered at `dx = -0.0117`, `dy = +0.4729` preview pixels, correlation peak 0.5783. This was one sequence, not a measured repeatability distribution.
- **No film-base borders were detected in any capture in that zero-nudge test:** `x_found: none`, `y_found: none`. It proves full-window acquisition executes, not that a complete frame and its rebates fit in one pass or that the physical frame width is known.
- Preview-to-1800 registration after 6× area averaging gave approximately `dx = -1.1366`, `dy = +1.0316` preview pixels, peak 0.7362. These offsets include scan-grid/calibration differences and are not pure mechanical drift.
- The separate directed-nudge sequence measured 21.99 preview pixels, approximately 1.86 mm, after 20 forward steps. The validation record contrasts an earlier approximately 1.20 mm backward move; direction/load effects remain unbounded. Preview B versus the high-resolution pass had `dy = 2.146` preview pixels, approximately 12.9 high-resolution pixels, exceeding a universal 10-pixel pad.
- An early whole-roll border-finding run took six frames and was reported to have worked.
- A later preview reached frame 6 and the driver would not confirm another advance. The application preserved the six previews and warned that the end of the roll needed confirmation.
- Some previews showed **“Borders found · wider scan”**. This means the edges were detected but the frame was not considered safe for a single full-resolution pass.
- A backward-eject operation was attempted. The user later confirmed that the physical film had exited even though the software had shown a driver/sensor error. A software change was made afterward to treat selector completion as success while reporting stale sensor state as a warning; that changed behavior was not reported as retested on the scanner.

These observations are hardware reports from the conversation, not results of the automated simulator tests below.

## Work implemented during the conversation

### Border search and full-resolution coverage

- Added adaptive border search that captures and registers additional previews when an edge is missing, with bounded movement and explicit reporting when the search cannot verify the border.
- Connected per-frame border previews to the whole-roll scan flow. The scan uses preview results to decide whether a frame fits one pass or needs wider overlapping coverage.
- The active native path completes bounded exploration at 300 DPI, requiring both side borders plus the rebate and provisional 18-pixel per-axis archival uncertainty allowance. It selects one or two optically measured windows and takes only those archival tiles. Replay arrivals receive local optical verification/correction. Failed verification preserves source acquisitions and stops without a high-resolution search loop.
- A full-resolution stitched result is not marked complete if its borders, crop, or required coverage check remain unverified.
- End-of-roll movement failure after one or more successful previews is treated as a possible roll boundary; completed previews are preserved.

### Whole-roll scanning and return positioning

- Whole-roll scans now execute in place: local border/rebate search, planned archival acquisition, reconcile fine offset, then advance to the next frame. Favorites receive fresh arrival registration and a bounded local search before acquisition.
- After all selected frames finish successfully, the scanner uses verified backward frame movement to return to frame 1. The session records whether that return was confirmed. If the movement fails, the saved scans remain, but the session reports the failure instead of claiming the return succeeded.
- End behavior is selectable: return to frame 1 (default), hold at the final frame, or eject forward. The endpoint validates the selected end action; in-place whole-roll scanning no longer requires backward frame seeking when hold/eject is chosen.

### Preview, favorites, and archive

- Added Quick 300 DPI and Detailed 600 DPI preview modes, each using border finding.
- Added favorite controls and high-resolution scanning of favorited previews.
- Roll previews appear in the archive with preview labels.
- Added a **Delete roll** action on the right side of each archive roll heading. It deletes the selected roll's saved captures, sessions, and source files after confirmation. This is in the CyberScan archive view, not just the separate simulator Rolls page.

### Film type and transport UI

- Added Auto film detection with a confidence threshold. Low-confidence results are suggested without overwriting the user's current film type. A reported 58% slide guess for color-negative film therefore should not be applied automatically.
- Added forward and backward eject controls and adjusted scanner-control spacing.

## Verification completed

Automated verification reported in the conversation:

- `npm run build` completed successfully after the archive delete UI change.
- The CyberScan archive deletion API test passed: `1 passed`.
- The border/scan API test file completed successfully after the latest wide-scan and return-to-frame-1 changes: `33 passed in 183.96s`.
- The focused tests covered oversized-frame overlapping recovery, normal whole-roll border checks, and returning to frame 1 after an unconfirmed end-of-roll advance.
- `git diff --check` reported only line-ending notices for the touched Python files, not whitespace errors.

These tests use the scanner simulator/fake bridge. They do not prove that the latest wide-scan recovery or return-to-frame-1 behavior has been exercised on the physical PF1800 AFL.

## Current status and practical next check

The latest code changes are local. The former seek, fine-offset, and acquisition-planning risks prompted the redesign now implemented. Hardware validation is documented in the linked report, including the bounded sample size and the independent limitation of unverified vertical containment. The hardware acceptance checks are:

1. Frames marked **“Borders found · wider scan”** receive overlapping coverage and are cropped from their detected borders.
2. The last frame is preserved when the scanner refuses to advance past the end of the roll.
3. After the batch finishes, the scanner returns to frame 1 and the session confirms that return.

If return-to-first-frame cannot be confirmed, inspect the session error and scanner position before continuing; do not assume the transport moved successfully.

## Relevant project files

- `FRAME_SPEC.md` — authoritative product and engineering specification.
- `services/api/cyberview_routes.py` — scanner API, border search, whole-roll preview and scan orchestration, coverage recovery, roll deletion, and transport return.
- `services/imaging/frame_align.py` — border alignment and rebate-coverage verification.
- `services/imaging/acquisition_plan.py` — padded optical tile planning, preview registration, constrained archival registration, and ambiguity checks.
- `services/scanner_host/workspace.py` — validated scan settings and full-window border-preview configuration.
- `services/scanner_host/native.py` — native bridge orchestration, transport validation, and nudge commands.
- `services/scanner_host/native_validation.json` — evidence and gates for acquisition bounds and transport actions.
- `services/native_bridge/aflbridge.c` — x86 bridge to vendor scanner functions.
- `apps/web/src/cyberscan.tsx` — scanner, preview, favorite, archive, and transport controls.
- `tests/api/test_frame_align_api.py` — border-search, whole-roll, coverage-recovery, and archive integration tests.

## Engineering review before the redesign (historical)

This section preserves the preceding review and its evidence. References to proposed or unimplemented work describe that checkpoint; the latest implementation and validation results are in the report linked above.

### Two concrete bugs fixed during this review

1. **Favorites started from the wrong frame when the last preview was not selected.** The runner used the largest selected favorite index as its starting position. If preview ended at frame 6 and only frame 2 was selected, it could treat the scanner as already at frame 2. The route and runner now use the persisted transport position, falling back to the completed preview count. A regression test checks frame 3 → selected frame 2 → final frame 1.
2. **Three-source stitch metadata paired sources with the wrong offsets.** Sources were stored as centre/back/forward while the three-image stitch passed back/centre/forward. Recovery guidance indexed these arrays together. The stitch now preserves source order with centre as reference. The test checks that the centre source has zero offset.

These corrections fix bookkeeping; they do not measure roller drift or validate old border coordinates after seeking.

### Architecture changes recommended next

| Recommendation | Inspected state and required change |
| --- | --- |
| Finish exploration at 300 DPI | Agree. Wide recovery still takes three initial high-resolution tiles and may take up to five more 1800 DPI probes. Replace this with bounded low-resolution border **and rebate** search, then a fixed archival acquisition plan. The low-resolution search currently stops at both edges and also needs the padded rebate criterion. |
| At most two archival tiles | A planning target, not an unconditional guarantee. Select one or two verified windows whose union contains the frame plus margins and sufficient overlap. If low-resolution evidence cannot establish a feasible plan, preserve previews and stop before archival acquisition. Do not start another high-resolution search. |
| Whole-roll scans in place | Agree. Currently the app first previews the roll, then seeks backward to scan selected/all previews. Change to local border verification → positioning → archival acquisition → advance for each frame. This reduces reversals and reuse of old coordinates. |
| Verify favorites after seeking | Agree. After arrival, take a fresh 300 DPI image, register it against saved preview content, reject unreliable matches, and re-find borders or correct position before planning acquisition. Acknowledged frame movement is not optical proof of alignment. |
| Configurable end action | Add `return_to_frame_1`, `hold_at_end`, and `eject_forward`, retaining return-to-first as the user's current default preference. Validate the chosen action. **First implement in-place Scan all:** the present scan itself needs backward seeking, so simply removing the backward gate would leave an unmet scan dependency. |
| Reconcile fine offsets before advancing | Additional issue found: adaptive probes can finish at nonzero `net_completed_steps`. The child records it, but the parent does not reconcile it before the next frame move. Track both frame index and fine offset/uncertainty; restore or adopt a verified anchor before advancing. Return to frame 1 currently means acknowledged relative commands, not a verified optical landing. |

### Existing features and numerical caveats

- **Full-window capture already exists** in `full_frame_scan_options()` for border-aware frame, favorites, and whole-roll scans: RGB16 at 1800 DPI, `[0, 2586/1800] × [0, .95]` inches. Use actual delivered dimensions for plans: the observed width was 2585. `ScanCrop` and saved general-purpose settings still have narrower defaults. A default migration must distinguish the historically validated baseline from the new default.
- **Cross-resolution pad:** ten 1800 DPI pixels is approximately 0.141 mm or 1.67 pixels at 300 DPI. It is a proposed longitudinal minimum, not a measured universal bound; the directed sequence's vertical mismatch exceeded it. Add uncertainty on top of the rebate margin per axis and collect repeated measurements before tightening it. This pad is not currently implemented.
- **A fixed ±15-pixel motor prediction is unsupported.** The proposed 0.060 mm/step conflicts with the 1.86 mm forward versus 1.20 mm backward observations over 20 steps. At 1800 DPI that difference is about 47 pixels. Predict from local image-measured offsets, propagate their uncertainty, and calibrate a narrow high-resolution search against those data rather than nominal step count alone.
- **A stitch correlation gate already exists:** nonfinite or below-0.05 final strengths fail the stitch. This alone cannot prove a seam correct. Add displacement consistency, adequate overlap, ambiguity/second-peak checks, and a calibrated confidence policy. Preserve failed tiles and report unverified alignment. `UNVERIFIED_STITCH_ALIGNMENT` is proposed terminology, not a current contract state.
- **Unstitched source TIFFs already remain** beside the composite with hashes, positions, and metadata. Preserve that in the redesign. These are vendor-calibrated transmission acquisitions, not demonstrated raw sensor samples. Effective sensor precision is still unmeasured.
- **The orange-mask prior already exists** in `film_type_detection.detect()`, using visible rebates and channel ratios. Orange base yields a 0.96 heuristic score, and application requires 0.80. Scores are not calibrated probabilities or evidence of near-100% accuracy. Missing rebates, unusual film bases, clipping, and colored scene content still require the uncertain/manual path.
- **The quoted 21-second/66-second timings are unverified estimates here.** The inspected measurement JSON files record geometry/registration, not duration benchmarks. Confirm timestamps before using those numbers for ETA or performance claims. Total scan time includes acquisition, transport, transfer, and processing; do not attribute it entirely to USB.

### Evidence and validation for this review

Inspected local evidence: `.local/border-finder/20261031-full-window-1800-test/measurements.json`, `.local/border-finder/20261031-directed-nudge-stay-put/measurements.json`, and `services/scanner_host/native_validation.json`. Private acquisitions and measurements remain outside version control.

The supplied draft mentioned duplicate text; the on-disk summary contained one title block. `FRAME_SUMMARY.md` is now the canonical full document. The old dated summary links here so there is one maintained full copy.

Code-correction tests: `python -m pytest -q tests/api/test_frame_align_api.py::test_favorite_seek_starts_at_last_preview_even_when_it_is_not_selected tests/api/test_frame_align_api.py::test_stitched_scan_calibrates_stitches_and_crops_exactly tests/api/test_frame_align_api.py::test_scan_favorite_uses_overlap_for_preview_known_to_be_too_wide` → **3 passed in 29.49 seconds**. These use the fake bridge; no physical scanner commands were issued during this review.

Workflow check: `npm run test:native-ui` → **passed**, synthetic pipe helper with no device access and no JavaScript exceptions. `git diff --check` found no whitespace errors in the changed code; Git reported line-ending notices only. The earlier 33-test file result belongs to the preceding change, not a new full-file run after this review.
