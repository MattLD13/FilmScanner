/* CPU-only stand-in for FVC.dll's kernel32 calls, used to test usbtrace.h. Every
 * call goes to the NUL device; nothing reaches USB. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
typedef struct { DWORD offset, length; BYTE *data; DWORD index; } IoBlock;
__declspec(dllexport) int __cdecl FVCProbe(void) {
    BYTE write[2] = {0x8d, 0x41}, read[4] = {0}, reg = 0; IoBlock block = {0xb0, 2, write, 0}; DWORD done = 0;
    HANDLE h = CreateFileA("NUL", GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return 0;
    DeviceIoControl(h, 0x80002010, &block, sizeof block, NULL, 0, &done, NULL);  /* NUL rejects it; logged anyway */
    block.offset = 7; block.length = 1; block.data = &reg;
    DeviceIoControl(h, 0x8000200C, &block, sizeof block, &reg, 1, &done, NULL);
    WriteFile(h, write, sizeof write, &done, NULL);
    ReadFile(h, read, sizeof read, &done, NULL);
    return CloseHandle(h);
}
