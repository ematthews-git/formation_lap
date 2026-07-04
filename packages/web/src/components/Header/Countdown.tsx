import { useCountdown } from '../../lib/useCountdown'
import { circuitTimezone, formatClock } from '../../lib/circuitTime'
import styles from './Countdown.module.css'

/**
 * We only have race_date (no session time) from the API yet, so the target is
 * approximated at 13:00 UTC on race day — refine once a sessions/weather
 * endpoint provides the real start time.
 */
function raceTarget(raceDate: string | undefined) {
  return raceDate ? `${raceDate}T13:00:00Z` : undefined
}

/** Big ticking lights-out countdown — DD:HH:MM.SS, sized to match the title. */
export function Countdown({ raceDate }: { raceDate: string | undefined }) {
  const { d, h, m, s } = useCountdown(raceTarget(raceDate))

  return (
    <div className={styles.clock}>
      {d}:{h}:{m}
      <span className={styles.seconds}>.{s}</span>
    </div>
  )
}

/** The two fixed lights-out times (circuit-local + viewer-local). Static. */
export function LightsOut({
  raceDate,
  circuitId,
}: {
  raceDate: string | undefined
  circuitId: string | undefined
}) {
  const target = raceTarget(raceDate)
  const circuitTz = circuitTimezone(circuitId)

  return (
    <div className={styles.times}>
      <div className={styles.timeRow}>
        <span className={styles.timeLabel}>LIGHTS OUT · CIRCUIT</span>
        <span className={styles.timeValue}>{formatClock(target, circuitTz)}</span>
      </div>
      <div className={styles.timeRow}>
        <span className={styles.timeLabel}>LIGHTS OUT · LOCAL</span>
        <span className={styles.timeValue}>{formatClock(target)}</span>
      </div>
    </div>
  )
}
