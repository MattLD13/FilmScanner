/* Live preview and stuck detection from the USB watch; included by cvbridge.c.
 * Needs <windows.h> and <stdio.h>. WATCH_NOW can be replaced in tests. */
#ifndef FRAME_USBWATCH_H
#define FRAME_USBWATCH_H
#ifndef WATCH_NOW
#define WATCH_NOW() GetTickCount()
#endif

/* USB watch (../native_bridge/usbtrace.h callbacks, on the driver's threads).
 *
 * Live preview: the image pass streams one bulk read per line, 16-bit little-endian
 * RGB (scan 2026-10-31: 1712 reads of 2479 px x 6 bytes). Lines are averaged into
 * LIVE_SCALE x LIVE_SCALE blocks, 8-bit, still raw transmission. Calibration passes
 * are narrower or shorter, so a pass is shown only once it is wide and long enough.
 *
 * Stuck: SCAN08 waits for some sensors with no timeout (0x1000c867 polled status for
 * six minutes on 2026-10-31). A healthy scan never went 7.2 s without a register
 * write or bulk transfer; a driver that only polls status for STUCK_MS is stuck.
 *
 * The callbacks only fill buffers; the main thread prints (live_flush), so stdout
 * has a single writer. */
#define LIVE_SCALE 8
#define LIVE_MIN_WIDTH 1000
#define LIVE_MIN_LINES 96
#define LIVE_MAX_W 400
#define LIVE_MAX_H 240
#define STUCK_MS 30000
#define STUCK_POLLS 500
static CRITICAL_SECTION watch_lock;
static int watch_on;
static volatile LONG watch_stuck;
static DWORD watch_progress_at, watch_polls;
static struct {
    int pass, src_width, width, lines, rows, sent, started;
    DWORD sums[LIVE_MAX_W * 3];
    BYTE data[LIVE_MAX_H][LIVE_MAX_W * 3];
} live;

static void watch_progress(void) { watch_progress_at = WATCH_NOW(); watch_polls = 0; }
static void live_new_pass(void) {
    live.pass++; live.src_width = live.width = live.lines = live.rows = live.sent = live.started = 0;
    memset(live.sums, 0, sizeof live.sums);
}
static void watch_register(BYTE reg, BYTE value) {
    EnterCriticalSection(&watch_lock);
    if (reg != 0x97) watch_progress();       /* 0x97 only selects the status page */
    if (reg == 0x90 && value) live_new_pass(); /* auto-scan start */
    LeaveCriticalSection(&watch_lock);
}
static void watch_status(BYTE value) {
    (void)value;
    EnterCriticalSection(&watch_lock);
    if (++watch_polls > STUCK_POLLS && WATCH_NOW() - watch_progress_at > STUCK_MS) InterlockedExchange(&watch_stuck, 1);
    LeaveCriticalSection(&watch_lock);
}
static void watch_bulk_in(const BYTE *data, DWORD size) {
    EnterCriticalSection(&watch_lock);
    watch_progress();
    int width = (int)(size / 6);
    if (size % 6 == 0 && width >= LIVE_MIN_WIDTH) {
        if (live.src_width && live.src_width != width) live_new_pass();
        if (!live.src_width) { live.src_width = width; live.width = min(width / LIVE_SCALE, LIVE_MAX_W); }
        if (live.rows < LIVE_MAX_H) {
            for (int x = 0; x < live.width * LIVE_SCALE; x++)
                for (int c = 0; c < 3; c++) live.sums[(x / LIVE_SCALE) * 3 + c] += data[(x * 3 + c) * 2 + 1]; /* high byte */
            if (++live.lines % LIVE_SCALE == 0) {
                for (int i = 0; i < live.width * 3; i++) live.data[live.rows][i] = (BYTE)(live.sums[i] / (LIVE_SCALE * LIVE_SCALE));
                memset(live.sums, 0, sizeof live.sums);
                live.rows++;
            }
        }
    }
    LeaveCriticalSection(&watch_lock);
}
static void base64(const BYTE *in, int n, char *out) {
    static const char a[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (int i = 0; i < n; i += 3) {
        DWORD v = (DWORD)in[i] << 16 | (i + 1 < n ? (DWORD)in[i + 1] << 8 : 0) | (i + 2 < n ? in[i + 2] : 0);
        *out++ = a[v >> 18 & 63]; *out++ = a[v >> 12 & 63];
        *out++ = i + 1 < n ? a[v >> 6 & 63] : '='; *out++ = i + 2 < n ? a[v & 63] : '=';
    }
    *out = 0;
}
/* Main thread only. Prints the preview rows that arrived since the last call. */
static void live_flush(void) {
    static char line[LIVE_MAX_W * 4 + 128], encoded[LIVE_MAX_W * 4 + 8];
    if (!watch_on) return;
    EnterCriticalSection(&watch_lock);
    if (live.lines >= LIVE_MIN_LINES) {
        if (!live.started) {
            printf("{\"event\":\"live_start\",\"pass\":%d,\"width\":%d,\"source_width\":%d,\"scale\":%d}\n",
                   live.pass, live.width, live.src_width, LIVE_SCALE);
            live.started = 1;
        }
        for (; live.sent < live.rows; live.sent++) {
            base64(live.data[live.sent], live.width * 3, encoded);
            _snprintf(line, sizeof line, "{\"event\":\"live\",\"pass\":%d,\"y\":%d,\"width\":%d,\"data\":\"%s\"}\n",
                      live.pass, live.sent, live.width, encoded);
            fputs(line, stdout);
        }
        fflush(stdout);
    }
    LeaveCriticalSection(&watch_lock);
}
#endif
