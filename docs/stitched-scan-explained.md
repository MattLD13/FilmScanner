# What the stitched scan does

The main UI now presents [Auto find borders](auto-find-borders.md), which locates
the frame with quick previews before selecting the needed final coverage. The
full-resolution recovery described below remains available as Recover full frame
in Scanner controls. The new workflow was also tested on loaded film; current
results are recorded in [progress.md](progress.md).

Current software update (October 31, 2026): source views no longer use the wider
mosaic's crop/dimensions. Crops now follow measured border spacing where two edges
are visible; missing dimensions remain nominal estimates. A new stitched crop is
applied automatically only when both horizontal borders are detected. Existing
saved edits are retained. Historical fixed-size results below remain historical
evidence, not measurements of this updated behavior. See [auto-align.md](auto-align.md).

A stitched scan photographs the same negative three times through slightly
different horizontal windows. FRAME joins the overlapping scans so a frame edge
that fell outside the first window can be recovered. It increases the area
captured, not the scanner's optical resolution.

## The capture sequence

1. Scan the film at its starting position. This is the centre reference image.
2. Move the film backwards a small number of motor steps, then scan again.
3. Measure the displacement between those two images. This estimates motor steps
   per millimetre from image content rather than assuming a precise motor pitch.
4. Move forwards past the starting position, then take the third scan.
5. Command a backwards move intended to undo the remaining displacement.
6. Align the three images, blend their overlap, and suggest a 36 × 24 mm crop.

The first probe is 20 steps when no calibration has been saved. Later runs use the
requested offset and saved steps-per-millimetre estimate to choose a bounded
probe. Each move is divided into calls of at most 300 steps. Acquisition remains
gated by the scanner's recorded validation; permission to stitch is not permission
to issue an arbitrary new motor command.

This is one frame captured three times. It does not advance through three frames
of the roll. Film movement can vary between directions and runs, so image
registration measures each scan's actual position again.

## How the images are joined

The centre scan is the reference. FRAME first searches small, reduced grayscale
copies for the overlapping image content, then refines the shift at full
resolution. The commanded movement supplies a search estimate, not the final
placement. Horizontal and vertical shifts are measured; the method does not
correct changing perspective, rotation, or local film distortion.

For each outer scan, FRAME compares overlapping pixels with the centre scan and
estimates a separate gain for red, green, and blue. This compensates for modest
brightness differences. It blends the overlap with gradually changing weights:
pixels near a scan's centre contribute more than pixels near its edges.

At the reviewed implementation checkpoint, the measured shifts have fractional
pixel precision but image placement rounds them to whole pixels. It is not a
subpixel super-resolution reconstruction. Overlap blending may soften fine
detail if registration, film flatness, or focus differs between acquisitions.
Three scans do not guarantee more detail or less noise.

The three original TIFFs remain separate and retain their recorded checksums.
The mosaic is a derived TIFF, with a coverage image identifying where at least
one source supplied data. Colour conversion and the final crop remain editable.

## What the saved physical test demonstrated

The saved session `fbedeac68601496ebee3dbc6f84f3038`, recorded on October 31,
2026, used the direct AFL driver at 1800 dpi and 16-bit RGB. Its persisted session
timestamps span approximately **207 seconds**. This is one measured session, not
a promised scan duration.

| Item | Saved result |
| --- | --- |
| Capture order | Centre, backwards position, forwards position |
| Commanded moves recorded in the session notes | Back 20 steps, forward 28, back 8 |
| Each original | 2479 × 1703 pixels, approximately 34.981 × 24.031 mm |
| Measured outer-image horizontal placement relative to centre | −92.89 pixels and +75.67 pixels, approximately −1.311 mm and +1.068 mm |
| Measured vertical placement | +6.35 and +9.05 pixels |
| Learned step estimate | 15.258 steps/mm |
| Registration strengths | 0.3359 and 0.3358; centre is recorded as 1.0 |
| Overlap gains | Back: 0.9950/0.9953/0.9938; forward: 0.9896/0.9891/0.9886 |
| Derived mosaic | 2648 × 1713 pixels, approximately 37.366 × 24.172 mm |
| Suggested crop | 2551 × 1701 pixels, approximately 35.997 × 24.003 mm |
| Frame-edge evidence | One horizontal frame edge found; the opposite edge inferred from the nominal 36 mm frame width |
| Reported skew | −0.458 degrees; measured, not automatically deskewed |

An offline audit checked the three source files and mosaic against their saved
SHA-256 values: all matched. The saved coverage image has **4,397 uncovered
pixels** around the mosaic boundary. The suggested crop contains **105 uncovered
pixels** out of 4,339,251, or approximately **99.9976% coverage**.

The historical record labels that crop `exact: true`. At that checkpoint, this
meant its nominal dimensions fitted the mosaic rectangle; the code did not
require every pixel in the crop to be covered. Consequently the physical test
demonstrated a nominal 36 × 24 mm crop and wider captured field, with a small
amount of missing edge coverage. It did not establish a completely acquired
36 × 24 mm rectangle, two-edge detection, or repeatability over a whole roll.

The last move commanded the opposite net motor step count, but there was no
fourth scan after that move. The saved stitched session therefore does not prove
that the film returned to exactly its starting position. A separate supervised
600 dpi movement test reported that back 20 and forward 20 steps returned within
0.11 mm; that is separate evidence, not a measurement of this final return.

## Scanner findings, 2026-10-31 evening

Three stitched runs on the PF1800 AFL through the app showed that **step counts are not a
reliable distance**:

| Command | Measured move |
| --- | --- |
| 20 steps (four times) | about 1.2-2.3 mm, each time |
| 6 steps after a scan | 0.10 mm (backlash ate most of it) |
| 31 or 37 steps | about 3.8 mm (a coarser step mode) |

A calibration from a 6-step probe (62 steps per mm) then sent the film 3.7 mm too far, and
the stitch correctly refused. The sequence is now fixed to 20-step commands only
(`NUDGE_CHUNK`): back 20, forward 2 x 20, back 20. Every position is measured from the
images over a 4 mm window, the forward scan must land on the other side of the back scan,
and a learned steps-per-mm outside 8-30 is ignored. With that, a run gave offsets
-2.27 / 0 / +1.72 mm, matches 0.21 and 0.19, a 2763 x 1712 mosaic and an exact
36 x 24 mm crop.

Ragged top and bottom edges (each scan sits a few px higher or lower) are filled from the
nearest scanned row of the same column; `covered` still records what was scanned. A crop
may include such filled edge pixels (at most 0.05 %; 272 pixels, 0.006 %, in that run) and
first slides up to 0.2 mm to avoid them. A hole inside the scanned area still blocks the crop.

## Crop and resolution limits

At 1800 dpi, 36 mm corresponds to approximately 2551 pixels. Joining wider scan
windows supplies those pixels from adjacent parts of the film; it does not make
the pixels smaller. The optical sampling remains 1800 dpi and effective acquired
sensor precision remains unmeasured despite the 16-bit file container.

Moving along the film chiefly expands horizontal coverage. It does not provide a
controlled vertical panorama. A requested crop or positive bleed may still be
taller than the available scan. A measured skew is information for review; an
axis-aligned crop does not by itself straighten the frame.

Gap detection looks for uniform clear film between images. One detected edge can
anchor a nominal full-frame crop. With no visible edge the suggestion is centred.
Those fallbacks are useful starting points, not proof of the actual exposure's
boundaries. Half-frame pictures, nonstandard frame sizes, substantial skew, low
texture, or an incorrect scanner DPI need separate handling and review.

## Cancellation and failures

A return move is an attempted physical operation, not a guarantee. An interrupted
scan, failed motor command, disconnected scanner, or uncertain film position can
leave the film displaced. Automatically sending more moves after an uncertain
failure could make recovery worse.

The code review accompanying this explanation found that the historical
stitched path lacked a persistent cancellation flag across its individual scans
and moves, and did not record a reliable return position after errors. It also
accepted a final registration without enforcing a minimum match strength. These
findings were sent for implementation fixes. They should not be described as
validated physical recovery simply because software regression tests pass.

Saved acquisitions survive an interrupted attempt. A finished mosaic should be
reported only after the required images, registration, and output saving succeed.
After a failed attempt, the user needs a truthful distinction between a known
commanded offset, an uncertain physical position, and an image-verified return.

## Evidence and implementation

- Acquisition sequence: `services/api/cyberview_routes.py`, `run_stitched`.
- Registration, gain matching, feathering, and crop calculation:
  `services/imaging/frame_align.py`.
- Real movement validation: `services/scanner_host/native_validation.json`.
- Historical session notes: `docs/standalone-plan.md`.
- Original local files, mosaic, metadata, and coverage: the ignored library folder
  `data/cyberview/fbedeac68601496ebee3dbc6f84f3038/`.

This document was written from source inspection and offline inspection of those
saved acquisitions. No scanner, bridge, vendor module, or motor command was run
for this analysis.
