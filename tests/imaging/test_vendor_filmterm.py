import hashlib
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from services.imaging import filmterms, vendor_filmterm

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / 'services/cyberview_bridge/bin/vendorcolour.exe'
DS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32/CyberViewX_MF/CyberViewX.ds'


def term(rows=256, matrix=True):
    scale = rows - 1
    positions = np.linspace(0, 1, rows)
    table = np.minimum(scale, np.stack([positions ** .8, positions ** 1.2, positions ** 1.8], axis=-1) * scale)
    body = '\n'.join(' '.join(f'{v:.6f}' for v in row) for row in table)
    mix = ([[1.11, -.07, -.03, .25], [-.03, 1.08, -.04, -.5], [-.01, -.02, 1.04, .75]] if matrix else
           [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]])
    return ('FilmName Synthetic parity;\nFilmClass NEG;\nFilmMfgr Fixture;\nFilmLut\n' + body + ';\n' +
            '\n'.join('FilmMat' + c + ' ' + ' '.join(str(v) for v in row) + ';' for c, row in zip('RGB', mix)))


def test_decimal_profile_values_survive_and_legacy_parser_stays_identical():
    text = term()
    exact = vendor_filmterm.parse(text)
    legacy = filmterms.parse(text)
    assert any(v != int(v) for row in exact['lut'] for v in row)
    assert all(v == int(v) for row in legacy['lut'] for v in row)
    x = np.array([[[0, 1, 2], [30000, 40000, 50000], [65535, 65535, 65535]]], np.uint16)
    assert vendor_filmterm.apply16(x, exact).dtype == np.uint16
    with pytest.raises(ValueError):
        vendor_filmterm.apply16(x.astype(np.float32), exact)


@pytest.mark.skipif(sys.platform != 'win32' or not ORACLE.is_file() or not DS.is_file(),
                    reason='Requires pinned local vendor binary and CPU-only vendorcolour oracle')
@pytest.mark.parametrize('rows,matrix', [(256, False), (256, True), (4096, False), (4096, True)])
def test_filmterm16_matches_vendor_cpu_worker(tmp_path, rows, matrix):
    settings = Path(os.environ['APPDATA']) / 'PIE/MF/CyberViewX.ini'
    before = settings.read_bytes() if settings.exists() else None
    profile = tmp_path / 'synthetic.ft'
    text = term(rows, matrix)
    profile.write_text(text, encoding='ascii')
    # Full input domain covers every knot/interpolation boundary and matrix output
    # transition, while permutations exercise distinct RGB values at each pixel.
    v = np.arange(65536, dtype=np.uint16)
    values = np.stack([v, np.roll(v, 17813), v[::-1]], axis=-1).reshape(256, 256, 3)
    raw, result = tmp_path / 'input.raw', tmp_path / 'output.raw'
    values.tofile(raw)
    completed = subprocess.run([str(ORACLE), 'film', str(raw), '256', '256', '16', str(profile), str(result)],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    expected = np.fromfile(result, dtype=np.uint16).reshape(values.shape)
    actual = vendor_filmterm.apply16(values, vendor_filmterm.parse(text))
    assert np.array_equal(actual, expected), {
        'different_samples': int(np.count_nonzero(actual != expected)),
        'max_error': int(np.max(abs(actual.astype(int) - expected.astype(int))))}
    assert (settings.read_bytes() if settings.exists() else None) == before
    assert hashlib.sha256(raw.read_bytes()).digest() == hashlib.sha256(values.tobytes()).digest()
