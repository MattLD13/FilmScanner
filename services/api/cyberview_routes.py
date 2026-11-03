"""FRAME scanner API: direct AFL capture and the retained research TWAIN path.

Each delivered TIFF is kept unchanged as the original, hashed and recorded. Viewing
adjustments are a recipe stored next to it and applied only to previews and exports.
"""

from __future__ import annotations

import asyncio
import hashlib
from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
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
from services.imaging import acquisition_plan, autocolor, frame_align, film_type_detection, pipeline, filmterms, negative, vendor_negative
from services.imaging import scan_filters, sensor_precision, statistics_guard, vendor_autogamma
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
NUDGE_CHUNK = 20      # film nudge steps per command (see run_stitched)
MAX_BORDER_SEARCH_PROBES = 5  # bounded extra previews on the side of a missing edge
MAX_ARCHIVE_RECOVERY_PROBES = MAX_BORDER_SEARCH_PROBES  # bounded extra 1800 dpi passes to prove full-frame rebates
AUTO_FILM_TYPE_MIN_CONFIDENCE = .80
LIVE_MAX_ROWS = 300  # 1708 lines / 8, with room to spare


class ScanRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=40)
    until_end: bool = False   # "All frames": scan, advance, repeat until the film runs out
    roll: str = Field(default='', max_length=120)
    settings: ScanOptions | None = None
    purpose: Literal['scan', 'prescan', 'frame_scan', 'roll_preview'] = 'scan'
    auto_detect_film_type: bool = False


class FavoriteScanRequest(BaseModel):
    preview_session_id: str = Field(min_length=32, max_length=32, pattern='^[0-9a-f]{32}$')
    roll: str = Field(default='', max_length=120)
    preview_ids: list[str] = Field(min_length=1, max_length=40)
    end_action: Literal['return_to_frame_1', 'hold_at_end', 'eject_forward'] = 'return_to_frame_1'
    repeat_samples: Literal[1,2,4] = 1


class RollPreviewRequest(BaseModel):
    scope: Literal['one', 'all'] = 'all'
    dpi: Literal[300, 600] = 600
    roll: str = Field(default='', max_length=120)
    expected_frames: int | None = Field(default=None,ge=1,le=40)


class RefusedAdvanceRequest(BaseModel):
    session_id: str = Field(min_length=32,max_length=32,pattern='^[0-9a-f]{32}$')
    action: Literal['confirm_end','retry_advance','abort']


class FilmRequest(BaseModel):
    action: Literal['next', 'previous', 'eject_forward', 'eject_backward', 'goto']
    frame: int | None = Field(default=None, ge=1, le=40)
    acknowledged: bool = False


class ControlRequest(BaseModel):
    action: Literal['autofocus', 'focus', 'calibrate', 'realign']
    value: int | None = Field(default=None, ge=0, le=200)
    acknowledged: bool = False


class BackendRequest(BaseModel):
    backend: Literal['cyberview-twain', 'afl-native-experimental']
    acknowledged: bool = False


class FilmTypeRequest(BaseModel):
    film_type: Literal['color_negative', 'bw_negative', 'positive']


class AutoFilmTypeRequest(BaseModel):
    roll: str = Field(default='', max_length=120)


class DeleteCyberScanRollRequest(BaseModel):
    roll: str = Field(default='', max_length=120)


class FrameOriginRequest(BaseModel):
    frame: Literal[1] = 1


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
    # Missing on old recipes: retain their original conversion exactly.
    negative_response: float = Field(default=negative.LEGACY_RESPONSE, ge=.1, le=3, allow_inf_nan=False)
    vendor_input_balance: bool = False
    color_restoration: float = Field(default=0,ge=0,le=1,allow_inf_nan=False)
    grain_reduction: float = Field(default=0,ge=0,le=1,allow_inf_nan=False)
    sharpening: float = Field(default=0,ge=0,le=1,allow_inf_nan=False)
    vendor_auto_gamma_tables: list[list[int]] | None = None

    @field_validator('vendor_auto_gamma_tables')
    @classmethod
    def valid_vendor_tables(cls,value):
        if value is not None:
            vendor_autogamma.validate_tables(value)
        return value
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
    preview_capture_id: str | None = Field(default=None, min_length=32, max_length=32, pattern='^[0-9a-f]{32}$')
    auto_detect_film_type: bool = False
    acknowledged: bool = False
    end_action: Literal['return_to_frame_1', 'hold_at_end', 'eject_forward'] = 'return_to_frame_1'
    repeat_samples: Literal[1,2,4] = 1
    expected_frames: int | None = Field(default=None,ge=1,le=40)


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
    if adjust.film_profile and (not profile or profile['id'] != adjust.film_profile):
        raise ValueError('The chosen film rendering profile is unavailable')
    vendor = profile and profile.get('kind') == 'vendor-negative'
    if vendor:
        if not adjust.invert:
            raise ValueError('AFL negative conversion requires negative transmission')
        source=vendor_negative.exposure_normalized_input(samples,adjust.film_base) if adjust.vendor_input_balance else samples
        samples = vendor_negative.apply(source, profile)
    elif adjust.invert:
        # Nominal transmission response, with the legacy exponent retained on old
        # recipes. Suggested/manual base is a display reference, not a scanner profile.
        samples = negative.invert(samples, adjust.film_base, adjust.negative_response)
    if adjust.film_profile and not vendor:
        if not profile or profile['id']!=adjust.film_profile:
            raise ValueError('The chosen film rendering profile is unavailable')
        samples=filmterms.apply(samples,profile)
    if adjust.vendor_auto_gamma_tables is not None:
        samples=vendor_autogamma.apply(samples,adjust.vendor_auto_gamma_tables)
    if adjust.color_restoration or adjust.grain_reduction or adjust.sharpening:
        samples=scan_filters.process(samples,{'color_restoration':adjust.color_restoration,
            'grain_reduction':adjust.grain_reduction,'sharpening':adjust.sharpening})
    if adjust.auto_color:
        samples = autocolor.apply(samples, adjust.auto_color)
    return samples


def auto_color_for(samples: np.ndarray, covered: np.ndarray | None = None, *, dpi: float | None=None):
    """Compute from a bounded preview, excluding uncovered stitch margins."""
    if dpi is not None:
        covered,_=statistics_guard.mask(samples.shape,dpi,covered)
    if covered is None:
        return autocolor.for_positive(samples)
    step = max(1, int(np.ceil(samples.shape[1] / 900)))
    pixels = samples[::step, ::step][covered[::step, ::step]]
    return autocolor.for_positive(pixels[:, None, :]) if pixels.size else None


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
    preview_lock = asyncio.Semaphore(1)
    vendor_tone_lock = asyncio.Lock()
    source = SOURCE if bridge.kind == 'cyberview-twain' else NATIVE_SOURCE
    runtime = {'session': None, 'task': None, 'present': (0.0, None), 'live': None, 'position_generation': 0,
               'frame_origin_raw':1}
    def bind_position_safety():
        if not isinstance(bridge,NativeAflBridge):return
        saved=next((p for p in store.all('cv_preferences') if p['id']=='transport-safety'),{})
        bridge.transport_position_uncertain=bool(saved.get('transport_position_uncertain',False))
        def changed(uncertain,basis):
            store.save('cv_preferences',{'id':'transport-safety',
                'transport_position_uncertain':uncertain,'basis':basis,'at':int(time.time()*1000)})
        bridge.position_safety_changed=changed
    bind_position_safety()

    def require_known_position():
        if isinstance(bridge,NativeAflBridge):
            try:bridge.require_known_position()
            except ScannerError as exc:raise HTTPException(409,str(exc)) from exc

    def optical_position_confirmed(basis):
        if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(False,basis)
    saved_workspace = next((p for p in store.all('cv_preferences') if p['id'] == 'workspace'), {})
    scan_options = ScanOptions(**saved_workspace.get('settings', {})).model_dump()
    scan_options['exposure'] = workspace.clamp_exposure(scan_options['exposure'])
    saved_film = next((p for p in store.all('cv_preferences') if p['id'] == 'film-type'), {})
    film_type = saved_film.get('film_type', 'positive' if scan_options['film'] == 'positive' else 'color_negative')
    if film_type not in ('color_negative', 'bw_negative', 'positive'):
        film_type = 'positive' if scan_options['film'] == 'positive' else 'color_negative'
    # Acquisition polarity is authoritative when loading older or inconsistent preferences.
    if scan_options['film'] == 'positive':
        film_type = 'positive'
    elif film_type == 'positive':
        film_type = 'color_negative'
    saved_align = next((p for p in store.all('cv_preferences') if p['id'] == 'align'), {})
    align_settings = AlignSettings(**{k: v for k, v in saved_align.items() if k in AlignSettings.model_fields}).model_dump()

    for item in store.all('cv_sessions'):
        if item['state'] not in ('complete', 'cancelled', 'error'):
            item.update(state='error', error='FRAME stopped during this scan; turn the scanner off and on before retrying')
            store.save('cv_sessions', item)

    def captures():
        return sorted(store.all('cv_captures'), key=lambda c: c['created_at'])

    def selected_film_type(settings):
        return 'positive' if settings.get('film') == 'positive' else 'bw_negative' if film_type == 'bw_negative' else 'color_negative'

    def resolve_profile(profile_id):
        if not profile_id:return None
        try:
            return filmterms.load(store,profile_id)
        except ValueError:
            profile=next((p for p in [*filmterms.discover(), *vendor_negative.discover()] if p['id']==profile_id),None)
            if profile is None:raise HTTPException(409,'The film rendering profile is no longer installed or cached')
            filmterms.remember(store,profile)
            return profile

    def capture(capture_id):
        try:
            return store.get('cv_captures', capture_id)
        except KeyError:
            raise HTTPException(404, 'Capture not found')

    def coverage(record):
        if not record.get('coverage_path'):
            return None
        with Image.open(store.path(record['coverage_path'])) as image:
            return np.asarray(image) > 0

    def compatible_profile(record, adjust, profile):
        if profile and profile.get('kind') == 'vendor-negative':
            if (not adjust.invert or record.get('image_kind') != 'vendor-calibrated-transmission' or
                    (record.get('requested_settings') or {}).get('film', 'negative') != 'negative'):
                raise HTTPException(422, 'AFL conversion needs an original direct negative transmission scan')

    @lru_cache(maxsize=48)
    def rendered_preview(original_path, digest, recipe, kind, original_stamp):
        """Bound cached JPEG bytes; full-resolution processing is serialized below."""
        data = store.path(original_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise HTTPException(409, 'The original no longer matches its recorded checksum')
        adjust = Adjustments(**json.loads(recipe))
        samples = apply(to_float(read_original(BytesIO(data))), adjust, resolve_profile(adjust.film_profile))
        return jpeg(samples, THUMB_EDGE if kind == 'thumb' else PREVIEW_EDGE)

    def present():
        checked, value = runtime['present']
        if time.monotonic() - checked > 5:
            value = cyberview.scanner_present()
            runtime['present'] = (time.monotonic(), value)
        return value

    def public_session(session):
        if (session and session.get('roll_preview_parent_id') and
                session.get('state') in ('complete','error','cancelled') and
                runtime.get('task') and not runtime['task'].done()):
            # A completed internal search is still part of an active parent job.
            return session | {'state':'saving','child_state':session['state']}
        return session

    def status():
        return {'bridge_built': bridge.built(), 'busy': bridge.busy, 'session_open': bridge.open,
                'auto_reset': bridge.kind == 'cyberview-twain' and cyberview.reset_available(),
                'vendor_open': False if bridge.open else cyberview.vendor_running(),
                'scanner_present': present(), 'settings': bridge.acquisition_settings(),
                'session': public_session(runtime['session']), 'source': source, 'backend': bridge.kind,
                'supports_next': bridge.supports_next, 'max_count': bridge.max_count,
                'image_kind': bridge.image_kind,
                'transport_position_uncertain':getattr(bridge,'transport_position_uncertain',False),
                'experimental_enabled': bridge.enabled,
                'native': {'dpi': 1800, 'bits': 16, 'note': (
                    'CyberView delivers the frame inverted with its selected film term' if bridge.kind == 'cyberview-twain'
                    else 'Vendor-calibrated transmission, identity LUT; effective sensor precision is unmeasured')}}

    async def update_session(**changes):
        session = runtime['session']
        session.update(changes)
        store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': public_session(session)})

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

    def film_base_exposure(record, samples, covered=None):
        """CyberView's auto exposure on the PF1800 AFL, done from the scan itself: the bare
        film base (brightest 0.5 % of luminance) is brought to 0.85 in every channel on the
        next scans. Verified linear on 2026-10-31 (base 0.84/0.855/0.856 at 120/168/269)."""
        nonlocal scan_options
        used = (record.get('requested_settings') or {}).get('exposure')
        if bridge.kind != 'afl-native-experimental' or not used or (record.get('requested_settings') or {}).get('film') != 'negative':
            return
        suggested=negative.suggest_base(samples,covered,dpi=record['dpi'])
        if suggested is None:
            return
        base=np.asarray(suggested)
        exposure = workspace.clamp_exposure([round(e * .85 / b) for e, b in zip(used, base)])
        _,guard=statistics_guard.mask(samples.shape,record['dpi'],covered)
        record['film_base'] = {'measured': [round(float(b), 4) for b in base], 'exposure_used': used, 'next_exposure': exposure,
                               'statistics_guard':guard}
        if exposure != scan_options['exposure'] and workspace.validated_options(scan_options | {'exposure': exposure}):
            scan_options = ScanOptions(**(scan_options | {'exposure': exposure})).model_dump()
            store.save('cv_preferences', {'id': 'workspace', 'settings': scan_options})

    def general_negative_display(record, samples, adjust, covered=None):
        """Apply a general editable display recipe from the acquired picture only."""
        positive = negative.invert(samples, adjust.film_base, adjust.negative_response)
        valid,_=statistics_guard.mask(samples.shape,record['dpi'],covered)
        # Estimate display tones from picture content, excluding rebate and ragged edges.
        edges = frame_align.align_35mm(samples, record['dpi'],
                    record.get('image_kind')=='vendor-calibrated-transmission',covered=covered)
        height,width=samples.shape[:2]
        margin=max(1,int(height*.02))
        valid[:margin]=False;valid[-margin:]=False
        x=edges['x']
        left=int(x.get('start',width*.02));right=int(x.get('end',width*.98))
        valid[:,:left]=False;valid[:,right:]=False
        suggestion=negative.suggest_display(positive,valid)
        if suggestion:
            record['display_suggestion']=suggestion['evidence']
            adjust=Adjustments(**(adjust.model_dump() | {k:v for k,v in suggestion.items() if k!='evidence'} |
                                  {'auto_color':None}))
        return adjust

    def initial_adjustments(record, samples, covered=None):
        """Same software conversion for individual and stitched direct negatives."""
        adjust = Adjustments(**record['adjustments'])
        base = negative.suggest_base(samples, covered, dpi=record['dpi']) if adjust.invert else None
        if base is not None:
            adjust = adjust.model_copy(update={'film_base': base, 'negative_response': negative.SUGGESTED_RESPONSE})
            record['negative_balance'] = {'version': negative.VERSION, 'method': 'brightest-0.5-percent',
                                          'suggested_base': base, 'response': negative.SUGGESTED_RESPONSE,
                                          'statistics_guard':statistics_guard.mask(samples.shape,record['dpi'],covered)[1]}
        if base is not None and not adjust.film_profile:
            profile=vendor_negative.default_profile(store) if record.get('film_type','color_negative')=='color_negative' else None
            if profile:
                adjust=Adjustments(**(adjust.model_dump() | {'film_profile':profile['id'],'vendor_input_balance':True,
                    'black_point':0,'white_point':1,'gamma':1,'rgb_balance':[1,1,1],
                    'curve':[0,.25,.5,.75,1],'auto_color':None}))
                record['display_suggestion']={'method':'recovered_vendor_generic_negative','reference_used':False,
                    'profile_id':profile['id'],'input_base_target':.85}
            else:
                adjust=general_negative_display(record,samples,adjust,covered)
        else:
            positive = before_levels(samples, adjust)
            adjust.auto_color = auto_color_for(positive, covered, dpi=record['dpi'])
        record['adjustments'] = adjust.model_dump()

    def tone_picture_crop(record,adjust,width):
        crop=adjust.crop.model_dump()
        edges=(record.get('alignment') or {}).get('edges_x') or {}
        if edges.get('found')=='both' and not (record.get('alignment') or {}).get('crop_applied'):
            crop.update(left=max(crop['left'],edges['start']/width),
                        right=min(crop['right'],edges['end']/width))
        return crop

    def initial_tone(record, samples, covered=None, preview=None, force=False):
        """Tone defaults off; carry an explicitly chosen preview LUT to its scan."""
        adjust=Adjustments(**record['adjustments'])
        if (record.get('image_kind')!='vendor-calibrated-transmission' or
                record.get('film_type','color_negative')!='color_negative' or
                not adjust.invert or not adjust.film_profile or
                (not force and record.get('purpose') not in ('scan','stitched','roll_preview'))):
            return
        if (record.get('vendor_auto_tone') or {}).get('user_disabled'):
            return
        if adjust.vendor_auto_gamma_tables is not None and preview is None:
            return
        profile=resolve_profile(adjust.film_profile)
        if not profile or profile.get('kind')!='vendor-negative':
            return
        source_meta=(preview or {}).get('vendor_auto_tone') or {}
        source_adjust=(preview or {}).get('adjustments') or {}
        if source_meta.get('user_disabled'):
            record['adjustments']=Adjustments(**(record['adjustments'] | {
                'vendor_auto_gamma_tables':None,'auto_color':None})).model_dump()
            record['vendor_auto_tone']={'enabled':False,'user_disabled':True,
                'source_capture_id':preview['id'],'source':'preview'}
            return
        cached=source_adjust.get('vendor_auto_gamma_tables')
        if (cached is None or not source_meta.get('enabled') or
                source_adjust.get('film_profile')!=adjust.film_profile):
            record['vendor_auto_tone']={'enabled':False,'automatic':False,'default_off':True}
            return
        try:
            tables=vendor_autogamma.validate_tables(cached,require_usable=True).astype(int).tolist()
            if vendor_autogamma.diagnostics(tables)['table_sha256']!=(source_meta.get('diagnostics') or {}).get('table_sha256'):
                raise ValueError('Preview tone table checksum changed')
        except ValueError as exc:
            record['vendor_auto_tone']={'enabled':False,'automatic':False,'reason':str(exc)}
            return
        record['adjustments']=Adjustments(**(record['adjustments'] | {
            'vendor_auto_gamma_tables':tables,'auto_color':None})).model_dump()
        record['vendor_auto_tone']=json.loads(json.dumps(source_meta)) | {'source':'preview',
            'source_capture_id':preview['id'],'source_sha256':preview['sha256'],
            'reused_without_highres_recalculation':True}

    def finalize(session, event, index):
        """Moves one delivered TIFF into place, hashes it and writes its previews."""
        nonlocal film_type, scan_options
        incoming = Path(event['path']).resolve()
        if not incoming.is_relative_to(store.root):
            raise ScannerError('The driver wrote outside the library')
        capture_id = uuid.uuid4().hex
        base = f"cyberview/{session['id']}/{index:02d}-{capture_id[:8]}"
        original = store.path(base + '.tif')
        os.replace(incoming, original)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        samples = to_float(read_original(original))
        detection = None
        if session.get('auto_detect_film_type'):
            detection = film_type_detection.detect(samples, round(event['dpi']), transmission=bridge.image_kind == 'vendor-calibrated-transmission',
                exposure=(session.get('requested_settings') or {}).get('exposure'))
            detected_type = detection.get('film_type')
            detection['applied'] = bool(detection.get('confidence', 0) >= AUTO_FILM_TYPE_MIN_CONFIDENCE)
            detection['previous_type'] = film_type
            if detection['applied'] and detected_type in ('color_negative', 'bw_negative', 'positive'):
                film_type = detected_type
                scan_options = ScanOptions(**(scan_options | {'film': 'positive' if detected_type == 'positive' else 'negative'})).model_dump()
                store.save_many('cv_preferences', [
                    {'id': 'film-type', 'film_type': film_type},
                    {'id': 'workspace', 'settings': scan_options}])
                session['film_type'] = film_type
            session['film_type_detection'] = detection
        atomic_write(store.path(base + '-preview.jpg'), jpeg(samples, PREVIEW_EDGE))
        atomic_write(store.path(base + '-thumb.jpg'), jpeg(samples, THUMB_EDGE))
        record_purpose = 'coverage_attempt' if session.get('purpose') == 'frame_scan' else session.get('purpose', 'scan')
        record = {'id': capture_id, 'session_id': session['id'], 'index': index, 'roll': session['roll'],
                  'title': f"{session['roll'] or 'Roll'} · {index:02d}", 'created_at': int(time.time() * 1000),
                  'original_path': base + '.tif', 'preview_path': base + '-preview.jpg', 'thumb_path': base + '-thumb.jpg',
                  'sha256': digest, 'width': event['width'], 'height': event['height'], 'bits': event['bits'],
                  'dpi': round(event['dpi']), 'source': source, 'hardware': not event.get('synthetic', False), 'favorite': False,
                  'backend': bridge.kind, 'image_kind': bridge.image_kind, 'effective_bits': None,
                  'purpose': record_purpose, 'requested_settings': session.get('requested_settings'),
                  'film_type': session.get('film_type', film_type),
                  'cyberview': session['settings'],
                  'adjustments': Adjustments(monochrome=event.get('binary_recipe_requested',False),
                                             saturation=-100 if session.get('film_type') == 'bw_negative' else 0,
                                             invert=bridge.image_kind == 'vendor-calibrated-transmission' and
                                             session.get('requested_settings', {}).get('film', 'negative') == 'negative').model_dump()}
        if not event.get('binary_recipe_requested',False):
            record['precision_measurement']=sensor_precision.analyze_acquisition(tifffile.imread(original),provenance={
                'original_acquisition':True,'hardware':record['hardware'],'synthetic':not record['hardware'],
                'image_kind':bridge.image_kind})
            record['precision_measurement']['measured_source_sha256']=digest
        if detection:
            record['film_type_detection'] = detection
            if record['film_type'] == 'positive':
                record['adjustments']['invert'] = False
        # Compute automatic colour as a nondestructive viewing recipe.
        film_base_exposure(record, samples)
        initial_adjustments(record, samples)
        if session.get('purpose') == 'frame_scan':
            result = align_record(record, samples, align_settings['bleed_mm'], apply_crop=False)
            witness = frame_align.rebate_witness(result, record['width'], record['dpi'])
            record['coverage_verification'] = witness
            if witness['verified']:
                record['purpose'] = 'scan'
                align_record(record, samples, align_settings['bleed_mm'], apply_crop=True)
            else:
                record['title'] = f"{session['roll'] or 'Roll'} · coverage check failed"
        elif session.get('purpose') == 'roll_preview':
            result = align_record(record, samples, align_settings['bleed_mm'], apply_crop=False)
            witness = frame_align.rebate_witness(result, record['width'], record['dpi'])
            window_mm = 2586 / 1800 * frame_align.MM_PER_INCH
            measured_mm = result['x'].get('measured_mm')
            record['derived'] = {'kind': 'roll-preview', 'rebate_witness': witness,
                                 'single_pass_eligible': bool(witness['verified'] and measured_mm is not None and
                                                              measured_mm + 2 * witness['minimum_mm'] <= window_mm),
                                 'note': '300 dpi roll preview; not an archival scan.'}
        elif align_settings['auto'] and session.get('purpose', 'scan') == 'scan':
            align_record(record, samples, align_settings['bleed_mm'])
        initial_tone(record,samples)
        atomic_write(store.path(base + '.json'), json.dumps(record, indent=1).encode())
        return store.save('cv_captures', record)

    def align_record(record, samples, bleed_mm, covered=None, apply_crop=True):
        """Finds the 35 mm frame and, when an exact crop fits, makes it the capture's crop."""
        result = frame_align.align_35mm(samples, record['dpi'], record.get('image_kind') == 'vendor-calibrated-transmission',
                                        bleed_mm, covered=covered)
        record['alignment'] = {k: result[k] for k in ('confidence', 'exact', 'crop_mm', 'crop_px', 'skew_deg', 'bleed_mm',
                                                     'dimensions_exact', 'coverage_fraction', 'missing_pixels', 'crop_basis')} | {
            'edges_x': result['x'], 'edges_y': result['y'], 'note': result.get('note'), 'at': int(time.time() * 1000)}
        # A nominal-size rectangle fitting the mosaic does not prove that the
        # actual exposure was located. Keep uncertain stitched crops for review.
        crop_applied = apply_crop and result['exact'] and (record.get('purpose') != 'stitched' or result['confidence'] == 'frame_found')
        record['alignment']['crop_applied'] = crop_applied
        if record.get('purpose') == 'stitched' and result['confidence'] != 'frame_found':
            record['alignment']['note'] = ('Both frame borders were not detected. No automatic crop was applied; '
                                           'the saved crop is unchanged. Adjust it manually or acquire wider coverage. '
                                           + (result.get('note') or '')).strip()
        if crop_applied:
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
                await bridge.scan(incoming, session['count'], on_event, session.get('until_end', False))
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
            if state == 'complete' and session.get('purpose') == 'frame_scan':
                attempts = [store.get('cv_captures', capture_id) for capture_id in session['captures']]
                failed = next((item for item in attempts if not item.get('coverage_verification', {}).get('verified')), None)
                if failed:
                    preview_id = session.get('border_preview_id')
                    if preview_id:
                        preview_record = capture(preview_id)
                        preview_record.setdefault('derived', {}).update(single_pass_eligible=False, requires_wider_capture=True,
                                                                        fallback_reason=failed.get('coverage_verification', {}).get('reason'))
                        store.save('cv_captures', preview_record)
                    await update_session(state='recovering', driver_status='Coverage was not verified; starting the overlapping full-frame path')
                    fallback = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': 3, 'completed': 0,
                                'roll': session['roll'], 'captures': [], 'started_at': int(time.time() * 1000),
                                'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0,
                                'rows': 0, 'height': 0, 'error': None, 'purpose': 'stitched',
                                'requested_settings': scan_options, 'border_search': False, 'until_end': False,
                                'coverage_preview_id': session.get('border_preview_id'),
                                'film_type': session.get('film_type'), 'driver_status': None, 'driver_dialog': None,
                                'cancel_requested': False,
                                'stitch': {'offset_mm': align_settings['offset_mm'], 'bleed_mm': align_settings['bleed_mm'],
                                           'sources': [], 'position': {'net_completed_steps': 0, 'position_known': True,
                                                                       'basis': 'acknowledged_relative_motor_steps',
                                                                       'pending_move': None, 'returned_to_start': False}}}
                    runtime['session'] = store.save('cv_sessions', fallback)
                    await publish({'type': 'cyberview_session', 'session': fallback})
                    await run_stitched(fallback, align_settings['offset_mm'], align_settings['bleed_mm'])
                    return
            if state == 'complete' and session.get('until_end') and index:
                await update_session(count=index)   # "All frames" ends where the film does
            elif state == 'complete' and index != session['count']:
                raise ScannerError(f'The driver delivered {index} of {session["count"]} requested frames')
            await update_session(state=state, finished_at=int(time.time() * 1000))
        except ScannerError as exc:
            await update_session(state='error', error=str(exc), finished_at=int(time.time() * 1000))
        except Exception as exc:  # recorded, never reported as success
            await update_session(state='error', error=f'Unexpected failure: {exc}', finished_at=int(time.time() * 1000))
        finally:
            for leftover in incoming.parent.glob('incoming*.tif'):
                leftover.unlink(missing_ok=True)

    def transport_state(session):
        return session.setdefault('transport', {'basis': 'acknowledged_frame_moves_with_local_optical_checks',
            'current_preview_index': 1, 'fine_step_offset': 0, 'position_known': True,
            'pending_action': None, 'pending_target': None})

    async def fine_position(session, target):
        if session.get('cancel_requested'):
            raise ScannerError('Scanning cancelled; no further film movement attempted')
        transport = transport_state(session)
        if isinstance(bridge,NativeAflBridge):bridge.require_known_position()
        if not transport.get('position_known', True):
            raise ScannerError('Film position is uncertain; no further movement was attempted')
        current = transport.setdefault('fine_step_offset', 0)
        while current != target:
            if session.get('cancel_requested') or bridge.cancel_requested:
                raise ScannerError('Scanning cancelled; completed sources are preserved')
            steps = min(NUDGE_CHUNK, abs(target-current))
            direction = 'forward' if target > current else 'back'
            transport.update(position_known=False, pending_action='nudge', pending_target=target)
            store.save('cv_sessions', session)
            await bridge.control('nudge', value=f'{direction} {steps}')
            if session.get('cancel_requested') or bridge.cancel_requested:
                if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'cancelled_before_fine_move_accounting')
                raise ScannerError('Film movement was interrupted; the final position is uncertain')
            current += steps if direction == 'forward' else -steps
            transport.update(fine_step_offset=current, position_known=True, pending_action=None, pending_target=None)
            store.save('cv_sessions', session)

    async def take_local(session, path, dpi, label, *, options_override=None):
        options = (ScanOptions(**options_override).model_dump() if options_override is not None else
                   workspace.border_preview_options(scan_options) if dpi == 300 else
                   workspace.full_frame_scan_options(scan_options))
        if options['dpi']!=dpi:
            raise ScannerError('The local acquisition options do not match the planned resolution')
        await bridge.configure(options)
        async def event(value):
            kind = value.get('event')
            if kind == 'image_start':
                await update_session(state='scanning', rows=0, height=value['height'], driver_status=label)
            elif kind == 'progress':
                await publish({'type': 'cyberview_progress', 'session_id': session['id'],
                               'frame': session.get('frame', 1), 'rows': value['rows'], 'height': value['height']})
            elif kind in ('live_start', 'live'):
                await relay_live(session, value, session.get('frame', 1))
        if session.get('cancel_requested'):
            raise ScannerError('Scanning cancelled before acquisition')
        started=time.monotonic()
        images = await bridge.scan(store.path(path), 1, event)
        if not images:
            raise ScannerError('The scanner delivered no image')
        delivered = images[0]
        source = {'path': path, 'sha256': hashlib.sha256(store.path(path).read_bytes()).hexdigest(),
                  'width': delivered['width'], 'height': delivered['height'], 'dpi': round(delivered['dpi']),
                  'bits': delivered['bits'], 'hardware': not delivered.get('synthetic', False),
                  'position_steps': transport_state(session).get('fine_step_offset', 0),
                  'seconds':round(time.monotonic()-started,3),'requested_settings':options,
                  'vendor_auto_exposure_reported':delivered.get('vendor_auto_exposure')}
        if dpi==1800:
            source['precision_measurement']=sensor_precision.analyze_acquisition(tifffile.imread(store.path(path)),provenance={
                'original_acquisition':True,'hardware':source['hardware'],'synthetic':not source['hardware'],
                'image_kind':bridge.image_kind})
            source['precision_measurement']['measured_source_sha256']=source['sha256']
            source['precision_measurement']['scope']='individual_original_source_not_derived_master'
        # Persist immediately: originals survive later registration or cancellation failures.
        session.setdefault('retained_sources', []).append(source)
        store.save('cv_sessions', session)
        if source['dpi']!=dpi or source['bits']!=options['bits'] or delivered.get('samples',3)!=3:
            raise ScannerError('UNVERIFIED_ACQUISITION_SETTINGS: delivered image does not match the planned RGB resolution/depth; original preserved')
        if not options['auto_exposure'] and delivered.get('vendor_auto_exposure') is True:
            raise ScannerError('UNVERIFIED_EXPOSURE_LOCK: acquisition reported vendor auto exposure despite fixed settings; original preserved')
        if session.get('cancel_requested') or bridge.cancel_requested:
            raise ScannerError('Scanning cancelled; delivered source was preserved')
        return source

    async def local_border_search(parent, frame, initial=None):
        transport = transport_state(parent)
        await fine_position(parent, 0)
        options = workspace.border_preview_options(scan_options)
        child = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': 1, 'completed': 0,
            'roll': parent['roll'], 'captures': [], 'started_at': int(time.time()*1000),
            'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': frame,
            'rows': 0, 'height': 0, 'error': None, 'purpose': 'prescan', 'border_search': True,
            'border_search_state': {'probe_limit': MAX_BORDER_SEARCH_PROBES, 'probes': 0,
                                  'limit_reached': False, 'stop_reason': None},
            'roll_preview_parent_id': parent['id'], 'position_generation': parent.get('position_generation'),
            'film_type': parent.get('film_type', film_type), 'requested_settings': options,
            'cancel_requested': False, 'initial_preview': initial,
            'stitch': {'offset_mm': align_settings['offset_mm'], 'bleed_mm': align_settings['bleed_mm'],
                'sources': [], 'position': {'net_completed_steps': 0, 'position_known': True,
                    'pending_move': None, 'returned_to_start': False, 'basis': 'acknowledged_relative_motor_steps'}}}
        runtime['session'] = store.save('cv_sessions', child)
        try:
            await bridge.configure(options)
            await run_stitched(child, align_settings['offset_mm'], align_settings['bleed_mm'])
        finally:
            position = child['stitch']['position']
            transport.update(fine_step_offset=position['net_completed_steps'], position_known=position['position_known'])
            if child.get('cancel_requested'):
                parent['cancel_requested']=True
            parent.setdefault('border_search_sessions', []).append(child['id'])
            runtime['session'] = store.save('cv_sessions', parent)
            await publish({'type': 'cyberview_session', 'session': parent})
        if child['state'] != 'complete' or not child['captures']:
            raise ScannerError(child.get('error') or 'Local border search did not complete')
        await fine_position(parent, 0)
        return capture(child['captures'][-1])

    async def verify_favorite_arrival(session, preview):
        # A saved preview is evidence about content, never a substitute for local positioning.
        source = await take_local(session, f"cyberview/{session['id']}/arrival-{preview['index']:02d}.tif",
                                  300, f"Verifying arrival at preview frame {preview['index']}")
        reference = preview
        reference_id = (preview.get('derived') or {}).get('border_preview_capture_id')
        if reference_id:
            reference = capture(reference_id)
        sources = (reference.get('derived') or {}).get('sources') or []
        centre = next((item for item in sources if item.get('label') == 'centre'), None)
        verification = {'preview_id': preview['id'], 'source': source, 'verified': False,
                        'action': 'fresh_bounded_border_search'}
        if centre:
            a = to_float(read_original(store.path(centre['path'])))
            b = to_float(read_original(store.path(source['path'])))
            try:
                match=await asyncio.to_thread(acquisition_plan.register_preview,a,b)
                verification.update(dx_preview_px=match['dx'],dy_preview_px=match['dy'],
                                    peak=match['peak'],peak_ratio=match['peak_ratio'],verified=True)
            except ValueError as exc:
                verification['reason']=str(exc)
        session.setdefault('arrival_verifications', []).append(verification)
        store.save('cv_sessions', session)
        # Reuse this physical capture as the first window of the local search.
        return source

    async def acquire_planned_frame(session, frame, preview=None, initial=None, replan_allowed=True, tone_preview=None):
        session['frame'] = frame
        transport = transport_state(session)
        await fine_position(session, 0)
        if preview is None:
            preview = await local_border_search(session, frame, initial)
        reference_id = (preview.get('derived') or {}).get('border_preview_capture_id')
        if reference_id:
            preview = capture(reference_id)
        try:
            plan = acquisition_plan.plan_archival(preview)
        except ValueError as exc:
            raise ScannerError(str(exc)) from exc
        session['acquisition_plan'] = plan
        session.setdefault('frame_plans', []).append({'frame': frame, 'plan': plan})
        # Restore the existing verified acquisition-exposure stage on this path.
        # The local preview is taken at known exposures; measure its film base
        # before archival capture rather than compensating for unequal channels
        # only after acquisition. Never derive gains from the rendered positive.
        preview_samples=to_float(read_original(store.path(preview['original_path'])))
        film_base_exposure(preview,preview_samples,coverage(preview))
        preview_adjustments=json.loads(json.dumps(preview['adjustments']))
        await asyncio.to_thread(initial_tone,preview,preview_samples,coverage(preview),tone_preview,True)
        latest_preview=capture(preview['id'])
        if latest_preview['adjustments']!=preview_adjustments:
            # A concurrent edit owns its recipe. Do not overwrite it with defaults
            # computed from the earlier snapshot while a CPU worker was running.
            preview['adjustments']=latest_preview['adjustments']
            preview['vendor_auto_tone']=latest_preview.get('vendor_auto_tone',{'enabled':False,'reason':'Preview edited during tone generation'})
        store.save('cv_captures',preview)
        if preview.get('film_base'):
            session.setdefault('acquisition_exposure',[]).append({'frame':frame,**preview['film_base']})
            store.save('cv_captures',preview)
        archival_options=workspace.full_frame_scan_options(scan_options)
        requested_auto=archival_options['auto_exposure']
        multiple_tiles=len(plan['tiles'])>1
        if multiple_tiles:
            # The vendor may choose a different internal multiplier at each
            # position. Freeze the measured/manual seeds and flag0 for all
            # archival tiles; retain the user's preference for single tiles.
            archival_options=ScanOptions(**(archival_options | {'auto_exposure':False})).model_dump()
        exposure_policy={'frame':frame,'tile_count':len(plan['tiles']),
            'requested_vendor_auto_exposure':requested_auto,
            'mode':'fixed_manual' if not archival_options['auto_exposure'] else 'vendor_auto_single_tile',
            'reason':'multiple_tiles_require_fixed_exposure' if multiple_tiles else 'single_tile',
            'seed_source':'local_film_base' if preview.get('film_base') else 'workspace_manual',
            'settings':archival_options,'scope':'requested_acquisition_settings_not_a_bound_on_internal_calibration_drift'}
        plan['archival_exposure']=exposure_policy
        session.setdefault('frame_exposure_policies',[]).append(exposure_policy)
        verification_options=workspace.border_preview_options(archival_options)
        store.save('cv_sessions', session)
        images, sources = [], []
        acquisition_tag=uuid.uuid4().hex[:8]
        for number, tile in enumerate(plan['tiles'], 1):
            await fine_position(session, tile['position_steps'])
            old_source = preview['derived']['sources'][tile['source_index']]
            old = to_float(read_original(store.path(old_source['path'])))
            original_dx,original_dy=tile['dx'],tile['dy']
            origin=-min(item['dx'] for item in preview['derived']['offsets_px'])
            bounds=plan['required_bounds_preview_px']
            for correction in range(MAX_BORDER_SEARCH_PROBES+1):
                verified=await take_local(session,
                    f"cyberview/{session['id']}/verify-{frame:02d}-{number}-{acquisition_tag}-{correction}.tif",300,
                    f"Optically verifying planned position {number}/{len(plan['tiles'])}",options_override=verification_options)
                now=to_float(read_original(store.path(verified['path'])))
                if now.shape!=old.shape:
                    raise ScannerError('UNVERIFIED_PREVIEW_GEOMETRY: arrival image dimensions changed; original preserved')
                try:
                    match=await asyncio.to_thread(acquisition_plan.register_preview,old,now)
                except ValueError as exc:
                    if not images and replan_allowed:
                        await fine_position(session,0)
                        return await acquire_planned_frame(session,frame,replan_allowed=False)
                    raise ScannerError(str(exc)) from exc
                tile['arrival_registration']=match
                tile['dx']=original_dx+match['dx']
                tile['dy']=original_dy+match['dy']
                actual_left=tile['dx']+origin
                actual_right=actual_left+verified['width']
                need_left=number==1 and actual_left>bounds['left']
                need_right=number==len(plan['tiles']) and actual_right<bounds['right']
                need_overlap=False
                if number>1:
                    previous=plan['tiles'][number-2]
                    overlap=min(previous['dx']+previous['width'],tile['dx']+tile['width'])-max(previous['dx'],tile['dx'])
                    need_overlap=overlap<plan['minimum_overlap_preview_px']
                if not (need_left or need_right or need_overlap):
                    break
                if correction>=MAX_BORDER_SEARCH_PROBES:
                    raise ScannerError('UNVERIFIED_PREVIEW_COVERAGE: bounded optical correction could not retain padded rebates/overlap; no further archival pass attempted')
                direction=-1 if need_left or need_overlap else 1
                target=transport['fine_step_offset']+direction*NUDGE_CHUNK
                await fine_position(session,target)
            tile['position_steps']=transport['fine_step_offset']
            tile['verification_source']=verified
            if 'top' in bounds:
                origin_y=-min(item.get('dy',0) for item in preview['derived']['offsets_px'])
                if tile['dy']+origin_y>bounds['top'] or tile['dy']+origin_y+tile['height']<bounds['bottom']:
                    plan['vertical_containment']={'status':'unverified','reason':'Replayed window does not retain padded vertical bounds; full acquired height retained.'}
            store.save('cv_sessions',session)
            repeats=[]
            repeat_images=[]
            for sample in range(session.get('repeat_samples',1)):
                source = await take_local(session, f"cyberview/{session['id']}/source-frame-{frame:02d}-tile-{number}-{acquisition_tag}-sample-{sample+1}.tif",
                                          1800, f"Acquiring tile {number}/{len(plan['tiles'])}, sample {sample+1}/{session.get('repeat_samples',1)}",
                                          options_override=archival_options)
                repeats.append(source)
                repeat_images.append(to_float(read_original(store.path(source['path']))))
            source=repeats[0] | {'label':f'tile-{number}'}
            if len(repeats)>1:
                try:
                    averaged=await asyncio.to_thread(scan_filters.aligned_mean,repeat_images,dpi=1800,search_radius_px=18)
                except ValueError as exc:
                    raise ScannerError(f'Repeated acquisitions could not be aligned; all originals preserved: {exc}') from exc
                averaged_image=averaged['image']
                if not averaged['covered'].all():
                    raise ScannerError('Repeated acquisitions have uncovered pixels; originals preserved without publishing an average')
                mean_path=f"cyberview/{session['id']}/mean-frame-{frame:02d}-tile-{number}-{acquisition_tag}.tif"
                mean_stream=BytesIO()
                repeat_processing={'engine':averaged['engine'],'method':averaged['method'],
                    'offset_normalization':averaged['offset_normalization'],'multiplicative_exposure_matching':False}
                tifffile.imwrite(mean_stream,np.uint16(np.clip(averaged_image,0,1)*65535+.5),photometric='rgb',
                                 resolution=(1800,1800),resolutionunit='INCH',software='FRAME optical repeat mean',
                                 description=json.dumps({'kind':'repeat_mean','repeat_processing':repeat_processing,
                                     'source_sha256':[item['sha256'] for item in repeats],
                                     'requested_settings':archival_options}))
                atomic_write(store.path(mean_path),mean_stream.getvalue())
                source=source | {'path':mean_path,'sha256':hashlib.sha256(mean_stream.getvalue()).hexdigest(),
                    'derived':True,'repeat_sources':repeats,'repeat_registration':averaged['registration'],
                    'full_repeat_coverage_fraction':float(averaged['full_repeat_coverage'].mean()),
                    'repeat_processing':repeat_processing,
                    'note':'Derived mean; individual repeat TIFFs are the acquisition originals.'}
                session.setdefault('derived_tiles',[]).append(source)
                store.save('cv_sessions',session)
                images.append(averaged_image)
            else:
                images.append(repeat_images[0])
            sources.append(source)
        try:
            stitched = await asyncio.to_thread(acquisition_plan.stitch_planned, images, plan)
        except ValueError as exc:
            raise ScannerError(str(exc)) from exc
        if session.get('cancel_requested') or bridge.cancel_requested:
            session['cancel_requested']=True
            raise ScannerError('Scanning cancelled during processing; acquired tiles are preserved')
        image = stitched['image']; h, w = image.shape[:2]
        capture_id = uuid.uuid4().hex
        base = f"cyberview/{session['id']}/planned-{frame:02d}-{capture_id[:8]}"
        stream = BytesIO()
        tifffile.imwrite(stream, (np.clip(image,0,1)*65535+.5).astype(np.uint16), photometric='rgb',
                         resolution=(1800,1800), resolutionunit='INCH', software='FRAME optical plan')
        atomic_write(store.path(base+'.tif'), stream.getvalue())
        cover = BytesIO(); Image.fromarray((stitched['covered']*255).astype(np.uint8)).save(cover,'PNG')
        atomic_write(store.path(base+'-coverage.png'), cover.getvalue())
        atomic_write(store.path(base+'-preview.jpg'), jpeg(image,PREVIEW_EDGE))
        atomic_write(store.path(base+'-thumb.jpg'), jpeg(image,THUMB_EDGE))
        record = {'id':capture_id, 'session_id':session['id'], 'index':frame, 'roll':session['roll'],
            'title':f"{session['roll'] or 'Roll'} · {frame:02d}", 'created_at':int(time.time()*1000),
            'original_path':base+'.tif','preview_path':base+'-preview.jpg','thumb_path':base+'-thumb.jpg',
            'coverage_path':base+'-coverage.png','sha256':hashlib.sha256(stream.getvalue()).hexdigest(),
            'width':w,'height':h,'bits':16,'dpi':1800,'source':NATIVE_SOURCE,
            'hardware':all(item['hardware'] for item in sources),'backend':bridge.kind,'image_kind':bridge.image_kind,
            'effective_bits':None,'precision_measurement':sources[0].get('precision_measurement'),
            'purpose':'scan' if len(sources)==1 else 'stitched','favorite':False,
            'film_type':session.get('film_type',film_type),'requested_settings':archival_options,
            'cyberview':bridge.acquisition_settings(),
            'derived':{'kind':'optically-planned','sources':sources,'acquisition_plan':plan,
                'offsets_px':stitched['offsets_px'],'match_strength':stitched['match_strength'],
                'registration':stitched.get('registration'), 'border_preview_capture_id':preview['id'],
                'archival_exposure':exposure_policy,
                'final_position_steps':transport.get('fine_step_offset',0)},
            'adjustments':Adjustments(invert=session.get('film_type',film_type)!='positive',
                saturation=-100 if session.get('film_type')=='bw_negative' else 0).model_dump()}
        initial_adjustments(record,image,stitched['covered'])
        alignment = align_record(record,image,align_settings['bleed_mm'],stitched['covered'])
        witness = frame_align.rebate_witness(alignment,w,1800)
        witness.update(scope='horizontal_rebates',vertical_containment=plan['vertical_containment'])
        record['coverage_verification']=witness
        if plan['vertical_containment']['status']!='verified' and record['alignment']['crop_applied']:
            record['adjustments']['crop'].update(top=0,bottom=1)
            record['alignment']['crop_scope']='horizontal_only'
            record['alignment']['vertical_containment_verified']=False
            record['alignment']['applied_crop_px']={'left':round(record['adjustments']['crop']['left']*w),
                'top':0,'width':round((record['adjustments']['crop']['right']-record['adjustments']['crop']['left'])*w),'height':h}
            record['alignment']['note']='Horizontal borders verified; vertical containment remains unverified. Full acquired height retained.'
        if not witness['verified'] or not record['alignment']['crop_applied']:
            record['purpose']='coverage_attempt'
        full_height=record['adjustments']['crop']['top']==0 and record['adjustments']['crop']['bottom']==1
        full_window=all(s['height']==1708 and s.get('requested_settings',{}).get('crop')==workspace.FULL_WINDOW_CROP for s in sources)
        witness.update(x_containment_verified=bool(witness['verified']),
            y_containment_verified=plan['vertical_containment']['status']=='verified',
            y_containment='verified' if plan['vertical_containment']['status']=='verified' else
                'vendor_window_limited' if full_height and full_window else 'unverified',
            full_acquired_height_retained=full_height)
        await asyncio.to_thread(initial_tone,record,image,stitched['covered'],preview)
        atomic_write(store.path(base+'-acquired.json'),json.dumps(record,indent=1).encode())
        store.save('cv_captures',record)
        session['captures'].append(record['id'])
        await publish({'type':'cyberview_capture','capture':record})
        if record['purpose']=='coverage_attempt':
            raise ScannerError('UNVERIFIED_FRAME_COVERAGE: planned acquisitions did not verify frame coverage; originals preserved, no high-resolution search was attempted')
        await fine_position(session,0)
        record['derived']['final_position_steps']=0
        atomic_write(store.path(base+'.json'),json.dumps(record,indent=1).encode())
        store.save('cv_captures',record)
        store.save('cv_sessions',session)
        return record

    def validate_end_action(action):
        required = {'return_to_frame_1':'previous','eject_forward':'eject_forward'}.get(action)
        if required and required not in workspace.validation().get('actions',[]):
            raise HTTPException(409,f'The selected end action requires verified {required} transport')

    def validate_repeats(count):
        if count>1 and scan_options.get('auto_exposure'):
            raise HTTPException(409,'Use fixed exposure settings for repeated scans; vendor auto exposure may choose different gains on each pass')

    async def move_frame(session,target):
        transport = transport_state(session)
        await fine_position(session,0)
        while transport['current_preview_index']!=target:
            if session.get('cancel_requested'):
                raise ScannerError('Scanning cancelled before frame movement')
            direction='next' if target>transport['current_preview_index'] else 'previous'
            transport.update(position_known=False,pending_action=direction,pending_target=target)
            store.save('cv_sessions',session)
            try:
                await bridge.film(direction)
            except ScannerError:
                transport['position_known']=False
                store.save('cv_sessions',session)
                raise
            if session.get('cancel_requested') or bridge.cancel_requested:
                if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'cancelled_before_frame_move_accounting')
                raise ScannerError('Frame movement was interrupted; final position remains uncertain')
            transport['current_preview_index']+=1 if direction=='next' else -1
            transport.update(position_known=True,pending_action=None,pending_target=None,fine_step_offset=0)
            store.save('cv_sessions',session)

    async def finish_batch(session):
        if session.get('cancel_requested') or bridge.cancel_requested:
            session['cancel_requested']=True
            raise ScannerError('Scanning cancelled; end-of-roll transport was not attempted')
        action=session.get('end_action','return_to_frame_1')
        await fine_position(session,0)
        await update_session(state='advancing',driver_status='Finishing roll transport')
        if action=='return_to_frame_1':
            await move_frame(session,1)
            transport_state(session)['returned_counter_to_first']=True
            reference=session.get('first_frame_reference')
            verification={'verified':False,'counter_acknowledged':True,'reason':'No saved first-frame optical reference.'}
            if reference:
                arrival=None
                try:
                    arrival=await take_local(session,f"cyberview/{session['id']}/return-arrival-{uuid.uuid4().hex[:8]}.tif",300,
                                             'Checking the returned first frame')
                    verification=await asyncio.to_thread(acquisition_plan.register_preview,
                        to_float(read_original(store.path(reference['path']))),to_float(read_original(store.path(arrival['path']))))
                    verification.update(counter_acknowledged=True,reference_source=reference,verification_source=arrival,
                                        dx_return_px=verification['dx'],dy_return_px=verification['dy'])
                except (ValueError,ScannerError) as exc:
                    verification={'verified':False,'counter_acknowledged':True,'reason':str(exc),
                                  'reference_source':reference,'verification_source':arrival}
            session['return_verification']=verification
            transport_state(session)['returned_to_first']=verification['verified']
            if verification['verified']:
                note='Film returned to frame 1; the arrival image matches the saved first frame.'
            else:
                note='Backward moves were acknowledged, but the first-frame image could not be verified. Check the film before continuing.'
                session['warning_code']='RETURN_COUNTER_ACK_OPTICAL_UNVERIFIED'
                transport_state(session)['position_known']=False
                if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'return_optical_verification_failed')
        elif action=='eject_forward':
            transport_state(session).update(position_known=False,pending_action='eject_forward')
            store.save('cv_sessions',session)
            await bridge.film('eject_forward')
            if session.get('cancel_requested') or bridge.cancel_requested:
                raise ScannerError('Ejection was interrupted; final position remains uncertain')
            transport_state(session).update(position_known=False,ejected=True,pending_action=None)
            note='Forward eject completed.'
        else:
            note='Film held at the final scanned frame.'
        session['end_action_result']={'action':action,'confirmed':verification['verified'] if action=='return_to_frame_1' else True,
                                     'counter_acknowledged':True if action=='return_to_frame_1' else None,'note':note}
        session['end_of_roll_note']=(session.get('end_of_roll_note','')+' '+note).strip()
        await update_session(state='complete',finished_at=int(time.time()*1000),driver_status=note)

    async def run_favorite_scans(session, previews):
        try:
            for number,preview in enumerate(sorted(previews,key=lambda item:item['index']),1):
                await move_frame(session,preview['index'])
                initial=await verify_favorite_arrival(session,preview)
                arrival=(session.get('arrival_verifications') or [{}])[-1]
                await acquire_planned_frame(session,preview['index'],initial=initial,
                    tone_preview=preview if arrival.get('verified') else None)
                await update_session(completed=number,count=len(previews))
            await finish_batch(session)
        except Exception as exc:
            await update_session(state='cancelled' if session.get('cancel_requested') else 'error',
                                 error=str(exc),finished_at=int(time.time()*1000))

    async def run_roll_preview(session, detail_dpi, border_options, scan_after=False, resume=False):
        """Run the adaptive border finder on one frame or every frame, then save its preview."""
        detailed_options = ScanOptions(**(scan_options | {'dpi': 600, 'bits': 16, 'channel': 'rgb','auto_exposure':False,
                                                         'crop': scan_options['crop'], 'focus': None})).model_dump()
        frame_index = session.get('completed',0) if resume else 0

        async def restore_parent():
            runtime['session'] = store.save('cv_sessions', session)
            await publish({'type': 'cyberview_session', 'session': session})

        async def one_frame_preview():
            border_record = await local_border_search(session, frame_index + 1)
            if frame_index==0:
                centre=next((s for s in (border_record.get('derived') or {}).get('sources',[]) if s.get('label')=='centre'),None)
                if centre:session.setdefault('first_frame_reference',centre)
            if detail_dpi!=300:
                await asyncio.to_thread(initial_tone,border_record,
                    to_float(read_original(store.path(border_record['original_path']))),coverage(border_record),None,True)
                store.save('cv_captures',border_record)
            if detail_dpi == 300:
                border_record.update(session_id=session['id'], index=frame_index + 1,
                                     title=f"{session['roll'] or 'Roll'} · preview {frame_index + 1:02d}",
                                     purpose='roll_preview', border_preview=True,
                                     position_generation=session['position_generation'])
                border_record.setdefault('derived', {})['roll_preview_detail'] = 'quick_300dpi'
                await asyncio.to_thread(initial_tone,border_record,
                    to_float(read_original(store.path(border_record['original_path']))),coverage(border_record))
                stored = store.save('cv_captures', border_record)
                session['captures'].append(stored['id'])
                await publish({'type': 'cyberview_capture', 'capture': stored})
                return stored

            await bridge.configure(detailed_options)
            path = store.path(f"cyberview/{session['id']}/incoming-detail-{frame_index + 1:02d}.tif")
            detailed = {}

            async def on_event(event):
                kind = event.get('event')
                if kind == 'enabled':
                    await update_session(state='warming', frame=frame_index + 1,
                                         driver_status=f"Capturing detailed preview {frame_index + 1}")
                elif kind == 'image_start':
                    await update_session(state='scanning', frame=frame_index + 1, rows=0, height=event['height'],
                                         delivered={k: event.get(k) for k in ('width', 'height', 'bits', 'dpi', 'samples')})
                elif kind == 'progress':
                    session.update(rows=event['rows'], height=event['height'])
                    await publish({'type': 'cyberview_progress', 'session_id': session['id'],
                                   'frame': frame_index + 1, 'rows': event['rows'], 'height': event['height']})
                elif kind in ('live_start', 'live'):
                    await relay_live(session, event, frame_index + 1)
                elif kind == 'image':
                    detailed.update(await asyncio.to_thread(finalize, session, event, frame_index + 1))

            try:
                images = await bridge.scan(path, 1, on_event)
            finally:
                path.unlink(missing_ok=True)
            if not images or not detailed:
                raise ScannerError(f"No detailed preview was delivered for frame {frame_index + 1}")
            detailed['derived'] = (detailed.get('derived') or {}) | {
                'kind': 'roll-preview', 'roll_preview_detail': 'detailed_600dpi',
                'single_pass_eligible': border_record.get('derived', {}).get('single_pass_eligible', False),
                'border_preview_capture_id': border_record['id'],
                'border_alignment': border_record.get('alignment')}
            detailed['title'] = f"{session['roll'] or 'Roll'} · detailed preview {frame_index + 1:02d}"
            detailed['position_generation'] = session['position_generation']
            await asyncio.to_thread(initial_tone,detailed,
                to_float(read_original(store.path(detailed['original_path']))),coverage(detailed),border_record)
            stored = store.save('cv_captures', detailed)
            session['captures'].append(stored['id'])
            await publish({'type': 'cyberview_capture', 'capture': stored})
            return stored

        async def finish_previews():
            session['roll_preview_complete'] = True
            if scan_after:
                session['purpose'] = 'scan_all'
                await update_session(count=session['completed'])
                await finish_batch(session)
            else:
                await update_session(state='complete', count=session['completed'], completed=session['completed'],
                                     driver_status=f"Roll preview complete · {detail_dpi} dpi",
                                     finished_at=int(time.time() * 1000))

        async def advance_from(index):
            # Balanced motor counts do not establish an optical anchor.
            # Record the real view after capture/fine-step reconciliation,
            # immediately before attempting the next frame movement.
            advance_reference=await take_local(session,
                f"cyberview/{session['id']}/advance-reference-{index+1:02d}-{uuid.uuid4().hex[:8]}.tif",300,
                'Recording the current frame before advancing')
            if index==0:session.setdefault('first_frame_reference',advance_reference)
            before_advance_counter=getattr(bridge,'last_frame_position',None)
            try:
                await update_session(state='advancing', frame=index + 2,
                                     driver_status=f"Moving to preview frame {index + 2}")
                transport_state(session).update(position_known=False,pending_action='next',pending_target=index+2)
                store.save('cv_sessions',session)
                await bridge.film('next')
                if session.get('cancel_requested') or bridge.cancel_requested:
                    if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'cancelled_before_advance_accounting')
                    raise ScannerError('Frame movement was interrupted; final position remains uncertain')
                transport_state(session).update(position_known=True,current_preview_index=index+2,
                                                pending_action=None,pending_target=None)
                store.save('cv_sessions',session)
            except ScannerError as exc:
                end_messages = ('No supported film strip is loaded', 'No further frame',
                                'The driver did not confirm the requested frame movement')
                if session.get('completed', 0) and any(message in str(exc) for message in end_messages):
                    # An unconfirmed move is not proof that the film stayed put.
                    end_source=await take_local(session,f"cyberview/{session['id']}/end-boundary-{uuid.uuid4().hex[:8]}.tif",300,
                                                'Checking the final frame after an unconfirmed advance')
                    a=to_float(read_original(store.path(advance_reference['path'])))
                    b=to_float(read_original(store.path(end_source['path'])))
                    try:
                        boundary=await asyncio.to_thread(acquisition_plan.register_preview,a,b)
                        after_advance_counter=getattr(bridge,'last_frame_position',None)
                        counter_unchanged=before_advance_counter is not None and after_advance_counter==before_advance_counter
                        boundary.update(verified=bool(boundary['verified'] and counter_unchanged),
                            vendor_counter_before=before_advance_counter,vendor_counter_after=after_advance_counter,
                            vendor_counter_unchanged=counter_unchanged,
                            stationary_within_three_preview_pixels=abs(boundary['dx'])<=3 and abs(boundary['dy'])<=3,
                            criterion='bounded_unambiguous_same_frame_match_and_unchanged_vendor_counter',
                            reference_source=advance_reference,verification_source=end_source)
                    except ValueError as match_error:
                        boundary={'verified':False,'reason':str(match_error)}
                    session['end_boundary_verification']=boundary
                    if not boundary['verified']:
                        raise ScannerError('The final frame position could not be verified after the failed advance; captures preserved, no return/eject attempted')
                    optical_position_confirmed('fresh_same_frame_match_and_unchanged_counter_after_refused_advance')
                    transport_state(session).update(position_known=True,pending_action=None,pending_target=None)
                    session['count'] = session['completed']
                    session['end_of_roll_unconfirmed'] = True
                    session['end_of_roll_note'] = (f"The scanner could not advance beyond preview frame {session['completed']}. "
                                                   'The captured previews are kept; check the last frame to confirm the film ended here.')
                    expected=session.get('expected_frames')
                    matched=expected is not None and expected==session['completed']
                    session['stop_reason']='EXPECTED_COUNT_REACHED_AFTER_REFUSED_ADVANCE' if matched else 'STOPPED_AT_REFUSED_ADVANCE'
                    session['expected_frame_count_matched']=matched
                    if matched:
                        session['end_of_roll_unconfirmed']=False
                        session['end_of_roll_note']='Further advance was refused at the expected frame count. '
                        await finish_previews()
                    else:
                        session['warning_code']='WARNING_EARLY_ADVANCE_REFUSED' if expected and session['completed']<expected else 'STOPPED_AT_REFUSED_ADVANCE'
                        session['awaiting_end_confirmation']=True
                        session['roll_preview_complete']=True
                        if scan_after:session['purpose']='scan_all'
                        note=f"Stopped after {session['completed']} frames because the scanner could not advance. "
                        if expected:note+=f"Expected {expected} frames. "
                        note+='Saved images are preserved. Confirm the end or retry the advance; no return or eject was attempted.'
                        session['end_of_roll_note']=note
                        await update_session(state='complete',driver_status=note,finished_at=int(time.time()*1000))
                    return False
                raise
            return True

        try:
            await bridge.configure(border_options)
            limit = bridge.max_count if session['preview_scope'] == 'all' else 1
            start_index=session.get('completed',0) if resume else 0
            if resume and not await advance_from(start_index-1):return
            for frame_index in range(start_index,limit):
                if session.get('cancel_requested') or bridge.cancel_requested:
                    await update_session(state='cancelled', error='Roll preview cancelled; completed previews remain available.',
                                         count=frame_index, completed=frame_index, finished_at=int(time.time() * 1000))
                    return
                preview = await one_frame_preview()
                if scan_after:
                    await acquire_planned_frame(session, frame_index + 1, preview=preview)
                transport_state(session)['current_preview_index'] = frame_index + 1
                session['completed'] = frame_index + 1
                await update_session(state='saving', count=limit, completed=frame_index + 1, frame=frame_index + 1,
                                     driver_status=f"Previewed frame {frame_index + 1}")
                if session['preview_scope'] == 'one' or frame_index + 1 >= limit:
                    break
                if not await advance_from(frame_index):return
            await finish_previews()
        except ScannerError as exc:
            await update_session(state='cancelled' if session.get('cancel_requested') else 'error',
                                 error=str(exc), finished_at=int(time.time() * 1000))
        except Exception as exc:
            await update_session(state='error', error=f'Unexpected roll-preview failure: {exc}',
                                 finished_at=int(time.time() * 1000))

    @app.get('/api/cyberview/status')
    async def get_status():
        return await asyncio.to_thread(status)

    @app.post('/api/cyberview/refused-advance')
    async def resolve_refused_advance(body:RefusedAdvanceRequest):
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409,'Finish the current scanner operation first')
            session=runtime.get('session')
            if (not session or session['id']!=body.session_id or not session.get('awaiting_end_confirmation') or
                    not bridge.open or session.get('position_generation')!=runtime['position_generation']):
                raise HTTPException(409,'This stopped scan no longer has a current verified film position')
            require_known_position()
            if not (session.get('end_boundary_verification') or {}).get('verified'):
                raise HTTPException(409,'The stopped frame position was not optically verified')
            if body.action=='retry_advance' and session['completed']>=bridge.max_count:
                raise HTTPException(409,'The scan reached its supported frame limit')
            if body.action!='abort':
                boundary=session['end_boundary_verification']
                reference=boundary.get('verification_source')
                try:
                    if not reference:raise ScannerError('Saved stopped-frame reference is missing')
                    arrival=await take_local(session,f"cyberview/{session['id']}/stopped-arrival-{uuid.uuid4().hex[:8]}.tif",300,
                        'Rechecking the stopped frame before continuing')
                    match=await asyncio.to_thread(acquisition_plan.register_preview,
                        to_float(read_original(store.path(reference['path']))),to_float(read_original(store.path(arrival['path']))))
                    counter=getattr(bridge,'last_frame_position',None)
                    match.update(verified=bool(match['verified'] and counter is not None and counter==boundary.get('vendor_counter_after')),
                        vendor_counter=counter,reference_source=reference,verification_source=arrival)
                    session['stopped_position_recheck']=match
                    if not match['verified']:raise ScannerError('Stopped-frame counter changed')
                except (ScannerError,ValueError) as exc:
                    if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'stopped_frame_recheck_failed')
                    transport_state(session)['position_known']=False
                    session.update(awaiting_end_confirmation=False,stop_reason='STOPPED_POSITION_RECHECK_FAILED')
                    await update_session(state='error',error=f'POSITION_UNCERTAIN: stopped-frame verification failed: {exc}',
                        driver_status='No return, eject or further advance was attempted.',finished_at=int(time.time()*1000))
                    raise HTTPException(409,session['error']) from exc
            session['awaiting_end_confirmation']=False
            session.setdefault('refused_advance_history',[]).append({
                'completed':session['completed'],'action':body.action,
                'verification':session['end_boundary_verification'],'at':int(time.time()*1000)})
            session.pop('warning_code',None)
            if body.action=='abort':
                session.update(stop_reason='USER_STOPPED_AT_REFUSED_ADVANCE',end_of_roll_unconfirmed=True,
                    end_of_roll_note='Stopped by user; completed images preserved and film held at the checked frame.')
                await update_session(state='cancelled',driver_status=session['end_of_roll_note'],finished_at=int(time.time()*1000))
            elif body.action=='retry_advance':
                session['roll_preview_complete']=False
                session['end_of_roll_unconfirmed']=True
                await update_session(state='starting',driver_status='Retrying the refused frame advance',finished_at=None)
                runtime['task']=asyncio.create_task(run_roll_preview(session,session.get('preview_dpi',300),
                    workspace.border_preview_options(scan_options),scan_after=session.get('preview_scope_all_scan',False),resume=True))
            else:
                session.update(end_of_roll_unconfirmed=False,user_confirmed_end=True,
                    stop_reason='USER_CONFIRMED_END_AFTER_REFUSED_ADVANCE',end_of_roll_note='End of strip confirmed by user. ')
                async def finish_confirmed():
                    try:
                        if session.get('preview_scope_all_scan'):await finish_batch(session)
                        else:await update_session(state='complete',driver_status='End of strip confirmed; previews preserved.',finished_at=int(time.time()*1000))
                    except Exception as exc:
                        await update_session(state='error',error=str(exc),finished_at=int(time.time()*1000))
                await update_session(state='saving',driver_status='Finishing the confirmed end of strip')
                runtime['task']=asyncio.create_task(finish_confirmed())
            return session

    def workspace_view():
        prescans = [c for c in captures() if c.get('purpose') == 'prescan']
        return {'settings': scan_options, 'capabilities': workspace.capabilities(bridge, scan_options),
                'film_type': film_type,
                'frame_position': {'raw':getattr(bridge,'last_frame_position',None),
                    'origin_raw':runtime['frame_origin_raw'],'absolute_encoder':False},
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
        nonlocal scan_options, film_type
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Finish the current scanner operation before changing settings')
            scan_options = body.model_dump()
            film_type = selected_film_type(scan_options)
            store.save_many('cv_preferences', [
                {'id': 'workspace', 'settings': scan_options},
                {'id': 'film-type', 'film_type': film_type}])
            return workspace_view()

    @app.put('/api/cyberview/film-type')
    async def save_film_type(body: FilmTypeRequest):
        nonlocal scan_options, film_type
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Finish the current scanner operation before changing film type')
            film_type = body.film_type
            scan_options = dict(scan_options, film='positive' if film_type == 'positive' else 'negative')
            store.save_many('cv_preferences', [
                {'id': 'film-type', 'film_type': film_type},
                {'id': 'workspace', 'settings': scan_options}])
            return workspace_view()

    @app.post('/api/cyberview/film-type/auto-detect')
    async def auto_detect_film_type(body: AutoFilmTypeRequest):
        async with operation_lock:
            if bridge.kind != 'afl-native-experimental':
                raise HTTPException(409, 'Auto film detection needs the native preview path')
            if not border_capability()['available']:
                raise HTTPException(409, border_capability()['reason'])
            return await start_overlapping(StitchedScanRequest(roll=body.roll, acknowledged=True,
                                                               auto_detect_film_type=True), border_search=True)

    @app.post('/api/cyberview/prescan')
    async def prescan(body: ScanRequest):
        selected = (body.settings or ScanOptions(**scan_options)).model_dump()
        selected.update(dpi=300, bits=8, channel='rgb', focus=None,auto_exposure=False)
        async with operation_lock:
            if bridge.kind != 'afl-native-experimental':
                raise HTTPException(409, 'Choose native capture for genuine low-resolution prescan')
            return await start_locked(ScanRequest(count=1, roll=body.roll, settings=ScanOptions(**selected), purpose='prescan'))

    @app.post('/api/cyberview/preview-roll')
    async def preview_roll(body: RollPreviewRequest):
        """Make a low- or medium-resolution contact preview; these remain non-archival."""
        async with operation_lock:
            require_known_position()
            if bridge.kind != 'afl-native-experimental':
                raise HTTPException(409, 'Choose native capture for a genuine roll preview')
            if body.scope == 'all' and not bridge.supports_next:
                raise HTTPException(409, 'Whole-roll previews need the verified next-frame transport control')
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'A scan is already running')
            border_options = workspace.border_preview_options(scan_options)
            if not workspace.validated_options(border_options) or not border_capability()['available']:
                raise HTTPException(409, 'This scanner cannot run the verified full-window border search')
            if body.dpi == 300:
                preview_options = border_options
            else:
                preview_options = ScanOptions(**(scan_options | {'dpi': 600, 'bits': 16, 'channel': 'rgb','auto_exposure':False,
                                                                 'crop': scan_options['crop'], 'focus': None})).model_dump()
                if not workspace.validated_options(preview_options):
                    raise HTTPException(409, 'The 600 dpi detailed preview settings are not validated')
            if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
                raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
            try:
                await bridge.configure(border_options)
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
            count = bridge.max_count if body.scope == 'all' else 1
            session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': count, 'completed': 0,
                       'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                       'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0,
                       'rows': 0, 'height': 0, 'error': None, 'purpose': 'roll_preview',
                       'preview_scope': body.scope, 'preview_dpi': body.dpi,
                       'requested_settings': preview_options, 'film_type': selected_film_type(preview_options),
                       'until_end': body.scope == 'all', 'position_generation': runtime['position_generation'],
                       'expected_frames':body.expected_frames,
                       'driver_status': 'Starting automatic border finding', 'driver_dialog': None,
                       'cancel_requested': False}
            runtime['session'] = store.save('cv_sessions', session)
            await publish({'type': 'cyberview_session', 'session': session})
            runtime['task'] = asyncio.create_task(run_roll_preview(session, body.dpi, border_options))
            return session

    @app.post('/api/cyberview/scan-all-verified')
    async def scan_all_verified(body: StitchedScanRequest):
        """Border-check every frame at 300 dpi, then scan every frame at full quality."""
        async with operation_lock:
            require_known_position()
            validate_repeats(body.repeat_samples)
            if bridge.kind != 'afl-native-experimental' or not bridge.supports_next:
                raise HTTPException(409, 'Verified whole-roll scanning needs native frame transport')
            validate_end_action(body.end_action)
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'A scan is already running')
            border_options = workspace.border_preview_options(scan_options)
            if not workspace.validated_options(border_options) or not border_capability()['available']:
                raise HTTPException(409, 'This scanner cannot run the verified full-window border search')
            if not workspace.capabilities(bridge, scan_options)['actions']['scan']['available']:
                raise HTTPException(409, workspace.capabilities(bridge, scan_options)['actions']['scan']['reason'])
            if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
                raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
            try:
                await bridge.configure(border_options)
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
            session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': bridge.max_count, 'completed': 0,
                       'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                       'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0, 'rows': 0,
                       'height': 0, 'error': None, 'purpose': 'roll_preview', 'preview_scope': 'all',
                       'preview_dpi': 300, 'preview_scope_all_scan': True, 'requested_settings': border_options,
                       'end_action': body.end_action,'repeat_samples':body.repeat_samples,
                       'expected_frames':body.expected_frames,
                       'film_type': selected_film_type(border_options), 'until_end': True,
                       'position_generation': runtime['position_generation'], 'driver_status': 'Finding borders before whole-roll scan',
                       'driver_dialog': None, 'cancel_requested': False}
            runtime['session'] = store.save('cv_sessions', session)
            await publish({'type': 'cyberview_session', 'session': session})
            runtime['task'] = asyncio.create_task(run_roll_preview(session, 300, border_options, scan_after=True))
            return session

    @app.post('/api/cyberview/scan-favorites')
    async def scan_favorites(body: FavoriteScanRequest):
        async with operation_lock:
            require_known_position()
            validate_repeats(body.repeat_samples)
            validate_end_action(body.end_action)
            if bridge.kind != 'afl-native-experimental':
                raise HTTPException(409, 'Favorite scanning needs native frame positioning')
            try:
                preview_session = store.get('cv_sessions', body.preview_session_id)
            except KeyError:
                preview_session = None
            if (not preview_session or not preview_session.get('roll_preview_complete') or
                    preview_session.get('state') != 'complete' or preview_session.get('awaiting_end_confirmation') or
                    preview_session.get('roll', '') != body.roll.strip()):
                raise HTTPException(409, 'Run a complete border-checked preview for this roll before scanning favorites')
            if preview_session.get('position_generation') != runtime['position_generation']:
                raise HTTPException(409, 'The film moved after the roll preview. Run Preview roll again before scanning favorites.')
            if not bridge.open or runtime.get('session', {}).get('id') != preview_session['id']:
                raise HTTPException(409, 'The scanner position changed after the preview. Run Preview roll again before scanning favorites.')
            available = {item['id']: item for item in captures()
                         if item.get('session_id') == body.preview_session_id and item.get('purpose') == 'roll_preview'
                         and item.get('roll', '') == body.roll.strip()}
            if len(set(body.preview_ids)) != len(body.preview_ids) or any(item_id not in available for item_id in body.preview_ids):
                raise HTTPException(422, 'Favorite selections must belong to this roll preview')
            previews = sorted([available[item_id] for item_id in body.preview_ids], key=lambda item: item['index'])
            if not previews:
                raise HTTPException(409, 'Star one or more preview frames first')
            start_index=(preview_session.get('transport') or {}).get('current_preview_index',preview_session['completed'])
            if previews[0]['index']<start_index and 'previous' not in workspace.validation().get('actions', []):
                raise HTTPException(409, 'The verified backward frame-position control is unavailable')
            selected = workspace.full_frame_scan_options(scan_options)
            if not workspace.validated_options(selected):
                raise HTTPException(409, 'The full-window 1800 dpi scan settings are not validated')
            session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': len(previews), 'completed': 0,
                       'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                       'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0, 'rows': 0,
                       'height': 0, 'error': None, 'purpose': 'favorites_scan', 'preview_session_id': body.preview_session_id,
                       'end_action': body.end_action,'repeat_samples':body.repeat_samples,
                       'position_generation': runtime['position_generation'],
                       'selected_preview_ids': [item['id'] for item in previews],
                       'first_frame_reference':preview_session.get('first_frame_reference'),
                       'selected_frames': [item['index'] for item in previews], 'requested_settings': selected,
                       'transport': {'basis': 'relative_verified_frame_advance_from_roll_preview',
                                     'current_preview_index': (preview_session.get('transport') or {}).get(
                                         'current_preview_index', preview_session['completed']),
                                     'position_known': True, 'pending_action': None, 'pending_target': None},
                       'film_type': selected_film_type(selected), 'until_end': False,
                       'driver_status': None, 'driver_dialog': None, 'cancel_requested': False}
            runtime['session'] = store.save('cv_sessions', session)
            await publish({'type': 'cyberview_session', 'session': session})
            runtime['task'] = asyncio.create_task(run_favorite_scans(session, previews))
            return session

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

    @app.post('/api/cyberview/scan-frame')
    async def scan_frame(body: StitchedScanRequest):
        """Use one full-window scan only when preview borders and safety rebates fit."""
        async with operation_lock:
            preview = next((item for item in reversed(captures())
                            if item.get('border_preview') and item.get('roll', '') == body.roll.strip()), None)
            if preview is None:
                raise HTTPException(409, 'Run Auto find borders before Scan frame so full coverage can be checked.')
            try:
                preview_session = store.get('cv_sessions', preview['session_id'])
            except KeyError:
                preview_session = None
            if (not preview_session or preview_session.get('state') != 'complete' or
                    preview_session.get('position_generation') != runtime['position_generation'] or
                    runtime.get('session', {}).get('id') != preview_session['id']):
                raise HTTPException(409, 'The film position changed after border finding. Run Auto find borders again before scanning.')
            body.preview_capture_id = preview['id']
            return await start_overlapping(body, border_search=False)

    async def start_locked(body: ScanRequest):
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'A scan is already running')
        if not bridge.built():
            raise HTTPException(409, 'The CyberView bridge is not built; run services/cyberview_bridge/build.ps1')
        if body.until_end:
            body = body.model_copy(update={'count': bridge.max_count})
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
        if body.purpose != 'roll_preview':
            runtime['position_generation'] += 1
        session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': body.count, 'completed': 0,
                   'roll': body.roll.strip(), 'captures': [], 'started_at': int(time.time() * 1000),
                   'settings': bridge.acquisition_settings(), 'backend': bridge.kind, 'frame': 0, 'rows': 0, 'height': 0, 'error': None,
                   'purpose': body.purpose, 'requested_settings': selected, 'until_end': body.until_end,
                   'position_generation': runtime['position_generation'],
                   'auto_detect_film_type': body.auto_detect_film_type,
                   'film_type': selected_film_type(selected),
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
            bind_position_safety()
            integration['bridge'] = bridge
            source = SOURCE if bridge.kind == 'cyberview-twain' else NATIVE_SOURCE
            store.save('cv_preferences', {'id': 'scanner', 'backend': body.backend, 'acknowledged': body.acknowledged})
            return await asyncio.to_thread(status)

    @app.post('/api/cyberview/cancel')
    async def cancel():
        active = bool(runtime['task'] and not runtime['task'].done())
        if not bridge.busy and not active:
            raise HTTPException(409, 'No scan is running')
        if active:
            # A planned/batch session spans several bridge operations. Their cancel
            # flags reset at dispatch, so cancellation must also latch here.
            await update_session(state='cancelling', cancel_requested=True)
        if bridge.busy:
            await bridge.cancel()
        return runtime['session'] if active else {'state':'cancelling','operation':'scanner_control'}

    @app.post('/api/cyberview/film')
    async def film(body: FilmRequest):
        async with operation_lock:
            return await film_locked(body)

    @app.post('/api/cyberview/frame-origin')
    async def reset_frame_origin(body:FrameOriginRequest):
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409,'Finish the current operation before changing frame labels')
            position=getattr(bridge,'last_frame_position',None)
            if not bridge.open or not getattr(bridge,'frame_initialized',False) or position is None:
                raise HTTPException(409,'Complete a scan in this session to establish the current frame before relabeling')
            runtime['frame_origin_raw']=position
            runtime['position_generation']+=1
            optical_position_confirmed('user_reindexed_current_frame_after_fresh_scan')
            return {'frame':1,'origin_raw':position,'software_only':True,'film_moved':False,
                    'note':'Current film position is labeled frame 1. The hardware counter was not rewritten.'}

    async def film_locked(body: FilmRequest):
        """Moves the film with CyberView's own transport commands."""
        capability = workspace.capabilities(bridge, scan_options)['actions'][body.action]
        if not capability['available']:
            raise HTTPException(409, capability['reason'])
        if body.action != 'next' and not body.acknowledged:
            raise HTTPException(422, 'Confirm the requested film movement')
        if body.action == 'goto' and body.frame is None:
            raise HTTPException(422, 'Choose a destination frame')
        target_frame=body.frame
        if body.action=='goto':
            target_frame=body.frame+runtime['frame_origin_raw']-1
            if target_frame>40:
                raise HTTPException(422,'The requested label is outside the remaining hardware frame range')
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'Wait for the scan to finish')
        if not bridge.open and await asyncio.to_thread(cyberview.vendor_running):
            raise HTTPException(409, 'CyberView is open. Close it so only one program uses the scanner.')
        await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'moving'})
        try:
            if bridge.kind == 'afl-native-experimental':
                await bridge.film(body.action, frame=target_frame)
            else:
                await bridge.film(body.action)
        except ScannerError as exc:
            await publish({'type': 'cyberview_film', 'action': body.action, 'state': 'error'})
            raise HTTPException(409, str(exc))
        runtime['position_generation'] += 1
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
                exposure = workspace.clamp_exposure(measured['rgb'])
                scan_options = ScanOptions(**(scan_options | {'exposure': exposure})).model_dump()
                store.save('cv_preferences', {'id': 'workspace', 'settings': scan_options})
            if body.action in ('realign','focus','autofocus','calibrate'):
                runtime['position_generation']+=1
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
        runtime['frame_origin_raw']=1
        runtime['position_generation']+=1
        return await asyncio.to_thread(status)

    @app.get('/api/cyberview/captures')
    async def list_captures():
        return {'captures': captures()}

    @app.delete('/api/cyberview/rolls')
    async def delete_cyberscan_roll(body: DeleteCyberScanRollRequest):
        async with operation_lock:
            if bridge.busy or (runtime['task'] and not runtime['task'].done()):
                raise HTTPException(409, 'Stop the active scanner session before deleting this roll')
            selected_captures = [item for item in captures() if item.get('roll', '') == body.roll]
            selected_sessions = [item for item in store.all('cv_sessions') if item.get('roll', '') == body.roll]
            if not selected_captures and not selected_sessions:
                raise HTTPException(404, 'No saved scans were found for this roll')
            session_ids = {item['id'] for item in selected_sessions}
            session_ids.update(item['session_id'] for item in selected_captures if item.get('session_id'))
            cyberview_root = store.path('cyberview')
            staged_dirs = []
            try:
                for session_id in sorted(session_ids):
                    if not isinstance(session_id, str) or not re.fullmatch(r'[0-9a-f]{32}', session_id):
                        raise HTTPException(409, 'A scan session has an invalid storage identifier')
                    folder = store.path(f'cyberview/{session_id}')
                    if folder.parent != cyberview_root:
                        raise HTTPException(409, 'A scan session path is not a direct child of the scanner archive')
                    if not folder.exists():
                        continue
                    staged = cyberview_root / f'.delete-roll-{session_id}-{uuid.uuid4().hex}'
                    os.replace(folder, staged)
                    staged_dirs.append((folder, staged))
            except Exception as exc:
                for folder, staged in reversed(staged_dirs):
                    if staged.exists() and not folder.exists():
                        os.replace(staged, folder)
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(507, f'Roll files could not be staged for deletion: {exc}')

            entities = ([('cv_captures', item['id']) for item in selected_captures] +
                        [('cv_sessions', item['id']) for item in selected_sessions])
            try:
                store.delete_many(entities)
            except Exception as exc:
                for folder, staged in reversed(staged_dirs):
                    if staged.exists() and not folder.exists():
                        os.replace(staged, folder)
                raise HTTPException(500, f'Roll records could not be deleted: {exc}')
            cleanup_pending = False
            for _, staged in staged_dirs:
                try:
                    shutil.rmtree(staged)
                except OSError:
                    cleanup_pending = True
            if runtime.get('session') and runtime['session'].get('roll', '') == body.roll:
                runtime.update(session=None, task=None, live=None)
            await publish({'type': 'cyberview_roll_deleted', 'roll': body.roll,
                           'captures_deleted': len(selected_captures)})
            return {'deleted': True, 'roll': body.roll, 'captures_deleted': len(selected_captures),
                    'cleanup_pending': cleanup_pending}

    def histogram(record):
        adjust=Adjustments(**record['adjustments'])
        values = before_levels(to_float(read_original(store.path(record['original_path']))),adjust,resolve_profile(adjust.film_profile))
        bins=[np.histogram(values[...,c],bins=256,range=(0,1))[0].tolist() for c in range(3)]
        valid,guard=statistics_guard.mask(values.shape,record['dpi'],coverage(record))
        h,w=values.shape[:2];crop=adjust.crop
        valid[:int(crop.top*h)]=False;valid[round(crop.bottom*h):]=False
        valid[:,:int(crop.left*w)]=False;valid[:,round(crop.right*w):]=False
        if not valid.any():raise HTTPException(409,'No acquired picture pixels are available for automatic levels')
        guard.update(used_picture_pixels=int(valid.sum()),crop_bounds_px=[int(crop.left*w),int(crop.top*h),round(crop.right*w),round(crop.bottom*h)])
        low,high=np.percentile(values[valid],[.5,99.5])
        return {'bins':bins,'percentiles':{'black':float(low),'white':float(high)},
                'original':False,'stage':'before_levels','source_sha256':record['sha256'],'statistics_guard':guard,
                'bins_scope':'full_processed_acquisition','percentiles_scope':'acquired_picture_with_edge_guard'}

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
        if ok and not workspace.capabilities(bridge, scan_options)['actions']['scan']['available']:
            ok, reason = False, workspace.capabilities(bridge, scan_options)['actions']['scan']['reason']
        return {'available': ok, 'reason': '' if ok else reason}

    @app.get('/api/cyberview/align')
    async def get_align():
        return {'settings': align_settings, 'stitched_scan': stitch_capability(), 'frame_mm': list(frame_align.FRAME_MM),
                'find_borders': border_capability(),
                'max_window_mm': [round(2586 / 1800 * 25.4, 2), round(1708 / 1800 * 25.4, 2)]}

    def border_capability():
        if bridge.kind != 'afl-native-experimental':
            return {'available': False, 'reason': 'Choose direct capture for quick border previews.'}
        capable = stitch_capability()
        if not capable['available']:
            return capable
        if not workspace.validated_options(workspace.border_preview_options(scan_options)):
            return {'available': False, 'reason': 'Full-window previews need a supervised scanner test.'}
        return {'available': True, 'reason': ''}

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
        return {'alignment': record['alignment'], 'capture': record,
                'applied': body.apply and record['alignment']['crop_applied']}

    @app.post('/api/cyberview/stitched-scan')
    async def stitched_scan(body: StitchedScanRequest):
        """Recover frame coverage using full-resolution overlapping acquisitions."""
        async with operation_lock:
            return await start_overlapping(body)

    @app.post('/api/cyberview/find-borders')
    async def find_borders(body: StitchedScanRequest):
        """Locate borders with low-resolution full-window previews, without archival scans."""
        async with operation_lock:
            return await start_overlapping(body, border_search=True)

    async def start_overlapping(body, border_search=False):
        require_known_position()
        if not border_search:
            validate_repeats(body.repeat_samples)
        capability = border_capability() if border_search else stitch_capability()
        if not capability['available']:
            raise HTTPException(409, capability['reason'])
        if not body.acknowledged:
            raise HTTPException(422, 'Confirm that the film will be moved a little back and forward')
        if bridge.busy or (runtime['task'] and not runtime['task'].done()):
            raise HTTPException(409, 'A scan is already running')
        offset = body.offset_mm or align_settings['offset_mm']
        bleed = align_settings['bleed_mm'] if body.bleed_mm is None else body.bleed_mm
        selected = workspace.border_preview_options(scan_options) if border_search else workspace.full_frame_scan_options(scan_options)
        if hasattr(bridge, 'configure'):
            try:
                await bridge.configure(selected)
            except ScannerError as exc:
                raise HTTPException(409, str(exc))
        runtime['position_generation'] += 1
        session = {'id': uuid.uuid4().hex, 'state': 'starting', 'count': 3, 'completed': 0, 'roll': body.roll.strip(),
                   'captures': [], 'started_at': int(time.time() * 1000), 'settings': bridge.acquisition_settings(),
                   'position_generation': runtime['position_generation'],
                   'backend': bridge.kind, 'frame': 0, 'rows': 0, 'height': 0, 'error': None,
                   'purpose': 'prescan' if border_search else 'stitched', 'border_search': border_search,
                   'auto_detect_film_type': body.auto_detect_film_type,
                   'coverage_preview_id': body.preview_capture_id,
                   'repeat_samples':body.repeat_samples,
                   'border_search_state': {'probe_limit': MAX_BORDER_SEARCH_PROBES, 'probes': 0,
                                           'limit_reached': False, 'stop_reason': None} if border_search else None,
                   'film_type': selected_film_type(selected),
                   'requested_settings': selected, 'driver_status': None, 'driver_dialog': None,
                   'cancel_requested': False,
                   'stitch': {'offset_mm': offset, 'bleed_mm': bleed, 'sources': [],
                              'position': {'net_completed_steps': 0, 'position_known': True,
                                           'basis': 'acknowledged_relative_motor_steps', 'pending_move': None,
                                           'returned_to_start': False}}}
        runtime['session'] = store.save('cv_sessions', session)
        await publish({'type': 'cyberview_session', 'session': session})
        runtime['task'] = asyncio.create_task(run_stitched(session, offset, bleed))
        return session

    async def run_stitched(session, offset_mm, bleed_mm):
        nonlocal film_type, scan_options
        if not session.get('border_search') and bridge.kind == 'afl-native-experimental':
            try:
                preview = capture(session['coverage_preview_id']) if session.get('coverage_preview_id') else None
                await acquire_planned_frame(session, session.get('frame') or 1, preview=preview)
                await update_session(state='complete', completed=1, count=1, finished_at=int(time.time()*1000))
            except Exception as exc:
                await update_session(state='cancelled' if session.get('cancel_requested') else 'error',
                                     error=str(exc), finished_at=int(time.time()*1000))
            return
        folder = f"cyberview/{session['id']}"
        sources = []
        position = session['stitch']['position']

        class StitchCancelled(ScannerError):
            pass

        def check_cancel():
            if session.get('cancel_requested'):
                raise StitchCancelled('Border finding was cancelled' if session.get('border_search') else 'The stitched scan was cancelled')

        def observe_bridge_cancel():
            if bridge.cancel_requested:
                session['cancel_requested'] = True
            check_cancel()

        def position_note():
            steps = position['net_completed_steps']
            if not position['position_known']:
                return ('A film move did not finish normally, so its final position is uncertain. '
                        f'Last completed moves total {steps:+d} steps from the start. '
                        'No automatic return move was attempted; check the film before continuing.')
            if steps:
                direction = 'forward' if steps > 0 else 'back'
                return (f'The completed moves leave a relative offset of {abs(steps)} steps {direction}. '
                        'No automatic return move was attempted; check the film before continuing.')
            return ('The completed film moves balance to zero steps. '
                    'Physical return accuracy has not been remeasured.')

        def save_motion():
            # Synchronous persistence leaves no cancellation gap between recording
            # an in-flight move and dispatch. Unknown means unacknowledged motion,
            # not that the scanner provides absolute position feedback.
            store.save('cv_sessions', session)

        async def relay(event):
            if session.get('cancel_requested'):
                return
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
            check_cancel()
            path = store.path(f'{folder}/source-{label}.tif')
            initial = session.get('initial_preview') if label == 'centre' else None
            if initial:
                path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(store.path(initial['path']), path)
                images = [initial | {'synthetic': not initial.get('hardware', True)}]
            else:
                images = await bridge.scan(path, 1, relay)
            if images:
                # A finished original remains recorded even if cancellation arrived
                # immediately after the bridge completed it.
                sources.append({'label': label, 'path': f'{folder}/source-{label}.tif',
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'dpi': round(images[0]['dpi']),
                                'width': images[0]['width'], 'height': images[0]['height'], 'bits': images[0]['bits'],
                                'position_steps': position['net_completed_steps'],
                                'hardware': not images[0].get('synthetic', False)})
                session['stitch']['sources'] = list(sources)
                if session.get('border_search'):
                    session['count'] = max(session['count'], len(sources))
                if session.get('coverage_preview_id'):
                    session['count'] = max(session['count'], len(sources))
                await update_session(completed=len(sources), count=session['count'])
            observe_bridge_cancel()
            if not images:
                raise ScannerError('The scanner did not deliver the next stitched-scan source')
            return to_float(read_original(path))

        async def nudge(direction, steps):
            check_cancel()
            await update_session(state='advancing', driver_status=f'Moving the film {direction} {steps} steps')
            remaining = steps
            while remaining > 0:
                check_cancel()
                # 20-step commands only: on 2026-10-31 a 20-step nudge moved about 1.25 mm every
                # time, while 31-37 step commands moved about 3.8 mm (a coarser step mode).
                chunk = min(remaining, NUDGE_CHUNK)
                was_known = position['position_known']
                position.update(position_known=False, returned_to_start=False,
                                pending_move={'direction': direction, 'steps': chunk})
                save_motion()
                await bridge.control('nudge', value=f'{direction} {chunk}')
                if bridge.cancel_requested:
                    if isinstance(bridge,NativeAflBridge):bridge.set_position_uncertain(True,'cancelled_before_border_move_accounting')
                    session['cancel_requested'] = True
                    check_cancel()   # do not claim an interrupted move completed
                position['net_completed_steps'] += chunk if direction == 'forward' else -chunk
                position.update(position_known=was_known, pending_move=None)
                save_motion()
                remaining -= chunk
                check_cancel()

        def measured_shift(reference, moved, dpi, guess_px):
            luma = frame_align.LUMA
            dy, dx, strength = frame_align.phase_shift(reference[..., :3] @ luma, moved[..., :3] @ luma, (0, guess_px),
                                                       frame_align.mm_to_px(4, dpi))
            return dx, strength

        scan_images = {}
        scan_offsets = {}
        scan_steps = {}

        def compose_scans():
            labels = list(scan_images)
            images = [scan_images[label] for label in labels]
            offsets = [scan_offsets[label] for label in labels]
            if len(images) == 1:
                return frame_align.stitch(images, offsets, reference=0)
            if labels[:3] == ['centre', 'back', 'forward'] and len(images) == 3:
                # Keep offsets in the same order as the persisted source records.
                return frame_align.stitch(images, offsets, reference=0,
                                          search_px=frame_align.mm_to_px(1.5, dpi))
            radius_mm = max(4.0, max(abs(value) for value in offsets) * frame_align.MM_PER_INCH / dpi + 2.0)
            return frame_align.stitch(images, offsets, reference=labels.index('centre'),
                                      search_px=frame_align.mm_to_px(radius_mm, dpi))

        try:
            centre = await take('centre')
            dpi = sources[0]['dpi']
            scan_images['centre'] = centre
            scan_offsets['centre'] = 0.0
            scan_steps['centre'] = position['net_completed_steps']
            single_preview = False
            if session.get('border_search'):
                detected = await asyncio.to_thread(frame_align.align_35mm, centre, dpi,
                                                   bridge.image_kind == 'vendor-calibrated-transmission')
                check_cancel()
                minimum = acquisition_plan.REBATE_MM + acquisition_plan.CROSS_RESOLUTION_PAD_PX['x']/1800*25.4
                single_preview = bool(detected['confidence'] == 'frame_found' and
                                      frame_align.rebate_witness(detected,centre.shape[1],dpi,minimum)['verified'])
            if single_preview:
                await update_session(count=1)
            else:
                # Only look outside the first preview when a side border is missing.
                # Each 20-step chunk is already verified; image registration measures
                # its actual displacement instead of trusting motor pitch.
                await nudge('back', NUDGE_CHUNK)
                back = await take('back')
                scan_images['back'] = back
                scan_steps['back'] = position['net_completed_steps']
                dx_back, strength = await asyncio.to_thread(measured_shift, centre, back, dpi, 0)
                scan_offsets['back'] = dx_back
                check_cancel()
                moved_mm = abs(dx_back) / dpi * frame_align.MM_PER_INCH
                if moved_mm < .05 or strength < .05:
                    raise ScannerError('The film did not move measurably during the nudge; capture was stopped.')
                measured_spm = NUDGE_CHUNK / moved_mm
                if 8 <= measured_spm <= 30:
                    align_settings['steps_per_mm'] = round(measured_spm, 3)
                    store.save('cv_preferences', {'id': 'align', **align_settings})
                await nudge('forward', 2 * NUDGE_CHUNK)
                fwd = await take('forward')
                scan_images['forward'] = fwd
                scan_steps['forward'] = position['net_completed_steps']
                forward_px, forward_strength = await asyncio.to_thread(measured_shift, centre, fwd, dpi, -dx_back)
                if np.sign(forward_px) == np.sign(dx_back):
                    raise ScannerError('The film moved the wrong way for the forward preview; the border search stopped.')
                if not np.isfinite(forward_strength) or forward_strength < .05:
                    raise ScannerError('The forward preview could not be registered reliably; the border search stopped.')
                scan_offsets['forward'] = forward_px
                # Restore acknowledged steps only on normal success. Physical return
                # accuracy remains unmeasured; never move again after an uncertain failure.
                remaining_steps = position['net_completed_steps']
                if remaining_steps:
                    await nudge('back' if remaining_steps > 0 else 'forward', abs(remaining_steps))
            if session.get('border_search') and not single_preview:
                mosaic = await asyncio.to_thread(compose_scans)
                alignment = await asyncio.to_thread(frame_align.align_35mm, mosaic['image'], dpi,
                                                    bridge.image_kind == 'vendor-calibrated-transmission',
                                                    0, mosaic['covered'])
                search = session['border_search_state']
                minimum = acquisition_plan.REBATE_MM + acquisition_plan.CROSS_RESOLUTION_PAD_PX['x']/1800*25.4
                witness = frame_align.rebate_witness(alignment,mosaic['image'].shape[1],dpi,minimum)
                def feasible_preview_plan():
                    try:
                        plan=acquisition_plan.plan_archival({'dpi':dpi,
                            'width':mosaic['image'].shape[1],'height':mosaic['image'].shape[0],
                            'alignment':{'edges_x':alignment['x'],'edges_y':alignment['y']},
                            'derived':{'sources':sources,'offsets_px':mosaic['offsets_px'],
                                       'final_position_steps':position['net_completed_steps']}})
                        return plan,None
                    except ValueError as exc:
                        return None,str(exc)
                preview_plan,planning_error=feasible_preview_plan()
                while (not witness['verified'] or preview_plan is None) and search['probes'] < MAX_BORDER_SEARCH_PROBES:
                    # A right/end border with the left/start edge missing needs a
                    # backward move to bring more left-side image content into view.
                    # The converse applies when only the left/start border is known.
                    found=alignment['x']['found']
                    if found=='both':
                        # The ceil-rounded mosaic canvas can be wider than the
                        # measured source footprints by almost one preview pixel.
                        # Plan against the real windows before ending the search.
                        padding=acquisition_plan.preview_padding(dpi)['x']
                        source_left=-min(item['dx'] for item in mosaic['offsets_px'])
                        rightmost=max(item['dx']+source_left+source['width']
                            for item,source in zip(mosaic['offsets_px'],sources))
                        direction='back' if alignment['x']['start']-padding<0 else 'forward'
                        search['planning_right_margin_px']=rightmost-alignment['x']['end']
                    elif found=='none':
                        direction='back' if search['probes']%2==0 else 'forward'
                    else:
                        direction='back' if found=='end' else 'forward'
                    search['last_direction'] = direction
                    target=(min(scan_steps.values())-NUDGE_CHUNK if direction=='back' else max(scan_steps.values())+NUDGE_CHUNK)
                    delta=target-position['net_completed_steps']
                    await nudge('forward' if delta>0 else 'back',abs(delta))
                    label = f"border-search-{search['probes'] + 1:02d}"
                    moved = await take(label)
                    target_steps = position['net_completed_steps']
                    candidates = sorted(scan_images, key=lambda name: abs(scan_steps[name] - target_steps))
                    match = None
                    for reference_label in candidates:
                        dx, strength = await asyncio.to_thread(measured_shift, scan_images[reference_label], moved, dpi, 0)
                        if np.isfinite(dx) and np.isfinite(strength) and strength >= .05:
                            match = (reference_label, dx, strength)
                            break
                    if match is None:
                        raise ScannerError('The extra border preview could not be registered reliably; the search stopped without another move.')
                    reference_label, dx, strength = match
                    scan_images[label] = moved
                    scan_offsets[label] = scan_offsets[reference_label] + dx
                    scan_steps[label] = target_steps
                    search['probes'] += 1
                    await update_session(count=session['count'], driver_status=f"Checking the missing {('left' if alignment['x']['found'] == 'end' else 'right')} border · {search['probes']}/{MAX_BORDER_SEARCH_PROBES}")
                    mosaic = await asyncio.to_thread(compose_scans)
                    alignment = await asyncio.to_thread(frame_align.align_35mm, mosaic['image'], dpi,
                                                        bridge.image_kind == 'vendor-calibrated-transmission',
                                                        0, mosaic['covered'])
                    witness = frame_align.rebate_witness(alignment,mosaic['image'].shape[1],dpi,minimum)
                    preview_plan,planning_error=feasible_preview_plan()
                    if witness['verified'] and preview_plan is not None:
                        search['stop_reason'] = 'padded_rebates_and_tile_plan_verified'
                        break
                search['tile_plan_feasible']=preview_plan is not None
                search['planning_error']=planning_error
                if witness['verified'] and preview_plan is not None:
                    search['stop_reason'] = 'padded_rebates_and_tile_plan_verified'
                elif search['probes'] >= MAX_BORDER_SEARCH_PROBES:
                    search['limit_reached'] = True
                    search['stop_reason'] = 'probe_limit_reached'
                elif search['stop_reason'] is None:
                    search['stop_reason'] = 'no_reliable_border'
                session['border_search_state'] = search
                store.save('cv_sessions', session)
            if session.get('border_search') and position['position_known'] and position['net_completed_steps']:
                remaining=position['net_completed_steps']
                await nudge('back' if remaining>0 else 'forward',abs(remaining))
            archive_recovery = None
            if not session.get('border_search') and session.get('coverage_preview_id'):
                preview_record = capture(session['coverage_preview_id'])
                preview_edges = (preview_record.get('alignment') or {}).get('edges_x') or {'found': 'none'}
                preview_sources = (preview_record.get('derived') or {}).get('sources') or []
                preview_offsets = (preview_record.get('derived') or {}).get('offsets_px') or []
                preview_final_steps = (preview_record.get('derived') or {}).get('final_position_steps', 0)

                def preview_guided_direction():
                    if preview_edges.get('found') == 'end':
                        return 'back'
                    if preview_edges.get('found') == 'start':
                        return 'forward'
                    positions = []
                    for idx, src in enumerate(preview_sources[:len(preview_offsets)]):
                        positions.append((abs(src.get('position_steps', 0) - preview_final_steps), idx, src))
                    if positions and preview_record.get('width'):
                        _, idx, src = min(positions)
                        x_offsets = [item.get('dx', 0) for item in preview_offsets]
                        origin = -min(x_offsets)
                        window_center = x_offsets[idx] + origin + src.get('width', preview_record['width']) / 2
                        bounds = preview_edges
                        if bounds.get('found') == 'both':
                            frame_center = (bounds.get('start', 0) + bounds.get('end', 0)) / 2
                        else:
                            crop = (preview_record.get('alignment') or {}).get('crop_px') or {}
                            frame_center = crop.get('left', 0) + crop.get('width', preview_record['width']) / 2
                        return 'back' if frame_center < window_center else 'forward'
                    return None

                mosaic = await asyncio.to_thread(compose_scans)
                alignment = await asyncio.to_thread(frame_align.align_35mm, mosaic['image'], dpi,
                                                    bridge.image_kind == 'vendor-calibrated-transmission',
                                                    0, mosaic['covered'])
                guide = preview_guided_direction()
                archive_recovery = {'probe_limit': MAX_ARCHIVE_RECOVERY_PROBES, 'probes': 0,
                                    'stop_reason': None, 'preview_capture_id': preview_record['id']}
                witness = frame_align.rebate_witness(alignment, mosaic['image'].shape[1], dpi)
                for probe in range(MAX_ARCHIVE_RECOVERY_PROBES):
                    if witness['verified']:
                        archive_recovery['stop_reason'] = 'full_coverage_verified'
                        break
                    if alignment['x']['found'] == 'end':
                        direction = 'back'
                    elif alignment['x']['found'] == 'start':
                        direction = 'forward'
                    elif witness.get('left_margin_mm') is not None and witness['left_margin_mm'] < witness['minimum_mm']:
                        direction = 'forward'
                    elif witness.get('right_margin_mm') is not None and witness['right_margin_mm'] < witness['minimum_mm']:
                        direction = 'back'
                    elif guide:
                        direction = guide if probe == 0 else ('forward' if guide == 'back' else 'back')
                    else:
                        direction = 'back' if probe % 2 == 0 else 'forward'
                    archive_recovery['last_direction'] = direction
                    await nudge(direction, NUDGE_CHUNK)
                    label = f"archive-recovery-{probe + 1:02d}"
                    moved = await take(label)
                    target_steps = position['net_completed_steps']
                    candidates = sorted(scan_images, key=lambda name: abs(scan_steps[name] - target_steps))
                    match = None
                    for reference_label in candidates:
                        dx, strength = await asyncio.to_thread(measured_shift, scan_images[reference_label], moved, dpi, 0)
                        if np.isfinite(dx) and np.isfinite(strength) and strength >= .05:
                            match = (reference_label, dx)
                            break
                    if match is None:
                        archive_recovery['stop_reason'] = 'registration_failed'
                        break
                    reference_label, dx = match
                    scan_images[label] = moved
                    scan_offsets[label] = scan_offsets[reference_label] + dx
                    scan_steps[label] = target_steps
                    archive_recovery['probes'] += 1
                    mosaic = await asyncio.to_thread(compose_scans)
                    alignment = await asyncio.to_thread(frame_align.align_35mm, mosaic['image'], dpi,
                                                        bridge.image_kind == 'vendor-calibrated-transmission',
                                                        0, mosaic['covered'])
                    witness = frame_align.rebate_witness(alignment, mosaic['image'].shape[1], dpi)
                    if witness['verified']:
                        archive_recovery['stop_reason'] = 'full_coverage_verified'
                        break
                    guide = None
                if archive_recovery['stop_reason'] is None:
                    archive_recovery['stop_reason'] = 'coverage_unverified_probe_limit'
                archive_recovery['coverage_verification'] = witness
                session['archive_recovery'] = archive_recovery
                store.save('cv_sessions', session)
            check_cancel()
            position['returned_to_start'] = position['position_known'] and position['net_completed_steps'] == 0
            position['note'] = position_note()
            await update_session(state='saving', driver_status='Finding frame borders' if session.get('border_search') else 'Recovering frame coverage')

            def build():
                check_cancel()
                stitched = compose_scans()
                check_cancel()
                if any(not np.isfinite(value) or value < .05 for value in stitched['match_strength']):
                    raise ScannerError('The overlapping scans could not be matched reliably; no stitched image was published.')
                image = stitched['image']
                border_search = session.get('border_search', False)
                output_bits = max(item['bits'] for item in sources) if border_search else 16
                capture_id = uuid.uuid4().hex
                base = f"{folder}/{'border-preview' if border_search else 'stitched'}-{capture_id[:8]}"
                stream = BytesIO()
                tifffile.imwrite(stream, (np.clip(image, 0, 1) * (2 ** output_bits - 1) + .5).astype(np.uint8 if output_bits == 8 else np.uint16), photometric='rgb',
                                 resolution=(dpi, dpi), resolutionunit='INCH', software='FRAME stitch')
                atomic_write(store.path(base + '.tif'), stream.getvalue())
                cover = BytesIO(); Image.fromarray((stitched['covered'] * 255).astype(np.uint8)).save(cover, 'PNG')
                atomic_write(store.path(base + '-coverage.png'), cover.getvalue())
                atomic_write(store.path(base + '-preview.jpg'), jpeg(image, PREVIEW_EDGE))
                atomic_write(store.path(base + '-thumb.jpg'), jpeg(image, THUMB_EDGE))
                h, w = image.shape[:2]
                record = {'id': capture_id, 'session_id': session['id'], 'index': 1, 'roll': session['roll'],
                          'title': f"{session['roll'] or 'Roll'} · {'border preview' if border_search else 'stitched'}", 'created_at': int(time.time() * 1000),
                          'original_path': base + '.tif', 'preview_path': base + '-preview.jpg', 'thumb_path': base + '-thumb.jpg',
                          'coverage_path': base + '-coverage.png',
                          'sha256': hashlib.sha256(store.path(base + '.tif').read_bytes()).hexdigest(),
                          'width': w, 'height': h, 'bits': output_bits, 'dpi': dpi, 'source': source,
                          'hardware': all(item['hardware'] for item in sources), 'favorite': False,
                          'backend': bridge.kind, 'image_kind': bridge.image_kind, 'effective_bits': None,
                          'purpose': 'prescan' if border_search else 'stitched', 'border_preview': border_search,
                          'film_type': session.get('film_type', 'color_negative'),
                          'derived': {'kind': 'border-preview' if border_search else 'stitched', 'sources': sources, 'offsets_px': stitched['offsets_px'],
                                      'gains': stitched['gains'], 'match_strength': stitched['match_strength'],
                                      'steps_per_mm': align_settings['steps_per_mm'],
                                      'note': f"Built from {len(sources)} source scan(s) kept next to it; those are the originals.",
                                      'border_search': session.get('border_search_state'),
                                      'archive_recovery': archive_recovery,
                                      'final_position_steps': position['net_completed_steps']},
                          'requested_settings': session.get('requested_settings'), 'cyberview': session['settings'],
                          'adjustments': Adjustments(saturation=-100 if session.get('film_type') == 'bw_negative' else 0,
                                                     invert=bridge.image_kind == 'vendor-calibrated-transmission' and
                                                     session.get('requested_settings', {}).get('film', 'negative') == 'negative').model_dump()}
                initial_adjustments(record, image, stitched['covered'])
                alignment = align_record(record, image, bleed_mm, stitched['covered'], apply_crop=not border_search)
                # Multiple previews mean the initial window missed a border, and
                # balancing motor steps alone does not re-verify its final position.
                # For a single preview compare the detected edges with the selected
                # archival crop, which can be narrower than the full preview window.
                witness = frame_align.rebate_witness(alignment, w, dpi)
                window_mm = 2586 / 1800 * frame_align.MM_PER_INCH
                measured_mm = alignment['x'].get('measured_mm')
                fits_one_window = measured_mm is not None and measured_mm + 2 * witness['minimum_mm'] <= window_mm
                single_pass_eligible = bool(witness['verified'] and fits_one_window)
                if border_search:
                    try:
                        preview_plan = acquisition_plan.plan_archival(record)
                        record['derived']['acquisition_plan'] = preview_plan
                        single_pass_eligible = len(preview_plan['tiles']) == 1
                    except ValueError as exc:
                        record['derived']['planning_error'] = str(exc)
                        single_pass_eligible = False
                record['derived']['single_pass_eligible'] = single_pass_eligible
                record['derived']['requires_wider_capture'] = bool(border_search and not single_pass_eligible)
                record['derived']['rebate_witness'] = witness
                if session.get('coverage_preview_id'):
                    record['derived']['border_preview_capture_id'] = session['coverage_preview_id']
                    record['derived']['archive_recovery'] = archive_recovery
                    record['coverage_verification'] = witness
                if border_search and (session.get('border_search_state') or {}).get('limit_reached'):
                    record['alignment']['note'] = (f"The missing {('left' if alignment['x']['found'] == 'end' else 'right')} border was not found after "
                                                   f"{MAX_BORDER_SEARCH_PROBES} additional previews. The available source scans are preserved; "
                                                   'reposition the film or retry border finding.')
                check_cancel()
                if not session.get('auto_detect_film_type'):
                    atomic_write(store.path(base + '.json'), json.dumps(record, indent=1).encode())
                return record

            record = await asyncio.to_thread(build)
            check_cancel()
            store.save('cv_captures', record)
            session['captures'].append(record['id'])
            if session.get('auto_detect_film_type'):
                def detect_saved_preview():
                    samples = to_float(read_original(store.path(record['original_path'])))
                    return film_type_detection.detect(samples, record['dpi'],
                                                      transmission=record.get('image_kind') == 'vendor-calibrated-transmission',
                                                      exposure=(record.get('requested_settings') or {}).get('exposure'))
                detection = await asyncio.to_thread(detect_saved_preview)
                detection['previous_type'] = film_type
                detection['applied'] = detection.get('confidence', 0) >= AUTO_FILM_TYPE_MIN_CONFIDENCE
                if detection['applied']:
                    film_type = detection['film_type']
                    scan_options = ScanOptions(**(scan_options | {'film': 'positive' if film_type == 'positive' else 'negative'})).model_dump()
                    store.save_many('cv_preferences', [
                        {'id': 'film-type', 'film_type': film_type},
                        {'id': 'workspace', 'settings': scan_options}])
                    session['film_type'] = film_type
                    record['film_type'] = film_type
                    record['adjustments']['saturation'] = -100 if film_type == 'bw_negative' else 0
                    record['adjustments']['invert'] = (record.get('image_kind') == 'vendor-calibrated-transmission' and
                                                       film_type != 'positive')
                    initial_adjustments(record, to_float(read_original(store.path(record['original_path']))))
                else:
                    detection['note'] += ' The current manual selection was kept.'
                record['film_type_detection'] = detection
                session['film_type_detection'] = detection
                atomic_write(store.path(record['original_path']).with_suffix('.json'), json.dumps(record, indent=1).encode())
                store.save('cv_captures', record)
            check_cancel()
            await publish({'type': 'cyberview_capture', 'capture': record})
            check_cancel()
            if not session.get('border_search', False) and (record['alignment']['confidence'] != 'frame_found' or
                                      not record['alignment']['exact'] or not record['alignment']['crop_applied'] or
                                      (session.get('coverage_preview_id') and not record.get('coverage_verification', {}).get('verified'))):
                reason = record['alignment'].get('note') or record.get('coverage_verification', {}).get('reason') or 'Both side borders and complete coverage could not be verified.'
                await update_session(state='error', error=f'{reason} The stitched original is preserved, but it is not marked as a complete frame.',
                                     finished_at=int(time.time() * 1000))
                return
            await update_session(state='complete', finished_at=int(time.time() * 1000), alignment=record['alignment'])
        except StitchCancelled as exc:
            position['note'] = position_note()
            await update_session(state='cancelled', error=f'{exc}. {position["note"]}',
                                 driver_status=position['note'], finished_at=int(time.time() * 1000))
        except ScannerError as exc:
            position['note'] = position_note()
            await update_session(state='cancelled' if session.get('cancel_requested') else 'error',
                                 error=f'{exc}. {position["note"]}', driver_status=position['note'],
                                 finished_at=int(time.time() * 1000))
        except asyncio.CancelledError:
            session['cancel_requested'] = True
            position['note'] = position_note()
            await update_session(state='cancelled', error='The stitched task stopped. ' + position['note'],
                                 driver_status=position['note'], finished_at=int(time.time() * 1000))
            raise
        except Exception as exc:  # recorded, never reported as success
            position['note'] = position_note()
            await update_session(state='error', error=f'Unexpected failure: {exc}. {position["note"]}',
                                 driver_status=position['note'], finished_at=int(time.time() * 1000))

    @app.post('/api/cyberview/captures/{capture_id}/balance-negative')
    async def balance_negative(capture_id: str):
        """Suggest a conversion for a saved transmission; no acquisition or exposure change."""
        record = capture(capture_id)
        if record.get('image_kind') != 'vendor-calibrated-transmission' or (record.get('requested_settings') or {}).get('film', 'negative') != 'negative':
            raise HTTPException(409, 'Balance negative needs an original negative transmission scan')
        def calculate():
            samples = to_float(read_original(store.path(record['original_path'])))
            covered = coverage(record)
            base = negative.suggest_base(samples, covered, dpi=record['dpi'])
            if base is None:
                raise HTTPException(409, 'A film base could not be suggested from this scan; set the base manually')
            adjust = Adjustments(**(record['adjustments'] | {'invert': True, 'film_base': base,
                                  'negative_response': negative.SUGGESTED_RESPONSE, 'auto_color': None}))
            profile = resolve_profile(adjust.film_profile)
            if not profile:
                profile=vendor_negative.default_profile(store) if record.get('film_type','color_negative')=='color_negative' else None
                if profile:
                    adjust=Adjustments(**(adjust.model_dump() | {'film_profile':profile['id'],'vendor_input_balance':True,
                        'black_point':0,'white_point':1,'gamma':1,'rgb_balance':[1,1,1],
                        'curve':[0,.25,.5,.75,1],'auto_color':None}))
                else:
                    adjust=general_negative_display(record,samples,adjust,covered)
            elif profile.get('kind')=='vendor-negative':
                adjust=adjust.model_copy(update={'vendor_input_balance':True,'auto_color':None})
            else:
                positive = before_levels(samples, adjust, profile)
                adjust.auto_color = None if profile.get('kind') in ('reference-tone', 'vendor-negative') else auto_color_for(positive, covered, dpi=record['dpi'])
            return adjust, base
        adjust, base = await asyncio.to_thread(calculate)
        latest = capture(capture_id)
        if latest['adjustments'] != record['adjustments']:
            raise HTTPException(409, 'The edit changed while balancing; try Balance negative again')
        record = latest
        record['adjustments'] = adjust.model_dump()
        if not adjust.film_profile:
            record['display_suggestion']={'version':negative.DISPLAY_VERSION,'reference_used':False,
                'method':'endpoint_preserving_midtone_curve','automatic_endpoint_clipping':False,
                'conversion_status':'nominal_negative_response_not_measured_scanner_calibration'}
        elif adjust.vendor_input_balance:
            record['display_suggestion']={'method':'recovered_vendor_negative','reference_used':False,
                'profile_id':adjust.film_profile,'input_base_target':.85}
        record['negative_balance'] = {'version': negative.VERSION, 'method': 'brightest-0.5-percent',
                                      'suggested_base': base, 'response': negative.SUGGESTED_RESPONSE}
        return store.save('cv_captures', record)

    @app.post('/api/cyberview/captures/{capture_id}/auto-color')
    async def auto_color(capture_id: str, body: AutoColorRequest):
        """Turns CyberView's automatic colour on (computed from this frame) or off."""
        record = capture(capture_id)
        adjust = Adjustments(**(record['adjustments'] | {'auto_color': None}))
        words = None
        if body.enabled:
            def calculate():
                samples = before_levels(to_float(read_original(store.path(record['original_path']))),
                                        adjust, resolve_profile(adjust.film_profile))
                return auto_color_for(samples, coverage(record), dpi=record['dpi'])
            words = await asyncio.to_thread(calculate)
            if words is None:
                raise HTTPException(409, 'This frame has no near-neutral midtones, so automatic colour does not apply')
        latest = capture(capture_id)
        if latest['adjustments'] != record['adjustments']:
            raise HTTPException(409, 'The edit changed while computing automatic colour; try again')
        record = latest
        record['adjustments'] = adjust.model_copy(update={'auto_color': words}).model_dump()
        return store.save('cv_captures', record)

    @app.post('/api/cyberview/captures/{capture_id}/vendor-auto-tone')
    async def vendor_auto_tone(capture_id:str,body:AutoColorRequest):
        record=capture(capture_id)
        previous=record['adjustments'].copy()
        if not body.enabled:
            record['adjustments']=Adjustments(**(previous | {'vendor_auto_gamma_tables':None,'auto_color':None})).model_dump()
            record['vendor_auto_tone']={'enabled':False,'user_disabled':True}
            return store.save('cv_captures',record)
        if record.get('image_kind')!='vendor-calibrated-transmission' or record.get('film_type')=='positive':
            raise HTTPException(409,'Vendor negative auto tone requires an original negative transmission acquisition')
        if not vendor_autogamma.available():
            raise HTTPException(409,'The verified local vendor automatic-tone worker is unavailable')
        def generate():
            path=store.path(record['original_path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
                raise HTTPException(409,'The original checksum changed; automatic tone was not applied')
            neutral=Adjustments(**(previous | {'vendor_auto_gamma_tables':None,'auto_color':None,
                'color_restoration':0,'grain_reduction':0,'sharpening':0}))
            profile=resolve_profile(neutral.film_profile)
            values=before_levels(to_float(read_original(path)),neutral,profile)
            # Do not let unacquired corners/rebate drive automatic scene statistics.
            selected,statistics=vendor_autogamma.statistics_input(values,tone_picture_crop(record,neutral,values.shape[1]),coverage(record),dpi=record['dpi'])
            generated=vendor_autogamma.generate_tables(selected,negative=True,input_plane='converted_positive')
            return generated | {'statistics':statistics,'vendor_profile':bool(profile and profile.get('kind')=='vendor-negative')}
        try:
            async with vendor_tone_lock:
                generated=await asyncio.to_thread(generate)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
        latest=capture(capture_id)
        if latest['adjustments']!=previous:
            raise HTTPException(409,'The edit changed while automatic tone was being generated; try again')
        latest['adjustments']=Adjustments(**(previous | {'vendor_auto_gamma_tables':generated['tables'],
            'auto_color':None,'black_point':0,'white_point':1,'gamma':1,'rgb_balance':[1,1,1],
            'curve':[0,.25,.5,.75,1]})).model_dump()
        diagnostics=generated['diagnostics'] | vendor_autogamma.diagnostics(generated['tables'])
        latest['vendor_auto_tone']=diagnostics | {'enabled':True,'automatic':False,
            'experimental':not (diagnostics.get('caller_stage_order_verified') and generated['vendor_profile']),
            'diagnostics':diagnostics,'statistics':generated['statistics'],'source':'picture',
            'profile_id':previous.get('film_profile'),'source_capture_id':capture_id,'source_sha256':record['sha256'],
            'generation_capture_id':capture_id,'generation_source_sha256':record['sha256'],
            'reused_without_highres_recalculation':False,
            'scope':'Film conversion -> automatic tone; acquisition settings and calibration parity are separate.'}
        return store.save('cv_captures',latest)

    @app.get('/api/cyberview/captures/{capture_id}/sources/{number}/preview')
    async def source_preview(capture_id: str, number: int):
        """Preview one immutable source acquisition; concurrent cache publication is harmless."""
        record = capture(capture_id)
        sources = (record.get('derived') or {}).get('sources') or []
        if not 1 <= number <= len(sources):
            raise HTTPException(404, 'This capture has no such source scan')
        source = sources[number - 1]
        cached = store.path(source['path'].rsplit('.', 1)[0] + '-preview.jpg')
        if not cached.is_file():
            original = store.path(source['path'])
            if not original.resolve().is_relative_to(store.root):
                raise HTTPException(404, 'Source scan not found')
            data = await asyncio.to_thread(lambda: jpeg(to_float(read_original(original)), PREVIEW_EDGE))
            try:
                atomic_write(cached, data)
            except FileExistsError:
                # Another request already published this complete derived cache.
                pass
        return FileResponse(cached, media_type='image/jpeg')

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
                profile = await asyncio.to_thread(resolve_profile,body.adjustments.film_profile)
                compatible_profile(record, body.adjustments, profile)
            edits = body.adjustments.model_dump()
            if 'negative_response' not in body.adjustments.model_fields_set:
                edits['negative_response'] = record['adjustments'].get('negative_response', negative.LEGACY_RESPONSE)
            record['adjustments'] = edits | {'rotation': body.adjustments.rotation % 360}
        if body.title is not None:
            record['title'] = body.title.strip() or record['title']
        if body.favorite is not None:
            record['favorite'] = body.favorite
        return store.save('cv_captures', record)

    @app.post('/api/cyberview/captures/{capture_id}/apply-to-roll')
    async def apply_to_roll(capture_id: str, body: RollAdjustments):
        profile = None
        if body.adjustments.film_profile:
            profile = await asyncio.to_thread(resolve_profile,body.adjustments.film_profile)
        source_record=capture(capture_id)
        if body.adjustments.rotation%90:
            raise HTTPException(422,'Rotation must be a multiple of 90 degrees')
        edits=body.adjustments.model_dump(exclude={'rotation','mirror','crop'})
        if 'negative_response' not in body.adjustments.model_fields_set:
            edits.pop('negative_response', None)
        selected=[c for c in captures() if (c['roll']==source_record['roll'] if source_record['roll'] else c['session_id']==source_record['session_id'])]
        for record in selected:
            compatible_profile(record, body.adjustments, profile)
            record['adjustments']=Adjustments(**(record['adjustments']|edits)).model_dump()
        store.save_many('cv_captures',selected)
        return {'captures':selected,'count':len(selected)}

    @app.get('/api/cyberview/captures/{capture_id}/processing-preview')
    @app.get('/api/cyberview/captures/{capture_id}/profile-preview')
    async def profile_preview(capture_id: str, profile_id: str | None=None, invert: bool=False,
                              base_r: float=1,base_g: float=1,base_b: float=1,negative_response: float=negative.LEGACY_RESPONSE,
                              vendor_input_balance: bool=False,color_restoration:float=0,grain_reduction:float=0,sharpening:float=0,
                              vendor_auto_tone:bool=False):
        record=capture(capture_id)
        try:adjust=Adjustments(film_profile=profile_id,invert=invert,film_base=[base_r,base_g,base_b],negative_response=negative_response,
                              vendor_input_balance=vendor_input_balance,color_restoration=color_restoration,
                              grain_reduction=grain_reduction,sharpening=sharpening,
                              vendor_auto_gamma_tables=record['adjustments'].get('vendor_auto_gamma_tables') if vendor_auto_tone else None)
        except ValueError as exc:raise HTTPException(422,'Invalid profile preview settings') from exc
        profile = resolve_profile(profile_id)
        compatible_profile(record, adjust, profile)
        def render():
            values=before_levels(to_float(read_original(store.path(record['original_path']))),adjust,profile)
            return jpeg(values,PREVIEW_EDGE)
        return Response(await asyncio.to_thread(render),media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})

    @app.get('/api/cyberview/captures/{capture_id}/rendered/{kind}')
    async def rendered_capture(capture_id: str, kind: str):
        """Saved edit for Home/Rolls; editor source previews remain unmodified."""
        if kind not in ('preview', 'thumb'):
            raise HTTPException(404, 'Unknown rendered image size')
        record = capture(capture_id)
        recipe = json.dumps(record['adjustments'], sort_keys=True, separators=(',', ':'))
        async with preview_lock:
            await asyncio.to_thread(resolve_profile, record['adjustments'].get('film_profile'))
            info = store.path(record['original_path']).stat()
            data = await asyncio.to_thread(rendered_preview, record['original_path'], record['sha256'], recipe, kind,
                                          (info.st_mtime_ns, info.st_size))
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})

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
            profile = resolve_profile(adjust.film_profile)
            samples = apply(to_float(read_original(original)), adjust, profile)
            if fmt == 'jpeg':
                image = Image.fromarray((samples * 255 + .5).astype(np.uint8))
                return pipeline.encode(image, 'JPEG')
            stream = BytesIO()
            tifffile.imwrite(stream, (samples * 65535 + .5).astype(np.uint16), photometric='rgb',
                             resolution=(record['dpi'], record['dpi']), resolutionunit='INCH',
                             iccprofile=pipeline.SRGB, software='FRAME',
                             description=json.dumps({'engine': negative.VERSION, 'adjustments': adjust.model_dump(),
                                                     'film_profile_engine': profile.get('engine') if profile else None,
                                                     'original_sha256': record['sha256']}))
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
