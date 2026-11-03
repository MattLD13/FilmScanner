"""Exclude acquisition-edge artifacts from statistics, never from saved pixels."""
from __future__ import annotations

import math
import numpy as np

VERSION='afl-statistics-edge-guard-1'


def mask(shape, dpi: float, covered=None):
    h,w=shape[:2]
    dpi=float(dpi)
    if not math.isfinite(dpi) or dpi<=0:
        raise ValueError('Statistics guard requires positive finite DPI')
    valid=np.ones((h,w),dtype=bool) if covered is None else np.asarray(covered,dtype=bool).copy()
    if valid.shape!=(h,w):
        raise ValueError('Coverage must match the image dimensions')
    # This is a conservative statistics policy based on the observed full-window
    # band, not a detector of its cause or an assertion about film containment.
    bottom=int(math.ceil(40*dpi/1800));side=int(math.ceil(8*dpi/1800))
    applied=min(h,w)>=64 and bottom<=.05*h and side<=.05*w
    if applied:
        valid[max(0,h-bottom):]=False
        valid[:,:min(side,w)]=False
        valid[:,max(0,w-side):]=False
    evidence={'version':VERSION,'dpi':dpi,'applied':applied,
              'bottom_rows':bottom if applied else 0,'side_columns_each':side if applied else 0,
              'valid_pixels':int(valid.sum()),'original_pixels_modified':False,
              'reason':None if applied else 'Image too small to assume the full-window edge geometry.'}
    return valid,evidence
