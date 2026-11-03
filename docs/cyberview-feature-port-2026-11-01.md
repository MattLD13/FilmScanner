# CyberView feature port and physical validation

November2 processing update: [observed sequence and physical FRAME acceptance](cyberview-processing-validation-2026-11-02.md)
supersedes the earlier Generic Negative stage-order uncertainty below. The UI
film-conversion/automatic-table sequence, RGB8 application and prescan-table reuse
on the saved RGB16 TIFF were replayed exactly. New vendor-negative defaults apply
automatic tone and preserve the chosen preview table on planned/favorite scans.
This does not establish identical acquisition calibration/exposure, other film
types, nonzero mode8/ROC/GEM behavior or calibrated sensor precision.

This report covers the requested automatic processing, exposure, transport/focus,
extra acquisition modes, optional filters, repeated sampling, and precision work.
Changes are in the actual FRAME workspace. No fitted photograph profile is used
to establish these features. Vendor binaries/tables and original test images stay
in ignored local storage. Work continued without further delegation after the
user requested that.

November 2 continuation: [the six-frame strip acceptance report](strip-acceptance-2026-11-02.md)
records a successful physical all-frame scan, fresh-witness end check, photographic
return verification, favorite rescan with two samples per tile, and89 matching
recorded file hashes. Full software suite:467 passed,2 xfailed; build, native UI
and simulated workflow passed. This bounded strip result does not broaden the
acquisition-mode, vertical-containment or precision claims below.

## Implemented and tested

| Area | Implementation | Evidence and limits |
| --- | --- | --- |
| Automatic color/tone | Existing exact parameter calculation and manufacturer model/film conversion retained; added exact pinned vendor automatic-table worker and exact mode-7 application. Optional **Try vendor auto tone** stores tables and diagnostics in the recipe. | Actual CPU oracle comparisons, including the complete 16-bit integer domain. Complete CyberView UI plane/state order is still unresolved, so this option is explicit/experimental, not default full-parity processing. |
| Vendor auto exposure | Scan request selector 32 receives the genuine flag 1. Metadata distinguishes requested seeds, unchanged caller block, and unknown effective internal gains. | Actual 300 RGB8 and 1800 RGB16 full-window captures passed after a bounded callback compatibility fix; a balanced 120/168/269 seed also passed. Restricted to recorded geometries. |
| Go to frame | Bounded vendor relative-counter reads and one-frame moves; application frame labels can use a software origin. | Actual raw counter 1 → 2 → 1, with images retained. Return had about 11 preview pixels of optical offset; not an absolute encoder or exact repositioning claim. Old border coordinates are invalidated. |
| Reset frame labels | **Label current frame as 1** records a software origin without issuing a device command or rewriting a hardware counter. | API tests cover initialization/busy checks, target translation, and reset on release. No unsupported hardware setter was invented. |
| Manual focus | Selector 16, selector-15 readback, then scan applies the stored value. | Actual steps 2 → 3 → 2 and 600 DPI captures. Production range restricted to tested steps 2–3; the wider parameter range is not promoted. |
| Vendor realignment | Selector 23 after session initialization, unchanged counter required; old preview generation invalidated. | Actual operation followed by 300 DPI image. Same frame, measured displacement relative to initial preview about −2.866 px x / +1.991 px y. Not proof that both exposure borders fit in one aperture. |
| More acquisition modes | New exact configuration records plus **Scan selected settings** in advanced controls. | Actual mode table below. Unsupported combinations still fail the acquisition gate. |
| Cleanup/detail | Optional color restoration, edge-aware grain smoothing, constrained sharpening; disabled settings preserve the prior image path. | Synthetic image tests, image demonstrations, API preview/export/hash tests. These are general software alternatives, **not exact Kodak ROC/GEM ports**. |
| Repeated sampling | 1/2/4 captures per planned tile, optical alignment, contribution/coverage metadata, derived average and retained original TIFFs. | Synthetic API tests and an offline mean of three actual same-setting acquisitions. Fixed exposure required; vendor auto-exposure repeats are rejected. No new optical resolution is claimed. |
| Precision diagnostics | Per-source code grid/occupancy, provenance, hashes, and stationary-repeat output-noise measurement; CLI rejects processed/stitched means as sensor evidence. | Three real originals measured. 16-bit storage carries 12-bit-aligned output codes. Effective sensor/ADC precision remains unmeasured for the reasons below. |

## Physical acquisition modes

All rows used a loaded negative strip, identity device LUT, default 100/100/100
exposure seeds, and the full window unless otherwise stated. Each original's
geometry/channel count/depth, nonflat pixel range, and SHA-256 were checked.
The completed configuration is promoted individually, not every combination of
every menu value.

| Requested mode | Actual pixels | TIFF channels/depth | Time |
| --- | --- | --- | --- |
| 360 DPI RGB8 | 517 × 341 | RGB / 8-bit | 15.833 s |
| 450 DPI RGB16 | 646 × 427 | RGB / 16-bit | 17.387 s |
| 600 DPI RGB8 | 861 × 569 | RGB / 8-bit | 14.572 s |
| 900 DPI RGB8 | 1292 × 854 | RGB / 8-bit | 17.406 s |
| 900 DPI RGB16 | 1292 × 854 | RGB / 16-bit | 17.432 s |
| 300 DPI grayscale8 | 430 × 284 | 1 / 8-bit | 14.515 s |
| 600 DPI grayscale16 | 861 × 569 | 1 / 16-bit | 14.542 s |
| 1800 DPI RGB8 | 2585 × 1708 | RGB / 8-bit | 26.541 s |
| 1800 DPI grayscale8 | 2585 × 1708 | 1 / 8-bit | 26.461 s |
| 1800 DPI grayscale16 | 2585 × 1708 | 1 / 16-bit | 61.205 s |
| 300 DPI binary requested | 430 × 284 | Original grayscale8 retained; threshold is an edit | 14.522 s |
| 300 DPI positive-mode RGB8 | 430 × 284 | RGB / 8-bit | 14.507 s |
| 1800 DPI positive-mode RGB16 | 2585 × 1708 | RGB / 16-bit | 61.519 s |
| 600 DPI custom area [0.1,0.05,1.3,0.90] inches | 719 × 509 | RGB / 16-bit | 13.973 s |
| 600 DPI full-window after autofocus | 861 × 569 | RGB / 16-bit | Retained in control manifest |

Positive-mode transfer on a negative strip verifies that acquisition setting only.
It does not verify slide color, mounted media, loading mechanics, or mount sensing.
The user confirmed only a film strip is available; mounted-slide handling remains
unverified and was not enabled by this work. Arbitrary custom rectangles likewise
remain gated unless covered by recorded configuration evidence.

## Vendor automatic exposure: actual failure and correction

The first flag-1 300 DPI test failed FRAME's strict image-strip sequence check.
Static inspection of pinned SCAN08 `0x100074e6` through `0x100075a8` showed that
its preview shortcut builds a legacy 0x24-byte callback record. Ordinary scan
callbacks include a tail through 0x2c; the shortcut never populates the tail's
remaining-line count. The host had read unrelated stack values as that count.

For exactly flag-1 / 300 DPI / RGB8, the host now validates geometry, cumulative
rows, no overflow/duplicate final strip, and final flag versus full delivered
height. Other paths retain strict remaining-line checks. A fake legacy-tail test
is accepted only with that exact flag/mode and rejected without it. The rebuilt
production helper hash is `bc5d0c6a9c21074bc36e65a6da193c67bec3281e188eb0aa2aedf5e4c92b1584`.

After that fix, 300 RGB8 completed in 14.543 s, 1800 RGB16 in 75.874 s, and a
balanced-seed 1800 RGB16 pass in 75.885 s. All reported complete 430×284 or
2585×1708 images and unchanged relative frame counter. The auto branch uses
internal request copies; unchanged caller-block seeds do not measure effective
exposure. Selector 33 reads different/default globals and is not substituted as
proof of the chosen gains.

Further static inspection of `0x10004a7f` shows a clipping/density exposure
adjustment that scales existing channel seeds. It does not itself establish the
orange-mask/DMin channel ratios. FRAME's separate measured film-base exposure
stage therefore remains relevant. The new flag is not presented as a complete
replacement for CyberView's UI calibration/DMin/Auto Gamma sequence.

Native auto exposure is available only for the recorded negative full-window and
existing default-inset RGB8/300 and RGB16/1800 geometries. The inset captures also
passed with balanced seeds: 413×283 in 28.878 s and 2479×1703 in 75.713 s. These
extra checks make the checkbox usable with the app's existing default scan area
without admitting arbitrary new automatic-exposure combinations.
Repeated sampling requires fixed manual
exposure because equal requested seeds do not prove equal internally chosen gains.

## Actual delivered precision and repeat noise

Three stationary full-window 1800 DPI RGB16 acquisitions used identical manual
100/100/100 settings and no requested intervening motor move. Their source hashes
were checked before and after analysis. All three channels on all three originals
have a **16-code lattice and four zero low bits**: 12-bit-aligned codes inside a
16-bit TIFF. This is an actual output-code observation, not an ADC ENOB result.

Optical registration relative to the first original measured approximately:

- repeat 2: dx −0.0449 px, dy +0.1610 px, peak ratio 37.15;
- repeat 3: dx −0.0663 px, dy +1.0539 px, peak ratio 35.37.

The output-noise measurement used 1,533,942 acquired low-gradient pixels. Robust
pair-difference sigmas were approximately R 467.23, G 335.12, B 336.74 in 16-bit
output codes, with nonzero global pair offsets. These include lamp/calibration
variation, residual motion/interpolation, and scene/film texture; they must not be
headlined as effective sensor bits. The report's qualified output-noise-equivalent
numbers are about 5.34/5.82/5.81 bits under those assumptions, **not a finding that
the scanner has a 5–6-bit ADC**. `effective_sensor_bits` and `effective_adc_bits`
remain null.

Actual effective sensor precision needs controlled flat/dark or calibrated-target
measurements and a known linear raw response. The vendor-calibrated image stream
and the available photographed film cannot establish it. The user has no calibrated
target available; this limitation is explicit rather than replaced with a guessed
12- or 16-bit sensor claim. Method: [sensor-precision-method.md](sensor-precision-method.md).

The three originals were also optically averaged without exposure matching.
99.8443% of the reference area had contributions from all repeats; edge pixels
with fewer acquired contributions are recorded separately. Original repeat TIFFs
remain independent of the derived mean.

## Output demonstrations

![Actual acquisitions, recovered conversion, optional vendor tone, and saved CyberView](../.local/feature-port/final-comparison/comparison.jpg)

Equal displayed widths preserve each source's aspect ratio. Acquisition time,
framing, and exposure differ. No reference photograph was fitted into these curves.
The isolated vendor-tone example is not evidence of exact full UI stage order.

![Generic optional filters and real repeat averaging demonstration](../.local/feature-port/filters/comparison.jpg)

Restoration/sharpening/grain processing changes a derived rendition and cannot
reconstruct information absent from the original. Infrared cleaning remains
unavailable on the current scanner path.

## Remaining work, without overclaiming completion

1. **Full CyberView automatic-processing parity:** the exact isolated table worker
   and application are recovered, but complete UI plane/state/order and the
   separate Auto color curve-builder selection are not fully reconstructed.
   [vendor-autogamma-investigation.md](vendor-autogamma-investigation.md) records
   the distinction. The default manufacturer conversion is not relabeled as a
   pixel-identical CyberView port.
2. **Exact ROC/GEM:** supplied generic alternatives are usable, but do not claim
   to reproduce proprietary Kodak algorithms. Their ports remain unfinished.
3. **Mounted slides:** needs an actual supported mounted slide and physical
   media/status/loading validation; a strip in positive mode is insufficient.
4. **Calibrated effective sensor precision:** needs the target/linear-response
   evidence described above. Actual delivered quantization and repeat output noise
   are now measured and exposed without conflating them with ADC precision.
5. **Broader hardware acceptance:** one strip/scene and adjacent focus/frame tests
   are not a complete roll or all-stock reliability distribution.

## Files, evidence, and verification

Main new modules: `scan_filters.py`, `sensor_precision.py`, `vendor_autogamma.py`.
Native/API/UI/shared contracts are integrated; invalid/ungated operations are
rejected. The evidence manifests and TIFFs are under ignored `.local/feature-port/`
(`device`, `controls`, `vendor-auto-fixed`, `vendor-auto-balanced`, `precision`).
No image library, vendor table, runtime token, or machine-only binary is committed.

The first mode sweep stopped before a focus capture because its isolated allowlist
omitted the full-window 600 RGB16 test configuration; a resumed bounded test
explicitly included that configuration and passed the control sequence. The first
auto-exposure failure and its strict callback fix are recorded above, not omitted.

- Production/fixture native rebuild passed; native/gate/automatic-table subset:
  **66 passed in 5.47 s**.
- Filter, precision, native, automatic-tone, and feature API subset:
  **104 passed in 77.65 s**.
- Vendor auto-tone API tests: **3 passed in 19.40 s**.
- Full `python -m pytest -q`: **452 passed, 2 expected failures in 347.29 s**.
- `npm run build`: passed. `npm run test:native-ui`: passed with the synthetic
  helper, no device access, and no JavaScript exceptions.
- `git diff --check`: no whitespace errors in scoped changes; line-ending notices
  may be printed by Git.

Final evidence check found **32 completed original hardware acquisitions** across
the five isolated runs, all matching recorded hashes. The two earlier stopped
runs remain labeled as stopped, with their configuration/callback errors retained;
successful retries are separate manifests. No native helper or CyberView process
remained open after validation. The last recorded raw vendor frame counter was 1;
no eject was requested. Current gates contain 20 individually recorded acquisition
configurations, four bounded auto-exposure geometries, and focus interval 2–3.

Software fixture tests establish implementation behavior, not new hardware gates.
Only completed, hash-verified physical observations were added to
`native_validation.json`; unsupported modes/media remain unavailable.

## Follow-up: repeat-offset normalization and wide-frame exposure locking

Two refinements were implemented after reviewing the measured repeat drift:

1. `scan_filters.aligned_mean()` now measures each repeat's median RGB difference
   from source 1 over the acquired, unclipped intersection shared by **all** repeats.
   It subtracts that additive vector before accumulating the mean. Registration,
   edge contributor counts, and retained original TIFFs remain unchanged. No
   multiplicative gain or per-source clipping is applied. The derived TIFF mean is
   range-clamped only after averaging; below-zero/above-one counts are explicitly
   recorded rather than silently claiming no processing loss. Every subtraction,
   support count, reference source, and units are stored in `repeat_processing` and
   embedded in the mean TIFF description. The session records derived-tile metadata
   before final stitching, so a subsequent failure does not lose the recipe.
2. Each planned frame freezes its archival acquisition settings after the local
   film-base measurement. A two-tile frame always uses fixed manual/calibrated
   seeds and `flag=0`, even if the user's single-tile vendor-auto preference is on.
   Both tiles and their arrival checks receive frozen settings. Source records,
   final `requested_settings`, and `archival_exposure` identify the actual request
   and the reason for the lock. The global single-tile preference remains intact.
   A single-tile capture can still use `flag=1`; repeated-sampling jobs retain the
   existing requirement for manual exposure. An acquisition that reports vendor
   auto exposure despite a locked request is rejected with the original preserved.

The actual three-original offline replay retained **99.8443%** full-contribution
coverage: 4,292 pixels had one contributor, 2,584 had two, and 4,408,304 had three.
Normalization used 4,382,690 shared unclipped pixels. RGB subtractions, expressed
in 16-bit output codes for readability, were source 1 `[0,0,0]`, source 2
`[153.80,97.58,73.27]`, and source 3 `[344.65,199.83,150.64]`. These are offsets
relative to source 1 over the new common mask, not the earlier adjacent-pair,
low-gradient noise-estimation offsets.

Over valid three-contributor picture pixels, median RGB bias relative to source 1
changed from approximately `[166.83,99.65,74.98]` codes to `[0.68,0.52,0.34]`.
At two-contributor pixels it decreased but did not become zero; sensor noise,
interpolation, and spatial/gain variation remain. A controlled integer-translation
fixture with known additive offsets recovers the reference without a contributor
boundary step. The real data supports correcting the measured additive component,
not a promise that every visible edge artifact is removed.

The derived real mean had 19,237/16,480/22,843 channel samples below zero before
its final range clamp and none above one. These processing counts are retained in
the manifest; originals and the normalization recipe preserve the source evidence.
No existing user average or original was rewritten. Private before/after derived
TIFFs and the read-only audit are in
`.local/feature-port/repeat-offset-normalization/`. No new scanner acquisition was
needed for this refinement, and no hardware validation gate was broadened.

Benchmark clarification: 300 DPI corresponds to approximately **84.7 µm/pixel**;
600 DPI is **42.3 µm/pixel**, not 29.9. Some sweep samples at 300 and 600 DPI took
similar time, but film mode, sample type, startup, and calibration state differ.
Warm arrival checks in the earlier batch were about 8 s, whereas cold previews
were much longer. These observations do not establish universal 14.5 s latency or
that switching every border search to 600 DPI has no cost. The verified 300 DPI
planning pipeline remains unchanged pending a paired benchmark and scale/padding
validation for a new preview configuration.

Follow-up verification:

- `python -m pytest -q tests/imaging/test_scan_filters.py tests/imaging/test_sensor_precision.py`
  → **30 passed in 0.41 s**.
- Filter and feature API subset → **29 passed in 93.21 s**; the separately added
  inconsistent vendor-auto-report case passed in **4.55 s**. These assert matching
  fixed settings across wide tiles, preserved single-tile auto preference, source
  hashes, and failure before another archival tile on a lock inconsistency.
- `python -m pytest -q tests/api/test_frame_align_api.py tests/api/test_planned_scan_api.py tests/imaging/test_sensor_precision.py`
  → **59 passed in 222.02 s**. A Windows asyncio pipe-reset notice occurred during
  fixture teardown; the assertions and process exit succeeded. No physical device
  was used by these tests.
- After adding the embedded mean recipe, its API check plus filter tests →
  **17 passed in 12.60 s**. Both database/session metadata and the TIFF description
  contain the same normalization recipe and original-source hashes.
- `npm run build` and `npm run test:native-ui` → **passed**, synthetic helper,
  no device access or JavaScript exceptions. Scoped `git diff --check` found no
  whitespace errors; Git printed line-ending notices only.
