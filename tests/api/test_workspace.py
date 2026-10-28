"""Scan workspace: film profiles, prescan, frame selection and simulated scan settings.

The .ft fixtures below are written by the tests with fictitious values in the
CyberView film-term layout; no vendor profile is part of the repository.
"""
import asyncio
from io import BytesIO
import shutil

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from services.api.main import create_app
from services.imaging import filmterms
from services.scanner_host.backend import SimulatedScannerBackend
from test_workflow import login, new_roll, ready, wait_scan


def ft_text(name='Test Negative', film_class='NEG', rows=256, curve=lambda v: v, matrix=True, scale=255):
    table = '\n'.join('\t'.join(str(min(scale, round(curve(i * scale / (rows - 1))))) for _ in range(3)) for i in range(rows))
    mat = ('FilmMatR\t1.0\t0.0\t0.0\t0.0;\nFilmMatG\t0.0\t1.0\t0.0\t0.0;\nFilmMatB\t0.0\t0.0\t1.0\t0.0;\n' if matrix else '')
    return (f'# Version 1.1;\n\nFilmClass\t\t{film_class};\nFilmMfgr\t\tFixture;\nFilmName\t\t{name};\n'
            f'FilmLevel\t\t0\t0\t0;\nFilmBalance\t\t100\t200\t300;\nFilmLut\t\t\n{table}\n{mat}')


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    root = tmp_path / 'cyberview' / 'GAMMA'
    (root / 'Original').mkdir(parents=True)
    (root / 'Original' / 'Linear.ft').write_text(ft_text('Linear'), encoding='latin-1')
    (root / 'Original' / 'Half.ft').write_text(ft_text('Half', curve=lambda v: v / 2), encoding='latin-1')
    (root / 'copy').mkdir()
    shutil.copy(root / 'Original' / 'Linear.ft', root / 'copy' / 'Linear.ft')
    (root / 'Original' / 'broken.ft').write_text('FilmClass NEG;\n', encoding='latin-1')
    monkeypatch.setenv('FRAME_FILMTERM_DIRS', str(root))
    return root


def test_parse_reads_class_table_and_matrix_and_defaults_identity():
    # 4096-row reversal tables use a 0..4095 range in the installed files.
    profile = filmterms.parse(ft_text(rows=4096, film_class='REV', matrix=False, scale=4095))
    assert (profile['film_class'], profile['rows'], profile['scale'], profile['balance']) == ('reversal', 4096, 4095, [100, 200, 300])
    assert profile['matrix'] == [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
    assert profile['lut'][0] == [0, 0, 0] and profile['lut'][-1] == [4095, 4095, 4095]
    values = np.linspace(0, 1, 11).reshape(1, 11, 1).repeat(3, axis=2)
    assert np.allclose(filmterms.apply(values, profile), values, atol=1 / 4095)
    assert filmterms.parse(ft_text(film_class='B&&W'))['film_class'] == 'bw'


def test_parse_accepts_crlf_tab_indented_rows_with_terminating_semicolon():
    # Layout of the files CyberView installs: CRLF, tab-indented rows, ';' after the last row.
    rows = '\r\n'.join(f'\t{i}\t{i}\t{i}' for i in range(256)) + ';'
    text = (f'FilmClass\t\tNEG;\r\nFilmName\t\tFixture CRLF;\r\nFilmLut\t\t\r\n{rows}\r\n'
            'FilmMatR\t1.1   -0.05   -0.05\t0.0;\r\nFilmMatG\t0.0 1.0 0.0 0.0;\r\nFilmMatB\t0.0 0.0 1.0 0.0;\r\n')
    profile = filmterms.parse(text)
    assert profile['rows'] == 256 and profile['lut'][-1] == [255, 255, 255]
    assert profile['matrix'][0] == [1.1, -0.05, -0.05, 0.0]


@pytest.mark.parametrize('text', [ft_text(film_class='XYZ'), ft_text(rows=100), ft_text(curve=lambda v: 255 - v), ft_text(scale=4095),
                                  'FilmName x;\nFilmClass NEG;\n', ''])
def test_parse_rejects_invalid_profiles(text):
    with pytest.raises(ValueError):
        filmterms.parse(text)


def test_apply_identity_and_halving_curves():
    values = np.random.default_rng(1).random((4, 5, 3))
    assert np.allclose(filmterms.apply(values, filmterms.parse(ft_text())), values, atol=1 / 255)
    assert np.allclose(filmterms.apply(values, filmterms.parse(ft_text(curve=lambda v: v / 2))), values / 2, atol=1 / 255)


def test_discover_dedupes_by_content_and_skips_broken_files(profile_dir):
    found = filmterms.discover()
    assert sorted(p['name'] for p in found) == ['Half', 'Linear']
    assert all(len(p['id']) == 16 for p in found)


def test_simulator_window_gains_and_prescan_preview():
    async def run():
        backend = SimulatedScannerBackend(delay=0)
        with pytest.raises(ValueError):
            backend.configure({'left': .9, 'top': 0, 'width': .5, 'height': .5})
        with pytest.raises(ValueError):
            backend.configure(gains=[1, 1, 9])
        backend.configure({'left': .25, 'top': .25, 'width': .5, 'height': .5}, [2, 1, .5])
        await backend.connect(); await backend.initialize(); await backend.calibrate()
        with pytest.raises(Exception):
            await backend.prescan_preview(1)
        await backend.load(3); await backend.prescan()
        assert (await backend.prescan_preview(2)).shape == (64, 96, 3)
        await backend.position_frame(1)
        pixels = await backend.acquire(1)
        reference = SimulatedScannerBackend.transmission_fixture(1)[32:96, 48:144].astype(float)
        assert pixels.shape == (64, 96, 3)
        assert np.array_equal(pixels[..., 1], reference[..., 1].astype(np.uint8))
        assert np.array_equal(pixels[..., 2], np.rint(reference[..., 2] * .5).astype(np.uint8))
    asyncio.run(run())


def test_prescan_select_frames_window_gains_and_profile(tmp_path, profile_dir):
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        listing = client.get('/api/film-profiles').json()
        assert listing['count'] == 2 and 'does not distribute' in listing['note']
        half = next(p['id'] for p in listing['profiles'] if p['name'] == 'Half')
        roll = new_roll(client, film_type='color_negative')
        assert client.post(f"/api/rolls/{roll['id']}/prescan", json={}).status_code == 409   # not connected
        ready(client, roll)
        assert client.post('/api/scanner/connect').status_code == 200
        response = client.post(f"/api/rolls/{roll['id']}/prescan", json={'frame_count': 8, 'film_profile': half})
        assert response.status_code == 200, response.text
        prescan = response.json()['prescan']
        assert len(prescan['frames']) == 8 and prescan['synthetic'] and prescan['film_profile'] == half
        thumb = client.get('/media/' + prescan['frames'][0]['preview_path'])
        assert thumb.status_code == 200 and Image.open(BytesIO(thumb.content)).size == (96, 64)

        base = {'roll_id': roll['id'], 'speed': 'fast', 'frame_count': 8}
        for bad in ({'frames': [2, 2]}, {'frames': [9]}, {'settings': {'dpi': 2400}},
                    {'settings': {'window': {'left': .9, 'top': 0, 'width': .5, 'height': .5}}},
                    {'settings': {'gains': [1, 1, 0]}}):
            assert client.post('/api/scans', json=base | bad).status_code == 422, bad
        assert client.post('/api/scans', json=base | {'settings': {'film_profile': 'f' * 16}}).status_code == 409

        settings = {'dpi': 600, 'bit_depth': 16, 'window': {'left': .25, 'top': .25, 'width': .5, 'height': .5},
                    'gains': [1.2, 1, .8], 'film_profile': half}
        assert client.post('/api/scans', json=base | {'frames': [7, 2, 5], 'settings': settings}).status_code == 200
        state = wait_scan(client)
        assert state['scan']['status'] == 'complete', state['scan']
        frames = sorted((f for f in state['frames'] if f['roll_id'] == roll['id']), key=lambda f: f['index'])
        assert [f['index'] for f in frames] == [2, 5, 7]
        for frame in frames:
            assert frame['edit']['film_profile'] == half
            assert frame['scan_settings']['requested'] and frame['scan_settings']['dpi'] == 600
            assert frame['scan_settings']['delivered'] == '96x64 uint8 synthetic fixture'
            with Image.open(app.state.store.path(frame['original_path'])) as original:
                assert original.size == (96, 64)

        # The profile is cached in the library, so renders survive removal of the CyberView install.
        shutil.rmtree(profile_dir)
        assert client.get('/api/film-profiles').json()['count'] == 0
        assert client.get(f"/api/frames/{frames[0]['id']}/export?format=tiff").status_code == 200
        cleared = client.post(f"/api/frames/{frames[0]['id']}/edit", json={'exposure': .5, 'film_profile': ''})
        assert cleared.status_code == 200 and 'film_profile' not in cleared.json()['edit']
        kept = client.post(f"/api/frames/{frames[1]['id']}/edit", json={'exposure': .5})
        assert kept.status_code == 200 and kept.json()['edit']['film_profile'] == half
