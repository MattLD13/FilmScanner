/* autocolor: run CyberView's own automatic colour on an image, without the scanner.
 *
 *   autocolor RAW WIDTH HEIGHT [PRESET [CLIP_LOW CLIP_HIGH]]
 *
 * RAW is 8-bit interleaved RGB, WIDTH x HEIGHT. CyberViewX.ds (1.4.0.0) exports
 * iComputeAutoColor and the image class CIP_RawImg it reads. CyberView calls it from
 * 0x101129c0 on its prescan as iComputeAutoColor(img, 2, {0,0,w,h}, 0.05f, 0.05f, out)
 * and turns the 18 result words into its Auto Exposure / Auto Gamma curves
 * (docs/auto-color-re.md). This program does the same call and prints the words as
 * one JSON line: {"result":0,"words":[...18]}.
 *
 * Loading the DS sends no TWAIN message, so the scanner is not touched. The DS may
 * rewrite CyberView's settings when it loads or unloads, so the per-user
 * CyberViewX.ini is backed up first, restored before exit, and the process ends
 * without running the DS's unload code.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { LONG left, top, right, bottom; } Rect;
typedef int (__cdecl *ComputeAutoColor)(void *image, int preset, Rect rect, float clip_low, float clip_high, WORD *out);
typedef void (__fastcall *Constructor)(void *self, void *unused); /* thiscall, no arguments */

static char ini[MAX_PATH], backup[MAX_PATH];

static void finish(int code) {
    fflush(stdout);
    if (backup[0]) { CopyFileA(backup, ini, FALSE); DeleteFileA(backup); }
    TerminateProcess(GetCurrentProcess(), (UINT)code); /* skip the DS's unload code */
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: autocolor RAW WIDTH HEIGHT [PRESET [CLIP_LOW CLIP_HIGH]]\n"); return 2; }
    int width = atoi(argv[2]), height = atoi(argv[3]), preset = argc > 4 ? atoi(argv[4]) : 2;
    float clip_low = argc > 6 ? (float)atof(argv[5]) : .05f, clip_high = argc > 6 ? (float)atof(argv[6]) : .05f;
    if (width < 1 || height < 1 || width > 20000 || height > 20000 || preset < 1 || preset > 3) {
        printf("{\"error\":\"usage\"}\n"); return 2;
    }
    size_t bytes = (size_t)width * height * 3;
    BYTE *pixels = (BYTE *)malloc(bytes);
    FILE *f = fopen(argv[1], "rb");
    if (!pixels || !f || fread(pixels, 1, bytes, f) != bytes) { printf("{\"error\":\"read\"}\n"); return 1; }
    fclose(f);

    if (SUCCEEDED(SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, ini))) {
        strcat_s(ini, sizeof ini, "\\PIE\\MF\\CyberViewX.ini");
        sprintf_s(backup, sizeof backup, "%s.autocolor-backup", ini);
        if (!CopyFileA(ini, backup, FALSE)) backup[0] = 0;
    }
    char ds[MAX_PATH];
    if (!GetWindowsDirectoryA(ds, MAX_PATH)) finish(1);
    strcat_s(ds, sizeof ds, "\\twain_32\\CyberViewX_MF\\CyberViewX.ds");
    HMODULE module = LoadLibraryExA(ds, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    ComputeAutoColor compute = module ? (ComputeAutoColor)GetProcAddress(module, "iComputeAutoColor") : NULL;
    Constructor construct = module ? (Constructor)GetProcAddress(module, "??0CIP_RawImg@@QAE@XZ") : NULL;
    if (!compute || !construct) { printf("{\"error\":\"module\"}\n"); finish(1); }

    /* CIP_RawImg fields read by iComputeAutoColor (as iLoadRAWImg 0x10123d70 sets them). */
    BYTE *image = (BYTE *)calloc(1, 0x400);
    construct(image, NULL);
    *(BYTE **)(image + 0x08) = pixels;
    *(int *)(image + 0x24) = 8;      /* bits per sample */
    *(int *)(image + 0x28) = 3;      /* samples per pixel */
    *(int *)(image + 0x2c) = height;
    *(int *)(image + 0x30) = width;
    *(int *)(image + 0x34) = 1;
    WORD out[18] = {0};
    Rect rect = {0, 0, width, height};
    int result = compute(image, preset, rect, clip_low, clip_high, out);
    printf("{\"result\":%d,\"preset\":%d,\"words\":[", result, preset);
    for (int i = 0; i < 18; i++) printf("%s%u", i ? "," : "", out[i]);
    printf("]}\n");
    finish(result == 0 ? 0 : 1);
    return 0;
}
