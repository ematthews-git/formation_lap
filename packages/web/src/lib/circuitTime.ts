/**
 * circuit_id → IANA timezone, so we can render the lights-out clock in the
 * track's local time. Keyed to the hand-curated circuits seed
 * (packages/data/.../jobs/static/circuits.py).
 */
const CIRCUIT_TZ: Record<string, string> = {
  melbourne: 'Australia/Melbourne',
  shanghai: 'Asia/Shanghai',
  suzuka: 'Asia/Tokyo',
  miami: 'America/New_York',
  montreal: 'America/Toronto',
  monaco: 'Europe/Monaco',
  barcelona: 'Europe/Madrid',
  red_bull_ring: 'Europe/Vienna',
  silverstone: 'Europe/London',
  spa: 'Europe/Brussels',
  hungaroring: 'Europe/Budapest',
  zandvoort: 'Europe/Amsterdam',
  monza: 'Europe/Rome',
  madrid: 'Europe/Madrid',
  baku: 'Asia/Baku',
  singapore: 'Asia/Singapore',
  austin: 'America/Chicago',
  mexico_city: 'America/Mexico_City',
  sao_paulo: 'America/Sao_Paulo',
  las_vegas: 'America/Los_Angeles',
  lusail: 'Asia/Qatar',
  abu_dhabi: 'Asia/Dubai',
}

/** IANA timezone for a circuit, or undefined if unmapped. */
export function circuitTimezone(circuitId: string | undefined): string | undefined {
  return circuitId ? CIRCUIT_TZ[circuitId] : undefined
}

/**
 * Format an instant (ISO string or epoch ms) as "HH:MM TZ" — 24-hour, with a
 * short timezone name. `tz` picks the zone (IANA name); omit it for the
 * browser's local zone. Returns "--:--" for missing/invalid input.
 */
export function formatClock(target: string | number | undefined, tz?: string): string {
  if (target == null) return '--:--'
  const d = new Date(target)
  if (Number.isNaN(d.getTime())) return '--:--'
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: tz,
    timeZoneName: 'short',
  }).format(d)
}

/**
 * Format an instant as "Fri 3 Jul" in the given timezone (or the browser's
 * local zone when `tz` is omitted). Returns "" for missing/invalid input.
 */
export function formatDayDate(
  target: string | number | undefined,
  tz?: string,
): string {
  if (target == null) return ''
  const d = new Date(target)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: tz,
  }).format(d)
}
