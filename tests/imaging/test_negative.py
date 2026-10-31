import numpy as np
import pytest

from services.api.cyberview_routes import Adjustments, before_levels, auto_color_for
from services.imaging import negative


def transmission():
    # A neutral wedge on orange film, with a clear film margin.
    values = np.linspace(.04, .95, 100).reshape(10, 10)
    values[0] = 1
    return values[..., None] * np.array([.7, .5, .3])


def test_base_and_conversion_are_invariant_to_channel_exposure():
    raw = transmission()
    boosted = raw * [1.2, 1.68, 2.69]
    base = negative.suggest_base(raw)
    boosted_base = negative.suggest_base(boosted)
    assert base == pytest.approx([.7, .5, .3])
    assert boosted_base == pytest.approx([.84, .84, .807])
    converted = negative.invert(raw, base, negative.SUGGESTED_RESPONSE)
    other = negative.invert(boosted, boosted_base, negative.SUGGESTED_RESPONSE)
    assert np.allclose(converted, other)
    assert np.allclose(converted[0], 0), 'Clear film must render black'
    assert np.allclose(converted[..., 0], converted[..., 2]), 'Neutral density must stay neutral'
    assert np.all(np.diff(converted[1:, :, 0].reshape(-1)) < 0)


def test_legacy_recipes_keep_the_exact_original_response():
    raw = transmission()
    assert Adjustments().negative_response == 1.6
    actual = before_levels(raw, Adjustments(invert=True))
    assert np.array_equal(actual, 1 - raw ** 1.6)
    tuned = before_levels(raw, Adjustments(invert=True, negative_response=.5))
    assert np.allclose(tuned, 1 - np.sqrt(raw))
    assert np.array_equal(before_levels(raw, Adjustments(negative_response=.5)), raw)
    for value in [0, 3.01, float('nan'), float('inf')]:
        with pytest.raises(ValueError):
            Adjustments(negative_response=value)


def test_uncovered_stitch_pixels_cannot_change_the_base_or_auto_colour():
    raw = transmission()
    padded = np.pad(raw, ((2, 2), (2, 2), (0, 0)), constant_values=1)
    mask = np.pad(np.ones(raw.shape[:2], bool), ((2, 2), (2, 2)))
    assert negative.suggest_base(padded, mask) == pytest.approx(negative.suggest_base(raw))
    positive = negative.invert(padded, [.7, .5, .3], .5)
    assert auto_color_for(positive, mask) == auto_color_for(positive[mask][:, None, :])
    assert auto_color_for(positive, np.zeros(mask.shape, bool)) is None
    with pytest.raises(ValueError, match='Coverage'):
        negative.suggest_base(raw, mask)


@pytest.mark.parametrize('raw', [np.ones((10, 10, 3)), np.full((10, 10, 3), .5),
                               np.zeros((10, 10, 3)), np.full((10, 10, 3), np.nan),
                               np.linspace(.1, 1, 300).reshape(10, 10, 3)])
def test_refuse_unreliable_base_suggestions(raw):
    assert negative.suggest_base(raw) is None
