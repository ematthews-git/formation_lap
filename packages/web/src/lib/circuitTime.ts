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
