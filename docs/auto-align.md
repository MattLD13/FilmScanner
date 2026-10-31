# 35 mm auto-align

CyberScan X finds the frame in a scan and crops it to exactly 36 × 24 mm (plus or
minus a bleed of up to 2 mm). The crop is part of the edit recipe; originals are
never changed. Code: `services/imaging/frame_align.py`.

## Why scans need to be longer

The AFL module clamps one scan to 2586 × 1708 px at 1800 dpi, which is 36.5 × 24.1 mm
(`0x100110af`, [scan08-feature-catalog.md](scan08-feature-catalog.md)). CyberView's
default crop is narrower still: every existing scan in the library is
34.98 × 24.03 mm, so none of them can take an exact 36 mm crop.

## How it works

1. **Stitched scan** (native capture): scan the frame, nudge the film back a little
   (selector 10), scan, nudge forward past the start, scan, and return the film.
   The first nudge is a small probe; its real distance is measured from the two
   images and calibrates the step size (steps per mm is then remembered).
2. **Registration**: each scan's true position is measured from its content by
   phase correlation, coarse then full resolution, with a sub-pixel peak. The
   motor's nominal movement only seeds the search.
3. **Exposure match**: per-channel gain from the overlap (median ratio), because
   auto exposure differs between scans. Blending is feathered so seams fade.
4. **Gap detection**: the gap between frames is bare film base, uniform down the
   frame (no picture texture). It is bright in a transmission scan and dark in a
   CyberView positive. The frame is the picture around the middle: it starts
   where the nearest gap on its left ends and ends where the nearest gap on its
   right begins. A sliver of the neighbouring frame beyond a gap is ignored.
5. **Exact crop**: 36 × 24 mm (+2 × bleed) centred on the two edges, or anchored
   to one edge, or centred on the scan if none is visible (and labelled so). Skew is
   measured from the edge positions down the frame and reported.

## In the app

- **Crop image → Auto align 35 mm** on any scan, with a bleed setting.
- **Align new scans automatically** applies it as each scan is saved.
- **Stitched scan** appears beside the scan button once film nudging has been
  tested on the scanner (native capture). It saves the three source scans as the
  originals and a stitched 16-bit image with its coverage mask as a derived capture.

## Evidence

- Synthetic strips (`tests/imaging/test_frame_align.py`): both edges found within
  2 px, exact crop sizes, recovered motor offsets within 1 px when the motor moved
  7–8 % off the requested distance, exposure mismatch undone, the previous-frame
  sliver case, and the no-edge fallback.
- The stitched scan end to end through the API with a fake scanner whose nudges
  really move a synthetic strip (`tests/api/test_frame_align_api.py`): steps per mm
  learned within 5 %, both edges found, exact 36 × 24 mm.
- Real library scans (2026-10-30): the gap was found on 3 of 8 CyberView scans at
  1.2–1.45 mm wide. Before the gap-based method, 2 of those 3 locked onto the
  previous frame's sliver; that is now a regression test. No real scan was wide
  enough for an exact crop.

## Two ways to move the film a little

Both end in SCAN08 selector 10 (`{direction, steps}`, 1 = back, 2 = forward):

- **CyberView path (default).** CyberView's menu has Forward One Step (32863) and
  Backward One Step (32862). Their handlers call the AFL class's vtable `0xd0`/`0xcc`,
  which send selector 10 with one step. The bridge command `film step forward|back N`
  (N 1-300) sends the menu command N times; `CyberViewBridge.control('nudge', 'back 20')`
  uses it. Enabled when `step_forward` and `step_back` are both listed in
  `services/scanner_host/cyberview_validation.json`.
- **Native path.** `aflbridge` calls selector 10 directly (`film nudge`). Enabled when
  `nudge` is in `services/scanner_host/native_validation.json`.

**Not yet tested on the scanner:** either fine move, and a full-window (36.5 mm) scan.
Backward One Frame hung the driver on 2026-10-30, so Backward One Step must be tried
under supervision before it is listed. Stitched scans stay disabled until then.
`tests/api/test_frame_align_api.py` runs the whole stitched scan through both paths
against the fake bridge.
