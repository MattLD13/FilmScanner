"""One-frame synthetic benchmark; does not measure any scanner hardware."""
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import tracemalloc

import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.imaging.pipeline import VERSION, render_tiff16


def main():
    height, width = 1701, 2551
    samples = np.empty((height, width, 3), dtype=np.uint16)
    samples[..., 0] = np.linspace(512, 64512, width, dtype=np.uint16)
    samples[..., 1] = 32000
    samples[..., 2] = 42000
    source = BytesIO()
    tifffile.imwrite(source, samples, photometric='rgb', metadata=None)
    original = source.getvalue()
    del samples
    tracemalloc.start()
    started = time.perf_counter()
    output = render_tiff16(original, {'invert': True, 'exposure': .2, 'contrast': 1.1}, 'color_negative')
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {'fixture': 'synthetic nominal 4.34 MP RGB TIFF; not hardware timing',
              'shape': [height, width, 3], 'source_sample_bits': 16, 'acquired_effective_bits': None,
              'source_bytes': len(original), 'output_bytes': len(output),
              'render_seconds': round(elapsed, 3), 'python_tracemalloc_peak_bytes': peak,
              'memory_scope': 'Tracked Python/NumPy allocations during render; excludes preallocated input and full OS RSS',
              'engine': VERSION, 'limitation': 'One image at a time; larger inputs need separate memory benchmarks'}
    (ROOT / 'docs' / 'imaging-benchmark.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
