"""Optional processing/acquisition controls tested with synthetic images only."""
from io import BytesIO
import hashlib
import json

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile

from services.api.main import create_app
from services.api import cyberview_routes
from services.imaging import negative, scan_filters
from services.scanner_host import workspace
from services.scanner_host.native import NativeAflBridge
from test_frame_align_api import native, strip_bridge, wait_session
from test_workflow import login


@pytest.fixture
def feature_client(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/cyberview/scan', json={'roll': 'Features', 'count': 1})
        assert response.status_code == 200, response.text
        session = wait_session(client)
        assert session['state'] == 'complete', session
        capture, = client.get('/api/cyberview/captures').json()['captures']
        yield client, app, capture


def test_disabled_filters_preserve_legacy_pipeline_exactly(monkeypatch):
    image = np.random.default_rng(8).uniform(.05, .95, (45, 63, 3)).astype(np.float32)
    recipe = {'invert': True, 'film_base': [.9, .7, .5], 'negative_response': .5}
    expected = negative.invert(image, recipe['film_base'], recipe['negative_response'])
    def forbidden(*args, **kwargs):
        raise AssertionError('Disabled filters must not run')
    monkeypatch.setattr(scan_filters, 'process', forbidden)
    actual = cyberview_routes.before_levels(image, cyberview_routes.Adjustments(**recipe))
    assert np.array_equal(actual, expected)


def test_filter_export_changes_pixels_and_metadata_but_preserves_original(feature_client):
    client, app, capture = feature_client
    url = f"/api/cyberview/captures/{capture['id']}"
    original = app.state.store.path(capture['original_path'])
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    before = tifffile.imread(BytesIO(client.get(url + '/export/tiff').content))
    edits = capture['adjustments'] | {'color_restoration': .8, 'grain_reduction': .7, 'sharpening': .6}
    response = client.patch(url, json={'adjustments': edits})
    assert response.status_code == 200, response.text
    exported = client.get(url + '/export/tiff')
    assert exported.status_code == 200, exported.text
    with tifffile.TiffFile(BytesIO(exported.content)) as tif:
        after = tif.asarray()
        metadata = json.loads(tif.pages[0].description)
    assert np.any(before != after)
    assert metadata['original_sha256'] == digest == capture['sha256']
    assert metadata['adjustments']['grain_reduction'] == .7
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    info = client.get(url + '/export/metadata').json()
    assert info['adjustments']['sharpening'] == .6
    assert info['precision_measurement']['effective_sensor_bits'] is None
    assert info['precision_measurement']['measured_source_sha256'] == digest


def test_processing_preview_applies_filters_once_and_matches_legacy_alias(feature_client, monkeypatch):
    client, app, capture = feature_client
    url = f"/api/cyberview/captures/{capture['id']}"
    params = {'invert': 'true', 'negative_response': .5, 'color_restoration': .8,
              'grain_reduction': .6, 'sharpening': .7}
    raw = cyberview_routes.to_float(cyberview_routes.read_original(app.state.store.path(capture['original_path'])))
    adjust = cyberview_routes.Adjustments(invert=True, negative_response=.5,
                 color_restoration=.8, grain_reduction=.6, sharpening=.7)
    expected = cyberview_routes.jpeg(cyberview_routes.before_levels(raw, adjust), cyberview_routes.PREVIEW_EDGE)
    before = client.get(url + '/processing-preview').content
    calls = []
    process = scan_filters.process
    def tracked(samples, settings=None):
        calls.append(settings)
        return process(samples, settings)
    monkeypatch.setattr(scan_filters, 'process', tracked)
    actual = client.get(url + '/processing-preview', params=params)
    assert actual.status_code == 200, actual.text
    assert actual.content == expected and actual.content != before
    assert len(calls) == 1
    alias = client.get(url + '/profile-preview', params=params)
    assert alias.status_code == 200 and alias.content == expected
    assert len(calls) == 2


@pytest.mark.parametrize('field,value', [('color_restoration', -1), ('grain_reduction', 1.01), ('sharpening', 'nan')])
def test_unsafe_filter_values_rejected_by_edit_and_preview(feature_client, field, value):
    client, app, capture = feature_client
    url = f"/api/cyberview/captures/{capture['id']}"
    response = client.patch(url, json={'adjustments': capture['adjustments'] | {field: value}})
    assert response.status_code == 422, response.text
    response = client.get(url + '/processing-preview', params={field: value})
    assert response.status_code == 422, response.text


def test_repeat_samples_make_actual_acquisitions_and_retain_sources(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    scans = []
    scan = NativeAflBridge.scan
    async def tracked(self, out, count, on_event, until_end=False):
        scans.append(self.options['dpi'])
        return await scan(self, out, count, on_event, until_end)
    monkeypatch.setattr(NativeAflBridge, 'scan', tracked)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Repeats', 'repeat_samples': 2, 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete', session
        assert scans.count(1800) == 2
        final = next(item for item in client.get('/api/cyberview/captures').json()['captures'] if item['purpose'] == 'scan')
        tile, = final['derived']['sources']
        assert tile['derived'] and len(tile['repeat_sources']) == 2
        normalization=tile['repeat_processing']['offset_normalization']
        assert normalization['applied'] is True and normalization['reference_source_index']==0
        assert normalization['measurement_pixel_count']>=64
        assert len(normalization['subtracted_rgb_deltas'])==2
        assert normalization['multiplicative_gain_applied'] is False
        assert session['derived_tiles'][0]['repeat_processing']==tile['repeat_processing']
        with tifffile.TiffFile(app.state.store.path(tile['path'])) as saved:
            manifest=json.loads(saved.pages[0].description)
        assert manifest['repeat_processing']==tile['repeat_processing']
        assert manifest['source_sha256']==[source['sha256'] for source in tile['repeat_sources']]
        for source in tile['repeat_sources']:
            path = app.state.store.path(source['path'])
            assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
            assert source['precision_measurement']['effective_sensor_bits'] is None
            assert source['precision_measurement']['measured_source_sha256'] == source['sha256']
            assert source['requested_settings']['auto_exposure'] is False


def test_ambiguous_repeat_alignment_retains_originals_without_success(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    def reject(*args, **kwargs):
        raise ValueError('UNVERIFIED_STITCH_ALIGNMENT: synthetic ambiguous repeat')
    monkeypatch.setattr(scan_filters, 'aligned_mean', reject)
    app = create_app(tmp_path / 'library')
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'repeat_samples': 2, 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'error' and 'ambiguous repeat' in session['error'], session
        sources = [item for item in session['retained_sources'] if item['dpi'] == 1800]
        assert len(sources) == 2 and all(app.state.store.path(item['path']).exists() for item in sources)
        assert not any(item['purpose'] in ('scan', 'stitched') for item in client.get('/api/cyberview/captures').json()['captures'])


@pytest.mark.parametrize('frame_width,expected_tiles,expected_auto',[(37.2,2,False),(34.5,1,True)])
def test_archival_tile_exposure_is_frozen_and_vendor_auto_is_only_used_for_single_tiles(
        tmp_path,strip_bridge,monkeypatch,frame_width,expected_tiles,expected_auto):
    native(monkeypatch,actions=('next','nudge','auto_exposure'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM',str(frame_width))
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM','0')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','1')
    archival=[]
    original=NativeAflBridge.scan
    async def track(self,out,count,on_event,until_end=False):
        if self.options['dpi']==1800:
            archival.append(json.loads(json.dumps(self.options)))
        return await original(self,out,count,on_event,until_end)
    monkeypatch.setattr(NativeAflBridge,'scan',track)
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        settings=client.get('/api/cyberview/workspace').json()['settings']
        response=client.put('/api/cyberview/workspace',json=settings|{'auto_exposure':True})
        assert response.status_code==200,response.text
        response=client.post('/api/cyberview/scan-all-verified',json={'roll':'Exposure lock','end_action':'hold_at_end'})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=90)
        assert session['state']=='complete',session
        assert len(archival)==expected_tiles
        assert all(options==archival[0] for options in archival)
        assert all(options['auto_exposure'] is expected_auto for options in archival)
        assert archival[0]['exposure'][2]>archival[0]['exposure'][0], 'Use measured film-base seeds'
        # Locking a wide frame must not silently change the user's single-frame preference.
        assert client.get('/api/cyberview/workspace').json()['settings']['auto_exposure'] is True
        final=next(item for item in client.get('/api/cyberview/captures').json()['captures'] if item['purpose'] in ('scan','stitched'))
        policy=final['derived']['archival_exposure']
        assert policy['requested_vendor_auto_exposure'] is True
        assert policy['settings']==archival[0] and final['requested_settings']==archival[0]
        assert policy['seed_source']=='local_film_base'
        assert (policy['mode']=='fixed_manual') is (not expected_auto)
        assert policy in session['frame_exposure_policies']
        assert all(source['requested_settings']==archival[0] for source in final['derived']['sources'])
        for source in final['derived']['sources']:
            assert hashlib.sha256(app.state.store.path(source['path']).read_bytes()).hexdigest()==source['sha256']


def test_wide_scan_rejects_an_auto_exposure_report_despite_locked_request(tmp_path,strip_bridge,monkeypatch):
    native(monkeypatch,actions=('next','nudge','auto_exposure'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM','37.2')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM','0')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','1')
    original=NativeAflBridge.scan
    async def wrong_report(self,*args,**kw):
        result=await original(self,*args,**kw)
        if self.options['dpi']==1800:
            assert self.options['auto_exposure'] is False
            result[0]['vendor_auto_exposure']=True
        return result
    monkeypatch.setattr(NativeAflBridge,'scan',wrong_report)
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        response=client.post('/api/cyberview/scan-all-verified',json={'end_action':'hold_at_end'})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=90)
        assert session['state']=='error' and 'UNVERIFIED_EXPOSURE_LOCK' in session['error']
        originals=[source for source in session['retained_sources'] if source['dpi']==1800]
        assert len(originals)==1
        source=originals[0]
        assert hashlib.sha256(app.state.store.path(source['path']).read_bytes()).hexdigest()==source['sha256']
        assert not any(item['purpose'] in ('scan','stitched') for item in client.get('/api/cyberview/captures').json()['captures'])


def test_frame_origin_is_software_only_goto_translates_and_release_resets(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge', 'goto'))
    instances, moves = [], []
    scan = NativeAflBridge.scan
    async def tracked_scan(self, *args, **kwargs):
        result = await scan(self, *args, **kwargs)
        self.last_frame_position = 7
        instances.append(self)
        return result
    async def fake_goto(self, action, on_event=None, frame=None):
        moves.append((action, frame))
    monkeypatch.setattr(NativeAflBridge, 'scan', tracked_scan)
    monkeypatch.setattr(NativeAflBridge, 'film', fake_goto)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        assert client.post('/api/cyberview/frame-origin', json={'frame': 1}).status_code == 409
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        response = client.post('/api/cyberview/frame-origin', json={'frame': 1})
        assert response.status_code == 200, response.text
        assert response.json()['software_only'] and not response.json()['film_moved'] and not moves
        with monkeypatch.context() as busy:
            busy.setattr(NativeAflBridge, 'busy', property(lambda self: True))
            assert client.post('/api/cyberview/frame-origin', json={'frame': 1}).status_code == 409
        response = client.post('/api/cyberview/film', json={'action': 'goto', 'frame': 3, 'acknowledged': True})
        assert response.status_code == 200, response.text
        assert moves == [('goto', 9)]
        assert client.post('/api/cyberview/frame-origin', json={'frame': 2}).status_code == 422
        assert client.post('/api/cyberview/release').status_code == 200
        assert client.post('/api/cyberview/frame-origin', json={'frame': 1}).status_code == 409
        client.post('/api/cyberview/scan', json={'count': 1})
        assert wait_session(client)['state'] == 'complete'
        response = client.post('/api/cyberview/film', json={'action': 'goto', 'frame': 2, 'acknowledged': True})
        assert response.status_code == 200, response.text
        assert moves[-1] == ('goto', 2)


def test_new_hardware_actions_are_gated_and_repeat_count_rejects_unsupported(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        settings = client.get('/api/cyberview/workspace').json()['settings']
        assert settings['auto_exposure'] is False
        assert workspace.validated_options(settings | {'auto_exposure': True}) is False
        response = client.post('/api/cyberview/control', json={'action': 'realign', 'acknowledged': True})
        assert response.status_code == 409, response.text
        for route in ('scan-frame', 'scan-all-verified'):
            response = client.post('/api/cyberview/' + route, json={'repeat_samples': 3, 'acknowledged': True})
            assert response.status_code == 422, response.text


def test_verified_realign_invalidates_previous_border_position(tmp_path, strip_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge', 'realign'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    controls = []
    original_control = NativeAflBridge.control
    async def simulated_realign(self, action, on_event=None, value=None):
        if action == 'realign':
            controls.append(action)
            return
        return await original_control(self, action, on_event, value)
    monkeypatch.setattr(NativeAflBridge, 'control', simulated_realign)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/find-borders', json={'roll': 'Alignment generation', 'acknowledged': True})
        assert response.status_code == 200, response.text
        assert wait_session(client)['state'] == 'complete'
        response = client.post('/api/cyberview/control', json={'action': 'realign', 'acknowledged': True})
        assert response.status_code == 200 and controls == ['realign'], response.text
        response = client.post('/api/cyberview/scan-frame', json={'roll': 'Alignment generation', 'acknowledged': True})
        assert response.status_code == 409, response.text
        assert 'position changed' in response.text.lower()
