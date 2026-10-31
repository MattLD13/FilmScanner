"""Opt-in native model-module host. No TWAIN or CyberView UI is loaded.

This uses the user's genuine AFL vendor DLL, not an independent USB driver.
Native startup may home motors. It remains blocked unless the operator has
explicitly enabled this experimental backend; there is no automatic fallback.
"""
from __future__ import annotations

import os
import asyncio
import json
from pathlib import Path

from services.scanner_host.cyberview import CyberViewBridge, PROJECT
from services.scanner_host.backend import ScannerError
from services.scanner_host import workspace
from services.native_bridge import driver


class NativeAflBridge(CyberViewBridge):
    kind = 'afl-native-experimental'
    image_kind = 'vendor-calibrated-transmission'
    supports_next = False
    max_count = 1

    def __init__(self, exe: Path | None = None, first_image_timeout: float = 300, device_test_approved: bool = False):
        super().__init__(exe or Path(os.environ.get('FRAME_NATIVE_BRIDGE') or
                                    PROJECT / 'services/native_bridge/bin/aflbridge.exe'), first_image_timeout)
        self.quarantined = False
        self.device_test_approved = device_test_approved
        self.options = workspace.ScanOptions().model_dump()
        self.frame_initialized = False

    @property
    def supports_next(self):
        return 'next' in workspace.validation().get('actions', [])

    @property
    def max_count(self):
        return 40 if self.supports_next else 1

    @property
    def enabled(self) -> bool:
        return self.device_test_approved or os.environ.get('FRAME_ALLOW_EXPERIMENTAL_SCANNER') == '1'

    @property
    def busy(self) -> bool:
        return self.scanning or self.quarantined

    async def _read(self, process) -> None:
        assert process.stdout
        async for raw in process.stdout:
            try:
                event = json.loads(raw.decode('utf-8', 'replace').lstrip('\ufeff'))
            except json.JSONDecodeError:
                continue
            if self.quarantined and event.get('event') == 'ready':
                # The timed-out vendor call has returned after cancellation.
                # Discard its old response stream before accepting another command.
                self.events = asyncio.Queue()
                self.quarantined = False
            await self.events.put(event)
        await self.events.put(None)
        self.quarantined = False

    async def _next(self, timeout=None):
        try:
            return await super()._next(min(timeout or self.first_image_timeout, self.first_image_timeout))
        except asyncio.TimeoutError:
            self.quarantined = True
            if self.open:
                await self._send('cancel')
            raise ScannerError('The native driver stopped responding. Cancellation was requested; the scanner session stays reserved until the driver returns. No automatic reset or retry was performed.') from None

    def _serve_args(self) -> list[str]:
        args = ['serve', '--allow-experimental-device-io', '--timeout', str(int(self.first_image_timeout))]
        if workspace.validation().get('configurations'):
            args.append('--allow-experimental-settings')
        controls = workspace.validation().get('actions', [])
        if controls:
            args += ['--allow-experimental-controls', '--controls', ','.join(controls)]
        return args

    async def _start(self) -> None:
        if not self.enabled:
            raise ScannerError('Native startup may home the film transport. Explicit device-test approval is required before enabling this backend.')
        self.frame_initialized = False
        if self.exe.suffix == '.exe':
            # Keep CyberScan's own verified driver copy, so CyberView X can be uninstalled.
            await asyncio.to_thread(driver.ensure)
        await super()._start()

    async def _prepare_device(self) -> None:
        # Do not reset or retry a newly reconstructed path automatically.
        pass

    async def restore_settings(self) -> None:
        # The native helper never reads or writes CyberView's INI.
        pass

    def acquisition_settings(self) -> dict:
        return {'found': True, 'film_term': None, 'auto_exposure': None, 'auto_gamma': False,
                'crop_inches': [self.options['crop'][k] for k in ('left','top','right','bottom')], 'scan_depth': self.options['bits']*3,
                'acquisition': self.options.copy(),
                'image_kind': self.image_kind, 'lut': 'identity-4096',
                'note': 'Vendor calibration remains active; sensor rawness and effective precision are not measured.'}

    async def configure(self, options):
        values = workspace.ScanOptions(**options).model_dump()
        if not workspace.validated_options(values):
            raise ScannerError('This acquisition configuration has not been validated on the scanner')
        if values['focus'] is not None:
            raise ScannerError('Use the dedicated focus control; acquisition focus overrides are not available')
        self.options = values

    def _settings_line(self):
        o=self.options
        fields=[o['dpi'],o['bits'],o['channel'],o['film'],*[o['crop'][k] for k in ('left','top','right','bottom')],*o['exposure']]
        return 'settings ' + ' '.join(str(v) for v in fields)

    async def scan(self, out, count, on_event):
        if self.quarantined:
            raise ScannerError('The native driver is still handling a timed-out operation; wait for it to return before retrying')
        if count != 1 and not self.supports_next:
            raise ScannerError('Native acquisition currently supports only the current frame')
        # Base scan owns the operation lock and cancellation state. Its startup
        # hook configures this exact acquisition without changing user defaults.
        result = await super().scan(out, count, on_event)
        if result:
            self.frame_initialized = True
        return result

    async def _exchange(self,line,until,on_event,limit=None):
        if line.startswith('scan '):
            _, error = await super()._exchange(self._settings_line(), 'configured', None, 30)
            if error:
                raise ScannerError(error.get('message','Native settings were rejected'))
            if self.cancel_requested:
                return [], None
        return await super()._exchange(line,until,on_event,limit)

    async def _stuck(self) -> None:
        # SCAN08's sensor loop has no timeout and never returns to the bridge, so the
        # process is ended; the scanner needs a power cycle afterwards anyway.
        await self._kill()
        self.frame_initialized = False

    async def release(self) -> None:
        if self.quarantined and self.open:
            raise ScannerError('The native driver has not returned after cancellation. Its session remains reserved; power down the scanner before terminating a stuck driver.')
        process = self.process
        if not process or process.returncode is not None:
            await self._ended()
            return
        await self._send('quit')
        try:
            await asyncio.wait_for(process.wait(), 15)
        except asyncio.TimeoutError:
            self.quarantined = True
            raise ScannerError('The native driver did not close. Its session remains reserved; no forced termination was performed.') from None
        await self._ended()
        self.frame_initialized = False
        if self.reader:
            self.reader.cancel()

    async def film(self, action, on_event=None, frame=None):
        if action not in workspace.validation().get('actions', []):
            raise ScannerError('Native film transport has not been validated for this action')
        return await self.control(action,on_event,frame)

    async def control(self,action,on_event=None,value=None):
        if action not in workspace.validation().get('actions', []):
            raise ScannerError('This native scanner control has not been validated')
        if self.busy:
            raise ScannerError('Another scanner operation is in progress')
        async with self.lock:
            self.scanning=True;self.cancel_requested=False
            try:
                if not self.open: await self._start()
                if self.cancel_requested: return
                line = ('focus auto' if action=='autofocus' else f'focus {value}' if action=='focus' else
                        'calibrate' if action=='calibrate' else f'film goto {value}' if action=='goto' else
                        f'film nudge {value}' if action=='nudge' else f'film {action}')
                _,error=await super()._exchange(line,'command_done',on_event,self.first_image_timeout)
                if error:raise ScannerError(error.get('message','Scanner control failed'))
                if action.startswith('eject_'):
                    self.frame_initialized=False
            finally:self.scanning=False


def configured_bridge() -> CyberViewBridge:
    """Direct capture is the product (user decision 2026-10-31: no CyberView app or TWAIN).

    FRAME_SCANNER_BACKEND=cyberview-twain keeps the hidden-CyberView bridge for tests and
    research tooling only; the app no longer offers it.
    """
    kind = os.environ.get('FRAME_SCANNER_BACKEND', 'afl-native-experimental')
    if kind == 'cyberview-twain':
        return CyberViewBridge()
    if kind == 'afl-native-experimental':
        return NativeAflBridge(device_test_approved=True)
    raise ValueError(f'Unknown scanner backend: {kind}')
