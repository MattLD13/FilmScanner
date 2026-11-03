"""Planned roll acquisition against the synthetic bridge; never device evidence."""
import hashlib
import threading

from fastapi.testclient import TestClient
import pytest
import tifffile

from services.api import cyberview_routes
from services.api.main import create_app
from services.scanner_host.native import NativeAflBridge
from services.scanner_host.backend import ScannerError
from services.imaging import acquisition_plan
from test_frame_align_api import strip_bridge, native, wait_session, wait_for_event, held_until
from test_workflow import login


@pytest.fixture
def planned_bridge(strip_bridge, monkeypatch):
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS', '1')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '2')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '34.5')
    monkeypatch.setenv('FAKE_FRAME_OFFSET_MM', '0')
    events = []
    original_scan, original_film = NativeAflBridge.scan, NativeAflBridge.film

    async def scan(self, out, count, on_event, until_end=False):
        events.append(('scan', self.options['dpi'], str(out)))
        return await original_scan(self, out, count, on_event, until_end)

    async def film(self, action, *args, **kwargs):
        events.append(('film', action))
        return await original_film(self, action, *args, **kwargs)

    monkeypatch.setattr(NativeAflBridge, 'scan', scan)
    monkeypatch.setattr(NativeAflBridge, 'film', film)
    return events


def highres(events):
    return [item for item in events if item[:2] == ('scan', 1800)]


@pytest.mark.parametrize('counter_after,strong_match,should_complete',[(1,True,True),(2,True,False),(None,True,False),(1,False,False)])
def test_strip_boundary_requires_fresh_optical_witness_and_matching_counter(
        tmp_path,planned_bridge,monkeypatch,counter_after,strong_match,should_complete):
    native(monkeypatch,actions=('next','previous','nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','1')
    failed={'next':False}
    original_film=NativeAflBridge.film
    original_scan=NativeAflBridge.scan
    original_match=acquisition_plan.register_preview
    async def film(self,action,*args,**kw):
        try:return await original_film(self,action,*args,**kw)
        except ScannerError:
            if action=='next':failed['next']=True
            raise
    async def scan(self,out,*args,**kw):
        result=await original_scan(self,out,*args,**kw)
        if 'end-boundary-' in str(out):
            self.last_frame_position=counter_after
        return result
    def match(a,b,*args,**kw):
        if not failed['next']:return original_match(a,b,*args,**kw)
        if not strong_match:raise ValueError('UNVERIFIED_PREVIEW_ALIGNMENT: ambiguous end witness')
        return {'verified':True,'dx':6.07,'dy':-.28,'peak':.23,'peak_ratio':12.8,'search_radius_px':47.24}
    monkeypatch.setattr(NativeAflBridge,'film',film)
    monkeypatch.setattr(NativeAflBridge,'scan',scan)
    monkeypatch.setattr(acquisition_plan,'register_preview',match)
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        response=client.post('/api/cyberview/scan-all-verified',json={'end_action':'return_to_frame_1','expected_frames':1})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=60)
        assert (session['state']=='complete') is should_complete,session
        assert session['completed']==1
        sources=session['retained_sources']
        paths=[item['path'] for item in sources]
        assert next(i for i,p in enumerate(paths) if 'advance-reference-01' in p)<next(i for i,p in enumerate(paths) if 'end-boundary' in p)
        boundary=session['end_boundary_verification']
        if should_complete:
            assert boundary['verified'] is True and boundary['vendor_counter_unchanged'] is True
            assert boundary['stationary_within_three_preview_pixels'] is False
            assert 'advance-reference-01' in boundary['reference_source']['path']
            assert session['transport']['returned_to_first'] is True
        else:
            assert boundary['verified'] is False
            assert 'end_action_result' not in session
            assert session['transport']['position_known'] is False
        assert all(app.state.store.path(item['path']).exists() for item in sources)


def test_roll_scan_acquires_in_place_and_hold_does_not_require_previous(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'In place', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=120)
        assert session['state'] == 'complete' and session['completed'] == 2, session
        first_next = next(i for i, event in enumerate(planned_bridge) if event == ('film', 'next'))
        assert highres(planned_bridge[:first_next]), planned_bridge
        after_first_next = planned_bridge[first_next + 1:]
        second_full = next(i for i, event in enumerate(after_first_next) if event[:2] == ('scan', 1800))
        assert any(event[:2] == ('scan', 300) for event in after_first_next[:second_full])
        assert ('film', 'previous') not in planned_bridge
        assert not any(event == ('film', 'eject_forward') for event in planned_bridge)
        assert session['transport']['fine_step_offset'] == 0
        assert session['transport']['position_known'] is True
        assert session['acquisition_exposure']
        first_exposure=session['acquisition_exposure'][0]
        assert len(first_exposure['measured'])==3
        assert first_exposure['next_exposure'][2]>first_exposure['next_exposure'][0]
        assert all(50<=value<=300 for value in first_exposure['next_exposure'])
        saved=client.get('/api/cyberview/captures').json()['captures']
        finals=[item for item in saved if item['purpose'] in ('scan','stitched')]
        assert finals
        for item in finals:
            assert item['adjustments']['film_profile'] is None
            assert item['display_suggestion']['reference_used'] is False
            assert item['adjustments']['gamma']==1.2
            assert .85<=item['adjustments']['white_point']<=1


def test_only_selected_end_action_requires_its_transport_capability(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Return unavailable'})
        assert response.status_code == 409, response.text
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Eject unavailable', 'end_action': 'eject_forward'})
        assert response.status_code == 409, response.text
        assert not planned_bridge


def test_roll_scan_can_eject_forward_without_backward_positioning(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge', 'eject_forward'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Eject strip', 'end_action': 'eject_forward','expected_frames':1})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete', session
        assert planned_bridge[-1] == ('film', 'eject_forward')
        assert ('film', 'previous') not in planned_bridge


def test_wide_frame_uses_at_most_two_archival_tiles_and_retains_them(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    root = tmp_path / 'library'
    with TestClient(create_app(root)) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Two tiles', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=120)
        assert session['state'] == 'complete' and session['completed'] == 1, session
        assert len(highres(planned_bridge)) == 2, planned_bridge
        captures = client.get('/api/cyberview/captures').json()['captures']
        final = next(item for item in captures if item['purpose'] == 'stitched')
        sources = final['derived']['sources']
        assert len(sources) == 2
        for source in sources:
            path = root / source['path']
            assert path.exists()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
        assert final['coverage_verification']['verified']
        assert session['transport']['fine_step_offset'] == 0


def test_unverified_low_resolution_borders_stop_before_archival_acquisition(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '70')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'No border', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'error', session
        assert not highres(planned_bridge), planned_bridge
        assert any(item[:2] == ('scan', 300) for item in planned_bridge)
        assert list((tmp_path / 'library' / 'cyberview').rglob('*.tif'))


def test_favorite_seek_gets_a_local_preview_before_archival_capture(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'previous', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '3')
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'roll': 'Seek then verify', 'scope': 'all', 'dpi': 300,'expected_frames':3})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client, timeout=90)
        assert preview_session['state'] == 'complete', preview_session
        captures = client.get('/api/cyberview/captures').json()['captures']
        selected = next(item for item in captures if item['purpose'] == 'roll_preview' and item['index'] == 2)
        client.patch(f"/api/cyberview/captures/{selected['id']}", json={'favorite': True})
        planned_bridge.clear()
        response = client.post('/api/cyberview/scan-favorites', json={
            'roll': 'Seek then verify', 'preview_session_id': preview_session['id'],
            'preview_ids': [selected['id']], 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete', session
        seek = next(i for i, event in enumerate(planned_bridge) if event == ('film', 'previous'))
        full = next(i for i, event in enumerate(planned_bridge) if event[:2] == ('scan', 1800))
        assert any(item[:2] == ('scan', 300) for item in planned_bridge[seek + 1:full])
        assert len(highres(planned_bridge)) <= 2


def test_favorites_hold_current_frame_needs_no_backward_gate_but_earlier_frame_does(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/preview-roll', json={'roll': 'Current favorite', 'scope': 'all', 'dpi': 300,'expected_frames':2})
        assert response.status_code == 200, response.text
        preview_session = wait_session(client, timeout=90)
        assert preview_session['state'] == 'complete' and preview_session['completed'] == 2, preview_session
        previews = {item['index']: item for item in client.get('/api/cyberview/captures').json()['captures']
                    if item['purpose'] == 'roll_preview'}
        for preview in previews.values():
            response = client.patch(f"/api/cyberview/captures/{preview['id']}", json={'favorite': True})
            assert response.status_code == 200, response.text
        planned_bridge.clear()
        payload = {'roll': 'Current favorite', 'preview_session_id': preview_session['id'], 'end_action': 'hold_at_end'}
        response = client.post('/api/cyberview/scan-favorites', json=payload | {'preview_ids': [previews[1]['id']]})
        assert response.status_code == 409, response.text
        assert not planned_bridge, planned_bridge
        response = client.post('/api/cyberview/scan-favorites', json=payload | {'preview_ids': [previews[2]['id']]})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete' and session['completed'] == 1, session
        assert session['transport']['current_preview_index'] == 2
        assert ('film', 'previous') not in planned_bridge
        assert len(highres(planned_bridge)) == 1


def test_failed_archival_alignment_preserves_tiles_without_more_highres_probes(tmp_path, planned_bridge, monkeypatch):
    from services.imaging import acquisition_plan

    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')

    def reject_alignment(*args, **kwargs):
        raise ValueError('UNVERIFIED_STITCH_ALIGNMENT: synthetic ambiguity')

    monkeypatch.setattr(acquisition_plan, 'stitch_planned', reject_alignment)
    root = tmp_path / 'library'
    with TestClient(create_app(root)) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Failed seam', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=120)
        assert session['state'] == 'error' and 'UNVERIFIED_STITCH_ALIGNMENT' in session['error'], session
        assert len(highres(planned_bridge)) == 2, planned_bridge
        full_tiles = [path for path in (root / 'cyberview').rglob('*.tif')
                      if tifffile.imread(path).shape[1] > 2000]
        assert len(full_tiles) >= 2, full_tiles
        assert ('film', 'next') not in planned_bridge


def test_failed_fine_move_marks_transport_unknown_and_does_not_advance(tmp_path, planned_bridge, monkeypatch):
    from services.scanner_host.backend import ScannerError

    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    original_control = NativeAflBridge.control

    async def fail_nudge(self, action, *args, **kwargs):
        if action == 'nudge':
            raise ScannerError('Synthetic uncertain nudge result')
        return await original_control(self, action, *args, **kwargs)

    monkeypatch.setattr(NativeAflBridge, 'control', fail_nudge)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Uncertain move', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        session = wait_session(client, timeout=90)
        assert session['state'] == 'error', session
        assert session['transport']['position_known'] is False
        assert not highres(planned_bridge)
        assert ('film', 'next') not in planned_bridge


def test_completed_internal_border_search_is_not_reported_as_completed_roll(tmp_path, planned_bridge, monkeypatch):
    native(monkeypatch, actions=('next', 'nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    entered, release = threading.Event(), threading.Event()
    original_register = cyberview_routes.register
    child_events = []

    def register(app, store, publish):
        async def controlled_publish(event):
            child = event.get('session') or {}
            if event.get('type') == 'cyberview_session' and child.get('child_state') == 'complete':
                child_events.append(child)
                entered.set()
                await held_until(release)
            await publish(event)
        return original_register(app, store, controlled_publish)

    monkeypatch.setattr(cyberview_routes, 'register', register)
    with TestClient(create_app(tmp_path / 'library')) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Child status', 'end_action': 'hold_at_end'})
        assert response.status_code == 200, response.text
        try:
            wait_for_event(entered)
            child = client.get('/api/cyberview/status').json()['session']
            assert child['child_state'] == 'complete' and child['state'] == 'saving'
            assert child_events[0]['state'] == 'saving'
            assert not highres(planned_bridge)
        finally:
            release.set()
        session = wait_session(client, timeout=90)
        assert session['state'] == 'complete' and session['completed'] == 1, session


def test_cancel_during_planned_stitch_preserves_tiles_and_prevents_end_transport(tmp_path, planned_bridge, monkeypatch):
    from services.imaging import acquisition_plan

    native(monkeypatch, actions=('next', 'nudge', 'eject_forward'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES', '1')
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM', '37.2')
    entered, release = threading.Event(), threading.Event()
    original_stitch, original_control = acquisition_plan.stitch_planned, NativeAflBridge.control

    def controlled_stitch(*args, **kwargs):
        entered.set()
        assert release.wait(10), 'The synthetic stitch was not released'
        return original_stitch(*args, **kwargs)

    async def control(self, action, on_event=None, value=None):
        planned_bridge.append(('control', action, value))
        return await original_control(self, action, on_event, value)

    monkeypatch.setattr(acquisition_plan, 'stitch_planned', controlled_stitch)
    monkeypatch.setattr(NativeAflBridge, 'control', control)
    root = tmp_path / 'library'
    with TestClient(create_app(root)) as client:
        login(client)
        response = client.post('/api/cyberview/scan-all-verified', json={'roll': 'Cancel seam', 'end_action': 'eject_forward'})
        assert response.status_code == 200, response.text
        try:
            assert entered.wait(60), 'The synthetic stitch did not reach its controlled boundary'
            mark = len(planned_bridge)
            response = client.post('/api/cyberview/cancel')
            assert response.status_code == 200, response.text
            assert response.json()['cancel_requested'] is True
        finally:
            release.set()
        session = wait_session(client, timeout=90)
        assert session['state'] == 'cancelled', session
        assert len(highres(planned_bridge)) == 2
        assert planned_bridge[mark:] == [], planned_bridge[mark:]
        tiles = [source for source in session['retained_sources'] if source['dpi'] == 1800]
        assert len(tiles) == 2
        assert all((root / source['path']).exists() for source in tiles)
        assert 'end_action_result' not in session
