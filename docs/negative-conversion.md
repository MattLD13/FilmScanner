# Negative conversion continuation — October 31, 2026

**Subsequent user review found the generic result still inadequate for flower
detail and colour balance.** See [reference-tone.md](reference-tone.md) for aligned
crop evidence and an experimental reference-derived profile. The quantile results
below are historical brightness comparisons, not a claim of sufficient quality.

The direct-capture checkpoint fixed acquisition exposure, but display conversion
still used base `[1,1,1]` and fixed response `1 - transmission ** 1.6`. A measured
film base near `[.84,.855,.856]` therefore did not map to black. The stitched path
also omitted the automatic colour applied to ordinary scans.

## Rendering change

`services/imaging/negative.py` suggests mean RGB of the jointly brightest 0.5% of
valid transmission pixels. It excludes uncovered stitch margins and refuses flat,
nearly opaque or clipped inputs. It cannot prove the brightest region is bare film;
the UI labels this a suggestion and retains manual film-base controls.

The versioned nominal response is
`positive = 1 - clip(transmission / film_base, 0, 1) ** negative_response`.
New direct negatives with a usable base start at response `0.5`, chosen by comparing
two saved exposures with CyberView's image of the same negative. This is an
appearance starting point, not measured film response or scanner characterisation.
Unusable suggestions retain the prior conversion. Saved recipes missing this field
retain their exact `1.6` conversion, including edits from older clients.

Single and stitched captures use the same conversion and automatic colour.
Conversion changes clear stale automatic-colour control points. Reset preserves
the chosen response. The existing hardware exposure calculation and validation
files are unchanged.

**Balance negative** applies the suggestion to a saved direct negative without
scanner access or exposure changes. It preserves other viewing adjustments;
users can reset those separately. Unsupported positives and unreliable suggestions
return explanations without changing edits. Concurrent adjustment changes return
409; concurrent titles/favorites are preserved. TIFF exports include engine
`cyberscan-negative-1`, the complete recipe and original checksum.

## Offline comparison

Private inputs: `data/sessions/direct-11/default1800.tif` (100/100/100),
`data/sessions/direct-12/exposed1800.tif` (120/168/269), and the existing CyberView
`Pictures/FilmScans/image001.tif`. None is distributed in Git.

Run `python scripts/compare_negative.py SOURCE.tif REFERENCE.tif OUTPUT_DIRECTORY`.
It writes comparison/component JPEGs and JSON with source/reference hashes and
the full recipe. It verifies both input hashes after writing, without changing the
library. Both former and proposed conversions compute their own automatic colour.

| Exposure | Suggested base RGB | Previous error | Proposed error |
| --- | --- | --- | --- |
| 100/100/100 | approximately .707/.507/.316 | 66.88 | 14.95 |
| 120/168/269 | approximately .841/.855/.856 | 82.39 | 14.43 |

Error is mean absolute RGB quantile difference from the reference: 97 quantiles
between the 2nd and 98th percentiles, on a 0–255 scale. It tolerates small framing
differences but **does not establish pixel registration, colour accuracy, Delta E,
or transfer to another scene or film stock**. These are repeat measurements of one
negative, not two independent photographic references. Residual foliage/paving
differences remain; further references are needed for calibrated colour or exact
vendor parity. Outputs are under `.local/color-review/default-exposure/` and
`.local/color-review/final/`.

## Verification

Targeted tests cover neutral-density/exposure invariance, monotonic conversion,
legacy reproduction, invalid inputs, coverage masks, saved-scan authentication,
conflicting edits, immutable originals and identical TIFF exports after restart.
The browser workflow exercises Balance negative, response preview, Reset and the
exported recipe using synthetic film only.

Independent review prompted fixes for concurrent edit loss, automatic colour
including uncovered stitch margins when toggled, and Reset restoring an incompatible
response. Regression tests cover the corrections.

An intermediate targeted run failed
`test_each_direct_scan_sets_the_next_exposure_from_its_film_base`: an early refactor
had applied new rendering validity checks to the existing exposure calculation.
The refactor was removed, restoring the prior exposure behaviour; the regression
subsequently passed. Final commands/results are in [progress.md](progress.md).
