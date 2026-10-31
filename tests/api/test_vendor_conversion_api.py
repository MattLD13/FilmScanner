"""Versioned AFL conversion API, with synthetic profiles and no scanner access."""
from io import BytesIO
import json

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile

from services.api.main import create_app
from services.imaging import vendor_negative, filmterms
from test_cyberview import bridge
from test_negative_balance import seed
from test_workflow import login


def install(store):
    film = ('FilmName Fixture stock;\nFilmMfgr Fixture;\nFilmClass NEG;\nFilmLut\n' +
            '\n'.join(f'{i} {i} {i}' for i in range(256)) + ';\n' +
            'FilmMatR 1 0 0 0;\nFilmMatG 0 1 0 0;\nFilmMatB 0 0 1 0;').encode()
    gamma = ('FilmLut\n' + '\n'.join(f'{i} {i} {i}' for i in range(4096)) + ';').encode()
    profile = vendor_negative.create(film, gamma, 'fixture.ft', 'Fixture')
    filmterms.remember(store, profile)
    return profile


def test_vendor_recipe_exports_and_restarts_without_install_or_hardware(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv('FRAME_FILMTERM_DIRS', str(tmp_path/'missing'))
    root = tmp_path/'library'
    app = create_app(root)
    with TestClient(app) as client:
        login(client)
        profile = install(app.state.store)
        record = seed(app)
        endpoint = '/api/cyberview/captures/negative'
        original = client.get(endpoint+'/export/original').content
        assert client.get('/api/film-profiles').json()['count'] == 0
        listing = client.get('/api/film-profiles?include_reference=true&include_vendor=true').json()
        assert listing['profiles'][0]['kind'] == 'vendor-negative'
        adjust = record['adjustments'] | {'film_profile': profile['id'], 'auto_color': None}
        response = client.patch(endpoint, json={'adjustments': adjust})
        assert response.status_code == 200, response.text
        preview = client.get(endpoint+'/profile-preview', params={'profile_id': profile['id'], 'invert':True})
        assert preview.status_code == 200
        assert client.get(endpoint+'/rendered/thumb').status_code == 200
        data = client.get(endpoint+'/export/tiff').content
        with tifffile.TiffFile(BytesIO(data)) as tif:
            assert tif.asarray().dtype == np.uint16
            assert json.loads(tif.pages[0].description)['adjustments']['film_profile'] == profile['id']
        assert client.get(endpoint+'/export/original').content == original
        assert not bridge.exists()
    with TestClient(create_app(root)) as client:
        login(client)
        assert client.get(endpoint+'/export/tiff').content == data


@pytest.mark.parametrize('kind,invert', [('cyberview-processed-positive', True), ('vendor-calibrated-transmission', False)])
def test_incompatible_vendor_conversion_rejected_before_recipe_change(tmp_path, bridge, kind, invert):
    app = create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        profile = install(app.state.store)
        record = seed(app,kind=kind)
        edits = record['adjustments'] | {'film_profile':profile['id'],'invert':invert}
        result = client.patch('/api/cyberview/captures/negative',json={'adjustments':edits})
        assert result.status_code == 422
        assert app.state.store.get('cv_captures','negative') == record
