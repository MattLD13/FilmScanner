"""CyberScan X's own verified copy of the AFL driver chain (services/native_bridge/driver.py)."""
import hashlib
import json

from services.native_bridge import driver


def test_copies_verified_files_and_never_keeps_a_bad_one(tmp_path, monkeypatch):
    source = tmp_path / 'installed'; source.mkdir()
    files = []
    for name in ('SCAN08.dll', 'SQ_Scan.dll'):
        data = name.encode() * 100
        (source / name).write_bytes(data)
        files.append({'name': name, 'installed_in': str(source), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': files}))
    monkeypatch.setattr(driver, 'MANIFEST', manifest)
    monkeypatch.setenv('FRAME_DRIVER_DIR', str(tmp_path / 'local'))
    assert driver.status()['complete'] is False
    result = driver.ensure()
    assert result['complete'] and all(f['local'] and f['installed'] for f in result['files'])
    # A tampered installed copy is never brought in, and a good local copy is kept.
    (source / 'SQ_Scan.dll').write_bytes(b'changed')
    (tmp_path / 'local' / 'SCAN08.dll').write_bytes(b'damaged')
    result = driver.ensure()
    by_name = {f['name']: f for f in result['files']}
    assert by_name['SQ_Scan.dll']['local'] and not by_name['SQ_Scan.dll']['installed']
    assert by_name['SCAN08.dll']['local']                   # restored from the good installed copy
    assert not list((tmp_path / 'local').glob('*.partial'))


def test_manifest_lists_the_whole_chain():
    names = [f['name'] for f in driver.files()]
    assert names == ['SCAN08.dll', 'SQ_Scan.dll', 'IO_PORT.dll', 'fvc.dll', 'SQ1394.DLL']
    assert all(len(f['sha256']) == 64 for f in driver.files())
