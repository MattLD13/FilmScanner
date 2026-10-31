"""PF1800 AFL negative path recovered from CyberView, with cached local profiles.

The model constructor chooses 37.GG (despite its PF3600AFL file comment).
Scanner gamma is complemented for negative film, followed by CFilmCIP. The source
acquisition has the vendor's calibration but an identity scan LUT; this reproduces
the recovered tone stages in software. It does not reproduce different exposures,
unknown prescan state or unverified automatic-gamma handling.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np

from services.imaging import filmterms, vendor_filmterm

LEGACY_VERSION = 'afl-vendor-negative-1'
VERSION = 'afl-vendor-negative-2'


def identify(profile: dict) -> dict:
    content = {k: v for k, v in profile.items() if k not in ('id', 'sha256')}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return content | {'id': digest[:16], 'sha256': digest}


def parse_generic(text: str) -> list[list[int]]:
    match = re.search(r'^\s*FilmLut\s*$(.*?);', text, re.M | re.S)
    if not match:
        raise ValueError('Generic gamma FilmLut is missing')
    rows = [line.split() for line in match.group(1).splitlines() if line.strip()]
    values = np.asarray(rows, dtype=np.float32)
    if values.shape != (4096, 3) or not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 4095):
        raise ValueError('Generic gamma must contain 4096 RGB rows within 0–4095')
    words = np.trunc(values).astype(np.uint16)
    if np.any(np.diff(words.astype(int), axis=0) < 0):
        raise ValueError('Generic gamma must be monotone')
    return words.tolist()


def create(film_data: bytes, gamma_data: bytes, source_file: str, source_folder: str) -> dict:
    profile = vendor_filmterm.parse(film_data.decode('latin-1'))
    if profile['film_class'] != 'negative':
        raise ValueError('Choose a negative film term for the AFL negative conversion')
    profile.update(kind='vendor-negative', engine=VERSION, generic_lut=parse_generic(gamma_data.decode('latin-1')),
                   source_file=source_file, source_folder=source_folder,
                   source_sha256=hashlib.sha256(film_data).hexdigest(), generic_sha256=hashlib.sha256(gamma_data).hexdigest(),
                   generic_file='37.GG', note='Recovered AFL gamma/inversion and film-term stages; full CyberView appearance remains under comparison.')
    return identify(profile)


def validate(profile: dict) -> None:
    try:
        vendor_filmterm.validate(profile)
        generic = np.asarray(profile['generic_lut'], dtype=float)
        if (profile['kind'] != 'vendor-negative' or profile['engine'] not in (VERSION, LEGACY_VERSION) or profile['film_class'] != 'negative' or
                profile['rows'] != len(profile['lut']) or profile['scale'] != len(profile['lut']) - 1 or
                any(not isinstance(profile[k], str) or not profile[k] for k in ('name', 'maker', 'source_file', 'source_folder')) or
                profile['generic_file'] != '37.GG' or
                not re.fullmatch(r'[0-9a-f]{64}', profile['source_sha256']) or
                not re.fullmatch(r'[0-9a-f]{64}', profile['generic_sha256']) or
                generic.shape != (4096, 3) or not np.isfinite(generic).all() or
                np.any(generic < 0) or np.any(generic > 4095) or np.any(generic != np.trunc(generic)) or
                np.any(np.diff(generic, axis=0) < 0) or identify(profile)['sha256'] != profile['sha256'] or
                profile['id'] != profile['sha256'][:16]):
            raise ValueError('Invalid AFL conversion profile')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('AFL conversion profile is invalid or its checksum changed') from exc


def discover() -> list[dict]:
    """No vendor curves are distributed; use and cache only the local installation."""
    profiles = {}
    for folder in filmterms.roots():
        gamma = folder / '37.GG'
        if not gamma.is_file():
            continue
        try:
            gamma_data = gamma.read_bytes()
        except OSError:
            continue
        if len(gamma_data) > filmterms.MAX_FILE_BYTES:
            continue
        for path in sorted(folder.rglob('*.ft')):
            try:
                if path.stat().st_size > filmterms.MAX_FILE_BYTES:
                    continue
                profile = create(path.read_bytes(), gamma_data, path.name, path.parent.name)
                profiles.setdefault(profile['id'], profile)
            except (OSError, ValueError):
                continue
    return sorted(profiles.values(), key=lambda p: p['name'])


def apply16(samples: np.ndarray, profile: dict) -> np.ndarray:
    """Exact SCAN08 16-bit LUT indexing followed by the CFilmCIP film term.

    SCAN08 0x10011a03 allocates three 65536-WORD host tables. For each 12-bit
    gamma entry it writes (entry << 4) sixteen times. Hence each input's low
    four bits select the same output. This is independent of effective sensor
    precision, which remains unmeasured.
    """
    validate(profile)
    if samples.dtype != np.uint16 or samples.ndim != 3 or samples.shape[-1] != 3:
        raise ValueError('AFL model LUT input must be uint16 RGB')
    table = np.asarray(profile['generic_lut'], dtype=np.uint16)
    gamma = (4095 - table[samples >> 4, np.arange(3)]) << 4
    return vendor_filmterm.apply16(gamma.astype(np.uint16), profile)


def apply(samples: np.ndarray, profile: dict) -> np.ndarray:
    """Recovered negative gamma plus exact film-term stage; no fitted image data."""
    validate(profile)
    if samples.ndim != 3 or samples.shape[-1] != 3 or not np.isfinite(samples).all():
        raise ValueError('AFL negative conversion needs finite RGB transmission')
    if profile['engine'] == VERSION:
        words = np.rint(np.clip(samples, 0, 1) * 65535).astype(np.uint16)
        return apply16(words, profile).astype(np.float64) / 65535
    table = np.asarray(profile['generic_lut'], dtype=np.float64)
    # The acquired uint16 container is expanded by the driver from a 12-bit scan
    # table. Interpolate in software to preserve the supported container precision.
    # This interpolation is explicitly a software adapter, not a new sensor claim.
    gamma = np.stack([np.interp(np.clip(samples[..., c], 0, 1), np.linspace(0, 1, 4096),
                                (4095 - table[:, c]) / 4095) for c in range(3)], axis=-1)
    return vendor_filmterm.apply(gamma, profile)
