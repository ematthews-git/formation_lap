import type { RaceWeekend, WeatherForecast } from '../../api/types'
import { prettifyCircuit } from '../../lib/format'
import styles from './TopBar.module.css'

interface TopBarProps {
  raceWeather: WeatherForecast | undefined
  /** The upcoming race weekend plus the next few, in calendar order — each is a selector. */
  races: RaceWeekend[]
  /** round_number of the weekend currently shown (for highlighting). */
  activeRound: number
  onSelectRound: (round: number) => void
}

function CloudIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M6 16a4 4 0 0 1 .5-7.97A5.5 5.5 0 0 1 17.5 9H18a3.5 3.5 0 0 1 0 7Z" />
      <path d="M9 19l-1 2M13 19l-1 2M17 19l-1 2" />
    </svg>
  )
}

/** Full-bleed status strip pinned to the top of the page, above the hero photo. */
export function TopBar({ raceWeather, races, activeRound, onSelectRound }: TopBarProps) {
  return (
    <div className={styles.topBar}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <span className={styles.brandDot} />
          <span className={styles.brandName}>FORMATION_LAP</span>
          <span className={styles.brandTag}>// STRATEGY_BRIEFING</span>
          {races.length > 0 && (
            <span className={styles.lookahead}>
              {races.map((w) => (
                <button
                  key={w.round_number}
                  type="button"
                  className={`${styles.lookaheadItem} ${
                    w.round_number === activeRound ? styles.lookaheadActive : ''
                  }`}
                  onClick={() => onSelectRound(w.round_number)}
                  title={`${w.event_name} · Round ${w.round_number}`}
                >
                  {prettifyCircuit(w.circuit_id)}
                </button>
              ))}
            </span>
          )}
        </div>
        <div className={styles.statusRight}>
          <span className={styles.feedLive}>
            <span className={styles.feedDot} />
            FEED_LIVE
          </span>
          <span className={styles.divider}>|</span>
          {raceWeather ? (
            <span className={styles.metLive}>
              <CloudIcon />
              {raceWeather.condition.toUpperCase()} ·{' '}
              {Math.round(raceWeather.temp_high_c)}°C · RAIN {raceWeather.rain_probability}%
            </span>
          ) : (
            <span className={styles.metPending}>MET FEED · PENDING</span>
          )}
        </div>
      </div>
    </div>
  )
}
