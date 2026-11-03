"""Best-effort film type estimate from the first full-window RGB preview.

An orange unexposed base is strong evidence for color negative film. A neutral
frame cannot always distinguish a positive slide from a black-and-white negative,
so those guesses carry lower confidence and include their evidence.
"""
from __future__ import annotations

import numpy as np

from services.imaging import frame_align


def detect(samples: np.ndarray, dpi: float, *, transmission: bool = True,
           alignment: dict | None = None, covered: np.ndarray | None = None,
           exposure: list[float] | None = None) -> dict:
    image = np.asarray(samples, dtype=np.float32)
    if image.ndim != 3 or image.shape[2] < 3 or not np.isfinite(image).all():
        raise ValueError('Film type detection needs a finite RGB preview')
    image = np.clip(image[..., :3], 0, 1)
    height, width = image.shape[:2]
    edge_record = alignment or frame_align.align_35mm(image, dpi, transmission=transmission)
    relative_scale=np.ones(3,dtype=np.float32)
    if exposure is not None:
        values=np.asarray(exposure)
        if (values.shape!=(3,) or values.dtype.kind not in 'uif' or
                not np.isfinite(values).all() or np.any(values<=0)):
            raise ValueError('Film type detection needs three finite positive channel exposures')
        # Channel-balanced acquisition deliberately neutralizes the orange base.
        # Undo the *relative* exposure for classification only. Scaling to the
        # lowest seed avoids clipping and requires no absolute lamp calibration.
        relative_scale=(values.min()/values).astype(np.float32)
        image=image*relative_scale
    edges = edge_record.get('edges_x', edge_record.get('x', {'found': 'none'}))
    coverage = np.ones((height, width), dtype=bool) if covered is None else np.asarray(covered, dtype=bool)
    if coverage.shape != (height, width):
        raise ValueError('Film-type coverage mask must match the preview dimensions')
    y0, y1 = int(height * .2), max(int(height * .8), int(height * .2) + 1)
    band = max(3, int(round(frame_align.mm_to_px(1.0, dpi))))
    base_regions = []
    if edges.get('found') in ('both', 'start') and edges.get('start') is not None:
        edge = int(round(edges['start']))
        if edge >= 3:
            columns = np.arange(max(0, edge - band), edge)
            mask = coverage[y0:y1, columns]
            region = image[y0:y1, columns][mask]
            if region.size:
                base_regions.append(region)
    if edges.get('found') in ('both', 'end') and edges.get('end') is not None:
        edge = int(round(edges['end']))
        if edge < width - 3:
            columns = np.arange(edge, min(width, edge + band))
            mask = coverage[y0:y1, columns]
            region = image[y0:y1, columns][mask]
            if region.size:
                base_regions.append(region)
    has_base = bool(base_regions)
    base = np.median(np.concatenate(base_regions, axis=0), axis=0) if has_base else None
    def evidence(result):
        result['exposure_normalization']={'applied':exposure is not None,
            'method':'undo_relative_requested_channel_exposure_for_classification_only',
            'requested_exposure':np.asarray(exposure).astype(float).tolist() if exposure is not None else None,
            'relative_scale':relative_scale.astype(float).tolist(),
            'not_absolute_sensor_calibration':True}
        if base is not None:
            result['observed_film_base_rgb']=[round(float(v),4) for v in base/relative_scale]
        return result
    orange_score = 0.0
    if base is not None:
        red, green, blue = [float(value) for value in base]
        orange_score = float((red - blue) + .5 * (green - blue))
        if red > green * 1.12 and green > blue * 1.10 and red - blue > .08:
            return evidence({'film_type': 'color_negative', 'confidence': .96, 'method': 'orange_film_base',
                    'film_base_rgb': [float(round(float(v), 4)) for v in base], 'orange_score': float(round(orange_score, 4)),
                    'note': 'The clear film base has the orange mask typical of color negative film after accounting for channel exposure.'})

    interior = image
    if edges.get('found') == 'both' and edges.get('start') is not None and edges.get('end') is not None:
        left, right = int(round(edges['start'])), int(round(edges['end']))
        if right - left >= 16:
            interior = image[:, left:right]
    maximum = np.max(interior, axis=2)
    minimum = np.min(interior, axis=2)
    chroma = (maximum - minimum) / np.maximum(maximum, .02)
    median_chroma = float(np.median(chroma))
    neutral_fraction = float(np.mean(chroma < .035))
    if neutral_fraction >= .88 and median_chroma < .045:
        return evidence({'film_type': 'bw_negative', 'confidence': .82 if has_base else .52,
                'method': 'neutral_frame', 'film_base_rgb': [float(round(float(v), 4)) for v in base] if base is not None else None,
                'median_chroma': float(round(median_chroma, 4)), 'neutral_fraction': float(round(neutral_fraction, 4)),
                'orange_score': float(round(orange_score, 4)),
                'note': 'The frame is nearly monochrome and the rebate is neutral. A monochrome slide can look similar; verify the selection.'})
    return evidence({'film_type': 'positive', 'confidence': .82 if has_base else .58,
            'method': 'neutral_rebate_color_frame', 'film_base_rgb': [float(round(float(v), 4)) for v in base] if base is not None else None,
            'median_chroma': float(round(median_chroma, 4)), 'neutral_fraction': float(round(neutral_fraction, 4)),
            'orange_score': float(round(orange_score, 4)),
            'note': ('The rebate is neutral and the frame has visible color, which suggests slide film. '
                     'A color negative with an unusual or obscured base can look similar; verify the selection.')})
