import hashlib
import json

import numpy as np
import pytest
import tifffile

from services.imaging import sensor_precision
from scripts.measure_sensor_precision import run


def original(**fields):
    return {'original_acquisition': True, 'hardware': False, 'synthetic': True,
            'image_kind': 'synthetic-transmission', **fields}


def test_12bit_shifted_codes_are_not_reported_as_16bit_sensor_precision():
    image = (np.arange(4096, dtype=np.uint16).reshape(64, 64) << 4)
    report = sensor_precision.analyze_acquisition(image, provenance=original())
    channel = report['channels'][0]
    assert report['container_bits'] == 16
    assert channel['observed_unique_code_count'] == 4096
    assert channel['observed_code_lattice_step'] == 16
    assert channel['aligned_low_zero_bits'] == 4
    assert channel['code_lattice_bits_ceiling'] == 12
    assert report['effective_sensor_bits'] is None and report['effective_adc_bits'] is None
    assert report['provenance']['evidence'] == 'synthetic'


def test_fully_occupied_low_bits_and_high_entropy_are_not_sensor_enob():
    image = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    report = sensor_precision.analyze_acquisition(image)
    channel = report['channels'][0]
    assert channel['observed_code_lattice_step'] == 1
    assert channel['varying_bit_count'] == 16 and channel['aligned_low_zero_bits'] == 0
    assert channel['scene_code_entropy_bits'] == pytest.approx(16)
    assert report['effective_sensor_bits'] is None
    assert report['provenance']['evidence'] == 'unverified_input'


def test_replicated_twelve_bit_output_is_not_proof_of_sixteen_bit_sensor():
    values = np.arange(4096, dtype=np.uint16)
    expanded = ((values << 4) | (values >> 8)).reshape(64, 64)
    report = sensor_precision.analyze_acquisition(expanded, provenance=original())
    assert report['channels'][0]['observed_unique_code_count'] == 4096
    assert report['channels'][0]['observed_code_lattice_step'] == 1
    assert report['effective_sensor_bits'] is None


@pytest.mark.parametrize('field', ['derived', 'processed', 'stitched', 'resampled'])
def test_processed_images_cannot_be_sensor_evidence(field):
    with pytest.raises(ValueError, match='Processed'):
        sensor_precision.analyze_acquisition(np.ones((64, 64), np.uint16), provenance=original(**{field: True}))


def test_stitched_capture_purpose_cannot_be_sensor_evidence():
    with pytest.raises(ValueError, match='Processed'):
        sensor_precision.analyze_acquisition(np.ones((64, 64), np.uint16), provenance=original(purpose='stitched'))


def test_identical_repeats_do_not_claim_infinite_precision():
    image = np.full((100, 120, 3), 20000, dtype=np.uint16)
    report = sensor_precision.analyze_repeats([image, image.copy()], 1800, provenance=original(same_position=True))
    assert report['temporal_measurement_valid'] and report['identical_inputs']
    assert all(channel['robust_temporal_sigma_output_codes'] == 0 for channel in report['channels'])
    assert all(channel['quantization_equivalent_output_noise_bits'] is None for channel in report['channels'])
    assert report['effective_sensor_bits'] is None


def test_known_flat_repeat_noise_is_an_output_estimate_with_stationary_assumption():
    rng = np.random.default_rng(10)
    images = [np.rint(24000 + rng.normal(0, 100, (160, 180, 3))).astype(np.uint16) for _ in range(4)]
    report = sensor_precision.analyze_repeats(images, 1800, provenance=original(same_position=True))
    assert report['temporal_measurement_valid'] and report['effective_sensor_bits'] is None
    assert any('assumed' in warning for warning in report['warnings'])
    for channel in report['channels']:
        assert channel['robust_temporal_sigma_output_codes'] == pytest.approx(100, rel=.12)
        assert channel['quantization_equivalent_output_noise_bits'] == pytest.approx(7.56, abs=.2)


def test_noisy_flat_repeats_without_stationary_provenance_fail_registration_honestly():
    rng = np.random.default_rng(12)
    images = [np.rint(24000 + rng.normal(0, 100, (100, 120, 3))).astype(np.uint16) for _ in range(2)]
    report = sensor_precision.analyze_repeats(images, 1800, provenance=original())
    assert not report['temporal_measurement_valid']
    assert report['effective_sensor_bits'] is None


def test_cli_measurement_verifies_hashes_and_refuses_mismatched_repeat_settings(tmp_path):
    images = []
    entries = []
    for index in range(2):
        path = tmp_path / f'original-{index}.tif'
        tifffile.imwrite(path, np.arange(4096, dtype=np.uint16).reshape(64, 64) << 4)
        images.append(path)
        entries.append(original(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                settings={'dpi': 300, 'exposure': [100, 100, 100]}, same_position=True))
    metadata = tmp_path / 'originals.json'
    metadata.write_text(json.dumps({'acquisitions': entries}), encoding='utf-8')
    report = run(images, metadata, 300)
    assert report['device_io'] is False and report['original_hashes_unchanged']
    assert report['effective_sensor_bits'] is None
    entries[1]['settings']['exposure'] = [120, 120, 120]
    metadata.write_text(json.dumps({'acquisitions': entries}), encoding='utf-8')
    with pytest.raises(ValueError, match='identical declared'):
        run(images, metadata, 300)
    entries[1]['sha256'] = '0' * 64
    metadata.write_text(json.dumps({'acquisitions': entries}), encoding='utf-8')
    with pytest.raises(ValueError, match='hash mismatch'):
        run(images, metadata, 300)


def test_cli_refuses_known_stitched_master_even_with_incorrect_original_declaration(tmp_path):
    path=tmp_path/'claimed-original.tif'
    tifffile.imwrite(path,np.arange(4096,dtype=np.uint16).reshape(64,64),software='FRAME optical plan')
    metadata=tmp_path/'originals.json'
    metadata.write_text(json.dumps({'acquisitions':[original(path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())]}),encoding='utf8')
    with pytest.raises(ValueError,match='processed/stitched'):
        run([path],metadata,1800)


def test_cli_auto_exposure_repeats_require_identical_measured_effective_exposure(tmp_path):
    paths=[]; entries=[]
    for index in range(2):
        path=tmp_path/f'auto-{index}.tif'
        tifffile.imwrite(path,np.full((80,90),20000,np.uint16))
        paths.append(path)
        entries.append(original(path=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            settings={'dpi':1800,'auto_exposure':True,'exposure':[100,100,100]},same_position=True))
    metadata=tmp_path/'auto.json'
    def save():
        metadata.write_text(json.dumps({'acquisitions':entries}),encoding='utf8')
    save()
    with pytest.raises(ValueError,match='measured effective_exposure'):
        run(paths,metadata,1800)
    entries[0]['effective_exposure']=[120,160,250]
    entries[1]['effective_exposure']=[120,161,250]
    save()
    with pytest.raises(ValueError,match='identical'):
        run(paths,metadata,1800)
    entries[1]['effective_exposure']=[120,160,250]
    save()
    report=run(paths,metadata,1800)
    assert report['repeat_noise']['measured_effective_exposure']==[120,160,250]
    assert report['effective_adc_bits'] is None
