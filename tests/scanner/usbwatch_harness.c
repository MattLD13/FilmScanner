/* CPU-only driver for services/native_bridge/usbwatch.h: feeds synthetic scan
 * passes and status polls through the watch callbacks and prints what it emits. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
static DWORD fake_now;
#define WATCH_NOW() fake_now
#include "../../services/native_bridge/usbwatch.h"

static BYTE line[2752 * 6];
/* High byte of each sample: constant inside every 8 x 8 block, so averages are exact. */
static void feed(int width, int lines, int first_y) {
    for (int y = first_y; y < first_y + lines; y++) {
        for (int x = 0; x < width; x++)
            for (int c = 0; c < 3; c++) {
                line[(x * 3 + c) * 2] = 0xab;
                line[(x * 3 + c) * 2 + 1] = (BYTE)((x / 8 + y / 8 + c * 50) & 0xff);
            }
        watch_bulk_in(line, (DWORD)width * 6);
    }
}
int main(void) {
    InitializeCriticalSection(&watch_lock); watch_on = 1;
    watch_register(0x90, 1); feed(2752, 62, 0); live_flush();      /* calibration: wide but short */
    watch_register(0x90, 1); feed(224, 300, 0); live_flush();      /* focus strip: narrow */
    watch_register(0x90, 1); feed(2479, 50, 0); live_flush();      /* the frame, too early to show */
    feed(2479, 150, 50); live_flush();                             /* 200 lines: 25 preview rows */
    fake_now = 40000; watch_register(0x80, 0);
    fake_now = 60000; for (int i = 0; i < 600; i++) watch_status(0x6b);
    printf("{\"event\":\"stuck_check\",\"after_ms\":20000,\"stuck\":%ld}\n", watch_stuck);
    fake_now = 71000; for (int i = 0; i < 600; i++) watch_status(0x6b);
    printf("{\"event\":\"stuck_check\",\"after_ms\":31000,\"stuck\":%ld}\n", watch_stuck);
    return 0;
}
