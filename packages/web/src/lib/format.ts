/** Prettify a circuit_id key ("las_vegas", "silverstone") into a display name. */
export function prettifyCircuit(circuitId: string): string {
  return circuitId
    .split(/[_-]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/**
 * A team's colour, from its team_id (the API's lineage key, e.g. "racing_bulls" for
 * AlphaTauri, RB and Racing Bulls alike). Each lineage's token is `--team-<team_id>`
 * in tokens.css; a team without one (Haas) or an unknown team is neutral grey.
 */
export function teamColor(teamId: string | null | undefined): string {
  return teamId ? `var(--team-${teamId}, var(--team-default))` : 'var(--team-default)'
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/** ISO date (YYYY-MM-DD) → "Sun 5 Jul 2026". */
export function formatRaceDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

/** Seconds → "H:MM:SS" (race durations are always over an hour). */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** A positive gap in seconds → "+45.2s" under a minute, else "+M:SS". */
export function formatGap(seconds: number): string {
  if (seconds < 60) return `+${seconds.toFixed(1)}s`
  let m = Math.floor(seconds / 60)
  let s = Math.round(seconds % 60)
  if (s === 60) {
    m += 1
    s = 0
  }
  return `+${m}:${String(s).padStart(2, '0')}`
}

/** Read an optional ?round= override from the URL. */
export function roundOverrideFromUrl(): number | undefined {
  const raw = new URLSearchParams(window.location.search).get('round')
  if (!raw) return undefined
  const n = Number(raw)
  return Number.isInteger(n) ? n : undefined
}
