"""Static PE survey. Never loads or executes the supplied image.

Requires the optional research pefile package, isolated from FRAME dependencies.
Output addresses are preferred image virtual addresses, not runtime addresses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pefile

INTEREST = re.compile(
    r"usb|vid_|pid_|scan|twain|scsi|focus|calib|expos|gain|firmware|motor|film|"
    r"1800|prime|pacific|deviceio|createfile|readfile|writefile|loadlibrary|inquir|"
    r"eject|prescan|position|genesys|geneusb|loader|download|update|sensor",
    re.I,
)


def strings(data: bytes):
    for encoding, pattern in (("ascii", rb"[\x20-\x7e]{5,}"),
                              ("utf-16le", rb"(?:[\x20-\x7e]\x00){5,}")):
        for match in re.finditer(pattern, data):
            value = match[0].decode(encoding)
            if INTEREST.search(value):
                yield match.start(), encoding, value


def survey(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    result = {"path": path.relative_to(root).as_posix(), "size": len(data),
              "sha256": hashlib.sha256(data).hexdigest(), "evidence": "static-file"}
    try:
        pe = pefile.PE(data=data, fast_load=False)
    except pefile.PEFormatError:
        result["kind"] = "non-PE"
        result["interesting_strings"] = [
            {"offset": hex(o), "encoding": e, "value": s} for o, e, s in strings(data)]
        return result
    base = pe.OPTIONAL_HEADER.ImageBase
    result.update({"kind": "PE", "machine": hex(pe.FILE_HEADER.Machine),
                   "image_base": hex(base), "entry_va": hex(base + pe.OPTIONAL_HEADER.AddressOfEntryPoint),
                   "timestamp": pe.FILE_HEADER.TimeDateStamp,
                   "sections": [{"name": s.Name.rstrip(b"\0").decode("ascii", "replace"),
                       "rva": hex(s.VirtualAddress), "raw_offset": hex(s.PointerToRawData),
                       "raw_size": s.SizeOfRawData} for s in pe.sections]})
    versions = {}
    for group in getattr(pe, "FileInfo", []):
        for block in group:
            for table in getattr(block, "StringTable", []):
                versions.update({k.decode(errors="replace"): v.decode(errors="replace")
                                 for k, v in table.entries.items()})
    result["versions"] = versions
    result["imports"] = [{"dll": lib.dll.decode(errors="replace"),
        "symbols": [{"name": item.name.decode(errors="replace") if item.name else None,
                     "ordinal": item.ordinal, "iat_va": hex(item.address)} for item in lib.imports]}
        for lib in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
    result["exports"] = [{"name": s.name.decode(errors="replace") if s.name else None,
                          "ordinal": s.ordinal, "va": hex(base + s.address)}
                         for s in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])]
    hits = []
    for offset, encoding, value in strings(data):
        try:
            rva = pe.get_rva_from_offset(offset)
            va = hex(base + rva) if rva is not None else None
        except pefile.PEFormatError:
            va = None
        hits.append({"offset": hex(offset), "va": va, "encoding": encoding, "value": value})
    result["interesting_strings"] = hits
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    report = {"tool": "pefile", "version": pefile.__version__,
              "files": [survey(path, root) for path in sorted(root.rglob("*")) if path.is_file()]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Surveyed {len(report['files'])} files into {args.output}")


if __name__ == "__main__":
    main()
