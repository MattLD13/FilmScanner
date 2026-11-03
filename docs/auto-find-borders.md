# Auto find borders

Use **Auto find borders** beside **Scan frame**. FRAME captures a full-window
300 DPI image, then performs a bounded optical search for both side borders and
padded rebates. It can inspect up to five additional positions after its initial
windows. It measures actual image displacement; motor steps identify repeatable
commands, not a trusted millimeter-per-step conversion. Search originals remain
preserved even when coverage or registration cannot be verified.

The acquisition planner requires 0.15 mm of horizontal rebate plus a provisional
18-high-resolution-pixel uncertainty allowance. It selects one or two measured
windows with adequate overlap. A 36 mm exposure often requires two tiles under
these margins because the full aperture is only about 36.5 mm wide. Before each
archival acquisition, a fresh 300 DPI arrival check verifies the position and can
make bounded optical feedback corrections. It then acquires at most two 1800 DPI
RGB16 tiles. There is no native high-resolution exploratory recovery loop.
With optional repeated sampling, those one/two planned positions each receive
the explicitly selected 2 or 4 acquisitions before averaging; that additional
acquisition time is intentional, not a border-search fallback.

Stitch registration is constrained by optical preview offsets and checks texture,
competing peaks, minimum overlap, and displacement consistency. Failure preserves
the unstitched source TIFFs and reports unverified alignment/coverage. Top and bottom
containment are independent: when not verified, FRAME retains the full acquired
height and reports that limitation rather than applying a nominal vertical trim.

In **Roll options**, choose **Current frame** or **Entire roll**, then **Quick ·
300 dpi** or **Detailed · 600 dpi**. Both use full-window 300 DPI border finding;
the validated 600 DPI detail configuration still has the narrower acquisition
area. Previews are archived with their resolution in the label. Favorite previews
can be scanned at archival quality. Each favorite gets a fresh local optical
arrival check and border/rebate search after seeking; old coordinates are not
reused as if transport were exact.

**Scan all frames** now works in place: search, plan, acquire, reconcile fine
steps, then advance. **After scanning** selects return to frame 1 (default), hold,
or forward eject. Only the selected end action adds its transport gate. Return is
based on acknowledged relative frame movement, not an absolute encoder. If a next
move fails at the probable roll end, the software optically checks that the last
frame remained in place before attempting the selected end action. Uncertain
motion stops further automatic movement.

See [the November 1 validation report](planned-scanning-validation-2026-11-01.md)
for current software tests, bounded physical runs, timings, comparison images,
and limitations. The historical checkpoints below describe the earlier design.

## Why this replaces the main stitched-scan control

Border finding is an image-location task, not a request for three archival scans.
Quick previews make it possible to inspect borders first and use expensive
additional captures only when the final frame needs more coverage. An image cannot
supply pixels that were outside every source window; resizing it is not recovery.
The current implementation uses translation and overlap blending, with no geometric
stretching, and preserves every original source separately.

The earlier detector used a hard 0.9 mm tolerance around a nominal 36 mm width.
The loaded-film experiment on October 31, 2026 measured 438 preview pixels between
clear borders: approximately 37.1 mm at the scanner's declared 300 dpi. One window
was only 430 pixels wide. The old rule discarded this otherwise clear pair.
Spacing is now a 10% plausibility prior; crop coordinates follow measured borders
rather than forcing nominal dimensions. This observation does not independently
calibrate the scanner's optical DPI or prove a physical 37.1 mm exposure width.

## Historical evidence and limits

- The supervised exploratory session completed four 430 × 284, 300 dpi, 8-bit
  RGB previews and the already verified 20-step nudge commands. The clear left
  and right borders were measured from those acquisitions. Originals/logs remain
  under ignored `.local/border-finder/20261031-212332/`.
- The new authenticated API action then completed on the loaded film in **63.654
  seconds**, preserving three 300 dpi 8-bit sources and finding both horizontal
  borders with full coverage of the proposed crop. The border preview is kept
  uncropped for inspection; it is not counted as an archival frame.
- Final recovery at the existing 1800 dpi/16-bit settings completed in **198.456 s**.
  Both side borders were measured and the applied crop was **2630 × 1701 pixels**.
  Vertical size remains nominal. The metadata reports 270 filled corner pixels
  (0.0060%); these are not acquired source pixels. All six source checksums and
  both derived image checksums were verified, and the exported JPEG was inspected.
- Full-window preview bounds were validated at 300 dpi, and later the full-window
  1800 dpi configuration was added after a successful scan. Raw USB commands,
  new motor modes and extended continuous two-frame capture were not enabled.
- A later supervised zero-nudge sequence completed 300 dpi full-window preview,
  1800 dpi full-window acquisition, and another 300 dpi preview: 430 × 284,
  2585 × 1708, and 430 × 284 pixels. The two previews registered within 0.48 px.
  No borders were visible in that subject, so it does not validate single-pass
  eligibility or rebate coverage. The full-window 1800 dpi settings are now
  recorded as observed. This was one stationary sequence, not a repeatability bound.
- A supervised directed-movement sequence then captured a preview, nudged forward
  20 verified steps, captured another preview, scanned at 1800 dpi without another
  move, and captured a third preview. The same right rebate edge was at preview
  pixel 416 before and after the high-resolution pass; its 1800 dpi position at
  pixel 2504 maps to within about half a 300 dpi pixel. The frame showed only one
  edge, so the capture does not establish full-frame single-pass coverage. This is
  one measurement, not a bound on mechanical repeatability. At that checkpoint the film remained at
  the tested +20-step position; later runs moved it again. The jog shifted image content 21.99 px (about
  1.86 mm), while an earlier 20-step backward jog measured 1.20 mm; direction and
  drivetrain load can affect travel, so use the image to verify movement.
- Roll preview and favorite acquisition are covered by synthetic API cases for
  300/600 dpi contact previews, selected-frame positioning, verified 1800 dpi capture
  and automatic stitched recovery for a preview known to be too wide. The 600 dpi
  detail mode is within a previously recorded acquisition configuration; full-roll
  preview timing and physical favorite selection have not been hardware-tested.
- Motion/cancellation reuse the existing persistent operation state. A failed or
  uncertain move does not trigger an automatic return. Balanced completed motor
  steps are not an image-verified final return position.
- Uniform bright subjects can resemble bare film; nonstandard frame formats,
  dust, skew, poorly exposed gaps and other stocks still need broader testing.
  Numeric manual cropping remains available. Automatic deskew is not implemented.

Shared overlay contracts are in `packages/contracts/schema.ts`; acquisition and
capability gates are in `services/api/cyberview_routes.py` and
`services/scanner_host/workspace.py`; border detection is in
`services/imaging/frame_align.py`.
