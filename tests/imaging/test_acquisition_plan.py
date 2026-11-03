"""Acquisition planning and strict stitch evidence, entirely synthetic."""
import copy

import numpy as np
import pytest

from services.imaging import acquisition_plan as ap


def preview_record(*, wide=False, vertical='none'):
    offsets = [{'dx': 0., 'dy': 0.}]
    sources = [{'label': 'centre', 'width': 430, 'height': 284, 'dpi': 300, 'position_steps': 0}]
    if wide:
        offsets.append({'dx': 80., 'dy': 2.})
        sources.append({'label': 'forward', 'width': 430, 'height': 284, 'dpi': 300, 'position_steps': 20})
    return {'id': 'synthetic-preview', 'dpi': 300, 'width': 510 if wide else 430, 'height': 286 if wide else 284,
            'alignment': {'edges_x': {'found': 'both', 'start': 10, 'end': 500 if wide else 410},
                          'edges_y': {'found': vertical, 'start': 6, 'end': 278} if vertical == 'both' else {'found': vertical}},
            'derived': {'sources': sources, 'offsets_px': offsets, 'final_position_steps': 20 if wide else 0}}


def test_single_window_needs_borders_plus_rebate_and_axis_padding():
    record = preview_record(vertical='both')
    before = copy.deepcopy(record)
    plan = ap.plan_archival(record)
    assert len(plan['tiles']) == 1
    assert plan['padding_highres_px'] == {'x': 18., 'y': 18.}
    assert plan['padding_preview_px']['x'] == pytest.approx(.15 / 25.4 * 300 + 18 / ap.SCALE_X)
    assert plan['vertical_containment']['status'] == 'verified'
    assert record == before


def test_two_windows_cover_padded_frame_with_measured_optical_offsets():
    plan = ap.plan_archival(preview_record(wide=True))
    assert len(plan['tiles']) == 2
    assert [tile['position_steps'] for tile in plan['tiles']] == [0, 20]
    assert [tile['dx'] for tile in plan['tiles']] == [0, 80]
    assert plan['vertical_containment']['status'] == 'unknown'


def test_missing_rebate_and_insufficient_measured_coverage_stop_before_archival():
    record = preview_record()
    record['alignment']['edges_x']['start'] = 1
    with pytest.raises(ValueError, match='UNVERIFIED_PREVIEW_COVERAGE'):
        ap.plan_archival(record)
    record['alignment']['edges_x']['found'] = 'end'
    with pytest.raises(ValueError, match='both measured side borders'):
        ap.plan_archival(record)


def test_pair_with_inadequate_overlap_is_rejected():
    record = preview_record(wide=True)
    record['derived']['offsets_px'][1]['dx'] = 400
    record['alignment']['edges_x']['end'] = 820
    with pytest.raises(ValueError, match='sufficient overlap'):
        ap.plan_archival(record)


def test_ceil_rounded_mosaic_margin_does_not_replace_actual_source_coverage():
    # Actual failed fourth-frame geometry: ceil(481.68)=482 looks padded,
    # while the source ends0.086px before the required481.766 bound.
    record={'dpi':300,'width':482,'height':285,
        'alignment':{'edges_x':{'found':'both','start':38,'end':477},'edges_y':{'found':'none'}},
        'derived':{'sources':[
            {'label':'centre','width':430,'height':284,'dpi':300,'position_steps':0},
            {'label':'back','width':430,'height':284,'dpi':300,'position_steps':-20},
            {'label':'forward','width':430,'height':284,'dpi':300,'position_steps':20}],
            'offsets_px':[{'dx':0,'dy':0},{'dx':-22.7,'dy':-.17},{'dx':28.98,'dy':.64}],
            'final_position_steps':0}}
    padding=ap.preview_padding()['x']
    assert record['width']-477>=padding
    assert 28.98+22.7+430-477<padding
    with pytest.raises(ValueError,match='UNVERIFIED_PREVIEW_COVERAGE'):
        ap.plan_archival(record)
    record['derived']['sources'].append({'label':'probe','width':430,'height':284,'dpi':300,'position_steps':40})
    record['derived']['offsets_px'].append({'dx':57,'dy':.5})
    assert len(ap.plan_archival(record)['tiles'])==2


def test_vertical_clipping_is_reported_separately_without_claiming_complete_frame():
    record = preview_record(vertical='both')
    record['alignment']['edges_y'].update(start=1, end=283)
    plan = ap.plan_archival(record)
    assert plan['vertical_containment']['status'] == 'unverified'


def scene_tiles(dx=114, dy=3):
    height, width = 320, 600
    random = np.random.default_rng(12)
    scene = .3 + .15 * random.random((height + abs(dy) + 20, width + dx + 20, 3))
    return [scene[:height, :width].astype(np.float32), scene[dy:dy + height, dx:dx + width].astype(np.float32)]


def test_stitch_measures_within_optical_prediction_and_keeps_input_tiles_unchanged():
    plan = ap.plan_archival(preview_record(wide=True))
    images = scene_tiles()
    before = [image.copy() for image in images]
    stitched = ap.stitch_planned(images, plan)
    assert stitched['alignment_verified']
    assert stitched['offsets_px'][1]['dx'] == pytest.approx(114, abs=.2)
    assert stitched['offsets_px'][1]['dy'] == pytest.approx(3, abs=.2)
    assert stitched['registration'][0]['peak_ratio'] >= ap.PEAK_RATIO_MINIMUM
    assert stitched['covered'].shape == stitched['image'].shape[:2]
    assert all(np.array_equal(a, b) for a, b in zip(images, before))


def test_flat_scene_and_shift_outside_predicted_uncertainty_fail_safely():
    plan = ap.plan_archival(preview_record(wide=True))
    with pytest.raises(ValueError, match='UNVERIFIED_STITCH_ALIGNMENT.*texture'):
        ap.stitch_planned([np.full((320, 600, 3), .3)] * 2, plan)
    with pytest.raises(ValueError, match='UNVERIFIED_STITCH_ALIGNMENT'):
        ap.stitch_planned(scene_tiles(dx=160), plan)


def test_periodic_texture_does_not_silently_publish_an_ambiguous_seam():
    plan = ap.plan_archival(preview_record(wide=True))
    yy, xx = np.mgrid[:340, :760]
    wave = .4 + .12 * np.sin(xx * np.pi / 4) + .10 * np.sin(yy * np.pi / 4)
    image = np.repeat(wave[..., None], 3, axis=2)
    with pytest.raises(ValueError, match='UNVERIFIED_STITCH_ALIGNMENT'):
        ap.stitch_planned([image[:320, :600], image[3:323, 114:714]], plan)


def test_preview_registration_recovers_strong_seek_error_beyond_cross_resolution_pad():
    random = np.random.default_rng(27)
    image = .2 + .4 * random.random((310, 480, 3))
    reference = image[:284, :430]
    moving = image[5:289, 17:447]
    evidence = ap.register_preview(reference, moving)
    assert evidence['verified']
    assert evidence['dx'] == pytest.approx(17, abs=.2)
    assert evidence['dy'] == pytest.approx(5, abs=.2)
    assert evidence['peak_ratio'] >= ap.PEAK_RATIO_MINIMUM


def test_preview_registration_rejects_low_texture_and_out_of_bound_displacement():
    with pytest.raises(ValueError, match='UNVERIFIED_PREVIEW_ALIGNMENT.*texture'):
        ap.register_preview(np.full((284, 430, 3), .3), np.full((284, 430, 3), .3))
    random = np.random.default_rng(14)
    image = random.random((284, 520, 3))
    with pytest.raises(ValueError, match='UNVERIFIED_PREVIEW_ALIGNMENT'):
        ap.register_preview(image[:, :430], image[:, 70:500])


def test_preview_registration_rejects_repeated_texture_and_invalid_inputs():
    yy, xx = np.mgrid[:310, :480]
    wave = .4 + .12 * np.sin(xx * np.pi / 4) + .1 * np.sin(yy * np.pi / 4)
    image = np.repeat(wave[..., None], 3, axis=2)
    with pytest.raises(ValueError, match='UNVERIFIED_PREVIEW_ALIGNMENT'):
        ap.register_preview(image[:284, :430], image[3:287, 8:438])
    with pytest.raises(ValueError, match='UNVERIFIED_PREVIEW_ALIGNMENT'):
        ap.register_preview(image[:284, :430], image[:284, :430], max_shift_mm=float('nan'))
