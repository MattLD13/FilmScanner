/* CPU-only colour oracle for the pinned CyberViewX.ds 1.4.0.0.
 *
 * vendorcolour film INPUT.raw WIDTH HEIGHT BITS PROFILE.ft OUTPUT.raw
 *
 * Calls only CFilmCIP construction, file parsing, mode5 and Run on caller-owned
 * RGB buffers. No TWAIN message or ScannerDeviceIO entry point is used. Output
 * is created exclusively, never overwriting an acquisition. All RVA calls require
 * the exact SHA-256 below. Settings are backed up/restored and DS unload is skipped.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *(__fastcall *Construct)(void *, void *, int, int);
typedef unsigned char (__fastcall *LoadFilm)(void *, void *, int, const char *, int);
typedef unsigned char (__fastcall *Configure)(void *, void *, int);
typedef unsigned char (__fastcall *RunFilm)(void *, void *, void *, int, int, int, int, DWORD);
typedef void *(__fastcall *ConstructNoArgs)(void *, void *);
typedef unsigned char (__fastcall *LoadGeneric)(void *, void *, const char *);
typedef void (__fastcall *CopyGeneric)(void *, void *, float *, int);
typedef unsigned char (__cdecl *BuildCurve)(const LONG *, int, WORD *, unsigned int);
typedef unsigned char (__fastcall *AutoTables)(void *, void *, const void *, int, int, int, int, WORD *, WORD *, WORD *, int);
typedef unsigned char (__fastcall *SetTables)(void *, void *, int, WORD *, WORD *, WORD *, int);

static const BYTE expected_sha[32] = {
    0xbf,0xe1,0xba,0xc8,0x74,0x43,0x20,0xa4,0x1d,0x23,0xee,0x7b,0x51,0xb2,0x1b,0x4e,
    0x0e,0x31,0x00,0x4e,0xea,0x4a,0x7a,0x49,0xa6,0x8b,0x32,0xb5,0x22,0xfd,0x28,0xbb};
static char settings[MAX_PATH], backup[MAX_PATH];
static HANDLE mutex;
static int settings_checked, settings_existed;

static void finish(int code) {
    fflush(stdout);
    if (backup[0]) {
        if (!CopyFileA(backup, settings, FALSE)) code = 90;
        else DeleteFileA(backup);
    } else if (settings_checked && !settings_existed && settings[0]) {
        /* DllMain may create a default INI even in a CPU-only worker. Restore
         * absence as well as existing contents; never remove a preexisting INI. */
        if (!DeleteFileA(settings) && GetLastError() != ERROR_FILE_NOT_FOUND &&
            GetLastError() != ERROR_PATH_NOT_FOUND) code = 90;
    }
    if (mutex) { ReleaseMutex(mutex); CloseHandle(mutex); }
    TerminateProcess(GetCurrentProcess(), (UINT)code);
}

static int error(const char *message, int code) {
    printf("{\"error\":\"%s\"}\n", message);
    finish(code); return code;
}

static int recognized(const char *path) {
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    BYTE output[32], block[32768];
    DWORD length; int ok = 0;
    HANDLE file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0) goto done;
    if (BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0) goto done;
    while (ReadFile(file, block, sizeof block, &length, NULL) && length)
        if (BCryptHashData(hash, block, length, 0) < 0) goto done;
    if (BCryptFinishHash(hash, output, sizeof output, 0) < 0) goto done;
    ok = memcmp(output, expected_sha, 32) == 0;
done:
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file); return ok;
}

static int vendor_running(void) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 entry = {sizeof entry};
    if (snapshot == INVALID_HANDLE_VALUE) return 1;
    if (Process32First(snapshot, &entry)) do {
        if (_stricmp(entry.szExeFile, "PfsLoader.exe") == 0) { CloseHandle(snapshot); return 1; }
    } while (Process32Next(snapshot, &entry));
    CloseHandle(snapshot); return 0;
}

int main(int argc, char **argv) {
    int generic = argc == 4 && strcmp(argv[1], "generic") == 0;
    int curve = argc == 5 && strcmp(argv[1], "curve") == 0;
    int film = argc == 8 && strcmp(argv[1], "film") == 0;
    int auto_tables = argc == 8 && strcmp(argv[1], "autotables") == 0;
    int auto_apply = argc == 8 && strcmp(argv[1], "autoapply") == 0;
    if (!generic && !curve && !film && !auto_tables && !auto_apply) {
        fprintf(stderr, "usage: vendorcolour film INPUT.raw WIDTH HEIGHT BITS PROFILE.ft OUTPUT.raw\n"
                        "       vendorcolour generic PROFILE.GG OUTPUT.raw\n"
                        "       vendorcolour curve POINTS.txt LENGTH OUTPUT.raw\n"
                        "       vendorcolour autotables INPUT.raw WIDTH HEIGHT BITS NEGATIVE OUTPUT.raw\n"
                        "       vendorcolour autoapply INPUT.raw WIDTH HEIGHT BITS TABLES.raw OUTPUT.raw\n"); return 2;
    }
    int image_mode = film || auto_tables || auto_apply;
    int width = image_mode ? atoi(argv[3]) : 1, height = image_mode ? atoi(argv[4]) : 1, bits = image_mode ? atoi(argv[5]) : 16;
    if (width < 1 || height < 1 || width > 20000 || height > 20000 || (bits != 8 && bits != 16)) return error("usage", 2);
    size_t bytes = (size_t)width * height * 3 * (bits / 8);
    if (bytes > 64000000) return error("image_too_large", 2);
    const char *output_path = argv[argc - 1];
    if (GetFileAttributesA(output_path) != INVALID_FILE_ATTRIBUTES) return error("output_exists", 2);
    if (vendor_running()) return error("vendor_app_running", 2);
    BYTE *pixels = (BYTE *)malloc(bytes);
    if (image_mode) {
        FILE *input = fopen(argv[2], "rb");
        if (!pixels || !input || fread(pixels, 1, bytes, input) != bytes || fgetc(input) != EOF) return error("input", 2);
        fclose(input);
    }
    char ds[MAX_PATH];
    if (!GetWindowsDirectoryA(ds, MAX_PATH)) return error("windows_path", 2);
    strcat_s(ds, sizeof ds, "\\twain_32\\CyberViewX_MF\\CyberViewX.ds");
    if (!recognized(ds)) return error("unrecognized_vendor_binary", 2);
    mutex = CreateMutexA(NULL, FALSE, "Local\\FRAMEVendorColourOracle");
    if (!mutex || WaitForSingleObject(mutex, 0) != WAIT_OBJECT_0) return error("oracle_busy", 2);
    if (FAILED(SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, settings))) return error("settings_path", 2);
    strcat_s(settings, sizeof settings, "\\PIE\\MF\\CyberViewX.ini");
    DWORD settings_attributes = GetFileAttributesA(settings);
    if (settings_attributes == INVALID_FILE_ATTRIBUTES && GetLastError() != ERROR_FILE_NOT_FOUND &&
        GetLastError() != ERROR_PATH_NOT_FOUND) return error("settings_access", 2);
    settings_checked = 1;
    settings_existed = settings_attributes != INVALID_FILE_ATTRIBUTES;
    if (settings_existed) {
        sprintf_s(backup, sizeof backup, "%s.colour-%lu-backup", settings, GetCurrentProcessId());
        if (!CopyFileA(settings, backup, TRUE)) { backup[0] = 0; return error("settings_backup", 2); }
    }
    HMODULE module = LoadLibraryExA(ds, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!module) return error("load_vendor_binary", 2);
    BYTE *base = (BYTE *)module;
    if (generic || curve) {
        __try {
            void *buffer = NULL; DWORD output_bytes = 0;
            if (generic) {
                BYTE *reader = (BYTE *)calloc(1, 0xc05c);
                float *table = (float *)calloc(0x3000, sizeof(float));
                ((ConstructNoArgs)(base + 0x691d0))(reader, NULL);
                if (!((LoadGeneric)(base + 0x69340))(reader, NULL, argv[2])) return error("generic_load", 3);
                ((CopyGeneric)(base + 0x168aa0))(reader, NULL, table, 0x3000);
                buffer = table; output_bytes = 0x3000 * sizeof(float);
            } else {
                LONG points[8]; int count = 0;
                unsigned int length = (unsigned int)atoi(argv[3]);
                if (length != 256 && length != 4096 && length != 65536) return error("curve_length", 2);
                FILE *input = fopen(argv[2], "r");
                if (!input) return error("curve_input", 2);
                while (count < 4 && fscanf(input, "%ld %ld", &points[count*2], &points[count*2+1]) == 2) {
                    if (points[count*2] < 0 || points[count*2] > 255 || points[count*2+1] < 0 || points[count*2+1] > 255) return error("curve_point_range", 2);
                    count++;
                }
                if (count == 0) return error("curve_input", 2);
                int c; while ((c = fgetc(input)) != EOF) if (c != ' ' && c != '\r' && c != '\n' && c != '\t') return error("curve_input", 2);
                fclose(input);
                WORD *table = (WORD *)calloc(length, sizeof(WORD));
                if (!((BuildCurve)(base + 0x104360))(points, count, table, length)) return error("curve_build", 3);
                buffer = table; output_bytes = length * sizeof(WORD);
            }
            HANDLE output = CreateFileA(output_path, GENERIC_WRITE, 0, NULL, CREATE_NEW, 0, NULL);
            if (output == INVALID_HANDLE_VALUE) return error("create_output", 3);
            DWORD written = 0;
            int saved = WriteFile(output, buffer, output_bytes, &written, NULL) && written == output_bytes;
            CloseHandle(output);
            if (!saved) return error("write_output", 3);
            printf("{\"result\":1,\"mode\":\"%s\",\"device_io\":false}\n", generic ? "generic" : "curve");
        } __except(EXCEPTION_EXECUTE_HANDLER) { return error("vendor_exception", 4); }
        finish(0);
    }
    BYTE *object = (BYTE *)calloc(1, 0xc0ec);
    if (!object) return error("allocation", 2);
    __try {
        ((Construct)(base + 0x4490))(object, NULL, 1, 0);
        if (auto_tables || auto_apply) {
            WORD tables[3][256] = {0};
            int type = bits == 8 ? 0 : 1;
            if (auto_tables) {
                int negative = atoi(argv[6]);
                if (negative != 0 && negative != 1) return error("negative_flag", 2);
                if (!((AutoTables)(base + 0x103810))(object, NULL, pixels, width, height, type,
                                                    negative, tables[0], tables[1], tables[2], 256)) return error("auto_tables", 3);
            } else {
                FILE *input = fopen(argv[6], "rb");
                if (!input || fread(tables, 1, sizeof tables, input) != sizeof tables || fgetc(input) != EOF) return error("table_input", 2);
                fclose(input);
                for (int c = 0; c < 3; c++) for (int i = 0; i < 256; i++) if (tables[c][i] > 255) return error("table_range", 2);
                if (!((SetTables)(base + 0xff880))(object, NULL, 7, tables[0], tables[1], tables[2], 256)) return error("set_auto_tables", 3);
                if (!((Configure)(base + 0x100e10))(object, NULL, 7)) return error("configure_auto_tables", 3);
                if (!((RunFilm)(base + 0x105490))(object, NULL, pixels, width, height, type, type, (DWORD)bytes)) return error("apply_auto_tables", 3);
            }
            HANDLE output = CreateFileA(output_path, GENERIC_WRITE, 0, NULL, CREATE_NEW, 0, NULL);
            if (output == INVALID_HANDLE_VALUE) return error("create_output", 3);
            DWORD written = 0, count = auto_tables ? sizeof tables : (DWORD)bytes;
            int saved = WriteFile(output, auto_tables ? (void *)tables : (void *)pixels, count, &written, NULL) && written == count;
            CloseHandle(output);
            if (!saved) return error("write_output", 3);
            printf("{\"result\":1,\"mode\":\"%s\",\"device_io\":false}\n", auto_tables ? "autotables" : "autoapply");
            finish(0);
        }
        int loaded = ((LoadFilm)(base + 0x45c0))(object, NULL, 6, argv[6], 1);
        if (!loaded) return error("profile_load", 3);
        int configured = ((Configure)(base + 0x100e10))(object, NULL, 5);
        int type = bits == 8 ? 0 : 1;
        int ran = configured && ((RunFilm)(base + 0x105490))(object, NULL, pixels, width, height, type, type, (DWORD)bytes);
        if (!ran) return error("film_run", 3);
        HANDLE output = CreateFileA(argv[7], GENERIC_WRITE, 0, NULL, CREATE_NEW, 0, NULL);
        if (output == INVALID_HANDLE_VALUE) return error("create_output", 3);
        DWORD written = 0;
        int saved = WriteFile(output, pixels, (DWORD)bytes, &written, NULL) && written == bytes;
        CloseHandle(output);
        if (!saved) return error("write_output", 3);
        printf("{\"result\":1,\"bits\":%d,\"samples\":%zu,\"profile_rows\":%lu,\"device_io\":false}\n",
               bits, bytes / (bits / 8), *(DWORD *)(object + 0x2c));
    } __except(EXCEPTION_EXECUTE_HANDLER) { return error("vendor_exception", 4); }
    finish(0); return 0;
}
