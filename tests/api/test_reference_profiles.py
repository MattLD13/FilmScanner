import hashlib
from io import BytesIO
import json

from fastapi.testclient import TestClient
import numpy as np
import tifffile
import pytest

from services.api.cyberview_routes import Adjustments
from services.api.main import create_app
from services.imaging import filmterms, reference_tone
from test_cyberview import bridge
from test_workflow import login


def profile():
    table = np.linspace(0, 1, 4096)[:, None] ** [1.3, 1.5, 1.4]
    return reference_tone.identify({'kind': 'reference-tone', 'name': 'Synthetic reference profile',
            'maker': 'Test fixture', 'film_class': 'negative', 'rows': 4096, 'scale': 4095,
            'lut': (table * 4095).tolist(), 'matrix': np.column_stack((np.eye(3), np.zeros(3))).tolist(),
            'source_file': 'fixture', 'source_folder': 'Reference profiles', 'input_response': .5})


def test_private_profile_lists_and_renders_without_vendor_install(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS', str(tmp_path / 'absent'))
    root = tmp_path / 'library'
    app = create_app(root)
    p = profile()
    with TestClient(app) as client:
        filmterms.remember(app.state.store, p)
        assert client.get('/api/film-profiles').status_code == 401
        login(client)
        assert client.get('/api/film-profiles').json()['count'] == 0
        listing = client.get('/api/film-profiles?include_reference=true').json()
        assert listing['count'] == 1
        assert listing['profiles'][0]['kind'] == 'reference-tone'
        assert listing['profiles'][0]['input_response'] == .5
        raw = np.linspace(.05, .85, 300).reshape(10, 10, 3)
        path = app.state.store.path('negative.tif')
        tifffile.imwrite(path, np.rint(raw * 65535).astype('uint16'), photometric='rgb')
        original = path.read_bytes()
        record = {'id': 'test', 'title': 'Reference test', 'created_at': 1, 'dpi': 1800,
                  'original_path': 'negative.tif', 'sha256': hashlib.sha256(original).hexdigest(),
                  'adjustments': Adjustments(invert=True, negative_response=.5, film_profile=p['id']).model_dump()}
        app.state.store.save('cv_captures', record)
        output = client.get('/api/cyberview/captures/test/export/tiff').content
        with tifffile.TiffFile(BytesIO(output)) as tif:
            assert tif.asarray().dtype == np.uint16
            assert json.loads(tif.pages[0].description)['adjustments']['film_profile'] == p['id']
        assert client.get('/api/cyberview/captures/test/export/original').content == original
        assert client.get('/api/cyberview/captures/test/profile-preview',
                          params={'profile_id': p['id'], 'invert': True, 'negative_response': .5}).status_code == 200
        assert not bridge.exists()
    with TestClient(create_app(root)) as client:
        login(client)
        assert client.get('/api/film-profiles?include_reference=true').json()['count'] == 1
        assert client.get('/api/cyberview/captures/test/export/tiff').content == output


def test_balance_preserves_reference_appearance_without_second_auto_colour(tmp_path, bridge):
    from test_negative_balance import seed
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        p = profile()
        filmterms.remember(app.state.store, p)
        record = seed(app)
        record['adjustments']['film_profile'] = p['id']
        app.state.store.save('cv_captures', record)
        result = client.post('/api/cyberview/captures/negative/balance-negative')
        assert result.status_code == 200, result.text
        assert result.json()['adjustments']['film_profile'] == p['id']
        assert result.json()['adjustments']['auto_color'] is None


def test_malformed_cached_profile_does_not_break_listing(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS', str(tmp_path / 'absent'))
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        p = profile()
        p['lut'][100] = [5000, -2, 4000]
        path = filmterms.cache_path(app.state.store, p['id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p))
        app.state.store.path('film_profiles/broken.json').write_text('{bad')
        login(client)
        assert client.get('/api/film-profiles?include_reference=true').json()['count'] == 0


@pytest.mark.parametrize('damage', ['matrix', 'scale', 'nan', 'changed_curve', 'wrong_path', 'array', 'null'])
def test_corrupt_reference_cache_is_rejected_before_listing_or_render(tmp_path, bridge, monkeypatch, damage):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS', str(tmp_path / 'absent'))
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        p = profile()
        identity = p['id']
        if damage == 'matrix':
            del p['matrix']
        elif damage == 'scale':
            p['scale'] = 0
        elif damage == 'nan':
            p['matrix'][0][0] = float('nan')
        elif damage == 'changed_curve':
            p['lut'][200][0] = (p['lut'][199][0] + p['lut'][200][0]) / 2
        elif damage == 'wrong_path':
            identity = 'f' * 16
        path = filmterms.cache_path(app.state.store, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([] if damage == 'array' else None if damage == 'null' else p))
        login(client)
        assert client.get('/api/film-profiles?include_reference=true').json()['count'] == 0
        with pytest.raises(ValueError):
            filmterms.load(app.state.store, identity)
