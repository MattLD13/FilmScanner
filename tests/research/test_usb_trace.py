"""Decode USB traces into register operations; synthetic records only, no scanner."""
from research.cyberview.analysis import usb_trace as ut

DEV = 304


def io(n, ioctl, offset, length, data='', index=0, ok=1):
    return {'n': n, 'call': 'DeviceIoControl', 'handle': DEV, 'ioctl': ioctl,
            'block': {'offset': offset, 'length': length, 'index': index}, 'data': data, 'ok': ok}


def test_register_writes_reads_and_bulk_lines_decode():
    records = [
        {'n': 0, 'call': 'hooked', 'module': 'fvc.dll', 'loaded': 1, 'slots': 5},
        {'n': 1, 'call': 'CreateFileA', 'name': r'\\.\USBSCAN0', 'handle': DEV, 'ok': 1},
        {'n': 2, 'call': 'CreateFileA', 'name': r'C:\temp\PF1800AFL.log', 'handle': 400, 'ok': 1},
        {'n': 3, 'call': 'WriteFile', 'handle': 400, 'size': 10, 'data': '00', 'done': 10, 'ok': 1},  # not the device
        io(4, 0x80002010, 0xB0, 2, 'a880'),            # SetLamp: power save
        io(5, 0x80002010, 0xB0, 2, '9700'),            # GetStatus: page 0
        io(6, 0x80002010, 0xB0, 1, '8b'),              # select status
        io(7, 0x8000200C, 0x07, 1, '0e'),              # read it back
        io(8, 0x80002010, 0xC0, 1, '00', index=0x8406),
        io(9, 0x80002010, 0x03, 1, '00', index=8064),  # ask for one 2688 x 3 line
        {'n': 10, 'call': 'ReadFile', 'handle': DEV, 'size': 8064, 'overlapped': 1, 'ok': 0, 'error': 997},
        {'n': 11, 'call': 'GetOverlappedResult', 'handle': DEV, 'done': 8064, 'data': 'ff' * 64, 'ok': 1},
        {'n': 12, 'call': 'CloseHandle', 'handle': DEV, 'ok': 1},
    ]
    ops = ut.decode(records)
    kinds = [op['op'] for op in ops]
    assert kinds == ['open', 'write', 'write', 'select', 'read', 'fifo_clean', 'bulk_in_request', 'bulk_in', 'close']
    assert ops[1] == {'n': 4, 'ok': True, 'op': 'write', 'reg': 0xa8, 'value': 0x80, 'name': 'power save'}
    assert ops[4]['reg'] == 0x8b and ops[4]['value'] == 0x0e and ops[4]['name'].startswith('status')
    assert ops[6]['bytes'] == 8064 and ops[7]['bytes'] == 8064
    assert ut.describe(ops[1]).startswith('W 0xa8 = 0x80')
    totals = ut.summary(ops)
    assert totals['bulk_in_bytes'] == 8064 and totals['failed'] == 0
    assert totals['final_registers']['0x97 status page select'] == '0x00'


def test_table_uploads_carry_their_ram_location():
    table = bytes(range(256)) * 16
    records = [
        {'n': 1, 'call': 'CreateFileA', 'name': r'\\.\USBSCAN0', 'handle': DEV, 'ok': 1},
        io(2, 0x80002010, 0xB0, 2, '9441'),
        io(3, 0x80002010, 0xB0, 2, 'b000'), io(4, 0x80002010, 0xB0, 2, 'b140'), io(5, 0x80002010, 0xB0, 2, 'b21f'),
        io(6, 0x80002010, 0xB0, 2, 'b3ff'), io(7, 0x80002010, 0xB0, 2, 'b4ff'), io(8, 0x80002010, 0xB0, 2, 'b51f'),
        io(9, 0x80002010, 0x02, 1, '02', index=len(table)),
        {'n': 10, 'call': 'WriteFile', 'handle': DEV, 'size': len(table), 'data': table.hex(), 'done': len(table), 'ok': 1},
    ]
    [t] = ut.tables(ut.decode(records))
    assert t['ram_select'] == 0x41 and t['start'] == 0x1f4000 and t['end'] == 0x1fffff
    assert t['complete'] and t['data'] == table


def test_phases_split_a_session_at_each_auto_scan_start():
    records = [
        {'n': 1, 'ms': 0.0, 'call': 'CreateFileA', 'name': r'\\.\USBSCAN0', 'handle': DEV, 'ok': 1},
        dict(io(2, 0x80002010, 0xB0, 2, '9001'), ms=60000.0),                  # first pass after 60 s
        {'n': 3, 'ms': 61000.0, 'call': 'ReadFile', 'handle': DEV, 'size': 16512, 'overlapped': 0, 'done': 16512, 'data': '', 'ok': 1},
        dict(io(4, 0x80002010, 0xB0, 2, '9001'), ms=63000.0),
        {'n': 5, 'ms': 64000.0, 'call': 'ReadFile', 'handle': DEV, 'size': 14874, 'overlapped': 0, 'done': 14874, 'data': '', 'ok': 1},
        {'n': 6, 'ms': 65000.0, 'call': 'ReadFile', 'handle': DEV, 'size': 224, 'overlapped': 0, 'done': 224, 'data': '', 'ok': 1},
    ]
    first, image = ut.phases(records)
    assert first == {'start_s': 60.0, 'setup_before_s': 60.0, 'reads': 1, 'line_bytes': 16512, 'end_s': 61.0}
    assert image['setup_before_s'] == 2.0 and image['reads'] == 2 and image['line_bytes'] == 14874
