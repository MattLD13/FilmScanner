import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps
import tifffile

from services.api.store import atomic_write
from services.imaging import filmterms

VERSION = 'frame-density-2'
DEFAULT_EDIT = {'exposure': 0, 'contrast': 1, 'rotation': 0, 'invert': True}
# A checked-in LittleCMS-generated profile avoids time-stamped ICC headers
# changing otherwise reproducible exports between application restarts.
SRGB = Path(__file__).with_name('sRGB.icc').read_bytes()


def encode(image, format='TIFF'):
    stream = BytesIO()
    image.save(stream, format=format, icc_profile=SRGB, **({'quality': 90} if format == 'JPEG' else {}))
    return stream.getvalue()


def _is_tiff(data):
    return data[:4] in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')


def source_info(original):
    with Image.open(BytesIO(original)) as source:
        info = {'format': source.format, 'sample_bits': 8,
                'extension': {'TIFF': '.tif', 'PNG': '.png', 'JPEG': '.jpg'}.get(source.format, '.source')}
    if _is_tiff(original):
        with tifffile.TiffFile(BytesIO(original)) as source:
            info['sample_bits'] = int(source.pages[0].bitspersample)
    elif original.startswith(b'\x89PNG\r\n\x1a\n'):
        info['sample_bits'] = original[24]
    return info


def load_samples(original):
    """Decode unsigned 8/16-bit samples without reducing TIFF precision."""
    if _is_tiff(original):
        with tifffile.TiffFile(BytesIO(original)) as source:
            if len(source.pages) != 1:
                raise ValueError('Import one image per TIFF; multi-page TIFF needs explicit page selection')
            page = source.pages[0]
            if page.imagewidth * page.imagelength > 32_000_000:
                raise ValueError('Maximum image size is 32 megapixels')
            if page.bitspersample not in (8, 16):
                raise ValueError('Only unsigned 8-bit and 16-bit TIFF samples are supported')
            try:
                values = page.asarray()
            except (ValueError, NotImplementedError) as exc:
                if page.bitspersample == 16:
                    raise ValueError('This 16-bit TIFF codec is unavailable; import an uncompressed TIFF') from exc
                with Image.open(BytesIO(original)) as image:
                    return np.asarray(ImageOps.exif_transpose(image).convert('RGB')).astype(np.float64) / 255
            if values.dtype.kind != 'u' or values.dtype.itemsize not in (1, 2):
                raise ValueError('TIFF must contain unsigned 8-bit or 16-bit samples')
            if int(page.planarconfig or 1) == 2 and values.ndim == 3:
                values = np.moveaxis(values, 0, -1)
            if values.ndim == 2:
                values = np.repeat(values[..., None], 3, axis=2)
            if values.ndim != 3 or values.shape[2] != 3 or int(page.photometric) not in (0, 1, 2):
                raise ValueError('Use RGB or grayscale TIFF without alpha or extra sample planes')
            values = values.astype(np.float64) / np.iinfo(values.dtype).max
            if int(page.photometric) == 0:
                values = 1 - values
            orientation = int(page.tags['Orientation'].value) if 'Orientation' in page.tags else 1
            transforms = {1: lambda x: x, 2: np.fliplr, 3: lambda x: np.rot90(x, 2), 4: np.flipud,
                          5: lambda x: x.swapaxes(0, 1), 6: lambda x: np.rot90(x, -1),
                          7: lambda x: np.rot90(x, 2).swapaxes(0, 1), 8: lambda x: np.rot90(x, 1)}
            if orientation not in transforms:
                raise ValueError('Unsupported TIFF orientation')
            return transforms[orientation](values)
    with Image.open(BytesIO(original)) as source:
        corrected = ImageOps.exif_transpose(source)
        samples = np.asarray(corrected)
        if samples.dtype.kind == 'u' and samples.dtype.itemsize == 2 and samples.ndim == 2:
            return np.repeat(samples[..., None], 3, axis=2).astype(np.float64) / 65535
        if original.startswith(b'\x89PNG\r\n\x1a\n') and original[24] == 16:
            raise ValueError('Use 16-bit TIFF for high-precision RGB input; this PNG decoder reduces RGB precision')
        return np.asarray(corrected.convert('RGB')).astype(np.float64) / 255


def render_samples(original: bytes, edit: dict, film_type='color_negative', profile=None):
    values = load_samples(original)
    if edit.get('invert', True) and film_type != 'positive':
        # Optical density relative to an explicit nominal film base. Manual measured
        # film-base selection and scanner ICC calibration are M2 work.
        base = np.asarray(edit.get('film_base', [1, 1, 1]), dtype=float)
        if base.shape != (3,) or not np.all(np.isfinite(base)) or np.any(base <= 0) or np.any(base > 1):
            raise ValueError('Film base must contain three finite transmission values above zero and at most one')
        density = -np.log(np.clip(values / base, 1 / 65535, 1))
        values = 1 - np.exp(-density * 1.6)
        if film_type == 'bw_negative':
            values = np.repeat(values.mean(axis=2, keepdims=True), 3, axis=2)
    if edit.get('film_profile'):
        # Film term before user adjustments, as CyberView orders them; the caller resolves the cached profile.
        if not profile or profile.get('id') != edit['film_profile']:
            raise ValueError('Film profile is not available for rendering')
        values = filmterms.apply(values, profile)
    values = ((values * 2 ** edit.get('exposure', 0) - .5) * edit.get('contrast', 1) + .5)
    values = np.clip(values, 0, 1)
    rotation = edit.get('rotation', 0) % 360
    if rotation % 90 == 0:
        return np.rot90(values, -int(rotation // 90))
    # Pillow's floating-point channel mode avoids an intermediate uint8 image.
    channels = [np.asarray(Image.fromarray(values[..., channel].astype(np.float32)).rotate(-rotation, expand=True))
                for channel in range(3)]
    return np.stack(channels, axis=2).astype(np.float64)


def render(original: bytes, edit: dict, film_type='color_negative', profile=None):
    return Image.fromarray(np.uint8(np.rint(render_samples(original, edit, film_type, profile) * 255)))


def render_tiff16(original, edit, film_type='color_negative', acquired_effective_bits=None, profile=None):
    values = np.asarray(np.rint(render_samples(original, edit, film_type, profile) * 65535), dtype='<u2')
    details = {'engine': VERSION, 'edit': edit, 'film_type': film_type,
               'source_sha256': hashlib.sha256(original).hexdigest(),
               'source_sample_bits': source_info(original)['sample_bits'],
               'acquired_effective_bits': acquired_effective_bits, 'output_sample_bits': 16,
               'processing_precision': 'float64', 'color_space': 'sRGB',
               'color_assumption': 'Nominal output space; scanner/film characterization not measured',
               'film_profile': ({'id': profile['id'], 'name': profile['name'], 'source': 'user CyberView install',
                                 'application': 'inferred table then matrix'} if profile else None)}
    stream = BytesIO()
    tifffile.imwrite(stream, values, photometric='rgb', planarconfig='contig', byteorder='<',
                     compression=None, metadata=None, description=json.dumps(details, sort_keys=True),
                     software=f'FRAME {VERSION}', extratags=[(34675, 'B', len(SRGB), SRGB, False)])
    return stream.getvalue()


def save_frame(store, roll, index, pixels, frame_id, synthetic=True, original_bytes=None, profile=None, scan_settings=None):
    original = original_bytes if original_bytes is not None else encode(Image.fromarray(pixels))
    prefix = f"{roll['id']}/acquisition/{frame_id}"
    info = source_info(original)
    original_path = prefix + info['extension']
    edit = dict(DEFAULT_EDIT, invert=synthetic and roll['film_type'] != 'positive')
    if profile:
        edit['film_profile'] = profile['id']
    preview = f"{roll['id']}/previews/{frame_id}-initial.jpg"
    image = render(original, edit, roll['film_type'], profile)
    image.thumbnail((1280, 1280))
    atomic_write(store.path(original_path), original)
    atomic_write(store.path(preview), encode(image, 'JPEG'))
    return {'id': frame_id, 'roll_id': roll['id'], 'index': index, 'original_path': original_path,
            'preview_path': preview, 'sha256': hashlib.sha256(original).hexdigest(), 'synthetic': synthetic,
            'edit': edit, 'favorite': False, 'effective_bits': 8 if synthetic else None,
            'source_sample_bits': info['sample_bits'], 'engine': VERSION,
            'provenance': 'Synthetic simulator transmission fixture' if synthetic else 'User imported image; acquired precision not measured',
            'scan_settings': scan_settings}


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
