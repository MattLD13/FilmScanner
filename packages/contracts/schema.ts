/** Portable v1 records. Times are UTC epoch milliseconds; image paths are relative. */
export type FilmType = 'color_negative' | 'bw_negative' | 'positive';
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
