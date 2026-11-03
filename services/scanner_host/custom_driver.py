"""Independent PF1800 command workbench. Default mode produces offline plans.

--identify and --status perform verified independent live reads. Live JSON mode
currently accepts only the exact page-0 status command; arbitrary commands stay
disabled until independently validated.

Run ``python -m services.scanner_host.custom_driver --help``. This research path
is deliberately separate from the production vendor-assisted scanner backend.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Protocol

from .custom_protocol import CommandError, CommandPlan, Transfer, compile_command

MAX_COMMANDS = 256
MAX_INPUT_BYTES = 2 * 1024 * 1024


class HardwareDisabled(RuntimeError):
    pass


class TransferError(RuntimeError):
    pass


class Transport(Protocol):
    def transfer(self, step: Transfer) -> bytes | int: ...


def execute_plan(plan: CommandPlan, transport: Transport) -> list[dict]:
    """Execute in strict order; fail on short transfer without retrying writes.

    Input is bytes; output reports the data bytes sent (not DeviceIoControl's
    output-buffer byte count, which can be zero for WRITE_REGISTERS). The native
    transport normalizes successful control-out completion accordingly.
    """
    responses = []
    for step in plan.transfers:
        value = transport.transfer(step)
        if step.kind.endswith('in'):
            if not isinstance(value, bytes) or len(value) != step.size:
                raise TransferError('Incomplete input transfer; command stopped')
            responses.append({'kind': step.kind, 'data_hex': value.hex(), 'size': len(value)})
        elif type(value) is not int or value != step.size:
            raise TransferError('Incomplete output transfer; command stopped without retry')
        else:
            responses.append({'kind': step.kind, 'transferred': value})
    return responses


class ReplayTransport:
    """Strict synthetic responses with the expected transfer recorded alongside.

    This never manufactures register values or accepts a differently ordered
    command. It is not a scanner emulator or evidence of device support.
    """
    def __init__(self, responses: list[dict]):
        if not isinstance(responses, list) or len(responses) > MAX_COMMANDS * 4:
            raise CommandError('Replay responses must be a bounded JSON array')
        self.responses = iter(responses)
        self.used = 0

    def transfer(self, step: Transfer) -> bytes | int:
        try:
            record = next(self.responses)
        except StopIteration as exc:
            raise TransferError('Replay has no response for this transfer') from exc
        if not isinstance(record, dict) or record.get('expected') != step.as_dict():
            raise TransferError('Replay transfer does not match the command plan')
        self.used += 1
        if step.kind.endswith('in'):
            data = record.get('data_hex')
            if not isinstance(data, str) or len(data) > step.size * 2:
                raise TransferError('Invalid replay input data')
            try:
                return bytes.fromhex(data)
            except ValueError as exc:
                raise TransferError('Invalid replay hexadecimal') from exc
        return record.get('transferred')

    def finish(self):
        exhausted = object()
        if next(self.responses, exhausted) is not exhausted:
            raise TransferError('Replay contains unused transfer responses')


class WindowsUsbscanTransport:
    """Verified whole-command transport; unrestricted partial transfers stay disabled."""
    def __init__(self, plan=None, device_index=0, timeout_ms=2000):
        approved = compile_command({'op': 'status_read', 'page': 0})
        if plan != approved:
            raise HardwareDisabled('Hardware access is disabled for arbitrary commands; '
                                   'only the verified page-0 status sequence is available.')
        from .usbscan_transport import require_verified_operation, UsbscanError
        try:
            require_verified_operation('status_read_page0')
        except UsbscanError as exc:
            raise HardwareDisabled(str(exc)) from None
        self.device_index, self.timeout_ms = device_index, timeout_ms

    def run(self):
        from .usbscan_transport import read_scanner_status
        return read_scanner_status(self.device_index, self.timeout_ms)


def _load_json(path: str):
    file = Path(path)
    if file.stat().st_size > MAX_INPUT_BYTES:
        raise CommandError('Input file exceeds 2 MiB')
    return json.loads(file.read_text(encoding='utf-8-sig'))


def _commands(args):
    if args.commands:
        values = _load_json(args.commands)
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_COMMANDS:
            raise CommandError('Commands file must contain 1 to 256 JSON commands')
        yield from values
    elif args.command:
        if len(args.command.encode()) > MAX_INPUT_BYTES:
            raise CommandError('Command exceeds 2 MiB')
        yield json.loads(args.command)
    else:
        # A JSON-line console is useful from PowerShell or a scripted pipe, and
        # avoids shell-dependent quoting. Each line is answered immediately.
        for index in range(MAX_COMMANDS + 1):
            line = sys.stdin.readline(MAX_INPUT_BYTES + 1)
            if not line:
                return
            if index == MAX_COMMANDS or len(line.encode()) > MAX_INPUT_BYTES:
                raise CommandError('Console command limit exceeded')
            yield json.loads(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('dry-run', 'replay', 'hardware'), default='dry-run',
                        help='Live mode accepts only independently verified whole-command templates')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--command', help='One JSON command; otherwise read JSON lines from stdin')
    inputs.add_argument('--commands', help='JSON file containing a bounded array of commands')
    parser.add_argument('--responses', help='Explicit transfer responses for replay mode')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--identify', action='store_true', help='Read scanner USB identity directly, without vendor DLLs or register writes')
    actions.add_argument('--status', action='store_true', help='Read the verified status register on page 0; no motor or lamp controls')
    parser.add_argument('--device-index', type=int, default=0, help='Explicit USBSCAN device index for live reads (default 0)')
    parser.add_argument('--timeout-ms', type=int, default=2000, help='Bounded identification I/O timeout, 100–10000 ms')
    args = parser.parse_args(argv)
    try:
        if args.identify or args.status:
            if args.mode != 'dry-run' or args.command or args.commands or args.responses:
                raise CommandError('--identify/--status must be used without command/replay/hardware options')
            from .usbscan_transport import identify_scanner, read_scanner_status, UsbscanError
            try:
                result = (read_scanner_status if args.status else identify_scanner)(args.device_index, args.timeout_ms)
            except UsbscanError as exc:
                print(json.dumps({'error': str(exc), 'hardware_accessed': exc.hardware_accessed,
                                  'ownership_uncertain': exc.ownership_uncertain}), file=sys.stderr, flush=True)
                return 2
            print(json.dumps(result), flush=True)
            return 0
        if args.mode == 'hardware':
            if not (args.command or args.commands):
                WindowsUsbscanTransport()  # no implicit hardware action or stdin wait
            if args.responses:
                raise CommandError('--responses is only valid in replay mode')
            plans = [compile_command(command) for command in _commands(args)]
            # Check the entire batch before executing even its first operation.
            transports = [WindowsUsbscanTransport(plan, args.device_index, args.timeout_ms) for plan in plans]
            from .usbscan_transport import UsbscanError
            for plan, transport in zip(plans, transports):
                try:
                    result = transport.run()
                except UsbscanError as exc:
                    print(json.dumps({'error': str(exc), 'hardware_accessed': exc.hardware_accessed,
                                      'ownership_uncertain': exc.ownership_uncertain}), file=sys.stderr, flush=True)
                    return 2
                print(json.dumps({'mode': 'hardware', 'plan': plan.as_dict() | {'raw_path_verified_on_device': True,
                                  'evidence': 'docs/custom-driver.md'}, 'result': result, 'hardware_accessed': True}), flush=True)
            return 0
        if args.mode == 'replay' and not args.responses:
            raise CommandError('Replay requires --responses')
        if args.responses and args.mode != 'replay':
            raise CommandError('--responses is only valid in replay mode')
        replay = ReplayTransport(_load_json(args.responses)) if args.responses else None
        for command in _commands(args):
            plan = compile_command(command)
            result = {'mode': args.mode, 'hardware_accessed': False, 'plan': plan.as_dict()}
            if replay:
                result['synthetic_responses'] = execute_plan(plan, replay)
            else:
                result['executed'] = False
            print(json.dumps(result), flush=True)
        if replay:
            replay.finish()
        return 0
    except (CommandError, HardwareDisabled, TransferError, OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'hardware_accessed': False}), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
