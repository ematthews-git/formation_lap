import { useCountdown } from '../../lib/useCountdown'
import styles from './Countdown.module.css'

/**
 * Lights-out countdown. We only have race_date (no session time) from the API
 * yet, so the target is approximated at 13:00 UTC on race day — refine once a
 * sessions/weather endpoint provides the real start time.
 */
export function Countdown({ raceDate }: { raceDate: string | undefined }) {
  const target = raceDate ? `${raceDate}T13:00:00Z` : undefined
  const { d, h, m, s } = useCountdown(target)

  return (
    <div className={styles.wrap}>
      <div className={styles.caption}>LIGHTS OUT IN</div>
      <div className={styles.cells}>
        <Cell value={d} unit="DAYS" />
        <Cell value={h} unit="HRS" />
        <Cell value={m} unit="MIN" />
        <Cell value={s} unit="SEC" hot />
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
