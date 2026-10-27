import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageOps

from services.api.store import atomic_write

VERSION = 'frame-density-1'
DEFAULT_EDIT = {'exposure': 0, 'contrast': 1, 'rotation': 0, 'invert': True}
# A checked-in LittleCMS-generated profile avoids time-stamped ICC headers
# changing otherwise reproducible exports between application restarts.
SRGB = Path(__file__).with_name('sRGB.icc').read_bytes()


def encode(image, format='TIFF'):
    stream = BytesIO()
    image.save(stream, format=format, icc_profile=SRGB, **({'quality': 90} if format == 'JPEG' else {}))
    return stream.getvalue()


def render(original: bytes, edit: dict, film_type='color_negative'):
    with Image.open(BytesIO(original)) as source:
        values = np.asarray(ImageOps.exif_transpose(source).convert('RGB')).astype(np.float64) / 255
    if edit.get('invert', True) and film_type != 'positive':
        # Optical density relative to an explicit nominal film base. Manual measured
        # film-base selection and scanner ICC calibration are M2 work.
        base = np.asarray(edit.get('film_base', [1, 1, 1]), dtype=float)
        density = -np.log(np.clip(values / base, 1 / 65535, 1))
        values = 1 - np.exp(-density * 1.6)
        if film_type == 'bw_negative':
            values = np.repeat(values.mean(axis=2, keepdims=True), 3, axis=2)
    values = ((values * 2 ** edit.get('exposure', 0) - .5) * edit.get('contrast', 1) + .5)
    image = Image.fromarray(np.uint8(np.rint(np.clip(values, 0, 1) * 255)))
    return image.rotate(-edit.get('rotation', 0), expand=True)


def save_frame(store, roll, index, pixels, frame_id, synthetic=True, original_bytes=None):
    original = original_bytes if original_bytes is not None else encode(Image.fromarray(pixels))
    prefix = f"{roll['id']}/acquisition/{frame_id}"
    original_path = f'{prefix}.tif' if original_bytes is None else f'{prefix}.source'
    atomic_write(store.path(original_path), original)
    edit = dict(DEFAULT_EDIT, invert=synthetic and roll['film_type'] != 'positive')
    preview = f"{roll['id']}/previews/{frame_id}-initial.jpg"
    image = render(original, edit, roll['film_type'])
    image.thumbnail((1280, 1280))
    atomic_write(store.path(preview), encode(image, 'JPEG'))
    return {'id': frame_id, 'roll_id': roll['id'], 'index': index, 'original_path': original_path,
            'preview_path': preview, 'sha256': hashlib.sha256(original).hexdigest(), 'synthetic': synthetic,
            'edit': edit, 'favorite': False, 'effective_bits': 8, 'engine': VERSION,
            'provenance': 'Synthetic simulator transmission fixture' if synthetic else 'User imported image; acquired precision not measured'}


def verify_frame(store, frame):
    try:
        return hashlib.sha256(store.path(frame['original_path']).read_bytes()).hexdigest() == frame['sha256']
    except OSError:
        return False


def contact_sheet(store, roll_id, frames, revision):
    ordered = sorted(frames, key=lambda item: item['index'])
    sheet = Image.new('RGB', (1000, max(1, (len(ordered) + 5) // 6) * 140), '#f4ead8')
    draw = ImageDraw.Draw(sheet)
    for position, frame in enumerate(ordered):
        with Image.open(store.path(frame['preview_path'])) as source:
            thumb = ImageOps.contain(source.convert('RGB'), (154, 108))
        x, y = (position % 6) * 166 + 6, (position // 6) * 140 + 6
        sheet.paste(thumb, (x, y))
        draw.text((x, y + 112), f"{frame['index']:02d}" + (' / SIM' if frame['synthetic'] else ''), fill='#2d1f1b')
    path = f'{roll_id}/contact_sheet-{revision}.jpg'
    atomic_write(store.path(path), encode(sheet, 'JPEG'))
    return path
