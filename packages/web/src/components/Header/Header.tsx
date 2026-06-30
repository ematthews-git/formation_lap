import type { Circuit, RaceWeekend } from '../../api/types'
import { formatRaceDate, prettifyCircuit } from '../../lib/format'
import { Countdown } from './Countdown'
import styles from './Header.module.css'

interface HeaderProps {
  weekend: RaceWeekend
  circuit: Circuit | undefined
  totalRounds: number
}

// Mockup track-outline path; circuit-specific outlines are a later enhancement.
const TRACK_PATH =
  'M58 196 C 80 150, 84 116, 122 116 C 146 116, 152 134, 174 136 C 214 140, 228 92, 262 90 C 308 88, 332 70, 346 90 C 358 108, 332 126, 296 132 C 264 137, 246 152, 260 172 C 274 192, 322 188, 332 208 C 339 223, 314 230, 284 226 C 240 220, 198 214, 176 207 C 138 195, 112 226, 86 216 C 64 207, 50 210, 58 196 Z'

export function Header({ weekend, circuit, totalRounds }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.scanline} />
      <svg className={styles.ghostTrack} viewBox="0 0 400 248" width="460">
        <path d={TRACK_PATH} fill="none" stroke="#fff" strokeWidth="2" />
      </svg>

      <div className={styles.inner}>
        {/* status bar */}
        <div className={styles.statusBar}>
          <div className={styles.brand}>
            <span className={styles.brandDot} />
            <span className={styles.brandName}>FORMATION_LAP</span>
            <span className={styles.brandTag}>// STRATEGY_BRIEFING</span>
          </div>
          <div className={styles.statusRight}>
            <span className={styles.feedLive}>
              <span className={styles.feedDot} />
              FEED_LIVE
            </span>
            <span className={styles.divider}>|</span>
            <span className={styles.metPending}>MET FEED · PENDING</span>
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

          <Countdown raceDate={weekend.race_date} />
        </div>
      </div>
    </header>
  )
}
