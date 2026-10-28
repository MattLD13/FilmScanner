"""Bounded offline QEMU evaluation guest launcher. No guest UI input functions.

Use the Computer Use workflow for UI interaction. The only QMP commands exposed
here inspect state, save a screenshot, or shut down our own QEMU process.
Runtime paths, process IDs, disks and license/media remain in ignored artifacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
    if execute not in {"query-status", "query-block", "screendump", "quit", "system_powerdown"}:
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


def start():
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
    launch_watchdog(port)
    print(json.dumps({"started_pid": process.pid, "qmp_port": port, "network": "none", "base": "read-only"}))


def launch_watchdog(port):
    with (LAB / "watchdog.txt").open("ab") as stream:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watchdog", "--port", str(port)],
                         stdout=stream, stderr=stream, creationflags=FLAGS)


def watchdog(port):
    """Five-minute first-pass budget; stop only the QEMU at our saved QMP socket."""
    deadline = time.monotonic() + 300
    while True:
        try:
            reserve()
            if time.monotonic() > deadline:
                raise RuntimeError("Five-minute evaluation pass budget reached")
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
    parser.add_argument("action", choices=["prepare", "start", "status", "screenshot", "stop", "verify-base", "watchdog"])
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.action == "prepare": prepare()
    elif args.action == "start": start()
    elif args.action == "watchdog": watchdog(args.port)
    elif args.action == "verify-base": print(json.dumps({"base_sha256": digest(BASE), "unchanged": digest(BASE) == BASE_SHA}))
    else:
        run = json.loads((LAB / "run.json").read_text()); port = run["qmp_port"]
        if args.action == "stop": print(qmp(port, "quit"))
        elif args.action == "status":
            reserve(); print(json.dumps({"status": qmp(port,"query-status"), "block": qmp(port,"query-block"),
                "overlay_bytes": (LAB / "experiment.qcow2").stat().st_size,
                "host_free_bytes": shutil.disk_usage(LAB).free}, indent=2))
        else:
            path = LAB / ("guest-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".ppm")
            qmp(port, "screendump", {"filename": str(path)})
            print(path)
