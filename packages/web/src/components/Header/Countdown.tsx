import { useCountdown } from '../../lib/useCountdown'
import { circuitTimezone, formatClock } from '../../lib/circuitTime'
import styles from './Countdown.module.css'

/**
 * The countdown target: the Race session's real start time (UTC) once the
 * sessions feed resolves; until then, approximated at 13:00 UTC on race day so
 * the clock isn't blank while sessions load.
 */
function raceTarget(raceDate: string | undefined, raceStart: string | undefined) {
  return raceStart ?? (raceDate ? `${raceDate}T13:00:00Z` : undefined)
}

/** F1's event time limit — treat the race as running for up to 3h after lights out. */
const RACE_WINDOW_MS = 3 * 3_600_000

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

/** Big ticking lights-out countdown — DD:HH:MM.SS, sized to match the title.
    Once the clock hits zero it flips to a race-underway / race-complete state
    instead of sitting at 00:00:00. */
export function Countdown({
  raceDate,
  raceStart,
}: {
  raceDate: string | undefined
  raceStart: string | undefined
}) {
  const target = raceTarget(raceDate, raceStart)
  const { d, h, m, s, done } = useCountdown(target)

  if (done) {
    const startMs = target ? Date.parse(target) : NaN
    const racing = !Number.isNaN(startMs) && Date.now() - startMs < RACE_WINDOW_MS
    return (
      <div className={styles.raceState}>
        {racing ? 'LIGHTS OUT' : 'RACE COMPLETE'}
      </div>
    )
  }

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
  raceStart,
  circuitId,
  light,
}: {
  raceDate: string | undefined
  raceStart: string | undefined
  circuitId: string | undefined
  /** Header tone (dark/night photo) — flips the mobile text to white, matching
      the other subheaders when the full-bleed hero sits behind these times. */
  light?: boolean
}) {
  const target = raceTarget(raceDate, raceStart)
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
