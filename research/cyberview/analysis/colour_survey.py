"""Bounded static inspection of the installed CyberView colour pipeline.

This module reads PE bytes only. It never loads or executes vendor code.
Requires the optional pefile/capstone analysis environment.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import capstone
from scan08_catalog import Image


def instructions(image):
    for ins in image.md.disasm(image.mem[image.text_lo-image.base:image.text_hi-image.base], image.text_lo):
        if ins.id:
            yield ins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, default=Path('C:/Windows/twain_32/CyberViewX_MF/CyberViewX.ds'))
    parser.add_argument('--function', type=lambda s: int(s, 0))
    parser.add_argument('--xref', type=lambda s: int(s, 0))
    parser.add_argument('--disp', type=lambda s: int(s, 0))
    parser.add_argument('--limit', type=lambda s: int(s, 0), default=0x5000)
    args = parser.parse_args()
    image = Image(args.module)
    if args.function is not None:
        for ins in image.function(args.function, args.limit):
            comment = ''
            for op in ins.operands:
                value = op.imm if op.type == capstone.x86.X86_OP_IMM else op.mem.disp if op.type == capstone.x86.X86_OP_MEM else None
                if value:
                    string = image.string_at(value)
                    if string:
                        comment += ' ; ' + repr(string)
                    if value in image.imports:
                        comment += ' ; ' + image.imports[value]
            print(f'{ins.address:08x}: {ins.mnemonic:8s} {ins.op_str}{comment}')
    elif args.xref is not None or args.disp is not None:
        for ins in instructions(image):
            for op in ins.operands:
                if (args.xref is not None and ((op.type == capstone.x86.X86_OP_IMM and op.imm == args.xref) or
                                               (op.type == capstone.x86.X86_OP_MEM and op.mem.disp == args.xref)) or
                    args.disp is not None and op.type == capstone.x86.X86_OP_MEM and op.mem.disp == args.disp):
                    print(f'{ins.address:08x}: {ins.mnemonic:8s} {ins.op_str}')
                    break
    else:
        for name, address in image.exports.items():
            print(f'{address:08x}: {name}')


if __name__ == '__main__':
    main()
