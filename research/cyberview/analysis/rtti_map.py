"""Recover MSVC32 RTTI/vtable candidates without executing vendor code.

The address relationships are static facts; automatic candidate detection does
not assign semantics to unnamed virtual methods.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import pefile


def recover(path: Path) -> dict:
    data = path.read_bytes()
    pe = pefile.PE(data=data)
    if pe.OPTIONAL_HEADER.Magic != 0x10B:
        raise ValueError("Only MSVC32 PE supported")
    base = pe.OPTIONAL_HEADER.ImageBase
    mapped = pe.get_memory_mapped_image()
    executable = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData))
                  for s in pe.sections if s.Characteristics & 0x20000000]
    def is_code(va):
        return any(start <= va < end for start, end in executable)
    def refs(va):
        return [m.start() for m in re.finditer(re.escape(struct.pack("<I", va)), mapped)]
    classes = []
    for match in re.finditer(rb"\.\?AVCPfs[A-Za-z0-9_]+@@\x00", mapped):
        name = match[0][4:-3].decode()
        if "1800" not in name:
            continue
        td = match.start() - 8 + base
        vtables = []
        for td_ref in refs(td):
            col_rva = td_ref - 12
            if col_rva < 0 or col_rva + 20 > len(mapped):
                continue
            signature, offset, cd_offset, _, hierarchy = struct.unpack_from("<IIIII", mapped, col_rva)
            if signature != 0 or offset > 4096 or cd_offset > 4096:
                continue
            for col_ref in refs(col_rva + base):
                methods = []
                start = col_ref + 4
                for index in range(256):
                    current = start + index * 4
                    if current + 4 > len(mapped):
                        break
                    va = struct.unpack_from("<I", mapped, current)[0]
                    if not is_code(va):
                        break
                    methods.append({"slot": index, "va": hex(va)})
                if methods:
                    vtables.append({"col_va": hex(col_rva + base), "this_offset": offset,
                                    "vtable_va": hex(start + base), "methods": methods})
        classes.append({"name": name, "type_descriptor_va": hex(td), "vtables": vtables})
    return {"binary": path.name, "sha256": hashlib.sha256(data).hexdigest(),
            "image_base": hex(base), "evidence": "static-MSCV32-RTTI-candidate-map", "classes": classes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(recover(args.binary), indent=2), encoding="utf-8")
