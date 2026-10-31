"""Automatic colour as CyberView X computes it, ported from CyberViewX.ds 1.4.0.0.

`compute(rgb8)` reproduces the DS's exported ``iComputeAutoColor`` (0x10122ba0) as
CyberView calls it on its prescan: preset 2, clip 0.05 % at both ends. It returns
the same 18 words, laid out ``[6][3]`` (rows x R, G, B):

    0 white in   1 white out   2 midtone in   3 midtone out   4 black in   5 black out

`curves(words)` gives the control points CyberView's curve builder (0x10111be0) makes
from them, including its quirk of always using 0 for green's black-point input.

The port keeps the DS's arithmetic: values the DS stores as float32 are rounded to
float32 here, and every float-to-int conversion truncates (MSVC ``__ftol``). It is
checked word for word against the DS itself by tests/imaging/test_autocolor.py
(which runs services/cyberview_bridge/bin/autocolor.exe when CyberView is installed).
See docs/auto-color-re.md.
"""
from __future__ import annotations

import numpy as np

LEVELS = 256
NO_NEUTRAL_MIDTONES = 0x517  # the DS's code when no pixel qualifies for the midtone balance

f32 = np.float32
# Stack slots -0xc0 ... -0xe4 of iComputeAutoColor, as float32 like the DS.
PRESETS = {
    1: dict(p0=.20, p1=.30, p2=.40, p3=45, p4=75, p5=.10, p6=.25, p7=.05, p8=.01, p9=.01),
    2: dict(p0=.35, p1=.55, p2=.70, p3=35, p4=65, p5=0., p6=.75, p7=.15, p8=.01, p9=.02),
    3: dict(p0=.25, p1=.45, p2=.55, p3=55, p4=65, p5=.10, p6=.35, p7=.35, p8=.02, p9=.04),
}


def _trunc(x):
    return np.trunc(x).astype(np.int64)


def _hsv(rgb: np.ndarray):
    """0x101254f0: hue in degrees, saturation and value, each stored as float32."""
    r, g, b = (rgb[..., c].astype(np.float64) for c in range(3))
    h = np.zeros(r.shape); s = np.zeros(r.shape); v = np.zeros(r.shape)
    red = (r >= g) & (r >= b)
    blue = ~red & (b >= r) & (b >= g)
    green = ~red & ~blue
    with np.errstate(divide='ignore', invalid='ignore'):
        lo = np.minimum(g, b)
        flat = red & (r == lo)
        hr = f32((g - b) / (r - lo) * 60.0).astype(np.float64)
        hr = np.where(hr < 0, f32(hr + 360.0).astype(np.float64), hr)
        h = np.where(red & ~flat, hr, h)
        s = np.where(red & ~flat, f32((r - lo) / r), s)
        v = np.where(red, f32(r / 255.0), v)
        lo = np.minimum(g, r)
        hb = f32(((r - g) / (b - lo) + 4.0) * 60.0).astype(np.float64)
        hb = np.where(hb < 0, f32(hb + 360.0).astype(np.float64), hb)
        h = np.where(blue, hb, h)
        s = np.where(blue, f32((b - lo) / b), s)
        v = np.where(blue, f32(b / 255.0), v)
        lo = np.minimum(b, r)
        h = np.where(green, f32(((b - r) / (g - lo) + 2.0) * 60.0), h)
        s = np.where(green, f32((g - lo) / g), s)
        v = np.where(green, f32(g / 255.0), v)
    return f32(h).astype(np.float64), f32(s).astype(np.float64), f32(v).astype(np.float64)


def _clip_count(n: int, fraction: float) -> int:
    count = int(np.trunc(n * float(f32(fraction)) / 100.0))
    return count or 1


def compute(rgb8: np.ndarray, preset: int = 2, clip_low: float = .05, clip_high: float = .05) -> tuple[int, list[int]]:
    """Returns (code, words); code 0 on success, as the DS returns it."""
    if rgb8.dtype != np.uint8 or rgb8.ndim != 3 or rgb8.shape[2] != 3:
        raise ValueError('expects an 8-bit RGB image')
    p = {k: float(f32(v)) for k, v in PRESETS[preset].items()}
    pixels = rgb8.reshape(-1, 3)
    n = len(pixels)
    out = np.zeros((6, 3), dtype=np.int64)

    hue, sat, val = _hsv(pixels)
    v16 = _trunc((LEVELS - 1) * val)
    s16 = _trunc((LEVELS - 1) * sat)
    h16 = _trunc(hue)
    hist_v = np.bincount(v16, minlength=LEVELS)

    # Darkest and brightest value levels holding at least clip pixels (single bins).
    clip = _clip_count(n, clip_low)
    low = next((i for i in range(LEVELS) if hist_v[i] >= clip), LEVELS)
    clip = _clip_count(n, clip_high)
    high = next((i for i in range(LEVELS - 1, -1, -1) if hist_v[i] >= clip), -1) & 0xFFFF
    mid = (low + int((high - low) / 2)) & 0xFFFF

    hist = [np.bincount(pixels[:, c], minlength=LEVELS) for c in range(3)]
    cap = int(np.trunc(LEVELS * p['p6']))
    limit = int(np.trunc(LEVELS * p['p7']))
    clip = _clip_count(n, clip_low)
    for c in range(3):                       # black point: first single bin with clip pixels
        i = next((i for i in range(LEVELS) if hist[c][i] >= clip), None)
        if i is not None:
            out[4, c] = min(int(np.trunc(i * (1.0 - p['p8']))), cap)
            out[5, c] = 0
    clip = _clip_count(n, clip_low)          # the DS uses the low clip for whites too
    for c in range(3):                       # white point: cumulative from the top
        total = 0
        for i in range(LEVELS - 1, -1, -1):
            total += hist[c][i]
            if total >= clip:
                white = min(int(np.trunc(i * (1.0 + p['p9']))), LEVELS - 1)
                out[0, c] = max(white, LEVELS - cap)
                out[1, c] = LEVELS - 1
                break

    # Midtone balance: mean RGB of pixels at the middle value level that are nearly
    # neutral, or (for hues p3..p4, moderately saturated) skin-like.
    sat_lo, sat_hi, sat_neutral = (int(np.trunc(LEVELS * p[k])) for k in ('p1', 'p2', 'p0'))
    at_mid = v16 == mid
    skin = (h16 > p['p3']) & (h16 < p['p4']) & (s16 > sat_lo) & (s16 < sat_hi)
    chosen = at_mid & (s16 < np.where(skin, sat_hi, sat_neutral))
    count = int(chosen.sum())
    if not count:
        identity = np.array([[LEVELS - 1] * 3, [LEVELS - 1] * 3, [LEVELS // 2] * 3, [LEVELS // 2] * 3, [0] * 3, [0] * 3])
        return NO_NEUTRAL_MIDTONES, identity.reshape(-1).tolist()
    sums = pixels[chosen].astype(np.int64).sum(axis=0)
    for c in range(3):
        out[2, c] = sums[c] // count
        out[3, c] = LEVELS // 2
        lim = int(limit / 2) if (c == 2 and preset == 1) else limit
        centre = (out[4, c] + int((out[0, c] - out[4, c]) / 2)) & 0xFFFF
        if abs(int(out[2, c]) - centre) >= lim:
            out[2, c] = centre + lim if out[2, c] > centre else centre - lim
        if c == 1:
            out[2, c] += int(np.trunc(abs(int(out[3, c]) - centre) * p['p5'])) & 0xFFFF
        elif c == 2:
            out[2, c] += int(np.trunc(abs(int(out[3, c]) - centre) * (2.0 * p['p5']))) & 0xFFFF
        out[2, c] &= 0xFFFF
    return 0, out.reshape(-1).tolist()


def curves(words: list[int]) -> dict[str, list[tuple[int, int]]]:
    """Control points of CyberView's four curves (0x10111be0), as (input, output)."""
    w = np.asarray(words).reshape(6, 3)
    points = {'master': [(155, 130)]}
    for c, name in enumerate('rgb'):
        black_in = 0 if c == 1 else int(w[4, c])  # DS bug: green's black input is overwritten
        points[name] = [(int(w[0, c]), int(w[1, c])), (int(w[2, c]), int(w[3, c])), (black_in, int(w[5, c]))]
    return points
