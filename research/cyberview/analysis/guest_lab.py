"""Bounded offline QEMU evaluation guest launcher.

Guest input (keys, ASCII text, absolute tablet clicks) goes only through our own
QMP socket and every event is appended to inputs.jsonl. It never touches the host
desktop. Credentials are never typed by this tool.

Media changes are limited to the hash-recorded vendor/tools CDs and this run's
blank evidence floppy, the only path for results out of the network-less guest.

Use the Computer Use workflow for UI interaction. The only QMP commands exposed
here inspect state, save a screenshot, or shut down our own QEMU process.
Runtime paths, process IDs, disks and license/media remain in ignored artifacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[3]
LAB = WORKSPACE / "research/cyberview/.artifacts/guest-lab"
QEMU = WORKSPACE / "research/.tools/qemu-portable"
BASE = WORKSPACE / "research/cyberview/.artifacts/guest-media/server2008-x86/vhd/Windows2008Fullx86Ent.vhd"
VENDOR = WORKSPACE / "research/cyberview/.artifacts/official-pf1800afl-v1.3/PrimeFilm_1800AFL_Windows_SF_ENG_1.3.exe"
BASE_SHA = "bc57268875ab4589f2f11b766fa214bbe11b5349b427ec518e2a6316e2ded19d"
VENDOR_SHA = "ebcbe798fe577b9461df22db3bde6240185e0553e65eb9b93d139d367f9109cf"
TOOLS = Path(__file__).resolve().parent / "guest_tools"
SIMULATOR = WORKSPACE / "research/cyberview/.artifacts/afl-sim/SCAN08.dll"
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reserve():
    if shutil.disk_usage(LAB).free < 8 * 1024**3:
        raise RuntimeError("Minimum 8GiB host reserve reached")
    overlay = LAB / "experiment.qcow2"
    if overlay.exists() and overlay.stat().st_size > 2 * 1024**3:
        raise RuntimeError("Guest overlay exceeds 2GiB experiment allocation limit")


def qmp(port, execute, arguments=None):
    if execute not in {"query-status", "query-block", "screendump", "quit", "system_powerdown",
                       "blockdev-change-medium", "eject", "send-key", "input-send-event"}:
        raise ValueError("Only inspection/screenshot/own-guest shutdown commands allowed")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(10)
        stream = connection.makefile("rb")
        greeting = json.loads(stream.readline())
        connection.sendall(b'{"execute":"qmp_capabilities","id":1}\n')
        while json.loads(stream.readline()).get("id") != 1:
            pass
        request = {"execute": execute, "id": 2}
        if arguments:
            request["arguments"] = arguments
        connection.sendall((json.dumps(request) + "\n").encode())
        while True:
            row = json.loads(stream.readline())
            if row.get("id") == 2:
                if "error" in row:
                    raise RuntimeError(row["error"])
                return row["return"]


def prepare():
    import pycdlib
    LAB.mkdir(parents=True, exist_ok=True)
    reserve()
    assert digest(BASE) == BASE_SHA, "Base VHD hash mismatch"
    assert digest(VENDOR) == VENDOR_SHA, "Vendor installer hash mismatch"
    overlay = LAB / "experiment.qcow2"
    if overlay.exists():
        raise FileExistsError("Preserve the existing experiment; choose an explicit new lab directory")
    subprocess.run([str(QEMU / "qemu-img.exe"), "create", "-f", "qcow2", "-F", "vpc",
                    "-b", str(BASE), str(overlay)], check=True, creationflags=FLAGS)
    image = pycdlib.PyCdlib()
    image.new(interchange_level=3, joliet=3, vol_ident="FRAME_RESEARCH")
    image.add_file(str(VENDOR), iso_path="/CYBER.EXE;1", joliet_path="/CyberView-Official.exe")
    manifest = LAB / "vendor-sha256.txt"
    manifest.write_text(VENDOR_SHA + "  CyberView-Official.exe\n", encoding="ascii")
    image.add_file(str(manifest), iso_path="/SHA256.TXT;1", joliet_path="/SHA256.txt")
    image.write(str(LAB / "vendor.iso")); image.close()
    (LAB / "preparation.json").write_text(json.dumps({
        "prepared_utc": datetime.now(timezone.utc).isoformat(), "base_sha256": BASE_SHA,
        "vendor_sha256": VENDOR_SHA, "iso_sha256": digest(LAB / "vendor.iso"),
        "virtualization": "QEMU TCG", "network": "no NIC", "base_read_only": True,
        "guest_os": "official Microsoft Windows Server2008 Enterprise x86 evaluation",
        "evaluation_only": True, "activation": "prohibited by supplied EULA"}, indent=2))
    print("Prepared verified base + qcow2 overlay + read-only vendor CD")


def start(budget_minutes=5):
    reserve()
    preparation = json.loads((LAB / "preparation.json").read_text())
    if digest(BASE) != BASE_SHA or digest(VENDOR) != VENDOR_SHA:
        raise RuntimeError("Preserved base or vendor source hash changed")
    if digest(LAB / "vendor.iso") != preparation["iso_sha256"]:
        raise RuntimeError("Read-only vendor ISO hash changed")
    if (LAB / "run.json").exists():
        old = json.loads((LAB / "run.json").read_text())
        try:
            qmp(old["qmp_port"], "query-status")
        except (OSError, ValueError):
            pass
        else:
            raise RuntimeError("Guest already running")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0)); port = reservation.getsockname()[1]
    options = ["-name", "FRAME CyberView isolated evaluation", "-machine", "pc", "-accel", "tcg",
        "-m", "1024", "-smp", "2", "-nic", "none", "-usb", "-device", "usb-tablet", "-rtc", "base=utc,clock=host",
        "-display", "gtk", "-vga", "std", "-no-reboot", "-monitor", "none",
        "-qmp", f"tcp:127.0.0.1:{port},server=on,wait=off",
        "-blockdev", json.dumps({"driver":"file","filename":str(BASE),"node-name":"base-file","read-only":True}),
        "-blockdev", json.dumps({"driver":"vpc","file":"base-file","node-name":"base-vhd","read-only":True}),
        "-blockdev", json.dumps({"driver":"file","filename":str(LAB / 'experiment.qcow2'),"node-name":"overlay-file"}),
        "-blockdev", json.dumps({"driver":"qcow2","file":"overlay-file","backing":"base-vhd","node-name":"experiment"}),
        "-device", "ide-hd,drive=experiment", "-drive",
        f"file={LAB / 'vendor.iso'},format=raw,media=cdrom,readonly=on,if=ide,index=2"]
    with (LAB / "qemu-stdout.txt").open("ab") as out, (LAB / "qemu-stderr.txt").open("ab") as err:
        process = subprocess.Popen([str(QEMU / "qemu-system-i386.exe"), *options],
                                   stdout=out, stderr=err, creationflags=FLAGS)
    record = {"pid": process.pid, "qmp_port": port, "started_utc": datetime.now(timezone.utc).isoformat(),
              "options": options, "guest_vendor_app_executed": False, "scanner_attached": False}
    (LAB / "run.json").write_text(json.dumps(record, indent=2))
    record["watchdog_budget_minutes"] = budget_minutes
    (LAB / "run.json").write_text(json.dumps(record, indent=2))
    launch_watchdog(port, budget_minutes)
    print(json.dumps({"started_pid": process.pid, "qmp_port": port, "network": "none", "base": "read-only"}))


def build_tools_iso():
    """Tools CD from tracked guest_tools scripts plus the built research simulator, if present."""
    import pycdlib
    image = pycdlib.PyCdlib()
    image.new(interchange_level=3, joliet=3, vol_ident="FRAME_TOOLS")
    files = {}
    sources = [(p, p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
               for p in sorted(TOOLS.glob("*.CMD"))]
    if SIMULATOR.exists():
        sources.append((SIMULATOR, SIMULATOR.read_bytes()))
    for path, data in sources:
        name = path.name.upper()
        image.add_fp(io.BytesIO(data), len(data), f"/{name};1", joliet_path=f"/{name}")
        files[name] = hashlib.sha256(data).hexdigest()
    image.write(str(LAB / "tools.iso")); image.close()
    return files


def new_floppy():
    from fat12 import blank_image
    floppy = "evidence-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".img"
    (LAB / floppy).write_bytes(blank_image())
    return floppy


def make_media(refresh=False):
    """Tools CD plus one blank evidence floppy. Refresh rebuilds both and keeps old floppies."""
    if (LAB / "media.json").exists() and not refresh:
        raise FileExistsError("Media already made for this lab; use refresh-media for a new run")
    files = build_tools_iso()
    floppy = new_floppy()
    media = {"made_utc": datetime.now(timezone.utc).isoformat(), "scripts": files,
             "tools_iso_sha256": digest(LAB / "tools.iso"), "evidence_floppy": floppy,
             "blank_floppy_sha256": digest(LAB / floppy)}
    if refresh:
        history = json.loads((LAB / "media.json").read_text())
        media["previous"] = history.get("previous", []) + [{k: v for k, v in history.items() if k != "previous"}]
    (LAB / "media.json").write_text(json.dumps(media, indent=2))
    print(json.dumps({k: v for k, v in media.items() if k != "previous"}, indent=2))


def insert(port, kind):
    """Swap only our hash-recorded CDs or this run's evidence floppy into the guest."""
    media = json.loads((LAB / "media.json").read_text())
    if kind == "evidence":
        path, device, mode = LAB / media["evidence_floppy"], "floppy0", "read-write"
    else:
        path = LAB / ("vendor.iso" if kind == "vendor" else "tools.iso")
        expected = (json.loads((LAB / "preparation.json").read_text())["iso_sha256"] if kind == "vendor"
                    else media["tools_iso_sha256"])
        if digest(path) != expected:
            raise RuntimeError(f"{path.name} hash changed")
        device, mode = "ide1-cd0", "read-only"
    qmp(port, "blockdev-change-medium", {"device": device, "filename": str(path),
                                         "format": "raw", "read-only-mode": mode})
    print(json.dumps({"inserted": path.name, "device": device, "mode": mode}))


def read_evidence():
    """Copy root files from the evidence floppy into a new ignored directory with hashes."""
    from fat12 import read_root_files
    media = json.loads((LAB / "media.json").read_text())
    image = (LAB / media["evidence_floppy"]).read_bytes()
    out = LAB / ("collected-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out.mkdir()
    manifest = {"floppy": media["evidence_floppy"], "floppy_sha256": hashlib.sha256(image).hexdigest(), "files": {}}
    for name, data in read_root_files(image).items():
        if not re.fullmatch(r"[A-Z0-9_~$!#%&@^-]{1,8}(\.[A-Z0-9_~$!#%&@^-]{1,3})?", name):
            raise ValueError(f"Unsafe evidence filename {name!r}")
        (out / name).write_bytes(data)
        manifest["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(out)


SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9",
           ")": "0", "_": "minus", "+": "equal", ":": "semicolon", '"': "apostrophe", "<": "comma",
           ">": "dot", "?": "slash", "|": "backslash", "{": "bracket_left", "}": "bracket_right", "~": "grave_accent"}
PLAIN = {" ": "spc", "-": "minus", "=": "equal", ";": "semicolon", "'": "apostrophe", ",": "comma",
         ".": "dot", "/": "slash", "\\": "backslash", "[": "bracket_left", "]": "bracket_right", "`": "grave_accent"}


def qcodes(char):
    """QEMU qcodes for one printable ASCII character on a US keyboard layout."""
    if char.isascii() and char.isalnum():
        return (["shift"] if char.isupper() else []) + [char.lower()]
    if char in PLAIN:
        return [PLAIN[char]]
    if char in SHIFTED:
        return ["shift", SHIFTED[char]]
    raise ValueError(f"Unsupported character {char!r}")


def log_input(record):
    record["utc"] = datetime.now(timezone.utc).isoformat()
    with (LAB / "inputs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + chr(10))


def send_keys(port, combo):
    """Press one chord such as 'ret', 'tab', 'alt-n' or 'meta_l-r'."""
    keys = combo.split("-") if combo != "minus" else ["minus"]
    qmp(port, "send-key", {"keys": [{"type": "qcode", "data": k} for k in keys], "hold-time": 120})
    log_input({"kind": "key", "value": combo})


def type_text(port, text):
    for char in text:
        qmp(port, "send-key", {"keys": [{"type": "qcode", "data": k} for k in qcodes(char)], "hold-time": 60})
        time.sleep(0.08)
    log_input({"kind": "text", "value": text})


def click(port, x, y, width=800, height=600, button="left", double=False):
    """Absolute tablet click at screenshot pixel (x, y)."""
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("Click outside guest screen")
    position = [{"type": "abs", "data": {"axis": "x", "value": round(x * 32767 / (width - 1))}},
                {"type": "abs", "data": {"axis": "y", "value": round(y * 32767 / (height - 1))}}]
    qmp(port, "input-send-event", {"events": position})
    for _ in range(2 if double else 1):
        for down in (True, False):
            qmp(port, "input-send-event", {"events": [{"type": "btn", "data": {"down": down, "button": button}}]})
            time.sleep(0.05)
    log_input({"kind": "click", "x": x, "y": y, "button": button, "double": double})


def launch_watchdog(port, budget_minutes):
    with (LAB / "watchdog.txt").open("ab") as stream:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watchdog", "--port", str(port),
                                    "--budget-minutes", str(budget_minutes)],
                                   stdout=stream, stderr=stream, creationflags=FLAGS)
    (LAB / "watchdog.pid").write_text(str(process.pid))


def rewatch(port, budget_minutes):
    """Replace this run's watchdog with a fresh budget, so a logged-in guest need not reboot."""
    pid_file = LAB / "watchdog.pid"
    if pid_file.exists():
        subprocess.run(["taskkill", "/PID", pid_file.read_text().strip(), "/F"],
                       capture_output=True, creationflags=FLAGS)
    launch_watchdog(port, budget_minutes)
    run = json.loads((LAB / "run.json").read_text())
    run.setdefault("watchdog_extensions", []).append(
        {"utc": datetime.now(timezone.utc).isoformat(), "budget_minutes": budget_minutes})
    (LAB / "run.json").write_text(json.dumps(run, indent=2))
    print(json.dumps({"watchdog_budget_minutes": budget_minutes, "from_utc": datetime.now(timezone.utc).isoformat()}))


def watchdog(port, budget_minutes=5):
    """Bounded pass budget (default five minutes); stop only the QEMU at our saved QMP socket."""
    deadline = time.monotonic() + budget_minutes * 60
    while True:
        try:
            reserve()
            if time.monotonic() > deadline:
                raise RuntimeError(f"{budget_minutes}-minute evaluation pass budget reached")
            status = qmp(port, "query-status")
            print(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "status": status,
                "overlay_bytes": (LAB / "experiment.qcow2").stat().st_size,
                "host_free_bytes": shutil.disk_usage(LAB).free}), flush=True)
        except RuntimeError as error:
            print(str(error), flush=True)
            try: qmp(port, "quit")
            except OSError: pass
            return
        except OSError:
            return
        time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "start", "status", "screenshot", "stop", "verify-base", "watchdog",
                                           "make-media", "refresh-media", "insert", "eject-evidence", "read-evidence", "rewatch",
                                           "key", "type", "click", "dclick", "rclick"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--media", choices=["vendor", "tools", "evidence"])
    parser.add_argument("value", nargs="*", help="key chord, text, or x y")
    parser.add_argument("--budget-minutes", type=int, default=5, choices=range(1, 241),
                        help="hard stop for this pass; at most four hours")
    args = parser.parse_args()
    if args.action == "prepare": prepare()
    elif args.action == "start": start(args.budget_minutes)
    elif args.action == "watchdog": watchdog(args.port, args.budget_minutes)
    elif args.action == "make-media": make_media()
    elif args.action == "refresh-media": make_media(refresh=True)
    elif args.action == "read-evidence": read_evidence()
    elif args.action == "verify-base": print(json.dumps({"base_sha256": digest(BASE), "unchanged": digest(BASE) == BASE_SHA}))
    else:
        run = json.loads((LAB / "run.json").read_text()); port = run["qmp_port"]
        if args.action == "stop": print(qmp(port, "quit"))
        elif args.action == "insert": insert(port, args.media)
        elif args.action == "rewatch": rewatch(port, args.budget_minutes)
        elif args.action == "key":
            for combo in args.value: send_keys(port, combo)
        elif args.action == "type": type_text(port, " ".join(args.value))
        elif args.action in ("click", "dclick", "rclick"):
            click(port, int(args.value[0]), int(args.value[1]), button="right" if args.action == "rclick" else "left",
                  double=args.action == "dclick")
        elif args.action == "eject-evidence": print(qmp(port, "eject", {"device": "floppy0"}))
        elif args.action == "status":
            reserve(); print(json.dumps({"status": qmp(port,"query-status"), "block": qmp(port,"query-block"),
                "overlay_bytes": (LAB / "experiment.qcow2").stat().st_size,
                "host_free_bytes": shutil.disk_usage(LAB).free}, indent=2))
        else:
            path = LAB / ("guest-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".ppm")
            qmp(port, "screendump", {"filename": str(path)})
            print(path)
