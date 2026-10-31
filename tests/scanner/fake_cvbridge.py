"""Stand-in for cvbridge.exe in tests: same command line and JSON-lines protocol, no driver.

FAKE_CVBRIDGE_MODE: ok (default), timeout (driver never starts), crash (exits mid-scan),
busy (refuses to open). Every invocation is appended to FAKE_CVBRIDGE_LOG when set.
"""
import json
import os
import sys
import threading
import time

import numpy as np
import tifffile

mode = os.environ.get('FAKE_CVBRIDGE_MODE', 'ok')
cancel = threading.Event()
position = 1  # the frame in the scan path


def emit(**event):
    print(json.dumps(event), flush=True)


def log(*parts):
    path = os.environ.get('FAKE_CVBRIDGE_LOG')
    if path:
        with open(path, 'a', encoding='utf8') as stream:
            stream.write(' '.join(parts) + '\n')


def numbered(path, index):
    stem, dot, suffix = path.rpartition('.')
    return f'{stem}_{index:02d}.{suffix}' if dot else f'{path}_{index:02d}'


def scan(path, count):
    emit(event='enabled', show_ui=False)
    emit(event='driver_status', text='Preparing film scanner, please wait..')
    if mode == 'timeout':
        emit(event='error', code='timeout', message='The driver did not deliver an image in time')
        emit(event='scan_done', images=0, result=0)
        return
    for index in range(1, count + 1):
        if cancel.is_set():
            emit(event='cancelled')
            emit(event='scan_done', images=index - 1, result=-1)
            return
        target = path if index == 1 else numbered(path, index)
        height, width = 40, 60
        emit(event='image_start', width=width, height=height, samples=3, bits=16, dpi=1800.0, pixel_type=2)
        if mode == 'crash':
            sys.exit(3)
        for rows in (20, 40):
            time.sleep(float(os.environ.get('FAKE_CVBRIDGE_DELAY', '0.01')))
            emit(event='progress', rows=rows, height=height)
        ramp = np.linspace(0, 65535, width * height * 3).astype(np.uint16).reshape(height, width, 3)
        ramp[..., 1] = 30000 + position + index  # distinct content per frame
        tifffile.imwrite(target, ramp, photometric='rgb')
        emit(event='image', path=target, width=width, height=height, samples=3, bits=16, dpi=1800.0)
    emit(event='scan_done', images=count, result=1)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    log(*sys.argv[1:])
    if command == 'restore':
        emit(event='done')
        return
    if mode == 'busy':
        emit(event='error', code='busy', message='CyberView is open. Close it so only one program uses the scanner.')
        sys.exit(3)
    emit(event='opened', source='CyberView X - MF ')
    if command != 'serve':
        sys.exit(2)
    emit(event='ready')
    lines = []
    ready = threading.Condition()

    def read():
        for line in sys.stdin:
            if line.startswith('cancel'):
                cancel.set()
                continue
            with ready:
                lines.append(line.strip())
                ready.notify()
        with ready:
            lines.append('quit')
            ready.notify()

    threading.Thread(target=read, daemon=True).start()
    while True:
        with ready:
            while not lines:
                ready.wait()
            line = lines.pop(0)
        if line == 'quit':
            emit(event='done', result=1)
            return
        if line.startswith('film '):
            global position
            action = line.split()[1]
            emit(event='command', name=action)
            position += {'next': 1, 'previous': -1}.get(action, 0)
            emit(event='command_done', name=action)
            emit(event='ready')
            continue
        _, count, path = line.split(' ', 2)
        cancel.clear()
        scan(path, int(count))
        emit(event='ready')


if __name__ == '__main__':
    main()
