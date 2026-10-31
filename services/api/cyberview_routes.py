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

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field
import tifffile

from services.api.store import atomic_write
from services.imaging import pipeline
from services.scanner_host import cyberview
from services.scanner_host.backend import ScannerError

SOURCE = 'CyberView X - MF (TWAIN, hidden) on PrimeFilm PF1800 AFL'
PREVIEW_EDGE = 1800
THUMB_EDGE = 360


class ScanRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=40)
    roll: str = Field(default='', max_length=120)


class FilmRequest(BaseModel):
    action: str = Field(pattern='^next$')


class Adjustments(BaseModel):
    exposure: float = Field(default=0, ge=-2, le=2)
    contrast: float = Field(default=0, ge=-100, le=100)
    saturation: float = Field(default=0, ge=-100, le=100)
    temperature: float = Field(default=0, ge=-100, le=100)
    rotation: int = 0
    mirror: bool = False


class CaptureUpdate(BaseModel):
    adjustments: Adjustments | None = None
    title: str | None = Field(default=None, max_length=120)
    favorite: bool | None = None


def color_matrix(adjust: Adjustments) -> tuple[np.ndarray, float]:
    """3x3 matrix and offset applied to display values; the client builds the same feColorMatrix."""
    t = adjust.temperature / 100
    scale = 2 ** adjust.exposure
    gains = np.array([scale * (1 + .15 * t), scale, scale * (1 - .15 * t)])
    s = 1 + adjust.saturation / 100
    luma = np.array([.2126, .7152, .0722])
    saturate = (1 - s) * np.tile(luma, (3, 1)) + s * np.eye(3)
    k = 1 + adjust.contrast / 100
    return k * saturate * gains, .5 * (1 - k)


def apply(samples: np.ndarray, adjust: Adjustments) -> np.ndarray:
    """samples: HxWx3 floats in 0..1. Returns adjusted, rotated and mirrored floats in 0..1."""
    matrix, offset = color_matrix(adjust)
    out = np.clip(samples @ matrix.T + offset, 0, 1)
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
    bridge = cyberview.CyberViewBridge()
    runtime = {'session': None, 'task': None, 'present': (0.0, None)}

    for item in store.all('cv_sessions'):
        if item['state'] not in ('complete', 'cancelled', 'error'):
            item.update(state='error', error='FRAME stopped during this scan; turn the scanner off and on before retrying')
            store.save('cv_sessions', item)

    def captures():
        return sorted(store.all('cv_captures'), key=lambda c: c['created_at'])

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
                'auto_reset': cyberview.reset_available(),
                'vendor_open': False if bridge.open else cyberview.vendor_running(),
                'scanner_present': present(), 'settings': cyberview.read_settings(),
                'session': runtime['session'], 'source': SOURCE,
                'native': {'dpi': 1800, 'bits': 16, 'note': 'CyberView delivers the frame inverted with its selected film term'}}

    async def update_session(**changes):
        session = runtime['session']
        session.update(changes)
        store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': session})

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
                  'dpi': round(event['dpi']), 'source': SOURCE, 'hardware': True, 'favorite': False,
                  'cyberview': session['settings'], 'adjustments': Adjustments().model_dump()}
        atomic_write(store.path(base + '.json'), json.dumps(record, indent=1).encode())
        return store.save('cv_captures', record)

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
                await update_session(state='scanning', frame=index + 1, rows=0, height=event['height'])
            elif kind == 'progress':
                session.update(rows=event['rows'], height=event['height'])
                await publish({'type': 'cyberview_progress', 'session_id': session['id'], 'frame': index + 1,
                               'rows': event['rows'], 'height': event['height']})
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
                if str(exc) != cyberview.STUCK or bridge.cancel_requested:
                    raise
                await update_session(state='recovering', driver_status='Restarting the scanner')
                if not await cyberview.reset_scanner():
                    raise
                remaining = session['count'] - index
                await update_session(state='starting', driver_status=None)
                await bridge.scan(store.path(f"cyberview/{session['id']}/incoming-retry.tif"), remaining, on_event)
            state = 'cancelled' if bridge.cancel_requested else 'complete'
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

    @app.post('/api/cyberview/scan')
    async def start(body: ScanRequest):
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'A scan is already running')
        if not bridge.built():
            raise HTTPException(409, 'The CyberView bridge is not built; run services/cyberview_bridge/build.ps1')
        if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
            raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
        session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': body.count, 'completed': 0,
                   'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                   'settings': cyberview.read_settings(), 'frame': 0, 'rows': 0, 'height': 0, 'error': None,
                   'driver_status': None, 'driver_dialog': None}
        runtime['session'] = store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': session})
        runtime['task'] = asyncio.create_task(run(session))
        return session

    @app.post('/api/cyberview/cancel')
    async def cancel():
        if not bridge.busy:
            raise HTTPException(409, 'No scan is running')
        await update_session(state='cancelling')
        await bridge.cancel()
        return runtime['session']

    @app.post('/api/cyberview/film')
    async def film(body: FilmRequest):
        """Moves the film with CyberView's own transport commands."""
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'Wait for the scan to finish')
        if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
            raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
        await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'moving'})
        try:
            await bridge.film(body.action)
        except ScannerError as exc:
            await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'error'})
            raise HTTPException(409, str(exc))
        await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'done'})
        return await asyncio.to_thread(status)

    @app.post('/api/cyberview/release')
    async def release():
        """Closes the hidden driver session so CyberView X can be opened."""
        if bridge.busy:
            raise HTTPException(409, 'Stop the scan first')
        await bridge.release()
        return await asyncio.to_thread(status)

    @app.get('/api/cyberview/captures')
    async def list_captures():
        return {'captures': captures()}

    @app.patch('/api/cyberview/captures/{capture_id}')
    async def update_capture(capture_id: str, body: CaptureUpdate):
        record = capture(capture_id)
        if body.adjustments:
            if body.adjustments.rotation % 90:
                raise HTTPException(422, 'Rotation must be a multiple of 90 degrees')
            record['adjustments'] = body.adjustments.model_dump() | {'rotation': body.adjustments.rotation % 360}
        if body.title is not None:
            record['title'] = body.title.strip() or record['title']
        if body.favorite is not None:
            record['favorite'] = body.favorite
        return store.save('cv_captures', record)

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
        if fmt == 'original':
            if hashlib.sha256(original.read_bytes()).hexdigest() != record['sha256']:
                raise HTTPException(500, 'The original no longer matches its recorded checksum')
            return FileResponse(original, media_type='image/tiff', filename=f'{name}-original.tif')
        if fmt not in ('jpeg', 'tiff'):
            raise HTTPException(404, 'Export as original, jpeg or tiff')

        def render():
            samples = apply(to_float(read_original(original)), Adjustments(**record['adjustments']))
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

    return {'bridge': bridge, 'runtime': runtime, 'recover': startup_recover, 'idle': idle}
