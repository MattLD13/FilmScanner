/* Passive USB watch and trace for the PF1800 AFL vendor stack (shared by aflbridge and cvbridge).
 *
 * FVC.dll is the only vendor module that sends traffic to the scanner. It does so
 * through five kernel32 calls on a \\.\USBSCANn handle (usbscan.sys):
 *   DeviceIoControl  IOCTL_WRITE_REGISTERS / READ_REGISTERS (vendor control requests),
 *                    IOCTL_WAIT_ON_DEVICE_EVENT (interrupt pipe), GET_DEVICE_DESCRIPTOR
 *   WriteFile / ReadFile (+ GetOverlappedResult)  bulk OUT / bulk IN
 *   CreateFileA / CloseHandle
 * usbtrace_install patches those import slots in the already-loaded vendor modules.
 * Every call is passed through unchanged; the watch adds no traffic.
 *
 * Two independent uses:
 *   - a log file (optional): one JSON line per call. Bulk OUT payloads (gamma and
 *     shading tables, at most TRACE_OUT_BYTES each) are logged whole; other payloads
 *     are cut to TRACE_BYTES so image data stays out. Decode with
 *     research/cyberview/analysis/usb_trace.py.
 *   - callbacks (optional): register writes, status reads and completed bulk-in
 *     reads, decoded with the wire mapping in docs/scanner-protocol.md. They run on
 *     the driver's own thread, outside the trace lock, and must return quickly.
 */
#ifndef FRAME_USBTRACE_H
#define FRAME_USBTRACE_H
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define TRACE_BYTES 64
#define TRACE_OUT_BYTES 65536
#define TRACE_PENDING 8
#define TRACE_HANDLES 16

typedef struct { DWORD offset, length; BYTE *data; DWORD index; } TraceIoBlock; /* usbscan IO_BLOCK */
typedef HANDLE (WINAPI *TraceCreateFileA)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef BOOL (WINAPI *TraceDeviceIoControl)(HANDLE, DWORD, LPVOID, DWORD, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *TraceReadFile)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *TraceWriteFile)(HANDLE, LPCVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *TraceGetOverlappedResult)(HANDLE, LPOVERLAPPED, LPDWORD, BOOL);
typedef BOOL (WINAPI *TraceCloseHandle)(HANDLE);

/* Callbacks. Register writes are IOCTL_WRITE_REGISTERS offset 0xB0 with [reg, value];
 * a status read is IOCTL_READ_REGISTERS offset 7 (the value of the selected register). */
static void (*trace_on_register)(BYTE reg, BYTE value);
static void (*trace_on_status)(BYTE value);
static void (*trace_on_bulk_in)(const BYTE *data, DWORD size);

static FILE *trace_file;
static int trace_installed;
static CRITICAL_SECTION trace_lock;
static LARGE_INTEGER trace_start, trace_frequency;
static LONG trace_sequence;
static TraceCreateFileA real_CreateFileA;
static TraceDeviceIoControl real_DeviceIoControl;
static TraceReadFile real_ReadFile;
static TraceWriteFile real_WriteFile;
static TraceGetOverlappedResult real_GetOverlappedResult;
static TraceCloseHandle real_CloseHandle;
static HANDLE trace_handles[TRACE_HANDLES];
static struct { LPOVERLAPPED overlapped; BYTE *buffer; } trace_pending[TRACE_PENDING];

static int trace_tracked(HANDLE h) {
    for (int i = 0; i < TRACE_HANDLES; i++) if (trace_handles[i] == h && h) return 1;
    return 0;
}
/* Starts a record; the caller holds trace_lock and has checked trace_file. */
static void trace_begin(const char *call) {
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    fprintf(trace_file, "{\"n\":%ld,\"ms\":%.3f,\"tid\":%lu,\"call\":\"%s\"", InterlockedIncrement(&trace_sequence),
            (double)(now.QuadPart - trace_start.QuadPart) * 1000.0 / (double)trace_frequency.QuadPart, GetCurrentThreadId(), call);
}
static void trace_hex_limit(const char *key, const void *data, DWORD count, DWORD limit) {
    const BYTE *p = (const BYTE *)data;
    fprintf(trace_file, ",\"%s\":\"", key);
    if (p) {
        __try { for (DWORD i = 0; i < count && i < limit; i++) fprintf(trace_file, "%02x", p[i]); }
        __except (EXCEPTION_EXECUTE_HANDLER) { fputs("??", trace_file); }
    }
    fputc('"', trace_file);
}
static void trace_hex(const char *key, const void *data, DWORD count) { trace_hex_limit(key, data, count, TRACE_BYTES); }
static void trace_end(BOOL ok, DWORD error) {
    fprintf(trace_file, ",\"ok\":%d", ok ? 1 : 0);
    if (!ok) fprintf(trace_file, ",\"error\":%lu", error);
    fputs("}\n", trace_file); fflush(trace_file);
}
static void trace_bulk_in(const BYTE *data, DWORD size) {
    if (!trace_on_bulk_in || !data || !size) return;
    __try { trace_on_bulk_in(data, size); } __except (EXCEPTION_EXECUTE_HANDLER) {}
}

static HANDLE WINAPI trace_CreateFileA(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security,
                                       DWORD disposition, DWORD flags, HANDLE templ) {
    HANDLE h = real_CreateFileA(name, access, share, security, disposition, flags, templ); DWORD error = GetLastError();
    EnterCriticalSection(&trace_lock);
    if (h != INVALID_HANDLE_VALUE)
        for (int i = 0; i < TRACE_HANDLES; i++) if (!trace_handles[i]) { trace_handles[i] = h; break; }
    if (trace_file) {
        trace_begin("CreateFileA");
        fputs(",\"name\":\"", trace_file);
        for (const char *p = name; p && *p; p++) fprintf(trace_file, (*p == '\\' || *p == '"') ? "\\%c" : "%c", *p);
        fprintf(trace_file, "\",\"access\":%lu,\"flags\":%lu,\"handle\":%lu", access, flags, (DWORD)(UINT_PTR)h);
        trace_end(h != INVALID_HANDLE_VALUE, error);
    }
    LeaveCriticalSection(&trace_lock);
    SetLastError(error); return h;
}
static BOOL WINAPI trace_DeviceIoControl(HANDLE h, DWORD code, LPVOID in, DWORD in_size, LPVOID out, DWORD out_size,
                                         LPDWORD returned, LPOVERLAPPED overlapped) {
    TraceIoBlock block = {0}; int has_block = in && in_size >= sizeof block; BYTE first[2] = {0};
    if (has_block) {
        __try { block = *(TraceIoBlock *)in; } __except (EXCEPTION_EXECUTE_HANDLER) { has_block = 0; }
    }
    BOOL ok = real_DeviceIoControl(h, code, in, in_size, out, out_size, returned, overlapped); DWORD error = GetLastError();
    if (ok && has_block && block.data && block.length) {
        __try { first[0] = block.data[0]; if (block.length > 1) first[1] = block.data[1]; }
        __except (EXCEPTION_EXECUTE_HANDLER) { has_block = 0; }
    }
    if (trace_file) {
        EnterCriticalSection(&trace_lock);
        trace_begin("DeviceIoControl");
        fprintf(trace_file, ",\"handle\":%lu,\"ioctl\":%lu,\"in_size\":%lu,\"out_size\":%lu", (DWORD)(UINT_PTR)h, code, in_size, out_size);
        trace_hex("in", in, in_size);
        if (has_block) {
            fprintf(trace_file, ",\"block\":{\"offset\":%lu,\"length\":%lu,\"index\":%lu}", block.offset, block.length, block.index);
            trace_hex("data", block.data, block.length);   /* written bytes, or the bytes read back */
        }
        if (ok && out) trace_hex("out", out, returned ? *returned : out_size);
        if (returned) fprintf(trace_file, ",\"returned\":%lu", *returned);
        trace_end(ok, error);
        LeaveCriticalSection(&trace_lock);
    }
    if (ok && has_block) {
        if (code == 0x80002010 && block.offset == 0xB0 && block.length == 2 && trace_on_register) trace_on_register(first[0], first[1]);
        else if (code == 0x8000200C && block.offset == 7 && block.length == 1 && trace_on_status) trace_on_status(first[0]);
    }
    SetLastError(error); return ok;
}
static BOOL WINAPI trace_WriteFile(HANDLE h, LPCVOID data, DWORD size, LPDWORD written, LPOVERLAPPED overlapped) {
    BOOL ok = real_WriteFile(h, data, size, written, overlapped); DWORD error = GetLastError();
    if (trace_file) {
        EnterCriticalSection(&trace_lock);
        trace_begin("WriteFile");
        fprintf(trace_file, ",\"handle\":%lu,\"size\":%lu", (DWORD)(UINT_PTR)h, size);
        trace_hex_limit("data", data, size, TRACE_OUT_BYTES);
        if (written) fprintf(trace_file, ",\"done\":%lu", *written);
        trace_end(ok, error);
        LeaveCriticalSection(&trace_lock);
    }
    SetLastError(error); return ok;
}
static BOOL WINAPI trace_ReadFile(HANDLE h, LPVOID data, DWORD size, LPDWORD read, LPOVERLAPPED overlapped) {
    BOOL ok = real_ReadFile(h, data, size, read, overlapped); DWORD error = GetLastError();
    EnterCriticalSection(&trace_lock);
    if (!ok && error == ERROR_IO_PENDING && overlapped)
        for (int i = 0; i < TRACE_PENDING; i++) if (!trace_pending[i].overlapped) {
            trace_pending[i].overlapped = overlapped; trace_pending[i].buffer = (BYTE *)data; break;
        }
    if (trace_file) {
        trace_begin("ReadFile");
        fprintf(trace_file, ",\"handle\":%lu,\"size\":%lu,\"overlapped\":%d", (DWORD)(UINT_PTR)h, size, overlapped != NULL);
        if (ok) { if (read) fprintf(trace_file, ",\"done\":%lu", *read); trace_hex("data", data, read ? *read : 0); }
        trace_end(ok, error);
    }
    LeaveCriticalSection(&trace_lock);
    if (ok && read && trace_tracked(h)) trace_bulk_in((const BYTE *)data, *read);
    SetLastError(error); return ok;
}
static BOOL WINAPI trace_GetOverlappedResult(HANDLE h, LPOVERLAPPED overlapped, LPDWORD done, BOOL wait) {
    BOOL ok = real_GetOverlappedResult(h, overlapped, done, wait); DWORD error = GetLastError(); BYTE *buffer = NULL;
    EnterCriticalSection(&trace_lock);
    for (int i = 0; i < TRACE_PENDING; i++) if (trace_pending[i].overlapped == overlapped) {
        buffer = trace_pending[i].buffer; trace_pending[i].overlapped = NULL; break;
    }
    if (trace_file) {
        trace_begin("GetOverlappedResult");
        fprintf(trace_file, ",\"handle\":%lu", (DWORD)(UINT_PTR)h);
        if (ok && done) { fprintf(trace_file, ",\"done\":%lu", *done); trace_hex("data", buffer, *done); }
        trace_end(ok, error);
    }
    LeaveCriticalSection(&trace_lock);
    if (ok && done && buffer) trace_bulk_in(buffer, *done);
    SetLastError(error); return ok;
}
static BOOL WINAPI trace_CloseHandle(HANDLE h) {
    BOOL tracked, ok;
    EnterCriticalSection(&trace_lock);
    tracked = trace_tracked(h);
    if (tracked) for (int i = 0; i < TRACE_HANDLES; i++) if (trace_handles[i] == h) trace_handles[i] = NULL;
    LeaveCriticalSection(&trace_lock);
    ok = real_CloseHandle(h);
    if (tracked && trace_file) {
        DWORD error = GetLastError();
        EnterCriticalSection(&trace_lock);
        trace_begin("CloseHandle"); fprintf(trace_file, ",\"handle\":%lu", (DWORD)(UINT_PTR)h); trace_end(ok, error);
        LeaveCriticalSection(&trace_lock);
        SetLastError(error);
    }
    return ok;
}

/* Replaces the import slots of ``module`` that hold one of the traced kernel32
 * functions. Slots are matched by address, so forwarded and unnamed imports work. */
static int trace_hook_module(HMODULE module) {
    static const char *names[] = {"CreateFileA", "DeviceIoControl", "ReadFile", "WriteFile", "GetOverlappedResult", "CloseHandle"};
    void *hooks[] = {(void *)trace_CreateFileA, (void *)trace_DeviceIoControl, (void *)trace_ReadFile,
                     (void *)trace_WriteFile, (void *)trace_GetOverlappedResult, (void *)trace_CloseHandle};
    HMODULE kernel = GetModuleHandleA("kernel32.dll"); void *real[6]; int patched = 0;
    BYTE *base = (BYTE *)module;
    if (!module || !kernel) return 0;
    for (int i = 0; i < 6; i++) real[i] = (void *)GetProcAddress(kernel, names[i]);
    IMAGE_NT_HEADERS32 *nt = (IMAGE_NT_HEADERS32 *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return 0;
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); d->Name; d++) {
        for (IMAGE_THUNK_DATA32 *slot = (IMAGE_THUNK_DATA32 *)(base + d->FirstThunk); slot->u1.Function; slot++) {
            for (int i = 0; i < 6; i++) {
                if (!real[i] || slot->u1.Function != (DWORD)(UINT_PTR)real[i]) continue;
                DWORD old;
                if (VirtualProtect(&slot->u1.Function, sizeof(DWORD), PAGE_READWRITE, &old)) {
                    slot->u1.Function = (DWORD)(UINT_PTR)hooks[i];
                    VirtualProtect(&slot->u1.Function, sizeof(DWORD), old, &old);
                    patched++;
                }
            }
        }
    }
    return patched;
}

/* Hooks every loaded module in ``modules`` (NULL-terminated base names) once. With a
 * ``path`` it also logs every call there. Returns the number of import slots patched,
 * or -1 if the log cannot open. Set the trace_on_* callbacks before calling. */
static int usbtrace_install(const char *path, const char **modules) {
    HMODULE kernel = GetModuleHandleA("kernel32.dll"); int patched = 0;
    if (trace_installed) return 0;
    if (path && (fopen_s(&trace_file, path, "w") || !trace_file)) { trace_file = NULL; return -1; }
    InitializeCriticalSection(&trace_lock);
    QueryPerformanceFrequency(&trace_frequency); QueryPerformanceCounter(&trace_start);
    real_CreateFileA = (TraceCreateFileA)GetProcAddress(kernel, "CreateFileA");
    real_DeviceIoControl = (TraceDeviceIoControl)GetProcAddress(kernel, "DeviceIoControl");
    real_ReadFile = (TraceReadFile)GetProcAddress(kernel, "ReadFile");
    real_WriteFile = (TraceWriteFile)GetProcAddress(kernel, "WriteFile");
    real_GetOverlappedResult = (TraceGetOverlappedResult)GetProcAddress(kernel, "GetOverlappedResult");
    real_CloseHandle = (TraceCloseHandle)GetProcAddress(kernel, "CloseHandle");
    trace_installed = 1;
    for (const char **m = modules; *m; m++) {
        int count = trace_hook_module(GetModuleHandleA(*m));
        if (trace_file)
            fprintf(trace_file, "{\"n\":0,\"call\":\"hooked\",\"module\":\"%s\",\"loaded\":%d,\"slots\":%d}\n",
                    *m, GetModuleHandleA(*m) != NULL, count);
        patched += count;
    }
    if (trace_file) fflush(trace_file);
    return patched;
}
#endif
