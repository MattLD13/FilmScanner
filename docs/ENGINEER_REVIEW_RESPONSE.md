# Engineering review follow-up

November3 commit-review continuation: [commit plan and bounded review](COMMIT_REVIEW_PLAN.md)
found an older `position_sensor` path that still killed the native helper. It now
quarantines an active call and preserves uncertainty without forced termination;
terminal-ready handling is tested separately. This closes a software reservation
exception, not a new physical recovery qualification. The5% width check is
per-side, with a160-column cutoff at1800 DPI;320 would be a combined-side rule.

This responds to the supplied bottom-band/containment/transport review. Current
appearance preference is unchanged: extra preview tone is **off by default**.
Original acquisitions and historical test results are not rewritten.

## Qualifications on the diagnosis

- The light lower band is present in CyberView's copied **pre-film/auto-tone**
  buffer and its saved TIFF, as well as FRAME's path. That rules out a unique
  FRAME display or TIFF-writing cause in those examples. CyberView's copied
  buffer already has the model negative LUT applied, and FRAME originals still
  contain vendor calibration. Neither is untouched sensor data before all host
  processing.
- Low/zero vendor output codes establish an output-floor phenomenon. Without a
  characterized linear response/dark reference, they do not alone prove zero
  photons or physical obstruction rather than calibration/processing clipping.
- Continuation into a genuinely unexposed film-base gap would argue against an
  ordinary camera-exposure boundary alone. The image supports this interpretation
  but does not independently characterize the gate, guide, film or calibration.
- The proposed two-image nudge test is useful but not uniquely causal. A fixed
  carrier shadow and fixed shading error can both stay fixed in delivered image
  coordinates; film walk can also change a scanner-fixed obstruction's apparent
  effect. Compare against measured optical displacement, not a step-to-pixel guess.
  The25-step request was not substituted for the verified20-step motor chunks.
-1708 rows is the reviewed **vendor-interface** limit. Declared-DPI height and
  nominal camera dimensions are not an independent measurement of the physical
  aperture or proof that a lower-level acquisition path could expose no more.

## Implemented changes

| Area | Current behavior |
| --- | --- |
| Statistics edge guard | At1800 DPI, exclude bottom40 rows and8 outer columns per side from automatic statistics; scale upward by ceiling at other DPI (7 bottom rows/2 columns at300). This is a conservative policy, not a proved universal artifact extent or an image crop. Each side margin and the bottom margin must individually occupy at most5% of the respective dimension. The1800-DPI cutoffs are therefore800 rows and160 columns; a320-column cutoff would implement5% for both side margins combined. Small images failing the current rule are explicitly marked unguarded. |
| DMin/base and optional tone | Acquisition base suggestions, negative balance, automatic colour and automatic-level percentiles use guarded acquired picture statistics. Optional vendor tone uses the guarded rectangle before the vendor histogram resize. Metadata records the guard and actual statistics region. Originals, displayed height, master pixels and manual crops are not trimmed by this policy. |
| Uncertain transport | Native controls latch uncertainty before dispatch and clear only after an acknowledged, noncancelled completion. The same applies to internal batch advances. The API persists the latch so a new job, driver release or API restart cannot silently bypass it. |
| Recovery | With uncertain position, reject archival capture and relative seeks. A current-frame300-DPI prescan remains allowed; it does not clear uncertainty automatically. The user can inspect it and explicitly relabel the checked current position, invalidating old preview positioning. Eject remains a separate verified recovery control. |
| Refused advance | Fresh image/counter verification establishes the current frame, not the physical strip end. Without a matching user-supplied expected count, completed images remain saved, the session reports a refused-advance warning, and return/eject is withheld. |
| User choice at a stop | UI/API provide Retry advance, Confirm end and finish, and Keep film and stop. Retry continues the same recorded job with unique acquisition paths; confirm applies the batch's selected end action. Before either moving action, a new300-DPI image must match the saved stopped frame and its vendor counter. A changed/reseated strip fails the request, latches uncertainty and dispatches no further movement. Keeping film/stopping does not move it. |
| Expected count | Optional1–40 frame count is accepted for all-frame preview/scanning. An early refusal gets `WARNING_EARLY_ADVANCE_REFUSED`. A refusal at the expected count permits the selected completion action, with that basis recorded; this is not independent tail-sensor proof. |
| Return verification | After acknowledged relative moves back, acquire a fresh300-DPI image and register it against the saved first-frame optical reference. Record dx/dy and sources. Failed/ambiguous acquisition or matching gets `RETURN_COUNTER_ACK_OPTICAL_UNVERIFIED`; counter acknowledgment is retained, return confirmation is false, and position uncertainty is latched. |
| Separate containment contract | `x_containment_verified` is distinct from `y_containment_verified`. When all validated full-height source windows are retained but vertical borders are unverified, record `y_containment: vendor_window_limited` and `full_acquired_height_retained`. The existing detailed vertical status/reason remains available. It is not renamed to verified physical containment. |
| Post-capture coverage | The actual archival witness remains independent of the provisional18-pixel planning allowance. A simulated22-pixel cross-resolution displacement cannot promote an incomplete single-tile frame; its original source is retained as a coverage attempt. No unbounded high-resolution recovery loop was introduced. |

## Regression evidence

New/updated tests cover:

- Base estimation and optional tone statistics with and without an edge wedge;
  the selected input pixels, DMin result and actual vendor CPU tables match under
  the guard. The original image arrays remain unchanged.
- Unacknowledged nudge timeout and cancellation, rejection of later archival
  capture/relative work, persistence across app restart, and explicit recovery
  through prescan plus user reindex.
- Early refused advance with a larger expected count, preserved completed
  original, no automatic return/eject, and confirm/retry/stop resolution.
- A changed counter or ambiguous/reseated image during the fresh stopped-frame
  recheck: request rejected before further movement, sources retained, and
  archival work blocked until recovery.
- Acknowledged return with failed optical matching: distinct counter and optical
  results, no false return confirmation, and subsequent archival work blocked.
- A22-pixel archival shift beyond a minimally padded single-window plan: no
  complete-frame promotion, one retained original tile and a failed actual witness.
- Existing planned scan/favorite tests now supply an independent expected count
  when they intend automatic completion. A missing count is tested as a stopped
  state rather than silently interpreted as true end-of-strip.
- UI request intent includes the optional expected count, and a synthetic stopped
  state exposes reachable confirm/retry actions with the correct session ID.

The first focused combined run passed56 tests in182.55s. Initial fixture/import
and older end-behavior expectations failed and were corrected; no production
claim is based on those failed invocations. Full-suite and final UI results are
recorded at the end of this report when available. Software tests use synthetic
scanner output; CPU worker oracle execution has no scanner I/O.

The first full run found six failing expectations: five reflected the new
refused-advance completion contract, and one exposed an overly aggressive guard
on a100×100 custom image. The guard was tightened to avoid excluding a large
fraction of small windows and gained a dedicated regression. The related58-test
API/imaging rerun passed in160.37s. The initial native UI request-intent assertion
also needed its new optional expected-count field; its corrected rerun passed.

## Retained nudge-pair analysis, not a new motor experiment

Two retained first-frame1800-DPI originals have matching requested settings,
recorded fine positions−40 and0 completed steps, and optically measured placement
dx=247.0477,dy=.7955 pixels. Their hashes were checked before analysis. The
existing protocol used bounded20-step commands; this is not a new0/+25-step test.

A candidate profile counts bottom-connected low-code rows after a9-column median,
limited to60 rows. At threshold.01, the median absolute profile difference was
1.0px in delivered coordinates and.7955px after applying scene placement; at.003,
the differences were2.0px and1.7479px. The profiles reproduce the sloping low-code
region but do not uniquely select physical strip occlusion versus calibration or
other vendor-line behavior. A nearly linear slope and near-floor quantization
make a small score preference insufficient causal evidence.

Local outputs:
`.local/engineering-review/retained-nudge-profiles.png` and
`retained-nudge-profile-results.json`. These are read-only historical-data
measurements, not new physical acceptance.

## Deliberately not claimed

No empty-gate scan, unverified25-step move, low-level CCD/ADC command or firmware
change was issued. No new physical cancellation, low-texture strip run, different
stock or mounted-slide test was performed in this follow-up. Additional strips
and a calibrated target are not available from the current conversation.

The bottom-band mechanism, calibrated precision and full vertical containment
remain unverified. An optional derived display crop was not introduced to hide
the artifact. Automatic second-tile promotion after a failed actual witness is
not claimed here: the safe failure retains sources; bounded recovery planning
needs its own implementation/acceptance criteria.

The uncertainty latch is persisted with the current library's preferences.
Cross-library/multi-host transfer of physical device state is not qualified here.
A timed-out vendor call is not assumed to have stopped: its session remains
reserved until it returns, and a power cycle can still be necessary. Synthetic
timeout/cancel tests do not establish clean hardware cancellation or firmware
recovery behavior.

## Validation checkpoints

- Corrected full suite: `python -m pytest -q` -> **486 passed,2 xfailed in547.98s**.
  This run collected before the additional fresh stopped-frame recheck was added.
- Latest stopped-position/transport/coverage subset:
  `python -m pytest -q tests/api/test_engineering_guards.py` -> **9 passed in85.93s**,
  including the new stale-counter/image recheck and pending-state invalidation.
  These are overlapping regression checks, not nine additional unique tests
  beyond the full-suite count.
- `npm run build`: passed. Native UI workflow passed with no JavaScript exceptions,
  including the expected-count input and stopped-state controls. Simulated36-frame
  workflow, phone emulation, authenticated reconnect and export/archive checks passed.
- Scoped `git diff --check`: no whitespace errors, CRLF/LF notices only.
- No new real scanner command was issued in this follow-up. New guard behavior is
  software-tested; prior hardware captures remain historical evidence.

Latest local logs are `review-full-suite-final.log`, `review-last-safety-tests.log`,
`review-native-ui-latest.log` and `review-workflow-latest.log` under `.local/`.
The simulated stopped-state screenshot is `.local/frame-ui-current/refused-advance.png`.
The source changes were uncommitted at this checkpoint. The subsequent November 3
user-authorized commit sequence and validation are recorded in
[the commit record](COMMIT_REVIEW_PLAN.md); library data and machine state remain
excluded.
