import base64
import hashlib
from io import BytesIO
import json
import struct
import zlib

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile

from services.api.main import create_app
from services.imaging import pipeline


def tiff(samples, **options):
    output = BytesIO()
    tifffile.imwrite(output, samples, photometric='rgb', metadata=None, **options)
    return output.getvalue()


def test_uint16_samples_survive_decode_and_neutral_export():
    samples = np.array([[[10000, 10001, 10002], [32767, 32768, 32769]],
                        [[50000, 50001, 50002], [65533, 65534, 65535]]], dtype=np.uint16)
    for byteorder in ('<', '>'):
        original = tiff(samples, byteorder=byteorder)
        result = pipeline.render_tiff16(original, {'invert': False}, 'positive')
        with tifffile.TiffFile(BytesIO(result)) as output:
            assert output.asarray().dtype == np.uint16
            assert np.array_equal(output.asarray(), samples)
            assert output.pages[0].bitspersample == 16
            assert output.pages[0].tags[34675].value == pipeline.SRGB
            metadata = json.loads(output.pages[0].description)
            assert metadata['source_sample_bits'] == 16
            assert metadata['acquired_effective_bits'] is None
    assert np.array_equal(np.rint(pipeline.load_samples(original) * 65535).astype('uint16'), samples)


def test_processed_precision_is_distinct_from_captured_precision():
    original = tiff(np.array([[[21, 87, 155], [51, 173, 233]]], dtype=np.uint8))
    edit = {'invert': True, 'exposure': .15, 'contrast': .9, 'film_base': [.95, .85, .75]}
    encoded = pipeline.render_tiff16(original, edit, acquired_effective_bits=8)
    with tifffile.TiffFile(BytesIO(encoded)) as output:
        assert output.asarray().dtype == np.uint16
        assert np.any(output.asarray() % 257 != 0), 'Float processing must precede 16-bit quantization'
        description = json.loads(output.pages[0].description)
        assert description['source_sample_bits'] == 8
        assert description['acquired_effective_bits'] == 8
        assert description['output_sample_bits'] == 16
    assert encoded == pipeline.render_tiff16(original, edit, acquired_effective_bits=8)


def test_density_reference_rotation_and_orientation():
    samples = np.array([[[12001, 24002, 48003], [32001, 40002, 56003]]], dtype=np.uint16)
    original = tiff(samples)
    result = pipeline.render_samples(original, {'invert': True}, 'color_negative')
    assert np.allclose(result, 1 - (samples.astype(float) / 65535) ** 1.6)
    rotated = pipeline.render_tiff16(original, {'invert': False, 'rotation': 90}, 'positive')
    assert np.array_equal(tifffile.imread(BytesIO(rotated)), np.rot90(samples, -1))
    oriented = tiff(samples, extratags=[(274, 'H', 1, 6, False)])
    assert np.allclose(pipeline.load_samples(oriented), np.rot90(samples, -1) / 65535)


def test_invalid_film_base_rejected():
    original = tiff(np.full((2, 3, 3), 128, dtype=np.uint8))
    for base in ([0, 1, 1], [1, float('nan'), 1], [1, 1], [1.1, 1, 1]):
        with pytest.raises(ValueError, match='Film base'):
            pipeline.render(original, {'film_base': base})


def test_import16_export_and_original_hash(tmp_path):
    original = tiff(np.arange(18, dtype=np.uint16).reshape(2, 3, 3) + 10000)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post('/api/auth/local')
        roll = client.post('/api/rolls', json={'stock': '16-bit precision fixture', 'film_type': 'positive'}).json()
        response = client.post(f'/api/rolls/{roll["id"]}/import', json={'data_base64': base64.b64encode(original).decode()})
        assert response.status_code == 200, response.text
        frame = response.json()
        assert frame['original_path'].endswith('.tif')
        assert frame['source_sample_bits'] == 16
        assert frame['effective_bits'] is None, 'Imported sample width is not measured acquired precision'
        assert frame['sha256'] == hashlib.sha256(original).hexdigest()
        exported = client.get(f'/api/frames/{frame["id"]}/export?format=tiff')
        assert exported.status_code == 200
        assert np.array_equal(tifffile.imread(BytesIO(exported.content)), tifffile.imread(BytesIO(original)))
        assert client.get(f'/api/frames/{frame["id"]}/export?format=original').content == original
        assert client.post(f'/api/frames/{frame["id"]}/edit', json={'film_base': [0, 1, 1]}).status_code == 422
        customized = client.post(f'/api/frames/{frame["id"]}/edit', json={'film_base': [.9, .8, .7]})
        assert customized.status_code == 200
        legacy_client = client.post(f'/api/frames/{frame["id"]}/edit', json={'exposure': .2})
        assert legacy_client.json()['edit']['film_base'] == [.9, .8, .7]


def rgb16_png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 16, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b'\0' + struct.pack('>6H', 10000, 10001, 10002, 20000, 20001, 20002))) + chunk(b'IEND', b''))


def test_unsupported_rgb16_png_is_rejected_before_writing_original(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post('/api/auth/local')
        roll = client.post('/api/rolls', json={'stock': 'Unsupported precision fixture'}).json()
        result = client.post(f'/api/rolls/{roll["id"]}/import', json={'data_base64': base64.b64encode(rgb16_png()).decode()})
        assert result.status_code == 422
        assert not list(tmp_path.rglob('acquisition/*'))
        assert app.state.store.all('frames') == []


def test_failed_export_cannot_replace_original_or_prior_export(tmp_path, monkeypatch):
    import services.api.main as module
    original = tiff(np.full((2, 3, 3), 12001, dtype=np.uint16))
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post('/api/auth/local')
        roll = client.post('/api/rolls', json={'stock': 'Disk interruption fixture', 'film_type': 'positive'}).json()
        frame = client.post(f'/api/rolls/{roll["id"]}/import', json={'data_base64': base64.b64encode(original).decode()}).json()
        endpoint = f'/api/frames/{frame["id"]}'
        prior = client.get(endpoint + '/export?format=tiff')
        assert prior.status_code == 200
        previous_path = app.state.store.all('exports')[0]['path']
        assert client.post(endpoint + '/edit', json={'exposure': .5}).status_code == 200
        def disk_full(path, data):
            raise OSError('injected disk full')
        monkeypatch.setattr(module, 'atomic_write', disk_full)
        assert client.get(endpoint + '/export?format=tiff').status_code == 507
        assert app.state.store.path(frame['original_path']).read_bytes() == original
        assert app.state.store.path(previous_path).read_bytes() == prior.content
