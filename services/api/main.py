import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import secrets
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from services.api import cyberview_routes, developing
from services.api.store import Store, atomic_write
from services.imaging import filmterms, pipeline

PROJECT = Path(__file__).resolve().parents[2]


class RollInput(BaseModel):
    stock: str = Field(min_length=1, max_length=120)
    camera: str = Field(default='', max_length=120)
    iso: int = Field(default=400, ge=1, le=25600)
    format: str = '35mm'
    film_type: str = 'color_negative'
    notes: str = Field(default='', max_length=4000)
    date: str = ''
    tags: list[str] = Field(default_factory=list, max_length=30)


class ScanWindow(BaseModel):
    left: float = Field(ge=0, le=.95)
    top: float = Field(ge=0, le=.95)
    width: float = Field(ge=.05, le=1)
    height: float = Field(ge=.05, le=1)


class ScanSettings(BaseModel):
    # Requested values are recorded; the simulator always returns 192x128 8-bit fixtures.
    dpi: int = 1800
    bit_depth: int = 8
    window: ScanWindow | None = None
    gains: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    film_profile: str | None = None

    @field_validator('dpi')
    @classmethod
    def validate_dpi(cls, value):
        if value not in (300, 600, 900, 1200, 1800):
            raise ValueError('Resolution must be 300, 600, 900, 1200 or 1800 dpi')
        return value

    @field_validator('bit_depth')
    @classmethod
    def validate_depth(cls, value):
        if value not in (8, 16):
            raise ValueError('Color depth must be 8 or 16 bits per channel')
        return value

    @field_validator('gains')
    @classmethod
    def validate_gains(cls, value):
        if any(not math.isfinite(g) or not .25 <= g <= 4 for g in value):
            raise ValueError('Exposure gains must be from 0.25 to 4')
        return value


class ScanInput(BaseModel):
    roll_id: str
    frame_count: int = Field(default=36, ge=1, le=72)
    media: str = 'uncut'
    speed: str = 'realtime'
    fault: str | None = None
    fault_frame: int = Field(default=17, ge=1, le=72)
    frames: list[int] | None = Field(default=None, min_length=1, max_length=72)
    settings: ScanSettings | None = None


class PrescanInput(BaseModel):
    frame_count: int = Field(default=36, ge=1, le=72)
    media: str = 'uncut'
    film_profile: str | None = None


class DevelopInput(BaseModel):
    roll_id: str
    recipe_id: str = 'demo-bw-v1'
    acknowledged: bool = False
    temperature: float = Field(default=20, ge=0, le=60)


class EditInput(BaseModel):
    exposure: float = Field(default=0, ge=-4, le=4)
    contrast: float = Field(default=1, ge=.1, le=3)
    rotation: int = Field(default=0, ge=-360, le=360)
    invert: bool = True
    film_base: list[float] | None = Field(default=None, min_length=3, max_length=3)
    film_profile: str | None = Field(default=None, max_length=16)  # '' clears the profile

    @field_validator('film_base')
    @classmethod
    def validate_film_base(cls, value):
        if value is None:
            return value
        if any(not math.isfinite(channel) or not 0 < channel <= 1 for channel in value):
            raise ValueError('Film base values must be finite, above zero and at most one')
        return value


def create_app(data_dir=None):
    store = Store(Path(data_dir or os.environ.get('FRAME_DATA_DIR', PROJECT / 'data')))
    clients = set()
    clock_guard = developing.ClockGuard()
    token = secrets.token_urlsafe(32)
    runtime = {'backend': None, 'task': None, 'scan_id': None, 'connected': False, 'cancel_requested': False}
    # Interrupted work is recoverable and never reported complete after a crash.
    for item in store.all('scans'):
        if item['status'] not in ('complete', 'error', 'cancelled', 'interrupted'):
            item.update(status='interrupted', error='Application stopped during acquisition; reconnect and recover')
            store.save('scans', item)

    @asynccontextmanager
    async def lifespan(app):
        await cyberscan['recover']()
        yield
        bridge = cyberscan['bridge']
        if bridge.busy:
            await bridge.cancel()
            await cyberscan['idle']()
        await bridge.release()
        task = runtime['task']
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        store.close()

    app = FastAPI(title='FRAME', lifespan=lifespan)
    app.state.store = store
    app.state.runtime = runtime

    def get(kind, entity_id):
        try:
            return store.get(kind, entity_id)
        except KeyError:
            raise HTTPException(404, 'Record not found')

    def scanner_info():
        backend = runtime['backend']
        return {'model': 'PrimeFilm PF1800 AFL simulator', 'backend': 'simulated',
                'connected': bool(backend and backend.connected), 'status': backend.status if backend else 'disconnected',
                'real_hardware_verified': False, 'capabilities': backend.capabilities() if backend else {},
                'original_precision': '8-bit synthetic fixture', 'dpi': 1800}

    def resolve_profile(profile_id):
        """Parsed profile from the library cache, else from the user's CyberView install (then cached)."""
        if not profile_id:
            return None
        try:
            cached = filmterms.load(store, profile_id)
            if cached.get('kind') in ('reference-tone', 'vendor-negative'):
                raise HTTPException(409, 'Reference appearance profiles require the CyberScan transmission workflow')
            return cached
        except ValueError:
            pass
        match = next((p for p in filmterms.discover() if p['id'] == profile_id), None)
        if not match:
            raise HTTPException(409, 'Film profile is not available; check FRAME_FILMTERM_DIRS or the CyberView install')
        filmterms.remember(store, match)
        return match

    def snapshot():
        scans = store.all('scans')
        sessions = []
        for session in store.all('development'):
            session = clock_guard.check(session)
            store.save('development', session)
            sessions.append(developing.view(session))
        return {'rolls': store.all('rolls'), 'frames': store.all('frames'),
                'development': sessions,
                'imaging_engine': pipeline.VERSION,
                'scan': next((s for s in reversed(scans) if s['status'] not in ('complete', 'cancelled')), scans[-1] if scans else None),
                'scanner': scanner_info(), 'recipes': [developing.DEMO_RECIPE], 'server_time': developing.now()}

    async def publish(event):
        event = dict(event, at=developing.now())
        # Slow companions never hold up acquisition. Reconnect obtains a snapshot.
        for queue in list(clients):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    cyberscan = cyberview_routes.register(app, store, publish)

    @app.middleware('http')
    async def access(request: Request, call_next):
        host = request.url.hostname
        if host not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            return JSONResponse({'detail': 'Local host required'}, 403)
        origin = request.headers.get('origin')
        expected = f'{request.url.scheme}://{request.headers.get("host")}'
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != expected:
            return JSONResponse({'detail': 'Same-origin requests required'}, 403)
        protected = request.url.path.startswith(('/api/', '/media/')) and request.url.path not in ('/api/auth/local', '/api/health')
        if protected and not secrets.compare_digest(request.cookies.get('frame_session', ''), token):
            return JSONResponse({'detail': 'Authentication required'}, 401)
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > 24_000_000:
            return JSONResponse({'detail': 'Request too large'}, 413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if protected:
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/auth/local')
    async def authenticate(request: Request):
        if request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient'):
            raise HTTPException(403, 'Local pairing only; LAN companions are not enabled')
        response = JSONResponse({'authenticated': True, 'scope': 'local-simulator'})
        response.set_cookie('frame_session', token, httponly=True, samesite='strict')
        return response

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'mode': 'simulator', 'version': '0.1.0'}

    @app.get('/api/state')
    async def state():
        return snapshot()

    @app.websocket('/api/events')
    async def events(socket: WebSocket):
        expected = f'http://{socket.headers.get("host")}'
        if (socket.url.hostname not in ('127.0.0.1', 'localhost', 'testserver') or
            not secrets.compare_digest(socket.cookies.get('frame_session', ''), token) or
            socket.headers.get('origin') not in (expected, expected.replace('http:', 'https:'))):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=32)
        clients.add(queue)
        try:
            await socket.send_json({'type': 'snapshot', 'data': snapshot()})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 15)
                except asyncio.TimeoutError:
                    event = {'type': 'heartbeat', 'server_time': developing.now()}
                await socket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.discard(queue)

    @app.post('/api/rolls')
    async def create_roll(body: RollInput):
        if body.format not in ('35mm', '120') or body.film_type not in ('color_negative', 'bw_negative', 'positive'):
            raise HTTPException(422, 'Unsupported film format or type')
        item = body.model_dump() | {'id': uuid.uuid4().hex, 'status': 'awaiting_development', 'created_at': developing.now()}
        store.save('rolls', item)
        await publish({'type': 'roll_created', 'roll_id': item['id']})
        return item

    @app.post('/api/rolls/{roll_id}/ready')
    async def ready(roll_id: str):
        roll = get('rolls', roll_id)
        if any(s['roll_id'] == roll_id and s['status'] not in ('completed', 'aborted') for s in store.all('development')):
            raise HTTPException(409, 'Finish or abort the development session first')
        roll['status'] = 'ready_to_scan'
        return store.save('rolls', roll)

    @app.post('/api/development')
    async def start_development(body: DevelopInput):
        roll = get('rolls', body.roll_id)
        if not body.acknowledged or body.recipe_id != developing.DEMO_RECIPE['id']:
            raise HTTPException(422, 'Verify recipe source and process settings; demo timings are for water only')
        if any(s['roll_id'] == roll['id'] and s['status'] not in ('completed', 'aborted') for s in store.all('development')):
            raise HTTPException(409, 'This roll already has an active development session')
        if runtime['task'] and not runtime['task'].done() and get('scans', runtime['scan_id'])['roll_id'] == roll['id']:
            raise HTTPException(409, 'Cannot develop a roll while it is being scanned')
        session = developing.create_session(roll['id'], developing.DEMO_RECIPE, body.temperature)
        clock_guard.check(session)
        roll['status'] = 'developing'
        store.save('rolls', roll)
        store.save('development', session)
        await publish({'type': 'development_started', 'session_id': session['id']})
        return developing.view(session)

    @app.post('/api/development/{session_id}/transition')
    async def transition(session_id: str):
        try:
            checked = clock_guard.check(get('development', session_id))
            store.save('development', checked)
            session = developing.transition(checked)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        store.save('development', session)
        if session['status'] == 'completed':
            roll = get('rolls', session['roll_id'])
            roll['status'] = 'ready_to_scan'
            store.save('rolls', roll)
        await publish({'type': 'development_transition', 'session_id': session_id})
        return developing.view(session)

    @app.post('/api/development/{session_id}/review-clock')
    async def review_clock(session_id: str, body: dict):
        session = get('development', session_id)
        if session['status'] != 'interrupted' or body.get('confirmed') is not True:
            raise HTTPException(409, 'Explicit clock and physical-step review required')
        elapsed = body.get('actual_elapsed_seconds')
        if isinstance(elapsed, bool) or not isinstance(elapsed, (float, int)) or not 0 <= elapsed <= 86_400:
            raise HTTPException(422, 'Record actual elapsed seconds after reviewing the physical process')
        stamp = developing.now()
        session.update(status='running', step_started_at=stamp - round(elapsed * 1000), checkpoint_at=stamp)
        session.pop('clock_warning', None)
        session['events'].append({'type': 'confirmed_clock_review', 'at': stamp, 'actual_elapsed_seconds': elapsed})
        clock_guard.observed.pop(session_id, None)
        store.save('development', session)
        return developing.view(session)

    @app.post('/api/development/{session_id}/abort')
    async def abort(session_id: str):
        session = get('development', session_id)
        if session['status'] in ('completed', 'aborted'):
            raise HTTPException(409, 'Session has already ended')
        session.update(status='aborted', completed_at=developing.now())
        session['events'].append({'type': 'aborted', 'at': developing.now()})
        store.save('development', session)
        roll = get('rolls', session['roll_id'])
        roll['status'] = 'awaiting_development'
        store.save('rolls', roll)
        return session

    @app.get('/api/dilution')
    async def dilution(total_ml: float = 500, parts_water: float = 9):
        try:
            return developing.dilution(total_ml, parts_water)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.post('/api/scanner/connect')
    async def connect():
        if runtime['task'] and not runtime['task'].done():
            raise HTTPException(409, 'Scanner is busy')
        from services.scanner_host.backend import SimulatedScannerBackend
        backend = SimulatedScannerBackend()
        await backend.connect()
        runtime.update(backend=backend, connected=True)
        await publish({'type': 'scanner_connected', 'simulated': True})
        return scanner_info()

    @app.get('/api/film-profiles')
    async def film_profiles(include_reference: bool = False, include_vendor: bool = False):
        from services.imaging import vendor_negative
        found = filmterms.discover()
        if include_vendor:
            found += vendor_negative.discover()
        cached = filmterms.reference_profiles(store) if include_reference else []
        found = list({p['id']: p for p in [*found, *cached]}.values())
        return {'sources': [str(root) for root in filmterms.roots()], 'count': len(found),
                'profiles': [filmterms.summary(p) for p in found],
                'note': 'Local CyberView terms and user reference profiles; FRAME does not distribute vendor files.'}

    @app.post('/api/rolls/{roll_id}/prescan')
    async def prescan_roll(roll_id: str, body: PrescanInput):
        roll = get('rolls', roll_id)
        if not runtime['backend'] or not runtime['backend'].connected:
            raise HTTPException(409, 'Connect the simulator first')
        if runtime['task'] and not runtime['task'].done():
            raise HTTPException(409, 'Scanner is busy')
        if roll['format'] != '35mm' or body.media not in ('uncut', 'strip'):
            raise HTTPException(422, 'Simulator prescans support 35mm uncut rolls and strips only')
        if roll['status'] != 'ready_to_scan' or frames_for(roll_id):
            raise HTTPException(409, 'Prescan a developed roll before it has scanned frames')
        profile = resolve_profile(body.film_profile)
        from services.scanner_host.backend import SimulatedScannerBackend

        async def run():
            backend = SimulatedScannerBackend(delay=.005)
            await backend.connect()
            await backend.initialize()
            await backend.calibrate()
            await backend.load(body.frame_count, body.media)
            positions = await backend.prescan()
            revision = uuid.uuid4().hex[:12]
            edit = dict(pipeline.DEFAULT_EDIT, invert=roll['film_type'] != 'positive')
            if profile:
                edit['film_profile'] = profile['id']
            frames = []
            for position in positions:
                pixels = await backend.prescan_preview(position['index'])
                image = pipeline.render(pipeline.encode(Image.fromarray(pixels)), edit, roll['film_type'], profile)
                path = f"{roll_id}/prescan/{revision}-{position['index']:02d}.jpg"
                atomic_write(store.path(path), pipeline.encode(image, 'JPEG'))
                frames.append(dict(position, preview_path=path))
            await backend.disconnect()
            return {'at': developing.now(), 'media': body.media, 'frame_count': body.frame_count, 'frames': frames,
                    'film_profile': profile['id'] if profile else None, 'synthetic': True,
                    'note': 'Low-resolution synthetic simulator prescan; not device imagery'}

        runtime['task'] = asyncio.create_task(run())
        try:
            roll['prescan'] = await runtime['task']
        except Exception as exc:
            raise HTTPException(422, f'Prescan failed: {exc}')
        store.save('rolls', roll)
        await publish({'type': 'prescan_complete', 'roll_id': roll_id})
        return roll

    def frames_for(roll_id):
        return sorted([f for f in store.all('frames') if f['roll_id'] == roll_id], key=lambda f: f['index'])

    async def scan_worker(session_id, recovery=False):
        from services.scanner_host.backend import SimulatedScannerBackend
        session = get('scans', session_id)
        roll = get('rolls', session['roll_id'])
        backend = SimulatedScannerBackend(delay=.015 if session['speed'] == 'fast' else .3,
                                          fault=None if recovery else session['fault'], fault_frame=session['fault_frame'])
        runtime['backend'] = backend
        async def on_event(event):
            await publish(dict(event, type='scanner_event', scan_id=session_id))
            log = store.path(f"{roll['id']}/logs/scanner_events.jsonl")
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf8') as stream:
                stream.write(json.dumps(event, default=str) + '\n')
        backend.subscribe(on_event)
        settings = session.get('settings') or {}
        selected = session.get('frames') or list(range(1, session['frame_count'] + 1))
        try:
            profile = resolve_profile(settings.get('film_profile'))
            backend.configure(settings.get('window'), settings.get('gains'))
            await backend.connect()
            runtime['connected'] = True
            for status, operation in [('initializing', backend.initialize), ('calibrating', backend.calibrate),
                                      ('loading', lambda: backend.load(session['frame_count'], session['media'])), ('prescanning', backend.prescan)]:
                session.update(status=status, updated_at=developing.now())
                store.save('scans', session)
                result = await operation()
                if status == 'prescanning':
                    session['positions'] = result
            completed = {f['index'] for f in frames_for(roll['id'])}
            session['completed_frames'] = len(completed)
            store.save('scans', session)
            for index in selected:
                if index in completed:
                    continue
                session.update(status='scanning', current_frame=index, updated_at=developing.now())
                store.save('scans', session)
                await publish({'type': 'scan_progress', 'scan': session})
                await backend.position_frame(index)
                pixels = await backend.acquire(index)
                session['status'] = 'saving'
                store.save('scans', session)
                scan_record = dict(settings, requested=True, delivered=f'{pixels.shape[1]}x{pixels.shape[0]} uint8 synthetic fixture') if settings else None
                frame = pipeline.save_frame(store, roll, index, pixels, uuid.uuid4().hex, profile=profile, scan_settings=scan_record)
                store.save('frames', frame)
                session['completed_frames'] = len(frames_for(roll['id']))
                session['updated_at'] = developing.now()
                elapsed = (session['updated_at'] - session['attempt_started_at']) / 1000
                session['eta_seconds'] = elapsed / max(1, session['completed_frames'] - session['initial_completed']) * (len(selected) - session['completed_frames'])
                store.save('scans', session)
                await publish({'type': 'frame_saved', 'frame': frame, 'scan': session})
            sheet = pipeline.contact_sheet(store, roll['id'], frames_for(roll['id']), uuid.uuid4().hex)
            roll.update(status='scanned', contact_sheet_path=sheet)
            store.save('rolls', roll)
            final_indexes = {f['index'] for f in frames_for(roll['id'])}
            if final_indexes != set(selected):
                raise ValueError('Saved frame indexes do not match the expected roll')
            session.update(status='complete', completed_frames=len(final_indexes), error=None, completed_at=developing.now(), eta_seconds=0)
            store.save('scans', session)
            await publish({'type': 'scan_complete', 'scan': session})
        except asyncio.CancelledError:
            session.update(status='interrupted', error='Application stopped; recover to continue')
            store.save('scans', session)
            raise
        except Exception as exc:
            cancelled = runtime['cancel_requested']
            session.update(status='cancelled' if cancelled else 'error', error=str(exc), updated_at=developing.now())
            store.save('scans', session)
            roll['status'] = 'ready_to_scan'
            store.save('rolls', roll)
            await publish({'type': 'scan_error', 'scan': session})

    @app.post('/api/scans')
    async def start_scan(body: ScanInput):
        roll = get('rolls', body.roll_id)
        if not runtime['backend'] or not runtime['backend'].connected:
            raise HTTPException(409, 'Connect the simulator first')
        if runtime['task'] and not runtime['task'].done():
            raise HTTPException(409, 'Only one scanner command session may run at once')
        if roll['format'] != '35mm' or body.media not in ('uncut', 'strip'):
            raise HTTPException(422, 'Simulator scanning supports 35mm uncut rolls and strips only')
        if body.speed not in ('fast', 'realtime') or body.fault not in (None, 'jam', 'calibration', 'disconnect', 'timeout', 'alignment', 'write'):
            raise HTTPException(422, 'Invalid simulator settings')
        if roll['status'] != 'ready_to_scan':
            raise HTTPException(409, 'Complete development or mark an already-developed roll ready to scan')
        if any(s['roll_id'] == roll['id'] for s in store.all('scans')):
            raise HTTPException(409, 'This roll already has a scan session; recover that session')
        if frames_for(roll['id']):
            raise HTTPException(409, 'Roll already has frames; recover its existing session instead')
        if body.frames is not None and (len(set(body.frames)) != len(body.frames) or
                                        any(not 1 <= i <= body.frame_count for i in body.frames)):
            raise HTTPException(422, 'Selected frames must be unique and within the loaded film')
        if body.settings:
            resolve_profile(body.settings.film_profile)
            try:
                from services.scanner_host.backend import SimulatedScannerBackend
                SimulatedScannerBackend().configure(body.settings.window and body.settings.window.model_dump(), body.settings.gains)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        stamp = developing.now()
        if body.frames:
            body.frames = sorted(body.frames)
        session = body.model_dump() | {'id': uuid.uuid4().hex, 'status': 'loading', 'current_frame': 0,
                 'completed_frames': 0, 'initial_completed': 0, 'error': None, 'started_at': stamp,
                 'attempt_started_at': stamp, 'updated_at': stamp, 'events': [], 'simulated': True}
        store.save('scans', session)
        roll['status'] = 'scanning'
        store.save('rolls', roll)
        runtime['scan_id'] = session['id']
        runtime['cancel_requested'] = False
        runtime['task'] = asyncio.create_task(scan_worker(session['id']))
        return session

    @app.post('/api/scans/{session_id}/recover')
    async def recover(session_id: str):
        session = get('scans', session_id)
        if runtime['task'] and not runtime['task'].done():
            raise HTTPException(409, 'Scanner is busy')
        if session['status'] not in ('error', 'cancelled', 'interrupted'):
            raise HTTPException(409, 'Only interrupted or failed scans may be recovered')
        roll = get('rolls', session['roll_id'])
        roll_scans = [s for s in store.all('scans') if s['roll_id'] == roll['id']]
        if roll_scans[-1]['id'] != session_id or roll['status'] == 'archived':
            raise HTTPException(409, 'This scan session has been superseded or archived')
        if any(s['roll_id'] == roll['id'] and s['status'] not in ('completed', 'aborted') for s in store.all('development')):
            raise HTTPException(409, 'Finish or abort development before scanner recovery')
        for frame in frames_for(session['roll_id']):
            if not pipeline.verify_frame(store, frame):
                raise HTTPException(409, 'Existing original failed its integrity check')
        count = len(frames_for(session['roll_id']))
        session.update(status='loading', error=None, cancel_requested=False, attempt_started_at=developing.now(), initial_completed=count, completed_frames=count)
        session['events'].append({'type': 'controlled_recovery', 'at': developing.now(), 'after_frame': session['completed_frames']})
        store.save('scans', session)
        roll['status'] = 'scanning'
        store.save('rolls', roll)
        runtime['scan_id'] = session_id
        runtime['cancel_requested'] = False
        runtime['task'] = asyncio.create_task(scan_worker(session_id, recovery=True))
        return session

    @app.post('/api/scans/{session_id}/cancel')
    async def cancel(session_id: str):
        session = get('scans', session_id)
        if runtime['scan_id'] != session_id or not runtime['task'] or runtime['task'].done():
            raise HTTPException(409, 'No active scan to cancel')
        session['cancel_requested'] = True
        runtime['cancel_requested'] = True
        store.save('scans', session)
        await runtime['backend'].cancel()
        return get('scans', session_id)

    @app.post('/api/rolls/{roll_id}/import')
    async def import_image(roll_id: str, body: dict):
        roll = get('rolls', roll_id)
        if any(s['roll_id'] == roll_id and s['status'] != 'complete' for s in store.all('scans')):
            raise HTTPException(409, 'Recover unfinished scanning before importing images')
        if runtime['task'] and not runtime['task'].done() and runtime['scan_id'] and get('scans', runtime['scan_id'])['roll_id'] == roll_id:
            raise HTTPException(409, 'Wait for scanning before importing')
        try:
            payload = body.get('data_base64', '').split(',')[-1]
            if len(payload) > 23_000_000:
                raise ValueError('Maximum image size is 16 MB')
            data = base64.b64decode(payload, validate=True)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > 32_000_000 or image.format not in ('JPEG', 'PNG', 'TIFF'):
                    raise ValueError('Use JPEG, PNG or TIFF up to 32 megapixels')
                image.verify()
        except Exception as exc:
            raise HTTPException(422, f'Invalid image: {exc}')
        try:
            frame = pipeline.save_frame(store, roll, len(frames_for(roll_id)) + 1, None, uuid.uuid4().hex, synthetic=False, original_bytes=data)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, f'Cannot preserve processing precision for this image: {exc}')
        store.save('frames', frame)
        roll.update(status='scanned', contact_sheet_path=pipeline.contact_sheet(store, roll_id, frames_for(roll_id), uuid.uuid4().hex))
        store.save('rolls', roll)
        await publish({'type': 'frame_imported', 'frame': frame})
        return frame

    @app.post('/api/frames/{frame_id}/edit')
    async def edit_frame(frame_id: str, body: EditInput):
        frame = get('frames', frame_id)
        if not pipeline.verify_frame(store, frame):
            raise HTTPException(409, 'Original integrity check failed')
        roll = get('rolls', frame['roll_id'])
        revision = uuid.uuid4().hex
        edit = body.model_dump(exclude_none=True)
        edit.setdefault('film_base', frame['edit'].get('film_base', [1, 1, 1]))
        edit.setdefault('film_profile', frame['edit'].get('film_profile'))
        if not edit['film_profile']:
            edit.pop('film_profile')
        try:
            image = pipeline.render(store.path(frame['original_path']).read_bytes(), edit, roll['film_type'],
                                    resolve_profile(edit.get('film_profile')))
        except ValueError as exc:
            raise HTTPException(422, f'Image processing failed: {exc}')
        image.thumbnail((1280, 1280))
        path = f"{roll['id']}/previews/{frame_id}-{revision}.jpg"
        atomic_write(store.path(path), pipeline.encode(image, 'JPEG'))
        record = {'edit': edit, 'engine': pipeline.VERSION, 'at': developing.now(), 'original_sha256': frame['sha256']}
        atomic_write(store.path(f"{roll['id']}/edits/{frame_id}-{revision}.json"), json.dumps(record).encode())
        frame.update(edit=edit, preview_path=path, engine=pipeline.VERSION)
        store.save('frames', frame)
        roll['contact_sheet_path'] = pipeline.contact_sheet(store, roll['id'], frames_for(roll['id']), revision)
        store.save('rolls', roll)
        return frame

    @app.post('/api/frames/{frame_id}/favorite')
    async def favorite(frame_id: str):
        frame = get('frames', frame_id)
        frame['favorite'] = not frame['favorite']
        return store.save('frames', frame)

    @app.get('/api/frames/{frame_id}/export')
    async def export(frame_id: str, format: str = 'jpeg'):
        frame = get('frames', frame_id)
        if not pipeline.verify_frame(store, frame):
            raise HTTPException(409, 'Original integrity check failed')
        if format == 'original':
            return FileResponse(store.path(frame['original_path']), filename=f'frame-{frame["index"]}-original' + Path(frame['original_path']).suffix)
        if format not in ('jpeg', 'tiff'):
            raise HTTPException(422, 'Choose jpeg, tiff or original')
        roll = get('rolls', frame['roll_id'])
        original = store.path(frame['original_path']).read_bytes()
        profile = resolve_profile(frame['edit'].get('film_profile'))
        try:
            if format == 'tiff':
                data = pipeline.render_tiff16(original, frame['edit'], roll['film_type'], frame.get('effective_bits'), profile)
            else:
                data = pipeline.encode(pipeline.render(original, frame['edit'], roll['film_type'], profile), 'JPEG')
        except (ValueError, OSError) as exc:
            raise HTTPException(422, f'Image processing failed: {exc}')
        signature = hashlib.sha256(json.dumps(frame['edit'], sort_keys=True).encode() + pipeline.VERSION.encode()).hexdigest()[:16]
        path = f"{roll['id']}/exports/{frame_id}-{signature}.{format}"
        try:
            if not store.path(path).exists():
                atomic_write(store.path(path), data)
            elif store.path(path).read_bytes() != data:
                raise HTTPException(409, 'Existing export does not match reproducible rendering')
        except OSError:
            raise HTTPException(507, 'Export could not be published; the original and previous exports are unchanged')
        export_record = {'id': f'{frame_id}-{signature}-{format}', 'frame_id': frame_id, 'format': format,
                         'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'engine': pipeline.VERSION,
                         'color_space': 'sRGB', 'output_sample_bits': 16 if format == 'tiff' else 8,
                         'acquired_effective_bits': frame.get('effective_bits'),
                         'source_sample_bits': pipeline.source_info(original)['sample_bits']}
        store.save('exports', export_record)
        return FileResponse(store.path(path), media_type=f'image/{format}', filename=f'frame-{frame["index"]}.{format}')

    @app.get('/api/rolls/{roll_id}/contact-sheet')
    async def sheet(roll_id: str):
        roll = get('rolls', roll_id)
        if not roll.get('contact_sheet_path'):
            raise HTTPException(404, 'No contact sheet yet')
        return FileResponse(store.path(roll['contact_sheet_path']), media_type='image/jpeg')

    @app.post('/api/rolls/{roll_id}/archive')
    async def archive(roll_id: str):
        roll = get('rolls', roll_id)
        frames = frames_for(roll_id)
        scans = [s for s in store.all('scans') if s['roll_id'] == roll_id]
        if scans and scans[-1]['status'] != 'complete':
            raise HTTPException(409, 'Complete or recover scanning before archiving')
        if not frames or not all(pipeline.verify_frame(store, frame) for frame in frames):
            raise HTTPException(409, 'Every original must exist and pass integrity checks')
        sheet_path = roll.get('contact_sheet_path')
        if not sheet_path or not store.path(sheet_path).is_file():
            raise HTTPException(409, 'Contact sheet is required')
        try:
            with Image.open(store.path(sheet_path)) as sheet_image:
                sheet_image.verify()
        except (OSError, ValueError):
            raise HTTPException(409, 'Contact sheet is corrupt; regenerate it before archiving')
        roll.update(status='archived', archived_at=developing.now(), integrity_verified_at=developing.now())
        store.save('rolls', roll)
        store.backup()
        return roll

    @app.get('/media/{relative:path}')
    async def media(relative: str):
        try:
            path = store.path(relative)
        except ValueError:
            raise HTTPException(403, 'Invalid path')
        allowed = {f['preview_path'] for f in store.all('frames')} | {r.get('contact_sheet_path') for r in store.all('rolls')}
        allowed |= {item['preview_path'] for r in store.all('rolls') for item in (r.get('prescan') or {}).get('frames', [])}
        if relative not in allowed or not path.is_file():
            raise HTTPException(404, 'Preview not found')
        return FileResponse(path)

    dist = PROJECT / 'apps' / 'web' / 'dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='web')
    else:
        @app.get('/')
        async def building():
            return Response('FRAME client is building. Run npm --prefix apps/web run build, then restart.', media_type='text/plain')
    return app


app = create_app()
