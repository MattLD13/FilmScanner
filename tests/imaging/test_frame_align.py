"""Auto-align: stitch nudged scans, find the 35 mm frame, crop exactly 36 x 24 mm."""
import numpy as np
import pytest
from services.imaging import film_type_detection

from services.imaging import frame_align as fa

DPI = 600  # small images keep the tests fast; geometry scales with dpi


def strip(frames=3, gap_mm=2.0, rebate_mm=1.0, seed=0, transmission=True, frame_size=(36, 24)):
    """A negative strip as transmission: bright bare base between frames, textured pictures."""
    rng = np.random.default_rng(seed)
    fw, fh = fa.mm_to_px(frame_size[0], DPI), fa.mm_to_px(frame_size[1], DPI)
    gap, reb = fa.mm_to_px(gap_mm, DPI), fa.mm_to_px(rebate_mm, DPI)
    width = int(round(frames * fw + (frames + 1) * gap)); height = int(round(fh + 2 * reb))
    img = np.full((height, width, 3), [.85, .55, .35])  # orange mask base, bright in transmission
    lefts = []
    for f in range(frames):
        x0 = int(round(gap + f * (fw + gap))); y0 = int(round(reb))
        x1, y1 = int(round(x0 + fw)), int(round(y0 + fh))
        yy, xx = np.mgrid[y0:y1, x0:x1]
        scene = .25 + .12 * np.sin(xx / 17.0 + f) * np.cos(yy / 23.0) + .05 * rng.standard_normal(xx.shape)
        img[y0:y1, x0:x1] = np.clip(scene[..., None] * [1.0, .8, .6], 0, 1)
        lefts.append(x0)
    img = np.clip(img + .01 * rng.standard_normal(img.shape), 0, 1)
    return (img if transmission else 1 - img), lefts, int(round(reb))


def window(img, x0, width, y0=0, height=None, gain=1.0):
    height = height or img.shape[0]
    return np.clip(img[y0:y0 + height, x0:x0 + width] * gain, 0, 1)


def test_single_full_window_finds_both_edges_and_crops_exactly():
    img, lefts, top = strip()
    fw = fa.mm_to_px(36, DPI)
    # A 37.5 mm window around the middle frame, 0.3 mm off-centre.
    x0 = int(round(lefts[1] - fa.mm_to_px(.45, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(37.5, DPI))))
    result = fa.align_35mm(scan, DPI, transmission=True)
    assert result['confidence'] == 'frame_found'
    assert abs(result['x']['start'] - (lefts[1] - x0)) <= 2
    assert abs(result['x']['measured_mm'] - 36) < .2
    assert result['exact'] and result['crop_mm'][0] == pytest.approx(36, abs=.05)
    assert result['crop_px']['left'] == pytest.approx(lefts[1] - x0, abs=2)
    assert abs(result['skew_deg']) < .3


@pytest.mark.parametrize('supported_rebate',[True,False])
def test_high_resolution_rebate_hysteresis_requires_strong_uniform_seeds(supported_rebate):
    dpi=1800;height=200;width=2755
    y=np.linspace(-1,1,height)[:,None]
    image=np.repeat((.29+.035*np.sin(np.arange(width)/51))[None,:,None],height,axis=0)
    image=np.repeat(image,3,axis=2)
    image[:,:66]=.89
    # Deliberately narrow final rebate followed by white scanner-edge pixels.
    # At1800DPI the true rebate is long enough but the strict spread test is
    # fragmented by harmless fluctuations around its .1 cutoff.
    image[:,2705:2734]=.87+y[:,:,None]*.096
    for column in range(2705,2734):
        if supported_rebate and column%3!=0:image[:,column]=.87+y*.08
    image[:,2734:2739]=.87+y[:,:,None]*.2
    image[:,2739:]=.994
    result=fa._edges_along(image @ fa.LUMA,np.ones((height,width),bool),1,fa.mm_to_px(36,dpi),dpi)
    if supported_rebate:
        assert result['found']=='both'
        assert abs(result['end']-2705)<=4
    else:
        assert result['found']!='both', 'A weak-only patch must not establish an exposure border'


def test_film_detection_accounts_for_relative_channel_exposure_without_changing_pixels():
    image,_,_=strip(frame_size=(34.5,24),frames=1)
    exposure=[100,155,260]
    acquired=image*np.array(exposure)/100
    acquired=np.clip(acquired,0,1)
    original=acquired.copy()
    result=film_type_detection.detect(acquired,DPI,exposure=exposure)
    assert result['film_type']=='color_negative' and result['confidence']>=.8
    assert result['exposure_normalization']['applied'] is True
    assert np.array_equal(acquired,original)
    with pytest.raises(ValueError,match='exposures'):
        film_type_detection.detect(acquired,DPI,exposure=[100,0,100])


def test_rebate_witness_requires_both_edges_and_minimum_acquired_margin():
    alignment = {'x': {'found': 'both', 'start': 30, 'end': 570}}
    safe = fa.rebate_witness(alignment, 600, DPI, minimum_mm=.5)
    assert safe['verified'] and safe['left_margin_mm'] == pytest.approx(1.27)
    assert not fa.rebate_witness({'x': {'found': 'both', 'start': 2, 'end': 598}}, 600, DPI, .5)['verified']
    assert not fa.rebate_witness({'x': {'found': 'start', 'start': 30}}, 600, DPI, .5)['verified']


def test_positive_polarity_and_bleed():
    img, lefts, top = strip(transmission=False)
    x0 = int(round(lefts[1] - fa.mm_to_px(1, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(38.5, DPI))))
    tight = fa.align_35mm(scan, DPI, transmission=False, bleed_mm=-.5)
    assert tight['confidence'] == 'frame_found'
    # Border localization is within two pixels; bleed trims the measured bounds.
    assert tight['crop_mm'] == pytest.approx([35, 23], abs=2 * fa.MM_PER_INCH / DPI)
    assert tight['crop_basis'] == {'x': 'detected_borders', 'y': 'detected_borders'}
    assert tight['crop_px']['left'] == pytest.approx(lefts[1] - x0 + fa.mm_to_px(.5, DPI), abs=2)


@pytest.mark.parametrize('frame_size', [(35.4, 23.6), (36.6, 24.4), (37.2, 24.0)])
def test_crop_uses_actual_frame_borders_instead_of_forcing_nominal_dimensions(frame_size):
    img, lefts, top = strip(frame_size=frame_size)
    x0 = int(round(lefts[1] - fa.mm_to_px(1, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(39, DPI))))
    result = fa.align_35mm(scan, DPI, transmission=True)
    assert result['exact'] and result['confidence'] == 'frame_found'
    assert result['crop_basis'] == {'x': 'detected_borders', 'y': 'detected_borders'}
    assert result['crop_mm'] == pytest.approx(frame_size, abs=2 * fa.MM_PER_INCH / DPI)
    c = result['crop_px']
    assert c['left'] == result['x']['start']
    assert c['left'] + c['width'] == result['x']['end']
    assert c['top'] == result['y']['start']
    assert c['top'] + c['height'] == result['y']['end']


@pytest.mark.parametrize('transmission', [True, False])
def test_two_frame_strip_with_central_gap_finds_a_complete_frame(transmission):
    img, lefts, top = strip(frames=2, transmission=transmission)
    before = img.copy()
    result = fa.align_35mm(img, DPI, transmission=transmission)
    assert result['confidence'] == 'frame_found' and result['exact']
    assert min(abs(result['x']['start'] - left) for left in lefts) <= 2
    assert result['x']['end'] - result['x']['start'] == pytest.approx(fa.mm_to_px(36, DPI), abs=2)
    assert result['crop_px']['left'] == pytest.approx(result['x']['start'], abs=2)
    assert len(result['x']['frames']) == 2
    for detected, left in zip(result['x']['frames'], lefts):
        assert detected['start'] == pytest.approx(left, abs=2)
        assert detected['end'] == pytest.approx(left + fa.mm_to_px(36, DPI), abs=2)
    np.testing.assert_array_equal(img, before)


def test_three_nudged_scans_are_stitched_from_image_content():
    img, lefts, top = strip(seed=3)
    win_w = int(round(fa.mm_to_px(36.5, DPI)))                 # the module's maximum window
    centre = int(round(lefts[1] + fa.mm_to_px(36, DPI) / 2 - win_w / 2 + fa.mm_to_px(.9, DPI)))  # AFL lands 0.9 mm off
    nominal = fa.mm_to_px(1.5, DPI)
    actual = [-nominal * 1.08, 0, nominal * .93]               # the motor does not move exactly as asked
    gains = [1.06, 1.0, .95]                                   # CyberView auto exposure varies per scan
    scans = [window(img, int(round(centre + a)), win_w, gain=g) for a, g in zip(actual, gains)]
    single = fa.align_35mm(scans[1], DPI, transmission=True)
    assert single['x']['found'] != 'both'                      # one window cannot see both gaps here
    result = fa.stitch(scans, [-nominal, 0, nominal])
    measured = [o['dx'] for o in result['offsets_px']]
    for got, want in zip(measured, actual):
        assert got == pytest.approx(want, abs=1.0)
    assert result['gains'][0][0] == pytest.approx(1 / 1.06, abs=.03)
    aligned = fa.align_35mm(result['image'], DPI, transmission=True, covered=result['covered'])
    assert aligned['confidence'] == 'frame_found' and aligned['exact']
    origin = centre + min(measured)                            # mosaic x=0 in strip coordinates
    assert aligned['crop_px']['left'] + origin == pytest.approx(lefts[1], abs=2)


def test_a_sliver_of_the_previous_frame_does_not_capture_the_alignment():
    # Seen on real CyberView scans: picture of the previous frame, then the gap, then ours.
    img, lefts, top = strip(transmission=False)
    fw, gap = fa.mm_to_px(36, DPI), fa.mm_to_px(2, DPI)
    x0 = int(round(lefts[1] - gap - fa.mm_to_px(.8, DPI)))   # 0.8 mm of frame 0 visible
    scan = window(img, x0, int(round(fa.mm_to_px(36.5, DPI))))
    result = fa.align_35mm(scan, DPI, transmission=False)
    assert result['x']['found'] == 'start'
    assert result['x']['start'] == pytest.approx(lefts[1] - x0, abs=2)
    assert result['crop_px']['left'] == pytest.approx(lefts[1] - x0, abs=2) or not result['exact']


def test_no_edges_falls_back_to_centre_and_says_so():
    img, lefts, top = strip()
    inner = window(img, lefts[1] + 20, int(round(fa.mm_to_px(36.5, DPI))) - 40, y0=top, height=int(fa.mm_to_px(24, DPI)))
    result = fa.align_35mm(inner, DPI, transmission=True)
    assert result['confidence'] == 'centered' and not result['exact']
    assert 'smaller than' in result['note']


def test_bleed_is_bounded():
    with pytest.raises(ValueError):
        fa.align_35mm(np.zeros((10, 10, 3)), DPI, True, bleed_mm=3)


def test_nominal_exact_dimensions_do_not_hide_missing_acquired_pixels():
    img, lefts, top = strip(seed=13)
    x0 = int(round(lefts[1] - fa.mm_to_px(1, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(38.5, DPI))))
    original = fa.align_35mm(scan, DPI, transmission=True)
    assert original['exact'] and original['dimensions_exact']
    c = original['crop_px']
    mask = np.ones(scan.shape[:2], bool)
    mask[c['top'] + c['height'] // 2, c['left'] + c['width'] // 2] = False
    result = fa.align_35mm(scan, DPI, transmission=True, covered=mask)
    assert result['dimensions_exact'] and not result['exact']
    assert result['missing_pixels'] == 1
    assert result['coverage_fraction'] == pytest.approx(1 - 1 / (c['width'] * c['height']))
    assert 'unacquired pixels' in result['note']
    assert 'not applied' in result['note']


@pytest.mark.filterwarnings('error::RuntimeWarning')
def test_uncovered_mosaic_margin_outside_crop_does_not_make_crop_inexact():
    img, lefts, top = strip(seed=13)
    x0 = int(round(lefts[1] - fa.mm_to_px(1, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(38.5, DPI))))
    mask = np.ones(scan.shape[:2], bool)
    mask[:, :4] = False
    result = fa.align_35mm(scan, DPI, True, covered=mask)
    assert result['exact'] and result['missing_pixels'] == 0
    assert result['coverage_fraction'] == 1
    with pytest.raises(ValueError, match='Coverage'):
        fa.align_35mm(scan, DPI, True, covered=np.ones((2, 3), bool))


def test_ragged_stitch_edges_are_filled_and_still_crop_exactly():
    # Seen on the scanner 2026-10-31: the forward scan sat 8 px lower, leaving 272 corner
    # pixels outside every scan. Those edge pixels are filled; a hole inside is not.
    img, lefts, top = strip(seed=13)
    x0 = int(round(lefts[1] - fa.mm_to_px(1, DPI)))
    scan = window(img, x0, int(round(fa.mm_to_px(38.5, DPI))))
    c = fa.align_35mm(scan, DPI, transmission=True)['crop_px']
    mask = np.ones(scan.shape[:2], bool)
    # Left columns start 3 rows low, right columns end 3 rows high: no slide avoids both.
    mask[:c['top'] + 3, c['left']:c['left'] + 20] = False
    mask[c['top'] + c['height'] - 3:, c['left'] + c['width'] - 20:c['left'] + c['width']] = False
    result = fa.align_35mm(scan, DPI, transmission=True, covered=mask)
    assert result['exact'] and result['filled_pixels'] == result['missing_pixels'] > 0
    assert 'filled from the nearest scanned row' in result['note']
