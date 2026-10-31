# Flower detail and reference-derived tone — October 31, 2026

User review correctly identified that the nominal `0.5` response still looked
substantially worse than CyberView: pale foliage/flowers were lavender, paving was
purple and too dark, and small leaf/stem contrasts were compressed. The earlier
whole-image quantile improvement was insufficient evidence of image quality.

## Investigation and result

Registered the saved 120/168/269 direct acquisition against its CyberView reference
with an affine similarity transform: 2,567 inliers, median feature residual 0.39 px.
Full-size crops confirmed lost tonal separation and a colour cast in our rendering.

Fitted separate monotone red/green/blue curves from corresponding pixels, using
robust bin medians and weighted isotonic pooling. Both flower/foreground and paving
regions were excluded from curve fitting. Registration uses geometric features;
reference RGB values in those regions are used only for evaluation. The resulting
4096-row profile changes pixel tones globally and cannot copy spatial reference
detail. No sharpening, denoising, texture synthesis or acquisition was performed.

| Saved scan | Held-out RGB error before | After reference curves |
| --- | --- | --- |
| 120/168/269, used to fit curves outside the excluded regions | 22.82 | 5.28 |
| 100/100/100, same profile without refitting | 22.94 | 5.50 |

Error is aligned pixel mean absolute RGB difference on a 0–255 scale in the
excluded regions. It replaces the earlier whole-image quantile metric for this
detail comparison. It is not Delta E or a measured optical resolution. Residual
differences include scan noise, registration/interpolation and rendering.

These remain two exposures of **one negative**. This result validates an
experimental appearance match for that negative, not universal colour conversion,
scanner characterisation, or an exact reconstruction of CyberView's algorithm.
The generic `0.5` response remains an incomplete starting point. Do not promote
this fitted profile as a global default without other photographic references.

## Deliverables and use

Private files under `.local/color-review/reference-profile/`:

- `corrected.tif`: full native-size, 16-bit RGB rendering from the original scan.
  It uses the reference-derived curves without spatial warping of the deliverable.
- `comparison.jpg` and `detail.jpg`: registered whole-image and excluded-region
  comparisons: previous conversion, reference curves, CyberView.
- `profile.json`, `recipe.json`, `report.json`, `transfer-exposure.json`: exact
  curves, rendering settings, input hashes, registration and metrics.

The local generated profile is installed in ignored `data/film_profiles/`, named
**Garden - CyberView reference (experimental)**. In CyberScan, use **Balance
negative** on an older direct negative first, then choose that film rendering
profile. Selecting it sets its input response and clears automatic colour.
Rebalancing a reference-profile image does not apply automatic colour again.
Application restart is needed to load updated code; no user's live service was
restarted for this work. Existing saved edits and acquisitions were not migrated.

Profile discovery is explicit to CyberScan (`include_reference=true`). The general
FRAME pipeline, which uses a different inversion response, neither lists nor
accepts these profiles. A reference profile is identified by its content hash;
listing, loading and caching verify its digest, dimensions, range, matrix and
input response. Corruption cannot silently change exports under the same ID.

Reproduce with the optional OpenCV analysis dependency (locally available 5.0.0):

```
python scripts/fit_reference_tone.py SOURCE.tif REFERENCE.tif OUTPUT_DIR --holdout 0,1200,900,1700 --holdout 1500,1100,2250,1600 --name "Garden - CyberView reference (experimental)"
```

Holdout coordinates must be chosen for the actual reference image. The command
checks same-frame registration, keeps separate training/test regions, writes a
native-grid TIFF and verifies source/reference hashes after output. It does not
install a profile or modify the library itself. `profile.json` can be copied to
`LIBRARY/film_profiles/PROFILE_ID.json`; its embedded `id` supplies that filename.

Tests cover known channel responses on excluded synthetic pixels, prevention of
reference texture transfer, finite monotone high-precision output, cache integrity,
scope isolation, preview/export selection and identical exports after restart.
Independent review identified cache-validation, digest-verification and shared-list
scope gaps; all were corrected with regression coverage. Actual command results
are recorded in [progress.md](progress.md).
