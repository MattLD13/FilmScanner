"""Build a private appearance profile from two scans of the same negative.

Requires optional OpenCV for image registration (not a scanner driver). Example:
python scripts/fit_reference_tone.py SOURCE.tif REFERENCE.tif OUTPUT_DIR \
    --holdout 0,1200,900,1700 --name "Garden reference (experimental)"

Coordinates describe excluded test rectangles in the reference image. The tool
fits global channel curves only; it never transfers reference texture or sharpens.
It does not modify the library. To offer the generated profile in CyberScan, copy
profile.json to LIBRARY/film_profiles/PROFILE_ID.json and restart the application.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw
import tifffile

from services.api.cyberview_routes import Adjustments, apply, auto_color_for, before_levels
from services.imaging import filmterms, negative, pipeline, reference_tone


def register(source, target):
    import cv2
    def features(values):
        grey = np.uint8(np.clip(values @ np.array([.2126, .7152, .0722]), 0, 1) * 255)
        return cv2.createCLAHE(2, (8, 8)).apply(grey)
    sift = cv2.SIFT_create(nfeatures=5000)
    keys1, desc1 = sift.detectAndCompute(features(source), None)
    keys2, desc2 = sift.detectAndCompute(features(target), None)
    if desc1 is None or desc2 is None:
        raise ValueError('Too few image features for same-frame registration')
    pairs = cv2.BFMatcher().knnMatch(desc1, desc2, k=2)
    matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .7 * pair[1].distance]
    if len(matches) < 30:
        raise ValueError('Too few matching features; use the same frame at the same resolution')
    points1 = np.float32([keys1[m.queryIdx].pt for m in matches])
    points2 = np.float32([keys2[m.trainIdx].pt for m in matches])
    affine, inliers = cv2.estimateAffinePartial2D(points1, points2, method=cv2.RANSAC, ransacReprojThreshold=1.5)
    if affine is None or inliers.sum() < 30 or inliers.mean() < .5:
        raise ValueError('Images could not be registered reliably')
    if not .98 <= np.hypot(affine[0, 0], affine[1, 0]) <= 1.02:
        raise ValueError('Use source and reference at the same optical resolution')
    residual = np.linalg.norm(points1 @ affine[:, :2].T + affine[:, 2] - points2, axis=1)[inliers.ravel() > 0]
    return affine, {'matched_features': len(matches), 'inliers': int(inliers.sum()),
                    'median_residual_px': float(np.median(residual))}


def run(source_path: Path, reference_path: Path, output: Path, holdouts: list[tuple[int, int, int, int]], name: str):
    import cv2
    source_bytes, reference_bytes = source_path.read_bytes(), reference_path.read_bytes()
    raw = pipeline.load_samples(source_bytes).astype(np.float32)
    reference = pipeline.load_samples(reference_bytes).astype(np.float32)
    base = negative.suggest_base(raw)
    if base is None:
        raise ValueError('No reliable film-base suggestion; choose a usable transmission scan')
    prior = Adjustments(invert=True, film_base=base, negative_response=.5)
    prior.auto_color = auto_color_for(before_levels(raw, prior))
    previous = apply(raw, prior).astype(np.float32)
    affine, registration = register(previous, reference)
    h, w = reference.shape[:2]
    aligned = cv2.warpAffine(raw, affine, (w, h), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.ones(raw.shape[:2], np.uint8), affine, (w, h)) > 0
    mask = cv2.erode(mask.astype(np.uint8), np.ones((61, 61), np.uint8), borderType=cv2.BORDER_CONSTANT) > 0
    excluded = np.zeros((h, w), bool)
    for left, top, right, bottom in holdouts:
        if not (0 <= left < right <= w and 0 <= top < bottom <= h):
            raise ValueError('Holdout rectangles must lie inside the reference image')
        excluded[top:bottom, left:right] = True
    heldout = excluded & mask
    yy, xx = np.indices((h, w))
    training = mask & ~excluded & (yy % 7 == 0) & (xx % 7 == 0)
    if heldout.sum() < 1000 or training.sum() < 1000:
        raise ValueError('Provide substantial separate training and holdout regions')
    positive = negative.invert(aligned, base, .5)
    lut, counts = reference_tone.fit(positive, reference, training)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    profile = {'kind': 'reference-tone', 'engine': reference_tone.VERSION, 'name': name,
               'maker': 'User reference comparison', 'film_class': 'negative',
               'rows': 4096, 'scale': 4095, 'lut': (lut * 4095).tolist(),
               'matrix': np.column_stack((np.eye(3), np.zeros(3))).tolist(),
               'balance': [0, 0, 0], 'level': [0, 0, 0], 'input_response': .5,
               'source_file': source_path.name, 'source_folder': 'Reference profiles',
               'evidence': {'source_sha256': digest(source_bytes), 'reference_sha256': digest(reference_bytes),
                            'holdout_rectangles': holdouts, 'populated_bins': counts, 'registration': registration,
                            'training_pixels': int(training.sum()), 'holdout_pixels': int(heldout.sum()),
                            'scope': 'Experimental same-negative appearance profile; other scenes and stocks unverified.'}}
    canonical = json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()
    profile.update(id=digest(canonical)[:16], sha256=digest(canonical))
    corrected = filmterms.apply(positive, profile)
    aligned_previous = cv2.warpAffine(previous, affine, (w, h), flags=cv2.INTER_LINEAR)
    mae = lambda im: float(np.abs(im[heldout] - reference[heldout]).mean() * 255)
    report = {'profile_id': profile['id'], 'registration': registration,
              'holdout_rgb_mae_8bit': {'previous': mae(aligned_previous), 'reference_curves': mae(corrected)},
              'limits': profile['evidence']['scope'], 'originals_unchanged': True}
    output = output.resolve()
    if output in (source_path.resolve().parent, reference_path.resolve().parent):
        raise ValueError('Choose a separate output directory')
    output.mkdir(parents=True, exist_ok=True)
    recipe = Adjustments(invert=True, film_base=base, negative_response=.5,
                         film_profile=profile['id']).model_dump()
    native_output = filmterms.apply(negative.invert(raw, base, .5), profile)
    stream = BytesIO()
    tifffile.imwrite(stream, np.rint(np.clip(native_output, 0, 1) * 65535).astype('uint16'), photometric='rgb',
                     iccprofile=pipeline.SRGB, software=reference_tone.VERSION,
                     description=json.dumps({'recipe': recipe, 'original_sha256': digest(source_bytes),
                                             'reference_sha256': digest(reference_bytes)}))
    (output / 'corrected.tif').write_bytes(stream.getvalue())
    for filename, data in [('profile.json', profile), ('recipe.json', recipe), ('report.json', report)]:
        (output / filename).write_text(json.dumps(data, indent=2), encoding='utf-8')
    canvas = Image.new('RGB', (1800, 440), '#eee8df')
    draw = ImageDraw.Draw(canvas)
    images = [('Previous conversion', aligned_previous), ('Reference-derived curves', corrected), ('CyberView reference', reference)]
    for i, (title, values) in enumerate(images):
        picture = Image.fromarray(np.uint8(np.clip(values, 0, 1) * 255 + .5))
        picture.thumbnail((580, 400))
        canvas.paste(picture, (i * 600 + 10, 30))
        draw.text((i * 600 + 10, 10), title, fill='black')
    canvas.save(output / 'comparison.jpg', quality=97)
    # Full-size crops from test regions; no crop pixels were used to fit the LUT.
    canvas = Image.new('RGB', (900 * 3, 540 * len(holdouts)), '#eee8df')
    draw = ImageDraw.Draw(canvas)
    for row, (left, top, right, bottom) in enumerate(holdouts):
        for col, (title, values) in enumerate(images):
            crop = Image.fromarray(np.uint8(np.clip(values[top:bottom, left:right], 0, 1) * 255 + .5))
            crop.thumbnail((900, 500))  # Never enlarge a crop.
            canvas.paste(crop, (col * 900, row * 540 + 30))
            draw.text((col * 900 + 10, row * 540 + 10), title + ' / excluded test region', fill='black')
    canvas.save(output / 'detail.jpg', quality=97)
    canvas.crop((0, 0, 2700, 540)).save(output / 'detail-01.jpg', quality=97)
    assert digest(source_path.read_bytes()) == profile['evidence']['source_sha256']
    assert digest(reference_path.read_bytes()) == profile['evidence']['reference_sha256']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--holdout', action='append', required=True,
                        type=lambda value: tuple(int(v) for v in value.split(',')))
    parser.add_argument('--name', default='PF1800 AFL reference appearance (experimental)')
    args = parser.parse_args()
    if any(len(rect) != 4 for rect in args.holdout):
        parser.error('--holdout requires left,top,right,bottom')
    print(json.dumps(run(args.source, args.reference, args.output, args.holdout, args.name)))
