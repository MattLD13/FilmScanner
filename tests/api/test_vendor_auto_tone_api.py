"""Automatic tone API uses isolated CPU table generation, no scanner/vendor I/O."""
import hashlib
import numpy as np
from fastapi.testclient import TestClient
import pytest

from services.api.main import create_app
from services.imaging import vendor_autogamma, vendor_negative, filmterms
from test_planned_scan_api import planned_bridge
from test_frame_align_api import strip_bridge,native,wait_session
from test_workflow import login


def capture_fixture(client):
    response=client.post('/api/cyberview/scan',json={'count':1})
    assert response.status_code==200,response.text
    assert wait_session(client)['state']=='complete'
    record=client.get('/api/cyberview/captures').json()['captures'][0]
    return record,f"/api/cyberview/captures/{record['id']}"


def test_vendor_auto_tone_saves_exact_tables_without_mutating_original_and_can_be_disabled(tmp_path,strip_bridge,monkeypatch):
    native(monkeypatch)
    monkeypatch.setenv('FAKE_CVBRIDGE_RESPECT_SETTINGS','1')
    tables=np.round(np.linspace(0,1,256)**.8*255).astype(int)[None].repeat(3,axis=0).tolist()
    called=[]
    def generate(values,**kw):
        assert np.isfinite(values).all() and values.ndim==3
        called.append(kw)
        return {'tables':tables,'diagnostics':{'device_io':False,'caller_stage_order_verified':False,'reference_used':False}}
    monkeypatch.setattr(vendor_autogamma,'available',lambda:True)
    monkeypatch.setattr(vendor_autogamma,'generate_tables',generate)
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        record,url=capture_fixture(client)
        original=client.get(url+'/export/original').content
        response=client.post(url+'/vendor-auto-tone',json={'enabled':True})
        assert response.status_code==200,response.text
        saved=response.json()
        assert saved['adjustments']['vendor_auto_gamma_tables']==tables
        assert saved['adjustments']['auto_color'] is None
        assert saved['adjustments']['gamma']==1 and saved['adjustments']['black_point']==0
        assert saved['vendor_auto_tone']['experimental'] is True
        assert called==[{'negative':True,'input_plane':'converted_positive'}]
        assert client.get(url+'/processing-preview',params={'vendor_auto_tone':True,'invert':True}).status_code==200
        assert hashlib.sha256(client.get(url+'/export/original').content).hexdigest()==record['sha256']
        assert client.get(url+'/export/original').content==original
        disabled=client.post(url+'/vendor-auto-tone',json={'enabled':False})
        assert disabled.status_code==200 and disabled.json()['adjustments']['vendor_auto_gamma_tables'] is None


@pytest.mark.parametrize('available',[True,False])
def test_vendor_auto_tone_failure_does_not_change_recipe(tmp_path,strip_bridge,monkeypatch,available):
    native(monkeypatch)
    monkeypatch.setattr(vendor_autogamma,'available',lambda:available)
    def fail(*args,**kw):raise ValueError('UNUSABLE_VENDOR_AUTO_TABLES: ambiguous input')
    monkeypatch.setattr(vendor_autogamma,'generate_tables',fail)
    app=create_app(tmp_path/'library')
    with TestClient(app) as client:
        login(client)
        record,url=capture_fixture(client)
        response=client.post(url+'/vendor-auto-tone',json={'enabled':True})
        assert response.status_code==409
        current=next(r for r in client.get('/api/cyberview/captures').json()['captures'] if r['id']==record['id'])
        assert current['adjustments']==record['adjustments']
        assert client.patch(url,json={'adjustments':{'vendor_auto_gamma_tables':[[0,1]]}}).status_code==422


@pytest.fixture
def generic_profile(monkeypatch):
    film=('FilmClass NEG;\nFilmName Synthetic automatic tone;\nFilmMfgr Fixture;\nFilmLut\n'+
          '\n'.join(f'{i} {i} {i}' for i in range(256))+';\n'+
          'FilmMatR 1 0 0 0;\nFilmMatG 0 1 0 0;\nFilmMatB 0 0 1 0;').encode()
    gamma=('FilmLut\n'+'\n'.join(f'{i} {i} {i}' for i in range(4096))+';').encode()
    profile=vendor_negative.create(film,gamma,'fixture.ft','Fixture')
    def default(store):
        filmterms.remember(store,profile)
        return profile
    monkeypatch.setattr(vendor_negative,'default_profile',default)
    return profile


def test_new_negative_defaults_to_no_preview_tone_with_explicit_opt_in(tmp_path,strip_bridge,monkeypatch,generic_profile):
    native(monkeypatch);calls=[]
    table=np.tile(np.arange(256),(3,1)).tolist()
    monkeypatch.setattr(vendor_autogamma,'available',lambda:True)
    def generate(values,**kw):
        calls.append((values.shape,kw))
        return {'tables':table,'diagnostics':{'device_io':False,'caller_stage_order_verified':True,'reference_used':False}}
    monkeypatch.setattr(vendor_autogamma,'generate_tables',generate)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client);record,url=capture_fixture(client)
        assert calls==[]
        assert record['adjustments']['vendor_auto_gamma_tables'] is None
        assert record['adjustments']['auto_color'] is None
        assert record['vendor_auto_tone']['default_off']
        response=client.post(url+'/vendor-auto-tone',json={'enabled':True})
        assert response.status_code==200,response.text
        enabled=response.json()
        assert len(calls)==1 and calls[0][1]=={'negative':True,'input_plane':'converted_positive'}
        assert enabled['adjustments']['vendor_auto_gamma_tables']==table
        assert not enabled['vendor_auto_tone']['automatic'] and not enabled['vendor_auto_tone']['experimental']
        assert enabled['vendor_auto_tone']['statistics']['unacquired_pixels_used']==0
        assert hashlib.sha256(client.get(url+'/export/original').content).hexdigest()==record['sha256']
        off=client.post(url+'/vendor-auto-tone',json={'enabled':False}).json()
        assert off['vendor_auto_tone']['user_disabled']
        assert off['adjustments']['vendor_auto_gamma_tables'] is None and off['adjustments']['auto_color'] is None


@pytest.mark.parametrize('available',[False,True])
def test_default_tone_failure_preserves_scan_and_generic_conversion(tmp_path,strip_bridge,monkeypatch,generic_profile,available):
    native(monkeypatch)
    monkeypatch.setattr(vendor_autogamma,'available',lambda:available)
    def fail(*a,**kw):raise ValueError('UNUSABLE_VENDOR_AUTO_TABLES: source unsuitable')
    monkeypatch.setattr(vendor_autogamma,'generate_tables',fail)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client);record,url=capture_fixture(client)
        assert record['adjustments']['film_profile']==generic_profile['id']
        assert record['adjustments']['vendor_auto_gamma_tables'] is None
        assert record['vendor_auto_tone']['enabled'] is False
        assert record['vendor_auto_tone']['default_off']
        assert client.post(url+'/vendor-auto-tone',json={'enabled':True}).status_code==409
        current=client.get('/api/cyberview/captures').json()['captures'][0]
        assert current['adjustments']==record['adjustments']
        assert hashlib.sha256(client.get(url+'/export/original').content).hexdigest()==record['sha256']


def test_planned_scans_default_to_no_preview_tone_and_never_generate_tables(
        tmp_path,planned_bridge,monkeypatch,generic_profile):
    native(monkeypatch,actions=('next','previous','nudge'));calls=[]
    monkeypatch.setattr(vendor_autogamma,'available',lambda:True)
    def generate(values,**kw):
        calls.append(values.shape)
        table=np.tile(np.round((np.arange(256)/255)**(.7+.1*len(calls))*255),(3,1)).astype(int).tolist()
        return {'tables':table,'diagnostics':{'device_io':False,'caller_stage_order_verified':True,'reference_used':False}}
    monkeypatch.setattr(vendor_autogamma,'generate_tables',generate)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        response=client.post('/api/cyberview/scan-all-verified',json={'roll':'Per-frame tone'})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=60);assert session['state']=='complete',session
        records=client.get('/api/cyberview/captures').json()['captures']
        finals=[r for r in records if r['session_id']==session['id'] and r['purpose'] in ('scan','stitched')]
        assert len(finals)==2 and calls==[]
        for record in finals:
            assert record['vendor_auto_tone']['default_off']
            assert record['adjustments']['vendor_auto_gamma_tables'] is None
            assert record['adjustments']['auto_color'] is None
            assert hashlib.sha256(client.get(f"/api/cyberview/captures/{record['id']}/export/original").content).hexdigest()==record['sha256']


@pytest.mark.parametrize('enabled',[True,False])
def test_favorite_reuses_verified_preview_tone_or_preserves_user_disabled_choice(
        tmp_path,planned_bridge,monkeypatch,generic_profile,enabled):
    native(monkeypatch,actions=('next','previous','nudge'));calls=[]
    monkeypatch.setattr(vendor_autogamma,'available',lambda:True)
    table=np.tile(np.arange(256),(3,1)).tolist()
    def generate(values,**kw):
        calls.append(values.shape)
        return {'tables':table,'diagnostics':{'device_io':False,'caller_stage_order_verified':True}}
    monkeypatch.setattr(vendor_autogamma,'generate_tables',generate)
    with TestClient(create_app(tmp_path/'library')) as client:
        login(client)
        response=client.post('/api/cyberview/preview-roll',json={'scope':'one','dpi':300,'roll':'Favorite tone'})
        assert response.status_code==200,response.text
        preview_session=wait_session(client,timeout=60);assert preview_session['state']=='complete',preview_session
        preview=next(r for r in client.get('/api/cyberview/captures').json()['captures']
                     if r['session_id']==preview_session['id'] and r['purpose']=='roll_preview')
        assert calls==[]
        response=client.post(f"/api/cyberview/captures/{preview['id']}/vendor-auto-tone",json={'enabled':True})
        assert response.status_code==200,response.text
        assert len(calls)==1
        if not enabled:
            client.post(f"/api/cyberview/captures/{preview['id']}/vendor-auto-tone",json={'enabled':False}).raise_for_status()
        client.patch(f"/api/cyberview/captures/{preview['id']}",json={'favorite':True}).raise_for_status()
        response=client.post('/api/cyberview/scan-favorites',json={'preview_session_id':preview_session['id'],
            'preview_ids':[preview['id']],'roll':'Favorite tone','end_action':'hold_at_end'})
        assert response.status_code==200,response.text
        session=wait_session(client,timeout=60);assert session['state']=='complete',session
        assert session['arrival_verifications'][-1]['verified']
        assert len(calls)==1,'A verified favorite must retain its chosen preview tone without regeneration'
        final=next(r for r in client.get('/api/cyberview/captures').json()['captures']
                   if r['session_id']==session['id'] and r['purpose'] in ('scan','stitched'))
        assert bool(final['adjustments']['vendor_auto_gamma_tables'])==enabled
        if enabled:
            assert final['adjustments']['vendor_auto_gamma_tables']==table
            assert final['vendor_auto_tone']['generation_capture_id']==preview['id']
        else:
            assert final['vendor_auto_tone']['user_disabled']
