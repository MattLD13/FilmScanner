# CyberView image-processing and bottom-edge comparison

**Subsequent user preference:** the user preferred the version without preview
tone. Automatic tone is now **off by default** for new previews and scans; the
generic vendor negative conversion remains. The recovered worker and explicit
Auto colour edit remain available, and favorites retain an explicitly selected
preview tone. Existing saved edits are not migrated. The default-on implementation
and physical evidence below describe the preceding checkpoint.

Status: processing sequence recovered and implemented; physical FRAME acceptance
and latest-code software verification passed. This
report distinguishes stage-by-stage pixel comparisons from appearance comparisons
between separate acquisitions. Local evidence is under `.local/cyberview-completion/`.

## Measured CyberView sequence

After scanner recovery and user-confirmed reload, an ordinary CyberView X MF
prescan of the first photograph succeeded without instrumentation. A second
prescan succeeded with read-only hooks restricted to the image-processing routines
in the pinned `CyberViewX.ds`:
`bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb`.
No scanner-module entry point was hooked in these successful observations.

The selected film term was Generic Negative, auto exposure and auto gamma were
enabled, RGB16/1800 DPI was selected for archival output, and digital noise
reduction intensity was0. The actual prescan processing plane was RGB8 at600 DPI:
861×568 for the complete preview and826×566 for its selected picture rectangle.
The existing film strip was used; no calibration-target or sensor-precision claim
is made.

The actual image sequence was:

1. Scanner output with CyberView's model negative LUT already applied.
2. CFilmCIP mode5: manufacturer Generic Negative film table/matrix.
3. `0x10113ce0` calls `0x10103810` with the negative histogram branch (boolean
   low byte1) on that converted-positive prescan plane.
4. Its generated three256-entry tables are copied into CFilmCIP mode7 and applied.
5. Mode8 ran on the preview, but changed no pixels with the observed intensity0.

The isolated CPU worker regenerated both the complete-preview and selected-picture
tables **exactly** from the copied original image-stage inputs. The mode7 Python
application reproduced the copied RGB8 output **byte for byte**.

The full scan produced a2480×1700 RGB16 TIFF. Its recorded pipeline applied mode5,
then mode7 using the table from the **selected826×566 prescan**, without calculating
a new table from the archival pixels. FRAME's mode7 application to the copied
mode5 output reproduced the saved vendor TIFF **pixel for pixel**, across all
12,648,000 channel samples. This proves the observed image stages; it does not
establish equal acquisition exposure/calibration or arbitrary-film parity.

Generating another table from the archival film-converted image instead changed
**607 of768 table entries**. Reusing the selected frame's preview tone is therefore
a substantive behavior, rather than an interchangeable optimization.

Evidence: `cpu-only/sequence-audit.json`, `cpu-only/observations.jsonl`,
`cpu-only/actual-processing-stages.jpg`, `full-scan/observations.jsonl`,
`full-scan/cyberview-original-output.tif`, and `replay-results.json`. The copied
vendor TIFF SHA-256 is
`1d0419172985924be00e83f2fd9e9f549ca56eb1aef3cae185e733c35c47044a`.
Vendor files, tables, pointers and photographs remain local/ignored.

## FRAME changes

- New supported color-negative scans and review previews using the recovered
  vendor-negative profile now receive automatic tone as a reversible viewing
  recipe. Older saved recipes are not migrated. Missing or unsuitable local
  workers retain the generic conversion and record the fallback reason.
- The worker receives the selected converted-positive picture at its existing
  resolution; FRAME no longer strides that image down a second time before the
  vendor's own histogram resize. Acquired-coverage checks exclude small outer
  incomplete rows, reject internal holes/substantially missing areas, and never
  fill missing pixels to manufacture statistics.
- Planned archival captures calculate tone from their local border preview once,
  then reuse the exact table on the stitched/one-tile result. Each frame retains
  its own tone; repeated/tiled capture exposure locking remains unchanged.
- A favorite with strong fresh arrival registration retains its chosen preview
  tone, including a deliberate user-disabled choice. If arrival identity cannot
  be verified, the fresh local preview supplies the new tone instead.
- Metadata records table hash, generator capture/hash, immediate source
  capture/hash, selected acquired region, processing branch and whether the
  archival image reused a preview table. Concurrent preview edits take priority
  over a default calculation from an older snapshot.
- CPU-worker calls are serialized around INI snapshots as well as the worker's
  own named mutex. Each invocation preserves its inputs and restores prior vendor
  settings. The saved CyberView UI settings were restored after comparison.
- Auto colour uses the recovered vendor tone for vendor-negative profiles. It can
  be disabled or recalculated; recalculation changes the editor preview URL so
  the main image refreshes even when the enabled/disabled state is unchanged.
  Changing the underlying film profile/base clears the old tone table.

These changes do not recover acquisition clipping or prove new sensor precision.
Automatic tone intentionally changes displayed endpoints/contrast. The originals
are unchanged and the adjustment is removable. Optional ROC/GEM equivalence,
nonzero vendor mode8 behavior, other film types/modes and complete vendor
auto-exposure/calibration state remain distinct tasks.

## Bottom-edge result

The light lower band is present in both the FRAME scan and the ordinary CyberView
scan. Critically, it is already present in the copied CyberView image **before**
the film term and automatic-tone stages; its last-row central median RGB values
are approximately.9951/.9997/.9992. CyberView's final TIFF reaches white in that
region. The FRAME identity-LUT transmission image reaches low/zero signal there,
which becomes light after negative conversion.

Therefore a unique FRAME TIFF-writing or display-processing cause is ruled out
for the observed band. Its precise optical, per-pass calibration, carriage or
driver-line mechanism remains unisolated. The acquisitions have different crop,
calibration state and exposures: CyberView148/203/322 versus FRAME119/155/253.
They are the same photograph, **not** a controlled equal-settings sensor comparison.
No unsupported exposure range was promoted to force identical caller values.

`bottom-edge-results.json` records original-stage row statistics and hashes;
`bottom-edge-comparison.jpg` shows the pre-film vendor pixels, final vendor TIFF,
and a software conversion of FRAME's original. No crop/fill or unsupported scanner
command was introduced to hide the band. Full vertical containment remains unknown.

## Offline six-frame replay

The actual six retained archival masters and their own border-preview originals
were copied to an isolated library. The new automatic-tone API ran on each
preview, and its table was applied to the corresponding master. The comparison
uses the same FRAME originals before/after, with no lab-photo fitting or edits to
the source library. All48 checked source-file hashes remained unchanged.
`offline-replay-20261103T003407Z/before-after-six-frames.jpg` and `report.json`
contain the images, per-frame generator provenance and displayed endpoint counts.
The UTC folder date is November3; the local work date is November2 in New York.

## Failures and recovery

The first attempted observation also hooked the scanner-module entry point and
strip callbacks. CyberView crashed at SCAN08 offset0x15397 after the prescan
returned, in a later counter call. The captured strips showed repeated buffers,
so that attempt is not usable acquisition evidence. Instrumentation may have
contributed; this is not proof that the uninstrumented vendor scanner code has
that defect. The observer was detached and its files retained separately.

An uninstrumented reopen stayed at Preparing film scanner. The user power-cycled
and reloaded the scanner; the old process still waited and did not exit after a
normal close request. Its settings/log were saved and that specific stalled
PfsLoader process was terminated. A fresh vendor session then calibrated and
completed both uninstrumented and image-only-observed acquisitions. The successful
session later closed normally; no forced termination was used for a running scan.

The first FRAME physical acceptance attempt after the vendor session stopped
before acquisition because the driver reported no film. It is retained as failed
in `native-after-20261103T002817Z/`. The user confirmed another reload at frame1;
the subsequent run is `native-after-20261103T005001Z/` and passed.

Some old UI controls exposed inaccessible element indexes and required refreshed
screenshots/keyboard selection. A local editing command initially failed on the
system default text encoding; it was rerun with explicit UTF-8 before writing.
Neither error changed an original image or issued a scanner command.

## Verification checkpoint

- Focused worker/API tests:17 passed in38.89s.
- API planned/preview/favorite tone tests:24 passed in147.98s.
- Full Python suite at the earlier implementation checkpoint:475 passed,2 xfailed
  in448.18s. Later crop/concurrency refinements require the final checks below.
- Build passed. Native UI workflow passed with no JavaScript exceptions; one
  Windows pipe-close `ConnectionResetError` appeared during fixture shutdown,
  despite the successful workflow result. Final workflow rerun will be reported.
- Simulated36-frame workflow, phone emulation, export/archive/reconnect passed.
- Physical vendor prescan and RGB16 scan succeeded; final FRAME physical acceptance
  subsequently passed as described below. Latest-code full-suite verification is
  still pending at this checkpoint.

## Final physical and preservation result

The physical FRAME quick preview completed in123.299s including its bounded
border search; the fresh-arrival favorite scan completed in275.883s with exactly
two archival tiles. Both side borders and padded source coverage verified. The
fresh favorite-arrival registration was strong enough to reuse the review
preview's tone, and the archival recipe contains that exact table, with the
original preview ID as its generator. No archival-tone regeneration was needed.

All20 recorded acquisition/master/source hashes were checked again after the job,
and all matched. All97 copied buffers from the successful vendor image-only
observations also matched their recorded hashes. The copied vendor TIFF still
matches its recorded SHA-256, and CyberView's original INI was restored byte-for-byte
(`5c9c9753daad0583cb3fb4d876d549843039a5917e8436e2ea38a3df700ca942`).

The accepted FRAME preview ID is `0b689083372745609e94a7b6e11dc42d`; the archival
capture ID is `d93f76c94cc14a8c9d545cbb19c2b724`. Their tone-table SHA-256 is
`bac95e908cff3a33a1d5f7c6529314e59fb45af292948fe3629793f806c951b4`.
`physical-frame-before-after.jpg` compares this same new original with tone off
versus its reused preview tone. `final-evidence-audit.json` cross-checks the
vendor replay, source preservation, settings restoration and transport state.

Final film state is relative frame1, fine offset0, position known and no pending
move. The physical job selected hold-at-end and requested no whole-frame advance
or eject. The native driver closed normally. Full vertical containment remains
unknown. Workspace changes remain uncommitted; no runtime library, vendor table,
image or machine state was committed.

## Final latest-code verification

- `python -m pytest -q`: **475 passed,2 xfailed in450.44s** on the final Python
  implementation, including default-tone fallback, per-frame reuse, favorites,
  user-disable preservation, worker arithmetic and acquired-statistics tests.
- `npm run build`: passed on the final client, including tone-table preview stamps.
- `npm run test:native-ui`: final rerun passed with no JavaScript exceptions and
  no pipe-close exception in its saved final log. This uses a synthetic helper,
  not physical scanner evidence.
- `npm run test:e2e`: passed the simulated36-frame workflow, phone emulation,
  authenticated reconnect and TIFF/archive checks.
- Scoped `git diff --check`: no whitespace errors; CRLF/LF notices only.
- Physical vendor and FRAME results and all final preservation checks above passed.

The lower band was investigated and shown to exist in the vendor path before
film/tone processing. Its underlying mechanism remains unresolved; no corrective
hardware claim is made. Exact image-stage replay is narrower than complete
CyberView acquisition/color-management parity. No independently measured vertical
containment, calibrated sensor precision or additional-mode acceptance was added.
