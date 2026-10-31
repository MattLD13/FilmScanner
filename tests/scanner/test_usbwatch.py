"""USB watch logic in services/cyberview_bridge/usbwatch.h, driven by a CPU-only harness.

Build once with services/cyberview_bridge/build.ps1 -Tests; skipped when absent.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest

HARNESS = Path(__file__).resolve().parents[2] / 'services' / 'cyberview_bridge' / 'bin' / 'usbwatch-harness.exe'
pytestmark = pytest.mark.skipif(sys.platform != 'win32' or not HARNESS.is_file(),
                                reason='Run services/cyberview_bridge/build.ps1 -Tests to build the harness')


def test_preview_shows_only_the_frame_pass_and_stuck_needs_30_seconds_of_polling():
    events = [json.loads(line) for line in subprocess.run([str(HARNESS)], capture_output=True, text=True,
                                                          timeout=30, check=True).stdout.splitlines()]
    starts = [e for e in events if e['event'] == 'live_start']
    # Calibration (wide, 62 lines) and the focus strip (224 px) never reach the preview.
    assert starts == [{'event': 'live_start', 'pass': 3, 'width': 309, 'source_width': 2479, 'scale': 8}]
    rows = [e for e in events if e['event'] == 'live']
    assert [r['y'] for r in rows] == list(range(25))          # 200 lines / 8
    for row in rows:
        pixels = base64.b64decode(row['data'])
        assert len(pixels) == 309 * 3
        for x in (0, 100, 308):
            assert list(pixels[x * 3:x * 3 + 3]) == [(x + row['y'] + c * 50) & 0xff for c in range(3)]
    checks = {e['after_ms']: e['stuck'] for e in events if e['event'] == 'stuck_check'}
    assert checks == {20000: 0, 31000: 1}
