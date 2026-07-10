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

/** Saira Condensed has no tabular-figures support and its digit glyphs vary
    widely in width, so `tabular-nums` alone can't stop per-tick jitter — pin
    each character to a fixed-width slot instead. */
function Digits({ value }: { value: string }) {
  return (
    <>
      {[...value].map((ch, i) => (
        <span key={i} className={styles.digit}>{ch}</span>
      ))}
    </>
  )
}

/** Big ticking lights-out countdown — DD:HH:MM.SS, sized to match the title. */
export function Countdown({ raceDate }: { raceDate: string | undefined }) {
  const { d, h, m, s } = useCountdown(raceTarget(raceDate))

  return (
    <div className={styles.clock}>
      <Digits value={d} />:<Digits value={h} />:<Digits value={m} />
      <span className={styles.seconds}>.<Digits value={s} /></span>
    </div>
  )
}

/** The two fixed lights-out times (circuit-local + viewer-local). Static. */
export function LightsOut({
  raceDate,
  circuitId,
  light,
}: {
  raceDate: string | undefined
  circuitId: string | undefined
  /** Header tone (dark/night photo) — flips the mobile text to white, matching
      the other subheaders when the full-bleed hero sits behind these times. */
  light?: boolean
}) {
  const target = raceTarget(raceDate)
  const circuitTz = circuitTimezone(circuitId)

  return (
    <div className={`${styles.times} ${light ? styles.light : ''}`}>
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
