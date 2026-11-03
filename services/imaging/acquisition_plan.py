"""Optically measured one/two-tile plans and constrained archival stitching.

No motor pitch is used here. Positions come from registered 300 dpi acquisitions;
step counts merely identify how to revisit those measured positions. High-resolution
tiles remain the caller's immutable originals, including when registration fails.
"""
from __future__ import annotations

from itertools import combinations
import math

import numpy as np

from services.imaging import frame_align


FULL_WINDOW_1800 = (2585, 1708)
FULL_WINDOW_300 = (430, 284)
SCALE_X = FULL_WINDOW_1800[0] / FULL_WINDOW_300[0]
SCALE_Y = FULL_WINDOW_1800[1] / FULL_WINDOW_300[1]
CROSS_RESOLUTION_PAD_PX = {'x': 18.0, 'y': 18.0}
REBATE_MM = .15
MIN_OVERLAP_MM = 5.0
CORRELATION_FLOOR = .05
PEAK_RATIO_MINIMUM = 1.4
TEXTURE_STD_MINIMUM = .01


def preview_padding(dpi: float = 300) -> dict:
    """Rebate plus provisional per-axis uncertainty, expressed on preview grid."""
    rebate = frame_align.mm_to_px(REBATE_MM, dpi)
    return {'x': rebate + CROSS_RESOLUTION_PAD_PX['x'] / SCALE_X * dpi / 300,
            'y': rebate + CROSS_RESOLUTION_PAD_PX['y'] / SCALE_Y * dpi / 300}


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'UNVERIFIED_PREVIEW_COVERAGE: invalid {name}')
    return number


def plan_archival(preview_record: dict) -> dict:
    """Select measured source windows containing the padded horizontal frame.

    The preview mosaic may contain more windows than archival acquisition needs.
    Every selected position must already have been acquired in that local search.
    Vertical containment is independent evidence: longitudinal film motion cannot
    make the physical aperture taller. Unknown vertical borders stay unknown.
    """
    dpi = _finite(preview_record.get('dpi', 300), 'DPI')
    if dpi <= 0:
        raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: DPI must be positive')
    alignment = preview_record.get('alignment') or {}
    edges = alignment.get('edges_x', alignment.get('x', {}))
    if edges.get('found') != 'both' or edges.get('start') is None or edges.get('end') is None:
        raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: both measured side borders are required')
    derived = preview_record.get('derived') or {}
    sources, offsets = derived.get('sources') or [], derived.get('offsets_px') or []
    if not sources or len(sources) != len(offsets):
        raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: source windows and offsets do not match')
    padding = preview_padding(dpi)
    x0 = _finite(edges['start'], 'left border') - padding['x']
    x1 = _finite(edges['end'], 'right border') + padding['x']
    if x1 <= x0:
        raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: frame borders are reversed')
    origin_x = -min(_finite(offset['dx'], 'source dx') for offset in offsets)
    origin_y = -min(_finite(offset.get('dy', 0), 'source dy') for offset in offsets)
    tiles = []
    for index, (source, offset) in enumerate(zip(sources, offsets)):
        step = _finite(source.get('position_steps', 0), 'source step position')
        if step != int(step):
            raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: source steps are not integral')
        tile = {'source_index': index, 'label': source.get('label', f'tile-{index + 1}'),
                'position_steps': int(step), 'dx': _finite(offset['dx'], 'source dx'),
                'dy': _finite(offset.get('dy', 0), 'source dy'),
                'width': int(source['width']), 'height': int(source['height']),
                'dpi': _finite(source.get('dpi', dpi), 'source DPI')}
        if tile['width'] <= 0 or tile['height'] <= 0 or tile['dpi'] != dpi:
            raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: inconsistent source geometry')
        tiles.append(tile)

    minimum_overlap = frame_align.mm_to_px(MIN_OVERLAP_MM, dpi)

    def bounds(tile):
        left = tile['dx'] + origin_x
        return left, left + tile['width']

    def covers(selected):
        windows = sorted(bounds(tile) for tile in selected)
        if windows[0][0] > x0 or max(right for _, right in windows) < x1:
            return False
        if len(windows) == 2:
            overlap = min(windows[0][1], windows[1][1]) - windows[1][0]
            if overlap < minimum_overlap:
                return False
            vertical_overlap = min(tile['dy'] + tile['height'] for tile in selected) - max(tile['dy'] for tile in selected)
            if vertical_overlap < max(16, frame_align.mm_to_px(10, dpi)):
                return False
        return True

    candidates = [list(items) for count in (1, 2) for items in combinations(tiles, count) if covers(items)]
    if not candidates:
        raise ValueError('UNVERIFIED_PREVIEW_COVERAGE: no one/two measured windows contain both padded rebates with sufficient overlap')
    final_steps = int(derived.get('final_position_steps', 0))
    selected = min(candidates, key=lambda items: (len(items),
                   max(tile['position_steps'] for tile in items) - min(tile['position_steps'] for tile in items),
                   min(abs(tile['position_steps'] - final_steps) for tile in items)))
    selected.sort(key=lambda tile: tile['dx'])
    y_edges = alignment.get('edges_y', alignment.get('y', {}))
    required = {'left': float(x0), 'right': float(x1)}
    vertical = {'status': 'unknown', 'reason': 'Both vertical film borders were not observed; longitudinal nudges cannot prove vertical containment.'}
    if y_edges.get('found') == 'both' and y_edges.get('start') is not None and y_edges.get('end') is not None:
        top = _finite(y_edges['start'], 'top border') - padding['y']
        bottom = _finite(y_edges['end'], 'bottom border') + padding['y']
        required.update(top=top, bottom=bottom)
        fits = all(tile['dy'] + origin_y <= top and tile['dy'] + origin_y + tile['height'] >= bottom for tile in selected)
        vertical = {'status': 'verified' if fits else 'unverified',
                    'reason': None if fits else 'Selected windows do not contain both padded vertical borders; the aperture cannot be enlarged by longitudinal motion.'}
    return {'version': 1, 'preview_capture_id': preview_record.get('id'), 'tiles': selected,
            'padding_highres_px': dict(CROSS_RESOLUTION_PAD_PX), 'padding_preview_px': padding,
            'required_bounds_preview_px': required, 'scale_1800': {'x': SCALE_X, 'y': SCALE_Y},
            'vertical_containment': vertical, 'minimum_overlap_preview_px': minimum_overlap,
            'registration': {'correlation_floor': CORRELATION_FLOOR, 'peak_ratio_minimum': PEAK_RATIO_MINIMUM,
                             'uncertainty_highres_px': dict(CROSS_RESOLUTION_PAD_PX)},
            'basis': 'locally_registered_preview_windows_not_nominal_motor_pitch'}


def _failure(reason):
    raise ValueError(f'UNVERIFIED_STITCH_ALIGNMENT: {reason}')


def _register(reference, moving, expected, radius, *, dpi=1800):
    """Measure residual displacement only inside predicted acquired overlap."""
    dy0, dx0 = (int(round(value)) for value in expected)
    rh, rw = reference.shape[:2]
    mh, mw = moving.shape[:2]
    y0, y1 = max(0, dy0), min(rh, dy0 + mh)
    x0, x1 = max(0, dx0), min(rw, dx0 + mw)
    min_width = max(32, int(frame_align.mm_to_px(MIN_OVERLAP_MM, dpi)))
    if x1 - x0 < min_width or y1 - y0 < 64:
        _failure('predicted overlap is too small')
    a = reference[y0:y1, x0:x1, :3] @ frame_align.LUMA
    b = moving[y0 - dy0:y1 - dy0, x0 - dx0:x1 - dx0, :3] @ frame_align.LUMA
    if min(float(a.std()), float(b.std())) < TEXTURE_STD_MINIMUM:
        _failure('overlap has insufficient scene texture')
    # Windowing can give periodic sensor/scene patterns one artificial dominant
    # phase peak. Check repeatability of acquired content itself as well as the
    # primary/secondary FFT peaks below. Sampling controls cost on 4 MP tiles.
    self_similarity = 0.
    for axis, limit in ((0, radius['y']), (1, radius['x'])):
        for shift in range(4, int(limit) + 1):
            first = a[:-shift:4, ::4] if axis == 0 else a[::4, :-shift:4]
            second = a[shift::4, ::4] if axis == 0 else a[::4, shift::4]
            first, second = first - first.mean(), second - second.mean()
            denominator = float(np.sqrt(np.sum(first * first) * np.sum(second * second)))
            similarity = abs(float(np.sum(first * second))) / max(denominator, 1e-12)
            self_similarity = max(self_similarity, similarity)
    if self_similarity > .995:
        _failure('overlap has repeated/ambiguous texture within the displacement interval')
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fa, fb = np.fft.fft2((a - a.mean()) * window), np.fft.fft2((b - b.mean()) * window)
    spectrum = fa * np.conj(fb)
    corr = np.fft.ifft2(spectrum / np.maximum(np.abs(spectrum), 1e-12)).real
    ys, xs = np.fft.fftfreq(h, 1 / h), np.fft.fftfreq(w, 1 / w)
    allowed = (np.abs(ys[:, None]) <= radius['y']) & (np.abs(xs[None, :]) <= radius['x'])
    restricted = np.where(allowed, corr, -np.inf)
    iy, ix = np.unravel_index(np.argmax(restricted), restricted.shape)
    peak = float(corr[iy, ix])
    excluded = (np.abs(ys[:, None] - ys[iy]) <= 2) & (np.abs(xs[None, :] - xs[ix]) <= 2)
    second = float(np.max(np.where(allowed & ~excluded, corr, -np.inf)))
    ratio = peak / max(second, 1e-12)
    if not math.isfinite(peak) or peak < CORRELATION_FLOOR:
        _failure(f'correlation peak {peak:.4f} is below the floor')
    if ratio < PEAK_RATIO_MINIMUM:
        _failure(f'ambiguous correlation peaks (ratio {ratio:.3f})')
    if abs(ys[iy]) >= radius['y'] - 1 or abs(xs[ix]) >= radius['x'] - 1:
        _failure('displacement reaches the boundary of the predicted search interval')

    def refine(values, index):
        left, centre, right = values[(index - 1) % len(values)], values[index], values[(index + 1) % len(values)]
        denominator = left - 2 * centre + right
        return 0. if abs(denominator) < 1e-12 else float(np.clip(.5 * (left - right) / denominator, -.5, .5))

    dy, dx = dy0 + ys[iy] + refine(corr[:, ix], iy), dx0 + xs[ix] + refine(corr[iy], ix)
    if abs(dy - expected[0]) > radius['y'] or abs(dx - expected[1]) > radius['x']:
        _failure('measured displacement disagrees with the local preview')
    return (float(dy), float(dx)), {'predicted_dx': float(expected[1]), 'predicted_dy': float(expected[0]),
        'measured_dx': float(dx), 'measured_dy': float(dy), 'peak': peak,
        'secondary_peak': second, 'peak_ratio': ratio, 'overlap_width_px': x1 - x0,
        'overlap_height_px': y1 - y0, 'maximum_self_similarity': self_similarity, 'verified': True}


def register_preview(reference: np.ndarray, moving: np.ndarray, dpi: float = 300,
                     max_shift_mm: float = 4) -> dict:
    """Measure local same-resolution seek/replay error without a motor-pitch guess.

    Both inputs are actual RGB preview acquisitions, normally 430 × 284 at
    300 dpi. A positive dx/dy is the moving image's measured placement relative
    to the reference. Registration is optical evidence only: callers must still
    verify that corrected source windows contain their padded frame bounds.
    """
    try:
        dpi, max_shift_mm = float(dpi), float(max_shift_mm)
        if not math.isfinite(dpi) or not math.isfinite(max_shift_mm) or dpi <= 0 or max_shift_mm <= 0:
            raise ValueError('positive finite DPI and displacement bound are required')
        arrays = [np.asarray(item, dtype=np.float32) for item in (reference, moving)]
        if any(item.ndim != 3 or item.shape[2] != 3 or min(item.shape[:2]) < 64 or
               not np.isfinite(item).all() for item in arrays):
            raise ValueError('finite RGB preview acquisitions are required')
        radius_px = frame_align.mm_to_px(max_shift_mm, dpi)
        if radius_px < 3 or radius_px >= min(min(item.shape[:2]) for item in arrays) / 2 - 2:
            raise ValueError('preview displacement bound is incompatible with acquisition dimensions')
        measured, evidence = _register(arrays[0], arrays[1], (0., 0.),
                                      {'x': radius_px, 'y': radius_px}, dpi=dpi)
        return {'dx': measured[1], 'dy': measured[0], 'peak': evidence['peak'],
                'peak_ratio': evidence['peak_ratio'], 'secondary_peak': evidence['secondary_peak'],
                'maximum_self_similarity': evidence['maximum_self_similarity'],
                'search_radius_px': radius_px, 'verified': True}
    except (TypeError, ValueError) as exc:
        reason = str(exc).removeprefix('UNVERIFIED_STITCH_ALIGNMENT: ')
        raise ValueError(f'UNVERIFIED_PREVIEW_ALIGNMENT: {reason}') from exc


def stitch_planned(images: list[np.ndarray], plan: dict) -> dict:
    """Register at most two archival tiles using local optical predictions.

    No unconstrained second registration is performed during composition. Failure
    is explicit; retaining original TIFF tiles is the acquisition caller's job.
    """
    tiles = plan.get('tiles') or []
    if len(images) != len(tiles) or not 1 <= len(images) <= 2:
        _failure('one or two images matching the plan are required')
    arrays = [np.asarray(image, dtype=np.float32) for image in images]
    for image in arrays:
        if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 16 or not np.isfinite(image).all():
            _failure('finite RGB tiles are required')
    offsets, strengths, diagnostics = [(0., 0.)], [1.], []
    if len(arrays) == 2:
        # Delivered dimensions absorb actual preview-to-archival scale instead of
        # pretending declared DPI alone guarantees exact 6x scaling.
        sx = arrays[0].shape[1] / tiles[0]['width']
        sy = arrays[0].shape[0] / tiles[0]['height']
        if abs(arrays[1].shape[1] / tiles[1]['width'] - sx) > .05 or abs(arrays[1].shape[0] / tiles[1]['height'] - sy) > .05:
            _failure('tile acquisition geometries have inconsistent scale')
        expected = ((tiles[1]['dy'] - tiles[0]['dy']) * sy, (tiles[1]['dx'] - tiles[0]['dx']) * sx)
        radius = plan.get('registration', {}).get('uncertainty_highres_px', CROSS_RESOLUTION_PAD_PX)
        measured, diagnostic = _register(arrays[0], arrays[1], expected, radius)
        offsets.append(measured)
        strengths.append(diagnostic['peak'])
        diagnostics.append(diagnostic)
    return _compose(arrays, offsets) | {'reference': 0, 'match_strength': strengths,
        'registration': diagnostics, 'alignment_verified': True,
        'plan_preview_capture_id': plan.get('preview_capture_id')}


def _compose(images, offsets):
    oy, ox = -min(dy for dy, _ in offsets), -min(dx for _, dx in offsets)
    positions = [(int(round(dy + oy)), int(round(dx + ox))) for dy, dx in offsets]
    height = max(y + image.shape[0] for image, (y, x) in zip(images, positions))
    width = max(x + image.shape[1] for image, (y, x) in zip(images, positions))
    accumulator = np.zeros((height, width, 3), dtype=np.float32)
    weights = np.zeros((height, width, 1), dtype=np.float32)
    gains = [np.ones(3, dtype=np.float32)]
    for index, (image, (y, x)) in enumerate(zip(images, positions)):
        if index:
            ry, rx = positions[0]
            yh, xw = images[0].shape[:2]
            top, bottom = max(y, ry), min(y + image.shape[0], ry + yh)
            left, right = max(x, rx), min(x + image.shape[1], rx + xw)
            a = images[0][top - ry:bottom - ry, left - rx:right - rx].reshape(-1, 3)
            b = image[top - y:bottom - y, left - x:right - x].reshape(-1, 3)
            keep = (a.min(axis=1) > .02) & (b.min(axis=1) > .02) & (a.max(axis=1) < .98) & (b.max(axis=1) < .98)
            gain = np.median(a[keep] / b[keep], axis=0) if keep.sum() > 100 else np.ones(3)
            if np.any(gain < .5) or np.any(gain > 2):
                _failure('exposure mismatch is too large')
            gains.append(gain)
        h, w = image.shape[:2]
        feather_y = np.minimum(np.arange(h) + 1, h - np.arange(h))[:, None]
        feather_x = np.minimum(np.arange(w) + 1, w - np.arange(w))[None, :]
        feather = np.minimum(feather_y, feather_x).astype(np.float32)[..., None]
        accumulator[y:y + h, x:x + w] += np.clip(image * gains[index], 0, 1) * feather
        weights[y:y + h, x:x + w] += feather
    covered = weights[..., 0] > 0
    mosaic = accumulator / np.maximum(weights, 1e-9)
    return {'image': mosaic, 'covered': covered,
            'offsets_px': [{'dx': float(dx), 'dy': float(dy)} for dy, dx in offsets],
            'gains': [[float(value) for value in gain] for gain in gains]}
