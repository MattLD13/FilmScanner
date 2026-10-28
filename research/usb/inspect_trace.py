"""Decode explicit hex JSONL records; input is never treated as a command.

Each input line: {"kind":"setup|descriptors|usbip-submit|command","hex":"..."}.
All rows are reported even when unknown/malformed; output is an analysis artifact,
not a raw trace or evidence that CyberView or a physical device generated input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .protocol import MAX_TRANSFER, ProtocolError, SetupPacket, decode_command, parse_descriptors
from .usbip import parse_submit


def inspect_record(record: dict) -> dict:
    raw_hex = record.get("hex")
    if not isinstance(raw_hex, str) or len(raw_hex) > MAX_TRANSFER * 2:
        raise ProtocolError("Missing or oversized hex field")
    try:
        data = bytes.fromhex(raw_hex)
    except ValueError as error:
        raise ProtocolError("Invalid hexadecimal input") from error
    decoders = {"setup": lambda b: SetupPacket.parse(b).to_dict(),
                "descriptors": parse_descriptors, "usbip-submit": parse_submit,
                "command": decode_command}
    kind = record.get("kind")
    if kind not in decoders:
        raise ProtocolError("Unknown record kind")
    return {"kind": kind, "decoded": decoders[kind](data), "evidence": "user-supplied-passive-input"}


def inspect_lines(lines):
    for index, line in enumerate(lines, 1):
        try:
            if len(line) > MAX_TRANSFER * 2 + 4096:
                raise ProtocolError("Input row too large")
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ProtocolError("Record must be a JSON object")
            yield {"line": index, "status": "decoded"} | inspect_record(record)
        except (ValueError, TypeError) as error:
            yield {"line": index, "status": "rejected", "error": str(error)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Output must not overwrite source evidence")
    with args.input.open(encoding="utf-8") as source, args.output.open("x", encoding="utf-8") as target:
        for result in inspect_lines(source):
            target.write(json.dumps(result, sort_keys=True) + "\n")
