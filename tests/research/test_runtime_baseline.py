"""Kernel-trace summarizer fixtures and the tracked no-device CyberView baseline.

The baseline JSON is GUEST OBSERVED evidence from the isolated Server 2008
evaluation guest with no scanner attached; it is not device behavior.
"""
import json
from pathlib import Path

from research.cyberview.analysis.kernel_trace import first_events, module_outcomes, parse_line

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / 'research/cyberview/analysis/evidence/runtime-baseline-2026-10-28.json').read_text())
STATIC = json.loads((ROOT / 'research/cyberview/analysis/scan08-evidence.json').read_text())


def _row(event, kind, timestamp, path, pid='0x00000A40'):
    fields = [event, kind, '0', '2', '0', '0', '64', '0', '0x0', pid, '0xFFFFFFFF', '1', '', '', '{0}', '',
              str(timestamp), '0', '0']
    return '  ' + ', '.join(fields) + f', "{path}"'


def test_parse_line_reads_event_pid_time_and_path_and_skips_headers():
    row = parse_line(_row('FileIo', 'Create', 134376506296488673, r'\Device\X\EXAMPLE.dll'))
    assert row == {'event': 'FileIo', 'type': 'Create', 'pid': 0xA40,
                   'timestamp': 134376506296488673, 'path': r'\Device\X\EXAMPLE.dll'}
    assert parse_line('Event Name, Type, Event ID') is None


def test_first_events_orders_and_marks_missing_modules():
    # Fictitious module names; a missing module has opens and no image load.
    lines = [_row('FileIo', 'Create', 30_000_000, r'\Device\X\app\GONE.dll'),
             _row('FileIo', 'Create', 31_000_000, r'\Device\X\sys\GONE.dll'),
             _row('FileIo', 'Create', 10_000_000, r'\Device\X\app\HERE.dll'),
             _row('Image', 'Load', 11_000_000, r'\app\HERE.dll'),
             _row('FileIo', 'Create', 12_000_000, r'\Device\X\app\here.dll'),
             _row('FileIo', 'Read', 13_000_000, r'\Device\X\app\GONE.dll'),
             _row('FileIo', 'Create', 14_000_000, r'\Device\X\app\OTHER.txt')]
    events = first_events(lines, r'\.dll$')
    assert [e['timestamp'] for e in events] == [10_000_000, 11_000_000, 30_000_000, 31_000_000]
    assert events[0]['seconds'] == 0 and events[-1]['seconds'] == 2.1
    outcomes = module_outcomes(events)
    assert outcomes['here.dll'] == {'open_paths': 1, 'image_loaded': True, 'loaded_from': r'\app\HERE.dll'}
    assert outcomes['gone.dll'] == {'open_paths': 2, 'image_loaded': False, 'loaded_from': None}


def test_no_device_baseline_requests_scan08_and_never_loads_it():
    assert BASELINE['evidence'] == 'GUEST OBSERVED' and BASELINE['guest']['scanner_attached'] is False
    assert BASELINE['install']['scan08_dll_installed'] is False
    assert BASELINE['install']['driver_install_prompts'] == 0
    assert BASELINE['modules']['scan08.dll'] == {'open_paths': 5, 'image_loaded': False, 'loaded_from': None}
    assert BASELINE['scan08_open_attempts'][0] == '\\Windows\\Twain_32\\CyberViewX_SF\\SCAN08.dll'
    assert 'Unable to communicate with the Film Scanner' in BASELINE['launch']['dialog']


def test_runtime_probe_order_is_the_static_benescan_table_walked_downward():
    table = sorted(STATIC['benescan_model_table'], key=lambda r: r['index'], reverse=True)
    expected = [r['module'].casefold() for r in table if r['index'] >= 1]
    assert [name.casefold() for name in BASELINE['model_probe_order']] == expected
    present = {r['module'].casefold() for r in table if r['present_in_payload']}
    for module, outcome in BASELINE['modules'].items():
        assert outcome['image_loaded'] == (module in present), module
