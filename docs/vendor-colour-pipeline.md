# Recovered PF1800 AFL colour stages

Offline investigation, October 31, 2026. This replaces the assumption that a
single nominal negative-response exponent can reproduce CyberView's colours.
It does **not** establish full CyberView output parity.

## Source and evidence

Installed `CyberViewX.ds` 1.4.0.0, SHA-256
`bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb`.
Internal addresses below are preferred-base VAs (`0x10000000`); the oracle uses
RVAs only after checking this exact hash. Vendor binaries and curves stay local.

Static inspection is repeatable with:

```
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/colour_survey.py --function ADDRESS --limit 0x3000
```

The optional analysis environment supplies pefile and Capstone. The script reads
PE bytes; it does not load vendor modules. Private annotated disassemblies are in
`.local/vendor-colour/` and `.local/vendor-gamma/`.

| Stage | Evidence | Result |
| --- | --- | --- |
| Model generic gamma selection | `CPfs1800AFL` constructor `0x101403a0`, string assignment `0x10140476` | The AFL selects **37.GG**, despite that file's PF3600AFL comment |
| Model generic gamma loading | `0x10164150`, reader constructor `0x100691d0`, file reader `0x10069340`, copy `0x10168aa0` | 4096 RGB floats, converted by truncation to model WORD tables |
| Negative inversion | `0x1004cd80`, 48-bit negative branch `0x1004d16c` | Each scanner LUT entry is `4095 - model_gamma[channel][index]` |
| Film-term setup/application | `CFilmCIP` constructor `0x10004490`, loader `0x100045c0`, config `0x10100e10`, Run `0x10105490` | Config 5 applies the film LUT and then the matrix |
| Film-term 16-bit mapping | `0x10108920` and `0x10108b30`, dispatched via `0x1010a700` | Integer interpolation/quantisation and matrix arithmetic described below |
| Auto Gamma table generation | `0x10115290` → `0x10104360` | Actual worker is Lagrange; duplicate endpoint x values produce zero tables in the isolated call |

Installed `37.GG` SHA-256:
`ea23cb1594620dacc6160a9d96eda9e62bffde40558a357c9066c05bf40808c8`.
Its curves are not identical across channels. This was a substantial missing
component of the previous nominal conversion.

## Verified film-term arithmetic

`services/imaging/vendor_filmterm.py` retains .ft LUT and matrix decimal values as
float32, rather than truncating LUT entries to integers as the old parser did.

For a 256- or 4096-row table, float32 knots are first expanded to uint16 by
`trunc(knot * 65535 / (rows - 1))`. The table builder interpolates in integer input
coordinates with truncation towards zero. The matrix operates on those integer
RGB values using float32 coefficients; the dot product is stored once to float32
before clipping and truncating to uint16. 4096-row matrix offsets are first scaled
by `255 / 4095`, as in the loader. Existing recipes keep the old application path.

`services/cyberview_bridge/vendorcolour.c` provides an offline oracle:

```
vendorcolour film INPUT.raw WIDTH HEIGHT 16 PROFILE.ft OUTPUT.raw
vendorcolour generic PROFILE.GG OUTPUT.raw
vendorcolour curve POINTS.txt 256 OUTPUT.raw
```

It calls only the inspected image workers or file readers on caller-owned
buffers, sends no TWAIN message or scanner command, refuses a running CyberView
app, pins the binary hash, backs up/restores settings and refuses output overwrite.
The build is `services/cyberview_bridge/build.ps1 -Tests`. No hardware session was
opened for this work.

Four synthetic exhaustive-domain tests compare the Python film-term stage with
the actual vendor worker: both table sizes, fractional entries, identity/mixing
matrices, offsets, all uint16 inputs with different channel permutations. Every
output sample matched. The generic reader also matches a synthetic fractional
4096-row file after the model's truncation. Settings hashes remain unchanged.

## FRAME integration and limits

`afl-vendor-negative-1` is an **explicitly selected** film rendering profile. In
**Film & colour**, select a stock suffixed **AFL conversion**, such as Kodak 200.
The app combines the locally installed 37.GG with the chosen .ft and caches a
content-hashed profile in the user's ignored library. Existing saved recipes are
not migrated, and ordinary/reversal/BW profiles remain selectable.

The recovered conversion bypasses nominal film-base/power controls, complements
the model gamma and applies the verified 16-bit film-term stage. Because FRAME
captured using an identity device LUT, it interpolates the recovered 12-bit gamma
in software to retain its 16-bit container. **That adapter is not a claim of
bit-identical scanner LUT application or measured sensor precision.** Acquisition
calibration and exposure are not changed. Best results require a scan already
acquired at balanced per-channel exposure.

Auto colour starts off when this profile is selected. The existing optional
monotone Auto Gamma approximation remains available as an edit. The exact worker
`0x10104360` appends endpoints `(0,0)` and `(255,255)` without deduplication: calling
it with the common white/black endpoint controls produces an all-zero table.
The surrounding caller's table selection/state is not yet understood well enough
to substitute this worker in production. Its surprising behaviour is retained as
a CPU-only regression, rather than silently replacing usable colour with zeroes.

The incompatible general FRAME simulator/archive conversion does not list or
accept these profiles. The scanner API rejects them for already processed
positives or with inversion off. Preview/export use the same recovered stages.
Profiles verify full content identity and structure on cache/load/listing; no
vendor tables or user images are committed.

## Photographic check without reference fitting

Command used on an existing balanced acquisition:

```
python scripts/compare_vendor_negative.py data/sessions/direct-12/exposed1800.tif "C:/Windows/twain_32/CyberViewX_MF/GAMMA/Kodak 200.ft" C:/Windows/twain_32/CyberViewX_MF/GAMMA/37.GG C:/Users/mld20/Pictures/FilmScans/image001.tif .local/color-review/vendor-pipeline
```

The reference is used only for geometric alignment, evaluation and display;
**no reference pixel colours are used to fit the rendering**. Registration found
3,232 inliers, median residual 0.366 px. Mean aligned RGB difference over valid
overlap is 9.47 levels on a 0–255 scale. This is not the earlier holdout/quantile
metric and must not be directly compared with those numbers.

The flower crop shows substantially more tonal separation and better colour than
the nominal response, with remaining differences from CyberView. The check still
uses one negative and differently exposed acquisitions; it cannot establish
general colour accuracy or identical vendor output. The prior fitted garden
profile remains separately labeled experimental.

Private results include native-size `corrected.tif`, `comparison.jpg`,
`flowers.jpg`, exact `profile.json`/`recipe.json`, input hashes and metrics under
`.local/color-review/vendor-pipeline/`. Inputs were verified unchanged after
rendering. Profile `4fe5c640f76366f8` was cached locally; existing capture edits were
left unchanged. Current checks and UI changes are recorded in `docs/progress.md`.
