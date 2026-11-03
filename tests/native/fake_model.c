/* CPU-only model ABI fixture. Its only I/O is fake-fvc.dll's probe of the NUL device
 * (mode "trace"), which exercises the USB tracer the way FVC.dll would. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../services/native_bridge/afl_contract.h"
__declspec(dllimport) int __cdecl FVCProbe(void);
static int initialized, opened, status_seen;
static const char *mode(void) { const char *s = getenv("FRAME_NATIVE_FIXTURE_MODE"); return s ? s : "ok"; }
static DWORD position=0,focus_value=0;static int film_loaded=1;
static int validate(const AflScanRequest *request) {
    const AflScanBlock *s=&request->scan;
    if (request->flags>1 || !s->dpi || !(s->mode==2||s->mode==3||s->mode==6||s->mode==7) || s->reserved || s->requested_lines!=255 || !s->callback || s->left<0 || s->right<=s->left || s->bottom<=s->top || s->option33!=3 || s->option34!=1 || !(s->film_class==0x20||s->film_class==0x10) || s->option38!=1 || s->option3c!=0x80) return 0;
    for(unsigned c=0;c<3;c++) {
      if(s->gain[c]||s->exposure[c]<50||s->exposure[c]>400||s->offset[c]!=100||!s->lut[c]) return 0;
      for(unsigned i=0;i<4096;i++) if(s->lut[c][i]!=i)return 0;
    }
    return 1;
}
__declspec(dllexport) int __cdecl ScannerDeviceIO(int selector, void *parameter) {
    if (selector == 1) { if (!strcmp(mode(),"trace") && !FVCProbe()) return 0; initialized = 1; opened = status_seen = 0;position=0;film_loaded=1; return 1; }
    if (selector == 2) { initialized = opened = 0; return 1; }
    if (!initialized) return 0;
    if (selector == 3) {
        BYTE *id = parameter;
        if (!id || !*(char **)(id+0x1c) || **(char **)(id+0x1c)) return 0;
        memcpy(id,"PIE     MF Film Scanner 4.00",28);
        id[32] = id[33] = id[34] = 0;
        return 1;
    }
    if (selector == 5) { opened = 1; return 1; }
    if (selector == 0x15) {
        DWORD *status = parameter;
        if (!status || status[0] != 0x1f || status[1] || !opened) return 0;
        if (!strcmp(mode(),"status-failure")) return 0;
        status[1] = (!film_loaded||!strcmp(mode(),"no-film")) ? 0x08 : 0x0e;
        status_seen = 1;
        return 1;
    }
    if (selector == 0x16) {
        BYTE *cap = parameter;
        if (!cap || cap[0] != 0x85) return 0;
        memset(cap,0,0x85);
        *(WORD *)(cap+0x25) = *(WORD *)(cap+0x27) = 1800;
        *(WORD *)(cap+0x29) = 2586; *(WORD *)(cap+0x2b) = 1708;
        *(WORD *)(cap+0x75) = !strcmp(mode(),"wrong-model") ? 42 : 37;
        return 1;
    }
    if(selector==12){*(DWORD *)parameter=position;return 1;}
    if(selector==9){WORD *v=parameter;if(v[1]!=1||!film_loaded||!(v[0]==1||v[0]==2))return 0;position+=(v[0]&1)? -1:1;return 1;}
    /* Fine movement: stays on the same frame unless the fixture is told to slip a frame. */
    if(selector==10){WORD *v=parameter;if(!film_loaded||!(v[0]==1||v[0]==2)||!v[1]||v[1]>300)return 0;
        if(!strcmp(mode(),"nudge-slips"))position+=1;return 1;}
    if(selector==8){WORD *v=parameter;if(!(v[0]==1||v[0]==2))return 0;film_loaded=0;return 1;}
    if(selector==16){focus_value=*(DWORD *)parameter;return 1;}
    if(selector==15){*(DWORD *)parameter=focus_value;return 1;}
    if(selector==14){focus_value=22;return 1;}
    if(selector==17){WORD *v=parameter;v[0]=100;v[1]=120;v[2]=150;return 1;}
    if(selector==23){if(!strcmp(mode(),"realign-slips"))position+=1;return 1;}
    if (selector == 0x20) {
        AflScanRequest *request = parameter; AflStrip strip; WORD pixels[7*3*3]; DWORD rows = 0;
        if (!opened || !status_seen || !request || !validate(request)) return 0;
        /* Fixture only: observable proof that the exact flag reaches selector32.
         * The true module may use a local request; these are not hardware gains. */
        if(request->flags==1){request->scan.exposure[0]=101;request->scan.exposure[1]=123;request->scan.exposure[2]=157;}
        status_seen = 0; /* Every acquisition needs a fresh status query. */
        if (!strcmp(mode(),"no-image")) return 1;
        if (!strcmp(mode(),"wide")) { /* full-width strips, enough lines for the live preview */
            static WORD wide[1200*16*3]; AflStrip w; DWORD done = 0;
            memset(&w,0,sizeof w); w.dpi = request->scan.dpi; w.mode = request->scan.mode; w.width = 1200; w.height = 128; w.reserved24 = 1;
            if (w.mode != 7) return 0;
            while (done < w.height) {
                w.lines = 16;
                for (DWORD y = 0; y < 16; y++) for (DWORD x = 0; x < 1200; x++) for (DWORD c = 0; c < 3; c++)
                    wide[(y*1200+x)*3+c] = (WORD)((((done+y)/8 + x/8 + c*50) & 0xff) << 8);
                done += 16; w.remaining_lines = w.height-done; w.last = done == w.height; w.data = (BYTE *)wide;
                request->scan.callback(&w);
                if (w.abort_requested) return 0;
            }
            return 1;
        }
        memset(&strip,0,sizeof strip);
        strip.dpi = request->scan.dpi; strip.mode = request->scan.mode; strip.width = 7; strip.height = 8; strip.data = (BYTE *)pixels; strip.reserved24 = 1;
        while (rows < strip.height) {
            strip.lines = strip.height-rows > 3 ? 3 : strip.height-rows;
            for (DWORD y = 0; y < strip.lines; y++) for (DWORD x = 0; x < strip.width; x++) for (DWORD c = 0; c < 3; c++)
                pixels[(y*strip.width+x)*3+c] = (WORD)(((rows+y)*100+x*7+c) << 4);
            rows += strip.lines; strip.remaining_lines = strip.height-rows; strip.last = rows == strip.height;
            if (!strcmp(mode(),"bad-remaining")) strip.remaining_lines++;
            if (!strcmp(mode(),"legacy-auto-preview")) strip.remaining_lines=0x00640064;
            BYTE bytes[7*3*3*2];int channels=(strip.mode==3||strip.mode==7)?3:1,bits=(strip.mode==6||strip.mode==7)?16:8;
            for(DWORD sample=0;sample<strip.lines*strip.width*(DWORD)channels;sample++) {
                if(bits==16)((WORD *)bytes)[sample]=pixels[sample];else bytes[sample]=(BYTE)(pixels[sample]>>8);
            }
            strip.data=bytes;
            if (!strcmp(mode(),"bad-size")) strip.width = 999999;
            request->scan.callback(&strip);
            if (strip.abort_requested) return 0;
            if (!strcmp(mode(),"truncated")) return 1;
            if (!strcmp(mode(),"slow")) Sleep(500);
            if (!strcmp(mode(),"timeout")) Sleep(600);
        }
        return 1;
    }
    return 0;
}
