import type { Circuit, RaceWeekend } from '../../api/types'
import { formatRaceDate, prettifyCircuit } from '../../lib/format'
import { resolveHero } from '../../lib/hero'
import { FALLBACK_TRACK_PATH } from '../../lib/trackPath'
import { Countdown, LightsOut } from './Countdown'
import styles from './Header.module.css'

interface HeaderProps {
  weekend: RaceWeekend
  circuit: Circuit | undefined
  totalRounds: number
  /** Race session start time (UTC ISO) from the sessions feed; the countdown
      falls back to 13:00 UTC on race day until it resolves. */
  raceStart: string | undefined
}

export function Header({ weekend, circuit, totalRounds, raceStart }: HeaderProps) {
  const ghostPath = circuit?.track_outline ?? FALLBACK_TRACK_PATH
  // Header text tone is hardcoded per hero photo (see lib/hero.ts): 'light'
  // flips the black subheader text to white for dark/night photos.
  const light = resolveHero(weekend.circuit_id)?.tone === 'light'
  return (
    <header className={`${styles.header} ${light ? styles.light : ''}`}>
      <svg className={styles.ghostTrack} viewBox="0 0 400 248" width="460">
        <path d={ghostPath} fill="none" stroke="#fff" strokeWidth="2" />
      </svg>

      <div className={styles.inner}>
        <div className={styles.roundLine}>
          <span className={styles.round}>
            ROUND_{String(weekend.round_number).padStart(2, '0')} / {totalRounds}
          </span>
          <span className={styles.championship}>
            FIA F1 WORLD CHAMPIONSHIP · {weekend.season}
          </span>
          {weekend.is_sprint && <span className={styles.sprint}>SPRINT</span>}
        </div>

        {/* title + countdown: share a baseline on desktop (grid areas), but the
            countdown reflows to just under the round line on mobile. */}
        <h1 className={styles.title}>{weekend.event_name}</h1>
        <div className={styles.clockSlot}>
          <Countdown raceDate={weekend.race_date} raceStart={raceStart} />
        </div>

        {/* circuit meta + lights-out times */}
        <div className={styles.metaLine}>
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

          <LightsOut
            raceDate={weekend.race_date}
            raceStart={raceStart}
            circuitId={weekend.circuit_id}
            light={light}
          />
        </div>
      </div>
    </header>
  )
}
