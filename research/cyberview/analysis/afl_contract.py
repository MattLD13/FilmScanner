"""CyberView -> model-module scan request (ScannerDeviceIO selector 0x20), decoded.

Field offsets come from two sources and are labeled accordingly:
* STATIC: how SCAN08-lineage LC.dll consumes the block (0x10010640, 0x10010f90).
* GUEST OBSERVED: the actual block original CyberView passed to the FRAME
  simulator on 2026-10-28 (research/cyberview/analysis/evidence/afl-simulator-2026-10-28.json).
Neither establishes what a physical PF1800 AFL does with these values.
"""
from __future__ import annotations

import struct

BLOCK_SIZE = 0x48
BYTES_PER_PIXEL = {1: 1, 2: 1, 3: 3, 4: 2, 5: 6, 6: 2, 7: 6}  # LC.dll 0x10011940 / 0x10010640
FULL_FRAME_PIXELS_AT_1800 = (2496, 1708)  # LC.dll capability block 0x100122c0 (+0x28, +0x2a)


def decode_scan_block(block: bytes) -> dict:
    """Decode the 0x48-byte scan parameter block (selector 0x20 passes it after a 4-byte flag word)."""
    if len(block) < BLOCK_SIZE:
        raise ValueError("scan block shorter than 0x48 bytes")
    dpi = struct.unpack_from("<H", block, 0x00)[0]
    left, top, width_in, height_in = struct.unpack_from("<4f", block, 0x04)
    mode = struct.unpack_from("<I", block, 0x14)[0]
    if mode not in BYTES_PER_PIXEL:
        raise ValueError(f"unknown color mode {mode}")
    return {
        "dpi": dpi,
        "window_inches": {"left": round(left, 4), "top": round(top, 4),
                          "width": round(width_in, 4), "height": round(height_in, 4)},
        "mode": mode,
        "bytes_per_pixel": BYTES_PER_PIXEL[mode],
        "exposure_rgb": list(struct.unpack_from("<3H", block, 0x18)),   # LC: vendor command 0x13
        "offset_rgb": list(struct.unpack_from("<3H", block, 0x1e)),     # LC: vendor command 0x14
        "lut_pointers": [hex(v) for v in struct.unpack_from("<3I", block, 0x24)],
        "gain_rgb": list(block[0x30:0x33]),                             # LC: vendor command 0x15
        "callback": hex(struct.unpack_from("<I", block, 0x40)[0]),
        "lines_per_strip": struct.unpack_from("<I", block, 0x44)[0],
    }


def simulated_geometry(dpi: int, mode: int) -> dict:
    """Full-frame size the FRAME simulator reports; the real module reads it from the device."""
    if not 0 < dpi <= 1800:
        raise ValueError("dpi outside 1..1800")
    width = FULL_FRAME_PIXELS_AT_1800[0] * dpi // 1800
    height = FULL_FRAME_PIXELS_AT_1800[1] * dpi // 1800
    return {"width": width, "height": height, "bytes_per_line": width * BYTES_PER_PIXEL[mode]}
