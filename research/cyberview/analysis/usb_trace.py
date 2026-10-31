"""Decode a PF1800 AFL USB trace (services/native_bridge/usbtrace.h) into protocol operations.

The wire mapping comes from disassembly of IO_PORT.dll (USB transport, case 4 of
0x10002640) and FVC.dll (SystemRequest), see docs/scanner-protocol.md:

  register write  IOCTL_WRITE_REGISTERS  offset 0xB0, data [reg, value]
  register select IOCTL_WRITE_REGISTERS  offset 0xB0, data [reg]
  register read   IOCTL_READ_REGISTERS   offset 0x07, 1 byte   (value of the selected reg)
  bulk-in request IOCTL_WRITE_REGISTERS  offset 0x03, index = byte count, then ReadFile
  bulk-out notice IOCTL_WRITE_REGISTERS  offset 0x02, index = byte count, then WriteFile
  FIFO clean      IOCTL_WRITE_REGISTERS  offset 0xC0, index 0x8406 then 0x0406

Usage: python usb_trace.py TRACE.jsonl [--summary | --phases | --tables OUT_DIR]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

IOCTL = {0x80002008: 'WAIT_ON_DEVICE_EVENT', 0x8000200C: 'READ_REGISTERS', 0x80002010: 'WRITE_REGISTERS',
         0x80002018: 'GET_DEVICE_DESCRIPTOR', 0x80002004: 'GET_PIPE_CONFIGURATION', 0x8000201C: 'RESET_PIPE'}

# Register names from the SQ_Scan export that writes each one (static analysis).
REGISTERS = {
    0x00: 'AFE reg 0', 0x01: 'AFE setup 1', 0x02: 'AFE setup 2', 0x03: 'AFE setup 3', 0x04: 'AFE reset', 0x05: 'AFE setup 4',
    0x20: 'AFE offset R', 0x21: 'AFE offset G', 0x22: 'AFE offset B', 0x24: 'AFE offset 24', 0x25: 'AFE offset 25', 0x26: 'AFE offset 26',
    0x28: 'AFE gain R', 0x29: 'AFE gain G', 0x2a: 'AFE gain B',
    0x80: 'motor/scan control', 0x82: 'motor run', 0x83: 'index for 0x85/0x87/0x8d', 0x84: 'motor steps lo',
    0x85: 'scan acc/dec data (indexed)', 0x86: 'motor commit', 0x87: 'CCD pixel number (indexed)', 0x88: 'motor speed',
    0x89: 'motor steps hi', 0x8b: 'status (page in 0x97)', 0x8d: 'lamp data (indexed)', 0x8e: 'auto-scan option',
    0x8f: 'RAM data port', 0x90: 'auto-scan start', 0x91: 'auto-scan 0x91', 0x93: 'lamp mode', 0x94: 'RAM select',
    0x97: 'status page select', 0x98: 'line offset R', 0x99: 'line offset G', 0x9a: 'line offset B', 0x9b: 'line offset index',
    0x9c: 'CCD timing 9c', 0x9d: 'CCD timing 9d', 0x9e: 'CCD timing 9e', 0x9f: 'CCD timing 9f', 0xa0: 'CCD timing a0',
    0xa1: 'GPIO a1', 0xa2: 'GPIO a2', 0xa3: 'GPIO a3', 0xa4: 'GPIO a4', 0xa5: 'CCD timing a5', 0xa6: 'CCD timing a6',
    0xa7: 'CCD timing a7', 0xa8: 'power save', 0xb0: 'RAM address 0', 0xb1: 'RAM address 1', 0xb2: 'RAM address 2',
    0xb3: 'RAM end 0', 0xb4: 'RAM end 1', 0xb5: 'RAM end 2', 0xb6: 'buffer range b6', 0xb7: 'buffer range b7',
    0xb8: 'buffer range b8', 0xb9: 'buffer range b9', 0xbb: 'auto-scan bb', 0xbc: 'scan acc bc', 0xbd: 'scan acc bd',
    0xbe: 'auto-scan be', 0xbf: 'auto-scan bf', 0xc0: 'motor acc/dec enable', 0xc1: 'acc/dec c1', 0xc2: 'acc/dec c2',
    0xc3: 'acc/dec c3', 0xc4: 'acc/dec c4', 0xc5: 'acc/dec c5', 0xc6: 'acc/dec c6', 0xc7: 'acc/dec c7', 0xc8: 'acc/dec c8',
    0xce: 'driving capability ce', 0xcf: 'driving capability / status page hi',
}


def reg_name(reg: int) -> str:
    return REGISTERS.get(reg, 'unknown')


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def decode(records: list[dict]) -> list[dict]:
    """One operation per device call, in order. Calls on non-device handles are dropped."""
    devices, ops, selected = set(), [], None
    for r in records:
        call = r.get('call')
        if call == 'CreateFileA':
            if r.get('ok') and r.get('name', '').upper().startswith('\\\\.\\USBSCAN'):
                devices.add(r['handle'])
                ops.append({'n': r['n'], 'op': 'open', 'name': r['name']})
            continue
        if r.get('handle') not in devices:
            continue
        data = bytes.fromhex(r.get('data', '') or '')
        if call == 'DeviceIoControl':
            code = r['ioctl']; block = r.get('block') or {}
            offset, index, length = block.get('offset'), block.get('index'), block.get('length')
            op = {'n': r['n'], 'ok': bool(r.get('ok'))}
            if code == 0x80002010 and offset == 0xB0 and length == 2:
                op.update(op='write', reg=data[0], value=data[1], name=reg_name(data[0]))
            elif code == 0x80002010 and offset == 0xB0 and length == 1:
                selected = data[0]; op.update(op='select', reg=data[0], name=reg_name(data[0]))
            elif code == 0x8000200C and offset == 0x07 and length == 1:
                op.update(op='read', reg=selected, value=data[0] if data else None, name=reg_name(selected) if selected is not None else '')
            elif code == 0x80002010 and offset == 0x03:
                op.update(op='bulk_in_request', bytes=index)
            elif code == 0x80002010 and offset == 0x02:
                op.update(op='bulk_out_notice', bytes=index)
            elif code == 0x80002010 and offset == 0xC0:
                op.update(op='fifo_clean', index=index)
            elif code == 0x80002010:
                op.update(op='vendor_out', offset=offset, index=index, data=data.hex())
            elif code == 0x8000200C:
                op.update(op='vendor_in', offset=offset, index=index, data=data.hex())
            else:
                op.update(op=IOCTL.get(code, f'ioctl {code:#x}').lower(), data=r.get('out', ''))
            ops.append(op)
        elif call == 'WriteFile':
            ops.append({'n': r['n'], 'op': 'bulk_out', 'bytes': r.get('done', r.get('size')), 'head': r.get('data', '')[:32],
                        'payload': r.get('data', ''), 'ok': bool(r.get('ok'))})
        elif call in ('ReadFile', 'GetOverlappedResult'):
            if call == 'ReadFile' and not r.get('ok') and r.get('error') == 997:
                continue  # pending: GetOverlappedResult carries the result
            ops.append({'n': r['n'], 'op': 'bulk_in', 'bytes': r.get('done'), 'head': r.get('data', '')[:32], 'ok': bool(r.get('ok'))})
        elif call == 'CloseHandle':
            devices.discard(r['handle']); ops.append({'n': r['n'], 'op': 'close'})
    return ops


def describe(op: dict) -> str:
    kind = op['op']
    if kind == 'write':
        return f"W {op['reg']:#04x} = {op['value']:#04x}   {op['name']}"
    if kind == 'read':
        reg = f"{op['reg']:#04x}" if op['reg'] is not None else '?'
        value = f"{op['value']:#04x}" if op['value'] is not None else '?'
        return f"R {reg} -> {value}   {op['name']}"
    if kind == 'select':
        return f"S {op['reg']:#04x}   {op['name']}"
    if kind in ('bulk_in', 'bulk_out'):
        return f"{kind} {op['bytes']} bytes {op['head']}"
    return kind + ' ' + ' '.join(f'{k}={v}' for k, v in op.items() if k not in ('n', 'op', 'ok'))


def tables(ops: list[dict]) -> list[dict]:
    """Bulk OUT uploads with the scanner RAM location set just before each one.

    RamRWBulk/WriteTable select a RAM area with 0x94 and set the start and end
    addresses in 0xb0-0xb2 and 0xb3-0xb5 (24-bit, low byte first) before the block.
    Traces made before 2026-10-31 hold only the first 64 bytes of each upload.
    """
    regs, out = {}, []
    for op in ops:
        if op['op'] == 'write':
            regs[op['reg']] = op['value']
        elif op['op'] == 'bulk_out' and op.get('bytes'):
            addr = lambda r: regs.get(r, 0) | regs.get(r + 1, 0) << 8 | regs.get(r + 2, 0) << 16
            data = bytes.fromhex(op.get('payload', ''))
            out.append({'n': op['n'], 'ram_select': regs.get(0x94), 'start': addr(0xb0), 'end': addr(0xb3),
                        'bytes': op['bytes'], 'complete': len(data) == op['bytes'], 'data': data})
    return out


def phases(records: list[dict]) -> list[dict]:
    """Where a session's time goes: one entry per auto-scan pass (0x90 set non-zero).

    Each pass reports when it started, how long the host spent before it since the
    previous pass ended (calibration, focus and motor work), and its line reads.
    Compare frame 1 with frame 2 of one session to see what CyberView repeats.
    """
    ms = {r['n']: r.get('ms') or 0.0 for r in records}
    ops = decode(records)
    out, current, last_end = [], None, (ops[0] and ms[ops[0]['n']]) if ops else 0.0
    for op in ops:
        t = ms[op['n']]
        if op['op'] == 'write' and op['reg'] == 0x90 and op['value']:
            if current:
                out.append(current); last_end = current['end_s'] * 1000
            current = {'start_s': round(t / 1000, 1), 'setup_before_s': round((t - last_end) / 1000, 1),
                       'reads': 0, 'line_bytes': None, 'end_s': round(t / 1000, 1)}
        elif current and op['op'] == 'bulk_in' and op.get('bytes', 0) > 1:
            current['reads'] += 1; current['end_s'] = round(t / 1000, 1)
            current['line_bytes'] = max(current['line_bytes'] or 0, op['bytes'])  # the last read can be a short tail
    if current:
        out.append(current)
    return out


def summary(ops: list[dict]) -> dict:
    writes = Counter(op['reg'] for op in ops if op['op'] == 'write')
    final = {}
    for op in ops:
        if op['op'] == 'write':
            final[op['reg']] = op['value']
    return {
        'operations': Counter(op['op'] for op in ops),
        'register_writes': {f'{r:#04x}': n for r, n in sorted(writes.items())},
        'final_registers': {f'{r:#04x} {reg_name(r)}': f'{v:#04x}' for r, v in sorted(final.items())},
        'bulk_in_bytes': sum(op.get('bytes') or 0 for op in ops if op['op'] == 'bulk_in'),
        'bulk_out_bytes': sum(op.get('bytes') or 0 for op in ops if op['op'] == 'bulk_out'),
        'failed': sum(1 for op in ops if op.get('ok') is False),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    ops = decode(load(Path(argv[0])))
    if '--phases' in argv:
        for phase in phases(load(Path(argv[0]))):
            print(json.dumps(phase))
    elif '--tables' in argv:
        folder = Path(argv[argv.index('--tables') + 1]); folder.mkdir(parents=True, exist_ok=True)
        for t in tables(ops):
            name = f"{t['n']:07d}-ram{t['ram_select'] or 0:02x}-{t['start']:06x}.bin"
            (folder / name).write_bytes(t['data'])
            print(name, t['bytes'], 'bytes', 'complete' if t['complete'] else 'truncated in the trace')
    elif '--summary' in argv:
        print(json.dumps(summary(ops), indent=2, default=dict))
    else:
        for op in ops:
            print(f"{op['n']:>7} {describe(op)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
