import type { WeatherForecast } from '../api/types'

const SESSION_SHORT: Record<string, string> = {
  FP1: 'FP1',
  FP2: 'FP2',
  FP3: 'FP3',
  'Sprint Qualifying': 'SQ',
  Sprint: 'SPR',
  Qualifying: 'Q',
  Race: 'R',
}

/** Short axis label for a session name (FP1, Q, R, …). */
export function sessionShort(name: string): string {
  return SESSION_SHORT[name] ?? name
}

/** The Race session (the headline), falling back to the last session listed. */
export function raceSession(
  weather: WeatherForecast[] | undefined,
): WeatherForecast | undefined {
  if (!weather || weather.length === 0) return undefined
  return weather.find((s) => s.session_name === 'Race') ?? weather[weather.length - 1]
}
