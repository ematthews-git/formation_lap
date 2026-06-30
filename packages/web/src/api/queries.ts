import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type {
  Circuit,
  CircuitStats,
  Driver,
  LapRecord,
  RaceWeekend,
  Standing,
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

export function useLapRecord(circuitId: string | undefined) {
  return useQuery({
    queryKey: ['lap-record', circuitId],
    enabled: !!circuitId,
    queryFn: () =>
      api.getOptional<LapRecord>(`/circuits/${circuitId}/lap-record`),
  })
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
  const sorted = [...weekends].sort((a, b) => a.round_number - b.round_number)
  if (roundOverride != null) {
    return sorted.find((w) => w.round_number === roundOverride) ?? sorted[0]
  }
  const today = new Date().toISOString().slice(0, 10)
  return sorted.find((w) => w.race_date >= today) ?? sorted[sorted.length - 1]
}
