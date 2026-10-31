"""CyberView's own automatic colour (iComputeAutoColor) through services/cyberview_bridge/bin/autocolor.exe.

Needs the installed CyberViewX.ds and the harness (build.ps1); no scanner access.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

EXE = Path(__file__).resolve().parents[2] / 'services' / 'cyberview_bridge' / 'bin' / 'autocolor.exe'
DS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32' / 'CyberViewX_MF' / 'CyberViewX.ds'
INI = Path(os.environ.get('APPDATA', '')) / 'PIE' / 'MF' / 'CyberViewX.ini'
pytestmark = pytest.mark.skipif(sys.platform != 'win32' or not EXE.is_file() or not DS.is_file(),
                                reason='Needs CyberView X installed and services/cyberview_bridge/build.ps1')


def test_cyberview_auto_colour_finds_each_channels_black_point(tmp_path):
    # A grey ramp whose channels start at different levels, like a hidden scan's lifted, tinted shadows.
    ramp = np.linspace(0, 1, 400)[None, :, None]
    image = np.broadcast_to(np.array([20, 45, 75]) + ramp * (np.array([250, 250, 250]) - [20, 45, 75]), (120, 400, 3))
    raw = tmp_path / 'ramp.raw'
    np.round(image).astype(np.uint8).tofile(raw)
    before = hashlib.sha256(INI.read_bytes()).hexdigest() if INI.is_file() else None
    result = json.loads(subprocess.run([str(EXE), str(raw), '400', '120'], capture_output=True, text=True,
                                       timeout=60, check=True).stdout)
    assert result['result'] == 0 and result['preset'] == 2
    words = np.array(result['words']).reshape(6, 3)       # [white in, white out, mid in, mid out, black in, black out] x RGB
    black = words[4]
    assert black[0] < black[1] < black[2]                  # R < G < B, as the ramp starts
    assert all(abs(b - s) <= 6 for b, s in zip(black, (20, 45, 75)))
    assert list(words[5]) == [0, 0, 0] and list(words[3]) == [128, 128, 128]
    if before:
        assert hashlib.sha256(INI.read_bytes()).hexdigest() == before   # CyberView's settings untouched
