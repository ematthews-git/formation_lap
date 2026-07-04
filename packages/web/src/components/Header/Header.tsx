import type { Circuit, RaceWeekend } from '../../api/types'
import { formatRaceDate, prettifyCircuit } from '../../lib/format'
import { FALLBACK_TRACK_PATH } from '../../lib/trackPath'
import { Countdown } from './Countdown'
import styles from './Header.module.css'

interface HeaderProps {
  weekend: RaceWeekend
  circuit: Circuit | undefined
  totalRounds: number
}

export function Header({ weekend, circuit, totalRounds }: HeaderProps) {
  const ghostPath = circuit?.track_outline ?? FALLBACK_TRACK_PATH
  return (
    <header className={styles.header}>
      <svg className={styles.ghostTrack} viewBox="0 0 400 248" width="460">
        <path d={ghostPath} fill="none" stroke="#fff" strokeWidth="2" />
      </svg>

      <div className={styles.inner}>
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
