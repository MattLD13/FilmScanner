/* cvbridge: drive the installed CyberView X TWAIN data source without its window.
 *
 * x86 only, because CyberViewX.ds and twain_32.dll are 32-bit. One command per
 * process; every result is one JSON object per stdout line. The vendor driver
 * performs all scanner I/O; this program never talks to USB itself.
 *
 *   cvbridge sources
 *   cvbridge caps  [--source NAME]
 *   cvbridge scan  --out PATH [--source NAME] [--dpi N] [--depth 8|16]
 *                  [--area L,T,R,B] [--show-ui] [--timeout SECONDS]
 *
 * scan writes PATH (uncompressed little-endian TIFF), or PATH with _NN before the
 * extension when the driver delivers more than one image. Writing "cancel" on
 * stdin requests a TWAIN cancel; the driver is always disabled and closed.
 *
 * scan and serve watch the vendor FVC.dll's calls to usbscan.sys
 * (../native_bridge/usbtrace.h) for live preview rows ("live_start", "live") and to
 * stop a driver stuck waiting for a sensor ("position_sensor"). --trace-usb PATH also
 * logs every call; --no-usb-watch turns the watch off. Neither adds scanner traffic.
 *
 * Hidden mode: CyberViewX.ds hides its own window when [Non UI Information]
 * "Hide UI" is 1 and "Host Handle" names a live window (static analysis of
 * CyberViewX.ds 1.4.0.0, see docs/cyberview-bridge.md). The keys are set in the
 * per-user CyberViewX.ini for the session and restored before exit.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tlhelp32.h>
#include "../native_bridge/usbtrace.h"

#pragma pack(push, 2)
typedef char TW_STR32[34];
typedef struct { WORD MajorNum, MinorNum, Language, Country; TW_STR32 Info; } TW_VERSION;
typedef struct { DWORD Id; TW_VERSION Version; WORD ProtocolMajor, ProtocolMinor; DWORD SupportedGroups;
                 TW_STR32 Manufacturer, ProductFamily, ProductName; } TW_IDENTITY;
typedef struct { short Whole; WORD Frac; } TW_FIX32;
typedef struct { TW_FIX32 Left, Top, Right, Bottom; } TW_FRAME;
typedef struct { WORD ShowUI, ModalUI; HANDLE hParent; } TW_USERINTERFACE;
typedef struct { void *pEvent; WORD TWMessage; } TW_EVENT;
typedef struct { WORD Cap, ConType; HANDLE hContainer; } TW_CAPABILITY;
typedef struct { WORD ItemType; DWORD Item; } TW_ONEVALUE;
typedef struct { WORD ItemType; DWORD MinValue, MaxValue, StepSize, DefaultValue, CurrentValue; } TW_RANGE;
typedef struct { WORD ItemType; DWORD NumItems, CurrentIndex, DefaultIndex; BYTE ItemList[1]; } TW_ENUMERATION;
typedef struct { WORD ItemType; DWORD NumItems; BYTE ItemList[1]; } TW_ARRAY;
typedef struct { TW_FIX32 XResolution, YResolution; long ImageWidth, ImageLength; short SamplesPerPixel;
                 short BitsPerSample[8]; short BitsPerPixel; WORD Planar; short PixelType; WORD Compression; } TW_IMAGEINFO;
typedef struct { TW_FRAME Frame; DWORD DocumentNumber, PageNumber, FrameNumber; } TW_IMAGELAYOUT;
typedef struct { DWORD MinBufSize, MaxBufSize, Preferred; } TW_SETUPMEMXFER;
typedef struct { DWORD Flags, Length; void *TheMem; } TW_MEMORY;
typedef struct { WORD Compression; DWORD BytesPerRow, Columns, Rows, XOffset, YOffset, BytesWritten; TW_MEMORY Memory; } TW_IMAGEMEMXFER;
typedef struct { WORD Count; DWORD EOJ; } TW_PENDINGXFERS;
typedef struct { WORD ConditionCode, Reserved; } TW_STATUS;
#pragma pack(pop)

enum { DG_CONTROL = 1, DG_IMAGE = 2 };
enum { DAT_CAPABILITY = 1, DAT_EVENT = 2, DAT_IDENTITY = 3, DAT_PARENT = 4, DAT_PENDINGXFERS = 5,
       DAT_SETUPMEMXFER = 6, DAT_STATUS = 8, DAT_USERINTERFACE = 9,
       DAT_IMAGEINFO = 0x101, DAT_IMAGELAYOUT = 0x102, DAT_IMAGEMEMXFER = 0x103 };
enum { MSG_GET = 1, MSG_GETCURRENT = 2, MSG_GETFIRST = 4, MSG_GETNEXT = 5, MSG_SET = 6, MSG_RESET = 7,
       MSG_XFERREADY = 0x101, MSG_CLOSEDSREQ = 0x102, MSG_CLOSEDSOK = 0x103, MSG_DEVICEEVENT = 0x104,
       MSG_OPENDSM = 0x301, MSG_CLOSEDSM = 0x302, MSG_OPENDS = 0x401, MSG_CLOSEDS = 0x402,
       MSG_DISABLEDS = 0x501, MSG_ENABLEDS = 0x502, MSG_PROCESSEVENT = 0x601, MSG_ENDXFER = 0x701 };
enum { TWRC_SUCCESS, TWRC_FAILURE, TWRC_CHECKSTATUS, TWRC_CANCEL, TWRC_DSEVENT, TWRC_NOTDSEVENT,
       TWRC_XFERDONE, TWRC_ENDOFLIST };
enum { TWON_ARRAY = 3, TWON_ENUMERATION = 4, TWON_ONEVALUE = 5, TWON_RANGE = 6 };
enum { TWTY_INT8, TWTY_INT16, TWTY_INT32, TWTY_UINT8, TWTY_UINT16, TWTY_UINT32, TWTY_BOOL, TWTY_FIX32,
       TWTY_FRAME, TWTY_STR32, TWTY_STR64, TWTY_STR128, TWTY_STR255 };
enum { CAP_XFERCOUNT = 1, ICAP_PIXELTYPE = 0x101, ICAP_UNITS = 0x102, ICAP_XFERMECH = 0x103,
       CAP_FEEDERENABLED = 0x1002, CAP_FEEDERLOADED = 0x1003, CAP_AUTOFEED = 0x1007, CAP_SUPPORTEDCAPS = 0x1005, CAP_INDICATORS = 0x100b, CAP_UICONTROLLABLE = 0x100e,
       ICAP_XRESOLUTION = 0x1118, ICAP_YRESOLUTION = 0x1119, ICAP_BITDEPTH = 0x112b };
enum { TWSX_MEMORY = 2, TWPT_GRAY = 1, TWPT_RGB = 2, TWUN_INCHES = 0, TWMF_APPOWNS = 1, TWMF_POINTER = 8 };

typedef WORD (WINAPI *DSMENTRYPROC)(TW_IDENTITY *, TW_IDENTITY *, DWORD, WORD, WORD, void *);

static DSMENTRYPROC dsm;
static TW_IDENTITY app, src;
static HWND hwnd;
static int dsm_open, ds_open, ds_enabled;
static volatile LONG cancel_requested;
static char ini_path[MAX_PATH];
static int ini_changed;

/* ---------- output ---------- */

static void json_str(FILE *f, const char *s) {
    fputc('"', f);
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') { fputc('\\', f); fputc(c, f); }
        else if (c < 0x20) fprintf(f, "\\u%04x", c);
        else fputc(c, f);
    }
    fputc('"', f);
}

static void emit_error(const char *code, const char *message, int condition) {
    printf("{\"event\":\"error\",\"code\":"); json_str(stdout, code);
    printf(",\"message\":"); json_str(stdout, message);
    if (condition >= 0) printf(",\"condition\":%d", condition);
    printf("}\n"); fflush(stdout);
}

static double fix32(TW_FIX32 v) { return v.Whole + v.Frac / 65536.0; }
static TW_FIX32 to_fix32(double v) {
    long n = (long)(v * 65536.0 + (v < 0 ? -0.5 : 0.5));
    TW_FIX32 f; f.Whole = (short)(n >> 16); f.Frac = (WORD)(n & 0xffff); return f;
}

/* ---------- TWAIN helpers ---------- */

static WORD call_dsm(TW_IDENTITY *dest, DWORD dg, WORD dat, WORD msg, void *data) {
    return dsm(&app, dest, dg, dat, msg, data);
}

static int condition_code(TW_IDENTITY *dest) {
    TW_STATUS st = {0};
    if (call_dsm(dest, DG_CONTROL, DAT_STATUS, MSG_GET, &st) != TWRC_SUCCESS) return -1;
    return st.ConditionCode;
}

static int item_size(WORD type) {
    switch (type) {
    case TWTY_INT8: case TWTY_UINT8: return 1;
    case TWTY_INT16: case TWTY_UINT16: case TWTY_BOOL: return 2;
    case TWTY_INT32: case TWTY_UINT32: case TWTY_FIX32: return 4;
    case TWTY_FRAME: return 16;
    case TWTY_STR32: return 34; case TWTY_STR64: return 66; case TWTY_STR128: return 130; case TWTY_STR255: return 256;
    }
    return 0;
}

static void print_item(WORD type, const BYTE *p) {
    switch (type) {
    case TWTY_INT8: printf("%d", *(const signed char *)p); break;
    case TWTY_UINT8: printf("%u", *p); break;
    case TWTY_INT16: printf("%d", *(const short *)p); break;
    case TWTY_UINT16: case TWTY_BOOL: printf("%u", *(const WORD *)p); break;
    case TWTY_INT32: printf("%ld", *(const long *)p); break;
    case TWTY_UINT32: printf("%lu", *(const DWORD *)p); break;
    case TWTY_FIX32: printf("%.4f", fix32(*(const TW_FIX32 *)p)); break;
    case TWTY_FRAME: { const TW_FRAME *fr = (const TW_FRAME *)p;
        printf("[%.4f,%.4f,%.4f,%.4f]", fix32(fr->Left), fix32(fr->Top), fix32(fr->Right), fix32(fr->Bottom)); break; }
    default: if (item_size(type) > 4) { char buf[257]; memcpy(buf, p, item_size(type)); buf[item_size(type) - 1] = 0; json_str(stdout, buf); }
        else printf("null");
    }
}

/* Prints {"con":...,"type":...,...} for a container returned by the source, then frees it. */
static void print_container(TW_CAPABILITY *cap) {
    BYTE *p = (BYTE *)GlobalLock(cap->hContainer);
    if (!p) { printf("null"); return; }
    WORD type = *(WORD *)p;
    int size = item_size(type);
    if (cap->ConType == TWON_ONEVALUE) {
        printf("{\"con\":\"one\",\"type\":%u,\"value\":", type); print_item(type, p + 2); printf("}");
    } else if (cap->ConType == TWON_RANGE) {
        TW_RANGE *r = (TW_RANGE *)p;
        printf("{\"con\":\"range\",\"type\":%u,\"min\":", type); print_item(type, (BYTE *)&r->MinValue);
        printf(",\"max\":"); print_item(type, (BYTE *)&r->MaxValue);
        printf(",\"step\":"); print_item(type, (BYTE *)&r->StepSize);
        printf(",\"default\":"); print_item(type, (BYTE *)&r->DefaultValue);
        printf(",\"current\":"); print_item(type, (BYTE *)&r->CurrentValue); printf("}");
    } else if (cap->ConType == TWON_ENUMERATION && size) {
        TW_ENUMERATION *e = (TW_ENUMERATION *)p;
        printf("{\"con\":\"enum\",\"type\":%u,\"current\":%lu,\"default\":%lu,\"items\":[", type, e->CurrentIndex, e->DefaultIndex);
        for (DWORD i = 0; i < e->NumItems && i < 512; i++) { if (i) printf(","); print_item(type, e->ItemList + i * size); }
        printf("]}");
    } else if (cap->ConType == TWON_ARRAY && size) {
        TW_ARRAY *a = (TW_ARRAY *)p;
        printf("{\"con\":\"array\",\"type\":%u,\"items\":[", type);
        for (DWORD i = 0; i < a->NumItems && i < 512; i++) { if (i) printf(","); print_item(type, a->ItemList + i * size); }
        printf("]}");
    } else printf("{\"con\":%u,\"type\":%u}", cap->ConType, type);
    GlobalUnlock(cap->hContainer);
    GlobalFree(cap->hContainer);
}

static int set_one(WORD capid, WORD type, DWORD value) {
    TW_CAPABILITY cap = { capid, TWON_ONEVALUE, GlobalAlloc(GHND, sizeof(TW_ONEVALUE)) };
    TW_ONEVALUE *one = (TW_ONEVALUE *)GlobalLock(cap.hContainer);
    one->ItemType = type; one->Item = value;
    GlobalUnlock(cap.hContainer);
    WORD rc = call_dsm(&src, DG_CONTROL, DAT_CAPABILITY, MSG_SET, &cap);
    GlobalFree(cap.hContainer);
    return rc == TWRC_SUCCESS || rc == TWRC_CHECKSTATUS;
}

static DWORD fix32_bits(double v) { TW_FIX32 f = to_fix32(v); DWORD d; memcpy(&d, &f, 4); return d; }

static void report_set(const char *name, int ok) {
    printf("{\"event\":\"set\",\"name\":"); json_str(stdout, name);
    printf(",\"ok\":%s", ok ? "true" : "false");
    if (!ok) printf(",\"condition\":%d", condition_code(&src));
    printf("}\n"); fflush(stdout);
}

/* ---------- vendor ini (hidden mode) ---------- */

static int ini_locate(void) {
    char appdata[MAX_PATH];
    const char *forced = getenv("FRAME_CYBERVIEW_INI"); /* tests point this at a copy */
    if (forced && *forced) {
        _snprintf(ini_path, sizeof ini_path, "%s", forced);
        return GetFileAttributesA(ini_path) != INVALID_FILE_ATTRIBUTES;
    }
    if (!SHGetSpecialFolderPathA(NULL, appdata, CSIDL_APPDATA, FALSE)) return 0;
    _snprintf(ini_path, sizeof ini_path, "%s\\PIE\\MF\\CyberViewX.ini", appdata);
    return GetFileAttributesA(ini_path) != INVALID_FILE_ATTRIBUTES;
}

/* The driver rewrites the whole file on close. Put back from the copy taken before
 * the session: the hidden-mode flags, the hidden session's window layout, any --set
 * override, and the film-base (DMin) and focus calibration. Hidden sessions saved
 * defaults there (DMin 100/100/100) even when their scans were good, and the next
 * session's colour was then badly wrong (2026-10-30), so only CyberView itself
 * changes calibration. The driver's film location is left as it wrote it. A copy left
 * by a session that died is merged the same way before anything else. */
static void ini_backup_path(char *out, size_t n) { _snprintf(out, n, "%s.cvbridge-backup", ini_path); }
static void ini_keys_path(char *out, size_t n) { _snprintf(out, n, "%s.cvbridge-keys", ini_path); }

static int presentation_key(const char *section, const char *key) {
    if (!_stricmp(section, "Non UI Information"))
        return !_stricmp(key, "Hide UI") || !_stricmp(key, "Host Handle") || !_stricmp(key, "Pfs Loader Call") ||
               !_stricmp(key, "Pfs Loader Handle");
    return strstr(key, "Layout") != NULL || strstr(key, "Maximized") != NULL;
}

static int calibration_key(const char *section, const char *key) {
    if (!_stricmp(section, "Non UI Information")) return !_stricmp(key, "Block Number");
    return !_stricmp(section, "SCAN INFORMATION") && (!strncmp(key, "DMin Value", 10) || !strncmp(key, "Focus Value", 11));
}

static int override_key(const char *keys, const char *section, const char *key) {
    char want[260];
    _snprintf(want, sizeof want, "%s|%s\n", section, key);
    return keys && strstr(keys, want) != NULL;
}

static void ini_recover_stale(void) {
    static char sections[8192], entries[32768], keys[4096];
    char backup[MAX_PATH], keyfile[MAX_PATH];
    ini_backup_path(backup, sizeof backup);
    ini_keys_path(keyfile, sizeof keyfile);
    if (GetFileAttributesA(backup) == INVALID_FILE_ATTRIBUTES) return;
    keys[0] = 0;
    FILE *kf = fopen(keyfile, "rb");
    if (kf) { size_t n = fread(keys, 1, sizeof keys - 1, kf); keys[n] = 0; fclose(kf); }
    GetPrivateProfileSectionNamesA(sections, sizeof sections, backup);
    for (char *section = sections; *section; section += strlen(section) + 1) {
        GetPrivateProfileSectionA(section, entries, sizeof entries, backup);
        for (char *entry = entries; *entry; entry += strlen(entry) + 1) {
            char *eq = strchr(entry, '=');
            if (!eq) continue;
            *eq = 0;
            if (presentation_key(section, entry) || override_key(keys, section, entry) ||
                calibration_key(section, entry))
                WritePrivateProfileStringA(section, entry, eq + 1, ini_path);
            *eq = '=';
        }
    }
    WritePrivateProfileStringA(NULL, NULL, NULL, ini_path);
    DeleteFileA(keyfile);
    if (DeleteFileA(backup)) { printf("{\"event\":\"settings_restored\"}\n"); fflush(stdout); }
}

/* Session overrides given as "Section|Key|Value"; they live only until the restore. */
static const char *overrides[32];
static int override_count;

static int ini_enter_hidden(int hide) {
    char handle[32], backup[MAX_PATH];
    ini_recover_stale();
    ini_backup_path(backup, sizeof backup);
    if (!CopyFileA(ini_path, backup, FALSE)) return 0;
    ini_changed = 1;
    if (hide) {
        _snprintf(handle, sizeof handle, "%lu", (unsigned long)(ULONG_PTR)hwnd);
        WritePrivateProfileStringA("Non UI Information", "Hide UI", "1", ini_path);
        WritePrivateProfileStringA("Non UI Information", "Host Handle", handle, ini_path);
        WritePrivateProfileStringA("Non UI Information", "Pfs Loader Call", "0", ini_path);
    }
    char keyfile[MAX_PATH];
    ini_keys_path(keyfile, sizeof keyfile);
    FILE *kf = override_count ? fopen(keyfile, "wb") : NULL;
    for (int i = 0; i < override_count; i++) {
        char section[128], key[128];
        const char *a = strchr(overrides[i], '|'), *b = a ? strchr(a + 1, '|') : NULL;
        if (!b || a - overrides[i] >= 128 || b - a - 1 >= 128) continue;
        _snprintf(section, sizeof section, "%.*s", (int)(a - overrides[i]), overrides[i]);
        _snprintf(key, sizeof key, "%.*s", (int)(b - a - 1), a + 1);
        if (kf) fprintf(kf, "%s|%s\n", section, key);
        WritePrivateProfileStringA(section, key, b + 1, ini_path);
    }
    if (kf) fclose(kf);
    return 1;
}

/* CyberViewX.ds writes the file again while this process exits, so the restore runs
 * in a second cvbridge process that waits for this one to end. */
static void ini_restore(void) {
    char exe[MAX_PATH], cmd[MAX_PATH + 64];
    STARTUPINFOA si = { sizeof si };
    PROCESS_INFORMATION pi;
    if (!ini_changed) return;
    ini_changed = 0;
    GetModuleFileNameA(NULL, exe, sizeof exe);
    _snprintf(cmd, sizeof cmd, "\"%s\" restore --wait-pid %lu", exe, GetCurrentProcessId());
    if (CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW | DETACHED_PROCESS, NULL, NULL, &si, &pi)) {
        CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    } else emit_error("settings_restore", "CyberView settings restore could not start; run cvbridge restore", -1);
}

static int run_restore(DWORD wait_pid) {
    if (wait_pid) {
        HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, wait_pid);
        if (h) { WaitForSingleObject(h, 60000); CloseHandle(h); }
    }
    if (!ini_locate()) return 1;
    ini_recover_stale();
    printf("{\"event\":\"done\"}\n"); fflush(stdout);
    return 1;
}

/* ---------- session ---------- */

/* A killed service does not always close our stdin pipe, so serve mode also watches
 * the process that started it and closes the driver properly once it has gone. */
static HANDLE parent_process;

static void watch_parent(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 pe = { sizeof pe };
    if (snap == INVALID_HANDLE_VALUE) return;
    for (BOOL ok = Process32First(snap, &pe); ok; ok = Process32Next(snap, &pe))
        if (pe.th32ProcessID == GetCurrentProcessId()) {
            parent_process = OpenProcess(SYNCHRONIZE, FALSE, pe.th32ParentProcessID);
            break;
        }
    CloseHandle(snap);
}

static int parent_gone(void) {
    return parent_process && WaitForSingleObject(parent_process, 0) == WAIT_OBJECT_0;
}

static int loader_running(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 pe = { sizeof pe };
    int found = 0;
    if (snap == INVALID_HANDLE_VALUE) return 0;
    for (BOOL ok = Process32First(snap, &pe); ok; ok = Process32Next(snap, &pe))
        if (!_stricmp(pe.szExeFile, "PfsLoader.exe")) { found = 1; break; }
    CloseHandle(snap);
    return found;
}

static int open_dsm(void) {
    HMODULE lib = LoadLibraryA("twain_32.dll");
    if (!lib || !(dsm = (DSMENTRYPROC)GetProcAddress(lib, "DSM_Entry"))) {
        emit_error("dsm_missing", "twain_32.dll or DSM_Entry not found", -1); return 0;
    }
    app.Version.MajorNum = 1; app.Version.Language = 13; app.Version.Country = 1;
    strcpy(app.Version.Info, "FRAME cvbridge 1.0");
    app.ProtocolMajor = 1; app.ProtocolMinor = 9; app.SupportedGroups = DG_CONTROL | DG_IMAGE;
    strcpy(app.Manufacturer, "FRAME"); strcpy(app.ProductFamily, "FRAME"); strcpy(app.ProductName, "cvbridge");
    if (call_dsm(NULL, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, &hwnd) != TWRC_SUCCESS) {
        emit_error("dsm_open", "TWAIN source manager did not open", -1); return 0;
    }
    dsm_open = 1;
    return 1;
}

static int find_source(const char *want) {
    TW_IDENTITY id;
    memset(&id, 0, sizeof id);
    WORD rc = call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, &id);
    while (rc == TWRC_SUCCESS) {
        if (want ? !_stricmp(id.ProductName, want) : (strstr(id.ProductName, "CyberView") != NULL)) { src = id; return 1; }
        memset(&id, 0, sizeof id);
        rc = call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, &id);
    }
    emit_error("source_missing", want ? want : "No CyberView TWAIN source is installed", -1);
    return 0;
}

static int open_source(void) {
    if (call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, &src) != TWRC_SUCCESS) {
        emit_error("source_open", "The CyberView data source did not open", condition_code(NULL)); return 0;
    }
    ds_open = 1;
    printf("{\"event\":\"opened\",\"source\":"); json_str(stdout, src.ProductName); printf("}\n"); fflush(stdout);
    return 1;
}

static void shutdown_all(void) {
    if (ds_enabled) {
        TW_PENDINGXFERS pend = {0};
        call_dsm(&src, DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, &pend);
        TW_USERINTERFACE ui = { 0, 0, hwnd };
        call_dsm(&src, DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, &ui);
        ds_enabled = 0;
    }
    if (ds_open) { call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_CLOSEDS, &src); ds_open = 0; }
    if (dsm_open) { call_dsm(NULL, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, &hwnd); dsm_open = 0; }
    ini_restore();
}

static BOOL WINAPI on_console(DWORD type) { (void)type; InterlockedExchange(&cancel_requested, 1); return TRUE; }

/* stdin lines other than "cancel" go to the main thread as WM_STDIN_LINE with a heap copy. */
#define WM_STDIN_LINE (WM_APP + 1)
static DWORD stdin_owner;
static int serving;

static DWORD WINAPI stdin_watch(LPVOID unused) {
    char line[MAX_PATH + 64];
    (void)unused;
    while (fgets(line, sizeof line, stdin)) {
        if (!strncmp(line, "cancel", 6)) InterlockedExchange(&cancel_requested, 1);
        else PostThreadMessageA(stdin_owner, WM_STDIN_LINE, 0, (LPARAM)_strdup(line));
    }
    /* A closed pipe means the controlling service has gone; one-shot runs have no stdin. */
    if (serving) PostThreadMessageA(stdin_owner, WM_STDIN_LINE, 0, (LPARAM)_strdup("quit"));
    return 0;
}

/* ---------- TIFF ---------- */

typedef struct { FILE *f; long width, rows, bytes_row; int spp, bps; double dpi; } Tiff;

static void put16(FILE *f, WORD v) { fwrite(&v, 2, 1, f); }
static void put32(FILE *f, DWORD v) { fwrite(&v, 4, 1, f); }
static void tag(FILE *f, WORD id, WORD type, DWORD count, DWORD value) { put16(f, id); put16(f, type); put32(f, count); put32(f, value); }

static int tiff_open(Tiff *t, const char *path) {
    t->f = fopen(path, "wb");
    if (!t->f) return 0;
    fwrite("II*\0\0\0\0\0", 1, 8, t->f); /* IFD offset patched on close */
    return 1;
}

static int tiff_close(Tiff *t) {
    static const char software[] = "FRAME cvbridge via CyberView X TWAIN";
    DWORD data_bytes = (DWORD)(t->rows * t->bytes_row);
    if (data_bytes & 1) { fputc(0, t->f); data_bytes++; }
    DWORD ifd = 8 + data_bytes;
    WORD count = 14;
    DWORD extra = ifd + 2 + count * 12 + 4;
    DWORD bps_at = extra, xres_at = bps_at + 8, yres_at = xres_at + 8, sw_at = yres_at + 8;
    DWORD res = (DWORD)(t->dpi + 0.5);
    put16(t->f, count);
    tag(t->f, 254, 4, 1, 0);
    tag(t->f, 256, 4, 1, (DWORD)t->width);
    tag(t->f, 257, 4, 1, (DWORD)t->rows);
    tag(t->f, 258, 3, t->spp, t->spp == 1 ? (DWORD)t->bps : bps_at);
    tag(t->f, 259, 3, 1, 1);
    tag(t->f, 262, 3, 1, t->spp == 1 ? 1 : 2);
    tag(t->f, 273, 4, 1, 8);
    tag(t->f, 277, 3, 1, (DWORD)t->spp);
    tag(t->f, 278, 4, 1, (DWORD)t->rows);
    tag(t->f, 279, 4, 1, (DWORD)(t->rows * t->bytes_row));
    tag(t->f, 282, 5, 1, xres_at);
    tag(t->f, 283, 5, 1, yres_at);
    tag(t->f, 296, 3, 1, 2);
    tag(t->f, 305, 2, sizeof software, sw_at);
    put32(t->f, 0);
    put16(t->f, (WORD)t->bps); put16(t->f, (WORD)t->bps); put16(t->f, (WORD)t->bps); put16(t->f, 0);
    put32(t->f, res); put32(t->f, 1); put32(t->f, res); put32(t->f, 1);
    fwrite(software, 1, sizeof software, t->f);
    fseek(t->f, 4, SEEK_SET); put32(t->f, ifd);
    int ok = !ferror(t->f);
    return fclose(t->f) == 0 && ok;
}

/* ---------- scan ---------- */

static void numbered(char *out, size_t n, const char *path, int index) {
    const char *dot = strrchr(path, '.');
    const char *slash = strrchr(path, '\\');
    if (!dot || (slash && dot < slash)) dot = path + strlen(path);
    _snprintf(out, n, "%.*s_%02d%s", (int)(dot - path), path, index, dot);
}

static void tame_driver_windows(void);

/* Transfers one pending image; returns 1 on success, 0 on failure, -1 on cancel. */
static int transfer_one(const char *path) {
    TW_IMAGEINFO info = {0};
    TW_SETUPMEMXFER setup = {0};
    Tiff t = {0};
    if (call_dsm(&src, DG_IMAGE, DAT_IMAGEINFO, MSG_GET, &info) != TWRC_SUCCESS) {
        emit_error("image_info", "The driver did not describe the image", condition_code(&src)); return 0;
    }
    t.width = info.ImageWidth; t.spp = info.SamplesPerPixel; t.bps = info.BitsPerSample[0];
    t.dpi = fix32(info.XResolution);
    if (t.spp < 1 || t.spp > 3 || (t.bps != 8 && t.bps != 16) || t.width <= 0) {
        emit_error("image_format", "Unsupported image format from the driver", -1); return 0;
    }
    t.bytes_row = t.width * t.spp * (t.bps / 8);
    printf("{\"event\":\"image_start\",\"width\":%ld,\"height\":%ld,\"samples\":%d,\"bits\":%d,\"dpi\":%.2f,\"pixel_type\":%d}\n",
           info.ImageWidth, info.ImageLength, t.spp, t.bps, t.dpi, info.PixelType);
    fflush(stdout);
    if (call_dsm(&src, DG_CONTROL, DAT_SETUPMEMXFER, MSG_GET, &setup) != TWRC_SUCCESS) setup.Preferred = 1 << 20;
    DWORD size = setup.Preferred ? setup.Preferred : (setup.MaxBufSize ? setup.MaxBufSize : 1 << 20);
    if (setup.MinBufSize && size < setup.MinBufSize) size = setup.MinBufSize;
    BYTE *buf = (BYTE *)malloc(size);
    if (!buf || !tiff_open(&t, path)) { free(buf); emit_error("write", "Could not create the output file", -1); return 0; }
    DWORD last_report = 0;
    for (;;) {
        TW_IMAGEMEMXFER mx;
        memset(&mx, 0xff, sizeof mx);
        mx.Memory.Flags = TWMF_APPOWNS | TWMF_POINTER; mx.Memory.Length = size; mx.Memory.TheMem = buf;
        if (cancel_requested) { free(buf); fclose(t.f); DeleteFileA(path); return -1; }
        WORD rc = call_dsm(&src, DG_IMAGE, DAT_IMAGEMEMXFER, MSG_GET, &mx);
        if (rc == TWRC_SUCCESS || rc == TWRC_XFERDONE) {
            for (DWORD r = 0; r < mx.Rows; r++) fwrite(buf + r * mx.BytesPerRow, 1, (size_t)t.bytes_row, t.f);
            t.rows += mx.Rows;
            if (GetTickCount() - last_report > 250 || rc == TWRC_XFERDONE) {
                tame_driver_windows();
                printf("{\"event\":\"progress\",\"rows\":%ld,\"height\":%ld}\n", t.rows, info.ImageLength); fflush(stdout);
                last_report = GetTickCount();
            }
            if (rc == TWRC_XFERDONE) break;
        } else if (rc == TWRC_CANCEL) {
            free(buf); fclose(t.f); DeleteFileA(path); return -1;
        } else {
            int cc = condition_code(&src);
            free(buf); fclose(t.f); DeleteFileA(path);
            emit_error("transfer", "The driver stopped during image transfer", cc); return 0;
        }
    }
    free(buf);
    if (!tiff_close(&t)) { emit_error("write", "Could not finish the output file", -1); return 0; }
    printf("{\"event\":\"image\",\"path\":"); json_str(stdout, path);
    printf(",\"width\":%ld,\"height\":%ld,\"samples\":%d,\"bits\":%d,\"dpi\":%.2f}\n", t.width, t.rows, t.spp, t.bps, t.dpi);
    fflush(stdout);
    return 1;
}

static int get_bool(WORD capid) {
    TW_CAPABILITY cap = { capid, 0, NULL };
    int value = -1;
    if (call_dsm(&src, DG_CONTROL, DAT_CAPABILITY, MSG_GETCURRENT, &cap) == TWRC_SUCCESS && cap.hContainer) {
        TW_ONEVALUE *one = (TW_ONEVALUE *)GlobalLock(cap.hContainer);
        if (cap.ConType == TWON_ONEVALUE) value = (WORD)one->Item;
        GlobalUnlock(cap.hContainer); GlobalFree(cap.hContainer);
    }
    return value;
}

/* Session-wide negotiation, done once after MSG_OPENDS (state 4). */
static void setup_caps(int dpi, int depth, const double *area) {
    printf("{\"event\":\"feeder\",\"enabled\":%d,\"loaded\":%d}\n", get_bool(CAP_FEEDERENABLED), get_bool(CAP_FEEDERLOADED));
    fflush(stdout);
    set_one(CAP_INDICATORS, TWTY_BOOL, 0);
    report_set("xfermech", set_one(ICAP_XFERMECH, TWTY_UINT16, TWSX_MEMORY));
    report_set("units", set_one(ICAP_UNITS, TWTY_UINT16, TWUN_INCHES));
    report_set("pixeltype", set_one(ICAP_PIXELTYPE, TWTY_UINT16, TWPT_RGB));
    /* CyberView counts bits per pixel: 24 = 8-bit RGB, 36 = 12-bit RGB (16-bit samples). */
    report_set("bitdepth", set_one(ICAP_BITDEPTH, TWTY_UINT16, (DWORD)(depth == 16 ? 36 : 24)));
    /* Observed: the driver lists only 100 dpi and refuses others; hidden scans arrive at 1800. */
    report_set("xresolution", set_one(ICAP_XRESOLUTION, TWTY_FIX32, fix32_bits(dpi)));
    report_set("yresolution", set_one(ICAP_YRESOLUTION, TWTY_FIX32, fix32_bits(dpi)));
    if (area) {
        TW_IMAGELAYOUT layout = {0};
        layout.Frame.Left = to_fix32(area[0]); layout.Frame.Top = to_fix32(area[1]);
        layout.Frame.Right = to_fix32(area[2]); layout.Frame.Bottom = to_fix32(area[3]);
        layout.DocumentNumber = layout.PageNumber = layout.FrameNumber = (DWORD)-1;
        WORD rc = call_dsm(&src, DG_IMAGE, DAT_IMAGELAYOUT, MSG_SET, &layout);
        report_set("layout", rc == TWRC_SUCCESS || rc == TWRC_CHECKSTATUS);
    }
}

static int quit_requested;

/* In hidden mode CyberView still minimizes its main window to the taskbar and shows a
 * progress dialog. Both are hidden here; the dialog's text is passed on as status so
 * the host can show what the driver is doing. Any other dialog is reported and left
 * visible, so a question from the driver is never hidden from the user. */
typedef struct { char text[160]; int progress, other_controls, buttons; } DialogInfo;
static char last_status[160];
static HWND reported[32];
static int reported_count;

static BOOL CALLBACK read_child(HWND child, LPARAM param) {
    DialogInfo *info = (DialogInfo *)param;
    char cls[32], text[160];
    GetClassNameA(child, cls, sizeof cls);
    if (!_stricmp(cls, "msctls_progress32")) info->progress = 1;
    else if (!_stricmp(cls, "Button")) info->buttons++;
    else if (_stricmp(cls, "Static")) info->other_controls++;
    if (!_stricmp(cls, "Static") && !info->text[0] && IsWindowVisible(child) && GetWindowTextA(child, text, sizeof text) > 3)
        strcpy(info->text, text);
    return TRUE;
}

static BOOL CALLBACK tame_window(HWND w, LPARAM unused) {
    DWORD pid = 0;
    char cls[64];
    (void)unused;
    GetWindowThreadProcessId(w, &pid);
    if (pid != GetCurrentProcessId() || w == hwnd) return TRUE;
    GetClassNameA(w, cls, sizeof cls);
    DialogInfo info = { "", 0, 0, 0 };
    EnumChildWindows(w, read_child, (LPARAM)&info);
    if (info.progress && info.text[0] && info.text[strlen(info.text) - 1] != ':') {
        /* "Preparing film scanner, please wait...." grows a dot at a time; compare without them. */
        char status[160];
        strcpy(status, info.text);
        for (size_t n = strlen(status); n && (status[n - 1] == '.' || status[n - 1] == ' '); n--) status[n - 1] = 0;
        if (strcmp(status, last_status)) {
            strcpy(last_status, status);
            printf("{\"event\":\"driver_status\",\"text\":"); json_str(stdout, status); printf("}\n"); fflush(stdout);
        }
    }
    if (!IsWindowVisible(w)) return TRUE;
    /* The MFC main frame, its tool panels and progress dialogs are CyberView's own UI. */
    int message_box = !_stricmp(cls, "#32770") && !info.progress && !info.other_controls && info.buttons && info.buttons <= 4;
    if (!message_box) { ShowWindow(w, SW_HIDE); return TRUE; }
    for (int i = 0; i < reported_count; i++) if (reported[i] == w) return TRUE;
    if (reported_count < 32) reported[reported_count++] = w;
    char title[160] = "";
    GetWindowTextA(w, title, sizeof title);
    printf("{\"event\":\"driver_dialog\",\"title\":"); json_str(stdout, title);
    printf(",\"text\":"); json_str(stdout, info.text); printf("}\n"); fflush(stdout);
    return TRUE;
}

static void tame_driver_windows(void) { EnumWindows(tame_window, 0); }

/* CyberView's own menu commands (RT_MENU 5160/5231 in CyberViewX.ds 1.4.0.0). Sending
 * them to its hidden main window runs the vendor's film transport code unchanged. */
static const struct { const char *name; WPARAM id; } menu_commands[] = {
    { "next", 32867 },          /* Forward One Frame */
    { "step_forward", 32863 },  /* Forward One Step: SCAN08 selector 10 {2, 1}, one motor step */
    { "step_back", 32862 },     /* Backward One Step: selector 10 {1, 1}; untested (Backward One Frame hung) */
};

static BOOL CALLBACK find_frame(HWND w, LPARAM out) {
    DWORD pid = 0;
    char cls[64];
    GetWindowThreadProcessId(w, &pid);
    GetClassNameA(w, cls, sizeof cls);
    if (pid == GetCurrentProcessId() && !strncmp(cls, "Afx:", 4) && GetMenu(w)) { *(HWND *)out = w; return FALSE; }
    return TRUE;
}

/* Runs a menu command ``repeat`` times; a step command moves one motor step each time. */
static void run_menu_command(const char *name, int repeat) {
    HWND frame = NULL;
    for (size_t i = 0; i < sizeof menu_commands / sizeof *menu_commands; i++) {
        if (strcmp(name, menu_commands[i].name)) continue;
        EnumWindows(find_frame, (LPARAM)&frame);
        if (!frame) { emit_error("no_window", "CyberView's main window is not available", -1); return; }
        printf("{\"event\":\"command\",\"name\":"); json_str(stdout, name); printf(",\"repeat\":%d}\n", repeat); fflush(stdout);
        /* Same thread as the driver's windows, so each runs to completion before returning. */
        for (int n = 0; n < repeat; n++) { SendMessageA(frame, WM_COMMAND, menu_commands[i].id, 0); tame_driver_windows(); }
        printf("{\"event\":\"command_done\",\"name\":"); json_str(stdout, name); printf("}\n"); fflush(stdout);
        return;
    }
    emit_error("usage", "Unknown film command", -1);
}

static void disable_source(void) {
    if (!ds_enabled) return;
    TW_PENDINGXFERS pend = {0};
    call_dsm(&src, DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, &pend);
    TW_USERINTERFACE ui = { 0, 0, hwnd };
    call_dsm(&src, DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, &ui);
    ds_enabled = 0;
}

/* Keeps the driver's windows and timers running without starting anything new. */
static void pump(DWORD ms) {
    DWORD until = GetTickCount() + ms;
    MSG msg;
    while ((int)(GetTickCount() - until) < 0) {
        MsgWaitForMultipleObjects(0, NULL, FALSE, 50, QS_ALLINPUT);
        tame_driver_windows();
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_STDIN_LINE) { free((void *)msg.lParam); continue; }
            TranslateMessage(&msg); DispatchMessageA(&msg);
        }
    }
}

/* One acquisition: enable hidden, transfer every pending image, disable. 1 ok, 0 failed, -1 cancelled. */
#include "../native_bridge/usbwatch.h"
#include "../native_bridge/vendorfix.h"

static int one_scan(const char *out, int count, int show_ui, int timeout_s) {
    report_set("autofeed", set_one(CAP_AUTOFEED, TWTY_BOOL, count > 1));
    report_set("xfercount", set_one(CAP_XFERCOUNT, TWTY_INT16, (DWORD)(WORD)(short)(count > 1 ? count : 1)));
    cancel_requested = 0;
    if (watch_on) {
        EnterCriticalSection(&watch_lock);
        live_new_pass(); watch_progress(); InterlockedExchange(&watch_stuck, 0);
        LeaveCriticalSection(&watch_lock);
    }
    TW_USERINTERFACE ui = { (WORD)(show_ui ? 1 : 0), 0, hwnd };
    WORD rc = call_dsm(&src, DG_CONTROL, DAT_USERINTERFACE, MSG_ENABLEDS, &ui);
    if (rc != TWRC_SUCCESS && rc != TWRC_CHECKSTATUS) {
        emit_error("enable", "The driver refused to start", condition_code(&src)); return 0;
    }
    ds_enabled = 1;
    printf("{\"event\":\"enabled\",\"show_ui\":%s}\n", show_ui ? "true" : "false"); fflush(stdout);

    int images = 0, result = 1;
    DWORD deadline = GetTickCount() + (DWORD)timeout_s * 1000u;
    UINT_PTR timer = SetTimer(NULL, 0, 200, NULL);
    MSG msg;
    while (ds_enabled) {
        if (!GetMessageA(&msg, NULL, 0, 0)) { quit_requested = 1; break; }
        if (msg.message == WM_TIMER) {
            tame_driver_windows();
            live_flush();
            if (serving && parent_gone()) { quit_requested = 1; cancel_requested = 1; }
            if (watch_stuck && !cancel_requested) {
                emit_error("position_sensor", "The scanner could not find its film position. Turn the scanner off and on, "
                           "take the film out and put it back in, then scan again.", -1);
                result = 0; break;
            }
        }
        if (msg.message == WM_STDIN_LINE) {
            if (!strncmp((char *)msg.lParam, "quit", 4)) { quit_requested = 1; cancel_requested = 1; }
            free((void *)msg.lParam);
            continue;
        }
        if (cancel_requested || (timeout_s > 0 && (int)(GetTickCount() - deadline) > 0)) {
            if (!cancel_requested) { emit_error("timeout", "The driver did not deliver an image in time", -1); result = 0; }
            else { printf("{\"event\":\"cancelled\"}\n"); fflush(stdout); result = -1; }
            break;
        }
        TW_EVENT ev = { &msg, 0 };
        rc = call_dsm(&src, DG_CONTROL, DAT_EVENT, MSG_PROCESSEVENT, &ev);
        if (rc == TWRC_NOTDSEVENT) { TranslateMessage(&msg); DispatchMessageA(&msg); }
        if (ev.TWMessage == MSG_XFERREADY) {
            TW_PENDINGXFERS pend = {0};
            do {
                char path[MAX_PATH];
                if (images == 0) _snprintf(path, sizeof path, "%s", out); else numbered(path, sizeof path, out, images + 1);
                int r = transfer_one(path);
                if (r <= 0) { result = r; break; }
                images++;
                memset(&pend, 0, sizeof pend);
                call_dsm(&src, DG_CONTROL, DAT_PENDINGXFERS, MSG_ENDXFER, &pend);
                deadline = GetTickCount() + (DWORD)timeout_s * 1000u;
            } while (pend.Count != 0 && !cancel_requested);
            if (result <= 0 || pend.Count == 0) break;
        } else if (ev.TWMessage == MSG_CLOSEDSREQ || ev.TWMessage == MSG_CLOSEDSOK) {
            printf("{\"event\":\"closed_by_driver\"}\n"); fflush(stdout);
            if (images == 0) result = -1;
            break;
        } else if (ev.TWMessage == MSG_DEVICEEVENT) {
            printf("{\"event\":\"device_event\"}\n"); fflush(stdout);
        }
    }
    KillTimer(NULL, timer);
    disable_source();
    printf("{\"event\":\"scan_done\",\"images\":%d,\"result\":%d}\n", images, result); fflush(stdout);
    return result;
}

static int run_scan(const char *out, int dpi, int depth, const double *area, int show_ui, int timeout_s,
                    int count, int settle_ms) {
    if (!open_source()) return 0;
    setup_caps(dpi, depth, area);
    int result = one_scan(out, count, show_ui, timeout_s);
    pump((DWORD)settle_ms);
    printf("{\"event\":\"done\",\"result\":%d}\n", result); fflush(stdout);
    return result > 0;
}

/* Keeps one driver session open, as CyberView does, and scans on request.
 * stdin: "scan COUNT PATH", "cancel" (during a scan) or "quit". */
static int run_serve(int dpi, int depth, const double *area, int timeout_s, int settle_ms) {
    if (!open_source()) return 0;
    tame_driver_windows();
    setup_caps(dpi, depth, area);
    printf("{\"event\":\"ready\"}\n"); fflush(stdout);
    MSG msg;
    UINT_PTR idle_timer = SetTimer(NULL, 0, 500, NULL);
    while (!quit_requested && GetMessageA(&msg, NULL, 0, 0)) {
        if (msg.message == WM_TIMER) {
            tame_driver_windows();
            if (parent_gone()) { quit_requested = 1; break; }
        }
        if (msg.message != WM_STDIN_LINE) { TranslateMessage(&msg); DispatchMessageA(&msg); continue; }
        char *line = (char *)msg.lParam;
        int count = 0, used = 0;
        if (!strncmp(line, "quit", 4)) quit_requested = 1;
        else if (sscanf(line, "scan %d %n", &count, &used) == 1 && used > 0 && count >= 1 && count <= 72) {
            char path[MAX_PATH];
            _snprintf(path, sizeof path, "%s", line + used);
            path[strcspn(path, "\r\n")] = 0;
            if (path[0]) one_scan(path, count, 0, timeout_s);
            else emit_error("usage", "scan COUNT PATH", -1);
            if (!quit_requested) { printf("{\"event\":\"ready\"}\n"); fflush(stdout); }
        } else if (!strncmp(line, "film ", 5)) {
            char name[32] = "", direction[16] = "";
            int steps = 0;
            if (sscanf(line + 5, "step %15s %d", direction, &steps) == 2) {
                if (steps < 1 || steps > 300 || (strcmp(direction, "forward") && strcmp(direction, "back")))
                    emit_error("usage", "film step forward|back STEPS (1-300)", -1);
                else run_menu_command(strcmp(direction, "back") ? "step_forward" : "step_back", steps);
            } else {
                sscanf(line + 5, "%31s", name);
                run_menu_command(name, 1);
            }
            printf("{\"event\":\"ready\"}\n"); fflush(stdout);
        } else emit_error("usage", "Commands: scan COUNT PATH, film next, film step forward|back N, cancel, quit", -1);
        free(line);
    }
    KillTimer(NULL, idle_timer);
    pump((DWORD)settle_ms);
    printf("{\"event\":\"done\",\"result\":1}\n"); fflush(stdout);
    return 1;
}

static int run_caps(void) {
    if (!open_source()) return 0;
    TW_CAPABILITY sup = { CAP_SUPPORTEDCAPS, 0, NULL };
    WORD ids[256]; int n = 0;
    if (call_dsm(&src, DG_CONTROL, DAT_CAPABILITY, MSG_GET, &sup) == TWRC_SUCCESS && sup.hContainer) {
        BYTE *p = (BYTE *)GlobalLock(sup.hContainer);
        if (sup.ConType == TWON_ARRAY) {
            TW_ARRAY *a = (TW_ARRAY *)p;
            for (DWORD i = 0; i < a->NumItems && n < 256; i++) ids[n++] = ((WORD *)a->ItemList)[i];
        }
        GlobalUnlock(sup.hContainer); GlobalFree(sup.hContainer);
    }
    printf("{\"event\":\"supported\",\"count\":%d}\n", n);
    for (int i = 0; i < n; i++) {
        TW_CAPABILITY cap = { ids[i], 0, NULL };
        WORD rc = call_dsm(&src, DG_CONTROL, DAT_CAPABILITY, MSG_GET, &cap);
        printf("{\"event\":\"cap\",\"id\":%u,\"hex\":\"0x%04x\",\"value\":", ids[i], ids[i]);
        if (rc == TWRC_SUCCESS && cap.hContainer) print_container(&cap); else printf("null");
        printf("}\n");
    }
    TW_IMAGELAYOUT layout = {0};
    if (call_dsm(&src, DG_IMAGE, DAT_IMAGELAYOUT, MSG_GET, &layout) == TWRC_SUCCESS)
        printf("{\"event\":\"layout\",\"frame\":[%.4f,%.4f,%.4f,%.4f]}\n", fix32(layout.Frame.Left), fix32(layout.Frame.Top),
               fix32(layout.Frame.Right), fix32(layout.Frame.Bottom));
    fflush(stdout);
    return 1;
}

static int run_sources(void) {
    TW_IDENTITY id;
    memset(&id, 0, sizeof id);
    WORD rc = call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, &id);
    while (rc == TWRC_SUCCESS) {
        printf("{\"event\":\"source\",\"name\":"); json_str(stdout, id.ProductName);
        printf(",\"manufacturer\":"); json_str(stdout, id.Manufacturer);
        printf(",\"family\":"); json_str(stdout, id.ProductFamily);
        printf(",\"version\":"); json_str(stdout, id.Version.Info);
        printf(",\"protocol\":\"%u.%u\"}\n", id.ProtocolMajor, id.ProtocolMinor);
        memset(&id, 0, sizeof id);
        rc = call_dsm(NULL, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, &id);
    }
    fflush(stdout);
    return 1;
}

static int parse_area(const char *s, double *a) {
    return sscanf(s, "%lf,%lf,%lf,%lf", &a[0], &a[1], &a[2], &a[3]) == 4 && a[2] > a[0] && a[3] > a[1] && a[0] >= 0 && a[1] >= 0;
}

/* All scanner traffic leaves through FVC.dll (SCAN08 -> SQ_Scan -> IO_PORT -> fvc).
 * Loading it first means the driver's own load reuses this hooked copy. The watch
 * (live preview, stuck detection) is optional: without a trace file a failure to
 * hook is reported and scanning goes on unwatched. */
static int start_watch(const char *trace_path) {
    char fvc[MAX_PATH], ioport[MAX_PATH];
    const char *traced[] = {"fvc.dll", NULL};
    UINT n = GetSystemDirectoryA(fvc, MAX_PATH);
    if (!n || n > MAX_PATH - 14) { emit_error("watch", "The system folder could not be found", -1); return !trace_path; }
    strcpy_s(ioport, sizeof ioport, fvc);
    strcat_s(fvc, sizeof fvc, "\\fvc.dll");
    strcat_s(ioport, sizeof ioport, "\\IO_PORT.dll");
    if (!LoadLibraryA(fvc)) {
        emit_error(trace_path ? "trace" : "watch", "The vendor FVC.dll could not be loaded for the USB watch", -1);
        return !trace_path;
    }
    /* IO_PORT too, so its uninitialised close write can be fixed before CyberView loads it. */
    if (LoadLibraryA(ioport)) {
        printf("{\"event\":\"vendorfix\",\"close_write_zeroed\":%s}\n", vendorfix_install() ? "true" : "false"); fflush(stdout);
    }
    InitializeCriticalSection(&watch_lock);
    trace_on_register = watch_register; trace_on_status = watch_status; trace_on_bulk_in = watch_bulk_in;
    int slots = usbtrace_install(trace_path, traced);
    if (slots <= 0) {
        emit_error(trace_path ? "trace" : "watch", "The USB watch could not start", -1);
        return !trace_path;
    }
    watch_on = 1;
    printf("{\"event\":\"%s\",\"slots\":%d}\n", trace_path ? "trace" : "watch", slots); fflush(stdout);
    return 1;
}

int main(int argc, char **argv) {
    const char *cmd = argc > 1 ? argv[1] : "", *source = NULL, *out = NULL, *trace = NULL;
    int dpi = 300, depth = 8, show_ui = 0, timeout_s = 600, hidden_caps = 0, watch = 1;
    DWORD wait_pid = 0;
    int count = 1, settle_ms = 8000;
    double area[4]; int has_area = 0;
    for (int i = 2; i < argc; i++) {
        const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(a, "--source") && v) { source = v; i++; }
        else if (!strcmp(a, "--out") && v) { out = v; i++; }
        else if (!strcmp(a, "--dpi") && v) { dpi = atoi(v); i++; }
        else if (!strcmp(a, "--depth") && v) { depth = atoi(v); i++; }
        else if (!strcmp(a, "--timeout") && v) { timeout_s = atoi(v); i++; }
        else if (!strcmp(a, "--area") && v) { if (!parse_area(v, area)) { emit_error("usage", "Bad --area", -1); return 2; } has_area = 1; i++; }
        else if (!strcmp(a, "--show-ui")) show_ui = 1;
        else if (!strcmp(a, "--hidden")) hidden_caps = 1;
        else if (!strcmp(a, "--wait-pid") && v) { wait_pid = (DWORD)strtoul(v, NULL, 10); i++; }
        else if (!strcmp(a, "--set") && v && override_count < 32) { overrides[override_count++] = v; i++; }
        else if (!strcmp(a, "--count") && v) { count = atoi(v); i++; }
        else if (!strcmp(a, "--settle") && v) { settle_ms = atoi(v); i++; }
        else if (!strcmp(a, "--trace-usb") && v) { trace = v; i++; }
        else if (!strcmp(a, "--no-usb-watch")) watch = 0;
        else { emit_error("usage", a, -1); return 2; }
    }
    if (!strcmp(cmd, "restore")) return run_restore(wait_pid) ? 0 : 1;
    if (strcmp(cmd, "sources") && strcmp(cmd, "caps") && strcmp(cmd, "scan") && strcmp(cmd, "serve")) {
        emit_error("usage", "cvbridge sources | caps | scan --out PATH | serve | restore", -1); return 2;
    }
    if (!strcmp(cmd, "scan") && (!out || dpi < 50 || dpi > 10000 || (depth != 8 && depth != 16))) {
        emit_error("usage", "scan needs --out, a valid --dpi and --depth 8 or 16", -1); return 2;
    }
    /* Both bridges own the same physical scanner. Do not let an experimental
     * native session race the proven TWAIN session in a different process. */
    HANDLE device_mutex = CreateMutexA(NULL, TRUE, "Local\\FRAME_PF1800AFL");
    if (!device_mutex || GetLastError() == ERROR_ALREADY_EXISTS) {
        if (device_mutex) CloseHandle(device_mutex);
        emit_error("busy", "Another scanner session is already open. Release it before starting this bridge.", -1);
        return 3;
    }
    if (strcmp(cmd, "sources") && loader_running()) {
        emit_error("busy", "CyberView is open. Close it so only one program uses the scanner.", -1); return 3;
    }
    SetConsoleCtrlHandler(on_console, TRUE);
    hwnd = CreateWindowA("STATIC", "cvbridge", WS_POPUP, 0, 0, 0, 0, NULL, NULL, GetModuleHandleA(NULL), NULL);
    /* The driver reads and rewrites its settings as soon as the source manager loads
     * it, so the backup and the hidden keys must come before open_dsm. */
    int hide = (!strcmp(cmd, "scan") && !show_ui) || !strcmp(cmd, "serve") || (!strcmp(cmd, "caps") && hidden_caps);
    if (strcmp(cmd, "sources") && (hide || override_count)) {
        if (!ini_locate()) { emit_error("ini_missing", "CyberView settings were not found; run CyberView once first", -1); return 1; }
        if (!ini_enter_hidden(hide)) { emit_error("settings_backup", "Could not back up CyberView settings", -1); return 1; }
    }
    /* The message queue exists once the window does, so the stdin thread can post to it. */
    stdin_owner = GetCurrentThreadId();
    serving = !strcmp(cmd, "serve");
    if (serving) watch_parent();
    CreateThread(NULL, 0, stdin_watch, NULL, 0, NULL);
    int scanning_command = !strcmp(cmd, "scan") || !strcmp(cmd, "serve");
    if ((trace || (watch && scanning_command)) && !start_watch(trace)) { shutdown_all(); return 1; }
    if (!open_dsm()) { shutdown_all(); return 1; }
    int ok;
    if (!strcmp(cmd, "sources")) ok = run_sources();
    else if (!find_source(source)) ok = 0;
    else if (!strcmp(cmd, "caps")) ok = run_caps();
    else if (!strcmp(cmd, "serve")) ok = run_serve(dpi, depth, has_area ? area : NULL, timeout_s, settle_ms);
    else ok = run_scan(out, dpi, depth, has_area ? area : NULL, show_ui, timeout_s, count, settle_ms);
    shutdown_all();
    return ok ? 0 : 1;
}
