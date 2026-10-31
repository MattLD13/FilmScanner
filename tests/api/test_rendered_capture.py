import hashlib
from io import BytesIO

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import tifffile

from services.api.cyberview_routes import Adjustments
from services.api.main import create_app
from test_cyberview import bridge
from test_workflow import login


def seed(app):
    path = app.state.store.path('negative.tif')
    samples = np.empty((480, 720, 3), dtype='uint16')
    samples[:] = [13107, 26214, 39321]  # Transmission: .2/.4/.6, visibly blue.
    tifffile.imwrite(path, samples, photometric='rgb')
    original = path.read_bytes()
    record = {'id': 'rendered-test', 'original_path': 'negative.tif',
              'sha256': hashlib.sha256(original).hexdigest(),
              'adjustments': Adjustments(invert=True, film_base=[.7, .5, .3], negative_response=.5).model_dump()}
    app.state.store.save('cv_captures', record)
    return record, original


def test_home_and_roll_images_use_current_saved_edit_without_changing_source(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        record, original = seed(app)
        endpoint = '/api/cyberview/captures/rendered-test/rendered/'
        assert client.get(endpoint + 'thumb').status_code == 401
        login(client)
        thumb = client.get(endpoint + 'thumb')
        assert thumb.status_code == 200 and 'no-store' in thumb.headers['cache-control']
        image = Image.open(BytesIO(thumb.content))
        assert image.size == (360, 240)
        r, g, b = np.asarray(image).mean(axis=(0, 1))
        assert r > g + 50 and g > b + 15, 'Rendered thumbnail must invert the original blue transmission'
        assert client.get(endpoint + 'thumb').content == thumb.content
        # The recipe is part of the cache identity: edits cannot return a stale image.
        record['adjustments']['rotation'] = 90
        record['adjustments']['exposure'] = -.5
        app.state.store.save('cv_captures', record)
        changed = client.get(endpoint + 'thumb')
        assert Image.open(BytesIO(changed.content)).size == (240, 360)
        assert changed.content != thumb.content
        assert app.state.store.path('negative.tif').read_bytes() == original
        assert client.get(endpoint + 'other').status_code == 404
        assert not bridge.exists()
        app.state.store.path('negative.tif').write_bytes(b'changed after cached render')
        assert client.get(endpoint + 'thumb').status_code == 409


def test_rendered_image_rejects_changed_original_on_first_render(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        seed(app)
        login(client)
        app.state.store.path('negative.tif').write_bytes(b'corrupted acquisition')
        response = client.get('/api/cyberview/captures/rendered-test/rendered/preview')
        assert response.status_code == 409 and 'checksum' in response.json()['detail']
