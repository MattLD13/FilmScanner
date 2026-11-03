# Maximum-height and vertical-containment investigation

Follow-up: [the CyberView processing comparison](cyberview-processing-validation-2026-11-02.md)
found the lower light band in CyberView's own pre-film pixels and saved16-bit TIFF.
It is not unique to FRAME's TIFF/display path. Its precise optical/calibration
mechanism and full vertical containment remain unverified; no automatic crop/fill
was added to hide it.

## Result

The requested investigation was performed on the loaded six-frame strip. FRAME
already requests the full height supported by the installed CyberView X scanner
module. Three fresh hardware captures succeeded, but neither they nor the twelve
retained original archival tiles establish a reliable pair of top/bottom
film-base borders. Vertical containment therefore remains **unknown**, with an
investigated acquisition-path limit rather than an unperformed test.

This does not prove that picture content is missing. It also does not justify
claiming that the full exposed picture is vertically contained. Production
acquisition bounds, safety margins, originals, crop behavior and evidence gates
were not changed to force a passing result.

## Vendor evidence: height and precision

The installed `SCAN08.dll` was read as bytes, not patched or executed for static
analysis. SHA-256:
`da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f`.

The coordinate conversion at `0x100110af` multiplies requested inch coordinates
by the1800-DPI reference scale. Its Y comparisons at `0x10011132` and
`0x10011148` clamp to `0x6ac` = **1708**; X clamps to `0xa1a` =2586. Thus
simply increasing FRAME's requested bottom coordinate would not obtain a taller
window through this module. Native startup independently requires the module's
capability block to report the reviewed2586×1708 maximum. Both fresh1800-DPI
captures returned1708 rows. This establishes a limit of the reviewed supported
vendor path, not an independently measured physical CCD/aperture maximum or a
proof that every possible low-level driver could expose no more.

CyberView's installed manual describes choosing8-bit or16-bit color depth. Its
module's mode5/7 LUT expansion at `0x10011909` iterates4096 entries, shifts values
left4 bits, and replicates them across16 table indices. These are output-format
and processing facts. They cannot supply the missing calibrated sensor/ADC
precision measurement. The inspected capability/scan contracts expose no measured
ENOB value. Internal lamp/CCD calibration is not itself an externally calibrated
noise/linearity measurement, and no calibrated precision claim was promoted.

## Fresh physical captures

All used full-window `[0,2586/1800] × [0,.95]` inch requests, negative RGB,
manual caller exposures119/155/253, vendor auto exposure off, existing validated
configurations, and identity acquisition LUTs. No explicit frame move, nudge,
focus operation or eject was issued. Vendor initialization still follows its
normal opening/calibration path.

| Capture | Delivered size | Elapsed including applicable startup | Vendor frame counter |
| --- | --- | --- | --- |
|300 DPI RGB8|430×284|28.664s|1|
|1800 DPI RGB16|2585×1708|61.524s|1|
|1800 DPI RGB8 comparison|2585×1708|125.804s|1|

The8-bit1800 capture used a newly opened driver and included startup/calibration;
its elapsed time is not a steady-state8-bit-versus16-bit scan benchmark.

At the declared DPI,1708 rows correspond to24.1018mm. This scale has not been
independently calibrated with a geometric target. A nominal24mm picture would
leave only0.1018mm total extra height. The existing conservative containment
policy requires about0.40435mm on **each** side: the.15mm film-base witness plus
the provisional cross-resolution uncertainty pad. A nominal24mm picture plus
those margins would require about24.8087mm. Nominal picture size is a prior,
not a measurement of this strip, so this arithmetic does not establish clipping.
It explains why the current window cannot prove that nominal picture with the
existing margins.

## Edge audit and bottom-band comparison

Read-only analysis used the existing film-base edge detector on each **original**
image, with full original coverage and no stitched/filled borders. It inspected
the three fresh captures and both archival original tiles from each of the six
previously accepted frames: **15 sources**, all with matching SHA-256 values.
None supplied a reliable pair of vertical film-base borders under the existing
detector criteria. No stitched master was used to manufacture border evidence.

The new1800-DPI original has a dark/low-transmission band near its bottom, appearing
white after negative inversion. It is present in both8-bit and16-bit1800-DPI
captures. The central-band all-channel-zero fraction in the last row was about
51.4% in16-bit and85.4% in8-bit. Different quantization thresholds and separate
calibration/opening states preclude attributing that difference to one cause.
The300-DPI image has no exactly-zero samples in those inspected bottom rows.
Neither that difference nor the band proves extra scene coverage in300 DPI,
identifies its physical/software mechanism, or establishes a true film-base edge.
Changing container depth did not produce a taller window or verify containment.

The generated inspection figure shows the actual acquired window, enlarged top
and bottom strips, and row profiles for all three modes. Its grayscale inverse
transmission display is for edge inspection, not a calibrated optical-density
plot or a proposed color conversion.

## Current behavior and remaining physical limitation

The planner already distinguishes verified horizontal coverage from unknown
vertical containment. When vertical borders are unverified, FRAME keeps the full
acquired height. The normal longitudinal transport moves the recorded picture
horizontally and does not establish additional vertical coverage. No extra
transport loop was introduced for a direction it cannot control.

Further proof would require a way to observe the real top and bottom picture
boundaries: for example, a suitable known-geometry film target and independently
verified holder/view geometry, or a separately investigated acquisition path that
demonstrates additional vertical field. A smaller nominal crop, resizing, padding,
or treating the digital scan edge as a film edge would not provide that proof.

Final driver closed normally; all three fresh vendor counters were1. No frame
advance/eject was requested. New originals remain in ignored local storage:
`.local/vertical-containment/20261102T210150Z/`, with `manifest.json`,
`session.jsonl`, `rgb8-events.jsonl`, `vendor-static-evidence.json`, exact vendor
assembly listings, `vertical-audit.json` and `vertical-inspection.png`.

## Verification

- Fresh hardware acquisitions:3 completed, zero acquisition errors.
- An initial offline analysis invocation failed because its saved-library path
  was relative when converted to a file URI. The local analysis runner was fixed
  to resolve that path; both subsequent audits completed. No scanner operation
  failed or was repeated because of that analysis-only error.
- Original-image audit:15 sources, all hashes matched; vertical result unknown.
- `python -m pytest -q tests/imaging/test_acquisition_plan.py tests/imaging/test_frame_align.py`:
  **30 passed in7.51s**, including separate unknown/unverified vertical states.
- Prior unchanged production-code verification remains467 passed,2 xfailed,
  successful build, native UI and simulated workflow; those checks were not
  presented as a new full-suite run for this read-only investigation.
- No production scanner/API/imaging/UI code changed. Runtime test/analysis
  scripts and vendor artifacts remain local; documentation records the finding.
