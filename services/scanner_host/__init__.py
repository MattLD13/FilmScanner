"""Scanner integration: synthetic simulator; real hardware remains disabled."""

from .backend import (
    ScannerBackend,
    ScannerCancelled,
    ScannerError,
    ScannerFault,
    SimulatedScannerBackend,
    TwainScannerBackend,
    UnsupportedOperation,
    UsbScannerBackend,
)

__all__ = [
    "ScannerBackend", "ScannerCancelled", "ScannerError", "ScannerFault",
    "SimulatedScannerBackend", "TwainScannerBackend", "UnsupportedOperation",
    "UsbScannerBackend",
]
