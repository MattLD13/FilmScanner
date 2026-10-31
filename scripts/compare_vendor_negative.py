"""Render recovered AFL gamma/inversion and film-term stages, without reference fitting.

python scripts/compare_vendor_negative.py SOURCE.tif STOCK.ft MODEL.GG REFERENCE.tif OUTPUT_DIR
Reference pixels are used only for evaluation, registration and side-by-side display.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageDraw
import tifffile

from services.imaging import pipeline, vendor_negative
from scripts.fit_reference_tone import register


def run(source: Path, stock: Path, generic: Path, reference: Path, output: Path):
    import cv2
    paths = [source.resolve(), stock.resolve(), generic.resolve(), reference.resolve()]
    if output.resolve() in [p.parent for p in paths]:
        raise ValueError('Choose a separate output directory')
    source_bytes, stock_bytes, generic_bytes, reference_bytes = [p.read_bytes() for p in paths]
    digest = lambda b: hashlib.sha256(b).hexdigest()
    hashes = [digest(b) for b in [source_bytes, stock_bytes, generic_bytes, reference_bytes]]
    profile = vendor_negative.create(stock_bytes, generic_bytes, stock.name, stock.parent.name)
    raw, ref = pipeline.load_samples(source_bytes), pipeline.load_samples(reference_bytes)
    corrected = vendor_negative.apply(raw, profile)
    affine, registration = register(corrected.astype(np.float32), ref.astype(np.float32))
    h, w = ref.shape[:2]
    aligned = cv2.warpAffine(corrected, affine, (w, h))
    covered = cv2.warpAffine(np.ones(raw.shape[:2], np.uint8), affine, (w, h)) > 0
    covered = cv2.erode(covered.astype(np.uint8), np.ones((61, 61), np.uint8)) > 0
    error = np.abs(aligned[covered] - ref[covered])
    report = {'engine': vendor_negative.VERSION, 'profile_id': profile['id'], 'original_sha256': hashes[0],
              'reference_sha256': hashes[3], 'registration': registration,
              'aligned_rgb_mae_8bit': float(error.mean() * 255), 'reference_used_to_fit': False,
              'limits': 'Recovered model gamma/inversion and exact film-term stage. Different scan exposure and unresolved Auto Gamma caller state prevent full CyberView parity.'}
    recipe = {'invert': True, 'film_profile': profile['id'], 'auto_color': None}
    output.mkdir(parents=True, exist_ok=True)
    stream = BytesIO()
    tifffile.imwrite(stream, np.rint(corrected * 65535).astype(np.uint16), photometric='rgb',
                     iccprofile=pipeline.SRGB, software='FRAME',
                     description=json.dumps({'engine': vendor_negative.VERSION, 'recipe': recipe, 'original_sha256': hashes[0]}))
    (output/'corrected.tif').write_bytes(stream.getvalue())
    for name, data in [('profile.json', profile), ('recipe.json', recipe), ('report.json', report)]:
        (output/name).write_text(json.dumps(data, indent=2), encoding='utf-8')
    canvas = Image.new('RGB', (1200, 450), '#eee8df');draw = ImageDraw.Draw(canvas)
    for i, (title, values) in enumerate([('FRAME · recovered AFL conversion', aligned), ('CyberView reference', ref)]):
        photo = Image.fromarray(np.uint8(np.clip(values, 0, 1)*255+.5))
        photo.thumbnail((580, 405));canvas.paste(photo, (600*i+10, 30));draw.text((600*i+10, 10), title, fill='black')
    canvas.save(output/'comparison.jpg', quality=97)
    if h >= 1670 and w >= 780:
        canvas = Image.new('RGB', (1320, 465), '#eee8df');draw = ImageDraw.Draw(canvas)
        for i, (title, values) in enumerate([('FRAME · recovered AFL conversion', aligned), ('CyberView reference', ref)]):
            crop = values[1240:1670, 120:780]
            canvas.paste(Image.fromarray(np.uint8(np.clip(crop, 0, 1)*255+.5)), (660*i, 30))
            draw.text((660*i+10, 10), title, fill='black')
        canvas.save(output/'flowers.jpg', quality=97)
    assert [digest(p.read_bytes()) for p in paths] == hashes
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'stock', 'generic', 'reference', 'output'):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.source, args.stock, args.generic, args.reference, args.output)))
