"""Final negative-scan Auto Gamma recovered from CyberView's CPU image workers.

This is distinct from iComputeAutoColor's prescan/curve-maker 18-word result.
The final scan estimates a histogram correction before the film term and applies
the composed LUT after that film term. Saved tables make the edit reproducible.
"""
from __future__ import annotations

import numpy as np

from services.imaging import vendor_filmterm

VERSION = 'cyberview-final-negative-gamma-1'


def region(shape) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    if h < 1 or w < 1:
        raise ValueError('Auto Gamma requires a nonempty image')
    # Inclusive bounds in the original C++ loops, not Python's usual half-open ROI.
    return (w * 10 // 100, h * 10 // 100, w * 90 // 100, h * 92 // 100)


def linear_curve(low_x: int, high_x: int, low_y: int = 0, high_y: int = 255) -> np.ndarray:
    """0x100069f0, three integer segments through four unsigned WORD parameters."""
    if not (0 <= low_x <= high_x <= 255 and 0 <= low_y <= high_y <= 255):
        raise ValueError('Invalid levels curve')
    x = np.arange(256, dtype=np.int64)
    out = np.empty(256, dtype=np.int64)
    lo, mid, hi = x <= low_x, (x > low_x) & (x <= high_x), x > high_x
    out[lo] = low_y * x[lo] // low_x if low_x else low_y
    if mid.any():
        out[mid] = (high_y - low_y) * (x[mid] - low_x) // (high_x - low_x) + low_y
    if hi.any():
        out[hi] = (255 - high_y) * (x[hi] - high_x) // (255 - high_x) + high_y
    return out.astype(np.uint16)


def apply8(image: np.ndarray, tables: np.ndarray) -> np.ndarray:
    return tables[np.arange(3), image].astype(np.uint8)


def compose(existing: np.ndarray, following: np.ndarray) -> np.ndarray:
    return following[np.arange(3)[:, None], existing]


def _levels(image: np.ndarray, roi, white: bool = False) -> np.ndarray:
    left, top, right, bottom = roi
    pixels = image[top:bottom + 1, left:right + 1].reshape(-1, 3)
    threshold = len(pixels) // 1000
    tables = []
    for c in range(3):
        histogram = np.bincount(pixels[:, c], minlength=256)
        if white:
            cumulative = np.cumsum(histogram[::-1])
            # The white pass stops at 128 even if the threshold was never met.
            matches = np.flatnonzero(cumulative[:128] >= threshold)
            cut = 255 - int(matches[0]) if len(matches) else 128
            tables.append(linear_curve(0, cut))
        else:
            matches = np.flatnonzero(np.cumsum(histogram) >= threshold)
            cut = int(matches[0]) if len(matches) else 0
            tables.append(linear_curve(cut, 255))
    return np.stack(tables)


def prepare8(image: np.ndarray) -> np.ndarray:
    """10103810's bounded integer box reduction and uint16→uint8 conversion."""
    if image.ndim != 3 or image.shape[-1] != 3 or image.dtype not in (np.uint8, np.uint16):
        raise ValueError('Final Auto Gamma requires unsigned RGB8 or RGB16')
    h, w = image.shape[:2]
    region(image.shape)
    factor = 1
    if max(h, w) > 222:
        ratio = float(np.float32(max(h, w) / 222))
        integer = int(ratio)
        factor = integer + int(ratio - integer > .5)  # exact halves round down
    if h // factor < 1 or w // factor < 1:
        raise ValueError('Auto Gamma reduction would produce an empty image')
    if factor > 1:
        out_h, out_w = h // factor, w // factor
        blocks = image[:out_h * factor, :out_w * factor].reshape(out_h, factor, out_w, factor, 3)
        reduced = blocks.sum(axis=(1, 3), dtype=np.uint64) // factor // factor
    else:
        reduced = image
    if image.dtype == np.uint16:
        reduced = reduced >> 8
    return reduced.astype(np.uint8)


def compute(image: np.ndarray) -> np.ndarray:
    """Negative-flag1 tables, matching 10103810 for the supplied image buffer."""
    from services.imaging.gamma_balance import estimate_balance
    small = prepare8(image)
    roi = region(small.shape)
    tables = _levels(small, roi)
    work = apply8(small, tables)
    for _ in range(2):
        correction = estimate_balance(work, roi)
        tables = compose(tables, correction)
        work = apply8(work, correction)
    return compose(tables, _levels(work, roi, white=True))


def scan_thumbnail(image: np.ndarray, dpi: int = 1800) -> np.ndarray:
    """1017e520/1017e360's 600dpi striped sampler, including its channel-row quirk.

    Only reproduce bounded accesses. The original worker does not correctly bound
    all unsupported geometry; raising is preferable to fabricating its heap reads.
    """
    if image.dtype != np.uint16 or image.ndim != 3 or image.shape[-1] != 3 or dpi < 600:
        raise ValueError('Exact scan thumbnail requires RGB16 at 600 dpi or above')
    height, width = image.shape[:2]
    out_w = int(600 * float(np.float32(width / dpi)))
    if out_w < 1:
        raise ValueError('Exact scan thumbnail width is empty')
    xs = np.floor(np.arange(out_w) * float(np.float32(width / out_w))).astype(int)
    stripes = []
    for top in range(0, height, 255):
        stripe = image[top:top + 255]
        out_h = int(600 * float(np.float32(len(stripe) / dpi)))
        if out_h < 1:
            raise ValueError('Exact scan thumbnail has an incomplete final stripe')
        ys = np.floor(np.arange(out_h) * float(np.float32(len(stripe) / out_h))).astype(int)
        if ys[-1] + 2 >= len(stripe) or xs[-1] >= width:
            raise ValueError('Exact vendor thumbnail would read outside its source stripe')
        stripes.append(np.stack([stripe[(ys + c)[:, None], xs[None, :], c] for c in range(3)], axis=-1))
    return np.concatenate(stripes)


def apply16(image: np.ndarray, tables: np.ndarray) -> np.ndarray:
    """CFilmCIP mode7: 256-entry WORD LUT expanded to uint16; no colour matrix."""
    table = np.asarray(tables)
    if table.shape != (3, 256) or not np.isfinite(table).all() or np.any(table < 0) or np.any(table > 255):
        raise ValueError('Final Auto Gamma tables must be 3 × 256 values in 0–255')
    return vendor_filmterm.apply16(image, {'lut': table.T.tolist(), 'matrix': [[1,0,0,0],[0,1,0,0],[0,0,1,0]]})
