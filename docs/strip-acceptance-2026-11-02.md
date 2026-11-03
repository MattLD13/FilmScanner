# Loaded six-frame strip acceptance test

Status: **the fourth physical run passed the loaded six-frame strip workflow and supplementary favorites/repeat checks. All six masters reproduced exactly, 89 recorded file hashes matched, and fresh images verified return to frame 1 twice. Driver closed; strip left loaded at relative frame 1. Changes remain uncommitted.**

The latest result is described under **Fourth-run final measurements** below.
Earlier attempts and their failures remain historical evidence. Acceptance is
bounded to this six-frame strip and does not establish uncut-roll handling,
vertical containment, calibrated sensor precision, or exact CyberView processing parity.

The user authorized the actual loaded strip test and independently reported six
exposed frames. The run uses FRAME's ordinary authenticated API and production
hardware gates, not a simulated bridge or shortened frame limit. It scans to the
detected end rather than stopping at the reported count. Scope is a six-frame
strip, not a full uncut roll, mounted-slide handling, or calibrated sensor ENOB.

## Configuration and evidence

- Full-window 300 DPI RGB8 border/rebate planning; 1800 DPI RGB16 archival tiles.
- One acquisition per tile, optional cleanup filters off for the main pass.
- Measured film-base exposure, fixed across a wide frame's tiles, vendor flag0.
- Selected batch end action: return to relative frame 1.
- Autofocus followed by a saved starting fingerprint before the main job.
- All originals, source hashes, code fingerprints, session events, acquisition
  requests, transport commands, and timing retained in an isolated test library.
- No firmware command, hardware evidence gate, or production scan limit changed.
- Existing workspace changes remain uncommitted.

Initial main-run evidence directory:
`.local/strip-acceptance/20261102T050125Z/` (UTC timestamp).
Initial root batch session: `2e98c1753b504b118743263d7973fbbd`.
Corrected rerun: `.local/strip-acceptance/20261102T054205Z/`, root batch
`8fa5774bcbfb49078d01987bd992a09b`. The driver confirmed forward eject between
runs, and the user reported reloading the strip at frame 1 before the new run.
That rerun stopped before frame-4 archival capture because of the footprint
rounding issue described below. The third run was
`.local/strip-acceptance/20261102T060229Z/`, root batch
`c2b8760b0b084526afecaccdb5beff1a`, after another confirmed forward eject and
user-reported reload at frame 1. Each attempt retains its original result/log.

The directory contains `session.jsonl`, `manifest.json`, the acquisition library,
interim `content-audit.json`, and `contact-sheet.jpg`. Final session snapshots,
hash results, and return-registration records are written as stages finish.
These files remain ignored local evidence and are not committed.

## Acceptance criteria

| Check | Required evidence | Current result |
| --- | --- | --- |
| Frame count and order | Six distinct exposed images, contiguous indices, forward transport trace | Passed: six photographs, matching independent user count and visual review |
| Borders and coverage | Both side borders plus rebate witness for every frame; acquired coverage retained | Passed horizontally on all six; vertical containment remains independently unverified |
| Tile planning | One/two local optical positions, no high-resolution border-search loop | Passed: two planned archival tiles per frame; additional search stayed at 300 DPI |
| Exposure locking | Same fixed requested channel settings across wide-frame tiles | Passed on all six frames and supplementary repeat scan |
| Fine movement accounting | Recorded pending/confirmed nudges and zero completed fine offset before next frame | Passed; final fine offset zero |
| Strip end | Failed further advance, preserved last frame, optical boundary verification | Passed: fresh witness matches after refused advance, vendor counter remains 6; physical film-tail sensor proof is not claimed |
| Return | Relative transport plus fresh starting-photo registration | Passed twice by new images matching the starting photograph |
| Image integrity | Exact reconstruction from originals and recorded optical plan; SHA-256 checks | Six masters reproduced exactly; all 89 recorded hashes match |
| Exports and edits | Real-image copy, 16-bit TIFF/ICC, JPEG, metadata, crop/rotate/mirror, source previews | Passed on disposable copy |
| Archive deletion | Delete only disposable copied roll; acceptance originals unchanged | Passed |
| Favorites/repeats | Valid fresh preview, original retention, derived repeat processing, final return check | Passed: stale location rejected, fresh favorite scanned, two samples per tile retained and normalized, final optical return verified |

Vertical containment remains independently labeled unknown when neither top nor
bottom film border is visible. A horizontal-coverage pass does not promote it.
Frame identity/ordering requires image review in addition to counters and hashes;
sensor noise makes different hashes insufficient evidence of different frames.

## Earlier software and copied-image checkpoint

- `python -m pytest -q`: **458 passed, 2 expected failures in 380.79 seconds**.
- `npm run build`: passed.
- `npm run test:native-ui`: passed, synthetic helper, no JavaScript exceptions.
- On a disposable copy of an actual captured image: crop/rotation/mirror and
  16-bit ICC TIFF export; filters; favorite/metadata persistence; original hashes;
  source previews; exact isolated vendor-tone worker; and roll deletion all passed.
  The copy's library was deleted through the API while the acceptance acquisition
  remained hash-identical. This was image/API testing, not another hardware scan.

Software tests and UI emulation do not substitute for the pending physical end and
return checks. Concurrent software verification also means these run timings are
acceptance observations, not an isolated throughput benchmark.

## First-attempt harness issue

The first attempt, `.local/strip-acceptance/20261102T045853Z/`, completed one
initialization preview but its observation wrapper incorrectly awaited a
synchronous API callback during autofocus. Shutdown then timed out just before
the native operation returned, masking that original harness error. The first
image and trace were preserved. The driver subsequently closed, with no forced
termination issued by this harness. The observer was corrected to support both
synchronous and asynchronous callbacks, and the test restarted in a new evidence
directory. That attempt is not called a successful acceptance run or an established
production scan failure.

## Actual failure found on the sixth frame

The first main strip job completed frames 1–5, acquired the two planned sixth-frame
tiles, then stopped on `UNVERIFIED_FRAME_COVERAGE`. It did not start more archival
search passes or attempt automatic return. Five completed images, the sixth
coverage attempt, all original previews/tiles, and transport offset +60 steps
were preserved. The end-of-strip and return stages were therefore not exercised.
The job elapsed 1450.142 seconds before failure. This is an observed failure,
not a six-frame acceptance pass.

The sixth composite contained both exposure boundaries, but its right rebate was
fragmented by measured vertical pixel spread fluctuating around the strict .1
uniformity threshold. Individual fragments were shorter than the .25 mm minimum.
A conservative hysteresis rule now permits a connected **bright** region with
spread below .12 only when at least half its pixels (minimum two) satisfy the
original strict .1 test. It does not bridge dark picture pixels or accept weak-only
regions. Synthetic supported/unsupported cases test that distinction.

Re-evaluating retained images without modifying them finds side borders on all
six acquisitions. Sixth-frame edges are x=66 and x=2705, with about0.9313/0.7056 mm
outer margins. The other five remain verified. Existing historical records retain
the initial failed decision; the offline re-evaluation is separate evidence in
`revised-detector-offline.json`.

## Auto-film detection failure found on balanced scans

An explicit saved-data check also reproduced a wrong Slide guess on the known
color-negative strip: requested channel exposures `[132,172,277]` made its observed
rebate nearly neutral `[0.8549,0.8627,0.8667]`. Looking only for orange in those
balanced sensor samples incorrectly returned Positive at .82.

The detector now receives recorded requested channel exposures and undoes their
relative balance for **classification only**, using scale `min(exposure)/exposure`.
It finds the orange base after that normalization and returns Color negative at
the existing .96 heuristic score. The acquired image is not edited, and that score
is not a calibrated accuracy probability. This relies on the previously observed
relative exposure response, not an absolute lamp calibration or unknown vendor
internal auto-exposure values. The new evidence records observed base, normalized
base, seed values, and correction method. The main acceptance job was explicitly
set to Color negative, so the wrong suggestion did not change its acquisition.

Focused revised-detector tests: **18 passed in 7.83 s**. Earlier border/film API
regression subset: **54 passed in 151.31 s**. A full-suite rerun on the revised
code is in progress. The corrected physical run is still required; offline success
alone does not promote the main strip workflow to accepted.

## Second physical failure: rounded mosaic versus real source footprint

The second main run completed three frames and stopped **before** taking frame-4
archival images. Its rounded preview canvas was482 pixels wide with borders
x=38 and x=477. A padded witness based on the canvas saw5 pixels outside the right
border, exceeding the4.76585-pixel requirement. The measured source windows actually
ended at481.68, however, giving only4.68 pixels. The planner correctly rejected
that shortfall; the low-resolution search had incorrectly considered its job done.

The search now requires **both** its rebate witness and a feasible actual-window
tile plan before stopping. It uses measured source footprints rather than the
ceil-rounded mosaic width. An infeasible plan sends the existing bounded300DPI
search toward the short side; the safety margin is not weakened and no extra
archival search is introduced. The exact saved geometry remains rejected until
an additional measured window is supplied in the regression fixture. Another API
regression forces that condition and verifies the extra acquisition stays300DPI.

Both physical failures exercised intended safe stops: originals retained, no
unverified archival frame promoted to complete, and no automatic return after
uncertain/incomplete job state. They also show that the previous software suite
was not sufficient to establish strip-level acceptance.

After the planner fix, focused detector/planner/API tests: **31 passed in9.78s**.
The latest full `python -m pytest -q` completed with **463 passed,2 expected failures
in380.39s**. Build and native UI workflow passed. This is software evidence;
the third physical run and its end/return checks remain in progress.

## Final third-run result and wrap-up

The third run, `.local/strip-acceptance/20261102T060229Z/`, completed **all six
archival frames**, matching the user's independent count. All six had verified
side borders, two planned fixed-exposure archival tiles each, and exact master
reconstruction from the recorded sources/plan in the offline audit. All **61
recorded original/master/source hashes** matched, with zero mismatches. The saved
contact sheet shows six distinct photographs: garden, portrait flowers, firepit,
landscape pool, portrait pool, and sky/roof. No top/bottom-containment or calibrated
color/precision claim is added by this result.

The attempted advance beyond frame 6 was refused. The end-check image strongly
registered to frame 6 at approximately dx=6.0713, dy=−0.2768 preview pixels, peak
0.2283, peak ratio12.872; its vendor counter remained6. The old guard nevertheless
required displacement≤3px against the **earlier border-search centre**, taken
before intervening search/capture/reconciliation movement. It stopped safely
instead of claiming exact stationary return. Main-job time was1406.459s.

The boundary logic is now corrected to capture a fresh300DPI witness immediately
before any next-frame attempt. On a failed move it requires an unambiguous bounded
same-frame image registration **and** an unchanged non-null vendor counter after
the verification capture. Pixel stationarity within3px is retained as diagnostic
information rather than conflated with same-frame identity. Changed/unknown
counters or ambiguous optical matching still leave position uncertain and block
return/eject. Four targeted boundary cases plus the planned API suite passed:
**15 passed in85.20s**. This last correction has **not** been physically retested.

The last full software suite before that boundary correction passed **463 tests,
with2 expected failures in380.39s**. Build and native UI workflow passed. Scoped
`git diff --check` found no whitespace errors, only line-ending notices. The final
API boundary change has the targeted15-test evidence above; a new full-suite or
physical pass is not implied.

Crop/rotation/mirroring,16-bit ICC TIFF export, filters/favorites/metadata, source
previews, optional CPU vendor tone, and deletion passed again on a disposable
copy of an actual third-run capture. Acceptance originals remained unchanged.
Actual supplemental favorite/repeat jobs and photographic return verification
were **not reached**, because the main job stopped at the end guard.

At the user's request to finish, no additional strip run or eject was started.
The native helper is closed. Film was **not automatically returned to frame1 or
ejected**; its last observed image/counter was the sixth frame. The failed move
means exact final positioning must not be assumed. Changes remain uncommitted.

Artifacts in the third-run directory:

- `contact-sheet.jpg`: six saved actual images;
- `manifest.json`: final stopped-job result, tests, code fingerprints,61 matching hashes;
- `session.jsonl`: timestamped acquisition, transport, status, and API trace;
- `whole-strip-session.json`, `captures.json`, `sessions.json`, `hash-checks.json`;
- `content-audit.json`, `end-boundary-reference-audit.json` and disposable-copy processing report.

These artifacts remain local/ignored. Full strip acceptance requires one final
physical check of the corrected end-and-return logic; it is not marked complete.

## Fourth physical run after user requested continuation

The driver confirmed forward eject on November 2 at 20:14:49 UTC. The user then
confirmed reloading the six-frame strip at frame 1. The new evidence directory is
`.local/strip-acceptance/20261102T201552Z/`; root batch
`0c8007da06ca4b7d8d524fdcd97977fe`. This run includes the fresh pre-advance witness
fix and retains the ordinary production acquisition gates and actual-end search.
Its final physical result passed, as detailed below.

Software checks on the current boundary-fix code completed during this run:

- `python -m pytest -q`: **467 passed, 2 xfailed in 459.42 seconds**.
- `npm run build`: passed.
- `npm run test:native-ui`: passed, synthetic helper, no device access or browser errors.
- `npm run test:e2e`: passed, simulated 36-frame workflow and phone emulation,
  TIFF export, authenticated reconnect and archive checks, no browser errors.

These software results do not establish physical end-of-strip or return success.

## Fourth-run final measurements

The actual main batch completed in **1542.474 seconds (25.71 minutes)**, including
border searches, two 1800 DPI RGB16 tiles per frame, pre-advance witnesses,
refused-advance verification and five confirmed backward moves. The six saved
masters measure2832×1709,2899×1709,2871×1708,2905×1710,2893×1709 and2749×1710.
Visual review shows the expected garden, portrait flowers, firepit, landscape pool,
portrait pool, and sky/roof images in order. All six reproduce pixel-for-pixel from
the retained source tiles and recorded plans, including derived overlap matching.
Fixed requested exposure prevents independent vendor auto-exposure scaling; it
does not eliminate per-pass calibration, lamp variation or software overlap gains.

The fresh sixth-frame witness matched the image after the refused advance at
dx=−0.00523,dy=+0.07214 preview pixels, peak0.3632 and peak ratio21.274.
Vendor counters before and after were both6. This establishes a bounded same-frame
result after an unconfirmed move, supported by the independent six-frame count;
it is not a separate hardware measurement of the physical strip tail.

The first new capture after automatic return matched the saved starting photograph
at dx=−2.1391,dy=−0.0509 preview pixels, peak0.6197 and peak ratio47.907.
The final verification after supplementary scanning matched at dx=−2.8013,
dy=−0.1343, peak0.5098 and peak ratio32.470. Return means the correct first
photograph was reached, not identical mechanical or sub-pixel placement.

Supplementary results:

- Quick preview of the current frame with border finding:52.526s, passed.
- Stale favorite location:409 rejection as intended after intervening scan.
- Fresh favorite high-resolution rescan, two samples per tile:362.857s, passed.
  Both tiles retain both original TIFFs, use identical manual settings across
  all four original captures, pass optical repeat alignment, and record common-mask
  offset normalization and final clipping counts. Both derived means' hashes match.
- Original/TIFF/JPEG/metadata exports passed on frames1 and6 and the filtered
  repeated master; originals remained unchanged and TIFF output was16-bit.
- Disposable-copy crop/rotation/mirror, ICC export, filters, favorites, source
  previews, optional CPU vendor tone and roll deletion passed without modifying
  the acceptance originals.
- **89 recorded original/source/master hashes match, zero mismatches.** All
  acquisition code/helper fingerprints match their values at run start.

| Earlier observed behavior | Corrected physical result | Why the change helps |
| --- | --- | --- |
| Frame6 rebate fragmented into rejected short runs | Six-frame run verifies both side borders on frame6 | Supported hysteresis tolerates small spread fluctuations while retaining strict bright seed support |
| Rounded mosaic appeared wide enough but true source footprint was short | Frame4 search obtains a feasible padded tile plan before archival capture | Uses real acquired geometry and continues cheap search instead of weakening margins |
| Stale pre-search image made end verification fail at6.07px offset | Fresh witness matches at about0.005/0.072px; counter6 unchanged; return completes | Compares the film immediately before and after the attempted advance |
| Previous batch ended with film at6 and uncertain position | Two fresh images verify the correct first photograph after return | Adds end-to-end photographic evidence to acknowledged transport commands |

Final film state: relative frame1, position known, fine offset0, no pending move;
driver closed normally. No eject was issued after the successful run. No changes
were committed. Runtime evidence remains ignored/local in
`.local/strip-acceptance/20261102T201552Z/`, including `acceptance-result.json`,
`manifest.json`, `session.jsonl`, `content-audit.json`, `contact-sheet.jpg`,
`hash-checks.json`, two return-registration records, saved sessions and exports.
The earlier failed runs remain separate and are not relabeled as passing.
