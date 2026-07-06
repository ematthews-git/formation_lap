import { useState } from 'react'
import type {
  CircuitStats,
  RaceWeekend,
  SimRaceStats,
  StrategyWithStints,
} from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { StintTimeline } from './StintTimeline'
import styles from './TyreStrategy.module.css'

interface Props {
  weekend: RaceWeekend
  stats: CircuitStats | null | undefined
  statsLoading: boolean
  historicalStrategies: StrategyWithStints[] | undefined
  historicalStrategiesLoading: boolean
  simStrategies: StrategyWithStints[] | undefined
  simStrategiesLoading: boolean
  simStats: SimRaceStats | null | undefined
}

const COMPOUNDS = [
  { key: 'hard', name: 'Hard', desc: 'DURABLE · LOW DEG', color: 'var(--hard)' },
  { key: 'medium', name: 'Medium', desc: 'BALANCED · GO-TO', color: 'var(--gold)' },
  { key: 'soft', name: 'Soft', desc: 'PEAK GRIP · QUALI', color: 'var(--soft)' },
] as const

type Source = 'sim' | 'historical'

export function TyreStrategy({
  weekend,
  stats,
  statsLoading,
  historicalStrategies,
  historicalStrategiesLoading,
  simStrategies,
  simStrategiesLoading,
  simStats,
}: Props) {
  const [source, setSource] = useState<Source>('sim')
  const showSim = source === 'sim'
  // Drop strategies whose plausibility rounds to 0% — a "0%" option isn't worth showing.
  // Historical strategies (null plausibility) are always kept.
  const selected = (showSim ? simStrategies : historicalStrategies)?.filter(
    (s) => s.plausibility == null || Math.round(s.plausibility * 100) > 0,
  )
  const selectedLoading = showSim
    ? simStrategiesLoading
    : historicalStrategiesLoading
  const phase = simStrategies?.[0]?.phase ?? simStats?.phase ?? null
  const raceStats = simStats?.stats?.race_stats as
    | Record<string, number | null>
    | undefined

  const code = {
    hard: weekend.hard_compound,
    medium: weekend.medium_compound,
    soft: weekend.soft_compound,
  }
  const allocation = `PIRELLI ${weekend.soft_compound}–${weekend.hard_compound}`

  return (
    <Panel strong>
      <PanelHeader
        accent
        label="TYRE_STRATEGY"
        sub={prettifyCircuit(weekend.circuit_id).toUpperCase()}
        meta={allocation}
      />

      <div className={styles.topRow}>
        {/* compounds — live from the weekend allocation */}
        <div className={styles.compounds}>
          <div className={styles.sectionLabel}>AVAILABLE COMPOUNDS</div>
          <div className={styles.compoundList}>
            {COMPOUNDS.map((c) => (
              <div key={c.key} className={styles.compound}>
                <div className={styles.compoundChip} style={{ borderColor: c.color, color: c.color }}>
                  {code[c.key]}
                </div>
                <div>
                  <div className={styles.compoundName}>{c.name}</div>
                  <div className={styles.compoundDesc}>{c.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* undercut window — from circuit stats (empty until recomputed) */}
        <div className={styles.undercut}>
          <div className={styles.sectionLabel}>UNDERCUT WINDOW</div>
          {statsLoading ? (
            <LoadingState />
          ) : stats ? (
            <>
              <div className={styles.bigValueRow}>
                <span className={styles.bigValue}>{stats.undercut_strength.toFixed(1)}</span>
                <span className={styles.bigUnit}>s</span>
                <span className={styles.bigCaption}>GAP THRESHOLD</span>
              </div>
              <div className={styles.miniStats}>
                <Mini label="PIT LOSS" value={`${stats.pit_loss_normal.toFixed(1)}s`} />
                <Mini
                  label="FAVOURS"
                  value={stats.undercut_strength >= stats.overcut_strength ? 'UNDERCUT' : 'OVERCUT'}
                />
              </div>
            </>
          ) : (
            <EmptyState hint="circuit-stats recompute job not yet run" />
          )}
        </div>

        {/* safety car probability — from circuit stats */}
        <div className={styles.safetyCar}>
          <div className={styles.sectionLabel}>SAFETY CAR PROBABILITY</div>
          {statsLoading ? (
            <LoadingState />
          ) : stats ? (
            <div>
              <div className={styles.scValueRow}>
                <span className={styles.scValue}>{stats.sc_probability}</span>
                <span className={styles.scUnit}>%</span>
              </div>
              <div className={styles.scBar}>
                <div className={styles.scBarFill} style={{ width: `${stats.sc_probability}%` }} />
              </div>
            </div>
          ) : (
            <EmptyState hint="circuit-stats recompute job not yet run" />
          )}
        </div>
      </div>

      {/* source toggle: simulated projection (default) vs historical mining */}
      <div className={styles.sourceRow}>
        <div className={styles.sourceToggle}>
          <button
            type="button"
            className={`${styles.sourceBtn} ${showSim ? styles.sourceBtnActive : ''}`}
            onClick={() => setSource('sim')}
          >
            SIMULATED
          </button>
          <button
            type="button"
            className={`${styles.sourceBtn} ${!showSim ? styles.sourceBtnActive : ''}`}
            onClick={() => setSource('historical')}
          >
            HISTORICAL
          </button>
        </div>
        <span className={styles.sourceNote}>
          {showSim
            ? phase
              ? `MONTE-CARLO · ${phase.toUpperCase()}`
              : 'MONTE-CARLO PROJECTION'
            : 'MINED FROM LAST DRY RUNNING'}
        </span>
      </div>

      {/* sim race-context numbers — only in the simulated view */}
      {showSim && raceStats && (
        <div className={styles.simStats}>
          <SimStat label="PIT LOSS" value={fmt(raceStats.pit_loss_s, 's', 1)} />
          <SimStat label="UNDERCUT" value={fmt(raceStats.undercut_s_per_lap, 's/lap', 2)} />
          <SimStat label="SAFETY CAR" value={pct(raceStats.safety_car_prob)} />
          <SimStat
            label="LIKELY STOPS"
            value={raceStats.most_likely_stops != null ? String(raceStats.most_likely_stops) : '—'}
          />
          <SimStat
            label="OVERTAKING"
            value={raceStats.overtaking_difficulty_0to100 != null ? `${raceStats.overtaking_difficulty_0to100}/100` : '—'}
          />
          <SimStat
            label="CHAOS"
            value={raceStats.chaos_index_0to100 != null ? `${raceStats.chaos_index_0to100}/100` : '—'}
          />
        </div>
      )}

      {/* stint timeline */}
      <div className={styles.stintArea}>
        {selectedLoading ? (
          <LoadingState label="LOADING STRATEGIES" />
        ) : selected && selected.length > 0 ? (
          <StintTimeline strategies={selected} />
        ) : (
          <EmptyState
            label="NO STRATEGY DATA"
            hint={
              showSim
                ? `run: formation-data sim-strategies generate --season ${weekend.season} --round ${weekend.round_number} --mode postquali`
                : `run: formation-data strategies generate --season ${weekend.season} --round ${weekend.round_number}`
            }
          />
        )}
      </div>
    </Panel>
  )
}

function fmt(v: number | null | undefined, unit: string, digits: number): string {
  return v == null ? '—' : `${v.toFixed(digits)}${unit}`
}

function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className={styles.miniLabel}>{label}</div>
      <div className={styles.miniValue}>{value}</div>
    </div>
  )
}

function SimStat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.simStat}>
      <div className={styles.simStatValue}>{value}</div>
      <div className={styles.simStatLabel}>{label}</div>
    </div>
  )
}
