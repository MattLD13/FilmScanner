"""Measure original acquisition output codes/repeat noise, never operate a scanner.

python scripts/measure_sensor_precision.py SOURCE.tif [REPEAT.tif ...] \
    --metadata original-acquisitions.json --dpi 1800 --output report.json

Metadata is {"acquisitions":[{"path":"SOURCE.tif","sha256":"...",
"original_acquisition":true,"hardware":true,"synthetic":false,
"image_kind":"vendor-calibrated-transmission","same_position":true,
"settings":{"dpi":1800,"exposure":[100,100,100],"lut":"identity"}}]}.
Each input must have its own entry and hash. A processed/stitched acquisition is
rejected. Stationary provenance is an explicit assumption, not measured motion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tifffile
from services.imaging import sensor_precision


def run(paths, metadata_path, dpi):
    paths = [Path(path).resolve() for path in paths]
    if not 1 <= len(paths) <= 8 or len(paths) != len(set(paths)):
        raise ValueError('Supply one to eight distinct original acquisition files')
    metadata_path = Path(metadata_path).resolve()
    manifest = json.loads(metadata_path.read_text(encoding='utf-8'))
    entries = manifest.get('acquisitions') if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or len(entries) != len(paths):
        raise ValueError('Metadata must contain one acquisition entry per input')
    by_path = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise ValueError('Each acquisition entry needs a path')
        path = Path(entry['path'])
        path = path.resolve() if path.is_absolute() else (metadata_path.parent / path).resolve()
        if path in by_path:
            raise ValueError('Metadata contains duplicate paths')
        by_path[path] = entry
    if set(by_path) != set(paths):
        raise ValueError('Metadata paths must exactly match the supplied inputs')
    arrays, reports, hashes = [], [], []
    for path in paths:
        entry = by_path[path]
        if entry.get('original_acquisition') is not True:
            raise ValueError('Each file must be explicitly identified as an original acquisition')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if entry.get('sha256') != digest:
            raise ValueError(f'Original acquisition hash mismatch: {path.name}')
        with tifffile.TiffFile(path) as image:
            if len(image.pages) != 1:
                raise ValueError('Use one original TIFF image per file')
            software = str(image.pages[0].tags['Software'].value) if 'Software' in image.pages[0].tags else ''
            if any(marker in software.casefold() for marker in ('frame stitch', 'frame optical plan', 'frame optical repeat mean', 'reference-tone')):
                raise ValueError('Known processed/stitched TIFF software marker cannot be used as original sensor evidence')
            array = image.pages[0].asarray()
        report = sensor_precision.analyze_acquisition(array, provenance=entry)
        arrays.append(array); hashes.append(digest)
        reports.append({'path': str(path), 'sha256': digest, 'analysis': report})
    result = {'engine': sensor_precision.VERSION, 'device_io': False,
              'inputs': reports, 'effective_sensor_bits': None, 'effective_adc_bits': None}
    if len(paths) > 1:
        entries_in_order = [by_path[path] for path in paths]
        settings = [entry.get('settings') for entry in entries_in_order]
        if any(not isinstance(setting, dict) for setting in settings) or any(setting != settings[0] for setting in settings[1:]):
            raise ValueError('Repeat-noise inputs require identical declared acquisition settings')
        if settings[0].get('dpi') != dpi:
            raise ValueError('Repeat analysis DPI must match the acquisition metadata')
        if settings[0].get('auto_exposure'):
            effective = [entry.get('effective_exposure') for entry in entries_in_order]
            if (any(not isinstance(value, list) or len(value) != 3 or
                    any(isinstance(channel, bool) or not isinstance(channel, (int, float)) or
                        not math.isfinite(channel) or channel <= 0 for channel in value)
                    for value in effective) or any(value != effective[0] for value in effective[1:])):
                raise ValueError('Vendor auto-exposure repeats require measured effective_exposure RGB values known identical for every acquisition')
        combined = entries_in_order[0].copy()
        combined['same_position'] = all(entry.get('same_position') is True for entry in entries_in_order)
        combined['hardware'] = all(entry.get('hardware') is True for entry in entries_in_order)
        combined['synthetic'] = any(entry.get('synthetic') is True for entry in entries_in_order)
        result['repeat_noise'] = sensor_precision.analyze_repeats(arrays, dpi, provenance=combined)
        result['repeat_noise']['measured_source_sha256'] = hashes
        result['repeat_noise']['measured_acquisition_paths'] = [str(path) for path in paths]
        result['repeat_noise']['declared_identical_settings'] = settings[0]
        if settings[0].get('auto_exposure'):
            result['repeat_noise']['measured_effective_exposure'] = effective[0]
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in zip(paths, hashes)):
        raise ValueError('An input changed during the measurement')
    result['original_hashes_unchanged'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, nargs='+')
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--dpi', type=float, default=1800)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = run(args.sources, args.metadata, args.dpi)
        encoded = json.dumps(report, indent=2, allow_nan=False)
        if args.output:
            target = args.output.resolve()
            if target in [path.resolve() for path in args.sources] or target == args.metadata.resolve():
                raise ValueError('Output must not overwrite an input or its metadata')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as stream:
                stream.write(encoded + '\n')
            print(json.dumps({'report': str(target), 'device_io': False, 'effective_sensor_bits': None}))
        else:
            print(encoded)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'Precision measurement failed: {exc}\n')


if __name__ == '__main__':
    main()
