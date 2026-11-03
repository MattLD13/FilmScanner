"""CPU image-worker evidence only: no scanner operation or driver session."""
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

from services.imaging import vendor_autogamma


def tables():
    grid = np.linspace(0, 1, 256)
    return np.floor(np.stack((grid ** .7, grid ** 1.4, grid ** 2.2)) * 255).astype(np.uint16)


def test_exact_16bit_application_preserves_identity_and_original_samples():
    ramp = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    image = np.stack((ramp, ramp[::-1], np.roll(ramp, 31, axis=1)), axis=-1)
    original = image.copy()
    identity = np.tile(np.arange(256), (3, 1))
    assert np.array_equal(vendor_autogamma.apply(image, identity), image)
    assert np.array_equal(image, original)
    out = vendor_autogamma.apply(image, tables())
    assert out.dtype == np.uint16 and out.shape == image.shape
    # Knot expansion differs from nearest-neighbour 8-bit lookup and preserves
    # interpolated low input bits wherever adjacent curve entries differ.
    assert out[1, 0, 0] == 1280 and out[1, 1, 0] == 1285
    assert np.any(out % 257 != 0)


def test_8bit_and_normalized_float_use_explicit_supported_domains():
    image = np.arange(240, dtype=np.uint8).reshape(8, 10, 3)
    expected = tables()[np.arange(3), image].astype(np.uint8)
    assert np.array_equal(vendor_autogamma.apply(image, tables()), expected)
    floats = image.astype(np.float32) / 255
    actual = vendor_autogamma.apply(floats, tables())
    words = vendor_autogamma.apply(np.rint(floats * 65535).astype(np.uint16), tables())
    assert actual.dtype == np.float32
    assert np.array_equal(actual, words.astype(np.float64).astype(np.float32) / np.float32(65535))


def test_bad_or_degenerate_tables_and_invalid_input_do_not_apply():
    with pytest.raises(ValueError, match='eight distinct'):
        vendor_autogamma.validate_tables(np.tile(np.where(np.arange(256) < 127, 0, 255), (3, 1)), require_usable=True)
    with pytest.raises(ValueError, match='monotone'):
        vendor_autogamma.apply(np.zeros((10, 10, 3), np.uint16), tables()[:, ::-1])
    with pytest.raises(ValueError, match='RGB'):
        vendor_autogamma.apply(np.zeros((10, 10), np.uint16), tables())
    with pytest.raises(ValueError, match='normalized'):
        vendor_autogamma.apply(np.full((10, 10, 3), np.nan), tables())
    with pytest.raises(ValueError, match='explicit'):
        vendor_autogamma.generate_tables(np.zeros((10, 10, 3), np.uint8), negative=1)


@pytest.mark.skipif(not vendor_autogamma.available(), reason='Requires pinned local vendor CPU worker')
@pytest.mark.parametrize('bits', [8, 16])
def test_application_matches_actual_vendor_on_entire_input_domain(tmp_path, bits):
    ramp = (np.arange(65536, dtype=np.uint16).reshape(256, 256) if bits == 16 else
            np.arange(256, dtype=np.uint8).reshape(16, 16))
    image = np.stack((ramp, ramp[::-1], np.roll(ramp, 3, axis=1)), axis=-1)
    source, table, destination = tmp_path / 'input.raw', tmp_path / 'tables.raw', tmp_path / 'output.raw'
    source.write_bytes(image.tobytes())
    table.write_bytes(tables().astype('<u2').tobytes())
    original = source.read_bytes()
    result = subprocess.run([str(vendor_autogamma.ORACLE), 'autoapply', str(source), str(image.shape[1]),
                             str(image.shape[0]), str(bits), str(table), str(destination)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['device_io'] is False
    actual = np.fromfile(destination, dtype=image.dtype).reshape(image.shape)
    assert np.array_equal(actual, vendor_autogamma.apply(image, tables()))
    assert source.read_bytes() == original


@pytest.mark.skipif(not vendor_autogamma.available(), reason='Requires pinned local vendor CPU worker')
@pytest.mark.parametrize('bits', [8, 16])
def test_negative_table_generation_is_real_worker_and_settings_are_unchanged(bits):
    rng = np.random.default_rng(519)
    image = rng.integers(15, 240, (100, 120, 3), dtype=np.uint8)
    if bits == 16:
        image = image.astype(np.uint16) * 257
    original = image.copy()
    settings = Path(os.environ['APPDATA']) / 'PIE/MF/CyberViewX.ini'
    before = settings.read_bytes() if settings.is_file() else None
    result = vendor_autogamma.generate_tables(image, negative=True, input_plane='converted_positive')
    assert len(result['tables']) == 3 and all(len(row) == 256 for row in result['tables'])
    evidence = result['diagnostics']
    assert evidence['device_io'] is False and evidence['reference_used'] is False
    assert evidence['caller_stage_order_verified'] is True
    assert evidence['acquisition_parity_verified'] is False
    assert evidence['branch'] == 'negative_histogram_0x10008bd0'
    assert min(evidence['unique_levels']) >= 8
    assert np.array_equal(image, original)
    assert (settings.read_bytes() if settings.is_file() else None) == before


def test_unavailable_vendor_worker_does_not_use_an_approximation(tmp_path):
    with pytest.raises(ValueError, match='unavailable'):
        vendor_autogamma.generate_tables(np.zeros((10, 10, 3), np.uint8), negative=True,
                                        oracle_path=tmp_path / 'missing.exe')


def test_statistics_use_full_selected_resolution_and_only_acquired_outer_rows():
    image=np.random.default_rng(3).random((100,1800,3),dtype=np.float32)
    original=image.copy();covered=np.ones((100,1800),bool)
    covered[0,:8]=False;covered[-1,-8:]=False
    selected,evidence=vendor_autogamma.statistics_input(image,dict(left=0,top=0,right=1,bottom=1),covered)
    assert selected.shape==(98,1800,3)
    assert np.array_equal(selected,image[1:-1])
    assert evidence['used_bounds_px']==[0,1,1800,99]
    assert evidence['host_strided_resampling'] is False
    assert evidence['unacquired_pixels_used']==0
    assert np.array_equal(image,original)
    covered[50,500]=False
    with pytest.raises(ValueError,match='internal holes'):
        vendor_autogamma.statistics_input(image,dict(left=0,top=0,right=1,bottom=1),covered)


def test_statistics_refuse_large_missing_regions_and_empty_crops():
    image=np.zeros((100,100,3),np.uint16);covered=np.ones((100,100),bool);covered[:8]=False
    with pytest.raises(ValueError,match='insufficient'):
        vendor_autogamma.statistics_input(image,dict(left=0,top=0,right=1,bottom=1),covered)
    with pytest.raises(ValueError,match='valid normalized'):
        vendor_autogamma.statistics_input(image,dict(left=.8,top=0,right=.2,bottom=1))


def test_statistics_edge_guard_rejects_wedge_influence_without_cropping_the_original():
    rng=np.random.default_rng(21);clean=rng.uniform(.02,.85,(284,430,3)).astype(np.float32)
    dirty=clean.copy();dirty[-5:]=1;dirty[:,:2]=1;dirty[:,-2:]=1
    crop=dict(left=0,top=0,right=1,bottom=1)
    a,ae=vendor_autogamma.statistics_input(clean,crop,dpi=300)
    b,be=vendor_autogamma.statistics_input(dirty,crop,dpi=300)
    assert np.array_equal(a,b)
    assert ae==be and ae['used_bounds_px']==[2,0,428,277]
    assert ae['edge_guard']['bottom_rows']==7
    assert np.all(dirty[-5:]==1)
    if vendor_autogamma.available():
        assert vendor_autogamma.generate_tables(a,negative=True,input_plane='converted_positive')['tables']==vendor_autogamma.generate_tables(b,negative=True,input_plane='converted_positive')['tables']
