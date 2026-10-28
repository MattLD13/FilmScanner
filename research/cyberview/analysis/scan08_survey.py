"""Static SCAN08 dependency survey. Never loads or executes the supplied images.

Reads an extracted official payload, checks the identities recorded in the
inventory and writes the evidence behind research/cyberview/scan08-investigation.md:
BeneScan model records, CyberViewX class-to-driver-name bindings, SCAN08-named
version/export metadata, USBSCAN descriptor comparisons, INF hardware IDs and
gamma headers. Every value is STATIC. A comparison inside a module is what that
module accepts, not proof of what the physical PF1800 AFL reports.

Pure parsers take bytes/text so tests can use synthetic fixtures. pefile and
capstone are imported only by the survey itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

RECORD_SIZE = 0x44
IOCTL_GET_DEVICE_DESCRIPTOR = 0x80002018  # USBSCAN: returns VID, PID, bcdDevice, language
EXPECTED = {
    "Resource_ENG/CyberViewX.ds": "50C9B359417CA61E555A743B8E7351DF43A22585822AA79C334140DD0EB6D64E",
    "CyberViewX_SF/BeneScan.dll": "ACD215AA92EC45B79837A6DC0ECF4A008AAE772A6A6946C98A93B9570635C27C",
    "CyberViewX_SF/LC.dll": "5486ACE5B00A6341CE0B8F8FE6AAC5F8BFF4041B5161A6D350E16B2AC92652AC",
    "WXP_DLL/PF1800LC.Dll": "54AB511F96F7E27C14D8FAF1E4CE585869BFC28E0E9EB6FA3204FB6E4567CE5D",
    "WXP_DLL/PWiaScnr.dll": "AC9B9ABD389A48F417A0097F95661078B47707267AB950B7A78ACA77374E0B07",
    "system/SQ_SCAN.DLL": "55A865E7119608D0FBB9C0E7F8990ACB061149E77CDDB2C4A3DF09CDDA4F243F",
}
BENESCAN_TABLE_VA = 0x100450D0
BENESCAN_TABLE_END_VA = 0x100455DC  # loop bound in BeneScan 0x1000c1c0


def parse_model_records(data: bytes, offset: int, count: int) -> list[dict]:
    """Decode BeneScan 0x44-byte records: little-endian model code, then ASCII module name."""
    records = []
    for index in range(count):
        raw = data[offset + index * RECORD_SIZE: offset + (index + 1) * RECORD_SIZE]
        if len(raw) < RECORD_SIZE:
            raise ValueError("truncated model record")
        code = struct.unpack_from("<I", raw)[0]
        name = raw[4:].split(b"\0", 1)[0]
        if not re.fullmatch(rb"[A-Za-z0-9_.]{1,63}", name):
            raise ValueError(f"record {index} has no printable module name")
        records.append({"index": index, "model_code": code, "module": name.decode("ascii")})
    return records


def inf_hardware_ids(text: str) -> list[str]:
    """USB hardware IDs named on INF model lines, normalized to upper case."""
    found = re.findall(r"USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", text, re.I)
    return sorted({f"{vid.upper()}:{pid.upper()}" for vid, pid in found})


def gamma_header(text: str) -> list[str]:
    """Leading '#' comment lines of a CyberView .GG gamma table."""
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("# ").rstrip(";").strip())
    return lines


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _pe(path: Path):
    import pefile
    return pefile.PE(data=path.read_bytes())


def _versions(pe) -> dict:
    values = {}
    for group in getattr(pe, "FileInfo", []):
        for block in group:
            for table in getattr(block, "StringTable", []):
                values.update({k.decode(errors="replace"): v.decode(errors="replace")
                               for k, v in table.entries.items()})
    return values


def _ascii_at(mapped: bytes, rva: int, limit: int = 64) -> str | None:
    if not 0 <= rva < len(mapped):
        return None
    raw = mapped[rva: rva + limit].split(b"\0", 1)[0]
    return raw.decode("ascii") if raw and all(32 <= c < 127 for c in raw) else None


def class_bindings(path: Path) -> list[dict]:
    """Pair each CPfs1800 constructor's vtable store with the strings it pushes nearby."""
    from rtti_map import recover
    pe = _pe(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    mapped = pe.get_memory_mapped_image()
    bindings = []
    for cls in recover(path)["classes"]:
        for table in cls["vtables"]:
            vtable = int(table["vtable_va"], 16)
            store = b"\xc7\x06" + struct.pack("<I", vtable)  # mov dword ptr [esi], vtable
            for match in re.finditer(re.escape(store), mapped):
                pushes = []
                window = mapped[match.start() - 0x20: match.start() + 0x60]
                for push in re.finditer(rb"\x68(....)", window, re.S):
                    target = struct.unpack("<I", push[1])[0] - base
                    text = _ascii_at(mapped, target)
                    if text and len(text) >= 2:
                        pushes.append({"va": hex(base + match.start() - 0x20 + push.start()), "string": text})
                driver = next((p["string"] for p in pushes if not p["string"].upper().endswith(".GG")), None)
                gamma = next((p["string"] for p in pushes if p["string"].upper().endswith(".GG")), None)
                bindings.append({"class": cls["name"], "vtable_va": hex(vtable),
                                 "vtable_store_va": hex(base + match.start()),
                                 "driver_name": driver, "gamma_file": gamma, "pushes": pushes})
    return bindings


def descriptor_checks(path: Path) -> list[dict]:
    """Collect 16-bit compare immediates after each USBSCAN descriptor IOCTL push."""
    import capstone
    pe = _pe(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    mapped = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    checks = []
    for match in re.finditer(re.escape(b"\x68" + struct.pack("<I", IOCTL_GET_DEVICE_DESCRIPTOR)), mapped):
        constants = []
        for insn in md.disasm(mapped[match.start(): match.start() + 0x90], base + match.start()):
            if insn.mnemonic == "cmp" and ", 0x" in insn.op_str:
                constants.append(int(insn.op_str.rsplit(", ", 1)[1], 16))
            elif insn.mnemonic == "mov" and insn.op_str.startswith("eax, 0x"):
                constants.append(int(insn.op_str.split(", ")[1], 16))  # PF1800LC loads the PID into eax first
            if insn.mnemonic in ("ret", "call") and insn.address > base + match.start() + 0x10 and constants:
                break
        words = [c for c in constants if 0 < c <= 0xFFFF and c not in (1, 0x7F)]
        pairs = [f"{words[i]:04X}:{words[i + 1]:04X}" for i in range(0, len(words) - 1, 2)]
        checks.append({"ioctl_push_va": hex(base + match.start()), "accepted_vid_pid": pairs})
    return checks


def survey(payload: Path, inventory: Path) -> dict:
    files = {row["path"]: row for row in json.loads(inventory.read_text(encoding="utf-8"))["files"]}
    identities = {}
    for rel, expected in EXPECTED.items():
        actual = sha256(payload / rel)
        if actual != expected or files[rel]["sha256"].upper() != expected:
            raise SystemExit(f"hash mismatch for {rel}")
        identities[rel] = actual
    named_scan08 = [p for p in files if Path(p).name.casefold() == "scan08.dll"]

    bene = payload / "CyberViewX_SF/BeneScan.dll"
    bpe = _pe(bene)
    rva = BENESCAN_TABLE_VA - bpe.OPTIONAL_HEADER.ImageBase
    count = (BENESCAN_TABLE_END_VA - BENESCAN_TABLE_VA) // RECORD_SIZE
    records = []
    for row in parse_model_records(bpe.get_memory_mapped_image(), rva, count):
        row["record_va"] = hex(BENESCAN_TABLE_VA + row["index"] * RECORD_SIZE)
        row["model_code_hex"] = hex(row["model_code"])
        row["present_in_payload"] = sorted(
            p for p in files if Path(p).name.casefold() == row["module"].casefold())
        records.append(row)

    modules = {}
    for rel in ("CyberViewX_SF/LC.dll", "WXP_DLL/PF1800LC.Dll", "system/SQ_SCAN.DLL"):
        pe = _pe(payload / rel)
        export = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        modules[rel] = {
            "timestamp": pe.FILE_HEADER.TimeDateStamp,
            "version_resources": _versions(pe),
            "export_directory_name": export.name.decode() if export and export.name else None,
            "exports": sorted(s.name.decode() for s in getattr(export, "symbols", []) if s.name),
            "imports": {lib.dll.decode(): sorted(i.name.decode() for i in lib.imports if i.name)
                        for lib in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])},
            "usbscan_descriptor_checks": descriptor_checks(payload / rel),
        }

    infs = {p: inf_hardware_ids((payload / p).read_text(encoding="latin-1"))
            for p in sorted(files) if p.casefold().endswith(".inf")}
    gammas = {p: gamma_header((payload / p).read_text(encoding="latin-1"))
              for p in sorted(files) if re.fullmatch(r"GAMMA/\d+\.gg", p, re.I)}
    wia = (payload / "WXP_DLL/PWiaScnr.dll").read_bytes()
    wia_pairs = []
    for match in re.finditer(rb"\.\?AVCPfs1800([A-Za-z]+)@@\x00", wia):
        tail = re.findall(rb"[\x20-\x7e]{2,}", wia[match.end(): match.end() + 0x30])
        wia_pairs.append({"class": f"CPfs1800{match[1].decode()}",
                          "following_strings": [t.decode() for t in tail[:2]]})

    return {"evidence": "STATIC", "payload_identities": identities,
            "payload_files_named_scan08_dll": named_scan08,
            "benescan_model_table": records,
            "cyberviewx_class_bindings": class_bindings(payload / "Resource_ENG/CyberViewX.ds"),
            "scan08_lineage_modules": modules,
            "pwiascnr_class_strings": wia_pairs,
            "inf_usb_hardware_ids": infs, "gamma_headers": gammas}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(survey(args.payload.resolve(), args.inventory), indent=2) + "\n",
                           encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
