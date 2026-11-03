import type { FilmType, CyberScanWorkspace } from '../../../packages/contracts/schema';

export const FILM_LOOKS = {
  color_negative: { label: 'Color negative', short: 'Color', code: 'CN', edge: '135 · COLOR NEGATIVE',
    eyebrow: 'THE COLOUR NEGATIVE WORKFLOW', description: 'Scan, balance and preserve the photographs on your roll.' },
  bw_negative: { label: 'Black & white', short: 'B&W', code: 'BW', edge: '135 · BLACK & WHITE',
    eyebrow: 'THE BLACK & WHITE WORKFLOW', description: 'A dedicated space for your black and white negatives.' },
  positive: { label: 'Slide', short: 'Slide', code: 'RV', edge: '135 · REVERSAL FILM',
    eyebrow: 'THE REVERSAL FILM WORKFLOW', description: 'Preview, scan and organise your positive transparencies.' },
} satisfies Record<FilmType, {label: string; short: string; code: string; edge: string; eyebrow: string; description: string}>;

export function initialFilmType(): FilmType {
  const requested = new URLSearchParams(location.search).get('film_type');
  if (requested && Object.prototype.hasOwnProperty.call(FILM_LOOKS, requested)) return requested as FilmType;
  try {
    const saved = localStorage.getItem('frame.film-type');
    if (saved && Object.prototype.hasOwnProperty.call(FILM_LOOKS, saved)) return saved as FilmType;
  } catch { /* The app also works when browser storage is unavailable. */ }
  return 'color_negative';
}

export function rememberFilmType(value: FilmType) {
  try { localStorage.setItem('frame.film-type', value); } catch { /* Live preferences are also saved by the API. */ }
}

export function workspaceFilmType(value: CyberScanWorkspace): FilmType {
  return value.film_type || (value.settings.film === 'positive' ? 'positive' : 'color_negative');
}

export function FilmGlyph({ type, size = 25 }: { type: FilmType; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden="true">
    {type === 'positive' ? <><rect x="2" y="3" width="24" height="22" rx="3" fill="currentColor" opacity=".2" /><rect x="2" y="3" width="24" height="22" rx="3" stroke="currentColor" strokeWidth="1.3" /><rect x="7" y="8" width="14" height="12" rx="1" stroke="currentColor" strokeWidth="1.3" /></> : <>
      <rect x="3" y="2" width="22" height="24" rx="2" stroke="currentColor" strokeWidth="1.3" />
      {[5, 11, 17, 23].map((y) => <g key={y}><rect x="5" y={y - 1} width="2" height="2.5" rx=".5" fill="currentColor" /><rect x="21" y={y - 1} width="2" height="2.5" rx=".5" fill="currentColor" /></g>)}
      <rect x="9" y="6" width="10" height="16" rx=".5" fill="currentColor" opacity=".2" />
      {type === 'bw_negative' ? <path d="M14 6h5v16h-5z" fill="currentColor" /> : <><path d="M10 17l3-5 2 3 3-5v11h-8z" fill="currentColor" opacity=".8" /><circle cx="12" cy="9" r="1.3" fill="currentColor" /></>}
    </>}
  </svg>;
}

export function FilmTypePicker({ value, onChange, onAutoDetect, autoDetecting = false, disabled }: {
  value: FilmType; onChange: (value: FilmType) => void; onAutoDetect: () => void; autoDetecting?: boolean; disabled: boolean;
}) {
  return <fieldset className="cx-film-picker" aria-label="Film type" disabled={disabled} title="Changes the workspace and new scans. Saved photographs keep their edits.">
    <legend>Film type <span>135</span></legend>
    <div className="cx-film-choices">{(Object.keys(FILM_LOOKS) as FilmType[]).map((type) => <label key={type}>
      <input type="radio" name="frame-film-type" aria-label={FILM_LOOKS[type].label} value={type} checked={value === type} onChange={() => onChange(type)} />
      <span className="cx-film-choice"><FilmGlyph type={type} size={24} /><span>{FILM_LOOKS[type].short}</span></span>
    </label>)}</div>
    <button type="button" className="cx-film-auto" onClick={onAutoDetect} disabled={disabled || autoDetecting}>
      <span className="cx-film-auto-mark">AUTO</span><span>{autoDetecting ? 'Checking first frame…' : 'Determine from first frame'}</span><span aria-hidden="true">↗</span>
    </button>
    <p><span className="cx-film-dot" />{FILM_LOOKS[value].label}<span className="cx-film-code">{FILM_LOOKS[value].code}</span></p>
  </fieldset>;
}
