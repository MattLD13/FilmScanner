import React, { useEffect, useRef, useState } from 'react';

export type Window = { left: number; top: number; width: number; height: number };
export type PrescanFrame = { index: number; preview_path: string };
export type Prescan = { at: number; media: string; frame_count: number; frames: PrescanFrame[]; film_profile?: string | null };
export type Profile = { id: string; name: string; maker: string; film_class: string; rows: number; source_folder: string };
export type WorkspaceState = { dpi: number; bitDepth: number; gains: number[]; window: Window | null; profile: string; selected: number[]; viewing: number };

export const initialWorkspace: WorkspaceState = { dpi: 1800, bitDepth: 8, gains: [1, 1, 1], window: null, profile: '', selected: [], viewing: 1 };
const DPI = [300, 600, 900, 1200, 1800];
const CLASSES: Record<string, string> = { negative: 'Color negative', reversal: 'Slide (reversal)', bw: 'Black & white' };
const round = (v: number) => Math.round(v * 1000) / 1000;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Fields added to POST /api/scans. Without a prescan only settings are sent, so the plain roll flow is unchanged. */
export function scanRequest(ws: WorkspaceState, prescan?: Prescan) {
  const settings = { dpi: ws.dpi, bit_depth: ws.bitDepth, gains: ws.gains, window: ws.window, film_profile: ws.profile || null };
  if (!prescan) return { settings };
  const all = ws.selected.length === prescan.frame_count;
  return { frame_count: prescan.frame_count, media: prescan.media, settings, ...(all ? {} : { frames: ws.selected }) };
}

type Props = {
  ws: WorkspaceState; setWs: (update: (ws: WorkspaceState) => WorkspaceState) => void;
  prescan?: Prescan; connected: boolean; busy: boolean; media: (path: string) => string;
};

export function ScanWorkspace({ ws, setWs, prescan, connected, busy, media }: Props) {
  const [profiles, setProfiles] = useState<{ profiles: Profile[]; sources: string[] } | null>(null);
  const [draft, setDraft] = useState<Window | null>(null);
  const origin = useRef<{ x: number; y: number } | null>(null);
  const viewer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!connected) return;
    fetch('/api/film-profiles', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).then(setProfiles).catch(() => setProfiles(null));
  }, [connected]);
  useEffect(() => {
    if (prescan) setWs(w => ({ ...w, selected: prescan.frames.map(f => f.index), viewing: prescan.frames[0]?.index ?? 1 }));
  }, [prescan?.at]);

  const point = (e: React.PointerEvent) => {
    const box = viewer.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - box.left) / box.width, 0, 1), y: clamp((e.clientY - box.top) / box.height, 0, 1) };
  };
  const rect = (a: { x: number; y: number }, b: { x: number; y: number }): Window =>
    ({ left: round(Math.min(a.x, b.x)), top: round(Math.min(a.y, b.y)), width: round(Math.abs(a.x - b.x)), height: round(Math.abs(a.y - b.y)) });
  const down = (e: React.PointerEvent) => { if (!prescan) return; viewer.current!.setPointerCapture(e.pointerId); origin.current = point(e); setDraft(null); };
  const move = (e: React.PointerEvent) => { if (origin.current) setDraft(rect(origin.current, point(e))); };
  const up = (e: React.PointerEvent) => {
    if (!origin.current) return;
    const result = rect(origin.current, point(e));
    origin.current = null;
    setDraft(null);
    setWs(w => ({ ...w, window: result.width >= .05 && result.height >= .05 ? result : w.window }));
  };
  const setWindowField = (key: keyof Window, percent: number) => setWs(w => {
    const next = { ...(w.window ?? { left: 0, top: 0, width: 1, height: 1 }), [key]: round(clamp(percent / 100, 0, 1)) };
    next.width = round(clamp(next.width, .05, 1 - next.left)); next.height = round(clamp(next.height, .05, 1 - next.top));
    return { ...w, window: next };
  });
  const toggle = (index: number) => setWs(w => ({ ...w, selected: w.selected.includes(index) ? w.selected.filter(i => i !== index) : [...w.selected, index].sort((a, b) => a - b) }));
  const shown = draft ?? ws.window;
  const viewing = prescan?.frames.find(f => f.index === ws.viewing) ?? prescan?.frames[0];
  const grouped = Object.keys(CLASSES).map(kind => [kind, (profiles?.profiles ?? []).filter(p => p.film_class === kind)] as const).filter(([, list]) => list.length);
  const profileStale = prescan && (prescan.film_profile ?? '') !== ws.profile;
  // CyberView ships same-named profiles per scanner family; name the folder only when it disambiguates.
  const names = (profiles?.profiles ?? []).map(p => p.name);
  const repeated = new Set(names.filter((name, i) => names.indexOf(name) !== i));

  return <section className="panel scan-workspace">
    <div className="panel-title"><div><span className="eyebrow">SCAN WORKSPACE</span><h2>Frame, expose, choose your film</h2></div><span className="number">03</span></div>
    <div className="ws-grid">
      <div>
        <div className="ws-viewer" ref={viewer} onPointerDown={down} onPointerMove={move} onPointerUp={up} aria-label="Prescan viewer; drag to set the scan window">
          {viewing ? <img src={media(viewing.preview_path)} alt={`Prescan of frame ${viewing.index}`} draggable={false} />
            : <div><span>◎</span><p>Prescan a roll to compose here.</p><small>Drag on the prescan to set the scan window.</small></div>}
          {viewing && shown && <div className="ws-window" style={{ left: `${shown.left * 100}%`, top: `${shown.top * 100}%`, width: `${shown.width * 100}%`, height: `${shown.height * 100}%` }} />}
          {viewing && <span className="ws-label">FRAME {String(viewing.index).padStart(2, '0')} · SYNTHETIC PRESCAN</span>}
        </div>
        {prescan && <>
          <div className="ws-strip-head"><span className="eyebrow">FRAME STRIP · {ws.selected.length} OF {prescan.frame_count} SELECTED</span>
            <span className="inline-actions"><button className="text-button" onClick={() => setWs(w => ({ ...w, selected: prescan.frames.map(f => f.index) }))}>ALL</button>
              <button className="text-button" onClick={() => setWs(w => ({ ...w, selected: [] }))}>NONE</button></span></div>
          <div className="frame-strip" role="list">
            {prescan.frames.map(f => <div role="listitem" key={f.index} className={`strip-frame${ws.selected.includes(f.index) ? ' picked' : ''}${viewing?.index === f.index ? ' viewing' : ''}`}>
              <button className="strip-view" onClick={() => setWs(w => ({ ...w, viewing: f.index }))} aria-label={`View frame ${f.index}`}><img src={media(f.preview_path)} alt="" /></button>
              <label className="strip-pick"><input type="checkbox" checked={ws.selected.includes(f.index)} onChange={() => toggle(f.index)} aria-label={`Scan frame ${f.index}`} />{String(f.index).padStart(2, '0')}</label>
            </div>)}
          </div>
        </>}
      </div>
      <div className="ws-controls">
        <div className="field-row">
          <label>RESOLUTION<select value={ws.dpi} onChange={e => setWs(w => ({ ...w, dpi: Number(e.target.value) }))}>{DPI.map(d => <option key={d} value={d}>{d} dpi</option>)}</select></label>
          <label>COLOR DEPTH<select value={ws.bitDepth} onChange={e => setWs(w => ({ ...w, bitDepth: Number(e.target.value) }))}><option value={8}>8 bit</option><option value={16}>16 bit</option></select></label>
        </div>
        <p className="small muted">Requested values are recorded with each frame. The simulator always delivers 8-bit synthetic fixtures.</p>
        <label>FILM PROFILE<select value={ws.profile} onChange={e => setWs(w => ({ ...w, profile: e.target.value }))}>
          <option value="">FRAME inversion only</option>
          {grouped.map(([kind, list]) => <optgroup key={kind} label={CLASSES[kind]}>{list.map(p => <option key={p.id} value={p.id}>{p.name}{repeated.has(p.name) ? ` · ${p.source_folder}` : ''}</option>)}</optgroup>)}
        </select></label>
        <p className="small muted">{profiles?.profiles.length ? `${profiles.profiles.length} profile${profiles.profiles.length === 1 ? "" : "s"} from your CyberView install.` : 'No CyberView film profiles found. Install CyberView or set FRAME_FILMTERM_DIRS.'}{profileStale ? ' Prescan again to preview with this profile.' : ''}</p>
        <span className="eyebrow ws-sub">EXPOSURE</span>
        {['R', 'G', 'B'].map((channel, i) => <label key={channel}>{`EXPOSURE ${channel} · ${Math.round(ws.gains[i] * 100)}%`}
          <input type="range" min={50} max={200} step={5} value={Math.round(ws.gains[i] * 100)} onChange={e => setWs(w => ({ ...w, gains: w.gains.map((g, j) => j === i ? Number(e.target.value) / 100 : g) }))} /></label>)}
        <span className="eyebrow ws-sub">SCAN WINDOW</span>
        <div className="ws-window-fields">
          {(['left', 'top', 'width', 'height'] as const).map(key => <label key={key}>{`WINDOW ${key.toUpperCase()} %`}
            <input type="number" min={0} max={100} step={1} value={Math.round((ws.window?.[key] ?? (key === 'width' || key === 'height' ? 1 : 0)) * 100)} onChange={e => setWindowField(key, Number(e.target.value))} /></label>)}
        </div>
        <button className="text-button" disabled={busy || !ws.window} onClick={() => setWs(w => ({ ...w, window: null }))}>RESET TO FULL FRAME</button>
      </div>
    </div>
  </section>;
}
