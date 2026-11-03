"""Synthetic failure-path evidence; these tests never command the real scanner."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile

from services.api.main import create_app
from services.imaging import acquisition_plan
from services.scanner_host.cyberview import CyberViewBridge
from services.scanner_host.native import NativeAflBridge
from services.scanner_host.backend import ScannerError
from test_frame_align_api import strip_bridge,native,wait_session
from test_planned_scan_api import planned_bridge,highres
from test_workflow import login


@pytest.mark.parametrize('failure',['timeout','cancel'])
def test_uncertain_nudge_blocks_archival_and_seek_across_restart_until_prescan_and_reindex(
        tmp_path,planned_bridge,monkeypatch,failure):
    native(monkeypatch,actions=('next','previous','nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM','37.2')
    original=CyberViewBridge._exchange;failed=[]
    async def exchange(self,line,*args,**kwargs):
        if line.startswith('film nudge') and not failed:
            failed.append(line)
            if failure=='cancel':
                result=await original(self,line,*args,**kwargs)
                self.cancel_requested=True
                return result
            raise ScannerError('Simulated unacknowledged motor timeout after the driver returned ready')
        return await original(self,line,*args,**kwargs)
    monkeypatch.setattr(CyberViewBridge,'_exchange',exchange)
    root=tmp_path/'library'
    with TestClient(create_app(root)) as c:
        login(c)
        response=c.post('/api/cyberview/find-borders',json={'acknowledged':True})
        assert response.status_code==200,response.text
        session=wait_session(c,timeout=60)
        assert session['state'] in ('error','cancelled') and failed
        assert c.get('/api/cyberview/status').json()['transport_position_uncertain']
        assert not highres(planned_bridge)
        saved=list(root.rglob('source-*.tif'));assert saved
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in saved}
        response=c.post('/api/cyberview/scan',json={'count':1})
        assert response.status_code==409 and 'POSITION_UNCERTAIN' in response.text
        response=c.post('/api/cyberview/find-borders',json={'acknowledged':True})
        assert response.status_code==409 and 'POSITION_UNCERTAIN' in response.text
        response=c.post('/api/cyberview/film',json={'action':'next','acknowledged':True})
        assert response.status_code==409
    with TestClient(create_app(root)) as c:
        login(c)
        assert c.get('/api/cyberview/status').json()['transport_position_uncertain']
        assert c.post('/api/cyberview/scan',json={'count':1}).status_code==409
        c.post('/api/cyberview/prescan',json={}).raise_for_status()
        assert wait_session(c,timeout=60)['state']=='complete'
        assert c.get('/api/cyberview/status').json()['transport_position_uncertain']
        c.post('/api/cyberview/frame-origin',json={'frame':1}).raise_for_status()
        assert not c.get('/api/cyberview/status').json()['transport_position_uncertain']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==d for p,d in before.items())


@pytest.mark.parametrize('action',['confirm_end','retry_advance','abort'])
def test_refused_advance_before_expected_count_keeps_frames_and_waits_for_user(
        tmp_path,planned_bridge,monkeypatch,action):
    native(monkeypatch,actions=('next','previous','nudge'))
    original_film=NativeAflBridge.film;once=[]
    async def film(self,verb,*args,**kwargs):
        if verb=='next' and self.last_frame_position==1 and not once:
            once.append(True);self.set_position_uncertain(True,'synthetic_refused_advance')
            raise ScannerError('The driver did not confirm the requested frame movement')
        return await original_film(self,verb,*args,**kwargs)
    monkeypatch.setattr(NativeAflBridge,'film',film)
    with TestClient(create_app(tmp_path/'library')) as c:
        login(c)
        c.post('/api/cyberview/scan-all-verified',json={'roll':'Early stall','expected_frames':6}).raise_for_status()
        stopped=wait_session(c,timeout=90)
        assert stopped['completed']==1 and stopped['awaiting_end_confirmation']
        assert stopped['warning_code']=='WARNING_EARLY_ADVANCE_REFUSED'
        assert 'end_action_result' not in stopped
        assert ('film','previous') not in planned_bridge
        records=c.get('/api/cyberview/captures').json()['captures']
        final=next(r for r in records if r['session_id']==stopped['id'] and r['purpose'] in ('scan','stitched'))
        before=c.get(f"/api/cyberview/captures/{final['id']}/export/original").content
        response=c.post('/api/cyberview/refused-advance',json={'session_id':stopped['id'],'action':action})
        assert response.status_code==200,response.text
        result=wait_session(c,timeout=90)
        if action=='confirm_end':
            assert result['user_confirmed_end'] and not result['awaiting_end_confirmation']
            assert result['return_verification']['verified']
        elif action=='retry_advance':
            assert result['completed']==2 and result['awaiting_end_confirmation']
            assert result['warning_code']=='WARNING_EARLY_ADVANCE_REFUSED'
            assert len(result['refused_advance_history'])==1
        else:
            assert result['state']=='cancelled' and not result['awaiting_end_confirmation']
            assert 'end_action_result' not in result
            assert ('film','previous') not in planned_bridge
        assert c.get(f"/api/cyberview/captures/{final['id']}/export/original").content==before


def test_counter_return_without_optical_match_does_not_claim_returned_first(tmp_path,planned_bridge,monkeypatch):
    native(monkeypatch,actions=('next','previous','nudge'))
    scan=NativeAflBridge.scan;register=acquisition_plan.register_preview;returning=[]
    async def watched_scan(self,out,*args,**kwargs):
        if 'return-arrival-' in str(out):returning.append(True)
        return await scan(self,out,*args,**kwargs)
    def match(*args,**kwargs):
        if returning:raise ValueError('UNVERIFIED_PREVIEW_ALIGNMENT: returned image is ambiguous')
        return register(*args,**kwargs)
    monkeypatch.setattr(NativeAflBridge,'scan',watched_scan)
    monkeypatch.setattr(acquisition_plan,'register_preview',match)
    with TestClient(create_app(tmp_path/'library')) as c:
        login(c)
        c.post('/api/cyberview/scan-all-verified',json={'expected_frames':2}).raise_for_status()
        session=wait_session(c,timeout=90)
        assert session['completed']==2
        assert session['transport']['returned_counter_to_first']
        assert not session['transport']['returned_to_first']
        assert session['end_action_result']['confirmed'] is False
        assert session['warning_code']=='RETURN_COUNTER_ACK_OPTICAL_UNVERIFIED'
        assert c.get('/api/cyberview/status').json()['transport_position_uncertain']
        response=c.post('/api/cyberview/scan',json={})
        assert response.status_code==409 and 'POSITION_UNCERTAIN' in response.text


def test_highres_shift_beyond_predicted_pad_cannot_promote_incomplete_frame(tmp_path,planned_bridge,monkeypatch):
    native(monkeypatch,actions=('next','previous','nudge'))
    monkeypatch.setenv('FAKE_FRAME_WIDTH_MM','35.58')
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','1')
    original=NativeAflBridge.scan
    async def shifted(self,out,*args,**kwargs):
        images=await original(self,out,*args,**kwargs)
        if self.options['dpi']==1800 and images:
            pixels=tifffile.imread(out);pixels=np.roll(pixels,-22,axis=1);pixels[:,-22:]=0
            tifffile.imwrite(out,pixels,photometric='rgb')
        return images
    monkeypatch.setattr(NativeAflBridge,'scan',shifted)
    with TestClient(create_app(tmp_path/'library')) as c:
        login(c)
        c.post('/api/cyberview/scan-all-verified',json={'expected_frames':1,'end_action':'hold_at_end'}).raise_for_status()
        session=wait_session(c,timeout=90)
        assert session['state']=='error' and 'UNVERIFIED_FRAME_COVERAGE' in session['error'],session
        records=c.get('/api/cyberview/captures').json()['captures']
        attempt=next(r for r in records if r['purpose']=='coverage_attempt')
        assert len(highres(planned_bridge))==1
        assert not attempt['coverage_verification']['x_containment_verified']
        assert len(attempt['derived']['sources'])==1
        for source in attempt['derived']['sources']:
            assert hashlib.sha256((tmp_path/'library'/source['path']).read_bytes()).hexdigest()==source['sha256']


@pytest.mark.parametrize('mismatch',['counter','image'])
def test_stopped_resolution_rechecks_physical_identity_before_another_move(tmp_path,planned_bridge,monkeypatch,mismatch):
    native(monkeypatch,actions=('next','previous','nudge'))
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','1')
    scan=NativeAflBridge.scan;register=acquisition_plan.register_preview;rechecking=[]
    async def watched(self,out,*args,**kwargs):
        result=await scan(self,out,*args,**kwargs)
        if 'stopped-arrival-' in str(out):
            rechecking.append(True)
            if mismatch=='counter':self.last_frame_position=2
        return result
    def match(*args,**kwargs):
        if rechecking and mismatch=='image':raise ValueError('UNVERIFIED_PREVIEW_ALIGNMENT: film reseated')
        return register(*args,**kwargs)
    monkeypatch.setattr(NativeAflBridge,'scan',watched)
    monkeypatch.setattr(acquisition_plan,'register_preview',match)
    with TestClient(create_app(tmp_path/'library')) as c:
        login(c)
        c.post('/api/cyberview/scan-all-verified',json={}).raise_for_status()
        stopped=wait_session(c,timeout=90)
        assert stopped['awaiting_end_confirmation']
        before=[e for e in planned_bridge if e[0]=='film']
        response=c.post('/api/cyberview/refused-advance',json={'session_id':stopped['id'],'action':'retry_advance'})
        assert response.status_code==409 and 'POSITION_UNCERTAIN' in response.text
        assert [e for e in planned_bridge if e[0]=='film']==before
        status=c.get('/api/cyberview/status').json()
        assert status['transport_position_uncertain']
        assert not status['session']['awaiting_end_confirmation']
