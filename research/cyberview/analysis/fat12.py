"""Minimal 1.44MB FAT12 floppy format/read for moving guest evidence out of an isolated VM.

The guest writes plain files to A:\\; the host reads root-directory files back by
their 8.3 names. Only what that needs is implemented: no subdirectories, no
writes from the host after formatting.
"""
from __future__ import annotations

import struct

SECTOR = 512
TOTAL_SECTORS = 2880


def blank_image(label: str = "FRAMEEVID", serial: int = 0x46524D45) -> bytes:
    """A formatted, empty 1.44MB FAT12 image (2 FATs of 9 sectors, 224 root entries)."""
    boot = bytearray(SECTOR)
    boot[0:3] = b"\xeb\x3c\x90"
    boot[3:11] = b"FRAME   "
    struct.pack_into("<HBHBHHBHHHII", boot, 11, SECTOR, 1, 1, 2, 224, TOTAL_SECTORS, 0xF0, 9, 18, 2, 0, 0)
    struct.pack_into("<BBBI", boot, 36, 0, 0, 0x29, serial)
    boot[43:54] = label.upper().encode("ascii")[:11].ljust(11)
    boot[54:62] = b"FAT12   "
    boot[510:512] = b"\x55\xaa"
    image = bytearray(SECTOR * TOTAL_SECTORS)
    image[:SECTOR] = boot
    for fat in range(2):
        start = SECTOR * (1 + fat * 9)
        image[start:start + 3] = b"\xf0\xff\xff"
    return bytes(image)


def _geometry(image: bytes) -> dict:
    (bps, spc, reserved, fats, root_entries, total, _media, spf) = struct.unpack_from("<HBHBHHBH", image, 11)
    if image[510:512] != b"\x55\xaa" or bps != SECTOR or spc < 1 or fats < 1:
        raise ValueError("not a supported FAT12 image")
    root = (reserved + fats * spf) * bps
    data = root + root_entries * 32
    if total * bps > len(image) or data > len(image):
        raise ValueError("FAT12 geometry exceeds image size")
    return {"fat": reserved * bps, "root": root, "root_entries": root_entries,
            "data": data, "cluster": spc * bps}


def _next_cluster(fat: bytes, cluster: int) -> int:
    offset = cluster * 3 // 2
    pair = fat[offset] | fat[offset + 1] << 8
    return pair >> 4 if cluster & 1 else pair & 0x0FFF


def read_root_files(image: bytes) -> dict[str, bytes]:
    """Return {8.3 name: contents} for regular files in the root directory."""
    geo = _geometry(image)
    fat = image[geo["fat"]:geo["root"]]
    files = {}
    for index in range(geo["root_entries"]):
        entry = image[geo["root"] + index * 32: geo["root"] + (index + 1) * 32]
        if entry[0] == 0:
            break
        attributes = entry[11]
        if entry[0] == 0xE5 or attributes == 0x0F or attributes & 0x18:
            continue  # deleted, long-name fragment, volume label or directory
        name = entry[0:8].decode("ascii", "replace").rstrip()
        ext = entry[8:11].decode("ascii", "replace").rstrip()
        cluster = struct.unpack_from("<H", entry, 26)[0]
        size = struct.unpack_from("<I", entry, 28)[0]
        content = bytearray()
        seen = set()
        while size and 2 <= cluster < 0xFF8 and len(content) < size:
            if cluster in seen:
                raise ValueError(f"FAT12 cluster loop in {name}")
            seen.add(cluster)
            start = geo["data"] + (cluster - 2) * geo["cluster"]
            content += image[start:start + geo["cluster"]]
            cluster = _next_cluster(fat, cluster)
        if len(content) < size:
            raise ValueError(f"FAT12 chain shorter than size for {name}")
        files[f"{name}.{ext}" if ext else name] = bytes(content[:size])
    return files
