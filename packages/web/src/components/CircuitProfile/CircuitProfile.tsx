import type { Circuit, LapRecord } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { StatCell } from '../common/StatCell'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import styles from './CircuitProfile.module.css'

const TRACK_PATH =
  'M58 196 C 80 150, 84 116, 122 116 C 146 116, 152 134, 174 136 C 214 140, 228 92, 262 90 C 308 88, 332 70, 346 90 C 358 108, 332 126, 296 132 C 264 137, 246 152, 260 172 C 274 192, 322 188, 332 208 C 339 223, 314 230, 284 226 C 240 220, 198 214, 176 207 C 138 195, 112 226, 86 216 C 64 207, 50 210, 58 196 Z'

function formatLapTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = (seconds % 60).toFixed(3).padStart(6, '0')
  return `${m}:${s}`
}

interface Props {
  circuit: Circuit | undefined
  circuitLoading: boolean
  lapRecord: LapRecord | null | undefined
  lapRecordLoading: boolean
}

export function CircuitProfile({
  circuit,
  circuitLoading,
  lapRecord,
  lapRecordLoading,
}: Props) {
  const distance =
    circuit ? Math.round(circuit.num_laps * circuit.track_length_km) : null

  return (
    <Panel>
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
              d={TRACK_PATH}
              fill="none"
              stroke="#4A4744"
              strokeWidth="9"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <path
              d={TRACK_PATH}
              fill="none"
              stroke="var(--text)"
              strokeWidth="2.4"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <line x1="52" y1="190" x2="64" y2="202" stroke="var(--accent)" strokeWidth="3.2" />
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
                <StatCell label="LAPS" value={circuit.num_laps} />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell label="DISTANCE" value={distance} unit="km" />
              </div>
              <div className={styles.cellBorder}>
                <StatCell label="DRS ZONES" value={circuit.sm_zones} />
              </div>
              <div className={`${styles.cellBorder} ${styles.cellLeft}`}>
                <StatCell label="CORNERS" value={circuit.num_corners} />
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
                  <EmptyState hint="Lap-records job not yet run" />
                )}
              </div>
            </>
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
