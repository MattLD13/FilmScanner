"""Optional derived-image filters; no vendor ROC/GEM algorithm is claimed.

Inputs and original acquisition files are never mutated. Restoration is a
bounded contrast/chroma adjustment, not recovery of faded information. Grain
reduction is edge-aware smoothing and sharpening is local-contrast enhancement.
"""
from __future__ import annotations

import math
import numpy as np

from services.imaging import acquisition_plan

VERSION = 'frame-scan-filters-1'
REPEAT_MEAN_VERSION = 'frame-repeat-mean-2'
MAX_PIXELS = 32_000_000
SETTINGS = ('color_restoration', 'grain_reduction', 'sharpening')
LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)


def _image(samples):
    image = np.asarray(samples)
    if image.ndim != 3 or image.shape[2] != 3 or image.shape[0] * image.shape[1] > MAX_PIXELS:
        raise ValueError('Filters need an RGB image of at most 32 megapixels')
    if min(image.shape[:2]) < 2 or not np.isfinite(image).all() or np.any(image < 0) or np.any(image > 1):
        raise ValueError('Filters need finite RGB samples in 0..1')
    return image.astype(np.float32 if image.dtype.itemsize <= 4 else np.float64, copy=True)


def _gamut(luma, chroma):
    """Scale chroma toward neutral to stay in gamut without independent clipping."""
    scale = np.ones(luma.shape, dtype=luma.dtype)
    for channel in range(3):
        delta = chroma[..., channel]
        bound = np.where(delta > 0, (1 - luma) / np.maximum(delta, 1e-12),
                         luma / np.maximum(-delta, 1e-12))
        scale = np.minimum(scale, np.where(abs(delta) > 1e-12, bound, 1))
    return np.clip(luma[..., None] + chroma * np.maximum(scale, 0)[..., None], 0, 1)


def _smooth(image, strength):
    padded = np.pad(image, ((1, 1), (1, 1), (0, 0)), mode='reflect')
    luma = image @ LUMA
    accumulator = image.copy()
    weights = np.ones(image.shape[:2], dtype=image.dtype)
    sigma = .015 + .045 * strength
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if not dx and not dy:
                continue
            neighbor = padded[1 + dy:1 + dy + image.shape[0], 1 + dx:1 + dx + image.shape[1]]
            distance = np.sum((neighbor - image) ** 2, axis=2)
            # Joint RGB distance keeps colored edges as well as luminance edges.
            weight = np.exp(-distance / (2 * sigma * sigma)) * (.7 if dx and dy else 1)
            accumulator += neighbor * weight[..., None]
            weights += weight
    return image * (1 - strength) + accumulator / weights[..., None] * strength


def process(samples: np.ndarray, settings: dict | None = None) -> np.ndarray:
    """Apply color_restoration, grain_reduction, sharpening, each within 0..1.

    Disabled settings are identity. These are general software alternatives,
    not ports of Kodak ROC/GEM, infrared repair, or calibrated color restoration.
    The caller stores VERSION/settings as a separate derived-image recipe.
    """
    settings = settings or {}
    if not isinstance(settings, dict) or any(key not in SETTINGS for key in settings):
        raise ValueError('Unknown scan filter setting')
    values = {}
    for name in SETTINGS:
        value = settings.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'{name} must be a finite number in 0..1')
        values[name] = float(value)
    out = _image(samples)
    if values['grain_reduction']:
        out = _smooth(out, values['grain_reduction'])
    if values['color_restoration']:
        strength = values['color_restoration']
        luma = out @ LUMA
        # Monotone contrast mapping fixes black and white, without auto-clipping
        # endpoints or treating the average color of the scene as a neutral.
        contrast = np.clip(luma + .4 * strength * (luma - .5) * luma * (1 - luma), 0, 1)
        out = _gamut(contrast, (out - luma[..., None]) * (1 + .25 * strength))
    if values['sharpening']:
        blurred = _smooth(out, 1)
        detail = (out - blurred) @ LUMA
        padding = np.pad(out @ LUMA, 1, mode='reflect')
        neighborhood = [padding[1 + y:1 + y + out.shape[0], 1 + x:1 + x + out.shape[1]]
                        for y in (-1, 0, 1) for x in (-1, 0, 1)]
        low, high = np.minimum.reduce(neighborhood), np.maximum.reduce(neighborhood)
        luma = out @ LUMA
        enhanced = np.clip(luma + 1.5 * values['sharpening'] * detail, low, high)
        out = _gamut(enhanced, out - luma[..., None])
    return out


def _sample(image, dy, dx):
    """Moving placement (dy,dx) onto reference; bilinear only where acquired."""
    height, width = image.shape[:2]
    yy = np.arange(height, dtype=float) - dy
    xx = np.arange(width, dtype=float) - dx
    y0, x0 = np.floor(yy).astype(int), np.floor(xx).astype(int)
    fy, fx = yy - y0, xx - x0
    valid_y = (yy >= 0) & (yy <= height - 1)
    valid_x = (xx >= 0) & (xx <= width - 1)
    y0 = np.clip(y0, 0, height - 1); x0 = np.clip(x0, 0, width - 1)
    y1 = np.minimum(y0 + 1, height - 1); x1 = np.minimum(x0 + 1, width - 1)
    sampled = (image[y0[:, None], x0] * ((1 - fy)[:, None] * (1 - fx))[..., None] +
               image[y1[:, None], x0] * (fy[:, None] * (1 - fx))[..., None] +
               image[y0[:, None], x1] * ((1 - fy)[:, None] * fx)[..., None] +
               image[y1[:, None], x1] * (fy[:, None] * fx)[..., None])
    return sampled, valid_y[:, None] & valid_x


def aligned_mean(images: list[np.ndarray], offsets: list[dict] | None = None, *,
                 dpi: float = 1800, search_radius_px: float = 3,
                 normalize_offsets: bool = True) -> dict:
    """Average 2–8 actual repeat images after constrained optical verification.

    Offsets describe each acquisition's placement relative to the first as
    {dx,dy}. They seed registration, not proof of its correctness. A median RGB
    delta relative to the first acquisition is measured on their shared acquired,
    unclipped interior and subtracted before averaging. No multiplicative exposure
    matching, sharpening, feathering or reference-image texture is introduced.
    Output geometry is the first source's geometry; counts disclose edge pixels
    that have fewer contributors. Original source retention is the caller's job.
    """
    if not 2 <= len(images) <= 8 or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError('Repeat averaging needs 2–8 same-resolution acquisitions and a positive DPI')
    if not math.isfinite(search_radius_px) or not 1 <= search_radius_px <= 30:
        raise ValueError('Repeat registration radius must be within 1–30 pixels')
    if type(normalize_offsets) is not bool:
        raise ValueError('Repeat offset normalization must be a boolean')
    arrays = [_image(image) for image in images]
    if any(image.shape != arrays[0].shape for image in arrays):
        raise ValueError('Repeat acquisition dimensions must match')
    offsets = offsets or [{'dx': 0., 'dy': 0.} for _ in images]
    if len(offsets) != len(images) or any(not all(math.isfinite(float(item.get(k, 0))) for k in ('dx', 'dy')) for item in offsets):
        raise ValueError('A finite measured/expected offset is needed per repeat')
    measured = [{'dx': 0., 'dy': 0.}]
    registration = []
    full_coverage = np.ones(arrays[0].shape[:2], dtype=bool)
    # Saturated calibration/edge pixels cannot establish a channel offset.
    epsilon = 1 / 65535
    common = np.all((arrays[0] > epsilon) & (arrays[0] < 1-epsilon), axis=2)
    first = offsets[0]
    for image, offset in zip(arrays[1:], offsets[1:]):
        expected = (float(offset.get('dy', 0)) - float(first.get('dy', 0)),
                    float(offset.get('dx', 0)) - float(first.get('dx', 0)))
        placement, evidence = acquisition_plan._register(arrays[0], image, expected,
            {'x': search_radius_px, 'y': search_radius_px}, dpi=dpi)
        sampled, covered = _sample(image, *placement)
        full_coverage &= covered
        common &= covered & np.all((sampled > epsilon) & (sampled < 1-epsilon), axis=2)
        measured.append({'dx': placement[1], 'dy': placement[0]})
        registration.append(evidence)
    support = int(common.sum())
    if normalize_offsets and support < 64:
        raise ValueError('Too few shared unclipped acquired pixels to normalize repeat offsets')
    accumulator = arrays[0].astype(np.float64)
    counts = np.ones(arrays[0].shape[:2], dtype=np.uint8)
    channel_deltas = [[0., 0., 0.]]
    reference = arrays[0][common].astype(np.float64) if normalize_offsets else None
    # Resample a second time to keep full-size aligned copies out of a stack.
    # In particular, never clip each corrected input before forming the mean.
    for image, placement in zip(arrays[1:], measured[1:]):
        sampled, covered = _sample(image, placement['dy'], placement['dx'])
        delta = np.median(sampled[common].astype(np.float64) - reference, axis=0) if normalize_offsets else np.zeros(3)
        accumulator += (sampled - delta) * covered[..., None]
        counts += covered.astype(np.uint8)
        channel_deltas.append(delta.astype(float).tolist())
    mean = accumulator / counts[..., None]
    normalization = {
        'applied': normalize_offsets, 'reference_source_index': 0,
        'method': 'median_channel_delta_on_shared_unclipped_acquired_interior' if normalize_offsets else 'disabled',
        'measurement_pixel_count': support if normalize_offsets else 0,
        'full_contribution_pixel_count': int(full_coverage.sum()),
        'subtracted_rgb_deltas': channel_deltas,
        'units': 'normalized_transmission', 'multiplicative_gain_applied': False,
        'per_source_clipping_applied': False,
        'final_mean_below_zero_samples_rgb': np.sum(mean < 0, axis=(0,1)).astype(int).tolist(),
        'final_mean_above_one_samples_rgb': np.sum(mean > 1, axis=(0,1)).astype(int).tolist(),
    }
    return {'image': np.clip(mean, 0, 1).astype(arrays[0].dtype),
            'covered': counts > 0, 'counts': counts, 'full_repeat_coverage': full_coverage,
            'offsets_px': measured, 'registration': registration, 'source_count': len(images),
            'method': 'optically_verified_offset_normalized_mean' if normalize_offsets else 'optically_verified_arithmetic_mean',
            'engine': REPEAT_MEAN_VERSION, 'offset_normalization': normalization,
            'exposure_matching': False, 'originals_mutated': False}
