import type { Session } from '../../api/types'
import { Panel } from '../common/Panel'
import { PanelHeader } from '../common/PanelHeader'
import { EmptyState, LoadingState } from '../common/Status'
import { prettifyCircuit } from '../../lib/format'
import { circuitTimezone, formatClock, formatDayDate } from '../../lib/circuitTime'
import styles from './WeekendSchedule.module.css'

interface Props {
  circuitId: string | undefined
  sessions: Session[] | undefined
  loading: boolean
}

/** Sessions that anchor the weekend get a coloured accent bar. */
function tone(name: string): 'race' | 'sprint' | undefined {
  const n = name.toLowerCase()
  if (n === 'race') return 'race'
  if (n.includes('sprint')) return 'sprint'
  return undefined
}

export function WeekendSchedule({ circuitId, sessions, loading }: Props) {
  const tz = circuitTimezone(circuitId)

  return (
    <Panel>
      <PanelHeader
        label="WEEKEND_SCHEDULE"
        sub={circuitId ? prettifyCircuit(circuitId).toUpperCase() : undefined}
        meta="CIRCUIT / LOCAL"
      />
      <div className={styles.headRow}>
        <span>SESSION</span>
        <span>DATE</span>
        <span>CIRCUIT</span>
        <span>LOCAL</span>
      </div>

      {loading && !sessions ? (
        <LoadingState label="LOADING SCHEDULE" />
      ) : sessions && sessions.length > 0 ? (
        sessions.map((s) => {
          const t = tone(s.name)
          return (
            <div key={s.id ?? s.session_order} className={styles.row}>
              {t && <span className={`${styles.accentBar} ${styles[t]}`} />}
              <span className={styles.session}>{s.name}</span>
              <span className={styles.date}>{formatDayDate(s.start_time, tz)}</span>
              <span className={styles.circuit}>{formatClock(s.start_time, tz)}</span>
              <span className={styles.local}>{formatClock(s.start_time)}</span>
            </div>
          )
        })
      ) : (
        <EmptyState label="NO SCHEDULE" />
      )}
    </Panel>
  )
}
