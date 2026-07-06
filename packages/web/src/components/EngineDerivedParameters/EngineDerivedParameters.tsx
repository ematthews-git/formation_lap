import type { RaceWeekend, SimRaceStats } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import styles from './EngineDerivedParameters.module.css'

interface Props {
  weekend: RaceWeekend
  simStats: SimRaceStats | null | undefined
  simStatsLoading: boolean
  /** Last season's sim stats — used when this season's sim hasn't run yet. */
  fallbackStats: SimRaceStats | null | undefined
  fallbackStatsLoading: boolean
}

// The four engine-derived parameters, each a 0–100 rating. `key` reads the value
// out of the sim's race_stats blob; params with no engine field yet stay blank (—).
const PARAMS = [
  { label: 'CHAOS RATING', key: 'chaos_index_0to100' },
  { label: 'OVERTAKING DIFFICULTY', key: 'overtaking_difficulty_0to100' },
  { label: 'QUALIFYING IMPORTANCE', key: null },
  { label: 'TYRE DEGRADATION', key: null },
] as const

export function EngineDerivedParameters({
  weekend,
  simStats,
  simStatsLoading,
  fallbackStats,
  fallbackStatsLoading,
}: Props) {
  // Prefer this season's sim; if the prelim hasn't run yet, fall back to last
  // season's engine parameters. With no previous-season rows, every gauge is —.
  const active = simStats ?? fallbackStats
  const usingFallback = !simStats && !!fallbackStats
  const loading = simStatsLoading || (!simStats && fallbackStatsLoading)
  const raceStats = active?.stats?.race_stats as
    | Record<string, number | null>
    | undefined

  const meta = usingFallback
    ? `LAST SEASON · ${weekend.season - 1}`
    : active
      ? `${(active.phase ?? 'SIM').toUpperCase()} SIM`
      : 'AWAITING SIM'

  return (
    <Panel>
      <PanelHeader
        label="ENGINE_DERIVED_PARAMETERS"
        sub={prettifyCircuit(weekend.circuit_id).toUpperCase()}
        meta={meta}
      />
      {loading ? (
        <div className={styles.loadingWrap}>
          <LoadingState label="LOADING PARAMETERS" />
        </div>
      ) : (
        <div className={styles.grid}>
          {PARAMS.map((p) => (
            <Gauge
              key={p.label}
              label={p.label}
              value={p.key && raceStats ? (raceStats[p.key] ?? null) : null}
            />
          ))}
        </div>
      )}
    </Panel>
  )
}

function Gauge({ label, value }: { label: string; value: number | null }) {
  const has = value != null
  const pct = has ? Math.max(0, Math.min(100, value)) : 0
  return (
    <div className={styles.gauge}>
      <div className={styles.gaugeLabel}>{label}</div>
      <div className={styles.valueRow}>
        <span className={`${styles.value} ${has ? '' : styles.valueEmpty}`}>
          {has ? Math.round(value) : '—'}
        </span>
        {has && <span className={styles.scale}>/100</span>}
      </div>
      <div className={styles.bar}>
        <div className={styles.barFill} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
