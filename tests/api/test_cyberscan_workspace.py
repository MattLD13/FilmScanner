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
