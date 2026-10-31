# FRAME v1 contracts

## CyberScan X acquisition

Authenticated `/api/cyberview/status` reports backend, supports_next, max_count,
image_kind, experimental_enabled and measured session state. Diagnostics at
`GET /api/cyberview/diagnostics` inspect installed files without opening hardware.
`POST /api/cyberview/backend` accepts `{backend:'cyberview-twain'|'afl-native-experimental',acknowledged:boolean}`;
native selection requires acknowledgment and the reviewed module hash, saves a
local preference and never starts hardware. Switching is rejected during work.
Native supports count1; transport requests are rejected. Its originals are
vendor-calibrated transmission, with effective_bits:null. Per-capture adjustments
also accept invert:boolean and film_base:[R,G,B], each finite0.01..1, default1.
Inversion precedes the color matrix using1-clip(transmission/base,0,1)^1.6.
Original export is immutable; previews/JPEG are8-bit and adjusted TIFF16-bit.

## FRAME workflow
Local single-origin JSON API under /api; dates are UTC epoch milliseconds. IDs are opaque UUID hex strings. Images use authenticated /media/{portable relative path}. WebSocket /api/events delivers bounded JSON events and begins with a snapshot; reconnect fetches /api/state. Session cookie is established by explicit POST /api/auth/local from the loopback same-origin UI. No network binding beyond 127.0.0.1.

GET /api/state -> {rolls: Roll[], frames: Frame[], development: DevelopmentSession[], scan: ScanSession|null, scanner: object, recipes: Recipe[], server_time: number}
POST /api/rolls {stock,camera?,iso?,format?:'35mm'|'120',film_type?:'color_negative'|'bw_negative'|'positive',notes?,date?,tags?} -> Roll
POST /api/development {roll_id, recipe_id:'demo-bw-v1', acknowledged:true, temperature:20} -> DevelopmentSession
POST /api/development/{id}/transition -> session; only after deadline, each physical transition requires confirmation. POST .../abort.
POST /api/development/{id}/review-clock {confirmed:true,actual_elapsed_seconds:number} -> session after explicit physical-step and clock review.
POST /api/rolls/{id}/ready -> roll for already-developed film.
POST /api/rolls/{id}/import {filename?,data_base64:string} -> frame, preserving imported bytes separately from simulated acquisitions.
POST /api/scanner/connect -> scanner
POST /api/scans {roll_id,frame_count:36,media:'uncut'|'strip',speed:'fast'|'realtime',fault?:'jam'|'calibration'|'disconnect'|'timeout'|'alignment'|'write',fault_frame?:17} -> ScanSession
POST /api/scans/{id}/recover or /cancel -> session
GET /api/rolls/{id}/contact-sheet -> image
POST /api/rolls/{id}/archive -> Roll; verifies original hashes and contact sheet
POST /api/frames/{id}/edit {exposure:0,contrast:1,rotation:0,invert:true} -> Frame
The `frame-density-2` engine also accepts film_base:[R,G,B] with normalized transmission values(0,1]. Omitting it preserves the stored base for older clients. /api/state advertises imaging_engine. Frames report source_sample_bits separately from measured effective_bits (null for unmeasured imports). Processed TIFF exports contain16-bit samples and embedded rendering/source-precision metadata; JPEG remains8-bit. Output precision never changes the acquired-precision claim.
GET /api/frames/{id}/export?format=jpeg|tiff|original -> file
POST /api/frames/{id}/favorite -> Frame

Roll: {id,stock,format,iso,camera,date,notes,tags,status,created_at}
Frame: {id,roll_id,index,original_path,preview_path,sha256,synthetic:boolean,edit:object,favorite:boolean}
DevelopmentSession: {id,roll_id,recipe_id,status,step_index,started_at,step_started_at,steps:[{name,duration_seconds,agitation_seconds}],events:[],temperature}
ScanSession: {id,roll_id,status,current_frame,frame_count,completed_frames,error,started_at,updated_at,media,speed,fault,fault_frame}

Simulator Python contract in services/scanner_host/backend.py (agent owned): ScannerBackend Protocol and SimulatedScannerBackend. Constructor accepts delay:float=0.02, fault:str|None=None, fault_frame:int=17. Async discover(), connect(), initialize(), calibrate(), load(frame_count:int,media:str='uncut'), prescan()->list[dict], position_frame(index:int), acquire(index:int)->numpy uint8 RGB array, cancel(), eject(), disconnect(); capabilities()->dict. subscribe(callback) supports async callback(dict); backend emits status/progress events. recover() clears one-shot fault and cancellation without discarding positions. No persistence in backend; root API owns file writes and recovery. Synthetic RGB arrays represent film transmission, not photographs or real scans. Exceptions carry meaningful strings. API owns the one-active-session gate.
