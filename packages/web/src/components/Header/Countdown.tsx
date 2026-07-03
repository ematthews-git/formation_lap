import { useCountdown } from '../../lib/useCountdown'
import { circuitTimezone, formatClock } from '../../lib/circuitTime'
import styles from './Countdown.module.css'

/**
 * Lights-out countdown. We only have race_date (no session time) from the API
 * yet, so the target is approximated at 13:00 UTC on race day — refine once a
 * sessions/weather endpoint provides the real start time.
 */
export function Countdown({
  raceDate,
  circuitId,
}: {
  raceDate: string | undefined
  circuitId: string | undefined
}) {
  const target = raceDate ? `${raceDate}T13:00:00Z` : undefined
  const { d, h, m, s } = useCountdown(target)
  const circuitTz = circuitTimezone(circuitId)

  return (
    <div className={styles.wrap}>
      <div className={styles.cells}>
        <Cell value={d} unit="DAYS" />
        <Cell value={h} unit="HRS" />
        <Cell value={m} unit="MIN" />
        <Cell value={s} unit="SEC" hot />
      </div>
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
    </div>
  )
}

function Cell({ value, unit, hot }: { value: string; unit: string; hot?: boolean }) {
  return (
    <div className={`${styles.cell} ${hot ? styles.hot : ''}`}>
      <div className={`${styles.value} ${hot ? styles.valueHot : ''}`}>{value}</div>
      <div className={styles.unit}>{unit}</div>
    </div>
  )
}
