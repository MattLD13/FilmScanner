import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CyberScanDiagnostics, ScannerEvidence, CyberScanOptions, CyberScanWorkspace, FilmProfile } from '../../../packages/contracts/schema';
import './cyberscan.css';

// CyberScan X: a modern front end for CyberView X. Live mode talks to the local FRAME
// service, which drives CyberView's own TWAIN driver with its window hidden. Demo mode
// (?demo=1, used by the static preview) makes no network requests at all.

type Adjust = { exposure: number; contrast: number; saturation: number; temperature: number; rotation: number; mirror: boolean; invert?: boolean; film_base?: number[]; black_point?: number; white_point?: number; gamma?: number; rgb_balance?: number[]; curve?: number[]; crop?: { left: number; top: number; right: number; bottom: number }; monochrome?: boolean; film_profile?: string | null };
type Alignment = { confidence: 'frame_found' | 'one_edge' | 'centered'; exact: boolean; crop_mm: number[]; skew_deg: number | null; bleed_mm: number; note?: string | null };
type AlignInfo = { settings: { auto: boolean; bleed_mm: number; offset_mm: number; steps_per_mm: number | null }; stitched_scan: { available: boolean; reason: string }; max_window_mm: number[] };
const ALIGN_LABEL: Record<Alignment['confidence'], string> = { frame_found: 'Both frame edges found', one_edge: 'One frame edge found', centered: 'No edge visible · centred' };
type Capture = {
  id: string; index: number; title: string; roll: string; created_at: number; width: number; height: number;
  bits: number; dpi: number; sha256: string; favorite: boolean; adjustments: Adjust; demo?: boolean; src?: string;
  cyberview?: Settings;
  backend?: string; image_kind?: string;
  purpose?: 'scan' | 'prescan' | 'stitched';
  alignment?: Alignment;
};
type Settings = { found: boolean; film_term?: string | null; film_type?: 'negative' | 'positive' | null; auto_exposure?: boolean | null; auto_gamma?: boolean; scan_depth?: number; crop_inches?: number[] | null };
type Session = {
  id: string; state: 'starting' | 'warming' | 'advancing' | 'recovering' | 'scanning' | 'saving' | 'cancelling' | 'complete' | 'cancelled' | 'error';
  count: number; completed: number; frame: number; rows: number; height: number; started_at: number; roll: string; error: string | null;
  driver_status?: string | null; driver_dialog?: string | null;
  backend?: string;
  purpose?: 'scan' | 'prescan';
};
type Status = { bridge_built: boolean; busy: boolean; session_open: boolean; auto_reset: boolean; vendor_open: boolean; scanner_present: boolean | null; settings: Settings; session: Session | null; backend?: string; supports_next?: boolean; max_count?: number; experimental_enabled?: boolean };
type ScanOptions = CyberScanOptions;
type ActionName = 'next' | 'previous' | 'eject_forward' | 'eject_backward' | 'goto' | 'prescan' | 'autofocus' | 'focus' | 'calibrate';
type ScannerWorkspace = CyberScanWorkspace<Capture>;
type Histogram = { bins: number[][]; percentiles: { black: number; white: number }; original: boolean; stage?: string };
type View = 'scan' | 'library' | 'settings';
// Rows the scanner streams while it reads a frame: 1/8 size, 8-bit RGB, raw transmission (base64 per row).
type Live = { session_id: string; frame: number; pass: number; width: number; rows: string[] };
type IconName = 'scan' | 'library' | 'settings' | 'rotate' | 'mirror' | 'download' | 'stop' | 'star' | 'reset' | 'alert' | 'check' | 'film' | 'minus' | 'plus' | 'fit' | 'close';

const NEUTRAL: Adjust = { exposure: 0, contrast: 0, saturation: 0, temperature: 0, rotation: 0, mirror: false, invert: false, film_base: [1, 1, 1], black_point: 0, white_point: 1, gamma: 1, rgb_balance: [1, 1, 1], curve: [0, .25, .5, .75, 1], crop: { left: 0, top: 0, right: 1, bottom: 1 }, monochrome: false, film_profile: null };
const DEMO: Capture[] = [
  ['forest', 'Forest'], ['coast', 'Coast'], ['street', 'Street'],
].map(([id, name], i) => ({
  id, index: i + 1, title: name, roll: 'Sample images', created_at: 0, width: 0, height: 0, bits: 8, dpi: 0,
  sha256: '', favorite: false, adjustments: NEUTRAL, demo: true, src: `/demo/${id}.jpg`,
}));
const ACTIVE = new Set(['starting', 'warming', 'advancing', 'recovering', 'scanning', 'saving', 'cancelling']);
const DEFAULT_OPTIONS: ScanOptions = { dpi: 1800, bits: 16, channel: 'rgb', film: 'negative', crop: { left: .03, top: .003, right: 1.407, bottom: .95 }, exposure: [100, 100, 100], focus: null };
const ACTION_NAMES: Record<ActionName, string> = { next: 'Next frame', previous: 'Previous frame', eject_forward: 'Eject forward', eject_backward: 'Eject backward', goto: 'Go to frame', prescan: 'Prescan frame', autofocus: 'Autofocus', focus: 'Set focus', calibrate: 'Calibrate' };

const paths: Record<IconName, React.ReactNode> = {
  scan: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M7 6V4h10v2M3 12h18" /></>,
  library: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  settings: <><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></>,
  rotate: <><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>,
  mirror: <><path d="M12 3v18" /><path d="M8 7 3 12l5 5V7ZM16 7l5 5-5 5V7Z" /></>,
  download: <><path d="M12 4v11m-4-4 4 4 4-4" /><path d="M5 20h14" /></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  star: <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4L4.2 9.7l5.4-.8Z" />,
  reset: <><path d="M4 12a8 8 0 1 0 2.3-5.7" /><path d="M4 4v5h5" /></>,
  alert: <><path d="M12 4 2.5 20h19Z" /><path d="M12 10v4m0 3v.1" /></>,
  check: <path d="m5 12 4.5 4.5L19 7" />,
  film: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 3v18M16 3v18M4 8h4M4 13h4M16 8h4M16 13h4" /></>,
  minus: <path d="M5 12h14" />,
  plus: <path d="M12 5v14M5 12h14" />,
  fit: <path d="M9 4H4v5M15 4h5v5M4 15v5h5M20 15v5h-5" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
};
function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

// Same math as services/api/cyberview_routes.color_matrix, so exports match the screen.
function colorMatrix(a: Adjust) {
  const t = a.temperature / 100, scale = 2 ** a.exposure;
  const balance = a.rgb_balance || [1, 1, 1];
  const gains = [scale * (1 + .15 * t) * balance[0], scale * balance[1], scale * (1 - .15 * t) * balance[2]];
  const s = 1 + a.saturation / 100, k = 1 + a.contrast / 100, luma = [.2126, .7152, .0722], offset = .5 * (1 - k);
  const rows = [0, 1, 2].map((i) => [0, 1, 2].map((j) => k * ((1 - s) * luma[j] + (i === j ? s : 0)) * gains[j]));
  return rows.map((r) => [...r.map((v) => v.toFixed(4)), '0', offset.toFixed(4)].join(' ')).join(' ') + ' 0 0 0 1 0';
}

// A sampled display LUT applies the same levels, gamma and piecewise-linear
// curve as the full-precision export. The original itself is untouched.
function toneTable(a: Adjust) {
  const black = a.black_point ?? 0, white = a.white_point ?? 1, gamma = a.gamma ?? 1;
  const points = a.curve || [0, .25, .5, .75, 1];
  return Array.from({ length: 256 }, (_, index) => {
    const normalized = Math.min(1, Math.max(0, (index / 255 - black) / (white - black)));
    const position = Math.pow(normalized, 1 / gamma) * 4;
    const lower = Math.min(3, Math.floor(position));
    return (points[lower] + (points[lower + 1] - points[lower]) * (position - lower)).toFixed(6);
  }).join(' ');
}
const edgeNumber = (n: number) => String(n).padStart(2, '0') + 'A';
const signed = (v: number, digits = 0) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(digits);
const shortDate = (ms: number) => ms ? new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Sample';
const imageUrl = (c: Capture, kind: 'preview' | 'thumb') => c.src || `/api/cyberview/captures/${c.id}/${kind}`;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

function useScanner(demo: boolean) {
  const [mode, setMode] = useState<'connecting' | 'live' | 'offline' | 'demo'>(demo ? 'demo' : 'connecting');
  const [status, setStatus] = useState<Status | null>(null);
  const [captures, setCaptures] = useState<Capture[]>(demo ? DEMO : []);
  const [session, setSession] = useState<Session | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const refresh = useCallback(async () => {
    const next = await api<Status>('/api/cyberview/status');
    setStatus(next);
    // The service's session record is authoritative; events only make it arrive sooner.
    if (next.session) setSession(next.session);
    return next;
  }, []);

  useEffect(() => {
    if (demo) return;
    let socket: WebSocket | null = null, closed = false, timer = 0;
    const connect = () => {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/events`);
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data);
        if (event.type === 'cyberview_session') setSession(event.session);
        else if (event.type === 'cyberview_progress') setSession((s) => s && s.id === event.session_id ? { ...s, rows: event.rows, height: event.height, frame: event.frame } : s);
        else if (event.type === 'cyberview_live_start') setLive({ session_id: event.session_id, frame: event.frame, pass: event.pass, width: event.width, rows: [] });
        else if (event.type === 'cyberview_live') setLive((l) => l && l.session_id === event.session_id && l.pass === event.pass && event.y === l.rows.length ? { ...l, rows: [...l.rows, event.data] } : l);
        else if (event.type === 'cyberview_capture') setCaptures((list) => list.some((c) => c.id === event.capture.id) ? list : [...list, event.capture]);
      };
      socket.onclose = () => { if (!closed) timer = window.setTimeout(connect, 2000); };
    };
    (async () => {
      try {
        await api('/api/auth/local', { method: 'POST' });
        const [, list] = await Promise.all([refresh(), api<{ captures: Capture[] }>('/api/cyberview/captures')]);
        setCaptures(list.captures);
        api<{ live: Live | null }>('/api/cyberview/live').then((r) => setLive(r.live)).catch(() => undefined);
        setMode('live');
        connect();
      } catch {
        setMode('offline');
      }
    })();
    return () => { closed = true; window.clearTimeout(timer); socket?.close(); };
  }, [demo, refresh]);

  // CyberView being opened or the scanner being unplugged are only visible by asking.
  useEffect(() => {
    if (mode !== 'live') return;
    const id = window.setInterval(() => { refresh().catch(() => undefined); }, session && ACTIVE.has(session.state) ? 15000 : 4000);
    return () => window.clearInterval(id);
  }, [mode, refresh, session]);

  return { mode, status, captures, setCaptures, session, setSession, refresh, live };
}

function readiness(mode: string, status: Status | null) {
  if (mode === 'demo') return { ok: false, title: 'Sample mode', detail: 'Scanning is off in this preview' };
  if (mode === 'connecting') return { ok: false, title: 'Connecting', detail: 'Starting the local service' };
  if (mode === 'offline' || !status) return { ok: false, title: 'Service unavailable', detail: 'Start FRAME, then reload' };
  if (!status.bridge_built) return { ok: false, title: 'Bridge not built', detail: 'Run services/cyberview_bridge/build.ps1' };
  if (status.experimental_enabled === false) return { ok: false, title: 'Native testing disabled', detail: 'Device-test approval is required' };
  if (status.vendor_open) return { ok: false, title: 'CyberView is open', detail: 'Close it to scan from here' };
  if (status.session_open) return { ok: true, title: 'PrimeFilm 1800 AFL', detail: 'Driver session open' };
  if (status.scanner_present === false) return { ok: false, title: 'Scanner not found', detail: 'Check power and USB' };
  if (!status.settings.found) return { ok: false, title: 'CyberView not set up', detail: 'Open CyberView once, then close it' };
  return { ok: true, title: 'PrimeFilm 1800 AFL', detail: 'Ready for loaded film' };
}

/** The frame as the scanner reads it. Raw transmission: levels are stretched per channel
 * (0.5th to 99.5th percentile) and negatives inverted. CyberView's own colour comes later. */
function LivePreview({ live, negative }: { live: Live; negative: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const decoded = useRef<{ key: string; rows: Uint8Array[] }>({ key: '', rows: [] });
  useEffect(() => {
    const key = `${live.session_id}:${live.pass}`;
    if (decoded.current.key !== key) decoded.current = { key, rows: [] };
    const rows = decoded.current.rows;
    for (let y = rows.length; y < live.rows.length; y++) rows.push(Uint8Array.from(atob(live.rows[y]), (c) => c.charCodeAt(0)));
    const element = canvas.current, context = element?.getContext('2d');
    if (!element || !context || !rows.length) return;
    const width = live.width, height = Math.max(rows.length, Math.round(width * 1703 / 2479));
    if (element.width !== width || element.height !== height) { element.width = width; element.height = height; }
    const levels = [0, 1, 2].map((c) => {
      const counts = new Uint32Array(256); let total = 0;
      for (const row of rows) for (let i = c; i < row.length; i += 3) { counts[row[i]]++; total++; }
      const at = (q: number) => { let sum = 0; for (let v = 0; v < 256; v++) { sum += counts[v]; if (sum >= q * total) return v; } return 255; };
      const low = at(.005), high = Math.max(at(.995), low + 1);
      return { low, span: high - low };
    });
    const image = context.createImageData(width, height);
    rows.forEach((row, y) => {
      for (let x = 0; x < width; x++) for (let c = 0; c < 3; c++) {
        const value = Math.min(1, Math.max(0, (row[x * 3 + c] - levels[c].low) / levels[c].span));
        image.data[(y * width + x) * 4 + c] = Math.round(255 * (negative ? 1 - value : value));
      }
      for (let x = 0; x < width; x++) image.data[(y * width + x) * 4 + 3] = 255;
    });
    context.putImageData(image, 0, 0);
  }, [live, negative]);
  return <div className="cx-live">
    <canvas ref={canvas} role="img" aria-label={`Frame ${live.frame} as the scanner reads it`} />
    <span className="cx-original-badge">Live from the scanner · uncorrected</span>
  </div>;
}

function ScanProgress({ session, onCancel, now }: { session: Session; onCancel: () => void; now: number }) {
  const nativeMode = session.backend === 'afl-native-experimental';
  const elapsed = Math.max(0, Math.round((now - session.started_at) / 1000));
  const fraction = session.height ? session.rows / session.height : 0;
  // Most of a frame's time is CyberView scanning internally; lines arrive in the last seconds.
  const driverScanning = /^scanning/i.test(session.driver_status || '');
  const label = {
    starting: nativeMode ? 'Starting scanner' : 'Starting CyberView',
    warming: driverScanning ? `Scanning frame ${session.completed + 1} of ${session.count}` : 'Preparing the scanner',
    advancing: `Moving to frame ${session.completed + 1} of ${session.count}`,
    recovering: 'Restarting the scanner',
    scanning: `Receiving frame ${session.frame} of ${session.count}`,
    saving: 'Saving the original', cancelling: 'Stopping after this step', complete: 'Done', cancelled: 'Stopped', error: 'Stopped',
  }[session.state];
  return <div className="cx-progress" role="status" aria-live="polite">
    <div className="cx-progress-frame" aria-hidden="true">
      <div className="cx-progress-fill" style={{ transform: `scaleY(${session.state === 'scanning' ? fraction : 0})` }} />
      {session.state === 'scanning' && <div className="cx-progress-line" style={{ top: `${fraction * 100}%` }} />}
      <span className="cx-edge">{edgeNumber(session.state === 'scanning' ? session.frame : session.completed + 1)}</span>
    </div>
    <div className="cx-progress-text">
      <strong>{label}</strong>
      <span>
        {session.driver_dialog && `CyberView is asking: ${session.driver_dialog}. Answer it in the CyberView window.`}
        {!session.driver_dialog && session.state === 'warming' && (session.driver_status
          ? `${session.driver_status.replace(/[.\s]+$/, '')}${driverScanning ? '' : ' · the first frame takes two to three minutes'}`
          : nativeMode ? 'The driver is preparing the current frame.' : 'The lamp warms up and the loader finds the frame. The first frame takes two to three minutes.')}
        {!session.driver_dialog && session.state === 'scanning' && (session.rows
          ? `${session.rows.toLocaleString()} of ${session.height.toLocaleString()} lines received`
          : session.driver_status?.replace(/\.{2,}$/, '') || 'CyberView is scanning the frame')}
        {session.state === 'starting' && (nativeMode ? 'Opening the direct scanner interface' : 'Loading the driver with its window hidden')}
        {session.state === 'saving' && 'Writing the TIFF and its checksum'}
        {session.state === 'recovering' && 'The scanner stalled. Restarting its USB connection, then continuing'}
        {session.state === 'cancelling' && 'CyberView finishes its current step before stopping'}
      </span>
      <span className="cx-meta">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')} elapsed · {session.completed} of {session.count} saved</span>
    </div>
    <button className="cx-button" onClick={onCancel} disabled={session.state === 'cancelling'}><Icon name="stop" />Stop</button>
  </div>;
}

function Slider({ label, value, min, max, step, unit = '', digits = 0, onChange }: { label: string; value: number; min: number; max: number; step: number; unit?: string; digits?: number; onChange: (v: number) => void }) {
  return <label className="cx-slider">
    <span><span>{label}</span><output>{value === 0 ? '0' : signed(value, digits)}{unit}</output></span>
    <input type="range" aria-label={label} min={min} max={max} step={step} value={value}
      onChange={(e) => onChange(Number(e.target.value))} onDoubleClick={() => onChange(0)} />
  </label>;
}

export function CyberScanSkin() {
  const demo = useMemo(() => new URLSearchParams(location.search).get('demo') === '1', []);
  const { mode, status, captures, setCaptures, session, setSession, refresh, live } = useScanner(demo);
  const [view, setView] = useState<View>('scan');
  const [selected, setSelected] = useState<string | null>(null);
  const [count, setCount] = useState(1);
  const [roll, setRoll] = useState('');
  const [zoom, setZoom] = useState(1);
  const [message, setMessage] = useState<{ text: string; tone: 'info' | 'error' } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [diagnostics, setDiagnostics] = useState<CyberScanDiagnostics | null>(null);
  const [diagnosticError, setDiagnosticError] = useState('');
  const [nativeAcknowledged, setNativeAcknowledged] = useState(false);
  const [switchingBackend, setSwitchingBackend] = useState(false);
  const [workspace, setWorkspace] = useState<ScannerWorkspace | null>(null);
  const [options, setOptions] = useState<ScanOptions>(DEFAULT_OPTIONS);
  const [workspaceError, setWorkspaceError] = useState('');
  const [savingOptions, setSavingOptions] = useState(false);
  const [optionsDirty, setOptionsDirty] = useState(false);
  const [pendingAction, setPendingAction] = useState<ActionName | null>(null);
  const [targetFrame, setTargetFrame] = useState(1);
  const [targetFocus, setTargetFocus] = useState(0);
  const [histogram, setHistogram] = useState<Histogram | null>(null);
  const [autoLevelBusy, setAutoLevelBusy] = useState(false);
  const [profiles, setProfiles] = useState<FilmProfile[]>([]);
  const [profileError, setProfileError] = useState('');
  const [previewError, setPreviewError] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const [confirmRoll, setConfirmRoll] = useState(false);
  const [rollApplying, setRollApplying] = useState(false);
  const pendingSaves = useRef(new Map<string, { timer: number; adjustments: Adjust }>());
  const inFlightSaves = useRef(new Map<string, Promise<void>>());

  const current = captures.find((c) => c.id === selected) || captures[captures.length - 1] || null;
  const adjust = current?.adjustments || NEUTRAL;
  const ready = readiness(mode, status);
  const scanning = !!session && ACTIVE.has(session.state);
  const showLive = scanning && !!live && live.session_id === session?.id && live.rows.length > 0 && session?.state !== 'saving';
  const nativeMode = status?.backend === 'afl-native-experimental';
  const profilePreview = !showOriginal && !!adjust.film_profile && !!current && !current.demo && mode === 'live';
  const imageSrc = current && profilePreview ? `/api/cyberview/captures/${current.id}/profile-preview?${new URLSearchParams({ profile_id: adjust.film_profile || '', invert: String(!!adjust.invert), base_r: String(adjust.film_base?.[0] ?? 1), base_g: String(adjust.film_base?.[1] ?? 1), base_b: String(adjust.film_base?.[2] ?? 1) }).toString()}` : current ? imageUrl(current, 'preview') : '';
  const optionsChanged = JSON.stringify(options) !== JSON.stringify(workspace?.settings);
  const can = (name: string) => workspace?.capabilities.actions[name]?.available === true;
  const reason = (name: string) => workspace?.capabilities.actions[name]?.reason || 'Not available with the selected scanner interface.';
  const controlsBusy = scanning || !!status?.busy || savingOptions || switchingBackend;
  const matrix = useMemo(() => colorMatrix(adjust), [adjust]);
  const tone = useMemo(() => toneTable(adjust), [adjust]);
  const rollCaptures = useMemo(() => {
    if (!current) return captures;
    return captures.filter((c) => c.roll === current.roll);
  }, [captures, current]);

  useEffect(() => { if (!scanning) return; const id = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(id); }, [scanning]);
  useEffect(() => {
    if (!pendingAction && !confirmRoll) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') { setPendingAction(null); setConfirmRoll(false); } };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [pendingAction, confirmRoll]);
  // Announce only sessions seen running here, not a finished one loaded at startup.
  const watched = useRef<string | null>(null);
  useEffect(() => {
    if (!session) return;
    if (ACTIVE.has(session.state)) { watched.current = session.id; return; }
    if (watched.current !== session.id) return;
    watched.current = null;
    if (session.state === 'error' && session.error) setMessage({ text: session.error, tone: 'error' });
    if (session.state === 'complete') setMessage({ text: session.purpose === 'prescan' ? 'Prescan complete.' : `${session.completed} ${session.completed === 1 ? 'frame' : 'frames'} saved.`, tone: 'info' });
  }, [session?.id, session?.state, session?.error, session?.completed]);
  useEffect(() => { setZoom(1); setShowOriginal(false); }, [current?.id]);
  useEffect(() => {
    if (mode !== 'live' || !current || current.demo) { setHistogram(null); return; }
    let cancelled = false;
    setHistogram(null);
    // Base and inversion edits save after 300 ms; wait for that save before
    // asking the server for the corresponding before-levels histogram.
    const timer = window.setTimeout(() => {
      api<Histogram>(`/api/cyberview/captures/${current.id}/histogram`)
        .then((data) => { if (!cancelled) setHistogram(data); })
        .catch(() => { if (!cancelled) setHistogram(null); });
    }, 800);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [mode, current?.id, adjust.invert, adjust.film_profile, (adjust.film_base || []).join(',')]);
  useEffect(() => {
    if (mode !== 'live') return;
    let cancelled = false;
    api<{ profiles: FilmProfile[] }>('/api/film-profiles')
      .then((data) => { if (!cancelled) { setProfiles(data.profiles); setProfileError(''); } })
      .catch(() => { if (!cancelled) { setProfiles([]); setProfileError('Film profiles could not be loaded.'); } });
    return () => { cancelled = true; };
  }, [mode]);
  useEffect(() => { setPreviewError(false); }, [imageSrc]);
  const refreshWorkspace = useCallback(async () => {
    const data = await api<ScannerWorkspace>('/api/cyberview/workspace');
    setWorkspace(data);
    setOptions(data.settings);
    setOptionsDirty(false);
    setWorkspaceError('');
    return data;
  }, []);
  useEffect(() => {
    if (mode !== 'live') return;
    let stale = false;
    api<ScannerWorkspace>('/api/cyberview/workspace').then((data) => {
      if (!stale) { setWorkspace(data); setOptions(data.settings); setOptionsDirty(false); setWorkspaceError(''); }
    }).catch((error: Error) => { if (!stale) { setWorkspace(null); setWorkspaceError(error.message); } });
    return () => { stale = true; };
  }, [mode, status?.backend]);
  useEffect(() => {
    if (mode === 'live' && session && !ACTIVE.has(session.state)) {
      api<ScannerWorkspace>('/api/cyberview/workspace').then((data) => {
        setWorkspace(data);
        if (!optionsDirty) setOptions(data.settings);
      }).catch(() => undefined);
    }
  }, [mode, session?.id, session?.state, optionsDirty]);
  useEffect(() => {
    if (mode !== 'live' || view !== 'settings') return;
    let closed = false;
    api<CyberScanDiagnostics>('/api/cyberview/diagnostics')
      .then((data) => { if (!closed) { setDiagnostics(data); setDiagnosticError(''); } })
      .catch((error: Error) => { if (!closed) setDiagnosticError(error.message); });
    return () => { closed = true; };
  }, [mode, view]);

  const flushSave = (id: string): Promise<void> => {
    const pending = pendingSaves.current.get(id);
    if (!pending) return inFlightSaves.current.get(id) || Promise.resolve();
    window.clearTimeout(pending.timer);
    pendingSaves.current.delete(id);
    const prior = inFlightSaves.current.get(id) || Promise.resolve();
    const request = prior.catch(() => undefined).then(async () => {
      await api(`/api/cyberview/captures/${id}`, { method: 'PATCH', body: JSON.stringify({ adjustments: pending.adjustments }) });
    });
    inFlightSaves.current.set(id, request);
    return request;
  };
  const updateAdjust = (patch: Partial<Adjust>) => {
    if (!current) return;
    const next = { ...current.adjustments, ...patch };
    setCaptures((list) => list.map((c) => c.id === current.id ? { ...c, adjustments: next } : c));
    if (mode !== 'live' || current.demo) return;
    const existing = pendingSaves.current.get(current.id);
    if (existing) window.clearTimeout(existing.timer);
    const id = current.id;
    const timer = window.setTimeout(() => { flushSave(id).catch((e: Error) => setMessage({ text: `Could not save this edit: ${e.message}`, tone: 'error' })); }, 300);
    pendingSaves.current.set(id, { timer, adjustments: next });
  };
  const toggleFavorite = () => {
    if (!current) return;
    const favorite = !current.favorite;
    setCaptures((list) => list.map((c) => c.id === current.id ? { ...c, favorite } : c));
    if (mode === 'live' && !current.demo) api(`/api/cyberview/captures/${current.id}`, { method: 'PATCH', body: JSON.stringify({ favorite }) }).catch(() => undefined);
  };
  const autoLevels = async () => {
    if (!current || current.demo || mode !== 'live') return;
    setAutoLevelBusy(true);
    try {
      await flushSave(current.id);
      const updated = await api<Capture>(`/api/cyberview/captures/${current.id}/auto-levels`, { method: 'POST' });
      setCaptures((list) => list.map((item) => item.id === updated.id ? updated : item));
      setMessage({ text: 'Auto levels applied to this edit. The original is unchanged.', tone: 'info' });
    } catch (error) { setMessage({ text: (error as Error).message, tone: 'error' }); }
    finally { setAutoLevelBusy(false); }
  };
  const exportCapture = async (event: React.MouseEvent<HTMLAnchorElement>, capture: Capture, format: string) => {
    event.preventDefault();
    if (rollApplying) return;
    try {
      await flushSave(capture.id);
      const link = document.createElement('a');
      link.href = `/api/cyberview/captures/${capture.id}/export/${format}`;
      link.download = '';
      document.body.appendChild(link); link.click(); link.remove();
    } catch (error) { setMessage({ text: `Save the edit before exporting: ${(error as Error).message}`, tone: 'error' }); }
  };
  const applyRollColor = async () => {
    if (!current || current.demo || mode !== 'live') return;
    setConfirmRoll(false); setRollApplying(true);
    try {
      const ids = new Set([...pendingSaves.current.keys(), ...inFlightSaves.current.keys()]);
      await Promise.all([...ids].map(flushSave));
      const result = await api<{ captures: Capture[]; count: number }>(`/api/cyberview/captures/${current.id}/apply-to-roll`, { method: 'POST', body: JSON.stringify({ adjustments: current.adjustments }) });
      setCaptures((list) => list.map((item) => result.captures.find((updated) => updated.id === item.id) || item));
      setMessage({ text: `Color settings applied to ${result.count} ${result.count === 1 ? 'frame' : 'frames'}.`, tone: 'info' });
    } catch (error) { setMessage({ text: (error as Error).message, tone: 'error' }); }
    finally { setRollApplying(false); }
  };
  const variation = (kind: string) => {
    const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, Number(value.toFixed(2))));
    if (kind === 'Lighter' || kind === 'Darker') updateAdjust({ exposure: clamp(adjust.exposure + (kind === 'Lighter' ? .25 : -.25), -2, 2) });
    else if (kind === 'Warmer' || kind === 'Cooler') updateAdjust({ temperature: clamp(adjust.temperature + (kind === 'Warmer' ? 10 : -10), -100, 100) });
    else {
      const channel = ['More red', 'More green', 'More blue'].indexOf(kind);
      if (channel < 0) return;
      const rgb_balance = [...(adjust.rgb_balance || [1, 1, 1])];
      rgb_balance[channel] = clamp(rgb_balance[channel] + .1, .25, 4);
      updateAdjust({ rgb_balance });
    }
  };
  const [alignInfo, setAlignInfo] = useState<AlignInfo | null>(null);
  const [aligning, setAligning] = useState(false);
  const [stitchArmed, setStitchArmed] = useState(false);
  useEffect(() => {
    if (mode !== 'live') return;
    api<AlignInfo>('/api/cyberview/align').then(setAlignInfo).catch(() => undefined);
  }, [mode, status?.backend]);
  const saveAlign = (patch: Partial<AlignInfo['settings']>) => {
    if (!alignInfo) return;
    api<AlignInfo>('/api/cyberview/align', { method: 'PUT', body: JSON.stringify({ ...alignInfo.settings, ...patch }) })
      .then(setAlignInfo).catch((e: Error) => setMessage({ text: e.message, tone: 'error' }));
  };
  const autoAlign = async () => {
    if (!current || current.demo) return;
    setAligning(true);
    try {
      const result = await api<{ alignment: Alignment; capture: Capture }>(`/api/cyberview/captures/${current.id}/auto-align`, { method: 'POST', body: JSON.stringify({ bleed_mm: alignInfo?.settings.bleed_mm ?? 0 }) });
      setCaptures((list) => list.map((c) => c.id === current.id ? result.capture : c));
      const a = result.alignment;
      setMessage(a.exact ? { text: `${ALIGN_LABEL[a.confidence]}. Cropped to ${a.crop_mm[0]} × ${a.crop_mm[1]} mm.`, tone: 'info' }
        : { text: a.note || 'The frame could not be cropped exactly.', tone: 'error' });
    } catch (e) {
      setMessage({ text: (e as Error).message, tone: 'error' });
    } finally {
      setAligning(false);
    }
  };
  const startStitched = async () => {
    if (!stitchArmed) { setStitchArmed(true); return; }
    setStitchArmed(false);
    try {
      setMessage(null);
      const started = await api<Session>('/api/cyberview/stitched-scan', { method: 'POST', body: JSON.stringify({ roll, acknowledged: true }) });
      setSession(started); setSelected(null); setNow(Date.now());
    } catch (e) {
      setMessage({ text: (e as Error).message, tone: 'error' });
    }
  };
  const startScan = async () => {
    try {
      setMessage(null);
      const started = await api<Session>('/api/cyberview/scan', { method: 'POST', body: JSON.stringify({ count, roll, ...(workspace ? { settings: workspace.settings } : {}) }) });
      setSession(started);
      setSelected(null);
      setNow(Date.now());
    } catch (e) {
      setMessage({ text: (e as Error).message, tone: 'error' });
      refresh().catch(() => undefined);
    }
  };
  const [moving, setMoving] = useState<string | null>(null);
  const moveFilm = async () => {
    setMoving('Moving to the next frame');
    try {
      await api<Status>('/api/cyberview/film', { method: 'POST', body: JSON.stringify({ action: 'next' }) });
      await refresh();
    } catch (e) {
      setMessage({ text: (e as Error).message, tone: 'error' });
    } finally {
      setMoving(null);
    }
  };
  const applyOptions = async () => {
    setSavingOptions(true);
    try {
      const data = await api<ScannerWorkspace>('/api/cyberview/workspace', { method: 'PUT', body: JSON.stringify(options) });
      setWorkspace(data); setOptions(data.settings); setOptionsDirty(false); setWorkspaceError('');
      setMessage({ text: 'Scan settings saved.', tone: 'info' });
    } catch (error) { setMessage({ text: (error as Error).message, tone: 'error' }); }
    finally { setSavingOptions(false); }
  };
  const changeOptions = (patch: Partial<ScanOptions>) => { setOptions((value) => ({ ...value, ...patch })); setOptionsDirty(true); };
  const startPrescan = async () => {
    if (!workspace || !can('prescan')) return;
    try {
      setMessage(null);
      const started = await api<Session>('/api/cyberview/prescan', { method: 'POST', body: JSON.stringify({ roll, settings: workspace.settings }) });
      setSession(started); setSelected(null); setNow(Date.now());
    } catch (error) { setMessage({ text: (error as Error).message, tone: 'error' }); }
  };
  const sendAction = async (action: ActionName, acknowledged = false) => {
    if (!can(action) || controlsBusy || moving) return;
    setPendingAction(null); setMoving(ACTION_NAMES[action]);
    try {
      const filmAction = ['next', 'previous', 'eject_forward', 'eject_backward', 'goto'].includes(action);
      const payload = filmAction ? { action, ...(action === 'goto' ? { frame: targetFrame } : {}), acknowledged } : { action, ...(action === 'focus' ? { value: targetFocus } : {}), acknowledged };
      await api(filmAction ? '/api/cyberview/film' : '/api/cyberview/control', { method: 'POST', body: JSON.stringify(payload) });
      await Promise.all([refresh(), refreshWorkspace()]);
      setMessage({ text: `${ACTION_NAMES[action]} complete.`, tone: 'info' });
    } catch (error) { setMessage({ text: (error as Error).message, tone: 'error' }); }
    finally { setMoving(null); }
  };
  const stopScan = () => api<Session>('/api/cyberview/cancel', { method: 'POST' }).then(setSession).catch((e: Error) => setMessage({ text: e.message, tone: 'error' }));
  const selectBackend = async (backend: 'cyberview-twain' | 'afl-native-experimental') => {
    setSwitchingBackend(true);
    try {
      await api('/api/cyberview/backend', { method: 'POST', body: JSON.stringify({ backend, acknowledged: nativeAcknowledged }) });
      setCount(1);
      await refresh();
      await refreshWorkspace();
      setMessage({ text: 'Scanner interface saved. No scan has started.', tone: 'info' });
    } catch (error) {
      setMessage({ text: (error as Error).message, tone: 'error' });
    } finally { setSwitchingBackend(false); }
  };

  const nav: [View, string, IconName][] = [['scan', 'Scan', 'scan'], ['library', 'Library', 'library'], ['settings', 'Settings', 'settings']];
  const transform = showOriginal ? `scale(${zoom})` : `scale(${zoom}) rotate(${adjust.rotation}deg) scaleX(${adjust.mirror ? -1 : 1})`;
  const crop = adjust.crop || { left: 0, top: 0, right: 1, bottom: 1 };
  const cropped = !showOriginal && (crop.left !== 0 || crop.top !== 0 || crop.right !== 1 || crop.bottom !== 1);
  const imageWidth = current?.width || 1200, imageHeight = current?.height || 800;

  return <div className="cx-app">
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <filter id="cx-adjust" colorInterpolationFilters="sRGB">
        <feComponentTransfer>
          <feFuncR type="gamma" amplitude={adjust.invert && !profilePreview ? -1 / Math.pow(adjust.film_base?.[0] ?? 1, 1.6) : 1} exponent={adjust.invert && !profilePreview ? 1.6 : 1} offset={adjust.invert && !profilePreview ? 1 : 0} />
          <feFuncG type="gamma" amplitude={adjust.invert && !profilePreview ? -1 / Math.pow(adjust.film_base?.[1] ?? 1, 1.6) : 1} exponent={adjust.invert && !profilePreview ? 1.6 : 1} offset={adjust.invert && !profilePreview ? 1 : 0} />
          <feFuncB type="gamma" amplitude={adjust.invert && !profilePreview ? -1 / Math.pow(adjust.film_base?.[2] ?? 1, 1.6) : 1} exponent={adjust.invert && !profilePreview ? 1.6 : 1} offset={adjust.invert && !profilePreview ? 1 : 0} />
        </feComponentTransfer>
        <feComponentTransfer>
          <feFuncR type="table" tableValues={tone} />
          <feFuncG type="table" tableValues={tone} />
          <feFuncB type="table" tableValues={tone} />
        </feComponentTransfer>
        <feColorMatrix type="matrix" values={matrix} />
        {adjust.monochrome && <>
          <feColorMatrix type="matrix" values="0.333333 0.333333 0.333333 0 0 0.333333 0.333333 0.333333 0 0 0.333333 0.333333 0.333333 0 0 0 0 0 1 0" />
          <feComponentTransfer><feFuncR type="discrete" tableValues="0 1" /><feFuncG type="discrete" tableValues="0 1" /><feFuncB type="discrete" tableValues="0 1" /></feComponentTransfer>
        </>}
      </filter>
    </svg>
    <aside className="cx-sidebar">
      <div className="cx-wordmark"><span className="cx-mark" aria-hidden="true" />CyberScan X</div>
      <nav aria-label="Sections">
        {nav.map(([id, label, icon]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}><Icon name={icon} />{label}</button>)}
      </nav>
      <div className="cx-device" aria-label="Scanner status">
        <span className={'cx-dot ' + (scanning || moving ? 'busy' : ready.ok ? 'ok' : 'off')} />
        <div><strong>{scanning ? 'Scanning' : ready.title}</strong><span>{scanning ? (nativeMode ? 'Direct scanner interface' : 'Through CyberView X') : ready.detail}</span></div>
      </div>
      <p className="cx-sidebar-note">{mode === 'demo' ? 'Sample photos, not scans' : nativeMode ? 'Direct AFL interface · experimental · transmission image' : 'Scans run through CyberView X with its window hidden'}</p>
    </aside>

    <main className="cx-main">
      {view === 'scan' && <>
        <header className="cx-topbar">
          <div className="cx-title">
            <h1>{current ? current.title : 'Scan'}</h1>
            <span className="cx-meta">{current ? (current.demo ? 'Sample image' : `${current.width} × ${current.height} · ${current.dpi} dpi · ${current.bits}-bit · ${shortDate(current.created_at)}`) : 'Load film, then scan the current frame'}</span>
          </div>
          <div className="cx-scanbar">
            <label className="cx-field"><span>Roll</span><input value={roll} maxLength={120} placeholder="Untitled roll" onChange={(e) => setRoll(e.target.value)} disabled={scanning || mode !== 'live'} /></label>
            <label className="cx-field cx-count"><span>Frames</span>
              <select value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={scanning || mode !== 'live'} aria-label="Frames to scan">
                {[1, 2, 3, 4, 6, 12, 24, 36].filter((n) => n <= (status?.max_count ?? 40)).map((n) => <option key={n} value={n}>{n === 1 ? 'Current frame' : `Next ${n}`}</option>)}
              </select>
            </label>
            {alignInfo?.stitched_scan.available && <button className="cx-button" onClick={startStitched} disabled={!ready.ok || scanning} title="Three scans with the film nudged back and forward, stitched and cropped to 36 × 24 mm">{stitchArmed ? `Move film ±${alignInfo.settings.offset_mm} mm and scan?` : 'Stitched scan'}</button>}
            <button className="cx-button primary" onClick={startScan} disabled={!ready.ok || controlsBusy || !!moving || (!!workspace && (!can('scan') || optionsChanged))}><Icon name="scan" />{count === 1 ? 'Scan frame' : `Scan ${count} frames`}</button>
          </div>
        </header>

        <div className="cx-workspace">
          <section className="cx-stage" aria-label="Viewer">
            <div className="cx-viewer">
              {showLive && live
                ? <LivePreview live={live} negative={status?.settings.film_type !== 'positive'} />
                : current
                ? <div className="cx-image" style={{ transform }}>
                    {cropped ? <svg className="cx-cropped-image" role="img" aria-label={`${current.title}, cropped`} width={imageWidth * (crop.right - crop.left)} height={imageHeight * (crop.bottom - crop.top)} viewBox={`${crop.left * imageWidth} ${crop.top * imageHeight} ${(crop.right - crop.left) * imageWidth} ${(crop.bottom - crop.top) * imageHeight}`}>
                      <image href={imageSrc} width={imageWidth} height={imageHeight} preserveAspectRatio="none" filter="url(#cx-adjust)" onError={() => setPreviewError(true)} />
                    </svg> : <img src={imageSrc} alt={current.title} style={{ filter: showOriginal ? 'none' : 'url(#cx-adjust)' }} draggable={false} onError={() => setPreviewError(true)} />}
                  </div>
                : <div className="cx-empty"><Icon name="film" size={24} /><strong>No scans yet</strong><span>{ready.ok ? 'Scan the frame that is in the loader now, or the next several frames in a row.' : ready.detail}</span></div>}
              {session && scanning && <ScanProgress session={session} onCancel={stopScan} now={now} />}
              {previewError && <p className="cx-preview-error" role="alert">The selected film profile preview could not be loaded. Check the profile and try again.</p>}
              {showOriginal && current && !showLive && <span className="cx-original-badge">Original · full frame</span>}
              {current && <span className="cx-edge cx-viewer-edge">{edgeNumber(current.index)}</span>}
            </div>
            <div className="cx-toolbar" role="toolbar" aria-label="View">
              <div className="cx-group">
                <button className="cx-icon" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(.5, +(z - .25).toFixed(2)))}><Icon name="minus" /></button>
                <span className="cx-zoom">{Math.round(zoom * 100)}%</span>
                <button className="cx-icon" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(3, +(z + .25).toFixed(2)))}><Icon name="plus" /></button>
                <button className="cx-icon" aria-label="Fit to window" onClick={() => setZoom(1)}><Icon name="fit" /></button>
              </div>
              <div className="cx-group" role="group" aria-label="Film">
                {/* Only Forward One Frame is offered: CyberView's backward command hung the AFL in testing. */}
                <button className="cx-text-button" disabled={!ready.ok || controlsBusy || !!moving || (workspace ? !can('next') : status?.supports_next === false)} title={workspace && !can('next') ? reason('next') : undefined} onClick={() => workspace ? sendAction('next') : moveFilm()}>Next frame</button>
                {moving && <span className="cx-meta" role="status">{moving}</span>}
              </div>
              <div className="cx-group">
                <button className="cx-icon" aria-label="Rotate 90 degrees" disabled={!current || rollApplying} onClick={() => updateAdjust({ rotation: (adjust.rotation + 90) % 360 })}><Icon name="rotate" /></button>
                <button className="cx-icon" aria-label="Mirror" aria-pressed={adjust.mirror} disabled={!current || rollApplying} onClick={() => updateAdjust({ mirror: !adjust.mirror })}><Icon name="mirror" /></button>
                <button className="cx-icon" aria-label={current?.favorite ? 'Remove from favorites' : 'Add to favorites'} aria-pressed={!!current?.favorite} disabled={!current} onClick={toggleFavorite}><Icon name="star" /></button>
              </div>
            </div>
            <div className="cx-compare-bar"><button className="cx-text-button" aria-pressed={showOriginal} disabled={!current} onClick={() => setShowOriginal((value) => !value)}>{showOriginal ? 'Show adjustments' : 'Show original'}</button><span className="cx-meta">{showOriginal ? 'Original image before edits' : 'Edited preview'}</span></div>
            <div className="cx-strip" aria-label="Frames on this roll">
              {rollCaptures.map((c) => <button key={c.id} className={c.id === current?.id ? 'active' : ''} aria-pressed={c.id === current?.id} aria-label={`Frame ${c.index}, ${c.title}`} onClick={() => setSelected(c.id)}>
                <img src={imageUrl(c, 'thumb')} alt="" loading="lazy" />
                <span className="cx-edge">{c.purpose === 'prescan' ? 'PRE' : edgeNumber(c.index)}</span>
              </button>)}
              {scanning && session && Array.from({ length: session.count - session.completed }, (_, i) => <div key={i} className="cx-strip-pending" aria-hidden="true"><span className="cx-edge">{edgeNumber(rollCaptures.length + i + 1)}</span></div>)}
            </div>
          </section>

          <aside className="cx-inspector" aria-label="Adjustments">
            {/* Only working controls are shown. Everything else stays hidden until it has been
                tested on the scanner (services/scanner_host/native_validation.json). */}
            <details className="cx-scanner-panel" open={nativeMode}>
              <summary><span>Scanner controls</span><span className="cx-meta">{nativeMode ? 'Native capture' : mode === 'demo' ? 'Sample mode' : 'CyberView capture'}</span></summary>
              {mode === 'demo' && <p className="cx-help">Sample photos are shown here. Scanner controls are disabled.</p>}
              {workspaceError && <p className="cx-help" role="status">Scanner settings unavailable: {workspaceError}</p>}
              {!nativeMode && mode !== 'demo' && <p className="cx-help">CyberView capture scans the current frame or the next several, and moves to the next frame from the toolbar. Native capture in Settings adds prescan, focus and film-base controls.</p>}
              {can('prescan') && <button className="cx-button cx-prescan" onClick={startPrescan} disabled={!ready.ok || controlsBusy || !!moving || optionsChanged}>Prescan frame</button>}
              {workspace?.prescan && <button className="cx-last-prescan" onClick={() => setSelected(workspace.prescan?.id || null)}>
                <img src={imageUrl(workspace.prescan, 'thumb')} alt="" /><span><strong>Last prescan</strong><small>View the acquired preview</small></span>
              </button>}
              {(['previous', 'eject_forward', 'eject_backward', 'goto'] as ActionName[]).some(can) && <>
                <div className="cx-control-title">Film transport</div>
                <div className="cx-control-grid">
                  {(['previous', 'eject_forward', 'eject_backward'] as ActionName[]).filter(can).map((action) => <button key={action} className="cx-button" disabled={!ready.ok || controlsBusy || !!moving} onClick={() => setPendingAction(action)}>{ACTION_NAMES[action]}</button>)}
                </div>
                {can('goto') && <label className="cx-inline-number">Frame <input type="number" min="1" max="72" value={targetFrame} onChange={(event) => setTargetFrame(Math.max(1, Math.min(72, Number(event.target.value) || 1)))} disabled={controlsBusy} />
                  <button className="cx-button" type="button" disabled={!ready.ok || controlsBusy || !!moving} onClick={() => setPendingAction('goto')}>Go to frame</button>
                </label>}
              </>}
              {nativeMode && (['next', 'previous', 'goto'] as ActionName[]).some((a) => workspace?.capabilities.actions[a]?.evidence === 'verified_on_device' && !can(a)) &&
                <p className="cx-help">Scan or prescan a frame first; film moves are enabled after one scan in the session.</p>}
              {(['autofocus', 'calibrate', 'focus'] as ActionName[]).some(can) && <>
                <div className="cx-control-title">Focus and film base</div>
                <div className="cx-control-grid">
                  {(['autofocus', 'calibrate'] as ActionName[]).filter(can).map((action) => <button key={action} className="cx-button" disabled={!ready.ok || controlsBusy || !!moving} onClick={() => setPendingAction(action)}>{ACTION_NAMES[action]}</button>)}
                </div>
                {can('focus') && <label className="cx-inline-number">Focus step <input type="number" min="0" max="200" value={targetFocus} onChange={(event) => setTargetFocus(Math.max(0, Math.min(200, Number(event.target.value) || 0)))} disabled={controlsBusy} />
                  <button className="cx-button" type="button" disabled={!ready.ok || controlsBusy || !!moving} onClick={() => setPendingAction('focus')}>Set focus</button>
                </label>}
              </>}
              {nativeMode && <details className="cx-subpanel">
                <summary>Scan settings <span className="cx-meta">{workspace ? `${options.dpi} dpi · ${options.bits}-bit` : ''}</span></summary>
                <p className="cx-help">These settings are applied to acquisition. Unsupported combinations remain unavailable until verified.</p>
                <fieldset disabled={!workspace || controlsBusy || !!moving} className="cx-scan-options">
                  <label>Resolution <select aria-label="Scan resolution" value={options.dpi} onChange={(event) => changeOptions({ dpi: Number(event.target.value) as ScanOptions['dpi'] })}>{(workspace?.capabilities.resolutions || [1800]).map((dpi) => <option value={dpi} key={dpi}>{dpi} dpi</option>)}</select></label>
                  <label>Depth <select aria-label="Scan depth" value={options.bits} onChange={(event) => changeOptions({ bits: Number(event.target.value) as 8 | 16 })}>{(workspace?.capabilities.depths || [16]).map((bits) => <option value={bits} key={bits}>{bits}-bit per channel</option>)}</select></label>
                  <label>Color <select aria-label="Scan color" value={options.channel} onChange={(event) => changeOptions({ channel: event.target.value as ScanOptions['channel'] })}>{(workspace?.capabilities.channels || ['rgb']).map((channel) => <option value={channel} key={channel}>{({rgb:'Color RGB',gray:'Grayscale',bw:'Black and white'} as Record<string,string>)[channel] || channel}</option>)}</select></label>
                  <label>Film <select aria-label="Film type" value={options.film} onChange={(event) => changeOptions({ film: event.target.value as ScanOptions['film'] })}>{(workspace?.capabilities.films || ['negative']).map((film) => <option value={film} key={film}>{film === 'negative' ? 'Negative' : film === 'positive' ? 'Positive / slide' : film}</option>)}</select></label>
                  <div className="cx-option-group"><span>Scan area <small>inches</small></span><div className="cx-area-grid">{(['left','top','right','bottom'] as const).map((edge) => <label key={edge}>{edge}<input aria-label={`Scan area ${edge}`} type="number" min="0" max={edge === 'left' || edge === 'right' ? '1.436666' : '.95'} step=".001" value={options.crop[edge]} onChange={(event) => changeOptions({ crop: { ...options.crop, [edge]: Number(event.target.value) } })} /></label>)}</div></div>
                  <div className="cx-option-group"><span>Scanner exposure <small>per channel · %</small></span><div className="cx-area-grid cx-exposure-grid">{['Red','Green','Blue'].map((name, channel) => <label key={name}>{name}<input aria-label={`${name} scan exposure`} type="number" min="50" max="200" step="1" value={options.exposure[channel]} onChange={(event) => { const exposure = [...options.exposure]; exposure[channel] = Number(event.target.value); changeOptions({ exposure }); }} /></label>)}</div></div>
                </fieldset>
                <button className="cx-button cx-apply-settings" onClick={applyOptions} disabled={!workspace || controlsBusy || !!moving || !optionsChanged}>Apply scan settings</button>
                {optionsChanged && workspace && <p className="cx-help">Apply these changes before scanning or prescanning.</p>}
                {workspace && !can('scan') && <p className="cx-help" role="status">{reason('scan')}</p>}
              </details>}
            </details>
            <div className="cx-panel-head"><h2>Adjust</h2><button className="cx-text-button" onClick={() => updateAdjust({ ...NEUTRAL, rotation: adjust.rotation, mirror: adjust.mirror, invert: adjust.invert, film_base: adjust.film_base, film_profile: adjust.film_profile })} disabled={!current || rollApplying || autoLevelBusy}>Reset</button></div>
            <fieldset disabled={!current || rollApplying || autoLevelBusy}>
              <Slider label="Exposure" value={adjust.exposure} min={-2} max={2} step={.05} unit=" EV" digits={2} onChange={(v) => updateAdjust({ exposure: v })} />
              <Slider label="Contrast" value={adjust.contrast} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ contrast: v })} />
              <Slider label="Saturation" value={adjust.saturation} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ saturation: v })} />
              <Slider label="Temperature" value={adjust.temperature} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ temperature: v })} />
              <label className="cx-native-check"><input type="checkbox" checked={!!adjust.invert} onChange={(e) => updateAdjust({ invert: e.target.checked })} />Invert negative</label>
              <label className="cx-native-check"><input type="checkbox" checked={!!adjust.monochrome} onChange={(e) => updateAdjust({ monochrome: e.target.checked })} />Threshold black and white</label>
              <details className="cx-subpanel cx-image-controls"><summary>Variations</summary>
                <p className="cx-help">Make a small change to the current edit.</p>
                <div className="cx-variations">{['Lighter', 'Darker', 'Warmer', 'Cooler', 'More red', 'More green', 'More blue'].map((kind) => <button type="button" key={kind} className="cx-button" onClick={() => variation(kind)}>{kind}</button>)}</div>
              </details>
              <label className="cx-profile-field">Film rendering profile
                <select aria-label="Film rendering profile" value={adjust.film_profile || ''} disabled={mode !== 'live' || !!current?.demo} onChange={(event) => updateAdjust({ film_profile: event.target.value || null })}>
                  <option value="">None</option>
                  {adjust.film_profile && !profiles.some((profile) => profile.id === adjust.film_profile) && <option value={adjust.film_profile}>Saved profile · {adjust.film_profile.slice(0, 8)}</option>}
                  {profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}{profile.maker ? ` · ${profile.maker}` : ''}</option>)}
                </select>
              </label>
              <p className="cx-help">Profiles apply to this edit. Their color response is an approximation, not a calibrated scanner profile.</p>
              {profileError && <p className="cx-help" role="status">{profileError}</p>}
              {adjust.invert && <>
                <p className="cx-help">Manual film-base transmission. This conversion uses a nominal response, without scanner color calibration.</p>
                {['Red', 'Green', 'Blue'].map((name, channel) => <label key={name} className="cx-base-field">{name} base
                  <input type="number" min="0.01" max="1" step="0.01" value={adjust.film_base?.[channel] ?? 1} onChange={(e) => {
                    const value = Number(e.target.value);
                    if (!Number.isFinite(value) || value < .01 || value > 1) return;
                    const base = [...(adjust.film_base ?? [1, 1, 1])]; base[channel] = value; updateAdjust({ film_base: base });
                  }} />
                </label>)}
              </>}
              <details className="cx-subpanel cx-image-controls">
                <summary>Levels and color</summary>
                <p className="cx-help">Adjust the saved edit; the acquisition stays unchanged.</p>
                {histogram && <div className="cx-histogram" role="img" aria-label="Image red, green and blue histograms before levels">
                  <svg viewBox="0 0 256 70" preserveAspectRatio="none" aria-hidden="true">
                    {histogram.bins.slice(0, 3).map((bins, channel) => {
                      const peak = Math.max(1, ...bins);
                      const points = bins.map((value, index) => `${index},${70 - 68 * Math.log1p(value) / Math.log1p(peak)}`).join(' ');
                      return <polyline key={channel} points={points} className={`cx-histogram-${channel}`} />;
                    })}
                  </svg>
                  <span>Before levels · logarithmic scale</span>
                </div>}
                <button className="cx-button cx-apply-settings" onClick={autoLevels} disabled={!histogram || autoLevelBusy || !current || !!current.demo || mode !== 'live'}>{autoLevelBusy ? 'Calculating…' : 'Auto levels'}</button>
                <label className="cx-level-field"><span>Black point <output>{(adjust.black_point ?? 0).toFixed(2)}</output></span><input aria-label="Black point" type="range" min="0" max=".99" step=".01" value={adjust.black_point ?? 0} onChange={(event) => { const value = Number(event.target.value); if (value < (adjust.white_point ?? 1)) updateAdjust({ black_point: value }); }} /></label>
                <label className="cx-level-field"><span>White point <output>{(adjust.white_point ?? 1).toFixed(2)}</output></span><input aria-label="White point" type="range" min=".01" max="1" step=".01" value={adjust.white_point ?? 1} onChange={(event) => { const value = Number(event.target.value); if (value > (adjust.black_point ?? 0)) updateAdjust({ white_point: value }); }} /></label>
                <label className="cx-level-field"><span>Gamma <output>{(adjust.gamma ?? 1).toFixed(2)}</output></span><input aria-label="Gamma" type="range" min=".1" max="4" step=".05" value={adjust.gamma ?? 1} onChange={(event) => updateAdjust({ gamma: Number(event.target.value) })} /></label>
                <div className="cx-option-group"><span>Color balance</span>
                  {['Red','Green','Blue'].map((name, channel) => <label className="cx-level-field" key={name}><span>{name} <output>{(adjust.rgb_balance?.[channel] ?? 1).toFixed(2)}×</output></span><input aria-label={`${name} color balance`} type="range" min=".25" max="4" step=".05" value={adjust.rgb_balance?.[channel] ?? 1} onChange={(event) => { const values = [...(adjust.rgb_balance || [1,1,1])]; values[channel] = Number(event.target.value); updateAdjust({ rgb_balance: values }); }} /></label>)}
                </div>
                <div className="cx-option-group"><span>Tone curve <small>shadow → highlight</small></span>
                  <svg className="cx-curve" viewBox="0 0 100 100" role="img" aria-label="Tone curve preview">
                    <path d="M 0 100 L 100 0" className="cx-curve-reference" />
                    <polyline points={(adjust.curve || [0,.25,.5,.75,1]).map((value, index) => `${index * 25},${100 - value * 100}`).join(' ')} />
                  </svg>
                  <div className="cx-area-grid cx-curve-grid">{(adjust.curve || [0,.25,.5,.75,1]).map((value, index, points) => <label key={index}>{['Black','Shadow','Mid','Light','White'][index]}<input aria-label={`Tone curve ${['black','shadow','mid','light','white'][index]}`} type="number" min={index ? points[index - 1] : 0} max={index < 4 ? points[index + 1] : 1} step=".01" value={value} onChange={(event) => { const next = Number(event.target.value); if (!Number.isFinite(next) || next < (index ? points[index - 1] : 0) || next > (index < 4 ? points[index + 1] : 1)) return; const curve = [...points]; curve[index] = next; updateAdjust({ curve }); }} /></label>)}</div>
                </div>
              </details>
              <details className="cx-subpanel cx-image-controls">
                <summary>Crop image</summary>
                <div className="cx-align">
                  <button type="button" className="cx-button" onClick={autoAlign} disabled={!current || current.demo || mode !== 'live' || aligning}>{aligning ? 'Aligning…' : 'Auto align 35 mm'}</button>
                  <label className="cx-inline-number">Bleed <input aria-label="Crop bleed in millimetres" type="number" min="-2" max="2" step=".25" value={alignInfo?.settings.bleed_mm ?? 0} disabled={!alignInfo} onChange={(event) => { const v = Number(event.target.value); if (Number.isFinite(v) && v >= -2 && v <= 2) saveAlign({ bleed_mm: v }); }} /> mm</label>
                </div>
                <p className="cx-help">Finds the frame edges and crops exactly {36 + 2 * (alignInfo?.settings.bleed_mm ?? 0)} × {24 + 2 * (alignInfo?.settings.bleed_mm ?? 0)} mm. Negative bleed trims inside the edges.</p>
                {current?.alignment && <p className="cx-help" role="status">{ALIGN_LABEL[current.alignment.confidence]}{current.alignment.exact ? ` · ${current.alignment.crop_mm.join(' × ')} mm` : ''}{current.alignment.skew_deg != null ? ` · skew ${current.alignment.skew_deg.toFixed(2)}°` : ''}{current.alignment.note ? `. ${current.alignment.note}` : ''}</p>}
                <label className="cx-native-check"><input type="checkbox" checked={!!alignInfo?.settings.auto} disabled={!alignInfo} onChange={(e) => saveAlign({ auto: e.target.checked })} />Align new scans automatically</label>
                <p className="cx-help">Manual crop, in percent of the scan. The original stays intact.</p>
                <div className="cx-area-grid">{(['left','top','right','bottom'] as const).map((edge) => <label key={edge}>{edge} %<input aria-label={`Image crop ${edge} percent`} type="number" min="0" max="100" step="1" value={Math.round(crop[edge] * 100)} onChange={(event) => {
                  const value = Number(event.target.value) / 100;
                  if (!Number.isFinite(value) || value < 0 || value > 1) return;
                  const next = { ...crop, [edge]: value };
                  if (next.left >= next.right || next.top >= next.bottom) return;
                  updateAdjust({ crop: next });
                }} /></label>)}</div>
                <button type="button" className="cx-text-button" onClick={() => updateAdjust({ crop: { left: 0, top: 0, right: 1, bottom: 1 } })}>Reset crop</button>
              </details>
            </fieldset>
            <p className="cx-help">Applied to previews and exports. The original TIFF is never changed.</p>
            <button className="cx-button cx-apply-settings" disabled={!current || !!current.demo || mode !== 'live' || rollApplying} onClick={() => setConfirmRoll(true)}>{rollApplying ? 'Applying color…' : 'Apply color to roll'}</button>

            <div className="cx-panel-head"><h2>Export</h2></div>
            <div className="cx-exports">
              {([['original', 'Original TIFF', current?.image_kind === 'vendor-calibrated-transmission' ? `Unchanged transmission, ${current.bits}-bit` : `As delivered by CyberView, ${current?.bits ?? 16}-bit`], ['tiff', 'Adjusted TIFF', '16-bit with your adjustments'], ['jpeg', 'Adjusted JPEG', '8-bit for sharing'], ['metadata', 'Edit metadata', 'JSON recipe and acquisition details']] as const).map(([fmt, label, hint]) =>
                current && !current.demo && mode === 'live'
                  ? <a key={fmt} className="cx-export" href={`/api/cyberview/captures/${current.id}/export/${fmt}`} download onClick={(event) => exportCapture(event, current, fmt)}><Icon name="download" /><span><strong>{label}</strong><small>{hint}</small></span></a>
                  : <span key={fmt} className="cx-export disabled" aria-disabled="true"><Icon name="download" /><span><strong>{label}</strong><small>{current?.demo ? 'Not available for samples' : hint}</small></span></span>)}
            </div>

            {current && !current.demo && <>
              <div className="cx-panel-head"><h2>Original</h2></div>
              <dl className="cx-facts">
                <dt>Size</dt><dd>{current.width} × {current.height}</dd>
                <dt>Resolution</dt><dd>{current.dpi} dpi</dd>
                <dt>Depth</dt><dd>{current.bits}-bit per channel</dd>
                {current.image_kind === 'vendor-calibrated-transmission' && <><dt>Original</dt><dd>Transmission · not inverted</dd></>}
                <dt>Film term</dt><dd>{current.cyberview?.film_term || 'Unknown'}</dd>
                <dt>Auto exposure</dt><dd>{current.cyberview?.auto_exposure == null ? 'Unmeasured' : current.cyberview.auto_exposure ? 'On' : 'Off'}</dd>
                <dt>SHA-256</dt><dd title={current.sha256}>{current.sha256.slice(0, 12)}</dd>
              </dl>
            </>}
          </aside>
        </div>
      </>}

      {view === 'library' && <section className="cx-page">
        <header className="cx-page-head"><h1>Library</h1><span className="cx-meta">{captures.length} {captures.length === 1 ? 'frame' : 'frames'}</span></header>
        {captures.length === 0 && <p className="cx-help">Scans appear here once saved.</p>}
        {Object.entries(captures.reduce<Record<string, Capture[]>>((groups, c) => { (groups[c.roll || 'Untitled roll'] ||= []).push(c); return groups; }, {})).map(([name, list]) =>
          <div key={name} className="cx-roll">
            <h2>{name}<span className="cx-meta">{list.length} · {shortDate(list[0].created_at)}</span></h2>
            <div className="cx-grid">
              {list.map((c) => <button key={c.id} onClick={() => { setSelected(c.id); setView('scan'); }} aria-label={`Open ${c.title}`}>
                <img src={imageUrl(c, 'thumb')} alt="" loading="lazy" />
                <span><span className="cx-edge">{edgeNumber(c.index)}</span>{c.favorite && <Icon name="star" size={14} />}</span>
              </button>)}
            </div>
          </div>)}
      </section>}

      {view === 'settings' && <section className="cx-page">
        <header className="cx-page-head"><h1>Settings</h1></header>
        <div className="cx-settings">
          <section>
            <h2>{nativeMode ? 'Native acquisition' : 'CyberView X'}</h2>
            <p className="cx-help">{nativeMode ? 'Current-frame transmission capture with an identity table. Vendor calibration remains active. Color conversion and additional controls are still under test.' : 'Scans use the settings saved in CyberView. To change them, open CyberView X, adjust, scan once and close it.'}</p>
            <dl className="cx-facts">
              <dt>Film term</dt><dd>{status?.settings.film_term || '—'}</dd>
              <dt>Auto exposure</dt><dd>{status?.settings.auto_exposure == null ? 'Unmeasured' : status.settings.auto_exposure ? 'On' : 'Off'}</dd>
              <dt>Auto gamma</dt><dd>{status ? (status.settings.auto_gamma ? 'On' : 'Off') : '—'}</dd>
              <dt>Crop</dt><dd>{status?.settings.crop_inches ? status.settings.crop_inches.map((v) => v.toFixed(2)).join(', ') + ' in' : '—'}</dd>
            </dl>
          </section>
          <section>
            <h2>Scanner</h2>
            <dl className="cx-facts">
              <dt>Status</dt><dd>{ready.title}</dd>
              <dt>Output</dt><dd>{nativeMode && workspace ? `${workspace.settings.dpi} dpi, ${workspace.settings.bits}-bit ${workspace.settings.channel.toUpperCase()} TIFF` : '1800 dpi, 16-bit RGB TIFF'}</dd>
              <dt>Driver</dt><dd>{nativeMode ? 'Direct AFL module · experimental' : 'CyberView X - MF (TWAIN)'}</dd>
              <dt>Bridge</dt><dd>{status ? (status.bridge_built ? 'Built' : 'Not built') : '—'}</dd>
              <dt>Automatic recovery</dt><dd>{status ? (status.auto_reset ? 'On' : 'Off') : '—'}</dd>
            </dl>
            <p className="cx-help">{nativeMode ? 'Native capture requests cancellation if the driver stops responding and reserves the session until the driver returns.' : status?.auto_reset
              ? 'If a scan stalls at "Preparing film scanner", CyberScan X restarts the scanner’s USB connection and continues.'
              : 'If a scan never starts, the scanner may be stuck at "Preparing film scanner". Turn it off and on, or run scripts\\install-scanner-reset.ps1 once as administrator so CyberScan X can restart it for you.'}</p>
          </section>
          {diagnostics?.scanner && <section>
            <h2>Scanner diagnostics</h2>
            <p className="cx-help">From the scanner driver's own log and calibration cache. Read only; nothing is sent to the scanner.</p>
            {diagnostics.scanner.log ? <dl className="cx-facts">
              <dt>Model</dt><dd>{diagnostics.scanner.log.header.model ?? '—'} · firmware {diagnostics.scanner.log.header.firmware ?? '—'}</dd>
              <dt>Sensor</dt><dd>CCD {diagnostics.scanner.log.header.ccd ?? '—'}</dd>
              <dt>Connection</dt><dd>{diagnostics.scanner.log.header.usb ?? '—'}</dd>
              <dt>Lamp level</dt><dd>{diagnostics.scanner.log.lamp_calibration.final_level ?? '—'} after {diagnostics.scanner.log.lamp_calibration.steps} calibration steps</dd>
              <dt>Scans logged</dt><dd>{diagnostics.scanner.log.scans_logged} · {shortDate(diagnostics.scanner.log.updated_at)}</dd>
              {diagnostics.scanner.log.last_scan && <>
                <dt>Last scan</dt><dd>{diagnostics.scanner.log.last_scan.film_type} · {diagnostics.scanner.log.last_scan.film_media}</dd>
                <dt>Colour balance</dt><dd>{diagnostics.scanner.log.last_scan.color_balance?.join(' / ') ?? '—'}</dd>
                <dt>Focus step</dt><dd>{diagnostics.scanner.log.last_scan.focus_step ?? '—'}</dd>
                <dt>Gain · black level</dt><dd>{diagnostics.scanner.log.last_scan.gain?.join('/') ?? '—'} · {diagnostics.scanner.log.last_scan.dc?.join('/') ?? '—'}</dd>
              </>}
              <dt>Calibration cache</dt><dd>{diagnostics.scanner.calibration_cache ? `${diagnostics.scanner.calibration_cache.age_hours} h old` : 'Not present · next scan calibrates'}</dd>
            </dl> : <p className="cx-help">No driver log yet. It appears after the first scan.</p>}
          </section>}
          <section>
            <h2>Native scanner integration</h2>
            <p className="cx-help">Native capture drives the scanner's own module without CyberView. This page reads installed files and the driver's log; it never starts or moves the scanner.</p>
            {diagnosticError && <p className="cx-help" role="alert">{diagnosticError}</p>}
            {diagnostics && <>
              <dl className="cx-facts">
                <dt>AFL module</dt><dd>{diagnostics.native_module_recognized ? 'Recognized · 1.0.3.6' : 'Unrecognized or missing'}</dd>
                <dt>Native bridge</dt><dd>{diagnostics.native_bridge_built ? (diagnostics.native_device_validation === 'current_frame_verified' ? 'Built · current frame tested' : 'Built · device testing pending') : 'Not built'}</dd>
                <dt>Device access</dt><dd>{nativeMode ? 'Direct AFL module · experimental' : 'Existing CyberView bridge'}</dd>
              </dl>
              <p className="cx-help">{diagnostics.native_note}</p>
              {!nativeMode && <label className="cx-native-check"><input type="checkbox" checked={nativeAcknowledged} onChange={(e) => setNativeAcknowledged(e.target.checked)} />I understand native startup may move film. Available transport and scan controls depend on device verification; originals are saved as transmission data.</label>}
              <button className="cx-button cx-release" disabled={mode !== 'live' || scanning || !!moving || switchingBackend || (!nativeMode && (!nativeAcknowledged || !diagnostics.native_bridge_built || !diagnostics.native_module_recognized))}
                onClick={() => selectBackend(nativeMode ? 'cyberview-twain' : 'afl-native-experimental')}>
                {switchingBackend ? 'Changing interface…' : nativeMode ? 'Use CyberView capture' : 'Use native capture'}
              </button>
              <details className="cx-discoveries"><summary>Scanner features and findings</summary>
                {diagnostics.features.map((feature) => <div key={feature.id} className="cx-discovery">
                  <strong>{feature.name}</strong>
                  <span className="cx-meta">{({ verified_on_device: 'Verified on this scanner', recorded_on_device: 'Tested in native capture', observed_vendor_call: 'Observed during a scan', static_only: 'Found in the driver · untested', unavailable: 'Unavailable' } satisfies Record<ScannerEvidence, string>)[feature.evidence]}</span>
                  <p className="cx-help">{feature.detail}</p>
                </div>)}
              </details>
              <details className="cx-discoveries"><summary>Installed driver files</summary>
                {diagnostics.files.map((file) => <div key={file.name} className="cx-discovery">
                  <strong>{file.name}</strong><span className="cx-meta">{file.installed ? `${file.bytes?.toLocaleString()} bytes` : 'Not installed'}</span>
                  {file.sha256 && <code className="cx-driver-hash">{file.sha256}</code>}
                </div>)}
              </details>
            </>}
            {mode === 'demo' && <p className="cx-help">Installation inspection is available in the live application.</p>}
          </section>
          <section>
            <h2>Driver session</h2>
            <p className="cx-help">CyberScan X keeps the scanner driver open between captures. Release it before opening CyberView X or changing scanner software.</p>
            <dl className="cx-facts"><dt>Session</dt><dd>{status?.session_open ? 'Open' : 'Closed'}</dd></dl>
            <button className="cx-button cx-release" disabled={mode !== 'live' || !status?.session_open || scanning}
              onClick={() => api<Status>('/api/cyberview/release', { method: 'POST' }).then(() => refresh()).then(() => setMessage({ text: 'Scanner released. CyberView X can be opened now.', tone: 'info' })).catch((e: Error) => setMessage({ text: e.message, tone: 'error' }))}>
              Release scanner
            </button>
          </section>
        </div>
      </section>}
    </main>

    {message && <div className={'cx-toast ' + message.tone} role={message.tone === 'error' ? 'alert' : 'status'}>
      <Icon name={message.tone === 'error' ? 'alert' : 'check'} /><span>{message.text}</span>
      <button className="cx-icon" aria-label="Dismiss" onClick={() => setMessage(null)}><Icon name="close" /></button>
    </div>}
    {pendingAction && <div className="cx-modal-shade" onClick={() => setPendingAction(null)}>
      <div className="cx-modal" role="dialog" aria-modal="true" aria-labelledby="cx-action-title" onClick={(event) => event.stopPropagation()}>
        <h2 id="cx-action-title">{ACTION_NAMES[pendingAction]}?</h2>
        <p>This action operates the scanner. Check that the film path is clear and stay near the scanner while it runs.</p>
        {(pendingAction === 'eject_forward' || pendingAction === 'eject_backward') && <p>Keep hold of the film as it leaves the scanner.</p>}
        <div><button className="cx-button" autoFocus onClick={() => setPendingAction(null)}>Cancel</button><button className="cx-button primary" onClick={() => sendAction(pendingAction, true)}>Continue</button></div>
      </div>
    </div>}
    {confirmRoll && <div className="cx-modal-shade" onClick={() => setConfirmRoll(false)}>
      <div className="cx-modal" role="dialog" aria-modal="true" aria-labelledby="cx-roll-color-title" onClick={(event) => event.stopPropagation()}>
        <h2 id="cx-roll-color-title">Apply color to roll?</h2>
        <p>This replaces color adjustments on {current?.roll ? `the roll “${current.roll}”` : 'the current scan session'}. Each frame keeps its crop, rotation and mirror. Originals remain unchanged.</p>
        <div><button className="cx-button" autoFocus onClick={() => setConfirmRoll(false)}>Cancel</button><button className="cx-button primary" onClick={applyRollColor}>Apply color</button></div>
      </div>
    </div>}
  </div>;
}
