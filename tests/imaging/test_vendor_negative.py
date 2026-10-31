import json
from pathlib import Path
import subprocess
import sys
import os

import numpy as np
import pytest

from services.api.cyberview_routes import Adjustments, before_levels
from services.imaging import vendor_negative, vendor_filmterm, filmterms
from services.api.store import Store

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / 'services/cyberview_bridge/bin/vendorcolour.exe'
DS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'twain_32/CyberViewX_MF/CyberViewX.ds'


def fixture_data():
    film = ('FilmClass NEG;\nFilmName Synthetic negative;\nFilmMfgr Fixture;\nFilmLut\n' +
            '\n'.join(f'{i} {i} {i}' for i in range(256)) + ';\n' +
            'FilmMatR 1 0 0 0;\nFilmMatG 0 1 0 0;\nFilmMatB 0 0 1 0;\n').encode()
    gamma = ('FilmLut\n' + '\n'.join(f'{i+.75 if i<4095 else i} {i} {i}' for i in range(4096)) + ';').encode()
    return film, gamma


def test_vendor_negative_uses_model_gamma_without_nominal_power_or_reference_fit():
    film, gamma = fixture_data()
    profile = vendor_negative.create(film, gamma, 'fixture.ft', 'Fixture')
    values = np.array([[[0, .1, .2], [.3, .6, 1]]])
    out = before_levels(values, Adjustments(invert=True, film_profile=profile['id']), profile)
    expected = vendor_filmterm.apply16(((4095 - (np.rint(values * 65535).astype(np.uint16) >> 4)) << 4).astype(np.uint16), profile) / 65535
    assert np.array_equal(out, expected)
    different_nominal = before_levels(values, Adjustments(invert=True, film_profile=profile['id'],
                                                         negative_response=.3, film_base=[.3, .5, .2]), profile)
    assert np.array_equal(out, different_nominal), 'Nominal base/power are not part of the vendor conversion'
    assert profile['generic_file'] == '37.GG' and len(profile['generic_lut']) == 4096
    with pytest.raises(ValueError, match='negative transmission'):
        before_levels(values, Adjustments(film_profile=profile['id']), profile)


def test_cached_vendor_profile_hash_and_source_precision_survive_restart(tmp_path):
    profile = vendor_negative.create(*fixture_data(), 'fixture.ft', 'Fixture')
    store = Store(tmp_path)
    filmterms.remember(store, profile)
    store.close()
    store = Store(tmp_path)
    try:
        assert filmterms.load(store, profile['id']) == profile
        assert filmterms.reference_profiles(store)[0]['kind'] == 'vendor-negative'
        changed = profile.copy()
        changed['matrix'] = [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
        filmterms.cache_path(store, profile['id']).write_text(json.dumps(changed))
        with pytest.raises(ValueError, match='checksum'):
            filmterms.load(store, profile['id'])
        assert filmterms.reference_profiles(store) == []
    finally:
        store.close()


def test_scan08_lut_boundaries_and_legacy_profile_reproduction():
    profile = vendor_negative.create(*fixture_data(), 'fixture.ft', 'Fixture')
    values = np.repeat(np.array([0, 1, 15, 16, 17, 31, 32, 65535], np.uint16)[None, :, None], 3, axis=-1)
    expected = np.repeat(np.array([65520, 65520, 65520, 65504, 65504, 65504, 65488, 0], np.uint16)[None, :, None], 3, axis=-1)
    assert np.array_equal(vendor_negative.apply16(values, profile), expected)
    profile = vendor_negative.identify(profile | {'engine': vendor_negative.LEGACY_VERSION})
    floats = values.astype(float) / 65535
    # Old version remains the original continuous adapter; loading it must not
    # silently introduce a new quantisation or change archived export bytes.
    assert np.array_equal(vendor_negative.apply(floats, profile), vendor_filmterm.apply(1 - floats, profile))


@pytest.mark.skipif(sys.platform != 'win32' or not ORACLE.is_file() or not DS.is_file(),
                    reason='Requires local pinned vendor binary and CPU-only oracle')
def test_generic_gamma_reader_matches_vendor_without_scanner(tmp_path):
    _, gamma = fixture_data()
    source = tmp_path / 'synthetic.gg'
    source.write_bytes(gamma)
    output = tmp_path / 'generic.raw'
    result = subprocess.run([str(ORACLE), 'generic', str(source), str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['device_io'] is False
    vendor = np.fromfile(output, dtype=np.float32).reshape(4096, 3)
    actual = np.array(vendor_negative.parse_generic(gamma.decode()))
    assert np.array_equal(actual, np.trunc(vendor))


@pytest.mark.skipif(sys.platform != 'win32' or not ORACLE.is_file() or not DS.is_file(),
                    reason='Requires local pinned vendor binary and CPU-only oracle')
def test_curve_builder_endpoint_duplicates_are_not_safe_to_promote(tmp_path):
    # Verifies the exact worker's surprising duplicate-x result; production keeps
    # the old monotone builder until caller sanitisation/selection is understood.
    points = tmp_path / 'points.txt'
    points.write_text('255 255\n113 128\n0 0\n')
    output = tmp_path / 'table.raw'
    result = subprocess.run([str(ORACLE), 'curve', str(points), '256', str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not np.fromfile(output, dtype=np.uint16).any()
