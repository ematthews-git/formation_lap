import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type {
  Circuit,
  CircuitRaceStats,
  CircuitStats,
  Driver,
  LapRecord,
  RaceResult,
  RaceWeekend,
  Session,
  SimRaceStats,
  Standing,
  StrategyWithStints,
  WeatherForecast,
} from './types'

export const DEFAULT_SEASON = 2026

export function useRaceWeekends(season: number) {
  return useQuery({
    queryKey: ['race-weekends', season],
    queryFn: () =>
      api.get<RaceWeekend[]>(`/race-weekends/?season=${season}`),
  })
}

export function useCircuit(circuitId: string | undefined) {
  return useQuery({
    queryKey: ['circuit', circuitId],
    enabled: !!circuitId,
    queryFn: () => api.get<Circuit>(`/circuits/${circuitId}`),
  })
}

export function useDrivers(season: number) {
  return useQuery({
    queryKey: ['drivers', season],
    queryFn: () => api.get<Driver[]>(`/drivers/?season=${season}`),
  })
}

export function useStandings(season: number, type: 'driver' | 'constructor' = 'driver') {
  return useQuery({
    queryKey: ['standings', season, type],
    queryFn: () =>
      api.get<Standing[]>(`/standings/?season=${season}&type=${type}`),
  })
}

export function useRaceResults(season: number) {
  return useQuery({
    queryKey: ['race-results', season],
    queryFn: () => api.get<RaceResult[]>(`/race-results/?season=${season}`),
  })
}

export function useCircuitStats(
  circuitId: string | undefined,
  season: number,
) {
  return useQuery({
    queryKey: ['circuit-stats', circuitId, season],
    enabled: !!circuitId,
    // 404 (no stats yet) → null, an expected empty state.
    queryFn: () =>
      api.getOptional<CircuitStats>(
        `/circuits/${circuitId}/stats?season=${season}`,
      ),
  })
}

/** Empirical race-analytics blob for a circuit-season (null until the pre-season job runs). */
export function useCircuitRaceStats(
  circuitId: string | undefined,
  season: number,
) {
  return useQuery({
    queryKey: ['circuit-race-stats', circuitId, season],
    enabled: !!circuitId,
    // 404 (no stats yet) → null, an expected empty state.
    queryFn: () =>
      api.getOptional<CircuitRaceStats>(
        `/circuits/${circuitId}/race-stats?season=${season}`,
      ),
  })
}

export function useWeather(season: number, round: number | undefined) {
  return useQuery({
    queryKey: ['weather', season, round],
    enabled: round != null,
    queryFn: () =>
      api.get<WeatherForecast[]>(`/weather/?season=${season}&round=${round}`),
  })
}

export function useSessions(season: number, round: number | undefined) {
  return useQuery({
    queryKey: ['sessions', season, round],
    enabled: round != null,
    queryFn: () =>
      api.get<Session[]>(`/sessions/?season=${season}&round=${round}`),
  })
}

export function useStrategies(season: number, round: number | undefined) {
  return useQuery({
    queryKey: ['strategies', season, round],
    enabled: round != null,
    queryFn: () =>
      api.get<StrategyWithStints[]>(`/strategies/?season=${season}&round=${round}`),
  })
}

/** The officially simulated strategies (race-level shown-5) for a weekend. */
export function useSimStrategies(season: number, round: number | undefined) {
  return useQuery({
    queryKey: ['sim-strategies', season, round],
    enabled: round != null,
    queryFn: () =>
      api.get<StrategyWithStints[]>(
        `/strategies/simulated?season=${season}&round=${round}`,
      ),
  })
}

/** Race-context numbers from the sim run (null until a sim has run). */
export function useSimStats(season: number, round: number | undefined) {
  return useQuery({
    queryKey: ['sim-stats', season, round],
    enabled: round != null,
    queryFn: () =>
      api.getOptional<SimRaceStats>(
        `/strategies/simulated/stats?season=${season}&round=${round}`,
      ),
  })
}

export function useCircuitPodiums(circuitId: string | undefined, limit = 5) {
  return useQuery({
    queryKey: ['podiums', circuitId, limit],
    enabled: !!circuitId,
    queryFn: () =>
      api.get<RaceResult[]>(`/circuits/${circuitId}/podiums?limit=${limit}`),
  })
}

export function useLapRecord(circuitId: string | undefined) {
  return useQuery({
    queryKey: ['lap-record', circuitId],
    enabled: !!circuitId,
    queryFn: () =>
      api.getOptional<LapRecord>(`/circuits/${circuitId}/lap-record`),
  })
}

/** Index of the upcoming round (race_date today or later); last round if the
 * season is over. Returns -1 for an empty/missing calendar. Assumes `sorted`. */
function upcomingIndex(sorted: RaceWeekend[]): number {
  if (sorted.length === 0) return -1
  const today = new Date().toISOString().slice(0, 10)
  const idx = sorted.findIndex((w) => w.race_date >= today)
  return idx === -1 ? sorted.length - 1 : idx
}

function sortByRound(weekends: RaceWeekend[]): RaceWeekend[] {
  return [...weekends].sort((a, b) => a.round_number - b.round_number)
}

/**
 * The weekend the briefing focuses on: the next round whose race_date is today
 * or later; if the season is over, the final round. An optional ?round= query
 * param overrides the pick. Returns `undefined` while weekends are loading.
 */
export function pickFeaturedWeekend(
  weekends: RaceWeekend[] | undefined,
  roundOverride?: number,
): RaceWeekend | undefined {
  if (!weekends || weekends.length === 0) return undefined
  const sorted = sortByRound(weekends)
  if (roundOverride != null) {
    return sorted.find((w) => w.round_number === roundOverride) ?? sorted[0]
  }
  return sorted[upcomingIndex(sorted)]
}

/** Look up a weekend by round number. */
export function weekendByRound(
  weekends: RaceWeekend[] | undefined,
  round: number,
): RaceWeekend | undefined {
  return weekends?.find((w) => w.round_number === round)
}

/** The next `count` race weekends after the upcoming one, in calendar order. */
export function lookaheadWeekends(
  weekends: RaceWeekend[] | undefined,
  count = 3,
): RaceWeekend[] {
  if (!weekends || weekends.length === 0) return []
  const sorted = sortByRound(weekends)
  const start = upcomingIndex(sorted) + 1
  return sorted.slice(start, start + count)
}
