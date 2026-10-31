import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './cyberscan.css';

// CyberScan X: a modern front end for CyberView X. Live mode talks to the local FRAME
// service, which drives CyberView's own TWAIN driver with its window hidden. Demo mode
// (?demo=1, used by the static preview) makes no network requests at all.

type Adjust = { exposure: number; contrast: number; saturation: number; temperature: number; rotation: number; mirror: boolean };
type Capture = {
  id: string; index: number; title: string; roll: string; created_at: number; width: number; height: number;
  bits: number; dpi: number; sha256: string; favorite: boolean; adjustments: Adjust; demo?: boolean; src?: string;
  cyberview?: Settings;
};
type Settings = { found: boolean; film_term?: string | null; auto_exposure?: boolean; auto_gamma?: boolean; scan_depth?: number; crop_inches?: number[] | null };
type Session = {
  id: string; state: 'starting' | 'warming' | 'advancing' | 'recovering' | 'scanning' | 'saving' | 'cancelling' | 'complete' | 'cancelled' | 'error';
  count: number; completed: number; frame: number; rows: number; height: number; started_at: number; roll: string; error: string | null;
  driver_status?: string | null; driver_dialog?: string | null;
};
type Status = { bridge_built: boolean; busy: boolean; session_open: boolean; auto_reset: boolean; vendor_open: boolean; scanner_present: boolean | null; settings: Settings; session: Session | null };
type View = 'scan' | 'library' | 'settings';
type IconName = 'scan' | 'library' | 'settings' | 'rotate' | 'mirror' | 'download' | 'stop' | 'star' | 'reset' | 'alert' | 'check' | 'film' | 'minus' | 'plus' | 'fit' | 'close';

const NEUTRAL: Adjust = { exposure: 0, contrast: 0, saturation: 0, temperature: 0, rotation: 0, mirror: false };
const DEMO: Capture[] = [
  ['forest', 'Forest'], ['coast', 'Coast'], ['street', 'Street'],
].map(([id, name], i) => ({
  id, index: i + 1, title: name, roll: 'Sample images', created_at: 0, width: 0, height: 0, bits: 8, dpi: 0,
  sha256: '', favorite: false, adjustments: NEUTRAL, demo: true, src: `/demo/${id}.jpg`,
}));
const ACTIVE = new Set(['starting', 'warming', 'advancing', 'recovering', 'scanning', 'saving', 'cancelling']);

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
  const gains = [scale * (1 + .15 * t), scale, scale * (1 - .15 * t)];
  const s = 1 + a.saturation / 100, k = 1 + a.contrast / 100, luma = [.2126, .7152, .0722], offset = .5 * (1 - k);
  const rows = [0, 1, 2].map((i) => [0, 1, 2].map((j) => k * ((1 - s) * luma[j] + (i === j ? s : 0)) * gains[j]));
  return rows.map((r) => [...r.map((v) => v.toFixed(4)), '0', offset.toFixed(4)].join(' ')).join(' ') + ' 0 0 0 1 0';
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
        else if (event.type === 'cyberview_capture') setCaptures((list) => list.some((c) => c.id === event.capture.id) ? list : [...list, event.capture]);
      };
      socket.onclose = () => { if (!closed) timer = window.setTimeout(connect, 2000); };
    };
    (async () => {
      try {
        await api('/api/auth/local', { method: 'POST' });
        const [, list] = await Promise.all([refresh(), api<{ captures: Capture[] }>('/api/cyberview/captures')]);
        setCaptures(list.captures);
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

  return { mode, status, captures, setCaptures, session, setSession, refresh };
}

function readiness(mode: string, status: Status | null) {
  if (mode === 'demo') return { ok: false, title: 'Sample mode', detail: 'Scanning is off in this preview' };
  if (mode === 'connecting') return { ok: false, title: 'Connecting', detail: 'Starting the local service' };
  if (mode === 'offline' || !status) return { ok: false, title: 'Service unavailable', detail: 'Start FRAME, then reload' };
  if (!status.bridge_built) return { ok: false, title: 'Bridge not built', detail: 'Run services/cyberview_bridge/build.ps1' };
  if (status.vendor_open) return { ok: false, title: 'CyberView is open', detail: 'Close it to scan from here' };
  if (status.session_open) return { ok: true, title: 'PrimeFilm 1800 AFL', detail: 'Ready · lamp warm' };
  if (status.scanner_present === false) return { ok: false, title: 'Scanner not found', detail: 'Check power and USB' };
  if (!status.settings.found) return { ok: false, title: 'CyberView not set up', detail: 'Open CyberView once, then close it' };
  return { ok: true, title: 'PrimeFilm 1800 AFL', detail: 'Ready · film in the loader' };
}

function ScanProgress({ session, onCancel, now }: { session: Session; onCancel: () => void; now: number }) {
  const elapsed = Math.max(0, Math.round((now - session.started_at) / 1000));
  const fraction = session.height ? session.rows / session.height : 0;
  // Most of a frame's time is CyberView scanning internally; lines arrive in the last seconds.
  const driverScanning = /^scanning/i.test(session.driver_status || '');
  const label = {
    starting: 'Starting CyberView',
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
          : 'The lamp warms up and the loader finds the frame. The first frame takes two to three minutes.')}
        {!session.driver_dialog && session.state === 'scanning' && (session.rows
          ? `${session.rows.toLocaleString()} of ${session.height.toLocaleString()} lines · 1800 dpi, 16-bit`
          : session.driver_status?.replace(/\.{2,}$/, '') || 'CyberView is scanning the frame')}
        {session.state === 'starting' && 'Loading the driver with its window hidden'}
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
  const { mode, status, captures, setCaptures, session, setSession, refresh } = useScanner(demo);
  const [view, setView] = useState<View>('scan');
  const [selected, setSelected] = useState<string | null>(null);
  const [count, setCount] = useState(1);
  const [roll, setRoll] = useState('');
  const [zoom, setZoom] = useState(1);
  const [message, setMessage] = useState<{ text: string; tone: 'info' | 'error' } | null>(null);
  const [now, setNow] = useState(Date.now());
  const saveTimer = useRef(0);

  const current = captures.find((c) => c.id === selected) || captures[captures.length - 1] || null;
  const adjust = current?.adjustments || NEUTRAL;
  const ready = readiness(mode, status);
  const scanning = !!session && ACTIVE.has(session.state);
  const matrix = useMemo(() => colorMatrix(adjust), [adjust]);
  const rollCaptures = useMemo(() => {
    if (!current) return captures;
    return captures.filter((c) => c.roll === current.roll);
  }, [captures, current]);

  useEffect(() => { if (!scanning) return; const id = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(id); }, [scanning]);
  // Announce only sessions seen running here, not a finished one loaded at startup.
  const watched = useRef<string | null>(null);
  useEffect(() => {
    if (!session) return;
    if (ACTIVE.has(session.state)) { watched.current = session.id; return; }
    if (watched.current !== session.id) return;
    watched.current = null;
    if (session.state === 'error' && session.error) setMessage({ text: session.error, tone: 'error' });
    if (session.state === 'complete') setMessage({ text: `${session.completed} ${session.completed === 1 ? 'frame' : 'frames'} saved as 16-bit originals`, tone: 'info' });
  }, [session?.id, session?.state, session?.error, session?.completed]);
  useEffect(() => { setZoom(1); }, [current?.id]);

  const updateAdjust = (patch: Partial<Adjust>) => {
    if (!current) return;
    const next = { ...current.adjustments, ...patch };
    setCaptures((list) => list.map((c) => c.id === current.id ? { ...c, adjustments: next } : c));
    if (mode !== 'live' || current.demo) return;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      api(`/api/cyberview/captures/${current.id}`, { method: 'PATCH', body: JSON.stringify({ adjustments: next }) })
        .catch((e: Error) => setMessage({ text: e.message, tone: 'error' }));
    }, 300);
  };
  const toggleFavorite = () => {
    if (!current) return;
    const favorite = !current.favorite;
    setCaptures((list) => list.map((c) => c.id === current.id ? { ...c, favorite } : c));
    if (mode === 'live' && !current.demo) api(`/api/cyberview/captures/${current.id}`, { method: 'PATCH', body: JSON.stringify({ favorite }) }).catch(() => undefined);
  };
  const startScan = async () => {
    try {
      setMessage(null);
      const started = await api<Session>('/api/cyberview/scan', { method: 'POST', body: JSON.stringify({ count, roll }) });
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
  const stopScan = () => api<Session>('/api/cyberview/cancel', { method: 'POST' }).then(setSession).catch((e: Error) => setMessage({ text: e.message, tone: 'error' }));

  const nav: [View, string, IconName][] = [['scan', 'Scan', 'scan'], ['library', 'Library', 'library'], ['settings', 'Settings', 'settings']];
  const transform = `scale(${zoom}) rotate(${adjust.rotation}deg) scaleX(${adjust.mirror ? -1 : 1})`;

  return <div className="cx-app">
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <filter id="cx-adjust" colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values={matrix} /></filter>
    </svg>
    <aside className="cx-sidebar">
      <div className="cx-wordmark"><span className="cx-mark" aria-hidden="true" />CyberScan X</div>
      <nav aria-label="Sections">
        {nav.map(([id, label, icon]) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}><Icon name={icon} />{label}</button>)}
      </nav>
      <div className="cx-device" aria-label="Scanner status">
        <span className={'cx-dot ' + (scanning || moving ? 'busy' : ready.ok ? 'ok' : 'off')} />
        <div><strong>{scanning ? 'Scanning' : ready.title}</strong><span>{scanning ? 'Through CyberView X' : ready.detail}</span></div>
      </div>
      <p className="cx-sidebar-note">{mode === 'demo' ? 'Sample photos, not scans' : 'Scans run through CyberView X with its window hidden'}</p>
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
                {[1, 2, 3, 4, 6, 12, 24, 36].map((n) => <option key={n} value={n}>{n === 1 ? 'Current frame' : `Next ${n}`}</option>)}
              </select>
            </label>
            <button className="cx-button primary" onClick={startScan} disabled={!ready.ok || scanning}><Icon name="scan" />{count === 1 ? 'Scan frame' : `Scan ${count} frames`}</button>
          </div>
        </header>

        <div className="cx-workspace">
          <section className="cx-stage" aria-label="Viewer">
            <div className="cx-viewer">
              {current
                ? <div className="cx-image" style={{ transform }}>
                    <img src={imageUrl(current, 'preview')} alt={current.title} style={{ filter: 'url(#cx-adjust)' }} draggable={false} />
                  </div>
                : <div className="cx-empty"><Icon name="film" size={24} /><strong>No scans yet</strong><span>{ready.ok ? 'Scan the frame that is in the loader now, or the next several frames in a row.' : ready.detail}</span></div>}
              {session && scanning && <ScanProgress session={session} onCancel={stopScan} now={now} />}
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
                <button className="cx-text-button" disabled={!ready.ok || scanning || !!moving} onClick={moveFilm}>Next frame</button>
                {moving && <span className="cx-meta" role="status">{moving}</span>}
              </div>
              <div className="cx-group">
                <button className="cx-icon" aria-label="Rotate 90 degrees" disabled={!current} onClick={() => updateAdjust({ rotation: (adjust.rotation + 90) % 360 })}><Icon name="rotate" /></button>
                <button className="cx-icon" aria-label="Mirror" aria-pressed={adjust.mirror} disabled={!current} onClick={() => updateAdjust({ mirror: !adjust.mirror })}><Icon name="mirror" /></button>
                <button className="cx-icon" aria-label={current?.favorite ? 'Remove from favorites' : 'Add to favorites'} aria-pressed={!!current?.favorite} disabled={!current} onClick={toggleFavorite}><Icon name="star" /></button>
              </div>
            </div>
            <div className="cx-strip" aria-label="Frames on this roll">
              {rollCaptures.map((c) => <button key={c.id} className={c.id === current?.id ? 'active' : ''} aria-pressed={c.id === current?.id} aria-label={`Frame ${c.index}, ${c.title}`} onClick={() => setSelected(c.id)}>
                <img src={imageUrl(c, 'thumb')} alt="" loading="lazy" />
                <span className="cx-edge">{edgeNumber(c.index)}</span>
              </button>)}
              {scanning && session && Array.from({ length: session.count - session.completed }, (_, i) => <div key={i} className="cx-strip-pending" aria-hidden="true"><span className="cx-edge">{edgeNumber(rollCaptures.length + i + 1)}</span></div>)}
            </div>
          </section>

          <aside className="cx-inspector" aria-label="Adjustments">
            <div className="cx-panel-head"><h2>Adjust</h2><button className="cx-text-button" onClick={() => updateAdjust({ ...NEUTRAL, rotation: adjust.rotation, mirror: adjust.mirror })} disabled={!current}>Reset</button></div>
            <fieldset disabled={!current}>
              <Slider label="Exposure" value={adjust.exposure} min={-2} max={2} step={.05} unit=" EV" digits={2} onChange={(v) => updateAdjust({ exposure: v })} />
              <Slider label="Contrast" value={adjust.contrast} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ contrast: v })} />
              <Slider label="Saturation" value={adjust.saturation} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ saturation: v })} />
              <Slider label="Temperature" value={adjust.temperature} min={-100} max={100} step={1} onChange={(v) => updateAdjust({ temperature: v })} />
            </fieldset>
            <p className="cx-help">Applied to previews and exports. The original TIFF is never changed.</p>

            <div className="cx-panel-head"><h2>Export</h2></div>
            <div className="cx-exports">
              {([['original', 'Original TIFF', 'As delivered by CyberView, 16-bit'], ['tiff', 'Adjusted TIFF', '16-bit with your adjustments'], ['jpeg', 'Adjusted JPEG', '8-bit for sharing']] as const).map(([fmt, label, hint]) =>
                current && !current.demo && mode === 'live'
                  ? <a key={fmt} className="cx-export" href={`/api/cyberview/captures/${current.id}/export/${fmt}`} download><Icon name="download" /><span><strong>{label}</strong><small>{hint}</small></span></a>
                  : <span key={fmt} className="cx-export disabled" aria-disabled="true"><Icon name="download" /><span><strong>{label}</strong><small>{current?.demo ? 'Not available for samples' : hint}</small></span></span>)}
            </div>

            {current && !current.demo && <>
              <div className="cx-panel-head"><h2>Original</h2></div>
              <dl className="cx-facts">
                <dt>Size</dt><dd>{current.width} × {current.height}</dd>
                <dt>Resolution</dt><dd>{current.dpi} dpi</dd>
                <dt>Depth</dt><dd>{current.bits}-bit RGB</dd>
                <dt>Film term</dt><dd>{current.cyberview?.film_term || 'Unknown'}</dd>
                <dt>Auto exposure</dt><dd>{current.cyberview?.auto_exposure ? 'On' : 'Off'}</dd>
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
            <h2>CyberView X</h2>
            <p className="cx-help">Scans use the settings saved in CyberView. To change them, open CyberView X, adjust, scan once and close it.</p>
            <dl className="cx-facts">
              <dt>Film term</dt><dd>{status?.settings.film_term || '—'}</dd>
              <dt>Auto exposure</dt><dd>{status ? (status.settings.auto_exposure ? 'On' : 'Off') : '—'}</dd>
              <dt>Auto gamma</dt><dd>{status ? (status.settings.auto_gamma ? 'On' : 'Off') : '—'}</dd>
              <dt>Crop</dt><dd>{status?.settings.crop_inches ? status.settings.crop_inches.map((v) => v.toFixed(2)).join(', ') + ' in' : '—'}</dd>
            </dl>
          </section>
          <section>
            <h2>Scanner</h2>
            <dl className="cx-facts">
              <dt>Status</dt><dd>{ready.title}</dd>
              <dt>Output</dt><dd>1800 dpi, 16-bit RGB TIFF</dd>
              <dt>Driver</dt><dd>CyberView X - MF (TWAIN)</dd>
              <dt>Bridge</dt><dd>{status ? (status.bridge_built ? 'Built' : 'Not built') : '—'}</dd>
              <dt>Automatic recovery</dt><dd>{status ? (status.auto_reset ? 'On' : 'Off') : '—'}</dd>
            </dl>
            <p className="cx-help">{status?.auto_reset
              ? 'If a scan stalls at "Preparing film scanner", CyberScan X restarts the scanner’s USB connection and continues.'
              : 'If a scan never starts, the scanner may be stuck at "Preparing film scanner". Turn it off and on, or run scripts\\install-scanner-reset.ps1 once as administrator so CyberScan X can restart it for you.'}</p>
          </section>
          <section>
            <h2>Driver session</h2>
            <p className="cx-help">After the first scan, CyberScan X keeps CyberView's driver open so later frames start sooner. Release it before opening CyberView X itself.</p>
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
  </div>;
}
