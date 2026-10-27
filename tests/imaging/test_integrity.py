from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from services.api.store import atomic_write
from services.imaging.pipeline import encode, render


def test_density_branches_and_deterministic_export():
    pixels = np.array([[[25, 75, 125], [220, 210, 200]]], dtype=np.uint8)
    original = encode(Image.fromarray(pixels))
    inverted = np.asarray(render(original, {'invert': True}, 'color_negative'))
    assert inverted[0, 0, 0] > inverted[0, 1, 0]
    bw = np.asarray(render(original, {'invert': True}, 'bw_negative'))
    assert np.all(bw[..., 0] == bw[..., 1])
    assert np.array_equal(np.asarray(render(original, {'invert': True}, 'positive')), pixels)
    assert encode(render(original, {'exposure': .5})) == encode(render(original, {'exposure': .5}))
    with Image.open(BytesIO(original)) as image:
        assert image.mode == 'RGB'


def test_atomic_publish_refuses_overwrite(tmp_path):
    target = tmp_path / 'original.tif'
    atomic_write(target, b'first')
    with pytest.raises(FileExistsError):
        atomic_write(target, b'second')
    assert target.read_bytes() == b'first'
    assert not list(tmp_path.glob('*.tmp'))
