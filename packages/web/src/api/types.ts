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

export interface CircuitStats {
  id: number | null
  circuit_id: string
  season: number
  sc_probability: number
  red_flag_probability: number
  pit_loss_normal: number
  pit_loss_sc: number
  pit_loss_vsc: number
  undercut_strength: number
  overcut_strength: number
  updated_at: string | null
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
  is_base: boolean
  num_stops: number
  label: string
  updated_at: string | null
  stints: StrategyStint[]
}
