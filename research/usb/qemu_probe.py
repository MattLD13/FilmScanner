"""Probe a portable QEMU controller in a stopped, diskless, networkless machine.

No guest OS, CyberView code, host USB device, kernel driver or physical scanner is
used. This is an infrastructure smoke test, not a scanner-detection experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import socket
import time


def probe(executable: Path, output: Path):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    version = subprocess.run([str(executable), "--version"], capture_output=True,
                             text=True, check=True, timeout=15, creationflags=flags).stdout.splitlines()[0]
    devices = subprocess.run([str(executable), "-device", "help"], capture_output=True,
                             text=True, check=True, timeout=15, creationflags=flags).stdout
    commands = [
        {"execute": "qmp_capabilities", "id": 1},
        {"execute": "query-status", "id": 2},
        {"execute": "human-monitor-command", "arguments": {"command-line": "info usb"}, "id": 3},
        {"execute": "quit", "id": 4},
    ]
    # -S prevents any guest CPU execution; there are no attached storage devices.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    options = ["-machine", "pc", "-accel", "tcg", "-m", "32", "-nodefaults",
               "-nic", "none", "-usb", "-S", "-display", "none", "-serial", "none",
               "-monitor", "none", "-qmp", f"tcp:127.0.0.1:{port},server=on,wait=off"]
    process = subprocess.Popen([str(executable), *options], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=flags)
    messages = []
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("QEMU QMP socket did not become available")
                time.sleep(0.1)
        with connection:
            connection.settimeout(10)
            stream = connection.makefile("rb")
            messages.append(json.loads(stream.readline()))
            for command in commands:
                connection.sendall((json.dumps(command) + "\n").encode())
                while True:
                    row = json.loads(stream.readline())
                    messages.append(row)
                    if row.get("id") == command["id"]:
                        break
        returncode = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    stderr = process.stderr.read().decode(errors="replace")
    status = next((row["return"] for row in messages if row.get("id") == 2), None)
    assert returncode == 0 and status and not status["running"], stderr
    assert all("error" not in row for row in messages), messages
    report = {"evidence": "actual-QEMU-diskless-stopped-smoke-test", "version": version,
              "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "options": options, "commands": commands, "responses": messages,
              "usb_redir_available": 'name "usb-redir"' in devices,
              "usbip_device_available": 'name "usbip"' in devices,
              "guest_os_present": False, "cyberview_launched": False,
              "pf1800_emulator_attached": False, "physical_usb_access": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({"result": "stopped-QEMU controller smoke passed", "status": status,
                      "cyberview_detection_attempted": False, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    probe(args.executable.resolve(), args.output)
