import type { SessionKind, WeatherForecast } from '../api/types'

const SESSION_SHORT: Record<SessionKind, string> = {
  fp1: 'FP1',
  fp2: 'FP2',
  fp3: 'FP3',
  sprint_quali: 'SQ',
  sprint: 'SPR',
  quali: 'Q',
  race: 'R',
}

/** Short axis label for a session (FP1, Q, R, …). */
export function sessionShort(kind: SessionKind): string {
  return SESSION_SHORT[kind] ?? kind
}

/** The Race session (the headline), falling back to the last session listed. */
export function raceSession(
  weather: WeatherForecast[] | undefined,
): WeatherForecast | undefined {
  if (!weather || weather.length === 0) return undefined
  return weather.find((s) => s.session_kind === 'race') ?? weather[weather.length - 1]
}
