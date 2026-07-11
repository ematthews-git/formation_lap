import type { CircuitRaceStats } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { StatCell } from '../common/StatCell'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { buildGridScatter } from '../../lib/gridScatter'
import styles from './QualiMetrics.module.css'

interface Props {
  circuitId: string | undefined
  raceStats: CircuitRaceStats | null | undefined
  loading: boolean
  /** Calendar-wide mean-finish-by-grid baseline (grey dots). */
  calendarAverages: Record<string, number> | undefined
}

type Metric = { label: string; value: string }

const pct = (v: number | null | undefined): string =>
  v != null ? `${Math.round(v * 100)}%` : '—'

export function QualiMetrics({
  circuitId,
  raceStats,
  loading,
  calendarAverages,
}: Props) {
  const grid = raceStats?.stats?.grid
  const scatter = buildGridScatter(grid?.avg_finish_by_grid, calendarAverages)
  const corr = grid?.quali_finish_correlation

  // Wins from progressively-worse grid slots — the header carries the "WIN" subject.
  const winMetrics: Metric[] = [
    { label: 'POLE → WIN', value: pct(grid?.pole_to_win_rate) },
    { label: 'OUTSIDE TOP 3', value: pct(grid?.win_outside_top3_quali_rate) },
    { label: 'OUTSIDE TOP 5', value: pct(grid?.winner_outside_top5_rate) },
  ]
  const comebackMetrics: Metric[] = [
    { label: 'PODIUM OUTSIDE TOP 10', value: pct(grid?.podium_outside_top10_rate) },
    { label: 'POINTS OUTSIDE TOP 10', value: pct(grid?.points_outside_top10_rate) },
  ]

  return (
    <Panel className={styles.panel}>
      <PanelHeader
        accent
        label="QUALI_METRICS"
        sub={circuitId ? prettifyCircuit(circuitId).toUpperCase() : undefined}
        meta="LAST 5 · FINISH BY GRID"
      />
      {loading ? (
        <div className={styles.fill}>
          <LoadingState label="LOADING QUALI METRICS" />
        </div>
      ) : grid ? (
        <div className={styles.body}>
          <div className={styles.chart}>
            <Scatter scatter={scatter} />
            <div className={styles.legend}>
              <span className={styles.legendItem}>
                <span className={`${styles.dot} ${styles.dotCircuit}`} /> THIS CIRCUIT
              </span>
              <span className={styles.legendItem}>
                <span className={`${styles.dot} ${styles.dotCalendar}`} /> CALENDAR AVG
              </span>
            </div>
          </div>
          <div className={styles.metrics}>
            <MetricGroup label="WIN DISTRIBUTION" metrics={winMetrics} cols={3} />
            <MetricGroup label="COMEBACK ABILITY" metrics={comebackMetrics} cols={2} />
            <div className={styles.standalone}>
              <StatCell
                label="QUALI → RACE CORR"
                value={corr != null ? corr.toFixed(2) : '—'}
                size="md"
              />
            </div>
          </div>
        </div>
      ) : (
        <div className={styles.fill}>
          <EmptyState
            label="NO QUALI DATA"
            hint="race-stats not yet available for this circuit"
          />
        </div>
      )}
    </Panel>
  )
}

function MetricGroup({
  label,
  metrics,
  cols,
}: {
  label: string
  metrics: Metric[]
  cols: 2 | 3
}) {
  return (
    <div className={styles.group}>
      <div className={styles.groupLabel}>{label}</div>
      <div className={`${styles.groupGrid} ${cols === 3 ? styles.cols3 : styles.cols2}`}>
        {metrics.map((m) => (
          <StatCell key={m.label} label={m.label} value={m.value} size="md" />
        ))}
      </div>
    </div>
  )
}

function Scatter({ scatter }: { scatter: ReturnType<typeof buildGridScatter> }) {
  const { width, height, box, maxPos, points, calendarPoints, diagonal } = scatter
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      className={styles.scatterSvg}
      role="img"
      aria-label="Mean finishing position by starting grid slot"
    >
      {/* axis frame */}
      <line x1={box.x0} y1={box.y0} x2={box.x0} y2={box.y1} className={styles.axis} />
      <line x1={box.x0} y1={box.y1} x2={box.x1} y2={box.y1} className={styles.axis} />
      {/* identity reference (grid = finish) */}
      <line
        x1={diagonal.x1}
        y1={diagonal.y1}
        x2={diagonal.x2}
        y2={diagonal.y2}
        className={styles.identity}
      />
      {/* calendar baseline */}
      {calendarPoints.map((p) => (
        <circle key={`c${p.grid}`} cx={p.x} cy={p.y} r="2.4" className={styles.calendarDot} />
      ))}
      {/* this circuit */}
      {points.map((p) => (
        <circle key={`p${p.grid}`} cx={p.x} cy={p.y} r="2.9" className={styles.circuitDot} />
      ))}
      {/* corner ticks — position 1 (best) and the field size */}
      <text x={box.x0 - 4} y={box.y0 + 3} className={styles.tickEnd}>1</text>
      <text x={box.x0 - 4} y={box.y1} className={styles.tickEnd}>{maxPos}</text>
      <text x={box.x0} y={box.y1 + 12} className={styles.tickStart}>1</text>
      <text x={box.x1} y={box.y1 + 12} className={styles.tickEnd}>{maxPos}</text>
      {/* axis titles */}
      <text x={(box.x0 + box.x1) / 2} y={height - 2} className={styles.axisTitleX}>GRID</text>
      <text
        x={-(box.y0 + box.y1) / 2}
        y={9}
        transform="rotate(-90)"
        className={styles.axisTitleY}
      >
        FINISH
      </text>
    </svg>
  )
}
