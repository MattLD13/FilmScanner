import time
import uuid


def now():
    return int(time.time() * 1000)


DEMO_RECIPE = {
    'id': 'demo-bw-v1', 'name': 'Practice in the light', 'version': 1,
    'manufacturer': 'FRAME demonstration only', 'chemistry': 'Water rehearsal — no chemicals',
    'source': 'FRAME test fixture, not a manufacturer recipe. Never use these short timings for film.',
    'verified': False, 'demo': True, 'temperature': 20,
    'steps': [{'name': 'Practice developer', 'duration_seconds': 8, 'agitation_seconds': 3},
              {'name': 'Practice rinse', 'duration_seconds': 5, 'agitation_seconds': 0},
              {'name': 'Practice fixer', 'duration_seconds': 6, 'agitation_seconds': 3}],
}


def create_session(roll_id, recipe, temperature):
    stamp = now()
    return {'id': uuid.uuid4().hex, 'roll_id': roll_id, 'recipe_id': recipe['id'], 'recipe': recipe,
            'status': 'running', 'step_index': 0, 'started_at': stamp, 'step_started_at': stamp,
            'steps': recipe['steps'], 'temperature': temperature,
            'events': [{'type': 'confirmed_start', 'at': stamp, 'step': 0}], 'checkpoint_at': stamp}


def view(session, stamp=None):
    item = dict(session)
    stamp = now() if stamp is None else stamp
    if item['status'] in ('running', 'awaiting_user_transition'):
        elapsed = (stamp - item['step_started_at']) / 1000
        duration = item['steps'][item['step_index']]['duration_seconds']
        item['remaining_seconds'] = max(0, duration - elapsed)
        if stamp < item['checkpoint_at'] - 2000:
            item['status'] = 'interrupted'
            item['clock_warning'] = 'Clock moved backwards. Review physical development before continuing.'
        elif elapsed >= duration:
            item['status'] = 'awaiting_user_transition'
        agitation = item['steps'][item['step_index']]['agitation_seconds']
        item['next_agitation_seconds'] = max(0, agitation - elapsed % agitation) if agitation and elapsed < duration else None
    return item


def transition(session):
    item = view(session)
    if item['status'] != 'awaiting_user_transition':
        raise ValueError('Wait for the step deadline and review any clock warning before confirming transition')
    stamp = now()
    item['events'].append({'type': 'confirmed_transition', 'at': stamp, 'step': item['step_index'],
                           'actual_duration_seconds': (stamp - item['step_started_at']) / 1000})
    if item['step_index'] + 1 == len(item['steps']):
        item['status'] = 'completed'
        item['completed_at'] = stamp
    else:
        item['step_index'] += 1
        item['step_started_at'] = stamp
        item['status'] = 'running'
    item['checkpoint_at'] = stamp
    return item


def dilution(total_ml, parts_water):
    if total_ml <= 0 or parts_water < 0:
        raise ValueError('Volumes must be positive and water parts nonnegative')
    concentrate = round(total_ml / (parts_water + 1), 2)
    return {'concentrate_ml': concentrate, 'water_ml': round(total_ml - concentrate, 2), 'rounding': '0.01 mL; water is the remainder'}


class ClockGuard:
    """Compare the authoritative service clock with monotonic elapsed time.

    Wall timestamps permit restarts; the monotonic reference detects adjustments
    while the service runs. Long unobserved restarts require an explicit review.
    """
    def __init__(self):
        self.observed = {}

    def check(self, session):
        if session['status'] not in ('running', 'awaiting_user_transition'):
            return session
        wall, monotonic = now(), time.monotonic()
        previous = self.observed.get(session['id'])
        uncertain = False
        if previous:
            expected = previous[0] + (monotonic - previous[1]) * 1000
            uncertain = abs(wall - expected) > 2000
        elif wall < session['checkpoint_at'] - 2000 or wall - session['checkpoint_at'] > 86_400_000:
            uncertain = True
        self.observed[session['id']] = (wall, monotonic)
        if uncertain:
            session['status'] = 'interrupted'
            session['clock_warning'] = 'Device clock changed or session was unobserved for over a day. Review the physical step before continuing.'
            session['events'].append({'type': 'clock_discontinuity', 'at': wall})
        session['checkpoint_at'] = wall
        return session
