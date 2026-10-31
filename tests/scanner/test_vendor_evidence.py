"""Passive scanner diagnostics from SCAN08.dll's own log; no driver is loaded."""
import os

from services.scanner_host import vendor_evidence

# Shape and values follow a real %TEMP%\PF1800AFL.log from the PF1800 AFL (2026-10-30).
LOG = '''Model Code\t  = 37\r
USB Standard\t  = USB 1.1\r
CCD\t\t  = 533\r
SDK Version\t  = 1,0,3,6\r
F/W Version\t  = 4\r
AVG=255   ,   lamp=245   ,   Pixel=193\r
AVG=254   ,   lamp=70   ,   Pixel=211\r
AVG=251   ,   lamp=65   ,   Pixel=2140\r
wStartPos\t  = 1581\r
wLeftEdge\t  = 158\r
wFilmHolePos\t  = 284\r
************************* 1 **************************\r
Film Type\t  = Film Strip\r
Film Media\t  = Postive Film\r
Focus Step        = 0\r
ColorBalance     R = 100  ,  G = 100  ,  B = 100\r
************************* 2 **************************\r
Film Type\t  = Film Strip\r
Film Media\t  = Negative Film\r
Lamp\t\t  = 65\r
Focus Step        = 2\r
ColorBalance     R = 153  ,  G = 205  ,  B = 323\r
HighlightEnhance R = 100  ,  G = 100  ,  B = 100\r
ShadowEnhance    R =   0  ,  G =   0  ,  B =   0\r
Gain             R =  2  ,   G =  2  ,   B =  2\r
DC               R = 252  ,  G = 248  ,  B = 227\r
'''


def test_parse_vendor_log_reads_header_lamp_geometry_and_last_scan():
    report = vendor_evidence.parse_vendor_log(LOG)
    assert report['header'] == {'model': '37', 'usb': 'USB 1.1', 'ccd': '533', 'sdk': '1,0,3,6', 'firmware': '4'}
    assert report['lamp_calibration'] == {'steps': 3, 'final_level': 65}
    assert report['geometry'] == {'StartPos': 1581, 'LeftEdge': 158, 'FilmHolePos': 284}
    assert report['scans_logged'] == 2
    last = report['last_scan']
    assert last['film_media'] == 'Negative Film' and last['focus_step'] == 2 and last['lamp'] == 65
    assert last['color_balance'] == [153, 205, 323] and last['gain'] == [2, 2, 2] and last['dc'] == [252, 248, 227]


def test_diagnostics_are_passive_and_tolerate_missing_files(tmp_path):
    empty = vendor_evidence.scanner_diagnostics(tmp_path)
    assert empty == {'device_io_performed': False, 'log': None, 'calibration_cache': None}
    (tmp_path / 'PF1800AFL.log').write_bytes(LOG.encode('latin-1'))
    (tmp_path / 'AFLScanner.CFG').write_bytes(b'\0' * 16530)
    report = vendor_evidence.scanner_diagnostics(tmp_path)
    assert report['log']['header']['ccd'] == '533' and report['calibration_cache']['bytes'] == 16530


def test_feature_list_follows_the_validation_record(monkeypatch, tmp_path):
    monkeypatch.setenv('FRAME_VENDOR_TEMP', str(tmp_path))
    monkeypatch.setattr(vendor_evidence, 'scanner_diagnostics', lambda directory=None: {'device_io_performed': False})
    from services.scanner_host import workspace
    monkeypatch.setattr(workspace, 'validation', lambda: {'actions': ['next', 'calibrate'], 'configurations': []})
    features = {f['id']: f for f in vendor_evidence.inspect_installation(tmp_path)['features']}
    assert features['dmin']['evidence'] == 'recorded_on_device'
    assert features['autofocus']['evidence'] == 'static_only' and not features['autofocus']['available']
    assert features['infrared']['evidence'] == 'unavailable'
