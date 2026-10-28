/*
 * FRAME research simulator for the missing CyberView model-37 (PF1800 AFL) module.
 *
 * NOT Pacific Image software and NOT device evidence. It implements the model-module
 * contract BeneScan.dll calls (int __cdecl ScannerDeviceIO(int selector, void *param)),
 * reconstructed statically from the SCAN08-lineage LC.dll (SHA-256 5486ACE5...):
 * selector switch 0x1000f020, identity 0x100115f0/0x1000f930, capabilities 0x100122c0,
 * status 0x10010470, scan 0x10010640/0x10010f90. Every answer is SIMULATED; image data
 * is a synthetic pattern. Every call is appended to C:\FRAME\SIMAFL.LOG.
 *
 * Only for the isolated research guest. It never opens a device or issues USB I/O.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define LOG_PATH "C:\\FRAME\\SIMAFL.LOG"
#define INI_PATH "C:\\FRAME\\SIMAFL.INI"
#define MODEL_CODE 0x25          /* BeneScan record 3 / CPfs1800AFL; LC.dll reports 0x2a */
#define MAX_DPI 1800
#define FULL_WIDTH 2496          /* LC.dll capability block at 1800 dpi (0x9c0) */
#define FULL_HEIGHT 1708         /* LC.dll capability block at 1800 dpi (0x6ac) */

typedef void (__cdecl *STRIP_CALLBACK)(void *strip);

/* Strip block LC.dll passes to the scan callback (built at EBP-0x54 in 0x10010640). */
typedef struct {
    DWORD first_param;   /* +0x00 dword 0 of the scan block */
    DWORD mode;          /* +0x04 color mode 2..7 */
    DWORD width;         /* +0x08 pixels per line */
    DWORD height;        /* +0x0c total lines */
    DWORD zero;          /* +0x10 */
    DWORD lines;         /* +0x14 lines in this strip */
    DWORD abort;         /* +0x18 callback sets 1 to cancel */
    DWORD last;          /* +0x1c 1 on the final strip */
    BYTE *data;          /* +0x20 strip pixels */
    DWORD available;     /* +0x24 */
    DWORD bytes_per_line;/* +0x28 */
    DWORD status;        /* +0x2c */
} STRIP;

static CRITICAL_SECTION lock;
static LONG calls;
static int opened;
static int frame;        /* simulated position on the roll, advanced by transport selectors */
static DWORD notify_window, notify_message;
static DWORD stored14[3];

static void logf(const char *format, ...)
{
    FILE *out;
    SYSTEMTIME now;
    va_list args;
    CreateDirectoryA("C:\\FRAME", NULL);
    out = fopen(LOG_PATH, "a");
    if (!out) return;
    GetLocalTime(&now);
    fprintf(out, "%02d:%02d:%02d.%03d ", now.wHour, now.wMinute, now.wSecond, now.wMilliseconds);
    va_start(args, format);
    vfprintf(out, format, args);
    va_end(args);
    fputc('\n', out);
    fclose(out);
}

static void hex(char *text, const void *data, int length)
{
    int i;
    text[0] = 0;
    if (!data) { strcpy(text, "null"); return; }
    if (IsBadReadPtr(data, length)) { strcpy(text, "unreadable"); return; }
    for (i = 0; i < length; i++) sprintf(text + i * 2, "%02x", ((const BYTE *)data)[i]);
}

static int setting(const char *key, int fallback)
{
    return GetPrivateProfileIntA("Simulator", key, fallback, INI_PATH);
}

/* 0x84-byte capability block, field for field as LC.dll 0x100122c0 builds it, model code changed. */
static void capabilities(BYTE *info)
{
    memset(info, 0, 0x84);
    info[0] = 6; info[2] = 2; info[3] = 1; info[4] = 0xb4;
    memcpy(info + 0x08, "PIE     ", 8);
    memcpy(info + 0x10, "SF Film Scanner ", 16);
    memcpy(info + 0x20, "1.0", 3);
    *(WORD *)(info + 0x24) = MAX_DPI;
    *(WORD *)(info + 0x26) = MAX_DPI;
    *(WORD *)(info + 0x28) = FULL_WIDTH;
    *(WORD *)(info + 0x2a) = FULL_HEIGHT;
    info[0x2c] = 0x8e; info[0x2d] = 0x14; info[0x2e] = 1; info[0x30] = 2;
    info[0x31] = 0x4b; info[0x32] = 0x28; info[0x33] = 8; info[0x34] = 0x0c;
    *(WORD *)(info + 0x36) = 0x96;
    info[0x65] = 100; info[0x66] = 0x19; info[0x67] = 2;
    *(WORD *)(info + 0x68) = 0x9c4;
    *(WORD *)(info + 0x6a) = 100;
    *(WORD *)(info + 0x70) = FULL_WIDTH;
    *(WORD *)(info + 0x72) = FULL_HEIGHT;
    *(WORD *)(info + 0x74) = MODEL_CODE;
    memcpy(info + 0x78, "PIE", 3);
    memset(info + 0x7c, ' ', 8);
}

/* Detect/open identity: vendor(8) product(16) revision(4) then three status bytes, as 0x100115f0. */
static int identity(BYTE *param)
{
    BYTE info[0x84];
    if (IsBadWritePtr(param, 0x23)) return 0;
    capabilities(info);
    memcpy(param, info + 0x08, 8);
    memcpy(param + 0x08, info + 0x10, 16);
    memcpy(param + 0x18, info + 0x20, 4);
    param[0x20] = 0; param[0x21] = 0; param[0x22] = 0;
    return 1;
}

static DWORD bytes_per_pixel(DWORD mode)
{
    switch (mode) {
    case 1: case 2: return 1;
    case 3: return 3;
    case 4: case 6: return 2;
    case 5: case 7: return 6;
    default: return 0;
    }
}

/* Synthetic frame: a film-holder border, a horizontal ramp and a frame-dependent band. */
static void fill_line(BYTE *line, DWORD width, DWORD y, DWORD height, DWORD mode)
{
    DWORD x, channels = (mode == 3 || mode == 5 || mode == 7) ? 3 : 1;
    int wide = (mode >= 4);
    DWORD border = width / 40 + 1;
    DWORD band = (DWORD)((frame % 6) + 1) * height / 8;
    for (x = 0; x < width; x++) {
        DWORD c;
        for (c = 0; c < channels; c++) {
            DWORD value;
            if (x < border || x >= width - border || y < border || y >= height - border)
                value = 0x0800;                                   /* dark holder edge */
            else if (y >= band && y < band + height / 12)
                value = c == 0 ? 0xe000 : (c == 1 ? 0x6000 : 0x2000); /* frame marker band */
            else
                value = (x * 0xffff / width) * (c + 2) / 4 + (y * 0x3fff / height);
            if (value > 0xffff) value = 0xffff;
            if (wide) {
                line[(x * channels + c) * 2] = (BYTE)value;
                line[(x * channels + c) * 2 + 1] = (BYTE)(value >> 8);
            } else {
                line[x * channels + c] = (BYTE)(value >> 8);
            }
        }
    }
}

static int scan(BYTE *block)
{
    STRIP strip;
    STRIP_CALLBACK callback;
    DWORD dpi, mode, bpp, per_strip, y = 0, strips = 0;
    char text[0x48 * 2 + 1];
    BYTE *buffer;

    if (IsBadReadPtr(block, 0x48)) return 0;
    hex(text, block, 0x48);
    dpi = *(WORD *)block;
    mode = *(DWORD *)(block + 0x14);
    callback = *(STRIP_CALLBACK *)(block + 0x40);
    per_strip = *(DWORD *)(block + 0x44);
    bpp = bytes_per_pixel(mode);
    logf("  scan block %s", text);
    if (!bpp || dpi == 0 || dpi > MAX_DPI || !callback || IsBadCodePtr((FARPROC)callback)) {
        logf("  scan rejected dpi=%lu mode=%lu callback=%p", dpi, mode, callback);
        return 0;
    }
    if (per_strip == 0 || per_strip > 512) per_strip = 64;
    memset(&strip, 0, sizeof strip);
    strip.first_param = *(DWORD *)block;
    strip.mode = mode;
    strip.width = FULL_WIDTH * dpi / MAX_DPI;
    strip.height = FULL_HEIGHT * dpi / MAX_DPI;
    strip.bytes_per_line = strip.width * bpp;
    buffer = (BYTE *)HeapAlloc(GetProcessHeap(), 0, strip.bytes_per_line * per_strip);
    if (!buffer) return 0;
    logf("  scan frame=%d dpi=%lu mode=%lu width=%lu height=%lu bytes_per_line=%lu lines_per_strip=%lu",
         frame, dpi, mode, strip.width, strip.height, strip.bytes_per_line, per_strip);
    while (y < strip.height) {
        DWORD i, lines = min(per_strip, strip.height - y);
        for (i = 0; i < lines; i++)
            fill_line(buffer + i * strip.bytes_per_line, strip.width, y + i, strip.height, mode);
        strip.lines = lines;
        strip.available = lines;
        strip.data = buffer;
        strip.last = (y + lines == strip.height);
        callback(&strip);
        strips++;
        y += lines;
        if (strip.abort == 1) {
            logf("  scan aborted by caller after %lu lines", y);
            HeapFree(GetProcessHeap(), 0, buffer);
            return 0;
        }
        Sleep(setting("StripDelayMs", 0));
    }
    HeapFree(GetProcessHeap(), 0, buffer);
    logf("  scan complete strips=%lu lines=%lu", strips, y);
    return 1;
}

static int dispatch(int selector, BYTE *param)
{
    BYTE info[0x84];
    switch (selector) {
    case 1: return 1;                                    /* init */
    case 2: opened = 0; return 1;                        /* close */
    case 3: return setting("Present", 1) ? identity(param) : 0;   /* detect */
    case 4: return 0;
    case 5: opened = identity(param); return opened;     /* open */
    case 6:                                              /* version strings */
        if (IsBadWritePtr(param, 9)) return 0;
        if (*(DWORD *)param == 1) memcpy(param + 4, "1.0", 4);
        else if (*(DWORD *)param == 2) memcpy(param + 4, "SIM", 4);
        param[8] = 0;
        return 1;
    case 7: case 8: case 0x0b: case 0x0c: case 0x0d: case 0x0e: case 0x0f: case 0x10:
    case 0x17: case 0x19: case 0x1a: case 0x2b: case 0x3e9: case 0x3ea: case 0x3eb:
    case 0x3ec: case 0x3ed: case 0x3ee: case 0x3ef:
        return 1;                                        /* LC.dll answers these with 1 */
    case 9: case 10:                                     /* transport in CyberViewX AFL methods */
        frame++;
        logf("  simulated transport selector=0x%x frame=%d", selector, frame);
        return 1;
    case 0x11: case 0x1b: case 0x21:                     /* three per-channel u16 values */
        if (IsBadWritePtr(param, 6)) return 0;
        ((WORD *)param)[0] = 100; ((WORD *)param)[1] = 100; ((WORD *)param)[2] = 100;
        return 1;
    case 0x12:
        if (IsBadWritePtr(param, 4)) return 0;
        *(DWORD *)param = 0;
        return 1;
    case 0x13: return scan(param);
    case 0x14:
        if (IsBadReadPtr(param, 12)) return 0;
        memcpy(stored14, param, 12);
        return 1;
    case 0x15: {
        /* Status bits as CyberViewX reads them (0x100bb1a0 GetScannerStatus, 0x100bb240
           IsDocumentInFeeder): bit0 -> busy (keeps polling), bit1 ready, bit4 set = feeder empty. */
        DWORD *status = (DWORD *)param, result;
        if (IsBadWritePtr(param, 8)) return 0;
        result = (DWORD)setting("StatusBits", 0x0a);
        if (!setting("FilmLoaded", 1)) result |= 0x10;
        status[1] = result & status[0];
        return 1;
    }
    case 0x16:                                           /* capabilities into param+1 */
        if (IsBadWritePtr(param, 0x85)) return 0;
        capabilities(info);
        memcpy(param + 1, info, 0x84);
        return 1;
    case 0x18: {                                         /* model byte, as 0x10010f00 */
        BYTE *target = *(BYTE **)param;
        BYTE size = param[4];
        if (IsBadWritePtr(target, size)) return 0;
        memset(target, 0, size);
        if (size > 1) target[0] = MODEL_CODE;
        return 1;
    }
    case 0x20:                                           /* flags + 0x48-byte scan block */
        if (IsBadReadPtr(param, 0x4c)) return 0;
        return scan(param + 4);
    case 0x23:
        if (IsBadWritePtr(param, 2) || param[0] < 2) return 0;
        memset(param + 1, 0, param[0] - 1);
        param[1] = 0x01;
        return 1;
    case 0x2a:                                           /* status notifications (window, message) */
        if (IsBadReadPtr(param, 8)) return 0;
        notify_window = ((DWORD *)param)[0];
        notify_message = ((DWORD *)param)[1];
        return 1;
    default:
        return 0;
    }
}

__declspec(dllexport) int __cdecl ScannerDeviceIO(int selector, void *param)
{
    char before[65], after[65];
    int result;
    LONG n;
    EnterCriticalSection(&lock);
    n = InterlockedIncrement(&calls);
    hex(before, param, 32);
    result = dispatch(selector, (BYTE *)param);
    hex(after, param, 32);
    logf("#%ld sel=0x%x param=%p result=%d in=%s out=%s", n, selector, param, result, before, after);
    LeaveCriticalSection(&lock);
    return result;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    char path[MAX_PATH];
    if (reason == DLL_PROCESS_ATTACH) {
        InitializeCriticalSection(&lock);
        GetModuleFileNameA(instance, path, MAX_PATH);
        logf("FRAME SIMULATED SCAN08 (model 0x%x) loaded from %s; not Pacific Image software", MODEL_CODE, path);
    } else if (reason == DLL_PROCESS_DETACH) {
        logf("FRAME SIMULATED SCAN08 unloaded after %ld calls", calls);
        DeleteCriticalSection(&lock);
    }
    return TRUE;
}
