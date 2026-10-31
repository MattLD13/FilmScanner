"""Compare an existing transmission scan with a saved positive reference, offline.

python scripts/compare_negative.py SOURCE.tif REFERENCE.tif OUTPUT_DIRECTORY
No library metadata is modified and no scanner bridge is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw

from services.api.cyberview_routes import Adjustments, apply, before_levels, auto_color_for
from services.imaging import negative, pipeline


def compare(source: Path, reference: Path, output: Path) -> dict:
    source_bytes, reference_bytes = source.read_bytes(), reference.read_bytes()
    samples = pipeline.load_samples(source_bytes)
    ref = pipeline.load_samples(reference_bytes)
    base = negative.suggest_base(samples)
    if base is None:
        raise ValueError('No reliable film-base suggestion; use manual controls')
    old = Adjustments(invert=True)
    old.auto_color = auto_color_for(before_levels(samples, old))
    proposed = Adjustments(invert=True, film_base=base, negative_response=negative.SUGGESTED_RESPONSE)
    proposed.auto_color = auto_color_for(before_levels(samples, proposed))
    before, after = apply(samples, old), apply(samples, proposed)
    quantiles = np.linspace(.02, .98, 97)
    target = np.quantile(ref, quantiles, axis=(0, 1))

    def error(values):
        # Distribution comparison tolerates small framing differences. It does not
        # establish pixel registration, colour accuracy or transfer to other film.
        return float(np.abs(np.quantile(values, quantiles, axis=(0, 1)) - target).mean() * 255)

    report = {'engine': negative.VERSION, 'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
              'reference_sha256': hashlib.sha256(reference_bytes).hexdigest(),
              'suggested_base': base, 'recipe': proposed.model_dump(),
              'quantile_mae_8bit': {'before': error(before), 'after': error(after)},
              'metric': 'Mean absolute RGB quantile difference, 2nd–98th percentiles, on a 0–255 scale. '
                        'Same-scene appearance comparison; not calibrated colour accuracy.'}
    # Refuse an output directory that could contain/replace either source.
    output = output.resolve()
    if output in (source.resolve().parent, reference.resolve().parent):
        raise ValueError('Choose a separate comparison output directory')
    output.mkdir(parents=True, exist_ok=True)
    canvas = Image.new('RGB', (1800, 460), '#eee8df')
    draw = ImageDraw.Draw(canvas)
    for i, (name, values) in enumerate([('Previous conversion', before), ('Suggested conversion', after), ('CyberView reference', ref)]):
        picture = Image.fromarray(np.uint8(np.clip(values, 0, 1) * 255 + .5))
        picture.thumbnail((580, 405))
        canvas.paste(picture, (i * 600 + 10, 35))
        draw.text((i * 600 + 10, 12), name, fill='#34291e')
        picture.save(output / ('before.jpg' if i == 0 else 'after.jpg' if i == 1 else 'reference.jpg'), quality=95)
    canvas.save(output / 'comparison.jpg', quality=95)
    (output / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == report['source_sha256']
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == report['reference_sha256']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = compare(args.source, args.reference, args.output)
    print(json.dumps({'engine': result['engine'], 'quantile_mae_8bit': result['quantile_mae_8bit'],
                      'comparison': str(args.output.resolve() / 'comparison.jpg')}))
