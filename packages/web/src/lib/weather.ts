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

/**
 * The card's backdrop, picked from the race-day forecast. Each kind maps to a
 * texture in WeatherStrip/Sky — kept light enough that black type stays legible.
 */
export type SkyKind = 'clear' | 'heat' | 'cloud' | 'overcast' | 'rain'

export const SKY_KINDS: readonly SkyKind[] = ['clear', 'heat', 'cloud', 'overcast', 'rain']

/** A clear race day at or above this high (°C) gets the hot palette. */
const HOT_HIGH_C = 30

export function skyKind(race: WeatherForecast | undefined): SkyKind {
  if (!race) return 'clear'
  switch (race.condition) {
    case 'Clear':
      return race.temp_high_c >= HOT_HIGH_C ? 'heat' : 'clear'
    case 'Partly Cloudy':
      return 'cloud'
    case 'Overcast':
    case 'Fog':
    case 'Snow':
      return 'overcast'
    case 'Drizzle':
    case 'Rain':
    case 'Showers':
    case 'Thunderstorm':
      return 'rain'
    default:
      return 'clear'
  }
}
