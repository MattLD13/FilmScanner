from services.api.developing import ClockGuard, DEMO_RECIPE, create_session, dilution, view


def test_elapsed_time_survives_reload_and_no_pause():
    session = create_session('roll', DEMO_RECIPE, 20)
    assert view(session, session['step_started_at'] + 5000)['remaining_seconds'] == 3
    assert view(session, session['step_started_at'] + 9000)['status'] == 'awaiting_user_transition'
    assert view(session, session['checkpoint_at'] - 5000)['status'] == 'interrupted'


def test_agitation_and_dilution():
    session = create_session('roll', DEMO_RECIPE, 20)
    assert view(session, session['step_started_at'] + 4000)['next_agitation_seconds'] == 2
    assert dilution(500, 9)['concentrate_ml'] == 50
    assert dilution(500, 9)['water_ml'] == 450


def test_monotonic_guard_detects_forward_and_backward_adjustments(monkeypatch):
    import services.api.developing as module
    for jump in (-5000, 5000):
        clock = {'wall': 100_000, 'mono': 10}
        monkeypatch.setattr(module, 'now', lambda: clock['wall'])
        monkeypatch.setattr(module.time, 'monotonic', lambda: clock['mono'])
        session = create_session('roll', DEMO_RECIPE, 20)
        guard = ClockGuard()
        guard.check(session)
        clock['wall'] += 1000 + jump
        clock['mono'] += 1
        assert guard.check(session)['status'] == 'interrupted'
