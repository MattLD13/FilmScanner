"""Passive, bounded metadata trace of an existing x86 CyberView bridge session.

Run in research/.tools/analysis-venv (optional frida dependency). No scan, reset,
transport, register write or image data capture is performed by this program.
Use the application's already verified controls separately to observe an action.
Logs contain machine-specific addresses: keep them under ignored .local/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time


def main():
    import frida

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300, choices=range(1, 901), metavar='1..900')
    args = parser.parse_args()
    device = frida.get_local_device()
    process = next((p for p in device.enumerate_processes() if p.pid == args.pid), None)
    if process is None or process.name.lower() not in ('cvbridge.exe', 'pfsloader.exe'):
        parser.error('Target must be a running cvbridge.exe or PfsLoader.exe')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an earlier observation.
    with args.out.open('x', encoding='utf-8') as stream:
        lock = threading.Lock()
        def record(payload):
            with lock:
                stream.write(json.dumps(payload) + '\n')
                stream.flush()
        record({'event': 'trace_start', 'frida': frida.__version__, 'time_ms': int(time.time()*1000),
                'pid': args.pid, 'process': process.name, 'mode': 'passive-metadata-only'})
        session = device.attach(args.pid)
        script = session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))
        def message(item, data):
            record(item['payload'] if item['type'] == 'send' else {'event':'instrumentation_error', 'message':item})
        script.on('message', message)
        try:
            script.load()
            print('Metadata observer attached; it does not command the scanner.', flush=True)
            threading.Event().wait(args.seconds)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                script.unload()
                session.detach()
            except frida.InvalidOperationError:
                pass
            record({'event':'trace_end', 'time_ms':int(time.time()*1000)})


if __name__ == '__main__':
    main()
