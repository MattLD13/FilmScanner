/* Experimental direct AFL model-module host. This does NOT implement USB.
 * Genuine vendor code loads only after --allow-experimental-device-io. Loading
 * and initialization can home motors; never call these operations diagnostics.
 * --describe and --self-test do not load a vendor DLL or access the scanner.
 * --trace-usb PATH logs the vendor modules' USB calls (usbtrace.h); it adds no traffic.
 */
#define _WIN32_WINNT 0x0602
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "afl_contract.h"
#include "usbtrace.h"
#include "usbwatch.h"
/* SCAN08 is polling a sensor that never sets (usbwatch.h). Its loop has no timeout and
 * holds this thread, so report it now; the service ends this process. */
static void native_stuck(void) {
    printf("{\"event\":\"error\",\"code\":\"position_sensor\",\"message\":\"The scanner could not find its film position.\"}\n");
    fflush(stdout);
}

#define MAX_COMMAND 4096
#define QUEUE_SIZE 4
#define MAX_WIDTH 2586
#define MAX_HEIGHT 1708
static const char expected_hash[] = "da413438c0136338799cc7d49a14abae700e29feb7da1e993d4da1b8b5554b7f";
static AflDeviceIO device_io;
static volatile LONG cancel_generation, input_closed, queue_overflow;
static int synthetic, timeout_seconds = 300;
static int allow_controls;
static int allow_settings;
static int frame_initialized;
static char permitted_controls[256] = ",";
typedef struct { int dpi, bits, channels, monochrome, negative; float left,top,right,bottom; WORD exposure[3]; } Settings;
static Settings settings = {1800,16,3,0,1,.03f,.003f,1.407f,.95f,{100,100,100}};
static int control_allowed(const char *name) {
    char token[80]; sprintf_s(token,sizeof token,",%s,",name);
    return allow_controls && strstr(permitted_controls,token) != NULL;
}
static CRITICAL_SECTION queue_lock;
static HANDLE queue_ready, queue_space;
static char commands[QUEUE_SIZE][MAX_COMMAND];
static LONG command_generation[QUEUE_SIZE];
static unsigned int queue_read, queue_write;

static void json_string(const char *text) {
    const unsigned char *p = (const unsigned char *)text;
    putchar('"');
    for (; *p; p++) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}
static void error(const char *code, const char *message) {
    printf("{\"event\":\"error\",\"code\":"); json_string(code);
    printf(",\"message\":"); json_string(message); printf("}\n"); fflush(stdout);
}
static int wide(const char *text, WCHAR *out, int count) {
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, out, count) != 0;
}
static int loader_running(void) {
    PROCESSENTRY32W p = {sizeof p};
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    int found = 0;
    if (snapshot == INVALID_HANDLE_VALUE) return 1; /* Cannot establish ownership. */
    if (Process32FirstW(snapshot, &p)) do {
        if (!_wcsicmp(p.szExeFile, L"PfsLoader.exe")) { found = 1; break; }
    } while (Process32NextW(snapshot, &p));
    CloseHandle(snapshot); return found;
}

/* The open handle denies replacement while the pinned file is loaded. */
static int pinned_file(HANDLE file) {
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    BYTE buffer[65536], digest[32]; DWORD read;
    char hex[65]; int ok = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0) goto done;
    if (BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0) goto done;
    for (;;) {
        if (!ReadFile(file, buffer, sizeof buffer, &read, NULL)) goto done;
        if (!read) break;
        if (BCryptHashData(hash, buffer, read, 0) < 0) goto done;
    }
    if (BCryptFinishHash(hash, digest, sizeof digest, 0) < 0) goto done;
    for (unsigned i = 0; i < 32; i++) sprintf(hex + 2*i, "%02x", digest[i]);
    ok = !strcmp(hex, expected_hash);
done:
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
}

typedef struct {
    HANDLE file;
    WCHAR temporary[4096], destination[4096];
    DWORD width, height, rows;
    DWORD dpi, bits, channels, mode;
    int failed, last, temporary_owned, cancelled, timed_out;
    LONG generation;
    const char *failure;
    ULONGLONG started;
} Acquisition;
static Acquisition acquisition;
static int write_bytes(HANDLE file, const void *data, DWORD size) {
    DWORD written; return WriteFile(file, data, size, &written, NULL) && written == size;
}
static int put16(HANDLE file, WORD value) { return write_bytes(file, &value, 2); }
static int put32(HANDLE file, DWORD value) { return write_bytes(file, &value, 4); }
static int tag(HANDLE file, WORD id, WORD type, DWORD count, DWORD value) {
    return put16(file,id) && put16(file,type) && put32(file,count) && put32(file,value);
}
static int output_open(const char *path, LONG generation) {
    memset(&acquisition, 0, sizeof acquisition);
    acquisition.file = INVALID_HANDLE_VALUE;
    acquisition.started = GetTickCount64();
    acquisition.generation = generation;
    if (!wide(path, acquisition.destination, 4096)) return 0;
    if (GetFileAttributesW(acquisition.destination) != INVALID_FILE_ATTRIBUTES) return 0;
    if (swprintf_s(acquisition.temporary,4096,L"%ls.partial-%lu",acquisition.destination,GetCurrentProcessId()) < 0) return 0;
    acquisition.file = CreateFileW(acquisition.temporary,GENERIC_READ|GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    if (acquisition.file == INVALID_HANDLE_VALUE) return 0;
    acquisition.temporary_owned = 1;
    return write_bytes(acquisition.file,"II*\0\0\0\0\0",8);
}
static void output_discard(void) {
    if (acquisition.file != INVALID_HANDLE_VALUE) { CloseHandle(acquisition.file); acquisition.file = INVALID_HANDLE_VALUE; }
    if (acquisition.temporary_owned) DeleteFileW(acquisition.temporary);
}
static int output_finish(void) {
    HANDLE f = acquisition.file;
    static const char software[] = "FRAME native AFL model module - experimental";
    DWORD data_size = acquisition.width*acquisition.rows*acquisition.channels*(acquisition.bits/8);
    DWORD ifd = 8+data_size+(data_size&1), extra = ifd+2+14*12+4;
    if (data_size&1) {BYTE padding=0;if(!write_bytes(f,&padding,1))return 0;}
    int ok = put16(f,14) && tag(f,254,4,1,0) && tag(f,256,4,1,acquisition.width) && tag(f,257,4,1,acquisition.rows)
      && tag(f,258,3,acquisition.channels,acquisition.channels==1?acquisition.bits:extra) && tag(f,259,3,1,1) && tag(f,262,3,1,acquisition.channels==3?2:1) && tag(f,273,4,1,8)
      && tag(f,277,3,1,acquisition.channels) && tag(f,278,4,1,acquisition.rows) && tag(f,279,4,1,data_size)
      && tag(f,282,5,1,extra+8) && tag(f,283,5,1,extra+16) && tag(f,296,3,1,2)
      && tag(f,305,2,sizeof software,extra+24) && put32(f,0)
      && put16(f,(WORD)acquisition.bits) && put16(f,(WORD)acquisition.bits) && put16(f,(WORD)acquisition.bits) && put16(f,0)
      && put32(f,acquisition.dpi) && put32(f,1) && put32(f,acquisition.dpi) && put32(f,1)
      && write_bytes(f,software,sizeof software);
    if (SetFilePointer(f,4,NULL,FILE_BEGIN) == INVALID_SET_FILE_POINTER || !put32(f,ifd)) ok = 0;
    if (!FlushFileBuffers(f)) ok = 0;
    if (!CloseHandle(f)) ok = 0;
    acquisition.file = INVALID_HANDLE_VALUE;
    if (ok && MoveFileExW(acquisition.temporary,acquisition.destination,MOVEFILE_WRITE_THROUGH)) { acquisition.temporary_owned = 0; return 1; }
    DeleteFileW(acquisition.temporary); return 0;
}
static int fail_strip(AflStrip *strip, const char *reason) {
    acquisition.failed = 1; acquisition.failure = reason;
    if (strip) strip->abort_requested = 1;
    return 0;
}
static int __cdecl receive_strip(void *parameter) {
    AflStrip *s = (AflStrip *)parameter;
    if (!s) return fail_strip(NULL,"Missing native image strip");
    if (InterlockedCompareExchange(&cancel_generation,0,0) != acquisition.generation || InterlockedCompareExchange(&input_closed,0,0)) {
        acquisition.cancelled = 1; s->abort_requested = 1; return 0;
    }
    if (GetTickCount64()-acquisition.started > (ULONGLONG)timeout_seconds*1000) {
        acquisition.timed_out = 1; s->abort_requested = 1; return 0;
    }
    if (acquisition.failed) { s->abort_requested = 1; return 0; }
    if (s->mode != (DWORD)(settings.channels==3?(settings.bits==16?7:3):(settings.bits==16?6:2)) || s->dpi != (DWORD)settings.dpi || !s->width || s->width > MAX_WIDTH ||
        !s->height || s->height > MAX_HEIGHT || !s->lines || s->lines > s->height || !s->data)
        return fail_strip(s,"Invalid native image geometry or format");
    if (!acquisition.width) {
        acquisition.width = s->width; acquisition.height = s->height;
        acquisition.dpi=settings.dpi; acquisition.bits=settings.bits; acquisition.channels=settings.channels; acquisition.mode=s->mode;
        printf("{\"event\":\"image_start\",\"width\":%lu,\"height\":%lu,\"bits\":%lu,\"samples\":%lu,\"dpi\":%lu,\"pixel_type\":%d}\n",s->width,s->height,acquisition.bits,acquisition.channels,acquisition.dpi,settings.channels==3?2:1); fflush(stdout);
    }
    if (s->width != acquisition.width || s->height != acquisition.height || acquisition.last ||
        s->lines > acquisition.height-acquisition.rows || s->remaining_lines != acquisition.height-acquisition.rows-s->lines ||
        (!!s->last != (s->remaining_lines == 0)))
        return fail_strip(s,"Inconsistent or incomplete native image strip sequence");
    DWORD count=s->width*s->lines*acquisition.channels*(acquisition.bits/8);
    /* Preserve acquired grayscale samples even for requested binary output.
     * Thresholding belongs to the editable recipe, never this original. */
    if (!write_bytes(acquisition.file,s->data,count)) return fail_strip(s,"Could not save native image strip");
    acquisition.rows += s->lines; acquisition.last = !!s->last;
    if (watch_on && acquisition.channels == 3 && s->width >= LIVE_MIN_WIDTH) {   /* live preview from the strip itself */
        DWORD line_bytes = s->width*3*(acquisition.bits/8);
        EnterCriticalSection(&watch_lock);
        for (DWORD y = 0; y < s->lines; y++) live_add_line(s->data + y*line_bytes, (int)s->width, (int)(acquisition.bits/8));
        LeaveCriticalSection(&watch_lock);
        live_flush();
    }
    printf("{\"event\":\"progress\",\"rows\":%lu,\"height\":%lu}\n",acquisition.rows,acquisition.height); fflush(stdout);
    return 1;
}
static int scan_current(const char *path, LONG generation) {
    AflScanRequest request; WORD tables[3][4096]; DWORD status[2] = {0x1f,0};
    memset(&request,0,sizeof request);
    request.scan.dpi = (WORD)settings.dpi;
    request.scan.left=settings.left; request.scan.top=settings.top; request.scan.right=settings.right; request.scan.bottom=settings.bottom;
    request.scan.mode = settings.channels==3?(settings.bits==16?7:3):(settings.bits==16?6:2);
    for (unsigned c = 0; c < 3; c++) {
        request.scan.exposure[c] = settings.exposure[c]; request.scan.offset[c] = 100;
        for (unsigned i = 0; i < 4096; i++) tables[c][i] = (WORD)i;
        request.scan.lut[c] = tables[c];
    }
    request.scan.option33 = 3; request.scan.option34 = 1; request.scan.film_class = settings.negative?0x20:0x10;
    request.scan.option38 = 1; request.scan.option3c = 0x80;
    request.scan.callback = receive_strip; request.scan.requested_lines = 255;
    if (InterlockedCompareExchange(&input_closed,0,0) || InterlockedCompareExchange(&cancel_generation,0,0) != generation) {
        printf("{\"event\":\"cancelled\"}\n"); fflush(stdout); return -1;
    }
    /* This verified vendor query also establishes the module's internal media
     * type. Detection/open alone leave that state unset in a fresh process.
     * Actual loaded-strip status is 0x0e; no-film status is 0x08. */
    if (!device_io(0x15,status)) { error("native_status","The native module could not establish film status"); return 0; }
    if (!(status[1] & 4)) { error("no_film","No supported film strip is present; native acquisition was not started"); return 0; }
    if (!output_open(path,generation)) { output_discard(); error("write","Output must be a new writable filename"); return 0; }
    if (InterlockedCompareExchange(&input_closed,0,0) || InterlockedCompareExchange(&cancel_generation,0,0) != generation) {
        output_discard(); printf("{\"event\":\"cancelled\"}\n"); fflush(stdout); return -1;
    }
    printf("{\"event\":\"enabled\",\"show_ui\":false,\"synthetic\":%s}\n",synthetic?"true":"false"); fflush(stdout);
    if (watch_on) {
        EnterCriticalSection(&watch_lock);
        live_new_pass(); watch_progress(); InterlockedExchange(&watch_stuck, 0);
        LeaveCriticalSection(&watch_lock);
    }
    int result = device_io(0x20,&request);
    if (acquisition.timed_out) { output_discard(); error("timeout","The native acquisition exceeded its callback time limit"); return 0; }
    if (acquisition.cancelled || InterlockedCompareExchange(&input_closed,0,0) ||
        InterlockedCompareExchange(&cancel_generation,0,0) != generation) {
        output_discard(); printf("{\"event\":\"cancelled\"}\n"); fflush(stdout); return -1;
    }
    if (!result || acquisition.failed || !acquisition.last || acquisition.rows != acquisition.height || !acquisition.rows) {
        output_discard(); error("native_transfer",acquisition.failure ? acquisition.failure : "The native module did not deliver one complete frame"); return 0;
    }
    if (!output_finish()) { error("write","Could not atomically finish the native TIFF"); return 0; }
    frame_initialized=1;
    printf("{\"event\":\"image\",\"path\":"); json_string(path);
    printf(",\"width\":%lu,\"height\":%lu,\"bits\":%lu,\"samples\":%lu,\"dpi\":%lu,\"synthetic\":%s,\"processing\":\"vendor-calibrated transmission; identity LUT\",\"binary_recipe_requested\":%s}\n",acquisition.width,acquisition.height,acquisition.bits,acquisition.channels,acquisition.dpi,synthetic?"true":"false",settings.monochrome?"true":"false"); fflush(stdout);
    return 1;
}
static void configure(const char *line) {
    Settings next=settings; char channel[8],film[12],tail; unsigned r,g,b;
    if (sscanf(line,"settings %d %d %7s %11s %f %f %f %f %u %u %u %c",&next.dpi,&next.bits,channel,film,&next.left,&next.top,&next.right,&next.bottom,&r,&g,&b,&tail)!=11) {
        error("settings","Invalid acquisition settings"); return;
    }
    if (!(next.dpi==300||next.dpi==360||next.dpi==450||next.dpi==600||next.dpi==900||next.dpi==1800)||
        !(next.bits==8||next.bits==16)||!isfinite(next.left)||!isfinite(next.top)||!isfinite(next.right)||!isfinite(next.bottom)||
        next.left<0||next.top<0||next.right<=next.left||next.bottom<=next.top||next.right>2586.f/1800.f||next.bottom>.95f||
        r<50||r>400||g<50||g>400||b<50||b>400||
        (strcmp(channel,"rgb")&&strcmp(channel,"gray")&&strcmp(channel,"bw"))||
        (strcmp(film,"negative")&&strcmp(film,"positive"))||(!strcmp(channel,"bw")&&next.bits!=8)) {
        error("settings","Acquisition settings are outside reviewed bounds"); return;
    }
    next.channels=!strcmp(channel,"rgb")?3:1; next.monochrome=!strcmp(channel,"bw"); next.negative=!strcmp(film,"negative");
    next.exposure[0]=(WORD)r;next.exposure[1]=(WORD)g;next.exposure[2]=(WORD)b;
    if (!allow_settings && !(next.dpi==1800&&next.bits==16&&next.channels==3&&next.negative&&next.left==.03f&&next.top==.003f&&next.right==1.407f&&next.bottom==.95f&&r==100&&g==100&&b==100)) {
        error("unverified_settings","This acquisition configuration needs supervised device validation"); return;
    }
    settings=next;
    printf("{\"event\":\"configured\",\"dpi\":%d,\"bits\":%d,\"channel\":\"%s\",\"film\":\"%s\"}\n",settings.dpi,settings.bits,channel,film);fflush(stdout);
}
static int operation_cancelled(LONG generation) {
    if (input_closed||InterlockedCompareExchange(&cancel_generation,0,0)!=generation) {
        error("cancelled","The operation was cancelled before dispatch"); return 1;
    }
    return 0;
}
static int status_query(DWORD *value) {
    DWORD block[2]={0x1f,0};
    if (!device_io(0x15,block)) { error("native_status","Could not establish scanner state");return 0; }
    *value=block[1];return 1;
}
static void control(const char *line,LONG generation) {
    char name[48],extra; unsigned target=0; DWORD state=0,before=0,after=0; WORD motion[2]={0,1};
    int focus_action=!strncmp(line,"focus ",6),calibrate=!strcmp(line,"calibrate");
    const char *verb=focus_action?line+6:line+5;
    if (calibrate) strcpy_s(name,sizeof name,"calibrate");
    else if (focus_action) {
        if (!strcmp(verb,"auto")) strcpy_s(name,sizeof name,"autofocus");
        else if (sscanf(verb,"%u %c",&target,&extra)==1 && target<=200) strcpy_s(name,sizeof name,"focus");
        else {error("control","Invalid focus request");return;}
    } else if (sscanf(verb,"goto %u %c",&target,&extra)==1&&target>=1&&target<=40) strcpy_s(name,sizeof name,"goto");
    else if (sscanf(verb,"nudge %47s %u %c",name,&target,&extra)==2&&(!strcmp(name,"forward")||!strcmp(name,"back"))&&target>=1&&target<=300) {
        /* Selector 10: {i16 direction (bit 0 set = back), i16 motor steps}; the module caps
         * steps at 300 and halves them on firmware 3+. Used for stitched auto-align scans. */
        motion[0]=(WORD)(!strcmp(name,"back")?1:2); motion[1]=(WORD)target; strcpy_s(name,sizeof name,"nudge");
    }
    else if (sscanf(verb,"%47s %c",name,&extra)!=1) {error("control","Invalid film command");return;}
    if (!control_allowed(name)) {error("unverified_control","This scanner operation has not been enabled for device validation");return;}
    if ((!strcmp(name,"next")||!strcmp(name,"previous")||!strcmp(name,"goto"))&&!frame_initialized) {
        error("prescan_required","Prescan or acquire a frame in this session before moving film");return;
    }
    if (operation_cancelled(generation)||!status_query(&state))return;
    if (!(state&4)) {error("no_film","No supported film strip is loaded");return;}
    if (operation_cancelled(generation))return;
    printf("{\"event\":\"command\",\"name\":");json_string(name);printf("}\n");fflush(stdout);
    if (!strcmp(name,"next")||!strcmp(name,"previous")||!strcmp(name,"goto")) {
        if (!device_io(12,&before)) {error("position","Could not read current film position");return;}
        unsigned count=1;int reverse=!strcmp(name,"previous");
        if (!strcmp(name,"goto")) {target--;reverse=target<before;count=target>before?target-before:before-target;}
        if (before>39||count>39 || (reverse&&before==0) || (!reverse&&before>=39&&count)) {error("position","Requested frame is outside the known transport range");return;}
        for (unsigned i=0;i<count;i++) {
            if (operation_cancelled(generation))return;
            motion[0]=(WORD)(reverse?1:2);motion[1]=1;
            /* Selector9 wrapper does not guarantee a C return value. Verify position. */
            device_io(9,motion);
            if (!device_io(12,&after)||after!=(reverse?before-1:before+1)) {error("position","The driver did not confirm the requested frame movement");return;}
            before=after;
        }
    } else if (!strcmp(name,"nudge")) {
        if (!frame_initialized) {error("prescan_required","Scan a frame in this session before nudging the film");return;}
        if (!device_io(12,&before)) {error("position","Could not read current film position");return;}
        if (operation_cancelled(generation))return;
        device_io(10,motion);
        /* A nudge stays within the frame; the frame counter must not change. */
        if (!device_io(12,&after)||after!=before) {error("position","The film moved to another frame during a nudge");return;}
        printf("{\"event\":\"nudge\",\"direction\":\"%s\",\"steps\":%u}\n",motion[0]==1?"back":"forward",motion[1]);
    } else if (!strcmp(name,"eject_forward")||!strcmp(name,"eject_backward")) {
        /* Selector8 is actual Eject; selector11 is a separate 99-frame long-travel routine. */
        motion[0]=!strcmp(name,"eject_backward")?1:2;
        if (operation_cancelled(generation))return;
        device_io(8,motion);
        if (!status_query(&state)||state&4) {error("eject","The driver has not confirmed that film was ejected");return;}
        frame_initialized=0;
    } else if (!strcmp(name,"focus")) {
        if (operation_cancelled(generation))return;
        device_io(16,&target);device_io(15,&after);
        if (after!=target) {error("focus","The driver did not retain the requested focus value");return;}
    } else if (!strcmp(name,"autofocus")) {
        float point[2]={(settings.left+settings.right)*.5f,(settings.top+settings.bottom)*.5f};
        if (operation_cancelled(generation))return;
        device_io(14,point);device_io(15,&after);
        if (!after||after>200) {error("focus","Autofocus did not return a bounded focus position");return;}
    } else if (!strcmp(name,"calibrate")) {
        WORD balance[3]={0,0,0};if (operation_cancelled(generation))return;device_io(17,balance);
        if (!balance[0]||!balance[1]||!balance[2]) {error("calibration","Film-base measurement did not return valid values");return;}
        printf("{\"event\":\"calibration\",\"rgb\":[%u,%u,%u]}\n",balance[0],balance[1],balance[2]);
    } else {error("unsupported","Unknown native operation");return;}
    printf("{\"event\":\"command_done\",\"name\":");json_string(name);printf(",\"position\":%lu,\"focus\":%lu}\n",before+1,after);fflush(stdout);
}
static DWORD WINAPI input_thread(void *unused) {
    char line[MAX_COMMAND]; (void)unused;
    while (fgets(line,sizeof line,stdin)) {
        size_t n = strlen(line);
        if (n == sizeof line-1 && line[n-1] != '\n') { /* Refuse, and drain, an oversized command. */
            int c; while ((c = getchar()) != '\n' && c != EOF) {}
            strcpy_s(line,sizeof line,"!oversized");
        }
        line[strcspn(line,"\r\n")] = 0;
        if (!strcmp(line,"cancel")) { InterlockedIncrement(&cancel_generation); continue; }
        /* A full queue must not stop the reader from receiving cancel or EOF. */
        if (WaitForSingleObject(queue_space,0) != WAIT_OBJECT_0) {
            InterlockedExchange(&queue_overflow,1); continue;
        }
        EnterCriticalSection(&queue_lock);
        unsigned int slot = queue_write++ % QUEUE_SIZE;
        strcpy_s(commands[slot],MAX_COMMAND,line);
        command_generation[slot] = InterlockedCompareExchange(&cancel_generation,0,0);
        LeaveCriticalSection(&queue_lock); ReleaseSemaphore(queue_ready,1,NULL);
    }
    InterlockedExchange(&input_closed,1); InterlockedIncrement(&cancel_generation);
    ReleaseSemaphore(queue_ready,1,NULL); return 0;
}
static int serve(HMODULE module) {
    BYTE identity[36] = {0}, capabilities[0x85] = {0}; char context[] = ""; int initialized = 0, code = 1;
    *(char **)(identity+0x1c) = context;
    device_io = (AflDeviceIO)GetProcAddress(module,"ScannerDeviceIO");
    if (!device_io) { error("module_export","The scanner module has no expected export"); return 1; }
    if (!device_io(1,NULL)) { error("native_init","Native module initialization failed"); goto cleanup; }
    initialized = 1;
    if (!device_io(3,identity) || identity[32] || identity[33] || identity[34]) {
        error("native_detect","The native module did not identify a scanner"); goto cleanup;
    }
    if (!device_io(5,identity)) { error("native_open","The native module could not open the scanner"); goto cleanup; }
    capabilities[0] = sizeof capabilities;
    if (!device_io(0x16,capabilities) || *(WORD *)(capabilities+0x75) != 0x25 ||
        *(WORD *)(capabilities+0x25) != 1800 || *(WORD *)(capabilities+0x27) != 1800 ||
        *(WORD *)(capabilities+0x29) != MAX_WIDTH || *(WORD *)(capabilities+0x2b) != MAX_HEIGHT) {
        error("native_model","The native module did not report the reviewed model-37 capability block"); goto cleanup;
    }
    printf("{\"event\":\"opened\",\"source\":\"PF1800 AFL direct vendor model module\",\"synthetic\":%s,\"experimental\":true}\n",synthetic?"true":"false");
    InitializeCriticalSection(&queue_lock);
    queue_ready = CreateSemaphoreW(NULL,0,QUEUE_SIZE+1,NULL); queue_space = CreateSemaphoreW(NULL,QUEUE_SIZE,QUEUE_SIZE,NULL);
    if (!queue_ready || !queue_space) { error("queue","Could not create command queue"); goto cleanup; }
    HANDLE reader = CreateThread(NULL,0,input_thread,NULL,0,NULL);
    if (!reader) { error("queue","Could not start command reader"); goto cleanup; }
    CloseHandle(reader);
    for (;;) {
        char line[MAX_COMMAND]; LONG generation;
        printf("{\"event\":\"ready\"}\n"); fflush(stdout);
        WaitForSingleObject(queue_ready,INFINITE);
        if (InterlockedCompareExchange(&input_closed,0,0)) break;
        if (InterlockedExchange(&queue_overflow,0)) error("queue_full","Excess scanner commands were discarded");
        EnterCriticalSection(&queue_lock);
        if (queue_read == queue_write) { LeaveCriticalSection(&queue_lock); break; }
        unsigned int slot = queue_read++ % QUEUE_SIZE;
        strcpy_s(line,sizeof line,commands[slot]); generation = command_generation[slot];
        LeaveCriticalSection(&queue_lock); ReleaseSemaphore(queue_space,1,NULL);
        if (!strcmp(line,"quit")) break;
        if (!strncmp(line,"scan 1 ",7) && line[7]) {
            int result = scan_current(line+7,generation);
            printf("{\"event\":\"scan_done\",\"images\":%d,\"result\":%d}\n",result==1?1:0,result); fflush(stdout);
        } else if (!strncmp(line,"settings ",9)) configure(line);
        else if (!strncmp(line,"film ",5)||!strncmp(line,"focus ",6)||!strcmp(line,"calibrate")) control(line,generation);
        else error("unsupported","Unknown scanner command");
        if (input_closed) break;
    }
    code = 0;
cleanup:
    if (initialized) device_io(2,NULL);
    printf("{\"event\":\"done\",\"result\":%d}\n",code==0); fflush(stdout);
    return code;
}
static int self_test(void) {
    /* ABI size assertions above run at compile time. No vendor code loaded. */
    printf("{\"event\":\"self_test\",\"ok\":true,\"request_bytes\":%u,\"strip_bytes\":%u,\"device_io\":false}\n",(unsigned)sizeof(AflScanRequest),(unsigned)sizeof(AflStrip));
    return 0;
}
int main(int argc, char **argv) {
    int allow = 0, result; WCHAR path[4096], mutex_name[128]; HMODULE module; HANDLE pinned = INVALID_HANDLE_VALUE, mutex;
    const char *command = argc > 1 ? argv[1] : "--describe";
#ifdef FRAME_NATIVE_TEST
    const char *fixture = NULL;
#endif
    const char *trace = NULL;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i],"--allow-experimental-device-io")) allow = 1;
        else if (!strcmp(argv[i],"--allow-experimental-settings")) allow_settings=1;
        else if (!strcmp(argv[i],"--allow-experimental-controls")) allow_controls=1;
        else if (!strcmp(argv[i],"--controls")&&i+1<argc) {
            const char *list=argv[++i];
            if (strlen(list)>240||strspn(list,"abcdefghijklmnopqrstuvwxyz_,")!=strlen(list)) {error("usage","Invalid control allowlist");return 2;}
            sprintf_s(permitted_controls,sizeof permitted_controls,",%s,",list);
        }
        else if (!strcmp(argv[i],"--trace-usb") && i+1<argc) trace = argv[++i];
        else if (!strcmp(argv[i],"--timeout") && i+1<argc) {
            char *end; long value = strtol(argv[++i],&end,10);
            if (*end || value<1 || value>600) { error("usage","Timeout must be 1..600 seconds"); return 2; }
            timeout_seconds = (int)value;
        }
#ifdef FRAME_NATIVE_TEST
        else if (!strcmp(argv[i],"--fixture-dll") && i+1<argc) { fixture = argv[++i]; synthetic = 1; }
#endif
        else { error("usage","Unknown option"); return 2; }
    }
    if (!strcmp(command,"--self-test")) return self_test();
    if (!strcmp(command,"--describe")) {
        /* Describes the build, not what the service enables: controls and settings are
         * refused unless passed on the command line (see native_validation.json). */
        printf("{\"event\":\"description\",\"backend\":\"afl_module\",\"experimental\":true,\"current_frame_verified\":true,\"device_io\":false,\"dpi\":1800,\"bits\":16,\"expected_adc_bits\":12,\"measured_effective_bits\":null,\"controls\":[\"next\",\"previous\",\"goto\",\"eject_forward\",\"eject_backward\",\"autofocus\",\"focus\",\"calibrate\"],\"controls_default\":\"refused\",\"settings_default\":\"1800 dpi 16-bit RGB negative only\",\"scan_commands\":1}\n"); return 0;
    }
    if (strcmp(command,"serve")) { error("usage","aflbridge --describe | --self-test | serve --allow-experimental-device-io"); return 2; }
#ifdef FRAME_NATIVE_TEST
    if (!fixture && !allow) {
#else
    if (!allow) {
#endif
        error("experimental_disabled","Direct scanner initialization may home motors; explicit experimental authorization is required"); return 3;
    }
    if (synthetic) swprintf_s(mutex_name,128,L"Local\\FRAME_PF1800AFL_FIXTURE_%lu",GetCurrentProcessId());
    else wcscpy_s(mutex_name,128,L"Local\\FRAME_PF1800AFL");
    mutex = CreateMutexW(NULL,FALSE,mutex_name);
    if (!mutex || GetLastError() == ERROR_ALREADY_EXISTS) { if (mutex) CloseHandle(mutex); error("busy","Another scanner process owns the PF1800 AFL"); return 3; }
    if (!synthetic && loader_running()) { CloseHandle(mutex); error("busy","CyberView is open; close it before using the direct module"); return 3; }
    if (!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)) { CloseHandle(mutex); error("module_search","Could not constrain DLL search"); return 1; }
#ifdef FRAME_NATIVE_TEST
    if (fixture) {
        if (!wide(fixture,path,4096)) { CloseHandle(mutex); return 2; }
    } else
#endif
    {
        /* CyberScan's own verified copy first (services/native_bridge/driver_manifest.json,
         * copied by driver.py), so CyberView X need not stay installed; then the CyberView
         * install. Windows searches a DLL's own folder only for its direct imports, so the
         * chain is loaded bottom-up from that folder and SCAN08's imports are then resolved
         * by the already-loaded copies (checked 2026-10-31). */
        WCHAR folder[4096], part[4096];
        static const WCHAR *chain[] = {L"SQ1394.DLL", L"fvc.dll", L"IO_PORT.dll", L"SQ_Scan.dll"};
        DWORD n = GetEnvironmentVariableW(L"FRAME_DRIVER_DIR",folder,4096);
        if (!n || n >= 4096) n = GetEnvironmentVariableW(L"LOCALAPPDATA",folder,4096) ? (wcscat_s(folder,4096,L"\\CyberScanX\\driver"), 1) : 0;
        if (n && !wcscpy_s(path,4096,folder) && !wcscat_s(path,4096,L"\\SCAN08.dll") && GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES) {
            for (int i = 0; i < 4; i++) {
                if (swprintf_s(part,4096,L"%ls\\%ls",folder,chain[i]) < 0 ||
                    !LoadLibraryExW(part,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32)) {
                    CloseHandle(mutex); error("module_load","CyberScan's copy of the scanner driver is incomplete"); return 1;
                }
            }
        } else if (!GetWindowsDirectoryW(path,4096) || wcscat_s(path,4096,L"\\twain_32\\CyberViewX_MF\\SCAN08.dll")) { CloseHandle(mutex); return 1; }
        pinned = CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
        if (pinned == INVALID_HANDLE_VALUE || !pinned_file(pinned)) {
            if (pinned != INVALID_HANDLE_VALUE) CloseHandle(pinned);
            CloseHandle(mutex); error("module_identity","Installed SCAN08.dll does not match the reviewed 1.0.3.6 binary"); return 1;
        }
    }
    module = LoadLibraryExW(path,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (pinned != INVALID_HANDLE_VALUE) CloseHandle(pinned);
    if (!module) { CloseHandle(mutex); error("module_load","The pinned model module or a system dependency could not load"); return 1; }
    {
        /* SCAN08 imports SQ_Scan -> IO_PORT -> fvc statically, so all are loaded now,
         * before ScannerDeviceIO(1) sends the first byte. The watch (stuck detection)
         * always runs; --trace-usb also logs every call. */
#ifdef FRAME_NATIVE_TEST
        const char *traced[] = {"fvc.dll","IO_PORT.dll","SQ_Scan.dll","SCAN08.dll","fake-model.dll","fake-fvc.dll",NULL};
#else
        const char *traced[] = {"fvc.dll","IO_PORT.dll","SQ_Scan.dll","SCAN08.dll",NULL};
#endif
        InitializeCriticalSection(&watch_lock);
        live_from_usb = 0; watch_on_stuck = native_stuck;
        trace_on_register = watch_register; trace_on_status = watch_status; trace_on_bulk_in = watch_bulk_in;
        int slots = usbtrace_install(trace,traced);
        if (slots < 0) { FreeLibrary(module); CloseHandle(mutex); error("trace","Could not open the USB trace file"); return 1; }
        watch_on = 1;
        printf("{\"event\":\"%s\",\"slots\":%d}\n",trace?"trace":"watch",slots); fflush(stdout);
    }
    result = serve(module);
    FreeLibrary(module); CloseHandle(mutex);
    return result;
}
