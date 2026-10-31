import numpy as np
import pytest

from services.imaging import filmterms, reference_tone


def fixture_profile():
    rng = np.random.default_rng(58)
    source = rng.uniform(.02, .98, (160, 180, 3))
    target = np.clip((source - [.05, .08, .03]) / [.86, .83, .90], 0, 1) ** [1.7, 1.45, 1.9]
    train = np.zeros(source.shape[:2], bool)
    train[:100] = True
    lut, counts = reference_tone.fit(source, target, train)
    profile = {'id': 'a' * 16, 'kind': 'reference-tone', 'name': 'Synthetic reference',
               'maker': 'Test fixture', 'film_class': 'negative', 'rows': 4096, 'scale': 4095,
               'lut': (lut * 4095).tolist(), 'matrix': np.column_stack((np.eye(3), np.zeros(3))).tolist(),
               'source_file': 'fixture', 'source_folder': 'Reference profiles', 'input_response': .5}
    return source, target, train, profile, counts


def test_reference_curves_recover_held_out_tones_without_spatial_texture():
    source, target, train, profile, counts = fixture_profile()
    out = filmterms.apply(source, profile)
    assert min(counts) > 200
    assert np.mean(np.abs(out[~train] - target[~train])) < .004
    assert np.mean(np.abs(out[~train] - target[~train])) < np.mean(np.abs(source[~train] - target[~train])) / 20
    lut = np.array(profile['lut'])
    assert np.all(np.diff(lut, axis=0) >= 0)
    assert np.array_equal(lut[[0, -1]], [[0, 0, 0], [4095, 4095, 4095]])
    # Permuting source pixels must permute output exactly: no reference texture can
    # be copied into an image by this global point transformation.
    assert np.array_equal(filmterms.apply(source[::-1, ::-1], profile), out[::-1, ::-1])
    assert np.any(np.rint(out * 65535).astype('uint16') % 257 != 0)


def test_holdout_changes_cannot_affect_a_fitted_profile():
    source, target, train, profile, _ = fixture_profile()
    changed = target.copy()
    changed[~train] = 1 - changed[~train]
    lut, _ = reference_tone.fit(source, changed, train)
    assert np.array_equal(lut * 4095, np.array(profile['lut']))


def test_refuse_unregistered_or_insufficient_inputs():
    source = np.ones((20, 20, 3)) * .4
    with pytest.raises(ValueError, match='registered'):
        reference_tone.fit(source, source[:, :-1], np.ones((20, 20), bool))
    with pytest.raises(ValueError, match='mask'):
        reference_tone.fit(source, source, np.ones((10, 20), bool))
    with pytest.raises(ValueError, match='insufficient'):
        reference_tone.fit(source, source, np.ones((20, 20), bool))
