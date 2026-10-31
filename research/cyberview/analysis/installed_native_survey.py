"""Static survey of the genuine installed CyberView X MF/AFL stack.

Reads PE files only. It never loads a DLL, calls an export, opens USBSCAN,
changes settings, or imports the production scanner backend. Address annotations
are enabled only for the exact SHA-256 examined with Ghidra 12.1.4.

Run in the optional research analysis venv:
    python installed_native_survey.py --output installed-native-evidence.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile


SCAN08_SHA256 = "da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f"
CYBERVIEW_SHA256 = "bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb"
SELECTORS = {
    1: (0x100156B9, 0x1000561B, "allocate CPU buffers", "CPU only"),
    2: (0x100156C8, 0x10005625, "free CPU buffers", "CPU only; not device disconnect"),
    3: (0x100156D7, 0x1000562F, "detect and initialize registers", "device writes"),
    4: (0x100156E8, 0x1000572C, "unsupported/sets error 0x20881", "no demonstrated use"),
    5: (0x100156F9, 0x1000573D, "open, firmware query, homing and lamp", "may move motor"),
    6: (0x10015800, 0x100064EA, "firmware/SDK string", "CPU state"),
    7: (None, None, "returns success without action", "no-op"),
    8: (0x10015720, 0x10005957, "load/eject positioning path", "motor"),
    9: (0x1001573B, 0x10005AAB, "frame advance/reverse", "motor; forward observed separately"),
    10: (0x1001574C, 0x10005CFB, "bounded incremental positioning", "motor"),
    11: (0x1001577A, 0x10005E11, "long travel/eject via count 99", "motor"),
    12: (0x1001578B, 0x10005EA6, "current frame state", "device status"),
    13: (0x1001579C, 0x10005F06, "frame capacity/status; strip returns 40", "device status"),
    14: (0x100157D9, 0x10005F91, "autofocus measurement", "scan and focus"),
    15: (0x100157AD, 0x10005F70, "get saved focus step", "CPU state"),
    16: (0x100157C3, 0x10005F82, "set saved focus step", "CPU state; next scan applies motor focus"),
    17: (0x10015827, 0x100066A3, "film base/minimum-density measurement", "scan and positioning"),
    18: (0x100157EA, 0x100064DA, "get last error", "CPU state"),
    19: (0x10015838, 0x10006EA9, "scan core with 0x48-byte block", "scan and calibration"),
    20: (0x10015849, 0x10006E82, "store three notification fields", "CPU state"),
    21: (0x10015816, 0x1000655D, "masked status flags", "device status"),
    22: (0x1001570A, 0x100057C0, "length-prefixed capabilities, maximum 0x85", "CPU state"),
    23: (0x1001585F, 0x1000687D, "automatic frame border alignment", "scan and motor"),
    24: (0x10015869, 0x10006DEC, "model code 0x25", "CPU state"),
    25: (None, None, "returns success without action", "no-op"),
    26: (0x100158B7, None, "returns success without action", "no-op"),
    27: (0x1001587F, 0x10006E64, "minimum density then border alignment", "scan and motor"),
    32: (0x10015890, 0x10007383, "flags plus 0x48-byte scan request", "scan and calibration"),
    33: (0x100158A1, 0x100076E8, "read saved RGB balance", "CPU state"),
    35: (0x100158C1, None, "extended capability block", "CPU state"),
    1001: (0x10015986, 0x10007B74, "low-level motor command", "motor; disabled"),
    1002: (0x1001599C, 0x10007B85, "start diagnostic line scan", "scan; disabled"),
    1003: (0x100159CA, 0x10007B9A, "low-level control sequence", "device writes; disabled"),
    1004: (0x100159D9, 0x10007BA4, "apply saved focus", "motor; disabled"),
    1005: (0x100159B2, 0x10007B85, "read diagnostic line", "acquisition; disabled"),
    1006: (0x100159E8, 0x10007B85, "stop diagnostic line scan", "device writes; disabled"),
    1007: (0x100159FE, 0x10007BB8, "read SQ status register 3", "device query; disabled"),
}
SETTING_KEYS = [
    "Save Raw When Scan", "Width of Raw", "Height of Raw", "Write Log",
    "MultiSample Pass", "Multi Scan", "Manual Set Focus", "Enable DMin",
    "Manual Set Scan Area", "Is SmartTest", "For QA Use", "Enable ICE",
    "Auto Exposure", "Film Term Name", "Scan Depth",
]


def identity(path: Path, label: str) -> dict:
    data = path.read_bytes()
    row = {"name": label, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    pe = pefile.PE(data=data)
    row["machine"] = hex(pe.FILE_HEADER.Machine)
    row["image_base"] = hex(pe.OPTIONAL_HEADER.ImageBase)
    row["versions"] = {
        k.decode(errors="replace"): v.decode(errors="replace")
        for group in getattr(pe, "FileInfo", []) for block in group
        for table in getattr(block, "StringTable", []) for k, v in table.entries.items()
    }
    row["exports"] = [
        {"name": item.name.decode(errors="replace") if item.name else None,
         "va": hex(pe.OPTIONAL_HEADER.ImageBase + item.address), "ordinal": item.ordinal}
        for item in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
    ]
    row["imports"] = [lib.dll.decode(errors="replace") for lib in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
    return row


def instructions(pe: pefile.PE, address: int, size: int) -> list[str]:
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [f"{insn.address:08x} {insn.mnemonic} {insn.op_str}" for insn in
            decoder.disasm(pe.get_data(address - pe.OPTIONAL_HEADER.ImageBase, size), address)]


def settings_references(pe: pefile.PE) -> list[dict]:
    data = pe.__data__
    base = pe.OPTIONAL_HEADER.ImageBase
    rows = []
    for key in SETTING_KEYS:
        offset, instances = 0, []
        while True:
            offset = data.find(key.encode() + b"\0", offset)
            if offset < 0:
                break
            address = base + pe.get_rva_from_offset(offset)
            references, start = [], 0
            while True:
                found = data.find(struct.pack("<I", address), start)
                if found < 0:
                    break
                start = found + 4
                rva = pe.get_rva_from_offset(found)
                section = pe.get_section_by_rva(rva)
                if section is not None and section.Name.startswith(b".text"):
                    references.append(hex(base + rva))
            instances.append({"string_va": hex(address), "immediate_reference_va": references})
            offset += 1
        if instances:
            rows.append({"key": key, "instances": instances,
                         "classification": "STATIC setting name/reference; effect not verified"})
    return rows


def verify_wrapper_calls(pe: pefile.PE) -> int:
    """Ensure address annotations still agree with the actual hash-pinned bytes."""
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    decoder.detail = True
    checked = 0
    for selector, (wrapper, target, _, _) in SELECTORS.items():
        if wrapper is None or target is None:
            continue
        calls = set()
        for insn in decoder.disasm(pe.get_data(wrapper - pe.OPTIONAL_HEADER.ImageBase, 64), wrapper):
            if insn.mnemonic == "call" and insn.operands[0].type == capstone.x86.X86_OP_IMM:
                calls.add(insn.operands[0].imm)
            if insn.mnemonic.startswith("ret"):
                break
        if target not in calls:
            raise ValueError(f"selector {selector} wrapper does not call annotated implementation")
        checked += 1
    return checked


def survey(root: Path, system: Path) -> dict:
    modules = [identity(root / name, name) for name in ("SCAN08.dll", "CyberViewX.ds", "BeneScan.dll")]
    for name in ("SQ_Scan.dll", "IO_PORT.DLL", "FVC.DLL"):
        candidate = system / name
        if candidate.is_file():
            modules.append(identity(candidate, "SysWOW64/" + name))
    report = {"evidence": "STATIC FILE BYTES ONLY; no DLL execution or physical I/O",
              "tools": {"pefile": pefile.__version__, "capstone": capstone.__version__}, "modules": modules}
    scan = next(row for row in modules if row["name"] == "SCAN08.dll")
    if scan["sha256"] != SCAN08_SHA256:
        raise ValueError("SCAN08 identity differs; refuse to apply address annotations")
    pe = pefile.PE(str(root / "SCAN08.dll"))
    report["verification"] = {"hash_gate": "passed", "wrapper_calls_checked": verify_wrapper_calls(pe)}
    report["calling_convention"] = {"export": "ScannerDeviceIO", "va": "0x10015390",
        "prototype": "int __cdecl ScannerDeviceIO(int selector, void *parameter)",
        "evidence": "stack arguments [EBP+8], [EBP+C], plain RET at 0x10015614",
        "entry_instructions": instructions(pe, 0x10015390, 0x20),
        "return_instructions": instructions(pe, 0x1001560F, 6)}
    report["notification_callbacks"] = {
        "selector": 20, "dispatcher_va": "0x100116dd",
        "pointers_va": ["0x10018d58", "0x10018d5c", "0x10018d60"],
        "phase_flags_va": ["0x10018d64", "0x10018d66", "0x10018d68"],
        "initial_pointer_values": list(struct.unpack("<3I", pe.get_data(0x18D58, 12))),
        "initial_phase_flags": list(struct.unpack("<3H", pe.get_data(0x18D64, 6))),
        "semantics": "Optional begin/end/progress callbacks. Fresh module with all-null pointers leaves all phase flags zero, so callbacks may be omitted.",
        "caution": "Final phase cleanup has no null guard on end pointer; never register begin without a valid matching end callback.",
    }
    report["required_film_state_initialization"] = {
        "selector": 21, "parameter": "uint32[2] = {0x1f, 0}",
        "status_reader_va": "0x100135f5", "film_type_global_va": "0x10018b82",
        "initial_film_type": pe.get_data(0x18B82, 1)[0],
        "require_loaded_strip_mask": "0x04", "observed_loaded_status": "0x0e",
        "observed_empty_status": "0x08",
        "rationale": "Selectors3/5 do not populate film type. Scan core uses this global to choose strip/mount calibration and transport; query before scanning.",
        "warning": "Do not use old simulator bit0 interpretation for this genuine build",
    }
    report["unset_negative_media_color_failure"] = {
        "classification": "STATIC causal explanation; corrected physical acquisition not yet verified",
        "exposure_routine_va": "0x10010ee9", "film_type_guard_va": "0x1001100a",
        "negative_guard_va": "0x1001100f",
        "green_integer_divisions_va": ["0x10011048", "0x10011050"],
        "blue_integer_divisions_va": ["0x1001106c", "0x10011074"],
        "condition": "film type !=5 and negative flag !=0",
        "red_formula": "(red_balance //100) *0.65",
        "green_formula": "(green_balance //100) //3",
        "blue_formula": "(blue_balance //100) //3",
        "default_balance100_result": [0.65, 0, 0],
        "normal_strip_branch": "float RGB balance/100 times per-channel coefficients; avoids integer-zero branch",
        "red_coefficient_from_pe": struct.unpack("<d", pe.get_data(0x173A8, 8))[0],
        "branch_instructions": instructions(pe, 0x10011002, 0xA9),
    }
    report["selectors"] = [{"selector": key, "wrapper_va": hex(value[0]) if value[0] else None,
        "implementation_va": hex(value[1]) if value[1] else None, "meaning": value[2],
        "risk": value[3], "confidence": "STATIC; no new hardware verification"}
        for key, value in SELECTORS.items()]
    report["scan_contract"] = {
        "selector": 32, "size": 76, "flags_offset": 0, "block_offset": 4,
        "fields_relative_to_block": {"dpi_u16": 0, "left_top_right_bottom_float32": 4,
            "mode_u32": 20, "exposure_rgb_u16": 24, "highlight_rgb_u16": 30,
            "lut_rgb_pointers32": 36, "shadow_rgb_u8": 48, "scan_options_u8": 51,
            "film_media_option_u8": 53, "callback32": 64, "max_strip_lines_u32": 68},
        "lut": "Three 4096-entry uint16 tables; modes5/7 expand each value <<4 to16 consecutive slots",
        "geometry": "Absolute right/bottom edges in inches, clamped to2586x1708 at1800 dpi; X mirrored internally",
        "callback_fields": {"dpi_u32": 0, "mode_u32": 4, "width_u32": 8,
            "height_u32": 12, "reserved_u32": 16, "lines_u32": 20,
            "abort_u32": 24, "last_u32": 28, "data_pointer32": 32,
            "transfer_result_u32": 36, "remaining_lines_u32": 40},
        "callback_warning": "+0x28 is remaining lines, not bytes per line; stride derives from mode and width",
        "addresses": {"core": "0x10006ea9", "geometry": "0x100110af", "lut": "0x10011909"},
    }
    report["usb_identity"] = {"probe_va": "0x1000831a", "descriptor_ioctl": "0x80002018",
        "accepted_pairs": ["2770:0119", "1606:F000", "05DA:00CD", "2770:011A", "2770:011B"],
        "warning": "Only2770:0119 matches existing physical project evidence; alternatives are static acceptance tests only"}
    cv = next(row for row in modules if row["name"] == "CyberViewX.ds")
    if cv["sha256"] == CYBERVIEW_SHA256:
        report["settings"] = settings_references(pefile.PE(str(root / "CyberViewX.ds")))
        report["diagnostic_raw_pipeline"] = {
            "classification": "STATIC reachable code, never enabled or physically tested in this pass",
            "getter_va": "0x10027210", "open_files_va": "0x1001fc90",
            "write_stage_va": "0x10020320", "close_preserve_delete_va": "0x1001ff60",
            "files": [
                {"name": "1_Raw.raw", "string_va": "0x101e9a98"},
                {"name": "2_AfterFT.raw", "string_va": "0x101e9aa4"},
                {"name": "3_AfterAG.raw", "string_va": "0x101e9ab4"},
                {"name": "4_AfterUC.raw", "string_va": "0x101e9ac4"},
                {"name": "5_raw.log", "string_va": "0x101e9af0"},
            ],
            "warning": "Image processing stage dumps; filenames do not establish untouched sensor data",
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("C:/Windows/twain_32/CyberViewX_MF"))
    parser.add_argument("--system", type=Path, default=Path("C:/Windows/SysWOW64"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = survey(args.root, args.system)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Static survey: {len(report['modules'])} modules, {len(report['selectors'])} selector annotations")


if __name__ == "__main__":
    main()
