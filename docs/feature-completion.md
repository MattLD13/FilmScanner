# Feature completion review — October 31, 2026

November 1 continuation: [CyberView feature port](cyberview-feature-port-2026-11-01.md)
records the new gated modes/controls, vendor exposure, CPU-exact optional tone,
generic cleanup filters, repeated-scan averaging, and measured output precision.
The active native border planner uses one or two archival tiles per frame,
with all repeat originals retained; it no longer launches exploratory archival
passes. Full real-roll acceptance, complete automatic CyberView stage parity,
exact ROC/GEM, mounted media, and calibrated sensor ENOB are not marked complete.

FRAME_SPEC.md is authoritative. This checklist compares the current implementation
with that specification; passing synthetic tests does not complete a hardware gate.
Older handoffs and capability tables describe historical checkpoints.

## Working now

- Physical single-frame capture, low-resolution prescan and genuine streamed preview
  have recorded PF1800 AFL evidence through the vendor-assisted direct bridge.
- Scan frame and Scan all frames are separate actions. End-of-film scanning has
  synthetic coverage; a complete physical uncut roll is not yet acceptance-tested.
- Preview roll captures a selectable 300 dpi quick or 600 dpi detailed contact
  sheet. Starred previews can be scanned at full quality; each is coverage-checked
  and wider frames use overlapping recovery. If the initial high-resolution stitch
  misses an edge, preview-guided additional passes extend coverage. Previews remain
  in the archive with a distinct resolution label.
- Native Scan all frames now borders-checks each frame before the full-resolution
  acquisition and requires full-resolution coverage evidence. A complete physical
  uncut roll remains to be supervised and verified.
- Acquisitions are retained separately from edits, with hashes, TIFF/JPEG exports,
  film-base balance, colour profiles, levels, curves, rotation and numeric cropping.
- Stitched scans retain all three sources and a coverage mask. Registration adds
  captured area; it does not increase optical resolution. Individual source views
  now use their own image geometry instead of the mosaic crop/dimensions.
- [Auto find borders](auto-find-borders.md) uses full-window low-resolution
  previews, stops after one when both side borders fit, and marks detected versus
  estimated borders. Scan frame automatically selects wider capture when the
  preview establishes it is needed. This current-frame workflow was exercised on
  loaded film; equivalent automatic recovery over a whole roll remains open.
- Stitched automatic crops require both horizontal borders. One-edge and centred
  suggestions remain uncertain and leave the saved crop unchanged. Existing saved
  edits are not migrated. A wider synthetic strip with a gap at its centre now
  selects a complete frame between adjacent gaps instead of assuming the centre
  of the strip is picture area. Crops use measured border spacing on each axis
  with two detected edges, and label missing-edge dimensions as nominal. Automatic
  deskew, arbitrary formats and nonrectangular boundary correction remain open.
- The separate original workflow supports simulated rolls, editing, integrity
  checks, contact sheets and persisted development rehearsal timers.

## Required for full completion

| Priority | Remaining work | Acceptance evidence needed |
| --- | --- | --- |
| 1 | Reliable frame borders and whole-roll acquisition | A supervised complete real uncut roll: correct order, no omissions/duplicates or transport damage; actual end detection, retries, cancellation and recovery. Border overlays/correction, deskew and selected-frame rescan with revision history. |
| 2 | Join scanner, developing and archive records | Real captures reference stable roll/frame IDs; stock, ISO, camera, dates, tags, notes and status are searchable; development history, contact sheets and verified archive completion operate on these same records. Current `cv_captures` free-text roll names are separate. |
| 3 | Validate conversion and calibration | Multiple negatives/scenes/stocks and controlled references; remaining Auto Gamma differences; optional scanner ICC/IT8 characterization; measured effective precision. Existing recovered vendor conversion is implemented, but one garden comparison is not general calibration. |
| 4 | Real development workflows | Sourced/versioned B&W and C41 recipes, custom recipe editor, temperatures/deviations, chemistry batches/dilutions/capacity, linked history, foreground alerts/wake lock and offline reconciliation. Current supplied recipe is water rehearsal only. |
| 5 | Portable backup and restore | Back up images, recipes, profiles, metadata and checksums together; restore on another location/machine; migrations, interrupted file/database commits and orphan reconciliation. A SQLite backup alone is insufficient. |
| 6 | Mobile companion | Deliberate LAN/HTTPS setup, scoped device pairing/revocation, permissions for remote physical operations, physical iPhone/iPad/Safari tests and offline timer behavior. Chromium phone emulation is already exercised. |
| 7 | Distribution and hardening | Clean-machine setup/installer, pinned dependencies and notices, shutdown/recovery, accessibility, and measured large-image/concurrent memory use. |

## Independent driver work

The current direct bridge still uses SCAN08 and the vendor USB stack.
[custom-driver.md](custom-driver.md) documents the raw-command workbench,
implemented Windows transport, strict replay and independently verified live
identity/page-0 status reads. Arbitrary register/bulk commands stay disabled.
This is not a finished replacement acquisition driver.

Completing the requested independent driver now requires independently validated
initialization and calibration, ordinary acquisition, exposure/focus/film movement, then bounded
extended-capture experiments. Increasing the number of CCD rows is not yet known
to extend the film axis needed for two successive frames. Keep originals and
actual coverage; do not resize one frame and call it a two-frame acquisition.

Optional later experiments include dust/scratch repair, repeated-exposure averaging,
multiexposure, sharpening, labeled AI upscaling, native iOS and firmware research.
They should not obscure the release requirements above.
