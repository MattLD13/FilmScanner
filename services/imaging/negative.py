"""Suggested film base and a nominal negative response, without scanner access.

This is a rendering starting point, not a measured film or scanner profile. The
response was compared with two saved exposures of the garden negative and its
CyberView reference. Existing recipes keep their original response of 1.6.
"""
from __future__ import annotations

import numpy as np

VERSION = 'cyberscan-negative-1'
SUGGESTED_RESPONSE = .5
LEGACY_RESPONSE = 1.6


def suggest_base(samples: np.ndarray, covered: np.ndarray | None = None) -> list[float] | None:
    """Mean RGB of the brightest 0.5% of valid transmission pixels.

    Pixels must be jointly bright; independent channel percentiles can mix scene
    colours. Exclude uncovered stitch pixels. Refuse flat, clipped or nearly
    opaque inputs. A bright image region may still be mistaken for clear film;
    callers must label this as a suggestion and retain manual base controls.
    """
    rgb = np.asarray(samples)[..., :3].reshape(-1, 3)
    if covered is not None:
        if covered.shape != samples.shape[:2]:
            raise ValueError('Coverage must match the image dimensions')
        rgb = rgb[np.asarray(covered, dtype=bool).reshape(-1)]
    rgb = rgb[np.all(np.isfinite(rgb) & (rgb >= 0) & (rgb <= 1), axis=1)]
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
