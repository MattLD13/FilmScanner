"""Find a 35 mm frame in overlapping scans and crop at its measured borders.

The AFL module clamps a single scan to 2586 x 1708 px at 1800 dpi (36.5 x 24.1 mm,
docs/scan08-feature-catalog.md), so frame edges may sit outside one scan. Several
scans taken with the film nudged between them are registered from their own image
content (the motor's nominal movement is only a starting guess), exposure-matched
and blended into one longer strip. The frame edges are then found where unexposed
film base (the gap between frames) meets the picture.

All functions work on float images in 0..1 (H x W x 3). Nothing here touches originals.
"""
from __future__ import annotations

import warnings

import numpy as np

MM_PER_INCH = 25.4
FRAME_MM = (36.0, 24.0)   # 135 film, full frame
LUMA = np.array([.2126, .7152, .0722])


def mm_to_px(mm: float, dpi: float) -> float:
    return mm / MM_PER_INCH * dpi


def rebate_witness(alignment: dict, width_px: int, dpi: float, minimum_mm: float = .15) -> dict:
    """Require both measured side borders and a small acquired film-base margin outside them.

    Missing edges are uncertain, not evidence that a nominal crop is complete.
    """
    edges = alignment.get('x', {})
    if edges.get('found') != 'both' or edges.get('start') is None or edges.get('end') is None:
        return {'verified': False, 'minimum_mm': minimum_mm, 'reason': 'Both side borders were not detected.'}
    left_mm = float(edges['start']) / dpi * MM_PER_INCH
    right_mm = (width_px - float(edges['end'])) / dpi * MM_PER_INCH
    verified = left_mm >= minimum_mm and right_mm >= minimum_mm
    return {'verified': verified, 'minimum_mm': minimum_mm,
            'left_margin_mm': round(left_mm, 4), 'right_margin_mm': round(right_mm, 4),
            'reason': None if verified else 'The acquired film-base margin is too narrow to verify full-frame coverage.'}


def base_likeness(samples: np.ndarray, transmission: bool) -> np.ndarray:
    """High where the film is bare base. Transmission: base is the brightest; a
    CyberView positive inverts it to the darkest."""
    luma = samples[..., :3] @ LUMA if samples.ndim == 3 else samples
    return luma if transmission else 1 - luma


# ---------- registration and stitching ----------

def _window(shape):
    return np.outer(np.hanning(shape[0]), np.hanning(shape[1]))


def phase_shift(reference: np.ndarray, moving: np.ndarray, guess: tuple[float, float] = (0, 0),
                radius: float | None = None) -> tuple[float, float, float]:
    """Translation (dy, dx) that maps ``moving`` onto ``reference``, with a peak strength.

    Searched within ``radius`` px of ``guess`` when given; sub-pixel by parabolic fit.
    """
    h, w = min(reference.shape[0], moving.shape[0]), min(reference.shape[1], moving.shape[1])
    a = reference[:h, :w] - reference[:h, :w].mean()
    b = moving[:h, :w] - moving[:h, :w].mean()
    win = _window((h, w))
    spectrum = np.fft.fft2(a * win) * np.conj(np.fft.fft2(b * win))
    spectrum /= np.abs(spectrum) + 1e-12
    corr = np.fft.ifft2(spectrum).real
    dys = np.fft.fftfreq(h, 1 / h)
    dxs = np.fft.fftfreq(w, 1 / w)
    if radius is not None:
        mask = (np.abs(dys[:, None] - guess[0]) <= radius) & (np.abs(dxs[None, :] - guess[1]) <= radius)
        corr = np.where(mask, corr, -np.inf)
    iy, ix = np.unravel_index(np.argmax(corr), corr.shape)
    peak = corr[iy, ix]

    def refine(values, i, n):
        l, c, r = values[(i - 1) % n], values[i], values[(i + 1) % n]
        if not np.isfinite(l) or not np.isfinite(r):
            return 0.0
        d = l - 2 * c + r
        return 0.0 if d == 0 else .5 * (l - r) / d

    dy = dys[iy] + refine(corr[:, ix], iy, h)
    dx = dxs[ix] + refine(corr[iy, :], ix, w)
    return float(dy), float(dx), float(peak)


MAX_FILLED_FRACTION = .0005


def stitch(scans: list[np.ndarray], nominal_dx: list[float], reference: int | None = None,
           search_px: float = 120, downsample: int = 4) -> dict:
    """Registers scans that overlap along x and blends them into one strip.

    ``nominal_dx`` is where each scan's left edge should sit relative to the reference
    scan, in pixels (from the commanded film movement). Real offsets are measured.
    """
    if len(scans) != len(nominal_dx) or not scans:
        raise ValueError('One nominal offset per scan is required')
    ref = len(scans) // 2 if reference is None else reference
    ref_img = scans[ref]

    def small(img):
        lum = img[..., :3] @ LUMA if img.ndim == 3 else img
        h, w = lum.shape[0] // downsample * downsample, lum.shape[1] // downsample * downsample
        return lum[:h, :w].reshape(h // downsample, downsample, w // downsample, downsample).mean(axis=(1, 3))

    ref_small = small(ref_img)
    offsets, strengths, gains = [], [], []
    for i, img in enumerate(scans):
        if i == ref:
            offsets.append((0.0, 0.0)); strengths.append(1.0); gains.append(np.ones(3)); continue
        # phase_shift's answer is the moving scan's position relative to the reference.
        guess = (0.0, (nominal_dx[i] - nominal_dx[ref]) / downsample)
        dy, dx, strength = phase_shift(ref_small, small(img), guess, search_px / downsample)
        # Refine at full resolution in a narrow window around the coarse answer.
        dy_f, dx_f, strength_f = phase_shift(ref_img[..., :3] @ LUMA, img[..., :3] @ LUMA,
                                             (dy * downsample, dx * downsample), downsample * 2)
        offsets.append((dy_f, dx_f)); strengths.append(strength_f)
        gains.append(None)
    # Canvas: each scan's top-left position relative to the reference scan.
    ys = [o[0] for o in offsets]; xs = [o[1] for o in offsets]
    h, w = ref_img.shape[:2]
    oy, ox = -min(ys), -min(xs)
    height = int(np.ceil(max(ys) - min(ys) + h)); width = int(np.ceil(max(xs) - min(xs) + w))
    channels = ref_img.shape[2] if ref_img.ndim == 3 else 1
    acc = np.zeros((height, width, channels)); weight = np.zeros((height, width, 1))

    # Feathered weights: strongest in each scan's middle, so seams fade.
    def feather(hh, ww):
        fy = np.minimum(np.arange(hh) + 1, hh - np.arange(hh))[:, None]
        fx = np.minimum(np.arange(ww) + 1, ww - np.arange(ww))[None, :]
        return np.minimum(fy, fx).astype(float)[..., None]

    placed = []
    for i, img in enumerate(scans):
        y0 = int(round(offsets[i][0] + oy)); x0 = int(round(offsets[i][1] + ox))
        im = img if img.ndim == 3 else img[..., None]
        placed.append((y0, x0, im))
    # Exposure matching: per-channel gain from the overlap with the reference (median ratio).
    ry, rx, rim = placed[ref]
    for i, (y0, x0, im) in enumerate(placed):
        if i == ref:
            continue
        yy0, yy1 = max(y0, ry), min(y0 + im.shape[0], ry + rim.shape[0])
        xx0, xx1 = max(x0, rx), min(x0 + im.shape[1], rx + rim.shape[1])
        if yy1 - yy0 < 16 or xx1 - xx0 < 16:
            gains[i] = np.ones(channels); continue
        a = rim[yy0 - ry:yy1 - ry, xx0 - rx:xx1 - rx].reshape(-1, channels)
        b = im[yy0 - y0:yy1 - y0, xx0 - x0:xx1 - x0].reshape(-1, channels)
        keep = (b.min(axis=1) > .02) & (b.max(axis=1) < .98) & (a.min(axis=1) > .02) & (a.max(axis=1) < .98)
        gains[i] = np.median(a[keep] / b[keep], axis=0) if keep.sum() > 100 else np.ones(channels)
        placed[i] = (y0, x0, np.clip(im * gains[i], 0, 1))
    for y0, x0, im in placed:
        f = feather(*im.shape[:2])
        acc[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] += im * f
        weight[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] += f
    covered = weight[..., 0] > 0
    mosaic = np.where(weight > 0, acc / np.maximum(weight, 1e-9), 0)
    # Ragged top and bottom edges (each scan sits a few px higher or lower) are filled from
    # the nearest acquired row of the same column; `covered` still records what was scanned.
    for x in np.where(~covered.all(axis=0))[0]:
        rows = np.where(covered[:, x])[0]
        if len(rows):
            mosaic[:rows[0], x] = mosaic[rows[0], x]
            mosaic[rows[-1] + 1:, x] = mosaic[rows[-1], x]
    if channels == 1:
        mosaic = mosaic[..., 0]
    return {'image': mosaic, 'covered': covered, 'reference': ref,
            'offsets_px': [{'dx': round(o[1], 2), 'dy': round(o[0], 2)} for o in offsets],
            'match_strength': [round(s, 4) for s in strengths],
            'gains': [[round(float(g), 4) for g in np.atleast_1d(gain)] for gain in gains]}


# ---------- frame edge detection ----------

def _smooth(values, size):
    if size <= 1:
        return values
    kernel = np.ones(size) / size
    pad = np.pad(values, size // 2, mode='edge')
    return np.convolve(pad, kernel, mode='valid')[:len(values)]


def _edges_along(base: np.ndarray, covered: np.ndarray, axis: int, expected_px: float, dpi: float):
    """Best (start, end) pair of frame edges along ``axis`` (1 = x, 0 = y).

    Profile = median over the central 70 % of the other axis. A frame start is a
    drop from base-like gap to picture; an end is the reverse. Pairs are scored
    by edge contrast and by how close their spacing is to the expected frame size.
    """
    other = base.shape[1 - axis]
    lo, hi = int(other * .15), int(other * .85)
    band = base[lo:hi, :] if axis == 1 else base[:, lo:hi].T
    cov = covered[lo:hi, :] if axis == 1 else covered[:, lo:hi].T
    masked = np.where(cov, band, np.nan)
    with warnings.catch_warnings():  # columns outside every stitched scan are all-NaN by design
        warnings.simplefilter('ignore', RuntimeWarning)
        profile = np.nanmedian(masked, axis=0)
        spread = np.nanpercentile(masked, 90, axis=0) - np.nanpercentile(masked, 10, axis=0)
    valid = np.isfinite(profile)
    profile = np.where(valid, profile, np.nanmedian(profile))
    spread = np.where(valid, spread, 1.0)
    n = len(profile)
    k = max(3, int(mm_to_px(.35, dpi)))          # compare 0.35 mm either side of a candidate
    sm = _smooth(profile, max(1, k // 3))
    cs = np.concatenate([[0], np.cumsum(sm)])
    left_mean = np.full(n, np.nan); right_mean = np.full(n, np.nan)
    idx = np.arange(k, n - k)
    left_mean[idx] = (cs[idx] - cs[idx - k]) / k
    right_mean[idx] = (cs[idx + k] - cs[idx]) / k
    # Bare base is bright in base_likeness and uniform across the frame height.
    base_level = np.nanpercentile(profile, 98)
    picture_level = np.nanpercentile(profile, 40)
    contrast = max(base_level - picture_level, 1e-6)
    flat = _smooth(spread, k)
    start = (left_mean - right_mean) / contrast        # gap on the left, picture on the right
    end = (right_mean - left_mean) / contrast
    # Gaps between frames are bare base: near the base level AND uniform down the frame
    # (no picture texture). The frame is the picture around the scan's middle: it starts
    # where the nearest gap on its left ends and ends where the nearest gap on its right
    # begins. A sliver of a neighbouring frame beyond a gap is ignored (observed on real
    # CyberView scans, 2026-10-30).
    if contrast < .08:
        return {'found': 'none'}
    bright = (profile > base_level - .3 * contrast) & valid
    gap = bright & (spread < .1)
    min_run = max(2, int(mm_to_px(.25, dpi)))
    # Film-base spread can fluctuate around .1 from grain/calibration noise.
    # A strict pointwise threshold fragmented a physically present ~.3 mm
    # rebate on the last frame of the real strip. Use bounded hysteresis:
    # a connected bright region may grow through spread<.12 only when at
    # least half its pixels (and at least two) already meet the strict test.
    # Never bridge a dark picture pixel or accept a weak-only uniformity run.
    soft = bright & (spread < .12)
    i=0
    while i<n:
        if soft[i]:
            j=i
            while j<n and soft[j]:j+=1
            strong=int(np.count_nonzero(gap[i:j]))
            if j-i>=min_run and strong>=max(2,int(np.ceil((j-i)/2))):
                gap[i:j]=True
            i=j
        else:
            i+=1
    runs, i = [], 0
    while i < n:
        if gap[i]:
            j = i
            while j < n and gap[j]:
                j += 1
            if j - i >= min_run:
                runs.append((i, j))          # gap occupies [i, j)
            i = j
        else:
            i += 1
    middle = n / 2

    def refine(pos, score):
        lo, hi = max(k, pos - k), min(n - k, pos + k)
        if hi <= lo:
            return pos, 0.0
        window = np.nan_to_num(score[lo:hi])
        best = lo + int(np.argmax(window))
        return best, float(np.nan_to_num(score[best]))

    # A wide strip can have a gap at its centre. Find complete frames between
    # neighbouring gaps before assuming that the centre itself is picture area.
    # Always return measured positions; never resize the image to fit the model.
    # Nominal 36 x 24 mm is a prior, not a reason to throw away two clear
    # borders. The real low-resolution AFL preview measured ~37.1 mm between
    # side borders at its declared DPI (2026-10-31); .9 mm rejected that pair.
    tol = max(expected_px * .10, mm_to_px(.9, dpi), 4)
    pairs = []
    for before, after in zip(runs, runs[1:]):
        s, ss = refine(before[1], start)
        e, es = refine(after[0], end)
        if ss > .05 and es > .05 and abs((e - s) - expected_px) <= tol:
            pairs.append((s, e, ss + es))
    if pairs:
        s, e, strength = min(pairs, key=lambda pair: abs((pair[0] + pair[1]) / 2 - middle))
        return {'start': s, 'end': e, 'found': 'both', 'strength': round(strength, 3),
                'measured_mm': round((e - s) / dpi * MM_PER_INCH, 3),
                'frames': [{'start': left, 'end': right, 'strength': round(score, 3),
                            'measured_mm': round((right - left) / dpi * MM_PER_INCH, 3)}
                           for left, right, score in pairs]}

    left = [r for r in runs if (r[0] + r[1]) / 2 < middle and r[1] < n]   # a gap reaching the far edge still counts
    right = [r for r in runs if (r[0] + r[1]) / 2 >= middle and r[0] > 0]
    edges = {}
    if left:
        gap_run = max(left, key=lambda r: r[1])          # the gap closest to the middle
        pos, strength = refine(gap_run[1], start)
        edges['start'] = (pos, strength, gap_run)
    if right:
        gap_run = min(right, key=lambda r: r[0])
        pos, strength = refine(gap_run[0], end)
        edges['end'] = (pos, strength, gap_run)
    if 'start' in edges and 'end' in edges:
        s, e = edges['start'][0], edges['end'][0]
        if abs((e - s) - expected_px) <= tol:
            return {'start': s, 'end': e, 'found': 'both', 'strength': round(edges['start'][1] + edges['end'][1], 3),
                    'measured_mm': round((e - s) / dpi * MM_PER_INCH, 3)}
        # Spacing is wrong for a full frame: keep the edge with the clearer gap.
        keep = max(('start', 'end'), key=lambda key: edges[key][2][1] - edges[key][2][0])
        edges = {keep: edges[keep]}
    if edges:
        kind, (pos, strength, run) = next(iter(edges.items()))
        return {kind: pos, 'found': kind, 'strength': round(strength, 3),
                'gap_mm': round((run[1] - run[0]) / dpi * MM_PER_INCH, 3)}
    return {'found': 'none'}


def _skew(base, covered, start, end, dpi, bands=8):
    """Degrees of rotation from the frame edge's x position in horizontal bands."""
    h = base.shape[0]
    xs, ys = [], []
    k = max(3, int(mm_to_px(.35, dpi)))
    for edge, sign in ((start, 1), (end, -1)):
        if edge is None:
            continue
        lo, hi = max(edge - 3 * k, k), min(edge + 3 * k, base.shape[1] - k)
        if hi - lo < 2 * k:
            continue
        for b in range(bands):
            r0, r1 = int(h * (.1 + .8 * b / bands)), int(h * (.1 + .8 * (b + 1) / bands))
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                prof = np.nanmedian(np.where(covered[r0:r1, lo - k:hi + k], base[r0:r1, lo - k:hi + k], np.nan), axis=0)
            valid = np.isfinite(prof[:-k]) & np.isfinite(prof[k:])
            if not valid.any():
                continue
            grad = np.where(valid, sign * (prof[:-k] - prof[k:]), -np.inf)
            xs.append(lo - k + int(np.argmax(grad)) + k / 2); ys.append((r0 + r1) / 2)
    if len(xs) < 4:
        return None
    slope = np.polyfit(ys, xs, 1)[0]
    return float(np.degrees(np.arctan(slope)))


def align_35mm(samples: np.ndarray, dpi: float, transmission: bool, bleed_mm: float = 0.0,
               covered: np.ndarray | None = None, frame_mm: tuple[float, float] = FRAME_MM) -> dict:
    """Use measured border spacing where both edges are visible, otherwise nominal size."""
    if not -2 <= bleed_mm <= 2:
        raise ValueError('Bleed must be between -2 and 2 mm')
    base = base_likeness(samples, transmission)
    covered = np.ones(base.shape, bool) if covered is None else np.asarray(covered, dtype=bool)
    if covered.shape != base.shape:
        raise ValueError('Coverage must match the image dimensions')
    h, w = base.shape
    want_w, want_h = mm_to_px(frame_mm[0], dpi), mm_to_px(frame_mm[1], dpi)
    result = {'dpi': dpi, 'frame_mm': list(frame_mm), 'bleed_mm': bleed_mm, 'image_px': [w, h],
              'image_mm': [round(w / dpi * MM_PER_INCH, 3), round(h / dpi * MM_PER_INCH, 3)]}
    centers, spans = [], []
    for axis, size, want in ((1, w, want_w), (0, h, want_h)):
        edges = _edges_along(base, covered, axis, want, dpi)
        if edges['found'] == 'both':
            center = (edges['start'] + edges['end']) / 2
        elif edges['found'] == 'start':
            center = edges['start'] + want / 2
        elif edges['found'] == 'end':
            center = edges['end'] - want / 2
        else:
            ys_or_xs = np.where(covered.any(axis=1 - axis))[0]
            center = (ys_or_xs[0] + ys_or_xs[-1]) / 2 if len(ys_or_xs) else size / 2
        result['x' if axis == 1 else 'y'] = edges
        centers.append(center)
        spans.append(edges['end'] - edges['start'] if edges['found'] == 'both' else want)
    crop_w, crop_h = [round(span + 2 * mm_to_px(bleed_mm, dpi)) for span in spans]
    result['crop_basis'] = {axis: 'detected_borders' if result[axis]['found'] == 'both' else 'nominal'
                            for axis in ('x', 'y')}
    result['requested_crop_mm'] = [round(size / dpi * MM_PER_INCH, 3) for size in (crop_w, crop_h)]
    cx, cy = centers
    x0 = int(round(cx - crop_w / 2)); y0 = int(round(cy - crop_h / 2))
    clamped = x0 < 0 or y0 < 0 or x0 + crop_w > w or y0 + crop_h > h
    x0 = min(max(x0, 0), max(w - crop_w, 0)); y0 = min(max(y0, 0), max(h - crop_h, 0))
    cw, ch = min(crop_w, w), min(crop_h, h)
    if np.count_nonzero(~covered[y0:y0 + ch, x0:x0 + cw]):
        # Stitched mosaics have ragged corners (each scan sits a few px higher or lower).
        # Never shift measured borders onto picture content to hide missing coverage.
        reach = int(round(mm_to_px(.2, dpi)))
        ys = (0,) if result['y']['found'] == 'both' else range(-reach, reach + 1)
        xs = (0,) if result['x']['found'] == 'both' else range(-reach, reach + 1)
        moves = sorted(((dy, dx) for dy in ys for dx in xs
                        if 0 <= y0 + dy <= h - ch and 0 <= x0 + dx <= w - cw), key=lambda m: (abs(m[1]), abs(m[0])))
        for dy, dx in moves:
            if covered[y0 + dy:y0 + dy + ch, x0 + dx:x0 + dx + cw].all():
                y0, x0 = y0 + dy, x0 + dx
                break
    missing_pixels = int(np.count_nonzero(~covered[y0:y0 + ch, x0:x0 + cw]))
    edge_filled = 0
    if missing_pixels:
        rows = np.arange(h)[:, None]
        first = np.where(covered.any(axis=0), covered.argmax(axis=0), h)
        last = np.where(covered.any(axis=0), h - 1 - covered[::-1].argmax(axis=0), -1)
        outside = (rows < first[None, :]) | (rows > last[None, :])
        edge_filled = int(np.count_nonzero((~covered & outside & (last[None, :] >= 0))[y0:y0 + ch, x0:x0 + cw]))
    coverage_fraction = 1 - missing_pixels / (cw * ch)
    dimensions_exact = not clamped and cw == crop_w and ch == crop_h
    found = (result['x']['found'], result['y']['found'])
    confidence = 'frame_found' if found[0] == 'both' else 'one_edge' if found[0] in ('start', 'end') else 'centered'
    result.update(
        crop_px={'left': x0, 'top': y0, 'width': cw, 'height': ch},
        crop={'left': x0 / w, 'top': y0 / h, 'right': (x0 + cw) / w, 'bottom': (y0 + ch) / h},
        crop_mm=[round(cw / dpi * MM_PER_INCH, 3), round(ch / dpi * MM_PER_INCH, 3)],
        dimensions_exact=dimensions_exact,
        missing_pixels=missing_pixels,
        coverage_fraction=coverage_fraction,
        # A stitched crop may include a few ragged-edge pixels that stitch() fills from the
        # nearest scanned row (at most 0.05 %); any hole inside the scanned area blocks it.
        exact=dimensions_exact and missing_pixels == edge_filled and edge_filled <= MAX_FILLED_FRACTION * cw * ch,
        filled_pixels=edge_filled,
        confidence=confidence,
        skew_deg=_skew(base, covered, result['x'].get('start'), result['x'].get('end'), dpi) if found[0] != 'none' else None)
    if missing_pixels and result['exact']:
        result['note'] = (f'{missing_pixels} corner pixels ({1 - coverage_fraction:.4%}) lie just outside the '
                          'scans and are filled from the nearest scanned row.')
    elif missing_pixels:
        result['note'] = (f'The requested crop contains {missing_pixels} unacquired pixels '
                          f'({coverage_fraction:.6%} coverage); the crop was not applied. '
                          'Adjust the crop or acquire more coverage.')
    elif crop_w > w or crop_h > h:
        result['note'] = (f"The scan is {result['image_mm'][0]} x {result['image_mm'][1]} mm, smaller than the "
                          f"{result['requested_crop_mm'][0]:g} x {result['requested_crop_mm'][1]:g} mm crop; scan the full window or stitch.")
    elif not result['exact']:
        result['note'] = ('The detected frame extends beyond the scanned area; automatic cropping was not applied. '
                          'Adjust the crop or acquire wider coverage.')
    elif confidence == 'centered':
        result['note'] = 'No frame edge was visible; the crop is centred on the scan.'
    elif confidence == 'frame_found' and result['y']['found'] != 'both':
        result['note'] = 'Both side borders were found; the crop height uses the nominal frame size because vertical borders are missing.'
    return result
