"""Passive CyberView installation evidence. Never loads a DLL or opens a device.

ScannerDeviceIO 'detect' and 'open' actually reset registers and may home film.
File inspection is deliberately the only native discovery used by this module.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path


MODEL_SHA256 = 'da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f'
PROJECT = Path(__file__).resolve().parents[2]
TRIPLE = re.compile(r'R\s*=\s*(\d+)\s*,\s*G\s*=\s*(\d+)\s*,\s*B\s*=\s*(\d+)')


def temp_dir() -> Path:
    return Path(os.environ.get('FRAME_VENDOR_TEMP') or os.environ.get('TEMP') or '.')


def parse_vendor_log(text: str) -> dict:
    """SCAN08.dll's own %TEMP%\\PF1800AFL.log: start-up header, lamp sweep, geometry, scans.

    The module writes it on every scan (docs/scan08-feature-catalog.md); reading
    it is the only diagnostics path that needs no scanner I/O.
    """
    header, geometry, scans, lamp_steps = {}, {}, [], []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sweep = re.match(r'AVG=(\d+)\s*,\s*lamp=(\d+)\s*,\s*Pixel=(\d+)', line)
        if sweep:
            lamp_steps.append({'average': int(sweep[1]), 'lamp': int(sweep[2]), 'pixel': int(sweep[3])})
            continue
        if re.match(r'\*+\s*\d+\s*\*+', line):
            current = {}
            scans.append(current)
            continue
        key, _, value = (part.strip() for part in line.partition('='))
        if not _:
            continue
        triple = TRIPLE.search(line)
        if current is not None:
            name = line.split()[0] if triple else key
            field = {'Film Type': 'film_type', 'Film Media': 'film_media', 'Lamp': 'lamp', 'Focus Step': 'focus_step',
                     'ColorBalance': 'color_balance', 'HighlightEnhance': 'highlight', 'ShadowEnhance': 'shadow',
                     'Gain': 'gain', 'DC': 'dc'}.get(name)
            if field:
                current[field] = [int(v) for v in triple.groups()] if triple else (int(value) if value.isdigit() else value)
        elif key in ('Model Code', 'USB Standard', 'CCD', 'SDK Version', 'F/W Version'):
            header[{'Model Code': 'model', 'USB Standard': 'usb', 'CCD': 'ccd', 'SDK Version': 'sdk',
                    'F/W Version': 'firmware'}[key]] = value
        elif key in ('wStartPos', 'wLeftEdge', 'wBkLinePos', 'wCaliBorPos', 'wFilmHolePos') and value.isdigit():
            geometry[key[1:]] = int(value)
    calibrated = lamp_steps[-1]['lamp'] if lamp_steps else None
    return {'header': header, 'geometry': geometry, 'lamp_calibration': {'steps': len(lamp_steps), 'final_level': calibrated},
            'scans_logged': len(scans), 'last_scan': scans[-1] if scans else None}


def scanner_diagnostics(directory: Path | None = None) -> dict:
    """Passive: reads the vendor log and calibration cache if they exist. No DLL, no device."""
    directory = directory or temp_dir()
    result = {'device_io_performed': False, 'log': None, 'calibration_cache': None}
    log = directory / 'PF1800AFL.log'
    try:
        stat = log.stat()
        result['log'] = parse_vendor_log(log.read_text(encoding='latin-1', errors='replace')) | {
            'updated_at': int(stat.st_mtime * 1000)}
    except OSError:
        pass
    cache = directory / 'AFLScanner.CFG'
    try:
        stat = cache.stat()
        result['calibration_cache'] = {'bytes': stat.st_size, 'updated_at': int(stat.st_mtime * 1000),
                                       'age_hours': round((time.time() - stat.st_mtime) / 3600, 1)}
    except OSError:
        pass
    return result


def inspect_installation(root: Path | None = None) -> dict:
    root = root or Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32' / 'CyberViewX_MF'
    files = []
    for name in ('CyberViewX.ds', 'BeneScan.dll', 'SCAN08.dll'):
        path = root / name
        try:
            content = path.read_bytes()
        except OSError:
            files.append({'name': name, 'installed': False})
            continue
        digest = hashlib.sha256(content).hexdigest()
        item = {'name': name, 'installed': True, 'bytes': len(content), 'sha256': digest}
        if name == 'SCAN08.dll':
            item.update(recognized=digest == MODEL_SHA256,
                        version='1.0.3.6' if digest == MODEL_SHA256 else None)
        files.append(item)
    model = files[-1]
    legacy_available = all(item['installed'] for item in files) and (PROJECT / 'services/cyberview_bridge/bin/cvbridge.exe').is_file()
    native = model.get('recognized', False)
    # Native evidence comes only from the version-controlled validation record, so this
    # summary can never claim more than the controls the bridge is actually allowed.
    from services.scanner_host import workspace
    proved = set(workspace.validation().get('actions', []))
    configurations = workspace.validation().get('configurations', [])
    dpis = sorted({c['dpi'] for c in configurations})

    def native_feature(fid, name, action, detail_ok, detail_pending):
        ok = action in proved
        return {'id': fid, 'name': name, 'evidence': 'recorded_on_device' if ok else 'static_only',
                'available': native and ok, 'detail': detail_ok if ok else detail_pending}

    return {
        'inspection': 'files_only', 'device_io_performed': False, 'files': files,
        'native_bridge_built': (PROJECT / 'services/native_bridge/bin/aflbridge.exe').is_file(),
        'native_module_recognized': native,
        'native_device_validation': 'current_frame_verified',
        'native_note': ('Native capture talks to the AFL module directly, without CyberView. Starting it may home the '
                        'transport. Controls listed as recorded on the device were run in supervised tests; see '
                        'docs/cyberview-parity.md. Everything else stays off until tested.'),
        'catalog': 'docs/scan08-feature-catalog.md',
        'features': [
            {'id': 'current_frame', 'name': 'Current-frame acquisition', 'evidence': 'verified_on_device',
             'available': legacy_available or native,
             'detail': f"CyberView: 1800 dpi, 16-bit. Native: {', '.join(str(d) for d in dpis) or '1800'} dpi recorded."},
            {'id': 'advance', 'name': 'Forward one frame', 'evidence': 'verified_on_device', 'available': legacy_available,
             'detail': 'CyberView capture, through its own menu command. Native: after a scan in the same session.'},
            native_feature('previous', 'Back one frame', 'previous', 'Native only, after a scan in the same session. '
                           'The same move through CyberView hung the driver.', 'Not tested. Hung through CyberView.'),
            native_feature('eject', 'Eject forward', 'eject_forward', 'Native only.', 'Not tested.'),
            native_feature('autofocus', 'Autofocus', 'autofocus', 'Native only. Stores the focus step for the next scan.',
                           'Exists in the module (selector 14); not tested.'),
            native_feature('dmin', 'Film-base measurement', 'calibrate', 'Native only. Measures red, green and blue film base.',
                           'Exists in the module (selector 17); not tested.'),
            {'id': 'auto_exposure', 'name': 'Vendor auto exposure', 'evidence': 'static_only', 'available': False,
             'detail': 'Scan flag bit 0 runs a 300 dpi pre-pass and sets exposure. Needs one supervised scan.'},
            {'id': 'scan_area', 'name': 'Custom scan area and other resolutions', 'evidence': 'static_only', 'available': False,
             'detail': 'Any area up to 2586 by 1708 pixels; 360, 450 and 900 dpi buckets exist. Untested.'},
            {'id': 'multisample', 'name': 'Multi-scan averaging', 'evidence': 'static_only', 'available': False,
             'detail': 'Not in the AFL module. CyberScan X could average repeated native scans itself.'},
            {'id': 'infrared', 'name': 'Infrared dust removal', 'evidence': 'unavailable', 'available': False,
             'detail': 'The AFL module has no infrared channel; CyberView ICE settings belong to other models.'},
        ],
        'scanner': scanner_diagnostics(),
    }
