import type { Circuit, RaceWeekend, WeatherForecast } from '../../api/types'
import { formatRaceDate, prettifyCircuit } from '../../lib/format'
import { FALLBACK_TRACK_PATH } from '../../lib/trackPath'
import { Countdown } from './Countdown'
import styles from './Header.module.css'

interface HeaderProps {
  weekend: RaceWeekend
  circuit: Circuit | undefined
  totalRounds: number
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

export function Header({
  weekend,
  circuit,
  totalRounds,
  raceWeather,
  races,
  activeRound,
  onSelectRound,
}: HeaderProps) {
  const ghostPath = circuit?.track_outline ?? FALLBACK_TRACK_PATH
  return (
    <header className={styles.header}>
      <div className={styles.scanline} />
      <svg className={styles.ghostTrack} viewBox="0 0 400 248" width="460">
        <path d={ghostPath} fill="none" stroke="#fff" strokeWidth="2" />
      </svg>

      <div className={styles.inner}>
        {/* status bar */}
        <div className={styles.statusBar}>
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
                {Math.round(raceWeather.temp_high_c)}°C · RAIN{' '}
                {raceWeather.rain_probability}%
              </span>
            ) : (
              <span className={styles.metPending}>MET FEED · PENDING</span>
            )}
          </div>
        </div>

        {/* title row */}
        <div className={styles.titleRow}>
          <div className={styles.titleMain}>
            <div className={styles.roundLine}>
              <span className={styles.round}>
                ROUND_{String(weekend.round_number).padStart(2, '0')} / {totalRounds}
              </span>
              <span className={styles.championship}>
                FIA F1 WORLD CHAMPIONSHIP · {weekend.season}
              </span>
              {weekend.is_sprint && <span className={styles.sprint}>SPRINT</span>}
            </div>
            <h1 className={styles.title}>{weekend.event_name}</h1>
            <div className={styles.meta}>
              <span className={styles.metaStrong}>
                {circuit ? prettifyCircuit(circuit.circuit_id) : prettifyCircuit(weekend.circuit_id)}{' '}
                Circuit
              </span>
              {circuit && (
                <>
                  <span className={styles.metaSlash}>//</span>
                  <span>{circuit.country}</span>
                </>
              )}
              <span className={styles.metaSlash}>//</span>
              <span>{formatRaceDate(weekend.race_date)}</span>
            </div>
          </div>

          <Countdown raceDate={weekend.race_date} circuitId={weekend.circuit_id} />
        </div>
      </div>
    </header>
  )
}
