"""Evidence floppy round trip and guard rails for the in-guest capture scripts."""
from pathlib import Path
import re
import struct

import pytest

from research.cyberview.analysis.fat12 import SECTOR, blank_image, read_root_files

ROOT = Path(__file__).resolve().parents[2]
ROOT_DIR = SECTOR * 19  # 1 boot sector + 2 FATs of 9 sectors
DATA = SECTOR * 33      # root directory holds 224 entries = 14 sectors


def _set_fat(image, cluster, value):
    for fat_start in (SECTOR, SECTOR * 10):
        offset = fat_start + cluster * 3 // 2
        pair = image[offset] | image[offset + 1] << 8
        pair = (pair & 0x000F) | value << 4 if cluster & 1 else (pair & 0xF000) | value
        image[offset:offset + 2] = struct.pack('<H', pair)


def _entry(name, attributes, cluster, size):
    return name.ljust(11).encode() + bytes([attributes]) + bytes(14) + struct.pack('<HI', cluster, size)


def test_blank_image_is_a_valid_empty_floppy():
    image = blank_image()
    assert len(image) == 1_474_560 and image[510:512] == b'\x55\xaa'
    assert read_root_files(image) == {}


def test_reads_multi_cluster_file_and_skips_lfn_deleted_label_and_directory():
    image = bytearray(blank_image())
    body = b'A' * SECTOR + b'tail'
    entries = [_entry('FRAMEEVID', 0x08, 0, 0), b'\x41' + bytes(10) + b'\x0f' + bytes(20),
               b'\xe5' + _entry('GONE    TXT', 0x20, 2, 1)[1:], _entry('SUBDIR', 0x10, 5, 0),
               _entry('RUN     TXT', 0x20, 2, len(body)), _entry('EMPTY   TXT', 0x20, 0, 0)]
    for index, entry in enumerate(entries):
        image[ROOT_DIR + index * 32: ROOT_DIR + (index + 1) * 32] = entry
    _set_fat(image, 2, 3)      # even cluster entry
    _set_fat(image, 3, 0xFFF)  # odd cluster entry, end of chain
    image[DATA:DATA + len(body)] = body
    assert read_root_files(bytes(image)) == {'RUN.TXT': body, 'EMPTY.TXT': b''}


def test_rejects_loops_short_chains_and_non_fat_images():
    image = bytearray(blank_image())
    image[ROOT_DIR:ROOT_DIR + 32] = _entry('LOOP    TXT', 0x20, 2, SECTOR * 3)
    _set_fat(image, 2, 2)
    with pytest.raises(ValueError, match='loop'):
        read_root_files(bytes(image))
    _set_fat(image, 2, 0xFFF)
    with pytest.raises(ValueError, match='shorter'):
        read_root_files(bytes(image))
    with pytest.raises(ValueError):
        read_root_files(bytes(SECTOR * 2880))


def test_guest_scripts_only_observe_and_write_evidence():
    scripts = {p.name: p.read_text() for p in (ROOT / 'research/cyberview/analysis/guest_tools').glob('*.CMD')}
    assert set(scripts) == {'BASELINE.CMD', 'COLLECT.CMD'}
    forbidden = re.compile(r'\breg\s+(add|delete|import)\b|\bdel\b|\berase\b|\bformat\b|\bnet\s|\bbcdedit\b|'
                           r'\bsc\s|\bdpinst\b|\bpnputil\b|\bdisableuac\b|\bshutdown\b|\brd\b|\brmdir\b', re.I)
    for name, text in scripts.items():
        assert not forbidden.search(text), name
    assert '-max 64' in scripts['BASELINE.CMD']
    assert 'A:\\' in scripts['COLLECT.CMD']
