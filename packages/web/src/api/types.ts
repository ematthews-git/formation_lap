/*
 * API response types — hand-mirrored from the backend Pydantic models in
 * packages/data/src/formation_data/domain.py. Kept here so the app type-checks
 * without a running backend.
 *
 * To regenerate canonical types from the live OpenAPI schema instead, start the
 * API and run `npm run gen:api` (writes src/api/schema.d.ts). If you adopt the
 * generated types, re-point the imports below at that file.
 */

export interface Circuit {
  circuit_id: string
  country: string
  track_length_km: number
  num_corners: number
  num_laps: number
  sm_zones: number
  jolpica_id: string
  fastf1_location: string
  lat: number
  lon: number
  track_outline: string | null
}

export interface RaceWeekend {
  id: number | null
  circuit_id: string
  season: number
  round_number: number
  event_name: string
  race_date: string // ISO date (YYYY-MM-DD)
  is_sprint: boolean
  soft_compound: string
  medium_compound: string
  hard_compound: string
}

export interface SessionFinisher {
  position: number
  driver_id: string
}

export interface Session {
  id: number | null
  race_weekend_id: number
  session_order: number
  name: string
  start_time: string // ISO datetime (UTC)
  // Top-3 finishers, empty until the session's results have been saved.
  top_finishers: SessionFinisher[]
}

export interface Driver {
  id: number | null
  driver_id: string
  full_name: string
  nationality: string
  team: string
  season: number
}

export interface Standing {
  id: number | null
  season: number
  after_round: number
  type: 'driver' | 'constructor'
  position: number
  name: string
  points: number
}

export interface RaceResult {
  id: number | null
  circuit_id: string
  season: number
  round_number: number
  position: number
  driver_id: string
  team: string
}

export interface CircuitStats {
  id: number | null
  circuit_id: string
  season: number
  sc_probability: number
  red_flag_probability: number
  updated_at: string | null
}

/** Empirical per-circuit race analytics over a trailing window (the JSONB `stats` blob).
 * Only the groups the frontend currently reads are typed; other groups (grid, overtaking,
 * weather, timing) are left loose. All numeric fields are nullable. */
export interface CircuitRaceStats {
  id: number | null
  circuit_id: string
  season: number
  updated_at: string | null
  stats: {
    incidents?: Record<string, number | null>
    pit?: Record<string, number | null>
    tyres?: {
      compound_usage_frequency?: Record<string, number>
      max_stint_length?: number | null
      avg_tyre_age_at_pit?: number | null
      avg_stint_degradation_s_per_lap?: number | null
    }
    [group: string]: unknown
  }
}

export interface LapRecord {
  id: number | null
  circuit_id: string
  driver: string
  year: number
  lap_time_seconds: number
}

export interface WeatherForecast {
  id: number | null
  race_weekend_id: number
  session_name: string
  session_date: string
  condition: string
  temp_high_c: number
  temp_low_c: number
  rain_probability: number
  wind_speed_kph: number
  updated_at: string | null
}

export interface StrategyStint {
  id: number | null
  strategy_id: number
  stint_order: number
  compound: string
  pit_lap_window_start: number
  pit_lap_window_end: number
}

export interface StrategyWithStints {
  id: number | null
  race_weekend_id: number
  // "historical" (mined) or "sim" (simulated).
  source: string
  // Sim only: "prelim" | "postquali". null for historical.
  phase: string | null
  is_base: boolean
  num_stops: number
  label: string
  // Sim only: field-plausibility share (0–1) and coarse tier. null for historical.
  plausibility: number | null
  tier: string | null
  updated_at: string | null
  stints: StrategyStint[]
}

/** Race-context numbers from a sim run (the JSONB `stats` blob). */
export interface SimRaceStats {
  id: number | null
  race_weekend_id: number
  phase: string
  generated_at: string | null
  stats: {
    meta?: Record<string, unknown>
    circuit_profile?: Record<string, number | null>
    race_stats?: Record<string, unknown>
  }
}
