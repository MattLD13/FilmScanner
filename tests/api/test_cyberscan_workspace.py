"""Workspace/editing integration with a synthetic pipe helper; no scanner I/O."""
from io import BytesIO
import hashlib
import time

from fastapi.testclient import TestClient
import numpy as np
import pytest
import tifffile

from services.api.main import create_app
from services.scanner_host import workspace
from test_cyberview import bridge, wait_session
from test_workflow import login


def test_workspace_persists_but_unverified_values_do_not_reach_driver(tmp_path,bridge,monkeypatch):
    root=tmp_path/'library'
    monkeypatch.setattr(workspace,'validation',lambda:{})
    with TestClient(create_app(root)) as client:
        assert client.get('/api/cyberview/workspace').status_code==401
        login(client)
        default=client.get('/api/cyberview/workspace').json()['settings']
        changed=default|{'dpi':600}
        saved=client.put('/api/cyberview/workspace',json=changed)
        assert saved.status_code==200
        assert saved.json()['capabilities']['actions']['scan']['available'] is False
        assert client.post('/api/cyberview/scan',json={'count':1}).status_code==409
        assert not bridge.exists()
        invalid=default|{'crop':{'left':1,'right':.5,'top':0,'bottom':.9}}
        assert client.put('/api/cyberview/workspace',json=invalid).status_code==422
    with TestClient(create_app(root)) as client:
        login(client)
        assert client.get('/api/cyberview/workspace').json()['settings']['dpi']==600


def test_native_prescan_is_real_acquisition_with_recorded_purpose(tmp_path,bridge,monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND','afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER','1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE',__import__('os').environ['FRAME_CVBRIDGE'])
    opts=workspace.ScanOptions(dpi=300,bits=8).model_dump()
    monkeypatch.setattr(workspace,'validation',lambda:{'configurations':[opts]})
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        result=client.post('/api/cyberview/prescan',json={'roll':'Test preview'})
        assert result.status_code==200,result.text
        session=wait_session(client)
        assert session['state']=='complete' and session['purpose']=='prescan'
        assert session['requested_settings']['dpi']==300
        item=client.get('/api/cyberview/workspace').json()['prescan']
        assert item['id']==session['captures'][0] and item['purpose']=='prescan'
        assert 'settings 300 8 rgb negative' in bridge.read_text()


def test_crop_levels_histogram_and_exports_preserve_original(tmp_path,bridge):
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        client.post('/api/cyberview/scan',json={'count':1})
        session=wait_session(client)
        assert session['state']=='complete'
        item=client.get('/api/cyberview/captures').json()['captures'][0]
        url=f'/api/cyberview/captures/{item["id"]}'
        original=client.get(url+'/export/original').content
        histogram=client.get(url+'/histogram').json()
        assert histogram['stage']=='before_levels' and len(histogram['bins'])==3
        assert all(len(channel)==256 and sum(channel)==2400 for channel in histogram['bins'])
        edits={'gamma':1.5,'rgb_balance':[1.2,1,1], 'curve':[0,.2,.4,.8,1],
               'crop':{'left':.2,'top':.25,'right':.9,'bottom':1}}
        saved=client.patch(url,json={'adjustments':edits})
        assert saved.status_code==200,saved.text
        rendered=tifffile.imread(BytesIO(client.get(url+'/export/tiff').content))
        assert rendered.dtype==np.uint16 and rendered.shape==(30,42,3)
        auto=client.post(url+'/auto-levels')
        assert auto.status_code==200
        assert auto.json()['adjustments']['crop']==edits['crop']
        assert client.get(url+'/export/original').content==original
        assert hashlib.sha256(original).hexdigest()==item['sha256']
        assert client.patch(url,json={'adjustments':{'black_point':.8,'white_point':.4}}).status_code==422
        assert client.patch(url,json={'adjustments':{'curve':[0,.5,.2,.8,1]}}).status_code==422


def test_film_base_measurement_becomes_exposure_but_scans_wait_for_validation(tmp_path,bridge,monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND','afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER','1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE',__import__('os').environ['FRAME_CVBRIDGE'])
    proven={'actions':['calibrate'],'configurations':[workspace.ScanOptions().model_dump()]}
    monkeypatch.setattr(workspace,'validation',lambda:proven)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        result=client.post('/api/cyberview/control',json={'action':'calibrate','acknowledged':True})
        assert result.status_code==200,result.text
        assert result.json()['film_base_exposure']==[151,201,318]
        # Without a validated exposure range the measurement cannot change the exposure.
        assert client.get('/api/cyberview/workspace').json()['settings']['exposure']==[100,100,100]
        monkeypatch.setattr(workspace,'validation',lambda:proven|{'exposure_range':[50,300]})
        client.post('/api/cyberview/control',json={'action':'calibrate','acknowledged':True})
        view=client.get('/api/cyberview/workspace').json()
        assert view['settings']['exposure']==[151,201,300]          # blue kept inside the scanned range
        assert view['capabilities']['actions']['scan']['available'] is True


def test_direct_capture_stops_and_ends_a_driver_stuck_on_a_sensor(tmp_path,bridge,monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND','afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER','1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE',__import__('os').environ['FRAME_CVBRIDGE'])
    monkeypatch.setenv('FAKE_CVBRIDGE_MODE','sensor')
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        assert client.post('/api/cyberview/scan',json={'count':1}).status_code==200
        session=wait_session(client)
        assert session['state']=='error' and 'take the film out' in session['error']
        assert client.get('/api/cyberview/status').json()['session_open'] is False


def test_each_direct_scan_sets_the_next_exposure_from_its_film_base(tmp_path,bridge,monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND','afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER','1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE',__import__('os').environ['FRAME_CVBRIDGE'])
    proven={'actions':[],'configurations':[workspace.ScanOptions().model_dump()],'exposure_range':[50,300]}
    monkeypatch.setattr(workspace,'validation',lambda:proven)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        assert client.post('/api/cyberview/scan',json={'count':1}).status_code==200
        assert wait_session(client)['state']=='complete'
        record=client.get('/api/cyberview/captures').json()['captures'][0]
        measured=record['film_base']
        assert measured['exposure_used']==[100,100,100] and len(measured['measured'])==3
        assert client.get('/api/cyberview/workspace').json()['settings']['exposure']==measured['next_exposure']


def test_all_frames_scans_until_the_film_runs_out(tmp_path,bridge,monkeypatch):
    monkeypatch.setenv('FRAME_SCANNER_BACKEND','afl-native-experimental')
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER','1')
    monkeypatch.setenv('FRAME_NATIVE_BRIDGE',__import__('os').environ['FRAME_CVBRIDGE'])
    monkeypatch.setenv('FAKE_CVBRIDGE_FRAMES','3')   # the fake strip ends after three frames
    monkeypatch.setattr(workspace,'validation',lambda:{'actions':['next'],'configurations':[workspace.ScanOptions().model_dump()]})
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        assert client.post('/api/cyberview/scan',json={'until_end':True,'roll':'Strip'}).status_code==200
        session=wait_session(client,timeout=30)
        assert session['state']=='complete' and session['completed']==3, session
        assert len(client.get('/api/cyberview/captures').json()['captures'])==3
