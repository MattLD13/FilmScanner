"""CyberView film-term (.ft) profiles read from the user's own CyberView installation.

FRAME never ships these vendor files. It discovers them in local folders, parses
them, and caches a parsed copy inside the user's library when one is used, so an
edit stays reproducible after CyberView is removed.

Format (observed in CyberView X SF 1.30 files): ``Key value...;`` lines with
FilmClass (NEG, REV, or B&&W / B for black and white), FilmMfgr, FilmName,
FilmLevel, FilmBalance, a FilmLut table of three-channel integer rows (256 rows
of 0-255, or 4096 rows of 0-4095 for some reversal stocks), and FilmMatR/G/B rows
of a 3x3 matrix plus offset. How CyberView applies them is INFERRED: here the table maps a
normalized positive per channel, then the matrix mixes channels.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

CLASSES = {'NEG': 'negative', 'REV': 'reversal', 'B': 'bw', 'B&&W': 'bw', 'B&W': 'bw'}
MAX_FILE_BYTES = 512_000
DEFAULT_ROOTS = (r'%WINDIR%\twain_32\CyberViewX_SF\GAMMA',)


def parse(text: str) -> dict:
    """Parse one .ft file into a validated profile without its identity fields."""
    fields = {key: value.strip() for key, value in re.findall(r'^\s*(Film\w+)\s+([^;]*);', text, re.M)}
    table = re.search(r'^\s*FilmLut\s*$(.*?)(?=^\s*Film\w+\s|\Z)', text, re.M | re.S)
    if not table or 'FilmName' not in fields or fields.get('FilmClass') not in CLASSES:
        raise ValueError('Not a CyberView film-term file')
    # Rows are tab-indented with CRLF endings, and the last row carries the statement's ';'.
    rows = [line.replace(';', ' ').split() for line in table.group(1).splitlines() if line.strip(' \t\r;')]
    lut = np.asarray(rows, dtype=float) if rows else np.empty((0, 3))
    if lut.ndim != 2 or lut.shape[1] != 3 or lut.shape[0] not in (256, 4096):
        raise ValueError('Film-term table must have 256 or 4096 rows of three values')
    scale = lut.shape[0] - 1 if lut.shape[0] == 4096 else 255
    if np.any(lut < 0) or np.any(lut > scale) or np.any(np.diff(lut, axis=0) < 0):
        raise ValueError(f'Film-term table values must be monotonic within 0..{scale}')
    matrix = []
    for channel in 'RGB':
        values = [float(v) for v in fields.get(f'FilmMat{channel}', '').split()]
        matrix.append(values if len(values) == 4 else [float(channel == c) for c in 'RGB'] + [0.0])
    numbers = lambda key: [float(v) for v in fields.get(key, '0 0 0').split()][:3]
    return {'name': fields['FilmName'], 'maker': fields.get('FilmMfgr', ''),
            'film_class': CLASSES[fields['FilmClass']], 'balance': numbers('FilmBalance'),
            'level': numbers('FilmLevel'), 'rows': int(lut.shape[0]), 'scale': scale,
            'lut': lut.astype(int).tolist(), 'matrix': matrix}


def roots(env=os.environ) -> list[Path]:
    configured = env.get('FRAME_FILMTERM_DIRS')
    candidates = configured.split(os.pathsep) if configured else [os.path.expandvars(r) for r in DEFAULT_ROOTS]
    return [Path(p) for p in candidates if p and Path(p).is_dir()]


def discover(env=os.environ) -> list[dict]:
    """Every readable profile under the configured folders, identified by content hash."""
    found = {}
    for root in roots(env):
        for path in sorted(root.rglob('*.ft')):
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = path.read_bytes()
                profile = parse(data.decode('latin-1'))
            except (OSError, ValueError):
                continue
            digest = hashlib.sha256(data).hexdigest()
            profile.update(id=digest[:16], sha256=digest, source_file=path.name, source_folder=path.parent.name)
            found.setdefault(profile['id'], profile)
    return sorted(found.values(), key=lambda p: (p['film_class'], p['name'], p['source_folder']))


def summary(profile: dict) -> dict:
    return {key: profile[key] for key in ('id', 'name', 'maker', 'film_class', 'rows', 'source_file', 'source_folder')}


def cache_path(store, profile_id: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{16}', profile_id):
        raise ValueError('Invalid film profile id')
    return store.path(f'film_profiles/{profile_id}.json')


def remember(store, profile: dict) -> None:
    """Keep the parsed profile in the library so renders do not depend on the CyberView install."""
    path = cache_path(store, profile['id'])
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(profile), encoding='utf-8')
        os.replace(temporary, path)


def load(store, profile_id: str) -> dict:
    path = cache_path(store, profile_id)
    if not path.exists():
        raise ValueError('Film profile is not in this library; choose it again from an installed CyberView')
    return json.loads(path.read_text(encoding='utf-8'))


def apply(values: np.ndarray, profile: dict) -> np.ndarray:
    """Map normalized RGB (0..1) through the per-channel table, then the 3x3 matrix plus offset."""
    lut = np.asarray(profile['lut'], dtype=float) / profile.get('scale', 255)
    positions = np.linspace(0, 1, lut.shape[0])
    mapped = np.stack([np.interp(values[..., c], positions, lut[:, c]) for c in range(3)], axis=-1)
    matrix = np.asarray(profile['matrix'], dtype=float)
    mixed = mapped @ matrix[:, :3].T + matrix[:, 3] / 255
    return np.clip(mixed, 0, 1)
