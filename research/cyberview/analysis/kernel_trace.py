"""Summarize a tracerpt CSV of the NT Kernel Logger (process, image, file I/O).

Input is the guest's own trace text; nothing here touches a device. Output keeps
first occurrences of model-module image loads and file opens in time order, so a
missing module (open attempts with no image load) is visible.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATH_FIELD = re.compile(r'"([^"]*)"\s*,?\s*$')
TIMESTAMP_COLUMN = 16


def parse_line(line: str) -> dict | None:
    """One tracerpt CSV event row -> event, type, pid, timestamp, path; None if not an event row."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) <= TIMESTAMP_COLUMN or not parts[TIMESTAMP_COLUMN].isdigit():
        return None
    match = PATH_FIELD.search(line)
    pid = parts[9]
    return {"event": parts[0], "type": parts[1], "pid": int(pid, 16) if pid.startswith("0x") else pid,
            "timestamp": int(parts[TIMESTAMP_COLUMN]), "path": match.group(1) if match else None}


def first_events(lines, pattern: str) -> list[dict]:
    """First image Load/DCStart and file Create per (event, type, path), filtered by module-name regex."""
    wanted = re.compile(pattern, re.I)
    seen = {}
    for line in lines:
        row = parse_line(line)
        if not row or not row["path"]:
            continue
        if not ((row["event"] == "Image" and row["type"] in ("Load", "DCStart"))
                or (row["event"] == "FileIo" and row["type"] == "Create")):
            continue
        name = row["path"].replace("\\", "/").rsplit("/", 1)[-1]
        if not wanted.search(name):
            continue
        key = (row["event"], row["type"], row["path"].casefold())
        if key not in seen or row["timestamp"] < seen[key]["timestamp"]:
            seen[key] = row
    ordered = sorted(seen.values(), key=lambda r: r["timestamp"])
    if ordered:
        start = ordered[0]["timestamp"]
        for row in ordered:
            row["seconds"] = round((row["timestamp"] - start) / 1e7, 4)
    return ordered


def module_outcomes(events: list[dict]) -> dict[str, dict]:
    """Per module filename: number of distinct open paths and whether any image load followed."""
    outcome = {}
    for row in events:
        name = row["path"].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        entry = outcome.setdefault(name, {"open_paths": 0, "image_loaded": False, "loaded_from": None})
        if row["event"] == "FileIo":
            entry["open_paths"] += 1
        else:
            entry["image_loaded"] = True
            entry["loaded_from"] = entry["loaded_from"] or row["path"]
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--pattern", default=r"scan08|^lc\.dll|pf1800|pf2700|bene|rawscan|pf7250|ps7200|ss3600|"
                        r"sq_scan|io_port|fvc\.dll|usbscan|geneusb|daspi|cyberviewx|dcvcom|pfsloader")
    args = parser.parse_args()
    lines = [line for path in args.inputs for line in path.read_text(encoding="latin-1").splitlines()]
    events = first_events(lines, args.pattern)
    args.output.write_text(json.dumps({"evidence": "GUEST OBSERVED", "events": events,
                                       "modules": module_outcomes(events)}, indent=2) + "\n", encoding="utf-8")
    print(f"{len(events)} events -> {args.output}")


if __name__ == "__main__":
    main()
