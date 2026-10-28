"""Malformed trace, fail-closed command and real loopback-management regressions.

All descriptor bytes below are clearly synthetic standard USB fixtures. They are
not a recovered PF1800 descriptor and never advertise a scanner to a guest.
"""
import asyncio
import json
import struct

import pytest

from research.usb.inspect_trace import inspect_lines, inspect_record
from research.usb.protocol import CommandEvidence, ProtocolError, SetupPacket, decode_command, parse_descriptors
from research.usb.usbip import COMMON, VERSION, REQ_DEVLIST, REQ_IMPORT, SUBMIT, exercise, parse_management_header, parse_submit
from research.usb.legacy_ioctl import IoBlock32, READ_REGISTERS, WRITE_REGISTERS, decode_ioctl
from research.usb.replay import ReplayDevice, Transfer


def test_standard_setup_uses_usb_little_endian():
    setup = SetupPacket.parse(bytes.fromhex("8006000100001200"))
    assert setup.value == 0x0100 and setup.length == 18
    assert setup.to_dict()["direction"] == "in"
    with pytest.raises(ProtocolError):
        SetupPacket.parse(bytes(7))


def test_synthetic_descriptor_fixture_and_configuration_endpoints():
    # Intentionally fictitious VID/PID, visible only to this passive decoder.
    device = bytes.fromhex("120100020000004034127856000101020001")
    parsed = parse_descriptors(device)[0]
    assert (parsed["idVendor"], parsed["idProduct"]) == (0x1234, 0x5678)
    config = bytes.fromhex("0902190001010080320904000001ff00000007058102400000")
    decoded = parse_descriptors(config)
    assert [r["type"] for r in decoded] == [2, 4, 5]
    assert decoded[2]["bEndpointAddress"] == 0x81
    assert decoded[2]["wMaxPacketSize"] == 64


@pytest.mark.parametrize("raw", [b"", b"\x00\x01", b"\x01\x01", b"\x12\x01",
    bytes.fromhex("090220000101008032"), b"\x03\x03\x41", bytes.fromhex("07050100")])
def test_descriptor_corruption_cannot_loop_or_read_past_buffer(raw):
    with pytest.raises(ProtocolError):
        parse_descriptors(raw)


def test_unknown_descriptor_is_preserved_without_assigning_meaning():
    assert parse_descriptors(bytes.fromhex("04fe1234"))[0] == {
        "offset": 0, "length": 4, "type": 254, "raw_hex": "04fe1234"}


def test_pf_commands_are_unknown_without_evidence():
    for raw in (b"\0" * 6, bytes.fromhex("120000002400"), bytes.fromhex("ff")):
        with pytest.raises(ProtocolError, match="Unknown"):
            decode_command(raw)
    # A hypothetical registry is an API test fixture, not a PF1800 finding.
    fixture = (CommandEvidence(0xAB, 3, "synthetic-fixture", "test-only"),)
    assert decode_command(bytes.fromhex("ab1234"), fixture)["execution_verified"] is False
    with pytest.raises(ProtocolError):
        decode_command(bytes.fromhex("ab1234ff"), fixture)
    with pytest.raises(ProtocolError):
        decode_command(bytes.fromhex("ab1234"), fixture + fixture)


def test_submit_parser_checks_lengths_direction_and_endpoint():
    setup = bytes.fromhex("8006000100001200")
    submit = SUBMIT.pack(1, 42, 0x10002, 1, 0, 0, 18, 0, 0, 0, setup)
    parsed = parse_submit(submit)
    assert parsed["sequence"] == 42 and parsed["setup"]["length"] == 18
    for raw in (submit[:-1], submit + b"extra",
                SUBMIT.pack(1, 42, 0x10002, 0, 0, 0, 18, 0, 0, 0, setup) + bytes(18),
                SUBMIT.pack(1, 42, 0x10002, 1, 16, 0, 18, 0, 0, 0, setup),
                SUBMIT.pack(1, 42, 0x10002, 1, 0, 0, -1, 0, 0, 0, setup),
                SUBMIT.pack(1, 42, 0x10002, 1, 0, 0, 2**25, 0, 0, 0, setup),
                SUBMIT.pack(1, 42, 0x10002, 1, 0, 0, 18, 0, 1, 0, setup)):
        with pytest.raises(ProtocolError):
            parse_submit(raw)


def test_submit_outbound_payload_is_passive_and_exact():
    raw = SUBMIT.pack(1, 7, 0x10002, 0, 2, 0, 3, 0, 0, 0, bytes(8)) + b"abc"
    assert parse_submit(raw)["payload_hex"] == "616263"
    with pytest.raises(ProtocolError):
        parse_submit(raw[:-1])


def test_management_rejects_wrong_version_status_and_opcode():
    assert parse_management_header(bytes.fromhex("0111800500000000")) == (VERSION, REQ_DEVLIST, 0)
    for raw in (bytes(7), COMMON.pack(0, REQ_DEVLIST, 0), COMMON.pack(VERSION, REQ_IMPORT, 1),
                COMMON.pack(VERSION, 0xFFFF, 0)):
        with pytest.raises(ProtocolError):
            parse_management_header(raw)


def test_trace_inspection_preserves_errors_and_continues():
    rows = list(inspect_lines([
        '{"kind":"setup","hex":"8006000100001200"}',
        '{"kind":"command","hex":"120000002400"}',
        '{"kind":"setup","hex":"nothex"}', "[1]", "invalid-json",
        '{"kind":"descriptors","hex":"04fe1234"}',
    ]))
    assert [r["status"] for r in rows] == ["decoded", "rejected", "rejected", "rejected", "rejected", "decoded"]
    assert rows[-1]["line"] == 6
    with pytest.raises(ProtocolError):
        inspect_record({"kind": "unknown", "hex": "00"})


def test_actual_fragmented_tcp_management_harness_reports_no_device(tmp_path):
    log = tmp_path / "exchange.jsonl"
    asyncio.run(exercise(log))
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [event["event"] for event in events] == ["listening", "devlist", "import-rejected", "malformed-rejected"]
    assert events[1]["devices"] == 0
    assert all(event["source"] == "harness-only" and not event["cyberview_guest"] and not event["physical_device"] for event in events)
    assert events[2]["response_hex"] == "0111000300000001"
    with pytest.raises(FileExistsError):
        asyncio.run(exercise(log))


def test_recovered_x86_ioctl_boundary_does_not_confuse_host_and_wire():
    # Synthetic pointer is intentionally omitted from the decoder's export.
    raw = struct.pack("<IIII", 0x82, 8, 0x12345678, 0)
    decoded = decode_ioctl(WRITE_REGISTERS, raw, bytes(8))
    assert decoded["offset"] == 0x82 and decoded["length"] == 8
    assert decoded["documented_usbscan_setup_expectation"] == {
        "request_type": 0x40, "request": 0x04, "value": 0x82, "index": 0, "length": 8}
    assert decoded["layer"] == "host-DeviceIoControl-x86"
    assert not decoded["observed_usb_traffic"] and not decoded["device_verified"]
    assert "12345678" not in json.dumps(decoded)
    single = decode_ioctl(READ_REGISTERS, struct.pack("<IIII", 0x84, 1, 0, 0))
    assert single["documented_usbscan_setup_expectation"]["request"] == 0x0C
    assert single["documented_usbscan_setup_expectation"]["request_type"] == 0xC0
    for code, block, payload in ((0, raw, None), (WRITE_REGISTERS, raw[:-1], None),
            (WRITE_REGISTERS, raw, bytes(7)),
            (READ_REGISTERS, struct.pack("<IIII", 0x84, 65536, 0, 0), None)):
        with pytest.raises(ProtocolError):
            decode_ioctl(code, block, payload)


def test_offline_replay_stalls_unknown_without_consuming_known_evidence():
    # Synthetic USB descriptor fixture, explicitly unrelated to any PF1800 ID.
    setup = bytes.fromhex("8006000100001200")
    response = bytes.fromhex("120100020000004034127856000101020001")
    device = ReplayDevice((Transfer(setup, b"", response),), provenance="synthetic-fixture")
    with pytest.raises(ProtocolError, match="detached"):
        device.control(setup)
    device.attach()
    with pytest.raises(ProtocolError, match="Uncaptured"):
        device.control(bytes.fromhex("c004820000000800"))
    assert device.position == 0
    assert device.control(setup) == response and device.state == "exhausted"
    with pytest.raises(ProtocolError, match="exhausted"):
        device.control(setup)
    device.detach(); device.attach()
    assert device.control(setup) == response
    assert all(not event["physical_device"] and not event["cyberview_guest"] for event in device.events)
    assert all(event["profile_provenance"] == "synthetic-fixture" for event in device.events)


def test_offline_replay_rejects_malformed_profiles():
    for transfer in (Transfer(b"bad", b"", b""),
            Transfer(bytes.fromhex("8006000100000100"), b"", bytes(2)),
            Transfer(bytes.fromhex("0009000000000000"), b"", b"unexpected")):
        with pytest.raises(ProtocolError):
            ReplayDevice((transfer,), provenance="synthetic-fixture")
    with pytest.raises(ProtocolError):
        ReplayDevice((), provenance="captured-hardware")
