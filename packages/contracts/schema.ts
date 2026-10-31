/** Portable v1 records. Times are UTC epoch milliseconds; image paths are relative. */
export type FilmType = 'color_negative' | 'bw_negative' | 'positive';
export type ScannerEvidence = 'verified_on_device' | 'recorded_on_device' | 'observed_vendor_call' | 'static_only' | 'unavailable';
/** Read passively from SCAN08.dll's own %TEMP% log and calibration cache; no device I/O. */
export interface VendorScannerReport {
  device_io_performed: false;
  log: null | { header: Partial<Record<'model' | 'usb' | 'ccd' | 'sdk' | 'firmware', string>>; geometry: Record<string, number>;
    lamp_calibration: { steps: number; final_level: number | null }; scans_logged: number; updated_at: number;
    last_scan: null | { film_type?: string; film_media?: string; lamp?: number; focus_step?: number; color_balance?: number[];
      highlight?: number[]; shadow?: number[]; gain?: number[]; dc?: number[] } };
  calibration_cache: null | { bytes: number; updated_at: number; age_hours: number };
}
export interface CyberScanOptions {
  dpi: 300 | 360 | 450 | 600 | 900 | 1800; bits: 8 | 16;
  channel: 'rgb' | 'gray' | 'bw'; film: 'negative' | 'positive';
  crop: {left: number; top: number; right: number; bottom: number};
  exposure: number[]; focus?: number | null;
}
export interface CyberScanWorkspace<TCapture = unknown> {
  settings: CyberScanOptions;
  capabilities: {actions: Record<string, {available: boolean; evidence: string; reason?: string}>;
    resolutions: number[]; depths: number[]; channels: string[]; films: string[];
    settings_validation?: {available: boolean; reason?: string}};
  prescan: TCapture | null;
}
export interface CyberScanDiagnostics {
  inspection: 'files_only'; device_io_performed: false;
  native_bridge_built: boolean; native_module_recognized: boolean;
  native_device_validation: 'pending' | 'current_frame_verified'; native_note: string;
  active_backend?: string;
  files: Array<{name: string; installed: boolean; bytes?: number; sha256?: string; recognized?: boolean; version?: string | null}>;
  features: Array<{id: string; name: string; evidence: ScannerEvidence; available: boolean; detail: string}>;
  catalog?: string;
  scanner?: VendorScannerReport;
}
export type RollStatus = 'awaiting_development' | 'developing' | 'ready_to_scan' | 'scanning' | 'scanned' | 'archived';
export interface Roll {
  id: string; stock: string; camera: string; iso: number; format: '35mm' | '120';
  film_type: FilmType; date: string; notes: string; tags: string[];
  status: RollStatus; created_at: number; contact_sheet_path?: string; prescan?: Prescan;
}
/** Low-resolution simulator prescan; previews are synthetic, never device imagery. */
export interface Prescan {
  at: number; media: 'uncut' | 'strip'; frame_count: number; synthetic: true; note: string;
  film_profile: string | null;
  frames: Array<{ index: number; position_mm?: number; preview_path: string }>;
}
/** Scan window as fractions of the frame (0..1). */
export interface ScanWindow { left: number; top: number; width: number; height: number }
/** Requested acquisition settings; `delivered` records what the backend actually returned. */
export interface ScanSettings {
  dpi: 300 | 600 | 900 | 1200 | 1800; bit_depth: 8 | 16; window: ScanWindow | null;
  gains: [number, number, number]; film_profile: string | null; requested?: true; delivered?: string;
}
/** CyberView .ft profile read from the user's own install; FRAME never distributes these. */
export interface FilmProfile {
  id: string; name: string; maker: string; film_class: 'negative' | 'reversal' | 'bw';
  rows: 256 | 4096; source_file: string; source_folder: string;
  kind?: 'reference-tone' | 'vendor-negative'; input_response?: number;
}
export interface EditRecipe {
  exposure: number; contrast: number; rotation: number; invert: boolean;
  film_base?: number[]; film_profile?: string;
}
export interface Frame {
  id: string; roll_id: string; index: number; original_path: string; preview_path: string;
  sha256: string; synthetic: boolean; edit: EditRecipe; favorite: boolean;
  effective_bits: number | null; source_sample_bits?: number; engine: string; provenance: string;
  scan_settings?: ScanSettings | null;
}
export interface DevelopmentStep {
  name: string; duration_seconds: number; agitation_seconds: number;
}
export interface DevelopmentSession {
  id: string; roll_id: string; recipe_id: string; status: 'running' | 'awaiting_user_transition' | 'completed' | 'interrupted' | 'aborted';
  step_index: number; started_at: number; step_started_at: number; checkpoint_at: number;
  steps: DevelopmentStep[]; events: Array<Record<string, unknown>>; temperature: number;
  remaining_seconds?: number; next_agitation_seconds?: number; clock_warning?: string;
}
export interface ScanSession {
  id: string; roll_id: string; status: string; current_frame: number; frame_count: number;
  completed_frames: number; error: string | null; started_at: number; updated_at: number;
  media: 'uncut' | 'strip'; speed: 'fast' | 'realtime'; fault: string | null;
  fault_frame: number; eta_seconds?: number; simulated: true;
  positions?: Array<Record<string, unknown>>; frames?: number[] | null; settings?: ScanSettings | null;
}
/** CyberScan viewing recipe; omitted conversion fields retain legacy rendering. */
export interface CyberScanAdjustments {
  exposure: number; contrast: number; saturation: number; temperature: number;
  rotation: number; mirror: boolean; invert?: boolean; film_base?: number[];
  negative_response?: number; black_point?: number; white_point?: number; gamma?: number;
  rgb_balance?: number[]; curve?: number[];
  crop?: { left: number; top: number; right: number; bottom: number };
  monochrome?: boolean; film_profile?: string | null; auto_color?: number[] | null;
}
