"""Independent USB plans and strict synthetic replay; never uses a scanner."""
import ctypes
import json
import subprocess
import sys

import pytest

from services.scanner_host.custom_driver import (
    HardwareDisabled, ReplayTransport, TransferError, WindowsUsbscanTransport,
    execute_plan, main,
)
from services.scanner_host.custom_protocol import (
    CommandError, CommandPlan, IoBlock, MAX_TRANSFER, READ_REGISTERS, WRITE_REGISTERS,
    Transfer, compile_command, control_block,
)


def test_register_read_has_select_then_control_input():
    plan = compile_command({'op': 'register_read', 'register': 0x8B})
    assert [step.as_dict() for step in plan.transfers] == [
        {'kind': 'control_out', 'size': 1, 'ioctl': WRITE_REGISTERS,
         'offset': 0xB0, 'index': 0, 'data_hex': '8b'},
        {'kind': 'control_in', 'size': 1, 'ioctl': READ_REGISTERS, 'offset': 7, 'index': 0},
    ]
    assert not plan.as_dict()['raw_path_verified_on_device']


def test_custom_register_write_is_an_explicit_two_byte_plan():
    plan = compile_command({'op': 'register_write', 'register': 0x97, 'value': 0})
    assert plan.transfers == (Transfer('control_out', 2, 0xB0, 0, b'\x97\x00'),)
    status = compile_command({'op': 'status_read', 'page': 0})
    assert status.transfers[0] == plan.transfers[0]
    assert status.transfers[1:] == compile_command({'op': 'register_read', 'register': 0x8B}).transfers


def test_bulk_announcement_matches_observed_zero_payload_and_splits_large_block():
    plan = compile_command({'op': 'bulk_read', 'length': 65535})
    assert plan.transfers[0] == Transfer('control_out', 1, 3, 65535, b'\x00')
    assert [step.size for step in plan.transfers[1:]] == [MAX_TRANSFER, 65535 - MAX_TRANSFER]
    stream = compile_command({'op': 'stream_read', 'length': 100})
    assert stream.transfers == (Transfer('bulk_in', 100),)
    data = b'\x21' * 65535
    write = compile_command({'op': 'bulk_write', 'data_hex': data.hex()})
    assert write.transfers[0] == Transfer('control_out', 1, 2, len(data), b'\x02')
    assert b''.join(step.data for step in write.transfers[1:]) == data


@pytest.mark.parametrize('command', [
    {'op': 'firmware_flash', 'data_hex': '00'},
    {'op': 'scan', 'lines': 99999},
    {'op': 'register_write', 'register': 0x84, 'value': 256},
    {'op': 'register_read', 'register': -1},
    {'op': 'register_read', 'register': True},
    {'op': 'register_read', 'register': 139.0},
    {'op': 'register_read', 'register': 139, 'allow_hardware': True},
    {'op': 'status_read', 'page': 15},
    {'op': 'bulk_read', 'length': 65536},
    {'op': 'bulk_read', 'length': 0},
    {'op': 'stream_read', 'length': MAX_TRANSFER + 1},
    {'op': 'bulk_write', 'data_hex': 'not hex'},
    {'op': 'bulk_write', 'data_hex': ''},
    {'op': ['register_read'], 'register': 1},
    [],
])
def test_invalid_and_unknown_commands_do_not_become_transfers(command):
    with pytest.raises(CommandError):
        compile_command(command)


def test_native_io_block_uses_pointer_width_and_32_bit_unsigneds():
    block, backing = control_block(compile_command({'op': 'register_write', 'register': 0x28, 'value': 2}).transfers[0])
    assert block.offset == 0xB0 and block.length == 2 and block.index == 0
    assert bytes(backing) == b'\x28\x02'
    assert bytes(block.data[:block.length]) == bytes(backing)
    assert IoBlock.data.offset == 8
    assert IoBlock.index.offset == 8 + ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(IoBlock) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
    with pytest.raises(CommandError):
        control_block(Transfer('bulk_in', 2))


def test_replay_requires_each_exact_transfer_in_order():
    plan = compile_command({'op': 'register_read', 'register': 0x8B})
    fixture = [{'expected': plan.transfers[0].as_dict(), 'transferred': 1},
               {'expected': plan.transfers[1].as_dict(), 'data_hex': '6f'}]
    transport = ReplayTransport(fixture)
    responses = execute_plan(plan, transport)
    assert responses[-1]['data_hex'] == '6f'
    transport.finish()
    with pytest.raises(TransferError, match='does not match'):
        execute_plan(plan, ReplayTransport(fixture[::-1]))


@pytest.mark.parametrize('input_response', ['', '6f00', None, 'zz'])
def test_short_overlong_and_invalid_reads_fail(input_response):
    step = Transfer('bulk_in', 1)
    with pytest.raises(TransferError):
        execute_plan(CommandPlan('stream_read', (step,)),
                     ReplayTransport([{'expected': step.as_dict(), 'data_hex': input_response}]))


def test_incomplete_output_never_retries_or_runs_later_commands():
    plan = compile_command({'op': 'status_read', 'page': 0})
    fixture = [{'expected': plan.transfers[0].as_dict(), 'transferred': 1},
               {'expected': plan.transfers[1].as_dict(), 'transferred': 1}]
    transport = ReplayTransport(fixture)
    with pytest.raises(TransferError, match='without retry'):
        execute_plan(plan, transport)
    assert transport.used == 1


def test_hardware_mode_is_disabled_before_any_device_or_vendor_load(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail('No Windows library may be loaded by the disabled raw path')
    monkeypatch.setattr(ctypes, 'WinDLL', forbidden, raising=False)
    monkeypatch.setenv('FRAME_ALLOW_EXPERIMENTAL_SCANNER', '1')
    with pytest.raises(HardwareDisabled):
        WindowsUsbscanTransport()
    assert main(['--mode', 'hardware']) == 2
    assert 'Hardware access is disabled' in capsys.readouterr().err


def test_console_defaults_to_nonexecuting_plans(capsys):
    assert main(['--command', '{"op":"register_write","register":132,"value":255}']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['mode'] == 'dry-run'
    assert result['executed'] is False and result['hardware_accessed'] is False
    assert result['plan']['transfers'][0]['data_hex'] == '84ff'


def test_json_line_console_and_replay_cli_are_real_processes(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'services.scanner_host.custom_driver'],
                            input='{"op":"register_read","register":139}\n', text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['executed'] is False
    plan = compile_command({'op': 'register_read', 'register': 139})
    responses = [{'expected': plan.transfers[0].as_dict(), 'transferred': 1},
                 {'expected': plan.transfers[1].as_dict(), 'data_hex': '6f'}]
    file = tmp_path / 'responses.json'
    file.write_text(json.dumps(responses))
    result = subprocess.run([sys.executable, '-m', 'services.scanner_host.custom_driver',
                             '--mode', 'replay', '--responses', str(file)],
                            input='{"op":"register_read","register":139}\n', text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['synthetic_responses'][-1]['data_hex'] == '6f'


def test_unused_replay_responses_and_unknown_commands_fail(tmp_path, capsys):
    file = tmp_path / 'responses.json'
    file.write_text('[{"expected":{}}]')
    commands = tmp_path / 'commands.json'
    commands.write_text('[]')
    assert main(['--mode', 'replay', '--responses', str(file), '--commands', str(commands)]) == 2
    assert '1 to 256' in capsys.readouterr().err
    assert main(['--command', '{"op":"scan","lines":3400}']) == 2
    assert 'Unknown operation' in capsys.readouterr().err


@pytest.mark.parametrize('unused', [None, {'expected': {}}])
def test_replay_never_silently_discards_extra_responses(unused):
    with pytest.raises(TransferError, match='unused'):
        ReplayTransport([unused]).finish()
