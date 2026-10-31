"""CyberScan X's own copy of the PF1800 AFL driver chain, so CyberView X can be uninstalled.

The five files in driver_manifest.json are copied from where CyberView X installed them
to %LOCALAPPDATA%\\CyberScanX\\driver (or FRAME_DRIVER_DIR) after checking each SHA-256.
aflbridge loads SCAN08.dll from that folder first, so its dependencies load from there
too. The binaries are vendor files: they stay on this PC and are never committed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

MANIFEST = Path(__file__).with_name('driver_manifest.json')


def folder() -> Path:
    if os.environ.get('FRAME_DRIVER_DIR'):
        return Path(os.environ['FRAME_DRIVER_DIR'])
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'CyberScanX' / 'driver'


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def files() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding='utf-8'))['files']


def installed_source(entry: dict) -> Path:
    return Path(os.path.expandvars(entry['installed_in'])) / entry['name']


def status() -> dict:
    """Which driver files CyberScan X already holds, and whether CyberView's copies remain."""
    target = folder()
    entries = [{'name': f['name'], 'local': _sha256(target / f['name']) == f['sha256'],
                'installed': _sha256(installed_source(f)) == f['sha256']} for f in files()]
    return {'folder': str(target), 'complete': all(e['local'] for e in entries), 'files': entries}


def ensure() -> dict:
    """Copies any missing or wrong local file from the CyberView install, verified. Never
    overwrites a good copy; leaves the folder partial (and reports it) if a source is missing."""
    target = folder()
    for entry in files():
        local = target / entry['name']
        if _sha256(local) == entry['sha256']:
            continue
        source = installed_source(entry)
        if _sha256(source) != entry['sha256']:
            continue
        target.mkdir(parents=True, exist_ok=True)
        partial = local.with_name(local.name + '.partial')
        shutil.copyfile(source, partial)
        if _sha256(partial) == entry['sha256']:
            os.replace(partial, local)
        else:
            partial.unlink(missing_ok=True)
    return status()
