"""CyberView CFilmCIP's verified 16-bit film-term stage, independent of its DLL.

This is NOT the complete negative conversion. It maps already gamma/inversion
processed samples through a film LUT, then its matrix, as CyberViewX.ds 1.4 does.
Legacy recipes retain filmterms.py's older interpolated stage.
"""
from __future__ import annotations

import re
from functools import lru_cache
import json

import numpy as np

from services.imaging import filmterms

VERSION = 'cyberview-filmterm16-1'


def parse(text: str) -> dict:
    """Retain decimal .ft values as float32, unlike the legacy integer reader."""
    profile = filmterms.parse(text)
    table = re.search(r'^\s*FilmLut\s*$(.*?)(?=^\s*Film\w+\s|\Z)', text, re.M | re.S)
    rows = [line.replace(';', ' ').split() for line in table.group(1).splitlines() if line.strip(' \t\r;')]
    profile['lut'] = np.asarray(rows, dtype=np.float32).astype(float).tolist()
    profile['matrix'] = np.asarray(profile['matrix'], dtype=np.float32).astype(float).tolist()
    validate(profile)
    return profile


def validate(profile: dict) -> None:
    table = np.asarray(profile.get('lut'), dtype=float)
    matrix = np.asarray(profile.get('matrix'), dtype=float)
    if (table.shape not in ((256, 3), (4096, 3)) or not np.isfinite(table).all() or
            np.any(table < 0) or np.any(table > len(table) - 1) or np.any(np.diff(table, axis=0) < 0) or
            matrix.shape != (3, 4) or not np.isfinite(matrix).all()):
        raise ValueError('Invalid vendor film-term table or matrix')


@lru_cache(maxsize=8)
def _tables(encoded: str) -> tuple[np.ndarray, np.ndarray]:
    profile = json.loads(encoded)
    validate(profile)
    table = np.asarray(profile['lut'], dtype=np.float32).astype(np.float64)
    n = len(table)
    knots = np.trunc(table * 65535 / (n - 1)).astype(np.int64)
    values = np.arange(65536, dtype=np.int64)
    lo = np.minimum(values * (n - 1) // 65535, n - 2)
    left = lo * 65535 // (n - 1)
    right = (lo + 1) * 65535 // (n - 1)
    product = (knots[lo + 1] - knots[lo]) * (values - left)[:, None]
    denominator = (right - left)[:, None]
    expanded = knots[lo] + np.sign(product) * (np.abs(product) // denominator)
    expanded[-1] = knots[-1]
    matrix = np.asarray(profile['matrix'], dtype=np.float32).astype(np.float64)
    if n == 4096:
        matrix[:, 3] = (matrix[:, 3] * 255 / 4095).astype(np.float32)
    return expanded, matrix


def apply16(samples: np.ndarray, profile: dict) -> np.ndarray:
    """Return uint16 CFilmCIP output from uint16 RGB input, with vendor truncation."""
    if samples.dtype != np.uint16 or samples.ndim != 3 or samples.shape[-1] != 3:
        raise ValueError('Vendor film-term input must be uint16 RGB')
    key = json.dumps({'lut': profile['lut'], 'matrix': profile['matrix']}, separators=(',', ':'), allow_nan=False)
    expanded, matrix = _tables(key)
    mapped = expanded[samples, np.arange(3)]
    # x87 accumulates each dot product before a single float32 store; explicit
    # operations avoid BLAS/FMA-dependent rounding at quantisation boundaries.
    out = np.empty(samples.shape, dtype=np.uint16)
    for channel in range(3):
        row = matrix[channel]
        value = (mapped[..., 0] * row[0] + mapped[..., 1] * row[1] +
                 mapped[..., 2] * row[2] + row[3] * 65535 / 255).astype(np.float32)
        out[..., channel] = np.clip(value, 0, 65535).astype(np.uint16)
    return out


def apply(samples: np.ndarray, profile: dict) -> np.ndarray:
    """Normalised adapter; only explicit opt-in recipes use this quantised stage."""
    if not np.isfinite(samples).all():
        raise ValueError('Vendor film-term input contains nonfinite samples')
    words = np.rint(np.clip(samples, 0, 1) * 65535).astype(np.uint16)
    return apply16(words, profile).astype(np.float64) / 65535
