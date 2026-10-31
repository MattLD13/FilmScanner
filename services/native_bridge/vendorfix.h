/* Fix for a PF1800 AFL vendor bug in IO_PORT.dll (SHA-256 768442427b7bbf28...).
 *
 * CloseTransferPort (0x10001310) sends, on the USB transport (0x100013a5), a 2-byte
 * register write whose bytes are an uninitialised stack slot:
 *     lea edx,[esp] ; push edx ; push 2 ; push 0 ; push 0xb0 ; push 2 ; push 0
 *     call [fvc!SystemRequest]          ; return address IO_PORT + 0x13bd
 * The parallel path clears that buffer to zeros first. So every driver close writes a
 * random register, decided by load addresses and stack contents. On 2026-10-31 the copy
 * of the driver in %LOCALAPPDATA% wrote 0x78 = 0x6e: status page 0x0d then read 0xaa
 * and frames came out white; from the CyberView install it wrote 0x86 = 0xd7 and frames
 * were good. The same 0xaa preceded the "Preparing film scanner" hang.
 *
 * vendorfix_install patches IO_PORT's import of fvc!SystemRequest so that, for that one
 * call site only (checked by return address and the instruction bytes), the two bytes are
 * zero, as the parallel path sends. Every other call passes through unchanged.
 */
#ifndef FRAME_VENDORFIX_H
#define FRAME_VENDORFIX_H
#include <windows.h>
#include <intrin.h>
#include <string.h>
#pragma intrinsic(_ReturnAddress)

typedef int (__cdecl *VendorSystemRequest)(int type, int unused, int offset, int index, int length, BYTE *data);
static VendorSystemRequest vendor_real_request;
static UINT_PTR vendor_close_return;
static volatile LONG vendor_close_fixes;

static int __cdecl vendor_fixed_request(int type, int unused, int offset, int index, int length, BYTE *data) {
    if ((UINT_PTR)_ReturnAddress() == vendor_close_return && type == 0 && offset == 0xb0 && length == 2 && data) {
        data[0] = 0; data[1] = 0;
        InterlockedIncrement(&vendor_close_fixes);
    }
    return vendor_real_request(type, unused, offset, index, length, data);
}

/* Returns 1 when the fix is in place, 0 if IO_PORT is absent or not the reviewed build. */
static int vendorfix_install(void) {
    static const BYTE close_site[] = {0x8d, 0x54, 0x24, 0x00, 0x52, 0x6a, 0x02, 0x6a, 0x00, 0x68, 0xb0, 0x00, 0x00, 0x00,
                                      0x6a, 0x02, 0x6a, 0x00, 0xff, 0x15};
    BYTE *base = (BYTE *)GetModuleHandleA("IO_PORT.dll");
    if (!base || vendor_real_request) return vendor_real_request != NULL;
    __try { if (memcmp(base + 0x13a5, close_site, sizeof close_site)) return 0; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }
    IMAGE_NT_HEADERS32 *nt = (IMAGE_NT_HEADERS32 *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); d->Name; d++) {
        if (_stricmp((char *)(base + d->Name), "fvc.dll") || !d->OriginalFirstThunk) continue;
        IMAGE_THUNK_DATA32 *names = (IMAGE_THUNK_DATA32 *)(base + d->OriginalFirstThunk);
        IMAGE_THUNK_DATA32 *slots = (IMAGE_THUNK_DATA32 *)(base + d->FirstThunk);
        for (; names->u1.AddressOfData; names++, slots++) {
            if (IMAGE_SNAP_BY_ORDINAL32(names->u1.Ordinal)) continue;
            if (strcmp((char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name, "SystemRequest")) continue;
            DWORD old;
            if (!VirtualProtect(&slots->u1.Function, sizeof(DWORD), PAGE_READWRITE, &old)) return 0;
            vendor_real_request = (VendorSystemRequest)(UINT_PTR)slots->u1.Function;
            vendor_close_return = (UINT_PTR)(base + 0x13bd);
            slots->u1.Function = (DWORD)(UINT_PTR)vendor_fixed_request;
            VirtualProtect(&slots->u1.Function, sizeof(DWORD), old, &old);
            return 1;
        }
    }
    return 0;
}
#endif
