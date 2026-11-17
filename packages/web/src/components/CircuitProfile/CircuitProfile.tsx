import type { ReactNode } from 'react'
import type { Circuit, CircuitRaceStats, LapRecord } from '../../api/types'
import { LiquidGlass } from '../common/LiquidGlass'
import { pathStartPoint } from '../../lib/trackPath'
import styles from './CircuitProfile.module.css'

function formatLapTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = (seconds % 60).toFixed(3).padStart(6, '0')
  return `${m}:${s}`
}

function ordinal(n: number): string {
  const v = n % 100
  const suffix = v >= 11 && v <= 13 ? 'th' : (['th', 'st', 'nd', 'rd'][n % 10] ?? 'th')
  return `${n}${suffix}`
}

/**
 * PLACEHOLDER — no endpoint ranks circuits by overtakes yet, so this is a fixed
 * made-up value to preview the pill. The real figure needs a calendar-wide
 * ranking of `avg_overtakes_per_race` (like /circuits/calendar-grid-averages).
 */
const PLACEHOLDER_OVERTAKE_RANK = { rank: 4, of: 24 }

interface Props {
  /** The featured weekend's circuit — known before the circuit query lands, so
      the glass can line up with the hero photo straight away. */
  circuitId: string
  circuit: Circuit | undefined
  circuitLoading: boolean
  /** Query failure (network/5xx) — distinct from "no circuit data yet". */
  circuitError?: boolean
  lapRecord: LapRecord | null | undefined
  lapRecordLoading: boolean
  raceStats: CircuitRaceStats | null | undefined
}

export function CircuitProfile({
  circuitId,
  circuit,
  circuitLoading,
  circuitError,
  lapRecord,
  lapRecordLoading,
  raceStats,
}: Props) {
  let body
  if (circuit) {
    body = (
      <Profile
        circuit={circuit}
        lapRecord={lapRecord}
        lapRecordLoading={lapRecordLoading}
        raceStats={raceStats}
      />
    )
  } else if (circuitLoading) {
    body = <p className={styles.message}>Loading circuit…</p>
  } else if (circuitError) {
    body = <p className={styles.message}>Couldn't load the circuit profile</p>
  } else {
    body = <p className={styles.message}>No circuit data yet</p>
  }

  return (
    <LiquidGlass circuitId={circuitId} label="Track profile" className={styles.card}>
      <div className={styles.content}>
        <header className={styles.top}>
          <h2 className={styles.title}>Track profile</h2>
          {circuit && (
            <span className={styles.chip}>{circuit.track_length_km.toFixed(3)} km</span>
          )}
        </header>
        {body}
      </div>
    </LiquidGlass>
  )
}

function Profile({
  circuit,
  lapRecord,
  lapRecordLoading,
  raceStats,
}: {
  circuit: Circuit
  lapRecord: LapRecord | null | undefined
  lapRecordLoading: boolean
  raceStats: CircuitRaceStats | null | undefined
}) {
  const distance = Math.round(circuit.num_laps * circuit.track_length_km)
  const trackPath = circuit.track_outline
  const [startX, startY] = trackPath ? pathStartPoint(trackPath) : [0, 0]

  // Empirical overtaking figures (null until the pre-season job has run).
  const overtaking = raceStats?.stats?.overtaking
  const avgOvertakes = overtaking?.avg_overtakes_per_race ?? null
  const lap1 = overtaking?.avg_position_changes_lap1
  const afterLap1 = overtaking?.avg_position_changes_after_lap1
  // Share of position-change activity that happens on lap 1 vs the rest of the race.
  const lap1Share =
    lap1 != null && afterLap1 != null && lap1 + afterLap1 > 0
      ? Math.round((lap1 / (lap1 + afterLap1)) * 100)
      : null
  const overtakeRank = PLACEHOLDER_OVERTAKE_RANK

  return (
    <div className={styles.body}>
      <div className={styles.map}>
        {trackPath ? (
          <svg viewBox="0 0 400 248" className={styles.track} role="img" aria-label="Track map">
            <path
              d={trackPath}
              fill="none"
              stroke="var(--ink)"
              strokeWidth="6"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {/* Start/finish: a ring around a dot, so it reads in one colour. */}
            <circle cx={startX} cy={startY} r="11" fill="none" stroke="var(--ink)" strokeWidth="3" />
            <circle cx={startX} cy={startY} r="4.5" fill="var(--ink)" />
          </svg>
        ) : (
          <p className={styles.message}>No track outline yet</p>
        )}
      </div>

      <div className={styles.data}>
        <div className={styles.record}>
          <div className={styles.label}>Lap record</div>
          {lapRecord ? (
            <div className={styles.recordValue}>
              <span className={styles.recordTime}>{formatLapTime(lapRecord.lap_time_seconds)}</span>
              <span className={styles.recordDriver}>
                {lapRecord.family_name} ’{String(lapRecord.year).slice(-2)}
              </span>
            </div>
          ) : (
            <div className={styles.recordTime}>{lapRecordLoading ? '…' : '—'}</div>
          )}
        </div>

        <div className={`${styles.tier} ${styles.tier2}`}>
          <Stat label="Laps" value={circuit.num_laps} />
          <Stat label="Straight mode zones" value={circuit.sm_zones} />
        </div>

        <div className={`${styles.tier} ${styles.tier3}`}>
          <Stat label="Distance" value={distance} unit="km" />
          <Stat label="Corners" value={circuit.num_corners} />
          <Stat
            label="Overtakes / race"
            value={avgOvertakes != null ? avgOvertakes.toFixed(1) : '—'}
            badge={
              <span
                className={styles.rank}
                title={`${ordinal(overtakeRank.rank)} most overtakes of ${overtakeRank.of} circuits on the calendar`}
              >
                {ordinal(overtakeRank.rank)}/{overtakeRank.of}
              </span>
            }
          />
          <Stat
            label="Overtakes on L1"
            value={lap1Share ?? '—'}
            unit={lap1Share != null ? '%' : undefined}
          />
        </div>
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  unit,
  badge,
}: {
  label: string
  value: string | number | null
  unit?: string
  /** Small pill after the value (e.g. the calendar ranking). */
  badge?: ReactNode
}) {
  return (
    <div className={styles.stat}>
      <div className={styles.label}>{label}</div>
      <div className={styles.statValue}>
        <span>{value ?? '—'}</span>
        {unit && value != null && <span className={styles.statUnit}>{unit}</span>}
        {badge}
      </div>
    </div>
  )
}
