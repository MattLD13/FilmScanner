"""Scan-request decoder and the tracked CyberView-against-simulated-AFL run.

The run evidence is GUEST OBSERVED behavior of original CyberView talking to the
FRAME research simulator; it never stands in for the physical PF1800 AFL.
"""
import json
import struct
from pathlib import Path

import pytest

from research.cyberview.analysis.afl_contract import BLOCK_SIZE, decode_scan_block, simulated_geometry

ROOT = Path(__file__).resolve().parents[2]
RUN = json.loads((ROOT / 'research/cyberview/analysis/evidence/afl-simulator-2026-10-28.json').read_text())
SOURCE = (ROOT / 'research/cyberview/simulator/scan08_sim.c').read_text()


def _block(dpi=600, mode=2, window=(0.1, 0.2, 1.0, 0.5), lines=32):
    # Synthetic block with arbitrary values, laid out at the decoded offsets.
    block = bytearray(BLOCK_SIZE)
    struct.pack_into('<H', block, 0x00, dpi)
    struct.pack_into('<4f', block, 0x04, *window)
    struct.pack_into('<I', block, 0x14, mode)
    struct.pack_into('<3H', block, 0x18, 1, 2, 3)
    struct.pack_into('<3H', block, 0x1e, 4, 5, 6)
    block[0x30:0x33] = bytes([7, 8, 9])
    struct.pack_into('<II', block, 0x40, 0x12345678, lines)
    return bytes(block)


def test_decoder_reads_every_documented_field():
    decoded = decode_scan_block(_block())
    assert decoded['dpi'] == 600 and decoded['mode'] == 2 and decoded['bytes_per_pixel'] == 1
    assert decoded['window_inches'] == {'left': 0.1, 'top': 0.2, 'width': 1.0, 'height': 0.5}
    assert (decoded['exposure_rgb'], decoded['offset_rgb'], decoded['gain_rgb']) == ([1, 2, 3], [4, 5, 6], [7, 8, 9])
    assert decoded['callback'] == '0x12345678' and decoded['lines_per_strip'] == 32


@pytest.mark.parametrize('block', [bytes(BLOCK_SIZE - 1), _block(mode=0), _block(mode=8)])
def test_decoder_rejects_short_blocks_and_unknown_modes(block):
    with pytest.raises(ValueError):
        decode_scan_block(block)


def test_simulated_geometry_scales_the_lc_full_frame():
    assert simulated_geometry(1800, 3) == {'width': 2496, 'height': 1708, 'bytes_per_line': 7488}
    assert simulated_geometry(300, 7) == {'width': 416, 'height': 284, 'bytes_per_line': 2496}
    with pytest.raises(ValueError):
        simulated_geometry(2400, 3)


def test_recorded_cyberview_requests_decode_to_the_recorded_values():
    decoded = [decode_scan_block(bytes.fromhex(h)) for h in RUN['scan_blocks_hex']]
    assert decoded == RUN['scan_blocks_decoded']
    final = decoded[-1]
    assert (final['dpi'], final['mode'], final['lines_per_strip']) == (300, 3, 255)
    assert final['exposure_rgb'] == [140, 140, 140] and final['offset_rgb'] == [100, 100, 100]


def test_run_reached_open_status_and_scan_and_wrote_the_simulated_frame():
    assert RUN['evidence'].startswith('GUEST OBSERVED with SIMULATED module')
    calls = [c['selector'] for c in RUN['first_calls']]
    assert calls[:8] == ['0x1', '0x3', '0x2', '0x1', '0x3', '0x5', '0x16', '0x16']
    assert RUN['selector_counts']['0x20'] == 2 and RUN['selector_counts']['0x15'] > 0
    scanned = RUN['scanned_file']
    expected = scanned['expected_from_simulator']
    assert scanned['pixels'] == [expected['width'], expected['height']] and scanned['dpi'] == 300
    assert any('GAMMA' in change for change in RUN['test_configuration_changes'])


def test_simulator_source_is_labeled_and_never_does_device_io():
    assert 'NOT Pacific Image software' in SOURCE and 'not device evidence' in SOURCE.lower()
    for forbidden in ('CreateFile', 'DeviceIoControl', 'USBSCAN', 'WriteFile', 'ReadFile'):
        assert forbidden not in SOURCE.replace('never opens a device or issues USB I/O', ''), forbidden
    assert '#define MODEL_CODE 0x25' in SOURCE
