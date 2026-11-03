"""Suggested film base and a nominal negative response, without scanner access.

This is a rendering starting point, not a measured film or scanner profile. The
response was compared with two saved exposures of the garden negative and its
CyberView reference. Existing recipes keep their original response of 1.6.
"""
from __future__ import annotations

import numpy as np
from services.imaging import statistics_guard

VERSION = 'cyberscan-negative-3'
SUGGESTED_RESPONSE = .5
LEGACY_RESPONSE = 1.6
DISPLAY_VERSION = 'frame-negative-display-2'


def suggest_base(samples: np.ndarray, covered: np.ndarray | None = None, *, dpi: float | None=None) -> list[float] | None:
    """Mean RGB of the brightest 0.5% of valid transmission pixels.

    Pixels must be jointly bright; independent channel percentiles can mix scene
    colours. Exclude uncovered stitch pixels and isolated clipped edge pixels.
    Refuse flat, extensively clipped or nearly
    opaque inputs. A bright image region may still be mistaken for clear film;
    callers must label this as a suggestion and retain manual base controls.
    """
    if dpi is not None:
        covered,_=statistics_guard.mask(samples.shape,dpi,covered)
    rgb = np.asarray(samples)[..., :3].reshape(-1, 3)
    if covered is not None:
        if covered.shape != samples.shape[:2]:
            raise ValueError('Coverage must match the image dimensions')
        rgb = rgb[np.asarray(covered, dtype=bool).reshape(-1)]
    rgb = rgb[np.all(np.isfinite(rgb) & (rgb >= 0) & (rgb <= 1), axis=1)]
    if len(rgb) < 16:
        return None
    # Unmasked scanner-edge/light-leak pixels can be nearly white in all
    # channels, brighter than the orange rebate. They are not usable film-base
    # samples. Exclude a small clipped population instead of letting it force
    # the whole negative back to an unbalanced identity-base conversion.
    usable = np.all(rgb < .99, axis=1)
    if np.mean(usable) < .95:
        return None
    rgb = rgb[usable]
    if len(rgb) < 16:
        return None
    low, high = np.percentile(rgb, [1, 99], axis=0)
    if np.any(high - low < .005):
        return None
    luminance = rgb @ np.array([.3, .5, .2])
    base = rgb[luminance >= np.percentile(luminance, 99.5)].mean(axis=0)
    if np.any(base <= .02) or np.any(base >= .99):
        return None
    return [float(b) for b in base]


def invert(samples: np.ndarray, base, response: float = LEGACY_RESPONSE) -> np.ndarray:
    """Nominal response: 1 - (transmission / base) ** response, in float."""
    return 1 - np.power(np.clip(samples / np.asarray(base), 0, 1), response)


def suggest_display(positive: np.ndarray, valid: np.ndarray | None = None) -> dict | None:
    """Conservative general viewing recipe; no stock/reference image is required.

    Keep endpoints and use a monotone midtone lift rather than forcing every
    scene to the same mean brightness. Film-base normalization provides the
    starting channel balance; do not infer neutral objects from scene colors.
    Returns ordinary editable recipe fields, preserving the original samples.
    """
    image = np.asarray(positive, dtype=float)
    if image.ndim != 3 or image.shape[-1] != 3:
        raise ValueError('Display suggestion requires RGB pixels')
    if valid is not None and valid.shape != image.shape[:2]:
        raise ValueError('Display mask must match image dimensions')
    pixels = image.reshape(-1, 3) if valid is None else image[np.asarray(valid, dtype=bool)]
    pixels = pixels[np.all(np.isfinite(pixels) & (pixels >= 0) & (pixels <= 1), axis=1)]
    if len(pixels) < 32:
        return None
    luma = pixels @ np.array([.2126, .7152, .0722])
    if np.percentile(luma, 99.5) - np.percentile(luma, .5) < .08:
        return None
    # Keep acquired endpoint distinctions. A luminance percentile applied as
    # a shared RGB black point can zero a substantial part of one channel even
    # when only a small fraction of luminance is dark. Do not auto-trim it.
    # The curve/gamma are monotone viewing adjustments, not scanner calibration.
    return {'black_point': 0., 'white_point': 1., 'gamma': 1.2,
            'rgb_balance': [1., 1., 1.], 'curve': [0., .30, .57, .80, 1.],
            'evidence': {'version': DISPLAY_VERSION,
                'method': 'endpoint_preserving_midtone_curve',
                'valid_pixels': int(len(pixels)), 'reference_used': False,
                'automatic_endpoint_clipping': False,
                'conversion_status': 'nominal_negative_response_not_measured_scanner_calibration'}}
