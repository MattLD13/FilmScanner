"""Validated acquisition contracts and evidence-based scanner capabilities."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EXPOSURE_MAX = 400


class ScanCrop(BaseModel):
    model_config = ConfigDict(extra='forbid')
    left: float = Field(default=.03, ge=0, lt=1.436667, allow_inf_nan=False)
    top: float = Field(default=.003, ge=0, lt=.95, allow_inf_nan=False)
    right: float = Field(default=1.407, gt=0, le=2586/1800, allow_inf_nan=False)
    bottom: float = Field(default=.95, gt=0, le=.95, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered(self):
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError('Crop must have a positive width and height')
        return self


class ScanOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dpi: Literal[300, 360, 450, 600, 900, 1800] = 1800
    bits: Literal[8, 16] = 16
    channel: Literal['rgb', 'gray', 'bw'] = 'rgb'
    film: Literal['negative', 'positive'] = 'negative'
    crop: ScanCrop = Field(default_factory=ScanCrop)
    exposure: list[int] = Field(default_factory=lambda: [100, 100, 100], min_length=3, max_length=3)
    focus: int | None = Field(default=None, ge=0, le=200)
    auto_exposure: bool = False

    @field_validator('exposure')
    @classmethod
    def exposure_bounds(cls, values):
        # CyberView sends the measured film base as exposure; blue reached 323 on 2026-10-30.
        if any(v < 50 or v > EXPOSURE_MAX for v in values):
            raise ValueError(f'Exposure must be between 50 and {EXPOSURE_MAX} percent')
        return values

    @model_validator(mode='after')
    def mode(self):
        if self.channel == 'bw' and self.bits != 8:
            raise ValueError('Binary output uses an 8-bit thresholded grayscale container')
        return self


DEFAULT_OPTIONS = ScanOptions().model_dump()
FULL_WINDOW_CROP = {'left': 0., 'top': 0., 'right': 2586 / 1800, 'bottom': .95}
VALIDATION = Path(__file__).with_name('native_validation.json')
ACTIONS = ('scan', 'prescan', 'next', 'previous', 'eject_forward', 'eject_backward', 'goto', 'autofocus', 'focus', 'calibrate', 'nudge', 'realign', 'auto_exposure')


def border_preview_options(options: dict) -> dict:
    return ScanOptions(**(options | {'dpi': 300, 'bits': 8, 'channel': 'rgb',
                                     'crop': FULL_WINDOW_CROP, 'focus': None, 'auto_exposure': False})).model_dump()


def full_frame_scan_options(options: dict) -> dict:
    """Full-resolution acquisition window used after a preview proves both rebates fit."""
    return ScanOptions(**(options | {'dpi': 1800, 'bits': 16, 'channel': 'rgb',
                                     'crop': FULL_WINDOW_CROP, 'focus': None})).model_dump()


def validation() -> dict:
    # Version-controlled, evidence-linked promotions. Arbitrary user requests
    # cannot declare an untested operation verified.
    try:
        data = json.loads(VALIDATION.read_text(encoding='utf-8'))
        return data if data.get('model_sha256') == 'da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f' else {}
    except (OSError, ValueError):
        return {}


def clamp_exposure(values) -> list[int]:
    """Keeps an automatic exposure inside what has been scanned under supervision."""
    low, high = validation().get('exposure_range', [100, 100])
    return [int(min(high, max(low, round(v)))) for v in values]


def focus_limits() -> list[int] | None:
    """Measured focus interval, or the legacy model bound when none is recorded.

    Malformed evidence must disable the operation instead of broadening it to
    the model's entire parameter interval.
    """
    values=validation().get('focus_range',[0,200])
    if (not isinstance(values,(list,tuple)) or len(values)!=2 or
            any(type(value) is not int for value in values) or
            not 0<=values[0]<=values[1]<=200):
        return None
    return list(values)


def validated_options(options: dict) -> bool:
    """A configuration is proven, or a proven one with a film-base exposure inside the
    validated ``exposure_range`` (recorded only after a supervised scan)."""
    normalized = ScanOptions(**options).model_dump()
    if normalized['auto_exposure']:
        if 'auto_exposure' not in validation().get('actions', []):
            return False
        # The command flag is validated separately from the acquisition geometry.
        normalized = normalized | {'auto_exposure': False}
        recorded_auto=validation().get('auto_exposure_configurations')
        if recorded_auto is not None:
            seeds=dict(normalized,exposure=[100,100,100])
            if seeds not in [ScanOptions(**(entry | {'auto_exposure':False})).model_dump() for entry in recorded_auto]:
                return False
    if normalized == DEFAULT_OPTIONS:
        return True
    # Older evidence predates the optional flag; omitted means false, never true.
    proven = [ScanOptions(**item).model_dump() for item in validation().get('configurations', [])]
    if normalized in proven:
        return True
    low, high = validation().get('exposure_range', [100, 100])
    if normalized['film']=='negative' and all(low <= v <= high for v in normalized['exposure']):
        neutral = dict(normalized, exposure=[100, 100, 100])
        return neutral == DEFAULT_OPTIONS or neutral in proven
    return False


def capabilities(bridge, options: dict) -> dict:
    native = bridge.kind == 'afl-native-experimental'
    proved = set(validation().get('actions', []))
    available = {'scan', 'next'} if not native else {'scan'} | proved
    if native and not validated_options(options):
        available.discard('scan')
    focus_range=focus_limits()
    if native and focus_range is None:
        available.discard('focus')
    if not native and options != DEFAULT_OPTIONS:
        available.discard('scan')
    prescan = dict(options, dpi=300, bits=8, channel='rgb', focus=None)
    if native and validated_options(prescan):
        available.add('prescan')
    result = {}
    for name in ACTIONS:
        enabled = name in available
        result[name] = {'available': enabled, 'evidence': 'verified_on_device' if enabled else 'static_only',
                        'reason': '' if enabled else ('Choose native capture for acquisition settings and prescan.' if not native else
                            'This configuration still needs a supervised scanner test.' if name == 'scan' else
                            'A supervised device test is required before this control is enabled.')}
        if native and name=='focus' and focus_range is None:
            result[name]['reason']='The recorded focus range is invalid; this control is disabled.'
        if native and name in ('next','previous','goto','realign') and enabled and not getattr(bridge,'frame_initialized',False):
            result[name]={'available':False,'evidence':'verified_on_device',
                          'reason':'Complete a prescan or scan in this session before moving film.'}
        if native and getattr(bridge,'transport_position_uncertain',False) and (
                name in ('next','previous','goto','nudge','realign','calibrate') or
                (name=='scan' and options['dpi']!=300)):
            result[name]={'available':False,'evidence':'verified_on_device',
                          'reason':'Film position needs checking. Prescan the current frame, then label the checked frame before scanning or moving again.'}
    return {'actions': result, 'resolutions': [300, 360, 450, 600, 900, 1800], 'depths': [8, 16],
            'channels': ['rgb', 'gray', 'bw'], 'films': ['negative', 'positive'],
            'focus_range':focus_range if focus_range is not None else [],
            'native': native, 'binary_output': 'Host threshold applied to acquired 8-bit grayscale',
            'settings_validation': result['scan']}
