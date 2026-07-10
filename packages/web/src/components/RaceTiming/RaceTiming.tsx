import type { CircuitRaceStats } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { StatCell } from '../common/StatCell'
import { EmptyState, LoadingState } from '../common/Status'
import { formatDuration, formatGap } from '../../lib/format'
import styles from './RaceTiming.module.css'

interface Props {
  raceStats: CircuitRaceStats | null | undefined
  loading: boolean
}

export function RaceTiming({ raceStats, loading }: Props) {
  const timing = raceStats?.stats?.timing
  const duration = timing?.avg_race_duration_s
  const toP10 = timing?.avg_winner_to_p10_s
  const toLast = timing?.avg_winner_to_last_s

  return (
    <Panel className={styles.panel}>
      <PanelHeader accent label="RACE_TIMING" sub="RACE_WINDOW" meta="LAST 5 · AVG" />
      {loading ? (
        <div className={styles.fill}>
          <LoadingState label="LOADING TIMING" />
        </div>
      ) : timing ? (
        <div className={styles.body}>
          <div className={styles.durationCell}>
            <StatCell
              label="AVG RACE DURATION"
              value={duration != null ? formatDuration(duration) : '—'}
            />
          </div>
          <div className={styles.spread}>
            <div className={styles.sectionLabel}>FIELD SPREAD FROM WINNER</div>
            <SpreadBar label="WINNER → P10" value={toP10} max={toLast} accent />
            <SpreadBar label="WINNER → LAST" value={toLast} max={toLast} />
          </div>
        </div>
      ) : (
        <div className={styles.fill}>
          <EmptyState
            label="NO TIMING DATA"
            hint="race-stats not yet available for this circuit"
          />
        </div>
      )}
    </Panel>
  )
}

/** A horizontal magnitude bar for a winner-relative gap, scaled to the widest gap. */
function SpreadBar({
  label,
  value,
  max,
  accent,
}: {
  label: string
  value: number | null | undefined
  max: number | null | undefined
  accent?: boolean
}) {
  const width =
    value != null && max != null && max > 0
      ? Math.max(2, Math.min(100, (value / max) * 100))
      : 0
  return (
    <div className={styles.barRow}>
      <div className={styles.barTop}>
        <span className={styles.barLabel}>{label}</span>
        <span className={styles.barValue}>{value != null ? formatGap(value) : '—'}</span>
      </div>
      <div className={styles.barTrack}>
        <div
          className={`${styles.barFill} ${accent ? styles.barFillAccent : ''}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}
