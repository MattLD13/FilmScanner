"""Reference-derived monotone RGB tone curves; never copy spatial image detail.

Inputs must already be registered photographs of the same frame. Spatial holdout
regions are required for evaluation. This estimates an appearance profile, not
scanner colourimetry, and cannot establish generalisation to another negative.
"""
from __future__ import annotations

import hashlib
import json
import numpy as np

VERSION = 'reference-tone-1'


def identify(profile: dict) -> dict:
    """Content identity for a reference profile, separate from vendor .ft hashes."""
    content = {key: value for key, value in profile.items() if key not in ('id', 'sha256')}
    encoded = json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return content | {'id': digest[:16], 'sha256': digest}


def _isotonic(values, weights):
    """Pool adjacent decreasing blocks into a nondecreasing weighted sequence."""
    blocks = []
    for i, (value, weight) in enumerate(zip(values, weights)):
        blocks.append([i, i, float(value), float(weight)])
        while len(blocks) > 1 and blocks[-2][2] > blocks[-1][2]:
            right, left = blocks.pop(), blocks.pop()
            total = left[3] + right[3]
            blocks.append([left[0], right[1],
                           (left[2] * left[3] + right[2] * right[3]) / total, total])
    result = np.empty(len(values))
    for first, last, value, _ in blocks:
        result[first:last + 1] = value
    return result


def fit(source: np.ndarray, reference: np.ndarray, training: np.ndarray,
        *, min_samples: int = 12) -> tuple[np.ndarray, list[int]]:
    """Fit (4096, 3) LUT in 0..1 to binned medians of registered training pixels.

    Use separate spatial regions for evaluation. Only sampled RGB tone pairs are
    retained; the output transformation has no access to reference image texture.
    The first/last entries are fixed to black/white. Unsupported end ranges are
    interpolated and must not be described as measured calibration.
    """
    if source.shape != reference.shape or source.ndim != 3 or source.shape[-1] != 3:
        raise ValueError('Source and reference must be registered RGB images of equal dimensions')
    if training.shape != source.shape[:2] or min_samples < 1:
        raise ValueError('Training mask or sample count is invalid')
    valid = np.asarray(training, dtype=bool).copy()
    valid &= np.all(np.isfinite(source) & np.isfinite(reference) &
                    (source >= 0) & (source <= 1) & (reference >= 0) & (reference <= 1), axis=-1)
    tables, populated = [], []
    for channel in range(3):
        src, dst = source[..., channel][valid], reference[..., channel][valid]
        bins = np.floor(src * 255).astype(int)
        centers, medians, counts = [], [], []
        for index in range(256):
            selected = bins == index
            count = int(selected.sum())
            if count >= min_samples:
                center = float(np.median(src[selected]))
                if 0 < center < 1:
                    centers.append(center)
                    medians.append(float(np.median(dst[selected])))
                    counts.append(count)
        if len(centers) < 8 or centers[-1] - centers[0] < .1:
            raise ValueError('Training image has insufficient tone range for a reference profile')
        monotone = _isotonic(medians, counts)
        tables.append(np.interp(np.linspace(0, 1, 4096), [0, *centers, 1], [0, *monotone, 1]))
        populated.append(len(centers))
    return np.stack(tables, axis=-1), populated
