import type { Circuit, CircuitRaceStats, LapRecord } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { StatCell } from '../common/StatCell'
import { EmptyState, ErrorState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { FALLBACK_TRACK_PATH, pathStartPoint } from '../../lib/trackPath'
import styles from './CircuitProfile.module.css'

function formatLapTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = (seconds % 60).toFixed(3).padStart(6, '0')
  return `${m}:${s}`
}

interface Props {
  circuit: Circuit | undefined
  circuitLoading: boolean
  /** Query failure (network/5xx) — distinct from "no circuit data yet". */
  circuitError?: boolean
  lapRecord: LapRecord | null | undefined
  lapRecordLoading: boolean
  raceStats: CircuitRaceStats | null | undefined
}

export function CircuitProfile({
  circuit,
  circuitLoading,
  circuitError,
  lapRecord,
  lapRecordLoading,
  raceStats,
}: Props) {
  const distance =
    circuit ? Math.round(circuit.num_laps * circuit.track_length_km) : null
  const trackPath = circuit?.track_outline ?? FALLBACK_TRACK_PATH
  const [startX, startY] = pathStartPoint(trackPath)

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

  return (
    <Panel frosted className={styles.panel}>
      <PanelHeader
        label="TRK_PROFILE"
        sub={circuit ? prettifyCircuit(circuit.circuit_id).toUpperCase() : undefined}
        meta={
          circuit ? `${circuit.track_length_km.toFixed(3)} KM` : undefined
        }
      />
      <div className={styles.body}>
        <div className={styles.diagram}>
          <svg viewBox="0 0 400 248" width="100%" className={styles.track}>
            <path
              d={trackPath}
              fill="none"
              stroke="#4A4744"
              strokeWidth="9"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <path
              d={trackPath}
              fill="none"
              stroke="var(--text)"
              strokeWidth="2.4"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <circle cx={startX} cy={startY} r="4" fill="var(--accent)" />
          </svg>
        </div>

        <div className={styles.stats}>
          {circuitLoading && !circuit ? (
            <div className={styles.span2}>
              <LoadingState label="LOADING CIRCUIT" />
            </div>
          ) : circuit ? (
            <>
              <div className={styles.cellBorder}>
                <StatCell label="LAPS" value={circuit.num_laps} size="md" />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell label="DISTANCE" value={distance} unit="km" size="md" />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell
                  label="OVERTAKES/RACE"
                  value={avgOvertakes != null ? avgOvertakes.toFixed(1) : '—'}
                  size="md"
                />
              </div>
              <div className={styles.cellBorder}>
                <StatCell label="STRAIGHT MODE ZONES" value={circuit.sm_zones} size="md" />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell label="CORNERS" value={circuit.num_corners} size="md" />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell
                  label="OVERTAKES IN L1"
                  value={lap1Share != null ? lap1Share : '—'}
                  unit={lap1Share != null ? '%' : undefined}
                  size="md"
                />
              </div>
              <div className={styles.lapRecord}>
                <div className={styles.lapRecordLabel}>LAP RECORD</div>
                {lapRecordLoading ? (
                  <LoadingState />
                ) : lapRecord ? (
                  <div className={styles.lapRecordValue}>
                    <span className={styles.lapTime}>
                      {formatLapTime(lapRecord.lap_time_seconds)}
                    </span>
                    <span className={styles.lapDriver}>
                      {lapRecord.driver} ’{String(lapRecord.year).slice(-2)}
                    </span>
                  </div>
                ) : (
                  <EmptyState hint="Lap-record not found" />
                )}
              </div>
            </>
          ) : circuitError ? (
            <div className={styles.span2}>
              <ErrorState message="couldn't load the circuit profile" />
            </div>
          ) : (
            <div className={styles.span2}>
              <EmptyState label="NO CIRCUIT DATA" />
            </div>
          )}
        </div>
      </div>
    </Panel>
  )
}
