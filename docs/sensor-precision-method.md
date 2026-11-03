# Acquisition output precision and repeat-noise measurements

`services/imaging/sensor_precision.py` and `scripts/measure_sensor_precision.py`
inspect original acquisition samples without opening a scanner connection. The
report distinguishes observations from the effective precision of a sensor/ADC.

## Measurements provided

- TIFF sample/container width: uint8 or uint16, not a sensor-bit claim.
- Each channel's occupied codes, varying bits, low-zero-bit pattern, and greatest
  common divisor of occupied code spacings. A 12-bit code left-shifted by four
  has a 16-code lattice and four zero low bits, but calibrated/LUT output can
  obscure that lattice. Conversely, populated low bits do not prove 16-bit sensing.
- Scene code entropy, percentiles, and clipped endpoint fractions. Scene texture,
  film grain, and lighting affect these numbers; entropy is not ADC ENOB.
- For two to eight matching-setting originals: constrained optical registration,
  low-gradient acquired-pixel selection, robust pair-difference output noise,
  full-scale pair-difference RMS, and measured global pair offsets.
- A **quantization-equivalent output-noise bit estimate**,
  `log2(full_scale_code / (sqrt(12) × sigma_output_codes))`, capped at the
  container size. This is explicitly not a calibrated ADC ENOB result. It assumes
  comparable exposures/response and uncorrelated temporal noise; lamp/calibration
  changes, residual motion, resampling, and noise correlations affect it. Identical
  inputs return unknown noise-bit precision rather than infinity.

`effective_sensor_bits` and `effective_adc_bits` remain null. Establishing either
requires a known linear raw response, controlled flat/dark or calibrated target
measurements, and an appropriate noise/dynamic-range method. A vendor-calibrated
transmission image and a single photographed negative cannot establish this.

Inspecting CyberView X does not remove that measurement requirement. Its installed
manual's8/16-bit choice describes output depth; the pinned AFL module expands a
4096-entry table into16-bit-container output. These facts do not establish ADC
ENOB. See the [November2 vendor/vertical investigation](vertical-containment-2026-11-02.md)
for exact module identity, static addresses and fresh acquisition evidence.

## Original-file evidence

The CLI requires a metadata JSON with one entry and matching SHA-256 per input.
Entries explicitly state original-acquisition status, hardware versus simulation,
image kind, and acquisition settings. Derived, processed, stitched, and resampled
images are refused as sensor-evidence inputs. A bare array without provenance may
be inspected, but is labeled unverified and never hardware sensor evidence.

Repeat measurements require identical declared settings. Strong scenes are
optically registered using the existing displacement/texture/ambiguity checks.
A truly flat field may not support registration; the operator can explicitly
declare `same_position: true`, in which case the report marks unverified stationary
alignment and warns that motion can inflate noise. No motor commands are issued.

Vendor auto-exposure repeats are rejected unless every metadata entry supplies
the **measured** `effective_exposure: [R,G,B]`, and those values match exactly.
Equal requested exposure settings do not establish equal exposure when the vendor
chooses gains internally. An averaged repeat TIFF is derived and is rejected by
its known `FRAME optical repeat mean` software marker, like stitched masters.

Example (metadata paths are relative to the metadata file):

```json
{
  "acquisitions": [
    {
      "path": "first.tif",
      "sha256": "PUT_THE_ACTUAL_SOURCE_SHA256_HERE",
      "original_acquisition": true,
      "hardware": true,
      "synthetic": false,
      "image_kind": "vendor-calibrated-transmission",
      "same_position": true,
      "settings": {"dpi": 1800, "bits": 16, "exposure": [100, 100, 100], "lut": "identity"}
    }
  ]
}
```

```powershell
python scripts/measure_sensor_precision.py first.tif --metadata originals.json --output precision.json
```

One file gives code diagnostics. Supply up to eight distinct files with matching
metadata to add repeat-noise analysis. Output uses exclusive creation and cannot
replace an acquisition or its metadata. All source hashes are rechecked afterward.

## Optional derived-image processing

`scan_filters.process()` provides general alternatives for chroma/contrast
restoration, edge-aware grain smoothing, and constrained sharpening. The strength
controls are independent and default to zero. These are not exact Kodak ROC/GEM,
infrared scratch repair, or a recovery of faded information. Originals remain
untouched, and the caller stores the engine/settings beside the derived result.

`scan_filters.aligned_mean()` combines two to eight optically verified repeated
captures. It uses strict registration and arithmetic averaging with recorded
additive common-mask RGB offset normalization, without multiplicative exposure
matching or stitching feather weights. Pixel contribution counts disclose areas
with fewer repeats. Ambiguous/low-texture alignment fails rather than silently
averaging misregistered scans. Averaging does not increase optical resolution or
prove a new sensor bit depth.
