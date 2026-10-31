/* SCAN08.dll 1.0.3.6, x86 host ABI. Evidence: research/cyberview reports.
 * These are vendor host structures, not USB requests. Never infer hardware
 * verification from the CPU-only fixture using these structures. */
#ifndef FRAME_AFL_CONTRACT_H
#define FRAME_AFL_CONTRACT_H
#include <windows.h>
#include <stddef.h>

typedef int (__cdecl *AflStripCallback)(void *);
typedef int (__cdecl *AflDeviceIO)(int, void *);

#pragma pack(push, 4)
typedef struct {
    WORD dpi, reserved;
    float left, top, right, bottom; /* Absolute edges, inches. */
    DWORD mode;
    WORD exposure[3], offset[3];
    WORD *lut[3]; /* Each points to 4096 uint16 samples. */
    BYTE gain[3], option33, option34, film_class, reserved36[2];
    DWORD option38, option3c;
    AflStripCallback callback;
    DWORD requested_lines;
} AflScanBlock;
typedef struct { DWORD flags; AflScanBlock scan; } AflScanRequest;
typedef struct {
    DWORD dpi, mode, width, height, reserved10, lines;
    DWORD abort_requested, last;
    BYTE *data;
    DWORD reserved24, remaining_lines; /* NOT bytes per row. */
} AflStrip;
#pragma pack(pop)

#define AFL_ASSERT(name, expression) typedef char name[(expression) ? 1 : -1]
AFL_ASSERT(afl_pointer_is_x86, sizeof(void *) == 4);
AFL_ASSERT(afl_scan_size, sizeof(AflScanBlock) == 0x48);
AFL_ASSERT(afl_request_size, sizeof(AflScanRequest) == 0x4c);
AFL_ASSERT(afl_callback_offset, offsetof(AflScanBlock, callback) == 0x40);
AFL_ASSERT(afl_lut_offset, offsetof(AflScanBlock, lut) == 0x24);
AFL_ASSERT(afl_class_offset, offsetof(AflScanBlock, film_class) == 0x35);
AFL_ASSERT(afl_strip_size, sizeof(AflStrip) == 0x2c);
AFL_ASSERT(afl_remaining_offset, offsetof(AflStrip, remaining_lines) == 0x28);
#endif
