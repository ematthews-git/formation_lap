import type { ReactNode } from 'react'
import type { CircuitRaceStats, WeatherForecast } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { raceSession, sessionShort } from '../../lib/weather'
import styles from './WeatherStrip.module.css'

interface Props {
  weather: WeatherForecast[] | undefined
  weatherLoading: boolean
  /** Historical climatology for the circuit — feeds the dry-race / avg-temp tiles. */
  raceStats: CircuitRaceStats | null | undefined
}

export function WeatherStrip({ weather, weatherLoading, raceStats }: Props) {
  const race = raceSession(weather)
  const climate = raceStats?.stats?.weather
  // The forecast (high/low/wind) lands ≤10 days out; the climatology tiles are
  // available year-round, so the panel is populated once either source resolves.
  const hasAny = !!race || !!climate

  return (
    <Panel frosted className={styles.panel}>
      <PanelHeader
        label="MET_FORECAST"
        sub="RACE_WINDOW"
        meta={race ? race.condition.toUpperCase() : undefined}
      />
      {weatherLoading && !hasAny ? (
        <div className={styles.fill}>
          <LoadingState label="LOADING FORECAST" />
        </div>
      ) : hasAny ? (
        <Forecast race={race} sessions={weather} climate={climate} />
      ) : (
        <div className={styles.fill}>
          <EmptyState
            label="FORECAST PENDING"
            hint="Forecast is available when Grand Prix is 10 days away"
          />
        </div>
      )}
    </Panel>
  )
}

function Forecast({
  race,
  sessions,
  climate,
}: {
  race: WeatherForecast | undefined
  sessions: WeatherForecast[] | undefined
  climate: CircuitRaceStats['stats']['weather']
}) {
  const highLow = race
    ? `${Math.round(race.temp_high_c)}° / ${Math.round(race.temp_low_c)}°`
    : '—'
  const airTemp = climate?.avg_air_temp_c
  const trackTemp = climate?.avg_track_temp_c
  const dryShare = climate?.dry_race_share
  const airTrack =
    airTemp == null && trackTemp == null
      ? '—'
      : `${airTemp != null ? `${Math.round(airTemp)}°` : '—'} / ${
          trackTemp != null ? `${Math.round(trackTemp)}°` : '—'
        }`
  const hasSessions = !!sessions && sessions.length > 0
  const maxRain = Math.max(10, ...(sessions ?? []).map((s) => s.rain_probability))

  return (
    <>
      <div className={styles.stats}>
        <Stat label="HIGH / LOW" value={highLow} />
        <Stat label="AIR / TRACK" value={airTrack} left />
        <Stat
          label="WIND"
          value={race ? Math.round(race.wind_speed_kph) : '—'}
          unit={race ? 'km/h' : undefined}
        />
        <Stat
          label="DRY RACE"
          value={dryShare != null ? Math.round(dryShare * 100) : '—'}
          unit={dryShare != null ? '%' : undefined}
          left
        />
      </div>

      <div className={styles.chart}>
        <div className={styles.chartLabel}>RAIN PROBABILITY · BY SESSION</div>
        {hasSessions ? (
          <div className={styles.bars}>
            {sessions!.map((s) => (
              <div key={s.id ?? s.session_name} className={styles.barCol}>
                <span className={styles.barPct}>{s.rain_probability}%</span>
                <div
                  className={styles.bar}
                  style={{ height: `${Math.max(3, (s.rain_probability / maxRain) * 42)}px` }}
                />
                <span className={styles.barName}>{sessionShort(s.session_name)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.chartPending}>AWAITING FORECAST · &lt;10 DAYS OUT</div>
        )}
      </div>
    </>
  )
}

function Stat({
  label,
  value,
  unit,
  color,
  left,
}: {
  label: string
  value: ReactNode
  unit?: string
  color?: string
  left?: boolean
}) {
  return (
    <div className={`${styles.cell} ${left ? styles.cellLeft : ''}`}>
      <div className={styles.cellLabel}>{label}</div>
      <div className={styles.cellValue} style={color ? { color } : undefined}>
        {value}
        {unit && <span className={styles.cellUnit}>{unit}</span>}
      </div>
    </div>
  )
}
