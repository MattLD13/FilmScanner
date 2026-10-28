"""Validate the portable research inventory without acquiring vendor binaries."""
import json
from pathlib import Path, PurePosixPath
import re


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / 'research/cyberview/acquisition/payload-inventory.json'


def test_complete_inventory_has_safe_paths_sizes_and_hashes():
    inventory = json.loads(INVENTORY.read_text(encoding='utf8'))
    files = inventory['files']
    assert len(files) == inventory['file_count'] == 290
    assert sum(row['bytes'] for row in files) == inventory['total_bytes'] == 24_474_629
    assert len({row['path'].casefold() for row in files}) == len(files)
    for row in files:
        path = PurePosixPath(row['path'])
        assert not path.is_absolute()
        assert '..' not in path.parts and ':' not in row['path']
        assert isinstance(row['bytes'], int) and row['bytes'] >= 0
        assert re.fullmatch('[A-Fa-f0-9]{64}', row['sha256'])


def test_inventory_keeps_model_and_component_versions_distinct():
    files = json.loads(INVENTORY.read_text(encoding='utf8'))['files']
    paths = {row['path']: row for row in files}
    main = paths['Resource_ENG/CyberViewX.ds']
    assert main['sha256'] == '50C9B359417CA61E555A743B8E7351DF43A22585822AA79C334140DD0EB6D64E'
    assert main['pe']['architecture'] == 'x86'
    assert paths['CyberViewX_SF/PF1800U.dll']['pe']['architecture'] == 'x86'
    assert not any(PurePosixPath(row['path']).name.casefold() == 'scan08.dll' for row in files)
    assert any(row['path'].casefold().endswith('pf1800u.inf') for row in files)


def test_research_harness_log_does_not_claim_cyberview_traffic():
    evidence = ROOT / 'research/usb/evidence/harness-usbip-2026-10-27.jsonl'
    rows = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert rows
    assert all(row['source'] == 'harness-only' for row in rows)
    assert all(row['cyberview_guest'] is False and row['physical_device'] is False for row in rows)
    assert any(row['event'] == 'import-rejected' for row in rows)
