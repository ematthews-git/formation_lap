/** Prettify a circuit_id key ("las_vegas", "silverstone") into a display name. */
export function prettifyCircuit(circuitId: string): string {
  return circuitId
    .split(/[_-]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Map a team name to its CSS team-colour variable (falls back to neutral). */
export function teamColorVar(team: string): string {
  const key = team.toLowerCase()
  if (key.includes('mclaren')) return 'var(--team-mclaren)'
  if (key.includes('red bull') || key.includes('redbull'))
    return 'var(--team-redbull)'
  if (key.includes('racing bull') || key.includes('rb')) return 'var(--team-racingbulls)'
  if (key.includes('ferrari')) return 'var(--team-ferrari)'
  if (key.includes('mercedes')) return 'var(--team-mercedes)'
  if (key.includes('aston')) return 'var(--team-aston)'
  if (key.includes('williams')) return 'var(--team-williams)'
  return 'var(--team-default)'
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

/** Read an optional ?round= override from the URL. */
export function roundOverrideFromUrl(): number | undefined {
  const raw = new URLSearchParams(window.location.search).get('round')
  if (!raw) return undefined
  const n = Number(raw)
  return Number.isInteger(n) ? n : undefined
}
