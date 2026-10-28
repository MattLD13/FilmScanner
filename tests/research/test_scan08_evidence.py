"""SCAN08 dependency evidence: synthetic parser fixtures and the tracked static survey.

The tracked JSON is the actual scan08_survey.py output for the inventoried
payload hashes. These tests keep its conclusions from drifting; they do not
prove what module or USB identity the physical PF1800 AFL uses.
"""
import json
import struct
from pathlib import Path

import pytest

from research.cyberview.analysis.scan08_survey import RECORD_SIZE, gamma_header, inf_hardware_ids, parse_model_records

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = json.loads((ROOT / 'research/cyberview/analysis/scan08-evidence.json').read_text(encoding='utf8'))


def _record(code, name):
    return struct.pack('<I', code) + name.ljust(RECORD_SIZE - 4, b'\0')


def test_model_record_parser_reads_code_and_module_name():
    # Synthetic records; the names are fictitious.
    data = b'pad' + _record(0x25, b'EXAMPLE.dll') + _record(0x2a, b'OTHER.dll')
    rows = parse_model_records(data, 3, 2)
    assert [(r['model_code'], r['module']) for r in rows] == [(0x25, 'EXAMPLE.dll'), (0x2a, 'OTHER.dll')]


@pytest.mark.parametrize('data', [_record(1, b'A.dll')[:-1], struct.pack('<I', 1) + b'\xff' * (RECORD_SIZE - 4),
                                  struct.pack('<I', 1) + bytes(RECORD_SIZE - 4)])
def test_model_record_parser_rejects_truncated_or_unprintable_records(data):
    with pytest.raises(ValueError):
        parse_model_records(data, 0, 1)


def test_inf_and_gamma_parsers_normalize_case_and_stop_at_table():
    text = '%Desc% = Dev, USB\\Vid_abcd&Pid_00ef\n%Desc% = Dev, USB\\VID_ABCD&PID_00EF\n'
    assert inf_hardware_ids(text) == ['ABCD:00EF']
    assert gamma_header('# Version 1.1;\r\n# Generic gamma file for Example;\r\n\r\nFilmLut\n# not header') == [
        'Version 1.1', 'Generic gamma file for Example']


def test_official_payload_has_no_file_named_scan08_but_afl_binds_model_37():
    assert EVIDENCE['evidence'] == 'STATIC'
    assert EVIDENCE['payload_files_named_scan08_dll'] == []
    table = {r['model_code']: r for r in EVIDENCE['benescan_model_table']}
    assert table[0x25]['module'] == 'SCAN08.dll' and table[0x25]['present_in_payload'] == []
    assert table[0x2a]['module'] == 'LC.dll' and table[0x2a]['present_in_payload'] == ['CyberViewX_SF/LC.dll']
    bindings = {b['class']: b for b in EVIDENCE['cyberviewx_class_bindings']}
    assert (bindings['CPfs1800AFL']['driver_name'], bindings['CPfs1800AFL']['gamma_file']) == ('SCAN08', '37.GG')
    assert (bindings['CPfs1800P']['driver_name'], bindings['CPfs1800P']['gamma_file']) == ('LC', '42.GG')
    assert bindings['CPfs1800U']['driver_name'] == 'PF1800U'


def test_scan08_named_builds_are_bound_to_other_records_and_ids():
    modules = EVIDENCE['scan08_lineage_modules']
    lc = modules['CyberViewX_SF/LC.dll']
    assert lc['version_resources']['OriginalFilename'] == 'SCAN08.DLL'
    assert lc['export_directory_name'] == 'LC.dll' and lc['exports'] == ['ScannerDeviceIO']
    assert {pair for check in lc['usbscan_descriptor_checks'] for pair in check['accepted_vid_pid']} == {'2770:011C'}
    wia = modules['WXP_DLL/PF1800LC.Dll']
    assert wia['export_directory_name'] == 'Scan08.dll'
    assert wia['usbscan_descriptor_checks'][0]['accepted_vid_pid'] == ['0461:034A', '2770:011C']
    assert EVIDENCE['inf_usb_hardware_ids']['DPInst/LC/Pf1800lc.inf'] == ['2770:011C']
    assert not any('0461:034A' in ids for ids in EVIDENCE['inf_usb_hardware_ids'].values())
    wia_classes = {row['class']: row['following_strings'] for row in EVIDENCE['pwiascnr_class_strings']}
    assert wia_classes['CPfs1800AFL'] == ['37.GG', 'SCAN08'] and wia_classes['CPfs1800P'] == ['42.GG', 'PF1800LC']
