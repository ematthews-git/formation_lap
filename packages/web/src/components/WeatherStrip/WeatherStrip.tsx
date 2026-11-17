import { useRef } from 'react'
import type { CircuitRaceStats, WeatherForecast } from '../../api/types'
import { liftClass, useLift } from '../common/useLift'
import { SKY_KINDS, raceSession, sessionShort, skyKind, type SkyKind } from '../../lib/weather'
import { Sky } from './Sky'
import styles from './WeatherStrip.module.css'

interface Props {
  weather: WeatherForecast[] | undefined
  weatherLoading: boolean
  /** Query failure (network/5xx) — distinct from "forecast not published yet". */
  weatherError?: boolean
  /** Historical climatology for the circuit — feeds the air/track and dry-race stats. */
  raceStats: CircuitRaceStats | null | undefined
}

type Climate = CircuitRaceStats['stats']['weather'] | undefined

/** Dev-only `?sky=rain` (etc.) override, to review every backdrop without a live forecast. */
function devSkyOverride(): SkyKind | null {
  if (!import.meta.env.DEV) return null
  const v = new URLSearchParams(window.location.search).get('sky')
  return SKY_KINDS.includes(v as SkyKind) ? (v as SkyKind) : null
}

export function WeatherStrip({ weather, weatherLoading, weatherError, raceStats }: Props) {
  const race = raceSession(weather)
  const climate = raceStats?.stats?.weather
  const sky = devSkyOverride() ?? skyKind(race)
  const ref = useRef<HTMLElement>(null)
  useLift(ref)

  let body
  if (race) {
    body = <Forecast race={race} sessions={weather!} climate={climate} />
  } else if (weatherLoading) {
    body = <p className={styles.message}>Loading forecast…</p>
  } else if (weatherError) {
    body = <p className={styles.message}>Couldn't load the forecast</p>
  } else {
    body = <Pending climate={climate} />
  }

  return (
    <section ref={ref} className={`${styles.card} ${liftClass}`} aria-label="Weather">
      <Sky kind={sky} />
      <div className={styles.content}>
        <header className={styles.top}>
          <h2 className={styles.title}>Weather</h2>
          {race && <span className={styles.chip}>{race.condition}</span>}
        </header>
        {body}
      </div>
    </section>
  )
}

function Forecast({
  race,
  sessions,
  climate,
}: {
  race: WeatherForecast
  sessions: WeatherForecast[]
  climate: Climate
}) {
  return (
    <>
      <div className={styles.hero}>
        <span className={styles.temp}>{Math.round(race.temp_high_c)}°</span>
        <span className={styles.low}>/{Math.round(race.temp_low_c)}°</span>
        <span className={styles.heroLabel}>
          Race day
          <br />
          high / low
        </span>
      </div>

      <div className={styles.stats}>
        <Stat label="Rain" value={race.rain_probability} unit="%" />
        <Stat label="Wind" value={Math.round(race.wind_speed_kph)} unit="km/h" />
        <ClimateStats climate={climate} />
      </div>

      <div className={styles.sessions} aria-label="Rain probability by session">
        {sessions.map((s) => (
          <div key={s.session_kind} className={styles.session}>
            <span className={styles.sessionPct}>{s.rain_probability}%</span>
            <span className={styles.track}>
              <span
                className={styles.bar}
                style={{ height: `${Math.max(4, s.rain_probability)}%` }}
              />
            </span>
            <span className={styles.sessionName}>{sessionShort(s.session_kind)}</span>
          </div>
        ))}
      </div>
    </>
  )
}

/** No forecast yet (it publishes ≤10 days out) — lead with what's typical here. */
function Pending({ climate }: { climate: Climate }) {
  return (
    <>
      <p className={styles.pending}>
        Forecast lands
        <br />
        10 days out
      </p>
      {climate && (
        <div className={`${styles.stats} ${styles.statsHalf}`}>
          <ClimateStats climate={climate} />
        </div>
      )}
    </>
  )
}

function ClimateStats({ climate }: { climate: Climate }) {
  const air = climate?.avg_air_temp_c
  const track = climate?.avg_track_temp_c
  const dry = climate?.dry_race_share
  const deg = (v: number | null | undefined) => (v != null ? `${Math.round(v)}°` : '—')
  return (
    <>
      <Stat
        label="Air / track · avg"
        value={air == null && track == null ? '—' : `${deg(air)}/${deg(track)}`}
      />
      <Stat
        label="Dry race · avg"
        value={dry != null ? Math.round(dry * 100) : '—'}
        unit={dry != null ? '%' : undefined}
      />
    </>
  )
}

function Stat({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className={styles.stat}>
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue}>
        {value}
        {unit && <span className={styles.statUnit}>{unit}</span>}
      </div>
    </div>
  )
}
