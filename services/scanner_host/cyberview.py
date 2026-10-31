"""CyberView X driven headlessly through its own TWAIN data source.

The x86 helper ``services/cyberview_bridge/bin/cvbridge.exe`` loads the installed
CyberViewX.ds with its window hidden and writes each delivered frame as a TIFF.
All scanner I/O stays inside Pacific Image's driver; nothing here talks to USB.

Observed on the PF1800 AFL (2770:0119) on 2026-10-30, see docs/cyberview-bridge.md:
every hidden scan returns the current frame at the scanner's native 1800 dpi with
16-bit samples, already inverted with CyberView's selected film term and cropped to
its default crop box. The TWAIN resolution list is a fixed 100 dpi and setting it
fails, so smaller sizes are made afterwards from the native original.

Opening and closing the driver repeatedly left the AFL stuck at "Preparing film
scanner" until it was power-cycled. Like CyberView itself, this module therefore
keeps one driver session open (``cvbridge serve``) for as many scans as are asked
for, and closes it only when released or when the service stops.
"""

from __future__ import annotations

import asyncio
import configparser
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable

from services.scanner_host.backend import ScannerError

PROJECT = Path(__file__).resolve().parents[2]
EventCallback = Callable[[dict], Awaitable[None] | None]

# Time allowed from "enabled" to the first image. A healthy AFL took 60-120 s here,
# including lamp warm-up; a stuck one never starts.
FIRST_IMAGE_TIMEOUT = 300
FILM_TIMEOUT = 120  # Forward One Frame took 3.4 s
STUCK = ('The scanner did not start. It may be stuck at "Preparing film scanner": '
         'turn it off and on again (power and USB), then scan again.')


class CyberViewBusy(ScannerError):
    """CyberView itself (or another scan) owns the scanner."""


def bridge_path() -> Path:
    return Path(os.environ.get('FRAME_CVBRIDGE') or PROJECT / 'services' / 'cyberview_bridge' / 'bin' / 'cvbridge.exe')


def settings_path() -> Path:
    return Path(os.environ.get('FRAME_CYBERVIEW_INI') or Path(os.environ.get('APPDATA', '')) / 'PIE' / 'MF' / 'CyberViewX.ini')


def read_settings(path: Path | None = None) -> dict:
    """The CyberView choices that shape a hidden scan, read from the user's own settings."""
    path = path or settings_path()
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding='latin-1'))
    except (OSError, configparser.Error):
        return {'found': False}

    def value(section, key, default=''):
        return parser.get(section, key, fallback=default).strip()

    def number(section, key):
        try:
            return float(value(section, key, 'nan'))
        except ValueError:
            return float('nan')

    crop = [number('SETUPDLG DEFAULT PAGE', f'Default Crop Area {side}') for side in ('Left', 'Top', 'Right', 'Bottom')]
    return {
        'found': True,
        'film_term': value('TOOLBAR FILMTERM', 'Film Term Name') or None,
        'auto_exposure': value('SETUPDLG DEFAULT PAGE', 'Auto Exposure') == '1',
        'auto_gamma': value('SETUPDLG DEFAULT PAGE', 'Auto Gamma') == '1',
        'scan_depth': int(value('MAIN PANEL', 'Scan Depth', '0') or 0),
        'crop_inches': crop if all(c == c for c in crop) else None,
    }


def _quiet_run(args: list[str], timeout: float) -> str | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def vendor_running() -> bool:
    """True while CyberView's own loader (PfsLoader.exe) is open."""
    if sys.platform != 'win32':
        return False
    out = _quiet_run(['tasklist', '/FI', 'IMAGENAME eq PfsLoader.exe', '/FO', 'CSV', '/NH'], 10)
    return bool(out) and 'pfsloader.exe' in out.lower()


RESET_TASK = r'FRAME\Reset PF1800 AFL'


def reset_available() -> bool:
    """True when scripts/install-scanner-reset.ps1 has been run (once, as administrator)."""
    if sys.platform != 'win32':
        return False
    return _quiet_run(['schtasks', '/Query', '/TN', RESET_TASK], 10) not in (None, '')


async def reset_scanner() -> bool:
    """Restarts the scanner's USB device through the installed task; False if unavailable.

    Observed 2026-10-30: this cleared a "Preparing film scanner" stall without
    unplugging, and the next session started in about 30 s.
    """
    if not await asyncio.to_thread(reset_available):
        return False
    if await asyncio.to_thread(_quiet_run, ['schtasks', '/Run', '/TN', RESET_TASK], 15) is None:
        return False
    await asyncio.sleep(12)  # the task restarts the device; Windows rebinds usbscan
    return True


def scanner_present() -> bool | None:
    """Whether Windows currently lists the PF1800 AFL (USB 2770:0119); None if unknown."""
    if sys.platform != 'win32':
        return None
    out = _quiet_run(['pnputil', '/enum-devices', '/connected', '/class', 'Image'], 15)
    return None if out is None else 'VID_2770&PID_0119' in out.upper()


class CyberViewBridge:
    """Owns one hidden CyberView driver session and runs scans in it, one at a time."""

    def __init__(self, exe: Path | None = None, first_image_timeout: float = FIRST_IMAGE_TIMEOUT):
        self.exe = exe or bridge_path()
        self.first_image_timeout = first_image_timeout
        self.process: asyncio.subprocess.Process | None = None
        self.events: asyncio.Queue[dict | None] = asyncio.Queue()
        self.reader: asyncio.Task | None = None
        self.scanning = False
        self.cancel_requested = False
        self.lock = asyncio.Lock()

    @property
    def open(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def busy(self) -> bool:
        return self.scanning

    def built(self) -> bool:
        return self.exe.is_file()

    def _command(self, *args: str) -> list[str]:
        # Tests substitute a Python script for the x86 executable.
        if self.exe.suffix == '.py':
            return [sys.executable, str(self.exe), *args]
        return [str(self.exe), *args]

    async def restore_settings(self) -> None:
        """Puts back CyberView's settings if a session ended without restoring them."""
        ini = settings_path()
        if not self.built() or not ini.with_name(ini.name + '.cvbridge-backup').exists():
            return
        process = await asyncio.create_subprocess_exec(*self._command('restore'), stdout=asyncio.subprocess.DEVNULL,
                                                       stderr=asyncio.subprocess.DEVNULL)
        await process.wait()

    async def _read(self, process) -> None:
        assert process.stdout
        async for raw in process.stdout:
            try:
                event = json.loads(raw.decode('utf-8', 'replace').lstrip('﻿'))
            except json.JSONDecodeError:
                continue
            await self.events.put(event)
        await self.events.put(None)

    async def _next(self, timeout: float | None = None) -> dict | None:
        return await asyncio.wait_for(self.events.get(), timeout)

    async def _send(self, line: str) -> None:
        assert self.process and self.process.stdin
        self.process.stdin.write(line.encode() + b'\n')
        await self.process.stdin.drain()

    async def _start(self) -> None:
        if not self.built():
            raise ScannerError('The CyberView bridge is not built; run services/cyberview_bridge/build.ps1')
        if await asyncio.to_thread(vendor_running):
            raise CyberViewBusy('CyberView is open. Close it so only one program uses the scanner.')
        # A session that scanned leaves the film where the next one cannot start from it
        # (observed twice on 2026-10-30), so a fresh session begins with a USB restart.
        await reset_scanner()
        self.events = asyncio.Queue()
        self.process = await asyncio.create_subprocess_exec(
            *self._command('serve', '--timeout', str(int(self.first_image_timeout))),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.reader = asyncio.create_task(self._read(self.process))
        while True:
            event = await self._next(120)
            if event is None:
                await self._ended()
                raise ScannerError('The CyberView driver did not open')
            if event.get('event') == 'ready':
                return
            if event.get('event') == 'error':
                await self.release()
                raise ScannerError(event.get('message') or 'The CyberView driver did not open')

    async def _ended(self) -> None:
        """The bridge exited; make sure CyberView's settings are back."""
        if self.process:
            await self.process.wait()
            code = self.process.returncode
            self.process = None
            if code != 0:
                await self.restore_settings()

    async def _kill(self) -> None:
        """Last resort for a driver that stopped responding; the AFL then needs a reset."""
        if self.process and self.process.returncode is None:
            self.process.kill()
        await self._ended()
        if self.reader:
            self.reader.cancel()

    async def _exchange(self, line: str, until: str, on_event: EventCallback | None,
                        limit: float | None = None) -> tuple[list[dict], dict | None]:
        """Sends one bridge command and relays its events until ``until``; returns images and the first error.

        ``limit`` bounds the silence between events; the bridge enforces its own scan timeout.
        """
        await self._send(line)
        images: list[dict] = []
        error: dict | None = None
        while True:
            try:
                event = await self._next(limit)
            except asyncio.TimeoutError:
                await self._kill()
                raise ScannerError(STUCK)
            if event is None:
                await self._ended()
                raise ScannerError('The CyberView driver stopped unexpectedly. Turn the scanner off and on, then retry.')
            kind = event.get('event')
            if kind == 'image':
                images.append(event)
            elif kind == 'error' and error is None:
                error = event
            if on_event:
                result = on_event(event)
                if asyncio.iscoroutine(result):
                    await result
            if kind == until or (until == 'command_done' and kind == 'error'):
                break
        if await self._next(30) is None:  # the bridge's "ready" after every command
            await self._ended()
        return images, error

    async def scan(self, out: Path, count: int, on_event: EventCallback) -> list[dict]:
        """Scans ``count`` frames starting at the current one; returns the image records.

        TWAIN auto-feed is refused by this driver, so later frames are reached with
        CyberView's own "Forward One Frame" command between single-frame scans.
        Images land at ``out`` and at ``out`` with _02, _03... before the suffix.
        """
        if self.scanning:
            raise CyberViewBusy('A scan is already running')
        async with self.lock:
            self.scanning = True
            self.cancel_requested = False
            images: list[dict] = []
            error: dict | None = None
            try:
                if not self.open:
                    await self._start()
                out.parent.mkdir(parents=True, exist_ok=True)
                for index in range(1, count + 1):
                    if index > 1:
                        if self.cancel_requested:
                            break
                        _, error = await self._exchange('film next', 'command_done', on_event, FILM_TIMEOUT)
                        if error:
                            break
                    target = out if index == 1 else out.with_name(f'{out.stem}_{index:02d}{out.suffix}')
                    got, error = await self._exchange(f'scan 1 {target}', 'scan_done', on_event)
                    images += got
                    if error or not got or self.cancel_requested:
                        break
            finally:
                self.scanning = False
        if self.cancel_requested:
            return images
        if error and not images:
            if error.get('code') == 'timeout':
                # A stuck driver session is not worth keeping; the next scan starts a fresh one.
                await self.release()
                raise ScannerError(STUCK)
            raise ScannerError(error.get('message') or 'The CyberView driver reported an error')
        if error:
            raise ScannerError(f"Stopped after {len(images)} frames: {error.get('message') or 'driver error'}")
        return images

    async def film(self, action: str, on_event: EventCallback | None = None) -> None:
        """Moves the film with CyberView's own transport command.

        Only "next" (Forward One Frame, about 3 s) is offered. "Backward One Frame"
        hung the driver for over six minutes on 2026-10-30; eject is untested.
        """
        if action != 'next':
            raise ValueError(action)
        if self.scanning:
            raise CyberViewBusy('A scan is running')
        async with self.lock:
            self.scanning = True
            try:
                if not self.open:
                    await self._start()
                _, error = await self._exchange(f'film {action}', 'command_done', on_event, FILM_TIMEOUT)
            finally:
                self.scanning = False
        if error:
            raise ScannerError(error.get('message') or 'CyberView could not move the film')

    async def cancel(self) -> None:
        """Asks the driver to stop the current scan; the session stays open."""
        if self.scanning and self.open:
            self.cancel_requested = True
            try:
                await self._send('cancel')
            except (ConnectionError, RuntimeError):
                pass

    async def release(self) -> None:
        """Closes the driver session so CyberView itself can use the scanner."""
        process = self.process
        if not process or process.returncode is not None:
            self.process = None
            return
        try:
            await self._send('quit')
            await asyncio.wait_for(process.wait(), 90)
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            # Last resort only: killing the driver can leave the AFL needing a power cycle.
            process.kill()
            await process.wait()
        await self._ended()
        if self.reader:
            self.reader.cancel()
