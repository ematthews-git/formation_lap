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
import styles from './StrategyEngine.module.css'

interface Props {
  weekend: RaceWeekend
  stats: CircuitStats | null | undefined
  statsLoading: boolean
  historicalStrategies: StrategyWithStints[] | undefined
  historicalStrategiesLoading: boolean
  simStrategies: StrategyWithStints[] | undefined
  simStrategiesLoading: boolean
  simStats: SimRaceStats | null | undefined
  simStatsLoading: boolean
  /** Last season's sim stats — the fallback for the engine parameters. */
  fallbackStats: SimRaceStats | null | undefined
  fallbackStatsLoading: boolean
}

const COMPOUNDS = [
  { key: 'hard', name: 'Hard', desc: 'DURABLE', color: 'var(--hard)' },
  { key: 'medium', name: 'Medium', desc: 'BALANCED', color: 'var(--gold)' },
  { key: 'soft', name: 'Soft', desc: 'PEAK GRIP', color: 'var(--soft)' },
] as const

const asNum = (v: unknown): number | null => (typeof v === 'number' ? v : null)

// Map a calendar `rank`/`of` pair (rank 1 = the highest-ranked circuit) onto the 0–100
// gauge, where rank 1 → 100. `field` is the nested race_stats object holding the pair
// (e.g. degradation, strategy_flexibility). Returns null when the pair is missing.
const rankToGauge = (field: unknown): number | null => {
  const obj = field as Record<string, unknown> | undefined
  const rank = asNum(obj?.rank)
  const of = asNum(obj?.of)
  if (rank == null || of == null || of <= 0) return null
  return (100 * (of - rank + 1)) / of
}

// The four engine-derived parameters, each a percentile of this circuit among the
// calendar (rank 1 → 100) rather than an absolute figure — the API precomputes the
// rank/of pair and we map it onto the 0–100 gauge. `get` reads it out of the sim's
// race_stats blob; a param whose field is missing from the blob stays blank (—).
const ENGINE_PARAMS: {
  label: string
  get: (s: Record<string, unknown>) => number | null
}[] = [
  // Chaos: rank 1 = most chaotic. Ranked across the season's simulated weekends at read
  // time (see repositories.chaos_rank), the same way flexibility is.
  { label: 'CHAOS RATING', get: (s) => rankToGauge(s.chaos) },
  // Overtaking difficulty: rank 1 = hardest to overtake. A static circuit-profile
  // property, so the sim ranks it against all known circuits (see stats._overtake_rank),
  // exactly like tyre degradation.
  { label: 'OVERTAKING DIFFICULTY', get: (s) => rankToGauge(s.overtaking_difficulty) },
  // Strategic flexibility: rank 1 = most flexible. Blends how spread the stop-count
  // distribution and shown-strategy plausibilities are; ranked across the season
  // (see repositories.strategy_flexibility_rank).
  { label: 'STRATEGY FLEXIBILITY', get: (s) => rankToGauge(s.strategy_flexibility) },
  // Tyre wear: rank 1 = highest deg. Raw severity is a tiny s/lap slope, ranked against
  // all known circuits at sim time (see stats._deg_rank).
  { label: 'TYRE WEAR', get: (s) => rankToGauge(s.degradation) },
]

type Source = 'sim' | 'historical'

export function StrategyEngine({
  weekend,
  stats,
  statsLoading,
  historicalStrategies,
  historicalStrategiesLoading,
  simStrategies,
  simStrategiesLoading,
  simStats,
  simStatsLoading,
  fallbackStats,
  fallbackStatsLoading,
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
  // Undercut + pit loss come from this season's sim race-context numbers.
  const raceStats = simStats?.stats?.race_stats as
    | Record<string, number | null>
    | undefined
  const undercut = raceStats?.undercut_s_per_lap
  const pitLoss = raceStats?.pit_loss_s

  // Engine parameters prefer this season's sim; if it hasn't run yet, fall back
  // to last season's. With no previous-season rows, every gauge reads —.
  const usingFallback = !simStats && !!fallbackStats
  const engineLoading = simStatsLoading || (!simStats && fallbackStatsLoading)
  const activeSim = simStats ?? fallbackStats
  const engineStats = activeSim?.stats?.race_stats as
    | Record<string, unknown>
    | undefined
  // Number of historical dry races behind the circuit profile, and the season
  // window they were drawn from — surfaced in the header meta.
  const nDryRaces = (
    activeSim?.stats?.circuit_profile as Record<string, number | null> | undefined
  )?.n_races_in_history
  const training = (activeSim?.stats?.meta as Record<string, unknown> | undefined)
    ?.training_window as { start_year?: number; end_year?: number } | undefined
  const headerMeta =
    nDryRaces != null
      ? `${nDryRaces} DRY RACE${nDryRaces === 1 ? '' : 'S'} ON RECORD` +
        (training?.start_year != null && training?.end_year != null
          ? ` · ${training.start_year}-${training.end_year}`
          : '')
      : undefined

  const code = {
    hard: weekend.hard_compound,
    medium: weekend.medium_compound,
    soft: weekend.soft_compound,
  }

  return (
    <Panel strong>
      <PanelHeader
        accent
        label="STRATEGY_ENGINE"
        sub={prettifyCircuit(weekend.circuit_id).toUpperCase()}
        meta={headerMeta}
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

        {/* fresh tyre advantage — from the sim's race-context numbers */}
        <div className={styles.undercut}>
          <div className={styles.sectionLabel}>FRESH TYRE ADVANTAGE</div>
          {simStatsLoading ? (
            <LoadingState />
          ) : raceStats ? (
            <>
              <div className={styles.bigValueRow}>
                <span className={styles.bigValue}>
                  {undercut != null ? undercut.toFixed(2) : '—'}
                </span>
                <span className={styles.bigUnit}>s/lap</span>
                <span className={styles.bigCaption}>UNDERCUT GAIN</span>
              </div>
              <div className={styles.miniStats}>
                <Mini
                  label="PIT LOSS"
                  value={pitLoss != null ? `${pitLoss.toFixed(1)}s` : '—'}
                />
              </div>
            </>
          ) : (
            <EmptyState hint="sim not yet run for this weekend" />
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

      {/* engine-derived parameters — 0–100 ratings from the sim */}
      <div className={styles.engineParams}>
        <div className={styles.engineHeader}>
          <span className={styles.engineHeaderLabel}>ENGINE-DERIVED PARAMETERS</span>
          {usingFallback && (
            <span className={styles.engineNote}>LAST SEASON · {weekend.season - 1}</span>
          )}
        </div>
        {engineLoading ? (
          <LoadingState label="LOADING PARAMETERS" />
        ) : (
          <div className={styles.engineGrid}>
            {ENGINE_PARAMS.map((p) => (
              <Gauge
                key={p.label}
                label={p.label}
                value={engineStats ? p.get(engineStats) : null}
              />
            ))}
          </div>
        )}
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

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className={styles.miniLabel}>{label}</div>
      <div className={styles.miniValue}>{value}</div>
    </div>
  )
}

function Gauge({ label, value }: { label: string; value: number | null }) {
  const has = value != null
  const pct = has ? Math.max(0, Math.min(100, value)) : 0
  return (
    <div className={styles.gauge}>
      <div className={styles.gaugeLabel}>{label}</div>
      <div className={styles.gaugeValueRow}>
        <span className={`${styles.gaugeValue} ${has ? '' : styles.gaugeValueEmpty}`}>
          {has ? Math.round(value) : '—'}
        </span>
        {has && <span className={styles.gaugeScale}>/100</span>}
      </div>
      <div className={styles.gaugeBar}>
        <div
          className={styles.gaugeBarFill}
          style={{ width: `${pct}%`, background: scaleColor(pct) }}
        />
      </div>
    </div>
  )
}

/** Traffic-light scale for a 0–100 rating: green (low) → amber → red (high). */
function scaleColor(value: number): string {
  const hue = 120 * (1 - Math.max(0, Math.min(100, value)) / 100)
  return `hsl(${Math.round(hue)}, 50%, 48%)`
}
