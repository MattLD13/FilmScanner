"""Stand-in for cvbridge.exe in tests: same command line and JSON-lines protocol, no driver.

FAKE_CVBRIDGE_MODE: ok (default), timeout (driver never starts), sensor (the USB watch
reports a stuck position sensor), crash (exits mid-scan), busy (refuses to open). Every invocation is appended to FAKE_CVBRIDGE_LOG when set.
"""
import base64
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
shift_px = 0.0  # 'strip' mode: film offset from fine nudges, in pixels at STRIP_DPI
STRIP_DPI = 600
PX_PER_STEP = float(os.environ.get('FAKE_PX_PER_STEP', '1.37'))  # deliberately not a round number


def strip_window():
    """'strip' mode: a 36.5 mm window of a synthetic negative strip (transmission), moved by nudges.

    The AFL lands 0.9 mm off-centre, so the frame's right edge is outside a single scan."""
    mm = STRIP_DPI / 25.4
    fw, fh, gap = 36 * mm, 24 * mm, 2 * mm
    width, height = int(round(3 * fw + 4 * gap)), int(round(fh + 2 * mm))
    rng = np.random.default_rng(7)
    img = np.full((height, width, 3), [.85, .55, .35])
    for f in range(3):
        x0, y0 = int(round(gap + f * (fw + gap))), int(round(mm))
        yy, xx = np.mgrid[y0:int(round(y0 + fh)), x0:int(round(x0 + fw))]
        scene = .25 + .12 * np.sin(xx / 17.0 + f) * np.cos(yy / 23.0) + .05 * rng.standard_normal(xx.shape)
        img[yy, xx] = np.clip(scene[..., None] * [1.0, .8, .6], 0, 1)
    win = int(round(36.5 * mm))
    left = int(round(gap + fw + gap + fw / 2 - win / 2 + .9 * mm + shift_px))
    out = img[:, left:left + win]
    out = np.clip(out + .01 * np.random.default_rng(int(abs(shift_px) * 10)).standard_normal(out.shape), 0, 1)
    return (out * 65535).astype(np.uint16)


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


LIVE_W, LIVE_H = 48, 30


def live_row(y):
    """A raw-transmission preview row: bright film base around a darker diagonal picture."""
    return bytes(min(255, 40 + (x * 3 + y * 5 + c * 30) % 180) if 6 <= x < 42 else 230 - c * 40
                 for x in range(LIVE_W) for c in range(3))


def scan(path, count):
    emit(event='enabled', show_ui=False)
    emit(event='driver_status', text='Preparing film scanner, please wait..')
    if mode == 'sensor':  # the USB watch saw the driver poll a sensor that never set
        emit(event='error', code='position_sensor', message='The scanner could not find its film position.')
        emit(event='scan_done', images=0, result=0)
        return
    if mode == 'timeout':
        emit(event='error', code='timeout', message='The driver did not deliver an image in time')
        emit(event='scan_done', images=0, result=0)
        return
    if mode == 'empty':
        emit(event='scan_done', images=0, result=1)
        return
    for index in range(1, count + 1):
        if cancel.is_set():
            emit(event='cancelled')
            emit(event='scan_done', images=index - 1, result=-1)
            return
        target = path if index == 1 else numbered(path, index)
        picture = strip_window() if mode == 'strip' else None
        height, width = picture.shape[:2] if picture is not None else (40, 60)
        dpi = float(STRIP_DPI) if picture is not None else 1800.0
        # The real bridge's USB watch streams 1/8-size rows while the scanner reads the frame.
        emit(event='live_start', **{'pass': 3, 'width': LIVE_W, 'source_width': LIVE_W * 8, 'scale': 8})
        for y in range(LIVE_H):
            emit(event='live', data=base64.b64encode(live_row(y)).decode(), y=y, width=LIVE_W, **{'pass': 3})
            time.sleep(float(os.environ.get('FAKE_CVBRIDGE_LIVE_DELAY', '0')))
        emit(event='image_start', width=width, height=height, samples=3, bits=16, dpi=dpi, pixel_type=2)
        if mode == 'crash':
            sys.exit(3)
        for rows in (20, 40):
            time.sleep(float(os.environ.get('FAKE_CVBRIDGE_DELAY', '0.01')))
            emit(event='progress', rows=rows, height=height)
        if picture is None:
            picture = np.linspace(0, 65535, width * height * 3).astype(np.uint16).reshape(height, width, 3)
            picture[..., 1] = 30000 + position + index  # distinct content per frame
        tifffile.imwrite(target, picture, photometric='rgb')
        emit(event='image', path=target, width=width, height=height, samples=3, bits=16, dpi=dpi)
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
    if '--trace-usb' in sys.argv:  # the real bridge logs FVC.dll's calls here
        trace = sys.argv[sys.argv.index('--trace-usb') + 1]
        with open(trace, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'n': 0, 'call': 'hooked', 'module': 'fvc.dll', 'loaded': 1, 'slots': 6}) + '\n')
        emit(event='trace', slots=6)
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
        if line.startswith('film nudge ') or line.startswith('film step '):  # native / CyberView fine move
            global shift_px
            log(line)
            _, _, direction, steps = line.split()
            emit(event='command', name='nudge')
            # The film moving back brings content from the left into the window.
            shift_px += (-1 if direction == 'back' else 1) * int(steps) * PX_PER_STEP
            emit(event='nudge', direction=direction, steps=int(steps))
            emit(event='command_done', name='nudge')
            emit(event='ready')
            continue
        if line.startswith('film '):
            global position
            action = line.split()[1]
            emit(event='command', name=action)
            position += {'next': 1, 'previous': -1}.get(action, 0)
            emit(event='command_done', name=action)
            emit(event='ready')
            continue
        if line.startswith('settings '):
            log(line)
            emit(event='configured')
            emit(event='ready')
            continue
        _, count, path = line.split(' ', 2)
        cancel.clear()
        scan(path, int(count))
        emit(event='ready')


if __name__ == '__main__':
    main()
