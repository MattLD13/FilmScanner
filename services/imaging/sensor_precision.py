"""Honest output-code and repeat-noise measurements on original acquisitions.

These diagnostics do not equate a uint16 container, occupied low bits, scene
entropy, or an output-noise estimate with effective ADC/sensor precision.
Vendor calibration, gain, LUTs, fixed-pattern noise and registration matter.
"""
from __future__ import annotations

import math
import numpy as np

from services.imaging import acquisition_plan, scan_filters

VERSION = 'frame-output-precision-1'


def _acquisition(image):
    array = np.asarray(image)
    if array.dtype.kind != 'u' or array.dtype.itemsize not in (1, 2):
        raise ValueError('Precision measurements require original uint8/uint16 acquisition samples')
    if array.ndim == 2:
        array = array[..., None]
    if array.ndim != 3 or array.shape[2] not in (1, 3) or min(array.shape[:2]) < 2:
        raise ValueError('Precision measurements require grayscale or RGB acquisitions')
    if array.shape[0] * array.shape[1] > 32_000_000:
        raise ValueError('Maximum acquisition size is 32 megapixels')
    return array


def _provenance(provenance):
    if provenance is None:
        return {'evidence': 'unverified_input', 'sensor_evidence_eligible': False,
                'reason': 'Original-acquisition provenance was not supplied.'}
    if not isinstance(provenance, dict):
        raise ValueError('Acquisition provenance must be a JSON object')
    if (provenance.get('derived') or provenance.get('processed') or provenance.get('stitched') or provenance.get('resampled') or
            provenance.get('purpose') in ('stitched', 'rendered', 'export', 'preview') or
            provenance.get('image_kind') in ('stitched', 'rendered', 'processed')):
        raise ValueError('Processed, stitched or resampled images cannot be used as sensor-precision evidence')
    original = provenance.get('original_acquisition') is True
    hardware = provenance.get('hardware') is True and provenance.get('synthetic') is False
    return {'evidence': 'hardware_original_output' if hardware and original else
                        'synthetic' if provenance.get('synthetic') is True else 'unverified_input',
            'sensor_evidence_eligible': False,
            'reason': ('Original vendor-calibrated output can measure output codes/noise, not ADC ENOB without '
                       'known linear raw response and a controlled calibration target.'),
            'original_acquisition_declared': original,
            'hardware_declared': hardware, 'image_kind': provenance.get('image_kind'),
            'stationary_declared': provenance.get('same_position') is True}


def analyze_acquisition(image: np.ndarray, *, provenance: dict | None = None) -> dict:
    """Inspect all codes without modifying an original uint8/uint16 array."""
    array = _acquisition(image)
    source = _provenance(provenance)
    container = array.dtype.itemsize * 8
    maximum = 2 ** container - 1
    channels = []
    for channel in range(array.shape[2]):
        values = array[..., channel].reshape(-1)
        histogram = np.bincount(values, minlength=maximum + 1)
        codes = np.flatnonzero(histogram)
        differences = np.diff(codes)
        step = int(np.gcd.reduce(differences)) if len(differences) else None
        bits_or = int(np.bitwise_or.reduce(values))
        bits_and = int(np.bitwise_and.reduce(values))
        low_zeros = next((i for i in range(container) if bits_or & (1 << i)), container)
        varying = bits_or ^ bits_and
        probabilities = histogram[codes] / len(values)
        channels.append({'channel': channel, 'sample_count': int(len(values)),
            'minimum_code': int(codes[0]), 'maximum_code': int(codes[-1]),
            'observed_unique_code_count': int(len(codes)), 'observed_code_lattice_step': step,
            'aligned_low_zero_bits': low_zeros, 'varying_bit_mask': varying,
            'varying_bit_count': varying.bit_count(),
            'constant_low_bit_pattern': int(codes[0] % step) if step and step > 1 else None,
            'code_lattice_bits_ceiling': float(math.log2((maximum + 1) / step)) if step else None,
            'scene_code_entropy_bits': float(-np.sum(probabilities * np.log2(probabilities))),
            'zero_code_fraction': float(histogram[0] / len(values)),
            'full_scale_code_fraction': float(histogram[maximum] / len(values)),
            'percentile_codes': {str(p): float(np.percentile(values, p)) for p in (.1, 1, 50, 99, 99.9)}})
    return {'engine': VERSION, 'container_bits': container, 'width': int(array.shape[1]),
            'height': int(array.shape[0]), 'channels': channels, 'provenance': source,
            'effective_sensor_bits': None, 'effective_adc_bits': None,
            'limit': 'Code lattice/entropy describe this output image, not independently measured sensor precision.'}


def analyze_repeats(images: list[np.ndarray], dpi: float, *, provenance: dict | None = None) -> dict:
    """Measure temporal output noise from 2–8 original same-setting captures.

    Rich scenes require optical registration. With flat fields, callers may
    explicitly declare same_position; any motion then remains an assumption.
    Quantization-equivalent output-noise bits are labeled separately from ADC
    ENOB. Identical inputs yield unknown precision, never infinite precision.
    """
    source = _provenance(provenance)
    if not 2 <= len(images) <= 8 or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError('Repeat precision measurement needs 2–8 captures and a finite positive DPI')
    originals = [_acquisition(image) for image in images]
    if any(image.shape != originals[0].shape or image.dtype != originals[0].dtype for image in originals):
        raise ValueError('Repeat acquisitions must have identical dimensions and sample type')
    scale = float(np.iinfo(originals[0].dtype).max)
    arrays = [image.astype(np.float64) / scale for image in originals]
    height, width = arrays[0].shape[:2]
    identical = all(np.array_equal(image, originals[0]) for image in originals[1:])
    evidence = []
    aligned = [arrays[0]]
    valid = np.ones((height, width), dtype=bool)
    warnings = ['Output temporal noise includes sensor/readout/calibration/lamp behavior and residual registration; it is not ADC ENOB.']
    for image in arrays[1:]:
        if identical:
            evidence.append({'method': 'identical_arrays', 'dx': 0., 'dy': 0., 'verified': False})
            aligned.append(image)
            continue
        rgb = [np.repeat(a, 3, axis=2) if a.shape[2] == 1 else a for a in (arrays[0], image)]
        try:
            # At archival resolution this limits image displacement to ~18 px;
            # at small synthetic sizes use a proportionally bounded window.
            radius_px = min(18., min(height, width) / 5)
            match = acquisition_plan.register_preview(rgb[0], rgb[1], dpi=dpi,
                        max_shift_mm=radius_px / dpi * 25.4)
            sampled, acquired = scan_filters._sample(image, match['dy'], match['dx'])
            aligned.append(sampled)
            valid &= acquired
            evidence.append(match | {'method': 'optical_translation'})
        except ValueError as exc:
            if source.get('stationary_declared'):
                aligned.append(image)
                evidence.append({'method': 'operator_declared_same_position', 'dx': 0., 'dy': 0.,
                                 'verified': False, 'optical_failure': str(exc)})
                warnings.append('Alignment was assumed from same_position provenance; motion can inflate this estimate.')
            else:
                return {'engine': VERSION, 'source_count': len(images), 'provenance': source,
                    'effective_sensor_bits': None, 'effective_adc_bits': None,
                    'temporal_measurement_valid': False, 'reason': str(exc), 'registration': evidence,
                    'warnings': warnings}
    stack = np.stack(aligned)
    valid &= np.all((stack > 1 / scale) & (stack < 1 - 1 / scale), axis=(0, 3))
    # Exclude strong scene edges: subpixel interpolation error there is not a
    # clean temporal-noise measurement. A remaining scene estimate is still not
    # a substitute for known flat-field calibration.
    mean_image = stack.mean(axis=0)
    luma = mean_image[..., 0] if mean_image.shape[2] == 1 else mean_image @ np.array([.2126, .7152, .0722])
    gy, gx = np.gradient(luma)
    gradient = np.hypot(gy, gx)
    if np.any(valid):
        valid &= gradient <= np.percentile(gradient[valid], 35)
    count = int(valid.sum())
    if count < 64:
        return {'engine': VERSION, 'source_count': len(images), 'provenance': source,
            'effective_sensor_bits': None, 'effective_adc_bits': None,
            'temporal_measurement_valid': False, 'reason': 'Too few valid low-gradient repeat pixels',
            'registration': evidence, 'warnings': warnings}
    differences = np.diff(stack, axis=0)[:, valid, :] * scale
    result = []
    for channel in range(stack.shape[3]):
        diff = differences[..., channel].reshape(-1)
        dc = float(np.median(diff))
        sigma = float(1.4826 * np.median(np.abs(diff - dc)) / math.sqrt(2))
        rms = float(np.sqrt(np.mean(diff ** 2)) / math.sqrt(2))
        bits = min(originals[0].dtype.itemsize * 8, math.log2(scale / (math.sqrt(12) * sigma))) if sigma > 0 else None
        result.append({'channel': channel, 'robust_temporal_sigma_output_codes': sigma,
            'rms_pair_difference_over_sqrt2_output_codes': rms, 'median_pair_offset_output_codes': dc,
            'quantization_equivalent_output_noise_bits': float(bits) if bits is not None else None,
            'measurement': 'robust pair-difference sigma after optical alignment, or declared stationary assumption',
            'not_adc_enob': True})
    if identical:
        warnings.append('Inputs are byte-identical; zero temporal difference cannot establish noiseless sensing or infinite precision.')
    return {'engine': VERSION, 'source_count': len(images), 'container_bits': originals[0].dtype.itemsize * 8,
        'provenance': source, 'registration': evidence, 'evaluated_low_gradient_pixels': count,
        'temporal_measurement_valid': True, 'channels': result,
        'effective_sensor_bits': None, 'effective_adc_bits': None,
        'identical_inputs': identical, 'warnings': list(dict.fromkeys(warnings))}
