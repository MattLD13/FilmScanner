"""Static feature catalogue of the installed AFL scanner stack. Executes no vendor code.

For SCAN08.dll it reads ScannerDeviceIO's two jump tables, follows every selector
into the module's own functions (call graph to a bounded depth) and records the
lower-level SQ_Scan/system imports, strings and global state each one reaches, plus
the parameter offsets the selector's wrapper reads or writes. For SQ_Scan.dll,
IO_PORT.DLL and FVC.DLL it records exports and what each export calls.

  research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/scan08_catalog.py \
      --output research/cyberview/analysis/evidence/scan08-catalog-2026-10-30.json

Hashes are checked against the installed 1.0.3.6 module the native bridge pins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
from pathlib import Path

import capstone
import pefile

WINDIR = Path(os.environ.get('WINDIR', r'C:\Windows'))
SCAN08 = WINDIR / 'twain_32' / 'CyberViewX_MF' / 'SCAN08.dll'
SYSWOW = WINDIR / 'SysWOW64'
SCAN08_SHA256 = 'da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f'
DISPATCH = 0x10015390
TABLE_LOW, TABLE_LOW_COUNT = 0x10015615, 35      # selectors 1..35
TABLE_HIGH, TABLE_HIGH_COUNT = 0x100156a1, 6     # selectors 1002..1007
SELECTOR_1001 = 0x100155c9
BUSY_FLAG = 0x10018b98


class Image:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.pe = pefile.PE(data=self.data)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.mem = self.pe.get_memory_mapped_image()
        text = next(s for s in self.pe.sections if s.Name.startswith(b'.text'))
        self.text_lo = self.base + text.VirtualAddress
        self.text_hi = self.text_lo + text.Misc_VirtualSize
        self.imports = {}
        for entry in getattr(self.pe, 'DIRECTORY_ENTRY_IMPORT', []):
            dll = entry.dll.decode()
            for imp in entry.imports:
                self.imports[imp.address] = f"{dll}!{imp.name.decode() if imp.name else f'#{imp.ordinal}'}"
        # name -> address; several names can share one address (SQ_Scan aliases
        # SafeInitialChip and StopAutoScan).
        self.exports = {}
        if hasattr(self.pe, 'DIRECTORY_ENTRY_EXPORT'):
            for e in self.pe.DIRECTORY_ENTRY_EXPORT.symbols:
                self.exports[e.name.decode() if e.name else f'#{e.ordinal}'] = self.base + e.address
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.md.detail = True
        self.md.skipdata = True

    def dword(self, va):
        return struct.unpack_from('<I', self.mem, va - self.base)[0]

    def string_at(self, va):
        if not (self.base <= va < self.base + len(self.mem)):
            return None
        raw = self.mem[va - self.base: va - self.base + 300]
        ascii_part = raw.split(b'\x00')[0]
        if len(ascii_part) >= 3 and all(32 <= c < 127 or c in (9, 10, 13) for c in ascii_part):
            return ascii_part.decode('latin-1')
        if len(raw) > 6 and raw[1] == 0 and raw[3] == 0:  # UTF-16
            text = raw.decode('utf-16le', 'ignore').split('\x00')[0]
            if len(text) >= 3 and all(31 < ord(c) < 127 for c in text):
                return text
        return None

    def function(self, start, limit=0x4000):
        """Linear disassembly to the last RET not jumped over; returns instructions."""
        out, furthest = [], start
        for ins in self.md.disasm(self.mem[start - self.base: start - self.base + limit], start):
            out.append(ins)
            if ins.group(capstone.CS_GRP_JUMP) and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
                target = ins.operands[0].imm
                if start <= target < start + limit:
                    furthest = max(furthest, target)
            if ins.mnemonic in ('ret', 'retf') and ins.address >= furthest:
                break
            if ins.mnemonic == 'int3' and ins.address >= furthest and len(out) > 1:
                break
        return out


def call_target(img: Image, ins):
    op = ins.operands[0] if ins.operands else None
    if op is None:
        return None, None
    if op.type == capstone.x86.X86_OP_IMM:
        return 'local', op.imm
    if op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
        return 'import', img.imports.get(op.mem.disp & 0xffffffff, f'[{op.mem.disp & 0xffffffff:#x}]')
    return 'indirect', ins.op_str


def follow_thunk(img: Image, va):
    """jmp [IAT] thunks become their import name."""
    ins = next(img.md.disasm(img.mem[va - img.base: va - img.base + 8], va), None)
    if ins and ins.mnemonic == 'jmp' and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_MEM:
        return img.imports.get(ins.operands[0].mem.disp & 0xffffffff)
    return None


def walk(img: Image, start, depth=6):
    """Call graph from ``start``: local functions, imports, strings, globals touched."""
    seen, imports, strings, globals_, indirect = set(), {}, {}, set(), 0
    order = [(start, 0)]
    while order:
        va, d = order.pop()
        if va in seen or not (img.text_lo <= va < img.text_hi):
            continue
        seen.add(va)
        thunk = follow_thunk(img, va)
        if thunk:
            imports[thunk] = imports.get(thunk, 0) + 1
            continue
        for ins in img.function(va):
            if ins.mnemonic == 'call':
                kind, target = call_target(img, ins)
                if kind == 'import':
                    imports[target] = imports.get(target, 0) + 1
                elif kind == 'local' and d < depth:
                    order.append((target, d + 1))
                elif kind == 'indirect':
                    indirect += 1
            for op in ins.operands:
                value = None
                if op.type == capstone.x86.X86_OP_IMM:
                    value = op.imm & 0xffffffff
                elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    value = op.mem.disp & 0xffffffff
                    if img.base <= value < img.base + len(img.mem) and not (img.text_lo <= value < img.text_hi):
                        if value not in img.imports:
                            globals_.add(value)
                if value is not None:
                    text = img.string_at(value)
                    if text:
                        strings[hex(value)] = text
    return {'functions': len(seen), 'imports': dict(sorted(imports.items())), 'strings': strings,
            'globals': sorted(hex(g) for g in globals_), 'indirect_calls': indirect}


def parameter_access(img: Image, wrapper):
    """Offsets the wrapper reads/writes through its pointer argument ([ebp+8])."""
    regs, accesses = set(), {}
    for ins in img.function(wrapper):
        ops = ins.operands
        if ins.mnemonic == 'mov' and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG and ops[1].type == capstone.x86.X86_OP_MEM:
            m = ops[1].mem
            if m.base == capstone.x86.X86_REG_EBP and m.disp == 8:
                regs.add(ops[0].reg)
                continue
        for i, op in enumerate(ops):
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base in regs and op.mem.index == 0:
                write = i == 0 and ins.mnemonic in ('mov', 'add', 'sub', 'and', 'or', 'inc', 'dec', 'fstp', 'movsd', 'stosd')
                key = f'{op.mem.disp:#x}'
                entry = accesses.setdefault(key, {'size': op.size, 'read': False, 'write': False})
                entry['write' if write else 'read'] = True
        if ins.mnemonic == 'mov' and ops and ops[0].type == capstone.x86.X86_OP_REG and ops[0].reg in regs:
            regs.discard(ops[0].reg)
    return dict(sorted(accesses.items(), key=lambda kv: int(kv[0], 16)))


def case_stub(img: Image, va):
    """The dispatcher's case: which wrapper it calls and how the parameter is passed."""
    calls, passes = [], 'none'
    constant = None
    for ins in img.md.disasm(img.mem[va - img.base: va - img.base + 64], va):
        if ins.mnemonic == 'mov' and 'ebp + 0xc' in ins.op_str:
            passes = 'pointer'
        if ins.mnemonic == 'mov' and passes == 'pointer' and re.search(r'dword ptr \[e[a-d]x\]$', ins.op_str):
            passes = 'dereferenced dword'
        if ins.mnemonic == 'mov' and ins.op_str.startswith('eax, ') and ins.op_str[5:].startswith('0x') or ins.op_str == 'eax, 1':
            try:
                constant = int(ins.op_str.split(', ')[1], 16 if '0x' in ins.op_str else 10)
            except ValueError:
                pass
        if ins.mnemonic == 'call':
            kind, target = call_target(img, ins)
            calls.append(target if kind == 'local' else str(target))
        if ins.mnemonic == 'jmp':
            break
    return calls, passes, constant


def catalogue_scan08(img: Image):
    cases = {}
    for i in range(TABLE_LOW_COUNT):
        cases[i + 1] = img.dword(TABLE_LOW + 4 * i)
    cases[1001] = SELECTOR_1001
    for i in range(TABLE_HIGH_COUNT):
        cases[1002 + i] = img.dword(TABLE_HIGH + 4 * i)
    result = {}
    by_target = {}
    for sel, target in cases.items():
        by_target.setdefault(target, []).append(sel)
    for sel, target in sorted(cases.items()):
        calls, passes, constant = case_stub(img, target)
        if target == 0x1001560f or (not calls and constant is None):
            result[sel] = {'case': hex(target), 'implemented': False, 'note': 'falls to the default (returns 0)'}
            continue
        entry = {'case': hex(target), 'implemented': True, 'parameter': passes,
                 'shared_with': [s for s in by_target[target] if s != sel]}
        if not calls:
            entry['returns_constant'] = constant
            result[sel] = entry
            continue
        wrapper = calls[0] if isinstance(calls[0], int) else None
        entry['wrapper'] = hex(wrapper) if wrapper else calls[0]
        if wrapper:
            entry['parameter_offsets'] = parameter_access(img, wrapper)
            entry['reach'] = walk(img, wrapper)
        result[sel] = entry
    return result


def catalogue_exports(img: Image, depth=4):
    out = {}
    for name, va in sorted(img.exports.items(), key=lambda item: (item[1], item[0])):
        info = walk(img, va, depth)
        aliases = sorted(n for n, a in img.exports.items() if a == va and n != name)
        out[name] = {'address': hex(va), 'aliases': aliases, 'functions': info['functions'], 'imports': info['imports'],
                     'strings': sorted(set(info['strings'].values()))}
    return out


def all_strings(img: Image, minimum=5):
    found = {}
    for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minimum, img.mem):
        va = img.base + m.start()
        if not (img.text_lo <= va < img.text_hi):
            found[hex(va)] = m.group().decode('latin-1')
    return found


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if sha256(SCAN08) != SCAN08_SHA256:
        raise SystemExit('SCAN08.dll is not the reviewed 1.0.3.6 build')
    scan08 = Image(SCAN08)
    report = {'scan08': {'path': str(SCAN08), 'sha256': SCAN08_SHA256, 'dispatcher': hex(DISPATCH),
                         'busy_wait_flag': hex(BUSY_FLAG), 'selectors': catalogue_scan08(scan08),
                         'imports': sorted(set(scan08.imports.values())), 'strings': all_strings(scan08)}}
    for name in ('SQ_Scan.dll', 'IO_PORT.DLL', 'FVC.DLL'):
        path = SYSWOW / name
        if path.exists():
            img = Image(path)
            report[name] = {'path': str(path), 'sha256': sha256(path), 'exports': catalogue_exports(img),
                            'imports': sorted(set(img.imports.values())), 'strings': all_strings(img)}
    Path(args.output).write_text(json.dumps(report, indent=1, sort_keys=False), encoding='utf-8')
    print(f"selectors: {sum(1 for s in report['scan08']['selectors'].values() if s['implemented'])} implemented")
    for name in ('SQ_Scan.dll', 'IO_PORT.DLL', 'FVC.DLL'):
        if name in report:
            print(name, len(report[name]['exports']), 'exports')


if __name__ == '__main__':
    main()
