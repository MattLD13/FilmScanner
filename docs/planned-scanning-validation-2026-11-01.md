# Planned scanning implementation and validation

Date: November 1, 2026. Changes are in the actual FRAME workspace.

## What changed

| Before | Now | Why this helps |
| --- | --- | --- |
| Native wider coverage could take three initial 1800 DPI passes and five additional expensive probes. | All exploratory border/rebate work runs at 300 DPI. A verified optical plan selects one or two archival tiles. | Limits expensive acquisition; insufficient preview coverage stops before an archival pass. |
| Border search could stop as soon as two edges appeared. | Search requires a rebate plus provisional 18-pixel archival padding per axis; horizontal feasibility drives the plan. | Avoids treating a barely visible edge as safe containment. |
| Nominal positions and old preview coordinates could guide later capture. | Revisited windows receive fresh optical registration; bounded 300 DPI feedback corrects replay offsets. Archival registration is centered on measured image shifts. | Handles unequal forward/backward movement without assuming a fixed motor pitch. |
| Whole-roll scan previewed the roll, sought backward, then scanned it. | Each frame is searched, acquired, reconciled to zero fine-step offset, then advanced. | Reduces whole-frame seeking and prevents unaccounted step offsets carrying into the next advance. |
| Returning to frame 1 was mandatory and required backward validation for every roll. | Choose return to frame 1 (default), hold, or eject forward. Only the selected end action adds its transport requirement. | Supports forward-only strip workflows and makes end behavior explicit. |
| Favorites relied on saved alignment after transport. | Each arrival gets a fresh 300 DPI verification and bounded local search before archival acquisition. | Saved coordinates do not silently survive a potentially drifting seek. |
| A correlation floor was the main stitch check. | Enforce optical displacement bounds, overlap, texture, competing-peak ratio, and correlation floor; preserve source TIFFs on failure. | Rejects ambiguous/ghosted stitches instead of claiming a verified master. |

Source tiles, hashes, positions, and plans remain available beside the derived master. Delivered resolution/depth are checked. The UI retains the full acquired height when vertical borders cannot be proven; horizontal transport cannot enlarge the vertical aperture.

The integration also fixes cancellation during idle processing, movement interruption uncertainty, transient child-job completion notifications, immutable manifest publication, and concurrent source-preview cache publication.

## Automated verification

- Imaging planner/registration and frame alignment: 26 passed, including flat/periodic ambiguity rejection and measured seek displacement.
- Imaging, workspace, and native capability-gate subset: 38 passed.
- Existing border/scan API file plus child-job status regression: 35 passed in 118.52 seconds.
- `python -m pytest -q tests/api/test_planned_scan_api.py`: the first **10 passed in 47.21 seconds**, covering in-place ordering, optional end actions, one/two-tile limits, source retention on failure, failure before archival acquisition, favorites arrival verification, child-job status, and cancellation during stitching. A subsequent favorites capability-gate regression passed separately in **5.85 seconds**; the file now contains 11 tests.
- `npm run build`: passed.
- `npm run test:native-ui`: passed, synthetic helper, no device access or JavaScript exceptions.

## Physical before/after evidence

Physical runs use a private isolated library under `.local/planner-validation/`; test tokens, database state, original TIFFs, and measurement JSON remain outside version control. The validation harness bounds the roll job to at most two real frames rather than scanning an unknown full strip length, and attempts one favorite afterward only if that job succeeds. The product's normal roll limit is unchanged.

Baseline, no requested film movement:

| Capture | Delivered size | Elapsed time | Detected borders |
| --- | --- | --- | --- |
| 300 DPI preview | 430 × 284, RGB8 | 93.605 s including cold startup | Right only |
| 1800 DPI full window | 2585 × 1708, RGB16 | 61.252 s | Right only |

Neither baseline acquisition verified complete horizontal coverage. These measurements do not support assuming a universal 21-second preview duration.

The first development hardware run acquired exactly two archival tiles, produced a 2822 × 1711 composite, and found both horizontal borders at x=103 and x=2736. The 2633-pixel separation is about 37.155 mm at the declared DPI, wider than a single window. Its rebate margins were 1.4534 mm and 1.2136 mm. Optical prediction for the second tile was 236.632 pixels horizontally versus 237.174 pixels measured; the residual was about 0.542 pixel. Peak ratio was 37.23 with a 2348-pixel overlap. Vertical containment remained unknown.

That first job then failed during metadata publication because the archive correctly refused an overwrite. Originals and the verified stitched image were preserved; the final metadata publication sequence was corrected before the subsequent validation run. This failed job is not reported as a successful batch.

The corrected **two-frame physical batch passed**, acquired exactly two archival tiles for each frame, and completed its selected return action. Final transport recorded frame index 1, fine-step offset 0, no pending move, and confirmed relative return. Total job time was 537.693 seconds including startup, low-resolution search, motor movements, optical arrival checks, four archival passes, processing, and return.

| Result | Frame 1 | Frame 2 |
| --- | --- | --- |
| Acquired composite | 2824 × 1710 | 2898 × 1712 |
| Detected side borders | x=100 and x=2734 | x=75 and x=2707 |
| Exposure width at declared DPI | about 37.169 mm | about 37.140 mm |
| Left/right rebate margins | 1.4111 / 1.2700 mm | 1.0583 / 2.6952 mm |
| High-resolution tiles | 2, each 2585 × 1708 | 2, each 2585 × 1708 |
| Predicted/measured horizontal tile shift | 239.785 / 239.026 px | 312.981 / 312.807 px |
| Correlation peak ratio | 43.06 | 52.62 |
| Horizontal coverage | Verified | Verified |
| Vertical containment | Unknown; full height retained | Unknown; full height retained |

The four archival tiles took 61.368–61.375 seconds each. Their four warm 300 DPI arrival checks took 8.006–8.011 seconds each. These are measurements for this run, not universal latency guarantees.

The follow-up favorite seek measured `dx=-8.056`, `dy=-1.101` pixels at 300 DPI compared with its saved preview, peak 0.7597 and peak ratio 27.30. That is approximately **48.4 archival pixels of longitudinal seek error**, showing why saved border coordinates must not be reused unchanged. The job re-found geometry locally before its two archival captures and **passed in 216.101 seconds**, producing a 2883 × 1709 master with verified horizontal borders. It returned to relative frame 1 with fine-step offset 0 and no pending movement. No forward eject was requested during the physical run.

All **23 preserved source files** in the final validation library matched their recorded SHA-256 hashes; there were zero mismatches. The helper closed normally after the test. Detailed machine-readable evidence is `.local/planner-validation/after-final/verified-results.json`; individual session logs, raw TIFFs, and the failed development-run evidence remain alongside it in the ignored validation folders. Those files were not added to the user archive or version control.

![Physical acquisition comparison: original single-pass left border missing; planned two-tile acquisition has both side borders](../.local/planner-validation/before-after.png)

The comparison uses the same grayscale viewing transform for both acquisitions so it compares coverage rather than color processing. Green lines indicate detected borders; red indicates a missing border. Original color TIFFs remain unchanged.

Overall elapsed time must not be compared against the single-pass baseline as an equal-work speed benchmark: the baseline was incomplete, whereas the new job searches and verifies coverage. The former wide path required at least three expensive archival captures and could use up to eight; the new native path is bounded to at most two. This limits archival acquisition time but is not itself a measured end-to-end speedup against an equivalent old whole-roll run.

## Limits

The 18-pixel uncertainty allowance is provisional, not a calibrated mechanical bound. Return to frame 1 uses acknowledged relative frame commands; it does not provide an absolute encoder position. Only measured side-border coverage is verified when top/bottom borders are not visible. A bounded two-frame physical run is not proof of reliability across every frame of a full roll.

## Follow-up: blue, washed-out negative conversion

The user reported the blue/bright rendered image after the coverage tests. Inspection of the saved TIFF and recipe established that approximately 1.5% of the stitched image comprised near-white clipped edge/artifact pixels. These dominated the brightest-0.5% base estimate, causing `negative.suggest_base` to reject the estimate. The viewing recipe therefore retained identity film base `[1,1,1]` and the older response 1.6, leaving the orange negative mask uncorrected and producing a blue, washed-out positive. No positive-display exposure boost had been set.

The estimator now excludes a small population of pixels clipped in any channel before estimating the base, while still refusing estimates when more than 5% are clipped or there is insufficient valid contrast/data. This threshold is a conservative software heuristic, not a film calibration. For the first final validation scan, the corrected estimated base is approximately `[0.7100, 0.5408, 0.3378]`, and the suggested response is 0.5. The picture interior had no pixels at or above 0.99 transmission in any channel; this establishes that the broad washed-out positive was not caused by upper-limit clipping throughout the scanned picture. It does not establish the original camera exposure or a calibrated final color appearance.

The three saved validation captures were rebalanced through the existing Balance negative API using the same originals. All three TIFF hashes remained unchanged. Other saved user edits were not migrated. New acquisitions use the corrected estimate; older scans can be rebalanced explicitly with **Balance negative** after loading the updated backend. No scanner movement or new acquisition was needed.

![Same TIFF before and after correcting the negative conversion](../.local/planner-validation/color-review/before-after.jpg)

This is a corrected starting conversion, not a measured scanner/film color profile. Some remaining color or tonal adjustment may be appropriate. Private recipes, clipping statistics, hashes, and comparison JPEGs are under `.local/planner-validation/color-review/`.

Follow-up verification: `python -m pytest -q tests/imaging/test_negative.py tests/api/test_cyberscan_workspace.py tests/api/test_planned_scan_api.py` → **28 passed in 63.10 seconds**. `npm run test:native-ui` → **passed**, synthetic helper with no device access or JavaScript exceptions. New regression cases cover a small white clipped scanner edge without loss of orange-base correction, and refusal of extensive clipping. `git diff --check` passed for the changed estimator, tests, and report.

## Main files

- `services/imaging/acquisition_plan.py`: planning and constrained optical registration.
- `services/api/cyberview_routes.py`: search, per-frame acquisition, transport ledger, end actions, and favorites verification.
- `apps/web/src/cyberscan.tsx`, `packages/contracts/schema.ts`: UI and end-action contract.
- `tests/imaging/test_acquisition_plan.py`, `tests/api/test_planned_scan_api.py`: new regression coverage.

## Follow-up: user-provided Kodak Gold 200 Noritsu reference

The user identified the stock as Kodak Gold 200 and supplied the Nice Film Club/Noritsu JPEG of the same garden frame. The corrected generic base/response conversion was still visibly too dark and cool. Removing the clipped-edge estimator failure did not establish a correct stock-specific display curve.

An optional local appearance profile, **Kodak Gold 200 · Nice Film Club reference (experimental)**, was fitted using the existing global monotone channel-curve pipeline. It is listed in Film & colour, but is not a new global default and was not applied to other saved user images. The validation capture alone was rendered with it through the app API. Both the original TIFF and reference JPEG hashes remained unchanged, and no scanner acquisition or transport action was issued.

Registration used 3189 matching inlier features with median error 1.191 source pixels. The reference was aligned to scanner geometry for comparison/training; the output retains the scanner's original pixels and geometry. Global RGB curves were trained on 120119 sparse pixels, excluding entire spatial blocks containing 963935 test pixels. The profile transfers tone/color only, without reference texture or sharpening.

On the held-out blocks, RGB mean absolute difference against the aligned lab JPEG decreased from **38.62 to 9.11 on an 8-bit scale**. Median luminance was 0.382 for the previous conversion, 0.522 for the fitted output, and 0.523 for the reference. These measurements describe appearance matching for this negative only; the user-provided lab JPEG is not a scanner characterization target or proof that the curves generalize to all Gold 200 scenes.

Profile ID: `23afb8a6a5121d0d`. Local profile, recipe, holdout metrics, full-size TIFF/JPEG, and comparison are under `.local/planner-validation/noritsu-gold200/`. A copy of the explicitly named profile is cached in the normal ignored `data/film_profiles/` folder. Existing capture recipes remain selectable and reversible. Reload the app's profile list to select this reference appearance on another saved negative; review each result.

![Previous conversion, reference-derived appearance, and aligned Noritsu scan](../.local/planner-validation/noritsu-gold200/comparison.jpg)

Verification: `python -m pytest -q tests/imaging/test_reference_tone.py tests/imaging/test_negative.py tests/api/test_cyberscan_workspace.py` → **20 passed in 2.99 seconds**. The profile passed schema/content-hash validation, appeared in the authenticated profile list, and rendered through the authenticated capture API without altering the TIFF. No general conversion-code or global-default change was made in this follow-up.

## General standard conversion requested by the user

The user clarified that a profile fitted to a particular reference was unnecessary: the normal immediate output should be usable. The actual default conversion was therefore updated in `negative.suggest_display()` and the API's `initial_adjustments()` path. No lab/reference pixels, vendor LUT, stock-name lookup, or per-frame fitted profile is used by this default.

After robust film-base removal and the existing nominal 0.5 negative response, the general display recipe estimates endpoints from picture pixels, excluding rebate and uncovered/outer scan edges. Black adjustment is bounded to 0–0.03, white to 0.85–1, and a gentle fixed gamma of 1.2 raises midtones without forcing each image's mean brightness to a target. Only supported near-neutral highlights contribute to the small color balance (channel gains bounded to 0.88–1.12); a green scene is not forced to average gray. Flat or insufficient inputs do not produce an unsupported suggestion. Explicit vendor/reference profiles remain separate optional edits, not the default.

The UI labels the no-extra-profile option **Standard conversion**. New negative acquisitions receive it automatically. **Balance negative** recalculates it for an existing scan when no optional film profile is selected. Original TIFFs and saved edits on other frames are not overwritten or silently migrated.

Saved immediate outputs were compared offline: FRAME's prior/default and the updated standard rendering from the same TIFF, alongside the saved CyberView positive JPEG. The saved CyberView output is itself darker/cooler than the user-provided Noritsu JPEG; it is evidence of a usable vendor starting rendition, not an exact appearance target. Acquisition exposure/framing differ between the saved vendor capture and the current TIFF, so this is a visual appearance comparison, not a controlled scanner benchmark. No new scanner operation was issued.

The three saved validation acquisitions (two frames plus one repeat) were re-rendered with ordinary recipe fields and no film profile. Example frame 1: black 0.02767, white 0.85, gamma 1.2, RGB balance `[1.12, 0.9664, 1.0008]`. Original file hashes remained unchanged. These examples demonstrate the default on the available garden images, not all stocks/lighting conditions. The balance and endpoint bounds are conservative heuristics, not measured scanner colorimetry.

![FRAME old default, updated general default, and saved CyberView immediate output](../.local/planner-validation/general-display/comparison.jpg)

Validation:

- `python -m pytest -q tests/imaging/test_negative.py tests/api/test_cyberscan_workspace.py tests/api/test_planned_scan_api.py` → **31 passed in 79.47 seconds**.
- Additional native acquisition assertion confirms that default output has no reference profile, records `reference_used: false`, and receives the new standard display fields: **1 passed in 13.44 seconds**.
- `npm run build` and `npm run test:native-ui` → **passed**; workflow used the synthetic helper with no device access or JavaScript exceptions.
- Regression tests check brightness lift, neutrality, preservation of a colored scene, bounded changes for dark scenes, mask exclusion, and refusal of flat inputs.

Private comparison images, per-frame recipes, and source hashes are under `.local/planner-validation/general-display/`.

## Audit after the user questioned loss of information

The concern was supported by measurement. In the first saved frame, the former default's luminance-based black point zeroed **5.6085% of previously nonzero red-channel picture samples** (green 0.0431%, blue 0.1577%). Other saved acquisitions lost approximately 0.98–1.00% red and 1.54–1.80% blue samples at that display stage. The TIFF acquisitions retained their original data; processed views/exports could hide or clip channel distinctions despite the files being preserved. The earlier presentation of the brightness adjustment as a sufficient conversion fix was too strong.

`frame-negative-display-2` now keeps black/white endpoints at 0/1, removes the automatic scene-derived RGB gains, and uses only an editable, strictly monotone viewing curve/gamma. Across the three available acquisitions, the display stage now newly clips **0%** of channels to black or white relative to the nominal-inversion output. This is a floating-point processing check before final JPEG/16-bit quantization. It does not erase clipping introduced at acquisition or by the preceding film-base inversion (which clamps transmission above the estimated base), nor does it prove a physically calibrated conversion. Dense low-red synthetic ramps are tested for strict monotonicity and no new endpoint plateaus.

The acquisition audit also found a separate omitted stage: planned native captures did not call the existing `film_base_exposure()` function used by the ordinary scan path. That function now uses the robust unclipped film-base estimate, and planned acquisitions call it from the locally measured preview **before** archival scanning, using only the already validated exposure configurations/range. The adjustment is per-channel acquisition exposure toward the existing verified 0.85 film-base target, not an exposure boost on the rendered positive. The requested settings and measured/next exposure values are recorded in the session. New pipeline tests assert that this stage runs and respects validation bounds. This integration has synthetic regression coverage; no additional physical exposure run was performed in this follow-up.

Saved measurements put the unbalanced frame's base at roughly `[0.710, 0.541, 0.338]` versus a previously exposure-normalized `[0.840, 0.855, 0.856]`. Offline diagnostics using the recovered vendor model/film conversion changed substantially when input exposure was normalized. That supports treating acquisition exposure, scanner model curves, and film inversion as distinct stages; it does not establish that software multiplication equals a new sensor exposure, or that a single exponent reproduces CyberView/Noritsu.

The default remains explicitly a nominal negative conversion. Restoring the omitted exposure stage and eliminating proven display clipping are concrete corrections; a generally calibrated color/density conversion is not established by brightening, profile fitting, or visually matching this one garden frame.

![Previous endpoint trim versus endpoint-preserving display and saved CyberView output](../.local/planner-validation/endpoint-display/comparison.jpg)

Private stage-by-stage clipping measurements and unchanged-source checks are in `.local/planner-validation/endpoint-display/clipping-audit.json`. The earlier `general-display/clipping-audit.json` preserves the previous audit. Existing user edits were not silently migrated; the isolated validation captures alone were refreshed through Balance negative.

Verification after the audit and exposure-stage integration: `python -m pytest -q tests/imaging/test_negative.py tests/api/test_cyberscan_workspace.py tests/api/test_planned_scan_api.py` → **33 passed in 67.63 seconds**. `npm run test:native-ui` → **passed**, synthetic helper, no device access/JavaScript exceptions. `git diff --check` reported no whitespace errors (line-ending notices only). During work an export regression exposed a text-encoding change in title separators; that edit was repaired. An older exposure test used a flat-channel fixture that cannot support the now-robust base estimate; it was replaced by explicit usable-orange-strip and unusable-flat-channel cases, requiring exposure adjustment only in the usable case. Both pass. No physical acquisition-exposure retest is claimed for this follow-up.

## Replacing the nominal default with the recovered manufacturer baseline

The user judged CyberView substantially better after the nominal conversion changes. A controlled offline comparison reused the exposure-balanced acquisition `data/sessions/direct-12/exposed1800.tif`: the current nominal curve, the recovered manufacturer's Generic Negative transform, the recovered Kodak 200 transform, and the actual saved CyberView positive. The vendor transforms produced substantially closer tonal separation than the lifted nominal response. This comparison did not fit any curve to reference pixels. It also showed that brightening alone had moved the nominal output away from the vendor's tone scale.

The active default now chooses the local manufacturer's **Generic Negative** film term plus PF1800 AFL `37.GG` model curve for new color negatives when available. It does not choose a photograph-derived reference profile or depend on a Kodak stock name. A cache/load helper accepts only validated vendor-negative profiles with the canonical generic name/root, or reads the genuine local Generic Negative/37.GG pair. Those tables stay in ignored local storage and are not redistributed. If unavailable, the app retains its explicitly nominal fallback. B&W and positive processing are not promoted to this color-negative baseline.

An explicit `vendor_input_balance` recipe field applies measured input normalization toward the previously validated 0.85 film-base target before the vendor model/film transform. This is separate from display brightness and is reversible. It helps re-render already saved unbalanced captures, but software multiplication cannot recover weak-channel sensor signal, noise performance, or clipped acquisition values. The separately restored acquisition-exposure stage remains the correct place to improve future capture levels. Display gamma, endpoints, curve, and RGB gains are neutral for the vendor default; the preceding cosmetic midtone lift is not stacked on top.

The new field defaults to false so archived vendor recipes retain exact prior behavior. It is carried through the shared contract, preview request, saved edits, and export path. Manually selecting a vendor profile resets generic display adjustments, and enables measured input normalization only when valid film-base values exist. Balance negative can explicitly upgrade an older no-profile negative. No other saved user edits were migrated; three isolated validation records were re-rendered and TIFF hashes stayed unchanged.

![Earlier nominal default, recovered generic manufacturer default, and actual saved CyberView output](../.local/planner-validation/vendor-default/comparison.jpg)

The new baseline is closer but **full CyberView parity is not established**. The exact auto-gamma caller state remains unresolved, generic and stock film terms differ, capture exposure/framing differ, and fine detail is affected by acquisition optics and sampling. The manufacturer's transform itself contains LUT quantization and possible gamut clipping; no new lossless-color or raw-sensor claim is made. Private no-fit comparisons, new recipes, and source checks are under `.local/vendor-baseline-review/` and `.local/planner-validation/vendor-default/`.

Verification: `python -m pytest -q tests/imaging/test_vendor_negative.py tests/imaging/test_negative.py tests/api/test_cyberscan_workspace.py tests/api/test_planned_scan_api.py` → **40 passed in 67.96 seconds**. A subsequently added API regression also passed (**1 in 6.28 seconds**) and verifies automatic selection of a synthetic manufacturer generic profile, neutral display controls, explicit input normalization, valid preview/rebalance, and immutable original bytes. `npm run build` passed. Fixture vendor paths are isolated so tests cannot accidentally depend on this machine's installed curves. CPU-only tests distinguish the new normalization from unchanged legacy vendor recipes.

`npm run test:native-ui` also passed with the synthetic helper, no device access, and no JavaScript exceptions. The no-table option is now labeled Basic conversion (fallback), so it is not confused with the new recovered-vendor default.
