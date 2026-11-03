import numpy as np
import pytest

from services.api.cyberview_routes import Adjustments, before_levels, auto_color_for
from services.imaging import negative
from services.imaging import statistics_guard


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


def test_small_clipped_scanner_edge_does_not_hide_the_orange_base():
    raw = np.tile(transmission(), (10, 10, 1))
    contaminated = raw.copy()
    contaminated[:2] = 65520 / 65535
    base = negative.suggest_base(contaminated)
    assert base == pytest.approx([.7, .5, .3])
    converted = negative.invert(raw, base, negative.SUGGESTED_RESPONSE)
    assert np.allclose(converted[..., 0], converted[..., 2])
    assert np.allclose(converted[0], 0)


@pytest.mark.parametrize('dpi,height,width,bottom,side',[(1800,1708,2585,40,8),(300,284,430,7,2)])
def test_guarded_base_is_invariant_to_bottom_wedge_and_outer_column_contamination(dpi,height,width,bottom,side):
    rng=np.random.default_rng(27)
    raw=rng.uniform(.08,.95,(height,width,1))*np.array([.7,.5,.3])
    raw[height//3:height//3+8,width//2:width//2+70]=[.7,.5,.3]
    contaminated=raw.copy()
    for x in range(width):
        depth=max(1,int((bottom-1)*(1-x/max(1,width-1))))
        contaminated[-depth:,x]=0
    contaminated[:,:side]=1;contaminated[:,-side:]=1
    before=raw.copy()
    assert negative.suggest_base(raw,dpi=dpi)==negative.suggest_base(contaminated,dpi=dpi)
    assert np.array_equal(raw,before)


def test_small_custom_window_does_not_lose_most_of_its_statistics_to_a_full_gate_guard():
    mask,evidence=statistics_guard.mask((100,100,3),1800)
    assert mask.all() and not evidence['applied']
    mask,evidence=statistics_guard.mask((1708,2585,3),1800)
    assert evidence['applied'] and not mask[-40:].any()
    assert mask[:,:8].sum()==0 and mask[:,-8:].sum()==0


def test_extensive_clipping_is_not_a_valid_base():
    raw = np.tile(transmission(), (10, 10, 1))
    raw[:20] = 1
    assert negative.suggest_base(raw) is None


def test_general_display_lifts_midtones_without_forcing_colored_scene_neutral():
    wedge=np.linspace(.03,.7,10000).reshape(100,100)
    positive=wedge[...,None]*[.55,1,.45]
    suggestion=negative.suggest_display(positive)
    assert suggestion is not None
    assert suggestion['evidence']['reference_used'] is False
    assert suggestion['evidence']['automatic_endpoint_clipping'] is False
    assert suggestion['rgb_balance']==[1,1,1]
    adjusted=Adjustments(**{k:v for k,v in suggestion.items() if k!='evidence'})
    from services.api.cyberview_routes import apply
    out=apply(positive,adjusted)
    assert np.median(out[...,1])>np.median(positive[...,1])
    assert np.all(out[...,1]>=out[...,0]) and np.all(out[...,1]>=out[...,2])


def test_general_display_preserves_neutrality_and_bounds_automatic_changes():
    wedge=np.linspace(.02,.8,10000).reshape(100,100)
    positive=np.repeat(wedge[...,None],3,axis=2)
    suggestion=negative.suggest_display(positive)
    assert suggestion['rgb_balance']==pytest.approx([1,1,1])
    assert 0<=suggestion['black_point']<=.03
    assert .85<=suggestion['white_point']<=1
    assert suggestion['black_point']==0 and suggestion['white_point']==1
    assert suggestion['gamma']==1.2
    assert negative.suggest_display(np.full((100,100,3),.05)) is None
    low=negative.suggest_display(positive*.3)
    assert low['white_point']>=.85, 'A dark scene must not be stretched all the way to white'


def test_general_display_excludes_unacquired_or_rebate_pixels():
    positive=np.repeat(np.linspace(.02,.8,10000).reshape(100,100,1),3,axis=2)
    padded=np.pad(positive,((10,10),(10,10),(0,0)),constant_values=1)
    mask=np.pad(np.ones((100,100),bool),((10,10),(10,10)))
    a=negative.suggest_display(positive)
    b=negative.suggest_display(padded,mask)
    assert a==b
    with pytest.raises(ValueError,match='mask'):
        negative.suggest_display(positive,mask)


def test_default_display_does_not_zero_low_red_channel_or_clip_high_channels():
    # Low red alongside brighter green/blue reproduces the luminance-percentile
    # black-point failure seen in the saved garden image.
    t=np.linspace(.00001,.99999,10000).reshape(100,100)
    positive=np.stack((t**3*.8+.00001,t*.8+.00001,t*.9+.00001),axis=-1)
    suggestion=negative.suggest_display(positive)
    from services.api.cyberview_routes import apply
    edit=Adjustments(**{k:v for k,v in suggestion.items() if k!='evidence'})
    out=apply(positive,edit)
    assert np.all(out>0) and np.all(out<1)
    assert np.all(np.diff(out.reshape(-1,3),axis=0)>0)
    assert edit.black_point==0 and edit.white_point==1
    assert edit.rgb_balance==[1,1,1]


@pytest.mark.parametrize('raw', [np.ones((10, 10, 3)), np.full((10, 10, 3), .5),
                               np.zeros((10, 10, 3)), np.full((10, 10, 3), np.nan),
                               np.tile([.3, .6, 1.0], (10, 10, 1))])
def test_refuse_unreliable_base_suggestions(raw):
    assert negative.suggest_base(raw) is None
