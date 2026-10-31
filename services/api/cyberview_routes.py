"""CyberScan X API: real scans from CyberView X's hidden TWAIN driver.

Each delivered TIFF is kept unchanged as the original, hashed and recorded. Viewing
adjustments are a recipe stored next to it and applied only to previews and exports.
"""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time
import uuid
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field, field_validator, model_validator
import tifffile

from services.api.store import atomic_write
from services.imaging import autocolor, frame_align, pipeline, filmterms
from services.scanner_host import cyberview
from services.scanner_host import vendor_evidence
from services.native_bridge import driver
from services.scanner_host.native import configured_bridge, NativeAflBridge
from services.scanner_host.backend import ScannerError
from services.scanner_host import workspace
from services.scanner_host.workspace import ScanOptions

SOURCE = 'CyberView X - MF (TWAIN, hidden) on PrimeFilm PF1800 AFL'
PREVIEW_EDGE = 1800
THUMB_EDGE = 360
NATIVE_SOURCE = 'PF1800 AFL direct capture (SCAN08 driver, vendor-calibrated transmission)'
LIVE_MAX_ROWS = 300  # 1708 lines / 8, with room to spare


class ScanRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=40)
    roll: str = Field(default='', max_length=120)
    settings: ScanOptions | None = None
    purpose: Literal['scan', 'prescan'] = 'scan'


class FilmRequest(BaseModel):
    action: Literal['next', 'previous', 'eject_forward', 'eject_backward', 'goto']
    frame: int | None = Field(default=None, ge=1, le=40)
    acknowledged: bool = False


class ControlRequest(BaseModel):
    action: Literal['autofocus', 'focus', 'calibrate']
    value: int | None = Field(default=None, ge=0, le=200)
    acknowledged: bool = False


class BackendRequest(BaseModel):
    backend: Literal['cyberview-twain', 'afl-native-experimental']
    acknowledged: bool = False


class EditCrop(BaseModel):
    left: float = Field(default=0,ge=0,lt=1,allow_inf_nan=False)
    top: float = Field(default=0,ge=0,lt=1,allow_inf_nan=False)
    right: float = Field(default=1,gt=0,le=1,allow_inf_nan=False)
    bottom: float = Field(default=1,gt=0,le=1,allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered(self):
        if self.right<=self.left or self.bottom<=self.top:
            raise ValueError('Crop must have positive width and height')
        return self


class Adjustments(BaseModel):
    exposure: float = Field(default=0, ge=-2, le=2)
    contrast: float = Field(default=0, ge=-100, le=100)
    saturation: float = Field(default=0, ge=-100, le=100)
    temperature: float = Field(default=0, ge=-100, le=100)
    rotation: int = 0
    mirror: bool = False
    invert: bool = False
    film_base: list[float] = Field(default_factory=lambda: [1., 1., 1.], min_length=3, max_length=3)
    black_point: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    white_point: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    gamma: float = Field(default=1, ge=.1, le=4, allow_inf_nan=False)
    rgb_balance: list[float] = Field(default_factory=lambda: [1.,1.,1.],min_length=3,max_length=3)
    curve: list[float] = Field(default_factory=lambda: [0.,.25,.5,.75,1.],min_length=5,max_length=5)
    crop: EditCrop = Field(default_factory=EditCrop)
    monochrome: bool = False
    film_profile: str | None = Field(default=None, pattern='^[0-9a-f]{16}$')
    # CyberView's Auto Gamma, as its 18 words (services/imaging/autocolor.py); None = off.
    auto_color: list[int] | None = Field(default=None, min_length=18, max_length=18)

    @field_validator('auto_color')
    @classmethod
    def auto_color_words(cls, values):
        if values is not None and any(not 0 <= v <= 0xFFFF for v in values):
            raise ValueError('Auto colour words must be 16-bit values')
        return values

    @field_validator('rgb_balance')
    @classmethod
    def balance_bounds(cls, values):
        if any(not np.isfinite(v) or not .25<=v<=4 for v in values):
            raise ValueError('Channel balance must be between 0.25 and 4')
        return values

    @field_validator('curve')
    @classmethod
    def monotonic_curve(cls, values):
        if any(not np.isfinite(v) or not 0<=v<=1 for v in values) or any(a>b for a,b in zip(values,values[1:])):
            raise ValueError('Tone curve must contain five increasing values between zero and one')
        return values

    @model_validator(mode='after')
    def ordered_levels(self):
        if self.white_point-self.black_point<.001:
            raise ValueError('White point must exceed black point by at least 0.001')
        return self

    @field_validator('film_base')
    @classmethod
    def valid_film_base(cls, values):
        if any(not np.isfinite(v) or not .01 <= v <= 1 for v in values):
            raise ValueError('Film-base transmission must be between 0.01 and 1')
        return values


class CaptureUpdate(BaseModel):
    adjustments: Adjustments | None = None
    title: str | None = Field(default=None, max_length=120)
    favorite: bool | None = None


class RollAdjustments(BaseModel):
    adjustments: Adjustments


class AlignSettings(BaseModel):
    auto: bool = False                                   # align every new scan as it is saved
    bleed_mm: float = Field(default=0, ge=-2, le=2)      # negative trims inside the frame edges
    offset_mm: float = Field(default=.5, ge=.2, le=3)    # film nudge either side for stitched scans
    steps_per_mm: float | None = Field(default=None, gt=0)  # learned from stitched scans


class AutoColorRequest(BaseModel):
    enabled: bool = True


class AlignRequest(BaseModel):
    bleed_mm: float = Field(default=0, ge=-2, le=2)
    apply: bool = True


class StitchedScanRequest(BaseModel):
    roll: str = Field(default='', max_length=120)
    offset_mm: float | None = Field(default=None, ge=.2, le=3)
    bleed_mm: float | None = Field(default=None, ge=-2, le=2)
    acknowledged: bool = False


def color_matrix(adjust: Adjustments) -> tuple[np.ndarray, float]:
    """3x3 matrix and offset applied to display values; the client builds the same feColorMatrix."""
    t = adjust.temperature / 100
    scale = 2 ** adjust.exposure
    gains = np.array([scale * (1 + .15 * t), scale, scale * (1 - .15 * t)]) * np.asarray(adjust.rgb_balance)
    s = 1 + adjust.saturation / 100
    luma = np.array([.2126, .7152, .0722])
    saturate = (1 - s) * np.tile(luma, (3, 1)) + s * np.eye(3)
    k = 1 + adjust.contrast / 100
    return k * saturate * gains, .5 * (1 - k)


def before_levels(samples: np.ndarray, adjust: Adjustments, profile=None) -> np.ndarray:
    if adjust.invert:
        # Same nominal optical-density response as frame-density-2. The manually
        # selected base is a display reference, not a calibrated scanner profile.
        samples = 1 - np.power(np.clip(samples / np.asarray(adjust.film_base), 0, 1), 1.6)
    if adjust.film_profile:
        if not profile or profile['id']!=adjust.film_profile:
            raise ValueError('The chosen film rendering profile is unavailable')
        samples=filmterms.apply(samples,profile)
    if adjust.auto_color:
        samples = autocolor.apply(samples, adjust.auto_color)
    return samples


def apply(samples: np.ndarray, adjust: Adjustments, profile=None) -> np.ndarray:
    """Nondestructive transmission, levels, curve, color and orientation pipeline."""
    samples = before_levels(samples,adjust,profile)
    samples = np.clip((samples-adjust.black_point)/(adjust.white_point-adjust.black_point),0,1)**(1/adjust.gamma)
    samples = np.interp(samples,[0,.25,.5,.75,1],adjust.curve)
    matrix, offset = color_matrix(adjust)
    out = np.clip(samples @ matrix.T + offset, 0, 1)
    if adjust.monochrome:
        out=np.repeat((out.mean(axis=2,keepdims=True)>=.5).astype(out.dtype),3,axis=2)
    h,w=out.shape[:2];c=adjust.crop
    x0=min(w-1,int(c.left*w));y0=min(h-1,int(c.top*h))
    x1=max(x0+1,min(w,round(c.right*w)));y1=max(y0+1,min(h,round(c.bottom*h)))
    out=out[y0:y1,x0:x1]
    if adjust.mirror:
        out = out[:, ::-1]
    return np.rot90(out, k=-(adjust.rotation // 90) % 4)


def read_original(path) -> np.ndarray:
    with tifffile.TiffFile(path) as tif:
        values = tif.pages[0].asarray()
    if values.ndim == 2:
        values = np.repeat(values[..., None], 3, axis=2)
    return values


def to_float(values: np.ndarray) -> np.ndarray:
    return values.astype(np.float32) / (65535 if values.dtype == np.uint16 else 255)


def jpeg(samples: np.ndarray, edge: int) -> bytes:
    image = Image.fromarray((np.clip(samples, 0, 1) * 255 + .5).astype(np.uint8))
    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return pipeline.encode(image, 'JPEG')


def register(app, store, publish):
    bridge = configured_bridge()
    # The saved preference only mattered while CyberView capture was offered.
    operation_lock = asyncio.Lock()
    source = SOURCE if bridge.kind == 'cyberview-twain' else NATIVE_SOURCE
    runtime = {'session': None, 'task': None, 'present': (0.0, None), 'live': None}
    saved_workspace = next((p for p in store.all('cv_preferences') if p['id'] == 'workspace'), {})
    scan_options = ScanOptions(**saved_workspace.get('settings', {})).model_dump()
    saved_align = next((p for p in store.all('cv_preferences') if p['id'] == 'align'), {})
    align_settings = AlignSettings(**{k: v for k, v in saved_align.items() if k in AlignSettings.model_fields}).model_dump()

    for item in store.all('cv_sessions'):
        if item['state'] not in ('complete', 'cancelled', 'error'):
            item.update(state='error', error='FRAME stopped during this scan; turn the scanner off and on before retrying')
            store.save('cv_sessions', item)

    def captures():
        return sorted(store.all('cv_captures'), key=lambda c: c['created_at'])

    def resolve_profile(profile_id):
        if not profile_id:return None
        try:
            return filmterms.load(store,profile_id)
        except ValueError:
            profile=next((p for p in filmterms.discover() if p['id']==profile_id),None)
            if profile is None:raise HTTPException(409,'The film rendering profile is no longer installed or cached')
            filmterms.remember(store,profile)
            return profile

    def capture(capture_id):
        try:
            return store.get('cv_captures', capture_id)
        except KeyError:
            raise HTTPException(404, 'Capture not found')

    def present():
        checked, value = runtime['present']
        if time.monotonic() - checked > 5:
            value = cyberview.scanner_present()
            runtime['present'] = (time.monotonic(), value)
        return value

    def status():
        return {'bridge_built': bridge.built(), 'busy': bridge.busy, 'session_open': bridge.open,
                'auto_reset': bridge.kind == 'cyberview-twain' and cyberview.reset_available(),
                'vendor_open': False if bridge.open else cyberview.vendor_running(),
                'scanner_present': present(), 'settings': bridge.acquisition_settings(),
                'session': runtime['session'], 'source': source, 'backend': bridge.kind,
                'supports_next': bridge.supports_next, 'max_count': bridge.max_count,
                'image_kind': bridge.image_kind,
                'experimental_enabled': bridge.enabled,
                'native': {'dpi': 1800, 'bits': 16, 'note': (
                    'CyberView delivers the frame inverted with its selected film term' if bridge.kind == 'cyberview-twain'
                    else 'Vendor-calibrated transmission, identity LUT; effective sensor precision is unmeasured')}}

    async def update_session(**changes):
        session = runtime['session']
        session.update(changes)
        store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': session})

    async def relay_live(session, event, frame):
        """Live preview rows from the bridge's USB watch: raw transmission, 1/8 size, 8-bit."""
        kind = event.get('event')
        if kind == 'live_start':
            runtime['live'] = {'session_id': session['id'], 'frame': frame, 'pass': event['pass'], 'width': event['width'],
                               'source_width': event['source_width'], 'scale': event['scale'], 'rows': []}
            await publish({'type': 'cyberview_live_start'} | {k: v for k, v in runtime['live'].items() if k != 'rows'})
        elif kind == 'live' and runtime['live'] and runtime['live']['pass'] == event['pass']:
            rows = runtime['live']['rows']
            if event['y'] == len(rows) and len(rows) < LIVE_MAX_ROWS:
                rows.append(event['data'])
                await publish({'type': 'cyberview_live', 'session_id': session['id'], 'pass': event['pass'],
                               'y': event['y'], 'data': event['data']})

    def finalize(session, event, index):
        """Moves one delivered TIFF into place, hashes it and writes its previews."""
        incoming = Path(event['path']).resolve()
        if not incoming.is_relative_to(store.root):
            raise ScannerError('The driver wrote outside the library')
        capture_id = uuid.uuid4().hex
        base = f"cyberview/{session['id']}/{index:02d}-{capture_id[:8]}"
        original = store.path(base + '.tif')
        os.replace(incoming, original)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        samples = to_float(read_original(original))
        atomic_write(store.path(base + '-preview.jpg'), jpeg(samples, PREVIEW_EDGE))
        atomic_write(store.path(base + '-thumb.jpg'), jpeg(samples, THUMB_EDGE))
        record = {'id': capture_id, 'session_id': session['id'], 'index': index, 'roll': session['roll'],
                  'title': f"{session['roll'] or 'Roll'} · {index:02d}", 'created_at': int(time.time() * 1000),
                  'original_path': base + '.tif', 'preview_path': base + '-preview.jpg', 'thumb_path': base + '-thumb.jpg',
                  'sha256': digest, 'width': event['width'], 'height': event['height'], 'bits': event['bits'],
                  'dpi': round(event['dpi']), 'source': source, 'hardware': not event.get('synthetic', False), 'favorite': False,
                  'backend': bridge.kind, 'image_kind': bridge.image_kind, 'effective_bits': None,
                  'purpose': session.get('purpose', 'scan'), 'requested_settings': session.get('requested_settings'),
                  'cyberview': session['settings'],
                  'adjustments': Adjustments(monochrome=event.get('binary_recipe_requested',False), invert=bridge.image_kind == 'vendor-calibrated-transmission' and
                                             session.get('requested_settings', {}).get('film', 'negative') == 'negative').model_dump()}
        # CyberView applies Auto Gamma to every scan; so does CyberScan X (toggle per frame).
        record['adjustments']['auto_color'] = autocolor.for_positive(before_levels(samples, Adjustments(**record['adjustments'])))
        if align_settings['auto'] and session.get('purpose', 'scan') == 'scan':
            align_record(record, samples, align_settings['bleed_mm'])
        atomic_write(store.path(base + '.json'), json.dumps(record, indent=1).encode())
        return store.save('cv_captures', record)

    def align_record(record, samples, bleed_mm, covered=None):
        """Finds the 35 mm frame and, when an exact crop fits, makes it the capture's crop."""
        result = frame_align.align_35mm(samples, record['dpi'], record.get('image_kind') == 'vendor-calibrated-transmission',
                                        bleed_mm, covered=covered)
        record['alignment'] = {k: result[k] for k in ('confidence', 'exact', 'crop_mm', 'crop_px', 'skew_deg', 'bleed_mm')} | {
            'edges_x': result['x'], 'note': result.get('note'), 'at': int(time.time() * 1000)}
        if result['exact']:
            record['adjustments'] = Adjustments(**(record['adjustments'] | {'crop': result['crop']})).model_dump()
        return result

    async def run(session):
        index = 0

        async def on_event(event):
            nonlocal index
            kind = event.get('event')
            if kind == 'enabled':
                await update_session(state='warming')
            elif kind == 'command' and event.get('name') == 'next':
                await update_session(state='advancing', driver_status='Moving to the next frame')
            elif kind == 'driver_status':
                await update_session(driver_status=event.get('text'))
            elif kind == 'driver_dialog':
                # Left on screen by the bridge so the user can answer CyberView directly.
                await update_session(driver_dialog=' '.join(filter(None, (event.get('title'), event.get('text')))))
            elif kind == 'image_start':
                await update_session(state='scanning', frame=index + 1, rows=0, height=event['height'],
                                     delivered={k:event.get(k) for k in ('width','height','bits','dpi','samples')})
            elif kind == 'progress':
                session.update(rows=event['rows'], height=event['height'])
                await publish({'type': 'cyberview_progress', 'session_id': session['id'], 'frame': index + 1,
                               'rows': event['rows'], 'height': event['height']})
            elif kind in ('live_start', 'live'):
                await relay_live(session, event, index + 1)
            elif kind == 'image':
                index += 1
                await update_session(state='saving')
                record = await asyncio.to_thread(finalize, session, event, index)
                session['captures'].append(record['id'])
                await update_session(state='scanning' if index < session['count'] else 'saving', completed=index)
                await publish({'type': 'cyberview_capture', 'capture': record})

        incoming = store.path(f"cyberview/{session['id']}/incoming.tif")
        try:
            try:
                await bridge.scan(incoming, session['count'], on_event)
            except ScannerError as exc:
                # A stalled AFL is recovered once by restarting its USB device, if the
                # reset task is installed; frames already saved are not scanned again.
                if bridge.kind != 'cyberview-twain' or str(exc) != cyberview.STUCK or bridge.cancel_requested:
                    raise
                await update_session(state='recovering', driver_status='Restarting the scanner')
                if not await cyberview.reset_scanner():
                    raise
                remaining = session['count'] - index
                await update_session(state='starting', driver_status=None)
                await bridge.scan(store.path(f"cyberview/{session['id']}/incoming-retry.tif"), remaining, on_event)
            state = 'cancelled' if bridge.cancel_requested else 'complete'
            if state == 'complete' and index != session['count']:
                raise ScannerError(f'The driver delivered {index} of {session["count"]} requested frames')
            await update_session(state=state, finished_at=int(time.time() * 1000))
        except ScannerError as exc:
            await update_session(state='error', error=str(exc), finished_at=int(time.time() * 1000))
        except Exception as exc:  # recorded, never reported as success
            await update_session(state='error', error=f'Unexpected failure: {exc}', finished_at=int(time.time() * 1000))
        finally:
            for leftover in incoming.parent.glob('incoming*.tif'):
                leftover.unlink(missing_ok=True)

    @app.get('/api/cyberview/status')
    async def get_status():
        return await asyncio.to_thread(status)

    def workspace_view():
        prescans = [c for c in captures() if c.get('purpose') == 'prescan']
        return {'settings': scan_options, 'capabilities': workspace.capabilities(bridge, scan_options),
                'prescan': prescans[-1] if prescans else None}

    @app.get('/api/cyberview/live')
    async def cyberview_live():
        """The live preview of the frame being scanned (or the last one), for a client that joined late."""
        return {'live': runtime['live']}

    @app.get('/api/cyberview/workspace')
    async def get_workspace():
        return workspace_view()

    @app.put('/api/cyberview/workspace')
    async def save_workspace(body: ScanOptions):
        nonlocal scan_options
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Finish the current scanner operation before changing settings')
            scan_options = body.model_dump()
            store.save('cv_preferences', {'id': 'workspace', 'settings': scan_options})
            return workspace_view()

    @app.post('/api/cyberview/prescan')
    async def prescan(body: ScanRequest):
        selected = (body.settings or ScanOptions(**scan_options)).model_dump()
        selected.update(dpi=300, bits=8, channel='rgb', focus=None)
        async with operation_lock:
            if bridge.kind != 'afl-native-experimental':
                raise HTTPException(409, 'Choose native capture for genuine low-resolution prescan')
            return await start_locked(ScanRequest(count=1, roll=body.roll, settings=ScanOptions(**selected), purpose='prescan'))

    @app.get('/api/cyberview/diagnostics')
    async def diagnostics():
        """Inspect installed files and research evidence without initializing hardware."""
        result = await asyncio.to_thread(vendor_evidence.inspect_installation)
        result['active_backend'] = bridge.kind
        result['driver'] = await asyncio.to_thread(driver.status)
        return result

    @app.post('/api/cyberview/scan')
    async def start(body: ScanRequest):
        async with operation_lock:
            return await start_locked(body)

    async def start_locked(body: ScanRequest):
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'A scan is already running')
        if not bridge.built():
            raise HTTPException(409, 'The CyberView bridge is not built; run services/cyberview_bridge/build.ps1')
        if body.count > bridge.max_count:
            raise HTTPException(422, 'This backend supports only the current frame; native film transport is not validated')
        if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
            raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
        selected = (body.settings or ScanOptions(**scan_options)).model_dump()
        if bridge.kind == 'afl-native-experimental':
            try:
                await bridge.configure(selected)
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
        elif selected != workspace.DEFAULT_OPTIONS:
            raise HTTPException(409, 'CyberView ignores these acquisition settings in hidden mode; choose native capture')
        session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': body.count, 'completed': 0,
                   'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                   'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0, 'rows': 0, 'height': 0, 'error': None,
                   'purpose': body.purpose, 'requested_settings': selected,
                   'driver_status': None, 'driver_dialog': None}
        runtime['session'] = store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': session})
        runtime['task'] = asyncio.create_task(run(session))
        return session

    @app.post('/api/cyberview/backend')
    async def select_backend(body: BackendRequest):
        nonlocal bridge, source
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Finish the current scanner operation before changing the interface')
            if body.backend == 'afl-native-experimental':
                if not body.acknowledged:
                    raise HTTPException(422, 'Acknowledge native startup, current-frame-only operation and transmission output')
                evidence = await asyncio.to_thread(vendor_evidence.inspect_installation)
                if not evidence['native_module_recognized']:
                    raise HTTPException(409, 'The installed AFL module does not match the reviewed version')
                candidate = NativeAflBridge(device_test_approved=True)
            else:
                candidate = cyberview.CyberViewBridge()
            if not candidate.built():
                raise HTTPException(409, 'Build the selected scanner bridge before using it')
            try:
                await bridge.release()
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
            bridge = candidate
            integration['bridge'] = bridge
            source = SOURCE if bridge.kind == 'cyberview-twain' else NATIVE_SOURCE
            store.save('cv_preferences', {'id': 'scanner', 'backend': body.backend, 'acknowledged': body.acknowledged})
            return await asyncio.to_thread(status)

    @app.post('/api/cyberview/cancel')
    async def cancel():
        if not bridge.busy:
            raise HTTPException(409, 'No scan is running')
        if runtime['task'] and not runtime['task'].done():
            await update_session(state='cancelling')
        await bridge.cancel()
        return runtime['session'] if runtime['task'] and not runtime['task'].done() else {'state':'cancelling','operation':'scanner_control'}

    @app.post('/api/cyberview/film')
    async def film(body: FilmRequest):
        async with operation_lock:
            return await film_locked(body)

    async def film_locked(body: FilmRequest):
        """Moves the film with CyberView's own transport commands."""
        capability = workspace.capabilities(bridge, scan_options)['actions'][body.action]
        if not capability['available']:
            raise HTTPException(409, capability['reason'])
        if body.action != 'next' and not body.acknowledged:
            raise HTTPException(422, 'Confirm the requested film movement')
        if body.action == 'goto' and body.frame is None:
            raise HTTPException(422, 'Choose a destination frame')
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'Wait for the scan to finish')
        if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
            raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
        await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'moving'})
        try:
            if bridge.kind == 'afl-native-experimental':
                await bridge.film(body.action, frame=body.frame)
            else:
                await bridge.film(body.action)
        except ScannerError as exc:
            await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'error'})
            raise HTTPException(409, str(exc))
        await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'done'})
        return await asyncio.to_thread(status)

    @app.post('/api/cyberview/control')
    async def scanner_control(body: ControlRequest):
        nonlocal scan_options
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Finish the current scanner operation first')
            capability = workspace.capabilities(bridge, scan_options)['actions'][body.action]
            if bridge.kind != 'afl-native-experimental' or not capability['available']:
                raise HTTPException(409, capability['reason'])
            if not body.acknowledged:
                raise HTTPException(422, 'Confirm this scanner operation')
            if body.action == 'focus' and body.value is None:
                raise HTTPException(422, 'Choose a focus value')
            measured = {}

            def on_event(event):
                if event.get('event') == 'calibration':
                    measured['rgb'] = event['rgb']
            try:
                await bridge.control(body.action, on_event, value=body.value)
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
            if measured:
                # CyberView's "auto exposure" on the PF1800 AFL: the measured film base
                # becomes the per-channel exposure of the next scans (docs/auto-color-re.md).
                exposure = [min(workspace.EXPOSURE_MAX, max(50, int(v))) for v in measured['rgb']]
                scan_options = ScanOptions(**(scan_options | {'exposure': exposure})).model_dump()
                store.save('cv_preferences', {'id': 'workspace', 'settings': scan_options})
            return await asyncio.to_thread(status) | ({'film_base_exposure': measured['rgb']} if measured else {})

    @app.post('/api/cyberview/release')
    async def release():
        async with operation_lock:
            return await release_locked()

    async def release_locked():
        """Closes the hidden driver session so CyberView X can be opened."""
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'Stop the scan first')
        try:
            await bridge.release()
        except ScannerError as exc:
            raise HTTPException(409, str(exc))
        return await asyncio.to_thread(status)

    @app.get('/api/cyberview/captures')
    async def list_captures():
        return {'captures': captures()}

    def histogram(record):
        adjust=Adjustments(**record['adjustments'])
        values = before_levels(to_float(read_original(store.path(record['original_path']))),adjust,resolve_profile(adjust.film_profile))
        bins=[np.histogram(values[...,c],bins=256,range=(0,1))[0].tolist() for c in range(3)]
        low,high=np.percentile(values,[.5,99.5])
        return {'bins':bins,'percentiles':{'black':float(low),'white':float(high)},
                'original':False,'stage':'before_levels','source_sha256':record['sha256']}

    @app.get('/api/cyberview/captures/{capture_id}/histogram')
    async def get_histogram(capture_id: str):
        return await asyncio.to_thread(histogram,capture(capture_id))

    # ---------- 35 mm auto-align ----------

    def stitch_capability():
        # Both paths end in SCAN08 selector 10: the native module directly, or CyberView's
        # Forward/Backward One Step menu commands through the hidden bridge.
        if bridge.kind == 'afl-native-experimental':
            ok = 'nudge' in workspace.validation().get('actions', [])
            reason = 'Film nudging (selector 10) needs one supervised test before stitched scans are enabled.'
        else:
            ok = bridge.can_nudge()
            reason = "CyberView's step moves need one supervised test before stitched scans are enabled."
        return {'available': ok, 'reason': '' if ok else reason}

    @app.get('/api/cyberview/align')
    async def get_align():
        return {'settings': align_settings, 'stitched_scan': stitch_capability(), 'frame_mm': list(frame_align.FRAME_MM),
                'max_window_mm': [round(2586 / 1800 * 25.4, 2), round(1708 / 1800 * 25.4, 2)]}

    @app.put('/api/cyberview/align')
    async def save_align(body: AlignSettings):
        align_settings.update(body.model_dump(exclude={'steps_per_mm'}))
        store.save('cv_preferences', {'id': 'align', **align_settings})
        return await get_align()

    @app.post('/api/cyberview/captures/{capture_id}/auto-align')
    async def auto_align(capture_id: str, body: AlignRequest):
        record = capture(capture_id)

        def work():
            samples = to_float(read_original(store.path(record['original_path'])))
            covered = None
            if record.get('coverage_path'):
                covered = np.asarray(Image.open(store.path(record['coverage_path']))) > 0
            return align_record(record, samples, body.bleed_mm, covered)

        result = await asyncio.to_thread(work)
        if body.apply:
            store.save('cv_captures', record)
        return {'alignment': record['alignment'], 'capture': record, 'applied': body.apply and result['exact']}

    @app.post('/api/cyberview/stitched-scan')
    async def stitched_scan(body: StitchedScanRequest):
        """Three scans with the film nudged back and forward, stitched and aligned to 36 x 24 mm."""
        async with operation_lock:
            capability = stitch_capability()
            if not capability['available']:
                raise HTTPException(409, capability['reason'])
            if not body.acknowledged:
                raise HTTPException(422, 'Confirm that the film will be moved a little back and forward')
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'A scan is already running')
            offset = body.offset_mm or align_settings['offset_mm']
            bleed = align_settings['bleed_mm'] if body.bleed_mm is None else body.bleed_mm
            if hasattr(bridge, 'configure'):  # native capture; CyberView scans with its own settings
                try:
                    await bridge.configure(scan_options)
                except ScannerError as exc:
                    raise HTTPException(409, str(exc))
            session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': 3, 'completed': 0, 'roll': body.roll.strip(),
                       'captures': [], 'started_at': int(time.time() * 1000), 'settings': bridge.acquisition_settings(),
                       'backend': bridge.kind, 'frame': 0, 'rows': 0, 'height': 0, 'error': None, 'purpose': 'stitched',
                       'requested_settings': scan_options, 'driver_status': None, 'driver_dialog': None,
                       'stitch': {'offset_mm': offset, 'bleed_mm': bleed}}
            runtime['session'] = store.save('cv_sessions', session)
            await publish({'type': 'cyberview_session', 'session': session})
            runtime['task'] = asyncio.create_task(run_stitched(session, offset, bleed))
            return session

    async def run_stitched(session, offset_mm, bleed_mm):
        folder = f"cyberview/{session['id']}"
        sources = []

        async def relay(event):
            kind = event.get('event')
            if kind == 'enabled':
                await update_session(state='warming')
            elif kind == 'driver_status':
                await update_session(driver_status=event.get('text'))
            elif kind == 'image_start':
                await update_session(state='scanning', frame=len(sources) + 1, rows=0, height=event['height'])
            elif kind == 'progress':
                session.update(rows=event['rows'], height=event['height'])
                await publish({'type': 'cyberview_progress', 'session_id': session['id'], 'frame': len(sources) + 1,
                               'rows': event['rows'], 'height': event['height']})
            elif kind in ('live_start', 'live'):
                await relay_live(session, event, len(sources) + 1)

        async def take(label):
            path = store.path(f'{folder}/source-{label}.tif')
            images = await bridge.scan(path, 1, relay)
            if bridge.cancel_requested or not images:
                raise ScannerError('The stitched scan was stopped')
            sources.append({'label': label, 'path': f'{folder}/source-{label}.tif',
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'dpi': round(images[0]['dpi'])})
            await update_session(completed=len(sources))
            return to_float(read_original(path))

        async def nudge(direction, steps):
            await update_session(state='advancing', driver_status=f'Moving the film {direction} {steps} steps')
            remaining = steps
            while remaining > 0:   # the module accepts at most 300 steps per call
                chunk = min(remaining, 300)
                await bridge.control('nudge', value=f'{direction} {chunk}')
                remaining -= chunk

        def measured_shift(reference, moved, dpi, guess_px):
            luma = frame_align.LUMA
            dy, dx, strength = frame_align.phase_shift(reference[..., :3] @ luma, moved[..., :3] @ luma, (0, guess_px),
                                                       frame_align.mm_to_px(4, dpi))
            return dx, strength

        try:
            centre = await take('centre')
            dpi = sources[0]['dpi']
            # Probe: a small move whose real size, measured from the images, calibrates the rest.
            spm = align_settings.get('steps_per_mm')
            probe = max(1, min(300, round(offset_mm * spm))) if spm else 20
            await nudge('back', probe)
            back = await take('back')
            dx_back, strength = await asyncio.to_thread(measured_shift, centre, back, dpi, 0)
            moved_mm = abs(dx_back) / dpi * frame_align.MM_PER_INCH
            if moved_mm < .05 or strength < .05:
                raise ScannerError('The film did not move measurably during the nudge; the stitched scan was stopped.')
            spm = probe / moved_mm
            align_settings['steps_per_mm'] = round(spm, 3)
            store.save('cv_preferences', {'id': 'align', **align_settings})
            forward_steps = round((moved_mm + offset_mm) * spm)
            if forward_steps > 900:
                raise ScannerError('The measured film movement is implausibly small; not moving further.')
            await nudge('forward', forward_steps)
            fwd = await take('forward')
            await nudge('back', max(1, round(offset_mm * spm)))   # leave the film where it started
            await update_session(state='saving', driver_status='Stitching and aligning')

            def build():
                scans = [back, centre, fwd]
                # Expected positions only seed the search; stitch() measures the real ones.
                forward_px = -np.sign(dx_back) * frame_align.mm_to_px(offset_mm, dpi)
                stitched = frame_align.stitch(scans, [dx_back, 0, forward_px], reference=1,
                                              search_px=frame_align.mm_to_px(1.5, dpi))
                image = stitched['image']
                capture_id = uuid.uuid4().hex
                base = f"{folder}/stitched-{capture_id[:8]}"
                stream = BytesIO()
                tifffile.imwrite(stream, (np.clip(image, 0, 1) * 65535 + .5).astype(np.uint16), photometric='rgb',
                                 resolution=(dpi, dpi), resolutionunit='INCH', software='FRAME CyberScan X stitch')
                atomic_write(store.path(base + '.tif'), stream.getvalue())
                cover = BytesIO(); Image.fromarray((stitched['covered'] * 255).astype(np.uint8)).save(cover, 'PNG')
                atomic_write(store.path(base + '-coverage.png'), cover.getvalue())
                atomic_write(store.path(base + '-preview.jpg'), jpeg(image, PREVIEW_EDGE))
                atomic_write(store.path(base + '-thumb.jpg'), jpeg(image, THUMB_EDGE))
                h, w = image.shape[:2]
                record = {'id': capture_id, 'session_id': session['id'], 'index': 1, 'roll': session['roll'],
                          'title': f"{session['roll'] or 'Roll'} · stitched", 'created_at': int(time.time() * 1000),
                          'original_path': base + '.tif', 'preview_path': base + '-preview.jpg', 'thumb_path': base + '-thumb.jpg',
                          'coverage_path': base + '-coverage.png',
                          'sha256': hashlib.sha256(store.path(base + '.tif').read_bytes()).hexdigest(),
                          'width': w, 'height': h, 'bits': 16, 'dpi': dpi, 'source': source, 'hardware': True, 'favorite': False,
                          'backend': bridge.kind, 'image_kind': bridge.image_kind, 'effective_bits': None, 'purpose': 'stitched',
                          'derived': {'kind': 'stitched', 'sources': sources, 'offsets_px': stitched['offsets_px'],
                                      'gains': stitched['gains'], 'match_strength': stitched['match_strength'],
                                      'steps_per_mm': align_settings['steps_per_mm'],
                                      'note': 'Built from the three source scans kept next to it; those are the originals.'},
                          'requested_settings': session.get('requested_settings'), 'cyberview': session['settings'],
                          'adjustments': Adjustments(invert=bridge.image_kind == 'vendor-calibrated-transmission').model_dump()}
                align_record(record, image, bleed_mm, stitched['covered'])
                atomic_write(store.path(base + '.json'), json.dumps(record, indent=1).encode())
                return store.save('cv_captures', record)

            record = await asyncio.to_thread(build)
            session['captures'].append(record['id'])
            await publish({'type': 'cyberview_capture', 'capture': record})
            await update_session(state='complete', finished_at=int(time.time() * 1000), alignment=record['alignment'])
        except ScannerError as exc:
            await update_session(state='error', error=str(exc), finished_at=int(time.time() * 1000))
        except Exception as exc:  # recorded, never reported as success
            await update_session(state='error', error=f'Unexpected failure: {exc}', finished_at=int(time.time() * 1000))

    @app.post('/api/cyberview/captures/{capture_id}/auto-color')
    async def auto_color(capture_id: str, body: AutoColorRequest):
        """Turns CyberView's automatic colour on (computed from this frame) or off."""
        record = capture(capture_id)
        adjust = Adjustments(**(record['adjustments'] | {'auto_color': None}))
        words = None
        if body.enabled:
            samples = await asyncio.to_thread(lambda: before_levels(to_float(read_original(store.path(record['original_path']))),
                                                                    adjust, resolve_profile(adjust.film_profile)))
            words = autocolor.for_positive(samples)
            if words is None:
                raise HTTPException(409, 'This frame has no near-neutral midtones, so automatic colour does not apply')
        record['adjustments'] = adjust.model_copy(update={'auto_color': words}).model_dump()
        return store.save('cv_captures', record)

    @app.post('/api/cyberview/captures/{capture_id}/auto-levels')
    async def auto_levels(capture_id: str):
        record=capture(capture_id)
        data=await asyncio.to_thread(histogram,record)
        low,high=data['percentiles']['black'],data['percentiles']['white']
        if high-low<.001:
            raise HTTPException(409,'This image has too little range for automatic levels')
        record['adjustments']=Adjustments(**(record['adjustments']|{'black_point':low,'white_point':high})).model_dump()
        return store.save('cv_captures',record)

    @app.patch('/api/cyberview/captures/{capture_id}')
    async def update_capture(capture_id: str, body: CaptureUpdate):
        record = capture(capture_id)
        if body.adjustments:
            if body.adjustments.rotation % 90:
                raise HTTPException(422, 'Rotation must be a multiple of 90 degrees')
            if body.adjustments.film_profile:
                await asyncio.to_thread(resolve_profile,body.adjustments.film_profile)
            record['adjustments'] = body.adjustments.model_dump() | {'rotation': body.adjustments.rotation % 360}
        if body.title is not None:
            record['title'] = body.title.strip() or record['title']
        if body.favorite is not None:
            record['favorite'] = body.favorite
        return store.save('cv_captures', record)

    @app.post('/api/cyberview/captures/{capture_id}/apply-to-roll')
    async def apply_to_roll(capture_id: str, body: RollAdjustments):
        if body.adjustments.film_profile:
            await asyncio.to_thread(resolve_profile,body.adjustments.film_profile)
        source_record=capture(capture_id)
        if body.adjustments.rotation%90:
            raise HTTPException(422,'Rotation must be a multiple of 90 degrees')
        edits=body.adjustments.model_dump(exclude={'rotation','mirror','crop'})
        selected=[c for c in captures() if (c['roll']==source_record['roll'] if source_record['roll'] else c['session_id']==source_record['session_id'])]
        for record in selected:
            record['adjustments']=Adjustments(**(record['adjustments']|edits)).model_dump()
        store.save_many('cv_captures',selected)
        return {'captures':selected,'count':len(selected)}

    @app.get('/api/cyberview/captures/{capture_id}/profile-preview')
    async def profile_preview(capture_id: str, profile_id: str, invert: bool=False,
                              base_r: float=1,base_g: float=1,base_b: float=1):
        record=capture(capture_id)
        try:adjust=Adjustments(film_profile=profile_id,invert=invert,film_base=[base_r,base_g,base_b])
        except ValueError as exc:raise HTTPException(422,'Invalid profile preview settings') from exc
        def render():
            values=before_levels(to_float(read_original(store.path(record['original_path']))),adjust,resolve_profile(profile_id))
            return jpeg(values,PREVIEW_EDGE)
        return Response(await asyncio.to_thread(render),media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})

    @app.get('/api/cyberview/captures/{capture_id}/{kind}')
    async def capture_file(capture_id: str, kind: str):
        record = capture(capture_id)
        paths = {'preview': record['preview_path'], 'thumb': record['thumb_path']}
        if kind not in paths:
            raise HTTPException(404, 'Unknown image')
        return FileResponse(store.path(paths[kind]), media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})

    @app.get('/api/cyberview/captures/{capture_id}/export/{fmt}')
    async def export(capture_id: str, fmt: str):
        record = capture(capture_id)
        name = '-'.join(''.join(c if c.isalnum() or c in '-_' else ' ' for c in record['title']).split()) or 'scan'
        original = store.path(record['original_path'])
        if fmt in ('metadata','json'):
            return Response(json.dumps(record,indent=2).encode(),media_type='application/json',headers={
                'Content-Disposition':f'attachment; filename="{name}.json"'})
        if fmt == 'original':
            if hashlib.sha256(original.read_bytes()).hexdigest() != record['sha256']:
                raise HTTPException(500, 'The original no longer matches its recorded checksum')
            return FileResponse(original, media_type='image/tiff', filename=f'{name}-original.tif')
        if fmt not in ('jpeg', 'tiff'):
            raise HTTPException(404, 'Export as original, jpeg or tiff')

        def render():
            adjust=Adjustments(**record['adjustments'])
            samples = apply(to_float(read_original(original)), adjust,resolve_profile(adjust.film_profile))
            if fmt == 'jpeg':
                image = Image.fromarray((samples * 255 + .5).astype(np.uint8))
                return pipeline.encode(image, 'JPEG')
            stream = BytesIO()
            tifffile.imwrite(stream, (samples * 65535 + .5).astype(np.uint16), photometric='rgb',
                             resolution=(record['dpi'], record['dpi']), resolutionunit='INCH',
                             iccprofile=pipeline.SRGB, software='FRAME CyberScan X')
            return stream.getvalue()

        data = await asyncio.to_thread(render)
        media = 'image/jpeg' if fmt == 'jpeg' else 'image/tiff'
        return Response(data, media_type=media, headers={
            'Content-Disposition': f'attachment; filename="{name}.{"jpg" if fmt == "jpeg" else "tif"}"'})

    async def startup_recover():
        await bridge.restore_settings()

    async def idle():
        task = runtime['task']
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), 90)
            except asyncio.TimeoutError:
                pass

    integration = {'bridge': bridge, 'runtime': runtime, 'recover': startup_recover, 'idle': idle}
    return integration
