import type { StrategyWithStints } from '../../api/types'
import styles from './StintTimeline.module.css'

const COMPOUND_STYLE: Record<string, { color: string; bg: string; short: string }> = {
  SOFT: { color: 'var(--soft)', bg: 'var(--stint-soft-bg)', short: 'S' },
  MEDIUM: { color: 'var(--gold)', bg: 'var(--stint-medium-bg)', short: 'M' },
  HARD: { color: 'var(--hard)', bg: 'var(--stint-hard-bg)', short: 'H' },
}
const FALLBACK = { color: 'var(--text-faint)', bg: 'var(--panel-raised)', short: '?' }
const styleFor = (c: string) => COMPOUND_STYLE[c] ?? FALLBACK

/** Colour a plausibility tier: most likely = gold, alternative = neutral, long-shot = faint. */
function tierColor(tier: string): string {
  const t = tier.toLowerCase()
  if (t.startsWith('most')) return 'var(--gold)'
  if (t.startsWith('alt')) return 'var(--text)'
  return 'var(--text-faint)'
}

interface Bar {
  compound: string
  startLap: number
  endLap: number
  widthPct: number
}

/**
 * Turn a strategy's pit windows into displayable stint bars. We don't store
 * exact stint boundaries, so each pit lap is taken as the midpoint of its
 * window; the final stint runs to the flag.
 */
function toBars(strategy: StrategyWithStints, raceLaps: number): Bar[] {
  const stints = [...strategy.stints].sort((a, b) => a.stint_order - b.stint_order)
  const bars: Bar[] = []
  let prevEnd = 0
  stints.forEach((st, i) => {
    const isLast = i === stints.length - 1
    const pitLap = isLast
      ? raceLaps
      : Math.round((st.pit_lap_window_start + st.pit_lap_window_end) / 2)
    const startLap = prevEnd + 1
    const endLap = Math.max(startLap, pitLap)
    bars.push({
      compound: st.compound,
      startLap,
      endLap,
      widthPct: ((endLap - startLap + 1) / raceLaps) * 100,
    })
    prevEnd = endLap
  })
  return bars
}

export function StintTimeline({ strategies }: { strategies: StrategyWithStints[] }) {
  const raceLaps = Math.max(
    1,
    ...strategies.flatMap((s) => s.stints.map((st) => st.pit_lap_window_end)),
  )
  const axis = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * raceLaps))

  return (
    <div>
      <div className={styles.head}>
        <span className={styles.label}>STINT PLAN · {raceLaps} LAPS</span>
        <div className={styles.legend}>
          {(['SOFT', 'MEDIUM', 'HARD'] as const).map((c) => (
            <span key={c} className={styles.legendItem}>
              <span className={styles.swatch} style={{ background: styleFor(c).color }} />
              {c}
            </span>
          ))}
        </div>
      </div>

      {strategies.map((strategy) => {
        const bars = toBars(strategy, raceLaps)
        const seq = bars.map((b) => styleFor(b.compound).short).join(' → ')
        return (
          <div key={strategy.id ?? strategy.label} className={styles.row}>
            <div className={styles.rowLabel}>
              <div className={styles.rowName}>
                <span className={styles.stops}>{strategy.num_stops}-STOP</span>
                {strategy.is_base && <span className={styles.rec}>REC</span>}
              </div>
              <span className={styles.seq}>{seq}</span>
              {strategy.tier && (
                <span className={styles.tier} style={{ color: tierColor(strategy.tier) }}>
                  {strategy.tier.toUpperCase()}
                  {strategy.plausibility != null &&
                    ` · ${Math.round(strategy.plausibility * 100)}%`}
                </span>
              )}
            </div>
            <div className={styles.bars}>
              {bars.map((b, i) => (
                <div
                  key={i}
                  className={styles.bar}
                  style={{
                    width: `${b.widthPct}%`,
                    background: styleFor(b.compound).bg,
                    borderTopColor: styleFor(b.compound).color,
                  }}
                >
                  <span className={styles.barName}>{b.compound}</span>
                  <span className={styles.barLaps}>
                    L{b.startLap}–{b.endLap}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )
      })}

      <div className={styles.axisRow}>
        <div className={styles.axisSpacer} />
        <div className={styles.axis}>
          {axis.map((lap, i) => (
            <span key={i}>L{lap}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
