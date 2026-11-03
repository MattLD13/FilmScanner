import hashlib
from io import BytesIO
import json
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile
from PIL import Image

from services.api.main import create_app
from services.api.cyberview_routes import Adjustments, auto_color_for, to_float
from services.imaging import negative
from test_cyberview import bridge
from test_workflow import login


def seed(app, *, kind='vendor-calibrated-transmission', flat=False):
    density = np.linspace(.08, .95, 600).reshape(20, 30)
    density[:2] = 1
    samples = density[..., None] * [.7, .5, .3]
    if flat:
        samples[:] = .4
    original = app.state.store.path('negative.tif')
    tifffile.imwrite(original, np.rint(samples * 65535).astype('uint16'), photometric='rgb')
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    return app.state.store.save('cv_captures', {
        'id': 'negative', 'original_path': 'negative.tif', 'sha256': digest,
        'image_kind': kind, 'requested_settings': {'film': 'negative'},
        'created_at': 1, 'title': 'Synthetic negative', 'dpi': 1800,
        'adjustments': Adjustments(invert=True, exposure=.15,
                                  crop={'left': .1, 'top': 0, 'right': .9, 'bottom': 1}).model_dump(),
    })


def test_saved_negative_balance_preserves_original_settings_and_restarts(tmp_path, bridge):
    root = tmp_path / 'library'
    app = create_app(root)
    with TestClient(app) as client:
        record = seed(app)
        url = '/api/cyberview/captures/negative'
        assert client.post(url + '/balance-negative').status_code == 401
        login(client)
        settings = client.get('/api/cyberview/workspace').json()['settings']
        original = client.get(url + '/export/original').content
        result = client.post(url + '/balance-negative')
        assert result.status_code == 200, result.text
        updated = result.json()
        assert updated['negative_balance']['version'] == negative.VERSION
        assert updated['adjustments']['negative_response'] == .5
        assert updated['adjustments']['film_base'] == pytest.approx([.7, .5, .3], abs=2/65535)
        assert updated['adjustments']['crop'] == record['adjustments']['crop']
        assert updated['adjustments']['exposure'] == .15
        output = client.get(url + '/export/tiff').content
        with tifffile.TiffFile(BytesIO(output)) as tif:
            assert tif.asarray().dtype == np.uint16
            metadata = json.loads(tif.pages[0].description)
            assert metadata['original_sha256'] == hashlib.sha256(original).hexdigest()
            assert metadata['adjustments'] == updated['adjustments']
        assert client.get(url + '/export/original').content == original
        assert client.get('/api/cyberview/workspace').json()['settings'] == settings
        legacy_edit = client.patch(url, json={'adjustments': {'exposure': .15}})
        assert legacy_edit.json()['adjustments']['negative_response'] == .5
        # Restore the complete edit so the restart comparison tests the same recipe.
        client.patch(url, json={'adjustments': updated['adjustments']})
        assert not bridge.exists(), 'Balancing a saved scan must not start the scanner bridge'
    with TestClient(create_app(root)) as client:
        login(client)
        assert client.get(url + '/export/tiff').content == output
        assert client.get(url + '/export/original').content == original


@pytest.mark.parametrize('kind,flat', [('cyberview-processed-positive', False), ('vendor-calibrated-transmission', True)])
def test_unsuitable_scans_are_rejected_without_edit_changes(tmp_path, bridge, kind, flat):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        record = seed(app, kind=kind, flat=flat)
        result = client.post('/api/cyberview/captures/negative/balance-negative')
        assert result.status_code == 409
        assert app.state.store.get('cv_captures', 'negative') == record
        assert not bridge.exists()


@pytest.mark.parametrize('change,expected_status', [({'title': 'Renamed while balancing', 'favorite': True}, 200),
                                                 ({'adjustments': {'exposure': .8}}, 409)])
def test_balance_preserves_concurrent_edits(tmp_path, bridge, monkeypatch, change, expected_status):
    app = create_app(tmp_path / 'library')
    entered, release = threading.Event(), threading.Event()
    original = negative.suggest_base
    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(negative, 'suggest_base', held)
    with TestClient(app) as client:
        login(client)
        seed(app)
        url = '/api/cyberview/captures/negative'
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(client.post, url + '/balance-negative')
            try:
                assert entered.wait(5)
                assert client.patch(url, json=change).status_code == 200
            finally:
                release.set()
            assert pending.result().status_code == expected_status
        final = app.state.store.get('cv_captures', 'negative')
        if 'title' in change:
            assert final['title'] == change['title'] and final['favorite'] is True
            assert final['adjustments']['negative_response'] == .5
        else:
            assert final['adjustments']['exposure'] == .8


def test_auto_colour_toggle_ignores_uncovered_stitch_margins(tmp_path, bridge):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        record = seed(app)
        ramp = np.linspace(.1, .75, 10000).reshape(100, 100)
        samples = np.pad(ramp[..., None] * [.9, 1, .95], ((1, 1), (0, 0), (0, 0)), constant_values=1)
        mask = np.pad(np.ones((100, 100), bool), ((1, 1), (0, 0)))
        values = np.rint(samples * 65535).astype('uint16')
        tifffile.imwrite(app.state.store.path(record['original_path']), values, photometric='rgb')
        record['coverage_path'] = 'coverage.png'
        Image.fromarray(np.uint8(mask) * 255).save(app.state.store.path(record['coverage_path']))
        record['adjustments'] = Adjustments().model_dump()
        record['adjustments']['auto_color'] = auto_color_for(to_float(values), mask,dpi=record['dpi'])
        assert record['adjustments']['auto_color'] != auto_color_for(to_float(values),dpi=record['dpi'])
        app.state.store.save('cv_captures', record)
        endpoint = '/api/cyberview/captures/negative/auto-color'
        assert client.post(endpoint, json={'enabled': False}).status_code == 200
        result = client.post(endpoint, json={'enabled': True})
        assert result.status_code == 200, result.text
        assert result.json()['adjustments']['auto_color'] == record['adjustments']['auto_color']
