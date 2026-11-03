import numpy as np
import pytest

from services.imaging import scan_filters


def test_disabled_filters_are_identity_without_aliasing_original():
    image = np.random.default_rng(12).uniform(0, 1, (80, 90, 3)).astype(np.float32)
    original = image.copy()
    out = scan_filters.process(image, {})
    assert np.array_equal(out, image)
    assert not np.shares_memory(out, image)
    out[0] = 0
    assert np.array_equal(image, original)


def test_grain_smoothing_reduces_noise_while_retaining_a_color_edge():
    rng = np.random.default_rng(4)
    clean = np.empty((100, 120, 3)); clean[:, :60] = [.2, .3, .2]; clean[:, 60:] = [.7, .6, .3]
    noisy = np.clip(clean + rng.normal(0, .015, clean.shape), 0, 1)
    out = scan_filters.process(noisy, {'grain_reduction': 1})
    assert np.std(out[5:-5, 5:50] - clean[5:-5, 5:50]) < np.std(noisy[5:-5, 5:50] - clean[5:-5, 5:50]) * .75
    assert np.mean(out[:, 60:64, 0]) - np.mean(out[:, 56:60, 0]) > .45
    assert np.array_equal(noisy, np.clip(clean + np.random.default_rng(4).normal(0, .015, clean.shape), 0, 1))


def test_restoration_preserves_neutrals_endpoints_and_colored_scene_hue_order():
    wedge = np.linspace(0, 1, 100).reshape(10, 10)
    neutral = np.repeat(wedge[..., None], 3, axis=2)
    out = scan_filters.process(neutral, {'color_restoration': 1})
    assert np.allclose(out[..., 0], out[..., 1]) and np.allclose(out[..., 1], out[..., 2])
    assert np.array_equal(out[0, 0], [0, 0, 0]) and np.array_equal(out[-1, -1], [1, 1, 1])
    assert np.all(np.diff(out[..., 0].reshape(-1)) > 0)
    green = np.tile([.2, .6, .3], (20, 20, 1))
    other = scan_filters.process(green, {'color_restoration': 1})
    assert np.all(other[..., 1] > other[..., 2]) and np.all(other[..., 2] > other[..., 0])
    assert np.all(other >= 0) and np.all(other <= 1)


def test_sharpening_increases_low_contrast_detail_without_overshoot():
    x = .45 + .06 * np.sin(np.linspace(0, 10 * np.pi, 120))
    image = np.tile(x[None, :, None], (100, 1, 3))
    out = scan_filters.process(image, {'sharpening': 1})
    assert np.max(abs(np.diff(out[20, :, 0]))) > np.max(abs(np.diff(image[20, :, 0])))
    assert out.min() >= image.min() - 1e-12 and out.max() <= image.max() + 1e-12


@pytest.mark.parametrize('settings', [{'unknown': .5}, {'sharpening': -1}, {'grain_reduction': float('nan')},
                                     {'color_restoration': 1.01}, {'sharpening': True}])
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        scan_filters.process(np.ones((20, 20, 3)) * .5, settings)


def test_all_filters_remain_bounded_and_original_stays_unchanged():
    image = np.random.default_rng(7).uniform(0, 1, (90, 100, 3))
    original = image.copy()
    out = scan_filters.process(image, dict.fromkeys(scan_filters.SETTINGS, 1))
    assert np.isfinite(out).all() and out.min() >= 0 and out.max() <= 1
    assert np.array_equal(image, original)


def test_registered_repeat_mean_reduces_noise_without_multiplicative_exposure_matching():
    rng = np.random.default_rng(13)
    scene = rng.uniform(.25, .75, (128, 160, 3))
    repeats = [scene + rng.normal(0, .015, scene.shape) for _ in range(4)]
    original = [image.copy() for image in repeats]
    result = scan_filters.aligned_mean(repeats, dpi=300)
    central = np.s_[4:-4, 4:-4]
    assert np.std(result['image'][central] - scene[central]) < np.std(repeats[0][central] - scene[central]) * .7
    assert result['source_count'] == 4 and result['exposure_matching'] is False
    assert result['offset_normalization']['applied'] is True
    assert result['offset_normalization']['multiplicative_gain_applied'] is False
    assert result['full_repeat_coverage'][central].all()
    assert all(np.array_equal(a, b) for a, b in zip(repeats, original))


def test_repeat_mean_verifies_supplied_displacement_and_reports_edge_contributors():
    scene = np.random.default_rng(32).uniform(.2, .8, (140, 170, 3))
    moving = np.roll(scene, (2, -3), axis=(0, 1))
    result = scan_filters.aligned_mean([scene, moving], [{'dx': 0, 'dy': 0}, {'dx': 3, 'dy': -2}], dpi=300)
    assert np.allclose(result['image'][5:-5, 5:-5], scene[5:-5, 5:-5], atol=.002)
    assert result['counts'].min() == 1 and result['counts'].max() == 2
    assert result['registration'][0]['verified'] is True
    with pytest.raises(ValueError, match='UNVERIFIED_STITCH_ALIGNMENT'):
        scan_filters.aligned_mean([scene, moving], [{'dx': 0, 'dy': 0}, {'dx': 20, 'dy': 0}], dpi=300)


def test_ambiguous_flat_repeats_do_not_silently_average():
    image = np.ones((100, 130, 3)) * .4
    with pytest.raises(ValueError, match='texture'):
        scan_filters.aligned_mean([image, image], dpi=300)


def test_shared_interior_offset_correction_removes_contributor_edge_steps(monkeypatch):
    scene=np.random.default_rng(82).uniform(.2,.7,(100,120,3))
    placements=[(0.,0.),(-1.,2.),(2.,-3.)]
    deltas=np.array([[0,0,0],[.02,-.01,.015],[-.03,.025,.01]])
    repeats=[scene.copy(),np.roll(scene,(1,-2),axis=(0,1))+deltas[1],
             np.roll(scene,(-2,3),axis=(0,1))+deltas[2]]
    originals=[image.copy() for image in repeats]
    def verified(reference,moving,expected,radius,*,dpi):
        return expected,{'verified':True,'method':'controlled_integer_translation_fixture'}
    monkeypatch.setattr(scan_filters.acquisition_plan,'_register',verified)
    offsets=[{'dy':dy,'dx':dx} for dy,dx in placements]
    before=scan_filters.aligned_mean(repeats,offsets,dpi=300,normalize_offsets=False)
    after=scan_filters.aligned_mean(repeats,offsets,dpi=300)
    assert set(np.unique(after['counts']))=={1,2,3}
    assert np.max(np.abs(before['image']-scene))>.01
    assert np.allclose(after['image'],scene,atol=1e-14)
    normalization=after['offset_normalization']
    assert np.allclose(normalization['subtracted_rgb_deltas'],deltas,atol=1e-14)
    assert normalization['measurement_pixel_count']==int(after['full_repeat_coverage'].sum())
    assert normalization['reference_source_index']==0
    assert normalization['per_source_clipping_applied'] is False
    assert normalization['final_mean_below_zero_samples_rgb']==[0,0,0]
    assert normalization['final_mean_above_one_samples_rgb']==[0,0,0]
    assert all(np.array_equal(a,b) for a,b in zip(repeats,originals))


def test_offset_correction_does_not_clip_each_source_before_averaging_and_reports_final_clipping(monkeypatch):
    scene=np.random.default_rng(73).uniform(.005,.98,(80,90,3))
    moving=np.clip(scene-.04,0,1)
    scene[0,0]=.98
    moving[0,0]=.99  # Acquired outlier: correction can exceed TIFF's range.
    original=moving.copy()
    monkeypatch.setattr(scan_filters.acquisition_plan,'_register',
        lambda *args,**kw:((0.,0.),{'verified':True}))
    result=scan_filters.aligned_mean([scene,moving],dpi=300)
    correction=result['offset_normalization']
    assert np.allclose(correction['subtracted_rgb_deltas'][1],[-.04]*3)
    assert correction['measurement_pixel_count']<scene.shape[0]*scene.shape[1]
    assert correction['per_source_clipping_applied'] is False
    assert correction['final_mean_above_one_samples_rgb']==[1,1,1]
    assert np.array_equal(result['image'][0,0],[1,1,1])
    assert np.array_equal(original,moving)
    assert np.isfinite(result['image']).all()
    assert result['image'].min()>=0 and result['image'].max()<=1
    with pytest.raises(ValueError,match='boolean'):
        scan_filters.aligned_mean([scene,moving],normalize_offsets=1)


def test_repeat_offset_measurement_requires_common_unclipped_support(monkeypatch):
    image=np.ones((50,60,3))
    monkeypatch.setattr(scan_filters.acquisition_plan,'_register',
        lambda *args,**kw:((0.,0.),{'verified':True}))
    with pytest.raises(ValueError,match='shared unclipped'):
        scan_filters.aligned_mean([image,image])
