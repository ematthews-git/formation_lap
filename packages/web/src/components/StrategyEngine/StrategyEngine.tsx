import { useState } from 'react'
import type {
  CircuitRaceStats,
  RaceWeekend,
  SimRaceStats,
  StrategyWithStints,
} from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { useCountUp } from '../../lib/useCountUp'
import { StintTimeline } from './StintTimeline'
import styles from './StrategyEngine.module.css'

interface Props {
  weekend: RaceWeekend
  circuitRaceStats: CircuitRaceStats | null | undefined
  circuitRaceStatsLoading: boolean
  /** Query failures (network/5xx) — distinct from "no data yet" empty states. */
  circuitRaceStatsError?: boolean
  historicalStrategies: StrategyWithStints[] | undefined
  historicalStrategiesLoading: boolean
  historicalStrategiesError?: boolean
  simStrategies: StrategyWithStints[] | undefined
  simStrategiesLoading: boolean
  simStrategiesError?: boolean
  simStats: SimRaceStats | null | undefined
  simStatsLoading: boolean
  simStatsError?: boolean
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
  circuitRaceStats,
  circuitRaceStatsLoading,
  circuitRaceStatsError,
  historicalStrategies,
  historicalStrategiesLoading,
  historicalStrategiesError,
  simStrategies,
  simStrategiesLoading,
  simStrategiesError,
  simStats,
  simStatsLoading,
  simStatsError,
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
  const selectedError = showSim ? simStrategiesError : historicalStrategiesError
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

  // Empirical race analytics for this circuit-season (null until the pre-season
  // job has run). Feeds the tyre, pit-loss and incident-probability figures.
  const incidents = circuitRaceStats?.stats?.incidents
  const pit = circuitRaceStats?.stats?.pit
  const tyres = circuitRaceStats?.stats?.tyres
  const compoundFreq = tyres?.compound_usage_frequency

  // The last-5-race window sometimes has no SC/VSC to measure a pit-loss delta from.
  // When that happens, fall back to a multiple of the base (green-flag) pit loss —
  // SC pits are slower under the full delta, VSC less so.
  const scPitLoss = pit?.sc_pit_loss_s ?? (pitLoss != null ? pitLoss * 0.5 : null)
  const vscPitLoss = pit?.vsc_pit_loss_s ?? (pitLoss != null ? pitLoss * 0.75 : null)
  const scEstimated = pit?.sc_pit_loss_s == null && scPitLoss != null
  const vscEstimated = pit?.vsc_pit_loss_s == null && vscPitLoss != null

  // Count-up targets for the top-row tiles — called unconditionally (hooks
  // can't live inside the conditional JSX below) so the numbers animate in
  // from 0 whenever a weekend's data first resolves.
  const animatedUndercut = useCountUp(undercut)
  const animatedPitLoss = useCountUp(pitLoss)
  const animatedScPitLoss = useCountUp(scPitLoss)
  const animatedVscPitLoss = useCountUp(vscPitLoss)
  const animatedMaxStint = useCountUp(tyres?.max_stint_length)
  const animatedAgeAtPit = useCountUp(tyres?.avg_tyre_age_at_pit)
  const animatedStintDeg = useCountUp(tyres?.avg_stint_degradation_s_per_lap)
  const animatedFreqHard = useCountUp(compoundFreq?.['HARD'])
  const animatedFreqMedium = useCountUp(compoundFreq?.['MEDIUM'])
  const animatedFreqSoft = useCountUp(compoundFreq?.['SOFT'])
  const animatedYellowLaps = useCountUp(incidents?.avg_yellow_flag_laps)
  const animatedRetirements = useCountUp(incidents?.avg_retirements)
  const animatedLap1Dnfs = useCountUp(incidents?.avg_lap1_dnfs)
  const animatedFreq: Record<string, number | null> = {
    hard: animatedFreqHard,
    medium: animatedFreqMedium,
    soft: animatedFreqSoft,
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
        {/* compounds — allocation from the weekend, usage/degradation from race stats */}
        <div className={styles.compounds}>
          <div className={styles.sectionLabel}>AVAILABLE COMPOUNDS</div>
          {tyres && <div className={styles.sectionSubLabel}>· LAST 5 USAGE</div>}
          <div className={styles.compoundsBody}>
            <div className={styles.compoundList}>
              {COMPOUNDS.map((c) => {
                const freq = animatedFreq[c.key]
                return (
                  <div key={c.key} className={styles.compound}>
                    <div className={styles.compoundChip} style={{ borderColor: c.color, color: c.color }}>
                      {code[c.key]}
                    </div>
                    <div>
                      <div className={styles.compoundName}>{c.name}</div>
                      <div className={styles.compoundDesc}>
                        {c.desc}
                        {freq != null && (
                          <span className={styles.compoundFreqInline}>
                            {' '}
                            · {Math.round(freq * 100)}%
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            {tyres && (
              <div className={styles.tyreStats}>
                <Mini
                  label="MAX STINT LENGTH"
                  value={
                    animatedMaxStint != null
                      ? `${Math.round(animatedMaxStint)} laps`
                      : '—'
                  }
                />
                <Mini
                  label="AVG TYRE AGE AT PIT"
                  value={
                    animatedAgeAtPit != null
                      ? `${animatedAgeAtPit.toFixed(1)} laps`
                      : '—'
                  }
                />
                <Mini
                  label="AVG STINT DEGRADATION"
                  value={
                    animatedStintDeg != null
                      ? `${animatedStintDeg.toFixed(2)}s`
                      : '—'
                  }
                />
              </div>
            )}
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
                  {animatedUndercut != null ? animatedUndercut.toFixed(2) : '—'}
                </span>
                <span className={styles.bigUnit}>s/lap</span>
                <span className={styles.bigCaption}>UNDERCUT GAIN</span>
              </div>
              <div className={styles.miniStats}>
                <Mini
                  label="PIT LOSS"
                  value={animatedPitLoss != null ? `${animatedPitLoss.toFixed(1)}s` : '—'}
                />
                <Mini
                  label="SC PIT LOSS"
                  value={
                    animatedScPitLoss != null
                      ? `${animatedScPitLoss.toFixed(1)}s${scEstimated ? '*' : ''}`
                      : '—'
                  }
                />
                <Mini
                  label="VSC PIT LOSS"
                  value={
                    animatedVscPitLoss != null
                      ? `${animatedVscPitLoss.toFixed(1)}s${vscEstimated ? '*' : ''}`
                      : '—'
                  }
                />
              </div>
              {(scEstimated || vscEstimated) && (
                <div className={styles.estimateFootnote}>
                  *ESTIMATED FROM BASE PIT LOSS
                </div>
              )}
            </>
          ) : simStatsError ? (
            <ErrorState message="couldn't load sim race context" />
          ) : (
            <EmptyState hint="sim not yet available for this weekend" />
          )}
        </div>

        {/* incident probabilities — empirical, from circuit race stats */}
        <div className={styles.safetyCar}>
          <div className={styles.sectionLabel}>INCIDENT PROBABILITY · LAST 5</div>
          {circuitRaceStatsLoading ? (
            <LoadingState />
          ) : incidents ? (
            <div className={styles.incidentBody}>
              <div className={styles.incidentList}>
                <IncidentRow
                  label="SAFETY CAR"
                  prob={incidents.sc_probability}
                  deployments={incidents.avg_sc_deployments}
                />
                <IncidentRow
                  label="VIRTUAL SC"
                  prob={incidents.vsc_probability}
                  deployments={incidents.avg_vsc_deployments}
                />
                <IncidentRow
                  label="RED FLAG"
                  prob={incidents.red_flag_probability}
                  tone="danger"
                />
              </div>
              <div className={styles.incidentStats}>
                <Mini
                  label="AVG YELLOW FLAG"
                  value={
                    animatedYellowLaps != null
                      ? `${animatedYellowLaps.toFixed(1)} laps`
                      : '—'
                  }
                />
                <Mini
                  label="AVG RETIREMENTS"
                  value={
                    animatedRetirements != null
                      ? animatedRetirements.toFixed(1)
                      : '—'
                  }
                />
                <Mini
                  label="AVG LAP 1 DNFS"
                  value={
                    animatedLap1Dnfs != null ? animatedLap1Dnfs.toFixed(1) : '—'
                  }
                />
              </div>
            </div>
          ) : circuitRaceStatsError ? (
            <ErrorState message="couldn't load incident stats" />
          ) : (
            <EmptyState hint="race-stats not yet available" />
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
        ) : selectedError ? (
          <ErrorState message="couldn't load strategies" />
        ) : (
          <EmptyState
            label="NO STRATEGY DATA"
            hint="Available on monday of race weekend"
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

/** One incident-probability row: a shrunk percentage with an optional average
 * deployment count, and a gauge bar. `prob`/`deployments` are nullable. */
function IncidentRow({
  label,
  prob,
  deployments,
  tone = 'gold',
}: {
  label: string
  prob: number | null | undefined
  deployments?: number | null
  /** Visual tone for the value/bar — 'danger' marks red-flag-severity incidents. */
  tone?: 'gold' | 'danger'
}) {
  const targetPct = prob != null ? Math.max(0, Math.min(100, prob * 100)) : null
  const pct = useCountUp(targetPct)
  const animatedDeployments = useCountUp(deployments)
  const has = pct != null
  const danger = tone === 'danger'
  return (
    <div className={styles.incidentRow}>
      <div className={styles.incidentLabel}>{label}</div>
      <div className={styles.incidentValueRow}>
        <span
          className={`${styles.incidentValue} ${danger ? styles.incidentValueDanger : ''}`}
        >
          {has ? Math.round(pct) : '—'}
        </span>
        {has && (
          <span
            className={`${styles.incidentUnit} ${danger ? styles.incidentUnitDanger : ''}`}
          >
            %
          </span>
        )}
        {animatedDeployments != null && (
          <span className={styles.incidentSub}>{animatedDeployments.toFixed(1)} avg</span>
        )}
      </div>
      <div className={styles.incidentBar}>
        <div
          className={`${styles.incidentBarFill} ${danger ? styles.incidentBarFillDanger : ''}`}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
    </div>
  )
}

function Gauge({ label, value }: { label: string; value: number | null }) {
  const targetPct = value != null ? Math.max(0, Math.min(100, value)) : null
  const pct = useCountUp(targetPct)
  const has = pct != null
  return (
    <div className={styles.gauge}>
      <div className={styles.gaugeLabel}>{label}</div>
      <div className={styles.gaugeValueRow}>
        <span className={`${styles.gaugeValue} ${has ? '' : styles.gaugeValueEmpty}`}>
          {has ? Math.round(pct) : '—'}
        </span>
        {has && <span className={styles.gaugeScale}>/100</span>}
      </div>
      <div className={styles.gaugeBar}>
        <div
          className={styles.gaugeBarFill}
          style={{ width: `${pct ?? 0}%`, background: scaleColor(pct ?? 0) }}
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
