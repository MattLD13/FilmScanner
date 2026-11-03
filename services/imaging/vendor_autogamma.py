"""CPU-only access to recovered vendor automatic-table branches.

Table generation calls the pinned local image worker, never a scanner command.
The Generic Negative UI sequence and reuse of cropped-prescan tables were observed
on actual RGB8/RGB16 captures. This does not establish equal acquisition exposure,
calibration, geometry or appearance for arbitrary scanner/film configurations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
import uuid

import numpy as np
from services.imaging import statistics_guard

VERSION = 'cyberview-auto-tables-2'
VENDOR_SHA256 = 'bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb'
PROJECT = Path(__file__).resolve().parents[2]
ORACLE = PROJECT / 'services/cyberview_bridge/bin/vendorcolour.exe'
MAX_BYTES = 64_000_000
_worker_lock = threading.Lock()


class VendorAutoGammaError(ValueError):
    pass


def _pixels(samples: np.ndarray) -> np.ndarray:
    values = np.asarray(samples)
    if values.ndim != 3 or values.shape[2] != 3 or min(values.shape[:2]) < 1:
        raise VendorAutoGammaError('Vendor automatic processing requires nonempty RGB pixels')
    if values.dtype not in (np.dtype('uint8'), np.dtype('uint16')):
        if values.dtype.kind != 'f' or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise VendorAutoGammaError('Vendor automatic input must be uint8/uint16 or finite normalized float RGB')
        values = np.rint(values.astype(np.float64) * 65535).astype(np.uint16)
    return np.ascontiguousarray(values)


def validate_tables(tables, *, require_usable: bool = False) -> np.ndarray:
    values = np.asarray(tables)
    if (values.shape != (3, 256) or values.dtype.kind not in 'uif' or
            not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 255) or
            np.any(values != np.trunc(values)) or np.any(np.diff(values.astype(np.int64), axis=1) < 0)):
        raise VendorAutoGammaError('Vendor automatic tables must be three monotone 256-entry integer tables in 0..255')
    if require_usable and any(len(np.unique(channel)) < 8 for channel in values):
        raise VendorAutoGammaError('UNUSABLE_VENDOR_AUTO_TABLES: table has fewer than eight distinct levels in a channel')
    return values.astype(np.uint16)


def diagnostics(tables) -> dict:
    values = validate_tables(tables)
    return {'unique_levels': [int(len(np.unique(row))) for row in values],
            'flat_intervals': [int(np.count_nonzero(np.diff(row.astype(int)) == 0)) for row in values],
            'minimum': values.min(axis=1).astype(int).tolist(), 'maximum': values.max(axis=1).astype(int).tolist(),
            'table_sha256': hashlib.sha256(values.astype('<u2').tobytes()).hexdigest()}


def available(oracle_path: Path | None = None) -> bool:
    oracle = Path(oracle_path or ORACLE)
    ds = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32/CyberViewX_MF/CyberViewX.ds'
    if sys.platform != 'win32' or not oracle.is_file() or not ds.is_file():
        return False
    return hashlib.sha256(ds.read_bytes()).hexdigest() == VENDOR_SHA256


def statistics_input(samples: np.ndarray, crop: dict, covered: np.ndarray | None = None, *, dpi: float | None=None) -> tuple[np.ndarray, dict]:
    """Select an acquired picture rectangle without a second strided resampling.

    The vendor worker owns its histogram resize. Remove only unacquired outer
    rows from the selected crop; internal holes or a substantially reduced region
    are rejected rather than filled or flattened into fictitious scene statistics.
    """
    values = np.asarray(samples)
    if values.ndim != 3 or values.shape[2] != 3 or min(values.shape[:2]) < 1:
        raise VendorAutoGammaError('Automatic tone requires a nonempty RGB picture')
    h,w=values.shape[:2]
    try:
        left,top,right,bottom=[float(crop[k]) for k in ('left','top','right','bottom')]
        if not np.isfinite([left,top,right,bottom]).all() or not (0<=left<right<=1 and 0<=top<bottom<=1):
            raise ValueError
    except (KeyError,TypeError,ValueError) as exc:
        raise VendorAutoGammaError('Automatic tone requires a valid normalized picture crop') from exc
    x0,y0,x1,y1=int(left*w),int(top*h),min(w,round(right*w)),min(h,round(bottom*h))
    if x1<=x0 or y1<=y0:
        raise VendorAutoGammaError('Automatic tone picture crop is empty')
    requested=[x0,y0,x1,y1]
    guard=None
    if dpi is not None:
        _,guard=statistics_guard.mask(values.shape,dpi)
        if guard['applied']:
            x0=max(x0,guard['side_columns_each']);x1=min(x1,w-guard['side_columns_each'])
            y1=min(y1,h-guard['bottom_rows'])
            if x1<=x0 or y1<=y0:
                raise VendorAutoGammaError('UNVERIFIED_TONE_INPUT: selected area lies inside the statistics edge guard')
    if covered is not None:
        mask=np.asarray(covered,dtype=bool)
        if mask.shape!=(h,w):
            raise VendorAutoGammaError('Automatic tone coverage does not match the image')
        rows=mask[y0:y1,x0:x1].all(axis=1)
        good=np.flatnonzero(rows)
        if not good.size or not rows[good[0]:good[-1]+1].all() or good.size<.95*len(rows):
            raise VendorAutoGammaError('UNVERIFIED_TONE_INPUT: picture has internal holes or insufficient acquired rows')
        start=y0+int(good[0]);y1=y0+int(good[-1])+1;y0=start
    selected=values[y0:y1,x0:x1]
    if min(selected.shape[:2])<8:
        raise VendorAutoGammaError('Automatic tone picture region is too small')
    return selected,{'requested_bounds_px':requested,'used_bounds_px':[x0,y0,x1,y1],
                     'acquired_pixels':int(selected.shape[0]*selected.shape[1]),
                     'unacquired_pixels_used':0,'host_strided_resampling':False,'edge_guard':guard}


def generate_tables(samples: np.ndarray, *, negative: bool, input_plane: str = 'unspecified',
                    oracle_path: Path | None = None, timeout: float = 30) -> dict:
    # Serialize defaults and explicit edits as well as the C worker's named mutex.
    # The INI before/after snapshots must belong to the same isolated worker call.
    with _worker_lock:
        return _generate_tables(samples,negative=negative,input_plane=input_plane,
                                oracle_path=oracle_path,timeout=timeout)


def _generate_tables(samples: np.ndarray, *, negative: bool, input_plane: str = 'unspecified',
                    oracle_path: Path | None = None, timeout: float = 30) -> dict:
    """Run the exact local image worker and return JSON-ready tables/evidence.

    ``negative`` chooses the recovered worker branch; it does not invert pixels.
    The caller must state which image plane it supplies and must not claim full
    CyberView parity merely because the worker itself matches. Degenerate tables
    fail instead of replacing the image with a binary or all-zero rendering.
    """
    if type(negative) is not bool or input_plane not in ('unspecified', 'transmission', 'converted_positive'):
        raise VendorAutoGammaError('Choose an explicit negative boolean and a supported input-plane label')
    if not np.isfinite(timeout) or not 0 < timeout <= 120:
        raise VendorAutoGammaError('CPU worker timeout must be greater than zero and at most 120 seconds')
    unconverted=np.asarray(samples)
    if unconverted.ndim!=3 or max(unconverted.shape[:2],default=0)>20000 or unconverted.size*2>MAX_BYTES:
        raise VendorAutoGammaError('Vendor automatic input exceeds the bounded CPU-worker size')
    pixels = _pixels(unconverted)
    h, w = pixels.shape[:2]
    if h > 20000 or w > 20000 or pixels.nbytes > MAX_BYTES:
        raise VendorAutoGammaError('Vendor automatic input exceeds the bounded CPU-worker size')
    oracle = Path(oracle_path or ORACLE).resolve()
    if not available(oracle):
        raise VendorAutoGammaError('The pinned local CyberView CPU image worker is unavailable')
    settings = Path(os.environ.get('APPDATA', '')) / 'PIE/MF/CyberViewX.ini'
    settings_before = settings.read_bytes() if settings.is_file() else None
    with TemporaryDirectory(prefix='frame-vendor-auto-') as temporary:
        folder = Path(temporary)
        source, destination = folder / 'input.raw', folder / 'tables.raw'
        source.write_bytes(pixels.astype('<u2' if pixels.dtype == np.uint16 else 'u1').tobytes())
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        process=subprocess.Popen([str(oracle), 'autotables', str(source), str(w), str(h),
                                  str(pixels.dtype.itemsize * 8), str(int(negative)), str(destination)],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
        try:
            stdout,stderr=process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            # A CPU-only worker can be killed on timeout; its C exit handler then
            # cannot run. Recover only the backup belonging to this exact PID and
            # only if it matches the snapshot taken before this call.
            own_backup=settings.with_name(f'{settings.name}.colour-{process.pid}-backup')
            if settings_before is not None and own_backup.is_file() and own_backup.read_bytes()==settings_before:
                temporary_restore=settings.with_name(f'.{settings.name}.frame-restore-{uuid.uuid4().hex}')
                try:
                    temporary_restore.write_bytes(settings_before)
                    os.replace(temporary_restore,settings)
                    own_backup.unlink()
                finally:
                    temporary_restore.unlink(missing_ok=True)
            raise VendorAutoGammaError('Vendor CPU automatic-table worker timed out; no tables were applied') from exc
        after = settings.read_bytes() if settings.is_file() else None
        if after != settings_before:
            raise VendorAutoGammaError('Vendor CPU worker did not restore its settings; no tables were applied')
        if process.returncode != 0:
            raise VendorAutoGammaError(f'Vendor CPU automatic-table worker failed: {stdout.strip()[:300]}')
        try:
            metadata = json.loads(stdout.strip())
        except json.JSONDecodeError as exc:
            raise VendorAutoGammaError('Vendor CPU worker returned invalid metadata') from exc
        if metadata.get('device_io') is not False or metadata.get('mode') != 'autotables':
            raise VendorAutoGammaError('CPU-only worker evidence did not match the requested operation')
        if not destination.is_file() or destination.stat().st_size != 1536:
            raise VendorAutoGammaError('Vendor CPU worker delivered an invalid table buffer')
        tables = validate_tables(np.fromfile(destination, dtype='<u2').reshape(3, 256), require_usable=True)
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha:
            raise VendorAutoGammaError('Vendor CPU worker altered its input buffer file')
    return {'tables': tables.astype(int).tolist(), 'diagnostics': diagnostics(tables) | {
        'version': VERSION, 'engine': 'pinned_vendor_cpu_worker', 'worker_va': '0x10103810',
        'branch': 'negative_histogram_0x10008bd0' if negative else 'sixpoint_gamma_0x101045b0',
        'negative': negative, 'input_plane': input_plane, 'input_bits': pixels.dtype.itemsize * 8,
        'input_width': w, 'input_height': h, 'input_sha256': source_sha,
        'vendor_sha256': VENDOR_SHA256, 'device_io': False,
        'caller_stage_order_verified': negative and input_plane=='converted_positive',
        'caller_verification_scope': 'Actual Generic Negative RGB8 prescan: film term -> automatic tables; RGB16 scan reuses cropped-prescan tables -> saved TIFF.',
        'acquisition_parity_verified': False, 'reference_used': False,
        'note': 'Verified image-stage sequence and exact tables/application; equal scanner exposure, calibration, field of view and arbitrary-film appearance are separate claims.'}}


def apply(samples: np.ndarray, tables) -> np.ndarray:
    """Apply mode-7 tables with exact vendor integer interpolation.

    uint8 uses direct channel lookup. uint16 expands table knots to positions
    and values at multiples of 257, then interpolates with integer arithmetic.
    Floats are explicitly quantized to the same uint16 domain and returned in
    0..1. The input array is never mutated.
    """
    original = np.asarray(samples)
    pixels = _pixels(original)
    lookup = validate_tables(tables).astype(np.int64)
    if pixels.dtype == np.uint8:
        output = lookup[np.arange(3), pixels].astype(np.uint8)
    else:
        # Expand the tiny table once instead of materializing several full-image
        # int64 temporaries for a multi-megapixel acquisition.
        values = np.arange(65536,dtype=np.int64)
        indices = np.minimum(values // 257, 254)
        remainder = values - indices * 257
        low,high=lookup[:,indices],lookup[:,indices+1]
        expanded=(low*257+(high-low)*remainder).astype(np.uint16)
        output=expanded[np.arange(3),pixels]
    if original.dtype.kind == 'f':
        return (output.astype(np.float64) / 65535).astype(original.dtype)
    return output
