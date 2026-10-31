"""The Python port of CyberView's automatic colour must equal CyberViewX.ds word for word.

Reference words were produced by the DS itself (services/cyberview_bridge/bin/autocolor.exe)
on 2026-10-31. When CyberView and the harness are installed, random images are also
compared live.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from services.imaging import autocolor

EXE = Path(__file__).resolve().parents[2] / 'services' / 'cyberview_bridge' / 'bin' / 'autocolor.exe'
DS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32' / 'CyberViewX_MF' / 'CyberViewX.ds'


def ramp():
    y, x = np.mgrid[0:120, 0:200]
    return np.stack([20 + x * 1.1, 45 + x * .9 + y * .3, 75 + x * .6 + y * .5], -1).clip(0, 255).astype(np.uint8)


def checker():
    y, x = np.mgrid[0:90, 0:150]
    v = ((x // 10 + y // 10) % 2) * 120 + 60 + (x % 10) * 3
    return np.stack([v, v * .9 + 10, v * .7 + 30], -1).clip(0, 255).astype(np.uint8)


@pytest.mark.parametrize('image, code, words', [
    (ramp(), 0, [242, 255, 255, 255, 255, 255, 140, 157, 164, 128, 128, 128, 19, 47, 77, 0, 0, 0]),
    # No nearly neutral pixel at the middle level: the DS resets to identity and reports 0x517.
    (checker(), 0x517, [255, 255, 255, 255, 255, 255, 128, 128, 128, 128, 128, 128, 0, 0, 0, 0, 0, 0]),
    (np.full((50, 60, 3), 128, np.uint8), 0, [130, 130, 130, 255, 255, 255, 128, 128, 128, 128, 128, 128, 126, 126, 126, 0, 0, 0]),
])
def test_matches_words_recorded_from_cyberview(image, code, words):
    assert autocolor.compute(image) == (code, words)


def test_curves_carry_cyberviews_green_black_point_quirk():
    points = autocolor.curves([255, 255, 255, 255, 255, 255, 113, 158, 156, 128, 128, 128, 12, 42, 75, 0, 0, 0])
    assert points['master'] == [(155, 130)]
    assert points['r'] == [(255, 255), (113, 128), (12, 0)]
    assert points['g'] == [(255, 255), (158, 128), (0, 0)]   # 42 is computed but never used
    assert points['b'] == [(255, 255), (156, 128), (75, 0)]


@pytest.mark.skipif(sys.platform != 'win32' or not EXE.is_file() or not DS.is_file(),
                    reason='Needs CyberView X installed and services/cyberview_bridge/build.ps1')
def test_matches_cyberview_live_on_random_images(tmp_path):
    rng = np.random.default_rng(2026)
    for k in range(8):
        h, w = (int(v) for v in rng.integers(40, 140, 2))
        base, span = rng.uniform(0, 80, 3), rng.uniform(80, 255, 3)
        shade = np.linspace(0, 1, w)[None, :, None] * np.linspace(.3, 1, h)[:, None, None]
        image = np.clip(base + shade * span + rng.normal(0, rng.uniform(0, 25), (h, w, 3)), 0, 255).astype(np.uint8)
        raw = tmp_path / f'{k}.raw'
        image.tofile(raw)
        ref = json.loads(subprocess.run([str(EXE), str(raw), str(w), str(h)], capture_output=True, text=True, timeout=60).stdout)
        assert autocolor.compute(image) == (ref['result'], ref['words']), k
