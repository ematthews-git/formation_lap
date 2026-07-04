import type { WeatherForecast } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { raceSession, sessionShort } from '../../lib/weather'
import styles from './WeatherStrip.module.css'

interface Props {
  weather: WeatherForecast[] | undefined
  weatherLoading: boolean
}

export function WeatherStrip({ weather, weatherLoading }: Props) {
  const race = raceSession(weather)

  return (
    <Panel frosted>
      <PanelHeader
        label="MET_FORECAST"
        sub="RACE_WINDOW"
        meta={race ? race.condition.toUpperCase() : undefined}
      />
      {weatherLoading && !weather ? (
        <div className={styles.fill}>
          <LoadingState label="LOADING FORECAST" />
        </div>
      ) : race && weather ? (
        <Forecast race={race} sessions={weather} />
      ) : (
        <div className={styles.fill}>
          <EmptyState
            label="FORECAST PENDING"
            hint="run: formation-data weather refresh --season … --round …"
          />
        </div>
      )}
    </Panel>
  )
}

function Forecast({ race, sessions }: { race: WeatherForecast; sessions: WeatherForecast[] }) {
  const maxRain = Math.max(10, ...sessions.map((s) => s.rain_probability))
  return (
    <>
      <div className={styles.stats}>
        <Stat label="HIGH" value={Math.round(race.temp_high_c)} unit="°C" />
        <Stat label="LOW" value={Math.round(race.temp_low_c)} unit="°C" left />
        <Stat
          label="RAIN CHANCE"
          value={race.rain_probability}
          unit="%"
          color="var(--rain)"
        />
        <Stat label="WIND" value={Math.round(race.wind_speed_kph)} unit="km/h" left />
      </div>

      <div className={styles.chart}>
        <div className={styles.chartLabel}>RAIN PROBABILITY · BY SESSION</div>
        <div className={styles.bars}>
          {sessions.map((s) => (
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
  value: number
  unit: string
  color?: string
  left?: boolean
}) {
  return (
    <div className={`${styles.cell} ${left ? styles.cellLeft : ''}`}>
      <div className={styles.cellLabel}>{label}</div>
      <div className={styles.cellValue} style={color ? { color } : undefined}>
        {value}
        <span className={styles.cellUnit}>{unit}</span>
      </div>
    </div>
  )
}
